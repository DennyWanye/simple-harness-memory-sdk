# Memory SDK 架构设计文档

> 历史基线：本文保留 0.4/0.5 的原始设计以便审计，不是 0.6 生产事实源。
> 0.6 当前边界见 [`../ARCHITECTURE/ARCHITECTURE.md`](../ARCHITECTURE/ARCHITECTURE.md)，
> fresh schema 见 [`human-memory-v1-schema.md`](human-memory-v1-schema.md)。

**创建日期**: 2026-08-17
**状态**: 已实施（Phase 1-4 本地切片完成；2026-08-19 已接入 Simple Harness host 并真机 E2E 验证）
**决策来源**: 2026-08-17 头脑风暴会话

---

## 0. 一句话

将 Simple Harness 的记忆系统从主应用中完全剥离，构建独立的 `simple-harness-memory-sdk` 包，基于认知科学三层模型 + 数字孪生体 + 世界对象，重新实现完整的智能记忆系统。

---

## 1. 背景与动机

### 1.1 现有系统的问题

| 问题 | 说明 |
|---|---|
| 扁平的 Facts 设计 | 只有键值对，没有层次结构和关系图谱 |
| 没有数字孪生体 | 无法建立用户的完整认知模型 |
| 没有世界对象 | Agent 不知道当前时间、外部事件 |
| 紧耦合到主应用 | 17,579 行代码嵌入主仓库，难以独立迭代 |
| 只支持本地 SQLite | 无法扩展到云端后端，无法跨设备同步 |
| 部分代码未接入 | Stage 1/2 的大量功能写完但未激活 |

### 1.2 重构目标

- **独立 SDK**：作为独立 pip 包发布，主应用通过依赖引用
- **认知科学基础**：基于三层记忆模型、遗忘曲线、显著性机制
- **数字孪生体**：完整的用户建模（身份/技能/偏好/关系/目标）
- **世界对象**：Agent 感知外部世界（时间/事件/天气/知识边界）
- **可插拔后端**：本地 SQLite 优先，后续支持云端向量数据库
- **从 0 开始**：不复用旧代码，基于新架构全新实现

---

## 2. 核心架构：认知三层模型

### 2.1 人类记忆的映射

```
人类记忆系统              →  Memory SDK 对应实现
─────────────────────────────────────────────────
工作记忆 (Working Memory)  → L1: 当前会话上下文
情景记忆 (Episodic Memory) → L2: Messages 表（完整对话历史）
语义记忆 (Semantic Memory) → L3: Facts 表（抽象知识事实）
程序性记忆 (Procedural)    → Workspace Memory（如何做事）
前瞻性记忆 (Prospective)   → Goals（目标与计划）
```

### 2.2 层次结构

```
┌────────────────────────────────────────────────────────┐
│                   Agent 认知架构                        │
├────────────────────────────────────────────────────────┤
│  内部认知（Memory System）                              │
│  ┌─────────────────────────────────────────────┐       │
│  │  L1: 工作记忆 (Messages)                     │       │
│  │  - 当前会话上下文，立即可用                   │       │
│  ├─────────────────────────────────────────────┤       │
│  │  L2: 情景记忆 (Episodes)                     │       │
│  │  - 完整对话历史 + 时间戳 + 遗忘曲线           │       │
│  ├─────────────────────────────────────────────┤       │
│  │  L3: 语义记忆 (Facts + Entities)             │       │
│  │  - 从对话中自动提取的结构化事实               │       │
│  ├─────────────────────────────────────────────┤       │
│  │  数字孪生体 (Digital Twin)                   │       │
│  │  - 用户的完整认知模型（身份/技能/关系/目标）  │       │
│  └─────────────────────────────────────────────┘       │
├────────────────────────────────────────────────────────┤
│  外部感知（World Model）                                │
│  - 时间感知 / 事件感知 / 地理感知 / 知识边界            │
└────────────────────────────────────────────────────────┘
                          ↓
         ┌────────────────────────────┐
         │  RRF 混合召回引擎           │
         │  (多路信号融合)             │
         └────────────────────────────┘
                          ↓
         ┌────────────────────────────┐
         │  个性化、时效性的回答        │
         └────────────────────────────┘
```

