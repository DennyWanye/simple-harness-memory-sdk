# 跨仓架构基线：Human Memory Digital Twin Program

> 校准日期：2026-08-30
> Memory SDK：`46624b5c49f2c0a64a522eca64d6eb798823370e`
> Harness SDK：`716fb8513095c4ad1dc005cb0fefe991e584c156`
> simple_harness Host：`e95821207d9d61667c8e0f111c81477e78991ba2`
> 状态：Phase 0 PASS（architecture challenger round 1 FAIL，修正后 round 2 PASS）

## 主要矛盾

当前生产链在 Provider 第一次调用前自动执行统一 Memory recall，并以 Session 作为历史、项目和 UI 边界；
目标却要求同一个主模型在同一 ReAct Run 中先判断 TaskScope/记忆需求，再由确定性代码按认知类型、隐私、
状态和预算执行，最后把有界结果继续送回同一模型。若不先改变 Harness 的路由时序和 Host 的 Session/Task
权威边界，只扩充 Memory SDK 表结构，会得到“数据类型变多，但模型仍无法正确决定何时使用”的假升级。

## 当前典型调用链（从 UI 请求到记忆落库）

1. Host 为每个请求创建或继续一个 Session/Run，并构造 `ConversationTurnInput`；当前输入仍携带
   `AgentIdentity(..., session_id)`（`simple_harness/runtime/agent_memory.py:61-87`、
   `simple_harness/runtime/conversation_memory.py:109-160`）。
2. Host 从同 Session 读取最多 10,000 行，再按 Token 从最新向前保留；这是“可用预算内的消息行”，不是
   最近 10 个完整因果 turn group（`simple_harness/backend/main.py:11147-11186`）。
3. Harness 在首个 Provider attempt 前调用 product context provider 与 `AgentMemoryPort.recall_for_turn`，冻结
   prepared stage；ReAct 恢复只读 frozen snapshot（`simple-harness-sdk/ARCHITECTURE/ARCHITECTURE.md:87-125`，
   `simple_harness-sdk/src/simple_harness/runtime/kernel.py:900-1188`）。
4. ReAct loop 从 frozen Context 发起 Provider 请求，收到工具调用后逐个写 effect 并把 Tool Result 追加回
   Context，直到最终回答（`simple-harness-sdk/src/simple_harness/runtime/drivers/react_loop.py:186-360`）。
5. completed terminal 才创建 canonical user+assistant `CommittedTurn`；Memory dispatcher 经 durable outbox
   调用 `record_committed_turn`（`simple-harness-sdk/src/simple_harness/runtime/kernel.py:3036-3111`）。
6. Host 以 `enable_facts=True` 启动 MemoryManager，却没有传 `fact_extractor`；backend 因而回退到
   `RuleBasedFactExtractor`（`simple_harness/backend/main.py:3041-3068`、
   `simple-harness-memory-sdk/src/simple_harness_memory/backends/base.py:98-134`）。
7. Memory SDK 原子写 user/assistant message 与 fact job；后台 worker 异步运行默认正则 extractor，写入统一
   `facts` 表（`simple-harness-memory-sdk/src/simple_harness_memory/core/manager.py:413-500`、
   `simple-harness-memory-sdk/src/simple_harness_memory/features/facts.py:27-127`）。

## 三仓当前权威与缺口

### Memory SDK 0.5.2

当前权威：

- `MemoryManager` 直接实现 `recall_for_turn`、`release_recall`、`record_committed_turn`；SQLite v4 保存
  session/message/fact/recall snapshot/receipt/fact job/embedding generation。
- identity 是 deployment/household/actor/session，scope 只有 personal/family；召回有 item/byte/deadline、
  replay hash、erasure fence 与 FTS/vector generation。
- Fact 只有 `subject/key/value/category/confidence/evidence/source_msg_id`，以 `superseded_by` 和
  `forgotten_at` 表示简单演化（`src/simple_harness_memory/core/models.py:58-103`）。
- `DigitalTwin` 由 active Fact 聚合，冲突只检测少量 single-valued keys（
  `src/simple_harness_memory/cognitive/twin_builder.py:9-71`）。

决定性缺口：

- 无 Episode/Semantic/Procedure/Prospective 独立 schema、状态机与 relation graph。
- 默认事实判断是正则；可选 `LLMFactExtractor` 使用旧 Chat Completions、自由 JSON、无 invocation/decision
  审计并吞掉异常（`src/simple_harness_memory/features/facts.py:130-186`）。
- `delete_scope`、`forget_fact`、`delete_session` 会物理删除原始 message/fact/session（
  `src/simple_harness_memory/backends/sqlite.py:1644-1714`、`:1716-1822`、`:2809-2820`）。
- recall 只接收 query text 和 scope，没有 RecallPlan、recipient/purpose、认知类型、epistemic/conflict/expiry。

### Harness SDK 0.6.4 candidate

当前权威：

- durable Run/ReAct/effect/UoW、Provider request snapshot、tool catalog、conversation Context staging 和 Memory
  outbox 均由 SDK 拥有。
