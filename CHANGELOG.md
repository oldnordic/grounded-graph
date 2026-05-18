# grounded-graph Changelog

## [0.4.1] - 2026-05-18

### Changed
- **Documentation overhaul**: added `API.md` (full Python API reference with code examples) and `MANUAL.md` (complete CLI reference with global options, all subcommands, examples).
- **`pyproject.toml` metadata**: added `[project.urls]` (Homepage, Repository, Bug Tracker, Changelog).
- **`__init__.py` re-exports**: top-level imports for `Graph`, `GraphNode`, `GraphEdge`, `QueryEngine`, `NeighborsProvider`, `Embedder`, `HashEmbedder`, `OllamaEmbedder`, `CALL_LIKE_KINDS`.
- Bumped minimum `grounded-index` dependency to `>=0.5.0` (uses `BudgetEnforcer` introduced in that version).

### Fixed
- Code formatting pass on `query.py`, `sqlitegraph_backend.py`, `test_context_pack.py`, `test_loader.py` (ruff format).
- Removed stray `./main` SQLite database from working tree.

### Notes
- This release prepares grounded-graph for PyPI publication. GitHub CI workflows added (python.yml, validate.yml) matching grounded-index conventions.

## [0.4.0] - 2026-05-16

### Added
- **`grounded_graph.context` module** with `rank_neighbors(graph, target_id, depth)` and `pack_context(target, ranked, budget, root_path, head_lines=20)`.
- **Priority tiers for neighborhood ordering**: target → direct callees → direct callers → tested-by → defined-in/defines → depth-2 call neighbors → imports/imported-by → related. Within each tier, neighbors are sorted by symbol id for stable output.
- **Snippet-mode fallback** in pack_context: each item tries `full` → `head` (first 20 lines) → `signature-only`, in that order, until one fits the remaining budget. New `mode` field on every output item.
- **`NeighborsProvider` Protocol** so both backends share the ranking implementation; `_SqlitegraphNeighborsAdapter` wraps `sqlitegraph.Graph` for the sqlitegraph backend.
- **12 new pytest cases** in `tests/test_context_pack.py` covering priority ordering, stable-by-id within a tier, depth-2 ordering, snippet fallback modes, mode field presence.

### Changed
- **`QueryEngine.neighborhood_context`** and **`SqlitegraphBackend.neighborhood_context`** now delegate to the shared `rank_neighbors` + `pack_context` helpers. Backend parity: both produce the same `(role, mode)` shape for the same input (small loader-level differences in file/`contains` edges remain unchanged).
- **`QueryEngine._role_for`** removed (logic now lives in `context.rank_neighbors`).

### Notes
- The previous `neighborhood_context` interleaved roles in set-iteration order. Output ordering is now deterministic; consumers that relied on the old order will need to update — but reliance was already unsafe.
- File-line dedup (parent/child source overlap) is intentionally not done in this release; will be added if benchmarks show real duplication noise.

## [0.3.0] - 2026-05-16

### Changed
- **`SqlitegraphBackend._load_from_index` uses bulk-insert** (`add_nodes_bulk` / `add_edges_bulk` from sqlitegraph 0.3.0). Three batched node inserts (symbols, files, modules) followed by a single batched edge insert that carries references, defines, imports, and tests edges together.

### Benchmark (`benchmarks/RESULTS.md`)
- 14008 symbols / 6640 sg edges on the `sqlitegraph` repo:
  - **`sqlitegraph build`: ~750 ms → ~190 ms** (3.9× faster) despite a **17× larger edge set** (imports/defines/tests added in 0.2.0).
  - Pure-Python build moved from 93 ms to 117 ms (same edge growth).
  - Query latency unchanged; the gap there is dict-lookup vs SQL round-trip, not FFI.

### Dependencies
- `sqlitegraph>=0.3.0` (was 0.2.0) — required for `add_nodes_bulk` / `add_edges_bulk`.
- `grounded-index>=0.2.0` (unchanged).

## [0.2.0] - 2026-05-16

