"""Sqlitegraph-backed graph storage and queries for grounded-graph."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import sqlitegraph
from grounded_index.budget import BudgetEnforcer  # type: ignore[import-untyped]

from grounded_graph.embedder import Embedder, embedder_from_config
from grounded_graph.graph import CALL_LIKE_KINDS, GraphNode

HNSW_INDEX_NAME = "symbols"

# Edge types we follow for call/impact-style queries. Mirrors the pure-Python
# CALL_LIKE_KINDS — kept as a list so sqlitegraph's typed APIs can iterate.
CALL_LIKE_EDGE_TYPES: tuple[str, ...] = tuple(sorted(CALL_LIKE_KINDS))


def _strip_test_prefix(name: str) -> set[str]:
    """Return candidate target-name strings stripped of common test prefixes."""
    candidates: set[str] = set()
    for prefix in ("test_", "tests_"):
        if name.startswith(prefix):
            candidates.add(name[len(prefix) :])
    m = re.match(r"^(?P<stem>.+?)(Test|Tests|Spec)$", name)
    if m:
        candidates.add(m.group("stem"))
    return candidates


def _to_graphnode(node: dict[str, Any]) -> GraphNode:
    """Convert a sqlitegraph node dict into a GraphNode dataclass."""
    data = node.get("data") or {}
    return GraphNode(
        id=node["id"],
        kind=node["kind"],
        name=node["name"],
        file_path=data.get("file_path", ""),
        line_start=data.get("line_start", 0),
        line_end=data.get("line_end", 0),
        signature=data.get("signature"),
        docstring=data.get("docstring"),
        is_public=bool(data.get("is_public", True)),
    )


def _embedder_config_path(sg_db_path: Path) -> Path:
    """Sidecar file path that stores the embedder config for an sg DB."""
    return sg_db_path.with_name(sg_db_path.name + ".embedder.json")


class SqlitegraphBackend:
    """Graph storage and queries backed by sqlitegraph (Rust core via PyO3)."""

    def __init__(self, root_path: str = "") -> None:
        self.root_path = Path(root_path)
        self._graph: sqlitegraph.Graph | None = None
        self._embedder: Embedder | None = None

    # ── Construction ───────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        index_db_path: Path | str,
        sg_db_path: Path | str | None = None,
        *,
        root_path: str = "",
        embedder: Embedder | None = None,
    ) -> SqlitegraphBackend:
        """Build a sqlitegraph DB from a grounded-index DB.

        ``sg_db_path=None`` builds in-memory. An existing file at
        ``sg_db_path`` is replaced. If ``embedder`` is provided, an HNSW
        index named "symbols" is built over each symbol's text content
        (kind + name + signature + docstring).
        """
        backend = cls(root_path=root_path)

        if sg_db_path is not None:
            sg_path = Path(sg_db_path)
            if sg_path.exists():
                sg_path.unlink()
            sidecar = _embedder_config_path(sg_path)
            if sidecar.exists():
                sidecar.unlink()
            backend._graph = sqlitegraph.Graph.open(str(sg_path))
        else:
            backend._graph = sqlitegraph.Graph.open_in_memory()

        backend._load_from_index(Path(index_db_path))

        if embedder is not None:
            backend._embedder = embedder
            backend._build_hnsw_index(embedder)
            if sg_db_path is not None:
                _embedder_config_path(Path(sg_db_path)).write_text(json.dumps(embedder.to_config()))

        return backend

    @classmethod
    def open(
        cls,
        sg_db_path: Path | str,
        *,
        root_path: str = "",
    ) -> SqlitegraphBackend:
        """Open an existing sqlitegraph DB without rebuilding."""
        backend = cls(root_path=root_path)
        backend._graph = sqlitegraph.Graph.open(str(sg_db_path))
        sidecar = _embedder_config_path(Path(sg_db_path))
        if sidecar.exists():
            backend._embedder = embedder_from_config(json.loads(sidecar.read_text()))
        return backend

    # ── Internals ──────────────────────────────────────────────────

    def _g(self) -> sqlitegraph.Graph:
        if self._graph is None:
            raise RuntimeError("Backend has no graph attached.")
        return self._graph

    def _load_from_index(self, index_db_path: Path) -> None:
        """Populate the sqlitegraph DB from a grounded-index SQLite file."""
        g = self._g()
        conn = sqlite3.connect(str(index_db_path))
        try:
            has_is_test = _has_is_test_column(conn)
            gi_to_sg: dict[int, int] = {}
            name_to_id: dict[str, int] = {}
            is_test_by_gi: dict[int, bool] = {}
            parent_by_gi: dict[int, int | None] = {}

            sym_query = (
                """
                SELECT s.id, s.name, s.kind, f.path,
                       s.line_start, s.line_end,
                       s.signature, s.docstring, s.is_public,
                       s.parent_id, s.is_test
                FROM gi_symbols s
                JOIN gi_files f ON s.file_id = f.id
                """
                if has_is_test
                else """
                SELECT s.id, s.name, s.kind, f.path,
                       s.line_start, s.line_end,
                       s.signature, s.docstring, s.is_public,
                       s.parent_id, 0
                FROM gi_symbols s
                JOIN gi_files f ON s.file_id = f.id
                """
            )
            cursor = conn.execute(sym_query)
            for row in cursor.fetchall():
                gi_id, name, kind, file_path = row[0], row[1], row[2], row[3]
                line_start, line_end = row[4], row[5]
                signature, docstring, is_public = row[6], row[7], row[8]
                parent_id, is_test = row[9], bool(row[10])
                data: dict[str, Any] = {
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "is_public": bool(is_public),
                }
                if signature:
                    data["signature"] = signature
                if docstring:
                    data["docstring"] = docstring
                sg_id = g.add_node(kind=kind, name=name, data=data)
                gi_to_sg[gi_id] = sg_id
                name_to_id[name] = sg_id
                is_test_by_gi[gi_id] = is_test
                parent_by_gi[gi_id] = parent_id

            # Reference edges (preserve ref_kind) and track test→target sets.
            test_target_pairs: list[tuple[int, int, str]] = []
            cursor = conn.execute(
                "SELECT from_symbol_id, to_symbol_name, ref_kind FROM gi_references"
            )
            for from_gi_id, to_name, ref_kind in cursor.fetchall():
                from_sg = gi_to_sg.get(from_gi_id)
                to_sg = name_to_id.get(to_name)
                if from_sg is not None and to_sg is not None:
                    g.add_edge(from_sg, to_sg, ref_kind)
                    if is_test_by_gi.get(from_gi_id):
                        test_target_pairs.append((from_sg, to_sg, ref_kind))

            # defines edges from parent_id.
            for gi_id, parent_id in parent_by_gi.items():
                if parent_id is None:
                    continue
                parent_sg = gi_to_sg.get(parent_id)
                child_sg = gi_to_sg.get(gi_id)
                if parent_sg is not None and child_sg is not None:
                    g.add_edge(parent_sg, child_sg, "defines")

            # imports edges: file → module nodes.
            cursor = conn.execute("SELECT id, path FROM gi_files")
            file_to_sg: dict[int, int] = {}
            for file_id, path in cursor.fetchall():
                file_sg = g.add_node(
                    kind="file",
                    name=path,
                    data={"file_path": path},
                )
                file_to_sg[file_id] = file_sg

            module_name_to_sg: dict[str, int] = {}
            cursor = conn.execute("SELECT file_id, module_name FROM gi_imports")
            for file_id, module_name in cursor.fetchall():
                if file_id not in file_to_sg or not module_name:
                    continue
                mod_sg = module_name_to_sg.get(module_name)
                if mod_sg is None:
                    mod_sg = g.add_node(
                        kind="module",
                        name=module_name,
                        data={"file_path": module_name},
                    )
                    module_name_to_sg[module_name] = mod_sg
                g.add_edge(file_to_sg[file_id], mod_sg, "imports")

            # tests edges:
            # 1. From test symbols to call-like targets they reference.
            for from_sg, to_sg, ref_kind in test_target_pairs:
                if ref_kind not in CALL_LIKE_KINDS:
                    continue
                g.add_edge(from_sg, to_sg, "tests")

            # 2. Name-convention matches.
            for gi_id, is_test in is_test_by_gi.items():
                if not is_test:
                    continue
                test_sg = gi_to_sg.get(gi_id)
                if test_sg is None:
                    continue
                test_name = next(
                    (name for name, nid in name_to_id.items() if nid == test_sg),
                    None,
                )
                if test_name is None:
                    continue
                for stem in _strip_test_prefix(test_name):
                    cand_sg = name_to_id.get(stem)
                    if cand_sg is None or cand_sg == test_sg:
                        continue
                    # Find the corresponding gi_id to check is_test on the target.
                    target_gi_id = next(
                        (gid for gid, sid in gi_to_sg.items() if sid == cand_sg),
                        None,
                    )
                    if target_gi_id is not None and is_test_by_gi.get(target_gi_id):
                        continue
                    g.add_edge(test_sg, cand_sg, "tests")
        finally:
            conn.close()

        g.checkpoint()

    def _find_id(self, name: str) -> int | None:
        """Resolve a symbol name to a node ID via sqlitegraph's name index."""
        ids = self._g().nodes_by_name_pattern(name)
        return ids[0] if ids else None

    def _build_hnsw_index(self, embedder: Embedder) -> None:
        """Embed every loaded symbol and bulk-insert into a HNSW index."""
        g = self._g()
        ids = g.node_ids()
        if not ids:
            return

        nodes = [_to_graphnode(g.get_node(nid)) for nid in ids]
        texts = [self.embed_text_for(n) for n in nodes]
        vectors = embedder.embed(texts)

        index = g.create_hnsw_index(name=HNSW_INDEX_NAME, dimension=embedder.dimension)
        items: list[tuple[list[float], dict[str, Any] | None]] = [
            (vec, {"node_id": node.id, "name": node.name})
            for vec, node in zip(vectors, nodes, strict=True)
        ]
        index.bulk_insert_vectors(items)
        g.checkpoint()

    @staticmethod
    def embed_text_for(node: GraphNode) -> str:
        """Construct the text used to embed a symbol for semantic search."""
        parts = [f"{node.kind} {node.name}"]
        if node.signature:
            parts.append(node.signature)
        if node.docstring:
            parts.append(node.docstring)
        return "\n".join(parts)

    # ── Queries ────────────────────────────────────────────────────

    def find_symbol(self, name: str) -> GraphNode | None:
        sg_id = self._find_id(name)
        if sg_id is None:
            return None
        return _to_graphnode(self._g().get_node(sg_id))

    def callers(self, name: str) -> list[GraphNode]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        result: list[GraphNode] = []
        seen: set[int] = set()
        for kind in CALL_LIKE_EDGE_TYPES:
            for cid in g.neighbors(sg_id, edge_type=kind, direction="incoming"):
                if cid in seen:
                    continue
                seen.add(cid)
                result.append(_to_graphnode(g.get_node(cid)))
        return result

    def callees(self, name: str) -> list[GraphNode]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        result: list[GraphNode] = []
        seen: set[int] = set()
        for kind in CALL_LIKE_EDGE_TYPES:
            for cid in g.neighbors(sg_id, edge_type=kind, direction="outgoing"):
                if cid in seen:
                    continue
                seen.add(cid)
                result.append(_to_graphnode(g.get_node(cid)))
        return result

    def tests_for(self, name: str) -> list[GraphNode]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        result: list[GraphNode] = []
        for cid in g.neighbors(sg_id, edge_type="tests", direction="incoming"):
            result.append(_to_graphnode(g.get_node(cid)))
        return result

    def impact(self, name: str, depth: int = 3) -> list[GraphNode]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        reached: set[int] = set()
        for kind in CALL_LIKE_EDGE_TYPES:
            reached |= {
                cid
                for cid in g.bfs(
                    sg_id, depth=depth, edge_types=[kind], direction="outgoing"
                )
                if cid != sg_id
            }
        return [_to_graphnode(g.get_node(cid)) for cid in reached]

    def affected(self, name: str, depth: int = 3) -> list[GraphNode]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        reached: set[int] = set()
        for kind in CALL_LIKE_EDGE_TYPES:
            reached |= {
                cid
                for cid in g.bfs(
                    sg_id, depth=depth, edge_types=[kind], direction="incoming"
                )
                if cid != sg_id
            }
        return [_to_graphnode(g.get_node(cid)) for cid in reached]

    def path(self, from_name: str, to_name: str) -> list[GraphNode] | None:
        from_id = self._find_id(from_name)
        to_id = self._find_id(to_name)
        if from_id is None or to_id is None:
            return None
        g = self._g()
        ids = g.shortest_path(from_id, to_id)
        if ids is None:
            return None
        return [_to_graphnode(g.get_node(cid)) for cid in ids]

    def neighborhood_context(
        self,
        name: str,
        depth: int = 2,
        budget: int = 4000,
    ) -> list[dict[str, Any]]:
        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        g = self._g()
        budget_enforcer = BudgetEnforcer(max_tokens=budget)

        out_ids = {cid for cid in g.bfs(sg_id, depth=depth) if cid != sg_id}
        in_ids: set[int] = set()
        frontier = {sg_id}
        for _ in range(depth):
            next_level: set[int] = set()
            for cid in frontier:
                for src in g.neighbors(cid, direction="incoming"):
                    if src not in in_ids and src != sg_id:
                        next_level.add(src)
            in_ids |= next_level
            frontier = next_level
            if not frontier:
                break

        target = _to_graphnode(g.get_node(sg_id))

        def _add(node: GraphNode, role: str) -> bool:
            try:
                src_path = self.root_path / node.file_path
                lines = src_path.read_text(encoding="utf-8").splitlines()
                source = "\n".join(lines[node.line_start - 1 : node.line_end])
            except OSError:
                source = ""
            item: dict[str, Any] = {
                "role": role,
                "symbol": node.name,
                "kind": node.kind,
                "file": node.file_path,
                "lines": (node.line_start, node.line_end),
                "source": source,
                "signature": node.signature,
                "docstring": node.docstring,
            }
            return budget_enforcer.add(item, source)  # type: ignore[no-any-return]

        _add(target, "target")

        for cid in out_ids | in_ids:
            if not budget_enforcer.can_fit(""):
                break
            node = _to_graphnode(g.get_node(cid))
            role = "callee" if cid in out_ids else "caller" if cid in in_ids else "related"
            _add(node, role)

        return budget_enforcer.items  # type: ignore[no-any-return]

    def stats(self) -> dict[str, int]:
        g = self._g()
        ids = g.node_ids()
        edges = sum(len(g.neighbors(nid, direction="outgoing")) for nid in ids)
        return {"nodes": len(ids), "edges": edges}

    # ── Semantic search ────────────────────────────────────────────

    def has_semantic_index(self) -> bool:
        """True when a HNSW index is attached to this graph."""
        return HNSW_INDEX_NAME in self._g().list_hnsw_indexes()

    def semantic_search(self, query: str, k: int = 10) -> list[tuple[GraphNode, float]]:
        """Return up to ``k`` symbols most semantically similar to ``query``.

        Returns an empty list when no HNSW index is attached or no embedder
        was provided at build time and the sidecar config is missing.
        """
        if self._embedder is None or not self.has_semantic_index():
            return []

        g = self._g()
        index = g.get_hnsw_index(HNSW_INDEX_NAME)
        query_vec = self._embedder.embed([query])[0]
        hits = index.search(query=query_vec, k=k)

        results: list[tuple[GraphNode, float]] = []
        for vector_id, distance in hits:
            stored = index.get_vector(vector_id)
            if stored is None:
                continue
            _vec, meta = stored
            node_id = meta.get("node_id") if isinstance(meta, dict) else None
            if not isinstance(node_id, int):
                continue
            try:
                node_dict = g.get_node(node_id)
            except Exception:
                continue
            results.append((_to_graphnode(node_dict), float(distance)))
        return results


def _has_is_test_column(conn: sqlite3.Connection) -> bool:
    """Detect whether the connected DB has `gi_symbols.is_test` (schema v2)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(gi_symbols)").fetchall()}
    return "is_test" in cols