---

## 3. 数据结构设计

### 3.1 Message（情景记忆）

```python
@dataclass
class Message:
    id: Optional[int]
    session_id: str         # 会话隔离（不同任务互不干扰）
    role: str               # "user" | "assistant" | "system" | "tool"
    content: str

    # 认知科学特性
    salience: float = 0.0          # 显著性（被召回次数影响）
    decay_rate: float = 0.02       # 衰减率（Ebbinghaus遗忘曲线）
    last_recalled: Optional[float] # 最后召回时间

    # 向量化
    embedding: Optional[bytes]     # BGE-M3向量 (BLOB)

    # 元数据
    is_summary: bool = False       # 是否是压缩的summary
    summary_of: Optional[str]      # summary的源消息ID列表
```

**关键机制：**
- `salience`：每次被召回 +0.05，模拟 Spreading Activation 理论
- `decay_rate`：`score = base * exp(-rate * days_since_last_recall)`
- `session_id`：跨 session 召回时自动降权（code session vs companion session）

---

### 3.2 Fact（语义记忆）

```python
@dataclass
class Fact:
    id: Optional[int]
    subject: str       # 主体，如 "user"
    key: str           # 属性 key（英文 snake_case），如 "pet_name"
    value: str         # 值（保持原始语言），如 "Max"
    category: str      # 见下方分类表
    confidence: float  # LLM 提取的置信度 0.0-1.0
    evidence: str      # 原文引用（verbatim）
    source_msg_id: int

    # 认知特性
    decay_rate: float          # 按 category 差异化
    pinned: bool = False       # 用户手动钉住（跳过衰减）

    # 演化（Stage 2）
    superseded_by: Optional[int]  # 被哪个 fact 替代
    forgotten_at: Optional[float] # 显式遗忘时间
```

**Fact 分类与衰减率（基于认知科学）：**

| Category | 衰减率 | 半衰期 | 认知类型 | 示例 |
|---|---|---|---|---|
| `profile` | 0.0 | 永久 | 语义记忆（身份） | 姓名、生日 |
| `preference` | 0.005 | ~200天 | 程序性记忆（习惯） | 喜欢喝茶 |
| `project` | 0.01 | ~70天 | 情景→语义 | 正在做的项目 |
| `event` | 0.05 | ~14天 | 情景记忆 | 昨天去了北京 |
| `reflection` | 0.02 | ~35天 | 元认知 | 擅长前端 |
| `episodic_summary` | 0.01 | ~70天 | 情景固化 | summary 提取 |
| `goal` | 0.005 | ~200天 | 前瞻性记忆 | 月底完成X |
| `decision` | 0.002 | ~1年 | 程序性记忆 | 选了方案A |
| `constraint` | 0.001 | 最慢 | 语义记忆 | 只用开源库 |
| `learning` | 0.01 | ~70天 | 程序性记忆 | PPT 要深色主题 |

---

### 3.3 Digital Twin（数字孪生体）

用户的**完整认知模型**，不只是零散 Facts：

```python
@dataclass
class DigitalTwin:
    subject: str = "user"

    # 5个核心维度
    profile: UserProfile             # 身份层（姓名/职业/位置）
    skills: SkillMap                 # 认知层（技能图谱）
    preferences: PreferenceMap       # 情感层（偏好地图）
    relationships: RelationshipGraph # 社交层（实体关系图）
    goals: List[Goal]                # 动机层（目标与约束）

    # 元数据
    completeness: float              # 完整度 0.0-1.0
    confidence: float                # 整体置信度
```

**孪生体功能：**

1. **完整性检查**：知道哪些字段还缺失，主动提问补全
2. **一致性校验**：检测跨维度矛盾（如职业 vs 技能不匹配）
3. **关系推理**：`"Max 怎么样？"` → 查关系图 → 知道 Max 是宠物
4. **时间演化**：技能/偏好/关系随时间衰减更新

**从 Facts 自动构建孪生体：**

```
Facts (profile.name="张三")     → twin.profile.name = "张三"
Facts (key="python_skill")       → twin.skills["python"].level += ...
Facts (key="pet_name", value="Max") → twin.relationships.entities["Max"]
Facts (category="goal")          → twin.goals.append(...)
```

