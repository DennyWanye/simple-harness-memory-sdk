# Changelog

## [0.6.2] - 2026-09-03（S5b Task 5：Memory 0.6.1 余项）

- **缺陷修复**（Host Task 4 真实/确定性车道发现）：多 evidence 的 analysis batch 中，只引用
  **非首条** evidence 的 operation 被 `decision_evidence_refs_ordinal_invalid` 拒绝。根因：
  `prepare_analysis_application` COMMIT 后构造 decision 时，把按 batch ordinal 过滤出的
  `plan.evidence_refs` 子集（如 ordinal=2）直接交给 `DecisionLedgerEntry`，而其 `_refs` 契约要求
  ordinal 恰为 1..n；异常在事务提交之后抛出，batch 卡在 `audit_pending`。修法：decision 的
  evidence_refs 按 batch 顺序过滤后重编 ordinal 为 1..n；成员集合仍由 prepare 内
  `plan.evidence_refs == request.ordered_evidence_refs` 校验，引用成员集合外 evidence 的 plan
  继续 `analysis_validator_rejected`。oracle：
  `tests/integration/test_memory_062_analysis_evidence_refs.py`。
- cutover：无 DDL 变化，schema 保持 **v7.1**（`SCHEMA_VERSION_LABEL="7.1"`，checksum 与 0.6.1
  相同并在 `tests/integration/test_memory_062_schema_cutover.py` 钉死）；0.6.1 写出的库打开不
  迁移、receipt/meta 稳定；0.6.0 写出的库（真实 v7.0 DDL）打开仍按 0.6.1 规则一次前向加列到 v7.1。
- 公共 API 快照 `tests/artifact/public-api-0.6.2.json`：根导出与 0.6.1 完全一致（不增不减）；
  `register_principal_owner`、`supported_filter_policies`、`analysis_lineage`、
  `current_analysis_apply_head()` 可达性由快照测试只读核对。
- 版本 `0.6.2`（`pyproject` 动态取 `src/simple_harness_memory/__init__.py::__version__`）；候选
  wheel `uv build --no-sources` 两次 clean build 字节一致：见 `docs/build-and-release.md`
  「0.6.2 candidate manifest」。

## [0.6.1] - 2026-09-02（S5b Task 4a：Memory 0.6.1 核心）

依据 `plans/2026-08-29-human-memory-digital-twin/increments/2026-09-02-s5b-effect-closure-memory/design-freeze.md` §8。

- `MemoryManager.build_human_memory_v7(..., supported_filter_policies=None)` 透传 backend；默认仍只认
  `credential-filter/v1`（§8.1）。
- 多 operation analysis finalize 收敛：`_read_decisions(operation_order=...)` 按 accepted plan 的
  operations 规范序比较，`decision_id`（hash）序不再作比较基准；≥2 op plan 不再卡死 audit_pending（§8.2）。
- accepted 且 `outcome=mutate` 的 analysis plan 在 `prepare_analysis_application` 同一事务内、以仓储
  单次签发的内核能力物化（复用 `apply_memory_mutation_plan` 的 compile/apply 内核）：写 cognitive
  revisions/heads、`memory_mutation_receipts`、`memory.cognitive.committed` 与 prospective registration
  outbox；`no_mutation` 不物化；replay 幂等；物化失败 SAVEPOINT 回退、plan 转 rejected
  （`analysis_materialization_rejected`）；`analysis_apply_heads` 与 `cognitive_apply_heads` 对齐到 max 后
  同步推进到 base+1。前置：backend 绑定 `evidence_authority` 与 `classification_policy`，否则保持 0.6.0
  审计-only；evidence authority 在写锁内被调用，不得回调 Memory backend 加锁读（§8.3）。
- `MemoryManager.register_principal_owner(principal, scope) -> PrincipalRegistrationReceipt`：幂等登记
  属主 deployment/household（修正 ingest 占位形状）；登记后 outbox/inbox/短时域读取不再
  `short_horizon_principal_rejected`（§8.4）。
- `AnalysisLineage(provider_id, model_id, model_config_hash)`（包根导出）；
  `ingest_committed_evidence(envelope, receipt, *, analysis_lineage=None)` 逐 evidence 持久到
  `evidence_envelopes.analysis_lineage_json`；回放给出不同血缘或事后补写 →
  `evidence_lineage_replay_conflict`。`claim_analysis_batch` 从成员派生 request 的
  provider/model/config_hash，成员不一致（含部分缺失）→ `analysis_batch_lineage_differs`，全部缺失
  回落 `MemoryJobWorkerConfig`（15 字段仍必填）（§8.5）。
