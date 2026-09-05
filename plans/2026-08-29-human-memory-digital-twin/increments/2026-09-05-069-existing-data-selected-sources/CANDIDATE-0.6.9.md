# Memory 0.6.9 isolated candidate

2026-09-05. No main merge, push, tag, release, Host/native environment installation, or frozen
0.6.8/earlier artifact overwrite. A+B source review2542736 scoped ACCEPT; follow-up f92fac1 fixes
reviewed P2 transient SQLite read-lock classification. This is not S3/program/native completion.

## Fixed identities
- Source: `f92fac121d2d9ce195b5715d272023e5aec920e3`.
- Wheel: `.local-test-evidence/2026-09-05/069-existing-data/build1/simple_harness_memory_sdk-0.6.9-py3-none-any.whl`.
- Wheel SHA256: `cf14902223063ba3586032553c3737d0ee0c13311df3e29bd4561629494d6719`.
- Harness0.7.2 source: `2b8428465cbd41032ba024a0b7199183161f5ecd`; wheel SHA256:
  `53bded3fea87168e5d2ad9e49fea5f99e1c1edb1d6077b2a52dd62716692f9ed`.
- Identity manifest: `.local-test-evidence/2026-09-05/069-existing-data/combination-manifest.json`;
  SHA256 `2c83263971068897038d3196cc7b433cf47700554b6c2b68b1a83fe337de0b8f`.
  Memory68 and Harness151 complete package files match committed source, wheel, installed bytes;
 209 imported runtime modules belong to the new isolated environment. Optional Harness testing
 plugin not runtime-imported; its package bytes are included. All previous JSON API snapshots match.
- `direct_url.json` confirms exact local wheels; uv leaves archive_info empty, so no invented
 installer hash receipt. Explicit --require-hashes and complete byte comparison supply identity.

## Validation, not additive totals
- Fixed2542736 scoped source41PASS/6.17s; BUSY follow-up16PASS/9deselected/12.98s and mypy1sourcePASS.
- Two offline hatchling1.32.0 builds with SOURCE_DATE_EPOCH=315532800 are byte-identical.
- `installed-public/result.json`:4 real public consumer stages PASS, installed=true, isolated -I
 and no PYTHONPATH/PYTHONHOME. Actual old .063/.067 nonempty WAL inputs upgrade; original forgotten
 USER evidence stays denied and unrelated USER stays visible; source-only adds no outbox/job;
 clock and protocol rejection witness remain; actual old short selection resolves full sources,
 forged carrier and later source forget/reopen deny; valid fresh7.2 returnsNone without backup.
- The same upgraded path closes/reopens twice and exact-replays original upgrade receipt;
 original backup SHA remains identical. No source private SQL/imports in installed consumer.
- `pip-check.log`:16 installed distributions compatible. `identity-check.log`: full identity PASS.
- Popper Host19 source-overlay PASS is separate from installed proof. Actual Host installed leaf,
 existing native data COPY and native outbound forgetting still require main/Popper verification.
- A real memory-only selected-source reverse-suppression control is in source tests; installed
 consumer separately checks the actual old selected source suppression path. Do not conflate them.

## Host entry points and lifetime
```python
from simple_harness_memory.migrations import migrate_human_memory_v7_to_v7_2

# Before first lazy builder; no live old manager. Missing path stays builder-owned.
if db_path.exists():
    schema_upgrade_receipt = await migrate_human_memory_v7_to_v7_2(
        db_path,
        backup_path=db_path.with_name(db_path.name + ".pre-schema-7.2.backup"),
        # Optional expected_initialization_receipt_hash from a previously trusted receipt.
    )
manager = await build_human_memory_v7(db_path, **host_authorities_and_policies)
```
Async migration returns HumanMemorySchemaUpgradeReceipt | None. Old finite7.0/7.1 upgrades return
receipt; marker-upgraded7.2 returns the original receipt even after legitimate data changes or
backup relocation. Valid fresh7.2 fully validates then returnsNone without creating backup.
Unknown/future/corrupt catalogs reject; temporary SQLite BUSY/LOCKED is MemoryWriterConflict,
not LEGACY_SCHEMA_UNSUPPORTED. Preserve actual Host filter/classification/authority configuration
on builder: migration validates historical bindings without widening the runtime policy allowlist.

`await manager.resolve_short_horizon_sources(principal=..., disclosure_context=...,
bindings=(HistoryShortHorizonBinding(audit_id, chunk_ref, content_hash), ...))` observes actual
selected complete S1/registration source refs in one snapshot. Host verifies full real terminal/USER
lineage and performs its outbound fence. A source projection is not a new execution authorization.

## Minimal rerun (from this worktree)
Use a fresh output name; consumer refuses to overwrite a previous run directory. Actual old input
DTO/rows were captured by each pinned OLD installed producer before successor migration.
```
env -u PYTHONPATH -u PYTHONHOME .local-test-evidence/2026-09-05/069-existing-data/venv/bin/python -I scripts/existing_data_public_consumer.py .local-test-evidence/2026-09-05/069-existing-data/installed-public-rerun .local-test-evidence/2026-09-05/069-existing-data/consumer-old063 .local-test-evidence/2026-09-05/069-existing-data/consumer-old067
```
Build/install commands (new directories/environments if reproducing; do not overwrite frozen files):
```
SOURCE_DATE_EPOCH=315532800 .local-test-evidence/2026-09-05/069-existing-data/devvenv/bin/python -m hatchling build -t wheel -d <new-build-dir>
uv pip install --offline --no-sources --no-deps --require-hashes --python <clean-venv>/bin/python -r .local-test-evidence/2026-09-05/069-existing-data/exact-wheels.txt
uv pip check --python <clean-venv>/bin/python
```
Runtime dependency set: ignored `runtime-dependencies.txt`; full identity checker and raw evidence
are ignored. Source old-wheel producer and public consumer scripts are committed for review.
Inherited version0.6.6/schema7.1 cutover test is stale and not claimed green; no full-suite claim.
No newly requested cross-operation audit capability is included in this frozen candidate.
