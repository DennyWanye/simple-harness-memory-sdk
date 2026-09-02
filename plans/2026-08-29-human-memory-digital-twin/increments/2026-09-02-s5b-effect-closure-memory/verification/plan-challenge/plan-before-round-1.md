<!-- plan-status: draft (待 challenge 与用户批准) -->

# Plan：S5b — 工作区 effect gate、TaskScope 语义收口与 Host↔Memory 异步面

## 矛盾分析（承 acceptance）

- 一句话：主模型替用户真干了活之后，系统能否把这一轮真实发生的事确定性地沉淀为任务档案语义状态与长期记忆。
- 最小验证动作 = 价值验证里程碑（Task 4 末）：真实 provider，"把 README 里的版本号改成 1.2.0" → `write_file`
  经 envelope 重验 → `host.file` 脏标记 → `task_scope_update` mutate（漏调则兜底）→ 终态同事务 Memory outbox →
  post-turn analysis 产出 accepted `MemoryMutationPlan`；一个 Run、一次 attempt、零重复 Provider 调用。
- 主要方面：终态门（三水位 + 同事务 outbox + 兜底收口）在真实 Run 上跑通并可重放。
- 里程碑之前只排它的直接依赖：Task 0（oracle/迁移设计）→ Task 1（effect gate 最小闭环，让 write_file 走 envelope）→
  Task 2（客观事件 + 脏标记）→ Task 3（task_scope_update + 终态门 + 兜底 invoker）→ Task 4（outbox + analysis executor）。
  Memory 0.6.1（物化+属主注册）、Prospective、即时操作、cutover 与验收矩阵全部排在里程碑之后。

## 现状调查结论（2026-09-02 三路并行调查，结论已核对 file:line；全文见同目录 `notes-investigation-task{5,6,7}.md`）

1. **effect gate 是"启动时查一次"**：`ProductTaskExecutionAuthority()` 在 `main.py:8567` 无 `root_resolver`；生产 catalog
   零 PROJECT_EFFECT 工具（`tool_authority.py:60-64` 只覆盖 `context_route`），SDK 的 project-effect 校验链
   （`react_loop.py:164-178`）在生产是死代码；`verify_task_execution_envelope`（`workspace_bindings.py:1168`）零生产调用；
   物理执行前卡点 `ProductEffectExecutor.execute`（`tools.py:344-357`）只做 `assert_workspace_current` + foreground admission，
   不看 envelope/revision/inode；Auto 从不到达 effect 层（`turn_preparer.py:989-1040` 只豁免 plan confirmation）。
2. **收口链缺席**：`TaskEventRecorder`（`store.py:650`）零生产调用；`task_scope_events` 只有 `run_terminal` 一种 Harness 证据
   （`foreground_runtime.py:1233-1260`），水位在 seq=1 平凡满足；无 dirty flags；`task_scope_update` 不是工具、
   `task_scope_mutation.py` 不存在；唯一 mutation 入口 `human_memory_service.mutate_task_scope`（:506-600）永不产 `no_mutation`；
   Host terminal 事实 = `foreground_queue.record_sdk_terminal`（:1853-1990，单 `BEGIN…commit`，有 `terminal.before_commit` 故障 seam）。
3. **SDK 冻结面**：`TaskScopeMutationPlan`（`task_scope_protocol.py:261-312`，含 `no_mutation`）与 `ExecutionEvidence` DTO 完整；
   **无** outbox/reader/watermark/closure hook；ROUTED_TASK 终答处（`react_loop.py:466-494`）无 Host 钩子；terminal Run 拒绝
   continuation（`kernel.py:1166-1169`）。⇒ closure 只能 Host 建：主路径经 `prepare_snapshot` 注入收口要求，兜底经 Host 独立调用。
4. **Memory 异步面**：`MemoryAnalysisExecutorPort`/`DeliveryAuthorityPort` 是 Harness 类型（`evidence_protocol.py:2606/2612`），
   Host 零实现；`DurableMemoryJobRunner`（memory `core/jobs.py:393-575`）ctor 需 `(repository=manager.backend, executor, delivery_authority,
   config(全字段必填), worker_id, now)`；repository 状态机 `handed_off→result_committed→audit_pending→applied|failed`
   （`schema_v5.py:377/398`）；摄入入口 `ingest_committed_evidence`（`sqlite_v5.py:504`，同事务写 job + outbox）**生产零调用**；
   `read_outbox`/`read_occurrence_inbox` 只读（consumer 永不 claim/settle）；Prospective 注册/失效 outbox（`sqlite_v5.py:9185-9245`）
   无 Host 消费者；`build_human_memory_v7` 只传 embedder（`human_memory_v7.py:71`）；`occurrence_presented`(v45) 缺 claim/ack 与游标。
5. **Host 既有先例可复用**：`ProductProviderAdapter`（`provider.py:476-571`）= Run 级不可变 provider/model/config/price 快照，
   `main.py:7526-7567` 由 durable `SdkRunBindingV1`（`foreground_run_sdk_bindings` v41）重建；`execution_provider_invocations`
   （`workflows/store/schema.py:2327`，`request_hash+attempt_ordinal`，claimed/completed/failed/unknown）+
   `ProviderInvocationCoordinator`（`execution/provider_invocations.py:331`）= 幂等 attempt 账本样板；`ReminderScheduler`
   （`companion/reminders.py:574-853`）= claim/lease/双检/settle 样板；`ExecutionEvidenceIngress`（`evidence_ingress.py:53-224`）
   = source_event_id 幂等 + 连续水位；`_CONFIRM_ONLY`（`effect_policy.py:22-32`）+ `tool_executor.py:557-612/894-911` = 高风险审批门。
