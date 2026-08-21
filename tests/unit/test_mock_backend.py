"""Unit tests for mock/backend contract parity."""

from __future__ import annotations

import time

import pytest

from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.core.errors import MemoryUnsupportedOperation
from simple_harness_memory.core.models import FACT_DECAY_DEFAULTS, Fact

USER = "user-1"


@pytest.fixture
def backend() -> MockMemoryBackend:
    return MockMemoryBackend()


async def _append(backend, session_id, role, content, event):
    return await backend.append_message(
        session_id,
        role,
        content,
        user_id=USER,
        source_event_id=event,
    )


@pytest.mark.asyncio
async def test_append_and_get_recent(backend: MockMemoryBackend) -> None:
    first = await _append(backend, "test-session", "user", "你好", "mock-1")
    second = await _append(backend, "test-session", "assistant", "你好呀", "mock-2")
    messages = await backend.get_recent_messages("test-session", limit=10, user_id=USER)
    assert [message.content for message in messages] == ["你好", "你好呀"]
    assert first.message_id < second.message_id


@pytest.mark.asyncio
async def test_get_message_by_id(backend: MockMemoryBackend) -> None:
    result = await _append(backend, "test-session", "user", "测试消息", "mock-3")
    message = await backend.get_message(result.message_id, user_id=USER)
    assert message is not None
    assert (message.content, message.role, message.user_id) == (
        "测试消息",
        "user",
        USER,
    )


@pytest.mark.asyncio
async def test_session_isolation(backend: MockMemoryBackend) -> None:
    await _append(backend, "session-A", "user", "A的消息", "mock-4")
    await _append(backend, "session-B", "user", "B的消息", "mock-5")
    messages_a = await backend.get_recent_messages("session-A", user_id=USER)
    messages_b = await backend.get_recent_messages("session-B", user_id=USER)
    assert [message.content for message in messages_a] == ["A的消息"]
    assert [message.content for message in messages_b] == ["B的消息"]


@pytest.mark.asyncio
async def test_recall_keyword_match(backend: MockMemoryBackend) -> None:
    await _append(backend, "recall", "user", "我养了一只猫", "mock-6")
    await _append(backend, "recall", "user", "今天天气很好", "mock-7")
    await _append(backend, "recall", "user", "猫叫小白", "mock-8")
    hits = await backend.recall("猫", user_id=USER)
    assert len(hits) >= 2
    assert any("猫" in hit.text for hit in hits)


@pytest.mark.asyncio
async def test_recall_no_match(backend: MockMemoryBackend) -> None:
    await _append(backend, "recall", "user", "今天吃了米饭", "mock-9")
    assert await backend.recall("量子计算", user_id=USER) == []


@pytest.mark.asyncio
async def test_digital_twin_roundtrip(backend: MockMemoryBackend) -> None:
    twin = await backend.get_digital_twin(user_id=USER)
    assert twin.subject == "user"
    twin.profile.name = "张三"
    twin.profile.location = "北京"
    twin.profile.occupation = "工程师"
    twin.profile.language = "zh"
    await backend.update_digital_twin(twin, user_id=USER)
    saved = await backend.get_digital_twin(user_id=USER)
    assert saved.profile.name == "张三"
    assert saved.completeness > 0


@pytest.mark.asyncio
async def test_suggest_questions_fills_missing(
    backend: MockMemoryBackend,
) -> None:
    questions = await backend.suggest_questions(user_id=USER)
    assert "你叫什么名字？" in questions


@pytest.mark.asyncio
async def test_fact_active_and_forget(backend: MockMemoryBackend) -> None:
    fact = Fact(
        id=None,
        user_id=USER,
        subject="user",
        key="pet_name",
        value="Max",
        category="profile",
        confidence=0.9,
        evidence="我养了一只叫Max的狗",
        source_msg_id=1,
        created_at=time.time(),
    )
    fact_id = await backend._insert_fact_impl(USER, fact)
    assert any(item.key == "pet_name" for item in await backend.get_facts(user_id=USER))
    assert await backend.forget_fact(fact_id, user_id=USER)
    assert not any(item.key == "pet_name" for item in await backend.get_facts(user_id=USER))


def test_fact_decay_defaults_by_category() -> None:
    assert FACT_DECAY_DEFAULTS["profile"] == 0.0
    assert FACT_DECAY_DEFAULTS["event"] == 0.05
    assert FACT_DECAY_DEFAULTS["constraint"] == 0.001
    profile = Fact(
        id=None,
        user_id=USER,
        subject="user",
        key="name",
        value="张三",
        category="profile",
        confidence=0.9,
        evidence="",
        source_msg_id=1,
        created_at=0.0,
    )
    event = Fact(
        id=None,
        user_id=USER,
        subject="user",
        key="event",
        value="昨天去了北京",
        category="event",
        confidence=0.6,
        evidence="",
        source_msg_id=1,
        created_at=0.0,
    )
    assert profile.decay_rate == 0.0
    assert event.decay_rate == 0.05


@pytest.mark.asyncio
async def test_recall_is_read_only(backend: MockMemoryBackend) -> None:
    result = await _append(backend, "s1", "user", "我养了一只猫", "mock-10")
    await backend.recall("猫", user_id=USER)
    message = await backend.get_message(result.message_id, user_id=USER)
    assert message is not None and message.salience == 0.0


@pytest.mark.asyncio
async def test_recall_and_reinforce_bumps_salience(
    backend: MockMemoryBackend,
) -> None:
    result = await _append(backend, "s1", "user", "我养了一只猫", "mock-11")
    await backend.recall_and_reinforce("猫", user_id=USER)
    message = await backend.get_message(result.message_id, user_id=USER)
    assert message is not None
    assert message.salience == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_delete_all_is_deprecated_fail_closed(
    backend: MockMemoryBackend,
) -> None:
    await _append(backend, "s1", "user", "保留", "mock-12")
    with pytest.raises(MemoryUnsupportedOperation) as error:
        await backend.delete_all()
    assert error.value.code == "runtime_delete_disabled"
    assert await backend.get_recent_messages("s1", user_id=USER)
