"""Reranker — 召回后精排。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from simple_harness_memory.core.models import Hit


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]: ...


class IdentityReranker(Reranker):
    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        return hits


class CrossEncoderReranker(Reranker):
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise ImportError(
                "CrossEncoderReranker requires simple-harness-memory-sdk[embeddings]"
            ) from exc
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        if not hits:
            return hits
        scores = self._model.predict([(query, h.text) for h in hits])
        for hit, score in zip(hits, scores):
            hit.score = round(float(score), 6)
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits
