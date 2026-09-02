# 中文摘要（Spike A2：exact Memory 0.6.0 wheel 上由 Host 驱动 DurableMemoryJobRunner）

- 结论：**部分成立**。步骤 1/2/3/5/6 通过：Host 可用自带 authority 构建 v7、`ingest_committed_evidence` 产生 job+outbox、`run_once` 到 APPLIED（executor 恰一次、delivery 校验恰一次）、第二次 IDLE、`apply_prospective_signal` 产生一条 matched occurrence。
- 步骤 4a **失败**：runner APPLIED 后 `cognitive_memory_heads=0`、无 prospective registration outbox——0.6.0 只审计/接受计划，不物化记忆；Host 另行调用 `apply_memory_mutation_plan` 后才出现物化与 registration outbox（4b 通过）。
- 两个实现者必知的坑：① 物化路径依赖 `evidence_authority.resolve_admitted_evidence`；② Host principal 行形状（deployment/household）在首次 caller-principal 写之前会被 `read_outbox`/`read_occurrence_inbox` 拒绝（`short_horizon_principal_rejected`），这正是 S5a fail-open 兜底的根因。
- 其它 API 事实：delivery authority 必须与 builder 绑定的是同一对象；`MemoryJobWorkerConfig` 15 字段无默认；plan.turn_id 必须等于 `_stable_id("analysis-batch-turn", batch_id)`。

（以下为子代理原始英文报告，保留作证据）

# Spike A2 — Host-side composition drives `DurableMemoryJobRunner` on the pinned Memory wheel

Environment (verified via `importlib.metadata`, real site-packages install, not editable):

- interpreter: `/Users/taiwan/PROJECTS/SimplaHarness/simple_harness/backend/.venv/bin/python` (CPython 3.12.14)
- `simple-harness-sdk==0.7.1`, `simple-harness-memory-sdk==0.6.0`
- no repository file and no SDK source touched; nothing pip-installed

## Command

```
cd /private/tmp/claude-501/-Users-taiwan-PROJECTS-SimplaHarness/84cdd128-88f2-4c7d-9db9-64a64b8ed54e/scratchpad/spike-a2
/Users/taiwan/PROJECTS/SimplaHarness/simple_harness/backend/.venv/bin/python spike_a2.py
```

Exit code 0. Full stdout in `run_final.log`; DB left at `spike_a2_1788343612.db`.

## Actual stdout (structlog info lines removed)

```
[PASS] step 1: built v7 manager; backend=SQLiteHumanMemoryBackend; db=spike_a2_1788343612.db
  probe: Host principal rejected: short_horizon_principal_rejected; switching to placeholder principal
  principals rows: [('deskpet-local-owner-v1', 'deskpet-local-owner-v1', 'deskpet-local-owner-v1', 'deskpet-local-owner-v1')]
[PASS] step 2: ingestion_receipt=EvidenceIngestionReceipt; jobs=[('evidence-mutation-job-9b55…', 'pending', 0)]; outbox=[('memory.mutation.requested', 'pending')]
[PASS] step 3: outcome=applied; jobs=[('evidence-mutation-job-9b55…', 'applied', 1)]; attempt_tables=[('job_attempts', 'applied'), …]; executor.calls=1; authority.verification_calls=1; evidence_authority.resolve_admitted_evidence calls=0; llm_invocations=[('analysis-invocation-788e', 'analysis_validator_accepted', 'accepted')]
[FAIL] step 4a: runner-only: pending outbox=[]; cognitive_memory_heads=0; accepted_analysis_plans=[('analysis-batch-a14f16090236478', 1, 2, '00f80e2066a59a64')]
  4b apply_memory_mutation_plan -> outcome=committed reason=memory_mutation_committed; evidence_authority.resolve_admitted_evidence calls now=1
  principals rows after 4b: [('deskpet-local-owner-v1', 'deskpet-local', 'deskpet-local-household', 'deskpet-local-owner-v1')]
  4b: Host deskpet-local principal now ACCEPTED by read_outbox (row upgraded)
[PASS] step 4b: after Host apply_memory_mutation_plan: pending outbox=[('memory.prospective.registration.requested', 'pending', 'prospective-schedule'), ('memory.cognitive.committed', 'pending', 'memory-mutation-outb')]; registration payload keys=['command', 'memory_id', 'prospective_revision', 'registration_revision', 'schema_version', 'trigger', 'trigger_hash']; cognitive_memory_revisions(memory_id,plan_hash,accepted_plan_hash_match)=[('cognitive-memory', '00f80e2066a59a64', 1)]
[PASS] step 5: outcome2=idle; executor.calls=1
  probe: apply_prospective_signal ACCEPTED Host deskpet-local principal
  probe: read_occurrence_inbox ACCEPTED Host deskpet-local principal at end
[PASS] step 6: memory_id=cognitive-memory.. rev=1; ack=(acknowledged,prospective_registration_acknowledged); due=(applied,triggered,prospective_trigger_matched); inbox=[('matched', 'time_due', 'triggered', '提交周报', 'cognitive-memory')]; outbox_after=[('memory.mutation.requested', 'applied'), ('memory.prospective.registration.requested', 'pending'), ('memory.cognitive.committed', 'pending'), ('memory.prospective.invalidation.requested', 'pending')]; signal_resolutions=2
SUMMARY: 1 PASS, 2 PASS, 3 PASS, 4a FAIL, 4b PASS, 5 PASS, 6 PASS
```

