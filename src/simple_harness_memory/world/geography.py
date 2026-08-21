"""地理/天气感知。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from simple_harness_memory.world.port import Weather


class WeatherProvider(ABC):
    @abstractmethod
    async def fetch(self, location: str) -> Weather | None: ...


class NoopWeatherProvider(WeatherProvider):
    async def fetch(self, location):
        return None


class StaticWeatherProvider(WeatherProvider):
    def __init__(self, weather=None):
        self._weather = weather

    async def fetch(self, location):
        if self._weather is None:
            return None
        return Weather(
            location=location,
            temperature_c=self._weather.temperature_c,
            description=self._weather.description,
            humidity=self._weather.humidity,
            fetched_at=time.time(),
        )


class OpenWeatherMapProvider(WeatherProvider):
    def __init__(
        self, api_key: str, base_url: str = "https://api.openweathermap.org/data/2.5"
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url

    async def fetch(self, location):
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self._base_url}/weather",
                    params={"q": location, "appid": self._api_key, "units": "metric"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        return Weather(
            location=location,
            temperature_c=float(data.get("main", {}).get("temp", 0.0)),
            description=str(data.get("weather", [{}])[0].get("description", "")),
            humidity=int(data.get("main", {}).get("humidity", 0)),
            fetched_at=time.time(),
        )