6. **即时操作**：`tools/memory_tools.py` 全是 `memory_sdk_unavailable` stub；Host 无 suppression 流；SDK `MemoryManager.suppress`
   （`manager.py:162`）就绪。
7. **冻结 oracle**：TC-HM-09 rev4 步骤 3–6（effect gate）、TC-HM-11 rev5 步骤 5（closure）、TC-HM-04 rev3 步骤 1/4（Prospective）、
   TC-HM-07 rev2 步骤 1–3（forget）、TC-HM-08 rev4 步骤 3（载荷变异）；fault-matrix lanes `foreground-fifo-closure` /
   `memory-mutation-plan` / `prospective-occurrence` / `taskscope-init-binding` 的 runner 文件 `backend/tests/faults/*` **不存在**
   （S4/S5a 均未兑现，本增量兑现前三条并按 runner_contract 输出 root_run_id + before/after hash）；V0 SPIKE-CROSS-DB-TRIGGER /
   SPIKE-RUNTIME-BRIDGE 协议（`spikes/manifests/spike-manifest.json`）冻结 kill 点与 required 断言。
8. **基线**：Host `main`@`ec1cb944` 6282 passed / 7 既有红；Memory `main`@`fcf1682` 1071 passed（`baseline.md`）。

## 方案与权衡（含最佳实践适配分析，反对本本主义）

| 主题 | 业界做法 | 本项目条件 | 取舍 |
|---|---|---|---|
| 终态→Memory 摄入 | Transactional outbox（业务事实与 outbox 行同事务，worker 至少一次投递，消费端幂等） | Host state.db 与 Memory DB 是两个 SQLite；`record_sdk_terminal` 已是单事务且有故障 seam；Memory `ingest_committed_evidence` 按 source_ref 幂等 | **照用**：outbox 行写进 `record_sdk_terminal` 同一事务；worker lease + 有界重试 + dead-letter；不引消息中间件 |
| 主模型 post-turn 调用幂等 | Stripe 式 idempotency key + 请求指纹；Temporal activity 的 "scheduled/started/completed/unknown" | Host 已有 `execution_provider_invocations` 同形账本；SDK Run 绑定给出不可变 provider/model/config | **改造复用**：新 `post_turn_invocation_attempts` 镜像既有 taxonomy，`UNIQUE(request_hash, attempt)`；不复用 workflows 表本身（那是 workflow Run 域） |
| closure 由同一模型补 | Agent 框架里常见 "post-hoc self-report" 二次调用 | SDK 冻结无钩子；program 要求同一 Run | **主路径 in-Run**（snapshot 注入收口要求 + 暴露 `task_scope_update`），**兜底独立调用**（同 Run 绑定），pending 可交付不扣押（acceptance D1） |
| 唯一 scheduler | 单 writer + lease 的 durable timer（cron-in-DB） | `ReminderScheduler` 已是该形态但在 companion DB | **衍生不复用实例**：state.db 新表 + 同设计（claim/lease/双检/settle），避免跨库事务（acceptance D4） |
| 事件语义判定 | 关键词/正则/小模型分类 | program 明令禁止 | **确定性映射表**：event_kind → material/trivial（`host.file`/`host.test`/`harness.tool_invocation(project_effect)` = material；`host.turn`/`harness.provider_invocation`/`context_snapshot`/`route_decision` = trivial） |
| effect 重验 | Capability token + per-call re-validation（zanzibar 风格 "check at use"） | S4 store 已提供 `verify_task_execution_envelope` + inode 重验 | **照用**：在 `ProductEffectExecutor.execute` 前调用，加 scope lifecycle 与 `_CONFIRM_ONLY` 不变断言 |

放弃的备选：① 改 SDK 加 closure hook（冻结，不可）；② 第二个 SDK Run 做 closure（破坏 1 用户请求 = 1 Run，FIFO 语义复杂）；
③ 复用 companion `ReminderScheduler` 实例跨库投影（跨库无事务）；④ 用 `commit_run_outcome.terminal_commit_extensions`
（那是 workflow runs 库的 seam，不是 Host foreground terminal 事实所在）。

## 关键假设与实践证据

