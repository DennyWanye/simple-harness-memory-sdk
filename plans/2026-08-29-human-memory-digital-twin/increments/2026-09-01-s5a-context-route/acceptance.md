# 增量验收：S5a — Host 动态 Context、五路 context_route 与同 Run continuation

> 状态：DRAFT（待用户确认）
> 父事实源：`../../acceptance.md`（program 级唯一真相，HM-AC-3/4/6/7/8 与冻结场景矩阵/LLM 变异清单在彼处）
> 流程：plan-test / FULL / MACHINE_GATE 启用（公共 Provider/API + 跨三仓 + LLM 载荷驱动状态机 + 共享生产 composition）
> S5 拆分：S5 slice 按 release-unit 门限拆为 S5a（本增量：Task 1–4 + Task 8 核心 + Memory 0.6 消费面补全）
> 与 S5b（Task 5 effect gate、Task 6 semantic closure、Task 7 Memory analysis/Prospective scheduler、
> semantic-relations pre-admission audit、S4 P2 清理）。

## 矛盾分析（骨架）

- **主要矛盾**：用户在永久主对话里说一句话时，主模型能否在同一个 Run 内正确判断这句话需要什么上下文
  （直接答 / 用记忆答 / 继续当前任务 / 恢复旧任务 / 开新任务）并据此拿到刚好够用的上下文完成回答。
- **产生原因**：S1–S4 已各自就位（协议、记忆、TaskScope 档案、执行调度），但互不相连——Host 生产 chat
  链仍是"10,000 行历史尾巴、恒 UNROUTED、memory 分区恒 None"的旧链路；SDK 0.7 要求的三个 mandatory
  authority port（run_context_authority / runtime_decision_sink / task_execution_authority）在 Host 只有必抛
  的空壳代理；Memory SDK 0.6 从未被 Host 生产接入。记忆与任务档案存在，却到不了主模型面前。
- **解决方向**：Host 实装三个 concrete authority 与 `context_route` 工具，把路由判断交给主模型、把裁决与
  上下文供给交给确定性代码：初始有界 Context → context_route → 同 Run continuation → terminal。
- **最小验证动作**（价值验证里程碑）：在含既往任务档案的 fresh Host 上，经真实 provider 输入"继续以前的
  A"：主模型经 `context_route` 收敛 `resume_existing` → search 候选 → exact open A → 同 Run continuation
  使用 exact ResumePackage 完成正确回答；全程一个 Run，产生 route receipt 与逐 Provider-turn snapshot
  receipt（Host expected hash = Harness request fingerprint = adapter captured payload hash）。
- **矛盾的主要方面**：五路 route + 同 Run continuation 的生产链能否真跑通（预算精调与质量阈值是价值成立
  之后的事）。

## 范围

**包含（S5a）**：

- S5 slice Task 1：初始 Context 与最近 10 完整因果 turn group（替换 `_bounded_sdk_history` 尾巴算法；
  大 tool result 摘要+exact ref page-in；分区预算与裁剪严格按 V0 冻结 oracle）。
- S5 slice Task 2：五路 `context_route` tool（strict schema、Host 裁决、search→exact open 分步、
  Host+Memory linked decisions）。
- S5 slice Task 3：Recall observation 与同 Run continuation（typed ContextFragments 二审资格、
  route receipt 作 function_call_output、no-recall 单 invocation、provider capability 按 V0 矩阵默认禁用
  reasoning continuation）。
- S5 slice Task 4：最终 Context assembler 每 Provider turn authority（`RunContextAuthorityPort` concrete
  实装、immutable snapshot per-turn revision、三 hash 相等、durable route/no-recall decision ledger）。
- S5 slice Task 8 核心：`_build_product_sdk_runtime_stack()` 注入三个 concrete authority + durable
  dependencies，缺任一 startup stable fail；Memory 0.6.0 wheel exact pin 接入；composition 断言与
  critical/affected smoke。
