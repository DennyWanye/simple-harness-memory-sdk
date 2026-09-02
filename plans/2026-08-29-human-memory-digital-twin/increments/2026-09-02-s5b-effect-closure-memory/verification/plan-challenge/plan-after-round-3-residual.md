<!-- plan-status: draft (round-1 challenge 已 synthesis，修订版待 closure 与用户批准；acceptance 修订提案见 acceptance-amendments-proposed.md) -->

# Plan：S5b — 工作区 effect gate、TaskScope 语义收口与 Host↔Memory 异步面

## 矛盾分析（承 acceptance）

- 一句话：主模型替用户真干了活之后，系统能否把这一轮真实发生的事确定性地沉淀为任务档案语义状态与长期记忆。
- 最小验证动作 = 价值验证里程碑（Task 4 末）：真实 provider，"把 README 里的版本号改成 1.2.0" → `write_file`
  经 envelope 重验 → `host.file` 脏标记 → `task_scope_update` mutate（漏调则兜底）→ 终态同事务 Memory outbox →
  post-turn analysis 产出的 `MemoryMutationPlan` 被 Memory **0.6.1** accepted **并物化**（cognitive head +
  `memory.cognitive.committed`）→ 下一轮 typed recall 可读到；一个 Run、一次 attempt、零重复 Provider 调用
  （acceptance 修订提案 A1）。
- 主要方面：终态门（三水位 + 同事务 outbox + 兜底收口）在真实 Run 上跑通并可重放。
- 里程碑之前只排它的直接依赖：Task 0（oracle/迁移设计/fault runner 骨架）→ Task 1（effect gate **最小**闭环：
  write_file 清单项 + BindingRootResolver + 最小 envelope 重验 + host.file 记录）→ Task 2（客观事件同事务直写 + 脏标记）→
  Task 3（task_scope_update 常暴露 + durable 兜底状态机）→ **Task 4a（Memory 0.6.1 核心：filter policy 透传、多 op finalize
  收敛、accepted plan 仓储内物化、属主注册、analysis lineage、base_revision 端口——challenge 实证为里程碑直接依赖）**
  → Task 4（outbox + analysis_proposal + executor + delivery）。effect gate hardening 矩阵、Prospective、即时操作、
  cutover 与验收矩阵全部排在里程碑之后。

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
   （S4/S5a 均未兑现，本增量兑现全部四条并按 runner_contract 输出 root_run_id + before/after hash）；V0 SPIKE-CROSS-DB-TRIGGER /
   SPIKE-RUNTIME-BRIDGE 协议（`spikes/manifests/spike-manifest.json`）冻结 kill 点与 required 断言。
8. **基线**：Host `main`@`ec1cb944` 6282 passed / 7 既有红；Memory `main`@`fcf1682` 1071 passed（`baseline.md`）。
9. **challenge round-1 实证补充（5 specialist，probe 全在 exact wheel/真 SDK 上跑）**：① 0.6.0 `prepare_analysis_application` 只做结构+血缘校验、
   不校验 span、不物化（`sqlite_v5.py:11335-11364`），APPLIED 后任何 Host 读路径为空；② 0.6.0 `finalize_analysis_application` 对 ≥2 operation 的
   accepted plan 因 decision 序不一致永久 `audit_pending`（`:11533-11566` vs `:13574`，真实模型 3/3 产 2 op，2/2 卡死）；③ Memory 只认
   `credential-filter/v1`（`core/evidence.py:32`），builder 无 `supported_filter_policies`，Host 真实 `host-public-turn/v1` envelope 被 ingest 拒绝；
   ④ 真实 provider 最后一跳可行：模型可填 proposal（type/字段/`evidence_item_id`/`exact_quote`）+ Host 确定性 EvidenceSpanRef 派生（键 `text`）
   4/4 逐字引用、0 派生失败，编译后 0.6.0 validator accepted；⑤ 物化内核结构性依赖 `evidence_authority`，且在 `BEGIN IMMEDIATE`+`_write_lock`
   内回调——解析器回读 Memory backend 会死锁（已观测）；⑥ 0.6.0 重试语义：executor 失败 → 新 batch/新 request_hash/新 attempt（成员集合不变或增长），
   只有 lease reclaim/authority transient 才重投同一 request；`sent_unknown` 在非流式 OpenAI 兼容端点无确认通道；30s lease 短于实测 analysis 延迟
   （16.6–33.9s）；⑦ Host `ExecutionEvidenceIngress` 的 `next_sequence` 只看已导入 receipts（`foreground_runtime.py:1170-1178`）——outbox 未导入行会被
   terminal 永久拒绝而门照常放行（probe 复现）；⑧ 终答由 SDK delivery pump 在 Host 终态前交付（`kernel_terminal.py:160-180`、`delivery.py:129-190`）；
   ⑨ 每个 foreground Run 在 admission 时绑定 scope（`QueueTurnRequest.scope_ref` 必填），Run 内 `context_route` 可换 scope 但写根在冻结时按
   admission scope 决定 → 再路由后 envelope 与物理写根分裂（probe E3）；⑩ SDK 授权路径 `decide()` 从不传 `explicit_only`，Auto 对任何类别合成
   `policy:auto` grant，`_CONFIRM_ONLY` 只在 legacy executor；⑪ 冻结 SDK 只有两条模型可见拒绝（`MODEL_AUTHORITY_FIELD_FORBIDDEN`/
   `ROUTE_BARRIER_NOT_OBSERVED`），standalone PROJECT_EFFECT/零多 root/hidden 工具全是 `driver_failed` 整 Run 故障（`catalog_execution_policy_unavailable`
   等）；⑫ Memory Prospective：`REGISTRATION_ACCEPTED` 回签是 TIME_DUE/EVENT 的前置（否则 `registration_not_live`），signal 身份必须确定性
   （同 ref 重放幂等，新身份重放 → `prospective_signal_replayed`/`ignored`），Host 无信号可退出 TRIGGERED 意图；v45 `occurrence_presented` 的
   `presented_at` 单调且 CHECK 禁 settled-without-presented。

## 方案与权衡（含最佳实践适配分析，反对本本主义）

