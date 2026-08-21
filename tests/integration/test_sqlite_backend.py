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
    MemoryUnsupportedOperation,
)
from simple_harness_memory.core.models import Fact, MemoryApplyStatus
from simple_harness_memory.embedders.mock import HashEmbedder


USER = "user-1"


async def _append(backend, session_id, role, content, event):
    return await backend.append_message(
        session_id,
        role,
        content,
        user_id=USER,
        source_event_id=event,
    )


@pytest.mark.asyncio
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
    backend = SQLiteMemoryBackend(
        str(tmp_path / "mem.db"), auto_extract_facts=True
    )
    await backend.initialize()
    await _append(
        backend,
        "s1",
        "user",
        "我养了一只叫Max的狗，很喜欢吃披萨",
        "sqlite-2",
    )
    facts = await backend.get_facts(user_id=USER)
    assert any(fact.key == "pet_name" and fact.value == "Max" for fact in facts)
    assert await backend.recall("Max", user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_sqlite_decay_forgets_old_event(tmp_path):
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
    assert (
        await backend.get_facts(
            category="event", active_only=True, user_id=USER
        )
        == []
    )
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
        "INSERT INTO digital_twins "
        "(user_id, subject, data_json, updated_at) VALUES (?, ?, ?, ?)",
        (USER, "user", "{corrupt", time.time()),
    )
    with pytest.raises(MemoryCorruptionError):
        await backend.get_digital_twin(user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_extract_facts_does_not_log_key_value(tmp_path, capsys):
    backend = SQLiteMemoryBackend(
        str(tmp_path / "mem.db"), auto_extract_facts=True
    )
    await backend.initialize()
    await _append(
        backend, "s1", "user", "我养了一只叫Max的狗", "sqlite-4"
    )
    captured = capsys.readouterr().out
    assert "memory.extract_facts" in captured
    assert "Max" not in captured
    await backend.close()


@pytest.mark.asyncio
async def test_schema_version_recorded_and_drift_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    async with backend._conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == SCHEMA_VERSION == 3
    await backend._conn.execute(
        "UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'"
    )
    await backend.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()


@pytest.mark.asyncio
async def test_schema_checksum_mismatch_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    backend = SQLiteMemoryBackend(path)
    await backend.initialize()
    await backend._conn.execute(
        "UPDATE schema_meta SET value = 'tampered' "
        "WHERE key = 'schema_checksum'"
    )
    await backend.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()


@pytest.mark.asyncio
async def test_legacy_database_fails_fast_without_migration(tmp_path):
    path = str(tmp_path / "legacy.db")
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE messages "
        "(id INTEGER PRIMARY KEY, session_id TEXT, content TEXT)"
    )
    connection.execute(
        "INSERT INTO messages VALUES (1, 's1', 'legacy-canary')"
    )
    connection.commit()
    connection.close()
    with pytest.raises(MemorySchemaIncompatible):
        await SQLiteMemoryBackend(path).initialize()
    connection = sqlite3.connect(path)
    assert connection.execute(
        "SELECT content FROM messages"
    ).fetchone()[0] == "legacy-canary"
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'schema_meta'"
    ).fetchone() is None
    connection.close()


@pytest.mark.asyncio
async def test_append_atomic_rollback(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(
        str(tmp_path / "mem.db"), auto_extract_facts=True
    )
    await backend.initialize()

    async def fail_insert(user_id, fact):
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "_insert_fact_impl", fail_insert)
    with pytest.raises(RuntimeError):
        await _append(
            backend, "s1", "user", "我养了一只猫", "sqlite-rollback"
        )
    assert await backend.get_recent_messages("s1", user_id=USER) == []
    await backend.close()


