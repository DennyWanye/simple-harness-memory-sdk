# S5b Task 1 独立代码审查（effect gate 最小闭环）

- 审查对象：Host 仓 `simple_harness` `git diff aec5bacf..f8097429`（7 commit，19 文件，+2266/-28）
- 口径：`acceptance.md` S5B-AC-3、`design-freeze.md` §1/§4/§11、`assurance-contract.json` ASSET-WORKSPACE-AUTHORITY / FAIL-EFFECT-AUTHORITY-DRIFT
- 方式：只读；核对 diff + 调用链上下游（S4 `workspace_bindings.py` verify_*/exact_receipt/current_receipt、`foreground_runtime_ports.freeze`、SDK `react_loop.py` 120-200/500-540/660-700、`tools/executor.py` 228-520、`consumer_adapter.py`、`tool_authority.py` prepare_run/restore_run/resolve）
- 本地复跑：`backend/.venv/bin/python -m pytest tests/sdk_adapters/test_effect_gate.py tests/sdk_adapters/test_s5b_acceptance_matrix.py tests/execution/test_foreground_queue.py tests/sdk_adapters/test_context_route_authority.py tests/sdk_adapters/test_tool_authority.py tests/sdk_adapters/test_composition.py` → 100 passed, 11 xfailed
- 计数：P0 = 0，P1 = 1，P2 = 9

---

## 已核对、未发现问题的边界（用于说明覆盖面）

1. **绕过路径**：模型侧所有工具调用（direct kernel 与 deferred 一视同仁）只经 `react_loop.py:179 services.tools.execute` → `ProductEffectExecutor.execute`（`tools.py:357-393`）；`SDK_DIRECT_TOOL_KERNEL` 只影响披露，不影响 dispatch。`consumer_adapter.py:279`、`desktop_runtime.py:309`（`_sdk_desktop_test_enabled()` 恒 False，`main.py:7631-7635`）、`s4_value_adapter.py:580`（空 `ToolRegistry()`）均不是生产 PROJECT_EFFECT 路径。gate 在 `assert_workspace_current`、foreground `authorize` 与 SDK `prepare_effect` 之前返回 `EffectExecution(effect=None, rejected)`，首次执行时无 `execution_effects` 行、无 Host 事件，仅 `logger.warning`。
2. **legacy epoch / standalone**：无 route receipt 时 `ProductTaskExecutionAuthority._issue` 抛 `sdk_task_execution_route_authority_missing`（整 Run 故障，`task_execution.py:130-139`），SDK 侧 `react_loop.py:176-177` 亦兜底；不存在放行。
3. **receipt 绑定完整性**：gate 从 v45 `context_route_decisions` 按 (sdk_run_id, receipt_id) 读 durable receipt（`context_authority.py:539-563`），再由 S4 `verify_task_execution_envelope` 七元组比对（含 `route_receipt_hash`、`binding_set_receipt_id/hash`、`run_id`），随后 `verify_effect_authority` 校验 receipt_id/hash/root 成员并做 dev/ino/symlink 检查；`BindingRootResolver` 走 `exact_receipt`（id+hash+revision 三重校验，stale → `workspace_binding_exact_receipt_stale`），零/多 root 分支正确，且 `appended_root.root_identity_hash` 与唯一 hash 交叉核对。
4. **冻结 authority**：`freeze` 单 root → `workspace_resolution=None` → `prepare_run` 归一为 `kind=legacy, effective_root=canonical_path`；零/多 root → `projectless` 且 `prepare_run` 拒绝 projectless+root；`restore_run`（v3 记录）原样恢复 `workspace_resolution`，`resolve(run_id)` 在 restart/WAITING 恢复后可解析（与既有 `assert_workspace_current` 同一前提）。projectless Run 不可能被 `legacy` 语义误放行。
5. **RunFaultMemo**：按 run_id 键、`threading.Lock`、首码优先；`catalog_execution_policy_unavailable` 仅由 `execution_policy` 抛出路径记录，所有生产调用方（`react_loop.py:130/677`、`effect_gate.py:103`）均把异常上抛为整 Run 故障，`is_tool_exposed` 走 `provider_specs` 不触发记录 → 无串扰/污染。`run_terminal.public_payload.error_code` 只含 Host 常量或 SDK 公开 payload 的 `code`。
6. **测试先行**：`0641211d` 先落 oracle（导入尚不存在的 `deskpet.sdk_adapters.effect_gate` 等模块 → 全红），此后测试文件仅 3 处非语义改动（`git diff 0641211d..f8097429 -- backend/tests`），无照实现改断言迹象。四个验收用例断言为真实断言（文件内容、handler 调用序列、TOOL 消息、v45 行、memo、终态 payload）。

