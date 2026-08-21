import sqlite3

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.errors import MemoryOwnershipConflict


@pytest.mark.asyncio
async def test_user_scoped_reads_and_immutable_session_binding(tmp_path):
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
    with pytest.raises(MemoryOwnershipConflict):
        await backend.append_message(
            "session-a",
            "user",
            "steal",
            user_id="user-b",
            source_event_id="event-steal",
        )
    async with backend._conn.execute("PRAGMA foreign_keys") as cursor:
        assert (await cursor.fetchone())[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        await backend._conn.execute(
            "INSERT INTO messages "
            "(user_id, session_id, role, content, created_at, "
            "source_event_id, payload_hash) "
            "VALUES ('orphan', 'none', 'user', 'x', 0, 'e', 'h')"
        )
    await backend.close()
