# Memory SDK 认知架构设计

**创建日期**: 2026-08-17  
**基于**: Simple Harness现有记忆系统（基于认知科学和记忆理论）

---

## 🧠 核心理念：模拟人类记忆系统

现有的Simple Harness记忆系统**不是简单的数据库**，而是基于认知科学的多层记忆架构：

### **人类记忆的三层模型**

```
┌─────────────────────────────────────────────────────────┐
│  L1: 工作记忆 (Working Memory)                          │
│  - 容量小，立即可用                                      │
│  - 像人的"短期记忆"                                      │
│  - 例子：当前对话的上下文                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  L2: 情景记忆 (Episodic Memory)                         │
│  - 完整的经历/对话记录                                   │
│  - 像人的"事件记忆"（你记得昨天干了什么）                │
│  - 例子：消息历史、时间戳、上下文                        │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  L3: 语义记忆 (Semantic Memory)                         │
│  - 抽象的知识和事实                                      │
│  - 像人的"知识记忆"（你知道Paris是法国首都）             │
│  - 例子：Facts提取、向量索引、实体关系                   │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 完整的数据结构设计

### **1. Messages（情景记忆层）**

这是**原始对话记录**，保留完整上下文：

```python
@dataclass
class Message:
    """对话消息（情景记忆）"""
    id: int
    session_id: str         # 会话ID（隔离不同任务）
    role: str              # "user" | "assistant" | "system" | "tool"
    content: str           # 原始文本
    created_at: float      # Unix时间戳
    
    # 认知科学特性
    salience: float = 0.0         # 显著性（被召回次数影响）
    decay_rate: float = 0.02      # 衰减率（随时间遗忘）
    last_recalled: Optional[float] = None  # 最后召回时间
    
    # 向量化
    embedding: Optional[bytes] = None      # BGE-M3向量（BLOB）
    
    # 元数据
    is_summary: bool = False      # 是否是压缩的summary
    summary_of: Optional[str] = None  # summary的源消息ID列表（JSON）
    
    # 工作流关联
    workflow_event_id: Optional[str] = None
```

**关键特性：**

1. **Salience（显著性）**：模拟人类记忆的"重要性标记"
   - 每次召回 +0.05
   - 越常用的记忆越容易被想起

2. **Decay（遗忘曲线）**：模拟Ebbinghaus遗忘曲线
   - `score = base_score * exp(-decay_rate * days_since_last_recall)`
   - 不常用的记忆自动淡化

3. **Session隔离**：不同任务的记忆互不干扰
   - `code-xxx`：代码任务
   - `companion-xxx`：日常对话
   - 跨session召回时自动降权

---

### **2. Facts（语义记忆层）**

从对话中**自动提取的结构化知识**：

```python
@dataclass
class Fact:
    """提取的事实（语义记忆）"""
    id: int
    
    # 事实三元组（主-谓-宾）
    subject: str           # 主体，如 "user"
    key: str              # 属性key（英文snake_case），如 "pet_name"
    value: str            # 值（保持原语言），如 "Max"
    
    # 分类（基于记忆类型）
    category: str         # 见下方类别详解
    confidence: float     # LLM提取的置信度 0.0-1.0
    
    # 溯源
    source_msg_id: int           # 来源消息ID
    evidence: str                # 原文引用（verbatim）
    
    # 时间与状态
    created_at: float
    updated_at: float
    is_active: bool = True       # 是否有效（矛盾检测可能标记为inactive）
    
    # 认知科学特性
    decay_rate: float            # 不同类别有不同衰减率
    last_recalled: Optional[float] = None
    
    # 向量化（语义搜索）
    embedding: Optional[bytes] = None  # "key: value"的BGE-M3向量
    
    # Stage 2: 矛盾检测与遗忘
    superseded_by: Optional[int] = None    # 被哪个fact替代
    forgotten_at: Optional[float] = None   # 显式遗忘时间
    
    # FP-4: 作用域与钉住
    scope: str = "user"           # "user" | "session"（用户级 vs 会话级）
    pinned: bool = False          # 用户手动钉住（跳过衰减）
