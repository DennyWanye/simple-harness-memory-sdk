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
        "explicit_fact_receipts",
        "schema_meta",
    }.issubset(tables)
    async with backend._conn.execute("PRAGMA foreign_key_check") as cursor:
        assert await cursor.fetchall() == []
    async with backend._conn.execute("PRAGMA table_info(sessions)") as cursor:
        session_columns = {row[1]: row[5] for row in await cursor.fetchall()}
    assert session_columns["deployment_id"] == 1
    assert session_columns["session_id"] == 2
    async with backend._conn.execute("PRAGMA table_info(turn_receipts)") as cursor:
        receipt_columns = {row[1]: row[5] for row in await cursor.fetchall()}
    assert receipt_columns["deployment_id"] == 1
    assert receipt_columns["turn_id"] == 2
    async with backend._conn.execute("PRAGMA table_info(recall_result_snapshots)") as cursor:
        snapshot_columns = {row[1]: row[5] for row in await cursor.fetchall()}
    assert snapshot_columns["deployment_id"] == 1
    assert snapshot_columns["context_query_id"] == 2
    async with backend._conn.execute("PRAGMA foreign_key_list(fact_jobs)") as cursor:
        fact_job_foreign_keys = await cursor.fetchall()
    assert {(row[2], row[3], row[4]) for row in fact_job_foreign_keys}.issuperset(
        {
            ("turn_receipts", "deployment_id", "deployment_id"),
            ("turn_receipts", "turn_id", "turn_id"),
        }
    )
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


@pytest.mark.asyncio
async def test_known_v4_snapshot_schema_is_repaired_transactionally(tmp_path):
    path = tmp_path / "known-v4.db"
    backend = SQLiteMemoryBackend(str(path))
    await backend.initialize()
    await backend.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE explicit_fact_receipts")
    connection.execute("DROP TABLE recall_result_snapshots")
    connection.execute(
        "CREATE TABLE recall_result_snapshots ("
        "context_query_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, deployment_id TEXT NOT NULL, "
        "household_id TEXT NOT NULL, actor_id TEXT NOT NULL, scope_set_hash TEXT NOT NULL, "
        "write_fence TEXT NOT NULL, session_id TEXT NOT NULL, query_hash TEXT NOT NULL, "
        "result_payload TEXT NOT NULL, result_hash TEXT NOT NULL, "
        "state TEXT NOT NULL CHECK (state IN ('retained', 'released')), created_at REAL NOT NULL, "
        "released_at REAL, FOREIGN KEY (user_id, session_id) "
        "REFERENCES sessions(user_id, session_id) ON DELETE CASCADE)"
    )
    connection.execute(
        "UPDATE schema_meta SET value = ? WHERE key = 'schema_checksum'",
        ("4e66bbfe712e479ef1e6ac5cbc0e720235b9ae6512a0668ddb18bb9cbf29e461",),
    )
    connection.commit()
    connection.close()

    repaired = SQLiteMemoryBackend(str(path))
    await repaired.initialize()
    async with repaired._conn.execute("PRAGMA table_info(recall_result_snapshots)") as cursor:
        columns = {row[1]: row[5] for row in await cursor.fetchall()}
    assert columns["deployment_id"] == 1
    assert columns["context_query_id"] == 2
    async with repaired._conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_checksum'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] == SCHEMA_CHECKSUM
    await repaired.close()