---

## Findings

### F-1 [P1] gate 抢在 SDK exact-replay / reconcile 之前，重放已 settle 或 UNKNOWN 的 effect 会被回报为 rejected

- 文件:行：`backend/deskpet/sdk_adapters/tools.py:362-383`（gate 在 `super().execute` 之前返回）；对照 SDK `tools/executor.py:263-310`（`existing = uow.read_effect(effect_id)` 的 terminal 直返 / HANDED_OFF|UNKNOWN reconcile 分支）与 `react_loop.py:511-533`（resume 时从 `tool_result_progress` 重放同一 call）。
- 问题：SDK 的 effect 幂等/恢复语义是"同 effect_id 已 terminal → 原 receipt 直返；HANDED_OFF/UNKNOWN → 先 reconcile"。gate 位于此之前且返回的是一个**终态形状**的 `rejected` 结果，而非抛错。于是重放时若 gate 条件已变化，SDK 的 replay/reconcile 分支被整体跳过。既有的 `assert_workspace_current` / `foreground_admission.authorize` 也在 `super().execute` 之前，但它们是**抛异常**（整 Run 故障，交由终态 reconcile），不会伪造一个 terminal 结果；本 diff 首次引入"前置返回终态结果"。
- 失败场景（具体）：
  1. Run 在 ROUTED_TASK 下 `write_file(a.txt)`，SDK `settle_effect` 落 `execution_effects=SUCCEEDED`、文件已写；进程在 checkpoint `tool_result_progress` 推进前崩溃。
  2. 崩溃—恢复窗口内用户对同 scope 做 Manual/Auto folder-append（head revision 2）。
  3. 恢复后 react loop 重放同一 call → gate 步骤 5 `workspace_binding_receipt_superseded` → 模型看到 `rejected`，checkpoint TOOL 消息记 rejected，而 ledger 行为 SUCCEEDED、磁盘已写。违反 program 契约 106-108"exact replay 只返回原 receipt"，且证据链（execution_effects vs TOOL 消息 vs Task 2 的 host.file 事件）自相矛盾；模型极可能按"被拒"再发一次写（新 effect_id）→ 再拒，形成不可自愈的错误反馈。
  4. 变体：effect 处于 HANDED_OFF/UNKNOWN（handler 中途崩溃），恢复后 gate 若拒绝，则 `reconcile` 永不执行，该 effect 永久 UNKNOWN，但模型收到 rejected。
- 建议修法：在 gate 之前用 `self._uow.read_effect(effect_id)`（或 SDK 暴露的等价读口）判断是否为**已存在的 effect record**；存在（任一状态）则直接进入 `super().execute` 由 SDK 走 replay/reconcile（S4/S5 的 admission 已在首次执行时做过且已 durable）；仅对首次出现的 effect 运行 gate。若担心"首次 PREPARED 后未 handoff"的窗口，可限定为 `existing is None or existing.state is PREPARED` 时才 gate。同时把这一点写进 `effect_gate.py` 模块 docstring 的 check order（"步骤 0：exact replay 不重验"）。
- 建议回归测试：`test_gate_skips_replay_of_settled_effect_and_returns_original_result`（settle 后追加 binding → 重放 → 返回 SUCCEEDED 原 result，且 handler 调用次数不变）；`test_gate_does_not_preempt_unknown_effect_reconciliation`（HANDED_OFF 记录 + gate 条件失效 → 进入 reconcile 而非 rejected）。

### F-2 [P2] 步骤 5 head 读取与物理写之间的 TOCTOU 窗口，且三个 store 各自开连接、不在同一快照

