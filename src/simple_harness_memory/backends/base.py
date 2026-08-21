"""Shared, user-scoped memory behavior for durable and mock backends."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import Any, overload

import structlog

from simple_harness_memory.cognitive.decay import (
    bump_salience,
    decay_salience,
    should_forget,
)
from simple_harness_memory.cognitive.twin_builder import (
    build_twin_from_facts,
    detect_fact_conflicts,
)
from simple_harness_memory.config import DEFAULT_BOUNDS, MemoryResourceBounds
from simple_harness_memory.core.conversation import (
    canonical_json,
    canonical_message_payload_hash,
    canonical_recall_query_hash,
    canonicalize_memory_text,
    validate_digest,
    validate_identity,
)
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryUnsupportedOperation,
    MemoryValidationError,
)
from simple_harness_memory.core.models import (
    SINGLE_VALUED_KEYS,
    BoundedRecallResult,
    Fact,
    FactConflict,
    Hit,
    MemoryApplyResult,
    MemoryApplyStatus,
    Message,
    RecallStatus,
)
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.embedders.base import (
    EMBEDDING_FORMAT_VERSION,
    encode_vector,
)
from simple_harness_memory.embedders.mock import HashEmbedder
from simple_harness_memory.features.facts import RuleBasedFactExtractor
from simple_harness_memory.features.reranker import IdentityReranker
from simple_harness_memory.features.retriever import Retriever
from simple_harness_memory.features.summarizer import RuleBasedSummarizer

logger = structlog.get_logger("simple_harness_memory.backends.base")


class BaseMemoryBackend(MemoryBackend):
    def __init__(
        self,
        *,
        embedder=None,
        fact_extractor=None,
        reranker=None,
        summarizer=None,
        auto_extract_facts: bool = False,
        bounds: MemoryResourceBounds | None = None,
        max_content_chars: int | None = None,
        max_fact_value_chars: int | None = None,
        max_payload_bytes: int | None = None,
        max_db_bytes: int | None = None,
    ) -> None:
        base = bounds or DEFAULT_BOUNDS
        self._bounds = MemoryResourceBounds(
            max_content_chars=(
                base.max_content_chars if max_content_chars is None else max_content_chars
            ),
            max_fact_value_chars=(
                base.max_fact_value_chars
                if max_fact_value_chars is None
                else max_fact_value_chars
            ),
            max_payload_bytes=(
                base.max_payload_bytes if max_payload_bytes is None else max_payload_bytes
            ),
            max_db_bytes=max_db_bytes if max_db_bytes is not None else base.max_db_bytes,
            recall_candidate_messages=base.recall_candidate_messages,
            recall_candidate_facts=base.recall_candidate_facts,
            recall_max_results=base.recall_max_results,
            recall_max_bytes=base.recall_max_bytes,
            recall_timeout_seconds=base.recall_timeout_seconds,
            maintenance_batch_size=base.maintenance_batch_size,
            summary_messages_per_session=base.summary_messages_per_session,
            context_result_dedupe_seconds=base.context_result_dedupe_seconds,
        )
        self._embedder = embedder or HashEmbedder()
        self._fact_extractor = fact_extractor or RuleBasedFactExtractor()
        self._reranker = reranker or IdentityReranker()
        self._summarizer = summarizer or RuleBasedSummarizer()
        self._retriever = Retriever(self._embedder, self._reranker)
        self._auto_extract_facts = auto_extract_facts

    async def _commit(self) -> None:
        return None

    @asynccontextmanager
    async def _transaction(self):
        yield

    async def _check_db_size(self) -> None:
        return None

    @abstractmethod
    async def _ensure_session_impl(self, user_id: str, session_id: str) -> None: ...

    @abstractmethod
    async def _append_message_impl(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        embedding: bytes | None,
        salience: float,
        decay_rate: float,
        created_at: float,
        is_summary: bool,
        summary_of: str | None,
        source_event_id: str,
        payload_hash: str,
        embedder_kind: str | None,
        embedding_dim: int | None,
        embedding_format_version: int | None,
    ) -> MemoryApplyResult: ...

    @abstractmethod
    async def _get_source_event_impl(
        self,
        user_id: str,
        source_event_id: str,
    ) -> tuple[int, str] | None: ...

    @abstractmethod
    async def _get_message_impl(self, user_id: str, message_id: int) -> Message | None: ...

    @abstractmethod
    async def _query_messages_impl(
        self,
        user_id: str,
        *,
        limit: int,
        session_id: str | None = None,
        older_than: float | None = None,
        lineage_mismatch: tuple[str, int, int] | None = None,
    ) -> list[Message]: ...

    @abstractmethod
    async def _query_facts_impl(
        self,
        user_id: str,
        *,
        limit: int,
        subject: str | None = None,
        category: str | None = None,
        active_only: bool = False,
    ) -> list[Fact]: ...

    @abstractmethod
    async def _insert_fact_impl(self, user_id: str, fact: Fact) -> int: ...

    @abstractmethod
    async def _supersede_fact_impl(
        self,
        user_id: str,
        fact_id: int,
        superseded_by: int,
    ) -> None: ...

    @abstractmethod
    async def _forget_fact_by_id_impl(
        self,
        user_id: str,
        fact_id: int,
        forgotten_at: float,
    ) -> bool: ...

    @abstractmethod
    async def _update_message_salience_impl(
        self,
        user_id: str,
        message_id: int,
        salience: float,
        last_recalled: float | None,
    ) -> None: ...

    @abstractmethod
    async def _set_fact_decay_impl(
        self,
        user_id: str,
        fact_id: int,
        *,
        forgotten_at: float | None = None,
        last_decay_at: float | None = None,
    ) -> None: ...

    @abstractmethod
    async def _load_twin_impl(self, user_id: str, subject: str) -> DigitalTwin: ...

    @abstractmethod
    async def _save_twin_impl(self, user_id: str, twin: DigitalTwin) -> None: ...

    @abstractmethod
    async def _record_workspace_impl(
        self,
        user_id: str,
        session_id: str,
        action_type: str,
        payload: dict,
    ) -> None: ...

    @abstractmethod
    async def _delete_session_impl(self, user_id: str, session_id: str) -> int: ...

    @abstractmethod
    async def _old_session_ids_impl(
        self,
        user_id: str,
        cutoff: float,
        limit: int,
    ) -> list[str]: ...

    @abstractmethod
    async def _update_embedding_impl(
        self,
        user_id: str,
        message_id: int,
        embedding: bytes,
        embedder_kind: str,
        embedding_dim: int,
        embedding_format_version: int,
    ) -> None: ...

    @abstractmethod
    async def _get_recall_snapshot_impl(
        self,
        user_id: str,
        context_query_id: str,
    ) -> tuple[str, str, str, str, str] | None: ...

    @abstractmethod
    async def _insert_recall_snapshot_impl(
        self,
        *,
        context_query_id: str,
        user_id: str,
        session_id: str,
        query_hash: str,
        result_payload: str,
        result_hash: str,
        created_at: float,
    ) -> None: ...

    @abstractmethod
    async def _release_recall_snapshot_impl(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
        released_at: float,
    ) -> bool: ...

    @abstractmethod
    async def _cleanup_recall_snapshots_impl(
        self,
        *,
        user_id: str,
        released_before: float,
        limit: int,
    ) -> int: ...

    @overload
    def _identity(self, user_id: str, session_id: str) -> tuple[str, str]: ...

    @overload
    def _identity(self, user_id: str, session_id: None = None) -> tuple[str, None]: ...

    def _identity(self, user_id: str, session_id: str | None = None) -> tuple[str, str | None]:
        user_id = validate_identity(user_id, "user_id")
        if session_id is not None:
            session_id = validate_identity(session_id, "session_id")
        return user_id, session_id

    def _check_content(self, content: str) -> str:
        canonical = canonicalize_memory_text(content)
        if len(canonical) > self._bounds.max_content_chars:
            raise MemoryLimitError("content exceeds max_content_chars")
        return canonical

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str,
        source_event_id: str,
        payload_hash: str | None = None,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> MemoryApplyResult:
        user_id, session_id = self._identity(user_id, session_id)
        assert session_id is not None
        source_event_id = validate_identity(source_event_id, "source_event_id")
        content = self._check_content(content)
        try:
            role = str(getattr(role, "value", role))
            expected_hash = canonical_message_payload_hash(
                source_event_id=source_event_id,
                user_id=user_id,
                session_id=session_id,
                role=role,
                memory_text=content,
            )
        except ValueError as exc:
            raise MemoryValidationError("role is not conversation-memory compatible") from exc
        if (
            payload_hash is not None
            and validate_digest(payload_hash, "payload_hash") != expected_hash
        ):
            raise MemoryIdempotencyConflict()
        existing = await self._get_source_event_impl(user_id, source_event_id)
        if existing is not None:
            message_id, saved_hash = existing
            if saved_hash != expected_hash:
                raise MemoryIdempotencyConflict()
            return MemoryApplyResult(
                message_id=message_id,
                source_event_id=source_event_id,
                payload_hash=expected_hash,
                status=MemoryApplyStatus.ALREADY_APPLIED,
            )
        await self._check_db_size()
        embedding = encode_vector(await self._embedder.embed(content))
        async with self._transaction():
            await self._ensure_session_impl(user_id, session_id)
            result = await self._append_message_impl(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                embedding=embedding,
                salience=salience,
                decay_rate=decay_rate,
                created_at=time.time(),
                is_summary=False,
                summary_of=None,
                source_event_id=source_event_id,
                payload_hash=expected_hash,
                embedder_kind=self._embedder.kind,
                embedding_dim=self._embedder.dim,
                embedding_format_version=EMBEDDING_FORMAT_VERSION,
            )
            if self._auto_extract_facts and role == "user" and result.status.value == "applied":
                await self.extract_facts(result.message_id, content, role, user_id=user_id)
        logger.info(
            "memory.append_message",
            user_id=user_id,
            session_id=session_id,
            source_event_id=source_event_id,
            payload_hash=expected_hash,
            status=result.status.value,
            content_len=len(content),
        )
        return result

    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Message]:
        user_id, session_id = self._identity(user_id, session_id)
        assert session_id is not None
        return list(
            reversed(
                await self._query_messages_impl(
                    user_id, session_id=session_id, limit=self._bounded_limit(limit)
                )
            )
        )

    async def get_message(self, message_id: int, *, user_id: str) -> Message | None:
        user_id, _ = self._identity(user_id)
        return await self._get_message_impl(user_id, message_id)

    async def extract_facts(
        self,
        message_id: int,
        content: str,
        role: str,
        *,
        user_id: str,
    ) -> list[Fact]:
        user_id, _ = self._identity(user_id)
        source_message = await self._get_message_impl(user_id, message_id)
        if source_message is None:
            raise MemoryValidationError("source message is not owned by user")
        await self._check_db_size()
        facts = await self._fact_extractor.extract(
            content,
            role=role,
            message_id=message_id,
            created_at=time.time(),
            subject="user",
            user_id=user_id,
        )
        stored: list[Fact] = []
        for fact in facts[: self._bounds.maintenance_batch_size]:
            fact.user_id = user_id
            fact.source_msg_id = message_id
            if (
                len(fact.value) > self._bounds.max_fact_value_chars
                or len(fact.evidence) > self._bounds.max_fact_value_chars
            ):
                raise MemoryLimitError("fact value/evidence exceeds max_fact_value_chars")
            new_id = await self._insert_fact_impl(user_id, fact)
            fact.id = new_id
            stored.append(fact)
            if fact.key in SINGLE_VALUED_KEYS:
                old_facts = await self._query_facts_impl(
                    user_id,
                    limit=self._bounds.recall_candidate_facts,
                    subject=fact.subject,
                    active_only=True,
                )
                for old in old_facts:
                    if old.key == fact.key and old.id != new_id and old.id is not None:
                        await self._supersede_fact_impl(user_id, old.id, new_id)
        await self._commit()
        logger.info(
            "memory.extract_facts", user_id=user_id, message_id=message_id, fact_count=len(stored)
        )
        return stored

    async def get_facts(
        self,
        subject: str = "user",
        category: str | None = None,
        active_only: bool = True,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> list[Fact]:
        user_id, _ = self._identity(user_id)
        return await self._query_facts_impl(
            user_id,
            limit=self._bounded_limit(limit or self._bounds.recall_candidate_facts),
            subject=subject,
            category=category,
            active_only=active_only,
        )

    async def forget_fact(self, fact_id: int, reason: str = "", *, user_id: str) -> bool:
        user_id, _ = self._identity(user_id)
        result = await self._forget_fact_by_id_impl(user_id, fact_id, time.time())
        await self._commit()
        return result

    async def get_digital_twin(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> DigitalTwin:
        user_id, _ = self._identity(user_id)
        base = await self._load_twin_impl(user_id, subject)
        facts = await self._query_facts_impl(
            user_id,
            limit=self._bounds.recall_candidate_facts,
            subject=subject,
            active_only=True,
        )
        return build_twin_from_facts(facts, base, subject)

    async def update_digital_twin(self, twin: DigitalTwin, *, user_id: str) -> None:
        user_id, _ = self._identity(user_id)
        await self._check_db_size()
        twin.last_updated = time.time()
        twin.recalculate_completeness()
        await self._save_twin_impl(user_id, twin)
        await self._commit()

    async def suggest_questions(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[str]:
        twin = await self.get_digital_twin(subject, user_id=user_id)
        q_map = {
            "name": "你叫什么名字？",
            "occupation": "你是做什么工作的？",
            "location": "你在哪个城市？",
            "language": "你常用的语言是什么？",
        }
        return [q_map[field] for field in twin.missing_profile_fields() if field in q_map]

    async def detect_inconsistencies(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[FactConflict]:
        return detect_fact_conflicts(
            await self.get_facts(subject, active_only=True, user_id=user_id)
        )

    async def _compute_recall(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str | None,
        limit: int,
    ) -> tuple[list[Hit], bool]:
        message_cap = self._bounds.recall_candidate_messages
        fact_cap = self._bounds.recall_candidate_facts
        messages = await self._query_messages_impl(user_id, limit=message_cap + 1)
        facts = await self._query_facts_impl(user_id, limit=fact_cap + 1, active_only=True)
        truncated = len(messages) > message_cap or len(facts) > fact_cap
        messages = messages[:message_cap]
        facts = facts[:fact_cap]
        twin = build_twin_from_facts(facts, base=None, subject="user")
        hits = await self._retriever.recall(
            query,
            messages=messages,
            facts=facts,
            twin=twin,
            session_id=session_id,
            limit=limit + 1,
        )
        if len(hits) > limit:
            truncated = True
        return hits[:limit], truncated

    async def recall(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]:
        user_id, session_id = self._identity(user_id, session_id)
        if session_id is not None:
            await self._ensure_session_impl(user_id, session_id)
            await self._commit()
        query = canonicalize_memory_text(query)
        hits, _ = await self._compute_recall(
            query,
            user_id=user_id,
            session_id=session_id,
            limit=self._bounded_limit(limit),
        )
        logger.info(
            "memory.recall",
            user_id=user_id,
            session_id=session_id,
            query_len=len(query),
            hit_count=len(hits),
        )
        return hits

    async def recall_bounded(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context_query_id: str,
        query_hash: str | None = None,
        max_results: int | None = None,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
    ) -> BoundedRecallResult:
        user_id, session_id = self._identity(user_id, session_id)
        assert session_id is not None
        context_query_id = validate_identity(context_query_id, "context_query_id")
        query = canonicalize_memory_text(query)
        requested_results = (
            self._bounds.recall_max_results if max_results is None else max_results
        )
        if (
            isinstance(requested_results, bool)
            or not isinstance(requested_results, int)
            or requested_results <= 0
        ):
            raise MemoryValidationError("max_results must be a positive integer")
        requested_bytes = self._bounds.recall_max_bytes if max_bytes is None else max_bytes
        if (
            isinstance(requested_bytes, bool)
            or not isinstance(requested_bytes, int)
            or requested_bytes <= 0
        ):
            raise MemoryValidationError("max_bytes must be a positive integer")
        effective_results = min(requested_results, self._bounds.recall_max_results)
        effective_bytes = min(requested_bytes, self._bounds.recall_max_bytes)
        if effective_bytes < len(
            canonical_json({"items": [], "status": "truncated"}).encode("utf-8")
        ):
            raise MemoryValidationError("max_bytes is too small for a recall result")
        if timeout_seconds is None:
            timeout_seconds = self._bounds.recall_timeout_seconds
        elif (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise MemoryValidationError("timeout_seconds must be positive")
        timeout_seconds = min(timeout_seconds, self._bounds.recall_timeout_seconds)
        expected_query_hash = canonical_recall_query_hash(
            user_id=user_id,
            session_id=session_id,
            query_text=query,
            max_items=requested_results,
            max_bytes=requested_bytes,
        )
        if (
            query_hash is not None
            and validate_digest(query_hash, "query_hash") != expected_query_hash
        ):
            raise MemoryIdempotencyConflict()
        query_hash = expected_query_hash
        async with self._transaction():
            existing = await self._get_recall_snapshot_impl(user_id, context_query_id)
            if existing is not None:
                saved_user, saved_session, saved_query_hash, payload_json, result_hash = existing
                if (saved_user, saved_session, saved_query_hash) != (
                    user_id,
                    session_id,
                    query_hash,
                ):
                    raise MemoryIdempotencyConflict()
                return self._decode_recall_result(
                    context_query_id=context_query_id,
                    query_hash=query_hash,
                    payload_json=payload_json,
                    result_hash=result_hash,
                    replayed=True,
                )
            await self._ensure_session_impl(user_id, session_id)
            try:
                async with asyncio.timeout(timeout_seconds):
                    hits, truncated = await self._compute_recall(
                        query,
                        user_id=user_id,
                        session_id=session_id,
                        limit=effective_results,
                    )
                status = RecallStatus.TRUNCATED if truncated else RecallStatus.COMPLETE
            except TimeoutError:
                hits = []
                status = RecallStatus.TIMEOUT
            hits, status, payload_json = self._fit_recall_payload(
                hits, status=status, max_bytes=effective_bytes
            )
            result_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            await self._insert_recall_snapshot_impl(
                context_query_id=context_query_id,
                user_id=user_id,
                session_id=session_id,
                query_hash=query_hash,
                result_payload=payload_json,
                result_hash=result_hash,
                created_at=time.time(),
            )
        logger.info(
            "memory.recall_bounded",
            user_id=user_id,
            context_query_id=context_query_id,
            query_hash=query_hash,
            result_hash=result_hash,
            status=status.value,
            item_count=len(hits),
            result_bytes=len(payload_json.encode("utf-8")),
        )
        return BoundedRecallResult(
            hits=tuple(hits),
            status=status,
            result_hash=result_hash,
            result_bytes=len(payload_json.encode("utf-8")),
            context_query_id=context_query_id,
            query_hash=query_hash,
        )

    def _fit_recall_payload(
        self,
        hits: list[Hit],
        *,
        status: RecallStatus,
        max_bytes: int,
    ) -> tuple[list[Hit], RecallStatus, str]:
        selected: list[Hit] = []
        for hit in hits:
            candidate = selected + [hit]
            candidate_status = status
            payload = self._recall_payload(candidate, candidate_status)
            if len(canonical_json(payload).encode("utf-8")) > max_bytes:
                status = RecallStatus.TRUNCATED
                break
            selected = candidate
        if len(selected) != len(hits):
            status = RecallStatus.TRUNCATED
        payload_json = canonical_json(self._recall_payload(selected, status))
        if len(payload_json.encode("utf-8")) > max_bytes:
            while selected and len(payload_json.encode("utf-8")) > max_bytes:
                selected.pop()
                status = RecallStatus.TRUNCATED
                payload_json = canonical_json(self._recall_payload(selected, status))
        return selected, status, payload_json

    @staticmethod
    def _recall_payload(hits: list[Hit], status: RecallStatus) -> dict[str, Any]:
        result = BoundedRecallResult(
            hits=tuple(hits), status=status, result_hash="", result_bytes=0
        )
        return result.as_payload()

    def _decode_recall_result(
        self,
        *,
        context_query_id: str,
        query_hash: str,
        payload_json: str,
        result_hash: str,
        replayed: bool,
    ) -> BoundedRecallResult:
        if hashlib.sha256(payload_json.encode("utf-8")).hexdigest() != result_hash:
            raise MemoryIdempotencyConflict()
        payload = json.loads(payload_json)
        hits = tuple(Hit(**item) for item in payload.get("items", []))
        status = RecallStatus(payload["status"])
        return BoundedRecallResult(
            hits=hits,
            status=status,
            result_hash=result_hash,
            result_bytes=len(payload_json.encode("utf-8")),
            context_query_id=context_query_id,
            query_hash=query_hash,
            replayed=replayed,
        )

    async def release_recall_result(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
    ) -> None:
        user_id, _ = self._identity(user_id)
        validate_identity(context_query_id, "context_query_id")
        validate_digest(result_hash, "result_hash")
        released = await self._release_recall_snapshot_impl(
            user_id=user_id,
            context_query_id=context_query_id,
            result_hash=result_hash,
            released_at=time.time(),
        )
        if not released:
            raise MemoryIdempotencyConflict()
        await self._commit()

    async def cleanup_recall_results(
        self,
        *,
        user_id: str,
        now: float | None = None,
        limit: int | None = None,
    ) -> int:
        user_id, _ = self._identity(user_id)
        cutoff = (now or time.time()) - self._bounds.context_result_dedupe_seconds
        deleted = await self._cleanup_recall_snapshots_impl(
            user_id=user_id,
            released_before=cutoff,
            limit=self._bounded_limit(limit or self._bounds.maintenance_batch_size),
        )
        await self._commit()
        return deleted

    async def recall_and_reinforce(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]:
        hits = await self.recall(query, session_id, limit, user_id=user_id)
        now = time.time()
        for hit in hits:
            bumped = bump_salience(hit.salience)
            await self._update_message_salience_impl(user_id, hit.message_id, bumped, now)
            hit.salience = bumped
        await self._commit()
        return hits

    async def vector_search(
        self,
        query: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Hit]:
        user_id, _ = self._identity(user_id)
        messages = await self._query_messages_impl(
            user_id, limit=self._bounds.recall_candidate_messages
        )
        return await self._retriever.vector_search(
            canonicalize_memory_text(query),
            messages=messages,
            limit=self._bounded_limit(limit),
        )

    async def daily_decay(
        self,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> dict[str, int]:
        user_id, _ = self._identity(user_id)
        cap = self._bounded_limit(limit or self._bounds.maintenance_batch_size)
        now = time.time()
        decayed = 0
        forgotten = 0
        messages = await self._query_messages_impl(user_id, limit=cap)
        facts = await self._query_facts_impl(user_id, limit=cap, active_only=True)
        for message in messages:
            ref = message.last_recalled or message.created_at
            days = (now - ref) / 86400.0
            new_salience = decay_salience(message.salience, message.decay_rate, days)
            if abs(new_salience - message.salience) > 1e-9 and message.id is not None:
                await self._update_message_salience_impl(user_id, message.id, new_salience, None)
                decayed += 1
        for fact in facts:
            if fact.pinned or fact.id is None:
                continue
            ref = fact.last_decay_at or fact.created_at
            days = (now - ref) / 86400.0
            if should_forget(fact.decay_rate, days):
                await self._set_fact_decay_impl(user_id, fact.id, forgotten_at=now)
                forgotten += 1
            else:
                await self._set_fact_decay_impl(user_id, fact.id, last_decay_at=now)
                decayed += 1
        await self._commit()
        return {"decayed": decayed, "forgotten": forgotten}

    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
        *,
        user_id: str,
    ) -> dict[str, int]:
        user_id, _ = self._identity(user_id)
        max_sessions = self._bounded_limit(max_sessions)
        cutoff = time.time() - older_than_days * 86400.0
        sessions = await self._old_session_ids_impl(user_id, cutoff, max_sessions)
        count = 0
        for session_id in sessions:
            messages = list(
                reversed(
                    await self._query_messages_impl(
                        user_id,
                        session_id=session_id,
                        older_than=cutoff,
                        limit=self._bounds.summary_messages_per_session,
                    )
                )
            )
            messages = [message for message in messages if not message.is_summary]
            summary = await self._summarizer.summarize(messages)
            if not summary:
                continue
            source_ids = [message.id for message in messages]
            source_event_id = (
                "memory-summary/v1/"
                + hashlib.sha256(
                    canonical_json(
                        {
                            "user_id": user_id,
                            "session_id": session_id,
                            "source_ids": source_ids,
                        }
                    ).encode("utf-8")
                ).hexdigest()
            )
            payload_hash = canonical_message_payload_hash(
                source_event_id=source_event_id,
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                memory_text=summary,
            )
            await self._append_message_impl(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=summary,
                embedding=None,
                salience=0.0,
                decay_rate=0.02,
                created_at=time.time(),
                is_summary=True,
                summary_of=canonical_json(source_ids),
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                embedder_kind=None,
                embedding_dim=None,
                embedding_format_version=None,
            )
            count += 1
        await self._commit()
        return {"summarized_sessions": count}

    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
        *,
        user_id: str,
    ) -> None:
        user_id, session_id = self._identity(user_id, session_id)
        assert session_id is not None
        encoded = canonical_json(payload)
        if len(encoded.encode("utf-8")) > self._bounds.max_payload_bytes:
            raise MemoryLimitError("payload exceeds max_payload_bytes")
        await self._check_db_size()
        await self._ensure_session_impl(user_id, session_id)
        await self._record_workspace_impl(user_id, session_id, action_type, payload)
        await self._commit()

    async def delete_session(self, session_id: str, *, user_id: str) -> int:
        user_id, session_id = self._identity(user_id, session_id)
        assert session_id is not None
        deleted = await self._delete_session_impl(user_id, session_id)
        await self._commit()
        await self._rebuild_twin(user_id=user_id)
        return deleted

    async def delete_all(self) -> None:
        raise MemoryUnsupportedOperation()

    async def delete_old_sessions(
        self,
        older_than_days: float = 30.0,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> int:
        user_id, _ = self._identity(user_id)
        cutoff = time.time() - older_than_days * 86400.0
        session_ids = await self._old_session_ids_impl(
            user_id,
            cutoff,
            self._bounded_limit(limit or self._bounds.maintenance_batch_size),
        )
        deleted = 0
        for session_id in session_ids:
            deleted += await self._delete_session_impl(user_id, session_id)
        await self._commit()
        if deleted:
            await self._rebuild_twin(user_id=user_id)
        return deleted

    async def _rebuild_twin(self, *, user_id: str, subject: str = "user") -> None:
        facts = await self._query_facts_impl(
            user_id,
            limit=self._bounds.recall_candidate_facts,
            subject=subject,
            active_only=True,
        )
        await self._save_twin_impl(
            user_id, build_twin_from_facts(facts, base=None, subject=subject)
        )
        await self._commit()

    async def reindex(
        self,
        embedder=None,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> int:
        user_id, _ = self._identity(user_id)
        new_embedder = embedder or self._embedder
        cap = self._bounded_limit(limit or self._bounds.maintenance_batch_size)
        messages = await self._query_messages_impl(
            user_id,
            limit=cap,
            lineage_mismatch=(new_embedder.kind, new_embedder.dim, EMBEDDING_FORMAT_VERSION),
        )
        vectors = await new_embedder.embed_batch([message.content for message in messages])
        for message, vector in zip(messages, vectors):
            if message.id is not None:
                await self._update_embedding_impl(
                    user_id,
                    message.id,
                    encode_vector(vector),
                    new_embedder.kind,
                    new_embedder.dim,
                    EMBEDDING_FORMAT_VERSION,
                )
        await self._commit()
        self._embedder = new_embedder
        self._retriever = Retriever(new_embedder, self._reranker)
        return len(messages)

    def _bounded_limit(self, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise MemoryValidationError("limit must be a positive integer")
        return min(value, self._bounds.maintenance_batch_size * 16)
