"""Text embeddings for schema retrieval.

The default embedder is a dependency-free feature-hashing model over word
tokens and character n-grams. Character n-grams are a good fit for
Azerbaijani, an agglutinative language: "satış", "satışlar", "satışların"
share most of their n-grams, so morphology is handled without a stemmer.
It is deterministic, which makes experiments reproducible. An
OpenAI-compatible embedding endpoint can be used instead.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Azerbaijani-aware lowercasing: dotted and dotless I are distinct letters.
_AZ_LOWER = str.maketrans({"I": "ı", "İ": "i"})

# Fold Azerbaijani letters to ASCII as an additional feature channel so that
# questions typed without the special letters ("satis" for "satış") still match.
_AZ_FOLD = str.maketrans({"ə": "e", "ı": "i", "ö": "o", "ü": "u", "ğ": "g", "ç": "c", "ş": "s"})


def normalize(text: str) -> str:
    return text.translate(_AZ_LOWER).lower()


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(normalize(text))


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 512, ngram_range: tuple[int, int] = (3, 5)) -> None:
        if dim < 16:
            raise ValueError("dim must be at least 16")
        self.dim = dim
        self.ngram_range = ngram_range
        self.model_name = f"hashing-ngram-{dim}"

    def _features(self, text: str) -> list[tuple[str, float]]:
        feats: list[tuple[str, float]] = []
        for word in tokenize(text):
            for variant in {word, word.translate(_AZ_FOLD)}:
                feats.append((f"w:{variant}", 2.0))
                padded = f"<{variant}>"
                lo, hi = self.ngram_range
                for n in range(lo, hi + 1):
                    for i in range(len(padded) - n + 1):
                        feats.append((f"c{n}:{padded[i:i + n]}", 1.0))
        return feats

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in self._features(text):
            digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dim
            sign = 1.0 if (value >> 63) & 1 else -1.0
            vec[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class OpenAICompatibleEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str | None, dim: int, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self.dim = dim
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            json={"model": self.model_name, "input": texts},
            headers=self._headers,
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return [list(map(float, d["embedding"])) for d in data]


def build_embedder(provider: str, dim: int, model: str, base_url: str | None, api_key: str | None) -> Embedder:
    if provider == "hashing":
        return HashingEmbedder(dim=dim)
    if provider == "openai":
        if not base_url:
            raise ValueError("SORVIA_EMBEDDING_BASE_URL is required for the openai embedding provider")
        return OpenAICompatibleEmbedder(base_url, model, api_key, dim)
    raise ValueError(f"Unknown embedding provider {provider!r}")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
