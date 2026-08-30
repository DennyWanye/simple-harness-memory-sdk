# S5 — Host 动态 Context、路由/召回/语义收口与生产集成

> Release unit：S5（Host + exact SDK wheels）  
> 高风险子系统：Context authority、provider/tool continuation、跨仓 ingestion/recall（3）  
> 覆盖：HM-AC-3/4/6/7/8

## 交付边界

把 S1—S4 接成真实生产链：初始有界 Context→主模型 route/recall tool→同 Run continuation→effect→semantic
closure→terminal evidence→Memory outbox。UI 只需现有 chat 可驱动，完整视觉在 S6。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `backend/deskpet/sdk_adapters/context_authority.py` | 扩展 prepared/final ContextSnapshot、route/assembly decisions 与 public redaction |
| `backend/deskpet/agent/context_budget.py`, `assembler/*` | 分区 token/item/byte budgets、priority/dedupe/causal closure |
| `backend/deskpet/agent/session_history_planner.py` | 从任意 10 message 改为最近 10 完整 causal turn groups |
| `backend/deskpet/sdk_adapters/context_route.py`（新） | strict route/task search/open/recall tool handlers 与 receipt |
| `backend/deskpet/sdk_adapters/task_scope_mutation.py`（新） | task_scope_update validator adapter 与 closure receipt |
| `backend/deskpet/sdk_adapters/tool_authority.py` | 从 trusted route/binding 注入 per-effect envelope |
| `backend/deskpet/memory/{product_outbox,recall_adapter}.py` | exact S3 wheel ingestion/typed recall/suppression receipt |
| `backend/deskpet/memory/analysis_executor.py`（新） | Run-bound main-model MemoryAnalysisExecutorPort 与 permanent invocation ledger |
| `backend/deskpet/companion/reminders.py` | 适配为唯一 Prospective registration/occurrence scheduler authority |
| `backend/deskpet/tool_catalog/providers.py` | 暴露 context_route/task_scope_* / typed memory tools；统一工具层不再隐藏关键 route tool |
| `backend/main.py` | `_bounded_sdk_history`/`_prepare_sdk_context_snapshot`/runtime composition 切换到新链路 |
| `backend/tests/sdk_adapters/`, `backend/tests/test_execute_sdk_run.py` | black-box integration/fault/replay/budget tests |

## Tasks

### Task 1 — 初始 Context 与最近 10 causal groups [HM-AC-6/8]

- 替换 `_bounded_sdk_history()` 的 10,000 rows+token tail：按 user turn 开始、assistant terminal、tool call/result 配对形成
  group，选最近 10 个完整 group；未终结当前 Run 单独标注，不截断 tool causality。
- 大型 tool result 保留 typed summary/artifact ref/必要 excerpt；raw 永久在 evidence，可按 exact ref page-in。
- 初始 snapshot 包含 protected rules/current query、最近组、active/recent TaskScope compact directory、可见 tools；不先
  查询 short/long memory。
- 使用 V0 `SPIKE-CONTEXT-DOC` 已选定的分区预算、裁剪顺序、page-ref 和 hard cap，不在实现时改 oracle。
- 冻结最近 10 causal groups；大型 tool result=`typed summary + exact ref`；4k/8k/32k generation reserve 分别
  1024/2048/4096 tokens；safety margin=`max(256, window×10%)`；可选分区裁剪顺序 attachments→long-term 至一项→
  short-horizon。真实 provider usage 校准若出现任何 estimator underestimate，S5 阻断并重做预算，不接受离线 oracle 代替。
- Provider 调用前先 reconcile Host mandatory occurrence inbox；合资格 summary 进入 initial snapshot，当前
  `DisclosureContext`/suppression/status 再校验。inbox 为空才允许 terminal no_recall。

### Task 2 — 五路 context_route tool [HM-AC-3/4/7]

- 主模型每轮可返回 direct_standalone、memory_standalone、continue_active、resume_existing、create_new；工具 schema 使用
  S1 exact DTO/strict mode。
- route adapter 调 S4 search/open/provision/binding 与 S3 recall；Host `DisclosureContext`/identity/mode/budget 覆盖模型同名值，
  unknown/ambiguous/external/stale/conflict 对敏感 recall fail-closed 或 clarification。
