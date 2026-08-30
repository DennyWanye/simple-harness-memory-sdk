# Memory SDK 设计文档

**创建日期**: 2026-08-17
**状态**: 头脑风暴阶段
**目标**: 将 Simple Harness 的记忆系统拆分成独立的 SDK

---

## 1. 设计目标

### 1.1 核心价值
- ✅ **轻量化主SDK**：主应用不需要打包所有记忆代码
- ✅ **可插拔后端**：支持本地（SQLite）和未来的云端后端
- ✅ **快速迭代**：记忆功能独立更新，不影响主系统
- ✅ **可重用**：其他项目也能使用这个记忆SDK

### 1.2 范围定义
**包含的功能（完整智能记忆系统）：**
- 基础消息存储和检索
- 自动 Facts 提取（从对话中提取结构化事实）
- 向量搜索（语义相似度检索）
- Enhanced 召回（多路召回 + RRF 融合）
- Reranker（召回结果重排序）
- 工作记忆（Workspace Memory，代码任务上下文）

**暂不包含（后续扩展）：**
- 云端向量数据库后端
- 跨设备同步
- 实体索引
- 跨 key 矛盾检测
- 显式遗忘（memory_forget）

---

## 2. 架构设计

### 2.1 Port 接口（抽象层）

```python
from abc import ABC, abstractmethod
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Message:
    """对话消息"""
    id: Optional[int] = None
    content: str
    role: str  # "user" | "assistant" | "system"
    session_id: str
    created_at: Optional[datetime] = None

@dataclass
class Fact:
    """提取的事实"""
    id: Optional[int] = None
    subject: str        # 主体，如 "user"
    key: str            # 属性key，如 "pet_name"
    value: str          # 值，如 "Max"
    category: str       # 类型："profile" | "preference" | "project" | "event"
    confidence: float   # 置信度 0.0-1.0
    source_msg_id: int  # 来源消息ID
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None
    is_active: bool = True

@dataclass
class SearchResult:
    """搜索结果"""
    content: str
    score: float
    source: str  # "l1" | "l2" | "l3" | "facts"
    message_id: Optional[int] = None
    fact_id: Optional[int] = None
    metadata: dict

class MemoryPort(ABC):
    """记忆系统抽象接口"""
    
    # ========== 消息管理 ==========
    @abstractmethod
    async def save_message(self, message: Message) -> int:
        """保存一条消息，返回消息ID"""
        pass
    
    @abstractmethod
    async def get_message(self, message_id: int) -> Optional[Message]:
        """获取指定消息"""
        pass
    
    @abstractmethod
    async def list_messages(
        self, 
        session_id: str, 
        limit: int = 100,
        offset: int = 0
    ) -> List[Message]:
        """列出会话的消息"""
        pass
    
    # ========== 事实管理 ==========
    @abstractmethod
    async def save_fact(self, fact: Fact) -> int:
        """保存一个事实，返回事实ID"""
        pass
    
    @abstractmethod
    async def get_fact(self, fact_id: int) -> Optional[Fact]:
        """获取指定事实"""
        pass
    
    @abstractmethod
    async def list_facts(
        self,
        subject: Optional[str] = None,
        category: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100
    ) -> List[Fact]:
        """列出事实"""
        pass
    
    # ========== 搜索与召回 ==========
    @abstractmethod
    async def search(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        搜索记忆（Enhanced召回）
        
        内部会：
        1. 多路召回（向量 + 关键词 + 时间衰减 + Facts）
        2. RRF 融合
        3. Reranker 重排序
        """
        pass
    
    @abstractmethod
    async def vector_search(
        self,
        query: str,
        limit: int = 10
    ) -> List[SearchResult]:
        """纯向量语义搜索"""
        pass
    
    # ========== 向量化 ==========
    @abstractmethod
    async def compute_embedding(self, text: str) -> List[float]:
        """计算文本的向量表示"""
        pass
```

### 2.2 实现层：SQLite 后端

