"""事件感知。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from simple_harness_memory.world.port import WorldEvent


class EventProvider(ABC):
    @abstractmethod
    async def fetch(self, days=3, interests=None, categories=None) -> list[WorldEvent]: ...


class NoopEventProvider(EventProvider):
    async def fetch(self, days=3, interests=None, categories=None):
        return []


class StaticEventProvider(EventProvider):
    def __init__(self, events):
        self._events = events

    async def fetch(self, days=3, interests=None, categories=None):
        return list(self._events)


class NewsAPIEventProvider(EventProvider):
    def __init__(self, api_key: str, base_url: str = "https://newsapi.org/v2") -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def fetch(self, days=3, interests=None, categories=None):
        import httpx

        params: dict[str, Any] = {"apiKey": self._api_key, "pageSize": 20, "language": "zh"}
        if interests:
            params["q"] = " OR ".join(interests)
        if categories:
            params["category"] = categories[0]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self._base_url}/top-headlines", params=params)
                resp.raise_for_status()
                articles = resp.json().get("articles", [])
        except Exception:
            return []
        events = []
        for a in articles:
            if not a.get("title"):
                continue
            events.append(
                WorldEvent(
                    title=a["title"],
                    summary=(a.get("description") or "")[:500],
                    source="news",
                    published_at=_iso_to_ts(a.get("publishedAt")),
                    url=a.get("url"),
                )
            )
        return events


def facts_to_events(facts):
    events = []
    for f in facts:
        if f.category == "event" and f.is_active:
            events.append(
                WorldEvent(
                    title=f.value,
                    summary=f.evidence,
                    source="personal",
                    published_at=f.created_at,
                    relevance=1.0,
                )
            )
    return events


def _iso_to_ts(value, default=0.0):
    if not value:
        return default
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return default