## Per-step results

| Step | Result | Observed |
|---|---|---|
| (1) build v7 with Host-provided `analysis_delivery_authority`, `prospective_signal_authority`, `memory_action_authority`, dev embedder | PASS | `MemoryManager.build_human_memory_v7(db, analysis_delivery_authority=..., evidence_authority=..., memory_action_authority=..., prospective_signal_authority=..., classification_policy=InformationClassificationPolicy(...), short_horizon_embedder=HashEmbedder(32), allow_development_embedder=True)` returns a `MemoryManager`; `manager.backend` is `SQLiteHumanMemoryBackend`. |
| (2) `manager.ingest_committed_evidence(envelope, receipt)` for "从今以后每周五提醒我提交周报" | PASS | returns `EvidenceIngestionReceipt`; `jobs` = 1 row `evidence-mutation-job-<sha256>` state `pending` attempt_count 0; `outbox` = 1 row topic `memory.mutation.requested` state `pending`. |
| (3) `DurableMemoryJobRunner(...).run_once()` with Host fake executor returning a `MemoryAnalysisResultEnvelope` wrapping ONE prospective CREATE op | PASS | `WorkerRunOutcome.APPLIED`; `jobs.state='applied'` (attempt_count 1); `job_attempts.state='applied'`; `job_attempt_events` sequence `provider_handoff -> result_committed -> application_staged(analysis_validator_accepted) -> mutation_audit_committed -> applied(analysis_application_applied)`; `llm_invocations.output_reason_code='analysis_validator_accepted'`, validation receipt `accepted`; executor called once; delivery authority `verify_analysis_delivery` called once. `accepted_analysis_plans` row: base_revision 1, committed_revision 2; `analysis_apply_heads.revision=2`. |
| (4a) `read_outbox(principal, states=("pending",))` shows `memory.prospective.registration.requested` **after the runner alone** | **FAIL** | pending outbox is empty; `cognitive_memory_heads` count 0; the only outbox row is `memory.mutation.requested` now in state `applied`. The runner on wheel 0.6.0 does NOT materialize the plan into cognitive memory. |
| (4b) same check after the Host additionally calls `manager.apply_memory_mutation_plan(principal=host_principal, scope=MemoryScope.personal(SUBJECT), plan=<the exact plan the executor returned>)` | PASS | apply outcome `committed` / `memory_mutation_committed`; pending outbox now = `memory.prospective.registration.requested` (outbox_id prefix `prospective-schedule…`, payload keys `command, memory_id, prospective_revision, registration_revision, schema_version, trigger, trigger_hash`) + `memory.cognitive.committed`; `cognitive_memory_revisions.plan_hash` equals `accepted_analysis_plans.plan_hash` (audit lineage bridged). |
| (5) second `run_once()` is idle, no second executor call | PASS | `WorkerRunOutcome.IDLE`; `executor.calls == 1`. |
| (6) Host `apply_prospective_signal(...)` with injected `ProspectiveSignalAuthorityRef` → occurrence in `read_occurrence_inbox` | PASS | REGISTRATION_ACCEPTED (bound to outbox_id + payload_hash) → `acknowledged` / `prospective_registration_acknowledged`; TIME_DUE PENDING→TRIGGERED → `applied` / `triggered` / `prospective_trigger_matched`; inbox has exactly one `matched` entry: signal_kind `time_due`, lifecycle `triggered`, action_text `提交周报`, memory_id matches. Host resolver `resolve_prospective_signal_authority` called twice. Trigger also enqueued `memory.prospective.invalidation.requested` (pending). |

## API-shape facts the Host implementer must know

1. **Builder kwargs (wheel 0.6.0)** — `MemoryManager.build_human_memory_v7(db_path, *, analysis_delivery_authority=None, evidence_authority=None, conversation_evidence_authority=None, classification_policy=None, memory_action_authority=None, procedure_observation_authority=None, prospective_signal_authority=None, audit_access_authority=None, short_horizon_embedder=None, world=None, allow_development_embedder=False)`. Module-level `simple_harness_memory.build_human_memory_v7(db_path, **kwargs)` forwards. `:memory:` is rejected; a `HashEmbedder` (kind `hash`) needs `allow_development_embedder=True` or raises `MemoryProductionConfigurationError("memory_development_embedder_forbidden")`. The builder takes no `now=` kwarg (backend uses wall clock).