| 主题 | 业界做法 | 本项目条件 | 取舍 |
|---|---|---|---|
| 终态→Memory 摄入 | Transactional outbox（业务事实与 outbox 行同事务，worker 至少一次投递，消费端幂等） | Host state.db 与 Memory DB 是两个 SQLite；`record_sdk_terminal` 已是单事务且有故障 seam；Memory `ingest_committed_evidence` 按 source_ref 幂等 | **照用**：outbox 行写进 `record_sdk_terminal` 同一事务；worker lease + 有界重试 + dead-letter；不引消息中间件 |
| 主模型 post-turn 调用幂等 | Stripe 式 idempotency key + 请求指纹；Temporal activity 的 "scheduled/started/completed/unknown" | Host 已有 `execution_provider_invocations` 同形账本；SDK Run 绑定给出不可变 provider/model/config | **改造复用**：新 `post_turn_invocation_attempts` 镜像既有 taxonomy，`UNIQUE(request_hash, attempt)`；不复用 workflows 表本身（那是 workflow Run 域） |
| closure 由同一模型补 | Agent 框架里常见 "post-hoc self-report" 二次调用 | SDK 冻结无钩子；program 要求同一 Run | **主路径 in-Run**（snapshot 注入收口要求 + 暴露 `task_scope_update`），**兜底独立调用**（同 Run 绑定），pending 可交付不扣押（acceptance D1） |
| 唯一 scheduler | 单 writer + lease 的 durable timer（cron-in-DB） | `ReminderScheduler` 已是该形态但在 companion DB | **衍生不复用实例**：state.db 新表 + 同设计（claim/lease/双检/settle），避免跨库事务（acceptance D4） |
| 事件语义判定 | 关键词/正则/小模型分类 | program 明令禁止 | **确定性映射表**：event_kind → material/trivial（`host.file`/`host.test`/`harness.tool_invocation(project_effect)` = material；`host.turn`/`harness.provider_invocation`/`harness.context_snapshot`/`harness.route_decision`/`harness.run_terminal` = trivial；Task 0 冻结，exhaustiveness 断言） |
| effect 重验 | Capability token + per-call re-validation（zanzibar 风格 "check at use"） | S4 store 已提供 `verify_task_execution_envelope` + inode 重验 | **照用**：在 `ProductEffectExecutor.execute` 前调用，加 scope lifecycle 与 `_CONFIRM_ONLY` 不变断言 |

| Harness 证据导入 | 生产者-消费者 outbox | 事实全部在 Host 进程内产生；`next_sequence` 只认已导入 receipts | **不用 outbox/worker**：state.db 内事实同事务直写 ingest；其它 DB 事实先预留 seq，terminal observer 唯一排空（challenge 实证丢行后改） |
| Prospective ack | 由模型自然语言/终态推断 | program 禁 NL 判断；SDK DTO 冻结 | **新 Host 工具 `prospective_ack{occurrence_key}`**：模型回显 Host 放进 inbox 消息的 64-hex key；processed := durable ack receipt |

放弃的备选：① 改 SDK 加 closure hook（冻结，不可）；② 第二个 SDK Run 做 closure（破坏 1 用户请求 = 1 Run，FIFO 语义复杂）；
③ 复用 companion `ReminderScheduler` 实例跨库投影（跨库无事务）；④ 用 `commit_run_outcome.terminal_commit_extensions`
（那是 workflow runs 库的 seam，不是 Host foreground terminal 事实所在）；⑤ Host 侧对 runner APPLIED 的 plan 调 `apply_memory_mutation_plan`
做物化 bridge（caller-principal 路径绕过仓储 application capability，且不能修 finalize 非收敛/filter policy 两个 P0——全部只能在 0.6.1 修）；
⑥ 用 per-turn 隐藏工具承担"拒绝"语义（隐藏工具被调用 = 整 Run 故障，probe E1/E2）；⑦ 扣押终答等 closure（交付点在 SDK pump，不可行）。

## 关键假设与实践证据

