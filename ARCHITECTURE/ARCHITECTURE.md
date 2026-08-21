<!-- last-calibrated: working-tree-after-87820fe2c4cdde21c3a9356ca461b93fe00aadcb -->

# ARCHITECTURE — simple-harness-memory-sdk（v0.4.0）

> 最后更新：2026-08-22
> 当前事实：S3 runtime 与 S4 storage/embedding 已实现；offline migration 因 A2 taxonomy 冻结问题暂停。

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

- SQLite 仅接受 fresh v4/checksum；v3、缺 meta 或 checksum 漂移均 `MemorySchemaIncompatible`，不会在
  runtime 隐式迁移或删除。
- sessions/messages/facts/recall snapshots/receipts/jobs/erasure state 全链路保存
  deployment/household/actor/session/scope_kind/scope_owner；session 第一次绑定后，任何 identity rebind
  在 recall/read 前失败。
- recall/export/delete/forget 使用 `core.identity.scope_predicate()` 同一 ownership predicate；personal
  owner 必须是 actor，family owner 必须是 household，不同 household 不进入候选集。
- SQLite 使用 WAL、FK、busy timeout、task-owned operation lock 与 `BEGIN IMMEDIATE`；数据库文件继续要求
  regular/no-symlink/current-owner/`0600`。每个数据库另有 OS writer lease，第二个 live manager fail-closed；
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

## Durable recall 与 committed turn

- 每个 query id 保存 canonical payload/result hash、identity binding、scope-set hash 与 personal erasure
  write fence；同 id 异 query/identity 冲突，同 id 同输入重放冻结 payload。release 校验 query/result hash，
  并有界清理超过 retention horizon 的 released stage。
- recall 先读取 erasure epoch/fence，再做候选查询；查询后故障通过 task-local fence 传入稳定 Harness error，
  使空召回降级后的 committed turn仍能校验删除边界。
- `record_committed_turn` 在一个事务中写 turn receipt、user row、assistant row和可选 fact job；任一步失败
  全部回滚。同 turn+hash 返回 `already_applied`，同 turn 异 hash 返回 conflict。
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
  `share_fact` 以 deterministic projection id投影到 household family scope，重复调用幂等。
- Agent Memory structured events只记录 opaque principal、ID/hash、count/bytes/stable code；不记录 content、
  token、embedding、数据库路径或 exception repr。legacy standalone日志中的 user/session/source id也已哈希。

## 当前明确限制 / 后续 Slice

- 显式 offline v3→v4 migrator与公开 migration manifest API 尚未实现。原因是已冻结三类 decision 无法
  唯一覆盖 continuation completed run 的早期 tentative user events（A2 `a2-001`）；在新增 taxonomy
  获批前必须暂停，不能猜测导入、丢弃或复制。
- AIPhone、K6/AgentOS、NovelTagSystem 未修改；它们只通过后续 joint wheel fixture验证未来接口。

## 验证状态

- S3 targeted：Agent direct port、Mock/SQLite、atomic fault、fact recovery、identity rebind、scope matrix、
  export/delete/forget、erasure replay、日志 canary均通过。
- S4 targeted：20k/100k FTS query plan与有界 recall、generation restart/switch/failure、production embedder、
  second-writer reject、checkpoint、backup/restore/corruption preserve均通过。
- 当前本仓 full 以最终 gate 重跑数字为准；Ruff 与 mypy全绿。
- exact wheel、Python 3.11/3.12/3.13联合 Harness candidate 与 release metadata 属 S5 gate，不能由 editable
  开发安装替代。
