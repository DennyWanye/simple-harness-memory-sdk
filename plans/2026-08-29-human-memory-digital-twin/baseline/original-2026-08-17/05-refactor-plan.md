# Memory SDK 从0重构 - 完整实施计划

**创建日期**: 2026-08-17  
**目标**: 从现有simple_harness app中完全移除记忆系统，从0开始基于认知架构重建

---

## 📊 现状分析

### **现有系统规模：**
- **代码文件**: 35个Python文件（`backend/deskpet/memory/`）
- **代码行数**: 17,579行
- **依赖引用**: 411处（其他模块调用记忆系统）
- **测试文件**: 需要检查`backend/tests/`中的相关测试

### **为什么要从0开始？**

| 现有问题 | 重构目标 |
|---|---|
| ❌ 扁平的Facts设计 | ✅ 层次化的数字孪生体 |
| ❌ 没有世界对象 | ✅ 内部记忆+外部感知 |
| ❌ 紧耦合到主应用 | ✅ 独立的SDK包 |
| ❌ 17K行单体代码 | ✅ 模块化、可测试 |
| ❌ 只有本地SQLite | ✅ 可插拔后端（本地/云端） |

---

## 🎯 重构策略：Strangler Fig模式

**不直接删除旧代码！** 使用"绞杀者模式"渐进式替换：

```
Phase 1: 新SDK与旧系统并存（双写）
Phase 2: 读流量切到新SDK
Phase 3: 写流量切到新SDK  
Phase 4: 移除旧代码
```

---

## 📅 分阶段实施计划

### **Phase 0: 准备工作（1-2天）**

#### **0.1 创建独立SDK仓库**

```bash
# 创建新目录
mkdir -p simple-harness-memory-sdk
cd simple-harness-memory-sdk

# 初始化git
git init
git remote add origin <your-repo-url>

# 创建项目结构
mkdir -p src/simple_harness_memory/{core,backends,features,embedders,cognitive,world}
mkdir -p tests docs examples
```

#### **0.2 项目骨架**

```
simple-harness-memory-sdk/
├── pyproject.toml
├── README.md
├── LICENSE
├── docs/
│   ├── architecture.md
│   ├── api-reference.md
│   └── migration-guide.md
├── src/
│   └── simple_harness_memory/
│       ├── __init__.py
│       ├── core/              # 核心抽象
│       │   ├── port.py        # MemoryBackend接口
│       │   ├── models.py      # Message/Fact/Hit数据类
│       │   └── twin.py        # 数字孪生体
│       ├── backends/          # 存储后端
│       │   ├── sqlite.py
│       │   └── mock.py
│       ├── features/          # 功能模块
│       │   ├── facts.py       # Facts提取
│       │   ├── retriever.py   # RRF混合召回
│       │   └── reranker.py
│       ├── embedders/         # 向量化
│       │   ├── bge.py
│       │   └── mock.py
│       ├── cognitive/         # 认知特性
│       │   ├── decay.py       # 遗忘曲线
│       │   └── salience.py    # 显著性
│       └── world/             # 世界对象
│           ├── temporal.py    # 时间感知
│           ├── events.py      # 事件感知
│           └── geography.py   # 地理感知
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
└── examples/
    └── quickstart.py
```

#### **0.3 依赖管理**

```toml
# pyproject.toml
[project]
name = "simple-harness-memory-sdk"
version = "0.1.0"
description = "Cognitive memory system SDK with digital twin and world model"
requires-python = ">=3.11"
dependencies = [
    "aiosqlite>=0.19.0",
    "pydantic>=2.0.0",
    "numpy>=1.24.0",
]

[project.optional-dependencies]
embeddings = [
    "torch>=2.0.0",
    "sentence-transformers>=2.0.0",
]
world = [
    "httpx>=0.24.0",        # HTTP客户端
    "python-dateutil>=2.8.0",
]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "ruff>=0.0.290",
]
all = [
    "simple-harness-memory-sdk[embeddings,world]",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

### **Phase 1: 核心接口定义（3-5天）**

#### **1.1 定义Port接口**

创建 `src/simple_harness_memory/core/port.py`：

```python
from abc import ABC, abstractmethod
from typing import Optional, List
from .models import Message, Fact, Hit, DigitalTwin, SearchResult
from .twin import DigitalTwin

