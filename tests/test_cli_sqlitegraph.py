"""CLI tests for the --backend sqlitegraph code path and `semantic` subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest
from grounded_index.indexer import Indexer

from grounded_graph.cli import main


def _seed(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        '''def greet(name: str) -> str:
    """Greet a user."""
    return f"Hello, {name}!"


def add_numbers(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def main_entry() -> None:
    print(greet("world"))
    print(add_numbers(1, 2))
'''
    )
    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()
    return db_path


def test_index_sqlitegraph_writes_sg_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    sg_db = tmp_path / "graph.sgdb"
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "index",
        ]
    )
    assert code == 0
    assert sg_db.exists(), "sqlitegraph DB should be created"
    out = capsys.readouterr().out
    assert "nodes" in out.lower()


def test_find_symbol_sqlitegraph_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    sg_db = tmp_path / "graph.sgdb"
    monkeypatch.chdir(tmp_path)

    main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "index",
        ]
    )
    capsys.readouterr()  # discard build output

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "find-symbol",
            "--name",
            "greet",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "greet" in out


def test_callers_sqlitegraph_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    sg_db = tmp_path / "graph.sgdb"
    monkeypatch.chdir(tmp_path)

    main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "index",
        ]
    )
    capsys.readouterr()

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "callers",
            "--symbol",
            "greet",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "main_entry" in out


def test_semantic_command_with_hash_embedder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    sg_db = tmp_path / "graph.sgdb"
    monkeypatch.chdir(tmp_path)

    main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "--embedder",
            "hash",
            "index",
        ]
    )
    capsys.readouterr()

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "semantic",
            "--query",
            "greet a user",
            "-k",
            "3",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    # At least one symbol name should appear in the output
    assert any(name in out for name in ("greet", "add_numbers", "main_entry"))


def test_semantic_errors_without_sqlitegraph_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "python",
            "semantic",
            "--query",
            "anything",
        ]
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "sqlitegraph" in err.lower()


def test_semantic_errors_when_no_embedder_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = _seed(tmp_path)
    sg_db = tmp_path / "graph.sgdb"
    monkeypatch.chdir(tmp_path)

    # Build without --embedder
    main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "index",
        ]
    )
    capsys.readouterr()

    code = main(
        [
            "--db",
            str(db_path),
            "--backend",
            "sqlitegraph",
            "--sg-db",
            str(sg_db),
            "semantic",
            "--query",
            "anything",
        ]
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "embedder" in err.lower() or "semantic" in err.lower()
