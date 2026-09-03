# 幂等性审查（本增量「遍历 + 写副作用」代码，2026-09-03）

对照 `checklists/idempotency-review.md` 五问逐条核。命中场景 5 处，全部落在前台执行链。

## 1. `WorkspaceBindingRuntimeAuthority.append_binding` / `_append_auto` bootstrap
`task_scope/runtime_binding_authority.py:85-96,278-340`

| 五问 | 答 |
|---|---|
| 重复触发会重复副作用吗 | **不会**。实测同一 `idempotency_key` 第二次调用被 `workspace_binding_proposal_conflict` 拒绝 |
| 有已处理判断吗 | 有：`record_proposal` 以 proposal 唯一键去重（`workspace_bindings.py:202`） |
| 标记持久化了吗 | 是，写在 state.db 的 `task_workspace_binding_*` 表 |
| 失败的还能重试吗 | 能：失败路径不写 proposal 行；`_pre_admission` 登记在 `finally` 里清除，异常也清 |
| 有幂等测试吗 | 有：`test_chat_session_project_effect_reachability.py`；本次另做实测探针 |

**实测**：`binding_revisions=1`、`binding_heads=1`、`pre_admission_leaked=0`、目录只建一次。

## 2. `_ensure_task_directory`（Agent 建任务目录）
`runtime_binding_authority.py:129-160`

`mkdir(parents=True, exist_ok=True)` 天然幂等；已存在即 return。**只在既定 workspace root 的真实
后代位置创建**，越界不建（决定性测试 `test_bootstrap_binding_still_refuses_roots_outside_the_workspace`）。

## 3. `record_start_observation`（启动观察，6 处调用点）
`execution/foreground_runtime.py:757,792,863,874,894,942`

**本增量在此发现并修掉一个真缺陷（P0-10）**：幂等键 `runtime-start-query:<host_run_id>:found` 与
`runtime-restart-query:<host_run_id>:found` 不含 Run 版本，而驱动被 `after_control` 唤醒后会重入，
`ingress.query` 拿到的 `record.version` 已变 → 同键写不同 `result_hash` →
`foreground_execution_start_observation_idempotency_conflict` → 回合卡死。两处键现已含 `:v<version>`。
其余 4 处键（intent / raised / missing / returned）内容不随重入变化，无此问题。

## 4. `record_route_decision`（Host 首轮路由回执落账）
`execution/foreground_runtime_ports.py:193-201`

幂等键 `foreground-initial-route:<receipt_id>`，而 `receipt_id` 由
`_uuid(f"foreground-initial-route:{host_run_id}:{host_ref}:{host_hash}")` 确定性派生 →
同一 Run 重入产生同一把键与同一内容，账本按幂等键去重。`provider_turn_ordinal=1`（表约束 > 0）。

## 5. `after_control` 唤醒驱动
`execution/foreground_runtime.py:382-395` + `main.py::_signal_product_harness_decision`

`_driver_lock` 内判断 `self._driver is None or self._driver.done()`，重复唤醒不会起第二个驱动任务；
唤醒失败只记 warning，不影响本次决策落地（决策本身已由 SDK ingress 幂等承接）。

## 结论
5 处全部满足幂等要求；其中 1 处（启动观察）本增量修复了真实缺陷并配了决定性测试。
无遗留风险点。
