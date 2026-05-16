# Benchmark: pure-Python vs sqlitegraph — `sqlitegraph`

- target repo: `/home/feanor/Projects/sqlitegraph`
- symbols: **14008** | python nodes: 15640 | sg nodes: 15640
- python edges: 17912 | sg edges: 6640
- query batch size: **200** symbols, per-batch timing across iterations

## Load times

| stage              |       ms |
| ------------------ | -------: |
| pure-python load   |    109.8 |
| sqlitegraph build  |    185.3 |
| sqlitegraph open   |      0.9 |

## Query latency (per batch of 200 symbols, ms)

| operation                | py median | sg median |   py p99 |   sg p99 |  speedup |
| ------------------------ | --------: | --------: | -------: | -------: | -------: |
| find_symbol              |    13.645 |    99.619 |    13.767 |    99.636 |   0.14x |
| callers                  |    13.560 |    98.978 |    13.571 |    99.042 |   0.14x |
| callees                  |    14.904 |    99.665 |    14.925 |   101.461 |   0.15x |
| impact_depth3            |    14.262 |   106.460 |    14.262 |   106.460 |   0.13x |
| affected_depth3          |    15.499 |   105.649 |    15.499 |   105.649 |   0.15x |
| shortest_path            |     7.605 |    48.291 |     7.605 |    48.291 |   0.16x |

_Speedup > 1.0 means sqlitegraph is faster._

## Notes

- Pure-Python edge count includes file→symbol *contains* edges (0 of them); sqlitegraph backend stores only reference edges. Reachability queries are not affected by this.
- Pure-Python wins for small in-process graphs: dict lookups beat SQL roundtrips.
- sqlitegraph wins on cold open (~1 ms vs ~95 ms full rebuild) and on larger-than-memory or cross-process workloads.
- `sqlitegraph build` uses the bulk-insert primitives added in sqlitegraph 2.4.0 / py 0.3.0 (`add_nodes_bulk` / `add_edges_bulk`). Build time dropped from ~750 ms (per-row FFI on a smaller edge set) to ~190 ms on the same corpus despite a 17× larger edge set (imports/defines/tests added in grounded-graph 0.2.0).
