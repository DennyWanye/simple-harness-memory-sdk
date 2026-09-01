# S5a journal（phase-4 验收记录，2026-09-02）

## 核心价值 smoke（主要矛盾最小验证动作）
- 命令：`cd backend && .venv/bin/python -m pytest tests/sdk_adapters/test_s5a_milestone_real_provider.py -m real_provider -q`
- 结果：4/4 PASS（gpt-5.6-luna）。"继续以前的 A" → search → exact open → 同 Run continuation 用 exact ResumePackage 回答；3 turn snapshot receipt 三 hash 相等；durable resume decision；worst prompt_tokens ≤ effective(32768)=25396。

## 兑现表（逐条必须 AC）
| AC | 矛盾地位 | 含 UI | 测试方式 | 驾驶者 | 真机证据 | 状态 |
|----|----------|------|----------|--------|----------|------|
| S5A-AC-1 五路 route 生产链 | 决定性 | 是(acceptance manual_required) | 自动化（真 SDK loop + 真 S4 store + 真实 provider 四路正向）| ai | r2-s5a evidence/s3-*.log + s1/s2 real logs + .local-test-evidence transcripts | ✅ 自动化面；⚠️ 真人桌面 UI run 待用户驾驶或批准等价（见遗留） |
| S5A-AC-2 per-turn snapshot 三 hash | 决定性 | 否 | 自动化（loop 级 + kill-replay + 冷启动 DB 断言）| ai | evidence/s5-kill-replay-twin.log、s6-cold-start-e2e.log | ✅ |
| S5A-AC-3 因果组/冻结预算 | 次要 | 否 | 自动化（常量逐字节 pin + 生产 fail-closed + usage 校准）| ai | evidence/s5-*.log、s2 real usage 断言 | ✅ |
| S5A-AC-4 no_recall 门 | 次要 | 否 | 自动化（真 v7 生产注入负测试 + suppression 对照 + presented membership + loop 级全接线）| ai | tests/sdk_adapters/test_no_recall_gate.py（6 lane）via s6 组合 log | ✅ |
| S5A-AC-5 recall 二审 | 次要 | 否 | 自动化（真 v7 双 lane、fragments bytes/tokens/lane、privacy+hash 去重）| ai | test_no_recall_gate::memory_standalone lane | ✅ |
| S5A-AC-6 composition fail-closed 版本锁 | 次要 | 部分 | 自动化（human-epoch 组合冒烟、缺件/44 库 stable fail、wrong-wheel-hash、冷启动 E2E）| ai | evidence/s6-*.log | ✅ |
| S5A-AC-7 Memory 0.6 消费面 | 次要 | 否 | 自动化（consumer contract 5 lane、双 clean build、exact pin）| ai | evidence/reg-memory-full-suite.log + wheel sha | ✅ |

## 冒烟脚本
- `scripts/e2e_s5a_cold_start.py`（冷启动组合，PASS，输出入 r2 evidence）；deterministic/real pytest lanes 全部存盘可复跑。

## 广度账本（输入敏感/LLM 载荷）
- 真实 provider distinct 场景：no-recall 改写、久远 resume（含 stale-pin 诚实拒绝一例）、direct 概念问答、continue 承接 ×各≥2 run（S1/S2 各 2 root，direct/continue 各 2 across会话）；载荷五类变异 deterministic 全 fail-closed；retry 只计 retry。
- 随机性：STOCHASTIC ≥2 独立 run 达成（S1×2、S2×2、direct/continue 复跑）。

## 用户决定在案（原话 hash）
- provider 配置/持久化（llm_runtime.json 明文=产品配置面）：sha256 53e8d640d1af4119…
- 向量模型 WeMM-Embedding-2B 取代 BGE：sha256 804fa34260665595…
- plan 批准："批准" sha256 8cbe697b157364a5…

## 遗留问题清单（无悬空）
1. **真人桌面 UI 场景（S5A-S1/S2/S3/S6 manual_required=是）+ ≥20 turn 真实长会话**：headless 后端被 Tauri 身份桥门控，只能由用户在真实 app 驱动，或用户显式批准 all-ai/自动化等价（record-approval 待用户答复）——DoD 收尾前唯一未决项。
2. WeMM 快照上传 COS 模型桶（发布前置，S5b/发布任务）。
3. PROJECT_EFFECT root 签发接线（S5b Task 5 前置义务）。
4. HM-AC-8 质量门 NOT_RUN/BLOCKED（外部人工语料 review 前置，如实维持）。
5. 本机 7 项环境红（S4 期在案基线）+ companion 首启依赖 Tauri 身份桥的 headless 不可达性（产品既有）。
6. S5b backlog：settled 状态机、semantic closure、Memory analysis/Prospective scheduler、11 P2 + 6 review-deferred。

## 终态行
（phase-final 填写）