| ID | 假设 | 验证方式（spike） | 实际输出 | 结论 |
|---|---|---|---|---|
| A1 | Host 可在 SDK Run 之外用 `ProductProviderAdapter`（同 registry Protocol）对真实 provider 做一次带 `task_scope_update` 工具的独立调用，并拿到 TaskScopeMutationPlan 形状的结构化 tool call | `scratchpad/spike-a1/spike_a1.py`（真实 `gpt-5.6-luna`，key 不打印） | 两次运行均 `finish=tool_calls`，1 个 `task_scope_update` 调用，`outcome=mutate`，`base_revision=7`，6 个 operation 全部只引用允许的 `ev-file-0091/ev-test-0092`；usage 590+559 / 4902+403 tokens，16.6–33.9s；`A1_VERDICT: PASS` | **PASS**；兜底 closure 与 analysis executor 共用该调用路径 |
| A2 | exact Memory 0.6.0 wheel 上，Host 提供 delivery/prospective/action authority 构建 v7，`ingest_committed_evidence` → `DurableMemoryJobRunner.run_once`（Host executor）→ applied → `read_outbox` 出现 prospective registration → 第二次 run_once idle → `apply_prospective_signal` 产生 inbox occurrence | `spikes/a2/spike_a2.py`（exact wheel，fresh sqlite） | 步骤 1/2/3/5/6 PASS：builder 接受 Host authority；ingest 产 job+outbox；`run_once`=APPLIED（`job_attempts` provider_handoff→result_committed→application_staged→mutation_audit_committed→applied，executor 1 次，`verify_analysis_delivery` 1 次）；第二次 IDLE；`apply_prospective_signal` 产生 1 条 `matched/time_due/triggered` inbox。**步骤 4a FAIL**：APPLIED 后 `cognitive_memory_heads=0`、无 prospective registration outbox——0.6.0 runner 只写 `accepted_analysis_plans`/decision/audit，**不物化记忆**；Host 额外调 `apply_memory_mutation_plan(principal, scope, plan)` 后才出现 registration outbox 且 `cognitive_memory_revisions.plan_hash == accepted_analysis_plans.plan_hash`。另：Host principal 行形状（deployment/household）在首次 caller-principal 写之前被 `read_outbox/read_occurrence_inbox` 拒绝（`short_horizon_principal_rejected`）= S5a fail-open 的根因；delivery authority 必须与 builder 绑定的是同一对象；`MemoryJobWorkerConfig` 15 字段无默认；plan.turn_id 必须 = `_stable_id("analysis-batch-turn", batch_id)` | **部分成立**：executor/runner/delivery 契约可用；**accepted plan 物化缺失属 Memory 0.6.0 上游缺口**（S2 Task 5 文本「apply 在单事务内、Memory 只 CAS apply 一次」未兑现）→ 本 plan Task 5 在 Memory 0.6.1 内修（repository 在 finalize 阶段以 application capability 物化），Host 不做 caller-principal 兜底；principal 形状 → 同版本属主注册 API |
| A3 | SDK 0.7.1 对 Host 覆盖为 PROJECT_EFFECT/required 的工具：standalone 路由拒绝、ROUTED_TASK 下 per-call `issue_envelope`（带 root_resolver）产出六元组 envelope 并到达 Host handler、模型伪造 authority 字段被拒、无 resolver fail-closed | `spikes/a3/spike_a3_test.py`（真 ReActLoop + 真三 authority + v45 ledger + S4 binding store，7 passed） | (a′) UNROUTED / (a″) 同批 route+write → `ROUTE_BARRIER_NOT_OBSERVED` rejected ToolResult，handler 0 次；(b) ROUTED_TASK：`issue_envelope` per call，envelope 六元组 = S4 binding head，`context.task_execution_envelope` 到达 handler，真 `verify_task_execution_envelope` 接受；(c) 模型传 `task_execution_envelope`/`binding_set_revision` → `MODEL_AUTHORITY_FIELD_FORBIDDEN`；(d) `root_resolver=None` → `sdk_task_execution_root_authority_unavailable` **异常逃出 ReActLoop**（checkpoint 停在 `tool_batch_reserved`）。**(a) 字面不成立**：`routed_standalone` 下 SDK preflight 不触发 barrier，直接进 `issue_envelope`，Host 抛 `sdk_task_execution_route_authority_missing` 同样逃出 loop——冻结 SDK 没有让模型看到「standalone 不许项目 effect」的 rejection 路径。policy 三字段进 capability/catalog fingerprint | **成立（含一条设计约束）**：PROJECT_EFFECT 工具必须**按路由状态控制暴露**（只在 ROUTED_TASK 暴露），standalone 下模型看不到写工具；Host authority 抛错保留为 defense-in-depth 的 Run fault（fail-closed，不半状态）；跨部署 fingerprint 变化 → in-flight Run stable fail（cutover 注记） |
| A4 | Host 终态事实 `record_sdk_terminal` 是单事务且可在同事务插入 outbox 行 | 静态核对 `foreground_queue.py:1853-1990` | 单 `BEGIN`…`db.commit()`，异常 rollback，已有 `self._fault("terminal.before_commit")` seam；无扩展钩子需新增 | **成立**（实现时加 `terminal_commit_hooks` 参数，故障 lane 复用同 seam） |
| A5 | Host 经注入 resolver 调 `apply_prospective_signal` 可产生 matched occurrence 并被 S5a reconcile 门读到 | S5a 既有生产路径测试 `tests/sdk_adapters/test_no_recall_gate.py:373-386` | S5a receipt 已证（no_recall 被拒 + summary 进 snapshot） | **成立**（沿用） |
| A6 | 真实主模型能从 Host 真实 sanitized turn payload（键 `text`）产出可被 Host 确定性派生 EvidenceSpanRef 并被 0.6.x validator accepted 的 MemoryMutationPlan | challenge specialist spike `scratchpad/spec-value/spike_value_last_hop.py`（真实 gpt-5.6-luna，raw 输出存档） | 4/4 逐字引用、0 派生失败、validator accepted、`apply_memory_mutation_plan` committed → head=1 + registration outbox；paraphrase fail-closed | **PASS** |
| A7 | 0.6.0 finalize 对多 operation plan 收敛 | `scratchpad/spec-value/spike_multiop_finalize.py`（确定性复现） | ≥2 op → `analysis_audit_decisions_differ`，永久 audit_pending，2/2 | **FAIL → 0.6.1 修（Task 4a）** |
| A8 | Host 真实 envelope 能被 0.6.0 ingest | 同上 run1–4 | `evidence_filter_policy_unsupported`（只认 credential-filter/v1） | **FAIL → 0.6.1 修（Task 4a）** |
| A9 | outbox+异步 worker 导入 Harness 证据不丢行 | `scratchpad/spec-closure/probe_closure_window.py` P1 | 迟到 seq 被 `execution_source_sequence_conflict`/`execution_after_terminal_rejected` 永久拒绝而 `authorize_terminal` 放行 | **FAIL → 改同事务直写+预留表** |
| A10 | 隐藏/standalone 下的 PROJECT_EFFECT 调用可成为模型可见拒绝 | `scratchpad/spec-effect/spike_effect_exposure_test.py`（17 passed） | `catalog_execution_policy_unavailable`/`route_authority_missing` 均逃出 loop → Run FAILED；同 Run 再路由后 envelope 证 root-B 而物理写 root-A | **FAIL → 二分口径 + EffectGate 冻结 authority 一致性** |
| A11 | Memory Prospective signal 重放幂等 | `scratchpad/spec-prosp/probe_replay.py` | 同 ref 重放幂等；新身份重放 → replayed/ignored；无 REGISTRATION_ACCEPTED → `registration_not_live` | **成立（约束：确定性 signal 身份 + 回签必做）** |

## 关联验收标准

S5B-AC-1（决定性）← Task 2/3；S5B-AC-2（决定性）← Task 3（invoker）/4a（0.6.1 核心）/4；S5B-AC-3 ← Task 1（最小）+ Task 8（hardening/Auto）；
S5B-AC-4 ← Task 4a/6；S5B-AC-5 ← Task 7；S5B-AC-6 ← Task 4a/5/8；全部 AC 的验收矩阵 ← Task 8b/9。

## 文件影响清单