class MemoryBackend(ABC):
    """记忆系统抽象接口"""
    
    # ========== L2: 情景记忆 ==========
    @abstractmethod
    async def append_message(
        self, 
        session_id: str, 
        role: str, 
        content: str
    ) -> int:
        """保存消息到情景记忆"""
        pass
    
    @abstractmethod
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Message]:
        """获取最近的消息"""
        pass
    
    # ========== L3: 语义记忆 ==========
    @abstractmethod
    async def extract_facts(
        self, 
        message_id: int, 
        content: str, 
        role: str
    ) -> List[Fact]:
        """从消息中自动提取事实"""
        pass
    
    @abstractmethod
    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True
    ) -> List[Fact]:
        """查询语义记忆"""
        pass
    
    # ========== 数字孪生体 ==========
    @abstractmethod
    async def get_digital_twin(
        self, 
        subject: str = "user"
    ) -> DigitalTwin:
        """获取数字孪生体"""
        pass
    
    @abstractmethod
    async def update_digital_twin(
        self, 
        twin: DigitalTwin
    ) -> None:
        """更新数字孪生体"""
        pass
    
    # ========== 混合召回 ==========
    @abstractmethod
    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Hit]:
        """
        RRF混合召回
        
        执行：vec + fts + recency + salience + facts + entity
        → RRF融合 → Rerank → 更新salience
        """
        pass
    
    # ========== 认知维护 ==========
    @abstractmethod
    async def daily_decay(self) -> dict:
        """每日遗忘衰减"""
        pass
```

#### **1.2 定义数据模型**

创建 `src/simple_harness_memory/core/models.py`：

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

@dataclass
class Message:
    """对话消息（情景记忆）"""
    id: Optional[int] = None
    session_id: str
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    created_at: Optional[float] = None
    
    # 认知特性
    salience: float = 0.0
    decay_rate: float = 0.02
    last_recalled: Optional[float] = None
    
    # 向量化
    embedding: Optional[bytes] = None
    
    # 元数据
    is_summary: bool = False
    summary_of: Optional[str] = None


@dataclass
class Fact:
    """提取的事实（语义记忆）"""
    id: Optional[int] = None
    subject: str
    key: str
    value: str
    category: str
    confidence: float
    source_msg_id: int
    evidence: str
    
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    is_active: bool = True
    
    # 认知特性
    decay_rate: float = 0.02
    last_recalled: Optional[float] = None
    embedding: Optional[bytes] = None
    
    # 演化
    superseded_by: Optional[int] = None
    forgotten_at: Optional[float] = None
    
    # 作用域
    scope: str = "user"
    pinned: bool = False


@dataclass
class Hit:
    """召回结果"""
    message_id: int
    text: str
    score: float
    source: str  # "vec" | "fts" | "recency" | "salience" | "facts"
    recency: float
    salience: float
    session_affinity: float = 1.0


# 更多模型...
```

#### **1.3 定义数字孪生体**

创建 `src/simple_harness_memory/core/twin.py`：

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class DigitalTwin:
    """用户的数字孪生体"""
    subject: str = "user"
    
    profile: 'UserProfile' = field(default_factory=lambda: UserProfile())
    skills: 'SkillMap' = field(default_factory=lambda: SkillMap())
    preferences: 'PreferenceMap' = field(default_factory=lambda: PreferenceMap())
    relationships: 'RelationshipGraph' = field(default_factory=lambda: RelationshipGraph())
    goals: List['Goal'] = field(default_factory=list)
    
    created_at: Optional[float] = None
    last_updated: Optional[float] = None
    completeness: float = 0.0
    confidence: float = 0.5


