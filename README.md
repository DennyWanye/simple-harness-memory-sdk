# simple-harness-memory-sdk

当前生产架构、SQLite/召回边界与已知限制见
[`ARCHITECTURE/index.md`](ARCHITECTURE/index.md)。
本地构建、冻结校验、GitHub 分发与 AIPhone 交接的操作手册见
[`docs/build-and-release.md`](docs/build-and-release.md)。

认知记忆 SDK，为运行时 consumer 提供独立、product-neutral 的持久记忆系统。

当前 source candidate：**0.6.0**（Python 3.11–3.13；尚未发布；已发布 fallback 为 0.5.1）。

**原始证据 + 五类长期记忆系统 + 跨系统过程 + 认知投影；工作记忆由 Host Context 承担。**

架构设计详见：[docs/architecture.md](docs/architecture.md)

---

## 安装

```bash
pip install simple-harness-memory-sdk                 # 基础（仅核心）
pip install "simple-harness-memory-sdk[embeddings]"   # BGE-M3 语义嵌入 + CrossEncoder 重排
pip install "simple-harness-memory-sdk[world]"        # 联网新闻/天气 provider
pip install "simple-harness-memory-sdk[harness]"      # Simple Harness Agent Memory v1 一等集成
pip install "simple-harness-memory-sdk[all]"          # 以上全部
```

extras 与功能的对应关系（与 `pyproject.toml` 的 `[project.optional-dependencies]`
逐条一致）：

| extra        | 依赖（pyproject 声明）         | 启用能力 |
|--------------|--------------------------------|----------|
| `embeddings` | `torch`、`sentence-transformers` | BGE-M3 语义向量（`embedder="bge"`）、CrossEncoder 重排；运行时只读本地权重，不下载 |
| `world`      | `httpx`、`python-dateutil`      | 联网的新闻/天气 provider（NewsAPI / OpenWeatherMap） |
| `harness`    | `simple-harness-sdk>=0.7,<0.8` | Harness 主模型提交严格结构化 analysis；Memory 验证、审计并应用 |
| `dev`        | `pytest` 等                     | 开发 / 测试 |
| `all`        | 上述三个运行时 extra            | 完整功能 |

## 快速上手

以下示例仅依赖**基础安装**（`pip install simple-harness-memory-sdk`），逐字运行即可：

```python
import asyncio

from simple_harness_memory import MemoryManager


async def main():
    # SQLite fresh schema v4；默认 HashEmbedder 仅需基础安装。
    memory = await MemoryManager.build("memory.db")

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

    print(f"OK: 召回 {len(hits)} 条")

    await memory.close()


asyncio.run(main())
```

### Human Memory v6 public facade

Fresh Human Memory databases use the explicit `build_human_memory_v6` entry point. It returns the
same public `MemoryManager` facade used for evidence admission, conversation registration, strict
mutation/recall, display-only twin graph, suppression and audit reads; consumers do not import the
SQLite implementation or access its connection.

```python fragment
from simple_harness_memory import MemoryPrincipal, build_human_memory_v6

principal = MemoryPrincipal(deployment_id, household_id, actor_id, session_id)
memory = await build_human_memory_v6(
    "human-memory-v6.db",
    evidence_authority=evidence_authority,
    conversation_evidence_authority=conversation_authority,
    classification_policy=classification_policy,
    memory_action_authority=memory_action_authority,
    audit_access_authority=audit_access_authority,
)
metrics = await memory.get_audit_aggregate_metrics(principal=principal)
```

Ordinary trace supports turn, invocation, decision, evidence and final memory ID selectors. Memory
trace includes hash-only proposal/accepted-plan/mutation/classification/revision/evidence lineage.
Sealed trace and canonical state manifests require an `AuditAccessAuthorityRefV1` resolved by an
injected authority; caller-constructed `SealedAuditAccessDecision` values are rejected. Every grant
and denial is append-only and hash-only. Ordinary trace requires the target `MemoryPrincipal`;
sealed trace and `export_sealed_evidence` require the authenticated requester principal and re-check
the durable ref's requester, target and scope binding. Aggregate metrics use a fixed schema over ordinary-visible
rows only: suppressed rows, content, provider/model identity, source refs and caller-defined grouping
never enter the result. An authenticated subject can observe changes in their own visible aggregates;
that first-party observation is within the API threat boundary and is not presented as differential privacy.

