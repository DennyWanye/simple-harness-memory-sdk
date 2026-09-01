# S4 Host Closure 基线（2026-09-01）

## 代码身份

- Host worktree：`/Users/denny/projects/simple_harness-memory-plan`
- branch：`feature/human-memory-plan`
- baseline HEAD：`70ff10eca3ef688ead526dc1ec54f395eeacca86`（包含独立提交的 receipt HMAC no-Keychain 修复）
- `origin/main`：`23f7e5dddf3ff66fe060a2b88a756eac15c6e48a`
- ancestry：baseline 比 `origin/main` ahead 23 / behind 0；已包含当前远端 main。

## 已实现事实

- v35：fresh primary conversation 与永久 Host evidence。
- v36：Canonical TaskScope Archive、mutation CAS、checkpoint/outbox、ExecutionEvidence ingress/watermark。
- v37：recoverable managed/explicit task-home provisioning。
- v38：append-only multi-root binding 与 Manual/Auto durable authority。
- S4 Task 1–4 的当前架构事实已写入 Host `ARCHITECTURE/`；普通生产 foreground 仍使用 legacy Session 路径。

## 缺口

- 不存在 `task_scope/projections.py`、`task_scope/search.py`、`execution/foreground_queue.py`、`execution/recovery_fence.py`。
- `backend/main.py` 尚未装配 fresh human-memory service/API，旧 Session CRUD 尚未对 primary authority 加 fence。
- v36 已预留 projection/search outbox/checkpoint 表，但没有六视图、FTS locator、Run/FIFO 或 recovery schema/worker。

## 实现调研结论

- 六阅读视图必须是 canonical state/events/checkpoints 的 deterministic projection；cache 与 FTS 都是可删除重建的派生物，不能成为恢复 authority。
- FTS5 external-content 索引由应用负责一致性，官方提供 `rebuild`；本项目使用显式 immutable search document + rebuildable FTS，permission filter 必须在 rank 前完成。
- WAL recovery 使用 SQLite 官方 `wal_checkpoint` 结果三元组作为 receipt；busy 不是成功，drain/park 后仍 busy 时 fail closed，不截断或删除 raw evidence。
- 一个 foreground Run 的唯一性必须由数据库 partial unique constraint/CAS 保证，不能依赖进程内 `asyncio.Queue`。
- Task 8 只把新 Host service 与新 API 接到生产 composition；S5 才把主 Agent 的 route/recall/context/tool 链切入该 authority，S6 才切 UI。

## 分片基线结果

- runner：`plan-test/scripts/baseline_runner.py`；manifest：Host `baseline-shards.json`。
- state：Host ignored `.local-test-evidence/2026-09-01/s4-host-closure-baseline/state.json`。
- 结果：17 个分片中 11 PASS、6 个已登记 known-red、0 个未解释的新失败；`rust-test`、`rust-check`、frontend build/typecheck/vitest、SDK adapter 与 6 个 backend 主分片均 PASS。
- known-red 签名文件：Host `baseline-known-failures.json`，记录时间 `2026-09-01T09:20:23+0800`。签名只用于相对回归；本增量验收后不得新增失败，且 Task 6 必须把下面第 2 项转绿。

### 已有红（均早于 S4 Task 5–8 实现）

1. `backend-a`：`test_dev_reset_rebuilds_three_databases_and_removes_sidecars` 仍断言 Memory SDK 最大 migration=6，实际 candidate 已为 7；`87 passed / 1 failed`。
2. `backend-m-r`：`test_real_product_sdk_production_composition_starts` 缺 Harness 0.7 新增的 `run_context_authority`、`runtime_decision_sink`、`task_execution_authority`；`1502 passed / 1 failed`。该项属于本 slice Task 6 Host wiring，必须修复并移出 known-red。
3. `backend-capabilities`：当前机器 Godot fixture 被投影为 `executable=false`，2 个 publisher 断言失败；`326 passed / 2 failed`，与 memory S4 无关。
4. `backend-companion`：旧测试期待 capability schema v2，实际为 v4；`473 passed / 10 skipped / 1 failed`，与 memory S4 无关。
5. `root-tests` 与 `frontend-lint`：命中仓库既有签名；本增量不扩大修复范围，但最终必须保持不劣于该基线。

## 最小价值路径

`v39 deterministic projections/checkpoint → v40 permission-first search/exact open → v41 durable foreground FIFO → fresh typed Host facade → 100k A/B cold-restart value smoke → v42 recovery fence/production entry → affected/full regression`。