| 文件 | 职责 | 现状 | 本次改动 |
|---|---|---|---|
| `backend/deskpet/memory/migrations/038_effect_closure_memory_v46.sql`（新） | v46 durable 表 | 无 | `task_scope_closure_receipts`（scope 归属：task_scope_id, sdk_run_id, closure_watermark, outcome mutate|no_mutation|pending, plan_id, reason）、`harness_evidence_reservations`（run_id, source_sequence UNIQUE, source_event_id UNIQUE, status reserved|ingested|abandoned）、`memory_ingestion_outbox`（含 analysis lineage/model_config_hash）+`_evidence_links`、`post_turn_invocation_attempts`（purpose, host/sdk run, generation, scope, closure_watermark, request_hash, attempt_ordinal, evidence_set_key, status reserved|handed_off|succeeded|failed|unknown, unknown_class, provider_request_id, plan_id；`UNIQUE(request_hash,attempt_ordinal)`）+`_members`(subject,run_id,evidence_id)+`_events`、`prospective_scheduler_registrations`(outbox_id PK, state received|accepted|invalidated)、`prospective_outbox_cursor`、`prospective_occurrences`（canonical 生命周期：occurrence_key PK, state claimed|presented|acknowledged|settled, settled_reason, presented_run_id/snapshot_id, ack_run_id/receipt）、`prospective_ack_invocations`(sdk_run_id, occurrence_key UNIQUE)、`effect_gate_rejections`(run_id, route_receipt_id sticky memo)、`host_pre_admission_audit`；全部 append-only 触发器；`occurrence_presented` 不改 schema，仅作门投影 |
| `backend/deskpet/memory/migrator.py` | 迁移注册 | v45 target | v46 target + 恢复表注册 |
| `backend/deskpet/sdk_adapters/tool_authority.py` | 工具执行策略覆盖表 | 只有 `context_route` | 冻结 PROJECT_EFFECT 清单（acceptance AC-3①）→ `(project_effect, required, required)` |
| `backend/deskpet/sdk_adapters/task_execution.py` | envelope 签发 | `root_resolver=None` | `BindingRootResolver`：由 receipt 的 exact binding receipt 解析恰一 root；零/多 root → `sdk_task_execution_root_authority_ambiguous|missing`（整 Run 故障口径，见二分表） |
| `backend/deskpet/sdk_adapters/tools.py` | 物理 effect executor | `assert_workspace_current` + admission | `ProductEffectExecutor.execute` 前新增 `EffectGate.verify(context)` → 失败返回 `EffectExecution(effect=None, ToolResult.rejected(error_code))`（无 execution_effects 行、无事件）；成功执行后同事务写 `host.file`/`host.test` 客观事件 + evidence 行（Task 2） |
| `backend/deskpet/sdk_adapters/effect_gate.py`（新） | per-effect 重验 + 客观事件 recorder 接线 | 无 | 冻结检查顺序与 reason-code 表：envelope 存在/身份回声 → sticky memo(run_id, route_receipt_id) → **冻结 authority 一致性**（`effect_gate_frozen_scope_mismatch`/`effect_gate_projectless_project_effect`/`effect_gate_frozen_root_mismatch`）→ `verify_task_execution_envelope`（S4 码集，含 inode/canonical）→ scope lifecycle（`effect_gate_task_scope_not_active`）→ confirm-only/grant（`explicit_only` 由冻结 effect 分类计算，`product_policy_user_confirmation`）；`ObjectiveEventRecorder`（工具→事件映射表，确定性 material/trivial 分类） |
| `backend/deskpet/execution/harness_evidence.py`（新） | Host 侧 Harness 证据同事务直写 + 预留 | 只有 run_terminal | state.db 内事实（snapshot receipt / route decision / route tool invocation）在各自提交事务内直接 `ingest`；其它 DB 事实（SDK effect、provider invocation）先在 `harness_evidence_reservations` 预留 seq，物理动作完成后 ingest；terminal observer = 唯一排空者（ingest 或 tombstone payload.status=abandoned），`next_sequence = MAX(reservations ∪ receipts)+1`；`run_terminal` 最后 |
| `backend/deskpet/sdk_adapters/task_scope_mutation.py`（新） | `task_scope_update` 工具 handler | 无 | strict schema → `TaskScopeMutationPlan`；Host 校验 evidence refs 属 scope、base_revision、状态迁移表、幂等 → `apply_mutation_plan` → closure receipt |
| `backend/deskpet/execution/semantic_closure.py`（新） | 脏标记计算 + 三水位终态门 + 兜底 | 无 | `dirty_state(scope)`（自最后非 pending closure receipt 的 watermark 起的 material 事件 × 映射表，**按 admission scope**）；`TerminalClosureGate.authorize(run)`（COMPLETED/FAILED/CANCELLED/STOPPED 一律生效）；`ClosureFallback`（仅 COMPLETED 且有 last assistant message；invoker 调用 → handler 校验 → receipt 与 apply 同事务 / pending）；`force_close_pending(scope, reason=closure_abandoned)` |
| `backend/deskpet/sdk_adapters/post_turn_invoker.py`（新） | Run-bound 独立主模型调用 + 五态 attempt 账本 | 无（先例 provider_invocations.py） | `RunBoundInvoker.invoke(purpose, request_hash, evidence_set_key, members, build_request)`：`UNIQUE(request_hash,attempt_ordinal)` + evidence_set_key + members 索引查重；reserved 行与 `_validate_lease_tx` 同事务（仅当前 lease owner）；reserved→handed_off→succeeded/failed/unknown；unknown 分类 `not_sent`（可 attempt+1）/`sent_unknown`（永不重发 → 终态拒绝）/`sent_confirmed`（仅注入观察者）；任一成员有 open handed_off/sent_unknown → 拒绝 0 调用 |
| `backend/deskpet/memory/analysis_proposal.py`（新） | 模型可填 proposal → MemoryMutationPlan | 无 | proposal 工具 schema（memory_type/字段/`evidence_item_id`/`exact_quote`/reason_code）+ prompt 常量（`prompt_version`）+ 确定性 EvidenceSpanRef 派生（`text.find(quote)` → UTF-8 byte range、quote_hash、pointer `/text`、item_ordinal=1；paraphrase fail-closed）+ 编译（Host 填 run_id/subject/disclosure/evidence_refs/idempotency_key/turn_id/base_revision（0.6.1 端口）） |
| `backend/deskpet/memory/analysis_executor.py`（新） | `MemoryAnalysisExecutorPort` + `DeliveryAuthorityPort` Host 实装 | 无 | 由 job→originating run 的 `foreground_run_sdk_bindings` 重建 adapter（incarnation/config_revision 校验；不可重建 → `not_sent(binding_unrebuildable:*)`）；校验 request lineage == binding；经 invoker 调用；`analysis_proposal` 编译；`MemoryAnalysisResultEnvelope`；delivery authority（与 builder 绑定同一对象）从同一 attempt store 校验；finalize 异常 → dead-letter 不崩溃循环 |
| `backend/deskpet/memory/memory_ingestion_outbox.py`（新） | 终态→Memory 摄入 worker | 无（`product_outbox.py` 是 legacy v30） | claim/lease → `ingest_committed_evidence` → receipt 回写 Host 事件；失败有界重试→dead-letter；raw 不删 |
| `backend/deskpet/execution/foreground_queue.py` | Host terminal 事实 | 单事务 | `record_sdk_terminal(..., terminal_commit_hooks)`：同事务排空预留 seq、closure 水位检查（`foreground_terminal_closure_pending`）、evidence links、`memory_ingestion_outbox` 行（含 lineage hash）、settled(acknowledged) 推进；`EffectBoundary.CLOSURE` |
| `backend/deskpet/execution/foreground_runtime.py` / `harness/kernel_terminal.py` | 终态观察与交付 | 无 closure 检查 | SDK terminal 观察后、`record_sdk_terminal` 前：排空 → gate → 兜底（lease-fenced）→ Host 终态；终答交付路径不变（SDK pump）；reconcile 分支处理 in-flight attempt（见 Task 3） |
| `backend/deskpet/sdk_adapters/context_authority.py` | per-turn snapshot | 无收口注入 | dirty/pending 时注入 protected "closure required" 指令（不控制工具可见性）；pending occurrence 消息携带 64-hex occurrence_key |
| `backend/deskpet/memory/human_memory_v7.py` | v7 接线 | 只传 embedder；fail-open 兜底 | 注入 analysis delivery / prospective signal / memory action / **evidence authority（Host state.db 解析器）**、`supported_filter_policies`；首次构建幂等 `register_principal_owner`；Task 4a 后删 fail-open |
| `backend/deskpet/memory/prospective_scheduler.py`（新） | 唯一 Prospective scheduler | 无 | 单事务消费 `read_outbox` 注册/失效 + 游标 → 确定性身份 `REGISTRATION_ACCEPTED` 回签 → tick `apply_prospective_signal` → 从 inbox claim `prospective_occurrences`；settled(superseded|expired|suppressed) 由 inbox/outbox 事实派生；`occurrence_presented` 投影只在清 inbox 迁移时写 |
| `backend/deskpet/sdk_adapters/prospective_ack.py`（新） | `prospective_ack{occurrence_key}` 工具 | 无 | direct kernel、PROJECTLESS_SAFE、默认 policy（五路可见）；handler 单事务：key ∈ presented → acknowledged → 投影行 → 幂等调用行 |
| `backend/deskpet/tools/memory_tools.py` + `tool_catalog/providers.py` | remember/correct/forget | stub | 真实 handler：write/correct → 高优先 job；forget → 同步 suppress |
| `backend/deskpet/memory/pre_admission_audit.py`（新） | Host durable pre-admission audit | `BLOCKED_UNTIL_S5` | Harness 拒绝的非法载荷写 `host_pre_admission_audit` |
| `backend/main.py` | composition | 三 authority 已注册 | 注册 root_resolver/effect gate/closure gate/invoker/analysis executor/outbox worker/scheduler；缺件 startup fail；epoch 门 v46 |
| memory-sdk `core/manager.py`, `core/port.py`, `core/evidence.py`, `core/jobs.py`, `backends/sqlite_v5.py`, `backends/schema_v5.py` | Memory 0.6.1 | 见现状 9 ①②③⑤⑥⑫ | ① builder 透传 `supported_filter_policies`；② finalize 写/读同一规范序（多 op 收敛）；③ accepted 分支同事务以 application capability 物化（复用 compile/apply 内核；no_mutation 不物化；replay 幂等；`analysis_apply_heads`/`cognitive_apply_heads` 统一规则）；④ `register_principal_owner(principal, scope)` 幂等；⑤ `ingest_committed_evidence(..., analysis_lineage=)` 逐 evidence 持久 + claim 从成员派生并断言一致；⑥ `MemoryAnalysisRequest`/claim 暴露 `analysis_apply_head`（base_revision 端口）；⑦ 可选 `AnalysisExecutorPermanentError`；schema version bump；0.6.1 wheel 两次 clean build 一致 + manifest；Host pin 更新 |
| `backend/tests/faults/test_{foreground_fifo_closure,memory_mutation_plan,prospective_occurrence,taskscope_init_binding}.py`（新，Task 0 建骨架） | fault-matrix runner（四 lane） | 不存在 | 按 lane seams 实装（新增 seam：observer next_sequence 竞争、attempt 五态 reconcile、跨 Run plan、≥2 op finalize/audit_pending 卡死、reconciliation observer、lease-reclaim in-flight、membership growth、Run fault 三稳定码、frozen-root 分裂、Auto+DESTRUCTIVE），输出 root_run_id + before/after hash，非零退出 |
| `scripts/dev/real_ui_channel/`（新，ignored 工具目录旁）| 真实桌面 UI 通道 | 交接 §6.3 脚本可能已清 | 重建 identity_harness / shim_proxy / tauri_shim；S5B-S8 预演 |
| `backend/tests/sdk_adapters/test_s5b_*.py`、`testcase/human-memory-program/s5b-*-verification-spec.json` | black-box 用例与 oracle | 无 | Task 0 冻结 |

