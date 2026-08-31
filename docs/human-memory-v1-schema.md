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

## v6 audit access and canonical state manifest

`sealed_audit_access_receipts` 保存 external authority ref、requester/target binding、decision hash、
issuer+nonce、replay identity 与 consumption hash；`audit_access_authority_events` 对每次授权或拒绝保存
stable reason 与 hash，不保存 exception text、凭据、内容或模型 reasoning。旧 direct decision issuance
只写 denial event 后 fail closed。

`canonical_manifest_access_events` 在 manifest snapshot 完成后写入，并绑定 manifest payload hash。
coverage registry 对每个 required v6 table 明确标记 principal-scoped root 或 derived/global exclusion；roots
覆盖 cognitive/current heads、evidence/mutation/context-use、analysis/job/outbox、conversation、Procedure/
Prospective、Short-Horizon、recall 与历史 audit access ledger。当前读取事件不在当前 snapshot 中，下一次
snapshot 会将它作为历史 ledger 行纳入。每张表只公开 count、root 与 first/last leaf hash，raw
row/ID/content/time 不离开 repository。`audit_cursor_authority` secret 不进入 manifest，但其 SHA-256
绑定 initialization receipt，reopen 会重验 key 与 receipt。

schema v6 仍为 fresh-only：DDL/checksum/initialization receipt 同步更新，不存在隐式 migration。