- Memory SDK 0.6 消费面补全（本增量的跨仓前置，Memory 仓代码改动）：
  ① `core.jobs` 消费符号（`DurableMemoryJobRunner`/`MemoryJobWorkerConfig`/`DurableJobRepositoryPort`）
  进入包根公开导出；② mandatory Prospective occurrence inbox 只读 reconcile API（provider 调用前
  `no_recall` 门的前置）；③ outbox 公开只读 reader（供 S5b 消费，本增量只交付 API）；④ v7 facade 的
  embedder production 守卫（hash/mock 在 production 拒绝）；⑤ 构建可复现 0.6.0 wheel + candidate
  manifest，修复 `uv.sources` 失效路径。
- Host 侧 `MEMORY_STANDALONE` 路径接通：typed recall（`execute_typed_recall`）与五天 short-horizon
  （`recall_short_horizon`）经 route 进入 Context（首次生产接入 Memory 0.6）。

**明确不包含（留 S5b / S6 / 外部门）**：

- Task 5 TaskExecutionEnvelope/workspace effect gate（S4 的 per-effect envelope 现状继续生效；多 root
  project effect 继续稳定 fail-closed）。
- Task 6 客观事件 + TaskScope semantic closure（closure watermark/dirty flags/terminal gate 扩展）。
- Task 7 主模型 Memory analysis、Host↔Memory ingestion outbox 生产消费、Prospective 唯一 scheduler。
- semantic-relations 留给 S5 的 Host durable pre-admission audit 实装（9 处 `BLOCKED_UNTIL_S5` 标记
  在 S5b 翻转）。
- **HM-AC-8 路由质量阈值门**（100%/90%/85% 与 p95 指标）：外部前置是"独立人工 review 冻结 240 条
  路由语料标注"（当前 `AI_DRAFT_UNREVIEWED`）；S5a 只交付生产链与确定性正确性，质量门如实保持
  `NOT_RUN/BLOCKED`，不以 deterministic fake 或未审语料冒充 PASS。
- S6 全部 UI；三仓 tag/push/publish；旧数据迁移。

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 矛盾地位 | 优先级 |
|----|--------|-------------------|----------|--------|
| S5A-AC-1 | 五路 context_route 生产链 | deterministic provider 下五类输入（HM-S10 六步）分别收敛到 exact 五路终态并产生 durable route receipt；standalone 不改 active cursor 且无项目写权限；search 命中不直接切 scope；歧义 resume 产生 clarification。真实 provider 下至少 direct_standalone（HM-S1 no-recall）、resume_existing（HM-S2）、continue_active 三路各 ≥1 次正向 root run 走通。 | 决定性 | 必须 |
| S5A-AC-2 | 每 Provider turn immutable snapshot 与三 hash 相等 | `ProductRunContextAuthority.prepare_snapshot` 成为每 Provider turn authority：snapshot_revision 跨轮单调、同 ID payload 不可变；provider reservation 前 receipt 入 checkpoint；Host expected hash = Harness request fingerprint = adapter captured payload hash 三者相等（20+ turns、大 tool result、两 TaskScope+resume、kill/replay 各 lane）；route receipt 作 function_call_output 回同一 Run，不另建 Run。 | 决定性 | 必须 |
| S5A-AC-3 | 初始 Context：10 因果组与冻结分区预算 | 历史按 user-turn 起、assistant terminal、tool call/result 配对成组，取最近 10 完整组；未终结当前 Run 单独标注；大 tool result = typed summary + exact ref（raw 可 page-in）。分区 caps/reserve/safety margin/裁剪顺序严格等于 `testcase/human-memory-program/fixtures/metric-formulas.json` 与 SPIKE-CONTEXT-DOC 冻结值（引用不重列）；真实 provider usage 校准出现任何 estimator underestimate → 本增量 BLOCKED 重做预算。 | 次要 | 必须 |
| S5A-AC-4 | no_recall 门与 mandatory inbox reconcile | Provider 调用前 reconcile 谓词（specialist 修订）：`pending = { matched occurrence | intent 当前处于 live/presentable 状态 ∧ 通过 recipient/purpose/suppression 资格门（与 S5A-AC-5 同一门）∧ occurrence_key ∉ v45 presented set }`；pending 非空 → 禁止 terminal `no_recall`，合资格 summary 进 initial snapshot；非 presentable/不合资格的 occurrence **不阻塞** no_recall（由 S5b settle 为 suppressed/superseded，防死锁且防 FORGOTTEN 内容入 Context）。presented set = per-occurrence append-only membership（身份键 `occurrence_key`，非标量 cursor）；S5a 只读比对零写入，presented/settled 前移属 S5b。**S5a 边界声明**：生产链尚无 occurrence producer（Task 7 属 S5b），生产 inbox 恒空，谓词真空成立；门的存在性由 required 负测试证明——**经既有生产写路径 `apply_prospective_signal` + 测试注入 prospective_signal_authority resolver** 产出真实 `matched` trigger event（不得 raw seed DB：backend open 时强制 FK + 审计链校验会拒开 store），断言 no_recall 被拒且 summary 进入 snapshot。no-recall 路径 = Memory 零查询 + 恰一次 provider invocation + durable `DIRECT_STANDALONE` decision（经 `record_no_recall`）。 | 次要 | 必须 |
| S5A-AC-5 | typed recall observation 与二审资格 | `memory_standalone`/recall 路径经 `execute_typed_recall`/`recall_short_horizon` 返回 typed fragments；Host 在进入 Context 前二次执行 recipient/purpose 与 suppression 校验、按最近窗口/TaskScope state 去重；fragments 带 source ref/type/eligibility/bytes/tokens；timeout/degraded 走稳定降级不半状态。 | 次要 | 必须 |
| S5A-AC-6 | 生产 composition fail-closed 与版本锁 | `_build_product_sdk_runtime_stack()` 注入三个 concrete authority 及 durable dependencies；逐项移除任一 prerequisite → startup stable fail（禁止 Noop/fake/metadata fallback）；Memory 0.6.0 wheel exact version+SHA pin（vendor + candidate manifest），Host 对错误 wheel hash fail-closed；provider reasoning continuation 按 V0 capability matrix 默认全禁。 | 次要 | 必须 |
| S5A-AC-7 | Memory 0.6 消费面补全（跨仓） | 包根公开导出 jobs 消费符号与 occurrence inbox / outbox 只读 API（exact-wheel package-root import 通过）；v7 facade 对 hash/mock embedder 在 production 拒绝；0.6.0 wheel 两次 clean build 字节一致并出 candidate manifest；Memory 全量测试与 consumer contract 不回归。 | 次要 | 必须 |

