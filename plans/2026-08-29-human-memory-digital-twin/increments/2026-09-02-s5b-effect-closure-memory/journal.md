# S5b journal（phase-4 验收记录；机器账本 = Host 仓 `plans/.../increments/2026-09-02-s5b-effect-closure-memory/verification/r1-s5b`）

> 完成判定依据：机器门 `finalize` exit code 与 receipt（MACHINE_GATE 启用）；本 journal 为人读视图。

## 核心价值 smoke（主要矛盾最小验证动作）
- 命令：`cd backend && .venv/bin/python -m pytest tests/sdk_adapters/test_s5b_milestone_real_provider.py -m real_provider -q`
- 结果（phase-3 里程碑，主 checkout `a42835d0`，2026-09-03）：1 passed / 51.5s；gpt-5.6-luna；主 Run 4 次 Provider 调用、3 次工具调用；README 1.1.3→1.2.0；closure 由模型在 Run 内自行 `task_scope_update`（兜底 0 调用）；outbox delivered → job applied → cognitive head 物化 → 下一轮 typed_recall 读到 1.2.0；attempts 恰 1。phase-4 将在 code freeze 后以 `record-run --exec` 复跑 ≥2 root。

## 兑现表（逐条必须 AC；phase-4 填）
| AC | 矛盾地位 | 含 UI | 测试方式 | 驾驶者 | 真机证据 | 状态 |
|----|----------|------|----------|--------|----------|------|
| S5B-AC-1 语义收口生产链 | 决定性 | 是 | 自动化（真 SDK loop + 真 store + 真实 provider）+ 真实桌面 UI | ai | 待填 | 待填 |
| S5B-AC-2 analysis 与 outbox | 决定性 | 是 | 自动化 + 真实 provider 里程碑 + 真实桌面 UI | ai | 待填 | 待填 |
| S5B-AC-3 effect gate | 次要 | 否 | 自动化（TC-HM-09 单根 per-canary 口径 + lane） | ai | 待填 | 待填 |
| S5B-AC-6 composition/cutover/遗留 | 次要 | 部分（冷启动） | 自动化 + 冷启动真实桌面 | ai | 待填 | 待填 |

## 冒烟脚本
- 待填（critical + affected surface；S5a `scripts/e2e_s5a_cold_start.py` 可复用为冷启动组合）。

## 广度账本（输入敏感/LLM 载荷）
- 待填（真实 provider distinct 场景 ≥3 类 + 负例；≥2 独立 root，其一 ≥20 turn）。

## 遗留问题清单（不许悬空）
1. F-5：MCP 写类工具未纳入 PROJECT_EFFECT 分类（仅经 unknown EffectClass → Auto confirm-only 间接收窄；project_bound Run 已排除 filesystem MCP）→ S5c/S6 前处理。
2. `_drive_claimed` 真实 runtime 端到端用例未补（Task 6 未完成项）。
3. `backend/uv.lock` 仍指 memory 0.5.2（pin 真相在 `sdk_candidate.py`）→ known-debt。
4. Task 4 审查 P2/P3 遗留：`lease_lost` 两事务窗口与 `revalidate` 生产永不触发；Host durable 响应无本地凭据过滤（Memory 两道边界兜住）；episode `occurred_at` 取分析时刻；`manager()` 注册失败泄漏；测试 `now` 常量；README oracle 偏弱。
5. Prospective/即时操作（AC-4/AC-5）→ S5c；Memory `sent_unknown` 确认通道、`not_sent` 判定依赖 httpx 消息 → SDK 0.8 义务。
6. 真实 UI 截图 PNG 无法落盘（screencapture 权限/Browser pane 不落盘）→ UI 证据以页面文本捕获 + 日志 + DB 行为形态（与 S5a 一致）。
7. HM-AC-8 质量门：240 条语料人工复审仍未安排（用户动作）→ `NOT_RUN/BLOCKED`。

## 终态行
（phase-final 填写）
