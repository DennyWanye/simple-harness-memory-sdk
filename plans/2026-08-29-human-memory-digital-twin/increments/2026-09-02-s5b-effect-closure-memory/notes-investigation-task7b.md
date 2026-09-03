# Task 7b 调查记录：真实桌面 UI（UI-B）暴露的两个产品缺陷

日期：2026-09-03。Host 起点 `af9fdc7a`（代码冻结点 `32d7849c`），修复后 HEAD `e46b1629`。
驱动方式：Browser pane 真实点击/输入 + 真实 provider `gpt-5.6-luna`，fresh isolated userdata。
用户 2026-09-03 原话「批准 S5b 真实 UI 场景由 AI 驾驶」（sha256 `7a84b793…`）已入 r2 账本。

## 一、S5B-UI-F1：不可激活的能力既不披露原因，拒绝也不透明

### 现象（两次独立复现：HEAD `9b0744dd` 与 `af9fdc7a`）
真实 UI 里对已绑定工作区的 TaskScope 说「继续任务：把 README 里的版本号改成 1.2.0」：
1. 模型 `tool_search(query="file read search edit README", toolset="file")`；
2. 命中列表被 `mcp:filesystem:*` 占满（它们描述很长，SDK 按 token 命中排序，压过内建文件工具）；
3. `tool_describe("mcp:filesystem:mcp_filesystem_search_files")` **成功**，返回 `activation_required=true`；
4. `tool_activate`（参数与 describe 返回逐字一致）**连续三次失败**，模型只看到
   `{"error_code":"tool_failed","public_message":"Tool execution failed."}`；
5. 模型原样重试 → `react_repeated_tool_exceeded` → **整个 Run 失败**，README 未改、
   `context_route_decisions` 零行。

### 根因（确定性复现测试已锁定）
- project-bound Run 把进程级 `mcp:filesystem` 判为 `workspace_unscoped`
  （其根是应用 userdata，不能重绑到 Session 的冻结 workspace，见 `PROJECT_BOUND_UNSCOPED_MCP_SOURCES`）。
- `SdkRuntimeCapabilityBridgeAdapter.activate` 因此抛 `RuntimeError("tool_unavailable:workspace_unscoped")`。
- 该异常被**两层**吞掉：`tools/tool_search.py::activate_handler` 变成 `{"error": str(exc)}`；
  `sdk_adapters/tools.py::_result` 把带 `error` 的载荷统一映射成 `tool_failed` +
  “Tool execution failed.”，且 Host **没有任何日志**（backend.log 只有 SDK 的 `tool_attempt.failed`）。
- 披露侧同样沉默：`tool_search` / `tool_describe` 对这类能力与普通 deferred 工具毫无区别。

pytest 真实车道（`test_s5b_milestone_real_provider.py`）之所以 PASS 而没抓到，是因为基座把
`write_file` 直接放进 ReActLoop 目录，**根本没走产品的 deferred 披露 / 激活路径**——正是 UI 验收要抓的差异。

### 修复（commit `951538bd`）
- `tool_search`：不可激活项标 `activatable=false` + `availability_reason` + `next_action`；
  Host 侧把可激活项稳定排前（SDK 排序保持组内不变），分页在重排后的列表上进行。
- `tool_describe`：返回 `activatable=false` / `activation_required=false` + “不要调用 tool_activate”。
- `tool_activate`：拒绝返回白名单稳定 `error_code`（`^[a-z][a-z0-9_]{0,63}$`）+ 可执行 `next_action`，
  记 `tool_activate.rejected` 结构化日志；不泄露路径/堆栈/私密内容。
- 产品 Tool handler 可用 `error_code`/`public_message` 让稳定码穿过 `_result`；失败调用统一记 `product_tool.failed`。

### 验证
- 决定性测试 `backend/tests/sdk_adapters/test_tool_activate_unavailable_disclosure.py`（生产投影 +
  真实 registry + 真实 handler 复现 UI-B 的 Run 形态）：**回退产品代码后 7/8 变红**
  （关键断言 `tool_failed != tool_unavailable`），修复后全绿。
