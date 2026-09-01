# plan-test Runlog（可提交摘要）

日期：2026-09-01（Asia/Shanghai）；本文件只记录命令、状态、代码/产物哈希和门禁结论，不包含原始 evidence。

## 最终状态（2026-09-01 第二轮 session，P1 整改闭合）

**SHIPPABLE。** `finalize` exit 0；GATE RECEIPT
`b57eadd5c501b30295c57f866c98e9caee9449016e3b35a7ad3130772221263d`
（gate run `r2-p1-closure`，run-20260901-153005，位于 Host 仓
`plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-s4-host-closure/verification/r2-p1-closure/`）。

| 项 | 值 |
|---|---|
| TESTED HEAD（Host） | `5b731364`（候选代码 `56d99a21`，docs 提交不改行为字节；基线 main `04a5a649`，分支 `fix/human-memory-runtime-p1-closure`） |
| SDK | 0.7.1 candidate `f5fe0dc7`；wheel SHA `4d5d2b7ba5c2…` |
| memory-sdk | 验证资产提交 `7cb2994` 起 |
| 执行/审计引擎 | executor=claude-fable-5；auditor=opus（独立） |

## 本轮完成步骤

| 阶段 | 状态 | 关键结果 |
|---|---|---|
| P1 整改 `audit-hm-runtime-generation-fence` | RESOLVED | EffectBoundary(SDK_START/SDK_CONTROL/TOOL) 最终 admission；四元组绑定全部 frozen authority；ForegroundEffectAdmissionGate 接入 ProductEffectExecutor（main.py 单例双向注入）；admission receipt 必填 |
| P1 整改 `audit-hm-control-delivery` | RESOLVED | after_control 即时唤醒；控制泵与 terminal 观察并发；pause ACK→PAUSED；STOP/CANCEL 独立信号（sdk-stop:/sdk-cancel:）与独立终态（resolve_host_terminal） |
| Minimality 三项 | DONE | admission receipt 必填删 fallback；audit sink 固定同步删 `_maybe_await`；合并 v44 alias 映射 |
| 四类竞态测试 | 12 passed | bind→start / signal-read→send / tool-admission→dispatch 的 reclaim race + pause/stop 即时送达（stale worker 外部副作用 = 0） |
| 独立 code-audit round-3（opus） | PASS | 2 P1 resolved；6 P2 open 已登记（`code-audit-round-3.json`） |
| 100k archive cold-resume value smoke | PASS | scheduler=held 保持 durability oracle 语义 |
| 100k execution value runner | PASS | first_run `d92d2785…`↔`product-sdk-47b21712…`；COMPLETED→next（身份不同）；`session_db_reads=0`；冷重启同一身份 |
| 9-boundary fault runner | PASS | 9/9 同一身份恢复；generation fence g1→g2 |
| critical/affected API smoke | PASS | 22 cases，含 Manual 两阶段 binding、live pause control（await RUNNING→pause→finish）、legacy CRUD fence |
| full-surface route smoke | PASS | main.py 装配 + 14 路由 + /health 200 |
| 聚焦套件 | 12/36/25/25/36 passed | views / fifo / integration / data-recovery / authority |
| Host full pytest | 6218 passed / 50 skipped / 6 failed | 6 个失败全部既有：4 项 baseline known-red + 2 项本机环境失败（`test_health_check_timeout_values` 硬编码他机路径、`test_exact_pinned_sdk_062_*`），auditor 亲自在未修改 main worktree 复现；required 转绿项 `test_real_product_sdk_production_composition_starts` 已绿；相对回归 = 0 |
| changed-surface ruff/mypy | PASS | 相对 main delta 为空（8/6 文件） |
| full-audit round-1（opus） | FAIL | P1 `audit-hm-value-execution-evidence-unbound`：执行价值链证据真实 PASS 但未绑定 S4-VALUE-100K |
| 整改 | DONE | 执行价值链 root run + 证据（ev-aef23908f545 / ev-f4c20b9c649c）绑定；spec 固化 execution facts、oracle pin/testcase revision 同步；lane-summary 修正并保留 batch1 原件 |
| full-audit round-2（opus） | PASS | 6/6 MUST AC；无 open P0/P1；17 条 evidence hash 复验一致 |
| `finalize` | exit 0 | receipt `b57eadd5…263d`；提交后重跑仍 PASS 同 digest |

## 本机环境说明

- 全套证据在本机（taiwan）fresh 重建：uv + Python 3.12 venv、vendored SDK 0.7.1 wheel（SHA 校验一致）。
- 上一 session 中断的 full pytest 已完整重跑（不继承）。
- 复用 adapter artifact 目录会因残留 `sdk-runtime` durable 状态阻塞 scheduler 启动——runner 必须用全新 artifact 目录（已在 lane-summary 与 gate resolution 留痕）。

## 遗留（P2，非阻塞，下一增量处理）

`auditor-output.json`（round-2）与 `code-audit-round-3.json` 为准，共 11 项 open P2：
composition 双路径漂移；effect gate 进程内注册表；泵异常降级；PAUSED 无生产 resume；
CLAIMED 期 control liveness；cancel 即时送达正向未单测；oracle pin 冻结机制无自检
（且 file-bytes vs canonical-bytes 口径未统一）；本 run 冻结 manifest 的 testcase revision
pin 落后于 spec（spec 已改 TC-HM-11=5/TC-HM-14=3）；S4-VIEWS artifact-kind 复用同一日志；
lane-summary 人工改写留痕；ARCHITECTURE.md P2 枚举缺第 6 项；baseline.md 身份段指向他机
（known-red 清单内容仍有效）。

## 范围边界（不变）

S5 剩余 RecallPlan/Memory recall/五天短时域/动态 Context/semantic closure 与 S6 UI 未实施；
多 root project effect 稳定 fail closed；发布/push/tag/merge 不在本增量。原始 evidence
仅存 ignored `.local-test-evidence/`，未提交。
