# 原始认知架构基准清单

> 冻结日期：2026-08-29  
> 原始文档创建日期：2026-08-17  
> 首次进入原始 Host 仓库的提交：`5da1784b601913692ce7c022a7a7f7a8777d755f`  
> 用途：本次 `plan-bs` 的产品与认知模型基准；这些快照不得在计划迭代中直接改写

## 基准文件

| 快照 | 原始路径 | SHA-256 | 基准职责 |
|---|---|---|---|
| [01-memory-sdk-cognitive-architecture.md](original-2026-08-17/01-memory-sdk-cognitive-architecture.md) | `docs/memory-sdk-cognitive-architecture.md` | `b68a33296f92b493c19f414aeae34335995d55b11dec03c0cb05c0774ea539c0` | 人类 L1/L2/L3 记忆模型、Facts、衰减、巩固、矛盾和遗忘 |
| [02-memory-sdk-deep-dive.md](original-2026-08-17/02-memory-sdk-deep-dive.md) | `docs/memory-sdk-deep-dive.md` | `3aa737326810f49f756665caccede3896f2e8f3660eaa4454b82f0fb701d2d93` | RRF、数字孪生体六维模型、关系图谱与个性化召回 |
| [03-memory-sdk-design.md](original-2026-08-17/03-memory-sdk-design.md) | `docs/memory-sdk-design.md` | `36533fd89a4c8990046fb65f5fd28b342fa8be4140b1ccb49c86c1b9ecc08f07` | SDK Port、后端、Facts 提取与迁移路线的初始设计 |
| [04-world-model-architecture.md](original-2026-08-17/04-world-model-architecture.md) | `docs/world-model-architecture.md` | `85479ecf54a206531778926a50e5cb300f3f18d4cb4ac99a4bda4d9e669933d6` | 外部世界模型及其与用户内部认知记忆的边界 |
| [05-refactor-plan.md](original-2026-08-17/05-refactor-plan.md) | `docs/refactor-plan.md` | `4891f4aef427a8e72cc57f0712c590024f0d99b9f017d9870d65b1808557b30f` | 当时基于认知架构从零重构 SDK 的原始实施设想 |
| [06-memory-sdk-architecture.md](original-2026-08-17/06-memory-sdk-architecture.md) | `plans/2026-08-17-memory-sdk/00-ARCHITECTURE.md` | `322e498d03fa3b9084955917b874ba2576af75e28520d15d9e23a6a72a90f353` | 三层记忆、数字孪生体、世界模型和 SDK 包结构的综合版本 |

## 权威性约定

1. `01` 和 `02` 是本次讨论“人类记忆模型”和“数字孪生体”的首要产品事实源。
2. `03`、`05`、`06` 是历史工程方案，只作为意图与遗漏检查依据；不能覆盖当前 SDK 生产事实。
3. `04` 定义世界模型边界；用户已确认世界模型纳入本次直接实施范围。其具体数据源、刷新策略和
   与记忆系统的接口仍须在 acceptance 与 architecture baseline 中重新校准。
4. 当前 SDK 实现事实以本仓库 `ARCHITECTURE/`、`src/simple_harness_memory/` 和测试为准；
   Host 接线事实需在后续架构基线阶段从 `simple_harness` 当前代码重新校准。
5. 计划提出的新模型、修正或取舍必须写入新的 `acceptance.md` / `plan.md`，不得修改这些快照来伪装成原始设计。

## 明确排除

- `plans/archive/2026-05-21-memory-system-survey.md` 使用的是“L1 文件 / L2 SessionDB / L3 向量”的旧工程存储分层，不作为本次人类认知 L1/L2/L3 的定义 authority。
- `plans/2026-08-17-memory-sdk/HANDOFF.md` 是后续 Host 清理与接入交接，不是原始认知模型；后续架构基线阶段可以作为迁移历史读取。

## 已确认的解释决策

- 原文的 L1/L2/L3、Fact Category、数字孪生体维度不是同一种分类，新的计划必须拆成独立轴。
- 冻结原文只保存历史设计，不直接授权沿用固定衰减率、RRF 权重、具体模型、数据库 Schema 或旧迁移步骤。
- 三种认知记忆统一使用“工作记忆 / 情景记忆 / 语义记忆”，不再使用 L1/L2/L3 编号。
- Session 原始信息完整保存用于审计和复查，不做系统自动删除；显式用户删除的合规语义待确认。
