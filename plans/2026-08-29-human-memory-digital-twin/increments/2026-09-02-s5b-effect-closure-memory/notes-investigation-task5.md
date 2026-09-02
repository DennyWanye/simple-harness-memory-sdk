# 现状调查 — Task 5 effect gate（调查代理 2026-09-02，file:line 已核；Host main @ ec1cb944）

## issue_envelope 现状（backend/deskpet/sdk_adapters/task_execution.py，96 行）
- 构造只有一个可选依赖 `root_resolver: Callable[[receipt], Awaitable[(root_id, root_identity_hash)]] | None`（:37-41）。
- 非 project effect：TaskScope/root 字段全 None（:49-53）。
- PROJECT_EFFECT 分支（:56-73）：receipt 缺 task_scope_id/binding_set_revision/receipt_id/hash → `sdk_task_execution_route_authority_missing`；
  `root_resolver is None` → `sdk_task_execution_root_authority_unavailable`（:67-70）；否则 root 来自 resolver(receipt)，其余字段只从 receipt 复制。
- `idempotency_key = effect_id`（:88）。
- Envelope DTO：simple-harness-sdk `execution/effects.py:71-90`；六元组 TaskScope 字段全有或全无（:150-160）；binding_set_revision ≥1；`envelope_hash` = canonical JSON sha256（:261-263）。

## SDK 侧校验（react_loop.py）
- 端口按 **per call** 调用（`EffectBatchExecutor.execute` one() 闭包 :133-141；ReActLoop 逐 call 派发 :520-532）。
- 校验 :142-178：身份回声；route receipt id+hash 相等；PROJECT_EFFECT 需 receipt 存在 + `ROUTED_TASK` + 四项绑定等于 checkpoint receipt（:164-176）；无 authority + PROJECT_EFFECT 硬失败（:177-178）。
- SDK **不校验 root_id/root_identity_hash**（Host 职责）。
- envelope 进 `ToolContext.task_execution_envelope`（:179-195）；`tools/contracts.py:132-142` 拒跨 run/call/effect。
- replay 校验：`tools/executor.py:281` 比较冻结 envelope；持久化 executor.py:440 → uow.py:5263-5303。
- 同批 route+project effect：`_preflight_tool_batch` :684-694 → `ROUTE_BARRIER_NOT_OBSERVED`；模型 authority 字段剥离 `_HOST_ONLY_ARGUMENTS`（:647-657, :678-680）→ `MODEL_AUTHORITY_FIELD_FORBIDDEN`。

## Host 工具分类与物理执行器
- 唯一覆盖表 `tool_authority.py:60-64`：只有 `context_route` 为 context_control；**当前零 PROJECT_EFFECT 工具**（SDK 默认 NON_PROJECT_EFFECT/OPTIONAL/OPTIONAL，runtime_catalog.py:211-213）。写文件/shell 等全部默认 → SDK project-effect 门在生产是死代码。
- envelope 生产消费者仅两处：`context_route.py:122-131`（身份读取）；`workspace_bindings.py:1168-1204 verify_task_execution_envelope`——**零生产调用者**（只有 tests/task_scope/test_workspace_bindings.py:282,284）。
- 生产 pre-effect 卡点：`ProductEffectExecutor.execute` tools.py:344-357 → `assert_workspace_current(run_id)`（:348 → tool_authority.py:271-281，只看 workspace_resolution.kind + identity validator，**不看 envelope/revision/root identity**）+ `foreground_admission.authorize`（:352-355）。
- 冻结时根选择 `foreground_runtime_ports.py:305-341`：恰一 root → project_bound；零/多 root → projectless 并排除 project effect（"Never select one root implicitly"）。catalog 投影 tools.py:606-660。

