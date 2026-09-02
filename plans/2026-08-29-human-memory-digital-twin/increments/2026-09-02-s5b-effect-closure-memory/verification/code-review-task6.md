# S5b Task 6 独立代码审查（正确性优先，只读）

- 审查对象：Host 仓 `simple_harness` `git diff 7d0e5368..0de95582`（merge 前 11 commit，41 文件 +3808/-279）。
- 对照：`acceptance.md` S5B-AC-3④⑤⑥ / S5B-AC-6①②⑤、`design-freeze.md` §4/§5/§11、`task6-hardening-backlog.md`、四份既有审查的 P2、`verification/real-ui-channel-20260903T003610/summary.md`。
- 方法：逐 diff 阅读 + 对真实启动链（`lifespan` → `_activate_product_sdk_runtime` → `_build_product_sdk_runtime_stack` → `_activate_memory_analysis_lane`）静态追踪 + 一个只读探针（用 `tests/memory/test_s5b_v46_cutover.py` 的旧库构造器 + 生产入口 `dispatch_startup_epoch`，探针文件在 scratchpad，未进仓）。
- 计数：**P0 = 0，P1 = 1，P2 = 4，P3 = 5**。

## 已确认成立的部分（不计 finding）

1. **P0 修复（真实启动顺序）为真修**。`backend/main.py:8706` 在 builder 内先 `service_context.register("sdk_provider_binding_resolver", …)`，`:8788` 才调 `_activate_memory_analysis_lane()`，其 `:8906` 改经 `_resolve_sdk_provider_binding_resolver()` 读槽（槽优先、模块全局兜底）。`_analysis_adapter`（`:8213`）同样改走该解析器（调用时解析，不再捕获构建期的 None）。`_activate_product_sdk_runtime` `:10820-10824` 对构建异常 `logger.exception` 后 `raise RuntimeError("product_sdk_runtime_build_failed: …") from exc`；`lifespan` `:5606` 直接 `await`，外层无 try/except，异常传到 FastAPI lifespan → 进程启动失败。"全局兜底"只是次序备选（槽 None 且全局非 None 才用），不是 Noop/静默降级；真实启动下槽恒先注册，兜底不会被走到。
2. **Auto `explicit_only` 接线**：SDK 授权路径唯一入口是 `SdkPreparedAuthorizationPolicy.decide` → `PreparedAuthorizationRuntime.plan_prepared_call`（`tool_authority.py:1733/1748`，仓内无其他 `plan_prepared_call` 调用者；`main.py:1979` 的 `service.decide` 是 companion 决策服务，与 Tool 授权无关）。`permissions/runtime.py:441-467`：`explicit_only` 时 `covers` 恒 False（既有 grant 不覆盖），`explicit_only and not confirmed` → `action="wait"`；`decide` 对 `plan.action != "allow" and (mode == "manual" or explicit_only)` 走 REQUIRE_USER 分支并以 `confirmed=True, explicit_only=True` 计算候选 grant，`source` 在 `explicit_only` 下恒 `"user"`（`runtime.py:469-474`）。因此 `_CONFIRM_ONLY` 类在 Auto 下不可能出现 `policy:auto` grant。`frozen_tool_effect` 的 `unknown` 回落使 `run_shell/process_start/move_file/file_organize/ppt_create` 与所有未分类工具（含 MCP）落 confirm-only，与 §11 一致。legacy 路径未改（`permissions/runtime.py` 无 diff，`explicit_only` 默认 False → 既有行为 preserve-approved）。测试 `test_auto_mode_never_grants_confirm_only` 用真实 `PreparedAuthorizationRuntime` + spy 断言 `explicit_only` 实参、`grant_source=="user"`、`facts.grant.source`，决定性成立。
3. **单快照 + 写锁再核 + sticky memo**：`_snapshot_verdict` 在 `BEGIN`（deferred）内依次读 memo / route receipt / binding revision+root / head / scope status，`context_authority.read_route_receipt`、`workspace_bindings.verify_*`/`current_receipt`、`store.read_head_status` 全部真的接收并使用 `db=` 参数（非各开连接）；`reservation_check` 钩子在 `evidence_ingress.reserve` 的 `BEGIN IMMEDIATE` 内、INSERT 后、COMMIT 前执行，抛 `EffectGateRejected` → rollback → 零预留零 dispatch → `memoize_rejection`。memo 表 append-only + UNIQUE(sdk_run_id, route_receipt_id)、`INSERT OR IGNORE` 首码保留；新 receipt 即新键，无需清空。并发推演：两 effect 同 Run 同 receipt 并发拒绝 → 一条 memo；append 与 verify 并发 → 快照裁决放行但写锁再核拒绝（`test_gate_head_and_scope_status_read_in_single_snapshot` 以真实线程/连接注入验证）；预留 COMMIT → 物理写窗口内的 append 不能替换旧 root（append-only），与 design-freeze §4 声明一致。
4. **步骤 0 只跳非 PREPARED**：`_is_first_occurrence` 用 SDK `EffectState.PREPARED` 判定；`test_gate_still_runs_for_prepared_effect` 用真实 SDK executor 制造 crash-before-handoff，重放再过门、账本仍 prepared，决定性。
5. **拒绝预留立即 tombstone**：SDK `EffectExecutor.execute` 只在 immediate DENY / durable denied 时返回 `effect=None`（REQUIRE_USER 是 `raise ToolAuthorizationPending`，预留保持 `reserved`，用户确认后重放走 PREPARED 再过门、`reserve_tx` 幂等返回同一 reserved 行），故 `_abandon_rejected_reservation` 不会误吞待确认效果。`rejected` tombstone 非 material、`rejected_fact`/`abandoned` material（`semantic_closure.is_material_event`）。
6. **Task 4 F-1**：Provider 响应后 `settle_succeeded_tx` 单事务先落 `succeeded` + `result_envelope_json={"response":…,"envelope":null}`，再派生；派生失败 → `analysis_derivation_failed:*`（可重试），重试时 invoker 复用 → `_durable_response` → `_derive_and_attach`，`provider_calls=0`；envelope 附着 UPDATE 带 `$.envelope IS NULL` 守卫，v46 触发器只允许 response→response+envelope 升级一次且 `$.response` 不变。`quote_too_long` 为 `AnalysisProposalRejected`（确定性拒绝单条 op）。`test_derivation_failure_after_provider_response_does_not_strand_attempt` 断言 `adapter.calls==1`。
7. **≥2 root 隐藏**：`ProductRunContextAuthority._hide_project_effects` 以 receipt 的 exact 四元组读 `exact_receipt`（不看 live head），`root_identity_hashes>=2` 时对 ROUTED_TASK 轮同样收缩 `provider_specs`；生产 `_build_run_context_authority` 已注入 `binding_store`。
8. backlog 逐条：F-2/F-3/F-6/F-7/F-8/F-9/F-10、T2-R 六条、T3-R 七条（含三条覆盖缺口中的 CANCELLED/STOPPED 与并发双连接 reserve）均有对应实现 + 命名一致的测试，且多数用真实 SDK executor / 真实 sqlite（非 mock 过深）。`uv.lock` 记 known-debt（PROJECT_STATUS）。

