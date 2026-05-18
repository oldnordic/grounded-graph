# grounded-graph API Reference

## Overview

`grounded-graph` provides two query backends with the same interface:

- `QueryEngine` — pure-Python in-memory graph
- `SqlitegraphBackend` — file-backed Rust graph via `sqlitegraph`

Both support the same query methods: `find_symbol`, `callers`, `callees`,
`impact`, `affected`, `path`, `tests_for`, `neighborhood_context`, `stats`.

The `sqlitegraph` backend additionally supports `semantic_search` via HNSW
indexes.

## Data types

### `GraphNode`

```python
@dataclass(frozen=True)
class GraphNode:
    id: int
    kind: str          # e.g. "function", "class", "method"
    name: str
    file_path: str
    line_start: int = 0
    line_end: int = 0
    signature: str | None = None
    docstring: str | None = None
    is_public: bool = True
```

### `GraphEdge`

```python
@dataclass(frozen=True)
class GraphEdge:
    from_id: int
    to_id: int
    kind: str          # e.g. "call", "method_call", "imports", "defines", "tests"
    line: int = 0
```

### `Graph`

The in-memory graph. Used directly by `QueryEngine`.

```python
from grounded_graph.graph import Graph, GraphNode

g = Graph()
g.add_node(GraphNode(id=1, kind="function", name="foo", file_path="src.py"))
g.add_node(GraphNode(id=2, kind="function", name="bar", file_path="src.py"))
g.add_edge(1, 2, "call")

# Kind-filtered neighbors
g.neighbors(1, direction="outgoing", edge_kinds={"call"})     # {2}
g.neighbors(1, direction="outgoing", edge_kinds={"imports"})   # set()

# BFS with kind filter
g.bfs(1, depth=3, direction="outgoing", edge_kinds={"call"})

# Shortest path
g.shortest_path(1, 2)  # [1, 2]

# Impact / affected (call-like edges only)
g.impact(1, depth=3)     # forward reachable
g.affected(1, depth=3)   # backward reachable
```

## QueryEngine (pure-Python)

```python
from grounded_graph.loader import load_from_index
from grounded_graph.query import QueryEngine
from pathlib import Path

db_path = Path(".grounded-index.db")
graph = load_from_index(db_path)
engine = QueryEngine(graph, root_path=".")

# Symbol lookup
node = engine.find_symbol("my_function")

# Call graph
callers = engine.callers("my_function")
callees = engine.callees("my_function")

# Impact analysis
impacted = engine.impact("my_function", depth=3)
affecting = engine.affected("my_function", depth=3)

# Path between symbols
path = engine.path("src_fn", "dst_fn")

# Tests
 tests = engine.tests_for("my_function")

# Token-bounded context pack
items = engine.neighborhood_context("my_function", depth=2, budget=4000)
# Each item: dict with keys:
#   role, symbol, kind, file, lines, source, signature, docstring, mode

# Stats
print(engine.stats())  # {"nodes": 1000, "edges": 5000}
```

## SqlitegraphBackend

```python
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend
from grounded_graph.embedder import HashEmbedder
from pathlib import Path

# Build from scratch
db_path = Path(".grounded-index.db")
sg_db = Path("graph.sg")

backend = SqlitegraphBackend.build(
    db_path,
    sg_db_path=sg_db,
    root_path=".",
    embedder=HashEmbedder(dimension=128),
)

# Open existing
backend = SqlitegraphBackend.open(sg_db, root_path=".")

# Same query interface as QueryEngine
callers = backend.callers("my_function")

# Semantic search (requires embedder at build time)
if backend.has_semantic_index():
    hits = backend.semantic_search("order validation", k=10)
    for node, distance in hits:
        print(f"{node.name}: {distance:.3f}")
```

## Context pack builder

The `context` module provides the ranking and packing logic used by both
backends.

```python
from grounded_graph.context import rank_neighbors, pack_context

# Rank neighbors by priority tier
ranked = rank_neighbors(graph, target_id=node.id, depth=2)
# Returns: [(role, GraphNode), ...] ordered by priority

# Pack into token-bounded context
items = pack_context(
    target=node,
    ranked=ranked,
    budget=4000,
    root_path=".",
    head_lines=20,
)
```

### Priority tiers (from highest to lowest)

| Role | Description |
|------|-------------|
| `target` | The queried symbol itself |
| `callee` | Direct callees (call-like outgoing edges) |
| `caller` | Direct callers (call-like incoming edges) |
| `tested-by` | Tests that call this symbol |
| `defined-in` | Parent symbol (structural containment) |
| `defines` | Child symbols (structural containment) |
| `callee-2` | Transitive callees at depth >= 2 |
| `caller-2` | Transitive callers at depth >= 2 |
| `imports` | Imported modules |
| `imported-by` | Files that import this module |
| `related` | Everything else within search depth |

### Snippet modes

Each item in the packed context includes a `mode` field:

| Mode | Description |
|------|-------------|
| `full` | Complete symbol body |
| `head` | First N lines (default 20) |
| `signature-only` | Signature + docstring only, no body |

Items are tried in `full` → `head` → `signature-only` order until one fits the
remaining budget. Items that don't fit even in `signature-only` mode are dropped.

## Embedders

### `HashEmbedder`

Deterministic hash-based embeddings. Fast, offline, no model calls.

```python
from grounded_graph.embedder import HashEmbedder

emb = HashEmbedder(dimension=128)
vectors = emb.embed(["def foo(): pass", "class Bar:"])
```

### `OllamaEmbedder`

Embeddings via a local Ollama server.

```python
from grounded_graph.embedder import OllamaEmbedder

emb = OllamaEmbedder()
vectors = emb.embed(["def foo(): pass"])
```

## Edge kinds

`CALL_LIKE_KINDS` defines which edge types are followed for call-graph queries:

```python
from grounded_graph.graph import CALL_LIKE_KINDS

# {"call", "method_call", "macro", "constructor", "construct"}
```

Other kinds (`imports`, `defines`, `tests`) are structural/test relationships
and do not participate in call-graph traversal.
