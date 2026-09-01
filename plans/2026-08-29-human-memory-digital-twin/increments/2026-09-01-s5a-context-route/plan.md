<!-- plan-status: draft (待 challenge 与用户批准) -->

# Plan：S5a — Host 动态 Context、五路 context_route 与同 Run continuation

## 主要矛盾（承 acceptance）

- 一句话：主模型能否在同一 Run 内正确判断"这句话需要什么上下文"并据此完成回答。
- 最小验证动作 = 价值验证里程碑（Task 2 末）：真实 provider 下 "继续以前的 A" → `resume_existing` →
  search→exact open→同 Run continuation 用 exact ResumePackage 回答；一个 Run、route receipt、
  逐 turn snapshot receipt 三 hash 相等。
- 主要方面：五路 route + 同 Run continuation 生产链跑通。

## 现状调查结论（2026-09-01 四路并行调查，结论已核对 file:line）

1. **route 三件套零实现**：`sdk_run_context_authority` / `sdk_runtime_decision_sink` /
   `sdk_task_execution_authority` 三个 service_context slot 全仓无 register，`main.py:7659-7693` 的代理
   一经调用必抛 `*_unavailable`——SDK 0.7 authority 路径在生产链上从未走通（P0，program plan.md:110-112）。
2. **Context 是 Run 级一次性冻结**：`_prepare_sdk_context_snapshot()`（main.py:11434）每 Run 只调一次；
   无 snapshot_revision、无 per-turn 重算；`_bounded_sdk_history()`（main.py:11392）是 10,000 行贪心尾巴，
   无因果组；continuation 分支另有 32k 硬编码预算（main.py:11053）构成第二套真相。
3. **chat 链恒 UNROUTED**：`_sdk_ingress.start`（main.py:11760）不传 initial_route_receipt；foreground 链
   （S4）已有 HOST_INITIAL route receipt 构造样板（foreground_runtime.py:575-610）可复用。
4. **memory 分区死路**：生产链 `memory_items=None`（main.py:9874）；`recall_adapter.py` 就绪但未接入。
5. **无 context_route 工具**：77 工具 manifest 零路由雏形；route 工具须 direct kernel + manifest 同步。
6. **Harness 0.7.1 冻结面足够本增量全部消费**（无需 SDK 改动）：`TaskScopeRoute` 五路、
   `ContextRouteReceipt` v1–v3 + origin、`RunContextAuthorityPort`（prepare_snapshot 单方法）+
   `RuntimeDecisionSinkPort`（record_no_recall，强制 DIRECT_STANDALONE+空 recall_refs）、react_loop 的
   三 hash 校验链（provider reservation 前 receipt 入 checkpoint）、CONTEXT_CONTROL 工具返回值
   `context_route_receipt` 解码、`signal_conversation+prepared_context`、五类载荷变异兜底
   （strict schema/size/topo/idempotency/route barrier）。关键约束：`route_state=UNROUTED ⟺ receipt=None`；
   同批 route+project-effect 拒绝；开启 authority 必须提供 sink。
7. **Memory 0.6 消费缺口（本增量跨仓前置）**：occurrence inbox 查询 API 不存在（全仓无 `inbox`）；
   `core.jobs` 符号不在包根导出（违反 exact-wheel oracle）；outbox 无公开 reader；0.6.0 wheel 未构建
   （`uv.sources` 指向不存在路径）；v7 facade 对 hash/mock embedder 零 production 守卫；
   `recall_for_turn` 等 legacy API 对 v7 backend 必然 PERMANENT 失败（不可用作 AgentMemoryPort）。
   typed recall 的 cognitive vector lane 无条件降级（语义向量只在五天短时域）——本增量按此现实设计，
   不虚构长期向量召回。
8. **冻结 oracle**（引用不重列）：分区预算/裁剪顺序/reserve/margin =
   `simple_harness/testcase/human-memory-program/fixtures/metric-formulas.json` + SPIKE-CONTEXT-DOC
   （capacity-results.json，manifest SHA `13a2f2b5…`）；provider reasoning continuation 四家默认全禁
   （SPIKE-PROVIDER-CONTINUATION）；fault lanes = fixtures/fault-matrix.json（`prospective-occurrence`、
   `foreground-fifo-closure` 等）；TC-HM-01/02/10/11 已为五路/no-recall/snapshot 预置 oracle（TC-HM-10:33
   明文"五路自然语言分流属 S5"，本增量正是兑现方）。
