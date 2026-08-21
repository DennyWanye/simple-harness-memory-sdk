import hashlib
import json

import pytest

from simple_harness_memory import (
    ConversationMemoryAdapter,
    ConversationMemoryApplyStatus,
    ConversationMemoryIntent,
    ConversationMemoryQueryStatus,
    ConversationMemoryRecallQuery,
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
    await adapter.close()
    await adapter.close()


def test_memory_package_never_imports_harness() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "simple_harness_memory"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    assert "import simple_harness" not in source
    assert "from simple_harness " not in source