@pytest.mark.asyncio
async def test_source_event_id_idempotent(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    first = await _append(
        backend, "s1", "user", "hello", "sqlite-idempotent"
    )
    second = await _append(
        backend, "s1", "user", "hello", "sqlite-idempotent"
    )
    assert first.message_id == second.message_id
    assert first.status is MemoryApplyStatus.APPLIED
    assert second.status is MemoryApplyStatus.ALREADY_APPLIED
    assert len(
        await backend.get_recent_messages("s1", user_id=USER)
    ) == 1
    await backend.close()


@pytest.mark.asyncio
async def test_delete_session_cascades(tmp_path):
    backend = SQLiteMemoryBackend(
        str(tmp_path / "mem.db"), auto_extract_facts=True
    )
    await backend.initialize()
    await _append(
        backend, "s1", "user", "我养了一只叫Max的狗", "sqlite-5"
    )
    await _append(
        backend, "s2", "user", "今天天气很好", "sqlite-6"
    )
    assert await backend.delete_session("s1", user_id=USER) == 1
    assert await backend.get_recent_messages("s1", user_id=USER) == []
    assert await backend.get_recent_messages("s2", user_id=USER)
    assert all(
        fact.value != "Max"
        for fact in await backend.get_facts(user_id=USER)
    )
    await backend.close()


@pytest.mark.asyncio
async def test_delete_all_is_fail_closed_and_non_mutating(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    await _append(backend, "s1", "user", "hello", "sqlite-7")
    with pytest.raises(MemoryUnsupportedOperation) as error:
        await backend.delete_all()
    assert error.value.code == "runtime_delete_disabled"
    assert await backend.get_recent_messages("s1", user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_lineage_recorded_and_reindex(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    await _append(backend, "s1", "user", "我养了一只猫", "sqlite-8")
    message = (
        await backend.get_recent_messages("s1", user_id=USER)
    )[0]
    assert (message.embedder_kind, message.embedding_dim) == ("hash", 256)
    assert await backend.reindex(
        HashEmbedder(dim=128), user_id=USER
    ) == 1
    reindexed = (
        await backend.get_recent_messages("s1", user_id=USER)
    )[0]
    assert (reindexed.embedder_kind, reindexed.embedding_dim) == ("hash", 128)
    assert await backend.recall("猫", user_id=USER)
    await backend.close()


@pytest.mark.asyncio
async def test_resource_limits_raise(tmp_path):
    content = SQLiteMemoryBackend(
        str(tmp_path / "content.db"), max_content_chars=10
    )
    await content.initialize()
    with pytest.raises(MemoryLimitError):
        await _append(content, "s1", "user", "x" * 11, "limit-1")
    await content.close()

    db_size = SQLiteMemoryBackend(
        str(tmp_path / "size.db"), max_db_bytes=1
    )
    await db_size.initialize()
    with pytest.raises(MemoryLimitError):
        await _append(db_size, "s1", "user", "hello", "limit-2")
    await db_size.close()

    facts = SQLiteMemoryBackend(
        str(tmp_path / "facts.db"),
        auto_extract_facts=True,
        max_fact_value_chars=2,
    )
    await facts.initialize()
    with pytest.raises(MemoryLimitError):
        await _append(
            facts, "s1", "user", "我养了一只叫Max的狗", "limit-3"
        )
    await facts.close()

    actions = SQLiteMemoryBackend(
        str(tmp_path / "actions.db"), max_payload_bytes=10
    )
    await actions.initialize()
    with pytest.raises(MemoryLimitError):
        await actions.record_workspace_action(
            "s1", "write", {"content": "x" * 100}, user_id=USER
        )
    await actions.close()


@pytest.mark.asyncio
async def test_delete_session_rebuilds_twin(tmp_path):
    backend = SQLiteMemoryBackend(
        str(tmp_path / "mem.db"), auto_extract_facts=True
    )
    await backend.initialize()
    await _append(
        backend, "s1", "user", "我养了一只叫Max的狗", "sqlite-9"
    )
    assert "Max" in (
        await backend.get_digital_twin(user_id=USER)
    ).relationships.entities
    await backend.delete_session("s1", user_id=USER)
    assert "Max" not in (
        await backend.get_digital_twin(user_id=USER)
    ).relationships.entities
    await backend.close()


@pytest.mark.asyncio
async def test_delete_old_sessions_is_user_scoped_and_bounded(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await backend.initialize()
    await _append(backend, "old", "user", "old msg", "sqlite-10")
    await backend._conn.execute(
        "UPDATE sessions SET last_activity_at = ? "
        "WHERE user_id = ? AND session_id = 'old'",
        (time.time() - 100 * 86400, USER),
    )
    await _append(backend, "recent", "user", "recent msg", "sqlite-11")
    deleted = await backend.delete_old_sessions(
        older_than_days=30, user_id=USER, limit=1
    )
    assert deleted == 1
    assert await backend.get_recent_messages("old", user_id=USER) == []
    assert await backend.get_recent_messages("recent", user_id=USER)
    await backend.close()