```

**Fact类别（Category）及衰减率：**

基于认知科学的记忆类型分类：

```python
FACT_CATEGORIES = {
    # 基础类别（Stage 1）
    "profile": {
        "decay_rate": 0.0,      # 永不衰减
        "例子": "用户姓名、生日、职业",
        "认知类型": "语义记忆（身份信息）"
    },
    "preference": {
        "decay_rate": 0.005,    # ~200天半衰期
        "例子": "喜欢喝茶、偏好深色主题",
        "认知类型": "程序性记忆（习惯偏好）"
    },
    "project": {
        "decay_rate": 0.01,     # ~70天半衰期
        "例子": "正在做的项目、技术栈",
        "认知类型": "情景记忆转语义记忆"
    },
    "event": {
        "decay_rate": 0.05,     # ~14天半衰期
        "例子": "昨天去了北京",
        "认知类型": "情景记忆（快速遗忘）"
    },
    "reflection": {
        "decay_rate": 0.02,     # ~35天半衰期
        "例子": "用户擅长前端但后端较弱",
        "认知类型": "元认知（反思性知识）"
    },
    
    # Stage 2: 情景→语义固化
    "episodic_summary": {
        "decay_rate": 0.01,     # 慢衰减
        "例子": "从对话summary中提取的长期事实",
        "认知类型": "情景记忆的语义化"
    },
    
    # FP-4: 目标导向
    "goal": {
        "decay_rate": 0.005,    # ~200天
        "例子": "我想在月底前完成X",
        "认知类型": "前瞻性记忆（prospective memory）"
    },
    "decision": {
        "decay_rate": 0.002,    # ~1年
        "例子": "这个项目决定用TypeScript",
        "认知类型": "程序性记忆（决策历史）"
    },
    "constraint": {
        "decay_rate": 0.001,    # 最慢
        "例子": "只能用开源库、预算2000以内",
        "认知类型": "语义记忆（约束条件）"
    },
    
    # 程序性记忆
    "learning": {
        "decay_rate": 0.01,     # ~70天
        "例子": "用户上次PPT要深色主题、生成周报的步骤",
        "认知类型": "程序性记忆（经验知识）"
    }
}
```

---

### **3. 混合召回（Hybrid Retrieval with RRF）**

模拟人类记忆的**多路径激活**：

```python
@dataclass
class Hit:
    """召回结果（单条记忆）"""
    message_id: int        # 消息ID（facts用偏移: 1_000_000_000_000_000 + fact_id）
    text: str             # 文本内容
    score: float          # 融合分数
    source: str           # 来源："vec" | "fts" | "recency" | "salience" | "facts" | "entity"
    
    # 认知特性
    recency: float        # 时间新近度
    salience: float       # 显著性
    session_affinity: float  # 会话相关性（跨session降权）
```

**RRF融合算法（Reciprocal Rank Fusion）：**

```python
# 四路并行召回
sources = {
    "vec":      0.5,   # 向量语义相似度（最重要）
    "fts":      0.3,   # 全文关键词匹配
    "recency":  0.15,  # 时间新近度
    "salience": 0.05,  # 显著性（被召回次数）
    "facts":    0.2,   # Facts路（Stage 1+）
    "entity":   0.1    # 实体索引（Stage 2+）
}

# 融合公式（k=60经典值）
rrf_score(item) = Σ [weight[source] / (60 + rank[source])]
                 for each source that hit this item
```

**为什么是RRF而不是简单加权？**

- **RRF对异常值鲁棒**：某一路召回失败不会拖垮整体
- **Rank比Score更稳定**：不同召回源的分数scale不同，用排名更公平
- **学术验证**：Cormack等人在IR领域验证的经典算法

---

### **4. 工作记忆（Workspace Memory）**

模拟**程序性记忆**（如何做事的记忆）：

```python
@dataclass
class WorkspaceState:
    """代码任务的工作记忆"""
    session_id: str
    path: str                    # 文件路径
    last_action: str            # "read" | "write"
    last_action_ts: float       # 最后操作时间
    
    # 内容指纹
    content_hash: str           # SHA1哈希
    content_summary: Optional[str] = None  # LLM生成的摘要
    byte_size: int
