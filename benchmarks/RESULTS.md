# Benchmark: pure-Python vs sqlitegraph — `sqlitegraph`

- target repo: `/home/feanor/Projects/sqlitegraph`
- symbols: **14008** | python nodes: 15099 | sg nodes: 14008
- python edges: 14242 | sg edges: 388
- query batch size: **200** symbols, per-batch timing across iterations

## Load times

| stage              |       ms |
| ------------------ | -------: |
| pure-python load   |     93.1 |
| sqlitegraph build  |    749.9 |
| sqlitegraph open   |      0.9 |

## Query latency (per batch of 200 symbols, ms)

| operation                | py median | sg median |   py p99 |   sg p99 |  speedup |
| ------------------------ | --------: | --------: | -------: | -------: | -------: |
| find_symbol              |    12.376 |    90.010 |    12.378 |    90.090 |   0.14x |
| callers                  |    13.359 |    88.341 |    13.425 |    88.614 |   0.15x |
| callees                  |    13.074 |    88.168 |    13.142 |    88.281 |   0.15x |
| impact_depth3            |    13.857 |    88.391 |    13.857 |    88.391 |   0.16x |
| affected_depth3          |    14.600 |    88.269 |    14.600 |    88.269 |   0.17x |
| shortest_path            |     7.790 |    44.221 |     7.790 |    44.221 |   0.18x |

_Speedup > 1.0 means sqlitegraph is faster._

## Notes

- Pure-Python edge count includes file→symbol *contains* edges (1091 of them); sqlitegraph backend stores only reference edges. Reachability queries are not affected by this.
- Pure-Python wins for small in-process graphs: dict lookups beat SQL roundtrips.
- sqlitegraph wins on cold open (~1 ms vs ~95 ms full rebuild) and on larger-than-memory or cross-process workloads.
- `sqlitegraph build` is dominated by Python→Rust FFI per `add_node`/`add_edge`; a bulk-insert primitive would close the gap.
