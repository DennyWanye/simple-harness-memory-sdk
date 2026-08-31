# Testcase Challenge Iteration 4 — FAIL

日期：2026-09-01  
Reviewer：`task5_closure_challenge`  
结论：`VERDICT: FAIL`

## P0

- `relation-integrity-evidence-self-attested`：旧 integrity verifier 只验证 artifact ref/hash、字段形状与生产者自报
  `status=PASS`，没有解析 artifact 并独立验证 exact rejection reason、all-old/all-new roots/cardinality、edge lifecycle、
  relation correction、corruption reopen 与 raw-evidence retention。因此任意 bytes + 自洽 hash 仍可能伪造 PASS。

## 修复方向

- artifact 必须是严格结构化 canonical JSON，不接收 producer-reported PASS。
- verifier 必须按 40 个 case 的类别独立计算调用数、exact reason、root/cardinality delta、receipt replay、old/new edge、
  reopen status/edge/payload 和 raw-evidence retention；任一差异 FAIL。
