# phase-4 lane 命令（每次真实执行据实入账；cwd = simple_harness/backend；退出码保真）

## 2026-09-05 已批准口径与当前操作修正

下表保留原操作清单，S1/REG 按本节执行；它不是修改原业务 oracle 或削弱原 AC。
A14 已将 S1 UI 面移交 S6：S1 必须由真实 backend 的公开 `queue.enqueue`、真实 Provider、
真实 workspace diff/STATUS/analysis evidence 兑现两独立 root；下面 pytest milestone 只能作集成回归。
同一真实执行据实 record-run/attach，不为入账先重复消耗一次 Provider。collector 修正版本及原 hash
见本机 `tools/derived-correction-recollection-before-20260905T095723/HANDOFF.md`；旧试次保持。

REG 按原 acceptance/plan/baseline 的“不低于基线、无本次新增回归”判定：历史红转绿不能因
未满足旧命令 `N == 7` 而制造失败；也不能只按总数≤7或节点同名豁免新原因。
必须逐项比较失败节点与原因、保留完整原 pytest 退出码，单列修复后的定向复测、收集/skip/deselect
与任何新增失败。旧七节点及原日志继续保留；当前差异见 `RESUME-2026-09-05.md` 和
Host ignored `reg-full-host/REPORT.md`，不以文字结论伪造 machine gate PASS。


| 场景 | root run 命令（`--exec -- bash -c "<cmd> 2>&1 | tail -2; exit ${PIPESTATUS[0]}"`） | 附加 flags |
|---|---|---|
| S5B-S1-REAL-EFFECT-CLOSURE-MEMORY | `.venv/bin/python -m pytest tests/sdk_adapters/test_s5b_milestone_real_provider.py -m real_provider -q -p no:cacheprovider` | `--run-id-under-test <sdk_run_id>` `--business-terminal completed+valid`；≥2 root；真实桌面 UI run 另以 attach-evidence（ui-capture=页面文本）入账 |
| S5B-S2-CLOSURE-FAULT-MATRIX | `.venv/bin/python -m pytest tests/faults/test_foreground_fifo_closure.py tests/sdk_adapters/test_task_scope_update_tool.py tests/sdk_adapters/test_post_turn_invoker.py tests/sdk_adapters/test_s5b_acceptance_matrix.py -q -p no:cacheprovider` | `--lane temporal-fault` `--run-id-under-test <fault root_run_id>` |
| S5B-S3-ANALYSIS-IDEMPOTENCY-FAULTS | `.venv/bin/python -m pytest tests/faults/test_memory_mutation_plan.py tests/sdk_adapters/test_post_turn_invoker.py tests/memory/test_memory_ingestion_outbox.py tests/sdk_adapters/test_s5b_milestone_effect_closure_memory.py -q -p no:cacheprovider` | `--lane temporal-fault` `--negative-assertion`（不创建 Run） |
| S5B-S4-EFFECT-GATE | `.venv/bin/python -m pytest tests/faults/test_taskscope_init_binding.py tests/sdk_adapters/test_effect_gate.py tests/sdk_adapters/test_effect_gate_hardening.py tests/sdk_adapters/test_effect_gate_replay.py tests/sdk_adapters/test_tool_authority.py -q -p no:cacheprovider` | `--run-id-under-test <root_run_id>` |
| S5B-S7-COLDSTART-COMPOSITION-PAYLOAD | `.venv/bin/python -m pytest tests/memory/test_s5b_v46_cutover.py tests/sdk_adapters/test_composition.py tests/sdk_adapters/test_no_recall_gate.py -q -p no:cacheprovider --deselect tests/sdk_adapters/test_composition.py::test_close_during_start_prevents_ready_publication` + 冷启动真实桌面（Task 7 通道，fresh userdata） | UI run 以 attach-evidence 入账（cold_start） |
| S5B-S8-REAL-UI-CHANNEL | Task 7 通道 1-turn 预演（evidence 目录 20260903T022508 已 PASS，code freeze 后复跑一次入账） | attach-evidence（ui-capture=页面文本 + 日志 + DB 行） |
| S5B-REG-FULL | Host：`set -o pipefail; .venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tee /tmp/reg.txt | tail -2; N=$(grep -c '^FAILED' /tmp/reg.txt); UNEXPECTED=$(grep '^FAILED' /tmp/reg.txt | grep -vcE 'test_atomic_publisher_install_update_rollback_and_uninstall|test_shared_publish_lock_never_exposes_mixed_snapshot|test_workflow_fresh_schema_installs_capability_v2_idempotently|test_exact_pinned_sdk_062_reopens_twice_and_rejects_recoverable_runs|test_dev_reset_rebuilds_three_databases_and_removes_sidecars|test_health_check_timeout_values|test_process_list_with_query'); test "$N" -eq 7 -a "$UNEXPECTED" -eq 0`；Memory：`.venv/bin/python -m pytest -q` 全绿 | `--negative-assertion` |

注意：既有挂起用例 `test_composition::test_close_during_start_prevents_ready_publication` 在 main 同样挂起（S4/S5a 在案），全量回归以 `-p no:cacheprovider` 直跑并核对 7 条基线红；若该用例导致全量挂起，用 `--deselect` 并在证据中说明。
