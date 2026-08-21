import time

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.embedders.mock import HashEmbedder


@pytest.mark.asyncio
async def test_maintenance_never_mutates_another_user(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    a = await backend.append_message(
        "a", "user", "same word",
        user_id="user-a", source_event_id="event-a",
        salience=1.0,
    )
    b = await backend.append_message(
        "b", "user", "same word",
        user_id="user-b", source_event_id="event-b",
        salience=1.0,
    )
    await backend._conn.execute(
        "UPDATE messages SET created_at = ? WHERE user_id IN (?, ?)",
        (time.time() - 100 * 86400, "user-a", "user-b"),
    )
    await backend.daily_decay(user_id="user-a", limit=1)
    message_a = await backend.get_message(a.message_id, user_id="user-a")
    message_b = await backend.get_message(b.message_id, user_id="user-b")
    assert message_a is not None and message_a.salience < 1.0
    assert message_b is not None and message_b.salience == 1.0

    assert await backend.reindex(
        HashEmbedder(dim=64), user_id="user-a", limit=1
    ) == 1
    message_a = await backend.get_message(a.message_id, user_id="user-a")
    message_b = await backend.get_message(b.message_id, user_id="user-b")
    assert message_a is not None and message_a.embedding_dim == 64
    assert message_b is not None and message_b.embedding_dim == 256
    await backend.close()


@pytest.mark.asyncio
async def test_recall_snapshot_cleanup_is_user_scoped_and_bounded(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    for user in ("user-a", "user-b"):
        result = await backend.recall_bounded(
            "query", user_id=user, session_id=f"session-{user}",
            context_query_id=f"query-{user}", max_results=2, max_bytes=1024,
        )
        await backend.release_recall_result(
            user_id=user,
            context_query_id=f"query-{user}",
            result_hash=result.result_hash,
        )
    deleted = await backend.cleanup_recall_results(
        user_id="user-a", now=time.time() + 8 * 86400, limit=1
    )
    assert deleted == 1
    async with backend._conn.execute(
        "SELECT user_id FROM recall_result_snapshots"
    ) as cursor:
        rows = await cursor.fetchall()
    assert [row["user_id"] for row in rows] == ["user-b"]
    await backend.close()
