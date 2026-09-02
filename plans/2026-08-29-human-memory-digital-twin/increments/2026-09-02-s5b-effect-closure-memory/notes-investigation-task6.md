# 现状调查 — Task 6 客观事件 + semantic closure（调查代理 2026-09-02，file:line 已核；Host main @ ec1cb944，SDK 0.7.1 冻结）

## SDK：TaskScopeMutationPlan（runtime/task_scope_protocol.py:261）
- 字段 :262-275：plan_id, run_id, subject, task_scope_id, base_revision, outcome, operations, closure_reason, source_turn_id, disclosure_context, evidence_refs, idempotency_key, schema_version + 派生 plan_hash（:311）。
- __post_init__ :277-312：标识符校验；base_revision 正整数；operation_id 唯一；mutate ⇒ operations 非空；no_mutation ⇒ 禁 operations 且 closure_reason 必填（≤4096B）；disclosure_context.run_id == run_id；plan 级 evidence_refs 非空。
- `TaskScopeMutationOperation` :218-231：每 op evidence_refs 非空；kind ∈ 17 种 `TaskScopeMutationKind`（:197-215，含 checkpoint.request / task.complete / resume.update）；value ≤32KiB。
- `TaskScopeMutationOutcome` :192-194 = MUTATE | NO_MUTATION（是 outcome，不是独立 DTO）。
- **SDK 无 task_scope_update tool spec / effect class**；ToolSpec 泛型（tools/contracts.py:65）。**DTO 不校验状态迁移合法性**（Host 侧）。

## SDK：ExecutionEvidence / outbox
- **SDK 无 `ExecutionEvidenceOutbox`**（全 src grep 仅 `MemoryOutboxRepository` execution/memory_outbox.py:113）。
- 只有纯 DTO：`ExecutionEvidenceKind` = provider_invocation|tool_invocation|context_snapshot|route_decision|run_terminal（runtime/evidence_protocol.py:1969-1974）；`ExecutionEvidence` :1978-1990（event_id, run_id, subject, kind, public_payload, disclosure_context, evidence_refs, idempotency_key, occurred_at）+ evidence_hash（:2013）。**SDK 从不构造它**（只有 re-export 与 1 条 conformance test）。无 reader、无 source_event_id、无 watermark。
- Host 现有全部机制：`backend/deskpet/execution/evidence_ingress.py`——`ExecutionEvidenceIngress.ingest(task_scope_id, source_sequence, evidence)` :53（source_event_id 去重 :71-86；subject 绑定 :92；(run_id, seq) 冲突 :94-100；terminal 后拒 :106-111；run_terminal 必须最后 :112-120；写 `harness.<kind>` 事件 source_event_id=`execution:{id}` :125-127）；`_advance_watermark_tx` :194-224 只跨连续 seq 推进；`authorize_terminal` :165-192 → `TerminalGateReceipt` / `TerminalWatermarkPending`（`task_scope_terminal_watermark_pending`）。
- **生产 producer 仅 RUN_TERMINAL**：foreground_runtime.py:1233-1260 合成一条 run_terminal 并 ingest+authorize_terminal（`ExecutionEvidenceKind.` 全 Host 仅此一处 :1237）。Provider/Tool/Context/Route 证据生产链零产出。

## SDK react loop：无 closure hook
- src 全 grep：无 semantic_closure / terminal_gate / dirty / continuation observation。
- 最近钩子 = no-recall sink：react_loop.py:466-494 `if not response.tool_calls:` 仅当 route_state==UNROUTED 调 `record_no_recall`；ROUTED_TASK 终答直接 `return ReActResult` → driver `_terminalize` COMPLETED。sink 只能 raise fail-closed，不能注入观察再提示。
- `signal_conversation`（kernel.py:1132-1207）只做 `conversation_user` 新用户轮 continuation；react.py:134-170 只认 kind==conversation_user 且 prepared_context 末消息必须等于当前消息；**terminal Run 拒绝 continuation**（kernel.py:1166-1169）。
- ⇒ "暂存 final 转 continuation observation 由同一主模型补 mutate|no_mutation" **在冻结 SDK 内无支持**，必须 Host 侧建：主路径 = prepare_snapshot 时注入 closure 要求（模型在终答前调 task_scope_update）；兜底 = Host post-turn Run-bound 主模型独立调用（与 Task 7 executor 同机制）。

