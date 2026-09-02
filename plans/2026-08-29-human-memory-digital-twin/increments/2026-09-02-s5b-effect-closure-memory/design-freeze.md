# S5b 设计冻结（Task 0，写代码前；oracle 先于实现）

> 本文冻结实现所依赖的常量、表结构、状态机与 reason code。实现不得偏离；需要改动时先改本文并在 RUNLOG 留痕。
> 依据：`plan.md` 现状调查 9、challenge synthesis 决策、委托裁决 A6/A7/A11。

## 1. PROJECT_EFFECT 工具清单（`tool_authority.SDK_TOOL_EXECUTION_POLICY_OVERRIDES` 追加）

`write_file`、`file_write`、`edit_file`、`move_file`、`file_organize`、`run_shell`、`process_start`、`doc_create`、`doc_edit`、`excel_create`、`ppt_create`、`pdf_export`、`download_file`、`workspace_prepare`
→ `("project_effect", "required", "required")`。读取类（`read_file`/`file_read`/`glob`/`file_glob`/`grep`/`file_grep`/`list_directory`/`doc_read`）保持默认 `non_project_effect/optional/optional`，仍受 workspace 投影过滤。
`task_scope_update` → `("non_project_effect", "required", "required")`（direct kernel，加入 `PROJECTLESS_SAFE_TOOL_NAMES`）。
exhaustiveness 断言：清单内每个名字必须在 manifest 中存在，且每个都有冻结 EffectClass（`IrreversibleEffectPolicy.classify`）。

## 2. 客观事件映射表（确定性，禁关键词/正则）

| 事件来源 | event_kind | material? |
|---|---|---|
| 清单 1 中写/编辑/移动/整理/文档生成/下载/`workspace_prepare` 成功或失败执行 | `host.file` | material |
| `run_shell` / `process_start`，命令首 token ∈ 注册 test runner 白名单 {`pytest`, `python -m pytest`, `npm test`, `pnpm test`, `cargo test`, `go test`, `vitest`, `jest`} 且有退出码 | `host.test` | material |
| `run_shell` / `process_start` 其它 | `host.file` | material |
| 用户/assistant turn（既有 `host.turn`） | `host.turn` | trivial |
| `harness.provider_invocation` / `harness.context_snapshot` / `harness.route_decision` / `harness.run_terminal` | 同名 | trivial |
| `harness.tool_invocation`（PROJECT_EFFECT 工具） | `harness.tool_invocation` | material |
| `harness.tool_invocation`（其它工具） | `harness.tool_invocation` | trivial |

`dirty_state(scope)` = 自该 scope 最后一条 `outcome ∈ {mutate, no_mutation}` 的 closure receipt 的 `closure_watermark` 之后，`event_sequence` 更大的 material 事件集合（含 pending receipt 覆盖的事件，pending 不清脏）。

## 3. Harness 证据的同事务直写与预留（`ExecutionEvidenceIngress` 扩展）

- 表 `harness_evidence_reservations(reservation_id PK, run_id, task_scope_id, source_sequence INT, source_event_id TEXT UNIQUE, kind, status CHECK(status IN ('reserved','ingested','abandoned')), reserved_at, resolved_at; UNIQUE(run_id, source_sequence))`。
- state.db 内事实（snapshot receipt、route decision、route tool invocation）：在各自写事务内 `reserve + ingest` 同事务。
- 其它 DB 事实（SDK effect 结果、provider invocation）：先 `reserve`（拿到 seq），物理动作/SDK 提交完成后 `ingest`。
- `next_sequence = MAX(reservations.source_sequence ∪ ingest_receipts.source_sequence) + 1`。
- terminal observer 在写 `run_terminal` 前排空：对每条 `reserved`，能从 SDK DB/coordinator 读到事实则 ingest，否则写 tombstone：同 kind、`public_payload = {"status": "abandoned", "reservation_id": ...}`，status=abandoned；`run_terminal` 用排空后的 next_sequence。
- crash 后新 owner 重放同一排空（`source_event_id` 幂等）。
- source_event_id 规范：`provider:{provider_request_id}`、`effect:{effect_id}`、`snapshot:{snapshot_id}`、`route:{decision_id}`、`terminal:{sdk_run_id}`。

## 4. EffectGate 检查顺序与 reason code（全部 `ToolResult.rejected(error_code)`，effect=None）

