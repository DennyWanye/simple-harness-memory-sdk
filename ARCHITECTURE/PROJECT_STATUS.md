# PROJECT STATUS — simple-harness-memory-sdk

> 最后更新：2026-09-02

## 2026-09-02 S5a：0.6 消费面定稿 + Host 生产接入

- **终态（2026-09-02）：S5a 增量 SHIPPABLE**，机器门 receipt
  `b5d416e372e3d2b8c3bd6ac86428941ce896b4123e291e12003697cee9118dac`（run `r3-s5a`）。
  7/7 required 场景 root PASS，独立 full-audit verdict=PASS。本仓全量 1071 passed 无回归；
  本轮本仓无代码改动（0.6.0 消费面已定稿），两个缺陷修复均落在 Host 侧。
- **真实桌面 UI 验收对本仓的一条上游义务**：Host 在全新安装场景发现，v7 store 的读路径
  （`read_occurrence_inbox`）对尚未注册的本地属主 fail-closed 抛
  `short_horizon_principal_rejected`，而属主只在首次 typed recall / mutation 时才自注册——
  全新安装的第一次 reconcile 因此必然失败。Host 侧已按"未注册属主的收件箱受 principals 外键
  强制不可能有条目"做了收窄的 fail-open 兜底，但**正解在本仓**：应提供正式的属主注册 API
  （或让读路径对未注册属主返回空页而非冲突），届时 Host 侧兜底分支移除。列 S5b 前置义务。
- **另一条 S5b 上游义务（SDK 仓，非本仓）**：`simple-harness-sdk` 的冻结契约禁止 provider
  assistant 消息把私有 metadata 写进 durable Context，导致 Host 无法跨轮携带 `tool_calls`，
  OpenAI 兼容端点因此拒绝 continuation 请求。建议上游把 assistant 的 `tool_calls` 视为
  一等公共 transcript 字段在 Context 重建请求时回挂。

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
