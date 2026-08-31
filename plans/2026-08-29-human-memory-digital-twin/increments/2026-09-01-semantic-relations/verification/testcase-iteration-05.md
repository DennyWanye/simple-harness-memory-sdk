# Testcase Challenge Iteration 5 — FAIL

日期：2026-09-01  
Reviewer：`task5_closure_challenge`  
结论：`VERDICT: FAIL`

## 未关闭的 P0

- `relation-integrity-evidence-self-attested`：虽然 verifier 已自行读取 SQLite、graph 与 parser 结果，
  但调用次数、fault event 和 replay observation 仍由候选 adapter 报告。候选可以执行普通调用后伪造
  `memory_call_count`、事务故障或 replay trace，最终状态差量仍可能满足 oracle。

## 修复方向

- 候选 adapter 不得返回 calls、fault events、outcome、reason code 或 PASS。
- 真实公开 API 调用、fault injection、调用 trace 与返回/异常采集必须由 verifier 所有。
- 为 no-op replay、单调用冒充 commit-before-ack、普通拒绝冒充 rollback fault 增加负向自检。
