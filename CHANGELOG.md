# grounded-graph Changelog

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
