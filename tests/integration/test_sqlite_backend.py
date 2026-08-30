import sqlite3
import time

import pytest

from simple_harness_memory.backends.sqlite import (
    SCHEMA_VERSION,
    SQLiteMemoryBackend,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryLimitError,
    MemorySchemaIncompatible,
)
from simple_harness_memory.core.models import Fact, MemoryApplyStatus
from simple_harness_memory.embedders.mock import HashEmbedder
from tests.fixtures.legacy_facts import LegacyRegexFactExtractor

USER = "user-1"


async def _append(backend, session_id, role, content, event):
    return await backend.append_message(
        session_id,
        role,
        content,
        user_id=USER,
        source_event_id=event,
    )


async def _insert_fixture_facts(
    backend: SQLiteMemoryBackend, message_id: int, content: str
) -> list[Fact]:
    extracted = await LegacyRegexFactExtractor().extract(
        content,
        message_id=message_id,
        user_id=USER,
    )
    for fact in extracted:
        fact.id = await backend._insert_fact_impl(USER, fact)
    await backend._commit()
    return extracted
async def test_sqlite_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    await _append(backend, "s1", "user", "hello", "sqlite-1")
    await backend.close()
    reopened = SQLiteMemoryBackend(path)
    await reopened.initialize()
    messages = await reopened.get_recent_messages("s1", user_id=USER)
    assert [message.content for message in messages] == ["hello"]
    await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_facts_and_recall(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    message = await _append(
        backend,
        "s1",
        "user",
        "我养了一只叫Max的狗，很喜欢吃披萨",
        "sqlite-2",
    )
    await _insert_fixture_facts(
        backend,
        message.message_id,
        "我养了一只叫Max的狗，很喜欢吃披萨",
    )
    facts = await backend.get_facts(user_id=USER)
    assert any(fact.key == "pet_name" and fact.value == "Max" for fact in facts)
    assert await backend.recall("Max", user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_sqlite_decay_does_not_infer_retention_from_category(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    message = await _append(backend, "s1", "user", "old", "sqlite-3")
    fact = Fact(
        id=None,
        user_id=USER,
        subject="user",
        key="event",
        value="昨天去了北京",
        category="event",
        confidence=0.6,
        evidence="",
        source_msg_id=message.message_id,
        created_at=time.time() - 100 * 86400,
    )
    await backend._insert_fact_impl(USER, fact)
    await backend.daily_decay(user_id=USER)
    active = await backend.get_facts(category="event", active_only=True, user_id=USER)
    assert len(active) == 1
    assert active[0].decay_rate == 0.0
    await backend.close()


@pytest.mark.asyncio
async def test_sqlite_twin_persists(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    twin = await backend.get_digital_twin(user_id=USER)
    twin.profile.name = "张三"
    await backend.update_digital_twin(twin, user_id=USER)
    await backend.close()
    reopened = SQLiteMemoryBackend(path)
    await reopened.initialize()
    saved = await reopened.get_digital_twin(user_id=USER)
    assert saved.profile.name == "张三"
    await reopened.close()


@pytest.mark.asyncio
async def test_sqlite_corrupt_twin_raises(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    await backend._conn.execute(
        "INSERT INTO users (user_id, created_at) VALUES (?, ?)",
        (USER, time.time()),
    )
    await backend._conn.execute(
        "INSERT INTO digital_twins (user_id, subject, data_json, updated_at) VALUES (?, ?, ?, ?)",
        (USER, "user", "{corrupt", time.time()),
    )
    with pytest.raises(MemoryCorruptionError):
        await backend.get_digital_twin(user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_sqlite_constructor_rejects_legacy_extractor_arguments(tmp_path):
    with pytest.raises(TypeError):
        SQLiteMemoryBackend(  # type: ignore[call-arg]
            str(tmp_path / "mem.db"),
            auto_extract_facts=True,
        )


@pytest.mark.asyncio
async def test_schema_version_recorded_and_drift_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    async with backend._conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == SCHEMA_VERSION == 4
    await backend._conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    await backend.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()


@pytest.mark.asyncio
async def test_schema_checksum_mismatch_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    await backend._conn.execute(
        "UPDATE schema_meta SET value = 'tampered' WHERE key = 'schema_checksum'"
    )
    await backend.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()


@pytest.mark.asyncio
async def test_legacy_database_fails_fast_without_migration(tmp_path):
    path = str(tmp_path / "legacy.db")
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, content TEXT)"
    )
    connection.execute("INSERT INTO messages VALUES (1, 's1', 'legacy-canary')")
    connection.commit()
    connection.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT content FROM messages").fetchone()[0] == "legacy-canary"
    assert (
        connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'schema_meta'").fetchone()
        is None
    )
    connection.close()


@pytest.mark.asyncio
async def test_source_event_id_idempotent(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    first = await _append(backend, "s1", "user", "hello", "sqlite-idempotent")
    await backend.close()

    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    second = await _append(backend, "s1", "user", "hello", "sqlite-idempotent")
    assert first.message_id == second.message_id
    assert first.status is MemoryApplyStatus.APPLIED
    assert second.status is MemoryApplyStatus.ALREADY_APPLIED
    assert len(await backend.get_recent_messages("s1", user_id=USER)) == 1
    await backend.close()


@pytest.mark.asyncio
async def test_physical_session_delete_is_not_public(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    assert not hasattr(backend, "delete_session")
    assert not hasattr(backend, "delete_old_sessions")
    assert not hasattr(backend, "delete_all")
    await backend.close()


@pytest.mark.asyncio
async def test_lineage_recorded_and_reindex(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    await _append(backend, "s1", "user", "我养了一只猫", "sqlite-8")
    message = (await backend.get_recent_messages("s1", user_id=USER))[0]
    assert (message.embedder_kind, message.embedding_dim) == ("hash", 256)
    assert await backend.reindex(HashEmbedder(dim=128), user_id=USER) == 1
    assert await backend.reindex(HashEmbedder(dim=128), user_id=USER) == 0
    reindexed = (await backend.get_recent_messages("s1", user_id=USER))[0]
    assert (reindexed.embedder_kind, reindexed.embedding_dim) == ("hash", 128)
    assert await backend.recall("猫", user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_resource_limits_raise(tmp_path):
    content = SQLiteMemoryBackend(str(tmp_path / "content.db"), max_content_chars=10)
    await content.initialize()
    with pytest.raises(MemoryLimitError):
        await _append(content, "s1", "user", "x" * 11, "limit-1")
    await content.close()

    db_size = SQLiteMemoryBackend(str(tmp_path / "size.db"), max_db_bytes=1)
    await db_size.initialize()
    with pytest.raises(MemoryLimitError):
        await _append(db_size, "s1", "user", "hello", "limit-2")
    await db_size.close()

    actions = SQLiteMemoryBackend(str(tmp_path / "actions.db"), max_payload_bytes=10)
    await actions.initialize()
    with pytest.raises(MemoryLimitError):
        await actions.record_workspace_action("s1", "write", {"content": "x" * 100}, user_id=USER)
    await actions.close()