---

### 3.4 Hit（召回结果）

```python
@dataclass
class Hit:
    message_id: int
    text: str
    score: float             # RRF 融合后的分数
    source: str              # "vec"|"fts"|"recency"|"salience"|"facts"|"entity"
    recency: float
    salience: float
    session_affinity: float  # 跨 session 降权系数
```

---

## 4. RRF 混合召回引擎

### 4.1 什么是 RRF？

**Reciprocal Rank Fusion**：把多路召回结果通过"排名投票"融合为一份最终排名。

**核心公式（k=60，Cormack 2009）：**

```
rrf_score(item) = Σ  weight[source] / (k + rank[source])
                 source ∈ item.sources
```

**为什么用排名而不是分数？**
- 不同召回源的 score scale 不同（向量相似度 0-1 vs BM25 0-100）
- 排名是统一的相对量，不需要归一化
- 对异常值鲁棒：一路召回失败不拖垮整体

### 4.2 六路召回信号

| 信号 | 权重 | 说明 |
|---|---|---|
| `vec` | 0.5 | BGE-M3 向量语义相似度 |
| `fts` | 0.3 | FTS5 全文关键词匹配 |
| `recency` | 0.15 | 时间新近度（越新越靠前） |
| `salience` | 0.05 | 显著性（被召回次数） |
| `facts` | 0.2 | Facts 路（结构化事实，Stage 1+） |
| `entity` | 0.1 | 实体索引（Stage 2+） |

### 4.3 Session 亲和性

- **同 session**：权重 1.0
- **code session 召回到 companion**：code-type 类降权到 0.5，person/preference 类保留 0.8
- **同 session 时间衰减**：`0.5^(age/half_life)`，half_life = 7天，floor = 0.15

### 4.4 召回后处理

1. **RRF 融合** → 统一排名
2. **Cross-encoder Reranker**（可选）→ 精排 top-30
3. **Salience 更新** → 命中的消息 salience += 0.05

---

## 5. 世界对象（World Model）

### 5.1 设计动机

记忆系统是**内部认知**（用户相关），世界对象是**外部感知**（世界相关）：

| 维度 | 记忆系统 | 世界对象 |
|---|---|---|
| 焦点 | 用户（内部） | 世界（外部） |
| 时效性 | 历史记录 | 实时更新 |
| 数据源 | 对话提取 | API/新闻/传感器 |
| 衰减 | 有（遗忘曲线） | 无（总是最新） |

### 5.2 数据结构

```python
@dataclass
class WorldModel:
    temporal: TemporalContext      # 当前时间/星期/节假日/季节
    events: EventStream            # 个人事件 + 世界事件（新闻）
    geography: GeographyContext    # 用户位置 + 天气
    knowledge_boundary: KnowledgeBoundary  # LLM 知识截止日期 + 差距
```

### 5.3 四个子系统

**时间感知（TemporalContext）：**
```python
temporal.current_time      # 2026-08-17 14:30
temporal.weekday           # "星期六"
temporal.time_of_day       # "afternoon"
temporal.season            # "summer"
temporal.is_holiday        # False
temporal.format_relative(past_time)  # "3天前"
```

**事件感知（EventStream）：**
- 个人事件：从用户 Facts 中提取（category="event"），近7天
- 世界事件：新闻 API 获取（今日头条/NewsAPI），近3天
- 技术事件：技术新闻，近7天
- 按用户数字孪生体的 skills/interests 计算个性化 relevance

**地理感知（GeographyContext）：**
- 从用户 profile.location 获取城市
- 天气 API（OpenWeatherMap）实时查询
- 刷新频率：30分钟

**知识边界（KnowledgeBoundary）：**
- 记录 LLM 训练截止日期（如 2026-05-31）
- 检测时间敏感词（"最近"、"今天"、"最新"）
- 自动建议工具（web_search / weather_api / financial_api）

### 5.4 工作方式

```
用户问："最近 AI 有什么新突破？"
         ↓
1. KnowledgeBoundary 检测到时间敏感词
2. 计算知识差距：今天 - 训练截止 = X天
3. 建议调用 web_search 工具
4. 返回最新搜索结果 + LLM 综合回答
```