@dataclass
class UserProfile:
    """用户基础身份"""
    name: Optional[str] = None
    age: Optional[int] = None
    occupation: Optional[str] = None
    location: Optional[str] = None
    
    last_updated: Optional[float] = None
    confidence: Dict[str, float] = field(default_factory=dict)


# 更多孪生体组件...
```

---

### **Phase 2: Mock实现（2-3天）**

#### **2.1 创建Mock后端**

创建 `src/simple_harness_memory/backends/mock.py`：

```python
from typing import List, Optional, Dict
from ..core.port import MemoryBackend
from ..core.models import Message, Fact, Hit
from ..core.twin import DigitalTwin

class MockMemoryBackend(MemoryBackend):
    """Mock实现（用于测试和开发）"""
    
    def __init__(self):
        self.messages: Dict[int, Message] = {}
        self.facts: Dict[int, Fact] = {}
        self.twins: Dict[str, DigitalTwin] = {}
        self._next_msg_id = 1
        self._next_fact_id = 1
    
    async def append_message(
        self, 
        session_id: str, 
        role: str, 
        content: str
    ) -> int:
        msg_id = self._next_msg_id
        self._next_msg_id += 1
        
        self.messages[msg_id] = Message(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=time.time()
        )
        
        return msg_id
    
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 10
    ) -> List[Message]:
        msgs = [
            m for m in self.messages.values()
            if m.session_id == session_id
        ]
        return sorted(msgs, key=lambda m: m.created_at, reverse=True)[:limit]
    
    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Hit]:
        # 简单的关键词匹配
        hits = []
        for msg in self.messages.values():
            if session_id and msg.session_id != session_id:
                continue
            if query.lower() in msg.content.lower():
                hits.append(Hit(
                    message_id=msg.id,
                    text=msg.content,
                    score=0.8,
                    source="mock",
                    recency=1.0,
                    salience=msg.salience
                ))
        
        return hits[:limit]
    
    async def get_digital_twin(self, subject: str = "user") -> DigitalTwin:
        if subject not in self.twins:
            self.twins[subject] = DigitalTwin(subject=subject)
        return self.twins[subject]
    
    # ... 其他方法的简单实现
```

#### **2.2 编写单元测试**

创建 `tests/unit/test_mock_backend.py`：

```python
import pytest
from simple_harness_memory.backends.mock import MockMemoryBackend

@pytest.mark.asyncio
async def test_append_and_get_messages():
    backend = MockMemoryBackend()
    
    # 保存消息
    msg_id = await backend.append_message(
        session_id="test-session",
        role="user",
        content="Hello world"
    )
    
    assert msg_id == 1
    
    # 获取消息
    messages = await backend.get_recent_messages("test-session")
    assert len(messages) == 1
    assert messages[0].content == "Hello world"


@pytest.mark.asyncio
async def test_recall():
    backend = MockMemoryBackend()
    
    await backend.append_message("test", "user", "我喜欢披萨")
    await backend.append_message("test", "assistant", "好的，记住了")
    
    hits = await backend.recall("披萨", session_id="test")
    assert len(hits) == 1
    assert "披萨" in hits[0].text
```

---

### **Phase 3: SQLite后端实现（1-2周）**

#### **3.1 数据库Schema设计**

创建 `src/simple_harness_memory/backends/schema.sql`：

```sql
-- L2: 情景记忆
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    salience REAL DEFAULT 0.0,
    decay_rate REAL DEFAULT 0.02,
    last_recalled REAL,
    embedding BLOB,
    is_summary INTEGER DEFAULT 0,
    summary_of TEXT
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);
CREATE INDEX idx_messages_created ON messages(created_at);

