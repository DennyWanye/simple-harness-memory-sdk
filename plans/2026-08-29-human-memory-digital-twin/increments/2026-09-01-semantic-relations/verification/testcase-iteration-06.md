# Testcase Challenge Iteration 6 — FAIL

日期：2026-09-01  
Reviewer：`task5_closure_challenge`  
结论：`VERDICT: FAIL`

## 未关闭的 P0

- `relation-integrity-evidence-self-attested`：verifier 虽然包装了真实 `MemoryManager` 并自行记录 trace，
  但 adapter 和包装器仍在同一个 Python 解释器。恶意 adapter 可通过包装方法的 `__globals__` 取得
  `calls`、`fault_events` 或原始方法，篡改 verifier 所有的观测后伪造 PASS。

## 修复方向

- 候选 adapter 与真实执行器必须进程隔离，不共享解释器 globals。
- adapter 只能在 request-only 临时目录中生成 bounded command JSON，不能获知真实 case DB 路径。
- verifier 在独立进程中加载精确 wheels、执行公开 API、注入 fault 并采集 trace；夹带任何自报执行证据的
  adapter 输出必须 fail closed。
