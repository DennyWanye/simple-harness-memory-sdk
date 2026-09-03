# 增量验收：S5b — 工作区 effect gate、TaskScope 语义收口与 Host↔Memory 异步面（analysis / outbox / Prospective / 即时操作）

> 状态：APPROVED（2026-09-02 用户批准 acceptance + 修订提案 A1–A13，批准原话 sha256 `2a99dd6aabeee8485b1453b7371170bef6a04ff2990165079f31c691f4ad75f7`；A6/A7/A11 三项裁决由用户委托独立审核代理，结论见 `verification/plan-challenge/delegated-decisions-A6-A7-A11.md`）
> 父事实源：`../../acceptance.md`（program 级唯一真相，HM-AC-2/3/5/7/8 与冻结场景矩阵/LLM 变异清单在彼处）
> 流程：plan-test / FULL / MACHINE_GATE 启用（schema v46 迁移 + 公共 Provider 后台调用 + 跨三仓 + LLM 载荷驱动状态机 + 共享生产 composition）
> 承接：S5a（receipt `b5d416e3…`，Host `main`@`ec1cb944`，Memory `main`@`fcf1682`）。本增量 = S5 slice **Task 5 / 6 / 7 的 effect gate、语义收口、终态 outbox + 主模型 analysis + Memory 0.6.1** + S5a 遗留义务；**Task 7 的 Prospective 唯一 scheduler 与即时 remember/correct/forget 依委托裁决 A11 移入独立增量 S5c**（S6 之前）；S6 UI 与 program 收口另开增量。

## 矛盾分析（骨架）

- **主要矛盾**：主模型替用户在任务里真干了活（改了文件、跑了命令、聊出了新的事实与未来意图）之后，
  系统能否把这一轮**真实发生的事**确定性地沉淀为任务档案的语义状态与长期记忆，而不是靠猜、靠关键词、
  靠人工整理，也不用伪造的 checkpoint 冒充。
- **产生原因**：S5a 之后主模型已能正确判断"这句话要什么上下文"并在同一 Run 内拿到它，但 Run 结束时
  发生的事**无人收账**：Host 的客观事件 recorder 零生产调用者，Harness 侧只产出 `run_terminal` 一种证据，
  `task_scope_update` 根本不是工具，`MemoryAnalysisExecutorPort` 零 Host 实现，`ingest_committed_evidence`
  生产零调用，Prospective 注册 outbox 无人消费，`memory_write/forget` 是返回 `memory_sdk_unavailable` 的 stub。
  同时，动文件的权限还停留在 S4 的"启动时查一次"（`verify_task_execution_envelope` 零生产调用、
  零 PROJECT_EFFECT 工具、`root_resolver=None`），effect 与后续沉淀之间没有可信的因果账。
- **解决方向**：三条确定性链路接进生产：① 每个项目 effect 执行前用当前轮 route receipt + exact binding
  重签 envelope 并重验；② 客观事件与 Harness 证据进 S4 账本并设脏标记，终态门按三水位放行，
  漏收口由**同一主模型**补 `mutate|no_mutation`；③ 终态提交同事务写 Memory 摄入 outbox，post-turn 用
  **同一 Run 绑定的主模型**做 analysis，Prospective 由唯一 Host scheduler 投影，remember/correct/forget 即时生效。
- **最小验证动作**（价值验证里程碑）：fresh Host + 真实 provider，在一个已绑定 workspace 的任务里对模型说
  "把 README 里的版本号改成 1.2.0"：模型经 `write_file`（PROJECT_EFFECT，envelope 重验通过）改文件 →
  Host 以 `host.file` 客观事件设脏标记 → 模型在终答前调 `task_scope_update` 提交 `mutate`（漏调则 Host
  兜底同主模型补一次）→ 终态提交同事务落 Memory 摄入 outbox → post-turn analysis 产出的 `MemoryMutationPlan` 被记忆库
  **（0.6.1）接受并物化**（cognitive head + `memory.cognitive.committed` 或 prospective registration outbox），
  **下一轮 typed recall 可读到**。全程一个 foreground Run、一次 durable analysis attempt、零重复 Provider 调用，
  终答非空且任务档案 STATUS 与真实文件变更一致。（A1）
- **矛盾的主要方面**：终态门（三水位 + 同事务 outbox + 兜底收口）能否在真实 Run 上跑通并可重放——
  analysis 结果的语义质量、Prospective 与即时操作是价值成立之后的事。

## 范围

**包含（S5b）**：

- S5 slice **Task 5**：TaskExecutionEnvelope 与 workspace effect gate（含 S5a 遗留的 `PROJECT_EFFECT` root 签发接线）。
- S5 slice **Task 6**：客观事件 + TaskScope semantic closure（Host 事件 recorder 接线、Harness 证据 outbox 导入、
  `task_scope_update` 工具、三水位终态门、同主模型兜底收口、`semantic_closure_pending`）。
- S5 slice **Task 7（部分）**：主模型 Memory analysis executor（Run-bound、durable 五态 attempt、幂等）、Host↔Memory
  摄入 outbox、Memory 0.6.1、故障矩阵。**Prospective 唯一 scheduler/occurrence/`prospective_ack` 与即时 remember/correct/forget 移交 S5c**（A11）。
- S5a 留下的未了结义务：S1 真实无召回车道补非空回答断言 + transcript dump；memory-sdk 正式属主注册 API
  并删 Host fail-open；Host durable pre-admission audit（翻转 `BLOCKED_UNTIL_S5`）；changed-surface lint 小项；
  S4 11 项 P2 中**触及本增量改动面**的项（effect gate durable 正向判定、oracle pin hash 口径统一）。
