# 现状调查 — Task 7 Memory analysis / outbox / Prospective scheduler / 即时操作（调查代理 2026-09-02，file:line 已核）

## 端口在 Harness SDK 0.7.1（冻结），Memory 再导入
- `MemoryAnalysisExecutorPort.analyze_memory(request) -> MemoryAnalysisResultEnvelope`（simple-harness-sdk runtime/evidence_protocol.py:2606）；`MemoryAnalysisDeliveryAuthorityPort.verify_analysis_delivery(request, envelope) -> None`（:2612，抛异常即拒；docstring :2320 receipt hash 只是审计材料非 authority）。
- 类型：`AnalysisBudget` :2066；`MemoryAnalysisRequest` :2109（job_id, run_id, subject, ordered_evidence_refs, prompt_version, result_schema_version, policy_version, provider_id, model_id, model_config_hash, attempt, budget, disclosure_context, idempotency_key + request_hash）；`MemoryAnalysisResult` :2230；`MemoryAnalysisDeliveryReceipt` :2320（request_hash/result_hash/attempt/provider_response_id/provider_response_hash/host_receipt_id/host_receipt_hash）；`MemoryAnalysisResultEnvelope` :2459（`verify_request()` :2483）；`MemoryAnalysisReceipt` :2506；`AnalysisValidationStatus` accepted/rejected/degraded :2223。

## Memory job runner（memory-sdk core/jobs.py）
- `MemoryJobWorkerConfig` :62-88 **无生产默认值**，全字段必填（provider_id, model_id, model_config_hash 64hex, analysis_budget, prompt_version, result_schema_version, policy_version, validator_version, retry_delays_seconds 长度 = max_attempts-1）。
- `AnalysisBatchClaim` :93；`DurableJobRepositoryPort` :314-390（claim_analysis_batch / register_analysis_delivery_authority / admit_analysis_delivery / discard_analysis_delivery_admission / admit_analysis_application / commit_analysis_result / reject_analysis_result / prepare_analysis_application / record_memory_analysis / finalize_analysis_application / fail_analysis_batch）——Memory SQLite backend 实现（sqlite_v5.py:10131…11738），Host 不实现。
- `DurableMemoryJobRunner` :393-575，ctor(repository, executor, delivery_authority, config, worker_id, now)；`run_once()` :414；executor 是唯一事务外调用（:429）；`WorkerRunOutcome` idle/applied/retry_scheduled/dead_letter/stale_lease :305。
- reject reason codes：analysis_executor_timeout/failed（:435,439）、analysis_envelope_type_invalid（:445）、analysis_envelope_lineage_invalid（:469）、analysis_delivery_authority_timeout/transient/rejected（:483,491,507）、analysis_delivery_public_metadata_invalid（:499）、analysis_result_private_material（:521）、analysis_result_oversize（:531）。
- repository 状态机 = 规格所述：schema_v5.py:377 `job_attempts.state` / :398 `analysis_batches.state` ∈ ('handed_off','result_committed','audit_pending','applied','failed')；表 jobs :349、job_attempts :369（PK(job_id,attempt)，request_hash,result_hash）、analysis_batches :383（request_hash/result_hash/result_envelope_hash UNIQUE）、analysis_batch_members :404、job_attempt_events :418（immutable）、analysis_apply_heads :434、accepted_analysis_plans :440。
- **`reserved`/`unknown` attempt 状态与 unknown-call taxonomy 在两个 SDK 均不存在**——Host 侧自建；Host 既有先例 = `workflows/store/schema.py:2327 execution_provider_invocations`（request_hash + attempt_ordinal，status claimed/completed/failed/unknown）+ `execution/provider_invocations.py ProviderInvocationCoordinator` :331（prepare_attempt :351，complete_or_unknown :576，_mark_unknown，ProviderDispatchUnknownError :71 / NotSentError :75）。