2. **Runner signature** — `DurableMemoryJobRunner(repository, executor, delivery_authority, config, worker_id, now)`; all six positional/keyword. `repository=manager.backend` works (the backend satisfies `DurableJobRepositoryPort`). `run_once()` returns `WorkerRunOutcome` StrEnum: `idle | applied | retry_scheduled | dead_letter | stale_lease`.

3. **Delivery-authority identity binding** — `delivery_authority` passed to the runner MUST be the very same Python object passed as `analysis_delivery_authority=` to the builder; the backend checks `authority is self._analysis_delivery_authority` and raises `MemoryValidationError("analysis_delivery_authority_identity_differs")` otherwise (and `..._not_bound` if the builder got none). The executor (`analyze_memory`) can be a separate object (the spike used one), but it must produce the envelope through the same authority that will later `verify_analysis_delivery`.

4. **`MemoryAnalysisDeliveryAuthorityPort`** = single async method `verify_analysis_delivery(request, envelope) -> None`. Minimal correct implementation: `envelope.verify_request(request)`, check `envelope.delivery_receipt.issuer_id == self.issuer_id`, and compare against the durable envelope the Host recorded for `(request.request_hash, request.attempt)`. Raising anything else rejects (reason `analysis_delivery_authority_rejected` → dead letter); `AnalysisDeliveryAuthorityTransientError` schedules a retry.

5. **`MemoryAnalysisExecutorPort`** (in `simple_harness.runtime`) = `analyze_memory(request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope`. It runs outside any backend transaction (asserted in spike). `request.job_id` **is the batch id**; the wheel derives `turn_id = _stable_id("analysis-batch-turn", batch_id)` where `_stable_id` = `f"{ns}-{sha256(canonical_json({'schema_version':1,'namespace':ns,'parts':[...]}))}"` — the plan's `turn_id` must be built the same way from `request.job_id` (copied from the SDK test; accepted by the validator).

