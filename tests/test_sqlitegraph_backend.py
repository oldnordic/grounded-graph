"""Tests for sqlitegraph backend integration (in-memory variant)."""

from pathlib import Path

from grounded_index.indexer import Indexer

from grounded_graph.graph import GraphNode
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend


def _build_backend(tmp_path: Path) -> SqlitegraphBackend:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)

def main() -> None:
    g = Greeter()
    print(g.greet("world"))
"""
    )

    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()

    return SqlitegraphBackend.build(db_path, sg_db_path=None, root_path=str(tmp_path))


def test_loads_symbols(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    node = backend.find_symbol("hello")
    assert isinstance(node, GraphNode)
    assert node.name == "hello"
    assert node.kind == "function"


def test_loads_call_edges(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    assert backend.find_symbol("hello") is not None
    assert backend.find_symbol("greet") is not None

    callers = backend.callers("hello")
    caller_names = {c.name for c in callers}
    assert "greet" in caller_names


def test_shortest_path(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    path = backend.path("main", "hello")
    assert path is not None
    assert path[0].name == "main"
    assert path[-1].name == "hello"


def test_impact(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    impacted = backend.impact("main", depth=3)
    names = {n.name for n in impacted}
    assert "greet" in names
    assert "hello" in names


def test_neighborhood_context(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    items = backend.neighborhood_context("hello", depth=2, budget=500)
    assert len(items) >= 1
    assert items[0]["symbol"] == "hello"


def test_stats(tmp_path: Path) -> None:
    backend = _build_backend(tmp_path)
    stats = backend.stats()
    assert stats["nodes"] > 0
    assert stats["edges"] > 0
