import sqlite3

import pytest

from simple_harness_memory.backends.sqlite import (
    SCHEMA_CHECKSUM,
    SCHEMA_VERSION,
    SQLiteMemoryBackend,
)
from simple_harness_memory.core.errors import MemorySchemaIncompatible


@pytest.mark.asyncio
async def test_fresh_v4_schema_has_complete_ownership_graph(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    assert SCHEMA_VERSION == 4
    assert len(SCHEMA_CHECKSUM) == 64
    async with backend._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ) as cursor:
        tables = {row[0] for row in await cursor.fetchall()}
    assert {
        "users",
        "sessions",
        "messages",
        "facts",
        "digital_twins",
        "workspace_actions",
        "recall_result_snapshots",
        "erasure_epochs",
        "turn_receipts",
        "fact_jobs",
        "fact_tombstones",
        "suppression_receipts",
        "schema_meta",
    }.issubset(tables)
    async with backend._conn.execute("PRAGMA foreign_key_check") as cursor:
        assert await cursor.fetchall() == []
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["no-meta", "v2"])
async def test_old_or_unstamped_schema_fails_fast_and_closes(tmp_path, kind):
    path = tmp_path / f"{kind}.db"
    connection = sqlite3.connect(path)
    if kind == "no-meta":
        connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
    else:
        connection.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO schema_meta VALUES (?, ?)",
            (("schema_version", "2"), ("schema_checksum", "legacy")),
        )
    connection.commit()
    connection.close()
    backend = SQLiteMemoryBackend(str(path))
    with pytest.raises(MemorySchemaIncompatible):
        await backend.initialize()
    assert backend._db is None