## Host S4：recorder / store / mutation / tool 注册
- 模块 `backend/deskpet/task_scope/{store,protocol,projections,projection_sources,provisioning,search,runtime_binding_authority,workspace_bindings}.py`。
- 客观事件：`CanonicalTaskScopeStore.append_host_event` store.py:175-232 只接受 {host.turn, host.file, host.test}（:185-186）；拒私有载荷 :192；source_event_id 幂等 + hash 冲突 :203-207；event_watermark 单调 :220-224。`TaskEventRecorder` :650-663（record_turn/file/test）。**生产零调用者**（只有 tests/task_scope/test_canonical_archive.py:128-135、tests/memory/test_human_memory_service.py:270,276）。
- **dirty flags：不存在**（backend/deskpet grep 只有 harness/reconciler.py 循环布尔、session/project_binding.py:636 git-dirty）。
- `apply_mutation_plan(plan)` store.py:234-338：`validate_mutation_plan`（protocol.py:211-263，DTO↔to_json 交叉核对 `mutation_plan_object_json_mismatch`、no_mutation 需 closure_reason、disclosure 绑定、evidence_refs、private payload、plan_hash==canonical_hash）；plan_id 幂等 + hash 冲突 `mutation_plan_id_hash_conflict`（:243-249）；cas_conflict 重放重抛（:250-252）；**CAS base_revision vs task_scope_heads.current_revision**（:263-272，先写 durable cas_conflict attempt 再抛 `mutation_base_revision_conflict`）；`_verify_refs_tx` :275；写 mutation.plan 事件 source_event_id=`mutation-plan:{plan_id}` :276-286；reduce :295（`_reduce` :578-606 **不校验状态迁移合法性**）；attempt/decision/canonical_revision 行；守卫 head UPDATE :318-323；projection 重建。
- `create_checkpoint` store.py:340-396（checkpoint_id 幂等，hash 冲突 `checkpoint_id_hash_conflict`）。
- **`task_scope_update` 未注册为工具**（real_tool_manifest.json 零命中；providers.py 无 handler，`_dynamic_handlers` :258，memory handlers :375-448）。**`task_scope_mutation.py` 不存在**。
- 唯一现有 mutation 入口：`memory/human_memory_service.py:506-600 mutate_task_scope()`（idempotency_key 派生 plan_id :521-526；current_revision :528-532；attempts.plan_json 重放对账 :533-554；先 append host evidence 得 EvidenceRef :559-570；构造 outcome=MUTATE 单 op、reason_code="host_typed_mutation" :574-600）；载荷校验 human_memory_api.py:178 / s4_value_adapter.py:1020（`task_scope_mutation_payload_rejected`）。**该路径永不产出 no_mutation**。

