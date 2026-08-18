"""BGEM3Embedder — 可选本地语义向量。"""
from __future__ import annotations

from typing import Any

from simple_harness_memory.embedders.base import Embedder


class BGEM3Embedder(Embedder):
    def __init__(self, model_name: str = "BAAI/bge-m3", device: Any = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "BGEM3Embedder requires simple-harness-memory-sdk[embeddings]"
            ) from exc
        self._model = SentenceTransformer(model_name, device=device)

    @property
    def dim(self) -> int:
        if hasattr(self._model, "get_embedding_dimension"):
            return int(self._model.get_embedding_dimension())
        return int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._model.encode(texts, normalize_embeddings=True).tolist()
