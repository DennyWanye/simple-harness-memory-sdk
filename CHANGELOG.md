# Changelog

All notable changes to `simple-harness-memory-sdk` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-08-23

### Observability

- Added optional shared Harness observability sinks and correlation to `MemoryManager` direct
  construction, all builders, and direct Mock/SQLite backends without changing business authority.
- Added privacy-safe structured lifecycle events for recall, committed turns, durable fact jobs and
  restart recovery, including replay, degradation, retry, dead-letter, erasure and lost-lease outcomes.
- Added bounded aggregate `diagnostics_snapshot()` health for recall stages, turn receipts, fact-job
  queues and sink counters. SQLite diagnostics select status/time/error-code aggregates only and never
  query content, payload or embedding columns.

### Packaging

- Promoted `simple-harness-sdk>=0.4,<0.5` to a base dependency so both SDKs consume the same
  import-pure observability envelope; the local sibling path source remains available for development.
- Froze the 0.5.0 public API and candidate metadata identity while retaining the 0.4.0 release record.

## [0.4.0] - 2026-08-22

### Breaking changes

- Fresh schema v4 replaces the earlier runtime schemas. Normal runtime startup never upgrades an old
  database; operators must use the explicit backup-first v3→v4 migration API.
- The public conversation adapter and duplicate Harness DTOs are retired. Consumers pass
  `MemoryManager` directly as the Harness `AgentMemoryPort`.
- Global `delete_all()` mutation is disabled; privacy operations require an explicit trusted principal
  and scope.

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
- Session and committed-turn receipt keys are deployment-scoped, with full household/actor/session/scope
  validation on replay; different deployments may safely reuse external session and turn identifiers.
- Recall captures its erasure fence before embedding/ranking, so timeout/corruption degradation retains the
  delete boundary and stale turns remain `rejected_erased`.
- A committed turn atomically creates one receipt, the user/assistant pair, and a durable fact job.
  The leased worker performs extraction outside the write transaction and atomically applies its
  canonical snapshot with the job acknowledgement; expired claims recover at startup.
- Added principal export, scope deletion, fact forgetting and authorized family projection APIs.
  Deletion advances the erasure epoch before cascading content and prevents late replay/job
  resurrection.
- Froze the Harness-free public `share_fact(MemoryPrincipal, fact_id)` contract: deterministic replay,
  cross-principal ownership conflicts, `projection_of` provenance, and source-forget tombstone cascade;
  `MemoryOwnershipConflict` is exported at package top level for future consumers.
- Added Harness-free `remember_fact` / `read_fact` principal APIs returning exact fact IDs, with canonical
  source-event replay, persisted salience/pinned/tier metadata, ownership isolation, and no-resurrection forget.
- Scoped recall snapshot identity by deployment, including checksum-gated transactional repair of the known
  early-v4 global-key schema, and added portable POSIX/Windows fail-fast writer leases.
- Persisted principal explicit-forget action receipts keyed by deployment/source event, preserving first-result
  replay semantics, ownership/payload conflicts, restart safety, and distinct no-op provenance without content.
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
- Fresh databases are stamped with the exact v4 schema descriptor and checksum; missing, older, newer,
  or checksum-mismatched runtime databases fail closed.
- `append_message` (including fact extraction/insert/supersede) is now atomic — a single
  transaction rolls back the message and any partially-written facts on failure.
- Added an optional `source_event_id` idempotency key on messages (partial unique index);
  re-appending the same event returns the existing message id without a duplicate row.

### Deletion & Limits
- Principal/scope privacy deletion cascades messages, source facts, vectors and pending jobs, repairs
  supersession lineage, and rebuilds the digital twin from retained facts.
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
