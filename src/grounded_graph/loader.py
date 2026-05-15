"""Load a grounded-index SQLite database into an in-memory Graph."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from grounded_graph.graph import CALL_LIKE_KINDS, Graph, GraphNode


# Module node IDs are negative and offset to avoid colliding with file nodes
# (also negative) and symbol nodes (positive). File ids start at 1 in
# grounded-index; module ids are assigned starting at MODULE_ID_BASE.
MODULE_ID_BASE = -1_000_000


def _strip_test_prefix(name: str) -> set[str]:
    """Return candidate target-name strings stripped of common test prefixes."""
    candidates: set[str] = set()
    lowered = name
    for prefix in ("test_", "tests_"):
        if lowered.startswith(prefix):
            candidates.add(lowered[len(prefix) :])
    # CamelCase suffixes: FooTest, FooSpec
    m = re.match(r"^(?P<stem>.+?)(Test|Tests|Spec)$", name)
    if m:
        candidates.add(m.group("stem"))
    return candidates


def load_from_index(db_path: Path | str) -> Graph:
    """Read a grounded-index database and build an in-memory graph."""
    conn = sqlite3.connect(str(db_path))
    graph = Graph()

    # ── Symbols as nodes ────────────────────────────────────────────
    symbol_is_test: dict[int, bool] = {}
    has_is_test = _has_is_test_column(conn)
    sym_query = (
        """
        SELECT s.id, s.name, s.kind, f.path, s.line_start, s.line_end,
               s.signature, s.docstring, s.is_public, s.parent_id, s.is_test
        FROM gi_symbols s
        JOIN gi_files f ON s.file_id = f.id
        """
        if has_is_test
        else """
        SELECT s.id, s.name, s.kind, f.path, s.line_start, s.line_end,
               s.signature, s.docstring, s.is_public, s.parent_id, 0
        FROM gi_symbols s
        JOIN gi_files f ON s.file_id = f.id
        """
    )
    cursor = conn.execute(sym_query)
    parent_map: dict[int, int | None] = {}
    name_to_ids: dict[str, list[int]] = {}
    for row in cursor.fetchall():
        sid, name = row[0], row[1]
        graph.add_node(
            GraphNode(
                id=sid,
                name=name,
                kind=row[2],
                file_path=row[3],
                line_start=row[4],
                line_end=row[5],
                signature=row[6],
                docstring=row[7],
                is_public=bool(row[8]),
            )
        )
        parent_map[sid] = row[9]
        symbol_is_test[sid] = bool(row[10])
        name_to_ids.setdefault(name, []).append(sid)

    # ── Files as nodes ──────────────────────────────────────────────
    file_id_map: dict[int, int] = {}
    cursor = conn.execute("SELECT id, path, language, line_count FROM gi_files")
    for row in cursor.fetchall():
        file_id, path, _language, line_count = row
        node_id = -file_id
        file_id_map[file_id] = node_id
        graph.add_node(
            GraphNode(
                id=node_id,
                name=path,
                kind="file",
                file_path=path,
                line_start=0,
                line_end=line_count,
            )
        )

    # ── `contains` edges: file → symbols inside the file ────────────
    cursor = conn.execute("SELECT id, file_id FROM gi_symbols")
    for sym_id, file_id in cursor.fetchall():
        if file_id in file_id_map:
            graph.add_edge(file_id_map[file_id], sym_id, "contains")

    # ── Reference edges from gi_references (preserves ref_kind) ─────
    test_symbol_outgoing_targets: dict[int, set[int]] = {}
    cursor = conn.execute(
        "SELECT from_symbol_id, to_symbol_name, ref_kind, line FROM gi_references"
    )
    for from_id, to_name, kind, line in cursor.fetchall():
        to_node = graph.find_by_name(to_name)
        if to_node is None:
            continue
        graph.add_edge(from_id, to_node.id, kind, line or 0)
        if symbol_is_test.get(from_id):
            test_symbol_outgoing_targets.setdefault(from_id, set()).add(to_node.id)

    # ── `defines` edges from parent_id ──────────────────────────────
    for sym_id, parent_id in parent_map.items():
        if parent_id is not None and parent_id in graph._nodes:  # noqa: SLF001
            graph.add_edge(parent_id, sym_id, "defines")

    # ── `imports` edges from gi_imports (file → module node) ────────
    module_name_to_id: dict[str, int] = {}
    next_module_id = MODULE_ID_BASE
    cursor = conn.execute("SELECT file_id, module_name, imported_name, line FROM gi_imports")
    for file_id, module_name, _imported_name, line in cursor.fetchall():
        if file_id not in file_id_map or not module_name:
            continue
        if module_name not in module_name_to_id:
            module_name_to_id[module_name] = next_module_id
            graph.add_node(
                GraphNode(
                    id=next_module_id,
                    name=module_name,
                    kind="module",
                    file_path=module_name,
                )
            )
            next_module_id -= 1
        graph.add_edge(
            file_id_map[file_id],
            module_name_to_id[module_name],
            "imports",
            line or 0,
        )

    # ── `tests` edges from test symbols ─────────────────────────────
    # 1. References originating from a test symbol → `tests` edge alongside
    #    the original reference edge.
    for test_id, targets in test_symbol_outgoing_targets.items():
        for target_id in targets:
            target_node = graph.get_node(target_id)
            if target_node is None:
                continue
            if symbol_is_test.get(target_id):
                continue  # test → test is not a "tests" relation
            # Only treat call-like targets as tested symbols. References to
            # types or modules from inside a test aren't meaningful coverage.
            kinds_between = graph.edge_kinds(test_id, target_id)
            if not (kinds_between & CALL_LIKE_KINDS):
                continue
            graph.add_edge(test_id, target_id, "tests")

    # 2. Name-convention matches: `test_foo` → any production `foo`.
    for test_id, is_test in symbol_is_test.items():
        if not is_test:
            continue
        test_node = graph.get_node(test_id)
        if test_node is None:
            continue
        for stem in _strip_test_prefix(test_node.name):
            for cand_id in name_to_ids.get(stem, ()):
                if cand_id == test_id:
                    continue
                if symbol_is_test.get(cand_id):
                    continue
                graph.add_edge(test_id, cand_id, "tests")

    conn.close()
    return graph


def _has_is_test_column(conn: sqlite3.Connection) -> bool:
    """Detect whether the connected DB has `gi_symbols.is_test` (schema v2)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(gi_symbols)").fetchall()}
    return "is_test" in cols