## Findings

### F-1 [P1] 037 回补对**真实启动入口**无效：S5a 旧库（v45）与 Task 6 之前建的 v46 库在 `dispatch_startup_epoch` 阶段即被 `human_memory_marker_chain_invalid` 稳定拒绝，repair 永远跑不到

- 文件:行：`backend/deskpet/memory/schema.py:302-346`（`_validate_s4_migration_chain` 新增要求 037 链行 + `schema_migrations` 标记）、`:532`（`inspect_startup_epoch` 对 `version >= TASK_SCOPE_PROJECTIONS_SCHEMA_VERSION` 调用该校验）、`:718-735`（`dispatch_startup_epoch` 先 `inspect_startup_epoch`，非 FRESH/HUMAN_RESUME 直接 `raise`）、`:600-606`（repair 只挂在 `initialize_human_memory_program_state_db` 内，位于 inspect 之后）；`backend/main.py:3232`（lifespan 唯一入口是 `dispatch_startup_epoch`）。
- 问题：`initialize_human_memory_program_state_db` 前置了 `repair_context_route_registration`，但生产 lifespan 不直接调它，而是 `dispatch_startup_epoch` → `inspect_startup_epoch`，后者在任何写入前对 v≥42 的库做 `_validate_s4_migration_chain(expected_user_version=version)`；该校验现在把 037 列为必需步骤（45 ≤ version），而 S5a 在链外应用的 037 没有链行 → 抛 `HumanMemoryProgramEpochError` → `INVALID/human_memory_marker_chain_invalid` → dispatch `raise`。同理适用于 Task 2–Task 6 之间建的 v46 库（有 038 链行、无 037 链行）。
- 失败场景（探针实证，只读）：用 `tests/memory/test_s5b_v46_cutover.py::_legacy_v45_database` 构造 S5a 口径旧库 → `inspect_startup_epoch(db, approved_fresh_lane=False)` 返回 `INVALID human_memory_marker_chain_invalid`；`await dispatch_startup_epoch(db, approved_fresh_lane=False)` 抛 `HumanMemoryProgramEpochError: human_memory_marker_chain_invalid`。即：已有用户从 S5a 升级到本 merge 后，后端**无法启动**（且不是 cutover 前置的可操作提示，是"marker chain invalid"）。真实 UI 预演用 isolated fresh userdata，不会暴露此问题。
- 为何测试没抓到：`test_v45_migration_registered_in_human_chain` ③ 先调 `initialize_human_memory_program_state_db(legacy2)`（走了 repair）再 `inspect_startup_epoch`，顺序与生产相反；而 `_legacy_v45_database` 构造期还 monkeypatch 了 `_validate_s4_migration_chain` 为 no-op。
- 修法（二选一，倾向 a）：a) `inspect_startup_epoch` 对 `human_memory_migration_chain` 中"仅缺 037 且 `schema_migrations` 已含 037 且 `context_route_marker` 表存在"的库判定为 `HUMAN_RESUME`（带 reason `context_route_registration_pending`），由 `initialize_…` 的 repair 完成回补后再严格校验；b) 在 `dispatch_startup_epoch` 的 `inspect` 之前调用 `repair_context_route_registration`（它自身带 `PRAGMA user_version >= 45` 与幂等守卫，只读库不写）。任一修法都要保留"回补之后再次 inspect 必须 HUMAN_RESUME"。
- 决定性回归测试：`test_dispatch_startup_epoch_repairs_s5a_v45_database_before_chain_validation`（构造 S5a 旧库 → `dispatch_startup_epoch` 不抛、`user_version==46`、`_assert_context_route_registered`；再对"v46 且无 037 链行"的库重复同一断言）。