## 非功能 / 边界（只列本增量真实相关）

- **program 硬架构契约**（`../../plan.md:87-112`）本增量直接背负：89-91（DisclosureContext 收窄）、
  92-93（三 hash 相等）、98-99（public/opaque continuation、reasoning 默认禁）、102-103 的 inbox 半句
  （no_recall 只在 mandatory inbox reconcile 后成立）、110-112（唯一 composition owner，P0）。
- 旧链路移除遵循 `BEHAVIOR_POLICY=preserve-approved`：`_bounded_sdk_history` 尾巴算法与恒 UNROUTED 行为
  是被 program acceptance 明确取代的旧行为，可删；continuation 分支 32k 硬编码预算须收敛到同一 planner。
- LLM 载荷五类变异（program 冻结清单）适用于 `context_route` tool 载荷：SDK 层兜底已冻结（strict
  schema/size/idempotency/route barrier），Host 增量必须补 route tool 自身的 schema 违约/拒调/重复用例。
- 冷启动：fresh userdata → 配置 provider → 直达对话可用（`stateful_init=true`；暖重启不算）。
- **program 硬契约 102-103 的解释声明**：本增量把 program plan.md:102-103 字面『mandatory inbox 已清空』
  解释为『reconcile pending 集合为空』——不合资格/非 presentable occurrence 不阻塞 no_recall，由 S5b
  settle 为 suppressed/superseded（防 no_recall 永久死锁与 FORGOTTEN 内容入 Context 的双失败路径；
  裁决记录 = challenge ledger S5A-DS-F1）。此为对 program 字面口径的显式收窄解释，随本 acceptance
  交用户批准。
- **slice cutover 义务**（program cutover 表：默认开启前完成 compatibility/rollback drill 与旧入口拒绝
  测试并产出 slice-specific cutover receipt）：v45 migration 前向应用 + 旧 runtime 打开 v45 userdata
  stable reject；composition 缺件回退演练；occurrence presented 表存在且恒空断言（S5a 零写入证据锚点）；cutover receipt 纳入 DoD 证据。回滚不删除新 evidence。
