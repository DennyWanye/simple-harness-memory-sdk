# ARCHITECTURE 索引

本目录是 simple-harness-memory-sdk 的当前架构事实源。当前 0.4.0 已实现 Agent Memory v1 direct
`MemoryManager`、deployment/household/actor/session + personal/family 隔离、committed-turn 原子写、
durable fact worker、privacy tombstone、有界 FTS5/vector recall、完整 embedding lineage、双 generation
reindex、单写者、SQLite backup/restore、四类 taxonomy 驱动的显式 backup-first v3→v4 migrator、
deployment-scoped recall snapshot、跨平台 writer lease、principal-scoped explicit fact write/read，以及
durable explicit forget action receipt、principal-scoped fact listing、0.4.0 exact-wheel candidate
identity/provenance门禁，以及基于 Harness 0.4 共享协议的 Memory observability S1+S2。公开 builders、
direct backends、recall/committed-turn/fact-job/recovery 与 aggregate diagnostics snapshot 已接线；
`simple_harness` 产品接线与真实 UI 已完成，其他 future consumers 仍只接口就绪。

| 文档 | 范围 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 包结构、分层、本地后端与召回/认知/世界对象的生产边界 |

<!-- last-updated: 2026-08-23 -->
