# ARCHITECTURE 索引

本目录是 simple-harness-memory-sdk 的当前架构事实源。当前 0.4.0 已实现 Agent Memory v1 direct
`MemoryManager`、deployment/household/actor/session + personal/family 隔离、committed-turn 原子写、
durable fact worker 与 privacy tombstone。FTS5、完整 embedding lineage、backup/restore 属 S4；显式
v3→v4 migrator 因 continuation tentative taxonomy 的 A2 冻结问题暂未发布。

| 文档 | 范围 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 包结构、分层、本地后端与召回/认知/世界对象的生产边界 |

<!-- last-updated: 2026-08-22 -->
