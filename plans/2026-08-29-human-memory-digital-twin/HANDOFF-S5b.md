# HANDOFF — 从 S5b 起接手 human-memory program 直至收官

> 交接时间：2026-09-02
> 交出方：完成 S5a 的会话
> 接手范围：S5b（S5 后半段）→ S6（UI + program 验收）→ 全 program 收口
> 本文件是接手方的**唯一开工入口**，读完这一份即可开工。

---

## 0. 一句话现状

第五块（宿主端上下文集成）的前半段 S5a 已交付并签发机器验收凭证，代码已合并进宿主仓 `main`。
下一步是 S5b，即 S5 slice 的 Task 5/6/7；之后是 S6；期间有一项必须真人参与的前置卡着最终质量门。

---

## 1. 仓库与分支现状（开工前先核对）

| 仓 | 路径 | 分支 | HEAD | 与远端 |
|---|---|---|---|---|
| Host | `simple_harness` | `main` | `ec1cb944` | 领先 `origin/main` 32 个提交，**未 push** |
| Memory SDK | `simple-harness-memory-sdk` | `main` | `70edc5d` | 领先 `origin/main` 10 个提交，**未 push** |
| Harness SDK | `simple-harness-sdk` | — | 0.7.1 **冻结** | 本 program 期间不得改 |

- 宿主仓的功能分支 `feat/human-memory-s5a-context-route` 已快进合并进 `main`，分支保留未删。
- `main` 同时被 checkout 在两个 worktree：主目录 `simple_harness/`（当前在 feat 分支，内容与 main 同）
  与 `/private/tmp/shmain-mypy`（在 main 上）。**在主目录开工前先 `git checkout main`。**
- 合并后已复跑宿主全量：`6282 passed / 7 failed`，7 条为本机既有环境红（见 §6）。

---

## 2. S5a 交付了什么（接手方需要知道的既成事实）

机器验收凭证：`b5d416e372e3d2b8c3bd6ac86428941ce896b4123e291e12003697cee9118dac`
（run 目录 `simple_harness/plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-s5a-context-route/verification/r3-s5a`）

已上线的生产能力：

- **五路 `context_route` 工具**：模型每轮先裁决走哪条路（直答、检索记忆、继续当前任务、恢复旧任务、开新任务），
  裁决落 durable 账本。宿主组合，非 SDK 内建。
- **每轮 Provider 调用前的不可变 Context 快照**：三处哈希（宿主预期、Harness 请求指纹、适配层实际载荷）
  必须相等，SDK 在预约 Provider 前强制校验，不等就抛。
- **初始 Context 的因果组与分区预算**：取最近 10 个完整因果组，分区上限/保留量/安全边际/裁剪顺序严格等于
  `testcase/human-memory-program/fixtures/metric-formulas.json` 冻结值。低估预算即失败，不许发超额载荷。
- **no-recall 门**：模型声称"无需回忆"前，宿主必须先核对待办收件箱；有合格待办就禁止该终态。
- **v45 迁移**：`037_context_route_ledger_v45.sql`，含 `occurrence_presented` 表（全列即建，S5a 零写入，S5b 接管写入）。
- **记忆库 0.6.0**：wheel 精确版本 + SHA 锁定，宿主对错误 hash 直接启动失败。

**关键实现文件**（S5b 会大量接触）：

```
backend/deskpet/sdk_adapters/context_route.py       五路路由工具
backend/deskpet/sdk_adapters/context_authority.py   per-turn 快照权威 + 预算装配
backend/deskpet/sdk_adapters/causal_groups.py       因果组 planner
backend/deskpet/sdk_adapters/context_partitions.py  冻结预算常量与裁剪
backend/deskpet/sdk_adapters/task_execution.py      envelope 权威（S5b Task 5 在此深化）
backend/deskpet/memory/human_memory_v7.py           v7 运行时（reconcile / typed recall）
backend/deskpet/memory/migrations/037_*.sql         v45 账本
backend/main.py                                     三权威注册、路由工具注册、epoch 门
```

---

## 3. S5b 要做什么（唯一实施清单）

事实源：`slices/S5-host-context-integration.md` 的 **Task 5 / 6 / 7**。逐字读那三节，下面只是导航。

### Task 5 — TaskExecutionEnvelope 与工作区副作用门 [HM-AC-3/7]

让 AI 动文件前每次重新校验，而不是只在开头查一遍。

