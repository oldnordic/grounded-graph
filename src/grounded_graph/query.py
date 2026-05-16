"""High-level graph queries over code metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from grounded_graph.graph import CALL_LIKE_KINDS, Graph, GraphNode


class QueryEngine:
    """Query interface for the code metadata graph."""

    def __init__(self, graph: Graph, root_path: str = "") -> None:
        self.graph = graph
        self.root_path = Path(root_path)

    def find_symbol(self, name: str) -> GraphNode | None:
        """Find a symbol node by exact name."""
        return self.graph.find_by_name(name)

    def _nodes_by_id(self, ids: set[int]) -> list[GraphNode]:
        result: list[GraphNode] = []
        for cid in ids:
            node = self.graph.get_node(cid)
            if node is not None:
                result.append(node)
        return result

    def callers(self, name: str) -> list[GraphNode]:
        """Symbols that call the named symbol (call-like edges only)."""
        node = self.find_symbol(name)
        if node is None:
            return []
        caller_ids = self.graph.neighbors(
            node.id, direction="incoming", edge_kinds=CALL_LIKE_KINDS
        )
        return self._nodes_by_id(caller_ids)

    def callees(self, name: str) -> list[GraphNode]:
        """Symbols that the named symbol calls (call-like edges only)."""
        node = self.find_symbol(name)
        if node is None:
            return []
        callee_ids = self.graph.neighbors(
            node.id, direction="outgoing", edge_kinds=CALL_LIKE_KINDS
        )
        return self._nodes_by_id(callee_ids)

    def tests_for(self, name: str) -> list[GraphNode]:
        """Symbols that test the named symbol (`tests` edges, incoming)."""
        node = self.find_symbol(name)
        if node is None:
            return []
        test_ids = self.graph.neighbors(
            node.id, direction="incoming", edge_kinds={"tests"}
        )
        return self._nodes_by_id(test_ids)

    def impact(self, name: str, depth: int = 3) -> list[GraphNode]:
        """Forward reachable symbols — what this symbol affects (call edges)."""
        node = self.find_symbol(name)
        if node is None:
            return []
        impacted_ids = self.graph.impact(node.id, depth=depth)
        return self._nodes_by_id(impacted_ids)

    def affected(self, name: str, depth: int = 3) -> list[GraphNode]:
        """Backward reachable symbols — what affects this symbol (call edges)."""
        node = self.find_symbol(name)
        if node is None:
            return []
        affecting_ids = self.graph.affected(node.id, depth=depth)
        return self._nodes_by_id(affecting_ids)

    def path(self, from_name: str, to_name: str) -> list[GraphNode] | None:
        """Shortest path between two symbols."""
        from_node = self.find_symbol(from_name)
        to_node = self.find_symbol(to_name)
        if from_node is None or to_node is None:
            return None
        path_ids = self.graph.shortest_path(from_node.id, to_node.id)
        if path_ids is None:
            return None
        result: list[GraphNode] = []
        for cid in path_ids:
            node = self.graph.get_node(cid)
            if node is not None:
                result.append(node)
        return result

    def neighborhood(self, name: str, depth: int = 2) -> list[GraphNode]:
        """N-hop neighborhood in both directions."""
        node = self.find_symbol(name)
        if node is None:
            return []
        out_ids = self.graph.bfs(node.id, depth=depth, direction="outgoing")
        in_ids = self.graph.bfs(node.id, depth=depth, direction="incoming")
        all_ids = {node.id} | out_ids | in_ids
        return self._nodes_by_id(all_ids)

    def neighborhood_context(
        self, name: str, depth: int = 2, budget: int = 4000
    ) -> list[dict[str, Any]]:
        """Token-bounded, priority-ranked context pack for the neighborhood.

        Delegates to :mod:`grounded_graph.context` so both backends produce
        the same shape — see ``rank_neighbors`` / ``pack_context``.
        """
        from grounded_graph.context import pack_context, rank_neighbors

        node = self.find_symbol(name)
        if node is None:
            return []
        ranked = rank_neighbors(self.graph, node.id, depth=depth)
        return pack_context(
            target=node, ranked=ranked, budget=budget, root_path=self.root_path
        )

    def stats(self) -> dict[str, int]:
        return self.graph.stats()