-- L3: 语义记忆（Facts）
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_msg_id INTEGER,
    evidence TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    is_active INTEGER DEFAULT 1,
    decay_rate REAL DEFAULT 0.02,
    last_recalled REAL,
    embedding BLOB,
    superseded_by INTEGER REFERENCES facts(id),
    forgotten_at REAL,
    scope TEXT DEFAULT 'user',
    pinned INTEGER DEFAULT 0
);
CREATE INDEX idx_facts_subject_key ON facts(subject, key, is_active);
CREATE INDEX idx_facts_category ON facts(category, is_active);

-- 数字孪生体 - Profile
CREATE TABLE IF NOT EXISTS twin_profiles (
    subject TEXT PRIMARY KEY,
    name TEXT,
    age INTEGER,
    occupation TEXT,
    location TEXT,
    last_updated REAL,
    confidence_json TEXT  -- JSON: {"name": 0.9, "age": 0.8, ...}
);

-- 数字孪生体 - Skills
CREATE TABLE IF NOT EXISTS twin_skills (
    subject TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    level REAL NOT NULL,
    confidence REAL NOT NULL,
    last_used TEXT,
    evidence_json TEXT,  -- JSON: [msg_id1, msg_id2, ...]
    PRIMARY KEY (subject, skill_name)
);

-- 数字孪生体 - Preferences
CREATE TABLE IF NOT EXISTS twin_preferences (
    subject TEXT NOT NULL,
    pref_key TEXT NOT NULL,
    pref_value TEXT NOT NULL,
    strength REAL NOT NULL,
    last_observed TEXT,
    frequency INTEGER DEFAULT 1,
    PRIMARY KEY (subject, pref_key)
);

-- 数字孪生体 - Entities & Relationships
CREATE TABLE IF NOT EXISTS twin_entities (
    entity_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- "person" | "pet" | "place" | "organization"
    attributes_json TEXT,
    created_at REAL NOT NULL,
    last_mentioned REAL
);

CREATE TABLE IF NOT EXISTS twin_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity TEXT NOT NULL,
    to_entity TEXT NOT NULL,
    rel_type TEXT NOT NULL,  -- "owns" | "works_with" | "family"
    strength REAL NOT NULL,
    evidence_json TEXT,
    UNIQUE(from_entity, to_entity, rel_type)
);

-- 世界对象 - 个人事件
CREATE TABLE IF NOT EXISTS world_personal_events (
    event_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    timestamp REAL NOT NULL,
    category TEXT NOT NULL,
    importance REAL NOT NULL,
    source_msg_id INTEGER
);

-- 世界对象 - 世界事件（新闻）
CREATE TABLE IF NOT EXISTS world_events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    timestamp REAL NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    relevance REAL DEFAULT 0.5
);
```

#### **3.2 实现SQLite后端**

创建 `src/simple_harness_memory/backends/sqlite.py`：

```python
import aiosqlite
from pathlib import Path
from typing import List, Optional
from ..core.port import MemoryBackend
from ..core.models import Message, Fact, Hit
from ..core.twin import DigitalTwin

class SQLiteMemoryBackend(MemoryBackend):
    """SQLite本地存储后端"""
    
    def __init__(
        self,
        db_path: str | Path,
        embedder: Optional['Embedder'] = None,
        facts_extractor: Optional['FactExtractor'] = None
    ):
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.facts_extractor = facts_extractor
        self._initialized = False
    
    async def initialize(self):
        """初始化数据库schema"""
        if self._initialized:
            return
        
        # 创建表
        schema_file = Path(__file__).parent / "schema.sql"
        schema = schema_file.read_text()
        
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.executescript(schema)
            await conn.commit()
        
        self._initialized = True
    
    async def append_message(
        self, 
        session_id: str, 
        role: str, 
        content: str
    ) -> int:
        """保存消息"""
        await self.initialize()
        
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO messages (session_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, time.time())
            )
            msg_id = cursor.lastrowid
            await conn.commit()
        
        # 异步触发Facts提取
        if self.facts_extractor and role in ("user", "assistant"):
            asyncio.create_task(
                self.facts_extractor.process_message(msg_id, content, role)
            )
        
        return msg_id
    
    # ... 其他方法实现