- `AnalysisBatchClaim.analysis_apply_head: int`（仓储必填 kw_only）：claim 时只读
  max(analysis head, cognitive head)，缺省 1；`DurableMemoryJobRunner` 在调用 executor 期间经
  contextvar 暴露，Host 用 `core.jobs.current_analysis_apply_head()` 填 `plan.base_revision`（§8.6）。
- schema v7 → **v7.1**（`SCHEMA_MINOR_VERSION=1`、`SCHEMA_VERSION_LABEL="7.1"`；主版本 7 与
  receipt CHECK 不变，小版本由 DDL checksum 编码）。规则：0.6.0 写出的库（meta checksum ==
  `SCHEMA_CHECKSUM_V7_0` 且无新列）打开时在一个事务内 `ALTER TABLE` 加列并把
  `initialization_receipts`/`schema_meta` 的 checksum 与 receipt_hash 重算为 v7.1 值，之后按 v7.1
  checksum 校验；新库直接按 v7.1 建；未知 checksum 仍 fail-closed。
- 公共 API 快照 `tests/artifact/public-api-0.6.1.json`：0.6.0 根导出全部保留，仅新增
  `AnalysisLineage`、`PrincipalRegistrationReceipt`。
- 候选 wheel `uv build --no-sources` 两次 clean build 字节一致：见 `docs/build-and-release.md`
  「0.6.1 candidate manifest」。

## 0.6.0（S5a 消费面定稿，2026-09-02）

- 包根导出 jobs 消费符号（`DurableMemoryJobRunner`/`MemoryJobWorkerConfig`/`WorkerRunOutcome`）。
- 新增只读 occurrence inbox / outbox 投影（`OccurrenceInboxEntryV1/PageV1`、`OutboxEntryV1/PageV1`）：
  `(occurred_at, event_id)` 排序键在形内、当前 head lifecycle_state、suppressed 标志（memory-scope
  suppression 指令联查）、principal fail-closed；Host reconcile 门的冻结 consumer contract。
- `build_human_memory_v7` 拒绝 hash/mock embedder（`allow_development_embedder` 显式豁免）。
- 修复 `[tool.uv.sources]` 路径；候选 wheel 双 clean build 字节一致
  sha256=62a3f63cadd7796b1e86e57a9dce2bffc773b3da2ef3e78ba5002fea50f822ff。

## [0.6.0] - 2026-08-30

### Human Memory foundation

- Added the fresh `human-memory-v1` evidence, audit, suppression and durable analysis repositories.
- Removed the regex fact extractor implementation from the production package, every production builder
  argument that could enable it, the legacy worker implementation, and Mock/SQLite recover/claim/apply/fail
  job mutation seams. Regression-only extractor/worker fixtures live under `tests/`; Harness 0.7 owns
  structured LLM analysis.
- Removed category-derived Fact half-lives and automatic Fact decay. Compatibility Fact rows use a neutral
  explicit decay value; category is no longer retention authority.
- Removed `delete_session`, `delete_old_sessions` and `delete_all` from the 0.6 public backend and
  manager protocols. Suppression is the ordinary-use authority; immutable evidence is retained.
- Froze candidate metadata at `0.6.0` with exact Harness compatibility `>=0.7,<0.8`.

## [0.5.2] - 2026-08-25

### Changed
- Expanded the Harness dependency metadata to `simple-harness-sdk>=0.4,<0.7` after the retained
  Agent Memory v1 contract passed against the exact Harness 0.6.1 prepublish wheel. No Memory
  behavior or public API changed.

All notable changes to `simple-harness-memory-sdk` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Semantic relation memory

- Added fresh schema v7 knowledge relations with an exact canonical Semantic relation owner while preserving
  existing immutable evolution relations.
- Added strict atomic `applies_to` persistence for Semantic claim to Procedure/Prospective endpoints, including
  same-plan exact endpoint resolution, fault rollback, replay, lifecycle and restart integrity gates.
- Added the principal-scoped public committed mutation receipt view and display-only graph projection that
  excludes relation memories as nodes and removes edges when the owner or either endpoint becomes ineligible.

### Human Memory audit access