| ID | 假设 | 验证方式（spike） | 实际输出 | 结论 |
|---|---|---|---|---|
| A1 | Host 可在 SDK Run 之外用 `ProductProviderAdapter`（同 registry Protocol）对真实 provider 做一次带 `task_scope_update` 工具的独立调用，并拿到 TaskScopeMutationPlan 形状的结构化 tool call | `scratchpad/spike-a1/spike_a1.py`（真实 `gpt-5.6-luna`，key 不打印） | 两次运行均 `finish=tool_calls`，1 个 `task_scope_update` 调用，`outcome=mutate`，`base_revision=7`，6 个 operation 全部只引用允许的 `ev-file-0091/ev-test-0092`；usage 590+559 / 4902+403 tokens，16.6–33.9s；`A1_VERDICT: PASS` | **PASS**；兜底 closure 与 analysis executor 共用该调用路径 |
| A2 | exact Memory 0.6.0 wheel 上，Host 提供 delivery/prospective/action authority 构建 v7，`ingest_committed_evidence` → `DurableMemoryJobRunner.run_once`（Host executor）→ applied → `read_outbox` 出现 prospective registration → 第二次 run_once idle → `apply_prospective_signal` 产生 inbox occurrence | `spikes/a2/spike_a2.py`（exact wheel，fresh sqlite） | 步骤 1/2/3/5/6 PASS：builder 接受 Host authority；ingest 产 job+outbox；`run_once`=APPLIED（`job_attempts` provider_handoff→result_committed→application_staged→mutation_audit_committed→applied，executor 1 次，`verify_analysis_delivery` 1 次）；第二次 IDLE；`apply_prospective_signal` 产生 1 条 `matched/time_due/triggered` inbox。**步骤 4a FAIL**：APPLIED 后 `cognitive_memory_heads=0`、无 prospective registration outbox——0.6.0 runner 只写 `accepted_analysis_plans`/decision/audit，**不物化记忆**；Host 额外调 `apply_memory_mutation_plan(principal, scope, plan)` 后才出现 registration outbox 且 `cognitive_memory_revisions.plan_hash == accepted_analysis_plans.plan_hash`。另：Host principal 行形状（deployment/household）在首次 caller-principal 写之前被 `read_outbox/read_occurrence_inbox` 拒绝（`short_horizon_principal_rejected`）= S5a fail-open 的根因；delivery authority 必须与 builder 绑定的是同一对象；`MemoryJobWorkerConfig` 15 字段无默认；plan.turn_id 必须 = `_stable_id("analysis-batch-turn", batch_id)` | **部分成立**：executor/runner/delivery 契约可用；**accepted plan 物化缺失属 Memory 0.6.0 上游缺口**（S2 Task 5 文本「apply 在单事务内、Memory 只 CAS apply 一次」未兑现）→ 本 plan Task 5 在 Memory 0.6.1 内修（repository 在 finalize 阶段以 application capability 物化），Host 不做 caller-principal 兜底；principal 形状 → 同版本属主注册 API |
| A3 | SDK 0.7.1 对 Host 覆盖为 PROJECT_EFFECT/required 的工具：standalone 路由拒绝、ROUTED_TASK 下 per-call `issue_envelope`（带 root_resolver）产出六元组 envelope 并到达 Host handler、模型伪造 authority 字段被拒、无 resolver fail-closed | `spikes/a3/spike_a3_test.py`（真 ReActLoop + 真三 authority + v45 ledger + S4 binding store，7 passed） | (a′) UNROUTED / (a″) 同批 route+write → `ROUTE_BARRIER_NOT_OBSERVED` rejected ToolResult，handler 0 次；(b) ROUTED_TASK：`issue_envelope` per call，envelope 六元组 = S4 binding head，`context.task_execution_envelope` 到达 handler，真 `verify_task_execution_envelope` 接受；(c) 模型传 `task_execution_envelope`/`binding_set_revision` → `MODEL_AUTHORITY_FIELD_FORBIDDEN`；(d) `root_resolver=None` → `sdk_task_execution_root_authority_unavailable` **异常逃出 ReActLoop**（checkpoint 停在 `tool_batch_reserved`）。**(a) 字面不成立**：`routed_standalone` 下 SDK preflight 不触发 barrier，直接进 `issue_envelope`，Host 抛 `sdk_task_execution_route_authority_missing` 同样逃出 loop——冻结 SDK 没有让模型看到「standalone 不许项目 effect」的 rejection 路径。policy 三字段进 capability/catalog fingerprint | **成立（含一条设计约束）**：PROJECT_EFFECT 工具必须**按路由状态控制暴露**（只在 ROUTED_TASK 暴露），standalone 下模型看不到写工具；Host authority 抛错保留为 defense-in-depth 的 Run fault（fail-closed，不半状态）；跨部署 fingerprint 变化 → in-flight Run stable fail（cutover 注记） |
| A4 | Host 终态事实 `record_sdk_terminal` 是单事务且可在同事务插入 outbox 行 | 静态核对 `foreground_queue.py:1853-1990` | 单 `BEGIN`…`db.commit()`，异常 rollback，已有 `self._fault("terminal.before_commit")` seam；无扩展钩子需新增 | **成立**（实现时加 `terminal_commit_hooks` 参数，故障 lane 复用同 seam） |
| A5 | Host 经注入 resolver 调 `apply_prospective_signal` 可产生 matched occurrence 并被 S5a reconcile 门读到 | S5a 既有生产路径测试 `tests/sdk_adapters/test_no_recall_gate.py:373-386` | S5a receipt 已证（no_recall 被拒 + summary 进 snapshot） | **成立**（沿用） |

## 关联验收标准

S5B-AC-1（决定性）← Task 2/3；S5B-AC-2（决定性）← Task 3（invoker）/4/5（物化）；S5B-AC-3 ← Task 1；S5B-AC-4 ← Task 5/6；
S5B-AC-5 ← Task 7；S5B-AC-6 ← Task 5/8；全部 AC 的验收矩阵 ← Task 9。

## 文件影响清单