The sealed canonical manifest is a read-only snapshot of allowlisted v6 business tables. It exposes
only category/table roots, counts, first/last leaf canaries and a payload hash. The coverage registry
accounts for every required v6 table as a principal-scoped root or an explicitly derived/global exclusion.
Prior audit-read events are included; the access event for the current snapshot is appended afterward,
bound to the manifest hash, and therefore appears only in a later snapshot. The
hash detects changes only when compared with an independently retained earlier manifest; a database
owner able to rewrite all rows and hashes is outside the local self-authentication boundary.

同一个 `source_event_id` 与相同 canonical payload 重放返回
`already_applied`；同 ID 不同 payload 稳定拒绝。standalone user 作为 deployment 边界，同名
`session_id` 可在不同 user/deployment 共存，但同一 deployment 内首次绑定后不可改绑。
Harness 消费者不再创建 Memory Adapter，也不手动 recall/append。安装 `[harness]` 后，直接把
`MemoryManager` 传给 Harness production ports；Harness canonical DTO 仅在 integration 方法调用时
lazy import。Harness 0.7 是精确的基础依赖范围，用于共享 typed analysis 与 observability contract；
Memory 不复制事件 schema，也不导入 Harness runtime/provider/tool 实现：

```python fragment
memory = await MemoryManager.build("memory.db")
ports = ConsumerRuntimePorts(memory=memory)  # direct AgentMemoryPort
```

### 安全 observability

`MemoryManager` 的直接构造、`build()`、`build_development()`、`build_production()`，以及
`MockMemoryBackend` / `SQLiteMemoryBackend` 直接构造均接受可选 `observability_sink=` 与
`correlation=`。未注入 sink 时使用共享 Noop 路径；sink 失败只进入有界丢弃/错误计数，不改变召回、
提交或恢复结果。

`await memory.diagnostics_snapshot()` 返回稳定、有界的聚合状态，包括 recall stage、turn receipt 与
sink counters。SQLite 查询只读取状态、时间和稳定错误码列，
不会选择 query/content/response/fact/payload/embedding/path 或异常文本。

官方路径以 committed user→assistant Turn 为写入单位：receipt 与两条消息在同一 SQLite 事务创建。
0.6 production package 不包含 legacy fact worker，Mock/SQLite 也不暴露 recover/claim/apply/fail
mutation seam；LLM 结构化分析只通过 Harness 0.7 的可审计 analysis contract 进入新 repository。

完整的 identity/scope ownership、稳定失败码和生命周期边界见
[`docs/agent-memory-v1.md`](docs/agent-memory-v1.md)。当前消费者验证状态见
[`docs/integration-status.md`](docs/integration-status.md)。

### 历史发布记录（不代表 0.6 current contract）

