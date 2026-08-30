# S2 — Memory 永久证据、审计、Suppression 与 Durable Outbox

> Release unit：S2（Memory SDK）  
> 高风险子系统：fresh SQLite schema、append-only privacy/audit、worker/outbox（3）  
> 覆盖：HM-AC-1/2/7/8
> 实施进度：Task 1—6 complete；Task 5 最终提交 `83ce301` 在候选链 `71066b69`→`3929669`→`4f58793` 上完成 repository 四阶段 authority、generic/mutation audit 隔离、同 request/attempt 恢复且 Provider 不重放。Task 6 source `e316919` 已把旧 regex extractor/worker 移出 production package，断开 Mock/SQLite job mutation seam、category half-life 与 public physical delete；独立审计 P0/P1/P2=0，全仓 `493 passed, 8 skipped`。clean-commit 0.6.0 wheel SHA-256 `5011da96…`、sdist `50faa1c6…`，与 exact Harness 0.7.0 wheel `b9421ddf…` 的隔离 consumer 验证通过；该候选仅为 S2 slice evidence，program 最终 candidate 仍须在 S3 完成后重建。

## 交付边界

建立新 Memory 事实底座，不实现四类认知状态机的业务细节。旧 v4 `Message/Fact` DB 不迁移；新版本对非 fresh
schema 明确拒绝。原始业务 evidence 从第一条起永久保留，所有普通读取先经过 suppression authority。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `core/evidence.py`（新） | SanitizedEvidence receipt 验证、EvidenceSpan、ingestion receipt、source refs |
| `core/audit.py`（新） | LLMInvocationEvidence、StructuredDecisionRecord、AuditAccessDecision/trace |
| `core/suppression.py`（新） | append-only directive/revoke、purpose-bound access、deny resolver |
| `core/jobs.py`（新） | durable mutation/index/projection job contracts、lease/attempt/dead-letter |
| `core/models.py` | 删除 L1/L2/L3 注释和新协议中的 Fact authority；只保留明确的 legacy-internal 类型到移除点 |
| `core/manager.py`, `core/port.py` | 新 ingestion/suppression/audit/job API；physical delete API 不导出到新版本 |
| `backends/sqlite.py` | fresh schema v5、append-only repositories、短事务/CAS/idempotency/permission-first reads |
| `backends/base.py`, `backends/mock.py` | 与 v5 port 对齐；默认 extractor 不再实例化 `RuleBasedFactExtractor` |
| `features/facts.py`, `core/fact_jobs.py` | 退役 regex/default Fact worker；LLM 只通过 Harness strict mutation protocol |
| `tests/` | init/crash/replay/suppression/secret canary/physical-delete prohibition |

## Tasks

### Task 1 — Fresh schema v5 与唯一初始化 receipt [HM-AC-1/8]

- schema 拆出明确 DDL/checksum，至少包含：principals、evidence envelopes/items、ingestion receipts、suppression
  directives、LLM invocations、decision records、jobs/attempts、outbox、embedding lineage/generations。
- schema meta 标记 `human-memory-v1`；空目录原子初始化，重复 initialize 返回同 receipt；检测 v4/未知 schema 只读
  报 `LEGACY_SCHEMA_UNSUPPORTED`，不得 migrate/delete/overwrite。
- SQLite 启用现有 writer lock/WAL/busy timeout；初始化中断后按 journal 重试，不形成第二套 writable root。
- 验证：每个 DDL/commit 点 fault injection、concurrent init、kill/reopen、schema checksum。

### Task 2 — Evidence-first ingestion 与 credential boundary [HM-AC-1/2/7]

- `ingest_committed_evidence()` 只接受 S1 `SanitizedEvidenceEnvelope`；先验证 source/sanitized hash、filter-policy version 与
  receipt，再防御性重扫结构化 headers/env/tool/provider payload，最后单事务写 raw evidence、receipt、mutation job outbox。
- raw evidence immutable；相同 source ID+hash replay receipt，异 hash conflict。内容/hash/refs 可导出，认证材料从不
  入 DB/log/vector/LLM payload。
- 大对象保存受控 blob/ref 与 hash，不让 observability log 保存正文。
- 验证：API key/cookie/password canary 全域扫描、partial failure、replay、disk-full 保留旧行。

### Task 3 — Append-only suppression authority [HM-AC-1/7]

- forget 写 directive，支持 exact evidence/memory/entity/subject 范围与 reason；同步 deny 后再发派生 rebuild outbox。
- ordinary read/search/recall/export/projection 的 repository 入口必须强制调用 deny resolver；不提供绕过布尔参数。
- revoke 是新 decision，不覆盖旧 directive；sealed audit 使用独立 purpose-bound access receipt，不能转交普通 Agent。
- 验证：exact ID、stale cache、old checkpoint ref、rebuild failure、worker replay、revoke、审计读取再留痕。

### Task 4 — LLM invocation 与 decision ledger [HM-AC-2/7]

- 保存与 Host permanent invocation receipt 互链的 public prompt input refs/hash、public structured output、provider/model/params、prompt/schema/policy/validator 版本、
  timing/token/cost/request ID、accepted/rejected operations、before/after refs、stable reason。
