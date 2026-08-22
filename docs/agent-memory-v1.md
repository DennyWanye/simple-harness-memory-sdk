# Agent Memory v1 API and ownership

`MemoryManager` is the production `AgentMemoryPort`. A consumer supplies one borrowed manager through
`ConsumerRuntimePorts(memory=memory)`; Harness owns automatic recall, frozen context, committed-turn
delivery and retry. Consumers do not create an adapter or manually call `recall()`/`append_message()` for
the automatic conversation lifecycle.

## Trusted identity and scope

Each production operation is bound to an `AgentIdentity` containing deployment, household, actor and
session. The consumer authentication boundary supplies that identity; model text, ordinary request data,
Memory content and tool output cannot replace it. A session is immutable after its first identity binding.
Session and committed-turn identifiers are scoped by deployment, so separate deployments may safely reuse
the same external session/turn strings. Within one deployment, household/actor/session ownership and scope
must match on replay.

- Personal scope owner is the authenticated actor. Only that actor can read, export, forget or delete it.
- Family scope owner is the authenticated household. Actors in the same household may recall authorized
  family projections; another household cannot.
- `MemoryManager` is borrowed by default. Only a runtime explicitly configured as owner may close it.

## Stable lifecycle and failures

`recall_for_turn()` creates one bounded, hash-addressed recall snapshot. `release_recall()` releases that
same snapshot. `record_committed_turn()` atomically writes one receipt, the committed user/assistant pair
and an optional durable fact job. Replaying the same canonical turn returns `already_applied`; reusing an
identifier with a different canonical payload raises `memory_idempotency_conflict`.

Recall failure may degrade a turn to empty Memory context. A committed response is not rolled back when
Memory delivery fails: Harness retries its durable outbox and Memory deduplicates by turn receipt. Erasure
epochs and write fences reject late recall, outbox and fact-worker replay with `rejected_erased` rather than
resurrecting deleted content.

The backend reads and exposes the personal erasure fence before embedding or ranking. An embedding timeout
or corruption path therefore retains the fence, and a deletion crossing that work boundary invalidates the
older turn rather than allowing a fence-less write.

Important stable configuration failures include:

| Code | Meaning |
|---|---|
| `harness_integration_extra_required` | The optional `[harness]` dependency is absent. |
| `memory_schema_incompatible` | Runtime storage is not an exact fresh-v4 database. |
| `memory_ownership_conflict` | A session or durable record is bound to another identity. |
| `memory_second_writer_rejected` | Another live manager owns the SQLite writer lease. |
| `memory_production_embedder_required` | Production mode lacks pinned local/remote embedding resources. |

The explicit offline migration and runtime manifest-import APIs remain in
`simple_harness_memory.migrations`; they are deliberately not members of `AgentMemoryPort`.

## SDK-only authorized family sharing

`await MemoryManager.share_fact(principal: MemoryPrincipal, fact_id: int) -> str` is a standalone
public API and does not require Harness. `MemoryPrincipal` must come from the consumer's trusted identity
boundary. The source must be that actor's personal fact in the same deployment and household; otherwise
the method raises the top-level public `MemoryOwnershipConflict` with code
`memory_ownership_conflict`.

The returned family projection ID is deterministic from source provenance and household. Replaying the
same call returns the same ID without another row, and the family row records `projection_of`. Forgetting
the personal source cascades to its projections and keeps the source tombstone, so a late fact-job replay
cannot recreate either record. Sharing is intentionally outside `AgentMemoryPort`; model content cannot
select or authorize a family scope.

## SDK-only explicit fact write/read

`await MemoryManager.remember_fact(principal, content, *, source_event_id, payload_hash=None,
salience=0.5, pinned=False, tier="auto") -> int` returns the exact durable fact ID consumed by
`await MemoryManager.read_fact(principal, fact_id) -> Fact | None`. The complete deployment/household/
actor identity and all visible metadata participate in the canonical idempotency hash. `tier` is one of
`auto|working|long_term|identity`, mapped to `explicit|event|learning|profile`. Forget preserves the
receipt, so exact replay returns the original ID without resurrecting content. These APIs are also outside
`AgentMemoryPort` and require no Harness import.

## Consumer migration map

| Previous consumer responsibility | Official path |
|---|---|
| `MemoryQueryPort` / manual prepare | Harness calls `MemoryManager.recall_for_turn()` and freezes the result. |
| `MemoryWritePort` / manual append | Harness terminal commit creates a durable outbox intent; Memory records the pair. |
| Public conversation Adapter | Pass `MemoryManager` directly as `ConsumerRuntimePorts.memory`. |
| Product-owned retry/idempotency | Harness outbox retries; Memory turn receipts deduplicate and detect conflicts. |
| Runtime opening an old database | Stop runtimes and invoke the explicit backup-first migration coordinator. |
