"""WorldModel 组合实现。"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Optional

from simple_harness_memory.world.events import EventProvider, NoopEventProvider
from simple_harness_memory.world.geography import NoopWeatherProvider, WeatherProvider
from simple_harness_memory.world.knowledge import detect_knowledge_gap
from simple_harness_memory.world.port import KnowledgeGap, TemporalContext, Weather, WorldEvent, WorldModelPort
from simple_harness_memory.world.temporal import build_temporal_context


class WorldModel(WorldModelPort):
    def __init__(self, *, knowledge_cutoff="2026-05-31", event_provider=None, weather_provider=None, personal_event_loader=None):
        self.knowledge_cutoff = knowledge_cutoff
        self._event_provider = event_provider or NoopEventProvider()
        self._weather_provider = weather_provider or NoopWeatherProvider()
        self._personal_event_loader = personal_event_loader

    async def get_temporal_context(self):
        return build_temporal_context()

    async def get_recent_events(self, days=3):
        events = []
        if self._personal_event_loader is not None:
            events.extend(await self._personal_event_loader())
        events.extend(await self._event_provider.fetch(days=days))
        cutoff = time.time() - days * 86400.0
        filtered = [e for e in events if e.published_at >= cutoff]
        return sorted(filtered, key=lambda e: e.published_at, reverse=True)

    async def get_weather(self, location):
        return await self._weather_provider.fetch(location)

    async def check_knowledge_boundary(self, query):
        return detect_knowledge_gap(query, self.knowledge_cutoff)

    async def get_personalized_news(self, interests, categories=None):
        return await self._event_provider.fetch(days=3, interests=interests, categories=categories)