- 文件:行：`backend/deskpet/sdk_adapters/effect_gate.py:151-182`（`read_route_receipt` / `verify_task_execution_envelope` / `current_receipt` / `read_head_status` 四次独立连接）；`tools.py:393-397`（物理 dispatch 在其后）。
- 问题：strict "head == receipt.revision" 在 gate 通过后到 handler 落盘之间可被 Manual/Auto append 越过；scope status 同理（`read_head_status` 后 scope 被 close）。append-only 保证旧 root 不会被替换，故物理风险有限，但 envelope 记录的 revision 与实际 head 不一致，"Run 内任何追加后后续 effect 必拒"在并发下不严格成立。
- 失败场景：gate 通过（head=1）→ 同一毫秒 Auto append 提交 head=2 → `write_file` 落盘；证据 envelope.revision=1，head=2；验收 ⑥ 的"追加后 head≠receipt.revision → 后续项目 effect 拒绝"对这一笔不成立。
- 建议修法：至少把 `current_receipt` 与 `read_head_status` 合并进 `verify_task_execution_envelope` 同一 `_connection()`（同一 SQLite 读事务快照）；若要闭合窗口，需要 Task 2 的"同事务落 execution_effects + host.file 事件"时再次核对 head（写入事务内 `SELECT current_receipt_id` 校验，失败则 settle 为 failed）。在 ARCHITECTURE 明示此窗口。
- 建议回归测试：`test_gate_head_and_scope_status_read_in_single_snapshot`（注入 append 于 verify 与 head 读之间，断言拒绝）。

### F-3 [P2] 拒绝不 sticky（acceptance ④ 措辞 vs design-freeze §4 步骤 2 "Task 6"）

- 文件:行：`effect_gate.py:24-25, 92-183`（无 memo）；`acceptance.md:65` ④ "任一 stale/missing → rejected 且直到下一轮 context_route 刷新前持续拒绝"。
- 问题：当前每次 effect 独立重验。对 durable 单调条件（superseded、scope closed、frozen mismatch）等价于 sticky；但对可逆的文件系统条件不等价。
- 失败场景：root 被临时改名 → 第 1 次 `write_file` 拒 `workspace_root_unavailable`；用户改回 → 同一 route 下第 2 次 `write_file` 放行，未经新 route receipt。与 acceptance ④ 字面不符（design-freeze 把它排到 Task 6，属已知延期，非 Task 1 缺陷，但需在 Task 6 验收前有测试锁定）。
- 建议修法：Task 6 落 `effect_gate_rejections(run_id, route_receipt_id, reason)`，步骤 2 命中即拒；Task 1 阶段在 RUNLOG/PROJECT_STATUS 明确"暂不 sticky"。
- 建议回归测试：`test_gate_rejection_is_sticky_until_next_route_receipt`（先拒后恢复条件 → 同 receipt 仍拒；新 `context_route` → 放行）。

### F-4 [P2] 测试基座绕过了真实 SDK `EffectExecutor.execute`，"拒绝零 execution_effects 行"与"legacy 冻结语义"只在镜像上验证

- 文件:行：`backend/tests/sdk_adapters/s5b_effect_gate_harness.py:245-297`（`PhysicalToolBridge.execute` 覆写 SDK `execute`，`uow=object()`）；`:466-500`（`frozen_authority` 用 `SimpleNamespace` 手写 `kind=legacy`，未经 `SdkRunToolAuthorityRegistry.prepare_run` / `ProductForegroundToolPort.freeze`）。
- 问题：(a) `test_executor_rejection_returns_effect_none_without_dispatch` 与验收用例断言的是 handler 未调用 + 文件不存在，并未对真实 uow 断言"无 `execution_effects` 行、无 `tool.attempt` 事件"；(b) gate 依赖的 `legacy + effective_root` 语义（design-freeze §11 修订）没有一条测试穿过真实 `freeze → prepare_run → resolve` 链；若将来 `prepare_run` 归一规则变化（例如单 root 改回 `project_bound`），gate 不会被任何测试抓住。
- 失败场景：`ProductForegroundToolPort.freeze` 未来把单 root 改为 `workspace_resolution={"kind":"project_bound",...}`（需要 validator）→ 生产 `registry.resolve` 记录含 `project_id` 等字段，测试仍绿；反之若改为 `projectless`，所有写全部拒绝，测试仍绿。
- 建议修法：补一条端到端用例：真实 `WorkspaceBindingAuthorityStore` + 真实 `ProductForegroundToolPort.freeze` + 真实 `SdkRunToolAuthorityRegistry`，`authority_resolver=registry.resolve`；并用 SDK 真实 `SqliteUnitOfWork`（或 SDK testing 基座）断言拒绝后 `execution_effects` 无行、放行后有行。
- 建议回归测试：`test_freeze_single_root_registers_legacy_exact_root_and_gate_admits_via_registry_resolve`；`test_executor_rejection_leaves_no_execution_effects_row_with_real_uow`。

