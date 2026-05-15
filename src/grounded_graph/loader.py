"""Load a grounded-index SQLite database into an in-memory Graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from grounded_graph.graph import Graph, GraphNode


def load_from_index(db_path: Path | str) -> Graph:
    """Read a grounded-index database and build an in-memory graph."""
    conn = sqlite3.connect(str(db_path))
    graph = Graph()

    # Load symbols as nodes
    cursor = conn.execute(
        """
        SELECT s.id, s.name, s.kind, f.path, s.line_start, s.line_end,
               s.signature, s.docstring, s.is_public
        FROM gi_symbols s
        JOIN gi_files f ON s.file_id = f.id
        """
    )
    for row in cursor.fetchall():
        graph.add_node(
            GraphNode(
                id=row[0],
                name=row[1],
                kind=row[2],
                file_path=row[3],
                line_start=row[4],
                line_end=row[5],
                signature=row[6],
                docstring=row[7],
                is_public=bool(row[8]),
            )
        )

    # Load references as edges
    cursor = conn.execute(
        """
        SELECT from_symbol_id, to_symbol_name, ref_kind, line
        FROM gi_references
        """
    )
    for row in cursor.fetchall():
        from_id, to_name, kind, line = row
        # Resolve to_symbol_name to a node id
        to_node = graph.find_by_name(to_name)
        if to_node is not None:
            graph.add_edge(from_id, to_node.id, kind, line or 0)

    # Load files as additional nodes (for file-level queries)
    cursor = conn.execute("SELECT id, path, language, line_count FROM gi_files")
    file_id_map: dict[int, int] = {}
    for row in cursor.fetchall():
        file_id, path, _language, line_count = row
        # Use negative ids for file nodes to avoid collision with symbol ids
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

    # Add contains edges: file -> symbols in that file
    cursor = conn.execute("SELECT id, file_id FROM gi_symbols")
    for row in cursor.fetchall():
        sym_id, file_id = row
        if file_id in file_id_map:
            graph.add_edge(file_id_map[file_id], sym_id, "contains")

    conn.close()
    return graph
