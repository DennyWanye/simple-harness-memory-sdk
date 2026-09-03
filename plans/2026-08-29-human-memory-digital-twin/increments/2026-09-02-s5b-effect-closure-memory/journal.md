# S5b journal（phase-4 验收记录；机器账本 = Host 仓 `plans/.../increments/2026-09-02-s5b-effect-closure-memory/verification/r1-s5b`）

> 完成判定依据：机器门 `finalize` exit code 与 receipt（MACHINE_GATE 启用）；本 journal 为人读视图。

## 核心价值 smoke（主要矛盾最小验证动作）

**注意：phase-3 记的那次 smoke 走的是 pytest 里程碑车道，独立裁决（2026-09-03，裁决 D）判定它
不能作为 S5B-S1 的主证据**——该基座替换了 `ProductForegroundToolPort.freeze`、
`context_route → append_binding`、`ForegroundRuntimeExecutionAuthority` 等多处生产接缝
（`s5b_milestone_harness.py:83-89`、`s5b_effect_gate_harness.py:473-501`），S5B-UI-F1 正是由此漏检。

- **phase-3 旧记录（保留备查）**：`pytest tests/sdk_adapters/test_s5b_milestone_real_provider.py -m real_provider`
  1 passed / 51.5s；README 1.1.3→1.2.0；outbox delivered → job applied → cognitive head 物化。
- **phase-4 生效口径 = 生产入口车道**：`tools/production_entry_run.py` 对**真实运行后端**经控制
  WebSocket 走 `primary.open → task_scope.create → binding.append → queue.enqueue`
  （`memory/human_memory_api.py:207`，与将来 S6 界面按钮同一段代码），真实 provider
  `gpt-5.6-luna`，自然用户语言，AUTO 模式下 Agent 在既定 workspace 自建并绑定任务目录。
  证据 `prod-lane-05` / `prod-lane-08`：README `1.1.3→1.2.0` → 客观事件 39/41 行 →
  语义收口回执 1 行 `outcome=mutate` → 前台回合 `SETTLED` → `memory_ingestion_outbox` +
  `memory_ingestion_evidence_links` 各 1 行 → `cognitive_memory_heads` 1 行（episode）。

## 兑现表（逐条必须 AC）

| AC | 矛盾地位 | 含 UI | 测试方式 | 驾驶者 | 真机证据 | 状态 |
|----|----------|------|----------|--------|----------|------|
| S5B-AC-1 语义收口生产链 | 决定性 | 否（UI 面按 A14 移交 S6） | **生产入口车道**（控制 WS `queue.enqueue` → 真实后端 → 真实 provider）×2 独立 root | ai（用户 2026-09-03 批准全 AI 驾驶，hash `7a84b793…`） | `.local-test-evidence/real-ui-channel/prod-lane-05`、`prod-lane-08`：README 1.1.3→1.2.0、`task_scope_events` 39/41、`task_scope_closure_receipts` 1 行 `outcome=mutate`、前台回合 `SETTLED` | ✅ |
| S5B-AC-2 analysis 与 outbox | 决定性 | 否（同上） | 同上（终态同事务 outbox → analysis → 物化） | ai | 同上两目录：`memory_ingestion_outbox` 1 行 + `memory_ingestion_evidence_links` 1 行 → `cognitive_memory_heads` 1 行（episode）；日志 `memory_outbox.claimed` / `.applied` | ✅ |
| S5B-AC-3 effect gate | 次要 | 否 | 自动化 fault lane `taskscope-init-binding`（11 seam）+ effect gate 套件 | ai | r3 `artifacts/faults/s4-fault-runner.log`（11 行，含 run-fault 三稳定码、frozen-root-split、auto-destructive）；exec 日志 `exec-S5B-S4-EFFECT-GATE-*.log` | ✅ |
| S5B-AC-6 composition/cutover/遗留 | 次要 | 部分（冷启动真实桌面） | 自动化（v46 cutover + composition + no_recall gate）+ 冷启动真实 UI 1-turn | ai | r3 `artifacts/ui-a/`：fresh userdata `user_version` 0→46、`product_sdk_runtime_ready` 无 skipped、Browser pane 真实点击终答非空、`context_route_decisions` 1 行 `direct_standalone/no_recall` | ✅ |

**降级声明**：无。含 UI 的两条（S5B-S7 冷启动、S5B-S8 通道）均为真机 Browser pane 点击/输入证据；
S5B-AC-1/2 的真实桌面 UI 面按 acceptance **A14 范围缩减**（用户 2026-09-03 显式批准，hash
`6086418d…`）移交 S6，其实质要求未降级——改由**唯一现存生产入口**兑现，见上方核心价值 smoke。

