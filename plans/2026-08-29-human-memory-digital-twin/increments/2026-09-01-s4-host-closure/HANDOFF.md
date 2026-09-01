# Handoff：S4 Host Runtime Execution Closure

最后更新：2026-09-01（Asia/Shanghai）

## 交接结论

本轮已完成并验证以下主体实现，但 **plan-test 尚未完成，当前不得宣称 SHIPPABLE**：

- Harness SDK 0.7.1 的 Host initial route / checkpoint / evidence v2 契约；
- Host v44 durable foreground execution ledger；
- TaskScope workspace binding authority；
- HUMAN production composition、foreground scheduler/runtime、唯一 `SdkRuntimeIngress.start`；
- 100k events、A/B 相似任务、cold restart、同一 Host/SDK Run identity 的正式价值链；
- prepare/claim/start/bind/terminal 九个崩溃边界、generation fence、recovery manifest/export。

独立 code-audit 发现两个 P1，任务因此停在整改阶段：

1. `audit-hm-runtime-generation-fence`：Context/Provider/Tool authority 尚未完整绑定
   `(host_run_id, sdk_run_id, owner_id, generation)`；SDK start、signal/cancel、tool effect 前缺少统一的最终
   current-generation admission，旧 worker 可能在 lease reclaim 后产生外部副作用。
2. `audit-hm-control-delivery`：pause/stop/cancel 只写 durable control；运行中的 Runtime 未被即时唤醒消费，
   pause 未可靠推进 PAUSED，stop/cancel 语义尚未完整分离。

另有一个 P2：production foreground composition 与旧 chat ingress 仍是两条构造路径，尚未完全收敛到
plan 中要求的共享 composition service。

## 远程代码身份

| 仓库 | 已完成候选 | 用途 |
|---|---|---|
| `DennyWanye/simple_harness` | `04a5a649109db4bede8a22bb2e4f6df2b481eed9` | 已验证到正式 value/fault runner 的 Host 候选；仍有上述 code-audit P1 |
| `DennyWanye/simple-harness-sdk` | `f5fe0dc7e8c5b521444e01c40cab176f3666c627` | SDK 0.7.1 candidate |
| `DennyWanye/simple-harness-memory-sdk` | 本文件所在提交 | 原始 plan、acceptance、assurance、挑战与交接记录 |
| `DennyWanye/simple_harness` WIP branch | `debug/human-memory-runtime-p1-handoff` / `d8ae3b8f` | 被用户中断时的 P1 修复草稿；仅供续作，不得当作已测试实现合入 |

三个候选在 2026-09-01 fetch/prune 后都证明各自 `origin/main` 是本地候选祖先，可 fast-forward。

## 正式验证事实

- 100k execution value：PASS。
  - 本地结果：`.local-test-evidence/2026-09-01/s4-runtime-value-adapter-14/s4-execution-value-result.json`
  - SHA-256：`ffa35e7c7626d4cee4be4a4770749e4c6e6c74dbc871fbed5c15e38413ccdfea`
- 9/9 execution fault matrix：PASS。
  - 本地结果：`.local-test-evidence/2026-09-01/s4-runtime-faults-4/s4-execution-faults-result.json`
  - SHA-256：`4dfe57fc9fa883c7f2c59133f040223247ee3cec161ef1e1418d7ae129da137a`
- Fault lane focused regression：`63 passed in 17.44s`。
- 当前实现聚焦回归曾取得 `76 passed in 14.86s`；fault 提交后又取得上述 63 passed。
- changed-surface ruff、scoped mypy、py_compile、`git diff --check`：PASS。
- Host full backend pytest 在用户要求立即 handoff 时被中断：执行到约 96%，未生成合法最终结果；途中可见 5 个失败标记，
  尚未完成与 baseline known-red 的签名比对。不得把该次运行记录为 PASS 或 FAIL 总结。
- plan-test `finalize` 尚未执行，未产生最终 receipt。

原始 evidence、SQLite、长日志、receipt 均只保留在本机 ignored `.local-test-evidence/`，没有提交到 Git。

## 下一 Session 的恢复顺序

1. 从三个远程 `main` 重新 fetch/prune，核对上表 SHA 和 ancestry。
2. 在 Host 中查看 `debug/human-memory-runtime-p1-handoff` 的草稿；不要直接合入。
3. 重新从 `main` 建安全修复分支，完成两个 P1：
   - 用一个 production admission seam 在 SDK start、每次 signal/cancel、每次 tool effect 前验证 exact current lease；
   - actual Tool executor 必须调用 `ForegroundQueueStore.authorize_effect`；
   - control commit 后唤醒 active Runtime；pause ACK 推进 PAUSED；STOP/CANCEL 保持独立语义；
   - 添加 bind→start、signal-read→send、tool-admission→effect 三个 reclaim race，断言 stale worker 的外部副作用计数为 0。
4. 应用 minimality review 的三个不降验收简化项：
   - `ClaimedExecution` admission receipt 字段改为必填，删除 Runtime test-store fallback；
   - audit sink 固定同步，删除 speculative `_maybe_await`；
   - 合并 `s4_value_adapter.py` 两处重复 v44 alias→table mapping。
5. 重新执行 code-audit，P1 全 resolved 后再跑：value runner、fault runner、聚焦测试、Host full backend pytest、
   changed-surface mypy/ruff、critical/affected/full-surface smoke。
6. 全绿后更新 Host `ARCHITECTURE/` 与 `ARCHITECTURE/PROJECT_STATUS.md`，再建立新的 plan-test gate run，
   导入/登记证据、full-audit、`finalize`。不得复用或删除旧 gate run。

## 硬边界

- 永远不删除任何原始 session / memory / audit 数据。
- 不访问、不请求、不迁移 `deskpet.receipt_hmac`；不调用 Keychain、`security` 或 `keyring`。
- 不提交 `.local-test-evidence/`、数据库、截图、原始日志、receipt 或 diagnostic archive。
- S5 剩余 RecallPlan、Memory recall、五天短时域、动态 Context、semantic closure 与 S6 UI 不在本次续作范围。

