import time

import pytest

from simple_harness_memory.world import WorldModel
from simple_harness_memory.world.events import StaticEventProvider
from simple_harness_memory.world.geography import StaticWeatherProvider
from simple_harness_memory.world.knowledge import detect_knowledge_gap
from simple_harness_memory.world.port import Weather, WorldEvent
from simple_harness_memory.world.temporal import build_temporal_context


def test_temporal_context():
    ctx = build_temporal_context()
    assert ctx.date_str
    assert ctx.weekday in {"星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"}


def test_knowledge_gap_detected():
    gap = detect_knowledge_gap("最近 AI 有什么新突破？")
    assert gap is not None
    assert gap.gap_days >= 0


def test_knowledge_gap_absent():
    assert detect_knowledge_gap("猫是什么动物？") is None


@pytest.mark.asyncio
async def test_world_model_noop_degrades():
    wm = WorldModel()
    ctx = await wm.get_temporal_context()
    assert ctx.date_str
    assert await wm.get_weather("北京") is None
    assert await wm.get_recent_events(3) == []


@pytest.mark.asyncio
async def test_world_model_static_providers():
    ev = WorldEvent(title="测试事件", summary="", source="news", published_at=time.time())
    weather = Weather("北京", 22.0, "晴", 50, time.time())
    wm = WorldModel(
        event_provider=StaticEventProvider([ev]),
        weather_provider=StaticWeatherProvider(weather),
    )
    assert len(await wm.get_recent_events(3)) == 1
    got = await wm.get_weather("北京")
    assert got.temperature_c == 22.0