```python
from simple_harness_memory.port import MemoryPort, Message, Fact, SearchResult

class SQLiteMemoryBackend(MemoryPort):
    """SQLite 本地存储后端"""
    
    def __init__(
        self,
        db_path: str,
        embedder: Optional["Embedder"] = None,
        facts_extractor: Optional["FactExtractor"] = None,
        enable_enhanced_retrieval: bool = True,
        enable_reranker: bool = True
    ):
        self.db_path = db_path
        self.embedder = embedder or MockEmbedder()  # 降级到Mock
        self.facts_extractor = facts_extractor
        self.enable_enhanced = enable_enhanced_retrieval
        self.enable_reranker = enable_reranker
        
        # 内部组件（从现有代码提取）
        self._session_db = SessionDB(db_path)
        self._facts_store = FactsStore(db_path)
        self._retriever = self._build_retriever()
    
    def _build_retriever(self):
        """构建召回器"""
        base_retriever = Retriever(
            db_path=self.db_path,
            embedder=self.embedder
        )
        
        if self.enable_enhanced:
            return EnhancedRetriever(
                base=base_retriever,
                facts_store=self._facts_store,
                facts_weight=0.2,
                reranker=BGEReranker() if self.enable_reranker else None,
                embedder=self.embedder
            )
        return base_retriever
    
    async def save_message(self, message: Message) -> int:
        """保存消息 + 自动触发Facts提取"""
        msg_id = await self._session_db.append_message(
            session_id=message.session_id,
            role=message.role,
            content=message.content
        )
        
        # 自动Facts提取（如果启用）
        if self.facts_extractor and message.role in ("user", "assistant"):
            await self.facts_extractor.process_message(
                message_id=msg_id,
                content=message.content,
                role=message.role
            )
        
        return msg_id
    
    async def search(self, query: str, session_id: Optional[str] = None, limit: int = 10):
        """Enhanced搜索"""
        hits = await self._retriever.recall(
            query=query,
            session_id=session_id,
            limit=limit
        )
        
        return [
            SearchResult(
                content=hit.text,
                score=hit.score,
                source=hit.source,
                message_id=hit.message_id,
                metadata={"recency": hit.recency}
            )
            for hit in hits
        ]
    
    # ... 其他方法实现
```

### 2.3 高级功能层

#### Facts提取器（从现有代码提取）

```python
class FactExtractor:
    """从对话中自动提取结构化事实"""
    
    def __init__(
        self,
        facts_store: FactsStore,
        llm_client,  # LLM调用客户端
        embedder: Embedder,
        min_chars: int = 10
    ):
        self.facts_store = facts_store
        self.llm = llm_client
        self.embedder = embedder
        self.min_chars = min_chars
    
    async def process_message(
        self,
        message_id: int,
        content: str,
        role: str
    ) -> List[Fact]:
        """
        提取事实的流程：
        1. 检查消息长度
        2. 调用LLM提取结构化事实
        3. 计算embedding
        4. 存储到facts表
        """
        if role not in ("user", "assistant"):
            return []
        
        if len(content.strip()) < self.min_chars:
            return []
        
        # LLM提取
        extracted = await self._llm_extract(content, role)
        
        # 持久化
        persisted = []
        for fact_dict in extracted:
            fact = Fact(
                subject=fact_dict["subject"],
                key=fact_dict["key"],
                value=fact_dict["value"],
                category=fact_dict["category"],
                confidence=fact_dict.get("confidence", 0.8),
                source_msg_id=message_id
            )
            
            # 计算embedding
            fact.embedding = await self.embedder.embed(
                f"{fact.key}: {fact.value}"
            )
            
            fact_id = await self.facts_store.save_fact(fact)
            fact.id = fact_id
            persisted.append(fact)
        
        return persisted
```

#### Embedder（向量计算）

```python
class Embedder(ABC):
    """向量计算抽象接口"""
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """计算向量"""
        pass
    
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        pass

class BGEEmbedder(Embedder):
    """BGE-M3 本地模型"""
    
    def __init__(self, model_path: Optional[str] = None):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(
            model_path or "BAAI/bge-m3"
        )
    
    async def embed(self, text: str) -> List[float]:
        # 在线程池中运行（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self.model.encode(text, normalize_embeddings=True)
        )
        return embedding.tolist()
    
    def dimension(self) -> int:
        return 1024  # BGE-M3

class MockEmbedder(Embedder):
    """Mock实现（测试用，或模型未下载时降级）"""
    
    async def embed(self, text: str) -> List[float]:
        # 简单hash作为伪向量
        import hashlib
        h = hashlib.md5(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:128]]
    
    def dimension(self) -> int:
        return 128
```