- 生产 composition 扩展（缺件 startup fail）、v46 迁移与 slice cutover receipt。

**明确不包含**：

- **S5B-AC-4 / S5B-AC-5 全部内容（移交 S5c）**：Prospective 唯一 scheduler、occurrence 生命周期、`prospective_ack`、`prospective_signal_authority`/`memory_action_authority` 注入、v47 prospective 三表、`prospective-occurrence` fault lane、S5B-S5/S6 真实车道、memory tool 载荷变异。S5b 边界不变量：analysis 产出的 Memory prospective registration outbox 行 durable 保留（state=pending、Host 无游标、零 dead-letter、意图 `registration_not_live`、inbox 恒空、no_recall 门不受影响）；`memory_write/forget` 维持 S5a 稳定 `memory_sdk_unavailable`。

- **Harness SDK 任何改动**（0.7.1 冻结；"assistant.tool_calls 一等公共字段"上游义务顺延至 program 后 SDK 0.8，
  Host `_wire_messages` 兜底保留——本条是对交接 §8 的显式修正，见"用户须确认的解释声明" D3）。
- HM-AC-8 路由质量阈值门（外部前置：240 条语料独立人工复审，当前 `AI_DRAFT_UNREVIEWED`）；本增量维持 `NOT_RUN/BLOCKED`。
- S6 全部 UI（TaskScopePanel / MemoryPanel 四类 / MemoryGraph / 会话 CRUD 移除）。
- 外部 notification/calendar provider、真实高风险 action executor（Prospective 交付通道 = 下一轮 Context，program OOS）。
- WeMM 快照上传 COS、三仓 push/tag/发布、旧数据迁移、多 root effect 的 root-selection 协议（继续 fail-closed）。
- S4 其余 P2（不触及本增量面者）：留 backlog 显式列出，不静默关闭。

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 矛盾地位 | 优先级 |
|----|--------|-------------------|----------|--------|
| S5B-AC-1 | TaskScope 语义收口生产链 | ① Host tool/file/test 事件在物理执行处由 Host 直接写 S4 recorder（`host.file`/`host.test`/`host.turn`），不经 LLM、不用关键词/正则；Harness Provider/Tool/Context/Route 证据由 Host 在各事实提交点**同事务直写** `ExecutionEvidenceIngress`（其它 DB 事实先预留 source_sequence，terminal observer 唯一排空；不引入异步 outbox worker）按 `source_event_id+payload_hash` 幂等导入并推进 `task_scope_run_watermarks`（不再只有 `run_terminal`）（A13）；每类事件映射到**确定性**脏标记（`objective_material` / `objective_trivial`，映射表冻结）。② `task_scope_update` 注册为工具（strict schema、direct kernel、manifest 同步），接受 S1 `TaskScopeMutationPlan`（含 `no_mutation`）；Host 校验 evidence refs 存在且属本 scope、`base_revision` CAS、状态迁移合法、`idempotency_key` 幂等后调 S4 `apply_mutation_plan`，产出 closure receipt。③ 终态门同时检查 Harness 证据水位、mandatory occurrence 水位、语义收敛水位；终答由 SDK delivery pump 按既有路径交付（Host 无法在该 seam 扣押）；有 material 脏标记而无 receipt 时，Host 在 SDK terminal 之后、Host 终态提交之前以**同一主模型**（Run 绑定 provider/model/config）发起一次 closure 调用（最后一条 assistant 消息 + 脏事件摘要作观察，仅暴露 `task_scope_update`；durable attempt、仅当前 lease owner、`handed_off/unknown` 绝不重发），合法 plan 则同事务提交 receipt；非法/拒绝/timeout/unknown → durable `semantic_closure_pending`，由 Host 终态 receipt 与 STATUS 投影承载并在**同一 admission scope 的下一 Run** snapshot 注入；scope complete/checkpoint/resume 时仍 pending → Host 强制 `no_mutation(closure_abandoned)` 零 Provider 调用；**不伪造 checkpoint、不写 Markdown 成功**。（A3）④ 验证 HM-TO-R8：多工具批次、模型漏调用/拒绝/timeout、CAS 冲突、重复 plan、projection worker 失败注入，均无半状态、可重试。 | 决定性 | 必须 |
| S5B-AC-2 | 主模型 Memory analysis 与 Host↔Memory 摄入 outbox | ① foreground Run 终态提交在**同一事务**内写 Host sanitized raw evidence link + Memory ingestion outbox 行；outbox worker 调 exact Memory **0.6.1** wheel `ingest_committed_evidence`（0.6.1：builder 透传 `supported_filter_policies`；多 operation finalize 收敛；accepted plan 仓储内物化；`register_principal_owner`；analysis lineage 绑在 ingest；`analysis_apply_head` 端口）（A2），receipt 回写 Host 事件；Memory 不可用 → 有界重试 → dead-letter 且 Host 原始证据不丢（行数/hash 守恒）。② `MemoryAnalysisExecutorPort` Host 实装：按 job 绑定的 originating Run 的 durable `SdkRunBindingV1` 重建 `ProductProviderAdapter` 做独立 post-turn 调用（**不新建 extractor client**）；永久记录 `reserved/handed_off/succeeded/failed/unknown` 五态 attempt 与 request/result/validator receipt。③ 幂等硬要求：任何 Provider 执行前按 `UNIQUE(request_hash, attempt)` + attempt 无关的 `evidence_set_key` + per-member evidence 索引查 durable attempt；已 succeeded 者返回同一行且 **Provider 调用计数为 0**；任一成员存在 open `handed_off`/`sent_unknown` 行 → 拒绝再投递（0 调用）；`sent_unknown` 在非流式 OpenAI 兼容端点无生产确认路径，可执行终态 = 拒绝一切再投递 → Memory dead_letter + Host durable `memory.analysis.blocked`；`sent_confirmed` 仅经注入的测试 reconciliation observer 可达（S5B-S3 lane 必含）；瞬时 authority 重试查同一行；新 attempt 只能按显式 unknown-call 分类法（`not_sent` / `sent_unknown` / `sent_confirmed`）构造；Memory lease 必须大于 analysis deadline 加余量。（A10）④ `MemoryAnalysisDeliveryAuthorityPort` 从同一 store 暴露 claim/request/attempt/envelope/result 事实；Memory 侧 `handed_off→result_committed→audit_pending→applied` 单向推进。⑤ 真实 provider：一轮含事实的对话 → analysis 产出被记忆库 accepted 的非空 `MemoryMutationPlan`，人工检查与对话事实一致、无臆造。⑥ 验证：Host commit / analysis claim / result / Memory apply 各 kill 点 crash-restart 收敛、duplicate payload、Memory unavailable/dead-letter、raw evidence 守恒。 | 决定性 | 必须 |
| S5B-AC-3 | TaskExecutionEnvelope 与 workspace effect gate | ① 冻结 PROJECT_EFFECT 工具清单（对绑定根**写入或在根内执行**的内置工具：`write_file/file_write/edit_file/move_file/file_organize/run_shell/process_start/doc_create/doc_edit/excel_create/ppt_create/pdf_export/download_file/workspace_prepare`；读取类保持 NON_PROJECT_EFFECT，仍受 workspace 投影过滤），`route_requirement=required`、`task_scope_requirement=required`；manifest/policy 表同步。② `root_resolver` 接线：从 route receipt 的 exact binding-set receipt 解析**恰一个** root（`root_id`+`root_identity_hash`）；零/多 root 稳定 fail-closed（`sdk_task_execution_root_authority_unavailable` 语义保留但换为可审计 reason）。③ envelope 只由当前轮 route receipt + exact binding set 生成；模型参数中的 authority 同名字段被 SDK 拒绝（既有）且 Host 侧对 envelope 缺失/跨 Run 拒绝。④ 物理 executor（`ProductEffectExecutor.execute`）前**每次**重验：envelope 存在/身份回声、**冻结 authority 一致性**（envelope scope == Run admission 冻结 scope、`project_bound`、根 canonical_path == 冻结写根）、root membership（`verify_task_execution_envelope`）、binding revision 等于 receipt、文件系统身份（dev/ino）未漂移、scope `active/open`、permission/risk policy；任一 stale/missing → `ToolResult.rejected(稳定 reason)` 且直到下一轮 `context_route` 刷新前持续拒绝。冻结 SDK 无模型可见的「standalone 不许项目 effect」拒绝路径：standalone 路由下写工具**不可见/不可激活**，模型仍调用则本轮以稳定原因 **fail-closed 整 Run（durable FAILED，零写入）**；建立 TaskScope 后**在下一轮**执行写入。（A4）⑤ Auto 豁免 folder-append 确认并**沿用既有可逆本地效果的 auto 策略**（preserve-approved）；`_CONFIRM_ONLY`（发布/删除/付款/凭据/隐私/未知）类在 Auto 下**永不 auto-grant**（`explicit_only` 从冻结 effect 分类计算并接入 SDK 授权路径 `decide()`），有显式断言测试。（A5）⑥ 验证 HM-S9（TC-HM-09 步骤 3–6）：步骤 3/4 在同一 scope 上执行 Manual/Auto 追加（新 revision、旧 root 不替换）；**步骤 6 以每个 canary root 一个单 root scope 执行**，每个 canary envelope 绑定 exact task_scope_id、root ref、当时 revision 并留逐 root hash；**追加断言**：≥2 root scope 的写工具不出现在 snapshot tools，强制调用 → durable FAILED + 稳定码（`catalog_execution_policy_unavailable` / `sdk_task_execution_root_authority_ambiguous`），两根 canary hash 均不变（OOS-MULTI-ROOT-SELECTION）。Run 内任何 binding 追加后 head ≠ receipt.revision → 后续项目 effect `workspace_binding_receipt_superseded`（strict，Manual/Auto 同一规则），sticky 至下一 Run `context_route` 刷新。以 verification-spec oracle 解释 + `behavior_changes`（exact old/new、用户委托消息 hash、scope=S5b/S5c/S6、expiry=多 root 选择协议独立验收之日）入账，TC-HM-09 文件不改；artifact 在 Task 0 写入并进 V0 sealed lineage（A6）；同批 pre-route effect 被 barrier 拒绝；运行中 root inode 漂移 → 拒绝；模型伪造 auto/envelope 字段 → 拒绝；高风险动作在 Auto 下仍要求确认。 | 次要 | 必须 |
| S5B-AC-4（**移交 S5c**，本增量不验收、不计 MUST；措辞按 A7/A8 修订后原样带入 S5c） | Prospective 唯一 scheduler 与 occurrence 生命周期 | ① Host 从 `ReminderScheduler` 衍生唯一 `ProspectiveScheduler`（复用 claim/lease/双检/settle 设计），消费 Memory `read_outbox` 的 `memory.prospective.{registration,invalidation}.requested`，按 `outbox_id` 幂等投影到 Host state.db durable registrations；**outbox 消费与游标同一事务**；Host 以 outbox_id 派生的确定性 signal 身份回签 `REGISTRATION_ACCEPTED`（crash 重放同 ref）；claims 来源于 inbox；递归意图（『每周五』）在 wheel 只有 time/event trigger 下按**一次性到期**处理，递归留 backlog。（A8）② 到期/事件触发时 Host 以 `prospective_signal_authority` 调 `apply_prospective_signal`，同 trigger revision/event **恰一个** occurrence；invalidation 后不再触发。③ occurrence 状态 `claimed→presented→acknowledged→settled(acknowledged|suppressed|superseded|expired)` 与游标分离（canonical 生命周期表 = v46 `prospective_occurrences`）；**processed := 该 occurrence_key 存在 durable `prospective_ack` 凭证**（新 Host 工具 `prospective_ack{occurrence_key}`，五路可见，模型回显 Host 放进 inbox 消息的 64-hex key）；模型未调用/拒绝 → 不 processed，下一轮继续 pending；`occurrence_presented`（v45，S5a 门读源）只作投影，只在 occurrence 离开 mandatory inbox（acknowledged 或 settled superseded/expired）时同事务写入，snapshot 注入时不写；suppressed/FORGOTTEN occurrence settle 为 suppressed，永不写投影，内容零进入 Context。（A7）④ 按 V0 SPIKE-CROSS-DB-TRIGGER 协议在 registration/occurrence/snapshot/ack 四 kill 点收敛：pending 不丢、replay snapshot hash 相同、无重复 occurrence。⑤ 真实 provider：用户说"发布成功以后提醒我更新变更日志"→ Prospective 注册 → 触发 → 下一轮 no_recall 被拒且 summary 进 snapshot → 模型调用 `prospective_ack` → settled(acknowledged)；『终答提及』只作 quality_bar 人工检查。 | 次要 | 移交 S5c |
| S5B-AC-5（**移交 S5c**） | 即时 remember / correct / forget | ① `memory_write`（remember/correct）与 `memory_forget` 从 stub 变为真实：remember/correct 产生高优先 immediate analysis job（同一 executor，优先于普通 batch，同一轮终态后立即执行）；forget 在工具内**同步**走 Host `memory_action_authority` → Memory `suppress`，suppression receipt durable 后工具才返回。② forget 生效顺序硬约束：suppression receipt 之后的任何普通读取（typed recall、five-day short-horizon、initial snapshot、occurrence inbox）不再返回该内容；原始证据行数/hash 不变。③ 验证：TC-HM-07 步骤 1–3 的自动化子集（记住→召回可见→忘掉→六路普通读取不可见→raw 守恒）+ 真实 provider 一例（自然语言"记住/忘掉"）。 | 次要 | 移交 S5c |
| S5B-AC-6 | 生产 composition、迁移 cutover 与遗留义务收口 | ① `_build_product_sdk_runtime_stack` / `build_human_memory_v7` 注入 root_resolver、closure authority、Memory analysis executor + delivery authority（同一对象绑定 builder）、prospective_signal_authority、memory_action_authority、**Host `evidence_authority`（只从 Host state.db durable envelope/receipt 解析）**、`supported_filter_policies`、单一后台 lane（ingestion outbox / job runner）；首次构建幂等 `register_principal_owner`；逐项移除任一 → startup stable fail（禁 Noop/fake）。`prospective_signal_authority`、`memory_action_authority` 移 S5c。（A9/A11）② v46 迁移（只含 closure receipts / harness evidence reservations / memory ingestion outbox / post-turn attempts / effect_gate_rejections / pre_admission_audit；prospective 表族属 S5c v47）前向应用；旧 runtime 打开 v46 userdata stable reject；rollback drill 不删 evidence；slice cutover receipt。③ memory-sdk 补正式属主注册 API（0.6.1 或 0.7.0 candidate，exact pin + hash）并删除 `human_memory_v7.py:101-119` fail-open 分支（回归测试证明删后首条对话仍可用）。④ Host durable pre-admission audit：Harness 在 Memory 之前拒绝的非法载荷在 Host 有 durable audit 行，`BLOCKED_UNTIL_S5` 标记翻转为真实 oracle。⑤ S1 真实无召回车道补非空回答断言 + transcript dump；S5a changed-surface lint 小项清零；S4 P2 中 effect gate durable 正向判定与 oracle pin 口径统一收口。 | 次要 | 必须 |

