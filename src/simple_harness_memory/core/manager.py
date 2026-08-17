"""MemoryManager — 统一入口，组合所有子系统。

Phase 1 默认使用 MockMemoryBackend，Phase 1+ 切换到 SQLiteMemoryBackend。
"""

from __future__ import annotations

import os
from typing import Optional

from simple_harness_memory.core.models import Fact, Hit, Message
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.world.port import (
    KnowledgeGap,
    TemporalContext,
    Weather,
    WorldEvent,
    WorldModelPort,
)


class _NullWorldModel(WorldModelPort):
    """空世界对象实现，Phase 4 前的占位符。"""

    async def get_temporal_context(self) -> TemporalContext:
        from simple_harness_memory.world.temporal import build_temporal_context
        return build_temporal_context()

    async def get_recent_events(self, days: int = 3) -> list[WorldEvent]:
        return []

    async def get_weather(self, location: str) -> Optional[Weather]:
        return None

    async def check_knowledge_boundary(self, query: str) -> Optional[KnowledgeGap]:
        return None

    async def get_personalized_news(
        self,
        interests: list[str],
        categories: list[str] | None = None,
    ) -> list[WorldEvent]:
        return []


class MemoryManager:
    """记忆系统统一管理器。

    用法：
        memory = await MemoryManager.build(db_path="./memory.db")
        msg_id = await memory.append_message("session-1", "user", "hello")
        hits = await memory.recall("用户说了什么？")
        twin = await memory.get_digital_twin()
        ctx = await memory.world.get_temporal_context()
    """

    def __init__(
        self,
        backend: MemoryBackend,
        world: WorldModelPort,
    ) -> None:
        self._backend = backend
        self.world = world

    @classmethod
    async def build(
        cls,
        db_path: Optional[str] = None,
        *,
        enable_facts: bool = False,
        enable_world_model: bool = False,
        backend: Optional[MemoryBackend] = None,
    ) -> "MemoryManager":
        """构建 MemoryManager。

        Args:
            db_path:           SQLite 数据库路径（None 使用 Mock 后端）
            enable_facts:      Phase 2+ 启用 Facts 自动提取
            enable_world_model:Phase 4+ 启用世界对象
            backend:           直接传入后端实例（覆盖 db_path）
        """
        if backend is None:
            if db_path is not None:
                from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
                backend = SQLiteMemoryBackend(db_path)
            else:
                from simple_harness_memory.backends.mock import MockMemoryBackend
                backend = MockMemoryBackend()

        await backend.initialize()

        world: WorldModelPort = _NullWorldModel()
        # Phase 4: 真实世界对象将在此注入

        return cls(backend=backend, world=world)

    # ── 代理到后端 ────────────────────────────────────

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> int:
        return await self._backend.append_message(
            session_id, role, content,
            salience=salience,
            decay_rate=decay_rate,
        )

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[Message]:
        return await self._backend.get_recent_messages(session_id, limit)

    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[Hit]:
        return await self._backend.recall(query, session_id, limit)

    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> list[Fact]:
        return await self._backend.get_facts(subject, category, active_only)

    async def get_digital_twin(self, subject: str = "user") -> DigitalTwin:
        return await self._backend.get_digital_twin(subject)

    async def update_digital_twin(self, twin: DigitalTwin) -> None:
        await self._backend.update_digital_twin(twin)

    async def suggest_questions(self, subject: str = "user") -> list[str]:
        return await self._backend.suggest_questions(subject)

    async def daily_decay(self) -> dict[str, int]:
        return await self._backend.daily_decay()

    async def close(self) -> None:
        await self._backend.close()

    async def __aenter__(self) -> "MemoryManager":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