## 冒烟脚本

| 用途 | 路径 | 说明 |
|---|---|---|
| **生产入口全链**（本增量核心价值 smoke） | `.local-test-evidence/real-ui-channel/tools/production_entry_run.py` | 对运行中的真实后端经控制 WS 走 `primary.open → task_scope.create → binding.append → queue.enqueue`，自动批准工具授权，跑到 Run 终态；输出 README diff 与 `production-entry.log`。**已纳入回归意义上的可复跑资产**（目录被 `.gitignore`，脚本随证据留存） |
| 真实 UI 通道 | `.local-test-evidence/real-ui-channel/tools/start_channel.sh` + `collect_evidence.sh` + `stop_channel.sh` | 纯浏览器 dev 通道 + 自持身份绑定；`shim_proxy.py` 新增 `--project-dir-file`（服务端注入原生文件夹选择器返回值）；`seed_task_scope.py` 新增 `--workspace` |
| 前台链断点回归 | `backend/tests/sdk_adapters/test_chat_session_project_effect_reachability.py` | 生产装配下断言「无前台 Run 时可 bootstrap 绑定」「越界根仍拒绝且不建目录」 |
| 工具拒绝可行动性 | `backend/tests/sdk_adapters/test_tool_activate_unavailable_disclosure.py`（17 条） | S5B-UI-F1/F2/F3 的决定性测试，含真实工具清单参数化断言 |

## 广度账本（输入敏感 / LLM 载荷）

**语义不等价输入类别**（`MANUAL_MIN_DISTINCT_CLASSES=3`，retry/改写不计数）：

| # | 类别 | 输入（自然语言） | 入口 | 业务终态 |
|---|---|---|---|---|
| 1 | 项目文件副作用 + 语义收口 + 记忆分析 | 「把项目里 README.md 的版本号从 1.1.3 改成 1.2.0，改完告诉我新版本号」 | 生产 `queue.enqueue` | ✅ 全链闭环（prod-lane-05） |
| 2 | 同一意图的**不等价改写**（措辞、动词、回报要求均不同） | 「请把项目 README.md 里的版本号更新到 1.2.0，完成后回报最终版本号」 | 生产 `queue.enqueue` | ✅ 全链闭环（prod-lane-08） |
| 3 | 无项目副作用的闲聊直达 | 「今天想去公园散步」 | 真实桌面 UI（Browser pane） | ✅ 终答非空；路由 `direct_standalone/no_recall`，**未触发任何项目 effect** |

**负例（`MANUAL_REQUIRE_NEGATIVE_CLASS`，不计入类别数）**：
- 跨任务域写入被 EffectGate 以 `effect_gate_frozen_scope_mismatch` **正确拒绝**，且模型终答
  **如实告知失败、未编造成功**（「README 的写入被项目保护机制连续拒绝了，文件没有被修改」），
  证据 `real-ui-channel/20260903T1000-uiB`。
- 委派工具不可用时给稳定码 `delegation_unavailable` + 替代路径，模型**一次即改道**，
  证据 `real-ui-channel/20260903T1300-uiB`。

**正向价值样本**（`MANUAL_MIN_POSITIVE_SAMPLES=1`）：类别 1、2 各 1 个，均为自然用户语言 +
真实生产入口 + 真实 provider + **非空有效业务结果**（文件真被改、记忆真被物化），人工核对达 quality_bar。

**≥20 turn 长上下文会话**：按 acceptance **A14** 随 S5B-S1 的 UI 载体面一并**移交 S6**
（S5a 是经真实桌面 UI 完成的，S5b 无此入口）。

**LLM 载荷变异**：`task_scope_update` 与 analysis result 的五类载荷变异由
`test_no_recall_gate.py` / `test_s5b_acceptance_matrix.py` 覆盖（S7 lane，fail-closed 无半状态）。

## 2026-09-04 终验补记：两个新缺陷与一次归因错误

重录场景时（闸门要求代码变更后复验）暴露出**决定性 AC 的通过取决于模型当次选了哪种路径写法**：

- **P0-12（真因）** `tools/file_tools.py::_resolve_within_workspace` 不展开 `~`。
  `Path("~/x")` 不是绝对路径 → 被拼成 `<root>/~/x` → 既通过 `relative_to(root)` 后代校验，
  又指向不存在的文件，模型只收到 "file not found" 而无从改正。本项目提示词习惯用
  `~/SimpleHarnessWorkSpace/...` 表述，这条路径几乎必踩。实测：同一条指令，模型给绝对路径时
  整轮通过、给 `~` 路径时 `file_read` 连挂 5 次、全程无副作用而 Run 仍 `SETTLED`。