## 非功能 / 边界（只列本增量真实相关）

- **program 硬架构契约**（`../../plan.md:87-112`）本增量直接背负：94-95（Harness 源账本→Host 幂等接收、terminal 越过 durable watermark）、
  96-97（MemoryAnalysisExecutorPort 用发起 Run 的主模型配置、request/result/receipt 与 lease/CAS 永久可审计）、102-103（Host 唯一 scheduler、
  durable registration/occurrence/cursor 进 pre-provider/pre-terminal gate）、104-105（delivery receipt 非 mutation authority；单向状态机）、
  106-108（Manual/Auto 两条 authority 生命周期；exact replay 只返回原 receipt）、110-112（唯一 composition owner）。
- **Harness SDK 0.7.1 冻结**：本增量零 SDK 改动；所有缺失能力（closure hook、evidence outbox、task_scope_update、五态 attempt）Host 侧建，
  只消费冻结 DTO/port。
- **同事务边界**：Host 终态提交 + evidence link + Memory ingestion outbox 同一 SQLite 事务；Host↔Memory 之间只承诺 outbox/receipt 最终一致，
  每个故障点可重放；不承诺跨库 ACID。
- **Provider 成本与延迟（用户可感知）**：每个 committed turn group 增加 ≤1 次 post-turn analysis 调用（按 S2 batch 窗口/数量合批，异步，不阻塞回答）；
  仅当模型漏收口时增加 1 次 closure 调用（同步，终答延迟一个 Provider 往返）；remember/correct 各增加 1 次高优先调用。
