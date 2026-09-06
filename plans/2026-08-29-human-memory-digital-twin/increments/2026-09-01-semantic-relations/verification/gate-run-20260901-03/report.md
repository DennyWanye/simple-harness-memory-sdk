# plan-test gate report

RUN: run-20260901-065117
STATE: SHIPPABLE
TESTED HEAD: 9de7635f490c34c4a9c5f144637a05f207e2717e
GATE RECEIPT: 9095e6062ff389e8971b0e652fc20ed708e33dc424521a6fe65bc98d9bd45ce2

TOOLCHAIN（开账时冻结）: gate 1.5.0 / plugin 0.6.1 / Darwin-25.4.0-arm64 / Python 3.9.6 / host Mac
  gate_sha256: 4d1ad47e37e1cfe4a2a3819e268ab59c847dbd5d3704f1ab47e0d8a0317d38f3

## 身份说明（tested vs delivery，读 receipt 前必看）
- TESTED HEAD 是**测试时**的代码提交；把本 run-dir 的账本/截图/receipt 提交进仓库
  的后续提交（evidence-only descendant）**不改变被测内容指纹**，receipt 依然有效。
- 所以「receipt 的 head 早于仓库最终 HEAD」可以是完全合法的状态——判定依据是
  内容指纹（排除下方声明范围），不是提交号。若 tested HEAD 之后还改了任何非 run-dir
  文件，validator 会以 TESTED_RUNTIME_MISMATCH / RETEST_REQUIRED_AFTER_CHANGE 拦截。

## 适用性判定（判「不适用」等于放弃对应条件门，理由须可追责）
- input_sensitive: 不适用（user 判定）理由：本增量只验证冻结的 typed relation plan 与确定性 SDK 行为；自然语言提取质量留待真实主模型门
- llm_payload_driven: 不适用（user 判定）理由：生产上由 LLM 提案，但本增量输入是预冻结的严格 v5 payload；不把 provider 质量纳入 SDK slice
- stateful_init: 适用（user 判定）理由：fresh schema v7、原子 relation write、close/reopen、fault replay 与 corruption 都是本增量核心

## 指纹排除范围（init 时冻结的显式声明；事后往仓库塞文件不改变它）
- 声明范围：.plan-test/active-run.json
- 声明范围：plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03

## 本次命中排除的文件
- .plan-test/active-run.json（declared-scope:.plan-test/active-run.json）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/exec-REL-INTEGRITY-0002.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/exec-REL-REGRESSION-0003.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/exec-REL-VALUE-0001.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/rel-integrity-fault-recovery.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/rel-regression-result.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/artifacts/rel-value-business-result.log（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/plan-test-run.json（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/rel-integrity-metadata.json（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/rel-regression-metadata.json（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）
- plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03/rel-value-metadata.json（declared-scope:plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/verification/gate-run-20260901-03）

## 收尾期改动（re-attest 记录）
- 2026-09-01T06:55:49+0800｜behavioral｜变更 12 个文件｜理由：superseded gate ledgers moved intact to ignored local evidence to satisfy sibling-run policy without deleting raw data

## Evidence 计数（引用不等于独立证明）
- evidence records: 15
- distinct artifacts（按 sha256）: 9
- distinct root runs: 6
- shared artifact hashes: 6

## 审计与账本完整性
- 审计：verdict=PASS engine=independent-codex-agent（产物 auditor-output-final.json）
- 账本链：自洽（36 条写入，链首 init）

## 场景状态（由 validator 重算）
- REL-VALUE [required]: PASS
- REL-INTEGRITY [required]: PASS
- REL-REGRESSION [required]: PASS

## 真人覆盖账本（自动生成；替代 phase-4 ①c 的手写表）
| scenario | gate_type | input_class | root | retry | cont | 业务终态 | 状态 |
|---|---|---|---|---|---|---|---|
| REL-VALUE | positive-value | exact-wheel-public-relation-value | 2 | 1 | 0 | completed+valid,completed+valid | PASS |
| REL-INTEGRITY | negative-safety | relation-admission-atomicity-replay-lifecycle-corruption | 2 | 1 | 0 | completed+valid,completed+valid | PASS |
| REL-REGRESSION | negative-safety | cross-repository-full-regression | 2 | 1 | 0 | completed+valid,completed+valid | PASS |
汇总：distinct_input_classes=3 / root=6 / retry=3 / continuation=0
> retry/同意图改写只证可靠性不增 distinct；continuation 只证 lineage。positive-value 场景的业务终态与 quality_bar 结论仍须人工判定后回填。

## 耗时分解（measured=CLI 单调时钟实测；declared=申报值，低信任）
- automated_test: measured 4.1 min / declared 0.0 min / retry 3 / abort 0 / tests 5670
- checkpoints: 0

## 本 run 开销表（阶段 × 耗时 × 子代理数）

| 阶段 | 事件跨度(min) | timing 实测(min) | 子代理派发 | 轮次 |
|---|---|---|---|---|
| phase-4 | 3.7 | 2.0 | 0 | 0 |
| phase-5 | 15.8 | 2.1 | 0 | 0 |

> 遥测口径：跨度=配对 phase-start/end 时间差合计；实测=该阶段 measured timing；子代理/轮次=phase-end --subagents/--rounds 自报（未报=0）。供 LEAN 档压缩效果比对，不参与门判定。
