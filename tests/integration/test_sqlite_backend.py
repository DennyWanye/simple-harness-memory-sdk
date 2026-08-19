import time

import pytest

from simple_harness_memory.backends.sqlite import SCHEMA_VERSION, SQLiteMemoryBackend
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError
from simple_harness_memory.core.models import Fact
from simple_harness_memory.embedders.mock import HashEmbedder


@pytest.mark.asyncio
async def test_sqlite_persistence_roundtrip(tmp_path):
    db = str(tmp_path / "mem.db")
    b = SQLiteMemoryBackend(db)
    await b.initialize()
    await b.append_message("s1", "user", "hello")
    await b.close()

    b2 = SQLiteMemoryBackend(db)
    await b2.initialize()
    msgs = await b2.get_recent_messages("s1")
    assert len(msgs) == 1
    assert msgs[0].content == "hello"
    await b2.close()


@pytest.mark.asyncio
async def test_sqlite_facts_and_recall(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), auto_extract_facts=True)
    await b.initialize()
    await b.append_message("s1", "user", "我养了一只叫Max的狗，很喜欢吃披萨")
    facts = await b.get_facts()
    assert any(f.key == "pet_name" and f.value == "Max" for f in facts)
    hits = await b.recall("Max")
    assert len(hits) >= 1
    await b.close()


@pytest.mark.asyncio
async def test_sqlite_decay_forgets_old_event(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b.initialize()
    fact = Fact(
        id=None, subject="user", key="event", value="昨天去了北京", category="event",
        confidence=0.6, evidence="", source_msg_id=1, created_at=time.time() - 100 * 86400,
    )
    await b._insert_fact(fact)
    await b.daily_decay()
    assert await b.get_facts(category="event", active_only=True) == []
    await b.close()


@pytest.mark.asyncio
async def test_sqlite_twin_persists(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b.initialize()
    twin = await b.get_digital_twin()
    twin.profile.name = "张三"
    await b.update_digital_twin(twin)
    await b.close()

    b2 = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b2.initialize()
    twin2 = await b2.get_digital_twin()
    assert twin2.profile.name == "张三"
    await b2.close()


@pytest.mark.asyncio
async def test_sqlite_corrupt_twin_raises(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b.initialize()
    await b._conn.execute(
        "INSERT INTO digital_twins (subject, data_json, updated_at) VALUES (?, ?, ?)",
        ("user", "{corrupt", time.time()),
    )
    await b._conn.commit()
    with pytest.raises(MemoryCorruptionError):
        await b.get_digital_twin("user")
    await b.close()


@pytest.mark.asyncio
async def test_extract_facts_does_not_log_key_value(tmp_path, capsys):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), auto_extract_facts=True)
    await b.initialize()
    await b.append_message("s1", "user", "我养了一只叫Max的狗")
    captured = capsys.readouterr().out
    assert "memory.extract_facts" in captured
    assert "Max" not in captured
    await b.close()


@pytest.mark.asyncio
async def test_schema_version_recorded_and_future_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    b = SQLiteMemoryBackend(path)
    await b.initialize()
    async with b._conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None and int(row[0]) == SCHEMA_VERSION
    await b._conn.execute("UPDATE schema_meta SET value='999' WHERE key='schema_version'")
    await b._conn.commit()
    await b.close()

    future = SQLiteMemoryBackend(path)
    with pytest.raises(MemoryCorruptionError):
        await future.initialize()


@pytest.mark.asyncio
async def test_schema_checksum_mismatch_rejected(tmp_path):
    path = str(tmp_path / "mem.db")
    b = SQLiteMemoryBackend(path)
    await b.initialize()
    await b._conn.execute("UPDATE schema_meta SET value='tampered' WHERE key='schema_checksum'")
    await b._conn.commit()
    await b.close()

    reopened = SQLiteMemoryBackend(path)
    with pytest.raises(MemoryCorruptionError):
        await reopened.initialize()


@pytest.mark.asyncio
async def test_legacy_010_db_migrates(tmp_path):
    import sqlite3

    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
        "role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL, "
        "salience REAL NOT NULL DEFAULT 0.0, decay_rate REAL NOT NULL DEFAULT 0.02, "
        "last_recalled REAL, embedding BLOB, is_summary INTEGER NOT NULL DEFAULT 0, summary_of TEXT)"
    )
    conn.execute(
        "CREATE TABLE facts (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, key TEXT NOT NULL, "
        "value TEXT NOT NULL, category TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0, "
        "evidence TEXT NOT NULL DEFAULT '', source_msg_id INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, "
        "decay_rate REAL NOT NULL DEFAULT 0.01, pinned INTEGER NOT NULL DEFAULT 0, last_decay_at REAL, "
        "superseded_by INTEGER, forgotten_at REAL)"
    )
    conn.execute(
        "CREATE TABLE digital_twins (subject TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE workspace_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
        "action_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES ('s1', 'user', 'hello', 0.0)"
    )
    conn.commit()
    conn.close()

    b = SQLiteMemoryBackend(path)
    await b.initialize()  # 0.1.0 → 迁移
    msgs = await b.get_recent_messages("s1")
    assert len(msgs) == 1 and msgs[0].content == "hello"
    # source_event_id 列已加，幂等 append 可用
    id1 = await b.append_message("s1", "user", "world", source_event_id="evt-1")
    id2 = await b.append_message("s1", "user", "world", source_event_id="evt-1")
    assert id1 == id2
    await b.close()


