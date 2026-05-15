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