- **凭据纪律**：API key 只进进程与 `llm_runtime.json`（用户既定口径），不进 DB/日志/证据/仓库；analysis request/result durable 记录只存 public 内容与 hash。
- **原始证据永不删除**：所有新表 append-only；dead-letter/suppression/settle 均为新行。
- **slice cutover 义务**：v46 前向迁移 + 旧 runtime stable reject + composition 缺件回退演练 + cutover receipt 纳入 DoD 证据。
- 性能边界（下限，非质量门）：closure 兜底调用硬 deadline = provider 既有 deadline；analysis worker lease 30s；occurrence tick 不阻塞 foreground。

## 用户须确认的解释声明（随本 acceptance 一并批准）

- **D1 closure 兜底的实现口径（已按 A3 修订）**：冻结 SDK 在 ROUTED_TASK 终答处无任何 Host 钩子且 terminal Run 拒绝 continuation
  （`react_loop.py:466-494`、`kernel.py:1166-1169`）。本增量把 slice Task 6"暂存 final 作为 continuation observation、同一主模型补
  mutate|no_mutation"实现为：**主路径** = 每 Provider turn 的 initial/next snapshot 在有脏标记时注入收口要求，模型在同一 Run 内先调
  `task_scope_update` 再终答；**兜底** = 模型漏调用时，Host 在 SDK Run terminal 之后、对用户交付之前，用同一 Run 绑定的 provider/model/config
  做一次独立 closure 调用（同 Task 7 executor 机制，durable attempt），不是第二个 SDK Run。program"同一 Run 内 semantic closure"在主路径字面成立，
  兜底路径以"同一主模型 + 同一 Run 绑定 + 交付前"作显式收窄解释。终答交付点 = SDK delivery pump（Host 终态之前），Host 无法扣押；pending 由 Host 终态 receipt/STATUS 承载并在同 scope 下一 Run 注入。
