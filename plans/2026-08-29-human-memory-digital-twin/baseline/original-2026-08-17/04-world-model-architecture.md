# 世界对象（World Model）架构设计

**创建日期**: 2026-08-17  
**目标**: Agent对外部世界的实时认知模型

---

## 🌍 核心概念

### **什么是世界对象？**

世界对象是Agent的**外部世界感知层**，与记忆系统（内部认知）互补：

```
┌─────────────────────────────────────────┐
│  Agent 认知架构                          │
├─────────────────────────────────────────┤
│  内部认知（Memory System）               │
│  ├─ 用户记忆（Digital Twin）             │
│  ├─ 对话历史（Episodic Memory）         │
│  └─ 知识事实（Semantic Memory）         │
├─────────────────────────────────────────┤
│  外部感知（World Model）                 │
│  ├─ 时间感知（Temporal Awareness）      │
│  ├─ 事件感知（Event Awareness）         │
│  ├─ 上下文感知（Context Awareness）     │
│  └─ 知识边界（Knowledge Boundary）      │
└─────────────────────────────────────────┘
```

---

## 📊 数据结构设计

### **1. 世界对象核心类**

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict

@dataclass
class WorldModel:
    """Agent的世界认知模型"""
    
    # ========== 时间维度 ==========
    temporal: TemporalContext
    
    # ========== 事件维度 ==========
    events: EventStream
    
    # ========== 地理维度 ==========
    geography: GeographyContext
    
    # ========== 知识边界 ==========
    knowledge_boundary: KnowledgeBoundary
    
    # ========== 元数据 ==========
    last_updated: datetime
    user_location: Optional[str] = None  # 用户所在地（用于天气等）


@dataclass
class TemporalContext:
    """时间上下文"""
    
    # 当前时间
    current_time: datetime
    timezone: str
    
    # 时间描述
    date_str: str           # "2026年8月17日"
    time_str: str           # "14:30"
    weekday: str            # "星期六"
    
    # 时间分类
    time_of_day: str        # "morning" | "afternoon" | "evening" | "night"
    season: str             # "spring" | "summer" | "fall" | "winter"
    
    # 特殊时间点
    is_weekend: bool
    is_holiday: bool
    holiday_name: Optional[str] = None
    
    # 相对时间计算
    def days_since(self, past_date: datetime) -> int:
        """计算距离某个过去日期的天数"""
        return (self.current_time - past_date).days
    
    def format_relative(self, past_time: datetime) -> str:
        """格式化相对时间（"3分钟前"、"昨天"、"上周"）"""
        delta = self.current_time - past_time
        
        if delta.seconds < 60:
            return "刚才"
        elif delta.seconds < 3600:
            return f"{delta.seconds // 60}分钟前"
        elif delta.days == 0:
            return f"{delta.seconds // 3600}小时前"
        elif delta.days == 1:
            return "昨天"
        elif delta.days < 7:
            return f"{delta.days}天前"
        elif delta.days < 30:
            return f"{delta.days // 7}周前"
        else:
            return f"{delta.days // 30}个月前"


@dataclass
class EventStream:
    """事件流（最近发生的事）"""
    
    # 个人事件（从用户记忆中提取）
    personal_events: List[PersonalEvent]
    
    # 世界事件（从新闻源获取）
    world_events: List[WorldEvent]
    
    # 技术事件（从技术新闻获取）
    tech_events: List[TechEvent]


@dataclass
class PersonalEvent:
    """个人事件（用户相关）"""
    event_id: str
    description: str        # "用户3天前去了北京"
    timestamp: datetime
    category: str          # "travel" | "work" | "social" | "health"
    importance: float      # 0.0-1.0
    source_message_id: int


@dataclass
class WorldEvent:
    """世界事件（新闻）"""
    event_id: str
    title: str
    summary: str
    timestamp: datetime
    category: str          # "politics" | "economy" | "tech" | "sports" | "entertainment"
    source: str            # "新华社"、"Reuters"
    url: Optional[str] = None
    relevance: float = 0.5  # 对用户的相关性（基于用户兴趣）