```

**作用：**

- Agent记住"刚才改过哪些文件"
- 下次任务优先召回相关文件
- 减少重复的`file_read`调用

---

### **5. 记忆压缩（Summarization）**

模拟人类的**记忆整合**（睡眠时的记忆巩固）：

```python
@dataclass
class MessageSummary:
    """压缩的对话摘要"""
    id: int
    session_id: str
    role: str = "system"        # 固定为system
    is_summary: bool = True     # 标记为summary
    
    content: str                # 压缩后的文本（LLM生成）
    summary_of: str             # 源消息ID列表（JSON）
    
    created_at: float
    embedding: Optional[bytes] = None
```

**压缩策略：**

1. **触发条件**：对话超过N轮（如30轮）
2. **压缩范围**：老旧消息（保留最近K条）
3. **二次提取**：从summary中提取Facts（episodic→semantic）

---

### **6. 矛盾检测与演化（Stage 2）**

模拟人类的**记忆更新机制**：

```python
@dataclass
class FactConflict:
    """检测到的事实矛盾"""
    old_fact_id: int
    new_fact: Fact
    conflict_type: str    # "replace" | "merge" | "no-op"
    reason: str           # LLM解释
    confidence: float
```

**跨Key矛盾检测：**

```
旧事实: (subject="user", key="allergy_peanut", value="对花生过敏")
新消息: "其实我是过敏海鲜，不过敏花生"
↓
LLM检测: 发现矛盾
↓
结果: 
  - 旧fact标记 is_active=0, superseded_by=<新fact_id>
  - 新fact插入 (key="allergy_seafood", value="过敏海鲜")
```

**混合视野（防止漏判）：**

```python
# 候选集 = 时间最近20条 ∪ 语义最近10条
recent = facts_store.list_active(subject="user", limit=20)
semantic = facts_store.vector_search(embedding, limit=10)
candidates = merge_dedup(recent, semantic, max=25)
```

---

### **7. 显式遗忘（Memory Forget）**

模拟人类的**主动遗忘**：

```python
@dataclass
class ForgetOperation:
    """遗忘操作记录"""
    op_id: str                  # UUID（用于5秒undo）
    fact_ids: list[int]         # 被遗忘的fact ID列表
    forgotten_at: float         # 遗忘时间
    reason: str                 # 原因（用户请求/自动清理）
```

**两种模式：**

1. **精确删除**：`memory_forget(fact_id=123)`
2. **自然语言删除**（默认禁用，需显式开启）：
   ```python
   memory_forget(query="忘记我的生日")
   # → 向量召回 → LLM二次确认 → 标记forgotten_at
   ```

**安全规则：**

- Query < 6字 → 拒绝
- 命中 > 5条 → 拒绝（防止"忘记所有"灾难）
- 单次最多删3条
- 5秒undo窗口

---

## 🎯 Memory SDK的Port接口设计

基于上述认知架构，SDK应该暴露这些抽象：

```python
from abc import ABC, abstractmethod
from typing import Protocol

class MemoryBackend(ABC):
    """记忆后端抽象接口（符合认知科学）"""
    
    # ========== L2: 情景记忆 ==========
    @abstractmethod
    async def append_message(
        self, 
        session_id: str, 
        role: str, 
        content: str
    ) -> int:
        """保存一条消息到情景记忆"""
        pass
    
    @abstractmethod
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10
    ) -> list[Message]:
        """获取最近的对话（工作记忆）"""
        pass
    
    # ========== L3: 语义记忆（Facts） ==========
    @abstractmethod
    async def extract_facts(
        self, 
        message_id: int, 
        content: str, 
        role: str
    ) -> list[Fact]:
        """从消息中自动提取事实"""
        pass
    
    @abstractmethod
    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True
    ) -> list[Fact]:
        """查询语义记忆"""
        pass
    
    @abstractmethod
    async def forget_fact(
        self, 
        fact_id: int, 
        reason: str = "user_request"
    ) -> ForgetOperation:
        """显式遗忘一个事实"""
        pass
    
    # ========== 混合召回 ==========
    @abstractmethod
    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> list[Hit]:
        """
        混合召回（模拟人类记忆激活）
        
        内部执行：
        1. 四路并行召回（vec/fts/recency/salience）
        2. Facts路召回
        3. Entity路召回（如果启用）
        4. RRF融合
        5. Rerank重排序
        6. 更新salience（召回的记忆+0.05）
        """
        pass
    
    # ========== 记忆维护 ==========
    @abstractmethod
    async def daily_decay(self) -> dict:
        """
        每日衰减（模拟遗忘曲线）
        
        salience *= exp(-decay_rate * days_since_last_recall)
        """
        pass
    
    @abstractmethod
    async def summarize_old_sessions(
        self, 
        session_id: str,
        keep_recent: int = 20
    ) -> int:
        """
        压缩老旧对话（模拟记忆整合）
        
        返回: summary message ID
        """
        pass
    
    # ========== 工作记忆 ==========
    @abstractmethod
    async def record_workspace_action(
        self,
        session_id: str,
        path: str,
        action: str,
        content_hash: str
    ) -> None:
        """记录代码任务的工作记忆"""
        pass
    
    @abstractmethod
    async def recall_workspace(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ) -> list[WorkspaceState]:
        """召回相关的工作记忆"""
        pass