## S4 binding store（backend/deskpet/task_scope/workspace_bindings.py，1429 行）
- canonical root + POSIX inode identity：`canonical_workspace_root()` :116-139；用时重验 `_open_verified_root()` :1357-1382（O_DIRECTORY|O_NOFOLLOW + fstat dev/ino → `workspace_root_identity_drift`）；广度守卫 `_verify_root()` :1338-1355（配置根本身/父目录 → `workspace_root_too_broad`；Auto 需配置根后代 → `workspace_root_not_configured_descendant`）。
- 默认根 `configured_root()` :169-179 → `~/SimpleHarnessWorkSpace`；配置根漂移 `_verify_configured_root_identity` :1080-1094。
- 表：task_workspace_binding_revisions/roots/heads/grants/proposals、task_workspace_run_mode_snapshots；`append_binding` :678-908 append-only + 根集 digest 链。
- 读：`current_receipt` :1205、`exact_receipt` :1219（stale → `workspace_binding_exact_receipt_stale`）、`verify_effect_authority` :1095-1135（root_identity_hash ∈ receipt 集合 + `_verify_root`）、`verify_route_binding` :1137、`verify_task_execution_envelope` :1168-1204（7 元组血缘 → `workspace_binding_envelope_lineage_mismatch`；root_id 相等 → `workspace_binding_envelope_root_mismatch`）。
- Manual/Auto：`issue_manual_challenge` :228 / `record_manual_decision` :324 / `verify_manual_authorization` :490；Auto `issue_run_binding_mode_snapshot` :535-620 / `authorize_auto_binding` :621-657；current-fact authority `CurrentRunBindingAuthority` :60-77 + `_verify_current_run_authority` :1041-1079（lifecycle active、mode AUTO；缺 port → `workspace_binding_current_run_authority_unavailable`）。runtime 包装 `task_scope/runtime_binding_authority.py:50-341`。
- store 构造：main.py:8063-8068（`_context_route_binding_store`）、foreground_runtime_ports.py:59,290、runtime_binding_authority.py:69。

## 既有审批/风险门与 Auto
- `permissions/effect_policy.py:22-32` `_CONFIRM_ONLY = {EXTERNAL_SEND, DESTRUCTIVE, PAYMENT, CREDENTIAL, PRIVACY, UNKNOWN}`；分类枚举 `tools/build_identity.py:26-36`。
- 执行边界强制：`harness/tool_executor.py:557-612`（confirm-only 快照对齐）、:894-911（explicit_only 无 grant_ref 拒绝）。交互闸 `permissions/gate.py:1-60`。
- Auto：`permissions/policy.py:21,66,115`、`types/task_grants.py:35,336-343`；Auto 豁免只作用于 plan confirmation（`agent/turn_preparer.py:989-1040`）；**tool_executor 完全不看 Auto**，`_CONFIRM_ONLY` 与 Auto 独立——"Auto 只免 folder append"目前是靠缺席成立，无显式断言。

## 既有测试
- `tests/sdk_adapters/test_context_route_authority.py:275-312`（envelope 回声 + PROJECT_EFFECT 双 fail-closed）；`tests/task_scope/test_workspace_bindings.py:261-306,998`；composition `tests/test_provider_runtime_refresh.py:386,443-446`；多处 `ProductTaskExecutionAuthority()` 无 resolver 构造（test_composition/test_s5a_*/test_no_recall_gate）；伪造 envelope 载荷 `test_s5a_acceptance_matrix.py:453-470`。
- **无测试覆盖**：物理 project effect 前 per-effect 重验、运行中 revision 漂移、运行中 root inode 漂移、Auto 豁免范围断言。`backend/tests/faults/` 不存在（fault-matrix `taskscope-init-binding` runner 缺）。
- HM-S9 = TC-HM-09 rev4（步骤 3–6 为本 Task 目标口径）；TC-PS-01/02/04/06/07 已 superseded → TC-HM-09。

## main.py
- `main.py:8567-8569` `register("sdk_task_execution_authority", ProductTaskExecutionAuthority())` **无参数**（root_resolver=None）；兄弟 authority 带真依赖（:8553-8566）；缺槽断言 :8570-8577；legacy pre-v35 跳过注册（:8522-8532）。
- 代理绑定 `_sdk_runtime_authority_bindings()` :7687-7695 / `_SdkTaskExecutionAuthorityProxy` :7679-7685。
- root_resolver 天然来源已存在未接线：`WorkspaceBindingAuthorityStore(_state_db_path)` main.py:8063-8068；`verify_effect_authority`/`verify_task_execution_envelope` 已返回带 root_id/root_identity_hash 的 `WorkspaceBindingEffectAuthority`。

## Gap 汇总
1. root_resolver=None（main.py:8567）。2. 零 PROJECT_EFFECT 工具分类。3. `verify_task_execution_envelope` 零生产调用、无 per-effect 重验钩子。4. effect 路径不查 TaskScope active/open。5. Auto 不到 effect gate，豁免边界无断言。6. fault lane runner 缺失。
