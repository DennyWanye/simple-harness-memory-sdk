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
| T2-R P2 | 步骤 0 对 PREPARED 状态也跳 gate（窄窗口 fail-open）→ 仅 HANDED_OFF/UNKNOWN/终态跳 | `test_gate_still_runs_for_prepared_effect` |
| T2-R P2 | `pytest && rm -rf` 类复合命令被标 host.test → 只有单一 runner 命令且无 shell 连接符才算 test | `test_compound_shell_command_not_classified_as_test` |
| T2-R P2 | v46 单调守卫漏列（`provider_request_id`、outbox lineage 等）→ 逐列补 UPDATE 拦截 | `test_v46_guard_covers_every_mutable_column` |
| T2-R P2 | terminal 未走 `terminal:{run_id}` 预留路径 → 统一 | `test_run_terminal_reserved_then_ingested` |
| T2-R P2 | envelope 回退（gate 拒绝/异常）产生无人排空的预留 → 拒绝路径立即 abandoned | `test_rejected_effect_reservation_abandoned_immediately` |
| T2-R P2 | `read_reserved_fact` 生产实现零测试 | `test_read_reserved_fact_reads_sdk_ledger` |
| T3-R P2 | `not_sent` 在真实 SDK（`from None` 包装）下是死路径；测试用裸 httpx 异常 → 用真实 adapter 异常类型判定 | `test_invoker_not_sent_classification_with_real_adapter_error` |
| T3-R P2 | `reserved→handed_off` UPDATE 不查 rowcount → 可能账本外调用 Provider | `test_invoker_handoff_requires_rowcount_one` |
| T3-R P2 | 多字节 `idempotency_key` 逃逸成 `tool_handler_failed` 无 pre-admission audit | `test_task_scope_update_multibyte_key_rejected_with_audit` |
| T3-R P2 | invoker 吞 `CancelledError` | `test_invoker_propagates_cancelled_error` |
| T3-R P2 | `force_close_pending` 以 head 水位吞执行中 Run 的脏 → 以该 Run 观察到的水位为界 | `test_force_close_does_not_swallow_in_flight_run_dirty` |
| T3-R P2 | drain 对 `objective_evidence_hash_conflict` 无降级（Task 2 F-1 残余） | `test_drain_degrades_on_objective_evidence_hash_conflict` |
| T3-R P2 | 覆盖缺口：CANCELLED/STOPPED 终态门、真实 runtime 端到端、并发双 owner | 三条 |