```

---

### **Phase 4: 在主应用中集成新SDK（双写模式，1周）**

#### **4.1 安装SDK到主应用**

```bash
cd /Users/denny/projects/simple_harness

# 本地开发模式安装
pip install -e ../simple-harness-memory-sdk

# 或添加到requirements.txt
echo "simple-harness-memory-sdk @ file://$(realpath ../simple-harness-memory-sdk)" >> backend/requirements.txt
```

#### **4.2 创建适配层**

创建 `backend/deskpet/memory_adapter.py`：

```python
"""
记忆系统适配层 - 新旧系统并存的桥接
"""
from simple_harness_memory import MemoryBackend, MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend

class MemoryAdapter:
    """新旧记忆系统的适配器"""
    
    def __init__(self, use_new_sdk: bool = False):
        self.use_new = use_new_sdk
        
        if use_new:
            # 新SDK
            self.new_backend = SQLiteMemoryBackend(db_path="./data/memory_v2.db")
        else:
            self.new_backend = None
        
        # 旧系统（保持兼容）
        from deskpet.memory.manager import MemoryManager
        self.old_manager = MemoryManager()
    
    async def append_message(self, session_id: str, role: str, content: str) -> int:
        """双写：同时写入新旧系统"""
        
        # 写入旧系统
        msg_id_old = await self.old_manager.append_message(session_id, role, content)
        
        # 写入新系统
        if self.use_new and self.new_backend:
            msg_id_new = await self.new_backend.append_message(session_id, role, content)
            print(f"[MemoryAdapter] 双写: 旧ID={msg_id_old}, 新ID={msg_id_new}")
        
        return msg_id_old  # 先返回旧ID保持兼容
    
    async def recall(self, query: str, **kwargs):
        """召回：优先用新系统，失败降级到旧系统"""
        
        if self.use_new and self.new_backend:
            try:
                results = await self.new_backend.recall(query, **kwargs)
                print(f"[MemoryAdapter] 使用新SDK召回: {len(results)}条")
                return results
            except Exception as e:
                print(f"[MemoryAdapter] 新SDK失败，降级到旧系统: {e}")
        
        # 降级到旧系统
        return await self.old_manager.recall(query, **kwargs)
```

#### **4.3 配置开关**

修改 `backend/config.toml`：

```toml
[memory]
# 新SDK开关（默认false，渐进式启用）
use_new_sdk = false
dual_write = true  # 双写模式（验证阶段）

[memory.new_sdk]
db_path = "./data/memory_v2.db"
enable_facts = true
enable_world_model = false  # 先不启用
```

#### **4.4 主应用集成**

修改 `backend/main.py`：

```python
from deskpet.memory_adapter import MemoryAdapter

# 启动时
app.state.memory = MemoryAdapter(use_new_sdk=cfg.memory.use_new_sdk)

# 使用
@app.post("/chat")
async def chat(request: ChatRequest):
    # 保存消息
    msg_id = await app.state.memory.append_message(
        session_id=request.session_id,
        role="user",
        content=request.message
    )
    
    # 召回
    hits = await app.state.memory.recall(
        query=request.message,
        session_id=request.session_id
    )
    
    # ... LLM处理
```

---

### **Phase 5: 验证与对比（1周）**

#### **5.1 创建验证脚本**

创建 `scripts/validate_new_sdk.py`：

```python
"""
验证新SDK与旧系统的一致性
"""
import asyncio
from deskpet.memory_adapter import MemoryAdapter