- search candidate→exact open 分步；ambiguity 影响项目/权限/关键事实时产生用户 clarification，不影响时保守回答。
- 所有 invocation/route/search/open/recall validation 产生 Host+Memory linked decisions。
- 同一 authenticated Host interaction 管线持久化 Manual workspace-binding 的 user evidence 与 decision facts；分别绑定
  subject/scope/proposal/root/base revision/channel/nonce/interaction/validity 和 challenge/nonce/actor/decision/time，供 S4
  constructor-bound authority 重启后重建。自然语言、模型 tool args 或 route metadata 不能代替 authenticated interaction。
- 验证：HM-S1/HM-S2/HM-S10，active scope inertia、false resume、memory/scope conflation、permission by retrieval。

### Task 3 — Recall observation 与同 Run continuation [HM-AC-4/6/8]

- typed ContextFragments 携带 source ref/type/status/score/eligibility reason/bytes/tokens；Host 二次执行 current recipient/purpose
  和 suppression check，去重最近窗口/TaskScope state。
- route receipt 作为 `function_call_output` 返回同一 Run；只保留 provider public/opaque continuation item，不持久 raw hidden
  reasoning，不另建 Run；按 V0 capability matrix 禁用或拒绝不兼容 provider。
- no-recall 记录 decision、Memory SDK 零查询、一次 provider invocation；recall 路径允许一次或必要多次 tool continuation，
  每次成本/latency 单列。
- 验证：call_id/reasoning continuation、timeout/degraded empty、duplicate fragments、hard deadline。

### Task 4 — 最终 Context assembler、runtime port 与 immutable snapshot [HM-AC-6/7/8]

- `_prepare_sdk_context_snapshot()` 变为每 Provider turn authority：initial；route/工具后 next snapshot。通过 S1
  `RunContextAuthorityPort` 返回 exact messages/tools/options 与 revision/fingerprint。各分区预算：
  protected、recent、task、short-horizon、long-term、tools/skills/attachments、current run observations。
- deterministic priority/crop/page-ref；不得裁掉当前 tool call/result 因果对或 system/current query。冻结真实发送 provider 的
  canonical payload hash、selected/excluded reason 和 source revisions。
- digital twin graph DTO 不得成为 assembler source；添加 import/dependency/serialized payload negative test。
- Harness provider reservation 前必须持久验证 receipt；验证 Host expected hash = Harness request fingerprint = adapter captured
  payload hash，以及 20+ turns、大 tool、两 TaskScope+resume、token estimator drift、snapshot replay、twin influence zero。
- `ProductRunContextAuthority` 和 `ProductRuntimeDecisionSink` 的 durable fact source 在本 Task 建立：immutable context snapshot/
  revision/hash、route decision、no-recall decision、binding receipt 与 current Run lineage 同事务或 receipt-linked 持久化；
  `prepare_snapshot`/`record_no_recall` 只能读取这些 Host facts，禁止从 caller metadata 或测试 fixture 补权。

### Task 5 — TaskExecutionEnvelope 与 workspace effect gate [HM-AC-3/7]

- adapter 从当前 run route receipt + exact binding set 生成 envelope；模型不能传 root path/revision 取得 authority。
- tool executor 前重验 TaskScope active/open、root membership、binding revision、filesystem identity、permission/risk policy；
  stale/missing fail-closed，下一轮 route 才能刷新。
- Auto 只免 folder append confirmation；发布/删除/付款/权限等继续既有 approval gate。
- 验证：HM-S9、same-batch pre-route effect、root drift、model forged auto、high-risk action。

### Task 6 — 客观事件 + TaskScope semantic closure [HM-AC-3/7/8]

- Host tool/file/test 事件直接进 S4 recorder；Harness Provider/Tool/Context/Route/Run events 由 source-ledger outbox→Host
  receipt/cursor 导入并设置 deterministic dirty flags；不按关键词/正则判断语义。
- `task_scope_update` 接 S1 TaskScopeMutationPlan；Host 检查 evidence refs/base revision/state/idempotency 后调用 S4 transaction。
- terminal gate 同时检查 Harness evidence watermark、mandatory occurrence watermark 与 semantic closure watermark。有 material
  dirty 而无 receipt 时，把暂存 final response 作为 continuation observation，
  要求同一主模型补 `mutate|no_mutation`；非法/timeout 标 semantic_closure_pending，不伪造 checkpoint。
- 验证：HM-TO-R8 多 tool batch、模型漏调用/拒绝、CAS、duplicate plan、projection failure。