- **D2 PROJECT_EFFECT 分类的用户可见变化（已按 A4 修订）**：standalone 路由下写工具不可见/不可激活；模型仍调用则本轮以稳定原因 fail-closed 整 Run 且零写入；
  建立 TaskScope 后在下一轮执行写入（Run 的写根在 admission 时冻结，同 Run 再路由到其它 scope 的项目 effect 以 `effect_gate_frozen_scope_mismatch` 拒绝）；读取类工具行为不变。追加第二个 root 之后，该 scope 的项目 effect 在多 root 选择协议落地前持续 fail-closed（S4 既有行为，本增量 OOS）；要继续在某目录写入，须使用只绑定该目录的 scope。这是 program HM-AC-3 的兑现，但对现有用户是新行为。
- **D3 SDK 上游义务顺延**：交接 §8 把"SDK 把 assistant.tool_calls 列为一等公共字段"记在 S5b，但交接 §1/§9 同时规定 SDK 0.7.1 program 期间冻结。
  本增量取冻结口径：不改 SDK，Host `_wire_messages` 兜底保留并在 PROJECT_STATUS 记为 SDK 0.8 义务。
- **D4 Prospective scheduler 落点**：从 companion `ReminderScheduler` 衍生设计但持久化在 Host state.db（与 occurrence/route ledger 同库同事务），
  不复用 companion DB；交付通道只有"下一轮 Context"（S5a 门），不推系统通知（外部动作执行器 program OOS）。
- **D5 Release unit（用户委托裁决，2026-09-02，A11）**：S5b = S5B-AC-1/2/3/6，高风险子系统 ① workspace effect authority ② TaskScope closure/终态门 ③ Host↔Memory 终态 outbox + 主模型 analysis executor + Memory 0.6.1 cutover，计 3；Task 0,1,2,3,4a,4,5,6,7,8 共 10。**S5B-AC-4 与 S5B-AC-5 移入独立增量 S5c**（Prospective 唯一 scheduler/occurrence/`prospective_ack`、即时 remember/correct/forget、`prospective_signal_authority` 与 `memory_action_authority` 注入、v47 prospective 三表、`prospective-occurrence` fault lane、S5B-S5/S6 真实车道、S5B-S7 的 memory tool 载荷变异），措辞按 A7/A8 修订后原样带入 S5c acceptance；S5c 在 S6 之前完成，S6 program 验收前三链齐全的前置不变。S5b 边界不变量见「明确不包含」。
- **D6 HM-AC-8 质量门**：需要用户安排 240 条语料的独立人工复审；本增量如实维持 `NOT_RUN/BLOCKED`，可与实施并行推进。
- **D7 Task 7 幂等的 unknown-call 分类法（已按 A10 修订：`sent_unknown` 终态 = 拒绝再投递 → dead_letter）**：`not_sent`（Provider 请求未发出，可安全重发）/ `sent_unknown`（已发出结果未知，只能按
  provider response id 或 request 幂等键确认，不得盲目重发）/ `sent_confirmed`（确认成功，返回同一行）。镜像 Host 既有
  `execution_provider_invocations` 的 claimed/completed/failed/unknown 口径。

## 适用性声明

- `input_sensitive=true`：closure / analysis 的正确性随自然语言语义变化；场景矩阵引用 program 冻结
  HM-S3/S9/S11（decided_by=user）。真实主模型 root run ≥2 轮独立完整跑（program STOCHASTIC 规则）。
  **≥20 turn 长上下文会话随 S5B-S1 的 UI 面一并移交 S6**（A14）：该长会话在 S5a 是经真实桌面 UI 完成的，
  而 S5b 生产链在桌面 UI 上无入口（见 A14），本增量内不存在可驱动它的真实入口。
