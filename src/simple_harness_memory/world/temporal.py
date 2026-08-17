"""时间感知实现。"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from simple_harness_memory.world.port import TemporalContext

_WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

_SEASON_MAP = {
    (3, 4, 5): "spring",
    (6, 7, 8): "summer",
    (9, 10, 11): "autumn",
    (12, 1, 2): "winter",
}


def _get_season(month: int) -> str:
    for months, season in _SEASON_MAP.items():
        if month in months:
            return season
    return "unknown"


def _get_time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def build_temporal_context(tz_offset_hours: float = 8.0) -> TemporalContext:
    """构建当前时间上下文（默认 UTC+8）。"""
    now_ts = time.time()
    tz = timezone.utc  # 暂用 UTC，后续可按用户 profile.timezone 调整
    dt = datetime.fromtimestamp(now_ts, tz=tz)

    return TemporalContext(
        current_time=now_ts,
        date_str=dt.strftime("%Y-%m-%d"),
        time_str=dt.strftime("%H:%M"),
        weekday=_WEEKDAY_ZH[dt.weekday()],
        time_of_day=_get_time_of_day(dt.hour),
        season=_get_season(dt.month),
        is_holiday=False,
    )
