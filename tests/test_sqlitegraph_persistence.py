"""Tests for file-backed persistence in SqlitegraphBackend."""

from pathlib import Path

from grounded_index.indexer import Indexer

from grounded_graph.graph import GraphNode
from grounded_graph.sqlitegraph_backend import SqlitegraphBackend


def _seed_index(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    \"\"\"Greet someone.\"\"\"
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)

def main() -> None:
    g = Greeter()
    print(g.greet("world"))
"""
    )
    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()
    return db_path


def test_build_writes_sg_db_to_disk(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))

    assert sg_db.exists(), "build() should create the sqlitegraph DB file"
    assert sg_db.stat().st_size > 0, "sqlitegraph DB should not be empty"


def test_open_reuses_existing_db_without_rebuild(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    # First: build
    SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))

    # Then: open without the index DB present
    index_db.unlink()  # remove grounded-index DB to prove open() doesn't rebuild
    reopened = SqlitegraphBackend.open(sg_db, root_path=str(tmp_path))

    hello = reopened.find_symbol("hello")
    assert hello is not None
    assert hello.name == "hello"
    assert hello.kind == "function"


def test_build_returns_graphnode_not_dict(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    backend = SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))

    node = backend.find_symbol("hello")
    assert node is not None
    assert isinstance(node, GraphNode), f"expected GraphNode, got {type(node).__name__}"


def test_callers_returns_graphnodes(tmp_path: Path) -> None:
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    backend = SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))

    callers = backend.callers("hello")
    assert all(isinstance(c, GraphNode) for c in callers)
    caller_names = {c.name for c in callers}
    assert "greet" in caller_names


def test_persisted_graph_has_signature_and_docstring(tmp_path: Path) -> None:
    """Persisted node data must include signature/docstring for context queries."""
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))
    reopened = SqlitegraphBackend.open(sg_db, root_path=str(tmp_path))

    hello = reopened.find_symbol("hello")
    assert hello is not None
    assert hello.signature is not None
    assert "name: str" in hello.signature
    assert hello.docstring == "Greet someone."


def test_build_in_memory_still_works(tmp_path: Path) -> None:
    """When sg_db_path is None, build() creates an in-memory graph."""
    index_db = _seed_index(tmp_path)

    backend = SqlitegraphBackend.build(index_db, sg_db_path=None, root_path=str(tmp_path))

    hello = backend.find_symbol("hello")
    assert hello is not None
    assert hello.name == "hello"


def test_rebuild_overwrites_existing_sg_db(tmp_path: Path) -> None:
    """Calling build() twice on the same path replaces the DB."""
    index_db = _seed_index(tmp_path)
    sg_db = tmp_path / "graph.sgdb"

    SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))
    first_size = sg_db.stat().st_size
    assert first_size > 0

    # Modify the source, re-index, then rebuild
    (tmp_path / "src" / "main.py").write_text("def only_one(): pass\n")
    Indexer(root=tmp_path, db_path=index_db).index()

    SqlitegraphBackend.build(index_db, sg_db_path=sg_db, root_path=str(tmp_path))
    backend = SqlitegraphBackend.open(sg_db, root_path=str(tmp_path))

    only_one = backend.find_symbol("only_one")
    assert only_one is not None
    hello_after = backend.find_symbol("hello")
    assert hello_after is None, "rebuild should drop the old 'hello' symbol"