### F-2 [P2] `test_product_sdk_runtime_stack_builds_on_real_startup_order` 未走真实启动路径，P0 的核心不变量（builder 内"注册槽先于 lane 激活"）无测试守护

- 文件:行：`backend/tests/sdk_adapters/test_composition.py:955-1030`。
- 问题：测试 ① 手工把 resolver 注册进 `service_context` 后直接调 `_activate_memory_analysis_lane()`；③ 把 `_build_product_sdk_runtime_stack` monkeypatch 成直接 raise 的桩再调 `_activate_product_sdk_runtime`。两段都没有执行真实的 `_build_product_sdk_runtime_stack`，因此"`:8706` 注册在 `:8788` 之前"这一顺序只由源码阅读保证；把 `_activate_memory_analysis_lane()` 挪到 `service_context.register("sdk_provider_binding_resolver", …)` 之前不会让任何测试变红。PROJECT_STATUS known-debt 已如实写"未跑完整 lifespan"，但用例名与 RUNLOG 措辞（"按真实启动顺序的构造测试"）超出其实际覆盖。
- 失败场景：后续重构 builder（例如把 Task 4 lane 激活前移）重新引入同一 P0，CI 仍绿；且仓内**尚无修复后的真实启动证据**（`verification/` 下只有 `real-ui-channel-20260903T003610` 失败现场，Task 7 复跑未落盘）。
- 修法：在 `_build_product_sdk_runtime_stack` 内以 `_fault_inject`/记录钩子或对 `service_context.register` 的顺序断言（记录 `("sdk_provider_binding_resolver", …)` 出现在 `_activate_memory_analysis_lane` 被调之前），或以最小真实依赖（tmp state.db + 假 provider registry）跑完整 builder；并把 Task 7 复跑的 `product_sdk_runtime_ready` 日志作为 AC-6① 证据入 `verification/`。
- 决定性回归测试：`test_builder_registers_provider_binding_resolver_before_memory_lane_activation`。

### F-3 [P2] cutover 前置"无 WAITING SDK Run"只覆盖 foreground 绑定且有 reconciliation 行的 Run；判定在 `BEGIN IMMEDIATE` 之外

