"""CLI entry point for grounded-graph."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from grounded_graph.embedder import Embedder, HashEmbedder, OllamaEmbedder
from grounded_graph.formatters import get_formatter
from grounded_graph.loader import load_from_index
from grounded_graph.query import QueryEngine
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend

Engine = QueryEngine | SqlitegraphBackend


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grounded-graph",
        description="Graph traversal and context queries over code metadata.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    parser.add_argument(
        "--db", "-d", default=".grounded-index.db", help="Path to grounded-index database"
    )
    parser.add_argument("--output", "-o", default="human", choices=["human", "json", "markdown"])
    parser.add_argument("--root", "-r", default=".", help="Repository root path")
    parser.add_argument(
        "--backend",
        choices=["python", "sqlitegraph"],
        default="python",
        help="Storage backend: pure-Python in-memory (default) or sqlitegraph (file-backed)",
    )
    parser.add_argument(
        "--sg-db",
        default=None,
        help="Sqlitegraph DB path (required for --backend sqlitegraph)",
    )
    parser.add_argument(
        "--embedder",
        choices=["none", "hash", "ollama"],
        default="none",
        help="Embedder for HNSW semantic search (used at index time)",
    )
    parser.add_argument(
        "--embedder-dim",
        type=int,
        default=128,
        help="Dimension for the hash embedder (ignored for ollama)",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("index", help="Build or load the graph")
    subparsers.add_parser("status", help="Show graph statistics")

    find_parser = subparsers.add_parser("find-symbol", help="Find symbol by name")
    find_parser.add_argument("--name", required=True, help="Symbol name")

    callers_parser = subparsers.add_parser("callers", help="Find symbols that call the target")
    callers_parser.add_argument("--symbol", required=True, help="Target symbol name")

    callees_parser = subparsers.add_parser("callees", help="Find symbols called by the target")
    callees_parser.add_argument("--symbol", required=True, help="Target symbol name")

    impact_parser = subparsers.add_parser("impact", help="Forward reachable symbols")
    impact_parser.add_argument("--symbol", required=True, help="Target symbol name")
    impact_parser.add_argument("--depth", type=int, default=3, help="Max traversal depth")

    affected_parser = subparsers.add_parser("affected", help="Backward reachable symbols")
    affected_parser.add_argument("--symbol", required=True, help="Target symbol name")
    affected_parser.add_argument("--depth", type=int, default=3, help="Max traversal depth")

    path_parser = subparsers.add_parser("path", help="Shortest path between two symbols")
    path_parser.add_argument("--from", dest="from_symbol", required=True, help="Start symbol")
    path_parser.add_argument("--to", dest="to_symbol", required=True, help="End symbol")

    hood_parser = subparsers.add_parser("neighborhood", help="N-hop context pack")
    hood_parser.add_argument("--symbol", required=True, help="Target symbol name")
    hood_parser.add_argument("--depth", type=int, default=2, help="Hop depth")
    hood_parser.add_argument("--budget", type=int, default=4000, help="Token budget")

    sem_parser = subparsers.add_parser(
        "semantic", help="HNSW-backed semantic search (sqlitegraph backend only)"
    )
    sem_parser.add_argument("--query", required=True, help="Free-text query")
    sem_parser.add_argument("-k", type=int, default=10, help="Number of nearest neighbors")

    return parser


def _make_embedder(name: str, dim: int) -> Embedder | None:
    if name == "hash":
        return HashEmbedder(dimension=dim)
    if name == "ollama":
        return OllamaEmbedder()
    return None


def _load_python_engine(db_path: Path, root_path: Path) -> QueryEngine:
    graph = load_from_index(db_path)
    return QueryEngine(graph, root_path=str(root_path))


def _open_sg_backend(sg_db: Path, root_path: Path) -> SqlitegraphBackend:
    return SqlitegraphBackend.open(sg_db, root_path=str(root_path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    root_path = Path(args.root).resolve()
    formatter = get_formatter(args.output)

    if args.backend == "sqlitegraph" and args.sg_db is None:
        print("Error: --sg-db is required when --backend sqlitegraph", file=sys.stderr)
        return 1

    sg_db = Path(args.sg_db) if args.sg_db else None

    # ── Index command (build/refresh graph) ─────────────────────────
    if args.command == "index":
        if not db_path.exists():
            print(f"Error: database not found: {db_path}", file=sys.stderr)
            return 1

        if args.backend == "python":
            graph = load_from_index(db_path)
            stats = graph.stats()
            print(f"Loaded graph: {stats['nodes']} nodes, {stats['edges']} edges")
            return 0

        assert sg_db is not None
        embedder = _make_embedder(args.embedder, args.embedder_dim)
        backend = SqlitegraphBackend.build(
            db_path,
            sg_db_path=sg_db,
            root_path=str(root_path),
            embedder=embedder,
        )
        stats = backend.stats()
        suffix = f" (HNSW: {args.embedder})" if embedder else ""
        print(
            f"Built sqlitegraph DB at {sg_db}: "
            f"{stats['nodes']} nodes, {stats['edges']} edges{suffix}"
        )
        return 0

    # ── All other commands require a loaded engine ──────────────────
    engine: Engine
    if args.backend == "sqlitegraph":
        assert sg_db is not None
        if not sg_db.exists():
            print(
                f"Error: sqlitegraph DB not found: {sg_db}. Run 'index' first.",
                file=sys.stderr,
            )
            return 1
        engine = _open_sg_backend(sg_db, root_path)
    else:
        if not db_path.exists():
            print(f"Error: database not found: {db_path}. Run 'index' first.", file=sys.stderr)
            return 1
        engine = _load_python_engine(db_path, root_path)

    if args.command == "status":
        print(formatter.format_status(engine.stats()))
        return 0

    if args.command == "find-symbol":
        node = engine.find_symbol(args.name)
        if node is None:
            print(f"Symbol not found: {args.name}", file=sys.stderr)
            return 1
        print(formatter.format_nodes([node]))
        return 0

    if args.command == "callers":
        results = engine.callers(args.symbol)
        if not results:
            print(f"No callers found for: {args.symbol}", file=sys.stderr)
            return 1
        print(formatter.format_nodes(results))
        return 0

    if args.command == "callees":
        results = engine.callees(args.symbol)
        if not results:
            print(f"No callees found for: {args.symbol}", file=sys.stderr)
            return 1
        print(formatter.format_nodes(results))
        return 0

    if args.command == "impact":
        results = engine.impact(args.symbol, depth=args.depth)
        if not results:
            print(f"No impact found for: {args.symbol}", file=sys.stderr)
            return 1
        print(formatter.format_nodes(results))
        return 0

    if args.command == "affected":
        results = engine.affected(args.symbol, depth=args.depth)
        if not results:
            print(f"No affected symbols found for: {args.symbol}", file=sys.stderr)
            return 1
        print(formatter.format_nodes(results))
        return 0

    if args.command == "path":
        path_nodes = engine.path(args.from_symbol, args.to_symbol)
        if path_nodes is None:
            print(f"No path from {args.from_symbol} to {args.to_symbol}", file=sys.stderr)
            return 1
        print(formatter.format_path(path_nodes))
        return 0

    if args.command == "neighborhood":
        items = engine.neighborhood_context(args.symbol, depth=args.depth, budget=args.budget)
        if not items:
            print(f"Symbol not found: {args.symbol}", file=sys.stderr)
            return 1
        print(formatter.format_context(items))
        return 0

    if args.command == "semantic":
        if not isinstance(engine, SqlitegraphBackend):
            print(
                "Error: 'semantic' requires --backend sqlitegraph",
                file=sys.stderr,
            )
            return 1
        if not engine.has_semantic_index() or engine._embedder is None:
            print(
                "Error: no semantic index found. Re-run 'index' with --embedder hash or ollama.",
                file=sys.stderr,
            )
            return 1
        hits = engine.semantic_search(args.query, k=args.k)
        if not hits:
            print(f"No results for: {args.query}", file=sys.stderr)
            return 1
        # Reuse the node formatter, append distances in human/markdown
        print(formatter.format_nodes([node for node, _ in hits]))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
