"""In-memory graph model with node/edge storage and traversal algorithms."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


# ── Edge kinds ───────────────────────────────────────────────────────
#
# Kinds carried on edges. Callers/callees/impact/affected traversal should
# only follow `CALL_LIKE_KINDS` — `imports`, `defines`, and `tests` are
# different relationships and must not pollute call-graph queries.

CALL_LIKE_KINDS: frozenset[str] = frozenset(
    {"call", "method_call", "macro", "constructor", "construct"}
)


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
    """Directed graph with bidirectional edge tracking and multi-kind edges."""

    def __init__(self) -> None:
        self._nodes: dict[int, GraphNode] = {}
        self._forward: dict[int, set[int]] = {}
        self._reverse: dict[int, set[int]] = {}
        # Maps (from_id, to_id) -> set of edge kinds present between that pair.
        self._edge_kinds: dict[tuple[int, int], set[str]] = {}

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._forward.setdefault(node.id, set())
        self._reverse.setdefault(node.id, set())

    def add_edge(self, from_id: int, to_id: int, kind: str, line: int = 0) -> None:
        self._forward.setdefault(from_id, set()).add(to_id)
        self._reverse.setdefault(to_id, set()).add(from_id)
        self._edge_kinds.setdefault((from_id, to_id), set()).add(kind)

    def get_node(self, node_id: int) -> GraphNode | None:
        return self._nodes.get(node_id)

    def has_edge(self, from_id: int, to_id: int) -> bool:
        return to_id in self._forward.get(from_id, set())

    def has_reverse_edge(self, from_id: int, to_id: int) -> bool:
        return to_id in self._reverse.get(from_id, set())

    def edge_kinds(self, from_id: int, to_id: int) -> set[str]:
        """Return every kind on the edge from `from_id` to `to_id`."""
        return set(self._edge_kinds.get((from_id, to_id), ()))

    def all_nodes(self) -> Iterator[GraphNode]:
        return iter(self._nodes.values())

    def all_edges(self) -> Iterator[tuple[int, int, str]]:
        """Yield `(from_id, to_id, kind)` for every kind on every edge."""
        for (frm, to), kinds in self._edge_kinds.items():
            for kind in kinds:
                yield frm, to, kind

    def neighbors(
        self,
        node_id: int,
        direction: str = "outgoing",
        edge_kinds: Iterable[str] | None = None,
    ) -> set[int]:
        """Return neighbor IDs in the given direction, optionally filtered by kind."""
        if direction == "outgoing":
            candidates = self._forward.get(node_id, set())
            key = lambda nid: (node_id, nid)  # noqa: E731
        elif direction == "incoming":
            candidates = self._reverse.get(node_id, set())
            key = lambda nid: (nid, node_id)  # noqa: E731
        else:
            out = self._forward.get(node_id, set())
            inc = self._reverse.get(node_id, set())
            if edge_kinds is None:
                return set(out) | set(inc)
            allowed = set(edge_kinds)
            return {
                nid
                for nid in (set(out) | set(inc))
                if (
                    bool(self._edge_kinds.get((node_id, nid), set()) & allowed)
                    or bool(self._edge_kinds.get((nid, node_id), set()) & allowed)
                )
            }

        if edge_kinds is None:
            return set(candidates)

        allowed = set(edge_kinds)
        return {nid for nid in candidates if self._edge_kinds.get(key(nid), set()) & allowed}

    def bfs(
        self,
        start_id: int,
        depth: int,
        direction: str = "outgoing",
        edge_kinds: Iterable[str] | None = None,
    ) -> set[int]:
        """Breadth-first search up to depth hops, with optional kind filter."""
        allowed: set[str] | None = set(edge_kinds) if edge_kinds is not None else None

        visited: set[int] = set()
        queue: deque[tuple[int, int]] = deque([(start_id, 0)])

        while queue:
            current, dist = queue.popleft()
            if current in visited or dist > depth:
                continue
            if dist > 0:
                visited.add(current)

            for neighbor in self.neighbors(current, direction, edge_kinds=allowed):
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
        """Forward reachable set — symbols this node affects (call-like edges only)."""
        return self.bfs(node_id, depth, direction="outgoing", edge_kinds=CALL_LIKE_KINDS)

    def affected(self, node_id: int, depth: int = 3) -> set[int]:
        """Backward reachable set — symbols that affect this node (call-like edges only)."""
        return self.bfs(node_id, depth, direction="incoming", edge_kinds=CALL_LIKE_KINDS)

    def find_by_name(self, name: str) -> GraphNode | None:
        for node in self._nodes.values():
            if node.name == name:
                return node
        return None

    def stats(self) -> dict[str, int]:
        node_count = len(self._nodes)
        edge_count = sum(len(kinds) for kinds in self._edge_kinds.values())
        return {"nodes": node_count, "edges": edge_count}