- envelope 从**当前轮的路由凭证 + 精确绑定集**生成。**模型不能自己传根路径或版本号来取得权限**，
  这是本任务的核心攻击面。
- 工具执行器执行前重验：任务范围是否 active/open、根目录归属、绑定版本、文件系统身份、权限与风险策略。
  过期或缺失一律 fail-closed，必须等下一轮路由刷新才能恢复。
- Auto 模式只豁免"往文件夹追加"的确认；发布、删除、付款、改权限继续走既有审批门。
- 验证点：HM-S9、同批次里先于路由的副作用、根目录漂移、模型伪造 auto、高风险动作。

**已知前置**：S5a 留了 `PROJECT_EFFECT` 的根签发接线未做（无 root_resolver 时稳定 fail-closed）。
这是 Task 5 的直接前置，先补它。

### Task 6 — 客观事件与任务语义收敛 [HM-AC-3/7/8]

让系统自己判断任务有没有实质进展，不靠猜。

- 宿主的工具/文件/测试事件直接进 S4 recorder；Harness 的 Provider/Tool/Context/Route/Run 事件
  经 source-ledger outbox 导入宿主，设置**确定性**脏标记。**明令禁止用关键词或正则判断语义。**
- `task_scope_update` 接 S1 的 TaskScopeMutationPlan，宿主校验证据引用、基线版本、状态、幂等键后
  调 S4 事务。
- 终态门同时检查三个水位：Harness 证据水位、强制 occurrence 水位、语义收敛水位。
  有实质脏标记却无凭证时，把暂存的最终回答降级为 continuation observation，
  要求**同一个主模型**补一句 `mutate` 或 `no_mutation`；非法或超时标记为 `semantic_closure_pending`，
  **不许伪造 checkpoint**。
- 验证点：HM-TO-R8 多工具批次、模型漏调用或拒绝、CAS 冲突、重复 plan、投影失败。

### Task 7 — 主模型记忆分析、宿主↔记忆库 outbox 与即时操作 [HM-AC-2/7/8]（最重）

- 终态提交在**同一事务**内写宿主净化后的原始证据链接 + 记忆库摄入 outbox。
- 实现 `MemoryAnalysisExecutorPort`：用该轮前台 Run 绑定的 provider/model/config 做独立的
  post-turn 主模型调用。**不许新建独立 extractor 客户端。**
  永久记录 reserved/handed_off/succeeded/failed/unknown 五态尝试与请求/结果/校验凭证。
- **幂等硬要求**：任何 Provider 执行前先按 `request_hash + attempt` 查 durable 尝试记录；
  已成功、或先 unknown 后确认成功的，必须返回同一行，**不得二次调用 Provider**。
  瞬时权威重试仍查同一行；构造新 attempt 只能遵守显式的 unknown-call 分类法。
- 被接受的 Prospective 注册/失效由记忆库 outbox 投影到**唯一**的调度器
  （从现有宿主 ReminderScheduler 衍生）。事件游标与 occurrence 的 claim/presented/acknowledged/settled
  分离；模型拒绝不得标记为 processed。
- 显式的 remember/correct/forget 标高优先级；**forget 的抑制凭证必须在后续普通读取生效前先生效**。
- 按 V0 的 runtime/trigger spike 协议跑故障矩阵，证明各 kill 点可收敛。
- 验证点：崩溃重启、重复载荷、记忆库不可用与死信、宿主原始证据不丢。

### S5b 的验证出口（`slices/S5-host-context-integration.md` §验证出口）

五路路由、no-recall/recall、TaskScope 副作用、语义收敛、outbox、Context 预算，
**生产链全部要有 primary evidence**。

---

## 4. S5b 之后：S6 与 program 收口

事实源 `slices/S6-ui-and-program-verification.md`。要点：

- 移除新建/切换/删除会话的 UI，收敛成唯一聊天入口。
- 新增 TaskScopePanel（活动/最近/搜索/打开、README/STATUS/checkpoint/漂移/血缘阅读）。
- MemoryPanel 从 Fact 列表升级为四类记忆 + 图谱/阅读/审计/更正/遗忘。
- 新增 MemoryGraph：可访问的 SVG 图，有筛选与节点/边详情，**不要动画特效，不引入独立图数据库**。
- 测试必须用**当前 worktree 的 exact build + 隔离 userdata + 真实点击 + 真实 provider**。

---

## 5. 必须真人参与的一件事（卡着最终质量门）

