import time

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.models import Fact


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
