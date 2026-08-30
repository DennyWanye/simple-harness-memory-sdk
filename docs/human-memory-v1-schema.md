# human-memory-v1 fresh schema boundary

0.6.0 的新写入路径从 fresh SQLite root 初始化，`schema_meta` 记录 protocol 和 DDL
checksum。任何 v4 或未知 schema 都稳定拒绝，runtime 不迁移、不覆盖、不删除旧行。

权威表分为：principal/subject，immutable evidence envelope/item/receipt，append-only suppression
directive/revoke，LLM invocation/structured decision，durable job/attempt/outbox，以及 embedding lineage /
generation。原始 evidence 只追加；suppression 改变普通读是否可见，不物理删除 evidence。

Memory analysis mutation 只能按 `handed_off → result_committed → audit_pending → applied`
推进。每个 phase capability 由 repository 单次签发，绑定 claim、request hash、attempt、
delivery result 与 repository-generated application receipt。调用方自造 receipt 或 decision 不是应用权限。

0.6 public API 不导出 `delete_session`、`delete_old_sessions` 或 `delete_all`。旧 v4 storage
中保留的私有 cleanup seam 只为兼容回归，无法经 `MemoryManager`、`MemoryBackend` 或
`BaseMemoryBackend` 调用。

兼容 v4 `Fact` row 不是新 Human Memory authority。其 `category` 只保留为标签，不映射
half-life；`decay_rate` 读取和写入显式 neutral `0.0`，maintenance 不再按 category 自动遗忘。
production package 不包含 regex/LLM Fact extractor 或 legacy Fact worker；Mock/SQLite 也不暴露
recover/claim/apply/fail mutation seam。旧 `fact_jobs` 表只允许 dormant storage、只读 diagnostics 与
erasure cleanup。