**HM-AC-8 路由质量阈值门**要求：硬触发召回率与隐私禁止项正确率 100%、
required-memory-type 召回 ≥90%、no-recall 判断正确率 ≥90%、额外类型率 ≤15%、
本地检索 p95 ≤500ms 且硬超时 ≤2s。

前置是**独立人工复审那 240 条冻结路由语料的标注**，当前状态 `AI_DRAFT_UNREVIEWED`。
S5a 已按 acceptance 要求如实记为 `NOT_RUN/BLOCKED`。

**接手方注意**：这一项 AI 不能自评自测——拿 AI 自己拟的题考 AI 等于自出自评。
必须请用户安排真人复审语料，否则整个 program 的最终验收拿不到。这件事可与 S5b/S6 并行推进，
但**不许用确定性假数据或未审语料冒充通过**。

---

## 6. 环境与踩坑（省下大量时间，务必读）

### 6.1 Provider 配置（已就绪，不要重配）

- 配置文件：`~/Library/Application Support/com.dennywanye.simpleharness/llm_runtime.json`
- 模型：`gpt-5.6-luna`，端点 `https://ai.svtun.cn/v1`
- 用户明确要求过"本地配置弄好，不要每次都重新输入 provider 信息"。**该文件明文存 key 是产品既有配置面，
  这是用户拍板的口径。绝不要把 key 写进仓库文件、日志或证据。**
- 真实 provider 测试被 pytest 默认排除，跑它必须显式加 marker：
  ```bash
  .venv/bin/python -m pytest tests/sdk_adapters/test_s5a_milestone_real_provider.py -m real_provider -q
  ```
  **忘加 `-m real_provider` 会静默 deselect（"4 deselected"），gate 会把它记成场景失败。**

### 6.2 向量模型

用户指定用 `tencent/WeMM-Embedding-2B`（2048 维 L2）取代 BGE-M3，本地快照在
`~/Library/Application Support/com.dennywanye.simpleharness/models/wemm-embedding-2b`（约 5.1GB）。
torch 三件套严格锁 2.7.1，**不要因为装 transformers 而让它漂到 2.13**（会连带炸 torchvision）。
发布前置：该快照需上传 COS 模型桶，provisioner 只认桶内容。

### 6.3 怎么驱动真实桌面 UI（我花了很久才走通，直接照抄）

真实 UI 验收是硬要求，但有三道坎：

1. **本机原本没有 Rust 工具链**，已装（`~/.cargo`）。首次构建 Tauri 壳需要几分钟。
2. **computer-use 驱动不了这个 dev 窗口**：无签名 dev 二进制的点击命中测试恒被判为"程序坞"，
   键盘事件也进不了 webview。别在这上面浪费时间。
3. **Tauri 壳的身份桥经常僵死**（`get_shared_secret` 拿不到，前端永远"正在恢复身份"）。

**可用的方案**（S5a 用它完成了 21 轮真实会话）：

- 用产品自带的纯浏览器 dev 通道（`App.tsx` 里的 P4-S18 hatch），前端跑在 vite 上，
  用一个本地反向代理在服务端把 Tauri IPC shim 注入页面，**secret 由代理服务端注入，不进 URL**
  （进 URL 会被权限分类器拦，且是隐私不良实践）。
- 身份门绕不开 Rust 签名，但可以**按产品自己的 bootstrap 协议自持 Ed25519 密钥拉起后端**，
  然后走 `companion_control_challenge` → `companion_profile_bind` 完成进程级身份绑定。
  协议实现见 `backend/deskpet/companion/control_credentials.py`，challenge 的字段是驼峰
  （`connectionId`/`controlEpoch`/`requestSeq`/`bindingEpoch`），别用蛇形。
- S5a 期间的脚本仍在
  `/private/tmp/claude-501/-Users-taiwan-PROJECTS-SimplaHarness/d3cb7731-.../scratchpad/`
  （`identity_harness.py`、`shim_proxy.py`、`tauri_shim.js`），临时目录可能已清，按上述描述重建即可。
- 有一个开发版包装 app 装在 `/Applications/SimpleHarness.app`，指向 debug 二进制，可直接删。

### 6.4 本机 7 条环境红（不是回归，别去修）