## Complexity inventory

| 复杂度表面 | 新增 | 理由 / AC 或 risk 绑定 |
|---|:---:|---|
| 新依赖 | 否 | 全部 SQLite/httpx/既有 SDK |
| 新公共 API | 是（memory-sdk 0.6.1：属主注册、`supported_filter_policies` kwarg、`analysis_lineage` ingest kwarg、`analysis_apply_head` 端口）| S5B-AC-2/6；消除 fail-open 与三处 0.6.0 阻断 |
| 新持久化状态 | 是（v46 九张表）| AC-1/2/4/6；每张绑定 assurance ASSET-RAW-EVIDENCE / PROVIDER-IDEMPOTENCY / TASKSCOPE-CANONICAL-STATE |
| 新工具 | 是（`task_scope_update`、`prospective_ack`；memory_* 由 stub 转真） | AC-1②、AC-4③、AC-5 |
| 新后台任务 | 是（ingestion outbox worker、analysis job runner、prospective scheduler）；**删除**原计划的 harness evidence ingest worker | AC-2/4；均无 Agent effect 权限（ASSET-FOREGROUND-RUN-ORDER）|
| 新抽象层 | `RunBoundInvoker`（closure 兜底 + analysis + remember 三消费者共用）| 避免三份 provider 调用/幂等账本（FAIL-DUPLICATE-PROVIDER-CALL）|
| 可复用 | `ProductProviderAdapter`、`ExecutionEvidenceIngress`、`CanonicalTaskScopeStore.apply_mutation_plan`、`WorkspaceBindingAuthorityStore.verify_*`、`ReminderScheduler` 设计、`_CONFIRM_ONLY` | — |
| 删除/退役 | `human_memory_v7.py` fail-open 分支；`memory_tools.py` stub；`BLOCKED_UNTIL_S5` 标记 | AC-6 |

## 任务清单（最短价值路径优先；oracle 先于实现贯穿）

### Task 0 — oracle 定稿、v46/0.6.1 设计冻结、fault runner 骨架、release-unit 体检 [全 AC]
- 改动：`testcase/human-memory-program/s5b-effect-closure-memory-verification-spec.json` + reuse-report（S5B-S1…S8/REG → TC-HM-04/07/08/09/11 rev 冻结；TC-HM-09 步骤 6 的单 root-per-canary oracle 解释 + `behavior_changes`；impact_paths **仓库相对路径**；evidence contract；oracle pins）；本目录 `verification-spec.json`；黑盒用例骨架 `backend/tests/sdk_adapters/test_s5b_acceptance_matrix.py`（`xfail(strict)` 直到实现）；**四 lane fault runner 骨架** `backend/tests/faults/*` + `runner_contract` 输出器 + seam 注入常量（seam 清单见文件影响表）。
- 设计冻结（写代码前）：v46 逻辑表（列/唯一键/append-only/CHECK）；EffectGate reason-code 表与检查顺序；material/trivial 映射表；PROJECT_EFFECT 清单；unknown-call 三分类；closure request_hash/plan_id 派生；Prospective 四 kill 点 ↔ 表/事务映射与三不变量；Memory 0.6.1 API 面（七项）与 schema version。
- `check-release-unit`（MUST AC=6、Task=12（0,1,2,3,4a,4,5,6,7,8,8b,9）、plan ≈240 行、高风险=3）；`phase-start`。
- 验证：spec 通过 `compile-manifest`；用例骨架被收集且 xfail；runner 骨架以 `NOT_IMPLEMENTED` 非零退出。
- 依赖：无。