9. **质量门外部前置**：240 条路由语料 `AI_DRAFT_UNREVIEWED`、`quality_gate NOT_RUN/BLOCKED`；无评估
   runner。本增量不建 runner、不宣称质量门（S5b/S6 承接）。
10. **S4 现状承接**：工作基线 = `fix/human-memory-runtime-p1-closure` @ `c9f73349`（receipt `dbaeaae7…`）；
    11 项 open P2 不在本增量（S5b 清理）。

## Spike 证据（实践先行，已实测）

- **SPIKE-S5-WHEEL（PASS）**：`uv build --no-sources` 在 memory-sdk 干净树构出
  `simple_harness_memory_sdk-0.6.0-py3-none-any.whl`（sha256 `c4928ed1704c29dd…`）；干净 venv 与
  Harness 0.7.1 wheel 共装无冲突；`build_human_memory_v6()` 在 durable path 上完成 fresh v7 schema
  init（≈1.4MB）。附带事实：`:memory:` 被显式拒绝；两次 clean build 字节一致性与 candidate manifest
  留 Task 4 正式化。
- **Harness authority 路径**：SDK 侧已有集成测试用 fake authority 走通 prepare_snapshot→三 hash→
  checkpoint 链（simple-harness-sdk tests/integration/runtime/test_human_memory_react_barrier.py）——
  协议可用性已证；Host 侧接线风险集中在 durable ledger 设计，无未验证的关键技术假设。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `backend/deskpet/memory/migrations/037_context_route_ledger_v45.sql`（新） | durable context/route ledger：per-run per-turn snapshot receipt（revision/payload_hash/source_revisions）、route decision、no-recall decision、route tool invocation 血缘；**occurrence presented 表（全列即建，S5a 零写入）**：`occurrence_key` TEXT PK、memory_id、prospective_revision、presented_at/presented_run_id、settled_at/settled_reason（可空，CHECK 单向）——membership 集合语义（哈希键无全序，标量 cursor 不可实现），S5b 纯数据写入接管，本表零 v46 迁移 |
| `backend/deskpet/sdk_adapters/context_authority.py` | 新增 `ProductRunContextAuthority`（prepare_snapshot per-turn）、`ProductRuntimeDecisionSink`（record_no_recall→durable+receipt）；沿用 `PreparedSdkContextSnapshotV1` canonical/redaction 基建 |
| `backend/deskpet/sdk_adapters/context_route.py`（新） | 五路 `context_route` strict tool handler：TaskScopeProposal 解析→Host 裁决（S4 search/open/provision/binding + recall 分步）→ContextRouteReceipt(context_tool) 构造与 durable decision |
| `backend/deskpet/sdk_adapters/causal_groups.py`（新） | 最近 10 完整因果 turn group planner（user 起、assistant terminal、tool 对配对；未终结 Run 标注；大 result→typed summary+exact ref） |
| `backend/deskpet/sdk_adapters/context_partitions.py`（新） | 分区预算 assembler：冻结 caps/reserve/margin/裁剪顺序（引用 metric-formulas.json 常量表）；page-ref |
| `backend/deskpet/sdk_adapters/task_execution.py`（新） | `ProductTaskExecutionAuthority.issue_envelope`：从 route receipt + S4 exact binding set 签发（单 root；多 root 维持 fail-closed） |
| `backend/deskpet/memory/recall_adapter.py` | 扩展：v7 facade 的 `execute_typed_recall`/`recall_short_horizon` 消费 + fragments 二审资格 + occurrence inbox reconcile |
| `backend/deskpet/tool_catalog/providers.py` + `real_tool_manifest.json` | 注册 `context_route`（CONTEXT_CONTROL、direct kernel）；manifest count/sha 同步 |
| `backend/main.py` | `_build_product_sdk_runtime_stack` 注册三 concrete authority（缺件 startup fail）；chat 链接入 per-turn authority；`_bounded_sdk_history`/32k continuation 预算收敛；Memory 0.6 pin 接入 |
| `backend/pyproject.toml` + `backend/vendor/` | `simple-harness-memory-sdk==0.6.0` + wheel + candidate manifest |
| memory-sdk `src/simple_harness_memory/__init__.py`、`core/jobs.py`、`core/manager.py`、`backends/sqlite_v5.py` | 包根导出 jobs 符号；occurrence inbox 只读 API；outbox 只读 reader；embedder production 守卫 |
| memory-sdk `pyproject.toml`、`docs/build-and-release.md` | 修 `uv.sources` 路径；本机构建说明 |
| `backend/tests/sdk_adapters/`、`backend/tests/test_execute_sdk_run.py`、testcase runners | black-box route/snapshot/预算/变异/kill-replay 用例（oracle 先于实现，见 Task 0 交付） |

