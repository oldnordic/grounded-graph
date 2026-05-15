# Sub-project #2 — sqlitegraph bulk-insert primitive

**Status:** Approved (5-section design + publish-on-tag plan).
**Date:** 2026-05-16.
**Scope:** Two repos (sqlitegraph, grounded-graph), versions bumped to 2.4.0 / 0.3.0 / 0.3.0.

## Goal

Close the 8× gap between pure-Python and sqlitegraph backend build times (~750 ms vs ~93 ms on a 14k-symbol corpus) by batching inserts in a single transaction across a single FFI call.

## Architecture

```
sqlitegraph-py:        Graph.add_nodes_bulk(items: list[dict]) -> list[int]
                       Graph.add_edges_bulk(items: list[dict]) -> list[int]

sqlitegraph-core:      GraphBackend::insert_nodes_bulk(&[NodeSpec]) -> Vec<i64>
                       GraphBackend::insert_edges_bulk(&[EdgeSpec]) -> Vec<i64>
                       (trait defaults loop single-insert; backends override)

SqliteGraphBackend:    BEGIN ; prepare_cached INSERT ; loop ; COMMIT
V3Backend:             WriteBatchGuard.{insert_node,insert_edge}+ ; commit()
```

## Phase 0 evidence

Magellan `sqlitegraph/.magellan/sqlitegraph.db`:
- `GraphBackend::insert_node` at `backend.rs:117`; `SqliteGraphBackend::insert_node` at `backend/sqlite/impl_.rs:246`; `V3Backend::insert_node` at `backend/native/v3/backend.rs:925`.
- `SqliteGraph::insert_entity` at `graph/entity_ops.rs:13` — single `execute()` per row, no transaction batching.
- `WriteBatchGuard::insert_node` at `v3/backend.rs:117` — already exists in V3, not wired through `GraphBackend`.
- No existing `insert_*_bulk` symbols (verified via `magellan find`).
- `graph/CLAUDE.md`: bulk ops "use transactions — wrap in BEGIN/COMMIT" — convention documented, not implemented.

Benchmark (`grounded-graph/benchmarks/RESULTS.md`):
- 14008 symbols + 388 edges → 750 ms SQLite backend build, 93 ms pure-Python.
- Per-insert: ~52 µs (mostly FFI + implicit per-statement transaction overhead).

## Design decisions

1. **Trait defaults loop single-insert** so third-party backends remain source-compatible at 2.3 → 2.4 with no required changes.
2. **All-or-nothing transaction**. On any error: `ROLLBACK`, return error. No partial success.
3. **Publisher events fire per-row after commit** — keeps observer semantics; no new batched-event type.
4. **Return `Vec<i64>` in input order** so callers can build edge specs from the returned node IDs by zip.
5. **No multi-row `VALUES (?, ?), (?, ?)` SQL** — getting N rowids back with order guarantees needs extra plumbing; per-row INSERT inside a transaction with `prepare_cached` is fast enough.
6. **Python binding takes `list[dict]`** to match today's kwargs-style `add_node`/`add_edge`.

## Versioning

- `sqlitegraph-core` 2.3.0 → **2.4.0**
- `sqlitegraph-py`   0.2.0 → **0.3.0**
- `grounded-graph`   0.2.0 → **0.3.0** (pins `sqlitegraph>=0.3.0`)

## Release flow

1. Local: `cargo fmt --all --check`, `RUSTFLAGS="-D warnings" cargo check --lib --bins`, `cargo test -p sqlitegraph --lib -- --test-threads=1`, `pytest`.
2. Push feature branch, open PR, watch Validate/Python/Wheels (rebase-merge to main on green).
3. After main CI green: tag `v2.4.0` + `py-v0.3.0`, push tags.
4. `cargo publish -p sqlitegraph` (Rust crate to crates.io). Note: v2.3.0 was tagged but never published to crates.io — we publish 2.4.0 directly; crates.io accepts the version gap.
5. `py-v0.3.0` tag triggers existing wheels CI → PyPI publish.
6. In grounded-graph: bump `sqlitegraph>=0.3.0`, refactor `_load_from_index` to use bulk API, re-run benchmark, update `benchmarks/RESULTS.md`, bump to 0.3.0, commit.

## Success criterion

`bench_backends.py` reports `sqlitegraph build` ≤ ~150 ms on the same 14008-symbol corpus (≥ 5× speedup from 750 ms). If not, treat the residual gap as the next thing to investigate rather than ship and forget.
