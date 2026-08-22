# simple-harness-memory-sdk

当前生产架构、SQLite/召回边界与已知限制见
[`ARCHITECTURE/index.md`](ARCHITECTURE/index.md)。

认知记忆 SDK，为运行时 consumer 提供独立、product-neutral 的持久记忆系统。

当前版本：**0.4.0**（Python 3.11–3.13）。

**基于认知科学三层模型 + 数字孪生体 + 世界对象，使用 RRF 混合召回。**

架构设计详见：[docs/architecture.md](docs/architecture.md)

---

## 安装

```bash
pip install simple-harness-memory-sdk                 # 基础（仅核心）
pip install "simple-harness-memory-sdk[embeddings]"   # BGE-M3 语义嵌入 + CrossEncoder 重排
pip install "simple-harness-memory-sdk[world]"        # 联网新闻/天气 provider
pip install "simple-harness-memory-sdk[openai]"       # LLM 事实提取
pip install "simple-harness-memory-sdk[harness]"      # Simple Harness Agent Memory v1 一等集成
pip install "simple-harness-memory-sdk[all]"          # 以上全部
```

extras 与功能的对应关系（与 `pyproject.toml` 的 `[project.optional-dependencies]`
逐条一致）：

| extra        | 依赖（pyproject 声明）         | 启用能力 |
|--------------|--------------------------------|----------|
| `embeddings` | `torch`、`sentence-transformers` | BGE-M3 语义向量（`embedder="bge"`）、CrossEncoder 重排；运行时只读本地权重，不下载 |
| `world`      | `httpx`、`python-dateutil`      | 联网的新闻/天气 provider（NewsAPI / OpenWeatherMap） |
| `openai`     | `openai`                        | LLM 事实提取（需自备 OpenAI 客户端，见 `features/facts.py` 的 `LLMFactExtractor`） |
| `harness`    | `simple-harness-sdk>=0.3,<0.4` | `MemoryManager` 直接实现 Harness `AgentMemoryPort` |
| `dev`        | `pytest` 等                     | 开发 / 测试 |
| `all`        | 上述四个运行时 extra            | 完整功能 |

## 快速上手

以下示例仅依赖**基础安装**（`pip install simple-harness-memory-sdk`），逐字运行即可：

```python
import asyncio

from simple_harness_memory import MemoryManager


async def main():
    # SQLite fresh schema v4；默认 HashEmbedder 仅需基础安装。
    memory = await MemoryManager.build("memory.db", enable_facts=True)

    # user_id 是稳定产品主体；source_event_id 是 consumer 生成的确定性幂等键。
    applied = await memory.append_message(
        session_id="chat-001",
        role="user",
        content="我养了一只叫Max的狗，很喜欢吃披萨",
        user_id="user-001",
        source_event_id="product-memory/v1/message/123",
    )
    assert applied.status.value == "applied"

    # 所有读写与维护入口都显式绑定 user_id。
    hits = await memory.recall(
        query="Max", session_id="chat-001", user_id="user-001"
    )
    assert hits, "recall 应返回命中结果"

    facts = await memory.get_facts(user_id="user-001")
    assert facts, "应提取到 facts"

    print(f"OK: 召回 {len(hits)} 条，提取 {len(facts)} 条事实")

    await memory.close()


asyncio.run(main())
```

同一个 `source_event_id` 与相同 canonical payload 重放返回
`already_applied`；同 ID 不同 payload 稳定拒绝。standalone user 作为 deployment 边界，同名
`session_id` 可在不同 user/deployment 共存，但同一 deployment 内首次绑定后不可改绑。
Harness 消费者不再创建 Memory Adapter，也不手动 recall/append。安装 `[harness]` 后，直接把
`MemoryManager` 传给 Harness production ports；Harness canonical DTO 仅在 integration 方法调用时
lazy import，基础安装仍可独立导入：

```python fragment
memory = await MemoryManager.build("memory.db", enable_facts=True)
ports = ConsumerRuntimePorts(memory=memory)  # direct AgentMemoryPort
```

官方路径以 committed user→assistant Turn 为写入单位：receipt、两条消息和 durable fact job 在同一
SQLite 事务创建；事实提取在事务外执行，结果与 job ack 再原子提交。

完整的 identity/scope ownership、稳定失败码和生命周期边界见
[`docs/agent-memory-v1.md`](docs/agent-memory-v1.md)。当前消费者验证状态见
[`docs/integration-status.md`](docs/integration-status.md)。

未来消费者可在不安装 Harness 的基础 wheel 中显式分享一条已授权的 personal fact：

```python fragment
from simple_harness_memory import MemoryOwnershipConflict, MemoryPrincipal

principal = MemoryPrincipal(deployment_id, household_id, actor_id, session_id)
projection_id = await memory.share_fact(principal, fact_id)
```

