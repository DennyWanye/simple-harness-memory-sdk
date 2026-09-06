# ARCHITECTURE 索引

2026-09-06主复核：源规格编译固定b72dbff限定ACCEPT并FF main；SDK源码仍0.6.3，15项源契约分批闭合，240正式执行仍0。详见[主复核](../scripts/corpus_runtime_input/主代理复核.md)；Host隔离组合18ec7194的M0613安装/模型short/资源验证与此源编译独立，见[续接记录](../plans/2026-08-29-human-memory-digital-twin/RESUME-2026-09-05.md)。

## 2026-09-06 21例可信字段source adapter验收

最后更新：2026-09-06。独立后继分支 `feat/corpus-trusted-bindings` 基于main `2641c90`，新增固定caseID、源行/UTF-8片段/hash映射，将C12全20例及C05-07的fixture配置需求与当前用户句显式分开；运行时不按自然语言分号推断角色、不从gold/setup决定权限。原r4及第一层源码/测试/中文文档未改，本后继分支尚未合入main。

8项标准库契约验收全部通过，覆盖21输入完整保留、源变更拒绝、隐藏gold/setup变异不影响绑定及无凭据/伪造凭据不可dispatch。经145资源入口默认共享锁、512MiB/90秒执行，进程组29035无残留，已通知主释放测试槽。没有运行SDK、Provider、模型或native。

模块边界仍为**源绑定已验收，Host公共setup及authority验证未实现**。21例全部ready/dispatchable/executed=false；第一层21 BLOCKED及240 ready=0历史结论保持。C05-07受众/用途/真实task ID与scope缺口明示；源policy hash不是权限receipt，不把此验收换算为模型质量或401矩阵通过。

[21项逐例映射](../scripts/corpus_trusted_bindings/逐例绑定.md)；[接口及剩余接线](../scripts/corpus_trusted_bindings/接口与状态.md)；[验收命令、源码及ignored证据SHA-256](../scripts/corpus_trusted_bindings/验收结果.md)。

## 2026-09-06 r4源编译与隔离契约验收

最后更新：2026-09-06。独立分支 `feat/corpus-runtime-input` 基于main `1a53e58`，新增标准库MD编译器，生产链路为只读r4源指纹校验 → 显式字段解析 → input/setup/scheduler/oracle/audit分区输出。原240条MD、旧集及阈值不变；不导入SDK、不执行Provider。此分支尚未合入main。

第一层源编译/隔离契约的15项必要验收已覆盖：首轮14项通过、1项测试变异定位错误；修正测试后定向3项通过。双次CLI输出字节一致，240ID/12类/22脚本、时钟与角色历史、输入非干扰和拒绝路径有标准库证据。统一资源入口145baed3以512MiB/90秒、默认共享锁运行；两个进程组无残留并已释放测试槽。

模块状态仅为**源编译层已验收，运行适配未完成**：21例混合可信输入仍阻断投影，全部240例ready=0/executed=0，公共setup/可信政策/三端时钟/真实历史/后续轮事件适配仍缺。零查询不证明后台gate已测，未运行模型质量或native，不能把本层验收当作program通过。

[接口与可见性](../scripts/corpus_runtime_input/接口契约.md)；[批次、命令、失败修正、ignored证据索引及SHA-256](../scripts/corpus_runtime_input/本轮实现状态.md)。以下保留既有审查及历史运行事实。

## 2026-09-06 后继中文语料完成AI两层审查

最后更新：2026-09-06。本仓SDK源码仍是main 0.6.3，隔离Host组合134bc4b8消费H073/M0612/S0313；本次未合入SDK运行时代码或切换用户主checkout。中文后继12×20语料由一个AI子代理和主代理逐条复核，r4语义基准可用于实现评估适配器。不是人工冻结、实际模型质量或完整program通过。
[审查结论、全部MD与剩余接线](../plans/2026-08-29-human-memory-digital-twin/quality/recall-corpus-candidate/review-zh/后继240条主代理复核.md)。401矩阵、两轮模型质量、性能与Context预算仍未完成；以下旧记录按历史保留。

本目录是 simple-harness-memory-sdk 的当前架构事实源。main 当前为 **0.6.3 source candidate**
新增 fresh `human-memory-v1` schema v7 的 immutable evidence、append-only suppression/audit、durable analysis
四阶段 authority、四类认知记录的 strict mutation/classification/action-authority 事务底座，以及 strict v4 typed
RecallPlan 执行与最终使用 authority，以及严格 display-only 的 Digital Twin graph projection，并精确依赖
Harness `>=0.7,<0.8`。0.6 不再默认实例化 regex fact
extractor，不导出物理会话删除 API；旧 v4 Message/Fact 类型和私有 storage seam 仅作兼容读及
回归 fixture，不是新 Human Memory 的 authority。候选版本尚未 tag/push/publish。

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