@pytest.mark.asyncio
async def test_append_atomic_rollback(tmp_path, monkeypatch):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), auto_extract_facts=True)
    await b.initialize()

    async def fail_insert(fact):
        raise RuntimeError("boom")

    monkeypatch.setattr(b, "_insert_fact", fail_insert)
    with pytest.raises(RuntimeError):
        await b.append_message("s1", "user", "我养了一只猫")
    msgs = await b.get_recent_messages("s1")
    assert msgs == []
    await b.close()


@pytest.mark.asyncio
async def test_source_event_id_idempotent(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b.initialize()
    id1 = await b.append_message("s1", "user", "hello", source_event_id="evt-1")
    id2 = await b.append_message("s1", "user", "hello", source_event_id="evt-1")
    assert id1 == id2
    msgs = await b.get_recent_messages("s1")
    assert len(msgs) == 1
    await b.close()


@pytest.mark.asyncio
async def test_delete_session_cascades(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), auto_extract_facts=True)
    await b.initialize()
    await b.append_message("s1", "user", "我养了一只叫Max的狗")
    await b.append_message("s2", "user", "今天天气很好")
    await b.delete_session("s1")
    msgs = await b._messages_all()
    assert all(m.session_id != "s1" for m in msgs)
    assert any(m.session_id == "s2" for m in msgs)
    facts = await b._facts_all()
    assert all(f.source_msg_id not in {m.id for m in msgs if m.session_id == "s1"} for f in facts)
    await b.close()


@pytest.mark.asyncio
async def test_delete_all(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), auto_extract_facts=True)
    await b.initialize()
    await b.append_message("s1", "user", "hello")
    await b.delete_all()
    assert await b._messages_all() == []
    assert await b._facts_all() == []
    await b.close()


@pytest.mark.asyncio
async def test_lineage_recorded_and_reindex(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"))
    await b.initialize()
    await b.append_message("s1", "user", "我养了一只猫")
    msgs = await b._messages_all()
    assert msgs[0].embedder_kind == "hash"
    assert msgs[0].embedding_dim == 256
    await b.reindex(HashEmbedder(dim=128))
    msgs2 = await b._messages_all()
    assert msgs2[0].embedding_dim == 128
    assert msgs2[0].embedder_kind == "hash"
    hits = await b.recall("猫")
    assert hits
    await b.close()


@pytest.mark.asyncio
async def test_content_limit_raises(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), max_content_chars=10)
    await b.initialize()
    with pytest.raises(MemoryLimitError):
        await b.append_message("s1", "user", "x" * 11)
    await b.close()


@pytest.mark.asyncio
async def test_db_size_limit_raises(tmp_path):
    b = SQLiteMemoryBackend(str(tmp_path / "mem.db"), max_db_bytes=1)
    await b.initialize()
    with pytest.raises(MemoryLimitError):
        await b.append_message("s1", "user", "hello")
    await b.close()
