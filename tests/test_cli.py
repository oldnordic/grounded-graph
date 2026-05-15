"""Tests for cli.py — CLI smoke tests."""

from pathlib import Path

import pytest

from grounded_graph.cli import main


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "grounded-graph" in captured.out


def test_index_and_status(tmp_path: Path, monkeypatch, capsys) -> None:
    # Create a mini project
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)
"""
    )

    # Index with grounded-index first
    from grounded_index.indexer import Indexer

    db_path = tmp_path / "index.db"
    indexer = Indexer(root=tmp_path, db_path=db_path)
    indexer.index()

    monkeypatch.chdir(tmp_path)

    # Index into grounded-graph
    code = main(["--db", str(db_path), "index"])
    assert code == 0

    # Status
    code = main(["--db", str(db_path), "status"])
    assert code == 0
    captured = capsys.readouterr()
    assert "nodes" in captured.out.lower()


def test_find_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("def hello(): pass\n")

    from grounded_index.indexer import Indexer

    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()

    monkeypatch.chdir(tmp_path)
    main(["--db", str(db_path), "index"])

    code = main(["--db", str(db_path), "find-symbol", "--name", "hello"])
    assert code == 0
    captured = capsys.readouterr()
    assert "hello" in captured.out


def test_callers(tmp_path: Path, monkeypatch, capsys) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(): pass

def greet():
    return hello()
"""
    )

    from grounded_index.indexer import Indexer

    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()

    monkeypatch.chdir(tmp_path)
    main(["--db", str(db_path), "index"])

    code = main(["--db", str(db_path), "callers", "--symbol", "hello"])
    assert code == 0
    captured = capsys.readouterr()
    assert "greet" in captured.out


def test_path_command(tmp_path: Path, monkeypatch, capsys) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        """def hello(): pass

def greet():
    return hello()

def main():
    return greet()
"""
    )

    from grounded_index.indexer import Indexer

    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()

    monkeypatch.chdir(tmp_path)
    main(["--db", str(db_path), "index"])

    code = main(["--db", str(db_path), "path", "--from", "main", "--to", "hello"])
    assert code == 0
    captured = capsys.readouterr()
    assert "main" in captured.out
    assert "hello" in captured.out


def test_tests_for_command(tmp_path: Path, monkeypatch, capsys) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.rs").write_text(
        """pub fn add(a: i32, b: i32) -> i32 { a + b }

#[cfg(test)]
mod tests {
    use super::add;

    #[test]
    fn test_add() {
        let _ = add(1, 2);
    }
}
"""
    )

    from grounded_index.indexer import Indexer

    db_path = tmp_path / "index.db"
    Indexer(root=tmp_path, db_path=db_path).index()

    monkeypatch.chdir(tmp_path)
    main(["--db", str(db_path), "index"])

    code = main(["--db", str(db_path), "tests-for", "--symbol", "add"])
    assert code == 0
    captured = capsys.readouterr()
    assert "test_add" in captured.out
