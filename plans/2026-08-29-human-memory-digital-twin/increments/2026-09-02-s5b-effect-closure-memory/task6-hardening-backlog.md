# Task 6 hardening 清单（来自 Task 1 代码审查 P2；实施前逐条对照）

| 来源 | 项 | 决定性测试 |
|---|---|---|
| F-2 | gate 的 route receipt / verify / current_receipt / head status 四次读合并到同一 SQLite 读快照；写事务内再核 head（失败 settle 为 failed） | `test_gate_head_and_scope_status_read_in_single_snapshot` |
| F-3 | sticky memo `effect_gate_rejections(run_id, route_receipt_id)`：命中即拒直到新 route receipt | `test_gate_rejection_sticky_until_new_route_receipt` |
| F-5 | MCP/动态激活的写类工具纳入 PROJECT_EFFECT 分类或在 projectless/route≠task 下不可激活 | `test_mcp_write_tool_cannot_bypass_gate` |
| F-6 | `RunFaultMemo` 在 observe 异常/非 foreground 终态路径也释放 | `test_run_fault_memo_released_on_observer_failure` |
| F-7 | `current_receipt` 缺 head 行 → `workspace_binding_route_authority_missing`（非 superseded） | `test_gate_missing_head_is_authority_missing_not_superseded` |
| F-8 | `effect_id` 回声改为必填（None → `effect_gate_envelope_identity_mismatch`） | `test_gate_requires_effect_id_echo` |
| F-9 | 终态 `error_code` 只接受稳定码白名单 `^[a-z][a-z0-9_]{2,63}$`，否则 `driver_failed` | `test_terminal_error_code_whitelist` |
| F-10 | inode 漂移（删目录同名重建）、symlink 根、跨 Run envelope、exposure 无 execution_policy 直通、UNROUTED hidden-tool 整 Run 故障、memo 多 Run 隔离、composition 真构造缺件 | 见审查报告 F-10 五条测试名 |
| A5/AC-3⑤ | Auto `explicit_only`：`_CONFIRM_ONLY` 类在 Auto 下 REQUIRE_USER；断言 a–d | `test_auto_mode_never_grants_confirm_only` 等 |
| Task 2 发现 | `migrator.py`：037 不在 `_S4_HUMAN_MIGRATIONS` 集合 → v45 无 marker/迁移链/恢复注册（fence 触发器缺失）；038 已补链，需回补 037 | `test_v45_migration_registered_in_human_chain` |
| S5a 遗留 | `backend/uv.lock` 仍指 memory 0.5.2（pin 真相在 sdk_candidate.py） | `uv lock` 刷新或记 known-debt |