- 文件:行：`backend/deskpet/memory/migrator.py:213-270`（`_assert_effect_closure_cutover_preconditions`）、`:837-839`（在 `BEGIN IMMEDIATE` 前调用）。
- 问题：WAITING 判定依赖 `foreground_execution_reconciliations.observed_state='BOUND_WAITING'` 最新行；无 reconciliation 行的 WAITING Run 只被第二个"非终态 foreground head"判定兜住（可接受），但**非 foreground 的 SDK Run**（skill install verification Run、`_sdk_retained_presentations` 恢复 Run）不在这两张表里，SDK 侧 `lease_state="waiting"` 只在进程内 `SdkRunBindingRegistry._bindings`（`run_bindings.py:149-155`），无 durable 表可查，前置对其不可判定。另外前置在写事务外读，虽有 `_human_memory_program_lock`，但与"库字节不变"的断言是同一进程内成立，跨进程并发启动仍靠文件锁。
- 失败场景：一个非 foreground SDK Run 处于 WAITING（durable decision OPEN）时升级到 v46 → 迁移通过 → 恢复后该 Run 的 authorization replay 跨越 schema 变更（与 §5 前置意图不符）。概率低（此类 Run 生命周期短），但前置口径写成"无 WAITING SDK Run"是过度声明。
- 修法：在前置里追加对 SDK durable ledger（`execution_decisions` OPEN 状态，SDK sqlite 库）或 Host `foreground_run_sdk_bindings` 之外的 Run 记录的检查；或把 acceptance/ARCHITECTURE 口径收窄为"无非终态 foreground Run（含其 WAITING 观察）"。
- 决定性回归测试：`test_v46_cutover_blocked_by_open_sdk_authorization_decision_without_foreground_binding`（或口径收窄后的文档断言）。

### F-4 [P2] F-5（MCP 写类工具纳入 gate）未做的风险评估：Manual 模式下用户确认的 MCP 写入不留客观事件、不脏、不进收口

- 文件:行：`backend/deskpet/sdk_adapters/tool_authority.py:283-305`（`frozen_tool_effect` unknown 回落）、`backend/deskpet/sdk_adapters/tools.py:85`（`PROJECT_BOUND_UNSCOPED_MCP_SOURCES = {"mcp:filesystem"}`，只排除该一个 source）、`effect_gate.py:_is_project_effect`（仅 `ToolEffectClass.PROJECT_EFFECT`）。
- 问题：Task 6 的"间接收窄"只在 **Auto** 下把 MCP 工具变成 confirm-only；Manual 模式本来就要确认，所以对 Manual 无任何新增约束。用户确认后的 MCP 写入（任何非 `mcp:filesystem` 的 source，例如自定义 MCP 暴露的 `write_note`/`git_commit`）不经 EffectGate（无 envelope/root membership/inode 校验）、不产 `host.file` 客观事件、不进 `dirty_state`、closure 不知情；对 S5b 主链"真实发生的事确定性沉淀"是一处盲区。
- 失败场景：project_bound Run 内模型调用第三方 MCP 写工具修改根内文件（用户 Manual 确认）→ Run 终态 closure `no_mutation` 合法通过 → 记忆与档案均无此变更。
- 修法（S5c 前）：a) 短期：`PROJECT_BOUND_UNSCOPED_MCP_SOURCES` 改为 allowlist 语义——project_bound Run 下所有 `mcp:*` 写类（inventory `effect_class ∉ {read_only}`）不可激活，或在 `ProductEffectExecutor._commit_evidence` 中对 `source.startswith("mcp:")` 且非 read_only 的 effect 记 `harness.tool_invocation` material 事件（保守脏）；b) 记入 acceptance 的 OOS 并写 `behavior_changes`。
- 决定性回归测试：`test_mcp_write_tool_cannot_bypass_gate`（backlog 原名，仍未落地）。

### F-5 [P2] §4 检查顺序偏离：步骤 3（冻结 authority）实际先于步骤 2（sticky memo）执行

