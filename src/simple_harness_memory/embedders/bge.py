"""BGEM3Embedder — 可选本地语义向量。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from simple_harness_memory.embedders.base import (
    EMBEDDING_FORMAT_FINGERPRINT,
    Embedder,
    EmbeddingLineage,
)


class BGEM3Embedder(Embedder):
    """BGE-M3 loaded strictly from local resources; it never downloads at runtime."""

    def __init__(
        self,
        model_path: str | Path = "BAAI/bge-m3",
        device: Any = None,
        *,
        revision: str = "local-cache",
        model_name: str | None = None,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "BGEM3Embedder requires simple-harness-memory-sdk[embeddings]"
            ) from exc
        model_ref = str(model_path)
        if not model_ref.strip():
            raise ValueError("model_path must be non-empty")
        if not revision.strip():
            raise ValueError("revision must be non-empty")
        self._model_ref = model_ref
        self._model_name = model_name or model_ref
        self._revision = revision
        self._model = SentenceTransformer(
            model_ref,
            device=device,
            local_files_only=True,
            revision=revision,
        )

    @property
    def kind(self) -> str:
        return "bge"

    @property
    def dim(self) -> int:
        if hasattr(self._model, "get_embedding_dimension"):
            dimension = self._model.get_embedding_dimension()
        else:
            dimension = self._model.get_sentence_embedding_dimension()
        return int(cast(int, dimension))

    @property
    def lineage(self) -> EmbeddingLineage:
        return EmbeddingLineage(
            kind="bge",
            provider="sentence-transformers",
            model=self._model_name,
            revision=self._revision,
            dimension=self.dim,
            normalization="l2",
            format_fingerprint=EMBEDDING_FORMAT_FINGERPRINT,
        )

    async def embed(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True).tolist()
        self.validate_vectors([vector], expected_count=1)
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True).tolist()
        self.validate_vectors(vectors, expected_count=len(texts))
        return vectors
