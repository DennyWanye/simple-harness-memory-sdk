# Memory schema v3 → v4 offline migration

Schema v4 remains fresh-only at runtime. `MemoryManager.build()` never upgrades or silently reinterprets a
v3 database; opening v3 still fails with `memory_schema_incompatible`. Upgrade is an explicit, closed-runtime
operation through `simple_harness_memory.migrations`.

The product coordinator supplies three hash-protected inputs:

1. Harness `ExecutionMigrationManifest` using the four dispositions
   `KEEP_COMPLETED_PAIR`, `SUPPRESS_TENTATIVE`, `SUPPRESS_TERMINAL`, `DEFERRED_TURN`;
2. a trusted one-to-one legacy user/session → AgentIdentity map;
3. `NonHarnessProvenanceManifest` for v3 message sources not owned by Harness execution.

Execution and product provenance must assign every v3 `source_event_id` exactly once. Duplicate ownership,
missing ownership, unknown product source, identity ambiguity, unknown manifest version, digest tamper or
row/payload hash mismatch fails closed.

Target session uniqueness and completed-turn receipts are deployment-scoped. Identity maps may therefore
rename two legacy sessions to the same target session string when their target deployments differ; the same
target deployment/session pair remains ambiguous and is rejected.

```python fragment
from simple_harness_memory.migrations import (
    NonHarnessProvenanceEntry,
    NonHarnessProvenanceManifest,
    migrate_v3_to_v4,
)

provenance = NonHarnessProvenanceManifest.create(
    (NonHarnessProvenanceEntry(source_event_id, payload_hash),)
)
receipt = migrate_v3_to_v4(
    "memory.db",
    backup_path="memory.db.v3.backup.db",
    execution_manifest=harness_manifest,
    provenance_manifest=provenance,
    identity_map=legacy_identity_map,
)
```

The migrator first creates and validates an owner-only SQLite backup, builds a separate v4 database, verifies
counts/integrity/FK, then atomically replaces the source. A fault after replacement restores the backup before
returning. The backup is retained for the product-level two-database rollback journal.

Only `KEEP_COMPLETED_PAIR` content is copied; a missing half may be reconstructed only from the manifest's
hash-verified canonical committed turn. The other three dispositions copy neither message, inline embedding,
source facts nor aggregate state, and receive `legacy-source:<event-id>` hash-only suppression receipts.
Recall snapshots are never migrated. Digital twins are rebuilt solely from retained source facts.

`import_execution_manifest(manager, manifest, identity_map)` is the public v4 import API outside
`AgentMemoryPort`. Runtime import accepts complete KEEP pairs only, honors existing erasure state, is atomic and
idempotent, and rejects all suppression/deferred dispositions. A later Harness outbox replay sees the canonical
turn receipt and returns `already_applied` without writing a duplicate pair.