- `llm_payload_driven=true`：`TaskScopeMutationPlan`、`MemoryMutationPlan`（analysis 结果）载荷驱动 Host/Memory 状态机；
  变异清单引用 program 冻结表，本增量必须补 `task_scope_update` 与 analysis result 的五类变异用例。
- `stateful_init=true` / `cold_start=true`：v46 新持久化状态 + fresh userdata 冷启动直达对话。

## 测试场景矩阵（引用 program 冻结场景，S5b 口径）

| scenario_id | 引用 | S5b 口径 | 矛盾地位 | gate_type | required | manual_required | min_root_runs |
|---|---|---|---|---|---|---|---|
| S5B-S1-REAL-EFFECT-CLOSURE-MEMORY | HM-S11 步骤5 + HM-S3 | 最小验证动作：真实 provider 改文件 → 客观事件脏标记 → `task_scope_update` mutate（或兜底）→ 同事务 outbox → analysis accepted；一个 Run、一次 attempt、零重复 Provider 调用；STATUS 与文件变更一致（人工检查）。**驱动入口 = 生产 `enqueue_turn`（真实 provider 车道）**；**真实桌面 UI 面移交 S6**（见下方「A14 范围缩减」）；**「下一轮 typed recall 可读到」移交下一切**（结构性不可达，见「A15 范围缩减」） | 决定性 | positive-value | 是 | 否（UI 面移交 S6） | 2 |
| S5B-S2-CLOSURE-FAULT-MATRIX | HM-TO-R8 / TC-HM-11 步骤5 / fault lane `foreground-fifo-closure` | deterministic：多工具批次脏标记、漏调用→兜底、拒绝/timeout/unknown→`semantic_closure_pending`、CAS 冲突、重复 plan、projection 失败；六 seam kill/replay + observer next_sequence 竞争、attempt 五态 reconcile、跨 Run plan、lease 到期第二 owner 零重发（A12） | 决定性 | negative-safety | 是 | 否 | 1 |
| S5B-S3-ANALYSIS-IDEMPOTENCY-FAULTS | TC-HM-08 步骤3 / fault lane `memory-mutation-plan` | deterministic：五态 attempt、账本三键先查后调（Provider 计数 0）、unknown 三分类（含注入 reconciliation observer 的 `sent_confirmed`）、≥2 op finalize、audit_pending 卡死 seam、lease-reclaim in-flight、membership growth、Host commit/claim/result/apply 各 kill 点、duplicate payload、Memory unavailable→dead-letter、raw evidence 守恒（A12） | 决定性 | negative-safety | 是 | 否 | 1 |
| S5B-S4-EFFECT-GATE | HM-S9 / TC-HM-09 步骤3–6 / lane `taskscope-init-binding` | deterministic：PROJECT_EFFECT 清单、root 签发、per-effect 重验（reason-code 表）、六类拒绝、root inode 漂移、same-batch pre-route、伪造 auto/envelope、Run fault 三稳定码、frozen-root 分裂、Auto+DESTRUCTIVE → REQUIRE_USER、单 root-per-canary 口径（A6/A12） | 次要 | negative-safety | 是 | 否 | 1 |
| S5B-S5-REAL-PROSPECTIVE（**移交 S5c**） | HM-S4 / TC-HM-04 步骤1、4 / lane `prospective-occurrence` | 真实 provider："发布成功以后提醒我更新变更日志"→注册→触发→下一轮 no_recall 被拒→模型提及→ack；deterministic 四 kill 点 + suppressed 不入 Context + 模型拒绝不 processed | 次要 | positive-value | 移交 | 移交 | — |
| S5B-S6-REAL-REMEMBER-FORGET（**移交 S5c**） | HM-S7 / TC-HM-07 步骤1–3 | 真实 provider："记住我住在 X"→召回可见→"忘掉住址"→六路普通读取不可见；raw 守恒；forget receipt 先于后续读取 | 次要 | positive-value | 移交 | 移交 | — |
| S5B-S7-COLDSTART-COMPOSITION-PAYLOAD | 新增（冷启动）+ TC-HM-08 步骤3 | fresh userdata → v46 → 直达对话；composition 逐缺件 startup fail；旧 runtime 拒 v46；`task_scope_update` / analysis result 载荷五类变异 fail-closed 无半状态（memory tool 载荷变异移交 S5c）；pre-admission audit 行 | 次要 | negative-safety | 是 | 是（冷启动真实桌面） | 1 |
| S5B-S8-REAL-UI-CHANNEL | 新增（A12） | 真实桌面 UI 通道重建后 1 turn 真实 provider 预演（S1 前置）；失败 → BLOCKED | 次要 | negative-safety | 是 | 是 | 1 |
| S5B-REG-FULL | — | Host + Memory 双仓全量回归不低于基线（Host 恰 7 条既有红） | — | negative-safety | 是 | 否 | 1 |

quality_bar（positive-value）：终答非空、自然、与请求相关；S1 的 mutation plan 字段（changed/next action）与真实文件 diff 一致；
analysis 产出的记忆条目每条可回指对话原句、无臆造（S5/S6 的 quality_bar 随场景移交 S5c）。

## Assurance 摘要

- Profile：standard；机器可读 contract 见同目录 `assurance-contract.json`。
- 受保护资产：原始证据 append-only（Host + Memory）、workspace root 权限边界、TaskScope canonical state 的 CAS/幂等、
  Provider 调用幂等（零重复计费/零重复副作用）、suppression 的即时生效、S4 单 foreground Run/FIFO、凭据不落盘。
