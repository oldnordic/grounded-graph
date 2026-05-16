"""Tests for the priority-ranked context pack (sub-project #3)."""

from __future__ import annotations

from pathlib import Path

from grounded_graph.context import pack_context, rank_neighbors
from grounded_graph.graph import Graph, GraphNode


def _node(nid: int, name: str, kind: str = "function", file_path: str = "x.py") -> GraphNode:
    return GraphNode(
        id=nid,
        kind=kind,
        name=name,
        file_path=file_path,
        line_start=1,
        line_end=3,
    )


# ---------------------------------------------------------------------------
# rank_neighbors — priority order
# ---------------------------------------------------------------------------


def test_rank_neighbors_orders_callees_before_callers() -> None:
    g = Graph()
    target = _node(1, "target")
    callee = _node(2, "callee_fn")
    caller = _node(3, "caller_fn")
    for n in (target, callee, caller):
        g.add_node(n)
    g.add_edge(1, 2, "call")  # target calls callee
    g.add_edge(3, 1, "call")  # caller calls target

    ranked = rank_neighbors(g, target_id=1, depth=2)
    roles = [r for r, _ in ranked]
    assert roles.index("callee") < roles.index("caller")


def test_rank_neighbors_tests_after_call_neighbors() -> None:
    g = Graph()
    target = _node(1, "add")
    callee = _node(2, "helper")
    caller = _node(3, "consumer")
    tester = _node(4, "test_add")
    for n in (target, callee, caller, tester):
        g.add_node(n)
    g.add_edge(1, 2, "call")
    g.add_edge(3, 1, "call")
    g.add_edge(4, 1, "tests")

    ranked = rank_neighbors(g, target_id=1, depth=2)
    roles = [r for r, _ in ranked]
    assert roles.index("callee") < roles.index("tested-by")
    assert roles.index("caller") < roles.index("tested-by")


def test_rank_neighbors_imports_last() -> None:
    g = Graph()
    target = _node(1, "X")
    callee = _node(2, "Y")
    module = _node(3, "some_module", kind="module", file_path="some_module")
    for n in (target, callee, module):
        g.add_node(n)
    g.add_edge(1, 2, "call")
    g.add_edge(1, 3, "imports")

    ranked = rank_neighbors(g, target_id=1, depth=2)
    roles = [r for r, _ in ranked]
    assert roles[-1] == "imports"


def test_rank_neighbors_stable_order_within_tier() -> None:
    g = Graph()
    target = _node(1, "X")
    a = _node(5, "a")
    b = _node(2, "b")
    c = _node(7, "c")
    for n in (target, a, b, c):
        g.add_node(n)
    g.add_edge(1, 5, "call")
    g.add_edge(1, 2, "call")
    g.add_edge(1, 7, "call")

    ranked = rank_neighbors(g, target_id=1, depth=1)
    callee_ids = [node.id for r, node in ranked if r == "callee"]
    # Stable order = ascending symbol_id
    assert callee_ids == sorted(callee_ids)
    assert callee_ids == [2, 5, 7]


def test_rank_neighbors_depth2_callees_after_depth1_callers() -> None:
    g = Graph()
    target = _node(1, "target")
    direct_callee = _node(2, "d1_callee")
    direct_caller = _node(3, "d1_caller")
    transitive_callee = _node(4, "d2_callee")
    for n in (target, direct_callee, direct_caller, transitive_callee):
        g.add_node(n)
    g.add_edge(1, 2, "call")
    g.add_edge(3, 1, "call")
    g.add_edge(2, 4, "call")  # callee-of-callee

    ranked = rank_neighbors(g, target_id=1, depth=2)
    roles = [r for r, _ in ranked]
    # Transitive callee tier comes after direct caller tier.
    assert roles.index("caller") < roles.index("callee-2")


# ---------------------------------------------------------------------------
# pack_context — snippet fallback modes
# ---------------------------------------------------------------------------


