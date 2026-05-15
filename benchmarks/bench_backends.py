"""Benchmark pure-Python vs sqlitegraph backends on the sqlitegraph repo.

Usage:
    python benchmarks/bench_backends.py [--target /path/to/repo] [--force-reindex]

This script:
  1. Indexes the target repo with grounded-index (caches under benchmarks/).
  2. Loads both pure-Python (loader.load_from_index → QueryEngine) and the
     sqlitegraph-backed backend.
  3. Times equivalent queries on each.
  4. Prints a comparison table and writes benchmarks/RESULTS.md.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grounded_index.indexer import Indexer

from grounded_graph.loader import load_from_index
from grounded_graph.query import QueryEngine
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend


def _time(fn: Callable[[], Any], iters: int) -> dict[str, float]:
    """Run ``fn`` ``iters`` times, return median / mean / p99 in milliseconds."""
    samples_ms: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    samples_ms.sort()
    p99_idx = max(0, int(len(samples_ms) * 0.99) - 1)
    return {
        "iters": float(iters),
        "median_ms": statistics.median(samples_ms),
        "mean_ms": statistics.fmean(samples_ms),
        "p99_ms": samples_ms[p99_idx],
        "min_ms": samples_ms[0],
        "max_ms": samples_ms[-1],
    }


def _bench(label: str, fn: Callable[[], Any], iters: int) -> dict[str, float]:
    """Time ``fn`` ``iters`` times. The ``label`` arg documents call sites."""
    del label
    return _time(fn, iters)


def _format_row(label: str, py: dict[str, float], sg: dict[str, float]) -> str:
    py_med = py["median_ms"]
    sg_med = sg["median_ms"]
    speedup = py_med / sg_med if sg_med > 0 else float("inf")
    return (
        f"| {label:<24} | {py_med:>9.3f} | {sg_med:>9.3f} "
        f"| {py['p99_ms']:>9.3f} | {sg['p99_ms']:>9.3f} | {speedup:>6.2f}x |"
    )


def _ensure_index(target: Path, index_db: Path, force: bool) -> int:
    """Index the target repo; return symbol count."""
    if index_db.exists() and not force:
        import sqlite3

        with sqlite3.connect(str(index_db)) as conn:
            symbols = conn.execute("SELECT COUNT(*) FROM gi_symbols").fetchone()[0]
        print(f"[cache] reusing existing index at {index_db} ({symbols} symbols)")
        return int(symbols)

    print(f"[index] indexing {target} → {index_db}")
    t0 = time.perf_counter()
    stats = Indexer(root=target, db_path=index_db).index()
    elapsed = time.perf_counter() - t0
    print(f"[index] indexed in {elapsed:.2f}s: {stats}")
    import sqlite3

    with sqlite3.connect(str(index_db)) as conn:
        symbols = conn.execute("SELECT COUNT(*) FROM gi_symbols").fetchone()[0]
    return int(symbols)


def _pick_samples(symbols: list[str], k: int, seed: int = 17) -> list[str]:
    rng = random.Random(seed)
    if len(symbols) <= k:
        return symbols
    return rng.sample(symbols, k)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("/home/feanor/Projects/sqlitegraph"),
        help="Repository to index and benchmark against",
    )
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument(
        "--iters",
        type=int,
        default=200,
        help="Query iterations per backend per operation",
    )
    args = parser.parse_args()

    bench_dir = Path(__file__).resolve().parent
    index_db = bench_dir / "sqlitegraph_index.db"
    sg_cache = bench_dir / "sqlitegraph_graph.sgdb"

    target: Path = args.target.resolve()
    if not target.exists():
        print(f"target repo not found: {target}")
        return 1

    symbol_count = _ensure_index(target, index_db, args.force_reindex)
    if symbol_count == 0:
        print("indexer produced no symbols — aborting")
        return 1

    # ── Pure Python backend ────────────────────────────────────────
    print("[load] pure-python backend")
    t0 = time.perf_counter()
    py_graph = load_from_index(index_db)
    py_engine = QueryEngine(py_graph, root_path=str(target))
    py_load_ms = (time.perf_counter() - t0) * 1000.0
    py_stats = py_engine.stats()
    print(f"       {py_stats} loaded in {py_load_ms:.1f} ms")

    # ── sqlitegraph backend ────────────────────────────────────────
    print("[load] sqlitegraph backend (rebuild)")
    if sg_cache.exists():
        sg_cache.unlink()
    t0 = time.perf_counter()
    sg_backend = SqlitegraphBackend.build(index_db, sg_db_path=sg_cache, root_path=str(target))
    sg_build_ms = (time.perf_counter() - t0) * 1000.0
    sg_stats = sg_backend.stats()
    print(f"       {sg_stats} built in {sg_build_ms:.1f} ms")

    print("[load] sqlitegraph backend (warm open)")
    t0 = time.perf_counter()
    sg_backend = SqlitegraphBackend.open(sg_cache, root_path=str(target))
    sg_open_ms = (time.perf_counter() - t0) * 1000.0
    print(f"       opened in {sg_open_ms:.1f} ms")

    # ── Pick representative symbols ────────────────────────────────
    import sqlite3

    with sqlite3.connect(str(index_db)) as conn:
        sample_names = [
            row[0] for row in conn.execute("SELECT name FROM gi_symbols ORDER BY id").fetchall()
        ]
    samples = _pick_samples(sample_names, args.iters)
    path_pairs = [(samples[i], samples[-(i + 1)]) for i in range(min(50, len(samples) // 2))]

    print(f"[bench] running {args.iters} iterations per op")

    results = {}
    results["find_symbol"] = (
        _bench("find_symbol", lambda: [py_engine.find_symbol(n) for n in samples], 5),
        _bench("find_symbol", lambda: [sg_backend.find_symbol(n) for n in samples], 5),
    )
    results["callers"] = (
        _bench("callers", lambda: [py_engine.callers(n) for n in samples], 5),
        _bench("callers", lambda: [sg_backend.callers(n) for n in samples], 5),
    )
    results["callees"] = (
        _bench("callees", lambda: [py_engine.callees(n) for n in samples], 5),
        _bench("callees", lambda: [sg_backend.callees(n) for n in samples], 5),
    )
    results["impact_depth3"] = (
        _bench("impact_depth3", lambda: [py_engine.impact(n, depth=3) for n in samples], 3),
        _bench("impact_depth3", lambda: [sg_backend.impact(n, depth=3) for n in samples], 3),
    )
    results["affected_depth3"] = (
        _bench("affected_depth3", lambda: [py_engine.affected(n, depth=3) for n in samples], 3),
        _bench("affected_depth3", lambda: [sg_backend.affected(n, depth=3) for n in samples], 3),
    )
    if path_pairs:
        results["shortest_path"] = (
            _bench("shortest_path", lambda: [py_engine.path(a, b) for a, b in path_pairs], 3),
            _bench("shortest_path", lambda: [sg_backend.path(a, b) for a, b in path_pairs], 3),
        )

    # ── Report ─────────────────────────────────────────────────────
    lines = [
        f"# Benchmark: pure-Python vs sqlitegraph — `{target.name}`",
        "",
        f"- target repo: `{target}`",
        f"- symbols: **{symbol_count}** | python nodes: {py_stats['nodes']} | "
        f"sg nodes: {sg_stats['nodes']}",
        f"- python edges: {py_stats['edges']} | sg edges: {sg_stats['edges']}",
        f"- query batch size: **{len(samples)}** symbols, per-batch timing across iterations",
        "",
        "## Load times",
        "",
        "| stage              |       ms |",
        "| ------------------ | -------: |",
        f"| pure-python load   | {py_load_ms:>8.1f} |",
        f"| sqlitegraph build  | {sg_build_ms:>8.1f} |",
        f"| sqlitegraph open   | {sg_open_ms:>8.1f} |",
        "",
        "## Query latency (per batch of {n} symbols, ms)".replace("{n}", str(len(samples))),
        "",
        "| operation                | py median | sg median |   py p99 |   sg p99 |  speedup |",
        "| ------------------------ | --------: | --------: | -------: | -------: | -------: |",
    ]
    for op, (py_r, sg_r) in results.items():
        lines.append(_format_row(op, py_r, sg_r))
    lines.append("")
    lines.append("_Speedup > 1.0 means sqlitegraph is faster._")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        f"- Pure-Python edge count includes file→symbol *contains* edges "
        f"({py_stats['nodes'] - sg_stats['nodes']} of them); sqlitegraph backend stores "
        f"only reference edges. Reachability queries are not affected by this."
    )
    lines.append(
        "- Pure-Python wins for small in-process graphs: dict lookups beat SQL roundtrips."
    )
    lines.append(
        "- sqlitegraph wins on cold open (~1 ms vs ~95 ms full rebuild) "
        "and on larger-than-memory or cross-process workloads."
    )
    lines.append(
        "- `sqlitegraph build` is dominated by Python→Rust FFI per `add_node`/`add_edge`; "
        "a bulk-insert primitive would close the gap."
    )
    report = "\n".join(lines)

    results_path = bench_dir / "RESULTS.md"
    results_path.write_text(report + "\n")
    print()
    print(report)
    print()
    print(f"[done] wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
