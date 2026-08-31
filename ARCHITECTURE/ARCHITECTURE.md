<!-- last-calibrated: 46624b5c49f2c0a64a522eca64d6eb798823370e -->

# ARCHITECTURE — simple-harness-memory-sdk（v0.6.0 candidate）

> 最后更新：2026-08-31
> 当前事实：Human Memory V0/S1/S2 与 S3 Task 1/2 已闭合；S3 Task 3—7、Host/UI 接线与最终 candidate
> packaging 尚未完成。旧 Agent Memory v1 能力仍保留，但不是新认知 mutation 的 authority。

## Human Memory Program 当前边界（2026-08-31）

以下是 0.6 candidate 的已验证生产边界：

- fresh `human-memory-v1` schema v5 保存不可覆盖的原始 evidence、conversation registration、suppression、
  durable analysis，以及 Episode、Semantic、Procedure、Prospective 四类 typed revision/head/relation。Working
  Memory 仍只存在于运行 Context，不建立长期存储表。
- `MemoryMutationPlan` 只接受 Harness mutation schema v4；四类 payload、生命周期、epistemic/conflict/
  verification/valid-time、classification 与 TaskScope origin 在同一 strict-atomic transaction 落库。
- CREATE 依靠 exact admitted evidence 与 Memory classification policy；修改既有记忆的 REVISE、SUPERSEDE、
  SUPPRESS 必须解析 Host `MemoryActionAuthority` schema v2，并精确绑定 subject、whole plan intent、canonical
  operation index、target ID/revision、evidence/span、run/turn、expiry、issuer 与 replay identity。
- 缺 action authority 返回 typed `NEEDS_USER_CONFIRMATION` 且不写认知状态；无效、过期、lookup miss、clock
  rollback 或 nonce replay 返回 typed `REJECTED` 并写 durable rejection audit。成功消费在 mutation transaction
  内以 `(issuer_ref, nonce)` 和 `replay_identity` 双唯一锁定；exact idempotent receipt replay不重复消费。
- CONTEST 不是 action-authority 旁路：target payload、lifecycle、epistemic、verification 与 valid-time 必须完全
  不变，只允许 conflict flag 进入 CONTESTED；否则原子拒绝。
- evidence classification 由 Memory policy、全部 Host `EvidenceItemAuthority` floor、target 与 proposal 做单调
  privacy max / attribute union。classification、action consumption、mutation decision、receipt 与 apply result
  都是不可变 hash-bound 审计链；close→tamper→reopen resolver fail closed。
- backend 与所有 production builders 都没有 fact extractor 参数或 worker 启动路径；旧 regex
  extractor 只存在于 `tests/fixtures`，不进入 source distribution 的生产包或 wheel。Harness 0.7 typed
  analysis 是新的 LLM 边界。
- 兼容 `Fact` 的 `category` 只作标签，`decay_rate` 为显式 neutral 值；category 不再决定保留周期，
  `daily_decay()` 也不再按 category 自动遗忘 Fact。
- public `MemoryManager`、`MemoryBackend` 与 `BaseMemoryBackend` 不存在会话物理删除方法。
- 新认知召回 pipeline 尚未接入公开 manager/port；旧召回仍只接受 query text、personal/family scopes 与统一
  结果 payload，尚无完整 `RecallPlan`、认知类型、
  recipient/purpose、epistemic/conflict/expiry 或跨 TaskScope 命中审计。
- `DigitalTwin` 仍是 Fact 聚合对象和 JSON 快照；没有展示专用的可追溯 graph projection，也没有
  “不得进入 Agent Context/召回/动作”的机器边界。
- 本 program 不迁移旧内容数据；schema v5 必须 fresh 初始化，旧数据库由 loader 稳定拒绝。

## 分层

