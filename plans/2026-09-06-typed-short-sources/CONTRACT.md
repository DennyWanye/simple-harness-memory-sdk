# Typed short selected-source public port

2026-09-06. Fixed Memory0612 basec3c59f4210ed5e238a2833c47db62039b6d10300,
isolated feat/typed-short-sources. Repository root has no AGENTS.md; ARCHITECTURE
index and existing short-source/history contracts read. No DDL, SDK archive edits,
private Host SQL, old hash/wire rewrite, model imports or new ledger.

```python
await manager.resolve_typed_short_horizon_sources(
    principal=principal,
    disclosure_context=current_disclosure,
    bindings=(HistoryRecallBinding(result_id, result_hash, item_id, result_item_hash),),
)
```

MemoryManager and MemoryBackendPort expose the method; human SQLite backend provides
implementation. Exact tuple of existing HistoryRecallBinding only, batch1..256.
Standalone HistoryShortHorizonBinding is rejected here. Return existing frozen
ShortHorizonSourceSnapshot/Item/Ref wire shape, with schema_version1 unchanged.
No new audit_id is fabricated and the old resolve_short_horizon_sources is unchanged.

New domains (Host may compute using history_hash/canonical domain+payload):
- memory.typed.short.sources.binding.v1: binding.to_json() (kind remains recall).
- memory.typed.short.sources.request.v1: principal asdict, disclosure.to_json(),
  bindings as ordered list of binding.to_json(), including exact duplicates.
Snapshot hash remains existing memory.short.sources.snapshot.v1; distinct request
and binding domains separate this port from standalone-short observations.

## Same current-visibility transaction

Reuse existing history source preparation and one history SQLite read transaction:
current principal row, one clock, authority epoch/policy, durable typed result JSON
and stored result hash, exact result id/item id/result_item_hash, current source
checker then selected chunk full registration group/source collector. Never read an
independent second snapshot or turn a display view into selection authority.

New port requires exact registered deployment/household/actor even when the row is
(actor,actor,actor), which old S1 history treats as a placeholder. This is current
owner authorization; an original session is not added to a ledger that never stored
it. Existing history/standalone port placeholder compatibility is not changed.
Unknown or wrong bindings return invisible/incomplete with empty refs; wrong registered
owner raises MemoryOwnershipConflict. Source kind must short_horizon BEFORE any
cognitive source expansion. Eligible-but-unselected or cognitive result items do not
expose refs, even if their typed result is genuine. Empty/malformed tuple rejects.

Short chunk proof reuses internal check_selected_chunk after selection is proven:
owned current nonexpired chunk/full hash, complete registered causal group/ordinals,
classification/disclosure, source evidence/entity/MEMORY suppression, canonical group
reconstruction, admission receipt/envelope/source/sanitized hashes and source-only
admission lineage. Source refs are published only after all group members validate.
Corruption fails closed, over-limit lineage is invisible/unverifiable without partial
refs. Duplicate request bindings yield corresponding identical items under one clock.
Historical result selection is provenance, not replay of a prior disclosure grant;
current source expiry/disclosure governs use, Host still checks HistoryRecallBinding
in final policy and verifies returned refs against its complete causal group.

Suppression through same backend waits behind read transaction; one batch cannot mix
pre/post-forget epochs. Later call sees the forget. Cancellation rolls back and returns
no snapshot/partial refs; next read works. Host source preparation remains the existing
operation-local authority primitive, no additional database transaction is invented.

## Delivery boundary

Source-stage tests use main composition venv with PYTHONPATH=src (explicit Memory
source overlay for SDK development only). Host must consume fixed successor wheel,
not overlay. Local refs/tag history contain no0.6.13; proposed successor0.6.13 only
after fixed-source independent review, then two independent offline local builds and
empty ownvenv public consumer/installed byte comparison. No push/tag/release/main
switch. Current source remains version0.6.12 until successor-version commit.