1. `effect_gate_envelope_missing` / `effect_gate_envelope_identity_mismatch`（run/call/effect/tool 回声）
2. `effect_gate_route_receipt_rejected`（sticky memo：`effect_gate_rejections(run_id, route_receipt_id, reason, created_at)` 命中即拒，直到新 route receipt）
3. 冻结 authority 一致性：`effect_gate_frozen_scope_mismatch`（envelope.task_scope_id ≠ Run 冻结 scope）、`effect_gate_projectless_project_effect`（Run 冻结时无 exact 写根：`workspace_resolution.kind ∈ {projectless, missing}` 或无 effective_root——注意 foreground 单 root 冻结实际 kind=`legacy`+exact effective_root，`foreground_runtime_ports.freeze` 有意绕过 Session validator，Task 1 实装按此语义；修订于 2026-09-02 Task 1）、`effect_gate_frozen_root_mismatch`（verify 根 canonical_path ≠ 冻结 workspace_root）
4. `WorkspaceBindingAuthorityStore.verify_task_execution_envelope` 的 S4 码集：`workspace_binding_route_authority_missing|stale`、`workspace_binding_envelope_lineage_mismatch`、`workspace_binding_effect_authority_missing|stale`、`workspace_binding_envelope_root_mismatch`、`workspace_root_unavailable`（根被重命名/删除）、`workspace_root_identity_drift`（dev/ino 变化）、`workspace_root_not_canonical`（symlink）、`workspace_root_too_broad`
5. `workspace_binding_receipt_superseded`（strict：head.revision ≠ receipt.revision，Manual/Auto 同规则，裁决 A6）
6. `effect_gate_task_scope_not_active`（scope lifecycle ∉ {active, open}）
7. confirm-only/grant：`product_policy_user_confirmation`（`explicit_only` 由冻结 EffectClass ∈ `_CONFIRM_ONLY` 计算；Auto 下 REQUIRE_USER）——Task 6 接入
整 Run 故障（不是 rejected）：`sdk_task_execution_route_authority_missing`（standalone 路由下 PROJECT_EFFECT）、`sdk_task_execution_root_authority_ambiguous|missing`（多/零 root）、`catalog_execution_policy_unavailable`（hidden 工具）→ Host 记 durable FAILED，`run_terminal.public_payload.error_code` 携带稳定码。

## 5. v46 表（`038_effect_closure_memory_v46.sql`，全部 append-only 触发器 + 单调守卫）

| 表 | 列 | 键/约束 |
|---|---|---|
| `task_scope_closure_receipts` | receipt_id PK, task_scope_id, sdk_run_id, host_run_id, closure_watermark INT, outcome CHECK IN('mutate','no_mutation','pending'), plan_id NULL, reason_code, attempt_id NULL, created_at | UNIQUE(sdk_run_id, closure_watermark, outcome)；`pending` 之后同 scope 可有新 receipt |
| `harness_evidence_reservations` | 见 §3 | UNIQUE(run_id, source_sequence)，source_event_id UNIQUE |
| `memory_ingestion_outbox` | outbox_id PK, host_run_id, sdk_run_id, turn_id, subject, evidence_ids_json, envelope_hash, model_config_hash(64), analysis_lineage_json, state CHECK IN('pending','claimed','delivered','dead_letter'), attempts INT, lease_owner NULL, lease_expires_at NULL, receipt_json NULL, last_error NULL, created_at, updated_at | UNIQUE(sdk_run_id, turn_id)；state 单调 pending→claimed→delivered/dead_letter（claimed→pending 允许于 lease 到期） |
| `memory_ingestion_evidence_links` | outbox_id, evidence_id | PK(outbox_id, evidence_id) |
| `post_turn_invocation_attempts` | attempt_id PK, purpose CHECK IN('closure','analysis'), host_run_id, sdk_run_id, generation INT, task_scope_id NULL, closure_watermark NULL, request_hash(64), attempt_ordinal INT, evidence_set_key(64), status CHECK IN('reserved','handed_off','succeeded','failed','unknown'), unknown_class NULL CHECK IN('not_sent','sent_unknown','sent_confirmed'), provider_id, model_id, model_config_hash, provider_request_id NULL, result_hash NULL, plan_id NULL, reserved_at, handed_off_at NULL, settled_at NULL, reason_code NULL | UNIQUE(request_hash, attempt_ordinal)；状态单调 reserved→handed_off→{succeeded,failed,unknown}；reserved→failed(not_sent) 允许 |
| `post_turn_invocation_members` | attempt_id, subject, run_id, evidence_id | PK(attempt_id, evidence_id)；索引 (subject, run_id, evidence_id) |
| `effect_gate_rejections` | rejection_id PK, sdk_run_id, route_receipt_id, reason_code, created_at | UNIQUE(sdk_run_id, route_receipt_id) |
| `host_pre_admission_audit` | audit_id PK, sdk_run_id NULL, payload_kind CHECK IN('context_route','task_scope_update','analysis_result'), reason_code, payload_hash(64), created_at | — |

