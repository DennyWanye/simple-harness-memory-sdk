import sqlite3
import time

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.models import Fact


@pytest.mark.asyncio
async def test_user_scoped_reads_and_same_session_id_is_deployment_isolated(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    first = await backend.append_message(
        "session-a",
        "user",
        "共享词 青松",
        user_id="user-a",
        source_event_id="event-a",
    )
    await backend.append_message(
        "session-b",
        "user",
        "共享词 白桦",
        user_id="user-b",
        source_event_id="event-b",
    )
    assert all("白桦" not in hit.text for hit in await backend.recall("共享词", user_id="user-a"))
    assert await backend.get_message(first.message_id, user_id="user-b") is None
    second = await backend.append_message(
        "session-a",
        "user",
        "isolated",
        user_id="user-b",
        source_event_id="event-isolated",
    )
    assert await backend.get_message(second.message_id, user_id="user-a") is None
    async with backend._conn.execute("PRAGMA foreign_keys") as cursor:
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        await backend._conn.execute(
            "INSERT INTO messages "
            "(user_id, session_id, role, content, created_at, "
            "source_event_id, payload_hash) "
            "VALUES ('orphan', 'none', 'user', 'x', 0, 'e', 'h')"
        )
    await backend.close()


@pytest.mark.asyncio
async def test_fact_supersede_relation_cannot_cross_user(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    messages = {}
    for user in ("user-a", "user-b"):
        messages[user] = await backend.append_message(
            f"session-{user}",
            "user",
            user,
            user_id=user,
            source_event_id=f"event-{user}",
        )
    facts = {}
    for user in ("user-a", "user-b"):
        fact = Fact(
            id=None,
            user_id=user,
            subject="user",
            key="name",
            value=user,
            category="profile",
            confidence=1.0,
            evidence=user,
            source_msg_id=messages[user].message_id,
            created_at=time.time(),
        )
        facts[user] = await backend._insert_fact_impl(user, fact)
    with pytest.raises(sqlite3.IntegrityError, match="memory_ownership_conflict"):
        await backend._conn.execute(
            "UPDATE facts SET superseded_by = ? WHERE user_id = ? AND id = ?",
            (facts["user-b"], "user-a", facts["user-a"]),
        )
    await backend.close()
