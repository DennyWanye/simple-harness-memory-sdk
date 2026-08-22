<!-- last-calibrated: working-tree-after-87820fe2c4cdde21c3a9356ca461b93fe00aadcb -->

# ARCHITECTURE — simple-harness-memory-sdk（v0.4.0）

> 最后更新：2026-08-22
> 当前事实：S3 runtime、四类 taxonomy offline migration、S4 storage/embedding 与 S5 Memory
> candidate packaging 已实现；simple_harness 产品接线和真人测试仍属于 S6。

## 分层

```text
src/simple_harness_memory/
├── core/         # MemoryManager、standalone identity/scope、Agent backend port、fact worker
├── backends/     # BaseMemoryBackend + Mock + SQLite fresh-v4
├── features/     # facts 提取 / Python 内有界候选融合 / reranker / summarizer
├── cognitive/    # 遗忘曲线 / 显著性 / 会话亲和 / 孪生体构建
├── embedders/    # hash 默认 / bge 可选 / cloud
└── world/        # WorldModelPort + temporal/events/geography/knowledge
```

## Agent Memory v1 一等边界

- `MemoryManager` 直接结构满足 Harness `AgentMemoryPort`：`recall_for_turn`、`release_recall`、
  `record_committed_turn`。消费者不构造公开 Adapter，也不维护自动 recall/append/outbox。
- Memory→Harness 是单向 optional `[harness]` extra；包根和 standalone API 不 import Harness，integration
  方法才 lazy import canonical DTO/status/error。缺 extra 稳定报 `harness_integration_extra_required`。
- root `__all__` 已移除旧 `ConversationMemoryAdapter` 与重复 DTO/enums；`core.conversation` 仅作为现有
  standalone canonical/hash 与内部兼容 helper，不是官方组合入口。
- default write scope 是 actor personal；recall 可读取 actor personal + household family。Memory 内容只作为
  带 scope provenance 的数据返回，instruction trust 投影由 Harness S1 负责。

## Fresh schema v4 与 identity/scope

- SQLite 接受 fresh v4/checksum；v3、缺 meta 或未知 checksum 漂移均 `MemorySchemaIncompatible`。仅已知
  早期v4 recall snapshot全局键通过checksum-gated事务修复，不执行内容迁移或删除。
- sessions/messages/facts/recall snapshots/receipts/jobs/erasure state 全链路保存
  deployment/household/actor/session/scope_kind/scope_owner；sessions主键为deployment+session，turn receipt
  主键为deployment+turn，允许不同deployment复用外部ID；同一deployment内的household/actor/session
  rebind在recall/read前失败，receipt replay还复核完整owner与scope。
- recall snapshot主键为deployment+context_query_id，允许不同deployment复用外部query ID。
- recall/export/delete/forget 使用 `core.identity.scope_predicate()` 同一 ownership predicate；personal
  owner 必须是 actor，family owner 必须是 household，不同 household 不进入候选集。
- SQLite 使用 WAL、FK、busy timeout、task-owned operation lock 与 `BEGIN IMMEDIATE`；数据库文件继续要求
  regular/no-symlink/current-owner/`0600`。每个数据库另有跨平台 OS writer lease（POSIX `flock`、Windows
  `msvcrt`非阻塞byte-range lock），第二个 live manager fail-closed；
  writer、checkpoint 与 online backup 都经同一 operation lock 串行。

## 有界检索与 embedding generation

- messages/facts 使用 external-content FTS5 与同步 insert/update/delete trigger。查询先绑定
  deployment/household/scope predicate，再 MATCH、稳定排序和 SQL LIMIT；20k/100k scale fixture 均确认
  query plan 使用 FTS virtual-table index。
- vector 只从当前 active generation 读取，候选来自有界 FTS + recent ids；每次 decode 有硬上限。
  active lineage 与当前 embedder 不一致，或 query embedding 失败时，记录稳定降级 code并只走 lexical，
  不混算未知 revision/dimension 的向量。
- lineage 包含 kind/provider/model/revision/dimension/normalization/format fingerprint，并以 canonical SHA-256
  标识。BGE 强制 local-only；production builder 拒绝 hash/mock、隐式模型或缺失资源。
- reindex 建立 building generation，分页持久化 cursor，可从中断点继续；count/dimension/hash/sample 校验全部
  通过后，在一个事务中 retired 旧 active并激活新 generation。故障 generation标记 failed，旧 active不变。

## SQLite 运维

- online backup 由 live manager串行执行，manifest记录 protocol、schema/checksum、SQLite version、active
  generation/lineage、SHA-256 与时间。日志只包含 hash/count/duration/stable code，不含路径或内容。
- restore 仅在 manager关闭后开放；先校验 manifest/hash、WAL残留、integrity/FK/schema/lineage，再写临时库并
  原子替换。任一校验失败保留原库。

## v3 → v4 显式迁移

- runtime loader仍只接受fresh v4；升级入口独立位于`simple_harness_memory.migrations`，不进入
  `AgentMemoryPort`。Memory结构化读取Harness公开manifest，不反向import Harness package。
- backup-first migrator要求closed source及可信一对一identity map；execution manifest与独立non-Harness
  provenance manifest对每个v3 source event恰好覆盖一次。未知版本、重复/缺失归属、identity歧义、digest或
  payload hash漂移均fail closed。