| 文件 | 职责 | 现状 | 本次改动 |
|---|---|---|---|
| `backend/deskpet/memory/migrations/038_effect_closure_memory_v46.sql`（新） | v46 durable 表 | 无 | `task_scope_closure_receipts`、`harness_evidence_outbox`、`memory_ingestion_outbox`（+`_evidence_links`）、`post_turn_invocation_attempts`（+`_events`）、`prospective_scheduler_registrations`、`prospective_outbox_cursor`、`prospective_occurrences`、`host_pre_admission_audit`；全部 append-only 触发器；`occurrence_presented` 不改 schema |
| `backend/deskpet/memory/migrator.py` | 迁移注册 | v45 target | v46 target + 恢复表注册 |
| `backend/deskpet/sdk_adapters/tool_authority.py` | 工具执行策略覆盖表 | 只有 `context_route` | 冻结 PROJECT_EFFECT 清单（acceptance AC-3①）→ `(project_effect, required, required)` |
| `backend/deskpet/sdk_adapters/task_execution.py` | envelope 签发 | `root_resolver=None` | `BindingRootResolver`：由 receipt 的 exact binding receipt 解析恰一 root；零/多 root → `sdk_task_execution_root_authority_ambiguous|missing` |
| `backend/deskpet/sdk_adapters/tools.py` | 物理 effect executor | `assert_workspace_current` + admission | `ProductEffectExecutor.execute` 前新增 `EffectGate.verify(context)`：scope lifecycle、`verify_task_execution_envelope`、inode 重验、`_CONFIRM_ONLY` 不变断言；执行后写 `host.file`/`host.test` 客观事件（Task 2） |
| `backend/deskpet/sdk_adapters/effect_gate.py`（新） | per-effect 重验 + 客观事件 recorder 接线 | 无 | 上述 gate + `ObjectiveEventRecorder`（工具→事件映射表，确定性 material/trivial 分类） |
| `backend/deskpet/execution/harness_evidence.py`（新） | Host 侧 source-ledger outbox | 只有 run_terminal | 由 provider adapter / tool executor / context authority / route ledger 各处写 `harness_evidence_outbox`（per-run source_sequence），worker 经 `ExecutionEvidenceIngress.ingest` 导入并推进水位；`run_terminal` 仍最后 |
| `backend/deskpet/sdk_adapters/task_scope_mutation.py`（新） | `task_scope_update` 工具 handler | 无 | strict schema → `TaskScopeMutationPlan`；Host 校验 evidence refs 属 scope、base_revision、状态迁移表、幂等 → `apply_mutation_plan` → closure receipt |
| `backend/deskpet/execution/semantic_closure.py`（新） | 脏标记计算 + 三水位终态门 + 兜底 | 无 | `dirty_state(run)`（events since last closure watermark × 映射表）；`TerminalClosureGate.authorize(run)`；`ClosureFallback`（invoker 调用 → plan 校验 → receipt / pending） |
| `backend/deskpet/sdk_adapters/post_turn_invoker.py`（新） | Run-bound 独立主模型调用 + 五态 attempt 账本 | 无（先例 provider_invocations.py） | `RunBoundInvoker.invoke(purpose, request_hash, build_request)`：查 `post_turn_invocation_attempts`，reserved→handed_off→succeeded/failed/unknown，unknown 三分类，同 request_hash 已成功直接返回 |
| `backend/deskpet/memory/analysis_executor.py`（新） | `MemoryAnalysisExecutorPort` + `DeliveryAuthorityPort` Host 实装 | 无 | 由 job→originating run 的 `foreground_run_sdk_bindings` 重建 adapter；经 invoker 调用；结果封装为 `MemoryAnalysisResultEnvelope`；delivery authority 从同一 attempt store 校验 |
| `backend/deskpet/memory/memory_ingestion_outbox.py`（新） | 终态→Memory 摄入 worker | 无（`product_outbox.py` 是 legacy v30） | claim/lease → `ingest_committed_evidence` → receipt 回写 Host 事件；失败有界重试→dead-letter；raw 不删 |
| `backend/deskpet/execution/foreground_queue.py` | Host terminal 事实 | 单事务 | `record_sdk_terminal(..., terminal_commit_hooks)`：同事务写 closure watermark 检查、evidence links、`memory_ingestion_outbox` 行；新增 `foreground_terminal_closure_pending` 门 |
| `backend/deskpet/execution/foreground_runtime.py` / `harness/kernel_terminal.py` | 终态观察与交付 | 无 closure 检查 | 终态前调用 `TerminalClosureGate`；pending 时暂存终答→兜底→交付（带标记） |
| `backend/deskpet/sdk_adapters/context_authority.py` | per-turn snapshot | 无收口注入 | dirty/pending 时注入 protected "closure required" 指令 + 暴露 `task_scope_update` |
| `backend/deskpet/memory/human_memory_v7.py` | v7 接线 | 只传 embedder；fail-open 兜底 | 注入 analysis delivery / prospective signal / memory action authority；Task 7 后删 fail-open |
| `backend/deskpet/memory/prospective_scheduler.py`（新） | 唯一 Prospective scheduler | 无 | 消费 `read_outbox` 注册/失效 → durable registrations；tick → `apply_prospective_signal` → `prospective_occurrences` 生命周期；写 `occurrence_presented` |
| `backend/deskpet/tools/memory_tools.py` + `tool_catalog/providers.py` | remember/correct/forget | stub | 真实 handler：write/correct → 高优先 job；forget → 同步 suppress |
| `backend/deskpet/memory/pre_admission_audit.py`（新） | Host durable pre-admission audit | `BLOCKED_UNTIL_S5` | Harness 拒绝的非法载荷写 `host_pre_admission_audit` |
| `backend/main.py` | composition | 三 authority 已注册 | 注册 root_resolver/effect gate/closure gate/invoker/analysis executor/outbox worker/scheduler；缺件 startup fail；epoch 门 v46 |
| memory-sdk `core/manager.py`, `backends/sqlite_v5.py`, `core/port.py` | analysis 物化 + 属主注册 | runner APPLIED 不物化（spike A2）；首次 caller 写才修正 principal 形状 | `prepare_analysis_application` accepted 分支同事务物化 plan（application capability）；新公开 API `register_principal_owner(principal, scope)`（幂等）；0.6.1 wheel/manifest；Host pin 更新 |
| `backend/tests/faults/test_{foreground_fifo_closure,memory_mutation_plan,prospective_occurrence,taskscope_init_binding}.py`（新） | fault-matrix runner | 不存在 | 按 lane seams 实装，输出 root_run_id + before/after hash，非零退出 |
| `backend/tests/sdk_adapters/test_s5b_*.py`、`testcase/human-memory-program/s5b-*-verification-spec.json` | black-box 用例与 oracle | 无 | Task 0 冻结 |

