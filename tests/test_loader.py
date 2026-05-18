"""Tests for loader.py — reading grounded-index DB into graph."""

from pathlib import Path

from grounded_index.indexer import Indexer

from grounded_graph.loader import load_from_index


def test_load_creates_graph(tmp_path: Path) -> None:
    # Create a mini Python project
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)
"""
    )

    # Index it with grounded-index
    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()

    # Load into graph
    graph = load_from_index(db_path)

    # Should have nodes for symbols
    assert graph.stats()["nodes"] > 0

    # Should find hello and Greeter
    assert graph.find_by_name("hello") is not None
    assert graph.find_by_name("Greeter") is not None
    assert graph.find_by_name("greet") is not None


def test_load_creates_call_edges(tmp_path: Path) -> None:
    # greet() calls hello()
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)
"""
    )

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()

    graph = load_from_index(db_path)

    # Find the nodes
    hello_node = graph.find_by_name("hello")
    greet_node = graph.find_by_name("greet")
    assert hello_node is not None
    assert greet_node is not None

    # greet should have an edge to hello
    assert graph.has_edge(greet_node.id, hello_node.id)


def test_load_creates_inherit_edges(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """class Base:
    pass

class Child(Base):
    pass
"""
    )

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()

    graph = load_from_index(db_path)

    base_node = graph.find_by_name("Base")
    child_node = graph.find_by_name("Child")
    assert base_node is not None
    assert child_node is not None

    # Child should have an inherit edge to Base
    assert graph.has_edge(child_node.id, base_node.id)


# ---------------------------------------------------------------------------
# New edge kinds: imports, defines, tests
# ---------------------------------------------------------------------------


def test_load_creates_imports_edges(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """from utils import helper
import os

def main():
    helper()
"""
    )

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()
    graph = load_from_index(db_path)

    # There should be module nodes for the imported modules
    module_nodes = [
        n for n in graph.all_nodes() if n.kind == "module" and n.name in ("utils", "os")
    ]
    assert len(module_nodes) >= 1, "expected at least one module node from imports"

    # And imports edges from the file node to the modules
    imports_edges = [(frm, to) for frm, to, kind in graph.all_edges() if kind == "imports"]
    assert len(imports_edges) >= 1, "expected at least one imports edge"


def test_load_creates_defines_edges(tmp_path: Path) -> None:
    """When the underlying index DB has parent_id populated, the loader emits
    `defines` edges from parent symbol to child symbol.

    grounded-index 0.2.0 does not yet populate parent_id from any parser, so
    this test exercises the loader path with a hand-built fixture instead of
    relying on the indexer.
    """

    db_path = tmp_path / "index.db"
    # Bootstrap a fresh DB via the public path, then poke a parent_id link
    # to assert the loader honours it.
    from grounded_index.db import open_db

    conn = open_db(db_path)
    conn.execute(
        "INSERT INTO gi_files (path, language, content_hash, line_count) "
        "VALUES ('src/main.py', 'python', 'abc', 6)"
    )
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end) "
        "VALUES (1, 1, 'Greeter', 'class', 1, 6)"
    )
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end, parent_id) "
        "VALUES (2, 1, 'greet', 'method', 2, 3, 1)"
    )
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end, parent_id) "
        "VALUES (3, 1, 'farewell', 'method', 5, 6, 1)"
    )
    conn.close()

    graph = load_from_index(db_path)

    defines_targets: set[int] = set()
    for frm, to, kind in graph.all_edges():
        if kind == "defines" and frm == 1:
            defines_targets.add(to)
    assert defines_targets == {2, 3}


def test_load_creates_tests_edges(tmp_path: Path) -> None:
    # Rust fixture so grounded-index 0.2.0's is_test detection fires.
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text(
        """pub fn add(a: i32, b: i32) -> i32 { a + b }

#[cfg(test)]
mod tests {
    use super::add;

    #[test]
    fn test_add() {
        let _ = add(1, 2);
    }
}
"""
    )

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()
    graph = load_from_index(db_path)

    add_node = graph.find_by_name("add")
    test_add_node = graph.find_by_name("test_add")
    assert add_node is not None
    assert test_add_node is not None

    # There must be a `tests` edge from the test function to the production fn.
    has_tests_edge = any(
        frm == test_add_node.id and to == add_node.id and kind == "tests"
        for frm, to, kind in graph.all_edges()
    )
    assert has_tests_edge, "expected a tests edge from test_add to add"


def test_load_skips_empty_and_whitespace_names(tmp_path: Path) -> None:
    """Symbols with empty or whitespace-only names are parser artifacts and
    must not be added to the graph.  References that target empty names must
    not create false edges.
    """
    db_path = tmp_path / "index.db"
    from grounded_index.db import open_db

    conn = open_db(db_path)
    conn.execute(
        "INSERT INTO gi_files (path, language, content_hash, line_count) "
        "VALUES ('src/main.py', 'python', 'abc', 10)"
    )
    # Real symbol
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end) "
        "VALUES (1, 1, 'main', 'function', 1, 5)"
    )
    # Empty-name symbol (parser artifact)
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end) "
        "VALUES (2, 1, '', 'function', 7, 9)"
    )
    # Whitespace-only name (parser artifact)
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end) "
        "VALUES (3, 1, '   ', 'method', 10, 12)"
    )
    # Reference from main to empty target (parser artifact)
    conn.execute(
        "INSERT INTO gi_references (from_symbol_id, to_symbol_name, ref_kind, line) "
        "VALUES (1, '', 'call', 3)"
    )
    # Reference from main to whitespace target (parser artifact)
    conn.execute(
        "INSERT INTO gi_references (from_symbol_id, to_symbol_name, ref_kind, line) "
        "VALUES (1, '  ', 'call', 4)"
    )
    # Valid reference from main to something real
    conn.execute(
        "INSERT INTO gi_symbols (id, file_id, name, kind, line_start, line_end) "
        "VALUES (4, 1, 'helper', 'function', 14, 16)"
    )
    conn.execute(
        "INSERT INTO gi_references (from_symbol_id, to_symbol_name, ref_kind, line) "
        "VALUES (1, 'helper', 'call', 2)"
    )
    conn.close()

    graph = load_from_index(db_path)

    # Only main and helper should exist; empty/whitespace symbols are skipped
    names = {n.name for n in graph.all_nodes() if n.kind == "function" or n.kind == "method"}
    assert names == {"main", "helper"}, f"unexpected names in graph: {names}"

    # Only the valid reference edge should exist
    main_node = graph.find_by_name("main")
    assert main_node is not None
    helper_node = graph.find_by_name("helper")
    assert helper_node is not None
    assert graph.has_edge(main_node.id, helper_node.id), "valid edge missing"

    # No false edges from main to garbage nodes
    all_neighbors = graph.neighbors(main_node.id, direction="outgoing")
    assert all_neighbors == {helper_node.id}, f"unexpected neighbors: {all_neighbors}"