## 方案选择与取舍

- **durable ledger 放 Host state.db v45**（非 SDK execution DB）：route/no-recall/snapshot receipt 是 Host
  authority 事实，与 S4 v39–v44 同库同纪律（append-only + head CAS）；SDK checkpoint 里已有 receipt 副本
  作交叉校验。
- **扩展而非重写 `PreparedSdkContextSnapshotV1`**：canonical hash/redaction 基建可用；per-turn 语义由新的
  `RunContextSnapshot` 构造层承担，Prepared 结构降级为"分区物料"内部产物。
- **新写轻量因果组 planner**，不复活 `session_history_planner`（绑 legacy segment store、与 revision 模型
  不兼容；Ponytail：513 行旧资产 vs ~200 行贴协议新实现）。
- **route 工具走 CONTEXT_CONTROL + direct kernel**：SDK 强制 CONTEXT_CONTROL 双 FORBIDDEN 且同批拒
  project effect，天然满足 route barrier；`memory_standalone` 的 recall 在 route handler 内同步执行并把
  fragments 经 prepared_context 送回同 Run（`signal_conversation` 路径），不新建 Run。
- **task_execution_authority 本增量按 S4 现状签发**（单 root exact、多 root fail-closed）：满足 SDK
  PROJECT_EFFECT 校验链即可；effect gate 深化留 S5b Task 5。
- **Memory 接入现实边界**：长期认知召回无向量 lane（SDK 现实），本增量语义检索 = 五天短时域向量 + 长期
  typed/FTS 资格召回；不为此加依赖。inbox/outbox API 在 Memory 仓以最小只读面补齐，写侧协议不动。
- **真实 provider**：本机当前无可用配置（config.toml api_key 空、无 .env）——真实 provider 场景执行前需
  用户提供配置（Settings 写 keychain 或临时注入）；计划将此列为执行期已知 BLOCKED 风险，deterministic
  provider lane 先行。

## 任务清单（最短价值路径优先；oracle 先于实现贯穿）

> 里程碑绑定最小依赖闭包（challenge S5A-BR-F1 修正）：最小验证动作只依赖 Task 0–2 + provider 配置；
> 因果组/分区预算（次要 S5A-AC-3）后置到里程碑之后。

### Task 0 — oracle 定稿、基线锁定与 provider 配置检查点 [全 AC]
- 依 TC-HM-01/02/10/11 冻结 oracle 写本增量 black-box 用例骨架与 verification-spec 草案（S5A-S1…S6
  映射、evidence contract、oracle_pins 逐文件 pin + 统一 file-bytes hash 口径）；锁定绿色基线。
- **provider 配置检查点（S5A-BR-F2）**：向用户请求真实 provider 配置（Settings 写 keychain 或进程内
  注入）并执行一次连通性 smoke；不可得 → 记录 BLOCKED 风险并继续 deterministic 先行，但 DoD 第 1 条
  的终态口径固定为"配置不可得 = 增量 BLOCKED"。
- 核对 chat lane DisclosureContext 构造参数面（S3 wheel RecallPlan/RecallContext；S4 enqueue_turn 样板）。

### Task 1 — 三 concrete authority 与 v45 ledger [S5A-AC-2/6]
- v45 migration（含 occurrence presented 表——per-occurrence membership，非标量水位）+ 三 authority 实装注册；composition 缺件
  startup stable fail + exhaustiveness 断言；先以现有 Run 级物料出 per-turn snapshot，打通
  prepare_snapshot→三 hash→checkpoint。

### Task 2 — 五路 context_route 工具与 Host 裁决 [S5A-AC-1] → **价值验证里程碑**
- strict tool spec + handler：五路裁决接 S4 search/open/provision/binding；receipt(context_tool) 构造
  与 durable decision；search→exact open 分步、歧义 clarification；manifest/direct kernel 注册；
  chat 链去 UNROUTED（direct_standalone 经 sink）。
