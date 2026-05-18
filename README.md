# grounded-graph

![version](https://img.shields.io/badge/version-0.4.1-blue)

Graph traversal and context queries over code metadata. `grounded-graph` reads a
[`grounded-index`](https://github.com/oldnordic/grounded-index) SQLite database
and exposes call graphs, impact analysis, test discovery, and token-bounded
context packs for AI coding agents.

Two storage backends:

- **Pure-Python** (`--backend python`) — fast in-memory, no extra dependencies.
- **sqlitegraph** (`--backend sqlitegraph`) — file-backed Rust graph with HNSW
  semantic search and persistent indexes.

## Quick start

```bash
# 1. Index your project (produces .grounded-index.db)
grounded-index index .

# 2. Load the graph and check stats
grounded-graph index --backend python

# 3. Query
grounded-graph callers --symbol my_function
grounded-graph tests-for --symbol CustomerService
grounded-graph neighborhood --symbol my_function --depth 2 --budget 4000
```

## What it does

| Capability | Description |
|------------|-------------|
| **Call graph** | `callers`, `callees`, `impact`, `affected` with kind-filtered traversal |
| **Test mapping** | `tests-for` links tests to the symbols they exercise |
| **Shortest path** | `path --from A --to B` between any two symbols |
| **Context packs** | `neighborhood` returns priority-ranked, token-bounded symbol context |
| **Semantic search** | HNSW-backed similarity search over symbol embeddings (sqlitegraph only) |
| **Multi-kind edges** | Same node pair can carry `call`, `defines`, `imports`, and `tests` edges |

See [MANUAL.md](MANUAL.md) for full CLI documentation and [API.md](API.md) for the
Python API.

## Install

```bash
pip install grounded-graph
```

Requires Python >= 3.10.

## Version

Current version: **0.4.1**
