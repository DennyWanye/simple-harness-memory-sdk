import time

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.embedders.mock import HashEmbedder


@pytest.mark.asyncio
async def test_maintenance_never_mutates_another_user(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    now = time.time()
    monkeypatch.setattr("simple_harness_memory.backends.base.time.time", lambda: now)
    a = await backend.append_message(
        "a",
        "user",
        "same word",
        user_id="user-a",
        source_event_id="event-a",
        salience=1.0,
    )
    b = await backend.append_message(
        "b",
        "user",
        "same word",
        user_id="user-b",
        source_event_id="event-b",
        salience=1.0,
    )
    await backend._conn.execute(
        "UPDATE messages SET created_at = ? WHERE user_id IN (?, ?)",
        (now - 100 * 86400, "user-a", "user-b"),
    )
    await backend.daily_decay(user_id="user-a", limit=1)
    message_a = await backend.get_message(a.message_id, user_id="user-a")
    message_b = await backend.get_message(b.message_id, user_id="user-b")
    assert message_a is not None and message_a.salience < 1.0
    assert message_b is not None and message_b.salience == 1.0
    first_decay = message_a.salience

    # A retry at the same logical time observes the durable decay watermark.
    await backend.daily_decay(user_id="user-a", limit=1)
    message_a = await backend.get_message(a.message_id, user_id="user-a")
    assert message_a is not None and message_a.salience == first_decay

    assert await backend.reindex(HashEmbedder(dim=64), user_id="user-a", limit=1) == 1
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
            "query",
            user_id=user,
            session_id=f"session-{user}",
            context_query_id=f"query-{user}",
            max_results=2,
            max_bytes=1024,
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
    async with backend._conn.execute("SELECT user_id FROM recall_result_snapshots") as cursor:
        rows = await cursor.fetchall()
    assert [row["user_id"] for row in rows] == ["user-b"]
    await backend.close()


@pytest.mark.asyncio
async def test_vector_reinforce_summary_and_actions_are_user_scoped(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    first = await backend.append_message(
        "session-a",
        "user",
        "shared alpha",
        user_id="user-a",
        source_event_id="event-alpha",
    )
    second = await backend.append_message(
        "session-b",
        "user",
        "shared beta",
        user_id="user-b",
        source_event_id="event-beta",
    )
    assert all(
        hit.message_id != second.message_id
        for hit in await backend.vector_search("shared", user_id="user-a")
    )
    await backend.recall_and_reinforce("shared", user_id="user-a")
    alpha = await backend.get_message(first.message_id, user_id="user-a")
    beta = await backend.get_message(second.message_id, user_id="user-b")
    assert alpha is not None and alpha.salience > 0
    assert beta is not None and beta.salience == 0

    old = time.time() - 100 * 86400
    await backend._conn.execute(
        "UPDATE sessions SET last_activity_at = ? WHERE user_id IN (?, ?)",
        (old, "user-a", "user-b"),
    )
    await backend._conn.execute(
        "UPDATE messages SET created_at = ? WHERE user_id IN (?, ?)",
        (old, "user-a", "user-b"),
    )
    result = await backend.summarize_old_sessions(user_id="user-a", max_sessions=1)
    assert result == {"summarized_sessions": 1}
    assert await backend.summarize_old_sessions(
        user_id="user-a", max_sessions=1
    ) == {"summarized_sessions": 0}
    assert any(
        message.is_summary
        for message in await backend.get_recent_messages("session-a", user_id="user-a")
    )
    assert not any(
        message.is_summary
        for message in await backend.get_recent_messages("session-b", user_id="user-b")
    )
    assert sum(
        message.is_summary
        for message in await backend.get_recent_messages("session-a", user_id="user-a")
    ) == 1

    await backend.record_workspace_action(
        "session-a", "write", {"path": "a"}, user_id="user-a"
    )
    async with backend._conn.execute(
        "SELECT user_id, session_id FROM workspace_actions"
    ) as cursor:
        actions = [tuple(row) for row in await cursor.fetchall()]
    assert actions == [("user-a", "session-a")]
    await backend.close()