6. **Result envelope recipe** — `MemoryAnalysisResult(job_id=request.job_id, run_id=request.run_id, request_hash=request.request_hash, provider_response_id=<str|None>, structured_result=plan.to_json(), input_tokens, output_tokens, cost_microunits, latency_ms)`; `MemoryAnalysisDeliveryReceipt(receipt_id, issuer_id, run_id, job_id, request_hash, result_hash=result.result_hash, attempt=request.attempt, provider_response_id, provider_response_hash=sha256(provider_response_id or "provider-response-id-null"), issued_at, host_receipt_id, host_receipt_hash)`; `MemoryAnalysisResultEnvelope(result, delivery)`. The plan inside must use `run_id=request.run_id`, `subject=request.subject`, `disclosure_context=request.disclosure_context`, `evidence_refs=request.ordered_evidence_refs`, `idempotency_key=request.idempotency_key`, `base_revision=1` on a fresh store (the runner's own apply head went 1→2).

7. **Evidence span** — the executor needs the ingested envelope + admission receipt to build a `EvidenceSpanRef` (envelope_hash, sanitized_hash, admission_receipt_id/hash, item_id, `/public_text` pointer, byte range over UTF-8, exact_quote, quote_hash, `EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1`, actor USER, provenance AUTHENTICATED_USER, support EXPLICIT_USER_ASSERTION). Read them back with `manager.backend.read_ingested_evidence(evidence_id)` (`.envelope`, `.admission_receipt`). The sanitized payload must contain `item_id` and `public_text` keys for this recipe.

8. **`MemoryJobWorkerConfig`** — all 15 fields are required, no defaults: `batch_size, idle_wait_seconds, max_batch_wait_seconds, lease_seconds, max_attempts, retry_delays_seconds, max_result_bytes, analysis_budget: AnalysisBudget(max_input_tokens, max_output_tokens, deadline_ms, max_cost_microunits), prompt_version, result_schema_version, policy_version, validator_version, provider_id, model_id, model_config_hash (64 hex)`. Gotcha: with `batch_size > pending jobs` the claim waits until `max_batch_wait_seconds` has elapsed since the oldest job under wall clock; the spike used `batch_size=1, max_batch_wait_seconds=0.0` to claim immediately.

9. **GOTCHA A — runner does not materialize memory (the substantive finding).** On wheel 0.6.0, `run_once() == APPLIED` means: LLM invocation audited, `accepted_analysis_plans` + `decision_records` written, `analysis_apply_heads` bumped, `jobs/job_attempts` = `applied`, `memory.mutation.requested` outbox row flipped to `applied`. It does **not** create `cognitive_memory_heads`/`cognitive_memory_revisions`, `memory_mutation_receipts`, nor emit `memory.prospective.registration.requested`. The designed bridge (evidenced by the audit-lineage SQL joining `cognitive_memory_revisions.plan_hash = accepted_analysis_plans.plan_hash`) is a caller-principal `manager.apply_memory_mutation_plan(principal=, scope=MemoryScope.personal(subject), plan=<same MemoryMutationPlan>)`. That call succeeded (`committed`), produced the prospective registration outbox row, and its revision's `plan_hash` matched the accepted analysis plan. The Host therefore must keep (or re-derive) the exact plan the executor returned and apply it after the runner reports APPLIED. This path invokes `evidence_authority.resolve_admitted_evidence` (count went 0→1), so the Host's `evidence_authority` must resolve an `AdmittedEvidenceAuthority(envelope, receipt, EvidenceItemAuthority(...))` for the span; the runner path itself never called it.

10. **GOTCHA B — principal row shape.** Ingest / analysis paths insert `principals(principal_id=subject, deployment_id=subject, household_id=subject, actor_id=subject)` (DO NOTHING on conflict). `read_outbox`, `read_occurrence_inbox` (and short-horizon paths) authorize by exact match of `(actor_id, deployment_id, household_id)`, so the Host's `local_memory_principal()` (`deskpet-local` / `deskpet-local-household` / `deskpet-local-owner-v1`) raises `MemoryOwnershipConflict("short_horizon_principal_rejected")` until some caller-principal write has run. `apply_memory_mutation_plan` is the only path with `ON CONFLICT ... DO UPDATE` that upgrades the placeholder row to the caller's deployment/household. After 4b the Host principal was accepted by `read_outbox`, `apply_prospective_signal`, and `read_occurrence_inbox`. Before that, a placeholder principal `MemoryPrincipal(subject, subject, subject, session)` works for reads. `apply_prospective_signal` itself only checks `scope.authorize(principal)` (actor/scope), not the principals row.

11. **Prospective signal injection (step 6)** — `ProspectiveSignalIntent(... target_memory_id, target_revision=1, signal_kind, trigger=ProspectiveTimeTrigger(at, tz), scheduler_registration_ref, registration_revision=1, signal_receipt_id/hash, observed_at, transition_from/to, outbox_id, outbox_payload_hash, run_id, operation_id)` → `issue_prospective_signal_authority(intent, authority_id=, issued_at=, expires_at=, nonce=, issuer_ref=)` → `ProspectiveSignalAuthorityRef.from_authority(grant)`; the Host's `prospective_signal_authority.resolve_prospective_signal_authority(ref)` must return the grant by `ref.authority_id`. `REGISTRATION_ACCEPTED` needs `outbox_id`/`outbox_payload_hash` from the `memory.prospective.registration.requested` entry (`OutboxEntryV1.outbox_id`, `.payload_hash`; `payload["memory_id"]` gives the memory id, no raw SQL needed). `TIME_DUE` PENDING→TRIGGERED produced the `matched` inbox entry. Only time triggers were exercised; the user text implies recurrence ("每周五") but the wheel exposes only `ProspectiveTimeTrigger` / `ProspectiveEventTrigger` — recurrence modelling is out of scope here.

12. Reason codes observed: `analysis_provider_handoff`, `analysis_result_committed`, `analysis_validator_accepted`, `analysis_mutation_audit_committed`, `analysis_application_applied`, `memory_mutation_committed`, `prospective_registration_acknowledged`, `prospective_trigger_matched`, `short_horizon_principal_rejected`.

## Verdict on assumption A2

**Partially holds — holds with one required Host-side addition.**

- Steps 1, 2, 3, 5, 6 pass exactly as assumed on the pinned wheel: a Host composition can build v7 with its own authorities, ingest evidence to produce the job + outbox row, drive `DurableMemoryJobRunner` with a Host executor and Host delivery authority to `applied` (job and job_attempts states), stay idle on the second run, and inject prospective signals that surface in the occurrence inbox.
- Step 4 as literally stated (registration outbox appears after `run_once()` alone) is **false** on `simple-harness-memory-sdk==0.6.0`: the runner only audits/accepts the plan. The Host must additionally call `manager.apply_memory_mutation_plan(principal, scope, plan)` with the same plan the executor returned; then the `memory.prospective.registration.requested` outbox row appears and audit lineage links to the accepted analysis plan. This also resolves the principal-row shape issue for subsequent reads.
- Net: `MemoryAnalysisExecutorPort` + `DurableMemoryJobRunner` are usable from the Host as assumed, but the plan the Host designs must include a "materialize accepted plan via `apply_memory_mutation_plan`" step (and an `evidence_authority` resolver, plus a principal-shape strategy) or the prospective pipeline never starts.

Files: `spike_a2.py` (script), `run_final.log` (full stdout), `run3.log` (previous identical run), `spike_a2_<ts>.db` (inspectable sqlite state).
