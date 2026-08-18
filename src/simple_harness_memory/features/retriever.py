"""Retriever — 六路 RRF 混合召回。"""
from __future__ import annotations

import time
from typing import Optional

from simple_harness_memory.cognitive.session_affinity import (
    cross_session_weight,
    temporal_affinity,
)
from simple_harness_memory.core.models import Fact, Hit, Message
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.embedders.base import (
    Embedder,
    cosine_similarity,
    decode_vector,
)
from simple_harness_memory.features.reranker import IdentityReranker, Reranker
from simple_harness_memory.features.rrf import RankedItem, fuse


class Retriever:
    def __init__(self, embedder: Embedder, reranker: Optional[Reranker] = None, min_similarity: float = 0.15) -> None:
        self._embedder = embedder
        self._reranker = reranker or IdentityReranker()
        self._min_similarity = min_similarity

    def recall(self, query, *, messages, facts, twin, session_id=None, limit=10):
        by_id = {m.id: m for m in messages if m.id is not None}
        vec_items = self._vec(query, messages)
        fts_items = self._fts(query, messages)
        facts_items = self._facts(query, facts, by_id)
        entity_items = self._entity(query, messages, twin)
        candidate_ids = {i.message_id for i in (vec_items + fts_items + facts_items + entity_items)}
        if not candidate_ids:
            return []
        candidates = [m for m in messages if m.id in candidate_ids]
        recency_items = self._rank_recency(candidates)
        salience_items = self._rank_salience(candidates)
        fused = fuse([vec_items, fts_items, recency_items, salience_items, facts_items, entity_items], limit=max(limit * 2, 30))
        hits = [self._to_hit(f) for f in fused]
        hits = self._apply_session_affinity(hits, session_id, facts)
        hits = self._reranker.rerank(query, hits)
        return hits[:limit]

    def vector_search(self, query, *, messages, limit=20):
        items = self._vec(query, messages)
        return [self._to_hit(f) for f in fuse([items], limit=limit)]

    def _vec(self, query, messages):
        qvec = self._embedder.embed(query)
        items = []
        for m in messages:
            if m.embedding is None:
                continue
            try:
                sim = cosine_similarity(qvec, decode_vector(m.embedding))
            except (ValueError, TypeError):
                continue
            if sim >= self._min_similarity:
                items.append(self._ranked(m, "vec", sim))
        items.sort(key=lambda x: x.raw_score, reverse=True)
        self._assign_ranks(items)
        return items

    def _fts(self, query, messages):
        q = query.casefold()
        items = [self._ranked(m, "fts", 1.0) for m in messages if q and q in m.content.casefold()]
        self._assign_ranks(items)
        return items

    def _facts(self, query, facts, by_id):
        q = query.casefold()
        items = []
        for f in facts:
            if not f.is_active or f.source_msg_id not in by_id:
                continue
            if q and q in f"{f.key} {f.value} {f.evidence}".casefold():
                items.append(self._ranked(by_id[f.source_msg_id], "facts", f.confidence))
        items.sort(key=lambda x: x.raw_score, reverse=True)
        self._assign_ranks(items)
        return items

    def _entity(self, query, messages, twin):
        q = query.casefold()
        matched = [name for name in twin.relationships.entities if name and name.casefold() in q]
        if not matched:
            return []
        items = [self._ranked(m, "entity", 1.0) for m in messages if any(n in m.content for n in matched)]
        self._assign_ranks(items)
        return items

    def _rank_recency(self, candidates):
        ordered = sorted(candidates, key=lambda m: m.created_at or 0.0, reverse=True)
        return [self._ranked(m, "recency", 1.0 / (i + 1)) for i, m in enumerate(ordered)]

    def _rank_salience(self, candidates):
        ordered = sorted(candidates, key=lambda m: m.salience, reverse=True)
        return [self._ranked(m, "salience", m.salience) for _, m in enumerate(ordered)]

    @staticmethod
    def _ranked(m, source, raw_score):
        return RankedItem(
            message_id=m.id or 0, text=m.content, rank=0, source=source,
            raw_score=raw_score, recency=0.0, salience=m.salience,
            session_affinity=1.0, session_id=m.session_id, role=m.role, created_at=m.created_at,
        )

    @staticmethod
    def _assign_ranks(items):
        for i, item in enumerate(items):
            item.rank = i + 1

    @staticmethod
    def _to_hit(item):
        return Hit(
            message_id=item["message_id"], text=item["text"], score=item["score"],
            source=item["source"], recency=item["recency"], salience=item["salience"],
            session_affinity=item["session_affinity"], session_id=item["session_id"],
            role=item["role"], created_at=item["created_at"],
        )

    @staticmethod
    def _apply_session_affinity(hits, session_id, facts):
        if not session_id:
            return hits
        cat_by_msg = {}
        for f in facts:
            if f.source_msg_id and f.source_msg_id not in cat_by_msg:
                cat_by_msg[f.source_msg_id] = f.category
        now = time.time()
        for hit in hits:
            if hit.session_id == session_id:
                hit.session_affinity = temporal_affinity(max(0.0, (now - (hit.created_at or now)) / 86400.0))
            else:
                hit.session_affinity = cross_session_weight(hit.session_id or "", session_id, cat_by_msg.get(hit.message_id, ""))
            hit.score = round(hit.score * hit.session_affinity, 6)
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits
