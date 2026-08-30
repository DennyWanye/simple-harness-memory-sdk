# V0 — 实施前验收权威、Testcase 迁移与真代码 Spikes

> Release unit：V0（plan/test infrastructure；不实现业务代码）  
> 高风险子系统：验收 authority、跨仓 prototype、容量/Provider compatibility（3）  
> 覆盖：HM-AC-1—8

## 交付边界

V0 必须在 S1 第一行业务代码前完成。它把冻结 acceptance 编译成可运行、可哈希的 testcase/metric/evidence
authority，并用可丢弃真代码关闭五个关键技术假设。Spike 代码和原始结果不进入生产包；选定协议、常数和拒绝路径
回写 S1—S6。任一 P0 spike 不成立则停止受影响实现并回到用户 review，不绕过。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `testcase/human-memory-program/`（三仓适用处） | HM-S1—S12、HM-TO-A1—A8/R1—R8、固定输入/gold/lineage |
| `testcase/index.md`, `testcase/test-inventory.json`（Host） | 旧 Session cases 的 reuse/replace/deprecate 与 replacement IDs |
| `verification/verification-spec.json`, compiled manifest | AC/risk/test/layer/evidence producer 一一映射与 input hash |
| `spikes/*.py`, `spikes/manifests/*.json` | 五项可丢弃 prototype、固定数据集/阈值/环境 |
| `spikes/results/*.json`, `evidence/spike-index.md` | 小型结论、选型、hash；大型原始产物仅 `.local-test-evidence` |

## Tasks

### Task 1 — Seal AC/Test/Evidence authority [HM-AC-1—8]

- 为每个 MUST AC 和 obligation 建 testcase ID、层级、固定输入或生成 seed、gold label、证据 contract、producer、
  required root-run/manual flag、failure meaning；编译前校验无 orphan AC/obligation/case。
- 冻结指标：required-memory-type recall、no-recall correctness、extra-type rate、hard-trigger/privacy correctness 的分母、
  timeout/refusal/invalid-plan 计分和多 run 聚合；性能同时记录 cold/warm p50/p95/max、token、cost。
- 真实模型 authority 为两个独立 root runs；至少一轮是同一 primary conversation 的 >=20 committed turns、两个
  TaskScope、一次 exact resume、工具/Provider/记忆/纠正/忘记/前瞻组合；不得降为 10 turns。
- 验证：compiled manifest hash、fixed corpus hash、formula unit tests、AC/obligation full audit。

### Task 2 — Resolve legacy Session testcase contradiction [HM-AC-1/8]

- 逐项审 `TC-GS-*`、`TC-PS-*` 等 active Session cases：不变行为 `reuse`；由 primary conversation/TaskScope 替代的
  标 `replace` 并给 replacement ID；只验证已退出 UI 的旧行为标 `deprecated`，保留原文件和历史结果。
- inventory 当前 authority 只指向新行为；不得删除历史 testcase 或让旧 Session create/switch/delete 继续作为新产品门。
- 验证：replacement lineage 闭合、无两个 active oracle 对同一行为给相反结论、inventory hash sealed。

### Task 3 — SPIKE-RUNTIME-BRIDGE + SPIKE-PROVIDER-CONTINUATION [HM-AC-1/3/4/6/7/8]

- 用真实 Harness checkpoint/UoW seam 和 fake Host 实现最小 `RunContextAuthorityPort`：route 后 snapshot receipt 在
  provider reservation 前 CAS；断言 Host/Harness/adapter 三方 payload hash 等式与 crash replay 同 snapshot。
- 扩展现有 provider projection outbox prototype，覆盖 Provider/Tool/Context/Route/terminal；Host idempotent receipt 与
  terminal watermark。逐边界 kill，不得有缺口/重复/乱序。
- 对当前支持的 OpenAI/Anthropic/Gemini/Qwen adapter 做 continuation capability inventory：持久记录扫描 raw
  reasoning canary 必须零命中；仅 opaque/public continuation 可恢复，否则冻结 `reasoning_disabled|provider_rejected`。
- 输出：协议草案、序列图、支持矩阵、失败注入结果和 P0 pass/fail receipt。

### Task 4 — SPIKE-CROSS-DB-TRIGGER [HM-AC-4/5/7/8]

- 用 fake clock、Memory registration outbox、Host append-only event cursor/occurrence inbox，证明 Host 是唯一 scheduler；
  复用或适配现有 ReminderScheduler，不建第二 timer authority。
- kill 在 registration、occurrence、snapshot/provider-send checkpoint、ack/settlement；覆盖 duplicate/late/reordered event、
  no-tool/no_recall/refusal、suppression、第三方 recipient。
- 硬判定：同 trigger revision/event 只有一个 occurrence；pending 不丢；replay snapshot hash 相同；sealed 内容零泄露。

### Task 5 — SPIKE-VECTOR [HM-AC-4/6/8]

- manifest 固定 seed/hash、1k/10k/100k active records，5-day 峰值由每日 causal-group/chunk 上限推导；1M 只 exploratory。
- 固定 >=200 queries，覆盖 exact/semantic/entity/time/task/cross-scope/no-match/suppressed/superseded/contested/expired；
  所有 backend 使用相同 permission-first input/top-k/oracle。
- 硬门：privacy/hard trigger 100%，required type recall>=90%，extra type<=15%，warm local p95<=500ms，单次<=2s，
  cold first query<=2s 或稳定降级；suppression/rebuild stale resurrection=0。
- 报告 index/RSS/wheel delta/build/rebuild/write amplification/WAL；多个方案过门时选择无 native 新依赖且部署面最小者。

### Task 6 — SPIKE-CONTEXT-DOC [HM-AC-3/6/7/8]

- CONTEXT fixture >=24 causal groups，两个 TaskScope、resume/standalone、并行工具完整配对、Provider/route/recall/closure、
  五日内外短时、四类长期记忆、skills/tools/attachments、1 MiB tool result；跑 4k/8k/32k 与真实 provider window。
- 冻结 generation reserve、安全余量、各分区 item/byte/token cap、10-group 表示、page-ref 和裁剪顺序；system/current
  query/current tool continuation 不丢，工具因果不拆，provider usage 不超 effective budget，低估 token 一律失败。
- DOC fixture 为同一 TaskScope 的 1k/10k/100k events；枚举 README/STATUS cap。顶层恒定有界，移出事实有稳定 page ref，
  ResumePackage 在固定预算内通过 goal/phase/completed/changed/cancelled reason/next action/repo/tests 全字段 oracle。
- 输出选定常数、hash、p50/p95、增长率并回写 S4/S5。

### Task 7 — V0 closure receipt [HM-AC-1—8]

- 汇总五项 spike 选择/拒绝、testcase/inventory/manifest hashes 和剩余外部 gate；更新所有受影响 slice。
- 运行 plan challenge closure diff；只有全部 canonical P0/P1 有可执行 plan/evidence 或 spike 结论才进入用户一次性 review。

## 验证出口

- S1 尚未修改业务代码；V0 产物已让每个后续 Task 的输入、硬阈值、故障点和证据 producer 固定。
- 任一 P0 spike 失败时结论为 BLOCKED/回到 review；不得以 mock 自洽结果宣称生产链可行。
