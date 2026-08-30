# TaskScope 代码执行架构

> 状态：历史代码核查与已被取代的两阶段草案；当前方案以 research/15 为准

> ⚠️ 本文中的 Route Run / Execute Run、冻结工具 authority 和 Task Capsule 方案已经被用户否决，不得作为
> 实施依据。保留本文只为保存当时的代码核查和方案演化记录。
> 日期：2026-08-30
> 适用仓库：`simple_harness` Host、`simple-harness-sdk`、`simple-harness-memory-sdk`

## 1. 先说结论

`TaskScope` 是任务与执行权限边界，不是认知记忆类型。它决定当前项目、文件根目录、工具权限、任务状态和
Context Capsule，因此**Host 是唯一状态 authority**；Harness SDK 定义中立协议和可靠执行语义；Memory SDK
只消费可信 `task_scope_id` 作为证据标签、过滤条件与排序亲和度，不能自行创建、切换或绑定项目。

推荐把每个用户 Turn 内部拆成两阶段：

1. **Route 阶段**：主模型只看有界 Routing Context，只能直接回答，或调用唯一的 `context_route` 工具提出
   `TaskScopeProposal + RecallPlan`；
2. **Execute 阶段**：Host 确定性裁决后冻结 TaskScope、Project、Context 和 Tool authority，再启动正式
   ReAct Run。需要记忆时，召回结果随 frozen Context 进入正式执行。

用户仍只看到一条对话和一个连续响应。Route/Execute 是内部 Run，不是两个 UI Session。

## 2. 为什么不能在当前 Run 中途直接切 TaskScope

当前生产代码已经把项目根目录和工具物理权限冻结到 Run：

- Host 在聊天入口先通过 `ProjectBindingService.resolve_session(session_id)` 取得不可变项目绑定；
- `TaskWorkContext`、tool authority 和 Context snapshot 随 RunStart 冻结；
- SDK ReAct loop 会重放冻结的 Provider request/tool effect，依赖 Run authority 不在中途改变。

如果让模型在同一个 ReAct Run 中先调用 `context_route`，随后把 workspace 从项目 A 改成项目 B，会破坏：

- 已冻结 Provider request 和工具授权的 replay 语义；
- filesystem/shell 的物理 scope；
- 并发与恢复时“这个 effect 到底属于哪个项目”的审计结论。

更危险的是，模型可能在一个 tool batch 同时给出 `context_route` 和写文件工具；当前 ReAct batch 可以并发执行，
不能依赖调用顺序让权限 magically 生效。因此 Route 阶段必须只有路由工具，项目/任务 authority 确认后才创建
Execute Run。

## 3. 当前代码能复用什么、必须替换什么

### 可复用

- Host `TaskContextSnapshot` 已有 `task_scope_id`、objective、decisions、completed、pending、artifacts、
  blockers 和 source revisions，可演进为 Task Capsule。
- Host `_prepare_sdk_context_snapshot` 已负责预算、history/persona/memory/skill/project fragments，并生成不可变
  `PreparedSdkContextSnapshotV1`。
- Harness SDK `ReActLoop` 已冻结每次 Provider request，执行工具后自动续推理；正式 Execute 阶段无需另造 loop。
- Host/SDK 已有 Run、request、turn、provider invocation、tool effect 和 context checkpoint lineage。

### 必须替换

- 当前 `task_scope_id` 由 `(session_id, request_id, turn_id)` 每轮生成，本质是 Turn scope，不是可跨 Turn 恢复的
  TaskScope。要改为 Host 持久化的稳定 UUID。
- 当前 Project binding 绑定在 Session。一个永久 Session 无法同时承载多个项目，必须迁移**代码语义**为
  `TaskScope -> immutable ProjectBinding`；这不是旧数据迁移。
- 当前 Harness kernel 在首次 Provider 调用前自动执行 `memory.recall_for_turn()`，因此每轮都会查 Memory SDK；
  要增加 model-routed 模式，未产生 `RecallPlan` 时不得查询。
- 当前 `MemoryRecallRequest v1` 只有 query text、identity、scope 和 bounds，无法表达 TaskScope、认知类型、
  purpose/recipient、时间、实体、事件和 no-recall reason，需要版本化 v2 协议。
- 当前 Host history 以 Token 预算尽量装入旧 Session history；目标改为最近 10 个完整 causal turn group，超出部分
  只能通过五天短时域或显式 page-in 进入 Context。

## 4. 跨仓组件

### 4.1 Host：唯一业务 authority

新增或重构以下服务：