- **P0-11** 四个 os_tool 路径归一化不一致：`read_file` / `list_directory` 相对路径按进程 cwd
  解析；`write_file` / `edit_file` 的 `~` 在越界校验**之后**才展开——后者是**越界通道**
  （`~/x` 被 `write_scope_check` 判成 scope 内，实际却写向 `$HOME/x`）。统一走
  `os_tools/_scope_paths.normalize_model_path`，次序钉死"先展开、后校验"。
  变异验证：调换次序 → `test_tilde_path_outside_scope_is_refused_not_smuggled` 立刻转红。

**一次归因错误（自我批评）**：我先改了 `os_tools/read_file.py`，但失败日志里的 `file_read`
走的是 `tools/file_tools.py`，两者是**不同处理器**。重跑后照样失败才发现。P0-11 的改动本身
仍然正确（含那条真实的越界次序修复），但它没有触及当次故障路径——已在 P0-12 提交信息里
写明归因错误，不掩盖。

**终态语义澄清（判读纪律）**：`foreground_turn_heads.current_state = SETTLED` 只表示回合终止，
**不表示成功**；业务结果由 `foreground_terminal_receipts.terminal_state`（`COMPLETED`/`FAILED`）
与 `task_scope_closure_receipts` 承载。本轮遇到上游 provider 502 与 60s transport timeout 各一次，
都得到 `SETTLED` + `terminal_state=FAILED` + 零收口回执——这是**正确行为**。lane 脚本已加终态判读，
把上游故障判为 `INCONCLUSIVE` 而非业务 FAIL，避免把外部不可用记成被测面的红。

**未能归因的现象（如实记录，不粉饰）**：在**通过**的 root run 中，`file_read` 仍失败 4 次
（稳定码 `tool_failed`）、`edit_file` 失败 4 次后第 5 次成功。工具参数不落库（隐私设计），
我**无法从持久证据归因**；最可能是模型去找 README 里提到的 CHANGELOG，但这是推测，未证实。
→ 列入遗留问题 8（可观测性义务）。

**闸门次序教训**：re-attest 必须在场景记录**之前**。我先记录后 attest，导致 re-attest 把
文档改动 fail-closed 成行为变更，7 场景全部作废重跑。`ARCHITECTURE/**` 不在默认 doc-only
白名单内，而自定义 glob **只能收窄不能放宽**（防止被测者自报豁免）——这是闸门的正确设计，
不是缺陷。

## 遗留问题清单（不许悬空）
1. F-5：MCP 写类工具未纳入 PROJECT_EFFECT 分类（仅经 unknown EffectClass → Auto confirm-only 间接收窄；project_bound Run 已排除 filesystem MCP）→ S5c/S6 前处理。
2. `_drive_claimed` 真实 runtime 端到端用例未补（Task 6 未完成项）。
3. `backend/uv.lock` 仍指 memory 0.5.2（pin 真相在 `sdk_candidate.py`）→ known-debt。
4. Task 4 审查 P2/P3 遗留：`lease_lost` 两事务窗口与 `revalidate` 生产永不触发；Host durable 响应无本地凭据过滤（Memory 两道边界兜住）；episode `occurred_at` 取分析时刻；`manager()` 注册失败泄漏；测试 `now` 常量；README oracle 偏弱。
5. Prospective/即时操作（AC-4/AC-5）→ S5c；Memory `sent_unknown` 确认通道、`not_sent` 判定依赖 httpx 消息 → SDK 0.8 义务。
6. 真实 UI 截图 PNG 无法落盘（screencapture 权限/Browser pane 不落盘）→ UI 证据以页面文本捕获 + 日志 + DB 行为形态（与 S5a 一致）。
7. HM-AC-8 质量门：240 条语料人工复审仍未安排（用户动作）→ `NOT_RUN/BLOCKED`。
8. **可观测性缺口**：`product_tool.failed tool=%s code=%s` 只记稳定码，丢弃拒因；工具参数不落库。
   本轮因此三次拖慢定位（每次都要靠探针复现机制）。通过的 root run 里 4 次 `file_read` 失败
   至今无法归因。→ 建议下一切补一条**不含路径的有界拒因分类**入日志。

## 终态行
（phase-final 填写）
