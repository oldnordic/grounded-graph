"""Sqlitegraph-backed graph storage and queries for grounded-graph."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import sqlitegraph

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


class _SqlitegraphNeighborsAdapter:
    """Adapt sqlitegraph.Graph to the context.NeighborsProvider protocol.

    `sqlitegraph.Graph.neighbors` takes a single `edge_type` and returns a
    list[int]; the context module wants a set[int] returned from a single
    call with a kind set. This adapter iterates the kinds and unions.
    """

    def __init__(self, g: sqlitegraph.Graph) -> None:
        self._g = g

    def neighbors(
        self,
        node_id: int,
        direction: str = "outgoing",
        edge_kinds: Iterable[str] | None = None,
    ) -> set[int]:
        if edge_kinds is None:
            return set(self._g.neighbors(node_id, direction=direction))
        result: set[int] = set()
        for kind in edge_kinds:
            result.update(self._g.neighbors(node_id, edge_type=kind, direction=direction))
        return result

    def get_node(self, node_id: int) -> GraphNode | None:
        try:
            node = self._g.get_node(node_id)
        except Exception:
            return None
        if node is None:
            return None
        return _to_graphnode(node)


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
        """Populate the sqlitegraph DB from a grounded-index SQLite file.

        Uses sqlitegraph 0.3.0's bulk-insert API to batch all node and edge
        inserts into two FFI calls per kind, closing the per-row FFI gap that
        dominated the previous build time.
        """
        g = self._g()
        conn = sqlite3.connect(str(index_db_path))
        try:
            has_is_test = _has_is_test_column(conn)

            # ── Symbol nodes (one bulk insert) ──────────────────────
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
            sym_rows = conn.execute(sym_query).fetchall()

            sym_items: list[dict[str, Any]] = []
            sym_gi_ids: list[int] = []
            sym_names: list[str] = []
            sym_is_test_flags: list[bool] = []
            sym_parent_ids: list[int | None] = []

            for row in sym_rows:
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
                sym_items.append({"kind": kind, "name": name, "data": data})
                sym_gi_ids.append(gi_id)
                sym_names.append(name)
                sym_is_test_flags.append(is_test)
                sym_parent_ids.append(parent_id)

            sym_sg_ids = g.add_nodes_bulk(sym_items)
            gi_to_sg = dict(zip(sym_gi_ids, sym_sg_ids, strict=True))
            name_to_id = dict(zip(sym_names, sym_sg_ids, strict=True))
            is_test_by_gi = dict(zip(sym_gi_ids, sym_is_test_flags, strict=True))

            # ── File nodes (one bulk insert) ────────────────────────
            file_rows = conn.execute("SELECT id, path FROM gi_files").fetchall()
            file_items = [
                {"kind": "file", "name": path, "data": {"file_path": path}}
                for _, path in file_rows
            ]
            file_sg_ids = g.add_nodes_bulk(file_items) if file_items else []
            file_to_sg = dict(zip((fid for fid, _ in file_rows), file_sg_ids, strict=True))

            # ── Module nodes (one bulk insert) ──────────────────────
            import_rows = conn.execute(
                "SELECT file_id, module_name FROM gi_imports"
            ).fetchall()
            unique_modules: list[str] = []
            seen_modules: set[str] = set()
            for _, module_name in import_rows:
                if module_name and module_name not in seen_modules:
                    unique_modules.append(module_name)
                    seen_modules.add(module_name)
            mod_items = [
                {"kind": "module", "name": mn, "data": {"file_path": mn}}
                for mn in unique_modules
            ]
            mod_sg_ids = g.add_nodes_bulk(mod_items) if mod_items else []
            module_name_to_sg = dict(zip(unique_modules, mod_sg_ids, strict=True))

            # ── Collect all edges into one bulk insert ──────────────
            edge_items: list[dict[str, Any]] = []
            test_target_pairs: list[tuple[int, int, str]] = []

            # Reference edges from gi_references.
            ref_rows = conn.execute(
                "SELECT from_symbol_id, to_symbol_name, ref_kind FROM gi_references"
            ).fetchall()
            for from_gi_id, to_name, ref_kind in ref_rows:
                from_sg = gi_to_sg.get(from_gi_id)
                to_sg = name_to_id.get(to_name)
                if from_sg is None or to_sg is None:
                    continue
                edge_items.append(
                    {"from_id": from_sg, "to_id": to_sg, "edge_type": ref_kind}
                )
                if is_test_by_gi.get(from_gi_id):
                    test_target_pairs.append((from_sg, to_sg, ref_kind))

            # defines edges from parent_id.
            for gi_id, parent_id in zip(sym_gi_ids, sym_parent_ids, strict=True):
                if parent_id is None:
                    continue
                parent_sg = gi_to_sg.get(parent_id)
                child_sg = gi_to_sg.get(gi_id)
                if parent_sg is not None and child_sg is not None:
                    edge_items.append(
                        {
                            "from_id": parent_sg,
                            "to_id": child_sg,
                            "edge_type": "defines",
                        }
                    )

            # imports edges: file → module nodes.
            for file_id, module_name in import_rows:
                if file_id not in file_to_sg or not module_name:
                    continue
                mod_sg = module_name_to_sg.get(module_name)
                if mod_sg is None:
                    continue
                edge_items.append(
                    {
                        "from_id": file_to_sg[file_id],
                        "to_id": mod_sg,
                        "edge_type": "imports",
                    }
                )

            # tests edges: from test symbols to call-like reference targets.
            for from_sg, to_sg, ref_kind in test_target_pairs:
                if ref_kind not in CALL_LIKE_KINDS:
                    continue
                edge_items.append(
                    {"from_id": from_sg, "to_id": to_sg, "edge_type": "tests"}
                )

            # tests edges: name-convention matches (test_foo → foo).
            sg_to_gi = {sg: gi for gi, sg in gi_to_sg.items()}
            for gi_id, is_test in zip(sym_gi_ids, sym_is_test_flags, strict=True):
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
                    target_gi_id = sg_to_gi.get(cand_sg)
                    if target_gi_id is not None and is_test_by_gi.get(target_gi_id):
                        continue
                    edge_items.append(
                        {
                            "from_id": test_sg,
                            "to_id": cand_sg,
                            "edge_type": "tests",
                        }
                    )

            if edge_items:
                g.add_edges_bulk(edge_items)
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
        from grounded_graph.context import pack_context, rank_neighbors

        sg_id = self._find_id(name)
        if sg_id is None:
            return []
        target = _to_graphnode(self._g().get_node(sg_id))
        adapter = _SqlitegraphNeighborsAdapter(self._g())
        ranked = rank_neighbors(adapter, target_id=sg_id, depth=depth)
        return pack_context(
            target=target, ranked=ranked, budget=budget, root_path=self.root_path
        )

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
