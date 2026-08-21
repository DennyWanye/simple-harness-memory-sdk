import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.errors import MemoryIdempotencyConflict


@pytest.mark.asyncio
async def test_recall_result_is_durable_across_return_loss_and_reopen(
    tmp_path, monkeypatch
):
    path = str(tmp_path / "memory.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    await backend.append_message(
        "s1", "user", "我叫小林",
        user_id="u1", source_event_id="event-1",
    )
    first = await backend.recall_bounded(
        "小林", user_id="u1", session_id="s1",
        context_query_id="query-1", max_results=5, max_bytes=4096,
    )
    calls = 0

    async def forbidden_recompute(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("durable replay recomputed recall")

    monkeypatch.setattr(backend, "_compute_recall", forbidden_recompute)
    replay = await backend.recall_bounded(
        "小林", user_id="u1", session_id="s1",
        context_query_id="query-1", max_results=5, max_bytes=4096,
    )
    assert calls == 0
    assert replay.replayed
    assert replay.result_hash == first.result_hash
    await backend.close()

    reopened = SQLiteMemoryBackend(path)
    await reopened.initialize()
    replay_after_crash = await reopened.recall_bounded(
        "小林", user_id="u1", session_id="s1",
        context_query_id="query-1", max_results=5, max_bytes=4096,
    )
    assert replay_after_crash.replayed
    assert replay_after_crash.result_hash == first.result_hash
    with pytest.raises(MemoryIdempotencyConflict):
        await reopened.recall_bounded(
            "different", user_id="u1", session_id="s1",
            context_query_id="query-1", max_results=5, max_bytes=4096,
        )
    await reopened.release_recall_result(
        user_id="u1", context_query_id="query-1",
        result_hash=first.result_hash,
    )
    await reopened.release_recall_result(
        user_id="u1", context_query_id="query-1",
        result_hash=first.result_hash,
    )
    await reopened.close()