## Complexity inventory

| 复杂度表面 | 新增 | 理由 / AC 或 risk 绑定 |
|---|:---:|---|
| 新依赖 | 否 | 全部 SQLite/httpx/既有 SDK |
| 新公共 API | 是（memory-sdk 1 个：属主注册）| S5B-AC-6③；消除 fail-open（FAIL-PRIVACY-STALE 相邻） |
| 新持久化状态 | 是（v46 九张表）| AC-1/2/4/6；每张绑定 assurance ASSET-RAW-EVIDENCE / PROVIDER-IDEMPOTENCY / TASKSCOPE-CANONICAL-STATE |
| 新工具 | 是（`task_scope_update`；memory_* 由 stub 转真） | AC-1②、AC-5 |
| 新后台任务 | 是（ingestion outbox worker、analysis job runner、prospective scheduler、harness evidence ingest）| AC-2/4；均无 Agent effect 权限（ASSET-FOREGROUND-RUN-ORDER）|
| 新抽象层 | `RunBoundInvoker`（closure 兜底 + analysis + remember 三消费者共用）| 避免三份 provider 调用/幂等账本（FAIL-DUPLICATE-PROVIDER-CALL）|
| 可复用 | `ProductProviderAdapter`、`ExecutionEvidenceIngress`、`CanonicalTaskScopeStore.apply_mutation_plan`、`WorkspaceBindingAuthorityStore.verify_*`、`ReminderScheduler` 设计、`_CONFIRM_ONLY` | — |
| 删除/退役 | `human_memory_v7.py` fail-open 分支；`memory_tools.py` stub；`BLOCKED_UNTIL_S5` 标记 | AC-6 |

## 任务清单（最短价值路径优先；oracle 先于实现贯穿）

### Task 0 — oracle 定稿、v46 设计冻结、release-unit 体检 [全 AC]
- 改动：`testcase/human-memory-program/s5b-effect-closure-memory-verification-spec.json` + reuse-report（S5B-S1…S7/REG → TC-HM-04/07/08/09/11 rev 冻结，impact_paths **仓库相对路径**，evidence contract，oracle pins）；本目录 `verification-spec.json`；黑盒用例骨架 `backend/tests/sdk_adapters/test_s5b_acceptance_matrix.py`（先写断言，`xfail(strict)` 直到实现）。
- v46 逻辑表设计冻结（写 SQL 前）：列/唯一键/append-only 触发器/CHECK；unknown-call 三分类枚举；material/trivial 映射表常量；PROJECT_EFFECT 清单常量。
- `check-release-unit`（MUST AC=6、Task=10、高风险=3）；`phase-start`。
- 验证：spec 通过 `compile-manifest`；用例骨架被 pytest 收集且 xfail。
- 依赖：无。

