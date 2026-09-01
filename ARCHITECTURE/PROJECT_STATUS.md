# PROJECT STATUS — simple-harness-memory-sdk

> 最后更新：2026-09-01

## 2026-09-02 S5a：0.6 消费面定稿 + Host 生产接入

- Host `feat/human-memory-s5a-context-route` 完成 S5a：v7 认知库首次生产组合（HumanMemoryV7Runtime），
  typed recall + short-horizon 双 lane 消费，occurrence inbox reconcile 成为 no_recall 硬门。
- 本仓交付：inbox/outbox 只读投影（含 suppressed 标志）、jobs 包根导出、v7 embedder 生产守卫、
  uv.sources 修复；1071 测试全绿；wheel 62a3f63c…（Host vendor exact pin + candidate manifest）。
- S5b 待办：registration outbox 消费/settled 状态机（presented cursor 由 Host v45 持有）、
  PROJECT_EFFECT root 签发接线（Host 侧）、WeMM 快照上传 COS。

## Human Memory Program

| Slice | 状态 | 当前生产事实 |
|---|---|---|
| V0 / S1 / S2 | 完成 | fresh v7 evidence、suppression、durable analysis 与 cognitive mutation authority |
| S3 Task 1–3 | 完成 | 四类 cognitive records、Procedure/Prospective lifecycle 与 Host authority consumption |
| S3 Task 4 | 完成 | 五天 Short-Horizon disposable projection；真实 semantic quality corpus 仍为外部 gate |
| S3 Task 5 | 完成 | strict typed recall、durable replay ledger、page-in 与 final current-use fence |
| S3 Task 6 | SDK 完成 | Harness v5 `applies_to` relation plan、Memory v7 canonical owner/derivative 原子写、公开 receipt view 与 display-only graph gate 已通过 exact-wheel 2-node/1-edge、suppression/reopen 0-edge 及 40-case integrity matrix |
| S3 Task 7 | 完成 | ref-authorized sealed audit、MEMORY trace、fixed metrics、canonical manifest、public v6 facade |
| Host / UI 接线 | 未开始 | Memory library API ready；不外推为产品或真人交互验收 |
| 0.6 candidate packaging | 待最终门禁 | relation SDK slice 已闭合；Host durable pre-admission audit 与真实 LLM quality 仍为明确外部门，未 tag、push、publish |

## Task 7 安全边界

- authenticated requester 与 target subject identity 分离并 exact 绑定；caller 自行构造 sealed decision 无效。
- 普通 metrics/trace 先执行 suppression policy；sealed read 共用 durable `max_reads` 预算并记录 hash-only access event。
- manifest coverage registry 覆盖全部 required v6 table；当前 access event 在 snapshot 后写入，历史 ledger 在后续 snapshot 可验证。
- manifest 是可比较的完整性快照，不替代外部保存的可信历史 hash，也不声称抵抗 DB owner 同步改写。