- **里程碑执行（口径按 closure S5A-CR-F1 收窄至 Task 0–2 依赖闭包）**：deterministic provider 五路
  **route 裁决 + receipt 收敛**（`memory_standalone` 的 recall 终态显式标 BLOCKED-until-Task-5，不以
  Noop/fake 顶替）+ 真实 provider "继续以前的 A" 同 Run 链（resume_existing 全终态：三 hash snapshot
  receipt + route receipt）→ **demo 给用户 + 矛盾再分析**。全五路 exact 终态验证（含 HM-S10 六步）在
  Task 5 后由 Task 6 执行。**中间态声明**：Task 2–5 间 chat 链产出的 durable DIRECT_STANDALONE
  no-recall decision 属未接 reconcile 门的中间态（生产 inbox 恒空使谓词真空成立但无 reconcile 调用
  证据）；Task 5 接门后 AC-4 证据以带 reconcile 调用的 run 为准。真实 provider 配置未就绪 →
  deterministic 里程碑先行 + BLOCKED 升级真实 lane。

### Task 3 — Memory 0.6 消费面补全与 wheel 接入 [S5A-AC-7]（可与 Task 1/2 并行，Memory 仓）
- 包根导出 jobs 符号；occurrence inbox 只读 API（**返回形状为 S5a 冻结 consumer contract**：event_id、occurrence_key、memory_id、prospective_revision、intent 当前 lifecycle_state、occurred_at、event_hash 及 summary 资格所需 source refs；`(occurred_at, event_id)` 稳定排序（排序键均在返回形状内）保证只读幂等与续读锚点）+ outbox 只读 reader（单测 + consumer contract）；
  embedder production 守卫；修 uv.sources；两次 clean build 字节一致 + candidate manifest；
  Host pyproject/vendor pin 0.6.0，错误 hash fail-closed 测试。

### Task 4 — 因果组 planner 与分区预算 assembler [S5A-AC-3]
- 因果组 planner + 分区预算（冻结常量引用）+ 裁剪顺序 + page-ref；continuation 32k 收敛；
  真实 provider usage 校准（任何 underestimate → 增量 BLOCKED 重做预算）。

### Task 5 — recall observation 与 no-recall 门 [S5A-AC-4/5]
- memory_standalone/recall 路径：typed recall + short-horizon 消费、fragments 二审资格与去重
  （DisclosureContext 按 Task 0 核对的 Host 构造）、prepared_context 回注同 Run；
- no_recall 门：provider 调用前 inbox 只读 reconcile，谓词按 AC-4 specialist 修订版（live/presentable ∧
  资格门 ∧ occurrence_key ∉ presented set；不合资格者不阻塞）；**required 负测试** = 经生产路径
  `apply_prospective_signal` + 测试注入 prospective_signal_authority resolver 产出真实 matched
  trigger event（禁止 raw seed：backend open 强制 FK+审计链校验），断言 no_recall 被拒且合资格
  summary 进 snapshot；另加 FORGOTTEN/suppressed occurrence 不阻塞 no_recall 的对照用例
  （S5a 生产 inbox 恒空为声明边界）。

### Task 6 — 验收矩阵、cutover 与回归收口 [全 AC]
- S5A-S1…S6 场景执行（真实 provider ≥2 独立 root run，其一 ≥20 turn）；载荷五类变异 + kill/replay
  lanes；twin-influence-zero 负测试（import/dependency/serialized-payload + snapshot 重放）。
- **slice cutover 子项（S5A-BR-F5）**：v45 前向 migration 测试 + 旧 runtime 打开 v45 userdata stable
  reject 测试 + composition 缺件回退演练（rollback drill）+ **occurrence presented 表存在且恒空断言**
  （S5a 零写入的 required 证据锚点）→ 产出 slice-specific cutover receipt 纳入 DoD 证据；回滚不删除
  新 evidence。
- changed-surface 静态检查、critical/affected(+命中条件 full-surface) smoke、Host full pytest 与
  Memory 全量回归；机器门 init→record→full-audit→finalize；三仓文档回写。

## Assurance / 信任与失败边界

见同目录 `assurance-contract.json`；执行期硬约束沿用 program（原始证据不删、凭据不落盘、
`.local-test-evidence` 不提交、不 push/tag/merge）。

## 停止追踪点

S5b（effect gate 深化、semantic closure、Memory analysis/Prospective scheduler、pre-admission audit、
S4 P2 清理）；HM-AC-8 质量门（人工语料前置）；S6 UI；多 root effect root-selection 协议。
