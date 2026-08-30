import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.errors import MemoryIdempotencyConflict
from simple_harness_memory.core.models import MemoryApplyStatus


@pytest.mark.asyncio
async def test_same_event_same_payload_replays_and_conflict_rejects(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    first = await backend.append_message(
        "s1",
        "user",
        "我叫小林",
        user_id="u1",
        source_event_id="event-1",
    )
    replay = await backend.append_message(
        "s1",
        "user",
        "我叫小林",
        user_id="u1",
        source_event_id="event-1",
    )
    assert replay.message_id == first.message_id
    assert replay.status is MemoryApplyStatus.ALREADY_APPLIED
    with pytest.raises(MemoryIdempotencyConflict):
        await backend.append_message(
            "s1",
            "user",
            "DIFFERENT",
            user_id="u1",
            source_event_id="event-1",
        )
    with pytest.raises(MemoryIdempotencyConflict):
        await backend.append_message(
            "s2",
            "user",
            "我叫小林",
            user_id="u2",
            source_event_id="event-1",
        )
    async with backend._conn.execute(
        "SELECT COUNT(*) FROM messages WHERE source_event_id = 'event-1'"
    ) as cursor:
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    assert await backend.get_facts(user_id="u1") == []
    await backend.close()