- **真实 UI 复验通过**（证据 `20260903T0600-uiB-fix`）：同一提问下 `tool_describe` 返回
  `activatable: true`、`tool_activate` **成功**（`builtin:file_grep`，activation_id `61cd5032…`），
  搜索首屏全是可激活的内建文件工具，`mcp:filesystem:*` 已被排到首屏之外。

## 二、S5B-UI-F2：模型漏填必填参数会打掉整个 Run

### 现象（同一次真实 UI 重跑）
F1 修复后 Run 继续推进，第 5 个 provider turn 模型返回
`tool_calls=[{name:"tool_search", arguments:{}}]`（缺必填 `query`）。冻结 SDK 0.7.1 在
`simple_harness/tools/registry.py:128` 的 `ToolRegistry.validate()` 抛
`MalformedToolArgumentsError`，`simple_harness.runtime.kernel` 记 `sdk_run_driver_failed`，
`run_events` 落 `run.failed code=driver_failed`，UI 显示 `sdk_run_failed — run_failed`。
**发生在进入处理器之前**，模型没有任何自纠机会；Host 的 `_handle_tool_search` 本身对空 query 是防御性的，
但根本没被调用到。

### 首版修复（commit `e46b1629`）与**覆盖不足**
任何真实模型都会偶尔漏填参数。`tool_search` / `tool_describe` / `tool_activate` 在每个 Run 都直出、
被调用最频繁，命中概率最高，因此把「必填」从 schema 下沉到处理器：三者 `parameters` 不再声明
`required`，缺项返回稳定码 `missing_required_argument` + `missing_arguments` + 可执行 `next_action`，
并记 `tool_arguments.missing` 日志。**语义没有放宽**——缺项照样被拒绝，只是拒绝从「杀 Run」变成
「模型可见且可重试」。

未采取的更大改动及理由：
- **改 SDK**：本增量硬约束是 Harness SDK 0.7.1 冻结，不动。
- **覆盖 `ToolRegistry.validate`**：`validate` 必须返回 `Tool`，无法就地转成拒绝；强行吞掉异常会让
  错类型参数直达处理器，把一个明确失败换成一堆不可预期的处理器崩溃，风险更大。
- **给所有工具去掉 `required`**：面太大，其余处理器未必防御性，且会削弱模型可见契约。
**首版修复覆盖不足，被真实 UI 当场证伪**：下一轮 UI-B（证据 `20260903T0710-uiB`）同一模型改用
`context_route {}`（非三件套的产品工具）又打掉了一整个 Run。

### 扩面修复（commit `38ff5e9a`）
必填校验统一下沉到 Host 的产品工具包装层 `_sdk_tool`：把 `required` 从发布给 SDK 的 schema 里取出、
留在 Host 侧执行；调用进来先按同一张必填清单校验，缺项（含 `None` / 空串）直接返回稳定码
`missing_required_argument` + 指名缺失参数的 `public_message`，记 `tool_arguments.missing` 日志，
处理器根本不被调用。已提供字段的类型校验仍由 SDK 负责，语义未放宽。

动态 MCP 工具的 schema 由远端提供，Host 无法一并接管，故仍登记为**上游 SDK 义务**
（`MalformedToolArgumentsError` 应作为模型可见的 rejected ToolResult 返回，而非驱动级失败）+
known-debt，待 SDK 0.8。

### 验证
- 决定性测试：回退产品代码后 `test_missing_arguments_are_model_visible_not_run_fatal` 与
  `test_product_tool_missing_required_is_not_run_fatal` 均变红，修复后该文件 11/11 绿。
- **真实 UI 复验通过**（证据 `20260903T0730-uiB`，Host `38ff5e9a`）：同一次 Run 内出现
  **六次空参数调用**——`tool_describe {}`、`tool_activate {}` ×2、`tool_search {}` ×2、
  `context_route {}`——**全部**返回 `missing_required_argument` 且 `public_message` 指名缺失参数，
  **Run 每一次都存活**并继续推进到 20 次工具调用。修复前其中任意一发都会终结整个 Run。
- 受影响套件：`sdk_adapters` + `faults` + agent_loop/capability/context_os/workflow 共 **567 passed**；
  另有 memory 等套件在 F1 轮已跑 166 passed。`ruff` 在改动文件上无新增告警。
