# simple-harness-memory-sdk

认知记忆 SDK，为 Simple Harness 提供独立的记忆系统。

**基于认知科学三层模型 + 数字孪生体 + 世界对象，使用 RRF 混合召回。**

架构设计详见：[docs/architecture.md](docs/architecture.md)

---

## 安装

```bash
pip install -e .                          # 基础（仅核心）
pip install -e ".[embeddings]"            # 含 BGE-M3
pip install -e ".[all]"                   # 完整功能
pip install -e ".[dev]"                   # 开发依赖
```

## 快速上手

```python
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
    content="我养了一只叫Max的狗，很喜欢吃披萨",
)

# 混合召回（RRF 六路融合）
hits = await memory.recall(query="用户养了什么宠物？")

# 查询数字孪生体
twin = await memory.get_digital_twin()
print(twin.relationships.entities["Max"])

# 获取世界上下文
ctx = await memory.world.get_temporal_context()
print(f"今天是 {ctx.date_str}，{ctx.weekday}")
```

## 架构概览

```
L1: 工作记忆 (Working Memory)  — 当前会话上下文
L2: 情景记忆 (Episodic Memory) — Messages 表 + 遗忘曲线
L3: 语义记忆 (Semantic Memory) — Facts 表 + 实体关系

数字孪生体 (Digital Twin)      — 用户完整认知模型
世界对象   (World Model)       — 时间/事件/地理/知识边界

召回引擎   (RRF Retriever)     — 六路信号融合
```

## 开发路线图

- **Phase 1 (MVP)**: 核心接口 + Mock/SQLite 后端
- **Phase 2**: Facts 提取 + BGE-M3 + RRF 六路召回
- **Phase 3**: 遗忘曲线 + 显著性 + 数字孪生体
- **Phase 4**: 世界对象（时间/事件/天气/知识边界）
- **Phase 5**: 集成到 Simple Harness 主应用
- **Phase 6**: 云端后端（Pinecone）

## 许可证

BUSL-1.1，2030-05-27 自动转换为 Apache-2.0。
