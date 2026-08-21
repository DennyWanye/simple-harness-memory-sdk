# Memory schema v3 → v4 migration status

Schema v4 is a fresh-only runtime schema. `MemoryManager.build()` never upgrades, deletes, or silently
reinterprets a v3 database; opening v3 fails with `memory_schema_incompatible`.

The planned offline migrator is intentionally not published yet. The frozen execution manifest decisions
(`KEEP_COMPLETED_PAIR`, `SUPPRESS_TERMINAL`, `DEFERRED_TURN`) cannot uniquely classify early tentative user
events belonging to a continuation that later completes. Guessing would risk either importing tentative
content or dropping part of a committed turn.

Until the manifest contract receives an explicit additional decision and its frozen oracle is updated:

1. Keep the v3 database closed and backed up.
2. Create a separate fresh v4 database for new installations only.
3. Do not copy v3 rows, embeddings, facts, twins, or recall snapshots manually.
4. Do not point a v4 runtime at v3 storage.

This is a deliberate fail-closed boundary, tracked as Program A2 finding `a2-001`.