```
用户问："今天出门穿什么？"
         ↓
1. temporal.current_time → 知道是2026-08-17
2. twin.profile.location → 北京
3. geography.weather → 今天22°C，多云
4. 回答："北京今天22°C多云，建议穿长袖"
```

---

## 6. Port 接口设计

### 6.1 MemoryBackend（核心抽象）

```python
class MemoryBackend(ABC):

    # L2: 情景记忆
    async def append_message(session_id, role, content) -> int
    async def get_recent_messages(session_id, limit) -> List[Message]

    # L3: 语义记忆
    async def extract_facts(message_id, content, role) -> List[Fact]
    async def get_facts(subject, category, active_only) -> List[Fact]
    async def forget_fact(fact_id, reason) -> ForgetOperation

    # 数字孪生体
    async def get_digital_twin(subject) -> DigitalTwin
    async def update_digital_twin(twin) -> None
    async def suggest_questions(subject) -> List[str]       # 补全空白
    async def detect_inconsistencies(subject) -> List[...]  # 矛盾检测

    # 混合召回
    async def recall(query, session_id, limit) -> List[Hit]
    async def vector_search(query, limit) -> List[Hit]

    # 认知维护
    async def daily_decay() -> dict          # 遗忘曲线
    async def summarize_old_sessions(...)    # 记忆压缩
    async def record_workspace_action(...)   # 工作记忆
```

### 6.2 WorldModelPort（世界感知抽象）

```python
class WorldModelPort(ABC):
    async def get_temporal_context() -> TemporalContext
    async def get_recent_events(days) -> List[Event]
    async def get_weather(location) -> Optional[Weather]
    async def check_knowledge_boundary(query) -> Optional[KnowledgeGap]
    async def get_personalized_news(twin, categories) -> List[WorldEvent]
```

---

## 7. SDK 包设计

### 7.1 仓库结构

```
simple-harness-memory-sdk/          ← 新的独立 git 仓库
├── pyproject.toml
├── README.md
├── src/
│   └── simple_harness_memory/
│       ├── __init__.py
│       ├── core/
│       │   ├── port.py             # MemoryBackend 抽象接口
│       │   ├── models.py           # Message/Fact/Hit 数据类
│       │   └── twin.py             # DigitalTwin 完整定义
│       ├── backends/
│       │   ├── sqlite.py           # SQLite 本地后端（Phase 1）
│       │   ├── mock.py             # Mock 后端（测试用）
│       │   └── pinecone.py         # 云端后端（Phase 3，待开发）
│       ├── features/
│       │   ├── facts.py            # Facts 自动提取
│       │   ├── retriever.py        # 六路召回
│       │   ├── rrf.py              # RRF 融合算法
│       │   ├── reranker.py         # Cross-encoder 重排序
│       │   └── summarizer.py       # 记忆压缩
│       ├── embedders/
│       │   ├── bge.py              # BGE-M3 本地模型
│       │   └── mock.py             # Mock（hash伪向量）
│       ├── cognitive/
│       │   ├── decay.py            # 遗忘曲线（Ebbinghaus）
│       │   ├── salience.py         # 显著性机制
│       │   └── session_affinity.py # 会话亲和性
│       └── world/
│           ├── port.py             # WorldModelPort 抽象
│           ├── temporal.py         # 时间感知
│           ├── events.py           # 事件感知
│           ├── geography.py        # 地理感知
│           └── knowledge.py        # 知识边界
└── tests/
    ├── unit/
    └── integration/
```

### 7.2 依赖分层

```toml
[project.dependencies]           # 核心（必须）
aiosqlite = ">=0.19"
pydantic = ">=2.0"
numpy = ">=1.24"

[project.optional-dependencies]
embeddings = ["torch", "sentence-transformers"]   # BGE-M3
world = ["httpx", "python-dateutil"]              # 世界对象API
openai = ["openai>=1.0"]                          # LLM客户端
all = ["...[embeddings,world,openai]"]
```

### 7.3 安装方式