`occurrence_presented`（v45）不改；prospective 表族 → S5c v47。迁移前置（Task 6 cutover）：无非终态 foreground Run、无 WAITING SDK Run。

## 6. unknown-call 分类法与 invoker 规则

- `not_sent`：请求未进入传输（连接失败/超时于发送前/binding 不可重建）→ 可 attempt+1。
- `sent_unknown`：请求已发出、无响应或响应不可解析 → **绝不重发**；closure：终结为 pending(`closure_attempt_unknown`)；analysis：拒绝一切再投递 → Memory dead_letter + Host 事件 `memory.analysis.blocked`。
- `sent_confirmed`：仅经注入的 reconciliation observer（测试）确认 → 返回同一行。
- 查重顺序：`(request_hash, attempt_ordinal)` 命中 succeeded → 返回同行；任一 member 存在 open `handed_off`/`unknown(sent_unknown)` → 拒绝（0 调用）；否则新 attempt。
- closure：`request_hash = sha256(canonical{sdk_run_id, task_scope_id, closure_watermark, last_assistant_message_hash})`，`plan_id = sha256(canonical{"closure-plan", request_hash})`；`evidence_set_key = sha256(canonical{sorted material event ids})`。
- analysis：`request_hash = MemoryAnalysisRequest.request_hash`；`evidence_set_key = sha256(canonical(request.to_json() − {job_id, attempt, idempotency_key}))`。
- 仅当前 lease owner 可插 reserved 行（与 `_validate_lease_tx` 同事务）；返回后再验 lease 才 apply。
- Memory lease：`lease_seconds = analysis_budget.deadline_ms/1000 + 30`（deadline 默认 60s → 90s）。

## 7. `task_scope_update` 载荷与状态迁移表

模型填：`outcome`、`base_revision`、`operations[]{operation_id, kind, value, reason_code, evidence_refs[]}`、`closure_reason`、`evidence_refs[]`、`idempotency_key`。Host 填：`plan_id`（= sha256(idempotency_key + scope)）、`run_id`、`subject`、`task_scope_id`（admission scope）、`source_turn_id`、`disclosure_context`。
合法迁移：`{draft,active,in_progress} --status.update--> {active,in_progress,paused,blocked}`；`* --task.complete--> completed`；`completed` 之后禁止任何 `plan.*`/`status.update`（`task_scope_update_after_complete`）；`pending --no_mutation(closure_abandoned|model_no_change)--> closed` 任何 status 合法。
handler 拒绝码：`task_scope_update_scope_unbound`（standalone）、`task_scope_update_nothing_to_close`（无脏/pending，不递增 revision）、`task_scope_update_refs_outside_scope`、`task_scope_update_illegal_transition`、`mutation_base_revision_conflict`（S4 既有，可重试）。

## 8. Memory 0.6.1 API 面（六项，Task 4a）