### Task 7 — 主模型 Memory analysis、Host↔Memory outbox 与即时操作 [HM-AC-2/7/8]

- terminal commit 同事务写 Host sanitized raw evidence links + Memory ingestion outbox；调用 S3 exact wheel，receipt 回写 Host event。
- 实现 `MemoryAnalysisExecutorPort`：按 job 绑定的 originating foreground Run provider/model/config 做独立 post-turn 主模型调用，
  永久记录 reserved/handed_off/succeeded/failed/unknown attempt 与 request/result/validator receipt；不新建独立 extractor client。
- Host executor 在任何 Provider execution 前按 `request_hash+attempt` 查询 durable attempt；已有成功/未知后确认成功的 result
  必须返回同一 durable row，不能再次调用 Provider。`MemoryAnalysisDeliveryAuthorityPort` 必须从同一 store 暴露 exact
  claim/request/attempt/envelope/result 事实给 Memory SDK；瞬时 authority 重试仍查同一行，构造新 attempt 只能遵守显式
  unknown-call taxonomy，不能掩盖第二次 Provider 调用。
- accepted Prospective registration/invalidation 由 Memory outbox 投影至现有 Host ReminderScheduler 衍生的唯一 scheduler；
  event cursor 与 occurrence claim/presented/acknowledged/settled 分离，模型拒绝不标 processed。
- explicit remember/correct/forget 标高优先 job，并确保 forget suppression receipt 在普通后续读取前生效；普通 batch 异步。
- 按 V0 runtime/trigger spike 协议执行故障矩阵，证明 Host commit、analysis claim/result、Memory apply、registration/
  occurrence/ack 与 Host receipt 各 kill 点可收敛。
- 验证：crash/restart、duplicate payload、Memory unavailable/dead-letter、raw Host evidence 不丢。

### Task 8 — 生产 composition、版本锁与集成回归 [HM-AC-8]

- Host 锁定 S1/S3 clean wheels exact version/hash；删除生产 `enable_facts=True` 无 extractor 的旧默认路径。
- `_build_product_sdk_runtime_stack()` 是 Harness 0.7 runtime 的唯一生产 composition owner。它必须构造并注入
  `ProductRunContextAuthority`、`ProductRuntimeDecisionSink`（`sdk_adapters/context_authority.py`）和
  `ProductTaskExecutionAuthority`（`sdk_adapters/tool_authority.py`）三个 concrete port；分别连接 Task 4 durable
  context/route ledger，以及 exact Run tool authority、route receipt、binding receipt、project binding 与 physical workspace
  validator。缺任一 store/authority/validator 必须在 startup stable fail，禁止 Noop、fake、metadata-derived 或测试 fallback。
- 同一 composition 还必须注入 S4 Manual authenticated-interaction authority、S4/S5 Auto current-fact authority，以及 Task 7
  real `MemoryAnalysisExecutorPort`/`MemoryAnalysisDeliveryAuthorityPort`；重启后只靠 durable stores 重建，不依赖进程内 map。
- 更新 tool manifest/schema migration、composition assertions、critical+affected surface smoke。真实 exact-wheel 构造测试必须
  捕获三个 concrete class 与 durable dependency identity；逐项移除 prerequisite 均 fail-closed。
- 黑盒生产链测试：provider snapshot fingerprint 与 Host expected hash 相等；context_route 持久 route/binding 并让同 Run
  continuation 使用 exact snapshot；project effect 到 physical executor 的 envelope 含 exact run/route/scope/binding/root/hash；
  same-batch pre-route effect 在 mutation 前 barrier reject；no-recall=一次 Provider、Memory 零查询、durable decision；route receipt
  后 kill/replay 不重复 effect；Manual/Auto authority restart 后仍按 durable facts 判定。
- backend 全量测试、真实 provider value smoke（先用主 checkout ignored `.env` 的 APIKEY，仅进进程，不打印/复制）；证据本地 ignored。
- 完成后更新 Host ARCHITECTURE/PROJECT_STATUS，但 UI 仍标 S6 pending。

## 验证出口

- 五路 route、no-recall/recall、TaskScope effect、closure、outbox、Context budgets 生产链全部有 primary evidence。
- 冻结路由质量与 latency/token 指标达到 HM-AC-8；达不到时 BLOCKED，不以 deterministic fake 代替真实 provider。