- 不保存 hidden chain-of-thought；reasoning item 只保存 provider public ID/type/hash/必要 continuation ref。
- `export_audit_trace()` 按 turn/invocation/decision/evidence ID 分页组合，普通面应用 suppression，sealed 面必须 access receipt。
- 本 Task 的 generic invocation/decision ledger 只证明“调用发生及公开结果如何被验证”，不得被 Task 5 mutation worker
  当作 apply authority。会改变 Memory canonical state 的 audit 必须引用 Task 5 repository 生成的 exact
  `AnalysisApplication`、phase capability 与 application receipt，调用方自造的 receipt/decisions 即使 hash 自洽也无权写入。
- 验证：lineage 不可覆盖、分页稳定、非法 output 仍有 rejected record、普通/审计权限隔离。

### Task 5 — Durable worker/outbox kernel [HM-AC-2/8]

- 替换 `FactJobWorker` 为通用 job runner：batch key、evidence watermark、lease expiry、attempt、next retry、dead-letter、
  canonical payload hash。LLM 调用在事务外；apply 在单事务内。
- worker 不持有 client/model/extractor；它只调用注入的 S1 `MemoryAnalysisExecutorPort`。同 request hash 的 Host durable
  result receipt 可重放；不确定调用可产生新 attempt，但 Memory 只 CAS apply 一次，后续 divergent response 只审计不应用。
- 退出/崩溃后 reclaim；同 job replay 不重复 decision/state/outbox。后台 worker 不生成 Agent effect 或 TaskScope mutation。
- batch size/idle/max-wait/cost 参数先留为显式 config，值由 Phase 2 spike 冻结。
- 实施校准：现有 Phase 2 artifacts 未包含 worker/provider 成本常数，因此 S2 不提供隐式产品默认值；所有运行参数
  与 `AnalysisBudget` 由调用方显式构造，真实 provider 成本值在 S5 composition 校准前不得宣称已冻结。
- 验证：kill 在 job commit、claim、provider handoff、Host result commit、receipt 返回、Memory apply；覆盖 lease race、
  timeout/refusal/duplicate/divergent/out-of-order/oversize、target revision drift、clean shutdown/restart。
- 独立审计附加门 `a2-003`：repository 的底层 commit/record seam 不得只凭 DTO/hash 自洽接受 delivery；直接伪造
  issuer/attempt/hash、admission 跨 claim/重放必须 fail-closed。Host authority verification 必须仍在 SQLite transaction 外，
  unsafe/oversize body 与 credential canary 在 DB/WAL/audit/export/log 中零落盘，同时保留安全公共
  delivery/validation metadata；瞬时 verifier timeout/不可用按显式 taxonomy 重试，确定性 contract rejection 才 dead-letter。
- mutation worker 的唯一合法 durable phase 为
  `handed_off → result_committed → audit_pending → applied`；每一步只由 repository 在验证当前 durable row 后签发
  单次 capability，绑定 exact claim、request hash、attempt、delivery envelope/result、repository-generated
  `AnalysisApplication` 与 application receipt。不得从 `handed_off` 直接 audit/apply，也不得复用 commit/audit capability。
- `record_memory_analysis()` 必须核对 batch 当前 phase、`application_receipt_hash` 和 repository 生成的 accepted/rejected
  decisions；调用方提供的 validation receipt 或 decisions 只能作为待验证输入，不能成为 authority。任何跨 claim、跨
  application、改 decision、audit-before-result、audit-before-application 都 stable reject 且不产生 canonical mutation。
- Host authority 瞬时不可用时，恢复必须查回同一 Host durable `request_hash+attempt` 的既有 result，Provider 第二次调用数为
  0；维持同 batch/request/result/attempt，按 bounded retry 后写 terminal public audit/dead-letter。任何未经验证 body 在
  DB/WAL/audit/export/log 中仍为零落盘。
- 追加故障矩阵：在每个 phase capability consume 前后与 transaction commit 前后 kill/reopen；验证单次 phase 推进、exact
  replay 收敛、divergent replay 拒绝、无半状态。新增 caller-created accepted/rejected receipt、changed decisions、
  cross-claim/application replay 的 repository-level negative tests。

### Task 6 — 移除旧默认行为并发布 candidate [HM-AC-2/8]

- 删除 `BaseMemoryBackend` 默认 `RuleBasedFactExtractor`；旧 `FACT_DECAY_DEFAULTS`、category half-life 与 physical
  `delete_session/delete_old_sessions/delete_all` 不进入 v0.6 public API。
- 更新 README/ARCHITECTURE/schema docs/public API snapshot/CHANGELOG；构建 `0.6.0` candidate wheel，依赖 S1 exact range。
- 验证：全仓 `rg` 不再有生产 L1/L2/L3/default regex/physical raw delete 调用；clean wheel consumer。

## 验证出口

- 旧 v4 fixture 未被修改且明确拒绝；fresh DB fault matrix 全绿。
- raw evidence row count/hash 在 forget、maintenance、rebuild、test cleanup 前后不变。
- credential canary 在 DB/WAL/log/docs/vector request/LLM evidence/export/Context fixture 均为零命中。
