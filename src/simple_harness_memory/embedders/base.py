"""Embedder 抽象与向量编码/余弦相似度。"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Final

EMBEDDING_FORMAT_VERSION = 1
EMBEDDING_FORMAT_FINGERPRINT: Final = "json-float-array:v1"


@dataclass(frozen=True, slots=True)
class EmbeddingLineage:
    """Complete, stable identity of vectors that may safely share an index."""

    kind: str
    provider: str
    model: str
    revision: str
    dimension: int
    normalization: str
    format_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "kind",
            "provider",
            "model",
            "revision",
            "normalization",
            "format_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"embedding lineage {field_name} must be non-empty")
        if self.dimension <= 0:
            raise ValueError("embedding lineage dimension must be positive")

    @property
    def lineage_id(self) -> str:
        canonical = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return f"emb:{sha256(canonical).hexdigest()}"


class Embedder(ABC):
    @property
    @abstractmethod
    def kind(self) -> str: ...

    @property
    @abstractmethod
    def dim(self) -> int: ...

    @property
    @abstractmethod
    def lineage(self) -> EmbeddingLineage: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]

    def validate_vectors(self, vectors: list[list[float]], *, expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise ValueError(
                f"embedding count mismatch: expected {expected_count}, got {len(vectors)}"
            )
        if any(len(vector) != self.lineage.dimension for vector in vectors):
            raise ValueError(
                f"embedding dimension mismatch: expected {self.lineage.dimension}"
            )


def encode_vector(vector: list[float]) -> bytes:
    return json.dumps(vector, separators=(",", ":")).encode("utf-8")


def decode_vector(data: bytes) -> list[float]:
    return json.loads(data.decode("utf-8"))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimension mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))
