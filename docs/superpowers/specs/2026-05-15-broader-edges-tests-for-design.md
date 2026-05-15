# Sub-project #1 — Broader edges + tests-for + sqlitegraph kind-aware traversal

**Status:** Approved (Section 1 + Section 2)
**Date:** 2026-05-15
**Scope:** Three repos (sqlitegraph, grounded-index, grounded-graph), three phases.

## Goal

Add the relationship vocabulary the vision calls for, expose a working `tests-for` query, and close the upstream gap that prevents kind-filtered graph traversal.

## Architecture Overview

Work is naturally phased; each downstream phase depends on the previous.

### Phase 1 — `sqlitegraph` upstream patch + release

Add kind-filtered variants of `bfs` and `shortest_path` to mirror the existing
`k_hop_filtered`, then expose the new surface (plus the already-supported
`k_hop` filter) through the Python binding. No breakage of existing APIs.

**Changes in `sqlitegraph-core`:**
- `src/bfs.rs`: add `bfs_neighbors_filtered(graph, start, max_depth, allowed_edge_types, direction)` and `shortest_path_filtered(graph, start, end, allowed_edge_types)`. Empty `allowed_edge_types` = no filter (parity with `k_hop_filtered`).
- `src/backend.rs` (`GraphBackend` trait): add `bfs_filtered` and `shortest_path_filtered` trait methods alongside the existing `k_hop_filtered`; add corresponding `&B` blanket impls.
- `src/backend/native/v3/backend.rs` (`V3Backend`): implement both, delegating to the `bfs.rs` free functions.
- `src/backend/sqlite/impl_.rs` (`SqliteGraphBackend`): same — delegate to the `bfs.rs` free functions.
- `src/query_cache.rs`: add `get_bfs_filtered`/`put_bfs_filtered` and `get_shortest_path_filtered`/`put_shortest_path_filtered` only if cache feeds the new public paths (verify via magellan before adding).

**Tests:** Rust tests cover (a) edge_types restricts traversal, (b) empty `allowed_edge_types` = no filter, (c) `Incoming` direction works, (d) unreachable target returns `None` for `shortest_path_filtered`.

**Changes in `sqlitegraph-py` (`src/lib.rs`):**
- Extend existing `bfs(start, depth)` → `bfs(start, depth, edge_types=None, direction=None)`. Dispatch to `backend.bfs(...)` when both are `None`, otherwise to `bfs_filtered`. Backwards-compatible.
- Extend `shortest_path(start, end)` → `shortest_path(start, end, edge_types=None)`.
- Extend `k_hop(start, depth, direction=None)` → add `edge_types=None`; dispatch to `k_hop_filtered` when provided.

**Python tests:** one per new param — `bfs(edge_types=[...])`, `bfs(direction="incoming")`, `shortest_path(edge_types=[...])`, `k_hop(edge_types=[...])`.

**Versioning (SemVer minor — new public surface, no breakage):**
- `sqlitegraph-core` 2.2.5 → **2.3.0**
- `sqlitegraph-py` 0.1.1 → **0.2.0**

**Release flow:**
1. Local: `cargo fmt --check && cargo clippy --workspace -- -D warnings && cargo test --workspace`; Python: `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin develop --release && pytest`.
2. Commit, push. **Watch CI**: `gh run list --repo oldnordic/sqlitegraph --branch <branch> --limit 1`; `gh run view <id> --log-failed` on failure. Self-heal per `sqlitegraph/CLAUDE.md` until green.
3. Tag and publish core to crates.io (existing CI flow handles it).
4. Build and publish wheels via existing PyPI workflow.

### Phase 2 — `grounded-index` schema v2 + test detection (sketch)

- Schema migration v2: `gi_symbols.is_test INTEGER NOT NULL DEFAULT 0`.
- Parser detection at parse time:
  - **Rust:** `#[test]`, `#[cfg(test)]` (parent mod), `#[tokio::test]`, `#[async_std::test]`, `#[rstest]` attributes on functions. Files under `tests/` mark all functions as tests.
  - **TS/JS:** function/arrow expressions inside `describe`/`it`/`test`/`it.each`/`test.each` (and `.skip`/`.only`); filename heuristics `*.test.{ts,tsx,js,jsx}`, `*.spec.{ts,tsx,js,jsx}`.
- Bump `grounded-index` 0.1.0 → 0.2.0. Update CHANGELOG.

### Phase 3 — `grounded-graph` multi-kind edges + `tests-for` (sketch)

- Pure-Python `Graph`: `_edge_kinds: dict[(from,to), set[str]]` (multi-kind); `neighbors`/`bfs` accept optional `edge_kinds: set[str] | None`.
- sqlitegraph backend: use new `bfs_filtered`/`shortest_path_filtered`/`neighbors(edge_type=...)` from Phase 1.
- Loader additions:
  - `imports` edges: file→module-node (new node kind `"module"`).
  - `defines` edges: parent_symbol→child_symbol from `gi_symbols.parent_id`.
  - `tests` edges: from each `is_test=1` symbol to every symbol it references + every symbol whose name matches the test's stripped-prefix name (e.g., `test_foo` → `foo`, `FooTest` → `Foo`).
- Queries: `callers`/`callees`/`impact`/`affected` filter to `{call, method_call, macro, constructor}`. New `tests_for(symbol)` method. New `tests-for --symbol X` CLI command.
- `neighborhood_context`: use edge kind to assign role labels (`callee`/`caller`/`imports`/`tested-by`/`defined-in`/`related`).
- Bump `grounded-graph` 0.1.0 → 0.2.0. Update CHANGELOG.

## Cross-phase Invariants

- Backend parity: pure-Python and sqlitegraph backends behave identically for all queries.
- Backward compatibility: existing CLI commands keep current behavior except for the semantic fix of kind-filtering call-like queries.
- Test detection runs at parse time only; grounded-graph never re-reads source for test classification.

## Magellan Evidence (Phase 1)

Queried `/home/feanor/Projects/sqlitegraph/.magellan/sqlitegraph.db`:

- `bfs_neighbors` at `sqlitegraph-core/src/bfs.rs:7` — 2 internal callers (`SqliteGraphBackend::bfs` at `backend/sqlite/impl_.rs:342`; CLI `run_bfs` at `sqlitegraph-cli/src/main.rs:138`). Small blast radius → safe to leave unchanged.
- `k_hop_filtered`: 9 symbols (trait method `backend.rs:245`, native impl `backend/native/v3/backend.rs:1226`, sqlite impl `backend/sqlite/impl_.rs:399`, free function `multi_hop.rs:60`, `&B` blanket `backend.rs:598`, query_cache `get_k_hop_filtered:287` + `put_k_hop_filtered:322` + `test_k_hop_filtered_cache:516`). Established template.
- `bfs_filtered`, `shortest_path_filtered`: not found anywhere → green-field addition.

## Phase Sequencing

Phase 1 ships and is published before Phase 2 starts (grounded-graph needs the new Python API).
Phase 2 ships before Phase 3 starts (grounded-graph reads `is_test` rows produced by grounded-index).
