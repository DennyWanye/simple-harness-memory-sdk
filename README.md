# simple-harness-memory-sdk

认知记忆 SDK，为 Simple Harness 提供独立的记忆系统。

**基于认知科学三层模型 + 数字孪生体 + 世界对象，使用 RRF 混合召回。**

架构设计详见：[docs/architecture.md](docs/architecture.md)

---

## 安装

```bash
pip install -e .                 # 基础（仅核心）
pip install -e ".[embeddings]"   # BGE-M3 语义嵌入 + CrossEncoder 重排
pip install -e ".[world]"        # 联网新闻/天气 provider
pip install -e ".[openai]"       # LLM 事实提取
pip install -e ".[dev]"          # 开发依赖
pip install -e ".[all]"          # 以上全部
```

extras 与功能的对应关系（与 `pyproject.toml` 的 `[project.optional-dependencies]`
逐条一致）：

| extra        | 依赖（pyproject 声明）         | 启用能力 |
|--------------|--------------------------------|----------|
| `embeddings` | `torch`、`sentence-transformers` | BGE-M3 语义向量（`embedder="bge"`）、CrossEncoder 重排；首次使用需联网下载权重 |
| `world`      | `httpx`、`python-dateutil`      | 联网的新闻/天气 provider（NewsAPI / OpenWeatherMap） |
| `openai`     | `openai`                        | LLM 事实提取（需自备 OpenAI 客户端，见 `features/facts.py` 的 `LLMFactExtractor`） |
| `dev`        | `pytest` 等                     | 开发 / 测试 |
| `all`        | 上述三者之和                    | 完整功能 |

## 快速上手

以下示例仅依赖**基础安装**（`pip install -e .`），逐字运行即可：

```python
import asyncio

from simple_harness_memory import MemoryManager


async def main():
    # 默认使用 HashEmbedder（确定性哈希伪向量），仅需基础安装
    memory = await MemoryManager.build(enable_facts=True)

    # 1. 追加消息（enable_facts=True 时自动提取 facts）
    await memory.append_message(
        session_id="chat-001",
        role="user",
        content="我养了一只叫Max的狗，很喜欢吃披萨",
    )

    # 2. 召回（关键词命中；语义召回见下方"可选能力"）
    hits = await memory.recall(query="Max")
    assert hits, "recall 应返回命中结果"

    # 3. 查询自动提取的 facts
    facts = await memory.get_facts()
    assert facts, "应提取到 facts"

    print(f"OK: 召回 {len(hits)} 条，提取 {len(facts)} 条事实")

    await memory.close()


asyncio.run(main())
```

> **默认 HashEmbedder 前提说明**：未安装 `[embeddings]` extra 时，SDK 默认使用
> `HashEmbedder`——一种确定性的哈希伪向量（字符 n-gram 哈希 + 符号累加，非语义
> 嵌入）。它的语义召回质量有限（关键词/文本子串命中可靠，近义语义召回不可靠），
> 仅用于跑通 API 与开发期占位。**生产环境建议安装 `[embeddings]` extra 启用
> BGE-M3 语义嵌入。**

## 可选能力

### BGE-M3 语义嵌入

需要 `[embeddings]` extra（`torch` + `sentence-transformers`），首次使用会联网
下载 `BAAI/bge-m3` 权重：

```bash
pip install -e ".[embeddings]"
```

```python fragment
memory = await MemoryManager.build(
    enable_facts=True,
    embedder="bge",   # 显式 BGE-M3；"auto" 会在缺依赖时回退 HashEmbedder
)
```

### 世界对象（World Model）

`enable_world_model=True` 开启世界对象。基础时间上下文（temporal）由标准库实现、
无需额外依赖；联网的新闻/天气 provider（NewsAPI / OpenWeatherMap）需要 `[world]`
extra（提供 `httpx`）：

```bash
pip install -e ".[world]"
```

```python fragment
memory = await MemoryManager.build(
    enable_facts=True,
    enable_world_model=True,
)

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