- `KEEP_COMPLETED_PAIR`保留完整user/assistant pair，缺失半边只能由hash-verified canonical turn补齐；
  `SUPPRESS_TENTATIVE`、`SUPPRESS_TERMINAL`、`DEFERRED_TURN`均不复制message/inline embedding/source facts，
  并写`legacy-source:` namespaced hash-only receipt。recall stage丢弃，digital twin只从保留facts重建。
- 临时v4经count/FK/integrity验证后原子替换；swap后故障从已验证backup恢复。公开runtime import只接受KEEP、
  遵守erasure、整manifest事务幂等，Harness outbox重放命中同canonical turn receipt而不重复写pair。

## Durable recall 与 committed turn

- 每个 query id 保存 canonical payload/result hash、identity binding、scope-set hash 与 personal erasure
  write fence；同 id 异 query/identity 冲突，同 id 同输入重放冻结 payload。release 校验 query/result hash，
  并有界清理超过 retention horizon 的 released stage。
- recall 先在短事务读取 erasure epoch/fence，再做embedding与候选ranking；embedding timeout/corruption或
  后续查询故障都通过task-local fence传入稳定Harness error。删除可以安全跨越embedding边界，旧fence的
  committed turn仍会被拒绝。
- `record_committed_turn` 在一个事务中写 turn receipt、user row、assistant row和可选 fact job；任一步失败
  全部回滚。幂等键为deployment+turn；同deployment下同turn+hash且完整identity/scope相同返回
  `already_applied`，payload或owner/scope不同返回conflict。
- fence 过期返回 hash-only `rejected_erased`。无 fence时，仅可信 `turn_started_at` 严格晚于最新
  `erased_at` 且不超当前可信时钟才可绑定当前 epoch；早于、相等或时钟回退均 fail closed。

## Durable fact worker

- committed user row只创建 durable `pending` job。worker 用 claim/lease/attempt/backoff 状态机；启动时
  回收过期 `claimed`，5 次失败进入 `dead_letter`，close 做有界 drain。
- extractor 在事务外运行并携带 versioned lineage；canonical extraction hash、deterministic fact ids、
  facts 与 job `applied` 在一个事务提交。提交前复核 erasure epoch 和 fact tombstone，删除/forget 之后的
  late worker只能进入 erased/no-op，不能复活内容。
- 旧 standalone `append_message` 保留兼容行为；官方自动 Memory 生命周期只走 committed-turn worker。

## Privacy lifecycle

- `export_principal` 是 versioned、有界、分页输出，默认不包含 raw embedding。
- `delete_scope/delete_principal` 先推进 erasure epoch，再级联 messages/facts/recall stages/job payload；
  turn receipt 与 hash-only tombstone保留以拦截旧 outbox/job。
- `forget_fact` 保存 deterministic provenance tombstone，并删除该 personal fact 及 family projections；
  `share_fact` 是Harness-free顶层公共能力，以source provenance+household生成deterministic projection id，
  重复调用幂等且只保留一行；跨actor/household抛`MemoryOwnershipConflict`，family row以`projection_of`
  保留来源。forget source级联删除projection并留source tombstone，applied/late job replay不会复活。
- `remember_fact/read_fact` 是Harness-free principal显式写读能力，返回exact fact ID；完整identity、content、
  salience/pinned/tier进入canonical replay hash，forget保留receipt且不复活。
- Agent Memory structured events只记录 opaque principal、ID/hash、count/bytes/stable code；不记录 content、
  token、embedding、数据库路径或 exception repr。legacy standalone日志中的 user/session/source id也已哈希。

## 当前明确限制 / 后续 Slice

- simple_harness 的 exact-wheel 产品接线与 MCP 真人 UI 尚未执行，不能把 SDK conformance 写成产品实测。
- AIPhone、K6/AgentOS、NovelTagSystem 未修改、未集成、未测试；前两者仅为 Agent Memory v1 接口就绪。

## Release candidate identity

- 唯一版本事实源为`src/simple_harness_memory/__init__.py`，当前为0.4.0；wheel metadata、README、公开API
  snapshot、changelog与candidate `BUILD_INFO.txt`必须一致。
- base wheel metadata不必选Harness；`[harness]`严格要求`simple-harness-sdk>=0.3,<0.4`。clean resolver gate
  使用真实Harness 0.3 candidate，0.2.x和0.4.x均必须拒绝。
- CI只build一次candidate wheel/sdist并记录source commit与SHA-256；Python 3.11/3.12/3.13及Windows x64、
  macOS ARM64、Linux ARM64 downstream只下载/验证同一artifact，不允许重建。release workflow仍只验证并
  交接冻结bytes，不upload、不tag。

## 验证状态

- S3 targeted：Agent direct port、Mock/SQLite、atomic fault、fact recovery、identity rebind、scope matrix、
  export/delete/forget、erasure replay、日志 canary均通过。
- S4 targeted：20k/100k FTS query plan与有界 recall、generation restart/switch/failure、production embedder、
  second-writer reject、checkpoint、backup/restore/corruption preserve均通过。
- S3 migration targeted：四类完整覆盖、canonical pair补齐、derived cascade、non-Harness provenance、
  identity/digest tamper、三阶段fault rollback及Harness公开manifest/runtime replay均通过。
- S5 Memory candidate：0.4.0 public snapshot、base import blocker、真实`[harness]` resolver、错误版本拒绝、
  installed-wheel strict typing、candidate metadata/SHA与跨Python/平台消费门禁已定义。
- 当前本仓 full 以最终 gate 重跑数字为准；Ruff 与 mypy全绿。
- simple_harness 产品接线、真实UI与最终promotion仍属S6，不能由SDK自动化替代。
