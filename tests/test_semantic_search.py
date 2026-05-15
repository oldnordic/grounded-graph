"""Tests for HNSW-backed semantic search in SqlitegraphBackend."""

from __future__ import annotations

from pathlib import Path

from grounded_index.indexer import Indexer

from grounded_graph.embedder import HashEmbedder
from grounded_graph.graph import GraphNode
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend


def _seed_index(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        '''def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}!"


def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


def read_file(path: str) -> str:
    """Read a file from disk and return its contents."""
    with open(path) as f:
        return f.read()


def main() -> None:
    print(greet("world"))
'''
    )
    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()
    return db_path


def test_build_without_embedder_has_no_semantic_index(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    backend = SqlitegraphBackend.build(index_db, sg_db_path=None, root_path=str(tmp_path))
    assert backend.has_semantic_index() is False
    assert backend.semantic_search("anything", k=5) == []


def test_build_with_embedder_creates_semantic_index(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    backend = SqlitegraphBackend.build(
        index_db,
        sg_db_path=None,
        root_path=str(tmp_path),
        embedder=HashEmbedder(dimension=64),
    )
    assert backend.has_semantic_index() is True


def test_semantic_search_returns_graphnode_distance_pairs(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    backend = SqlitegraphBackend.build(
        index_db,
        sg_db_path=None,
        root_path=str(tmp_path),
        embedder=HashEmbedder(dimension=64),
    )
    results = backend.semantic_search("greet", k=3)
    assert len(results) > 0
    for node, distance in results:
        assert isinstance(node, GraphNode)
        assert isinstance(distance, float)


def test_semantic_search_recovers_exact_match_with_hash_embedder(tmp_path: Path) -> None:
    """HashEmbedder gives identical vectors for identical input.

    Querying with the exact concatenated text of a symbol should put that
    symbol at the top of the result list (distance ~0).
    """
    index_db = _seed_index(tmp_path)
    backend = SqlitegraphBackend.build(
        index_db,
        sg_db_path=None,
        root_path=str(tmp_path),
        embedder=HashEmbedder(dimension=64),
    )
    node = backend.find_symbol("greet")
    assert node is not None
    query_text = backend.embed_text_for(node)
    results = backend.semantic_search(query_text, k=1)
    assert len(results) == 1
    top_node, distance = results[0]
    assert top_node.name == "greet"
    assert distance < 1e-3


def test_semantic_search_persists_across_open(tmp_path: Path) -> None:
    """HNSW index built into a file-backed graph survives reopen."""
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    SqlitegraphBackend.build(
        index_db,
        sg_db_path=sg_db,
        root_path=str(tmp_path),
        embedder=HashEmbedder(dimension=64),
    )
    reopened = SqlitegraphBackend.open(sg_db, root_path=str(tmp_path))
    assert reopened.has_semantic_index() is True
    results = reopened.semantic_search("greet", k=3)
    assert len(results) > 0
