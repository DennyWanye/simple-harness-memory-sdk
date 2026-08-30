# 最佳实践调研与本项目适配

> 日期：2026-08-30  
> 阶段：plan-test Phase 1  
> 代码基线：Memory SDK `46624b5`、Harness SDK `716fb85`、Host `e958212`

## 1. 主要矛盾

决定成败的不是“多建几张记忆表”，而是把不可信的 LLM 语义判断，安全地接到永久证据、可演化认知状态、
TaskScope 权限和有限 Context 上：模型只能提出操作；确定性代码必须在同一条可重放链路里完成资格判断、状态
转换、预算裁剪和审计。

## 2. 外部实践与适配结论

| 实践 | 成立前提 | 本项目条件 | 结论 |
|---|---|---|---|
| 人类记忆按多个交互系统与跨系统过程建模，而非三层仓库 | 认知分类不直接等同脑区或数据库 | 产品同时要求真实审计与类人投影 | 改造后用：原始证据独立保存；Working Memory 是运行态；Episode/Semantic/Procedure/Prospective 分开建模；数字孪生体只做投影。依据见 `research/01-*` |
| 目标和线索驱动的类型化检索 | 检索目的、人物、时间、任务等上下文可获得 | Host 以 provenance-bearing `DisclosureContext` 提供 identity/audience/purpose/run/task；语义意图仍需主模型 | 改造后用：主模型提出 `RecallPlan`，SDK 先资格过滤再按类型检索、跨类型排序和预算选择。依据见 `research/02-*` |
| 严格函数调用 + tool result continuation | Provider 支持 JSON Schema tool arguments 和同一响应链续推理 | Harness 已有 ReAct tool continuation，但当前 Memory recall 在 provider 前自动执行 | 照用协议，改造运行时：所有提案工具 `strict=true`，对象禁额外字段，所有字段 required/nullable；Host 返回带 `call_id` 的结果后在同一 Run 续推理。OpenAI 官方文档建议 strict mode，并规定 `additionalProperties=false` 与完整 required 字段；reasoning tool call 的输出要与 reasoning items 一同续传：https://developers.openai.com/api/docs/guides/function-calling |
| Append-only evidence + transactional outbox + idempotency | 业务事实先提交；派生工作允许最终一致 | Host 与 Memory SDK 是两个本地数据库，不能伪造跨库 ACID | 改造后用：Host 原始 Turn/Run/Tool/LLM evidence 是入口事实源；同事务写 durable outbox；Memory SDK 以 source event/idempotency key 接收并返回 receipt；失败不回滚用户已提交事实 |
| Event-sourced authority + materialized views | 事件与 canonical state 有稳定 revision；阅读视图可重建 | TaskScope 需要长期复查，README/STATUS 又必须有界 | 改造后用：Host 保存 raw links、append-only events、canonical state 和 immutable checkpoints；六个 Markdown 仅为 bounded projections，删除可重建 |
| Permission-first retrieval | 候选相似度不能授予身份、隐私或路径权限 | 普通认知记忆 V1 跨 TaskScope 可候选，但 workspace effect 必须 exact root | 照用：subject/recipient/purpose/suppression/status 在排序前过滤；TaskScope search 只定位候选，exact open 才读 canonical archive；binding receipt 才授权 effect |
| SQLite WAL、短事务和周期 checkpoint | 单机同一主机；单 writer；避免长读事务造成 checkpoint starvation | 本产品是单机桌面；多个后台 worker 会并发读写 | 照用：每次 mutation/outbox lease 使用短事务，busy timeout + bounded retry；不跨两个 DB 宣称原子；长导出使用分页快照。SQLite 官方说明 WAL 允许 reader/writer 并发但仍只有一个 writer，并要求关注 checkpoint：https://www.sqlite.org/wal.html |
| FTS + semantic candidate generation | FTS 是词法索引；向量索引需独立验证过滤和规模 | 当前 SQLite 只取候选后在 Python 做 cosine；原型目标 p95 500ms | 改造后用：FTS5 保留精确词召回；向量后端先经可丢弃 spike 决定。没有达到基准前不得引入图数据库或远程向量服务。SQLite FTS5 官方文档：https://www.sqlite.org/fts5.html |
| CAS + stable idempotency key | 每个 mutation 有 base revision 和 canonical payload hash | TaskScope、四类认知状态和 binding set 都会被 worker/retry 触碰 | 照用：同 key 同 payload replay receipt；同 key 异 payload conflict；过期 revision 拒绝并留下 decision，不静默 last-write-wins |
| 逻辑遗忘优先于派生清理 | 原始证据因审计要求不可删；普通读取必须立即阻断 | 用户已明确“永远不删除任何原始数据” | 改造后用：append-only suppression 是同步 deny authority；索引/视图清理异步；普通 exact-ID、旧 checkpoint、cache 与 rebuild 都必须再次过 deny gate |

## 2.1 当前实现证据

- Memory SDK 仍以 `Fact` + 单一 `category` 表达长期记忆（`src/simple_harness_memory/core/models.py:74`），默认
  `RuleBasedFactExtractor` 位于 `features/facts.py:27`，可选 free-form LLM extractor 位于 `:130`；当前 schema 是 v4
  （`backends/sqlite.py:422`），且公共 manager 仍有 physical delete/retention 入口（`core/manager.py:844,850`）。
- Harness SDK 当前公共 recall 只有 Session-centric `MemoryRecallRequest`（`runtime/agent_memory.py:155`）；Kernel 在
  provider 之前直接调用 Memory（`runtime/kernel.py:1047`），而现有 ReAct tool continuation 循环位于
  `runtime/drivers/react_loop.py:186-307`，可作为同 Run route barrier 的落点。