### F-5 [P2] MCP / 动态激活工具未纳入 PROJECT_EFFECT 分类，写入工作区的 MCP 工具不经 gate

- 文件:行：`backend/deskpet/sdk_adapters/tool_authority.py:66-93`（仅按 14 个内置名覆盖）；`:800-806`（`SDK_TOOL_EXECUTION_POLICY_OVERRIDES.get(name, ())`，MCP 工具落 SDK 默认 `non_project_effect/optional/optional`）。
- 问题：ASSET-WORKSPACE-AUTHORITY 的表述是"项目 effect 只能在 envelope 下执行"，而不是"14 个内置工具"。一个 `mcp:filesystem` 的 `write_file`/`create_directory`（名字不同于内置）在 ROUTED_STANDALONE 甚至 UNROUTED 下（若 `route_requirement=optional`）可直接物理写入 workspace 根，零 gate、零 envelope。
- 失败场景：用户挂载 filesystem MCP（root 指向项目目录）→ 模型在 standalone 路由下调用 `mcp__fs__write_file` → 落盘；`execution_effects` 行有但无 envelope；FAIL-EFFECT-AUTHORITY-DRIFT 成立。
- 建议修法：在 design-freeze §1 明确 MCP 工具口径（要么 program OOS 且 ARCHITECTURE 标注，要么保守规则：`source.startswith("mcp:")` 且 inventory `dispatch_kind`/permission_category 为写类 → `project_effect/required/required`）。
- 建议回归测试：`test_mcp_write_class_tool_is_project_effect_or_explicitly_documented_oos`。

### F-6 [P2] `RunFaultMemo` 只在 terminal observer 成功路径释放；observe 异常或非 foreground 终态路径会残留

- 文件:行：`backend/deskpet/execution/foreground_runtime.py:1286-1291`（`release` 在 `authorize_terminal` 之后）；`run_faults.py:32-45`。
- 问题：`observe` 在 `authorize_terminal`/ingest 之前抛错（evidence mismatch、DB 错误）→ 条目不释放；同 sdk_run_id 不会复用故无串扰，但进程内字典单调增长；且若同一 run 因 reclaim 在另一进程终态，则本进程条目永不清理（无害但违背"释放"承诺）。
- 失败场景：长驻进程 + 反复整 Run 故障 + observe 失败重试 → 字典泄漏；无正确性后果，属资源/可维护性。
- 建议修法：`try/finally` 释放，或在 `SdkRunToolAuthorityRegistry.mark_terminal` 处一并释放；给 memo 加上限/TTL。
- 建议回归测试：`test_run_fault_memo_released_even_when_terminal_observe_raises`。

### F-7 [P2] `current_receipt` 缺 head 行被映射为 `workspace_binding_receipt_superseded`，语义错位

- 文件:行：`effect_gate.py:168-171`。
- 问题：`TaskScopeNotFound("workspace_binding_set_not_found")` 表示该 scope 根本没有 binding head（数据不一致或 scope 无绑定），不是"被后续 revision 取代"。步骤 4 已通过时出现此情形说明 `task_workspace_binding_heads` 与 `_revisions` 不一致，应给出可区分的码以便排障。
- 失败场景：迁移/修复脚本误删 head 行 → 所有写以 "superseded" 报错，运维按"用户追加了目录"误判。
- 建议修法：映射为 `workspace_binding_effect_authority_missing`（S4 已有码）或新增 `effect_gate_binding_head_missing`（需先改 design-freeze §4）。
- 建议回归测试：`test_gate_missing_binding_head_reports_authority_missing_not_superseded`。

### F-8 [P2] 步骤 1 的 `effect_id` 回声是条件检查，Host 侧调用者传 `context.effect_id=None` 时身份绑定退化

