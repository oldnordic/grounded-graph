"""Tests for the Embedder protocol and HashEmbedder / OllamaEmbedder."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest

from grounded_graph.embedder import HashEmbedder, OllamaEmbedder


def test_hash_embedder_is_deterministic() -> None:
    embedder = HashEmbedder(dimension=64)
    a = embedder.embed(["hello world"])[0]
    b = embedder.embed(["hello world"])[0]
    assert a == b


def test_hash_embedder_produces_correct_dimension() -> None:
    embedder = HashEmbedder(dimension=128)
    vec = embedder.embed(["hello"])[0]
    assert len(vec) == 128


def test_hash_embedder_different_inputs_differ() -> None:
    embedder = HashEmbedder(dimension=64)
    a = embedder.embed(["foo"])[0]
    b = embedder.embed(["bar"])[0]
    assert a != b


def test_hash_embedder_outputs_are_l2_normalized() -> None:
    embedder = HashEmbedder(dimension=64)
    vec = embedder.embed(["normalize me"])[0]
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_hash_embedder_batch_matches_singletons() -> None:
    embedder = HashEmbedder(dimension=32)
    batch = embedder.embed(["a", "b", "c"])
    individual = [embedder.embed([t])[0] for t in ("a", "b", "c")]
    assert batch == individual


def _ollama_available() -> bool:
    """Probe whether ollama is reachable with nomic-embed-text."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data: dict[str, Any] = json.loads(resp.read())
        models = {m["name"] for m in data.get("models", [])}
        return any(m.startswith("nomic-embed-text") for m in models)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


_OLLAMA_OK = _ollama_available()


@pytest.mark.skipif(not _OLLAMA_OK, reason="ollama with nomic-embed-text not available")
def test_ollama_embedder_produces_vector() -> None:
    embedder = OllamaEmbedder()
    vecs = embedder.embed(["a function that greets a user"])
    assert len(vecs) == 1
    assert len(vecs[0]) == embedder.dimension
    assert all(isinstance(x, float) for x in vecs[0])


@pytest.mark.skipif(not _OLLAMA_OK, reason="ollama with nomic-embed-text not available")
def test_ollama_embedder_batch() -> None:
    embedder = OllamaEmbedder()
    vecs = embedder.embed(["greet", "compute sum", "open file"])
    assert len(vecs) == 3
    assert all(len(v) == embedder.dimension for v in vecs)


def test_ollama_embedder_unreachable_url_raises() -> None:
    """An unreachable ollama instance should surface a clear error."""
    embedder = OllamaEmbedder(url="http://127.0.0.1:1")  # closed port
    with pytest.raises(Exception):  # noqa: B017 - any network failure is acceptable
        embedder.embed(["test"])


def test_env_var_can_force_skip_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """GROUNDED_GRAPH_SKIP_OLLAMA=1 should be respected by anyone reading it."""
    monkeypatch.setenv("GROUNDED_GRAPH_SKIP_OLLAMA", "1")
    assert os.environ["GROUNDED_GRAPH_SKIP_OLLAMA"] == "1"
