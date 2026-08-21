"""CloudEmbedder — 云端向量化（provider 无关）。"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Protocol

from simple_harness_memory.core.errors import EmbeddingError
from simple_harness_memory.embedders.base import (
    EMBEDDING_FORMAT_FINGERPRINT,
    Embedder,
    EmbeddingLineage,
)


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class CloudEmbedder(Embedder):
    """Async cloud embedder with an LRU cache, retry and fail-closed semantics.

    No silent offline fallback: on network/timeout failure after retries it
    raises ``EmbeddingError`` so the caller can choose an explicit degradation
    (e.g. HashEmbedder, whose ``kind="hash"`` lineage is recorded correctly).
    """

    def __init__(
        self,
        client: EmbeddingClient,
        *,
        model: str,
        dim: int,
        provider: str = "openai-compatible",
        revision: str = "unspecified",
        cache_size: int = 1024,
        retries: int = 2,
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        if not provider.strip() or not model.strip() or not revision.strip():
            raise ValueError("provider, model, and revision must be non-empty")
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._provider = provider
        self._model = model
        self._revision = revision
        self._dim = dim
        self._cache_size = cache_size
        self._retries = retries
        self._timeout = timeout
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    @property
    def kind(self) -> str:
        return "cloud"

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def lineage(self) -> EmbeddingLineage:
        return EmbeddingLineage(
            kind="cloud",
            provider=self._provider,
            model=self._model,
            revision=self._revision,
            dimension=self._dim,
            normalization="provider-defined",
            format_fingerprint=EMBEDDING_FORMAT_FINGERPRINT,
        )

    def __repr__(self) -> str:
        return f"CloudEmbedder(model={self._model!r}, dim={self._dim})"

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        missing: list[str] = []
        for text in texts:
            if text in self._cache:
                result.append(self._cache[text])
            else:
                result.append([])  # placeholder
                missing.append(text)
        if missing:
            vectors = await self._embed_with_retry(missing)
            try:
                self.validate_vectors(vectors, expected_count=len(missing))
            except ValueError as exc:
                raise EmbeddingError(str(exc)) from exc
            idx = 0
            for i, text in enumerate(texts):
                if text in missing:
                    vec = vectors[idx]
                    idx += 1
                    result[i] = vec
                    self._cache[text] = vec
                    if len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
        return result

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await asyncio.wait_for(self._client.embed(texts), timeout=self._timeout)
            except EmbeddingError:
                # 确定性错误（如维度不符）不重试，保留具体消息
                raise
            except Exception as exc:  # noqa: BLE001 - network boundary, retry then fail-closed
                last_exc = exc
                if attempt < self._retries:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise EmbeddingError(
            f"cloud embedding failed after {self._retries + 1} attempts: {type(last_exc).__name__}"
        ) from last_exc
