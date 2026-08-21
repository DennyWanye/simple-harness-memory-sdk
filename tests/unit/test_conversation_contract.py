import hashlib
import inspect
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
from simple_harness_memory.core.errors import (
    EmbeddingError,
    MemoryCorruptionError,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemoryValidationError,
)


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


@pytest.mark.parametrize(
    "timeout_seconds", (float("nan"), float("inf"), -float("inf"), True, 0, -1)
)
def test_recall_query_rejects_non_finite_or_non_positive_timeout(
    timeout_seconds,
) -> None:
    with pytest.raises(MemoryValidationError, match="finite and positive"):
        ConversationMemoryRecallQuery.create(
            context_query_id="query-invalid-timeout",
            user_id="u1",
            session_id="s1",
            query_text="Max",
            max_items=10,
            max_bytes=4096,
            timeout_seconds=timeout_seconds,
        )


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


def test_adapter_release_matches_harness_query_port_signature() -> None:
    parameters = inspect.signature(ConversationMemoryAdapter.release).parameters
    assert list(parameters) == ["self", "user_id", "context_query_id", "result_hash"]
    assert all(
        parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        for name in ("user_id", "context_query_id", "result_hash")
    )


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


@pytest.mark.asyncio
async def test_adapter_release_is_idempotent_and_maps_wrong_hash_to_query_conflict() -> None:
    backend = MockMemoryBackend()
    adapter = ConversationMemoryAdapter(backend, close_backend=False)
    query = ConversationMemoryRecallQuery.create(
        context_query_id="release-query",
        user_id="u1",
        session_id="s1",
        query_text="release",
        max_items=5,
        max_bytes=4096,
        timeout_seconds=1.0,
    )
    result = await adapter.recall_bounded(query)

    await adapter.release(
        user_id="u1",
        context_query_id=query.context_query_id,
        result_hash=result.result_hash,
    )
    await adapter.release(
        user_id="u1",
        context_query_id=query.context_query_id,
        result_hash=result.result_hash,
    )

    with pytest.raises(ConversationMemoryError) as error:
        await adapter.release(
            user_id="u1",
            context_query_id=query.context_query_id,
            result_hash="0" * 64,
        )
    assert error.value.code is ConversationMemoryErrorCode.QUERY_CONFLICT
    assert str(error.value) == "memory_query_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend_error", "expected_code"),
    [
        (TimeoutError("private-timeout-detail"), ConversationMemoryErrorCode.TIMEOUT),
        (
            MemoryValidationError("private-validation-detail"),
            ConversationMemoryErrorCode.PERMANENT,
        ),
        (
            MemoryOwnershipConflict("private-owner-detail"),
            ConversationMemoryErrorCode.PERMANENT,
        ),
        (
            MemoryCorruptionError("private-corruption-detail"),
            ConversationMemoryErrorCode.PERMANENT,
        ),
        (
            MemoryLimitError("private-limit-detail"),
            ConversationMemoryErrorCode.PERMANENT,
        ),
        (ValueError("private-value-detail"), ConversationMemoryErrorCode.PERMANENT),
        (
            EmbeddingError("private-embedding-detail"),
            ConversationMemoryErrorCode.TRANSIENT,
        ),
        (RuntimeError("private-storage-detail"), ConversationMemoryErrorCode.TRANSIENT),
    ],
)
async def test_adapter_release_redacts_timeout_and_unknown_failures(
    backend_error: Exception,
    expected_code: ConversationMemoryErrorCode,
) -> None:
    class BrokenReleaseBackend:
        async def release_recall_result(self, **kwargs):
            raise backend_error

    adapter = ConversationMemoryAdapter(BrokenReleaseBackend(), close_backend=False)
    with pytest.raises(ConversationMemoryError) as error:
        await adapter.release(
            user_id="u1",
            context_query_id="query-1",
            result_hash="a" * 64,
        )
    assert error.value.code is expected_code
    assert str(error.value) == expected_code.value
    assert "private" not in str(error.value)


def test_memory_package_never_imports_harness() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "simple_harness_memory"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    assert "import simple_harness" not in source
    assert "from simple_harness " not in source