### Added
- **Multi-kind edges on the pure-Python `Graph`** — `_edge_kinds` is now `dict[(from, to), set[str]]`, so the same node pair can carry distinct relationships (e.g. a `call` edge alongside a `tests` edge) without clobbering. New helpers `edge_kinds(from_id, to_id)`, `all_nodes()`, `all_edges()`. `neighbors(node_id, direction, edge_kinds=None)` accepts an optional kind filter; `bfs(..., edge_kinds=None)` propagates the filter through traversal.
- **`CALL_LIKE_KINDS`** constant (`{call, method_call, macro, constructor, construct}`) defining which edges count as call-style for `callers`/`callees`/`impact`/`affected`.
- **`imports` edges** — `gi_imports` rows are loaded as edges from file nodes to new `module` nodes (kind `"module"`). Module nodes use negative IDs offset from file nodes.
- **`defines` edges** — `gi_symbols.parent_id` is loaded as `parent_symbol → child_symbol` edges.
- **`tests` edges** — Built at load time from grounded-index 0.2.0's `is_test` symbols by (a) treating call-like references from test symbols to production symbols as `tests` edges and (b) name-convention matching (`test_foo`/`testsFoo`/`FooTest`/`FooSpec` → `foo`).
- **`QueryEngine.tests_for(name)`** — Returns symbols whose `tests` edges point at the named symbol.
- **`grounded-graph tests-for --symbol X`** CLI subcommand wired up across both backends.
- **`SqlitegraphBackend`** parity for all of the above — multi-kind edges via sqlitegraph 0.2.0's `edge_type=` and `edge_types=` kwargs; `callers`/`callees`/`impact`/`affected` iterate the call-like kind set; `tests_for` uses the typed `tests` edge directly.

### Changed
- **`callers`/`callees`/`impact`/`affected` now filter to call-like edge kinds.** `imports`, `defines`, and `tests` edges no longer pollute call-graph queries. Pure-Python `Graph.impact` and `Graph.affected` traverse with `edge_kinds=CALL_LIKE_KINDS`; `SqlitegraphBackend.impact`/`affected` iterate `bfs(..., edge_types=[kind])` per call-like type.
- **`Graph.stats()`** counts edges across all kinds, not unique `(from, to)` pairs.
- **`QueryEngine.neighborhood_context`** assigns roles by edge kind: `callee`/`caller`/`tested-by`/`tests`/`imports`/`imported-by`/`defined-in`/`defines`/`related`.

### Dependencies
- `sqlitegraph>=0.2.0` (was 0.1.1) — uses the new `bfs(edge_types=...)`, `shortest_path(edge_types=...)`, `k_hop(edge_types=...)` kwargs introduced in 0.2.0 for kind-filtered traversal.
- `grounded-index>=0.2.0` (no upper) — reads the new `gi_symbols.is_test` column when available; falls back gracefully when an older v1 DB is used (`is_test` defaults to `False`, no `tests` edges are emitted).

### Tests
- 4 pure-Python `Graph` tests (multi-kind edges don't clobber, kind-filtered `neighbors`, unfiltered `neighbors` includes all kinds, kind-filtered `bfs`).
- 4 `QueryEngine` tests (`callers`/`callees` exclude non-call edges, `tests_for` returns test callers, empty for untested).
- 3 loader tests (imports edges from `gi_imports`, defines edges from hand-built `parent_id`, tests edges from a Rust fixture with `#[test]`).
- 1 CLI test for `tests-for --symbol`.

## [0.1.0] - 2026-05-15

### Added
- `sqlitegraph` (Python bindings) as a dependency (`>=0.1.1`) for the
  `sqlitegraph` backend.
- `SqlitegraphBackend` class providing graph storage and queries backed by
  sqlitegraph (Rust core via PyO3):
  - Symbol loading from grounded-index DBs.
  - Call edge extraction.
  - HNSW semantic index creation with embedders (hash-based + Ollama).
  - Persistence across sessions via `hnsw_index_persistent`.
- CLI `--backend sqlitegraph` flag for file-backed graph storage.
- `semantic` CLI command for HNSW-backed semantic symbol search.
- 62 pytest tests covering both pure-Python and sqlitegraph backends,
  including semantic search persistence tests.

### Fixed
- Bumped `sqlitegraph` dependency to `>=0.1.1` to include the HNSW persistence
  fix (`create_hnsw_index` now calls `hnsw_index_persistent`).