### Task 1 — effect gate **最小**闭环 [S5B-AC-3 直接依赖部分]
- 改动：`tool_authority.py`（清单）、`task_execution.py`（`BindingRootResolver`）、`effect_gate.py`（新，最小：envelope 存在/身份 → 冻结 authority 一致性 → `verify_task_execution_envelope` → scope lifecycle）、`tools.py`（executor 前置 gate + rejected 返回）、`main.py:8567`（注入 resolver + gate）、`context_authority.py`（可选：route ≠ ROUTED_TASK 时 `provider_specs` 不含 PROJECT_EFFECT 工具，降低整 Run 故障概率；fingerprint 稳定）、`foreground_runtime.py`（三条 Run fault 稳定码 → durable FAILED；故障码写入 `run_terminal` ExecutionEvidence 的 `public_payload.error_code`——不新增 host.* 事件种类，S4 recorder 允许集 {host.turn, host.file, host.test} 不变；映射表中 `run_terminal` 为 trivial）。
- 现状：调查 1、9⑨⑩⑪；spike A3/A10。
- 修改方式：① 清单常量进覆盖表（`project_effect/required/required`）；② resolver：`store.exact_receipt(receipt.binding_set_receipt_id)` → roots 恰一 → `(root_id, root_identity_hash)`，否则抛可审计 reason（整 Run 故障口径）；③ `EffectGate.verify` 冻结顺序前四步（Task 8 补 confirm-only/`explicit_only`）；失败 → `ToolResult.rejected(error_code)`、effect=None；④ 二分口径落文档与测试。
- 验证（oracle 先行）：ROUTED_TASK 单 root：write_file 经 envelope 重验通过并落 execution_effects；再路由到另一 scope 后 write_file → `effect_gate_frozen_scope_mismatch`；伪造 authority 字段 → `MODEL_AUTHORITY_FIELD_FORBIDDEN`；同批 route+write → barrier；standalone 路由下 snapshot tools 不含写工具（exhaustiveness），模型仍调用 → durable FAILED + 稳定码 `sdk_task_execution_route_authority_missing`；零/多 root → `sdk_task_execution_root_authority_*` 故障；`root_resolver` 缺 → startup fail。
- 依赖：Task 0；spike A3/A10。

### Task 2 — 客观事件同事务直写、脏标记与 Harness 证据预留/排空 [S5B-AC-1①]
- 改动：`effect_gate.py`（`ObjectiveEventRecorder`）、`harness_evidence.py`（新）、`provider.py`/`context_authority.py`/`context_route.py`（各自提交点直写或预留）、`foreground_runtime.py`（observer 排空）、`semantic_closure.py`（`dirty_state(scope)`）、v46 表。
- 现状：调查 2、9⑦；probe A9。
- 修改方式：① 物理 executor 成功/失败后在同一事务写 `host.file`/`host.test` 事件 **与 `human_memory_evidence` 行**（refs 可用），source_event_id=`effect:{effect_id}`；映射：写/编辑/移动/整理/文档/下载 → `host.file`；`run_shell`/`process_start` 由确定性规则（工具名 + 退出码 + 注册 test runner 白名单）→ `host.test` 否则 `host.file`；② state.db 内事实（snapshot receipt / route decision / route tool invocation）在各自事务内直接 `ingest`（同事务预留+导入）；SDK effect / provider invocation 先预留 seq，物理动作后 ingest；③ terminal observer 在 `run_terminal` 前按 seq 排空全部 reserved（ingest 或 tombstone），`next_sequence=MAX(reservations∪receipts)+1`；crash 后新 owner 重放同一排空；④ `dirty_state(scope)`：自最后一条非 pending closure receipt 的 watermark 起的 material 事件集合。
- 验证：事件顺序/幂等/hash 冲突；4 类 Harness 证据水位推进到 terminal；probe A9 场景（迟到 seq）→ 不再丢行、terminal 前排空；乱序/缺口 → `TerminalWatermarkPending`；映射表 exhaustiveness；`foreground-fifo-closure` lane `objective-event-commit`/`terminal-watermark` seam。
- 依赖：Task 1。

### Task 3 — `task_scope_update`（常暴露）、三水位终态门与 lease-fenced 兜底状态机 [S5B-AC-1②③④]
- 改动：`task_scope_mutation.py`（新）、`semantic_closure.py`、`post_turn_invoker.py`（新）、`foreground_queue.py`（钩子 + `foreground_terminal_closure_pending` + `EffectBoundary.CLOSURE`）、`foreground_runtime.py`（观察后排空→gate→兜底→终态；reconcile 分支）、`context_authority.py`（指令注入）、`tool_catalog/providers.py` + manifest + `PROJECTLESS_SAFE_TOOL_NAMES`（注册工具，direct kernel；policy non_project_effect/route required/task_scope required）。
- 现状：调查 2/3、9⑧⑨；A1 PASS；closure specialist 设计。
- 修改方式：① handler：strict schema（模型填 outcome/base_revision/operations/closure_reason/evidence_refs/idempotency_key；Host 填 scope=admission scope、run、disclosure）→ 状态迁移表（pending→no_mutation 任何 status 合法；complete 后禁 plan.*）→ refs ∈ 该 scope 已链接 evidence → `apply_mutation_plan` 与 `task_scope_closure_receipts` **同事务**；standalone → `rejected(task_scope_update_scope_unbound)`；无脏/pending → `rejected(task_scope_update_nothing_to_close)`（不递增 revision）；② snapshot 注入只控制收口指令文本；③ 终态门在 `record_sdk_terminal` 钩子内查 receipt 覆盖 watermark，否则 `foreground_terminal_closure_pending`；对全部终态生效；④ 兜底（仅 COMPLETED 且有 last assistant message）：`RunBoundInvoker.invoke(purpose=closure, request_hash=H(sdk_run_id, scope, closure_watermark, last_assistant_hash))`，plan_id=H(request_hash)，仅当前 lease owner（reserved 行与 `_validate_lease_tx` 同事务；返回后再验 lease 才 apply）；只带 `task_scope_update` spec，deadline=provider timeout；非法/拒绝/timeout/unknown → receipt(outcome=pending, reason) 且 Host 终态照常提交；⑤ reconcile（新 owner/重启）：无行/failed(not_sent) → 新 ordinal；reserved 未 handed_off → failed(not_sent) 后新建；handed_off/unknown → 绝不重发 → pending(closure_attempt_unknown)；succeeded 无 receipt → 从 `task_scope_mutation_decisions` 按 plan_id 派生 receipt；⑥ pending 归属 admission scope：同 scope 下一 Run 合并注入；complete/checkpoint/resume 仍 pending → Host `no_mutation(closure_abandoned)` 零调用；STATUS/投影显式 `semantic_closure_pending`。
- 验证（HM-TO-R8 / TC-HM-11 步骤 5 / lane `foreground-fifo-closure`）：多工具批次 → 单 receipt；漏调用 → 兜底一次 mutate（Provider 计数 1）；拒绝/timeout → pending → 终态照常 → 下一 Run 同 scope 注入并补交；unknown → pending 且重启后 0 重发；CAS 冲突可重试；重复 plan 同 receipt；projection 失败不回滚；kill 在 `semantic-closure-commit`/`terminal-watermark`/attempt reserved/handed_off seam → 重放收敛；lease 到期第二 owner 不重复调用；跨 Run plan 的 base_revision/refs 口径；standalone 调用稳定拒绝。
- 依赖：Task 2。

