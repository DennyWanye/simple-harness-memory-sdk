"""HashEmbedder — 确定性哈希伪向量。"""
from __future__ import annotations

import hashlib
import math

from simple_harness_memory.embedders.base import Embedder


class HashEmbedder(Embedder):
    def __init__(self, dim: int = 256, ngrams: tuple[int, ...] = (1, 2, 3)) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim
        self._ngrams = tuple(ngrams)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        norm = text.casefold()
        shingles: list[str] = []
        for n in self._ngrams:
            if n <= 1:
                shingles.extend(norm)
            else:
                shingles.extend(norm[i:i + n] for i in range(len(norm) - n + 1))
        for gram in shingles:
            h = int.from_bytes(hashlib.md5(gram.encode("utf-8")).digest()[:8], "big")
            idx = h % self._dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        length = math.sqrt(sum(v * v for v in vec))
        if length == 0.0:
            return vec
        return [v / length for v in vec]


MockEmbedder = HashEmbedder
