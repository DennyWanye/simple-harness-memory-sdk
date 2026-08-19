"""Embedder 抽象与向量编码/余弦相似度。"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod


class Embedder(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


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
    return dot / ((na ** 0.5) * (nb ** 0.5))