- 最大可接受影响：收口失败只能导致 `semantic_closure_pending`（可重试）与保守终答，不得伪造状态；effect 校验失败只能拒绝执行；
  analysis 失败只能 dead-letter 并保留原始证据；任何情况下不重复调用 Provider、不越权召回、不丢原始证据。

## A15 范围缩减：S5B-S1 的「下一轮 typed recall 可读到」移交下一切（用户 2026-09-04 显式批准）

**用户决定**：原话「移交下一切，把这个记录在followup中」，sha256
`ead12cfb135375eece8c2449658f33947af73d1b8e2ba52909190a9712c972ac`，
原文存 `verification/plan-challenge/user-approval-scope-reduction-2026-09-04.txt`。
与 A14 同为 plan-test DoD 第二类合法出口（用户 chat 显式批准缩减 → 回写 acceptance →
结论按缩减后范围表述）。

**事实依据**（Host `2b32fcb7` 实测，10 轮真实 provider 验证）：

- `typed_recall_attempts` **10/10 轮均为 0 行**；其中 5 轮业务全链通过（README 改写、
  收口回执 `outcome=mutate`、outbox/links、episode 物化）——即**业务成功也不产生召回**。
- 后端日志 `context_route` 出现 **0 次**：模型从未调用该工具。
- `context_route_decisions` 两轮均为 Host 自签 `origin=host_initial` / `route=resume_existing`。

**机制**：typed recall 仅在 `context_route(memory_standalone)` 被选中时执行
（`main.py::recall_executor` → `sdk_adapters/context_route.py:302-315`）。前台任务链首轮由
Host 自签路由回执（`foreground_runtime_ports.py::verify_initial_route` 记 `origin=host_initial`），
模型无机会选择 `memory_standalone`。**该要求在当前接线下不可满足**，与提示词措辞、
是否新建 scope 均无关（两种测法都试过且都为 0）。

**这不是执行缺失，是 plan 层缺口**：plan 从未为这一环安排可达路径或 oracle。补它属**新增接线**
（让前台链在有可用记忆时走召回路由，或由 Host 在上下文装配阶段直接注入 typed recall），
不是缺陷修复。

**对 S5B-S1 证据契约的影响**：`required_business_facts` 的 `next_turn_typed_recall_hit`
在本增量记为 **`NOT_MEASURED`（结构性不可达）**，并附上述实测数字与机制说明；
**不得**填写「已物化，可供下一轮 typed_recall」这类推断措辞——独立终审正是据此判 P1。

**交付纪律**：S5b 结论必须写明这一环未闭合，不得用「记忆已物化」暗示「下一轮读得到」，
也不得用其他场景的 PASS 稀释。义务登记在 `HANDOFF-S5b.md` §8 与 §8.1。

## A14 范围缩减：S5B-S1 的真实桌面 UI 面移交 S6（用户 2026-09-03 显式批准）

**用户决定**：原话「判定 UI 面移交下一切」，sha256
`6086418dcc44ba2e7f4be13c9ced929cc7241f614cc16662bfa25e3fc3c2c41b`，
原文存 `verification/plan-challenge/user-approval-scope-reduction-2026-09-03.txt`。
本条是 plan-test DoD 允许的第二类合法出口（「用户 chat 显式批准缩减，已回写 acceptance，
结论按缩减后范围表述」），据此回写本文件。

**事实依据**（Host `620a6f18` 实测，8 次真实桌面 UI run）：
1. S5b 生产链（前台队列准入 → 工作区绑定 → EffectGate → 语义收口 → Memory analysis）由
   `HumanMemoryHostService.enqueue_turn` 驱动（`memory/human_memory_service.py:794`）。
2. `enqueue_turn` 生产上只有一个入口：WebSocket `human_memory_request` +
   `operation:"queue.enqueue"`（`memory/human_memory_api.py:207`，`main.py:14883` 分发）。
3. 桌面 UI 普通聊天走 `chat_v2`，**从不入队**；全仓 `after_enqueue` 只在 `main.py:11011`
   的启动恢复处调用一次。
4. 前端**没有任何**发送 `human_memory_request` / `queue.enqueue` 的代码；只在 run projection
   里展示 `task_scope_id`，没有「对某个 TaskScope 发起一轮」的界面动作。
5. 实测佐证：4 个真实 UI run 的 `foreground_runs` 表全为 0 行；项目会话里模型激活
   `edit_file`/`read_file` 后，`context_route` 以 `workspace_binding_current_run_authority_missing`
   失败（`task_scope/runtime_binding_authority.py:288`，因 `current_snapshot` 返回 None）。

**定性**：这不是产品缺陷，也不是本增量改动引起——该链路的 UI 入口属 **S6（全部 UI）**，
而 S6 在本增量 plan/acceptance 里本就是明确的范围外与停止追踪点。S5B-S1 当初标
`manual_required=是（真实桌面 chat UI）` 属起草时的范围错误。

**独立裁决（2026-09-03，裁决 D）修正了本节初稿的两处过头**，以裁决为准：
1. **不接受**「pytest 真实车道即本 AC 主证据」。该车道替换了多处生产接缝——
   `s5b_milestone_harness.py:83-89` 用 `h.freeze_run` 代替 `ProductForegroundToolPort.freeze`、
   用 `make_bound_scope` 绕过 `context_route → append_binding`、手工 `claim_and_bind` 绕过
   `ForegroundRuntimeExecutionAuthority`；`s5b_effect_gate_harness.py:473-490` 配 `_ManualAuthority()` 桩。
   本增量自己的 `notes-investigation-task7b.md` 已承认该盲区（"基座把 `write_file` 直接放进
   ReActLoop 目录，根本没走产品的 deferred 披露/激活路径"——S5B-UI-F1 正是这么漏掉的）。
   它是很强的组件级真实证据，但不是 `MANUAL_MIN_POSITIVE_SAMPLES` 要求的"真实**入口**"端到端。
