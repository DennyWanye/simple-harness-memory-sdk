# plan-test Runlog（可提交摘要）

日期：2026-09-01（Asia/Shanghai）

本文件只记录命令、状态、代码/产物哈希和门禁结论，不包含原始 evidence。

## 已完成步骤

| 阶段 | 状态 | 关键结果 |
|---|---|---|
| SDK 0.7.1 evidence compatibility / Host exact pin | PASS | SDK `f5fe0dc7`; wheel SHA `4d5d2b7ba5c2f8ef4956af77769d75e1ac7889a037acbdcf853d0b9a5b3a3218` |
| v44 foreground ledger | PASS | atomic claim、immutable preparation/start/terminal/reconciliation receipts |
| minimum Runtime composition | PASS（代码与聚焦测试） | production HUMAN ports、唯一 SDK ingress、exact route/binding/recovery |
| 100k execution value | PASS | result SHA `ffa35e7c7626d4cee4be4a4770749e4c6e6c74dbc871fbed5c15e38413ccdfea` |
| 9-boundary fault/restart | PASS | result SHA `4dfe57fc9fa883c7f2c59133f040223247ee3cec161ef1e1418d7ae129da137a` |
| diff minimality review | LEAN | 3 个可自动应用的内部简化项，尚未应用 |
| independent code-audit | FAIL | 2 个 open P1、1 个 open P2；完成度 4/6 MUST AC = 67% |
| Host full backend pytest | INTERRUPTED | 用户要求立即交接时约 96%；无最终 summary，不可用于门禁 |
| plan-test full-audit/finalize | NOT RUN | 没有最终 receipt；当前非 SHIPPABLE |

## 正式命令

```text
PYTHONPATH=backend backend/.venv/bin/python testcase/human-memory-program/runners/run_s4_execution_value.py \
  --adapter backend/deskpet/memory/s4_value_adapter.py \
  --artifact-dir .local-test-evidence/2026-09-01/s4-runtime-value-adapter-14 \
  --sdk-wheel backend/vendor/simple_harness_sdk-0.7.1-py3-none-any.whl \
  --sdk-wheel-sha256 4d5d2b7ba5c2f8ef4956af77769d75e1ac7889a037acbdcf853d0b9a5b3a3218 \
  --sdk-version 0.7.1 \
  --sdk-source-commit f5fe0dc7e8c5b521444e01c40cab176f3666c627
```

结果：PASS；result SHA `ffa35e7c7626d4cee4be4a4770749e4c6e6c74dbc871fbed5c15e38413ccdfea`。

```text
PYTHONPATH=backend backend/.venv/bin/python testcase/human-memory-program/runners/run_s4_execution_faults.py \
  --adapter backend/deskpet/memory/s4_value_adapter.py \
  --artifact-dir .local-test-evidence/2026-09-01/s4-runtime-faults-4 \
  --sdk-wheel backend/vendor/simple_harness_sdk-0.7.1-py3-none-any.whl \
  --sdk-wheel-sha256 4d5d2b7ba5c2f8ef4956af77769d75e1ac7889a037acbdcf853d0b9a5b3a3218 \
  --sdk-version 0.7.1
```

结果：PASS；9/9 fault boundaries；result SHA `4dfe57fc9fa883c7f2c59133f040223247ee3cec161ef1e1418d7ae129da137a`。

```text
backend/.venv/bin/python -m pytest backend/tests -q
```

结果：INTERRUPTED at ~96%；未产生 final exit/summary。运行途中看到 5 个 `F` 标记，需下一 Session 重跑并与
`baseline.md` 的 known-red signature 比对。

## 审查发现

### P1 `audit-hm-runtime-generation-fence`

旧 worker 在 lease reclaim 后仍可能越过 Host ledger 调 SDK start/signal/tool effect。需要把 exact
`(host_run_id, sdk_run_id, owner_id, generation)` 绑定到所有 authority，并在每个外部 effect 前做最终 admission。

### P1 `audit-hm-control-delivery`

durable control commit 没有即时唤醒 active Runtime；pause/stop/cancel 状态语义未闭合。

### P2 `audit-hm-composition-drift`

foreground composition 与旧 chat ingress 尚未共享同一构造 service，存在双路径漂移。

### Minimality findings

1. admission receipt 字段必填，删除 test-only compatibility fallback；
2. audit sink 固定同步，删除 speculative async helper；
3. 合并 adapter 重复的 v44 audit table mapping。

## 中断时状态

- Host 已验证候选：`04a5a649109db4bede8a22bb2e4f6df2b481eed9`。
- P1 修复草稿：remote branch `debug/human-memory-runtime-p1-handoff`，commit `d8ae3b8f`；未测试、不得直接合入。
- ARCHITECTURE 未回写为完成，因为 code-audit 未通过。
- 旧 gate run 与本地 evidence 均保留，未删除、未提交。

