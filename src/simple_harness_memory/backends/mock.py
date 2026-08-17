"""Mock 后端 — 纯内存实现，用于测试。

不依赖任何外部库，所有数据存储在 Python list/dict 中。
每次实例化都从空状态开始（无持久化）。
"""

from __future__ import annotations

import time
from typing import Optional

from simple_harness_memory.core.models import Fact, Hit, Message
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.features.rrf import RankedItem, fuse


class MockMemoryBackend(MemoryBackend):
    """内存 Mock 后端，适用于单元测试和快速原型。"""

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._facts: list[Fact] = []
        self._twins: dict[str, DigitalTwin] = {}
        self._next_msg_id = 1
        self._next_fact_id = 1

    # ── L2: 情景记忆 ────────────────────────────────

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> int:
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        msg = Message(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=time.time(),
            salience=salience,
            decay_rate=decay_rate,
        )
        self._messages.append(msg)
        return msg_id

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[Message]:
        # 按时间升序（旧→新）返回最近 limit 条
        filtered = [m for m in self._messages if m.session_id == session_id]
        return filtered[-limit:]

    async def get_message(self, message_id: int) -> Optional[Message]:
        for m in self._messages:
            if m.id == message_id:
                return m
        return None

    # ── L3: 语义记忆 ────────────────────────────────

    async def extract_facts(self, message_id: int, content: str, role: str) -> list[Fact]:
        # Mock 不做 LLM 提取，返回空列表
        return []

    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> list[Fact]:
        results = [f for f in self._facts if f.subject == subject]
        if category:
            results = [f for f in results if f.category == category]
        if active_only:
            results = [f for f in results if f.is_active]
        return results

    async def forget_fact(self, fact_id: int, reason: str = "") -> bool:
        for f in self._facts:
            if f.id == fact_id:
                f.forgotten_at = time.time()
                return True
        return False

    def _add_fact(self, fact: Fact) -> int:
        """测试辅助方法：直接写入一个 Fact。"""
        fact_id = self._next_fact_id
        self._next_fact_id += 1
        fact.id = fact_id
        self._facts.append(fact)
        return fact_id

    # ── 数字孪生体 ────────────────────────────────────

    async def get_digital_twin(self, subject: str = "user") -> DigitalTwin:
        if subject not in self._twins:
            self._twins[subject] = DigitalTwin(subject=subject)
        return self._twins[subject]

    async def update_digital_twin(self, twin: DigitalTwin) -> None:
        twin.last_updated = time.time()
        twin.recalculate_completeness()
        self._twins[twin.subject] = twin

    async def suggest_questions(self, subject: str = "user") -> list[str]:
        twin = await self.get_digital_twin(subject)
        questions = []
        for field in twin.missing_profile_fields():
            q_map = {
                "name": "你叫什么名字？",
                "occupation": "你是做什么工作的？",
                "location": "你在哪个城市？",
                "language": "你常用的语言是什么？",
            }
            if field in q_map:
                questions.append(q_map[field])
        return questions

    # ── 混合召回 ─────────────────────────────────────

    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[Hit]:
        """Mock 实现：关键词包含匹配，不做向量计算。"""
        query_lower = query.lower()
        ranked = []
        for i, msg in enumerate(reversed(self._messages)):
            if query_lower in msg.content.lower():
                ranked.append(
                    RankedItem(
                        message_id=msg.id or 0,
                        text=msg.content,
                        rank=i + 1,
                        source="fts",
                        raw_score=1.0,
                        recency=1.0 / (i + 1),
                        salience=msg.salience,
                        session_id=msg.session_id,
                        role=msg.role,
                        created_at=msg.created_at,
                    )
                )
        fused = fuse([ranked], limit=limit)
        return [
            Hit(
                message_id=r["message_id"],
                text=r["text"],
                score=r["score"],
                source=r["source"],
                recency=r["recency"],
                salience=r["salience"],
                session_id=r["session_id"],
                role=r["role"],
                created_at=r["created_at"],
            )
            for r in fused
        ]

    async def vector_search(self, query: str, limit: int = 20) -> list[Hit]:
        # Mock 降级为关键词匹配
        return await self.recall(query, limit=limit)

    # ── 认知维护 ─────────────────────────────────────

    async def daily_decay(self) -> dict[str, int]:
        # Mock 不执行衰减，直接返回 0
        return {"decayed": 0, "forgotten": 0}

    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
    ) -> dict[str, int]:
        return {"summarized_sessions": 0}

    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
    ) -> None:
        pass  # Mock 不持久化工作记忆动作