### Task 1 — effect gate 最小闭环 [S5B-AC-3，次要但里程碑直接依赖]
- 改动：`tool_authority.py`（清单）、`task_execution.py`（`BindingRootResolver`）、`effect_gate.py`（新）、`tools.py`（executor 前置 gate）、`main.py:8567`（注入 resolver + gate）。
- 现状：见调查 1。SDK 已保证 per-call `issue_envelope`、身份回声、同批 barrier、模型 authority 字段拒绝（spike A3 待证）。
- 修改方式：① 清单常量 `PROJECT_EFFECT_TOOL_NAMES` 进覆盖表；② resolver：`store.exact_receipt(receipt.binding_set_receipt_id)` → roots 恰一 → `(root_id, root_identity_hash)`，否则抛可审计 reason；③ `EffectGate.verify(context)`：envelope 非空且 run/call 匹配 → `store.verify_task_execution_envelope(envelope, route_receipt)`（含 inode 重验）→ scope `lifecycle in {active, open}`（`CanonicalTaskScopeStore.head`）→ 断言 `effect_policy` 分类不受 Auto 影响；失败 → `ToolResult.rejected(reason)`，不落 effect 副作用；④ 失败后同 Run 持续拒绝直到新 route receipt（以 `route_receipt_id` 为键的 durable reject 记录）；⑤ **暴露随路由**（spike A3 约束）：`ProductRunContextAuthority.exposure_resolver` 在 route_state ≠ ROUTED_TASK 时不暴露 PROJECT_EFFECT 工具（复用 S4 `projectless` 投影），使模型在 standalone 下看不到写工具；Host authority 抛 `route_authority_missing/root_authority_unavailable` 保留为 Run fault（`foreground_runtime` 记 FAILED，不半状态）。
- 验证（oracle 先行）：TC-HM-09 步骤 3–6 自动化：Manual/Auto 追加后逐 root canary；六类拒绝；运行中 `os.rename` 根目录 → inode 漂移拒绝；模型传 `binding_set_revision` → `MODEL_AUTHORITY_FIELD_FORBIDDEN`；同批 `context_route + write_file` → barrier；`direct_standalone` 路由下 snapshot 的 tools 集不含任何 PROJECT_EFFECT 工具（exhaustiveness 断言）；模型仍调用未暴露写工具 → SDK unknown-tool rejection 而非 Run fault；Auto 下 `run_shell rm -rf` 类 DESTRUCTIVE 仍要求 grant；`root_resolver` 缺 → startup fail。
- 依赖：Task 0；spike A3。

### Task 2 — 客观事件、脏标记与 Harness 证据导入 [S5B-AC-1①]
- 改动：`effect_gate.py`（`ObjectiveEventRecorder`）、`harness_evidence.py`（新）、`provider.py`/`context_authority.py`/`context_route.py`（各自写 outbox 行）、`semantic_closure.py`（`dirty_state`）、v46 表。
- 现状：调查 2；`append_host_event` 只收 `host.turn/file/test`，source_event_id 幂等；`ExecutionEvidenceIngress` 要求连续 seq 且 `run_terminal` 最后。
- 修改方式：① 物理 executor 成功/失败后按工具→事件映射（write/edit/move/organize/doc/excel/ppt/pdf/download → `host.file`；run_shell/process_start 的测试类命令由 **确定性规则**：工具名 + 退出码 + 注册的 test runner 白名单 → `host.test`，否则 `host.file`）写事件，source_event_id = `effect:{effect_id}`；② `harness_evidence_outbox`：provider adapter 完成 → `provider_invocation`；tool 结果提交 → `tool_invocation`；snapshot receipt → `context_snapshot`；route decision → `route_decision`；每行 per-run 单调 `source_sequence`（从 v45/v41 已有序数派生，不新造时钟）；ingest worker 顺序导入并推进 `task_scope_run_watermarks`；`run_terminal` 由既有 observer 以 `next_sequence` 最后写；③ `dirty_state(run)` = 自上次 closure receipt 的 `event_watermark` 之后 material 事件集合（映射表常量）。
- 验证：事件顺序/幂等/hash 冲突（复用 test_canonical_archive 样式）；4 类 Harness 证据水位推进到 terminal；乱序/缺口 → `TerminalWatermarkPending`；映射表 exhaustiveness 断言（每个 PROJECT_EFFECT 工具有映射）。
- 依赖：Task 1。

### Task 3 — `task_scope_update`、三水位终态门与同主模型兜底 [S5B-AC-1②③④]
- 改动：`task_scope_mutation.py`（新）、`semantic_closure.py`（gate + fallback）、`post_turn_invoker.py`（新）、`foreground_queue.py`（`record_sdk_terminal` 钩子 + `foreground_terminal_closure_pending`）、`foreground_runtime.py`/`kernel_terminal.py`（暂存终答）、`context_authority.py`（snapshot 注入）、`tool_catalog/providers.py` + manifest（注册工具，direct kernel，`PROJECTLESS_SAFE_TOOL_NAMES` 加入）。
- 现状：调查 2/3；`apply_mutation_plan` 已做 plan_id 幂等 + CAS + refs 校验，**不校验状态迁移**；SDK 无钩子。
- 修改方式：① handler：strict schema（复用 SDK `TaskScopeMutationPlan.to_json` 形状，模型只填 outcome/base_revision/operations/closure_reason/evidence_refs/idempotency_key，其余由 Host 从 envelope/route receipt 填）→ 状态迁移表（`task_scope_status` 合法边）→ refs 必须 ∈ 本 scope 事件/证据 → `apply_mutation_plan` → `task_scope_closure_receipts(run, watermark, outcome, plan_id)`；② snapshot 注入：`prepare_snapshot` 当 `dirty_state` 非空或存在 pending receipt 时，在 protected 分区加收口指令并把 `task_scope_update` 放入暴露集；③ 终态门：`record_sdk_terminal` 钩子内查 closure receipt 覆盖当前 watermark，否则 `foreground_terminal_closure_pending`；④ 兜底：观察者收到 SDK terminal 后先跑 gate；pending → `RunBoundInvoker.invoke(purpose="closure", request_hash=H(run, watermark, staged_answer_hash))`（spike A1 路径，只暴露 `task_scope_update`，deadline=provider timeout）→ 校验同 handler → receipt；非法/拒绝/timeout → receipt(outcome=pending, reason) 且终答交付带 `semantic_closure_pending`；下一轮 snapshot 继续注入；⑤ invoker：`post_turn_invocation_attempts` reserved→handed_off→(succeeded|failed|unknown)，unknown 分类 `not_sent`（可重发 attempt+1）/`sent_unknown`（只查 provider_response_id 或等待，不重发）/`sent_confirmed`；同 request_hash 已 succeeded → 返回同行，Provider 计数 0。
- 验证（HM-TO-R8 / TC-HM-11 步骤 5）：deterministic provider：多工具批次 → 单 receipt 覆盖全部事件；模型漏调用 → 兜底一次 → mutate；模型拒绝 → pending → 终答带标记 → 下一轮补交；CAS 冲突（并发 revision）→ `mutation_base_revision_conflict` 可重试；重复 plan（同 idempotency）→ 同 receipt；projection worker 失败 → canonical 不回滚；kill 在 `semantic-closure-commit`/`terminal-watermark` seam → 重放收敛；invoker：同 request_hash 二次调用 Provider 计数 0；`sent_unknown` 不重发。
- 依赖：Task 2。