- Added the public fresh-v6 `build_human_memory_v6` manager facade, including evidence/conversation
  admission, mutation, suppression/revocation, typed recall, display graph and audit methods.
- Added resolver-backed `AuditAccessAuthorityRefV1`; direct caller-minted sealed decisions now fail
  closed. Grant/deny, replay, expiry and shared read-budget outcomes are durable hash-only events.
- Added MEMORY trace with hash-only cognitive lineage, ordinary-visible fixed aggregate metrics and
  sealed canonical state manifests with independently reproducible table roots and access-event
  binding.
- Bound the audit cursor authority hash into the initialization receipt, made public trace/evidence
  reads principal/requester-mandatory, and froze full required-table manifest coverage with explicit
  derived/global exclusions.
- Exported suppression request/decision/scope contracts and stable evidence receipt/record DTOs from
  the package root so exact-wheel consumers can use the complete Manager facade without core imports.
- Exported `InformationClassificationPolicy` and `EffectiveInformationClassification` from the
  package root; callers continue to source `PrivacyClass` and `InformationAttribute` from Harness.

## [0.5.1] - 2026-08-24

### Compatibility

- Expanded the Harness dependency metadata to `simple-harness-sdk>=0.4,<0.6` while preserving the
  Agent Memory v1 public contracts and all personal/family scope, cloud embedding, receipt, outbox,
  and message behavior.
- Added an isolated exact-wheel compatibility runner and a pinned Harness 0.4.0 CI cell. Harness
  0.5.0 remains a required pending cell until its candidate or release wheel is available; 0.5.1
  must not be published before both cells pass.

## [0.5.0] - 2026-08-23

### Observability

- Added optional shared Harness observability sinks and correlation to `MemoryManager` direct
  construction, all builders, and direct Mock/SQLite backends without changing business authority.
- Added privacy-safe structured lifecycle events for recall, committed turns, durable fact jobs and
  restart recovery, including replay, degradation, retry, dead-letter, erasure and lost-lease outcomes.
- Added bounded aggregate `diagnostics_snapshot()` health for recall stages, turn receipts, fact-job
  queues and sink counters. SQLite diagnostics select status/time/error-code aggregates only and never
  query content, payload or embedding columns.

### Packaging

- Promoted `simple-harness-sdk>=0.4,<0.5` to a base dependency so both SDKs consume the same
  import-pure observability envelope; the local sibling path source remains available for development.
- Froze the 0.5.0 public API and candidate metadata identity while retaining the 0.4.0 release record.

## [0.4.0] - 2026-08-22

### Breaking changes

- Fresh schema v4 replaces the earlier runtime schemas. Normal runtime startup never upgrades an old
  database; operators must use the explicit backup-first v3→v4 migration API.
- The public conversation adapter and duplicate Harness DTOs are retired. Consumers pass
  `MemoryManager` directly as the Harness `AgentMemoryPort`.
- Global `delete_all()` mutation is disabled; privacy operations require an explicit trusted principal
  and scope.

### Bounded retrieval and SQLite operations

- Added identity/scope-filtered external-content FTS5 indexes and bounded lexical/recent vector
  candidate decoding against the active embedding generation only.
- Added complete embedding lineage, local-only BGE loading, fail-closed production embedder
  construction, and restartable two-generation reindex with verified atomic activation.
- Added a per-database writer lease, serialized bounded checkpoints, online backups with
  schema/lineage/SHA-256 manifests, and closed-manager restore with corruption checks and atomic
  replacement.

### Agent Memory v1 / schema v4

- `MemoryManager` now directly implements the Simple Harness `AgentMemoryPort` through lazy
  imports supplied by the optional `[harness]` extra; the former public conversation adapter and
  duplicate DTO exports are retired.
- Fresh SQLite schema v4 persists deployment/household/actor/session identity, personal/family
  scope, immutable bindings, recall write fences, erasure epochs, turn receipts and tombstones.
- Session and committed-turn receipt keys are deployment-scoped, with full household/actor/session/scope
  validation on replay; different deployments may safely reuse external session and turn identifiers.
- Recall captures its erasure fence before embedding/ranking, so timeout/corruption degradation retains the
  delete boundary and stale turns remain `rejected_erased`.
- A committed turn atomically creates one receipt, the user/assistant pair, and a durable fact job.
  The leased worker performs extraction outside the write transaction and atomically applies its
  canonical snapshot with the job acknowledgement; expired claims recover at startup.
