# Sub-project #3 — Better context packs

**Status:** Approved.
**Date:** 2026-05-16.
**Scope:** grounded-graph only. Version: 0.3.0 → 0.4.0.

## Goal

Make `neighborhood_context` deterministic, priority-aware, and budget-friendlier so AI consumers get the most-useful evidence first instead of a set-iteration mash-up.

## Architecture

New shared helper `grounded_graph/context.py`:

```python
def rank_neighbors(graph, target_id, depth) -> list[tuple[str, GraphNode]]:
    """Ranked (role, node) pairs ordered by (priority_tier, symbol_id)."""

def pack_context(target, ranked, budget, root_path) -> list[dict]:
    """Fill budget with full -> head -> signature-only fallback per item."""
```

Both `QueryEngine.neighborhood_context` and `SqlitegraphBackend.neighborhood_context` delegate to these — convergent behavior, easier to test.

## Priority tiers

| tier | role | what |
|---:|---|---|
| 0 | `target` | the queried symbol |
| 1 | `callee` | X -> Y, call-like, depth 1 |
| 2 | `caller` | Z -> X, call-like, depth 1 |
| 3 | `tested-by` | T -> X, `tests` edge |
| 4 | `defined-in` / `defines` | `defines` edge, depth 1 |
| 5 | `callee-2` / `caller-2` | call-like, depth 2 |
| 6 | `imports` / `imported-by` | `imports` edge |
| 7 | `related` | anything else inside `depth` hops |

Within a tier: sort by `symbol_id` for stable output.

## Snippet selection

Per item, attempt these modes in order; stop at the first that fits:
1. **`full`** — `lines[line_start-1:line_end]`
2. **`head`** — first 20 lines (configurable `head_lines`)
3. **`signature-only`** — signature + docstring, no source

New output field `mode: "full" | "head" | "signature-only"`. Existing fields unchanged.

## Out of scope (v1)

- **File-line dedup** (parent/child overlap suppression) — defer until benchmarks show real duplication noise.
- **Multi-pass packing** (signatures first for everyone, then bodies) — Approach B from brainstorming. Defer; v1 keeps it linear.

## Versioning

`grounded-graph` 0.3.0 -> **0.4.0** (additive `mode` field; semantic shift in ordering is observable but consumers couldn't rely on set iteration order before).

## Success criteria

- Backend parity: both backends produce the same output for the same input.
- Tests cover: priority ordering, snippet fallback, stable ordering by symbol id, role discrimination on multi-kind edges.
- All existing tests stay green.