- Host 现有 Context authority 是 `PreparedSdkContextSnapshotV1`（`backend/deskpet/sdk_adapters/context_authority.py:52`），
  history selector 是 `backend/main.py:11147`，最终 snapshot 入口是 `backend/main.py:11189`；目前只把
  `memory_recall/memory_search` 从模型 catalog 过滤（`backend/main.py:7290`）。
- Host 当前 Session UI 仍主动 create/delete（`tauri-app/src/components/SessionList.tsx:166,263`）；默认 Session workspace
  落到 Documents 下的 `SimpleHarnessProjects`（`backend/deskpet/session/project_binding.py:964`），且 raw turn 仍有
  `delete_turn`（`backend/deskpet/memory/session_db.py:4301`）。这些都与冻结目标直接冲突。

## 3. 放弃的方案

- 不采用“Session = Task = Context”：它会让永久主对话无限增长并把项目权限绑错到聊天容器。
- 不采用“全部记忆一次向量 Top-K”：它无法表达程序适用性、前瞻触发、冲突和隐私资格。
- 不采用“小模型先做 MemoryNeedAnalyzer”：用户已确认实验期直接由主模型判断，减少能力不足造成的漏召回。
- 不采用独立 Route Run：`context_route` 是同一 ReAct Run 内的控制屏障，避免额外运行环境和审计断链。
- 不采用跨 Host/Memory DB 的伪两阶段提交：以 Host evidence + outbox 为事实，Memory receipt 为最终一致证据。
- 不采用 graph database：V1 图谱只展示，关系表投影足够；真实规模日志证明需要前不引入新服务。
- 不保留旧 L1/L2/L3 或 Fact category 作为新协议兼容层：本次使用 fresh data，旧数据迁移明确不在范围。

## 4. 解剖麻雀：一条普通多步骤用户请求

典型输入：“继续以前的 Memory SDK 计划，按我一贯的发布检查方式做，完成后提醒我更新变更日志。”

1. Host 在唯一 `primary_conversation_id` 下先写经过 credential filter 的 user evidence 与 ingestion receipt，并把
   消息投入单 foreground Run FIFO。
2. Harness `ProductionAgentKernel` 冻结初始 Context：当前 query、最近 10 个因果 turn group、当前/最近
   TaskScope 目录、受保护规则与当前可见工具；不做自动 Memory recall。
3. 主模型调用严格 schema 的 `context_route`，提出 `resume_existing` 和类型化 RecallPlan；该 tool call、模型输出
   hash、model/prompt/schema lineage 先进入 invocation evidence。
4. Host 校验 Run、subject、mode snapshot、candidate search 权限；TaskScope search 只返回候选。模型选择 exact ID
   后 `task_scope_open` 从 canonical Archive 构造有界 ResumePackage。
5. Memory SDK 对 RecallPlan 先执行 subject/recipient/purpose/suppression/status/expiry 资格门，再并行召回
   Procedure、Prospective、Episode/Semantic 候选，预算化返回 `RecallDecision`；每个 rejected candidate 也有 reason。
6. Host 将 TaskScope ID、binding-set revision、受控 recall fragments 和 root refs 作为 tool observation 返回同一
   ReAct Run。只有新 continuation 中提出的项目 effect 才可执行。
7. Host 为每个 effect 注入 `TaskExecutionEnvelope(run_id, task_scope_id, binding_set_revision, root_id,
   effect_id, idempotency_key)`；工具层仍统一，但 authority 来自 envelope，不来自模型参数。
8. 所有 tool/file/test 结果由 Host 直接追加客观事件。主模型在目标、决定、计划或阶段变化时调用
   `task_scope_update`；最终化前 closure gate 要求覆盖当前 event watermark 的 mutation/no-mutation receipt。
9. 最终 assistant turn、Run terminal、ContextSnapshot 和 decision lineage 一起提交；普通对话立即返回。
10. durable outbox 后台批量请求主模型产生 `MemoryMutationPlan`。Memory SDK 以 evidence refs、CAS、状态机和
    idempotency 校验，更新四类长期记忆、短时域索引和展示图谱 outbox；任何失败不影响原始证据。

这条链路是全部 LLM 驱动状态变化的通用模式：`evidence first → strict proposal → deterministic validation →
transactional decision/state/outbox → replayable receipt → bounded projection`。

## 5. Phase 2 disposable spike 结论与剩余生产门

1. `SPIKE-RUNTIME-BRIDGE`：已用 SQLite crash/reopen prototype 证明每 Provider turn Host snapshot receipt、三方 payload
   hash、Harness execution outbox、Host receipt/cursor 与 terminal watermark 的协议可闭合；生产实现须复跑相同 fault matrix。
2. `SPIKE-PROVIDER-CONTINUATION`：已冻结 durable Provider allowlist 与 canary 零命中；只有 opaque continuation 可持久，
   否则 reasoning disabled/provider rejected。各真实 adapter 支持性仍是 S1 集成门。
3. `SPIKE-CROSS-DB-TRIGGER`：已证明 Memory registration→唯一 Host scheduler→occurrence inbox→pre-provider/pre-terminal
   gate 的幂等协议；生产 Host/Memory 故障矩阵仍必须通过。
4. `SPIKE-VECTOR`：本机 1k/10k/100k synthetic backend benchmark 选择 SQLite metadata/FTS5 + numpy float32 generation
   cache，无新 native dependency；它只证明结构/延迟，不替代 S3 的 200+ 真实 semantic query 质量门。
5. `SPIKE-CONTEXT-DOC`：24 causal groups/1 MiB tool result 和 1k/10k/100k events 已冻结 Context/read-view 常数；
   离线 token oracle 不替代 S5 的真实 provider usage 校准，任何 estimator underestimate 都阻断。