## 摄入入口与 outbox
- 摄入 = `MemoryManager.ingest_committed_evidence(envelope, receipt) -> EvidenceIngestionReceipt`（core/manager.py:128；port core/port.py:318；impl sqlite_v5.py:504）。单 BEGIN IMMEDIATE（:674-705）写 principal upsert、evidence_envelopes、`jobs(job_kind='analyze_evidence')`（:660-676）、outbox `memory.mutation.requested`（:678-692）；source_ref 重放同 receipt（:665）；重复 admission receipt → MemoryIdempotencyConflict（:669）。
- outbox topics：memory.mutation.requested（:686）、memory.cognitive.committed（:7252）、memory.prospective.{registration|invalidation}.requested（:9218）、suppression-rebuild（:1512）。
- 只读消费面：`read_occurrence_inbox(principal, after=(occurred_at,event_id), limit)` manager.py:275；`read_outbox(principal, states=("pending",), after=(created_at,outbox_id), limit)` :287（impl :746/:840）；DTO core/occurrence.py:34/113/141/180；`OutboxEntryV1.state ∈ {pending, claimed, applied, dead_letter}`（:159）；**consumer 永不 claim/settle**（manager.py:294）——游标/结算 authority 在 Host。
- `apply_prospective_signal(*, principal, scope, reference: ProspectiveSignalAuthorityRef)`（port.py:346 / manager.py:1159 / sqlite_v5.py:5550）。
- `MemoryMutationPlan` = Harness 类型（memory_protocol.py:2899；outcome :1885；apply receipt :3613）；Memory 编译 core/mutations.py:383；apply sqlite_v5.py:5906。
- 组合：`MemoryManager.build_human_memory_v7(db_path, *, analysis_delivery_authority, evidence_authority, conversation_evidence_authority, classification_policy, memory_action_authority, procedure_observation_authority, prospective_signal_authority, audit_access_authority, short_horizon_embedder, world, allow_development_embedder)` manager.py:404-445；backend 校验 analysis_delivery_authority 端口 sqlite_v5.py:365-372、prospective_signal_authority :415-419；`MemoryManager.backend`（:125）即 DurableJobRepositoryPort。**无专门 Host consumer 文档**，契约 = port + tests。

## Prospective（Memory 侧）
- 表 prospective_records :644、signal_authority_consumptions :1194、scheduler_registrations :1220（UNIQUE(memory_id, prospective_revision, registration_revision, state)）、trigger_events :1246（occurrence_key UNIQUE）、signal_decisions :1271、signal_results :1292；全 immutable 触发器。
- 注册/失效 outbox 投影 sqlite_v5.py:9185-9245，payload {schema_version, command, memory_id, prospective_revision, registration_revision, trigger, trigger_hash}，outbox_id=_stable_id(...)（:9209,9219）幂等键；前一 live revision 追加 invalidation（:9227-9234）。
- **occurrence claim/presented/acknowledged/settled 在 Memory 不存在**——Host 游标；`ProspectiveSignalAuthorityPort/Ref`（Harness 类型，sqlite_v5.py:70-71），resolver `resolve_prospective_signal_authority`（:416），缺 → `prospective_signal_authority_required`（:5604）。
- 故障点 `PROSPECTIVE_SIGNAL_FAULT_POINTS` :243-251（before_begin, after_begin, after_consumption, after_event, after_revision, after_decision, before_commit, after_commit）；`COGNITIVE_MUTATION_FAULT_POINTS` :202（含 mutation.after_outbox）；ingestion.after_outbox :171；suppression.before/after_outbox :180-181。

