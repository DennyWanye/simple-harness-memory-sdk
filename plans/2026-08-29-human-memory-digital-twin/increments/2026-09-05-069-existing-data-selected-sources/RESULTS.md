# 0.6.9 A+B implementation candidate — independent review pending

2026-09-05. Isolated feat/human-memory-069-existing-data-selected-sources. No push/tag/main/native
environment change; frozen068 and earlier wheels untouched. 069 version was not occupied by a
local tag/artifact and is explicitly allocated by the main executor. Old root snapshot JSON stays exact.

## Actual implementation and evidence
- Official async migrations.migrate_human_memory_v7_to_v7_2 explicitly upgrades finite official
  7.0/7.1 catalogs; current7.2 returnsNone after validation; already upgraded returns exact receipt.
  WAL-aware read transaction, exclusive writer lease, SQLite snapshot backup, one atomic allowed DDL
  transaction and marker, preserved initialization/meta/cursor/all old-column rows. Validation clone
  only overlays allowed DDL and checks old-column equality, then runs read-only canonical validators.
- Four real old-wheel routes (.060/.063/.067/actual prior official ALTER) pass preservation and public
  history reopen. Original MEMORY/EVIDENCE/entity forget remains denied; unrelated USER remains visible.
  .060 source3fa5657/60files, .0632f3d738/60files, .067fa6badd/63files match exact installed wheels.
- Actual committed-WAL inputs retain main-only cognitive count0 vs WAL1. Present/missing/stale SHM
  cases pass through SQLite's own read snapshot. Real process death after backup/DDL/beforeCOMMIT
  leaves old state; afterCOMMIT leaves marker+DDL only in WAL and successor initializer reopens it.
  Old installed063 opens precommit state. Migration replay returns exact first receipt and backup bytes.
- Extended old067 fixture has original cognitive/span+analysis application receipt, eleven pending
  USER jobs, eleven registrations/one selected short audit and active+revoked suppression. Successor
  preserves all old data, admits assistant source without a job, admits one new USER/cognitive record,
  runs six pending no_mutation analysis batches once, then idles after reopen. Original init/upgrade
  receipts and backup remain exact despite legitimate changes to the current state root.
- B public resolve_short_horizon_sources shares one current history transaction/clock and exact
  short check; validates real selected audit/attempt, complete canonical registration group and S1
  bindings, current expiry/disclosure/owner/suppression. Returns ordered complete refs without text;
  no partial refs on refusal. Global259 indexed groups do not block one actual selected hit when
  an unrelated indexed source is forgotten. MEMORY-only reverse suppression has an unaffected-hit
  control. This is SDK evidence, not Host/native nextProvider proof.

## Runs (overlapping, not additive totals)
Raw ignored root: `.local-test-evidence/2026-09-05/069-existing-data/`.
- `contract-red.log`: receipt export genuinely absent before implementation; 1FAIL/1PASS.
- `short-contract-red.log`: B DTO genuinely absent before implementation; 1FAIL.
- `ab-decisive-r3.log`:31PASS/5.28s before later MEMORY-only control and final validation refinement.
- `short-memory-r1.log`:1PASS new reverse MEMORY-only selected-source control.
- `adjacent-public-r1.log`:76PASS/5.02s existing history/short/source-only.
- `canonical-extra-r1.log`:5PASS extended canonical validation/old routes.
- `api-r1.log`:4PASS; `mypy-r3.log`:7 source files PASS.
- `source-pre-review.log`:40PASS/5.76s combined A+B/vectors/API (before the later Hostpolicy fix).
- `host-policy-r1.log`:1PASS real custom Host policy reopen + no runtime policy widening.
- `adjacent-r1.log`:494PASS then old v4 rejection directory-inventory assertion fails on SQLite
  readonly empty-WAL/SHM creation; not counted green. Rejection class/code/message/main/mode/mtime
  are unchanged. Dirac subsequently accepted the exact readonly coordination rule; `readonly-contract-green.log`
  has6PASS including class/code/message preservation. Prior red log remains intact.
- `adjacent-rest-r2.log`: unrelated inherited cutover fixture hardcodes version0.6.6/schema7.1;
  .068 baseline source already declares0.6.8/schema7.2. It was not silently edited or claimed PASS.
  Required069 old-root behavior is exercised by actual old wheels above, not that relabeled fixture.

A real implementation bug found by W5 was fixed: closing a rejected writer after its readonly reader
allowed SQLite to checkpoint old WAL, changing main bytes. Hold the reader until writer close instead;
three leftover-backup controls now preserve source and existing WAL bytes exactly. SQLite can still
create an empty WAL/SHM for a previously sidecar-free WAL-mode root during a mode=ro open. No manual
cleanup, immutable/main-only fallback, or test failure deletion is used to hide this fact.

## Remaining gates
Independent source review, committed scoped checks,
two offline identical builds, exact isolated installed public consumer and full package byte/origin
identity manifest. Host selected-source leaf is owned by Popper; Host migration/native actual-data
copy and final conversation E2E are owned by main. No original401/threshold/oracle files changed;
no S3/program/native completion claim. Runner327b remains stopped.

Minimal source command, from this worktree:
```
.local-test-evidence/2026-09-05/069-existing-data/devvenv/bin/python -m pytest -q tests/integration/test_schema_upgrade_v7_2.py tests/integration/test_short_sources.py tests/unit/test_schema_upgrade_contract.py tests/unit/test_short_sources_contract.py tests/artifact/test_public_api_snapshot.py
```
Old fixture generation requires the three exact isolated wheel environments and source archives
listed in ORACLE.md; databases/logs stay ignored. These are actual old API producer fixtures, not
new-code-generated expected migrated output.

Real Host source-policy finding: Popper's source-overlay Host fixture exposed a validation-clone
configuration bug (default SDK filter policies reject legal Host admissions). Fixed validation-only
historical reconstruction without widening real runtime admission; custom-policy SQLite regression
passes. Popper is independently rerunning the actual Host leaf. No installed claim yet.
