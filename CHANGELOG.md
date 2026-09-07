# Changelog

## [0.6.22] - 2026-09-07（遗忘只针对记忆：补齐 duplicate-source 路径）

- 基于 0.6.21。`_resolve_suppression_snapshot_unlocked` 仅对记忆候选调用 `duplicate_source_matches`：MEMORY 范围指令的重复来源别名仍可拒绝重学的记忆，但不再拒绝来源对话证据（原生 r6 发现 0.6.21 仍经此路径隐藏会话）。cut/proof 机制不变。
- duplicate-source 三个测试文件按新口径改写（19+ 项），全量 63 failed / 1510 passed 与基线一致。仅本地候选，未发布。

## [0.6.21] - 2026-09-07（遗忘只针对记忆候选）

- 基于 0.6.20。用户 09-07 产品决定：忘记一条认知记忆只抑制该记忆（typed recall、图谱、工作记忆、记忆读取），**不再**隐藏其来源对话证据。`_resolve_suppression_snapshot_unlocked` 对 evidence 候选不再纳入反向 MEMORY 目标；EVIDENCE/SUBJECT/ENTITY 指令行为不变，撤销与原始字节保留不变（源码与测试改写随 `4bd11cc` 提交）。
- 11 项既有测试按新口径改写（含 3 项同因回归），新增 `test_manager_memory_forget_keeps_evidence_visible_and_evidence_forget_hides_it`。无 DDL、无公共 DTO/hash 域变化。仅本地候选，未发布。

## [0.6.20] - 2026-09-07（typed recall 中文词法门修复候选）

- 基于 0.6.19 源 e27003c6。typed recall 候选门与 confirmation 门的查询切词改用 `features.lexical.typed_recall_query_terms`：保留原 `\w` 词项，新增 CJK 二字组合。此前 `\w` 已匹配汉字，中文查询只按标点断成整句并要求在 payload 中逐字出现，导致中文长期记忆在无 entity/scope/时间约束时全部被 `recall_no_eligible_memory` 丢弃（Host 语料 C01-10 真实运行复现，spike 验证修复后召回命中）。
- 无 DDL、无公共 DTO/hash 域变化；向量通道 `cognitive_vector_unavailable` 与短期 `[\w]+` 切词未改。新增 3 项中文正/负控测试。仅本地候选，未发布。

## [0.6.19] - 2026-09-07（Procedure 与本轮输入共同候选）

- 基于实际0.6.18源码d8d80d5c，整合已审Procedure目标/观察prepare恢复、DRAFT发现及精确历史binding；新增操作观察供Host独立审计。
- 本轮完整USER输入公开检查保留完整principal、真实Host来源与用途；当前项例外不传播到其它历史或Procedure草稿。混合批次请求hash接受exact草稿binding，原域与旧项hash不变。
- 保留0.6.18全部106根导出，新增12个公共导出；Memory无新DDL。旧0.6.18制品不改写，安装及原生验收独立记录。仅本地候选，未发布。

## [0.6.13] - 2026-09-06（独立 typed-short 来源候选）

- 新增 public resolve_typed_short_horizon_sources，以 durable selected typed item 四元组
  在同一当前可见性事务中返回完整短期来源 refs；认知/非 selected 不给 refs。
- 保留旧 standalone source port、DTO wire、hash、DDL 和冻结0612；新 request/binding hash 域分离。
- 精确校验当前 owner，复用 suppression/disclosure/expiry/registration lineage；不代替 Host 最终出站校验。
- cd1ea1a source 已独立限定 ACCEPT；仅本地后继候选，不 push/tag/release。

## [0.6.12] - 2026-09-05（独立凭据误报窄修候选）

- 保留已审0.6.11 privacy/OA1/retry能力，仅修正五个已确证公开完整词元被凭据前缀扫描误报。
- 原有凭据格式、无分隔符拒绝、阈值、其它扫描及S1/subject/suppression门保持；不改公共API/DDL/旧receipt或archive。
- 160项限定source及真实旧native三库副本Host factory page红绿已通过，固定ce1a85b独立scoped ACCEPT；本候选installed/native另验，不push/tag/release。

