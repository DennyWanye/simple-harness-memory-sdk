# ARCHITECTURE 索引

本目录是 simple-harness-memory-sdk 的当前架构事实源。main 当前为 **0.6.3 source candidate**
新增 fresh `human-memory-v1` schema v7 的 immutable evidence、append-only suppression/audit、durable analysis
四阶段 authority、四类认知记录的 strict mutation/classification/action-authority 事务底座，以及 strict v4 typed
RecallPlan 执行与最终使用 authority，以及严格 display-only 的 Digital Twin graph projection，并精确依赖
Harness `>=0.7,<0.8`。0.6 不再默认实例化 regex fact
extractor，不导出物理会话删除 API；旧 v4 Message/Fact 类型和私有 storage seam 仅作兼容读及
回归 fixture，不是新 Human Memory 的 authority。候选版本尚未 tag/push/publish。

2026-09-05：隔离0.6.3基线 history visibility 源码候选新增 public batch 来源可见性检查，
修复 memory_id 遗忘后原 USER 历史复活；94项限定 source 测试通过，独立 review 接受。
未改版本/build/pin/合 main，Host接线及 native遗忘验证仍待主线完成；
[交付边界与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/RESULTS.md)。

2026-09-05：0.6.6组合候选在独立分支保留history+clock+rejection，130项限定源码测试通过；
source9ec5943/wheel381d8543已通过新venv publicconsumer与全包字节核验，Host接线另验，冻结旧candidate不变。
[当前候选](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/CANDIDATE-0.6.6.md)。

2026-09-05：后继独立short exact history源码修复28专项+93相邻测试通过，独立review接受。
新增三元carrier复用当前batch suppression/expiry/disclosure；版本尚未分配，未build/合main/接Host，
封存0.6.6 wheel不含此增量。[当前独立源码交付](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/RESULTS.md)。

2026-09-05：主分配0.6.7给已审short增量，独立候选根快照和消费者源码检查通过，wheel验证待完成。
[本轮候选](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/CANDIDATE-0.6.7.md)，不覆盖封存0.6.6或修改Host环境。

| 文档 | 范围 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 包结构、分层、本地后端与召回/认知/世界对象的生产边界 |

Human Memory Program 的 SDK 范围当前闭合到 S3 Task 7：长期认知与五天 Short-Horizon 统一进入 typed recall eligibility、
disclosure、lane-cap/weighted-RRF、去重和 provider-visible budget；durable request/attempt/decision/result/terminal
ledger 支持 exact replay、reopen hash rebuild、atomic confirmation、result-bound page-in 与 final current-use fence；
Digital Twin graph 从 canonical current cognitive records/relation rows 按普通展示 policy 即时重建，且 API/依赖
方向禁止它进入 recall、ranking、Context 或动作 authority。Harness v5 + Memory v7 已从 exact-wheel package root
原子创建一等 `applies_to` relation memory，并通过 owner/endpoint 状态门投影知识边。resolver-backed sealed audit、MEMORY lineage trace、
ordinary-visible metrics 与 canonical state manifest 均通过 public v6 Manager facade 提供。Host/UI 接线仍未实现。

<!-- last-updated: 2026-09-05 -->

2026-09-05：S3 隔离 0.6.5 candidate 已通过源码全量与独立 installed-wheel 核验，尚未合入 main 或 Host pin；401-cell、S5b 及 program 状态见 PROJECT_STATUS 最新节。

2026-09-05：独立0.6.8 source-only admission源码完成36专项、721含专项相邻、4 schema检查；
公开独立receipt/零analysis job、双模式冲突、registration/history union与fresh7.2边界已实现。
Dirac已审oracle，源码复审/wheel/Host11组组合待验，不合main，不标S3/program或selected-only完成。
[本轮事实与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-source-only-admission/RESULTS.md)。

2026-09-05：独立0.6.9 A+B源码候选实现官方非空7.0/7.1保留式升级和actual-selected短来源批量读口；
WAL-only/升级COMMIT前后真进程退出、备份重试、旧任务续跑和history过滤已有限定源码证据。
固定2542736源码已独立scoped ACCEPT；BUSY窄修16项通过，installed wheel待验，不改冻结068、不合main，不标S3/program或Host native完成。
[069验证与剩余边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-069-existing-data-selected-sources/RESULTS.md)。

2026-09-05：独立duplicate-source forget共享源码候选206项限定测试通过，原short用例补强单跑通过；
Dirac对53099e7完整源码 scoped ACCEPT。后继artifact、Hostlegacy settle及native仍待验，不标旧v1cut或program完成。
[当前事实](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-duplicate-source-forget/ENFORCEMENT.md)。