---

## 3. 用户API设计

### 3.1 简单模式（开箱即用）

```python
from simple_harness_memory import MemoryManager

# 自动配置（本地SQLite + BGE-M3）
memory = await MemoryManager.build(
    db_path="./memory.db",
    enable_facts=True,
    enable_embeddings=True,
    enable_enhanced_retrieval=True
)

# 保存对话
await memory.save_message(
    content="我养了一只叫Max的狗，它很可爱",
    role="user",
    session_id="chat-001"
)

# 搜索记忆
results = await memory.search(
    query="用户养了什么宠物？",
    limit=5
)

for r in results:
    print(f"[{r.source}] {r.content} (score: {r.score})")
```

### 3.2 高级模式（自定义配置）

```python
from simple_harness_memory import (
    SQLiteMemoryBackend,
    BGEEmbedder,
    FactExtractor,
    EnhancedRetriever
)
from simple_harness_memory.llm import OpenAIClient

# 自定义组件
embedder = BGEEmbedder(model_path="/path/to/bge-m3")
llm_client = OpenAIClient(api_key="sk-...")

memory = SQLiteMemoryBackend(
    db_path="./memory.db",
    embedder=embedder,
    facts_extractor=FactExtractor(
        llm_client=llm_client,
        embedder=embedder,
        min_chars=20  # 自定义阈值
    ),
    enable_enhanced_retrieval=True,
    enable_reranker=True
)

# 同样的API使用
await memory.save_message(...)
results = await memory.search(...)
```

---

## 4. 打包与分发

### 4.1 项目结构

```
simple-harness-memory-sdk/
├── README.md
├── LICENSE
├── pyproject.toml
├── src/
│   └── simple_harness_memory/
│       ├── __init__.py           # 公开API
│       ├── port.py               # Port接口定义
│       ├── manager.py            # MemoryManager工厂类
│       ├── backends/
│       │   ├── __init__.py
│       │   ├── sqlite.py         # SQLite实现
│       │   └── mock.py           # Mock实现（测试用）
│       ├── features/
│       │   ├── __init__.py
│       │   ├── facts.py          # Facts提取
│       │   ├── retriever.py      # 基础召回器
│       │   ├── enhanced_retriever.py  # 增强召回器
│       │   └── reranker.py       # 重排序
│       ├── embedders/
│       │   ├── __init__.py
│       │   ├── base.py           # Embedder接口
│       │   ├── bge.py            # BGE-M3实现
│       │   └── mock.py           # Mock实现
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── session_db.py     # 消息存储
│       │   ├── facts_store.py    # Facts存储
│       │   └── schema.py         # 数据库schema
│       └── llm/
│           ├── __init__.py
│           ├── base.py           # LLM客户端接口
│           └── openai_client.py  # OpenAI实现
└── tests/
    ├── conftest.py
    ├── test_port.py
    ├── test_sqlite_backend.py
    ├── test_facts_extractor.py
    └── test_integration.py
```

### 4.2 依赖管理

```toml
[project]
name = "simple-harness-memory-sdk"
version = "0.1.0"
description = "Intelligent memory system SDK with facts extraction and semantic search"
requires-python = ">=3.11"
dependencies = [
    "aiosqlite>=0.19.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
embeddings = [
    "torch>=2.0.0",
    "sentence-transformers>=2.0.0",
]
openai = [
    "openai>=1.0.0",
]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
]
all = [
    "simple-harness-memory-sdk[embeddings,openai]",
]
```

### 4.3 安装方式

```bash
# 基础安装（不含embedding模型）
pip install simple-harness-memory-sdk

# 完整安装（含BGE-M3）
pip install simple-harness-memory-sdk[embeddings]

# 开发安装
pip install -e ".[dev,all]"
```

---

## 5. 开发路线图

### Phase 1: MVP（预计2-3周）
- [ ] Port接口定义
- [ ] SQLite后端基础实现
- [ ] 基础消息存储/检索
- [ ] Mock Embedder（不依赖模型）
- [ ] 单元测试覆盖

**验收标准：**
- 能存/取消息
- Mock模式下能跑通所有API
- 测试覆盖率 > 80%

