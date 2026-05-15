"""Pluggable text embedders for semantic search over code symbols."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from typing import Any, Protocol


class Embedder(Protocol):
    """A callable that turns text into fixed-dimension vectors."""

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def to_config(self) -> dict[str, Any]: ...


class HashEmbedder:
    """Deterministic SHA-256-derived embeddings.

    Useful for tests and offline use — produces stable vectors with no
    network or model dependency. Two identical inputs always yield the
    same vector. Output vectors are L2-normalized.
    """

    def __init__(self, dimension: int = 128) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def to_config(self) -> dict[str, Any]:
        return {"type": "hash", "dimension": self._dimension}

    def _embed_one(self, text: str) -> list[float]:
        seed = text.encode("utf-8")
        buf = bytearray()
        counter = 0
        while len(buf) < self._dimension:
            buf.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
            counter += 1
        floats = [b / 127.5 - 1.0 for b in buf[: self._dimension]]
        norm = sum(x * x for x in floats) ** 0.5
        if norm > 0.0:
            floats = [x / norm for x in floats]
        return floats


class OllamaEmbedder:
    """Embeddings via a local ollama daemon.

    Default model ``nomic-embed-text`` produces 768-dimension vectors.
    Requires ollama to be running and the model pulled locally.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        url: str = "http://localhost:11434",
        dimension: int = 768,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self._dimension = dimension
        self.timeout = timeout

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read())
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list):
            raise RuntimeError(f"ollama returned no embeddings: {body!r}")
        return [list(v) for v in embeddings]

    def to_config(self) -> dict[str, Any]:
        return {
            "type": "ollama",
            "model": self.model,
            "url": self.url,
            "dimension": self._dimension,
            "timeout": self.timeout,
        }


def embedder_from_config(config: dict[str, Any]) -> Embedder:
    """Reconstruct an embedder from a serialized config dict."""
    kind = config.get("type")
    if kind == "hash":
        return HashEmbedder(dimension=int(config["dimension"]))
    if kind == "ollama":
        return OllamaEmbedder(
            model=str(config.get("model", "nomic-embed-text")),
            url=str(config.get("url", "http://localhost:11434")),
            dimension=int(config.get("dimension", 768)),
            timeout=float(config.get("timeout", 30.0)),
        )
    raise ValueError(f"unknown embedder type: {kind!r}")