```text
src/simple_harness_memory/
├── core/         # MemoryManager、standalone identity/scope、Agent backend port、durable analysis kernel
├── backends/     # BaseMemoryBackend + Mock + SQLite fresh-v4
├── features/     # Python 内有界候选融合 / reranker / summarizer（无 fact extractor）
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

## 当前 Observability 边界

- 基础依赖为 `simple-harness-sdk>=0.7,<0.8`，本地开发仍由 `uv.sources` 指向 sibling checkout。
  Memory 只复用 import-pure `simple_harness.observability` envelope、correlation、runtime 与 sinks；没有
  复制 wire schema，也不让 observability 成为授权、重试、CAS、事务或恢复 authority。
- `MemoryManager` direct init、三个 builders，以及 Mock/SQLite direct backend constructors 接受可选
  `observability_sink` / `correlation`。Noop 默认路径保持旧行为，sink construction/emit/close failure
  只增加共享 runtime counters。
- recall 发射 accepted/started/replayed/degraded/succeeded/released/cleanup/failed；committed turn 在权威
  receipt 可见后发射 applied/replayed/rejected。0.6 production path 不启动 legacy fact worker。
- correlation 未新增 durable 列：recall `query_id`、receipt `turn_id` 与 `session_id` 足以生成 bounded
  opaque identity；Host 显式注入时原样贯穿。
- `diagnostics_snapshot()` 的 schema 固定且有界。Mock 从内存状态聚合；SQLite 仅 GROUP BY/COUNT/MIN
  `state/status/created_at/last_error_code`，100ms query timeout、250ms manager deadline，错误与 close
  返回 degraded/closed schema 而不影响业务。禁止查询 content、result_payload、fact value、embedding、
  文件 path 或 exception repr；recent error codes 最多 20 项，age clamp 为非负值。

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
- `record_committed_turn` 在一个事务中写 turn receipt、user row和assistant row；任一步失败全部回滚。
  production builder 不创建 legacy fact job。幂等键为deployment+turn；同deployment下同turn+hash且完整identity/scope相同返回
  `already_applied`，payload或owner/scope不同返回conflict。
- fence 过期返回 hash-only `rejected_erased`。无 fence时，仅可信 `turn_started_at` 严格晚于最新
  `erased_at` 且不超当前可信时钟才可绑定当前 epoch；早于、相等或时钟回退均 fail closed。

## Legacy Fact compatibility storage

- 旧 v4 Fact/job 表只保留为 dormant compatibility storage、只读 diagnostics 与 erasure cleanup；
  production Mock/SQLite 不暴露 recover/claim/apply/fail mutation seam。
- regex extractor 与 legacy worker 都已完全移到 `tests/fixtures`，不打入 wheel/sdist 的 production package。
- 显式 `remember_fact()` 仍可写兼容 Fact；category 仅作标签，写入 neutral `decay_rate=0.0`，普通
  `daily_decay()` 不再扫描、衰减或自动遗忘 Fact。

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
- principal `forget_fact`将reason/source_event_id持久绑定到deployment/household/actor/fact/hash；同动作重放
  返回原bool，不同动作对已遗忘fact记录false no-op，receipt不含content。
- Agent Memory structured events只记录 opaque principal、ID/hash、count/bytes/stable code；不记录 content、
  token、embedding、数据库路径或 exception repr。legacy standalone日志中的 user/session/source id也已哈希。

## 当前明确限制 / 后续 Slice

- simple_harness 已完成 exact-wheel 产品接线与真实 macOS UI；该结论不外推到其他消费者。
- AIPhone、K6/AgentOS、NovelTagSystem 未修改、未集成、未测试；前两者仅为 Agent Memory v1 接口就绪。

## Release candidate identity

- 唯一版本事实源为`src/simple_harness_memory/__init__.py`，当前 source candidate 为0.6.0；wheel metadata、README、公开API
  snapshot、changelog与candidate `BUILD_INFO.txt`必须一致。
- base wheel metadata 直接要求 `simple-harness-sdk>=0.7,<0.8`，`[harness]` 保持同一范围；当前 clean
  resolver gate 只接受 exact Harness 0.7 artifact，`<0.7` 与 `>=0.8` 必须拒绝。
- CI只build一次candidate wheel/sdist并记录source commit与SHA-256；Python 3.11/3.12/3.13及Windows x64、
  macOS ARM64、Linux ARM64 downstream只下载/验证同一 Memory artifact 与同一 pinned Harness 0.7
  artifact，不允许重建。0.6 当前只生成候选制品，不调用旧 release workflow，也不 tag/push/publish。

### 历史发布事实（不代表 0.6 current contract）

- Memory tag `v0.4.0` 指向 `3d4247b` 的冻结 candidate；2026-08-23 source、`main` 与 tag 已推送；
  当时的 wheel/sdist 已正式发布到 GitHub Release，并通过公开稳定 URL 下载回验。
- 0.5.0 已发布：tag 指向 `9c92ede`，wheel SHA-256 为
  `c274fa6b2db538c29897f684b3f2f85775cb4b3a6870018e83792ff90b51ea46`；公开下载回验通过。
  base 与 `[harness]` metadata 均要求 `simple-harness-sdk>=0.4,<0.5`。
- 0.5.1 已发布：仅扩大 Harness metadata 范围并增加真实 wheel 矩阵，不改变 Memory 业务模块行为。
  released Harness 0.4.0 与 Harness 0.5.0 candidate/release 是两个强制 clean-venv 格；H0.5 wheel 未就绪时
  必须保持 pending，两个格均通过前不得发布。H0.4.0 released wheel 本地 clean-venv 格已通过，CI 使用
  固定 SHA-256 重跑同一 oracle；当前 H0.5.0 candidate commit `ac2e2add` / wheel `d5ac2976…` 已通过同一
  clean-venv aggregate 并保存 privacy-safe superseding receipt。旧 `e44d619` / `7d70b9fa…` receipt 已
  superseded；Harness v0.5.0 正式 wheel 与 accepted candidate 字节一致，H0.4/H0.5 release/download-back
  aggregate 均已通过并保存 formal receipt。
- Memory annotated tag `v0.5.1` 解引用到 `da85fa2`；正式 wheel `314c1b89…`、sdist `63b01464…` 均与
  clean-source 第二次构建逐字节一致，并通过公开 URL 下载回验。GitHub Release 为 Latest、非 Draft、
  非 Prerelease。

## 验证状态

- Human Memory S3 Task 1/2 candidate：Harness exact HEAD `baaefac2`（Mutation v4 / Action Authority v2）；
  Memory 全仓 `758 passed, 9 skipped`，Ruff 全绿，mypy `107 source files` 全绿，`git diff --check` 通过。
  独立 mutation/classification/action-authority closure audit 为 P0/P1/P2=0；focused `105 passed`，覆盖 missing/
  invalid/expired/lookup-miss/clock-rollback/replay、CONTEST 旁路、late fault 原子回滚、principal attribution 与
  receipt/ledger/decision corruption close→tamper→reopen。该证据只关闭 S3 Task 1/2，不代表 S3 整体完成。

- 0.6.0 Task 6 source audit：冻结 Harness 0.7 下全仓 `493 passed, 8 skipped`；Ruff、项目 mypy
  `97 source files`、3 个发布脚本 strict mypy 与 REUSE 全绿。非最终 dirty-tree wheel/sdist 通过 Twine，
  public/artifact/clean-consumer gate `17 passed`；wheel 明确不含 `core/fact_jobs.py`、legacy worker 或 backend
  recover/claim/apply/fail seam，并消费 Harness wheel
  `b9421ddf…6037d7b`；这组 Memory bytes 只证明 source contract，不具 promotion authority。只有从审阅后的
  clean commit 重建并复验的 bytes 才能成为最终 candidate。候选制品未 tag/push/publish。

- 以下为 0.5 历史 observability/release 证据，不代表 0.6 fact-worker production path：privacy canary、sink failure isolation、public/direct composition、recall/
  receipt/fact-job 状态矩阵、snapshot schema/bounds/SQL denylist、close/reopen recovery correlation 均通过；
  `tests/integration/test_observability.py` 13 passed。Harness candidate `bc6ae8d` 声明 0.4.0，Memory installed
  metadata 确认 base/extra 均解析 `simple-harness-sdk>=0.4,<0.5`。
- 0.5.0 release-identity gate：源码 full `213 passed, 7 skipped`，Ruff 全绿，mypy 对 src/tests
  `83 source files` 全绿；本地临时 0.5.0 wheel/sdist 通过 Twine，联合 Harness 0.4 exact-wheel
  artifact suite `10 passed`；发布制品与下载回验字节一致。

- S3 targeted：Agent direct port、Mock/SQLite、atomic fault、fact recovery、identity rebind、scope matrix、
  export/delete/forget、erasure replay、日志 canary均通过。
- S4 targeted：20k/100k FTS query plan与有界 recall、generation restart/switch/failure、production embedder、
  second-writer reject、checkpoint、backup/restore/corruption preserve均通过。
- S3 migration targeted：四类完整覆盖、canonical pair补齐、derived cascade、non-Harness provenance、
  identity/digest tamper、三阶段fault rollback及Harness公开manifest/runtime replay均通过。
- S5 Memory candidate：0.4.0 public snapshot、base import blocker、真实`[harness]` resolver、错误版本拒绝、
  installed-wheel strict typing、candidate metadata/SHA与跨Python/平台消费门禁已定义。
- 最终本仓默认 full：`200 passed, 7 skipped`；正式 candidate gate：`205 passed, 2 skipped`；Ruff 与 mypy 全绿。
- Memory `3d4247b` / 0.4.0 wheel `bfcd2506…` 由 simple_harness `4e797ccd` exact installed-origin
  消费；产品 Gate r4 的 21/21 required 场景达到 `READY_FOR_AUDIT`。SH-M5 跨进程新 Session 召回，
  SH-M6 recall timeout 与 record transient/startup recovery 均由真实 UI + DeepSeek 验证。