## Host ReminderScheduler（companion/reminders.py）
- `ReminderStorePort` :26-96；`ReminderScheduler` :574（ctor :577 (store, policy_provider, clock, lease_seconds=30)）；`tick(owner, claim_owner)` :608 双检设计（claim :629 后重取 policy :648-651）；`claim_delivery_outbox` :789（sink_kind=companion_notification）；`settle` :802。
- 持久化 companion DB `companion/migrations/001_companion_v1.sql`：reminders :1130、reminder_occurrences :1148（status pending|leased|delivered|cancelled|expired，claim_owner/claim_epoch/lease_expires_at/attempt）、reminder_mutation_receipts :1169、outbox :1219、jobs :1023。
- 驱动 main.py:1192 构造；`_settle_ready_reminder` :1199-1231；tick 驱动 :1241-1253；tests/companion/test_reminders.py。

## Host↔Memory 现状
- `memory/human_memory_v7.py`（382 行）唯一 v7 接线：`build_human_memory_v7` :71 **只传 short_horizon_embedder**（无 analysis_delivery_authority / prospective_signal_authority / memory_action_authority）；消费 `pending_occurrences()` :88（谓词 :118-129）与 `typed_recall()` :136。
- **fail-open 兜底** :101-119：`read_occurrence_inbox` 的 MemoryOwnershipConflict 收窄为 reason "short_horizon_principal_rejected" 且 `after is None and not pending` → 返回 ()；注释标 "S5b: 向 memory-sdk 上游补正式的属主注册 API 后移除"。
- **无 Memory 摄入 outbox**：`ingest_committed_evidence` 生产零调用（只有 tests/sdk_adapters/test_no_recall_gate.py:330、testcase adapters）。
- Host `enqueue_turn`（human_memory_service.py:778）与 Memory 无关：构造 SanitizedEvidenceEnvelope/Receipt（:818/:832，filter_policy_version=host-public-turn/v1）→ `_program.append_evidence` 入 Host state.db（:852）→ foreground_queue.enqueue_turn（:853 → foreground_queue.py:344）；`_append_host_evidence` :1664-1721（host-typed-ingress/v1）。
- `memory/product_outbox.py` 是 legacy v30 `product_memory_outbox`（022_v30.sql:28）投影 chat 消息到 `append_message`——**不是 S5b outbox**。
- **`memory/analysis_executor.py` 不存在**。
- Host 证据提交 `human_memory_program.py:627 append_evidence`（BEGIN IMMEDIATE :640；fence :641；幂等 :653-666；写 sanitization_receipts :668 + human_memory_evidence :687）。

## Host provider 调用与 Run 绑定
- `sdk_adapters/provider.py`：`_ProductOpenAICompatibleProvider` :160，`_wire_messages` :179-230（从后续 tool result 重建 assistant tool_calls；docstring :198-206 登记 S5b 上游义务）。
- `ProductProviderAdapter` :476 "One immutable provider/model/config/price snapshot for an SDK Run"（ctor :479-565；endpoint_identity :530-534；`ProviderTarget` :562）；`invoke(request, *, cancel) -> ProviderResponse` :571 ——**post-turn executor 应复用的单次调用路径**。
- Run 绑定 `sdk_adapters/run_bindings.py`：`SdkRunBindingV1` :32（provider_id, provider_incarnation_id, provider_config_revision, model_id, model_params, context_window, catalog_*, budget_fingerprint, binding_fingerprint）；durable `foreground_run_sdk_bindings`（033_v41.sql:110，binding_json+hash，append-only）；main.py:7526-7567 由 binding 构造 adapter（model=binding.model_id, model_params :7540-7541）。配置 `LLM_RUNTIME_PATH = user_data_dir()/"llm_runtime.json"`（main.py:251；loader :254）。

## terminal commit 与 Host outbox
- `execution/ports.py:204 commit_run_outcome(..., terminal_commit_extensions=(), delivery_fence, release_receipt_kind)`；UoW impl uow_ports.py:138,210,815；`TerminalCommitFenceV1` fences.py:52/63；`run_block_signals.py:171 apply_terminal_commit`。**`terminal_commit_extensions` 是把 sanitized evidence link + Memory ingestion outbox 写进同一事务的既有 seam。**
- 既有 outbox：product_memory_outbox(v30)、task_scope_projection_outbox/search_outbox(v36)、projection_source_outbox(v39)、foreground_signal_outbox(v41)。**无 Memory ingestion outbox。**
- 最新迁移 037 = v45（migrator.py:118-120）。`occurrence_presented` 全列已建（presented/settled），**缺 claim/acknowledged 列与独立 event cursor 表**。