async def test_consistency():
    """测试新旧系统的一致性"""
    
    adapter = MemoryAdapter(use_new_sdk=True)
    
    # 写入测试数据
    test_messages = [
        ("user", "我喜欢披萨"),
        ("assistant", "好的，记住了"),
        ("user", "我养了一只叫Max的狗"),
    ]
    
    for role, content in test_messages:
        await adapter.append_message("test-session", role, content)
    
    # 召回测试
    hits_old = await adapter.old_manager.recall("披萨")
    hits_new = await adapter.new_backend.recall("披萨")
    
    print(f"旧系统召回: {len(hits_old)}条")
    print(f"新系统召回: {len(hits_new)}条")
    
    # 对比结果
    if len(hits_old) == len(hits_new):
        print("✅ 召回数量一致")
    else:
        print("❌ 召回数量不一致")

if __name__ == "__main__":
    asyncio.run(test_consistency())
```

---

### **Phase 6: 移除旧代码（1-2天）**

#### **6.1 确认切换完成**

```bash
# 1. 确认所有测试通过
pytest backend/tests/

# 2. 确认新SDK在生产运行稳定（至少1周）
# 3. 确认所有依赖已切换到新SDK
grep -r "from deskpet.memory import" backend/ | wc -l
# 应该为0
```

#### **6.2 删除旧代码**

```bash
# 备份旧代码（以防万一）
git checkout -b backup-old-memory
git add backend/deskpet/memory/
git commit -m "backup: old memory system before removal"
git push origin backup-old-memory

# 回到主分支删除
git checkout main
rm -rf backend/deskpet/memory/

# 删除相关测试
rm -rf backend/tests/test_memory*.py

# 提交
git add .
git commit -m "refactor: remove old memory system, fully migrated to new SDK"
```

---

## 📊 时间线总结

| Phase | 任务 | 预计时间 | 依赖 |
|---|---|---|---|
| 0 | 准备工作（仓库/骨架） | 1-2天 | - |
| 1 | 核心接口定义 | 3-5天 | Phase 0 |
| 2 | Mock实现+测试 | 2-3天 | Phase 1 |
| 3 | SQLite后端 | 1-2周 | Phase 2 |
| 4 | 主应用集成（双写） | 1周 | Phase 3 |
| 5 | 验证与对比 | 1周 | Phase 4 |
| 6 | 移除旧代码 | 1-2天 | Phase 5 |
| **总计** | **4-6周** | |

---

## ⚠️ 风险与缓解

### **风险1：数据迁移丢失**
**缓解：** 双写模式验证，旧数据保留备份

### **风险2：性能回归**
**缓解：** 性能测试对比，RRF召回benchmark

### **风险3：功能遗漏**
**缓解：** 完整的功能对比checklist，逐项验证

### **风险4：团队其他成员的代码冲突**
**缓解：** 适配层保持向后兼容，渐进式切换

---

## ✅ 验收标准

### **Phase 1-3完成标准：**
- [ ] Port接口定义完整
- [ ] Mock实现通过所有单元测试
- [ ] SQLite后端实现所有核心功能
- [ ] 测试覆盖率 > 80%

### **Phase 4-5完成标准：**
- [ ] 双写模式稳定运行
- [ ] 新旧系统召回结果一致性 > 95%
- [ ] 新SDK性能不低于旧系统

### **Phase 6完成标准：**
- [ ] 旧代码完全移除
- [ ] 所有依赖切换到新SDK
- [ ] 生产环境稳定运行1周+

---

## 🚀 立即行动

**现在我可以帮你：**

1. **创建SDK仓库骨架** - 生成所有目录和文件
2. **编写核心Port接口** - 完整的抽象定义
3. **实现Mock后端** - 用于快速验证
4. **制定详细的迁移checklist** - 逐项追踪进度

**你想从哪里开始？**

A. 创建SDK仓库骨架  
B. 先编写核心接口代码  
C. 先做一个最小Demo验证可行性  
D. 其他想法？

告诉我你的选择，我们立即开始！🎉
