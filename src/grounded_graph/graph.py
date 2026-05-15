"""In-memory graph model with node/edge storage and traversal algorithms."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class GraphNode:
    id: int
    kind: str
    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    signature: str | None = None
    docstring: str | None = None
    is_public: bool = True


@dataclass(frozen=True)
class GraphEdge:
    from_id: int
    to_id: int
    kind: str
    line: int = 0


class Graph:
    """Directed graph with bidirectional edge tracking."""

    def __init__(self) -> None:
        self._nodes: dict[int, GraphNode] = {}
        self._forward: dict[int, set[int]] = {}
        self._reverse: dict[int, set[int]] = {}
        self._edge_kinds: dict[tuple[int, int], str] = {}

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._forward.setdefault(node.id, set())
        self._reverse.setdefault(node.id, set())

    def add_edge(self, from_id: int, to_id: int, kind: str, line: int = 0) -> None:
        self._forward.setdefault(from_id, set()).add(to_id)
        self._reverse.setdefault(to_id, set()).add(from_id)
        self._edge_kinds[(from_id, to_id)] = kind

    def get_node(self, node_id: int) -> GraphNode | None:
        return self._nodes.get(node_id)

    def has_edge(self, from_id: int, to_id: int) -> bool:
        return to_id in self._forward.get(from_id, set())

    def has_reverse_edge(self, from_id: int, to_id: int) -> bool:
        return to_id in self._reverse.get(from_id, set())

    def neighbors(self, node_id: int, direction: str = "outgoing") -> set[int]:
        if direction == "outgoing":
            return set(self._forward.get(node_id, set()))
        if direction == "incoming":
            return set(self._reverse.get(node_id, set()))
        return set(self._forward.get(node_id, set())) | set(self._reverse.get(node_id, set()))

    def bfs(self, start_id: int, depth: int, direction: str = "outgoing") -> set[int]:
        """Breadth-first search up to depth hops."""
        visited: set[int] = set()
        queue: deque[tuple[int, int]] = deque([(start_id, 0)])

        while queue:
            current, dist = queue.popleft()
            if current in visited or dist > depth:
                continue
            if dist > 0:
                visited.add(current)

            for neighbor in self.neighbors(current, direction):
                if neighbor not in visited:
                    queue.append((neighbor, dist + 1))

        return visited

    def shortest_path(self, from_id: int, to_id: int) -> list[int] | None:
        """Find shortest path using BFS."""
        if from_id not in self._nodes or to_id not in self._nodes:
            return None

        queue: deque[tuple[int, list[int]]] = deque([(from_id, [from_id])])
        visited: set[int] = {from_id}

        while queue:
            current, path = queue.popleft()
            if current == to_id:
                return path

            for neighbor in sorted(self._forward.get(current, set())):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path, neighbor]))

        return None

    def impact(self, node_id: int, depth: int = 3) -> set[int]:
        """Forward reachable set — symbols this node affects."""
        return self.bfs(node_id, depth, direction="outgoing")

    def affected(self, node_id: int, depth: int = 3) -> set[int]:
        """Backward reachable set — symbols that affect this node."""
        return self.bfs(node_id, depth, direction="incoming")

    def find_by_name(self, name: str) -> GraphNode | None:
        for node in self._nodes.values():
            if node.name == name:
                return node
        return None

    def stats(self) -> dict[str, int]:
        node_count = len(self._nodes)
        edge_count = sum(len(v) for v in self._forward.values())
        return {"nodes": node_count, "edges": edge_count}