@dataclass
class TechEvent:
    """技术事件（科技新闻）"""
    event_id: str
    title: str
    description: str
    timestamp: datetime
    technology: str        # "AI" | "Python" | "React" | ...
    impact: str           # "major" | "moderate" | "minor"
    source: str


@dataclass
class GeographyContext:
    """地理上下文"""
    
    # 用户位置
    user_location: Optional[Location] = None
    
    # 当前天气
    weather: Optional[Weather] = None
    
    # 附近事件
    nearby_events: List[str] = None


@dataclass
class Location:
    """地理位置"""
    city: str
    country: str
    timezone: str
    coordinates: Optional[tuple[float, float]] = None  # (lat, lon)


@dataclass
class Weather:
    """天气信息"""
    temperature: float      # 摄氏度
    condition: str         # "晴" | "多云" | "雨" | "雪"
    humidity: float        # 湿度百分比
    wind_speed: float      # 风速 km/h
    updated_at: datetime


@dataclass
class KnowledgeBoundary:
    """知识边界（Agent知道什么、不知道什么）"""
    
    # LLM训练数据截止日期
    training_cutoff: datetime  # "2026-05-31"
    
    # 知识差距
    knowledge_gaps: List[KnowledgeGap]
    
    # 实时数据源
    data_sources: Dict[str, DataSource]


@dataclass
class KnowledgeGap:
    """知识差距"""
    topic: str              # "2026年6月后的AI进展"
    gap_start: datetime     # 差距开始时间
    severity: str          # "critical" | "important" | "minor"
    how_to_fill: str       # "需要搜索最新新闻"


@dataclass
class DataSource:
    """数据源"""
    name: str
    type: str              # "news_api" | "weather_api" | "web_search"
    last_updated: datetime
    is_available: bool
    update_frequency: str  # "realtime" | "hourly" | "daily"