1. `MemoryManager.build_human_memory_v7(..., supported_filter_policies: frozenset[str] | None = None)` → 透传 backend；Host 传 `{"credential-filter/v1","host-public-turn/v1","host-typed-ingress/v1"}`。
2. `finalize_analysis_application`/`_application_from_batch_unlocked` 与 `_read_decisions` 同一规范序（按 operation 在 plan 中的顺序；`decision_id` 序不再作为比较基准）；≥2 op applied 测试。
3. `prepare_analysis_application` accepted 且 `outcome=mutate` 分支：同一事务内以 repository 生成的 application capability 调用 compile/apply 内核物化（写 cognitive revisions/heads、`memory.cognitive.committed`、prospective registration outbox）；`no_mutation` 不物化；replay 幂等（同 plan_hash 不重复）；`analysis_apply_heads` 与 `cognitive_apply_heads` 统一：物化后两者同步推进到同一 revision。
4. `MemoryManager.register_principal_owner(principal: MemoryPrincipal, scope: MemoryScope) -> PrincipalRegistrationReceipt`（幂等；写/修正 principals 行 deployment/household；重复调用返回同 receipt）。
5. `ingest_committed_evidence(envelope, receipt, *, analysis_lineage: AnalysisLineage | None)`，`AnalysisLineage(provider_id, model_id, model_config_hash)` 逐 evidence 持久（`evidence_envelopes` 新列 `analysis_lineage_json`）；`claim_analysis_batch` 从成员派生 request 的 provider/model/config_hash 并断言一致（`analysis_batch_lineage_differs`）；`MemoryJobWorkerConfig` 的 provider/model/config_hash 变为可选默认（成员无 lineage 时用）。
6. `AnalysisBatchClaim.analysis_apply_head: int`（claim 时读取 `analysis_apply_heads` 当前 revision）供 Host 填 `base_revision`。
schema version：v7 → **v7.1**（新列 + 无破坏）；0.6.0 已写 DB 打开时前向加列。版本 `0.6.1`，wheel 两次 clean build 字节一致 + candidate manifest；Host `pyproject`/`vendor` pin 更新。

## 9. analysis_proposal（Host）

proposal 工具 `memory_analysis_proposal`（仅在 post-turn 独立调用中暴露）：`{operations:[{memory_type: semantic|episode|procedure|prospective, payload:{...按类型}, evidence_item_id, exact_quote, reason_code}], outcome: mutate|no_mutation, closure_reason?}`。
派生：`text.find(exact_quote)` 唯一命中 → UTF-8 byte range；`quote_hash = sha256(quote)`；pointer `/text`；`item_ordinal = 1`；`item_id` = Host delivery key；normalization `EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1`；actor USER；provenance AUTHENTICATED_USER；support EXPLICIT_USER_ASSERTION。未命中/多命中/paraphrase → 该 operation 拒绝（`analysis_quote_not_found`），全 plan 视 validator 策略。
常量：`prompt_version = "host-analysis-prompt/v1"`，`result_schema_version = "memory-analysis-proposal/v1"`，`policy_version = "host-analysis-policy/v1"`，`validator_version = "host-analysis-validator/v1"`。

## 10. A6 behavior_changes artifact（写入 verification-spec manifest）

`behavior_change_id = bc-s5b-tchm09-step6-single-root-scope`；old = TC-HM-09 rev4 步骤 6 字面"在每个 root 执行不同 canary effect"（同一多根 scope）；new = 每个 canary root 一个单根 scope 逐一执行 + ≥2 root scope 写工具不可见/强制调用 fail-closed 且 canary hash 不变；approval = 用户委托原话 sha256 `2a99dd6aabeee8485b1453b7371170bef6a04ff2990165079f31c691f4ad75f7` + 裁决文件 sha256；scope = S5b/S5c/S6；expiry = 多 root 选择协议独立验收之日。TC-HM-09 文件不改。


## 11. Task 1 实装后的冻结修订（2026-09-02）

- §4 第 3 步 projectless 判定改为「无 exact 冻结写根」语义（见上）。
- 冻结 SDK `run.failed` 只暴露 `driver_failed`：三条整 Run 故障稳定码由 Host 进程内 `RunFaultMemo`（首码优先）携带进 `run_terminal.public_payload.error_code`；进程 crash 后终态证据退回 `driver_failed`（如实标注，不伪造）。
- legacy（<v35）epoch 无 route 能力，§1 清单 14 工具在该 epoch 下稳定 fail-closed（整 Run 故障）——program 不承诺旧数据兼容，接受。
- manifest 中 `move_file/file_organize/run_shell/process_start/ppt_create` 的冻结 EffectClass 为 `unknown` → 落 `_CONFIRM_ONLY`（Task 6 Auto 下 REQUIRE_USER）。
- Task 2 oracle 追加：`test_write_file_effect_commits_execution_effect_row_and_host_file_event_same_tx`（strict xfail 直到 Task 2）。