```
tests/capabilities/test_registry_publisher.py::test_atomic_publisher_install_update_rollback_and_uninstall
tests/capabilities/test_registry_publisher.py::test_shared_publish_lock_never_exposes_mixed_snapshot
tests/companion/test_capability_owner_scope.py::test_workflow_fresh_schema_installs_capability_v2_idempotently
tests/product_state/test_host_control_downgrade.py::test_exact_pinned_sdk_062_reopens_twice_and_rejects_recoverable_runs
tests/test_agent_storage_reset.py::test_dev_reset_rebuilds_three_databases_and_removes_sidecars
tests/test_error_handling_fixes.py::test_health_check_timeout_values
tests/test_process_list_error.py::test_process_list_with_query
```

S4 期即在案，主干 + memory-0.5.2 上可复现。判据是"不低于基线"，
证据文件 `.../verification/r3-s5a/evidence/reg-baseline-exclusions.md`。
**回归 lane 不要写 `; exit 0` 掩码退出码**，正确写法是脚本自判"恰好 7 条且零意外"
（见 r3-s5a 的 `reg-final-host` lane 命令）。

---

## 7. 机器验收门的坑（plan-test gate）

S5b 同样是 FULL 档 + MACHINE_GATE，会再走一遍 gate。以下是 S5a 交的学费：

1. **`impact_paths` 必须写仓库相对路径。** 写成绝对 glob 永不匹配，每次 re-attest 都退化成全量复测。
2. **任何非文档改动都触发全量重测。** `ARCHITECTURE/` 目录下的 md **不在** doc-only 白名单里
   （只有根目录的 `ARCHITECTURE.md` 在）。所以文档回写也会触发全量。**把文档回写放到最后一次全量之前做完。**
3. **场景一旦有过失败的 root run，就永远 FLAKY，该轮无法推进到 SHIPPABLE。** 豁免只能把 diag 降级为
   advisory，改不了场景状态。S5a 因此不得不开新 run 承接（旧 run 用 `retire --superseded-by` 交代，
   账本完整保留不删）。
   **教训：record-run 之前先手工跑一遍命令确认能过，别让自己的命令错误污染稳定性判定。**
   S5a 的 6 条 root fail 里有 5 条是执行者的 cwd/路径/marker 错误。
4. **`positive-value` 类场景的 root run 必须带 `--business-terminal`**，否则算 PARTIAL 不算 PASS。
5. **声明会创建 Run 的场景要带 `--run-id-under-test`**；声明不创建 Run 的要 `--negative-assertion`。
6. **timing 要覆盖 80% 以上活动跨度**，等用户的时段用 `--activity-class user_wait --wait-reason user_input` 申报。
7. `record-run --exec` 的正确写法（保住真实退出码）：
   ```bash
   --exec -- bash -c "cmd 2>&1 | tail -2; exit ${PIPESTATUS[0]}"
   ```

---

## 8. 未了结的账（不许静默关闭）

| 事项 | 性质 | 去处 |
|---|---|---|
| S1 真实无召回车道补非空回答断言 + transcript dump | 审计 deferral，**唯一悬空义务** | S5b |
| 记忆库补正式的属主注册 API | 上游义务，做了可删宿主兜底 | S5b |
| SDK 把 assistant 的 `tool_calls` 列为一等公共 transcript 字段 | 上游义务，做了可删宿主兜底 | S5b |
| `PROJECT_EFFECT` 根签发接线 | Task 5 直接前置 | S5b Task 5 |
| WeMM 快照上传 COS 模型桶 | 发布前置 | 发布任务 |
| changed-surface lint 小项（`context_route.py` SIM102、real-provider 测试 F811/F841） | 清理 | S5b |
| 240 条路由语料人工复审 | **必须真人** | 见 §5 |
| 三仓 push / tag / 发布 | 用户决策 | 待用户 |
| **前台任务链的「下一轮 typed recall 可读到」** | **结构性缺口**（见下方 §8.1） | **S5c/S6（用户 2026-09-04 决定移交，hash `ead12cfb…`）** |

### 8.1 typed recall 在前台任务链上不可达（S5b 未闭合，已移交）

acceptance 的最小验证动作以加粗的「**下一轮 typed recall 可读到**」收尾。S5b 终验实测**未能满足**，
且查明**不是运气问题、不是模型抖动**：

- 10 轮真实 provider 验证（`.local-test-evidence/real-ui-channel/`，其中 5 轮业务全链通过）：
  `human_memory_v7.db` 的 **`typed_recall_attempts` 每一轮都是 0 行**。