```

---

## 🔑 关键设计决策

### **1. 为什么要分层？**

**认知科学依据：**
- Atkinson-Shiffrin模型（1968）：人类记忆分短期/长期
- Tulving（1972）：长期记忆分情景记忆/语义记忆
- Baddeley（2000）：工作记忆的多成分模型

**工程优势：**
- L1（工作记忆）：O(1)快速访问
- L2（情景记忆）：完整保留，可审计
- L3（语义记忆）：压缩、索引、快速检索

---

### **2. 为什么用RRF而不是向量搜索？**

**单一向量搜索的问题：**
- ❌ 语义漂移（"苹果"可能召回"水果"而不是"iPhone"）
- ❌ 忽略时间信息（昨天的消息比去年的更重要）
- ❌ 忽略使用频率（常用的记忆应该更容易想起）

**RRF融合的优势：**
- ✅ 多路信号互补（语义+关键词+时间+频率）
- ✅ 鲁棒性强（一路失败不影响整体）
- ✅ 学术验证（IR领域经典算法）

---

### **3. 为什么Facts要有Category？**

**认知科学依据：**
- 不同类型的记忆有不同的遗忘曲线
- Profile（身份信息）几乎不遗忘
- Event（事件）快速遗忘
- Preference（偏好）介于两者之间

**工程优势：**
- 差异化衰减率
- 分类召回（"用户有什么偏好？"）
- 优先级管理

---

### **4. 为什么要Salience？**

**认知科学依据：**
- Spreading Activation理论：常用的概念更容易激活
- 记忆强度（Memory Strength）：使用次数影响回忆概率

**实现方式：**
```python
# 每次召回命中
salience += 0.05
salience = min(salience, 1.0)  # 上限

# 每日衰减
salience *= exp(-decay_rate * days)
salience = max(salience, 0.0)  # 下限
```

---

## 📦 SDK实现建议

### **模块拆分：**

```
simple-harness-memory-sdk/
├── core/
│   ├── port.py              # 抽象接口
│   ├── models.py            # Message/Fact/Hit等数据类
│   └── constants.py         # 类别、衰减率等常量
├── backends/
│   ├── sqlite.py            # SQLite实现
│   └── mock.py              # 测试用Mock
├── features/
│   ├── facts_extractor.py   # Facts自动提取
│   ├── retriever.py         # 混合召回+RRF
│   ├── reranker.py          # 重排序
│   ├── summarizer.py        # 记忆压缩
│   └── conflict_detector.py # 矛盾检测
├── embedders/
│   ├── bge.py               # BGE-M3
│   └── mock.py              # Mock
└── cognitive/
    ├── decay.py             # 遗忘曲线
    ├── salience.py          # 显著性更新
    └── session_affinity.py  # 会话相关性
```

---

## 🎓 相关认知科学文献

1. **Atkinson & Shiffrin (1968)**: Human Memory: A Proposed System
2. **Tulving (1972)**: Episodic and Semantic Memory
3. **Ebbinghaus (1885)**: Memory: A Contribution to Experimental Psychology
4. **Baddeley (2000)**: The episodic buffer: a new component of working memory
5. **Collins & Loftus (1975)**: Spreading Activation Theory

---

## ✅ 下一步行动

1. **确认理解**：这份架构设计清楚了吗？
2. **选择起点**：
   - 从Port接口开始？
   - 先实现Facts提取？
   - 先搭建RRF召回？
3. **提取代码**：从现有`backend/deskpet/memory/`中提取哪些模块？

**告诉我你的想法，我们开始实施！** 🚀
