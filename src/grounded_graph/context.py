"""Priority-ranked context pack builder shared between backends.

Two entry points:

- ``rank_neighbors`` orders the neighbors of a target node by edge-kind
  priority (callees first, then callers, then tests, then structural
  defines, then transitive call neighbors at depth 2, then imports, then
  anything else inside the search depth). Within a tier, neighbors are
  ordered by symbol id for stable output.

- ``pack_context`` fills a token budget starting from the target, walks the
  ranked candidate list, and degrades each snippet from full source to a
  head slice to signature-only as the budget tightens. Items that don't fit
  in even signature-only mode are dropped.

Both backends adapt to a small protocol (`NeighborsProvider`) so they share
this logic instead of each maintaining a parallel implementation.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from grounded_index.budget import BudgetEnforcer  # type: ignore[import-untyped]

from grounded_graph.graph import CALL_LIKE_KINDS, GraphNode

DEFAULT_HEAD_LINES = 20


class NeighborsProvider(Protocol):
    """Minimal interface ranking needs from a graph backend."""

    def neighbors(
        self,
        node_id: int,
        direction: str = "outgoing",
        edge_kinds: Iterable[str] | None = None,
    ) -> set[int]: ...

    def get_node(self, node_id: int) -> GraphNode | None: ...


_ROLE_TIER: dict[str, int] = {
    "target": 0,
    "callee": 1,
    "caller": 2,
    "tested-by": 3,
    "tests": 3,
    "defined-in": 4,
    "defines": 4,
    "callee-2": 5,
    "caller-2": 5,
    "imports": 6,
    "imported-by": 6,
    "related": 7,
}


def rank_neighbors(
    graph: NeighborsProvider, target_id: int, depth: int = 2
) -> list[tuple[str, GraphNode]]:
    """Return ``(role, node)`` pairs ordered by priority tier then symbol id."""
    seen: set[int] = {target_id}
    buckets: dict[str, list[GraphNode]] = {role: [] for role in _ROLE_TIER}

    def _take(role: str, nid: int) -> None:
        if nid in seen:
            return
        node = graph.get_node(nid)
        if node is None:
            return
        seen.add(nid)
        buckets[role].append(node)

    # Tier 1 — direct callees (call-like outgoing).
    for nid in graph.neighbors(target_id, direction="outgoing", edge_kinds=CALL_LIKE_KINDS):
        _take("callee", nid)

    # Tier 2 — direct callers (call-like incoming).
    for nid in graph.neighbors(target_id, direction="incoming", edge_kinds=CALL_LIKE_KINDS):
        _take("caller", nid)

    # Tier 3 — tested-by (incoming `tests` edge).
    for nid in graph.neighbors(target_id, direction="incoming", edge_kinds={"tests"}):
        _take("tested-by", nid)

    # Tier 4 — structural `defines`.
    for nid in graph.neighbors(target_id, direction="incoming", edge_kinds={"defines"}):
        _take("defined-in", nid)
    for nid in graph.neighbors(target_id, direction="outgoing", edge_kinds={"defines"}):
        _take("defines", nid)

    # Tier 5 — transitive call-like reach at depth >= 2.
    if depth >= 2:
        for nid in _bfs(graph, target_id, depth, "outgoing", CALL_LIKE_KINDS):
            _take("callee-2", nid)
        for nid in _bfs(graph, target_id, depth, "incoming", CALL_LIKE_KINDS):
            _take("caller-2", nid)

    # Tier 6 — imports edges.
    for nid in graph.neighbors(target_id, direction="outgoing", edge_kinds={"imports"}):
        _take("imports", nid)
    for nid in graph.neighbors(target_id, direction="incoming", edge_kinds={"imports"}):
        _take("imported-by", nid)

    # Tier 7 — anything else within the search depth (both directions).
    if depth >= 1:
        for nid in _bfs(graph, target_id, depth, "outgoing", edge_kinds=None):
            _take("related", nid)
        for nid in _bfs(graph, target_id, depth, "incoming", edge_kinds=None):
            _take("related", nid)

    ranked: list[tuple[str, GraphNode]] = []
    for role in sorted(buckets, key=lambda r: _ROLE_TIER[r]):
        if role == "target":
            continue
        for node in sorted(buckets[role], key=lambda n: n.id):
            ranked.append((role, node))
    return ranked


def _bfs(
    graph: NeighborsProvider,
    start: int,
    depth: int,
    direction: str,
    edge_kinds: Iterable[str] | None,
) -> set[int]:
    """Local BFS that excludes the start node from the result."""
    allowed = set(edge_kinds) if edge_kinds is not None else None
    visited: set[int] = set()
    queue: deque[tuple[int, int]] = deque([(start, 0)])
    while queue:
        current, dist = queue.popleft()
        if current in visited or dist > depth:
            continue
        if dist > 0:
            visited.add(current)
        for neighbor in graph.neighbors(current, direction=direction, edge_kinds=allowed):
            if neighbor not in visited and neighbor != start:
                queue.append((neighbor, dist + 1))
    return visited


def pack_context(
    target: GraphNode,
    ranked: list[tuple[str, GraphNode]],
    budget: int,
    root_path: Path | str,
    head_lines: int = DEFAULT_HEAD_LINES,
) -> list[dict[str, Any]]:
    """Token-bounded pack: target first, then ranked neighbors in order.

    Each item is rendered in one of three modes — ``full`` (entire symbol
    body), ``head`` (first ``head_lines`` lines), or ``signature-only`` (no
    body). The first mode that fits within the remaining budget wins; if
    none fit, the item is dropped silently.
    """
    enforcer = BudgetEnforcer(max_tokens=budget)
    root = Path(root_path)
    items: list[dict[str, Any]] = []

    _try_add(items, enforcer, target, "target", root, head_lines)
    if not items:
        return items
    for role, node in ranked:
        _try_add(items, enforcer, node, role, root, head_lines)
    return items


def _try_add(
    items: list[dict[str, Any]],
    enforcer: BudgetEnforcer,
    node: GraphNode,
    role: str,
    root: Path,
    head_lines: int,
) -> None:
    """Try `full`, then `head`, then `signature-only` until one fits."""
    full_source = _read_source(node, root, head_lines=None)
    head_source = _read_source(node, root, head_lines=head_lines)

    # Full mode — only if there's actual source AND it fits.
    if full_source and _try_mode(items, enforcer, node, role, full_source, "full"):
        return
    # Head mode — only if the head slice is shorter than full (otherwise pointless).
    if (
        head_source
        and head_source != full_source
        and _try_mode(items, enforcer, node, role, head_source, "head")
    ):
        return
    # Signature-only — text we charge against the budget is signature + docstring.
    sig_text = "\n".join(filter(None, [node.signature, node.docstring]))
    _try_mode(items, enforcer, node, role, "", "signature-only", token_text=sig_text)


def _try_mode(
    items: list[dict[str, Any]],
    enforcer: BudgetEnforcer,
    node: GraphNode,
    role: str,
    source: str,
    mode: str,
    token_text: str | None = None,
) -> bool:
    item: dict[str, Any] = {
        "role": role,
        "symbol": node.name,
        "kind": node.kind,
        "file": node.file_path,
        "lines": (node.line_start, node.line_end),
        "source": source,
        "signature": node.signature,
        "docstring": node.docstring,
        "mode": mode,
    }
    text = token_text if token_text is not None else source
    if enforcer.add(item, text):
        items.append(item)
        return True
    return False


def _read_source(node: GraphNode, root: Path, head_lines: int | None) -> str:
    """Read the source slice for ``node``; empty string when the file is missing."""
    try:
        src_path = root / node.file_path
        lines = src_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    start = max(node.line_start - 1, 0)
    end = node.line_end
    body = lines[start:end]
    if head_lines is not None and len(body) > head_lines:
        body = body[:head_lines]
    return "\n".join(body)