- 文件:行：`backend/deskpet/sdk_adapters/effect_gate.py:281-296`（步骤 3 无 DB 读、先返回）、`:299-315`（步骤 2 在 `_snapshot_verdict` 内）。
- 问题：design-freeze §4 与模块 docstring 都写 1→2→3；实装为 1→3→2/4/5/6。同 receipt 已 sticky 的 Run，若再次触发 frozen mismatch，回报的是 `effect_gate_frozen_scope_mismatch` 而非 `effect_gate_route_receipt_rejected`；memo `INSERT OR IGNORE` 保首码所以 durable 不受影响，仅模型可见码与 oracle 口径不一致。
- 失败场景：verification-spec 若按 §4 顺序断言"sticky 后任何项目 effect 码恒为 route_receipt_rejected"会与实装不一致。
- 修法：把 `_sticky_tx` 提前到步骤 3 之前（单独一个短读；或把步骤 3 也挪进快照之后，因其不读 DB 成本为零），或修订 §4/§11 记录实际顺序。
- 决定性回归测试：`test_sticky_memo_precedes_frozen_authority_checks`。

### F-6 [P3] `_activate_product_sdk_runtime` 仍保留一条静默 skip：`provider_registry` 缺失 → `product_sdk_runtime_skipped` return

- `backend/main.py:10812-10814`。AC-6① 说"逐项移除任一 → startup stable fail"；该分支是 composition 之前的前置，非 Task 6 引入，但它与被删掉的 `build_failed` skip 是同一类"整机无 SDK runtime 但进程健康"的静默态。建议改 raise 或至少在 `/health` 反映 `sdk_runtime=unavailable`。测试名：`test_missing_provider_registry_is_startup_fail`。

### F-7 [P3] `_resolve_sdk_provider_binding_resolver` 的模块全局兜底在 runtime 重建（generation 变更）时可能返回上一代 resolver

- `backend/main.py:8852-8861`。若某处 `service_context.register("sdk_provider_binding_resolver", None)`（测试 teardown / 未来的重建路径）而全局仍持旧对象，lane 会绑到旧代 resolver。当前生产无此路径；建议兜底只在 `_sdk_runtime_stack is None` 时允许，或直接删兜底（槽是唯一真相）。

### F-8 [P3] rollback drill 的"回滚"是备份替换，未验证 v46 库本身的降级不可能性以外的路径

- `tests/memory/test_s5b_v46_cutover.py::test_v46_forward_migration_and_rollback_drill_keep_evidence`：drill = 迁移前 `shutil.copy2` 备份 → 旧 runtime 打开 v46 字节不变 → 备份再前向。evidence 守恒断言充分（表 hash），但 acceptance ②"rollback drill 不删 evidence"若指对 v46 库执行某个 rollback 过程，则仓内不存在这样的过程；建议在 ARCHITECTURE 明写"rollback = 恢复迁移前备份，无 in-place 降级"。

### F-9 [P3] 小项

- `foreground_runtime._terminal_binding` 现在吞所有 `Exception`（`:439-447`）并 dead_letter；异常类型只进 audit `error_code`，`last_error` 只有 `run_binding_unavailable`——排障时看不到根因类型，建议把 `type(exc).__name__` 拼进 dead_letter reason（仍需满足 lineage hash 稳定）。
- `effect_gate._snapshot_verdict` 的 `BEGIN`（deferred）在 WAL 模式下是快照读，在 rollback-journal 模式下是 SHARED 锁——测试注释按 rollback-journal 写（"COMMIT waits for SHARED readers"），生产 `state.db` 若为 WAL 则 append 可以在快照期间提交、由写锁再核抓住，行为仍正确，只是注释口径需与生产 journal mode 一致。
- `_has_shell_operator` 对 `pytest -k "a or b"`（token 含空格引号）安全；但 `tokens` 来自 `_command_tokens`，若 arguments 以 list 形式给出 `["pytest","tests","&&","rm"]` 也被抓住。无问题，仅记录已核对。

## 覆盖缺口与回归风险汇总

- 真实启动：F-1（旧库启动被拒）+ F-2（无真实 builder 顺序守护、无修复后启动证据）。建议 Task 7 复跑除 fresh userdata 外，**追加一个由 S5a 旧 userdata 拷贝而来的启动预演**。
- MCP 写入盲区（F-4）在 Manual 下未收窄。
- cutover 前置对非 foreground SDK Run 不可判定（F-3）。
- 其余 backlog 项的测试多为真实 SDK executor / 真实 sqlite，决定性充分；未发现"照实现写断言"的用例。

VERDICT: FAIL