def test_pack_context_includes_target_first(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("def a():\n    return 1\n")
    target = _node(1, "a", file_path="x.py")

    items = pack_context(target=target, ranked=[], budget=4000, root_path=tmp_path)
    assert len(items) == 1
    assert items[0]["role"] == "target"
    assert items[0]["symbol"] == "a"
    assert items[0]["mode"] in {"full", "head", "signature-only"}


def test_pack_context_full_mode_when_budget_allows(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("def a():\n    return 1\n")
    target = _node(1, "a", file_path="x.py")

    items = pack_context(target=target, ranked=[], budget=4000, root_path=tmp_path)
    assert items[0]["mode"] == "full"
    assert "return 1" in items[0]["source"]


def test_pack_context_falls_back_to_signature_only_when_source_too_big(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    big = "x = 1\n" * 5000  # ~30k chars; ~7500 tokens at 0.25 tokens/char
    src.write_text(big)
    target = GraphNode(
        id=1,
        kind="function",
        name="big_fn",
        file_path="x.py",
        line_start=1,
        line_end=5000,
        signature="def big_fn():",
        docstring="A doc.",
    )

    # Budget tight enough that even the head slice (~20 lines * 6 chars * 0.25 tok/char = ~30 tok)
    # doesn't fit, but signature+docstring (~20 chars * 0.25 = ~5 tok) does.
    items = pack_context(target=target, ranked=[], budget=10, root_path=tmp_path)
    assert len(items) == 1
    assert items[0]["mode"] == "signature-only"
    assert items[0]["source"] == ""
    assert items[0]["signature"] == "def big_fn():"


def test_pack_context_head_mode_for_long_symbol(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("\n".join(f"line {i}" for i in range(100)) + "\n")
    target = GraphNode(
        id=1,
        kind="function",
        name="long_fn",
        file_path="x.py",
        line_start=1,
        line_end=100,
        signature="def long_fn():",
    )
    # ~700 chars in full body => 175 tokens; head of 20 lines => ~140 chars => ~35 tokens.
    # Budget 100 => head fits, full doesn't.
    items = pack_context(target=target, ranked=[], budget=100, root_path=tmp_path)
    assert len(items) == 1
    assert items[0]["mode"] == "head"
    # First line is included, line 99 is not.
    assert "line 0" in items[0]["source"]
    assert "line 99" not in items[0]["source"]


def test_pack_context_skips_below_signature_budget(tmp_path: Path) -> None:
    """When budget is too small for even the signature, the item is dropped."""
    src = tmp_path / "x.py"
    src.write_text("def x(): pass\n")
    target = GraphNode(
        id=1,
        kind="function",
        name="x",
        file_path="x.py",
        line_start=1,
        line_end=1,
        signature="def x_with_a_really_long_signature_that_exceeds_the_tiny_budget():",
        docstring="A doc that also takes more tokens than we have available.",
    )
    items = pack_context(target=target, ranked=[], budget=1, root_path=tmp_path)
    assert items == []


def test_pack_context_walks_ranked_in_order(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("def a(): pass\ndef b(): pass\ndef c(): pass\n")
    target = GraphNode(
        id=1, kind="function", name="a", file_path="x.py", line_start=1, line_end=1
    )
    b = GraphNode(id=2, kind="function", name="b", file_path="x.py", line_start=2, line_end=2)
    c = GraphNode(id=3, kind="function", name="c", file_path="x.py", line_start=3, line_end=3)

    items = pack_context(
        target=target,
        ranked=[("callee", b), ("caller", c)],
        budget=4000,
        root_path=tmp_path,
    )
    assert [i["symbol"] for i in items] == ["a", "b", "c"]
    assert [i["role"] for i in items] == ["target", "callee", "caller"]


def test_pack_context_includes_mode_field(tmp_path: Path) -> None:
    src = tmp_path / "x.py"
    src.write_text("def a(): pass\n")
    target = GraphNode(
        id=1, kind="function", name="a", file_path="x.py", line_start=1, line_end=1
    )
    items = pack_context(target=target, ranked=[], budget=4000, root_path=tmp_path)
    assert "mode" in items[0]
