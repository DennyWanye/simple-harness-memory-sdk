"""BaseMemoryBackend — 后端共享逻辑。"""
from __future__ import annotations

import json
import time
from abc import abstractmethod
from typing import Optional

from simple_harness_memory.cognitive.decay import bump_salience, decay_salience, should_forget
from simple_harness_memory.cognitive.twin_builder import build_twin_from_facts, detect_fact_conflicts
from simple_harness_memory.core.models import SINGLE_VALUED_KEYS, Fact, FactConflict, Hit, Message
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.embedders.base import Embedder, encode_vector
from simple_harness_memory.embedders.mock import HashEmbedder
from simple_harness_memory.features.facts import FactExtractor, RuleBasedFactExtractor
from simple_harness_memory.features.reranker import IdentityReranker, Reranker
from simple_harness_memory.features.retriever import Retriever
from simple_harness_memory.features.summarizer import RuleBasedSummarizer, Summarizer


class BaseMemoryBackend(MemoryBackend):
    def __init__(self, *, embedder=None, fact_extractor=None, reranker=None, summarizer=None, auto_extract_facts=False):
        self._embedder = embedder or HashEmbedder()
        self._fact_extractor = fact_extractor or RuleBasedFactExtractor()
        self._reranker = reranker or IdentityReranker()
        self._summarizer = summarizer or RuleBasedSummarizer()
        self._retriever = Retriever(self._embedder, self._reranker)
        self._auto_extract_facts = auto_extract_facts

    @abstractmethod
    async def _append_message_impl(self, session_id, role, content, embedding, salience, decay_rate, created_at, is_summary, summary_of) -> int: ...

    @abstractmethod
    async def _get_message_impl(self, message_id) -> Optional[Message]: ...

    @abstractmethod
    async def _get_recent_messages_impl(self, session_id, limit) -> list[Message]: ...

    @abstractmethod
    async def _messages_all(self) -> list[Message]: ...

    @abstractmethod
    async def _facts_all(self) -> list[Fact]: ...

    @abstractmethod
    async def _insert_fact(self, fact) -> int: ...

    @abstractmethod
    async def _supersede_fact(self, fact_id, superseded_by) -> None: ...

    @abstractmethod
    async def _forget_fact_by_id(self, fact_id, forgotten_at) -> bool: ...

    @abstractmethod
    async def _update_message_salience(self, message_id, salience, last_recalled) -> None: ...

    @abstractmethod
    async def _set_fact_decay(self, fact_id, *, forgotten_at=None, last_decay_at=None) -> None: ...

    @abstractmethod
    async def _load_twin(self, subject) -> DigitalTwin: ...

    @abstractmethod
    async def _save_twin(self, twin) -> None: ...

    @abstractmethod
    async def _record_workspace_impl(self, session_id, action_type, payload) -> None: ...

    async def append_message(self, session_id, role, content, *, salience=0.0, decay_rate=0.02):
        now = time.time()
        embedding = encode_vector(self._embedder.embed(content))
        msg_id = await self._append_message_impl(session_id, role, content, embedding, salience, decay_rate, now, False, None)
        if self._auto_extract_facts and role == "user":
            await self.extract_facts(msg_id, content, role)
        return msg_id

    async def get_recent_messages(self, session_id, limit=20):
        return await self._get_recent_messages_impl(session_id, limit)

    async def get_message(self, message_id):
        return await self._get_message_impl(message_id)

    async def extract_facts(self, message_id, content, role):
        facts = await self._fact_extractor.extract(content, role=role, message_id=message_id, created_at=time.time())
        stored = []
        for fact in facts:
            fact.source_msg_id = message_id
            new_id = await self._insert_fact(fact)
            fact.id = new_id
            stored.append(fact)
            if fact.key in SINGLE_VALUED_KEYS:
                for old in await self._facts_all():
                    if old.subject == fact.subject and old.key == fact.key and old.is_active and old.id != new_id:
                        await self._supersede_fact(old.id, new_id)
        return stored

    async def get_facts(self, subject="user", category=None, active_only=True):
        facts = [f for f in await self._facts_all() if f.subject == subject]
        if category:
            facts = [f for f in facts if f.category == category]
        if active_only:
            facts = [f for f in facts if f.is_active]
        return facts

    async def forget_fact(self, fact_id, reason=""):
        return await self._forget_fact_by_id(fact_id, time.time())

    async def get_digital_twin(self, subject="user"):
        base = await self._load_twin(subject)
        facts = await self._facts_all()
        return build_twin_from_facts(facts, base, subject)

    async def update_digital_twin(self, twin):
        twin.last_updated = time.time()
        twin.recalculate_completeness()
        await self._save_twin(twin)

    async def suggest_questions(self, subject="user"):
        twin = await self.get_digital_twin(subject)
        q_map = {"name": "你叫什么名字？", "occupation": "你是做什么工作的？", "location": "你在哪个城市？", "language": "你常用的语言是什么？"}
        return [q_map[f] for f in twin.missing_profile_fields() if f in q_map]

    async def detect_inconsistencies(self, subject="user"):
        facts = await self._facts_all()
        return detect_fact_conflicts([f for f in facts if f.subject == subject])

    async def recall(self, query, session_id=None, limit=10):
        messages = await self._messages_all()
        facts = await self._facts_all()
        twin = await self.get_digital_twin("user")
        hits = self._retriever.recall(query, messages=messages, facts=facts, twin=twin, session_id=session_id, limit=limit)
        now = time.time()
        for hit in hits:
            bumped = bump_salience(hit.salience)
            await self._update_message_salience(hit.message_id, bumped, now)
            hit.salience = bumped
        return hits

    async def vector_search(self, query, limit=20):
        messages = await self._messages_all()
        return self._retriever.vector_search(query, messages=messages, limit=limit)

    async def daily_decay(self):
        now = time.time()
        decayed = 0
        forgotten = 0
        for m in await self._messages_all():
            ref = m.last_recalled or m.created_at
            days = (now - ref) / 86400.0
            new_salience = decay_salience(m.salience, m.decay_rate, days)
            if abs(new_salience - m.salience) > 1e-9:
                await self._update_message_salience(m.id, new_salience, None)
                decayed += 1
        for f in await self._facts_all():
            if not f.is_active or f.pinned:
                continue
            ref = f.last_decay_at or f.created_at
            days = (now - ref) / 86400.0
            if should_forget(f.decay_rate, days):
                await self._set_fact_decay(f.id, forgotten_at=now)
                forgotten += 1
            else:
                await self._set_fact_decay(f.id, last_decay_at=now)
                decayed += 1
        return {"decayed": decayed, "forgotten": forgotten}

    async def summarize_old_sessions(self, older_than_days=7, max_sessions=5):
        now = time.time()
        cutoff = now - older_than_days * 86400.0
        by_session: dict[str, list[Message]] = {}
        for m in await self._messages_all():
            if m.is_summary or m.created_at >= cutoff:
                continue
            by_session.setdefault(m.session_id, []).append(m)
        ordered = sorted(by_session, key=lambda s: min(m.created_at for m in by_session[s]))
        count = 0
        for session_id in ordered[:max_sessions]:
            msgs = sorted(by_session[session_id], key=lambda m: m.created_at)
            summary = await self._summarizer.summarize(msgs)
            if not summary:
                continue
            await self._append_message_impl(session_id, "system", summary, None, 0.0, 0.02, now, True, json.dumps([m.id for m in msgs]))
            count += 1
        return {"summarized_sessions": count}

    async def record_workspace_action(self, session_id, action_type, payload):
        await self._record_workspace_impl(session_id, action_type, payload)