### Task 4a — Memory 0.6.1 核心（里程碑直接依赖）[S5B-AC-2②③⑤/AC-4①/AC-6③]
- 改动：memory-sdk 文件影响表七项中 ①②③④⑤⑥ + schema version；`tests/integration/test_durable_memory_jobs_v5.py` 新增：≥2 op applied、APPLIED 后 cognitive head/prospective outbox 存在、replay 不重复、no_mutation 零物化、kill 在 apply 前后收敛、filter policy 透传、lineage 派生一致性断言、`register_principal_owner` 幂等；0.6.1 wheel 两次 clean build 一致 + candidate manifest；Host `pyproject`/`vendor` pin + 错误 hash fail-closed。**本 Task 只改 Memory 仓 + Host pin**；Host 侧接线（`human_memory_v7.py` 传 `supported_filter_policies`/evidence authority/首次 `register_principal_owner` 并**删除 fail-open 分支**，回归证明首条对话仍可用）放在 Task 4（与 `memory/evidence_authority.py` 同任务）。
- 现状：调查 9①②③⑤⑥；A2/A7/A8。
- 验证：Memory 全量绿；spike A2 脚本在 0.6.1 上步骤 4a 转 PASS；spike A7/A8 转 PASS；Host 侧 exact pin 回归；0.6.0 已写 DB 被 0.6.1 打开的前向行为测试。
- 依赖：Task 0（可与 Task 1–3 分兵，Memory 仓）。

### Task 4 — 终态同事务 Memory outbox、analysis_proposal、executor 与 delivery authority [S5B-AC-2] → **价值验证里程碑**
- 改动：`memory_ingestion_outbox.py`（新）、`analysis_proposal.py`（新）、`analysis_executor.py`（新）、`human_memory_v7.py`（`supported_filter_policies`、evidence/delivery/action authority 注入、首次 `register_principal_owner`、删 fail-open 分支、job runner 装配，`lease_seconds > analysis deadline + 余量`）、`foreground_queue.py`（同事务 outbox 行含 lineage hash + evidence links）、`main.py`（worker 生命周期）、`memory/evidence_authority.py`（新，Host state.db 解析器）。
- 现状：调查 4/5/9④⑤⑥；A1/A6 PASS；idempotency specialist 设计。
- 修改方式：① `record_sdk_terminal` 钩子：本 turn group 的 sanitized evidence ids + `model_config_hash=sha256(canonical{provider_id, incarnation, config_revision, model_id, model_params, endpoint_identity})` → outbox(pending) + links；② worker：lease claim → 复用 Host 已 durable 的 envelope/receipt（不重新封装）→ `ingest_committed_evidence(..., analysis_lineage)` → receipt 回写 Host 事件；失败 retry_delays → dead_letter；③ `HostMemoryAnalysisExecutor.analyze_memory(request)`：`request.run_id` → binding → adapter（不可重建 → `not_sent(binding_unrebuildable:*)`）→ lineage 校验 → `RunBoundInvoker.invoke(purpose=analysis, request_hash=request.request_hash, evidence_set_key, members)` → `analysis_proposal` 派生/编译（base_revision 由 0.6.1 端口）→ envelope；④ delivery authority 与 builder 同一对象，从同一 attempt store 校验；⑤ `DurableMemoryJobRunner` 由 Host 后台任务驱动；finalize 异常 → dead-letter；任一成员 open handed_off/sent_unknown → 拒绝再投递；`sent_unknown` 终态 = dead_letter + `memory.analysis.blocked`。
- 验证：deterministic executor 下 lane `memory-mutation-plan` 六 seam + 新 seam（≥2 op、audit_pending 卡死、reconciliation observer、lease-reclaim in-flight、membership growth）；attempt 五态与 UNIQUE；Memory 不可用 → dead-letter + raw 守恒；duplicate outbox 投递 → 同 receipt；**里程碑真实车道** `test_s5b_milestone_real_provider.py -m real_provider`（0.6.1 上）：README 版本改写 → 一个 Run、closure receipt、outbox delivered、analysis applied **且物化**（cognitive head + `memory.cognitive.committed`）、下一轮 typed recall 读到、Provider 计数 = 1 主 Run + ≤1 closure + 1 analysis。
- **里程碑执行**：deterministic 先行 → 真实 provider → demo 给用户 + 矛盾转化再分析（RUNLOG）。
- 依赖：Task 3、Task 4a。

### Task 5 — Memory 0.6.1 余项、pre-admission audit 与 cutover receipt [S5B-AC-6③④]
- 改动：可选 `AnalysisExecutorPermanentError`；`pre_admission_audit.py`（新）+ Harness 拒绝点接线；testcase runner/fixture `BLOCKED_UNTIL_S5` 翻转（`behavior_changes`）；Memory 0.6.1 独立 cutover 子项（schema version 声明、前向打开测试、pin/hash 回归、cutover receipt）。
- 验证：pre-admission audit 行 + TC-HM-08 关系 malformed wire 用例；cutover receipt。
- 依赖：Task 4a（Memory 仓，可与 Task 4 真实车道并行）。

