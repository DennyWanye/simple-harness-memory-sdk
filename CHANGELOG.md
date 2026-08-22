# Changelog

All notable changes to `simple-harness-memory-sdk` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Bounded retrieval and SQLite operations

- Added identity/scope-filtered external-content FTS5 indexes and bounded lexical/recent vector
  candidate decoding against the active embedding generation only.
- Added complete embedding lineage, local-only BGE loading, fail-closed production embedder
  construction, and restartable two-generation reindex with verified atomic activation.
- Added a per-database writer lease, serialized bounded checkpoints, online backups with
  schema/lineage/SHA-256 manifests, and closed-manager restore with corruption checks and atomic
  replacement.

### Agent Memory v1 / schema v4

- `MemoryManager` now directly implements the Simple Harness `AgentMemoryPort` through lazy
  imports supplied by the optional `[harness]` extra; the former public conversation adapter and
  duplicate DTO exports are retired.
- Fresh SQLite schema v4 persists deployment/household/actor/session identity, personal/family
  scope, immutable bindings, recall write fences, erasure epochs, turn receipts and tombstones.
- A committed turn atomically creates one receipt, the user/assistant pair, and a durable fact job.
  The leased worker performs extraction outside the write transaction and atomically applies its
  canonical snapshot with the job acknowledgement; expired claims recover at startup.
- Added principal export, scope deletion, fact forgetting and authorized family projection APIs.
  Deletion advances the erasure epoch before cascading content and prevents late replay/job
  resurrection.
- Structured Agent Memory events emit opaque principal identifiers and counts/hashes only.
- Added an explicit backup-first v3→v4 migrator and public manifest import API. The approved
  four-way taxonomy suppresses tentative, terminal and deferred legacy sources with hash-only
  receipts, cascades their embeddings/facts, rebuilds aggregates from retained facts, and restores
  the verified backup on any publication fault. Runtime opening of v3 remains fail-closed.

### Changed
- `recall()` is now read-only: it no longer bumps salience or writes `last_recalled`.
  Reinforcement is available via the explicit `recall_and_reinforce()` method.
- `Embedder.embed()` / `embed_batch()` are now async (the whole retriever/recall chain
  awaits them), preparing for a cloud embedder.
- `get_embedder("auto")` no longer eagerly loads BGE-M3; it always returns the
  deterministic `HashEmbedder`. BGE-M3 remains available via the explicit `"bge"` kind.
- A corrupted `digital_twins` row now raises `MemoryCorruptionError` instead of silently
  returning an empty DigitalTwin.

### Persistence
- Added a schema version + migration mechanism (`schema_meta` table with `schema_version`
  and `schema_checksum`). A fresh database is stamped version 1; a legacy 0.1.0 database
  is migrated in place (adding `source_event_id`); a newer or checksum-mismatched schema
  fails closed with `MemoryCorruptionError`.
- `append_message` (including fact extraction/insert/supersede) is now atomic — a single
  transaction rolls back the message and any partially-written facts on failure.
- Added an optional `source_event_id` idempotency key on messages (partial unique index);
  re-appending the same event returns the existing message id without a duplicate row.

### Deletion & Limits
- Added `delete_session` / `delete_all` / `delete_old_sessions` (cascade delete of
  messages + source facts + workspace actions, with transitive dangling-supersede
  re-pointing and a digital-twin rebuild).
- Added embedding lineage columns (`embedder_kind` / `embedding_dim` /
  `embedding_format_version`) plus a `reindex(embedder)` method that re-embeds every
  message and swaps the active embedder/retriever.
- Added size limits (`max_content_chars` / `max_db_bytes`) raising `MemoryLimitError`.

### Cloud embedding
- Added `CloudEmbedder` (async, batched, LRU-cached, retry-with-backoff, fail-closed)
  and `OpenAICompatibleClient` (httpx `/embeddings`, dimension-validated). Cloud
  embedding has no silent offline fallback — network failure raises `EmbeddingError`,
  so callers choose an explicit degradation (e.g. `HashEmbedder`).
- `get_embedder("cloud", base_url=..., api_key=..., model=..., dim=...)` wires the
  cloud embedder; `api_key` never appears in repr/log/exception.

### Privacy
- Recall and fact-extraction logs no longer emit raw query text or fact key/value
  content; they log lengths/counts only.

### Observability

- Added `memory.recall` / `memory.recall_empty` structured events (query length, hit
  count, per-source contribution) to the hybrid retriever.

### Documentation
- README quickstart restructured so the basic example runs under a plain `pip install -e .`
  (append + recall + facts); world model and BGE-M3 embedding moved to an "optional capabilities"
  section with their exact extras and weight-download prerequisites.
- Documented the default HashEmbedder as a deterministic hash pseudo-vector (not semantic);
  production semantic recall requires the `[embeddings]` extra.

### Tooling
- Added `scripts/verify_quickstart.sh`, a release gate that installs into a clean venv and executes
  the README quickstart block verbatim (no paraphrase), reporting a structured PASS/FAIL.
