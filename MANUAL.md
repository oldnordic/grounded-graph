# grounded-graph Manual

Complete reference for the `grounded-graph` CLI.

## Global options

These options apply to every subcommand:

| Option | Default | Description |
|--------|---------|-------------|
| `--db`, `-d` | `.grounded-index.db` | Path to the grounded-index database |
| `--root`, `-r` | `.` | Repository root path |
| `--output`, `-o` | `human` | Output format: `human`, `json`, `markdown` |
| `--backend` | `python` | Storage backend: `python` or `sqlitegraph` |
| `--sg-db` | (none) | Sqlitegraph DB path (required when `--backend sqlitegraph`) |
| `--embedder` | `none` | Embedder for HNSW: `none`, `hash`, `ollama` |
| `--embedder-dim` | `128` | Dimension for the hash embedder |

## Commands

### `index`

Build or load the graph.

```bash
# Pure-Python backend — loads into memory
grounded-graph index --backend python

# Sqlitegraph backend — builds a persistent graph file
grounded-graph index --backend sqlitegraph --sg-db graph.sg --embedder hash
```

With `--backend sqlitegraph`, this creates (or overwrites) the sqlitegraph DB
and optionally builds an HNSW semantic index using the chosen embedder. The
embedder config is stored in a `.embedder.json` sidecar file next to the DB.

### `status`

Show graph statistics.

```bash
grounded-graph status
# Output: 14008 nodes, 6640 edges
```

### `find-symbol`

Find a symbol node by exact name.

```bash
grounded-graph find-symbol --name CustomerService.updateCustomer
```

### `callers`

Symbols that call the target symbol (call-like edges only: `call`,
`method_call`, `macro`, `constructor`, `construct`).

```bash
grounded-graph callers --symbol my_function
```

### `callees`

Symbols that the target symbol calls (call-like edges only).

```bash
grounded-graph callees --symbol my_function
```

### `impact`

Forward reachable symbols — what the target affects.

```bash
grounded-graph impact --symbol my_function --depth 3
```

| Option | Default | Description |
|--------|---------|-------------|
| `--depth` | `3` | Maximum traversal depth |

### `affected`

Backward reachable symbols — what affects the target.

```bash
grounded-graph affected --symbol my_function --depth 3
```

### `path`

Shortest path between two symbols.

```bash
grounded-graph path --from src_fn --to dst_fn
```

### `neighborhood`

N-hop context pack — priority-ranked, token-bounded symbol context.

```bash
grounded-graph neighborhood --symbol my_function --depth 2 --budget 4000
```

| Option | Default | Description |
|--------|---------|-------------|
| `--depth` | `2` | Hop depth for neighborhood search |
| `--budget` | `4000` | Token budget for the context pack |

The output is ordered by priority tier:

1. Target symbol
2. Direct callees
3. Direct callers
4. Tested-by (tests that call this symbol)
5. Defined-in / defines (parent/child structural edges)
6. Transitive call neighbors at depth >= 2
7. Imports / imported-by
8. Everything else within search depth

Each item includes a `mode` field: `full` (entire source), `head` (first 20
lines), or `signature-only` (no body), depending on what fits the budget.

### `tests-for`

Find tests that exercise the named symbol.

```bash
grounded-graph tests-for --symbol CustomerService
```

Tests are discovered via:
- `tests` edges from test symbols (from `grounded-index` schema v2 `is_test`)
- Name-convention matching (`test_foo`, `testsFoo`, `FooTest`, `FooSpec` → `foo`)

### `semantic`

HNSW-backed semantic symbol search. Requires `--backend sqlitegraph` with an
index built using `--embedder`.

```bash
# Build with embedder
grounded-graph index --backend sqlitegraph --sg-db graph.sg --embedder hash

# Search
grounded-graph semantic --query "customer authentication" -k 10 --backend sqlitegraph --sg-db graph.sg
```

| Option | Default | Description |
|--------|---------|-------------|
| `--query` | (required) | Free-text query |
| `-k` | `10` | Number of nearest neighbors |

## Output formats

### `human`

Plain text, one item per line. Default for interactive use.

### `json`

Machine-readable JSON array. Each item includes all fields (`role`, `symbol`,
`kind`, `file`, `lines`, `source`, `signature`, `docstring`, `mode`).

### `markdown`

Markdown-formatted code blocks with symbol headers. Good for pasting into LLM
prompts.

## Typical workflows

### Pure-Python backend (fast, ephemeral)

```bash
grounded-index index .
grounded-graph callers --symbol process_order
grounded-graph tests-for --symbol process_order
grounded-graph neighborhood --symbol process_order --budget 6000
```

### Sqlitegraph backend (persistent, semantic search)

```bash
grounded-index index .
grounded-graph index --backend sqlitegraph --sg-db graph.sg --embedder hash
grounded-graph semantic --query "order validation" -k 5 --backend sqlitegraph --sg-db graph.sg
grounded-graph callers --symbol validate_order --backend sqlitegraph --sg-db graph.sg
```