### Task 4 — 终态同事务 Memory outbox、analysis executor 与 delivery authority [S5B-AC-2] → **价值验证里程碑**
- 改动：`memory_ingestion_outbox.py`（新）、`analysis_executor.py`（新）、`human_memory_v7.py`（注入 authority + job runner 装配）、`foreground_queue.py`（同事务 outbox 行 + evidence links）、`main.py`（worker 生命周期）。
- 现状：调查 4/5；spike A2（待证）给出 runner/config/envelope 精确形状。
- 修改方式：① `record_sdk_terminal` 钩子：本 turn group 的 sanitized evidence ids → `memory_ingestion_outbox(pending)` + links；② worker：lease claim → 构造 `SanitizedEvidenceEnvelope/Receipt`（复用 `human_memory_service._append_host_evidence` 的构造，`filter_policy_version` 同）→ `ingest_committed_evidence` → receipt 回写 Host 事件 `memory.ingestion.receipt`；失败 retry_delays → dead_letter；③ `HostMemoryAnalysisExecutor.analyze_memory(request)`：`request.run_id` → `foreground_run_sdk_bindings` → adapter（incarnation/config_revision 校验同 main.py:7526）→ `RunBoundInvoker.invoke(purpose="analysis", request_hash=request.request_hash, attempt=request.attempt)` → 解析结构化 `MemoryMutationPlan`（strict）→ `MemoryAnalysisResultEnvelope`（delivery receipt 绑 attempt/provider_response_id/host_receipt）；④ `HostMemoryAnalysisDeliveryAuthority.verify_analysis_delivery` 从同一 attempt store 校验 request_hash/attempt/result_hash/envelope 一致；⑤ `DurableMemoryJobRunner` 用 `MemoryJobWorkerConfig`（provider/model/config_hash 来自 Run 绑定；prompt/schema/policy/validator version 常量）由 Host 后台任务驱动；remember 高优先由 Task 6 接。
- 验证：deterministic executor 下 fault lane `memory-mutation-plan` 六 seam；attempt 五态转移与 `UNIQUE(request_hash,attempt)`；Memory 不可用（关闭 DB 文件权限）→ dead-letter + raw 守恒；duplicate outbox 投递 → 同 receipt；**里程碑真实车道**：`test_s5b_milestone_real_provider.py -m real_provider`：README 版本改写 → 全链断言（一个 Run、closure receipt、outbox delivered、analysis applied、Provider 计数 = 1 主 Run 调用 + ≤1 closure + 1 analysis）。
- **spike A2 边界声明**：0.6.0 wheel 下 APPLIED = 记忆库已接受并审计 plan（`accepted_analysis_plans` + `job_attempts=applied`），**尚不物化**为 cognitive heads；里程碑口径 = 「被记忆库接受的 MemoryMutationPlan」（acceptance 原文），物化与 Prospective 注册由 Task 5 的 Memory 0.6.1 兑现后在 S5B-S1 真实车道复跑断言（root run ≥2 之一必须在 0.6.1 上）。
- **里程碑执行**：deterministic 先行 → 真实 provider → demo 给用户 + 矛盾转化再分析（RUNLOG）。
- 依赖：Task 3；spike A2。

### Task 5 — Memory 0.6.1：accepted plan 物化、属主注册 API、删 fail-open、pre-admission audit [S5B-AC-2⑤/AC-4①/AC-6③④]
- 改动：memory-sdk `backends/sqlite_v5.py`（`prepare_analysis_application` 在 accepted 分支内、同一事务、以 repository 生成的 application capability 编译并物化 plan——复用 `apply_memory_mutation_plan` 的 compile/apply 内核，写 cognitive revisions/heads + `memory.cognitive.committed` + prospective registration outbox；no_mutation 不物化；replay 幂等）、`core/port.py`/`manager.py`/`sqlite_v5.py`（`register_principal_owner(principal, scope)` 幂等注册，修正 principal 行 deployment/household 形状）、`pyproject` 版本 0.6.1 + 两次 clean build 一致 + candidate manifest；Host `pyproject`/`vendor` pin；`human_memory_v7.py:101-119` 删除；`pre_admission_audit.py`（新）+ Harness 拒绝点接线（`context_route`/`task_scope_update`/analysis 结果解析处）；testcase runner/fixture 的 `BLOCKED_UNTIL_S5` 翻转（走 behavior_changes 批准，因 fixture 是冻结 oracle）。
- 验证：Memory 仓 `test_durable_memory_jobs_v5` 新增「APPLIED 后 cognitive heads/prospective outbox 存在、replay 不重复、no_mutation 零物化、kill 在 apply 前后收敛」；spike A2 脚本在 0.6.1 上重跑步骤 4a 转 PASS；fresh install 首条对话不再依赖 fail-open（删分支后回归绿）；错误 wheel hash fail-closed；pre-admission audit 行 + TC-HM-08 关系 malformed wire 用例。
- 依赖：Task 4（Memory 仓，可与 Task 4 真实车道并行；Task 6/7 依赖本 Task）。