- `ARCHITECTURE/AGENT_HARNESS.md` 已在同一交付内同步两条契约。

## 三、同轮观察到但不归为本次修复的三件事

1. **执行者操作延迟（非产品缺陷）**：首个 Run 的 `context_route` 授权确认框在执行者排查数据库期间
   超时过期（`decision expires_at` 到点后 `decision.expired`），Run 随之失败。教训：真实 UI 驾驶时
   确认框必须立即处理。
2. **`context_route(route=continue_active)` 返回 `context_route_no_active_task_scope`**：种入的 TaskScope
   未挂到新会话，模型需先 `task_scope_search` 再 `resume_existing`。错误码稳定且模型确实自纠了
   （改走 tool_search 路线），属**预期产品行为**，不是缺陷。但 `public_message` 仍是通用的
   “Tool execution failed.”，可读性有提升空间——记入 S5c 候选。
3. **provider 传输超时把 Run 挂在 `provider_outcome_unknown`**：第三次 UI-B（HEAD `e46b1629`，证据
   `20260903T0700-uiB`）中上游 relay 60 秒超时，SDK 按 `sent_unknown` 契约**不重发**（避免重复副作用），
   Run 落 `run.waiting` + `run_wait_blockers(kind=provider)` 并长时间不恢复，用户侧既没有终答也没有报错。
   这是既有 **SDK 0.8 义务（not_sent / sent_unknown）** 在真实环境下的表现，非本次引入；环境触发
   （上游 relay 慢），不改冻结 SDK。建议 S5c 评估 Host 侧对该状态的用户可见提示与超时兜底。

## 四、UI 里程碑仍未在真实 UI 上跑通（如实记录）
README 至今未被真实 UI 改成 1.2.0。两个产品缺陷都已修并各自在真实 UI 上验证，但里程碑闭环被两件事挡住：

1. **工作区权威在 Run 准入时冻结**。种子任务域原先绑定 `<run>/workspace`，而 UI 会话的 Run 冻结的是
   会话自己的项目目录（`documents/SimpleHarnessProjects/Session-XXXX`），中途 `context_route` 只改上下文
   不改冻结根，因此 `file_grep("README.md")` 必然找不到文件。这是**种子设置问题，非产品缺陷**。
   已给 `seed_task_scope.py` 加 `--workspace`，把任务域改绑到会话自己的项目目录（README 也放到那里）。
2. **上游 provider 从本机时间 09:2x 起持续不稳定**：`ai.svtun.cn` 反复 60 秒 `transport_timeout`
   （四轮里至少 4 次），SDK 按 `sent_unknown` 不重发，Run 挂在 `provider_outcome_unknown` 不恢复。
   环境因素，非产品回归。

因此 S5B-S1 的**真实 UI 补充证据仍缺**；S1 的主闸是 pytest 真实车道（已 ×2 PASS），S8/S7 由 UI-A 冷启动
PASS 覆盖。建议 provider 恢复后按上面的 `--workspace` 设置重跑一次 UI-B（以及 ≥20 turn 的 UI-C）。

## 五、证据目录（均保留，`.local-test-evidence/real-ui-channel/`）
| 目录 | Host HEAD | 结果 |
|---|---|---|
| `20260903T030437-uiA` | `af9fdc7a` | **PASS**：冷启动 1-turn（S5B-S8 + S7 cold_start） |
| `20260903T030628-uiB` | `af9fdc7a` | S5B-UI-F1 复现（tool_activate 三连不透明失败 → 整 Run 死） |
| `20260903T0600-uiB-fix` | `951538bd` | F1 **已修复并复验**；同轮暴露 F2（`tool_search {}` → driver_failed） |
| `20260903T0700-uiB` | `e46b1629` | F2 首版修复后；被 provider 60s 超时挂起 |
| `20260903T0710-uiB` | `e46b1629` | 路由链全通；`context_route {}` 证伪首版修复覆盖面 → 扩面 |
| `20260903T0730-uiB` | `38ff5e9a` | F2 扩面修复**真实 UI 验证通过**（六次空参数全部可见拒绝、Run 存活）；里程碑被 provider 超时阻断 |