`share_fact()` 只接受属于该 trusted principal 的 personal source fact；跨 actor/household 稳定抛
`MemoryOwnershipConflict`。同一 source/household 重放返回相同 projection ID 且只保留一行，family row
通过 `projection_of` 保留来源；`forget_fact(..., principal=principal)` 会级联删除 source 与 projection，
并留下 tombstone 阻止 late fact job 重建。该 SDK-only API 不属于 Harness `AgentMemoryPort`，也不接受模型
选择 scope。

### 持久化边界

- SQLite 只接受 fresh schema v4；旧 schema/version/checksum 一律 fail-fast，不做隐式迁移。
- v4 全链路保存 deployment/household/actor/session 与 personal/family scope；session 和 turn receipt
  都以 deployment 为持久化命名空间，同一 deployment 内首次绑定后不可换 household/actor。
- `export_principal`、`delete_scope`、`forget_fact` 和 `share_fact` 共用同一 scope predicate；删除先推进
  erasure epoch，再级联 content/vector/stage/job，并保留 hash-only tombstone，旧 outbox/job 不会复活内容。
- v3→v4 只通过显式、closed-runtime、backup-first migrator执行，runtime仍不会隐式升级。迁移接收 Harness
  四类 execution manifest、可信 identity map和独立 non-Harness provenance manifest；全 source-event 唯一
  覆盖、hash、pair、FK或identity任一不一致都不会发布临时库。操作说明见
  [`docs/migration-v4.md`](docs/migration-v4.md)。
- 数据库必须是当前用户拥有的 regular file，拒绝 symlink，并以 `0600` 创建和回读校验。
- 同一数据库只允许一个 live `MemoryManager` 持有 writer lease；第二个 writer 稳定报
  `memory_second_writer_rejected`。writer、checkpoint 与 online backup 共用同一串行边界。
- 召回使用 external-content FTS5，先做 deployment/household/scope 过滤，再执行 MATCH/ORDER/LIMIT；
  vector 只 decode 当前 active generation 的有界 lexical/recent candidates。lineage 漂移或 embedding
  暂不可用时明确降级为 lexical-only，不混用不同模型向量。
- Agent recall 在任何 embedding/ranking 前持久读取 erasure fence；embedding 超时或损坏的降级错误仍
  携带该 fence，因此并发删除后的旧 turn 会稳定返回 `rejected_erased`。
- `reindex_generation()` 分页建立 building generation，校验 count/dimension/hash/sample 后原子切换；失败
  保留旧 active generation。`backup()` 生成带 schema/lineage/SHA-256 的 manifest，`restore_backup()`
  仅允许 manager 关闭后执行，并在替换原库前完成独立完整性校验。
- `recall_bounded()` 对确定性 `context_query_id` 保存 canonical 结果；commit 后重试不重新计算。
- `delete_all()` 仅保留为 deprecated compatibility symbol，调用稳定抛出
  `runtime_delete_disabled`，不会执行全库 mutation。开发 reset 应在 consumer 停服后删除其精确配置的
  SQLite storage set（主文件及 sidecars），再创建 fresh v4 数据库。

> **默认 HashEmbedder 前提说明**：未安装 `[embeddings]` extra 时，development builder 默认使用
> `HashEmbedder`——一种确定性的哈希伪向量（字符 n-gram 哈希 + 符号累加，非语义
> 嵌入）。它的语义召回质量有限（关键词/文本子串命中可靠，近义语义召回不可靠），
> 仅用于跑通 API 与开发期占位。生产代码必须显式提供 production embedder 和已解析资源路径；
> `build_production()` 会拒绝 hash/mock 与缺失资源。

## 可选能力

### BGE-M3 语义嵌入

需要 `[embeddings]` extra（`torch` + `sentence-transformers`）。模型权重必须在部署阶段准备好；
SDK 始终以 `local_files_only=True` 加载，运行时不会下载：

```bash
pip install -e ".[embeddings]"
```

```python fragment
from simple_harness_memory.embedders import get_production_embedder

embedder = get_production_embedder(
    "bge",
    resource_path="/opt/models/bge-m3",
    model="BAAI/bge-m3",
    revision="pinned-model-revision",
)
memory = await MemoryManager.build_production(
    "memory.db",
    embedder=embedder,
    resource_path="/opt/models/bge-m3",
    enable_facts=True,
)
```

运维操作同样由 manager 承担：

```python fragment
await memory.reindex_generation(embedder, page_size=256)
await memory.checkpoint(deadline_seconds=5.0)
manifest = await memory.backup("memory.backup.db")
await memory.close()
await memory.restore_backup("memory.backup.db")
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
