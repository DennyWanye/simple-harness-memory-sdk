"""Internal canonicalization and stable error translation helpers.

Harness owns the Agent Memory DTOs.  This module intentionally contains no
public adapter or duplicate wire dataclasses.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata

from simple_harness_memory.core.errors import (
    EmbeddingError,
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemoryValidationError,
)


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
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
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


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name} must be a positive integer")
    return value


def canonical_message_payload_hash(
    *,
    source_event_id: str,
    user_id: str,
    session_id: str,
    role: object,
    memory_text: str | None,
) -> str:
    role_value = str(getattr(role, "value", role))
    if role_value not in {"user", "assistant"}:
        raise MemoryValidationError("role is not conversation-memory compatible")
    canonical_text = None if memory_text is None else canonicalize_memory_text(memory_text)
    payload = {
        "protocol": "harness-conversation-memory-intent-v1",
        "source_event_id": validate_identity(source_event_id, "source_event_id"),
        "user_id": validate_identity(user_id, "user_id"),
        "session_id": validate_identity(session_id, "session_id"),
        "role": role_value,
        "memory_text": canonical_text,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def canonical_recall_query_hash(
    *,
    user_id: str,
    session_id: str,
    query_text: str,
    max_items: int,
    max_bytes: int,
) -> str:
    payload = {
        "protocol": "harness-memory-context-query-v1",
        "user_id": validate_identity(user_id, "user_id"),
        "session_id": validate_identity(session_id, "session_id"),
        "query_text": canonicalize_memory_text(query_text),
        "max_items": _positive_int(max_items, "max_items"),
        "max_bytes": _positive_int(max_bytes, "max_bytes"),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _stable_agent_error_code(error: BaseException) -> str:
    """Translate internals without leaking exception text across the SDK boundary."""

    if isinstance(error, MemoryIdempotencyConflict):
        return "memory_conflict"
    if isinstance(error, TimeoutError):
        return "memory_timeout"
    if isinstance(
        error,
        (
            MemoryCorruptionError,
            MemoryLimitError,
            MemoryOwnershipConflict,
            MemoryValidationError,
            ValueError,
        ),
    ):
        return "memory_permanent"
    if isinstance(error, EmbeddingError):
        return "memory_transient"
    return "memory_transient"


__all__ = (
    "canonical_json",
    "canonical_message_payload_hash",
    "canonical_recall_query_hash",
    "canonicalize_memory_text",
    "validate_digest",
    "validate_identity",
)