### Phase 2: Facts提取（预计1-2周）
- [ ] FactExtractor实现
- [ ] LLM客户端抽象
- [ ] Facts存储schema
- [ ] 自动触发提取

**验收标准：**
- 保存消息自动提取Facts
- Facts能被搜索和列出

### Phase 3: 向量搜索（预计1-2周）
- [ ] BGEEmbedder实现
- [ ] 向量存储（embedding列）
- [ ] 向量召回（brute-force）
- [ ] 降级机制（模型未下载时用Mock）

**验收标准：**
- 语义搜索能工作
- 中文查询准确率达标

### Phase 4: Enhanced召回（预计1周）
- [ ] 多路召回（向量+FTS+时间衰减）
- [ ] RRF融合
- [ ] Facts路融合
- [ ] Reranker重排序

**验收标准：**
- 召回质量 hit@5 达到baseline
- 与现有系统对比无回归

### Phase 5: 集成与文档（预计1周）
- [ ] 集成到Simple Harness主项目
- [ ] API文档
- [ ] 使用示例
- [ ] 性能测试

**总计：6-9周（1.5-2个月）**

---

## 6. 集成回主项目

### 6.1 主项目修改

```python
# backend/main.py

from simple_harness_memory import MemoryManager
from simple_harness_memory.llm import CustomLLMClient

# 构建Memory SDK实例
memory_sdk = await MemoryManager.build(
    db_path=cfg.memory.db_path,
    embedder_type="bge-m3",
    llm_client=CustomLLMClient(local_llm),  # 复用现有LLM
    enable_facts=cfg.memory.v2.facts_extract,
    enable_enhanced_retrieval=cfg.memory.v2.enhanced_retriever,
    enable_reranker=cfg.memory.v2.rerank
)

# 替换现有的MemoryManager
app.state.memory = memory_sdk
```

### 6.2 渐进式迁移

**Step 1:** SDK与现有系统并行运行，双写验证
**Step 2:** 只读流量切到SDK
**Step 3:** 写流量切到SDK
**Step 4:** 移除旧代码

---

## 7. 成功标准

### 7.1 功能标准
- ✅ 所有现有记忆功能无回归
- ✅ Facts提取准确率 ≥ 现有系统
- ✅ 召回质量 hit@5 ≥ baseline
- ✅ 支持中文查询

### 7.2 性能标准
- ✅ 保存消息延迟 < 100ms（不含Facts提取）
- ✅ 搜索延迟 < 500ms（10条结果）
- ✅ 内存占用 < 500MB（含BGE-M3模型）

### 7.3 质量标准
- ✅ 单元测试覆盖率 > 80%
- ✅ 集成测试覆盖核心流程
- ✅ 文档完整（API + 使用示例）

---

## 8. 未来扩展（后续版本）

### v0.2: 云端后端
- Pinecone适配器
- Weaviate适配器
- 同步机制

### v0.3: 高级治理
- 跨key矛盾检测
- 显式遗忘（memory_forget）
- 实体索引

### v0.4: 性能优化
- sqlite-vec索引（替代brute-force）
- 批量操作优化
- 缓存层

---

## 9. 风险与缓解

### R1: 代码提取复杂度
**风险：** 现有代码耦合紧密，提取困难
**缓解：** 逐模块提取，先建Port接口，再逐步迁移实现

### R2: 依赖冲突
**风险：** SDK与主项目的依赖版本冲突
**缓解：** 使用宽松的版本约束，optional-dependencies隔离重依赖

### R3: 性能回归
**风险：** 抽象层带来性能损失
**缓解：** 性能测试门控，对比现有系统baseline

### R4: API设计不稳定
**风险：** Port接口需要频繁修改
**缓解：** Phase 1充分验证API设计，延长MVP阶段

---

## 10. 下一步行动

### 立即行动（本周）
1. [ ] 创建 `simple-harness-memory-sdk` 仓库
2. [ ] 编写详细的Port接口代码
3. [ ] 从现有代码中识别要提取的具体文件清单
4. [ ] 搭建项目骨架（pyproject.toml, 目录结构）

### 第一周目标
- [ ] Port接口定义完成
- [ ] Mock实现跑通
- [ ] 单元测试框架搭建

**准备好开始了吗？我可以帮你从创建Port接口开始！**