### Task 6 — Prospective 唯一 scheduler、occurrence 生命周期与 `prospective_ack` [S5B-AC-4]
- 改动：`prospective_scheduler.py`（新）、`prospective_ack.py`（新）、v46 四表、`human_memory_v7.py`（`prospective_signal_authority`）、`context_authority.py`（inbox 消息携带 occurrence_key；投影只读）、`foreground_queue.py`（终态钩子 settled(acknowledged)）、`main.py`（tick 任务）。
- 现状：调查 4、9⑫；A5/A11。
- 修改方式：① outbox 消费 = 单事务写 `prospective_scheduler_registrations(state=received)` + 游标；② 以 outbox_id 派生的确定性 signal 身份（signal_id/receipt/nonce/operation_id = stable hash；observed_at = durable received_at）发 `REGISTRATION_ACCEPTED` → state=accepted（`prospective_signal_replayed` 仅在重读 Memory 注册状态后视为已接受）；同法消费 invalidation 行；③ tick（Reminder 双检）：到期/事件 → `apply_prospective_signal(TIME_DUE|EVENT)` → 从 **inbox** claim `prospective_occurrences(claimed)`；④ snapshot reconcile 读到 pending → `presented`（同事务与 snapshot receipt；**不写** `occurrence_presented`）；⑤ `prospective_ack` handler 单事务：key ∈ presented → acknowledged → `occurrence_presented` 投影行 → `prospective_ack_invocations` 幂等；ack 轮终态提交 → settled(acknowledged)；未调用/拒绝 → 保持 presented，下一轮继续注入；⑥ settled(superseded|expired|suppressed) 由 inbox/outbox 事实（lifecycle 非 presentable、suppressed、invalidation 行）在 tick 内派生，需要门投影者同事务写；suppressed 永不写投影；⑦ Memory 侧 triggered→completed 只由 ack 轮的 analysis plan 产生（Task 7 目标）；递归意图按一次性到期（backlog）；presented-never-acked 的有界重现规则写入设计冻结。
- 验证：lane `prospective-occurrence` 四 kill 点按映射（registration_commit = Host tx(received+cursor) → Memory ack tx → Host tx(accepted)；occurrence_commit = Memory trigger tx → Host claimed；snapshot_commit = snapshot receipt+presented 一 tx；ack_commit = 调用行+acknowledged+投影 一 tx）；同 revision/event 恰一 occurrence；无 REGISTRATION_ACCEPTED → `registration_not_live` 被拦；invalidation 后零触发；重复 outbox 投递幂等；ack 重放同 receipt；suppressed 不入 Context；真实 provider 场景 S5B-S5（模型调用 `prospective_ack`）。
- 依赖：Task 4a/4。

### Task 7 — 即时 remember / correct / forget [S5B-AC-5]
- 改动：`tools/memory_tools.py`、`tool_catalog/providers.py`、`human_memory_v7.py`（`memory_action_authority`）、`analysis_executor.py`（高优先 job）。
- 修改方式：`memory_write(kind=remember|correct, statement, evidence_ref)` → 先写 Host evidence → outbox 行 `priority=immediate` → worker 立即触发 analysis（同 executor/账本）；`memory_forget(target)` → `memory_search` 的 exact memory ref → Host `MemoryActionAuthority` → `MemoryManager.suppress` → receipt durable 后返回。
- 验证：TC-HM-07 步骤 1–3 自动化（记住→typed recall 可见→忘掉→六路读取不可见→raw 守恒）；载荷变异 fail-closed；真实 provider S5B-S6。
- 依赖：Task 4a/4。

### Task 8 — effect gate hardening、Auto `explicit_only`、composition、v46 cutover 与遗留义务 [S5B-AC-3 其余/AC-6①②⑤]
- 改动：`effect_gate.py`（完整 reason-code 表：sticky memo、S4 码集含 inode/canonical、`workspace_binding_receipt_superseded` strict、confirm-only）、`tool_authority.py`/`permissions/runtime.py`（`decide()` 接 `explicit_only`，auto 下 `_CONFIRM_ONLY` → REQUIRE_USER）、`main.py`（逐项注入 + 缺件 startup fail + epoch v46）、cutover 测试（v46 前向、旧 runtime 拒 v46、rollback drill、**迁移前置：无非终态 foreground Run/无 WAITING SDK Run + 旧 checkpoint 恢复稳定隔离测试**）、S1 真实车道断言 + transcript dump、lint 小项、S4 P2（effect gate durable 正向判定；oracle pin 口径统一进 spec）。
- 验证：TC-HM-09 步骤 3–6（单 root-per-canary 口径）：Manual/Auto 追加、六类拒绝各稳定码、运行中 root 重命名/替换 → `workspace_root_unavailable`/`workspace_root_identity_drift`、Auto+DESTRUCTIVE → REQUIRE_USER、Auto+write_file → ALLOW（既有）、Auto+append_binding 无 challenge、PROJECT_EFFECT 清单逐项 EffectClass 断言；`test_composition` 逐缺件；cutover receipt；ruff changed-surface 零新增。
- 依赖：Task 6/7。

### Task 8b — 真实桌面 UI 通道重建与预演 [S5B-S8]
- 按交接 §6.3 重建 identity_harness / shim_proxy / tauri_shim（ignored 工具目录），在 S5B-S1 之前跑通 1 turn 真实 provider 预演并存证；失败 → BLOCKED 升级（不以 headless 替代）。
- 依赖：Task 4（里程碑后即可开始，与 Task 5–8 并行）。

### Task 9 — 验收矩阵、机器门与文档回写 [全 AC]
- S5B-S1…S8/REG 执行（真实 provider ≥2 root，其一 ≥20 turn；真实桌面 UI 经 Task 8b 通道）；验收按三条链分 lane 先后 record-run（effect/closure → memory analysis → prospective/即时）；机器门 `compile-manifest → init → record-run --exec → attach-evidence → re-attest → full-audit → finalize`；三仓文档回写（**在最后一次全量前完成**）；journal/retro。
- 依赖：Task 8/8b。

## 执行模式自决
集中兵力串行：Task 0→1→2→3 共享 `foreground_queue.py`/`main.py`/`sdk_adapters` 文件簇且强顺序依赖；**Task 4a（Memory 仓）与 Task 1–3 分兵并行**（文件不相交），Task 4 汇合；Task 5/8b 在里程碑后与 Task 6/7 分兵，Task 8/9 收口。

## Assurance / 信任与失败边界
见 `assurance-contract.json`；执行期硬约束沿用 program（原始证据不删、凭据不落盘、`.local-test-evidence` 不提交、不 push/tag、不改 SDK）。

## 停止追踪点
S6 UI；HM-AC-8 质量门（人工语料）；SDK 0.8 tool_calls；多 root selection；Prospective 递归意图；WeMM COS 上传；系统通知交付；Memory 侧 triggered→completed 的非 analysis 路径。
