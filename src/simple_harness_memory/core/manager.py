"""MemoryManager — explicit-user facade over a backend and world model."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.errors import (
    HarnessIntegrationExtraRequired,
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryProductionConfigurationError,
)
from simple_harness_memory.core.fact_jobs import FactJobWorker
from simple_harness_memory.core.identity import (
    ExportPage,
    MemoryPrincipal,
    MemoryScope,
    PrivacyReceipt,
    ScopeKind,
)
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.world.port import WorldModelPort

if TYPE_CHECKING:
    from simple_harness import (
        CommittedTurn,
        CommittedTurnReceipt,
        MemoryRecallRequest,
        MemoryRecallResult,
        MemoryReleaseRequest,
    )

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
    def __init__(
        self,
        backend: MemoryBackend,
        world: WorldModelPort,
        *,
        fact_worker: FactJobWorker | None = None,
    ) -> None:
        self._backend = backend
        self.world = world
        self._fact_worker = fact_worker
        self._closed = False

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
        worker = None
        if enable_facts and all(
            hasattr(backend, name)
            for name in ("recover_fact_jobs", "claim_fact_job", "apply_fact_job")
        ):
            worker = FactJobWorker(backend, backend._fact_extractor)
            await worker.start()
        return cls(backend=backend, world=world_model, fact_worker=worker)

    @classmethod
    async def build_development(cls, db_path=None, **kwargs):
        """Explicit development builder; deterministic hash embeddings are allowed."""

        return await cls.build(db_path, **kwargs)

    @classmethod
    async def build_production(
        cls,
        db_path,
        *,
        embedder=None,
        resource_path=None,
        **kwargs,
    ):
        """Build with an explicit production embedder and pre-resolved local resources."""

        if embedder is None or isinstance(embedder, str):
            raise MemoryProductionConfigurationError()
        if getattr(embedder, "kind", None) in {"hash", "mock"}:
            raise MemoryProductionConfigurationError()
        if resource_path is None:
            raise MemoryProductionConfigurationError("memory_embedding_resource_unavailable")
        pinned_resource = Path(resource_path)
        if not pinned_resource.is_absolute() or not pinned_resource.exists():
            raise MemoryProductionConfigurationError("memory_embedding_resource_unavailable")
        return await cls.build(db_path, embedder=embedder, **kwargs)

    @staticmethod
    def _harness() -> Any:
        try:
            import simple_harness
        except ImportError as exc:
            raise HarnessIntegrationExtraRequired() from exc
        return simple_harness

    @staticmethod
    def _principal(identity: object) -> MemoryPrincipal:
        return MemoryPrincipal(
            str(getattr(identity, "deployment_id")),
            str(getattr(identity, "household_id")),
            str(getattr(identity, "actor_id")),
            str(getattr(identity, "session_id")),
        )

    @staticmethod
    def _scope(scope: object) -> MemoryScope:
        return MemoryScope(
            ScopeKind(str(getattr(getattr(scope, "kind"), "value", getattr(scope, "kind")))),
            str(getattr(scope, "owner_id")),
        )

    async def recall_for_turn(self, request: MemoryRecallRequest) -> MemoryRecallResult:
        """Implement the canonical AgentMemoryPort without a consumer adapter."""

        harness = self._harness()
        principal = self._principal(request.identity)
        scopes = tuple(self._scope(scope) for scope in request.scopes)
        try:
            recall = getattr(self._backend, "agent_recall")
            async with asyncio.timeout(request.bounds.deadline_seconds):
                payload, fence, _replayed = await recall(
                    principal=principal,
                    scopes=scopes,
                    query_id=request.query_id,
                    query_hash=request.query_hash,
                    query_text=request.query_text,
                    max_items=request.bounds.max_items,
                    max_bytes=request.bounds.max_bytes,
                )
        except MemoryIdempotencyConflict as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except MemoryOwnershipConflict as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except TimeoutError as exc:
            fence = getattr(self._backend, "agent_failure_fence", lambda: None)()
            raise harness.AgentMemoryError(
                harness.AgentMemoryErrorCode.TIMEOUT, write_fence=fence
            ) from exc
        except AttributeError as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except Exception as exc:
            fence = getattr(self._backend, "agent_failure_fence", lambda: None)()
            raise harness.AgentMemoryError(
                harness.AgentMemoryErrorCode.TRANSIENT, write_fence=fence
            ) from exc
        items = payload.get("items", [])
        assert isinstance(items, list)
        status = (
            harness.MemoryRecallStatus.TRUNCATED
            if payload.get("truncated")
            else (harness.MemoryRecallStatus.READY if items else harness.MemoryRecallStatus.EMPTY)
        )
        byte_count = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        result = harness.MemoryRecallResult(
            request.query_id,
            request.query_hash,
            f"memory-recall/v1/{request.query_id}",
            payload,
            status,
            len(items),
            byte_count,
            fence,
        )
        logger.info(
            "memory.agent_recall",
            principal_id=principal.opaque_id,
            item_count=len(items),
            byte_count=byte_count,
            stable_code=status.value,
        )
        return result

    async def release_recall(self, request: MemoryReleaseRequest) -> None:
        harness = self._harness()
        try:
            release = getattr(self._backend, "agent_release")
            await release(
                query_id=request.query_id,
                query_hash=request.query_hash,
                result_hash=request.result_hash,
            )
        except MemoryIdempotencyConflict as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except Exception as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TRANSIENT) from exc

    async def record_committed_turn(self, request: CommittedTurn) -> CommittedTurnReceipt:
        harness = self._harness()
        principal = self._principal(request.identity)
        scope = self._scope(request.write_scope)
        try:
            record = getattr(self._backend, "agent_record_turn")
            status_value, receipt_id = await record(
                principal=principal,
                scope=scope,
                turn_id=request.turn_id,
                payload_hash=request.payload_hash,
                user_text=request.user_text,
                assistant_text=request.assistant_text,
                write_fence=request.write_fence,
                turn_started_at=request.turn_started_at,
            )
        except MemoryIdempotencyConflict as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.CONFLICT) from exc
        except MemoryOwnershipConflict as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.PERMANENT) from exc
        except TimeoutError as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TIMEOUT) from exc
        except Exception as exc:
            raise harness.AgentMemoryError(harness.AgentMemoryErrorCode.TRANSIENT) from exc
        if self._fact_worker is not None and status_value == "applied":
            self._fact_worker.notify()
        status = harness.CommittedTurnStatus(status_value)
        logger.info(
            "memory.committed_turn",
            principal_id=principal.opaque_id,
            turn_id=request.turn_id,
            stable_code=status.value,
        )
        return harness.CommittedTurnReceipt(
            request.turn_id, request.payload_hash, status, receipt_id
        )

    async def drain_fact_jobs(self) -> None:
        if self._fact_worker is not None:
            while await self._fact_worker.drain_once():
                pass

    async def export_principal(
        self,
        principal: MemoryPrincipal,
        *,
        scopes: tuple[MemoryScope, ...] | None = None,
        cursor: int = 0,
        limit: int = 100,
    ) -> ExportPage:
        selected = scopes or (
            MemoryScope.personal(principal.actor_id),
            MemoryScope.family(principal.household_id),
        )
        records, next_cursor = await getattr(self._backend, "agent_export")(
            principal, selected, cursor=cursor, limit=limit
        )
        return ExportPage(
            "simple-harness-memory/export/v1",
            tuple(records),
            None if next_cursor is None else str(next_cursor),
        )

    async def delete_principal(self, principal: MemoryPrincipal) -> PrivacyReceipt:
        return await self.delete_scope(
            principal,
            (
                MemoryScope.personal(principal.actor_id),
                MemoryScope.family(principal.household_id),
            ),
        )

    async def delete_scope(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> PrivacyReceipt:
        counts = await getattr(self._backend, "agent_delete_scopes")(principal, scopes)
        logger.info(
            "memory.privacy_delete",
            principal_id=principal.opaque_id,
            message_count=int(counts["messages"]),
            fact_count=int(counts["facts"]),
            stable_code="deleted",
        )
        return PrivacyReceipt(
            str(counts["receipt_id"]),
            int(counts["messages"]),
            int(counts["facts"]),
            int(counts["snapshots"]),
            int(counts["jobs"]),
        )

    async def share_fact(self, principal: MemoryPrincipal, fact_id: int) -> str:
        return await getattr(self._backend, "agent_share_fact")(principal, fact_id)

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

    async def forget_fact(
        self,
        fact_id,
        reason="",
        *,
        user_id=None,
        principal: MemoryPrincipal | None = None,
    ):
        if principal is not None:
            return await getattr(self._backend, "agent_forget_fact")(principal, fact_id)
        if user_id is None:
            raise TypeError("user_id or principal is required")
        return await self._backend.forget_fact(fact_id, reason, user_id=user_id)

    async def recall(self, query, session_id=None, limit=10, *, user_id):
        return await self._backend.recall(query, session_id, limit, user_id=user_id)

    async def recall_bounded(
        self,
        query,
        *,
        user_id,
        session_id,
        context_query_id,
        query_hash=None,
        max_results=None,
        max_bytes=None,
        timeout_seconds=None,
    ):
        return await self._backend.recall_bounded(
            query,
            user_id=user_id,
            session_id=session_id,
            context_query_id=context_query_id,
            query_hash=query_hash,
            max_results=max_results,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        )

    async def release_recall_result(
        self,
        *,
        user_id,
        context_query_id,
        result_hash,
    ):
        return await self._backend.release_recall_result(
            user_id=user_id,
            context_query_id=context_query_id,
            result_hash=result_hash,
        )

    async def cleanup_recall_results(
        self,
        *,
        user_id,
        now=None,
        limit=None,
    ):
        return await self._backend.cleanup_recall_results(
            user_id=user_id,
            now=now,
            limit=limit,
        )

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

    async def reindex_generation(self, embedder=None, *, page_size=None):
        operation = getattr(self._backend, "reindex_generation", None)
        if operation is None:
            raise RuntimeError("backend does not support embedding generations")
        return await operation(embedder, page_size=page_size)

    async def checkpoint(self, *, deadline_seconds=5.0):
        operation = getattr(self._backend, "checkpoint", None)
        if operation is None:
            raise RuntimeError("backend does not support checkpoints")
        return await operation(deadline_seconds=deadline_seconds)

    async def backup(self, destination):
        operation = getattr(self._backend, "backup", None)
        if operation is None:
            raise RuntimeError("backend does not support backups")
        return await operation(destination)

    async def restore_backup(self, backup):
        """Restore this manager's SQLite path after it has been explicitly closed."""

        if not self._closed:
            raise RuntimeError("memory_restore_requires_closed_manager")
        from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

        if not isinstance(self._backend, SQLiteMemoryBackend):
            raise RuntimeError("backend does not support restore")
        return await asyncio.to_thread(
            SQLiteMemoryBackend.restore_backup_sync, backup, self._backend._db_path
        )

    async def close(self):
        if self._fact_worker is not None:
            await self._fact_worker.close()
        await self._backend.close()
        self._closed = True
        logger.info("memory.manager_closed", backend_type=type(self._backend).__name__)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