- 后端日志里 **`context_route` 出现 0 次**——模型从未调用过该工具。
- 两轮的路由决策都是 Host 自签的 **`origin=host_initial` / `route=resume_existing`**
  （`context_route_decisions` 表）。

**机制**：typed recall 只在 `context_route(memory_standalone)` 被选中时才执行
（`main.py::recall_executor=_human_memory_v7.typed_recall` → `sdk_adapters/context_route.py:302-315`）。
而前台任务链在首轮由 Host 自签路由回执（这正是 S5b Task 7 的 9 处修复之一：
`foreground_runtime_ports.py::verify_initial_route` 记 `origin=host_initial`），模型没有机会去选
`memory_standalone`。**试过的两种测法都无效**：同一 scope 发续轮（模型在上下文里就看得到上一轮，
没有召回动机）、新建 scope 提问过往工作（路由仍由 Host 自签）。

**已经成立的部分**（不受此影响）：analysis 产出被记忆库接受并物化为 `cognitive_memory_heads`
1 行 episode，内容逐句可回指用户原话、无臆造。缺的只是「下一轮读得到」这一环的可达路径。

**移交范围**：让前台任务链在有可用记忆时走召回路由（或由 Host 在上下文装配阶段直接注入 typed recall），
属**新增接线**而非缺陷修复。

**交付纪律**：S5b 的交付结论必须写明这一环未闭合，**不得**用「记忆已物化」暗示「下一轮读得到」，
也不得用其他场景的 PASS 稀释这一点。

### 两个宿主侧兜底分支的来龙去脉（S5b 若做掉上游义务，记得删）

真实 UI 验收抓到两个自动化测试测不出的缺陷，修复时都在宿主侧做了兜底：

- **`human_memory_v7.py` 的 fail-open**：全新安装时 v7 库没注册本地属主，读收件箱会 fail-closed，
  导致**首条对话必死**。兜底是：仅当"首页读且零累积"的未注册态返回空（该状态下收件箱受外键强制不可能有条目），
  按 reason code 收窄，其余冲突照旧抛出。上游补了属主注册 API 后删掉这段。
- **`provider.py` 的 `_wire_messages`**：SDK 0.7.1 冻结契约禁止 provider assistant 消息把私有 metadata
  写进 durable Context，导致续接请求丢了 `assistant.tool_calls`，被 OpenAI 兼容端点 400 拒绝，
  **每个用到工具的对话第二轮必挂**。兜底是从 durable 消息序列自身补齐 tool_calls，
  入参同进程保真、跨进程退化为空对象。上游把 tool_calls 列为一等公共字段后删掉这段。

---

## 9. 硬约束（program 级，继续生效）

- **永远不删除任何原始 session、memory、审计或测试证据。** 旧 gate run 只 retire 不删。
- **不访问、不请求、不迁移 `deskpet.receipt_hmac`。**
- **不调用 Keychain / `security` / `keyring`。**
- 原始数据库、截图、长日志、receipt 放 ignored 的 `.local-test-evidence/`，**不提交 Git**。
- 真实 provider 的 API key 只进进程与配置文件，**不落仓库文件、不打印、不进证据**。
- **不 push / tag / 发布**（merge 用户已于 2026-09-02 授权并完成）。
- 宿主仓 CLAUDE.md 的两条硬约束继续生效：任务通过测试必须同一交付更新 `ARCHITECTURE/`；
  测试阶段完成的能力必须**立即默认开启**，不做灰度。

---

## 10. 建议的开工顺序

1. `cd simple_harness && git checkout main`，确认工作树干净、全量跑通（7 红为基线）。
2. 用 plan-test skill 起 S5b 增量：先写 acceptance（矛盾分析 + AC + 场景矩阵 + DoD），
   再写 plan，挑战定稿后**交用户批准**才动手。
   参考同级目录 `increments/2026-09-01-s5a-context-route/{acceptance,plan}.md` 的体例。
3. Task 顺序建议 5 → 6 → 7。Task 5 最独立，Task 7 最重且依赖前两者的事件与凭证。
4. Task 5 开工前先补 `PROJECT_EFFECT` 根签发接线。
5. 每个 Task 完成后立刻回写 `ARCHITECTURE/`，别攒到最后（会触发额外的全量重测，见 §7.2）。
6. 真实 UI 验收不要留到最后：S5a 的两个 P0 都是零件全绿、整机不通，**只有真机真链路能暴露**。
7. 收官前提醒用户安排 240 条语料的人工复审（§5），否则 program 最终验收无法完成。
