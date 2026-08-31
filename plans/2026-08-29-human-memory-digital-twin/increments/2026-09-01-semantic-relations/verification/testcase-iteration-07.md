# Testcase Challenge Iteration 7 — FAIL

日期：2026-09-01  
Reviewer：`task5_closure_challenge`  
结论：`VERDICT: FAIL`

## 未关闭的 P0

- `relation-integrity-evidence-self-attested`：进程隔离已关闭共享 globals 逃逸，但 adapter 仍能自由选择
  每个 case/phase 的 command 内容。`exact-replay` 可以在 setup 真实提交两条不同关系，exercise 再真实重放
  第二条；旧 oracle 只验证 replay 前后不变，因此会漏掉额外关系。

## 修复方向

- 为全部 40 cases 的 setup/exercise 冻结 canonical command plan hash、命令 kind 与数量，并由 verifier 独立核对。
- `exact-replay` setup 必须恰好一个真实 apply；setup 后必须精确为一个 relation memory、一个 knowledge row、
  两个 graph nodes 和一个 edge。
- 增加“两条 setup relation 后重放最后一条”的具体负向自检。