- 凭据纪律：真实 provider APIKEY 只进进程与 OS keychain，不落仓库文件、不打印、不进证据。
- **DisclosureContext 构造来源**：单用户 chat lane 的 recall DisclosureContext 由 Host 从 authenticated
  subject 构造（recipient=USER_SELF，purpose=TASK_EXECUTION，样板 = S4 human_memory_service 的
  enqueue_turn 构造）；模型同名值一律被 Host 覆盖；S3 wheel 的 RecallPlan/RecallContext 已内建该结构。
- 性能边界（本增量下限，非质量门）：no-recall 路径零 Memory 查询；recall 硬 deadline 2s（SDK 常量）
  的超时走稳定降级。p95 阈值属 HM-AC-8 质量门，S5a 不宣称。

## 适用性声明

- `input_sensitive=true`：路由判断质量随自然语言语义变化；场景矩阵引用 program 冻结 HM-S1/S2/S10
  （decided_by=user，program acceptance 已批）。真实主模型 root run ≥2 轮独立完整跑，其一在 ≥20 turn
  长上下文会话中（program 冻结的 STOCHASTIC 规则）。
- `llm_payload_driven=true`：context_route/recall 结构化载荷驱动 Host 状态机；变异清单引用 program 冻结表。
- `stateful_init=true`：三 authority durable ledger 新持久化状态 + fresh 冷启动。

## 测试场景矩阵（引用 program 冻结场景，S5a 子集口径）

| scenario_id | 引用 | S5a 口径 | gate_type | required | manual_required |
|---|---|---|---|---|---|
| S5A-S1 | HM-S1 | no-recall：真实 provider，零 Memory 查询 + 单 invocation + durable decision | positive-value | 是 | 是（真实桌面 chat UI） |
| S5A-S2 | HM-S2 | 久远任务恢复：search→exact open→同 Run continuation 用 ResumePackage，不混入 B | positive-value | 是 | 是 |
| S5A-S3 | HM-S10 | 五路分流六步矩阵：deterministic provider 全五路 + 真实 provider 三路正向 | positive-value | 是 | 是 |
| S5A-S4 | HM-S8 子集 | context_route 载荷五类变异 + timeout/refusal → fail-closed/降级，无半状态 | negative-safety | 是 | 否 |
| S5A-S5 | 新增 | 20+ turn/大 tool/两 TaskScope/kill-replay 的 snapshot 三 hash 与因果组不破坏矩阵；**twin-influence-zero**：digital twin graph DTO 不得成为 assembler source（import/dependency/serialized-payload 负测试 + snapshot 重放断言 Context 不含图谱数据） | negative-safety | 是 | 否 |
| S5A-S6 | 新增（冷启动） | fresh userdata → 配 provider → 直达对话；composition 缺件 startup fail | negative-safety | 是 | 是 |

## Assurance 摘要

- Profile：standard；机器可读 contract 见同目录 `assurance-contract.json`。
- 受保护资产：ContextSnapshot 可审计性与三 hash 一致、route/decision durable ledger、原始证据完整、
  recall 资格边界、单 Run/FIFO（承接 S4）。
- 最大可接受影响：路由错误只能导致保守回答/clarification，不得越权召回或执行；provider 不可用时
  fail-closed 不半状态；任何情况下不丢原始证据。

## 完成的定义（DoD 摘要）

1. 决定性 S5A-AC-1/2 实测达成（最小验证动作在真实 provider 上 PASS）——此二条 FAIL 时其余 PASS 不救场；
   **真实 provider 配置由用户在里程碑检查点前提供**（Settings 写 keychain 或进程内注入）；配置不可得
   时本增量终态只能是 BLOCKED，deterministic lane 的通过不得冒充 DoD 第 1 条；
2. 全部必须 AC 有 required 证据；HM-AC-8 质量门如实记 `NOT_RUN/BLOCKED`（外部人工语料前置）；
3. 机器门 `finalize` exit 0 + receipt（MACHINE_GATE 启用）；
4. 三仓文档回写（Host ARCHITECTURE/PROJECT_STATUS、Memory CHANGELOG/PROJECT_STATUS、本增量 RUNLOG）。