- 文件:行：`effect_gate.py:117-123`（`context.effect_id is not None and ...`）。
- 问题：SDK react loop 总是传 effect_id，因此当前无实际漏洞；但 gate 的契约是"exact identity echo"，对 `None` 静默放宽意味着任何未来的 Host 内部 dispatch（workflow/subagent 桥）可用同一 envelope 复用于不同 effect_id。SDK `executor.py:249-250` 也只在非 None 时校验，故 Host 是最后一道。
- 失败场景：未来某调用方以 `ToolContext(call_id=X, effect_id=None, task_execution_envelope=E)` 重放另一 effect → gate 通过 → 同一 envelope 授权两次物理写。
- 建议修法：`context.effect_id is None` → `reject("effect_gate_envelope_identity_mismatch")`（或抛 `effect_gate_effect_identity_missing` 整 Run 故障，与 `call_identity_missing` 对齐）。
- 建议回归测试：`test_gate_requires_context_effect_id_for_project_effect`。

### F-9 [P2] 终态 `error_code` 直接复制 SDK payload 的 `code` 字段，无格式白名单

- 文件:行：`backend/deskpet/sdk_adapters/composition.py:635-644`；`foreground_runtime.py:1137-1144, 1256-1264`。
- 问题：`run_terminal.public_payload` 进入 `task_scope_events`（durable、对外可披露）。SDK 公开 payload 按设计不含私有材料，但 Host 侧没有任何长度/字符集约束；若 SDK 未来某 `code` 携带路径或异常文本（或 payload 被非 SDK 写入者篡改），会原样进证据。
- 失败场景：`payload["code"] = "driver_failed: /Users/x/secret.txt"` → 原样写入 `public_payload.error_code`。
- 建议修法：只接受 `^[a-z][a-z0-9_]{0,63}$` 的 token，否则退回 `driver_failed`；Host 三条稳定码与 SDK 公开码做枚举白名单更佳。
- 建议回归测试：`test_terminal_error_code_rejects_non_token_sdk_code_and_falls_back_to_driver_failed`。

### F-10 [P2] 覆盖缺口清单（Task 1 范围内可补）

- 文件:行：`backend/tests/sdk_adapters/test_effect_gate.py:142-170`（S4 码只覆盖 route missing / lineage / root mismatch / root unavailable）；`test_composition.py`（对 `main.py` 做源码字符串 grep，不是构建断言）。
- 缺口：
  1. `workspace_root_identity_drift`（dev/ino，删目录再同名重建）与 `workspace_root_not_canonical`（symlink）在 gate 层无用例（注释推到 Task 6，但 acceptance ④ 明确列 "文件系统身份（dev/ino）未漂移"）。
  2. `effect_gate_envelope_identity_mismatch` 的跨 Run（`envelope.run_id ≠ context.run_id`）分支无用例。
  3. `_visible_provider_specs`：`exposure` 无 `execution_policy` 的 pass-through 分支无用例；也没有"snapshot 隐藏但模型仍调用 → 整 Run 故障"的 UNROUTED（非 standalone）用例。
  4. `test_composition` 若 `main.py` 改名变量即失效，且不能证明 startup 真的 fail：应改为调用 `_build_product_sdk_runtime_stack` 的可注入片段或至少 import-time 构造 `EffectGate(...)` 缺参断言。
  5. `RunFaultMemo` 多 Run 隔离（run-A 记录不影响 run-B 读取）无用例。
- 建议回归测试：`test_gate_rejects_inode_drift_and_symlink_root`、`test_gate_rejects_cross_run_envelope`、`test_snapshot_passthrough_when_exposure_lacks_execution_policy`、`test_run_fault_memo_isolated_per_run`、`test_effect_gate_composition_missing_piece_fails_stack_build`。

---

## 其他观察（不计入 finding）

- `effect_gate.py:164` 根比较为字符串等值：foreground 冻结的 `workspace_root` 与 S4 `canonical_path` 同源，成立；`main.py:10197` 路径传入的 Session `workspace` 可能非 canonical，但该路径无 route receipt，先于步骤 3(cont.) 即整 Run 故障，方向 fail-closed。
- 子 Run（`agent`/`spawn_subagents`）若未在 registry 注册，gate 的 `exposure_resolver` 先于 effect class 判断即抛 `sdk_runtime_tool_exposure_unavailable`（整 Run 故障）——与既有 `assert_workspace_current` 前提一致，非本 diff 引入。
- design-freeze §11 已如实记录 `legacy` 语义修订与 memo 进程内退化（`driver_failed`），与实现一致。

---

VERDICT: FAIL