```bash
pip install simple-harness-memory-sdk              # 基础
pip install simple-harness-memory-sdk[embeddings]  # 含BGE-M3
pip install simple-harness-memory-sdk[all]         # 完整
```

---

## 8. 与主应用的集成方式

### 8.1 主应用添加依赖

```python
# backend/requirements.txt
simple-harness-memory-sdk[embeddings] @ file://../../simple-harness-memory-sdk
```

### 8.2 主应用使用

```python
# backend/main.py
from simple_harness_memory import MemoryManager

memory = await MemoryManager.build(
    db_path="./data/memory.db",
    enable_facts=True,
    enable_world_model=True,
)

# 保存消息（自动触发 facts 提取、embedding、twin 更新）
msg_id = await memory.append_message(
    session_id="chat-001",
    role="user",
    content="我养了一只叫Max的狗，很喜欢吃披萨"
)

# 混合召回（RRF 六路融合）
hits = await memory.recall(query="用户养了什么宠物？")

# 查询数字孪生体
twin = await memory.get_digital_twin()
print(twin.relationships.entities["Max"])  # → Entity(type="pet", ...)

# 获取世界上下文
ctx = await memory.world.get_temporal_context()
print(f"今天是{ctx.date_str}，{ctx.weekday}")
```

---

## 9. 开发路线图

### Phase 1: MVP（2-3周）
- [ ] 创建独立 git 仓库
- [ ] Port 接口定义（`core/port.py`）
- [ ] 核心数据模型（`core/models.py`，`core/twin.py`）
- [ ] Mock 后端（`backends/mock.py`）
- [ ] SQLite 后端基础实现
- [ ] 单元测试覆盖率 > 80%

**验收：** 能存/取消息，Mock 模式跑通所有 API

### Phase 2: 智能特性（1-2周）
- [ ] Facts 自动提取（`features/facts.py`）
- [ ] BGE-M3 Embedder（`embedders/bge.py`）
- [ ] RRF 融合（`features/rrf.py`）
- [ ] 六路召回（`features/retriever.py`）
- [ ] Reranker（`features/reranker.py`）

**验收：** 语义搜索准确，hit@5 达标

### Phase 3: 认知特性（1周）
- [ ] 遗忘曲线（`cognitive/decay.py`）
- [ ] 显著性机制（`cognitive/salience.py`）
- [ ] 数字孪生体构建（从 Facts 自动更新）
- [ ] 矛盾检测（cross-key conflict）

**验收：** 每日 decay 运行，孪生体随对话更新

### Phase 4: 世界对象（1-2周）
- [ ] 时间感知（`world/temporal.py`）
- [ ] 事件感知（`world/events.py`，含新闻 API）
- [ ] 地理感知（`world/geography.py`，含天气 API）
- [ ] 知识边界（`world/knowledge.py`）

**验收：** Agent 能感知当前时间、最近事件，检测知识差距

### Phase 5: 集成与发布（1周）
- [ ] 集成到 Simple Harness 主应用
- [ ] 渐进式迁移（双写验证）
- [ ] 端到端测试
- [ ] 文档完善

**验收：** 主应用稳定运行，旧代码可移除

### Phase 6: 云端后端（后续）
- [ ] Pinecone 适配器
- [ ] 跨设备同步机制
- [ ] 冲突解决策略

---

## 10. 非目标

- ❌ 不复用旧代码（从 0 开始）
- ❌ 不引入图数据库（关系图谱用 SQLite 实现）
- ❌ Phase 1 不做云端后端（先做好本地）
- ❌ 不做 gradual rollout（testing 阶段直接 default ON）

---

## 11. 风险登记

| # | 风险 | 缓解 |
|---|---|---|
| R1 | Facts 提取质量差 → 脏孪生体 | shadow 模式观察，人工抽查 |
| R2 | RRF 六路召回性能问题 | 并行 fan-out，各路独立超时隔离 |
| R3 | BGE-M3 模型体积大（~2GB） | optional-dependency，mock 降级 |
| R4 | 孪生体更新频率 → 写放大 | 批量写，异步触发 |
| R5 | 世界 API 不可用 | 全部有降级路径（无 API → 返回空） |
| R6 | 主应用迁移冲突 | 双写适配层，保持旧接口向后兼容 |