## Host：foreground Run terminal 路径
- 组合 main.py:3086-3129（`ForegroundRuntimeExecutionAuthority`，terminal_observer=`SqliteSdkTerminalObserver` :3119）。
- 驱动 foreground_runtime.py:884-934：`_observe_with_heartbeats` :884 → `record_sdk_terminal` :921-930 → provider/tool authority `mark_terminal` :931-932。
- `SqliteSdkTerminalObserver.observe` :1114-1160：查 `task_scope_execution_ingest_receipts`，无则合成 run_terminal（:1233-1253）ingest（:1255-1259）+ authorize_terminal（:1260）；缺 scope authority → `foreground_terminal_task_scope_authority_missing`（:1201-1203）；`resolve_host_terminal` :268-291。
- 既有 terminal 门 foreground_queue.py:1853-1930 `record_sdk_terminal`：①`foreground_terminal_sdk_evidence_missing`（:1856-1865）②`foreground_terminal_scope_mismatch`（:1866-1871）③`foreground_terminal_gate_pending`（terminal_gate_receipts ⋈ run_watermarks，durable≥terminal 双重 :1872-1888）④evidence/generation/state 一致性（:1889-1919）。
- Host `KernelTerminalLifecycle`（harness/kernel_terminal.py:41-293）：`_finalize` :90、`_notify_terminal` :44、`terminal_commit_extensions` :118-158、`_cleanup_after_terminal_commit` :241——**暂存 final 可被拦截的 Host seam，现无 closure 检查**。
- `occurrence_presented`（037 v45 :72-83；append-only+单调触发器 :93-110）：读 `context_authority.py:539-551 presented_occurrence_keys()`；消费者 = snapshot reconcile（:878-883 → `_pending_occurrence_message` :686-703）与 `record_no_recall`（:960-964）；migrator.py:845 注册恢复；测试 test_s5a_acceptance_matrix.py:528、test_no_recall_gate.py:479。

## 迁移 v36–v45 表（backend/deskpet/memory/migrations/）
- 028 v36：task_scopes(:15)、**task_scope_events**(:24；source_kind∈{host,harness,mutation}，source_event_id UNIQUE，UNIQUE(task_scope_id,event_sequence))、steps(:42)、evidence_links(:55)、mutation_decisions(:70)、mutation_attempts(:83)、canonical_revisions(:96)、**task_scope_heads**(:110；current_revision,event_watermark,state_hash)、**checkpoints**(:120)、projection/search outbox(:132-176)、**execution_ingest_receipts**(:177)、**run_watermarks**(:192；durable_source_sequence,terminal_source_sequence)、**terminal_gate_receipts**(:201)；append-only 触发器 :213+。
- 031 v39 projections；032 v40 search；033 v41 foreground queue（foreground_turns/runs/run_sdk_bindings/run_heads/lease/control_intents/signal_outbox/signal_acks/terminal_receipts）；034 v42 recovery；035 v43 quiescence；036 v44 execution（preparation_drafts/start_intents/start_observations/reconciliations）；037 v45 context route ledger（context_route_decisions/run_context_snapshot_receipts/context_route_tool_invocations/occurrence_presented）。

## 既有测试
- mutation/CAS/幂等：tests/task_scope/test_canonical_archive.py:126,139,167。
- ingress/watermark/terminal gate：test_canonical_archive.py:211-238；tests/execution/test_foreground_queue.py:20-22,298,323,687-704；test_recovery_fence.py。
- closure/occurrence/no-recall：test_no_recall_gate.py:420,479,485,538；test_context_route_authority.py:214-241；test_s5a_acceptance_matrix.py:489,528。
- **无任何测试提及 dirty / semantic_closure / semantic_closure_pending / evidence outbox**。
- oracle：**TC-HM-11 rev5 步骤 5** 为 Task 6 直接口径（客观事件不经 LLM 入账；closure gate 以合法 mutation 或显式 no_mutation 收口，可重试不伪造）；HM-TO-R8 由 TC-HM-02/08/11 承载；fault lane `foreground-fifo-closure`（seams: message-commit, run-admission, terminal-watermark, objective-event-commit, semantic-closure-commit, projection-commit）runner `backend/tests/faults/test_foreground_fifo_closure.py` **不存在**。

## Gap 汇总
1. SDK 只有 DTO；outbox/reader/watermark/task_scope_update/closure hook 全需 Host 建。
2. Host watermark+terminal gate 已强制但只有 run_terminal 一种证据 ⇒ Harness 证据水位在 seq=1 平凡满足。
3. TaskEventRecorder 零生产调用。
4. 无 dirty flags、无 task_scope_mutation.py、无 task_scope_update 工具、无 semantic closure 水位、无"暂存 final → continuation"路径（SDK 在 terminal 拒 continuation）。
5. 只有 mandatory occurrence 水位有真 fail-closed 实装，且只能阻断不能再提示。
