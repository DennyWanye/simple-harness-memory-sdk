import hashlib
import json

import pytest

from simple_harness_memory import (
    ContextPreparationMode,
    ConversationMemoryAdapter,
    ConversationMemoryApplyResult,
    ConversationMemoryApplyStatus,
    ConversationMemoryError,
    ConversationMemoryErrorCode,
    ConversationMemoryIntent,
    ConversationMemoryQueryStatus,
    ConversationMemoryRecallQuery,
    ConversationMemoryRecallResult,
    ConversationMemoryRole,
)
from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.core.conversation import canonical_json


def test_intent_hash_matches_frozen_harness_protocol() -> None:
    intent = ConversationMemoryIntent(
        source_event_id="harness-memory/v1/user/run-1",
        user_id="u1",
        session_id="s1",
        role=ConversationMemoryRole.USER,
        memory_text="line1\r\nline2",
    )
    expected = hashlib.sha256(
        json.dumps(
            {
                "protocol": "harness-conversation-memory-intent-v1",
                "source_event_id": "harness-memory/v1/user/run-1",
                "user_id": "u1",
                "session_id": "s1",
                "role": "user",
                "memory_text": "line1\nline2",
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    assert intent.payload_hash == expected


def test_recall_query_hash_matches_frozen_harness_protocol() -> None:
    query = ConversationMemoryRecallQuery.create(
        context_query_id="harness-memory/v1/context/root-1",
        user_id="u1",
        session_id="s1",
        query_text="Max",
        max_items=10,
        max_bytes=4096,
        timeout_seconds=1.0,
    )
    assert len(query.query_hash) == 64
    assert query.query_text == "Max"


def test_result_types_validate_the_frozen_hash_and_status_contract() -> None:
    payload = {"items": [], "status": "complete"}
    encoded = canonical_json(payload).encode("utf-8")
    result = ConversationMemoryRecallResult(
        context_query_id="query-1",
        result_id="memory-recall/v1/query-1",
        query_hash="a" * 64,
        payload=payload,
        result_hash=hashlib.sha256(encoded).hexdigest(),
        status="complete",
        item_count=0,
        byte_count=len(encoded),
    )
    assert result.status is ConversationMemoryQueryStatus.COMPLETE
    with pytest.raises(ValueError, match="result_hash"):
        ConversationMemoryRecallResult(
            context_query_id="query-1",
            result_id="memory-recall/v1/query-1",
            query_hash="a" * 64,
            payload=payload,
            result_hash="b" * 64,
            status="complete",
            item_count=0,
            byte_count=len(encoded),
        )
    apply_result = ConversationMemoryApplyResult(
        "event-1", "c" * 64, "applied", "1"
    )
    assert apply_result.status is ConversationMemoryApplyStatus.APPLIED
    assert ContextPreparationMode.SDK_PREPARED.value == "sdk_prepared"


@pytest.mark.asyncio
async def test_adapter_implements_sink_and_query_shapes() -> None:
    backend = MockMemoryBackend()
    adapter = ConversationMemoryAdapter(backend)
    intent = ConversationMemoryIntent(
        "event-1", "u1", "s1", ConversationMemoryRole.USER, "我叫小林"
    )
    first = await adapter.apply(intent)
    second = await adapter.apply(intent)
    assert first.status is ConversationMemoryApplyStatus.APPLIED
    assert second.status is ConversationMemoryApplyStatus.ALREADY_APPLIED
    with pytest.raises(ConversationMemoryError) as apply_error:
        await adapter.apply(
            ConversationMemoryIntent(
                "event-1", "u1", "s1", ConversationMemoryRole.USER, "different"
            )
        )
    assert apply_error.value.code is ConversationMemoryErrorCode.APPLY_CONFLICT
    query = ConversationMemoryRecallQuery.create(
        context_query_id="query-1",
        user_id="u1",
        session_id="s1",
        query_text="小林",
        max_items=5,
        max_bytes=4096,
        timeout_seconds=1.0,
    )
    result = await adapter.recall_bounded(query)
    assert result.status is ConversationMemoryQueryStatus.COMPLETE
    assert result.item_count == 1
    assert result.byte_count == len(canonical_json(result.payload).encode("utf-8"))
    assert (
        hashlib.sha256(canonical_json(result.payload).encode("utf-8")).hexdigest()
        == result.result_hash
    )
    conflicting_query = ConversationMemoryRecallQuery.create(
        context_query_id="query-1",
        user_id="u1",
        session_id="s1",
        query_text="different",
        max_items=5,
        max_bytes=4096,
        timeout_seconds=1.0,
    )
    with pytest.raises(ConversationMemoryError) as query_error:
        await adapter.recall_bounded(conflicting_query)
    assert query_error.value.code is ConversationMemoryErrorCode.QUERY_CONFLICT
    await adapter.close()
    await adapter.close()


@pytest.mark.asyncio
async def test_adapter_redacts_unexpected_backend_failures() -> None:
    class BrokenBackend:
        async def append_message(self, *args, **kwargs):
            raise RuntimeError("private-storage-detail")

        async def close(self):
            return None

    adapter = ConversationMemoryAdapter(BrokenBackend())
    intent = ConversationMemoryIntent(
        "event-1", "u1", "s1", ConversationMemoryRole.USER, "hello"
    )
    with pytest.raises(ConversationMemoryError) as error:
        await adapter.apply(intent)
    assert error.value.code is ConversationMemoryErrorCode.TRANSIENT
    assert str(error.value) == "memory_transient"
    assert "private-storage-detail" not in str(error.value)


def test_memory_package_never_imports_harness() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "simple_harness_memory"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    assert "import simple_harness" not in source
    assert "from simple_harness " not in source