- Added principal export, scope deletion, fact forgetting and authorized family projection APIs.
  Deletion advances the erasure epoch before cascading content and prevents late replay/job
  resurrection.
- Froze the Harness-free public `share_fact(MemoryPrincipal, fact_id)` contract: deterministic replay,
  cross-principal ownership conflicts, `projection_of` provenance, and source-forget tombstone cascade;
  `MemoryOwnershipConflict` is exported at package top level for future consumers.
- Added Harness-free `remember_fact` / `read_fact` principal APIs returning exact fact IDs, with canonical
  source-event replay, persisted salience/pinned/tier metadata, ownership isolation, and no-resurrection forget.
- Scoped recall snapshot identity by deployment, including checksum-gated transactional repair of the known
  early-v4 global-key schema, and added portable POSIX/Windows fail-fast writer leases.
- Persisted principal explicit-forget action receipts keyed by deployment/source event, preserving first-result
  replay semantics, ownership/payload conflicts, restart safety, and distinct no-op provenance without content.
- Structured Agent Memory events emit opaque principal identifiers and counts/hashes only.
- Added an explicit backup-first v3→v4 migrator and public manifest import API. The approved
  four-way taxonomy suppresses tentative, terminal and deferred legacy sources with hash-only
  receipts, cascades their embeddings/facts, rebuilds aggregates from retained facts, and restores
  the verified backup on any publication fault. Runtime opening of v3 remains fail-closed.

### Changed
- `recall()` is now read-only: it no longer bumps salience or writes `last_recalled`.
  Reinforcement is available via the explicit `recall_and_reinforce()` method.
- `Embedder.embed()` / `embed_batch()` are now async (the whole retriever/recall chain
  awaits them), preparing for a cloud embedder.
- `get_embedder("auto")` no longer eagerly loads BGE-M3; it always returns the
  deterministic `HashEmbedder`. BGE-M3 remains available via the explicit `"bge"` kind.
- A corrupted `digital_twins` row now raises `MemoryCorruptionError` instead of silently
  returning an empty DigitalTwin.

### Persistence
- Fresh databases are stamped with the exact v4 schema descriptor and checksum; missing, older, newer,
  or checksum-mismatched runtime databases fail closed.
- `append_message` (including fact extraction/insert/supersede) is now atomic — a single
  transaction rolls back the message and any partially-written facts on failure.
- Added an optional `source_event_id` idempotency key on messages (partial unique index);
  re-appending the same event returns the existing message id without a duplicate row.

### Deletion & Limits
- Principal/scope privacy deletion cascades messages, source facts, vectors and pending jobs, repairs
  supersession lineage, and rebuilds the digital twin from retained facts.
- Added embedding lineage columns (`embedder_kind` / `embedding_dim` /
  `embedding_format_version`) plus a `reindex(embedder)` method that re-embeds every
  message and swaps the active embedder/retriever.
- Added size limits (`max_content_chars` / `max_db_bytes`) raising `MemoryLimitError`.

### Cloud embedding
- Added `CloudEmbedder` (async, batched, LRU-cached, retry-with-backoff, fail-closed)
  and `OpenAICompatibleClient` (httpx `/embeddings`, dimension-validated). Cloud
  embedding has no silent offline fallback — network failure raises `EmbeddingError`,
  so callers choose an explicit degradation (e.g. `HashEmbedder`).
- `get_embedder("cloud", base_url=..., api_key=..., model=..., dim=...)` wires the
  cloud embedder; `api_key` never appears in repr/log/exception.

### Privacy
- Recall and fact-extraction logs no longer emit raw query text or fact key/value
  content; they log lengths/counts only.

### Observability

- Added `memory.recall` / `memory.recall_empty` structured events (query length, hit
  count, per-source contribution) to the hybrid retriever.

### Documentation
- README quickstart restructured so the basic example runs under a plain `pip install -e .`
  (append + recall + facts); world model and BGE-M3 embedding moved to an "optional capabilities"
  section with their exact extras and weight-download prerequisites.
- Documented the default HashEmbedder as a deterministic hash pseudo-vector (not semantic);
  production semantic recall requires the `[embeddings]` extra.

### Tooling
- Added `scripts/verify_quickstart.sh`, a release gate that installs into a clean venv and executes
  the README quickstart block verbatim (no paraphrase), reporting a structured PASS/FAIL.
