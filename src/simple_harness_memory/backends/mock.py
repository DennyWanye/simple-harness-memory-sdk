"""Mock 后端 — 纯内存实现。"""
from __future__ import annotations

import time

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.core.models import Fact, Message
from simple_harness_memory.core.twin import DigitalTwin


class MockMemoryBackend(BaseMemoryBackend):
    def __init__(self, *, embedder=None, fact_extractor=None, reranker=None, summarizer=None, auto_extract_facts=False):
        super().__init__(embedder=embedder, fact_extractor=fact_extractor, reranker=reranker, summarizer=summarizer, auto_extract_facts=auto_extract_facts)
        self._messages: list[Message] = []
        self._facts: list[Fact] = []
        self._twins: dict[str, DigitalTwin] = {}
        self._workspace_actions: list[tuple[str, str, dict, float]] = []
        self._next_msg_id = 1
        self._next_fact_id = 1

    async def _append_message_impl(self, session_id, role, content, embedding, salience, decay_rate, created_at, is_summary, summary_of, source_event_id):
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        self._messages.append(Message(id=msg_id, session_id=session_id, role=role, content=content, created_at=created_at, salience=salience, decay_rate=decay_rate, embedding=embedding, is_summary=is_summary, summary_of=summary_of))
        return msg_id

    async def _get_message_impl(self, message_id):
        for m in self._messages:
            if m.id == message_id:
                return m
        return None

    async def _get_recent_messages_impl(self, session_id, limit):
        filtered = [m for m in self._messages if m.session_id == session_id]
        return filtered[-limit:]

    async def _messages_all(self):
        return list(self._messages)

    async def _facts_all(self):
        return list(self._facts)

    async def _insert_fact(self, fact):
        return self._add_fact(fact)

    async def _supersede_fact(self, fact_id, superseded_by):
        for f in self._facts:
            if f.id == fact_id:
                f.superseded_by = superseded_by
                return

    async def _forget_fact_by_id(self, fact_id, forgotten_at):
        for f in self._facts:
            if f.id == fact_id:
                f.forgotten_at = forgotten_at
                return True
        return False

    async def _update_message_salience(self, message_id, salience, last_recalled):
        for m in self._messages:
            if m.id == message_id:
                m.salience = salience
                if last_recalled is not None:
                    m.last_recalled = last_recalled
                return

    async def _set_fact_decay(self, fact_id, *, forgotten_at=None, last_decay_at=None):
        for f in self._facts:
            if f.id == fact_id:
                if forgotten_at is not None:
                    f.forgotten_at = forgotten_at
                if last_decay_at is not None:
                    f.last_decay_at = last_decay_at
                return

    async def _load_twin(self, subject):
        return self._twins.get(subject, DigitalTwin(subject=subject))

    async def _save_twin(self, twin):
        self._twins[twin.subject] = twin

    async def _record_workspace_impl(self, session_id, action_type, payload):
        self._workspace_actions.append((session_id, action_type, payload, time.time()))

    def _add_fact(self, fact):
        fact_id = self._next_fact_id
        self._next_fact_id += 1
        fact.id = fact_id
        self._facts.append(fact)
        return fact_id