## 即时 remember/correct/forget
- `tools/memory_tools.py` 全是 stub：`_unavailable()` :23 返回 memory_sdk_unavailable；manifest 仍列 memory_forget/read/search/write（sdk_adapters/tools.py:32,56；registry.py:137,664,677,690 system_change delete/write）。
- **Host 无 suppression 流**；只有读侧过滤 human_memory_v7.py:126。SDK 就绪：`MemoryManager.suppress`/`revoke_suppression` manager.py:162/167；core/suppression.py；故障点 suppression.before/after_outbox。读侧需观察 suppression receipt 的接线：recall_adapter.py:51,73,147,226,261；memory_facts_surface.py:65（legacy）。

## 测试/fixture
- Memory：integration/test_durable_memory_jobs_v5.py（2541 行，权威行为规格；:1816 authority retry 不二次调 provider；:2064 result commit 后 crash 不二次调；:2184；:2116；:2304 commit 边界故障矩阵；:2372；:531/571/616 伪造 delivery fail-closed；:1607/1641/1735 retry→dead-letter；:2536 config 无默认）；test_prospective_signal_repository_v5.py（:120,:247,:391-397）；test_occurrence_inbox_v6.py（:139-142）；unit/test_prospective_kernel_v5.py；test_evidence_ingestion_v5.py；test_suppression_v5.py；test_cognitive_mutation_repository_v5.py。
- Host：tests/sdk_adapters/test_no_recall_gate.py（envelope builder :106-140，ingest :330，apply_prospective_signal :373/386）；tests/memory/*；tests/test_memory_outbox_faults.py；tests/companion/test_reminders.py。
- fault-matrix 9 lanes；Task 7 直接目标 = `memory-mutation-plan`（seams raw-evidence-commit, invocation-evidence-commit, validation-decision-commit, state-mutation-commit, outbox-commit, commit-before-ack）与 `prospective-occurrence`（registration-commit, occurrence-commit, snapshot-commit, ack-commit）；`embedding-outbox-worker` 的 outbox-commit-before-ack 为新 Host↔Memory outbox lane 样板。runner_contract：非零退出 + root_run_id + before/after state hash。
- V0 spike：run_protocol_spikes.py `init_trigger` :255 / `run_trigger` :292；manifest SPIKE-CROSS-DB-TRIGGER fault_points [registration_commit, occurrence_commit, snapshot_commit, ack_commit]，required [one_occurrence_per_revision_event, pending_not_lost, snapshot_hash_replay, suppression_fail_closed]；SPIKE-RUNTIME-BRIDGE fault_points [source_commit, host_evidence_commit, receipt_commit, provider_reservation]，required [no_event_gap, no_duplicate, terminal_watermark, triple_payload_hash, same_snapshot_replay]。

## Gap 汇总
1. 两个 analysis port 零 Host 实现；analysis_executor.py 不存在。
2. ingest_committed_evidence 生产零调用；terminal→Memory ingestion outbox 链缺失（seam = terminal_commit_extensions）。
3. reserved/unknown 五态与 unknown-call taxonomy 无上游定义；镜像 execution_provider_invocations 模式。
4. occurrence_presented 缺 claim/acknowledged 与独立 event cursor。
5. ReminderScheduler 无 Memory outbox 入口；prospective_signal_authority 未传给 build_human_memory_v7。
6. remember/correct/forget 工具是 stub；Host 读侧无 suppression receipt 路径。
7. human_memory_v7.py:101-119 fail-open 待上游属主注册 API 后移除。
