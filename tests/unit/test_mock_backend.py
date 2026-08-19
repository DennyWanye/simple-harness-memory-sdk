"""单元测试：Mock 后端基础功能。"""
from __future__ import annotations

import pytest

from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.core.models import FACT_DECAY_DEFAULTS, Fact
from simple_harness_memory.core.twin import DigitalTwin


@pytest.fixture
def backend() -> MockMemoryBackend:
    return MockMemoryBackend()


@pytest.mark.asyncio
async def test_append_and_get_recent(backend: MockMemoryBackend) -> None:
    sid = "test-session"
    id1 = await backend.append_message(sid, "user", "你好")
    id2 = await backend.append_message(sid, "assistant", "你好呀")
    msgs = await backend.get_recent_messages(sid, limit=10)
    assert len(msgs) == 2
    # get_recent_messages 按时间顺序（旧→新）返回
    assert msgs[0].content == "你好"
    assert msgs[1].content == "你好呀"
    # 验证 ID 递增

    assert id1 < id2


@pytest.mark.asyncio
async def test_get_message_by_id(backend: MockMemoryBackend) -> None:
    sid = "test-session"
    msg_id = await backend.append_message(sid, "user", "测试消息")
    msg = await backend.get_message(msg_id)
    assert msg is not None
    assert msg.content == "测试消息"
    assert msg.role == "user"
    assert msg.session_id == sid


@pytest.mark.asyncio
async def test_session_isolation(backend: MockMemoryBackend) -> None:
    await backend.append_message("session-A", "user", "A的消息")
    await backend.append_message("session-B", "user", "B的消息")
    msgs_a = await backend.get_recent_messages("session-A")
    msgs_b = await backend.get_recent_messages("session-B")
    assert len(msgs_a) == 1
    assert len(msgs_b) == 1
    assert msgs_a[0].content == "A的消息"
    assert msgs_b[0].content == "B的消息"


@pytest.mark.asyncio
async def test_recall_keyword_match(backend: MockMemoryBackend) -> None:
    sid = "recall-session"
    await backend.append_message(sid, "user", "我养了一只猫")
    await backend.append_message(sid, "user", "今天天气很好")
    await backend.append_message(sid, "user", "猫叫小白")
    hits = await backend.recall("猫")
    assert len(hits) >= 2
    texts = [h.text for h in hits]
    assert any("猫" in t for t in texts)


@pytest.mark.asyncio
async def test_recall_no_match(backend: MockMemoryBackend) -> None:
    sid = "recall-session"
    await backend.append_message(sid, "user", "今天吃了米饭")
    hits = await backend.recall("量子计算")
    assert hits == []


@pytest.mark.asyncio
async def test_digital_twin_default(backend: MockMemoryBackend) -> None:
    twin = await backend.get_digital_twin("user")
    assert twin.subject == "user"
    assert twin.completeness == 0.0
    assert twin.profile.name is None


@pytest.mark.asyncio
async def test_digital_twin_update(backend: MockMemoryBackend) -> None:
    twin = await backend.get_digital_twin("user")
    twin.profile.name = "张三"
    twin.profile.location = "北京"
    twin.profile.occupation = "工程师"
    twin.profile.language = "zh"
    await backend.update_digital_twin(twin)
    twin2 = await backend.get_digital_twin("user")
    assert twin2.profile.name == "张三"
    assert twin2.completeness > 0.0


@pytest.mark.asyncio
async def test_suggest_questions_fills_missing(backend: MockMemoryBackend) -> None:
    questions = await backend.suggest_questions()
    assert "你叫什么名字？" in questions


@pytest.mark.asyncio
async def test_fact_active_and_forget(backend: MockMemoryBackend) -> None:
    import time
    fact = Fact(
        id=None,
        subject="user",
        key="pet_name",
        value="Max",
        category="profile",
        confidence=0.9,
        evidence="我养了一只叫Max的狗",
        source_msg_id=1,
        created_at=time.time(),
    )
    fact_id = backend._add_fact(fact)
    active = await backend.get_facts("user", active_only=True)
    assert any(f.key == "pet_name" for f in active)
    ok = await backend.forget_fact(fact_id)
    assert ok
    active_after = await backend.get_facts("user", active_only=True)
    assert not any(f.key == "pet_name" for f in active_after)


def test_fact_decay_defaults_by_category() -> None:
    """AC-1 / F-2：Fact 按 category 得到差异化 decay_rate。"""
    assert FACT_DECAY_DEFAULTS["profile"] == 0.0
    assert FACT_DECAY_DEFAULTS["event"] == 0.05
    assert FACT_DECAY_DEFAULTS["constraint"] == 0.001
    profile = Fact(
        id=None, subject="user", key="name", value="张三", category="profile",
        confidence=0.9, evidence="", source_msg_id=1, created_at=0.0,
    )
    event = Fact(
        id=None, subject="user", key="event", value="昨天去了北京", category="event",
        confidence=0.6, evidence="", source_msg_id=1, created_at=0.0,
    )
    assert profile.decay_rate == 0.0
    assert event.decay_rate == 0.05


@pytest.mark.asyncio
async def test_recall_is_read_only(backend: MockMemoryBackend) -> None:
    """M1-AC-1：recall 物理无写入，salience 不变。"""
    msg_id = await backend.append_message("s1", "user", "我养了一只猫")
    await backend.recall("猫")
    msg = await backend.get_message(msg_id)
    assert msg is not None
    assert msg.salience == 0.0


@pytest.mark.asyncio
async def test_recall_and_reinforce_bumps_salience(backend: MockMemoryBackend) -> None:
    """M1-AC-1：reinforcement 由 recall_and_reinforce 显式执行。"""
    msg_id = await backend.append_message("s1", "user", "我养了一只猫")
    await backend.recall_and_reinforce("猫")
    msg = await backend.get_message(msg_id)
    assert msg is not None
    assert msg.salience == pytest.approx(0.05)
