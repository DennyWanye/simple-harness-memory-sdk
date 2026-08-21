"""Harness-neutral conversation-memory adapter and canonical wire domain.

This module intentionally does not import ``simple_harness``.  Its dataclasses
mirror the public structural port so consumers can translate (or use them
duck-typed) without coupling the two SDK packages.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from simple_harness_memory.core.errors import (
    EmbeddingError,
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.models import MemoryApplyStatus


class ConversationMemoryRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ContextPreparationMode(StrEnum):
    SDK_PREPARED = "sdk_prepared"
    CONSUMER_PREPARED = "consumer_prepared"


class ConversationMemoryQueryStatus(StrEnum):
    COMPLETE = "complete"
    TRUNCATED = "truncated"
    TIMEOUT = "timeout"


class ConversationMemoryApplyStatus(StrEnum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"


class ConversationMemoryErrorCode(StrEnum):
    QUERY_CONFLICT = "memory_query_conflict"
    APPLY_CONFLICT = "memory_apply_conflict"
    TRANSIENT = "memory_transient"
    PERMANENT = "memory_permanent"
    TIMEOUT = "memory_timeout"


class ConversationMemoryError(RuntimeError):
    def __init__(self, code: ConversationMemoryErrorCode) -> None:
        self.code = ConversationMemoryErrorCode(code)
        super().__init__(self.code.value)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonicalize_memory_text(value: str) -> str:
    if not isinstance(value, str):
        raise MemoryValidationError("memory_text must be a string")
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise MemoryValidationError("memory_text must be non-empty")
    if "\x00" in normalized:
        raise MemoryValidationError("memory_text must not contain NUL")
    return normalized


def validate_identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{name} is required")
    return value


def validate_digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MemoryValidationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def canonical_message_payload_hash(
    *,
    source_event_id: str,
    user_id: str,
    session_id: str,
    role: str | ConversationMemoryRole,
    memory_text: str | None,
) -> str:
    role_value = ConversationMemoryRole(role).value
    canonical_text = None if memory_text is None else canonicalize_memory_text(memory_text)
    payload = {
        "protocol": "harness-conversation-memory-intent-v1",
        "source_event_id": validate_identity(source_event_id, "source_event_id"),
        "user_id": validate_identity(user_id, "user_id"),
        "session_id": validate_identity(session_id, "session_id"),
        "role": role_value,
        "memory_text": canonical_text,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_recall_query_hash(
    *,
    user_id: str,
    session_id: str,
    query_text: str,
    max_items: int,
    max_bytes: int,
) -> str:
    canonical = canonicalize_memory_text(query_text)
    payload = {
        "protocol": "harness-memory-context-query-v1",
        "user_id": validate_identity(user_id, "user_id"),
        "session_id": validate_identity(session_id, "session_id"),
        "query_text": canonical,
        "max_items": _positive_int(max_items, "max_items"),
        "max_bytes": _positive_int(max_bytes, "max_bytes"),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ConversationMemoryRecallQuery:
    context_query_id: str
    user_id: str
    session_id: str
    query_text: str
    query_hash: str
    max_items: int
    max_bytes: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        validate_identity(self.context_query_id, "context_query_id")
        canonical = canonicalize_memory_text(self.query_text)
        expected = canonical_recall_query_hash(
            user_id=self.user_id,
            session_id=self.session_id,
            query_text=canonical,
            max_items=self.max_items,
            max_bytes=self.max_bytes,
        )
        if validate_digest(self.query_hash, "query_hash") != expected:
            raise MemoryValidationError("query_hash differs from canonical query")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise MemoryValidationError("timeout_seconds must be positive")
        object.__setattr__(self, "query_text", canonical)

    @classmethod
    def create(
        cls,
        *,
        context_query_id: str,
        user_id: str,
        session_id: str,
        query_text: str,
        max_items: int,
        max_bytes: int,
        timeout_seconds: float,
    ) -> ConversationMemoryRecallQuery:
        query_hash = canonical_recall_query_hash(
            user_id=user_id,
            session_id=session_id,
            query_text=query_text,
            max_items=max_items,
            max_bytes=max_bytes,
        )
        return cls(
            context_query_id=context_query_id,
            user_id=user_id,
            session_id=session_id,
            query_text=query_text,
            query_hash=query_hash,
            max_items=max_items,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ConversationMemoryRecallResult:
    context_query_id: str
    result_id: str
    query_hash: str
    payload: Mapping[str, Any]
    result_hash: str
    status: ConversationMemoryQueryStatus
    item_count: int
    byte_count: int

    def __post_init__(self) -> None:
        validate_identity(self.context_query_id, "context_query_id")
        validate_identity(self.result_id, "result_id")
        validate_digest(self.query_hash, "query_hash")
        validate_digest(self.result_hash, "result_hash")
        status = ConversationMemoryQueryStatus(self.status)
        try:
            payload = json.loads(canonical_json(dict(self.payload)))
            canonical = canonical_json(payload)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("payload must be canonical JSON") from exc
        actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if actual_hash != self.result_hash:
            raise MemoryValidationError("result_hash differs from canonical result payload")
        for name in ("item_count", "byte_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MemoryValidationError(f"{name} must be a non-negative integer")
        if len(canonical.encode("utf-8")) != self.byte_count:
            raise MemoryValidationError("byte_count differs from canonical result payload")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class ConversationMemoryIntent:
    source_event_id: str
    user_id: str
    session_id: str
    role: ConversationMemoryRole
    memory_text: str | None
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        role = ConversationMemoryRole(self.role)
        canonical = None if self.memory_text is None else canonicalize_memory_text(self.memory_text)
        payload_hash = canonical_message_payload_hash(
            source_event_id=self.source_event_id,
            user_id=self.user_id,
            session_id=self.session_id,
            role=role,
            memory_text=canonical,
        )
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "memory_text", canonical)
        object.__setattr__(self, "payload_hash", payload_hash)


@dataclass(frozen=True, slots=True)
class ConversationMemoryApplyResult:
    source_event_id: str
    payload_hash: str
    status: ConversationMemoryApplyStatus
    record_id: str

    def __post_init__(self) -> None:
        validate_identity(self.source_event_id, "source_event_id")
        validate_identity(self.record_id, "record_id")
        validate_digest(self.payload_hash, "payload_hash")
        object.__setattr__(self, "status", ConversationMemoryApplyStatus(self.status))


class _IntentLike(Protocol):
    source_event_id: str
    user_id: str
    session_id: str
    role: object
    memory_text: str | None
    payload_hash: str


class _RecallQueryLike(Protocol):
    context_query_id: str
    user_id: str
    session_id: str
    query_text: str
    query_hash: str
    max_items: int
    max_bytes: int
    timeout_seconds: float


class ConversationMemoryAdapter:
    """One idempotent adapter implementing both conversation port shapes."""

    def __init__(self, backend: Any, *, close_backend: bool = True) -> None:
        self._backend = backend
        self._close_backend = close_backend
        self._closed = False

    async def apply(self, intent: _IntentLike) -> ConversationMemoryApplyResult:
        if intent.memory_text is None:
            raise ConversationMemoryError(ConversationMemoryErrorCode.PERMANENT)
        try:
            role = ConversationMemoryRole(
                str(getattr(intent.role, "value", intent.role))
            )
            result = await self._backend.append_message(
                intent.session_id,
                role.value,
                intent.memory_text,
                user_id=intent.user_id,
                source_event_id=intent.source_event_id,
                payload_hash=intent.payload_hash,
            )
        except MemoryIdempotencyConflict as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.APPLY_CONFLICT) from exc
        except TimeoutError as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TIMEOUT) from exc
        except (
            MemoryCorruptionError,
            MemoryLimitError,
            MemoryOwnershipConflict,
            MemoryValidationError,
            ValueError,
        ) as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.PERMANENT) from exc
        except EmbeddingError as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TRANSIENT) from exc
        except Exception as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TRANSIENT) from exc
        status = (
            ConversationMemoryApplyStatus.APPLIED
            if result.status is MemoryApplyStatus.APPLIED
            else ConversationMemoryApplyStatus.ALREADY_APPLIED
        )
        return ConversationMemoryApplyResult(
            source_event_id=result.source_event_id,
            payload_hash=result.payload_hash,
            status=status,
            record_id=str(result.message_id),
        )

    async def recall_bounded(
        self,
        query: _RecallQueryLike,
    ) -> ConversationMemoryRecallResult:
        try:
            result = await self._backend.recall_bounded(
                query.query_text,
                user_id=query.user_id,
                session_id=query.session_id,
                context_query_id=query.context_query_id,
                query_hash=query.query_hash,
                max_results=query.max_items,
                max_bytes=query.max_bytes,
                timeout_seconds=query.timeout_seconds,
            )
        except MemoryIdempotencyConflict as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.QUERY_CONFLICT) from exc
        except TimeoutError as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TIMEOUT) from exc
        except (
            MemoryCorruptionError,
            MemoryLimitError,
            MemoryOwnershipConflict,
            MemoryValidationError,
            ValueError,
        ) as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.PERMANENT) from exc
        except EmbeddingError as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TRANSIENT) from exc
        except Exception as exc:
            raise ConversationMemoryError(ConversationMemoryErrorCode.TRANSIENT) from exc
        payload = result.as_payload()
        byte_count = len(canonical_json(payload).encode("utf-8"))
        return ConversationMemoryRecallResult(
            context_query_id=query.context_query_id,
            result_id=f"memory-recall/v1/{query.context_query_id}",
            query_hash=result.query_hash or query.query_hash,
            payload=payload,
            result_hash=result.result_hash,
            status=ConversationMemoryQueryStatus(result.status.value),
            item_count=len(result.hits),
            byte_count=byte_count,
        )

    async def release(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
    ) -> None:
        await self._backend.release_recall_result(
            user_id=user_id,
            context_query_id=context_query_id,
            result_hash=result_hash,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._close_backend:
            await self._backend.close()


__all__ = (
    "ConversationMemoryAdapter",
    "ConversationMemoryApplyResult",
    "ConversationMemoryApplyStatus",
    "ConversationMemoryError",
    "ConversationMemoryErrorCode",
    "ConversationMemoryIntent",
    "ConversationMemoryQueryStatus",
    "ConversationMemoryRecallQuery",
    "ConversationMemoryRecallResult",
    "ConversationMemoryRole",
    "ContextPreparationMode",
    "canonical_message_payload_hash",
    "canonical_recall_query_hash",
    "canonicalize_memory_text",
)
