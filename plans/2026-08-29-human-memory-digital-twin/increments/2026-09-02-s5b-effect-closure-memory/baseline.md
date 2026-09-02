# 绿色基线（S5b 开工前，2026-09-02）

| 仓 | HEAD | 命令 | 结果 | 备注 |
|---|---|---|---|---|
| Host `simple_harness` | `ec1cb944`（main，工作树干净） | `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` | **7 failed, 6282 passed, 50 skipped, 5 deselected**（386.67s） | 7 红 = 本机既有环境红，与 S5a receipt `r3-s5a` 的 `reg-baseline-exclusions.md` 逐条相同（见下） |
| Memory SDK `simple-harness-memory-sdk` | `fcf1682`（main，工作树干净） | `.venv/bin/python -m pytest -q -p no:cacheprovider` | **1071 passed, 8 skipped**（40.60s） | 全绿 |
| Harness SDK `simple-harness-sdk` | 0.7.1 冻结（`f5fe0dc`） | 不改动、不复跑 | — | program 期间冻结 |

## Host 既有 7 红（基线签名，非本增量回归；判据"不低于基线"）

```
tests/capabilities/test_registry_publisher.py::test_atomic_publisher_install_update_rollback_and_uninstall
tests/capabilities/test_registry_publisher.py::test_shared_publish_lock_never_exposes_mixed_snapshot
tests/companion/test_capability_owner_scope.py::test_workflow_fresh_schema_installs_capability_v2_idempotently
tests/product_state/test_host_control_downgrade.py::test_exact_pinned_sdk_062_reopens_twice_and_rejects_recoverable_runs
tests/test_agent_storage_reset.py::test_dev_reset_rebuilds_three_databases_and_removes_sidecars
tests/test_error_handling_fixes.py::test_health_check_timeout_values
tests/test_process_list_error.py::test_process_list_with_query
```

回归 lane 口径：脚本自判"恰好这 7 条且零意外"（`set -o pipefail`，不用 `; exit 0` 掩码）。

原始日志：本目录 `.baseline-host-full.log`（ignored 不提交；若缺失以本表为准）。