### Task 6 — Prospective 唯一 scheduler 与 occurrence 生命周期 [S5B-AC-4]
- 改动：`prospective_scheduler.py`（新）、v46 三表、`human_memory_v7.py`（`prospective_signal_authority` 注入）、`context_authority.py`（presented/ack 写入接管）、`main.py`（tick 任务）。
- 现状：调查 4（Memory 侧 outbox 就绪、`apply_prospective_signal` 就绪、S5a reconcile 只读比对）；A5 成立。
- 修改方式：① outbox 消费：按 `(created_at, outbox_id)` 游标读 `memory.prospective.*.requested`，`outbox_id` 幂等写 registrations（register/invalidate 单向）；② tick（复用 Reminder 双检）：到期/事件 → claim registration → Host 构造 `ProspectiveSignalAuthorityRef` → `apply_prospective_signal` → Memory inbox 出现 occurrence → Host `prospective_occurrences(claimed)`；③ snapshot reconcile 读到 pending → `presented`（写 `occurrence_presented`）；终答后 Host 检查模型是否 ack（`task_scope_update`/终答 receipt 里的 `acknowledged_occurrences`，由 Host 从 tool 载荷解析，不解析自然语言）→ `acknowledged`→`settled`；模型拒绝/未提及 → 保持 presented 不 processed；suppressed → `settled(suppressed)` 内容零进 Context。
- 验证：fault lane `prospective-occurrence` 四 seam；同 revision/event 恰一 occurrence；invalidation 后零触发；重复 outbox 投递幂等；真实 provider 场景 S5B-S5。
- 依赖：Task 5（0.6.1 物化后才有 registration outbox）。

### Task 7 — 即时 remember / correct / forget [S5B-AC-5]
- 改动：`tools/memory_tools.py`、`tool_catalog/providers.py`、`human_memory_v7.py`（`memory_action_authority`）、`analysis_executor.py`（高优先 job）。
- 现状：调查 6；SDK `suppress` 就绪；typed recall 读侧已按 suppression gate（S3）。
- 修改方式：`memory_write(kind=remember|correct, statement, evidence_ref)` → 先写 Host evidence → outbox 行 `priority=immediate` → worker 立即触发 analysis（同 executor）；`memory_forget(target)` → `memory_search` 结果的 exact memory ref → Host `MemoryActionAuthority`（已认证 subject、purpose=forget、nonce）→ `MemoryManager.suppress` → receipt durable 后返回；Host 读侧（`recall_adapter`、short-horizon、snapshot、inbox）均走 Memory 门，无需缓存失效。
- 验证：TC-HM-07 步骤 1–3 自动化：记住→typed recall 可见→忘掉→六路读取不可见→raw 行数/hash 守恒；载荷变异（缺 ref/非法 target）fail-closed；真实 provider S5B-S6。
- 依赖：Task 5。

### Task 8 — composition、v46 cutover 与遗留义务收口 [S5B-AC-6①②⑤]
- 改动：`main.py`（逐项注入 + 缺件 startup fail + epoch）、cutover 测试（v46 前向、旧 runtime 拒 v46、rollback drill）、S1 真实车道断言 + transcript dump（`test_s5a_milestone_real_provider.py`）、lint 小项、S4 P2（effect gate durable 正向判定 = Task 1 已达；oracle pin 口径统一进 spec）。
- 验证：`test_composition` 逐缺件；cutover receipt；ruff changed-surface 零新增。
- 依赖：Task 6/7。

### Task 9 — 验收矩阵、故障矩阵 lanes、真实 UI、机器门与文档回写 [全 AC]
- fault runners `backend/tests/faults/*`（四 lane，runner_contract）；S5B-S1…S7/REG 执行（真实 provider ≥2 root，其一 ≥20 turn；真实桌面 UI 按交接 §6.3 通道）；机器门 `compile-manifest → init → record-run --exec → attach-evidence → re-attest → full-audit → finalize`；三仓文档回写（**在最后一次全量前完成**，防 ARCHITECTURE/ 触发重测）；journal/retro。
- 依赖：Task 8。

## 执行模式自决
集中兵力串行：Task 0→1→2→3→4 共享 `foreground_queue.py`/`main.py`/`sdk_adapters` 文件簇且强顺序依赖；Task 5（Memory 仓）在里程碑后可与 Task 4 真实车道分兵，Task 6/7 串行其后。

## Assurance / 信任与失败边界
见 `assurance-contract.json`；执行期硬约束沿用 program（原始证据不删、凭据不落盘、`.local-test-evidence` 不提交、不 push/tag、不改 SDK）。

## 停止追踪点
S6 UI；HM-AC-8 质量门（人工语料）；SDK 0.8 tool_calls；多 root selection；WeMM COS 上传；系统通知交付。