```

---

## 🔧 功能实现

### **1. 时间感知**

```python
class TemporalAwareness:
    """时间感知模块"""
    
    @staticmethod
    def get_current_context() -> TemporalContext:
        """获取当前时间上下文"""
        now = datetime.now(timezone.utc)
        
        return TemporalContext(
            current_time=now,
            timezone=str(now.tzinfo),
            date_str=now.strftime("%Y年%m月%d日"),
            time_str=now.strftime("%H:%M"),
            weekday=["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
            time_of_day=_classify_time_of_day(now.hour),
            season=_classify_season(now.month),
            is_weekend=now.weekday() >= 5,
            is_holiday=_check_holiday(now)
        )
    
    @staticmethod
    def format_event_time(event_time: datetime, current_time: datetime) -> str:
        """格式化事件时间（相对或绝对）"""
        delta = current_time - event_time
        
        if delta.days == 0:
            return f"今天{event_time.strftime('%H:%M')}"
        elif delta.days == 1:
            return f"昨天{event_time.strftime('%H:%M')}"
        elif delta.days < 7:
            return f"{delta.days}天前"
        else:
            return event_time.strftime("%Y-%m-%d")


def _classify_time_of_day(hour: int) -> str:
    """分类时段"""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    else:
        return "night"


def _classify_season(month: int) -> str:
    """分类季节（北半球）"""
    if month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    elif month in [9, 10, 11]:
        return "fall"
    else:
        return "winter"


def _check_holiday(date: datetime) -> tuple[bool, Optional[str]]:
    """检查是否是节假日"""
    # 简化版，实际需要完整的节假日数据库
    holidays = {
        (1, 1): "元旦",
        (10, 1): "国庆节",
        (5, 1): "劳动节",
        (12, 25): "圣诞节",
        # ... 更多节假日
    }
    
    key = (date.month, date.day)
    if key in holidays:
        return True, holidays[key]
    return False, None
```

---

### **2. 事件感知**

```python
class EventAwareness:
    """事件感知模块"""
    
    def __init__(
        self,
        news_api_key: Optional[str] = None,
        memory_backend: Optional[MemoryBackend] = None
    ):
        self.news_api = NewsAPI(api_key=news_api_key) if news_api_key else None
        self.memory = memory_backend
    
    async def get_recent_personal_events(
        self, 
        days: int = 7
    ) -> List[PersonalEvent]:
        """从用户记忆中提取最近的个人事件"""
        
        if not self.memory:
            return []
        
        # 从记忆中召回最近的重要事件
        cutoff = datetime.now() - timedelta(days=days)
        
        # 查询category="event"的Facts
        facts = await self.memory.get_facts(
            category="event",
            active_only=True
        )
        
        events = []
        for fact in facts:
            if fact.created_at > cutoff.timestamp():
                events.append(PersonalEvent(
                    event_id=f"personal_{fact.id}",
                    description=fact.value,
                    timestamp=datetime.fromtimestamp(fact.created_at),
                    category=self._classify_event_category(fact.value),
                    importance=fact.confidence,
                    source_message_id=fact.source_msg_id
                ))
        
        return sorted(events, key=lambda e: e.timestamp, reverse=True)
    
    async def get_recent_world_events(
        self, 
        days: int = 3,
        categories: Optional[List[str]] = None
    ) -> List[WorldEvent]:
        """获取最近的世界事件（新闻）"""
        
        if not self.news_api:
            return []
        
        # 调用新闻API
        news = await self.news_api.get_top_headlines(
            days=days,
            categories=categories or ["technology", "business"]
        )
        
        events = []
        for article in news:
            events.append(WorldEvent(
                event_id=f"world_{article['id']}",
                title=article["title"],
                summary=article["description"],
                timestamp=datetime.fromisoformat(article["published_at"]),
                category=article["category"],
                source=article["source"]["name"],
                url=article["url"],
                relevance=await self._calculate_relevance(article)
            ))
        
        return events
    
    async def _calculate_relevance(self, article: dict) -> float:
        """计算新闻对用户的相关性"""
        
        if not self.memory:
            return 0.5
        
        # 基于用户的数字孪生体计算相关性
        twin = await self.memory.get_digital_twin()
        
        relevance = 0.0
        
        # 1. 匹配用户技能
        for skill_name in twin.skills.skills.keys():
            if skill_name.lower() in article["title"].lower():
                relevance += 0.3
        
        # 2. 匹配用户兴趣（从偏好推断）
        # ...
        
        # 3. 匹配用户目标
        # ...
        
        return min(relevance, 1.0)
    
    @staticmethod
    def _classify_event_category(description: str) -> str:
        """分类事件类型"""
        keywords = {
            "travel": ["去了", "旅游", "出差", "飞", "机场"],
            "work": ["项目", "会议", "上班", "加班", "deadline"],
            "social": ["朋友", "聚会", "见面", "约"],
            "health": ["医院", "体检", "锻炼", "跑步", "健身"]
        }
        
        for category, kws in keywords.items():
            if any(kw in description for kw in kws):
                return category
        
        return "other"
```

---

### **3. 地理与天气感知**

```python
class GeographyAwareness:
    """地理感知模块"""
    
    def __init__(self, weather_api_key: Optional[str] = None):
        self.weather_api = WeatherAPI(api_key=weather_api_key) if weather_api_key else None
    
    async def get_user_location(self, user_twin: DigitalTwin) -> Optional[Location]:
        """从用户孪生体获取位置"""
        
        location_fact = user_twin.profile.location
        if not location_fact:
            return None
        
        return Location(
            city=location_fact,
            country="中国",  # 可以从profile推断
            timezone="Asia/Shanghai"
        )
    
    async def get_current_weather(self, location: Location) -> Optional[Weather]:
        """获取当前天气"""
        
        if not self.weather_api:
            return None
        
        data = await self.weather_api.get_current(
            city=location.city,
            country=location.country
        )
        
        return Weather(
            temperature=data["temp"],
            condition=data["condition"],
            humidity=data["humidity"],
            wind_speed=data["wind_speed"],
            updated_at=datetime.now()
        )
```

---

### **4. 知识边界管理**

```python
class KnowledgeBoundaryManager:
    """知识边界管理器"""
    
    def __init__(self, training_cutoff: str = "2026-05-31"):
        self.training_cutoff = datetime.fromisoformat(training_cutoff)
        self.gaps: List[KnowledgeGap] = []
    
    def check_if_outdated(self, query: str, current_time: datetime) -> Optional[KnowledgeGap]:
        """检查查询是否涉及训练数据外的知识"""
        
        # 时间敏感词
        time_sensitive_words = [
            "最近", "今天", "昨天", "这周", "本月",
            "现在", "当前", "最新"
        ]
        
        if any(word in query for word in time_sensitive_words):
            days_gap = (current_time - self.training_cutoff).days
            
            if days_gap > 7:  # 超过1周
                return KnowledgeGap(
                    topic=f"关于'{query}'的最新信息",
                    gap_start=self.training_cutoff,
                    severity="important",
                    how_to_fill="需要搜索最新新闻或使用web_search工具"
                )
        
        return None
    
    def suggest_tool(self, gap: KnowledgeGap) -> str:
        """建议使用的工具"""
        
        if "新闻" in gap.topic or "事件" in gap.topic:
            return "web_search"
        elif "天气" in gap.topic:
            return "weather_api"
        elif "股市" in gap.topic or "汇率" in gap.topic:
            return "financial_api"
        else:
            return "web_search"
```

---

## 🔗 与记忆系统的集成

### **世界对象 + 记忆系统 = 完整认知**

```python
class CognitiveArchitecture:
    """Agent完整认知架构"""
    
    def __init__(
        self,
        memory_backend: MemoryBackend,
        world_model: WorldModel
    ):
        self.memory = memory_backend
        self.world = world_model
    
    async def contextualize_query(self, query: str) -> ContextualizedQuery:
        """为查询添加上下文"""
        
        # 1. 时间上下文
        temporal = self.world.temporal
        
        # 2. 用户上下文（从记忆）
        user_twin = await self.memory.get_digital_twin()
        
        # 3. 事件上下文
        recent_events = await self.world.events.get_recent_personal_events()
        
        # 4. 知识边界检查
        gap = self.world.knowledge_boundary.check_if_outdated(
            query, 
            temporal.current_time
        )
        
        return ContextualizedQuery(
            original_query=query,
            temporal_context=temporal,
            user_context=user_twin,
            recent_events=recent_events,
            knowledge_gap=gap,
            suggested_tools=[self.world.knowledge_boundary.suggest_tool(gap)] if gap else []
        )
    
    async def answer_with_context(self, query: str) -> str:
        """带上下文的回答"""
        
        ctx = await self.contextualize_query(query)
        
        # 构建增强的prompt
        prompt = f"""
当前时间: {ctx.temporal_context.date_str} {ctx.temporal_context.time_str}
用户: {ctx.user_context.profile.name or "用户"}
用户最近: {ctx.recent_events[0].description if ctx.recent_events else "无特殊事件"}

{'⚠️ 注意: ' + ctx.knowledge_gap.how_to_fill if ctx.knowledge_gap else ''}

用户问题: {query}

请基于以上上下文回答。
"""
        
        # 调用LLM
        answer = await self.llm_call(prompt)
        
        return answer
```

---

## 📈 使用示例

### **示例1：时间敏感查询**

```python
world = WorldModel(
    temporal=TemporalAwareness.get_current_context(),
    events=EventStream(...),
    geography=GeographyContext(...),
    knowledge_boundary=KnowledgeBoundary(training_cutoff="2026-05-31")
)

# 用户："今天是几号？"
temporal = world.temporal
answer = f"{temporal.date_str}，{temporal.weekday}"
# → "2026年8月17日，星期六"
```

### **示例2：事件感知**

```python
# 用户："最近有什么重要的事吗？"
personal = await world.events.get_recent_personal_events(days=7)
world_events = await world.events.get_recent_world_events(days=3)

answer = f"""
你最近的事:
- {personal[0].description} ({temporal.format_relative(personal[0].timestamp)})

最近的新闻:
- {world_events[0].title}
"""
```

### **示例3：知识边界检测**

```python
# 用户："最近AI有什么新突破？"
gap = world.knowledge_boundary.check_if_outdated(
    "最近AI有什么新突破",
    datetime.now()
)

if gap:
    tool = world.knowledge_boundary.suggest_tool(gap)
    # → 调用web_search工具获取最新信息
```

---

## 🎯 数据源配置

### **1. 新闻API**

```python
NEWS_SOURCES = {
    "cn": {
        "provider": "toutiao_api",  # 今日头条API
        "categories": ["tech", "finance", "society"],
        "update_frequency": "hourly"
    },
    "en": {
        "provider": "newsapi.org",
        "categories": ["technology", "business"],
        "update_frequency": "hourly"
    }
}
```

### **2. 天气API**

```python
WEATHER_SOURCES = {
    "provider": "openweathermap",
    "update_frequency": "every_30_minutes"
}
```

### **3. Web搜索（备选）**

```python
WEB_SEARCH = {
    "provider": "duckduckgo" | "bing" | "google",
    "use_case": "当新闻API不可用时的备选"
}
```

---

## ⚙️ 配置示例

```toml
[world_model]
enabled = true
training_cutoff = "2026-05-31"

[world_model.temporal]
timezone = "Asia/Shanghai"
locale = "zh_CN"

[world_model.events]
personal_event_window_days = 7
world_event_window_days = 3
tech_event_window_days = 7

[world_model.news]
enabled = true
provider = "toutiao_api"  # or "newsapi.org"
api_key = "${NEWS_API_KEY}"  # from env
categories = ["tech", "business"]
update_frequency = "hourly"

[world_model.weather]
enabled = true
provider = "openweathermap"
api_key = "${WEATHER_API_KEY}"
update_frequency = "30min"

[world_model.web_search]
enabled = true
provider = "duckduckgo"  # 免费，无需API key
fallback_provider = "bing"
```

---

## 📊 完整架构图

```
┌────────────────────────────────────────────────────────┐
│                  Agent 认知架构                         │
└────────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────┴─────────────────┐
        ↓                                   ↓
┌───────────────┐                  ┌─────────────────┐
│ 内部认知       │                  │ 外部感知         │
│ (Memory)      │                  │ (World Model)   │
├───────────────┤                  ├─────────────────┤
│ · 用户画像     │                  │ · 当前时间       │
│ · 对话历史     │←─────融合────────│ · 最近事件       │
│ · 知识事实     │                  │ · 天气位置       │
│               │                  │ · 知识边界       │
└───────────────┘                  └─────────────────┘
        ↓                                   ↓
        └────────────┬───────────────────────┘
                    ↓
         ┌─────────────────────┐
         │  上下文化的查询       │
         │  (Contextualized)   │
         └─────────────────────┘
                    ↓
         ┌─────────────────────┐
         │  LLM推理 + 工具调用  │
         └─────────────────────┘
                    ↓
         ┌─────────────────────┐
         │  个性化、时效性的回答 │
         └─────────────────────┘
```

---

## ✅ 总结

### **世界对象的核心价值：**

1. **时间感知** - Agent知道"现在"
2. **事件感知** - Agent知道"最近发生了什么"
3. **知识边界** - Agent知道"自己不知道什么"
4. **主动工具使用** - 检测到知识差距→自动调用工具

### **与记忆系统的区别：**

| 维度 | 记忆系统 | 世界对象 |
|---|---|---|
| **焦点** | 用户（内部） | 世界（外部） |
| **时效性** | 历史记录 | 实时更新 |
| **数据源** | 对话提取 | API/新闻/传感器 |
| **衰减** | 有（遗忘曲线） | 无（总是最新） |

### **两者结合才是完整认知！**

```
完整回答 = 记忆系统（谁） + 世界对象（什么时候、发生了什么）
```
