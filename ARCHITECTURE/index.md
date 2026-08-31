# ARCHITECTURE 索引

本目录是 simple-harness-memory-sdk 的当前架构事实源。当前 **0.6.0 source candidate**
新增 fresh `human-memory-v1` schema v5 的 immutable evidence、append-only suppression/audit、durable analysis
四阶段 authority，以及四类认知记录的 strict mutation/classification/action-authority 事务底座，并精确依赖
Harness `>=0.7,<0.8`。0.6 不再默认实例化 regex fact
extractor，不导出物理会话删除 API；旧 v4 Message/Fact 类型和私有 storage seam 仅作兼容读及
回归 fixture，不是新 Human Memory 的 authority。候选版本尚未 tag/push/publish。

| 文档 | 范围 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 包结构、分层、本地后端与召回/认知/世界对象的生产边界 |

Human Memory Program 当前只闭合到 S3 Task 1/2；Procedure/Prospective 专用 repository、Short-Horizon、
typed Recall、graph projection 和 Host/UI 接线仍明确标为未实现，避免把计划能力误写成生产事实。

<!-- last-updated: 2026-08-31 -->
