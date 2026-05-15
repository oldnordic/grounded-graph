"""Tests for query.py — high-level graph queries."""

from pathlib import Path

from grounded_index.indexer import Indexer

from grounded_graph.graph import Graph, GraphNode
from grounded_graph.loader import load_from_index
from grounded_graph.query import QueryEngine


def _build_engine(tmp_path: Path) -> QueryEngine:
    """Build a QueryEngine from a sample repo."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)

def main() -> None:
    g = Greeter("Hi")
    print(g.greet("world"))
"""
    )

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()

    graph = load_from_index(db_path)
    return QueryEngine(graph, root_path=str(tmp_path))


def test_find_symbol(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    result = engine.find_symbol("hello")
    assert result is not None
    assert result.name == "hello"
    assert result.kind == "function"


def test_find_symbol_not_found(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    assert engine.find_symbol("nonexistent") is None


def test_callers(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    # greet() calls hello()
    callers = engine.callers("hello")
    names = {c.name for c in callers}
    assert "greet" in names


def test_callees(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    # main() calls Greeter(), greet(), print()
    callees = engine.callees("main")
    names = {c.name for c in callees}
    assert "greet" in names


def test_impact(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    # Changing main() affects greet(), hello(), Greeter (forward reach)
    impacted = engine.impact("main", depth=3)
    names = {n.name for n in impacted}
    assert "greet" in names
    assert "hello" in names


def test_affected(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    # hello() is affected by greet() and main() (backward reach)
    affecting = engine.affected("hello", depth=3)
    names = {n.name for n in affecting}
    assert "greet" in names


def test_path_between_symbols(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    path = engine.path("main", "hello")
    assert path is not None
    assert path[0].name == "main"
    assert path[-1].name == "hello"


def test_neighborhood(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    hood = engine.neighborhood("hello", depth=2)
    names = {n.name for n in hood}
    assert "hello" in names
    assert "greet" in names


def test_neighborhood_with_budget(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    # Small budget should still include target
    items = engine.neighborhood_context("hello", depth=2, budget=500)
    assert len(items) >= 1
    assert items[0]["symbol"] == "hello"


# ---------------------------------------------------------------------------
# Kind-aware queries: callers/callees filter out non-call edges
# ---------------------------------------------------------------------------


def _engine_with_mixed_edges() -> QueryEngine:
    g = Graph()
    g.add_node(GraphNode(id=1, kind="function", name="prod_a", file_path="src/a.py"))
    g.add_node(GraphNode(id=2, kind="function", name="prod_b", file_path="src/b.py"))
    g.add_node(GraphNode(id=3, kind="function", name="test_prod_b", file_path="tests/test_b.py"))
    g.add_node(GraphNode(id=4, kind="module", name="my_mod", file_path="src/a.py"))
    # prod_a calls prod_b
    g.add_edge(1, 2, "call")
    # test_prod_b tests prod_b
    g.add_edge(3, 2, "tests")
    # prod_a imports my_mod
    g.add_edge(1, 4, "imports")
    return QueryEngine(g, root_path="")


def test_callers_excludes_non_call_edges() -> None:
    engine = _engine_with_mixed_edges()
    callers = engine.callers("prod_b")
    names = {c.name for c in callers}
    assert "prod_a" in names
    # test_prod_b reaches prod_b via a `tests` edge, not a `call`. It MUST NOT
    # appear as a caller.
    assert "test_prod_b" not in names


def test_callees_excludes_non_call_edges() -> None:
    engine = _engine_with_mixed_edges()
    callees = engine.callees("prod_a")
    names = {c.name for c in callees}
    assert "prod_b" in names
    # prod_a -> my_mod is an `imports` edge, not a call.
    assert "my_mod" not in names


def test_tests_for_returns_test_callers() -> None:
    engine = _engine_with_mixed_edges()
    tests = engine.tests_for("prod_b")
    names = {t.name for t in tests}
    assert "test_prod_b" in names
    # Should NOT include prod_a (caller-but-not-test).
    assert "prod_a" not in names


def test_tests_for_returns_empty_for_untested_symbol() -> None:
    engine = _engine_with_mixed_edges()
    tests = engine.tests_for("prod_a")
    assert tests == []
