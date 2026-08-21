"""MemoryManager — explicit-user facade over a backend and world model."""

from __future__ import annotations

import structlog

from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.world.port import WorldModelPort

logger = structlog.get_logger("simple_harness_memory.core.manager")


class _NullWorldModel(WorldModelPort):
    async def get_temporal_context(self):
        from simple_harness_memory.world.temporal import build_temporal_context

        return build_temporal_context()

    async def get_recent_events(self, days=3):
        return []

    async def get_weather(self, location):
        return None

    async def check_knowledge_boundary(self, query):
        return None

    async def get_personalized_news(self, interests, categories=None):
        return []


class MemoryManager:
    def __init__(self, backend: MemoryBackend, world: WorldModelPort) -> None:
        self._backend = backend
        self.world = world

    @property
    def backend(self) -> MemoryBackend:
        return self._backend

    @classmethod
    async def build(
        cls,
        db_path=None,
        *,
        enable_facts=False,
        enable_world_model=False,
        backend=None,
        embedder=None,
        fact_extractor=None,
        reranker=None,
        summarizer=None,
        world=None,
        bounds: MemoryResourceBounds | None = None,
    ):
        if isinstance(embedder, str):
            from simple_harness_memory.embedders.factory import get_embedder

            embedder = get_embedder(embedder)
        if backend is None:
            kwargs = {
                "embedder": embedder,
                "fact_extractor": fact_extractor,
                "reranker": reranker,
                "summarizer": summarizer,
                "auto_extract_facts": enable_facts,
                "bounds": bounds,
            }
            if db_path is not None:
                from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

                backend = SQLiteMemoryBackend(db_path, **kwargs)
            else:
                from simple_harness_memory.backends.mock import MockMemoryBackend

                backend = MockMemoryBackend(**kwargs)
        await backend.initialize()
        if world is not None:
            world_model = world
        elif enable_world_model:
            from simple_harness_memory.world.model import WorldModel

            world_model = WorldModel()
        else:
            world_model = _NullWorldModel()
        logger.info(
            "memory.manager_built",
            backend_type=type(backend).__name__,
            enable_facts=enable_facts,
            enable_world_model=enable_world_model,
        )
        return cls(backend=backend, world=world_model)

    async def append_message(
        self,
        session_id,
        role,
        content,
        *,
        user_id,
        source_event_id,
        payload_hash=None,
        salience=0.0,
        decay_rate=0.02,
    ):
        return await self._backend.append_message(
            session_id,
            role,
            content,
            user_id=user_id,
            source_event_id=source_event_id,
            payload_hash=payload_hash,
            salience=salience,
            decay_rate=decay_rate,
        )

    async def get_recent_messages(self, session_id, limit=20, *, user_id):
        return await self._backend.get_recent_messages(session_id, limit, user_id=user_id)

    async def get_message(self, message_id, *, user_id):
        return await self._backend.get_message(message_id, user_id=user_id)

    async def extract_facts(self, message_id, content, role, *, user_id):
        return await self._backend.extract_facts(message_id, content, role, user_id=user_id)

    async def get_facts(
        self,
        subject="user",
        category=None,
        active_only=True,
        *,
        user_id,
        limit=None,
    ):
        return await self._backend.get_facts(
            subject,
            category,
            active_only,
            user_id=user_id,
            limit=limit,
        )

    async def forget_fact(self, fact_id, reason="", *, user_id):
        return await self._backend.forget_fact(fact_id, reason, user_id=user_id)

    async def recall(self, query, session_id=None, limit=10, *, user_id):
        return await self._backend.recall(query, session_id, limit, user_id=user_id)

    async def recall_bounded(self, query, **kwargs):
        return await self._backend.recall_bounded(query, **kwargs)

    async def release_recall_result(self, **kwargs):
        return await self._backend.release_recall_result(**kwargs)

    async def cleanup_recall_results(self, **kwargs):
        return await self._backend.cleanup_recall_results(**kwargs)

    async def recall_and_reinforce(self, query, session_id=None, limit=10, *, user_id):
        return await self._backend.recall_and_reinforce(query, session_id, limit, user_id=user_id)

    async def vector_search(self, query, limit=20, *, user_id):
        return await self._backend.vector_search(query, limit, user_id=user_id)

    async def get_digital_twin(self, subject="user", *, user_id):
        return await self._backend.get_digital_twin(subject, user_id=user_id)

    async def update_digital_twin(self, twin, *, user_id):
        await self._backend.update_digital_twin(twin, user_id=user_id)

    async def suggest_questions(self, subject="user", *, user_id):
        return await self._backend.suggest_questions(subject, user_id=user_id)

    async def detect_inconsistencies(self, subject="user", *, user_id):
        return await self._backend.detect_inconsistencies(subject, user_id=user_id)

    async def daily_decay(self, *, user_id, limit=None):
        return await self._backend.daily_decay(user_id=user_id, limit=limit)

    async def summarize_old_sessions(self, older_than_days=7, max_sessions=5, *, user_id):
        return await self._backend.summarize_old_sessions(
            older_than_days, max_sessions, user_id=user_id
        )

    async def record_workspace_action(self, session_id, action_type, payload, *, user_id):
        await self._backend.record_workspace_action(
            session_id, action_type, payload, user_id=user_id
        )

    async def delete_session(self, session_id, *, user_id):
        return await self._backend.delete_session(session_id, user_id=user_id)

    async def delete_all(self):
        await self._backend.delete_all()

    async def delete_old_sessions(self, older_than_days=30.0, *, user_id, limit=None):
        return await self._backend.delete_old_sessions(
            older_than_days, user_id=user_id, limit=limit
        )

    async def reindex(self, embedder=None, *, user_id, limit=None):
        return await self._backend.reindex(embedder, user_id=user_id, limit=limit)

    async def close(self):
        await self._backend.close()
        logger.info("memory.manager_closed", backend_type=type(self._backend).__name__)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
