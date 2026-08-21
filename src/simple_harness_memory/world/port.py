"""WorldModelPort — 世界感知抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TemporalContext:
    """时间感知快照。"""

    current_time: float  # Unix timestamp
    date_str: str  # "2026-08-17"
    time_str: str  # "14:30"
    weekday: str  # "星期一"
    time_of_day: str  # "morning" | "afternoon" | "evening" | "night"
    season: str  # "spring" | "summer" | "autumn" | "winter"
    is_holiday: bool = False
    holiday_name: str | None = None

    def format_relative(self, past_unix: float) -> str:
        """将过去的时间格式化为相对描述，如 '3天前'。"""
        delta = self.current_time - past_unix
        days = delta / 86400
        if days < 1:
            hours = delta / 3600
            return f"{int(hours)}小时前" if hours >= 1 else "刚刚"
        if days < 7:
            return f"{int(days)}天前"
        if days < 30:
            return f"{int(days / 7)}周前"
        return f"{int(days / 30)}个月前"


@dataclass
class WorldEvent:
    """世界或个人事件。"""

    title: str
    summary: str
    source: str  # "personal" | "news" | "tech"
    published_at: float  # Unix timestamp
    relevance: float = 0.5  # 0.0-1.0，按用户 twin 计算的个性化相关度
    url: str | None = None


@dataclass
class Weather:
    """天气快照。"""

    location: str
    temperature_c: float
    description: str  # "晴" | "多云" | "小雨"
    humidity: int  # 百分比
    fetched_at: float  # Unix timestamp


@dataclass
class KnowledgeGap:
    """LLM 知识边界与当前时间的差距。"""

    cutoff_date: str  # "2026-05-31"
    current_date: str  # "2026-08-17"
    gap_days: int
    time_sensitive_terms: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)


class WorldModelPort(ABC):
    """世界感知抽象接口。"""

    @abstractmethod
    async def get_temporal_context(self) -> TemporalContext:
        """获取当前时间上下文。"""

    @abstractmethod
    async def get_recent_events(self, days: int = 3) -> list[WorldEvent]:
        """获取最近 N 天的世界/个人事件。"""

    @abstractmethod
    async def get_weather(self, location: str) -> Weather | None:
        """获取指定城市天气（失败返回 None）。"""

    @abstractmethod
    async def check_knowledge_boundary(self, query: str) -> KnowledgeGap | None:
        """检测查询是否涉及 LLM 知识截止日期之后的内容。"""

    @abstractmethod
    async def get_personalized_news(
        self,
        interests: list[str],
        categories: list[str] | None = None,
    ) -> list[WorldEvent]:
        """根据用户兴趣获取个性化新闻。"""