- `AgentMemoryPort` 是产品中立的三方法边界；Memory 被降权为 USER/untrusted data。
- conversation continuation 可以在既有非终态 Run 内排队；正常新请求、等待中 continuation 和 terminal 后
  新 Run 的产品路由仍由 Host 决定。

决定性缺口：

- 自动 recall 发生在主模型之前；主模型没有 RecallNeedAnalyzer/RecallPlan 决策机会。
- 无 TaskScope route/search/open/mutation、binding-set revision 或 per-Effect `TaskExecutionEnvelope` 公共 DTO。
- 无单 foreground Run + 普通消息 durable FIFO + control priority 的完整协议。
- Context contract 不表达最近 10 个完整因果组、五天 short-horizon、TaskScope projection、分区 Token 预算、
  page-in 与最终选择 reason。

### simple_harness Host

当前权威：

- Host 选择 Provider、冻结 tool/skill/project/attachment/persona Context，拥有本地路径、权限、UI 与真实
  Provider 调用组合。
- `PreparedSdkContextSnapshotV1` 已冻结 Provider messages、catalog、attachments、sections、budget、lineage
  与 Memory ref/hash，并提供 default-deny 公共投影（`backend/deskpet/sdk_adapters/context_authority.py:51-187`、
  `:193-316`）。
- Project binding 校验 canonical root/filesystem identity，并把单个 Session 不可变绑定到一个 Project/执行根
  （`backend/deskpet/session/project_binding.py:58-97`、
  `backend/deskpet/memory/migrations/024_project_scoped_sessions_v32.sql:19-67`）。

决定性缺口：

- 当前 `TaskSessionManager` 仅用 `/new`、`/continue` 正则/前缀产生 effective session id，全部为进程内字典；
  不是真正 TaskScope（`backend/deskpet/session/task_scope.py:21-154`）。
- 多 Session 列表、标题、删除和 immutable single-project binding 与“一个永久主对话 + TaskScope 多根”冲突。
- `SessionDB.delete_turn` 物理删除 message 与 vector（`backend/deskpet/memory/session_db.py:4301-4327`）。
- Context 历史按 Token 截断，不保证因果组；无五天专用索引和 TaskScope canonical state。
- model-visible catalog 只排除 `memory_recall` / `memory_search`；`memory_write` / `memory_read` /
  `memory_forget` 仍作为显式 Fact 管理工具可见。write 使用可信 principal，read 按 exact Fact ID，forget
  最终进入当前 Memory SDK 的物理删除路径（`simple_harness/backend/main.py:7275-7291`、
  `simple_harness/backend/deskpet/tool_catalog/providers.py:342-420`）。
- 没有 TaskScope Archive/Search Index/六阅读视图/immutable checkpoint，也没有数字孪生 graph UI。

## 目标所有权（Phase 1 计划必须保持）

| 权威 | 唯一职责 | 不得拥有 |
|---|---|---|
| Memory SDK | 原始 Memory evidence 接收、四类长期认知状态机、short-horizon/long-term 检索、suppression、关系投影、审计 trace | Host 路径授权、最终 Provider Context、UI、模型选择 |
| Harness SDK | 版本化 DTO、单 Run 路由 barrier、durable FIFO/control、ReAct/tool/effect 生命周期、Context selection/replay 接缝 | 产品目录创建、具体 TaskScope 文档、记忆语义真值、数字孪生 UI |
| simple_harness Host | 唯一主对话、主模型 prompt/tool 接线、TaskScope canonical archive 与多根绑定、最终 Context assembler、真实 Provider/工具权限、审计与 graph UI | 绕过 SDK route/effect 状态机、直接改认知记忆表、把 graph 投影回灌 Agent |

## 不可复用与可复用

可复用：四元 identity、durable outbox/lease/CAS/idempotency、Provider request snapshot、tool effect ledger、
Context private/public snapshot、BGE/FTS generation、Project filesystem identity 校验。

必须替换或退役：Fact category 单表作为认知模型、默认正则提取、物理 delete privacy 语义、pre-provider
automatic recall、Session=TaskScope、单 Project root、按任意消息行 Token 截取的历史，以及缺少 model-visible、
版本化 `RecallPlan` / context-route / typed-recall 协议。既有显式 write/read/forget 工具必须被明确升级或退役，
不能在含义不清的情况下重复建设。

## 待 Phase 2 spike 闭环

1. 如何在首个 Provider attempt 中同时允许“直接最终回答=no_recall”与“调用 context_route/recall 后续推理”，
   并对未调用工具的直接路径生成无额外 LLM 调用的可审计 decision。
2. SQLite fresh schema 中 raw evidence、认知状态、suppression、TaskScope event/checkpoint 分库还是同库事务；
   需以 crash injection 验证跨 owner outbox，而不是假设跨数据库原子事务。
3. 最近 10 个“完整因果 turn group”的稳定边界，尤其 tool-call/tool-result、cancelled/failed Run 与排队消息。
4. README/STATUS 上限、拆分格式与从 canonical facts 重建的确定性。
5. 图谱布局与大型关系集的 UI 性能；V1 不引入图数据库。