2. **实质要求不降级**：缩的只是"真人桌面点击"这个**载体**，改由**唯一现存生产入口**兑现——
   对真实运行后端经同一条控制 WebSocket 发 `human_memory_request` / `queue.enqueue`
   （`memory/human_memory_api.py:207-214`，未来 S6 那个按钮必然调用的同一段代码），
   自然用户语言 + 真实 provider + 真实文件 diff + 人工核对达 quality_bar。
   **补不上这条 → 本增量退化为 BLOCKED**，不得以 pytest 车道顶替。

**缩减后的边界（只缩这些，其余不动）**：
- S5B-S1 的**载体面**（真人桌面点击）移交 S6；`manual_required` 改为
  「真实生产入口 WS `queue.enqueue` + 真实后端进程」，业务判据与 `min_root_runs=2` 不变。
- 随之移交 S6 的还有 **≥20 turn 长上下文会话**（S5a 是经真实桌面 UI 完成的，S5b 无此入口）。
- **不缩减**：S5B-S1 的业务判据一字不改（真实 provider 改文件 → 客观事件脏标记 →
  `task_scope_update` 收口 → 同事务 outbox → analysis accepted；≥2 独立 root run；
  一个 Run、一次 attempt、零重复 Provider 调用；STATUS 与文件变更一致）。
- **不缩减**：S5B-S7 冷启动与 S5B-S8 真实 UI 通道两条 UI 面**照旧 required 且已 PASS**
  （证据 `.local-test-evidence/real-ui-channel/20260903T030437-uiA` 与 `20260903T1130-uiA`）。

**结论措辞纪律**：S5b 的交付结论必须写明「真实桌面 UI 面移交 S6」并给出本节链接；
不得以 S5B-S7/S8 的 UI PASS 或 pytest 车道 PASS 暗示 S5B-S1 的 UI 面已验证。

**登记的义务（不许悬空；编号按裁决）**：
- **OBL-1 → S6（S5b 侧为 P1 交付缺口）**：human-memory 前台队列在桌面端无用户入口。
  S6 acceptance 必须显式写明：① 主对话发送打到 `queue.enqueue` 而非 `chat_v2`；
  ② 有 UI 承接 `binding.manual.decide` 的挑战确认（该操作同样仅 WS 可达）。
  S6 的 required 真人 E2E 应把 S5B-S1 的最小验证动作原样纳入。
  **定性**：在它建成前，S5b 交付的整条能力链**用户价值为零**。
- **OBL-2 → 本增量自己（P0 / 回归级，已实测证实）**：**PROJECT_EFFECT 工具在桌面聊天会话中
  结构性不可达**。AC-3④ 预设「普通聊天 Run 可先建 TaskScope、下一轮写入」，而
  `context_route._create_new → append_binding → _append_auto`
  （`task_scope/runtime_binding_authority.py:288`）硬依赖前台 Run 快照，`chat_v2` Run 永远拿不到。
  决定性测试 `backend/tests/sdk_adapters/test_chat_session_project_effect_reachability.py`
  在**生产装配**（真实 `WorkspaceBindingRuntimeAuthority` + 真实 `ForegroundQueueStore`）下
  **已证实**：无前台 Run 时 `append_binding` 抛 `workspace_binding_current_run_authority_missing`；
  对照组（走生产 `enqueue_turn` 拿到前台 Run）前置条件满足。与 8 次真实 UI 实测一致。
  **与 `BEHAVIOR_POLICY = preserve-approved` 冲突**（写文件是已交付能力），不得推给 S6。
  两条出路属技术选型，需另开独立裁决：① 让 `_append_auto` 接受非前台 Run 的准入权威；
  ② 明确「桌面聊天会话在 S6 前不提供项目写入」并作为**已批准行为的显式缩减**入账（需用户批准）。
  **不允许沉默现状。**
- **OBL-3 → 本增量 retro（流程义务）**：验收矩阵起草期缺一道「该场景的最小验证动作，在本增量
  **起点 HEAD** 上是否存在可达的生产入口」的检查。S5B-S1 与本文件「S6 全部 UI 范围外」在**同一份
  文档内**自相矛盾，却通过了 challenge / minimality 两道审。建议写入 plan-test 起草检查表：
  **每个 `manual_required=true` 的场景，必须给出该入口的 file:line，或标注「入口由本增量交付（Task N）」。**

## 完成的定义（DoD 摘要）

1. 决定性 S5B-AC-1/2 实测达成（MUST = AC-1/2/3/6，AC-4/5 移交 S5c）（最小验证动作在**真实 provider + 生产 `enqueue_turn` 入口**上 PASS，≥2 独立 root run；**真实桌面 UI 面与 ≥20 turn 长会话移交 S6**，见 A14）——此二条 FAIL 时其余 PASS 不救场；
2. 全部必须 AC 有 required 证据；HM-AC-8 质量门如实记 `NOT_RUN/BLOCKED`（外部人工语料前置）；
3. 机器门 `finalize` exit 0 + receipt（MACHINE_GATE 启用）；
4. 三仓文档回写（Host ARCHITECTURE/PROJECT_STATUS、Memory CHANGELOG/PROJECT_STATUS、本增量 RUNLOG/journal/retro）；
   S5a 遗留义务逐条有去处（做掉或显式顺延且写明理由）。