## [0.6.10] - 2026-09-05（独立 duplicate-source privacy 候选）

- 保留冻结069能力，新增已独立审的 Host source origin/cut 公共契约与跨 history/ordinary/typed/short/mutation/background 共享当前 suppression 检查。
- memory-only forget 覆盖同 subject 的完整 USER /text 精确重复及真实来源血缘；新 atomic source 依原 cut 判定，旧 v1 无 cut/legacy 晚入队明确不可验证。
- 不改 schema、旧快照、既有 hash 或冻结069轮子；仅隔离候选，不 push/tag/native。Host late-enqueue 收尾及原生闭环独立验证。

## [0.6.7] - 2026-09-05（独立 short 候选）

- 保留0.6.6 history/clock/rejection，新增已独立审查的 exact standalone short history carrier。
- 同一 public history batch 核验实际 audit 选中、当前来源/subject/disclosure/expiry 及反向 suppression。
- 原0.6.6及旧快照/wheel保持冻结；本版本仅候选，未push/tag/release，Host接线另验。

## [0.6.6] - 2026-09-05（独立组合候选）

- 合并0.6.3基线的 history visibility 完整修复、0.6.4公开可信clock及0.6.5限定拒绝见证；普通历史可见性以当前SDK反向suppression和source状态为准。
- 新增五项history根导出与0.6.6 API快照；保留所有旧快照、schema v7.1、typed v4 hash和原数值阈值。
- 不替换冻结0.6.3/0.6.5 artifact，不合main/tag/push；本候选的源码、wheel与最小installed验证另见history increment候选记录。

## [0.6.5] - 2026-09-05（S3 候选访问前拒绝见证）

- `execute_typed_recall` 的类型、ownership、narrowing 和精确幂等冲突保留原异常，附加不可变 `TypedRecallRejectionV1`，绑定本次 invocation 与可合法计算的 request/context/plan hash。逻辑零表示未进入候选访问，不是 SQL 条数，也不声称没有 admission 写入。
- 数据库故障、损坏、取消、timeout 和候选访问后的异常不获得此见证；没有新增账本、授权 token 或全局 last-error 槽。
- Manager/backend 增加严格 `harness_protocol=4` 入口，未知版本在 backend 操作前拒绝；默认调用保留旧 backend 参数集合、原 v4 hash 和 schema v7.1。
- 新增 30 条专项回归，全量 1157 passed / 9 skipped，独立 source review ACCEPT；本分支仍为 S3 隔离候选，不替换 Host S5b 的 0.6.3。401-cell 与 program verdict 按实际验收独立记录。

## [0.6.4] - 2026-09-05（S3 公开时间依赖）

- `build_human_memory_v7` 增加可选可信构造依赖 `clock`，复用既有 backend 时钟，让 recall、page-in 和 current-use 使用同一时间源；默认仍为系统时间。请求不能通过回填时间绕过分页过期。
- 真实 SQLite 回归覆盖固定时间、关闭重开、过期拒绝、默认时钟及非法构造输入；独立 review ACCEPT。schema v7.1、根导出及旧候选快照保持。
- 本分支为 S3 隔离候选；不替换 Host S5b 已安装的 0.6.3，不代表 401-cell 或 program gate 已通过。

## [0.6.3] - 2026-09-05（S5b 恢复正确性）

- 同 principal 的后续 analysis 等待已领取批次完成物化，保留固定 plan/base_revision/evidence/hash，避免故障恢复丢失旧批次事实。
- 合法 no_mutation 保留可选 closure_reason 并以同一规则恢复；不可用响应仍被拒绝，零认知写入。
- schema v7.1 与 0.6.2 公共 API 完全一致；新增 0.6.3 快照保留旧版本谱系。独立复审接受，候选构建与 Host 验收另行记录。

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