截至 2026-08-23，`simple_harness` 曾换入 Harness 0.4.0 / Memory 0.5.0 exact-wheel 版本对；
AIPhone、K6/AgentOS、NovelTagSystem 仍未修改或测试，仅保留 SDK 接口就绪状态。
tag `v0.5.0` 指向验证过的 `9c92ede` candidate，wheel SHA 为 `c274fa6b…`；
source、`main` 与 tag 已推送，冻结 wheel/sdist 已正式发布到
[`v0.5.0` GitHub Release](https://github.com/DennyWanye/simple-harness-memory-sdk/releases/tag/v0.5.0)，
并通过公开稳定 URL 下载回验。

0.5.1 仅扩大 Harness metadata 兼容范围到 `>=0.4,<0.6` 并增加真实 wheel 矩阵门禁；personal/family
scope、cloud embedding lineage、receipt/outbox/message 语义不变。Harness 0.4.0 released wheel 格必须
通过；当前 Harness 0.5.0 candidate（source `ac2e2add`）exact-wheel 格也已通过并保存 privacy-safe
superseding receipt。先前 `e44d619` / `7d70b9fa…` receipt 已 superseded，不具 promotion authority。
Harness 正式 v0.5.0 release wheel 已从公开 URL 下载回验，字节与 accepted candidate 一致；H0.4/H0.5
正式格均已通过并保存 formal receipt。

Memory tag `v0.5.1` 指向 release source `da85fa2`；冻结 wheel SHA-256 为 `314c1b89…7a9898`，
sdist SHA-256 为 `63b01464…f69b3`。Release 为 Latest、非 Draft、非 Prerelease，公开制品见
[`v0.5.1` GitHub Release](https://github.com/DennyWanye/simple-harness-memory-sdk/releases/tag/v0.5.1)。

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

显式产品写入使用 principal-scoped fact API，直接返回随后可读取/遗忘/分享的 exact fact ID：

```python fragment
fact_id = await memory.remember_fact(
    principal,
    "Prefer concise replies",
    source_event_id="tool-call-123",
    salience=0.75,
    pinned=True,
    tier="long_term",
)
fact = await memory.read_fact(principal, fact_id)
```

`source_event_id` 在 deployment 内幂等；相同 canonical content/metadata 重放返回同一 ID，内容、
`salience`、`pinned` 或 `tier` 变化均抛 `MemoryIdempotencyConflict`。`tier` 只接受
`auto|working|long_term|identity`，分别稳定映射为 `explicit|event|learning|profile` category；这些
category 仅为兼容标签，不决定保留周期。兼容 Fact 的 `decay_rate` 为 neutral `0.0`，普通维护不会按
category 自动遗忘 Fact。
跨 principal 读取返回 `None`；遗忘后 receipt 保留且重放不会复活 fact。
principal 遗忘动作把现有 `reason` 正式解释为 action `source_event_id`，也可显式传
`source_event_id=` 与可选 `payload_hash=`。首次成功返回 `True`，同 action 重放返回相同结果；新的
action 遗忘已删除 fact 返回并持久化稳定 `False` no-op。同 action 换 fact/payload 会抛
`MemoryIdempotencyConflict`，receipt 只保存 identity、fact ID、hash 与结果，不保存内容。

### 持久化边界

- Human Memory only accepts fresh schema v6/checksum through `build_human_memory_v6`; it never
  upgrades legacy content in place. `MemoryManager.build()` remains the standalone v4 compatibility
  builder.
- SQLite 接受 fresh schema v4；v3/未知 version/checksum 一律 fail-fast。仅已发布且可识别的早期 v4
  recall-snapshot 全局键缺陷会在同一事务内修复为 deployment-scoped key；内容迁移仍只允许显式 migrator。
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
  `memory_second_writer_rejected`。POSIX 使用 `flock`，Windows 使用非阻塞 `msvcrt` byte-range lock；
  writer、checkpoint 与 online backup 共用同一串行边界。
- 召回使用 external-content FTS5，先做 deployment/household/scope 过滤，再执行 MATCH/ORDER/LIMIT；
  vector 只 decode 当前 active generation 的有界 lexical/recent candidates。lineage 漂移或 embedding
  暂不可用时明确降级为 lexical-only，不混用不同模型向量。
- Agent recall 在任何 embedding/ranking 前持久读取 erasure fence；embedding 超时或损坏的降级错误仍
  携带该 fence，因此并发删除后的旧 turn 会稳定返回 `rejected_erased`。
- `reindex_generation()` 分页建立 building generation，校验 count/dimension/hash/sample 后原子切换；失败
  保留旧 active generation。`backup()` 生成带 schema/lineage/SHA-256 的 manifest，`restore_backup()`
  仅允许 manager 关闭后执行，并在替换原库前完成独立完整性校验。
- `recall_bounded()` 对 `(deployment_id, context_query_id)` 保存 canonical 结果；不同 deployment 可安全
  复用 query ID，commit 后重试不重新计算。
- `delete_session()`、`delete_old_sessions()` 和 `delete_all()` 不在 0.6 public API。原始 evidence 不由
  runtime 物理删除；普通使用通过 append-only suppression directive 失效。

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
memory = await MemoryManager.build(enable_world_model=True)

ctx = await memory.world.get_temporal_context()
print(f"今天是 {ctx.date_str}，{ctx.weekday}")
```

## 架构概览

0.6 将不可变 evidence 与 episodic / semantic / procedural / prospective / conditioned-affective
长期状态分开。工作记忆是 Host 组装的有界 Context，不是第六张长期存储表。
LLM 只提出 typed operations；Memory repository 依据 durable phase capability 决定是否应用。

## 开发路线图

- **Phase 1 (MVP)**: 核心接口 + Mock/SQLite 后端
- **Phase 2**: Facts 提取 + BGE-M3 + RRF 六路召回
- **Phase 3**: 遗忘曲线 + 显著性 + 数字孪生体
- **Phase 4**: 世界对象（时间/事件/天气/知识边界）
- **Phase 5**: 集成到 Simple Harness 主应用
- **Phase 6**: 云端后端（Pinecone）

## 许可证

BUSL-1.1，2030-05-27 自动转换为 Apache-2.0。