```text
PrimaryConversationService
  ensure_primary(actor_id) -> primary_conversation_id

TaskScopeStore
  list_route_candidates(conversation_id)
  get(scope_id)
  create_cas(...)
  transition_cas(...)
  bind_turn(...)

TaskScopeDecisionService
  validate(proposal, trusted_run_context)
  apply_cas(validated_proposal)
  emit_decision_record(...)

TaskCapsuleProjector
  rebuild(scope_id, source_revisions)
  get_compact_directory_entry(scope_id)
  get_full_capsule(scope_id)

RoutingContextAssembler
  build(current_query, recent_10_groups, scope_directory)

ContextContinuationCoordinator
  start_execute_run(route_receipt, recalled_fragments)

FinalContextAssembler
  freeze(task_capsule, recent_window, memory, tools, skills, attachments, budget)
```

Host 还负责 `TaskScope -> ProjectBinding` 的不可变绑定以及所有 filesystem/shell/tool authority。模型提供的
`project_hint` 只能匹配 Host 的可信 Project catalog，绝不能直接成为文件路径权限。

### 4.2 Harness SDK：中立协议与可靠执行

新增公共类型：

```text
TaskScopeAction = continue | create | switch | link | complete | reopen | standalone
TaskScopeProposalV1
TaskScopeDecisionV1
TaskScopeBindingReceiptV1

CognitiveMemoryType = episodic | semantic | procedural | prospective | raw_evidence
RecallPlanV2
RecallContextV2
RecallDecisionV2
ContextFragmentV1
ContextAssemblyDecisionV1

RouteRunInput / RouteRunResult
```

新增一个很薄的 `RouteDriver`：

- 固定只暴露 `context_route`；
- 冻结并审计 Route Provider request/response；
- 只接受两种终态：`direct_response` 或一个合法 route tool call；
- route tool 不得与其他 tool 并批；
- route proposal 只是一项不可信提案，不直接改变权限；
- Host 返回 binding receipt 后，`ContextContinuationCoordinator` 创建关联的 Execute Run，或者输出
  `needs_user_confirmation`。

现有 `ReActLoop` 继续拥有 Execute Run。不要把 TaskScope 业务状态机塞进通用 ReAct loop。

### 4.3 Memory SDK：证据、短时域和长期认知召回

新增能力：

```text
ingest_committed_evidence(CommittedTurnV2)
recall(RecallContextV2, RecallPlanV2) -> TypedRecallResultV2
record_recall_decision(RecallDecisionV2)
```

Memory SDK 校验 trusted actor/scope、task_scope_id 格式、认知类型、状态、隐私、时间、预算和 evidence refs；
它不校验 filesystem 权限，也不能创建 TaskScope 或 Project binding。

## 5. Host 持久化模型

原型从空库初始化，建议在 Host `state.db` 增加：

```text
primary_conversations
  actor_id PK
  conversation_id UNIQUE
  created_at

task_scopes
  task_scope_id PK
  conversation_id FK
  goal
  status: active | suspended | completed
  project_binding_id nullable
  created_turn_id
  last_active_turn_id
  revision
  created_at / updated_at

conversation_scope_cursor
  conversation_id PK
  active_task_scope_id nullable
  revision
  decision_id

turn_task_scope_links
  turn_id
  task_scope_id
  relation: primary | related | evidence
  decision_id
  UNIQUE(turn_id, task_scope_id, relation)

task_scope_capsules
  task_scope_id
  capsule_revision
  payload_json
  payload_hash
  source_revision_set_hash
  status: active | stale | superseded

task_scope_decisions
  decision_id PK
  route_run_id
  provider_invocation_id
  proposal_json / proposal_hash
  action
  previous_scope_id / decided_scope_id
  validation_status / reason_codes
  resulting_revision
  created_at
```

所有 decision 表 append-only；scope/cursor/capsule 用 CAS 更新。`standalone` Turn 不改变 active cursor，也不污染
任何长期 Task Capsule。

Memory DB 只保存可信外键/标签：

```text
evidence_events(..., host_turn_ref, content_hash, task_scope_id nullable, ...)
short_horizon_chunks(..., evidence_refs, task_scope_ids, expires_from_index_at, ...)
short_horizon_vectors(chunk_id, generation_id, embedding, ...)
short_horizon_fts(...)
recall_decisions(...)
```

五天到期只让 chunk 退出派生查询资格；`evidence_events` 永久保留。

## 6. `context_route` 工具协议

模型只能提交提案：

```json
{
  "scope": {
    "action": "continue|create|switch|link|complete|reopen|standalone",
    "target_scope_id": "optional",
    "goal": "required for create",
    "project_hint": "optional trusted-catalog hint",
    "confidence": 0.0,
    "evidence_turn_ids": ["..."]
  },
  "recall": {
    "required": true,
    "types": ["episodic", "procedural"],
    "query": "发布失败及解决过程",
    "time_range": {"kind": "last_5_days"},
    "entities": ["project-x"],
    "reason_codes": ["PAST_EVENT_DEPENDENCY"]
  }
}
```

确定性验证至少包括：

