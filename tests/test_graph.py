"""Tests for graph.py — in-memory graph and algorithms."""

from grounded_graph.graph import Graph, GraphNode


def _build_sample_graph() -> Graph:
    """Build a sample call graph:

    main() -> greet() -> format_msg()
    main() -> cleanup()
    helper() -> format_msg()
    """
    g = Graph()
    g.add_node(GraphNode(id=1, kind="function", name="main", file_path="src/main.py"))
    g.add_node(GraphNode(id=2, kind="function", name="greet", file_path="src/main.py"))
    g.add_node(GraphNode(id=3, kind="function", name="format_msg", file_path="src/utils.py"))
    g.add_node(GraphNode(id=4, kind="function", name="cleanup", file_path="src/main.py"))
    g.add_node(GraphNode(id=5, kind="function", name="helper", file_path="src/utils.py"))

    g.add_edge(1, 2, "call")  # main -> greet
    g.add_edge(2, 3, "call")  # greet -> format_msg
    g.add_edge(1, 4, "call")  # main -> cleanup
    g.add_edge(5, 3, "call")  # helper -> format_msg
    return g


def test_add_node_and_lookup() -> None:
    g = Graph()
    node = GraphNode(id=1, kind="function", name="foo", file_path="a.py")
    g.add_node(node)

    assert g.get_node(1) == node
    assert g.get_node(99) is None


def test_add_edge_bidirectional() -> None:
    g = _build_sample_graph()

    # Forward edges
    assert g.has_edge(1, 2)
    assert g.has_edge(2, 3)
    assert not g.has_edge(3, 1)

    # Reverse edges
    assert g.has_reverse_edge(2, 1)  # 2 is called by 1
    assert g.has_reverse_edge(3, 2)  # 3 is called by 2


def test_neighbors_outgoing() -> None:
    g = _build_sample_graph()
    neighbors = g.neighbors(1, direction="outgoing")
    assert set(neighbors) == {2, 4}


def test_neighbors_incoming() -> None:
    g = _build_sample_graph()
    callers = g.neighbors(3, direction="incoming")
    assert set(callers) == {2, 5}


def test_bfs_forward() -> None:
    g = _build_sample_graph()
    reachable = g.bfs(1, depth=2, direction="outgoing")
    assert set(reachable) == {2, 4, 3}


def test_bfs_backward() -> None:
    g = _build_sample_graph()
    affecting = g.bfs(3, depth=2, direction="incoming")
    assert set(affecting) == {2, 5, 1}


def test_shortest_path_found() -> None:
    g = _build_sample_graph()
    path = g.shortest_path(1, 3)
    assert path == [1, 2, 3]


def test_shortest_path_not_found() -> None:
    g = _build_sample_graph()
    path = g.shortest_path(3, 4)
    assert path is None


def test_impact() -> None:
    g = _build_sample_graph()
    affected = g.impact(1, depth=2)
    assert set(affected) == {2, 4, 3}


def test_affected() -> None:
    g = _build_sample_graph()
    sources = g.affected(3, depth=2)
    assert set(sources) == {2, 5, 1}


def test_find_by_name() -> None:
    g = _build_sample_graph()
    node = g.find_by_name("greet")
    assert node is not None
    assert node.id == 2

    assert g.find_by_name("nonexistent") is None


def test_stats() -> None:
    g = _build_sample_graph()
    stats = g.stats()
    assert stats["nodes"] == 5
    assert stats["edges"] == 4