- `continue/switch/reopen` 的 target 必须出现在当前 actor 的可信候选集中；
- `create` 必须有 goal，project hint 必须解析成 Host catalog 中的 exact Project ID；
- `standalone` 不得同时申请 project-bound state-changing tool；
- evidence turn 必须属于当前唯一主对话且对当前 actor 可见；
- recall types、time range、recipient/purpose、item/byte/token/deadline 均过白名单；
- 同一个 route call ID 重放只能得到同一 receipt；不同 payload 复用 ID 必须 conflict；
- 低置信本身不自动失败，只有“歧义会改变项目、文件、权限、外部动作或答案事实”时返回确认要求。

## 7. 每轮精确执行顺序

```text
1. UI -> ChatIngressService(query)
2. PrimaryConversationService.ensure_primary(actor)
3. SessionDB 原子写入 user Turn + root_run reservation
4. RecentCausalWindowPlanner 读取最近 10 个完整 turn group
5. TaskScopeStore 返回 active + 最近候选的 compact directory
6. RoutingContextAssembler 冻结 RoutingContextSnapshot
7. Harness RouteDriver 调主模型

   7A. 模型直接回答
       - 协议约定只用于与 TaskScope 无关的 self-contained/standalone 回答
       - 不调用 Memory SDK
       - 记录 RecallDecision(outcome=no_recall)
       - 原子提交 assistant Turn、provider evidence、decision
       - 结束（只有一次模型调用）

   7B. 模型调用 context_route
       - SDK 冻结 tool proposal
       - Host TaskScopeDecisionService 校验

       7B-1. 歧义影响正确性/权限
             -> 返回 needs_user_confirmation
             -> 主模型向用户问一个具体问题
             -> 不创建/切换 Scope，不召回，不执行动作

       7B-2. 决策有效
             -> CAS 创建/切换/恢复/关联 TaskScope
             -> 冻结 TaskScopeBindingReceipt + ProjectBinding
             -> 若 RecallPlan.required=true，调用 Memory SDK 类型化召回
             -> Host FinalContextAssembler 组装并冻结 ExecuteContextSnapshot
             -> ContextContinuationCoordinator 启动关联 Execute Run
             -> ReActLoop 正常调用模型、执行工具、续推理直至 terminal

8. Host 原子提交 assistant/tool/run/provider/decision evidence
9. CommittedTurnV2 异步进入 Memory SDK
10. Memory worker 生成 MemoryMutationPlan，确定性写入短时域和长期认知状态
11. TaskCapsuleProjector 根据 Host 任务事实异步重建 capsule
```

必须承认一个能力边界：代码可以确保 Route 阶段没有项目写权限、不能调用其他 effect tool，但无法用确定性
规则证明某段自然语言回答“真的不需要记忆”。模型直接返回文本会被解释为它提出 `no_recall + standalone`；
是否判断正确要靠冻结语料、真实主模型多轮测试、用户纠正率和后续审计评估，不能伪装成规则可 100% 保证。

## 8. 四个具体例子

### “今天天气怎么样？”

无任务依赖。Route Run 直接回答，`no_recall + standalone`，一次模型调用，不改变 active TaskScope。

### “继续刚才 memory-sdk 的计划”

模型调用 `context_route(action=continue,target_scope_id=...)`；Host 校验候选、返回 capsule，并按计划请求 Episode、
Procedure 或短时域片段；Execute Run 续推理。

### “帮我修另一个项目的登录问题”

模型调用 `create` 并给出 project hint。若唯一匹配，Host 创建带不可变 Project binding 的 TaskScope，再启动
Execute Run；若有两个相似项目，返回 `needs_user_confirmation`，模型询问用户。

### “顺便问一下 Python 的 list 怎么排序？”

模型直接回答 standalone；不切走当前项目 Scope，也不把该问答写进当前 Task Capsule。原始 Turn 仍永久保存，
五天内可从短时域检索。

## 9. 审计记录

每个用户 Turn 至少能由 `root_run_id` 导出：

```text
raw user evidence
-> RoutingContextSnapshot hash
-> Route provider invocation evidence
-> TaskScopeProposal（若有）
-> TaskScopeDecision + reason codes
-> RecallPlan / RecallDecision（含 no_recall）
-> Memory query/result/filter lineage（若有）
-> TaskScopeBindingReceipt / ProjectBinding snapshot（若有）
-> ExecuteContextSnapshot hash（若有）
-> Execute provider/tool invocation lineage（若有）
-> final assistant evidence
-> post-turn MemoryMutationPlan decisions
```

不保存隐藏思维链；保存模型实际可审查的结构化输出、工具调用、输入输出 hash、版本、Token、费用、延迟和代码
裁决结果。

## 10. 方案代价

- self-contained/no-recall：一次模型调用，和当前理想成本一致；
- continue/create/switch/recall：Route 调用 + Execute 续推理，至少两次 Provider invocation；
- 优点：不会在判断任务之前把错误项目、旧记忆和全工具权限交给模型；Run authority 可冻结、可恢复、可审计；
- 代价：需要新增 RouteDriver、TaskScope Store/状态机、两阶段 Run 关联和协议 v2，而不是只改一个向量查询函数。
