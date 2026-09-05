# 0.6.8 source-only admission — bounded source checkpoint

2026-09-05. User approved independent0.6.8 from067; frozen067source/wheel untouched.
Dirac implementation-oracle review ACCEPT e3c2da9, independent stdlib vector SHA
9ab0e0ed0fcb43e5839762a22e7f1199491ebaf8b239f7f6d0db7e160b9f866e.
No provider/model/native UI, no main/push/tag/release. Selected-source public interface remains a separate gap.

## Current implemented contract
MemoryManager.admit_evidence_source(*,principal,envelope,receipt) returns distinct immutable
EvidenceSourceAdmissionReceipt with no job/outbox IDs. Exact S1/current registered owner/live
canonical hashes required. The source transaction adds only envelope/item/link/source receipt rows.
Both admission modes reject the opposite mode on subject+source_ref/evidence_id/Host admission ID;
no promotion or job cleanup. Existing full receipt/hash/default USER analysis flow preserved.
Registration and history reconstruct either actual receipt; full-only mutation span admission unchanged.
Canonical state manifest includes source receipts. Schema7.2 accepts fresh/current roots only;
old7.0/7.1 DBs rejected read-only, including former automatic7.0 migration. This is an explicit
approved candidate limitation. Existing historical7.0 DDL/hash fixture remains byte exact; its current
initialization tests now assert the approved7.2 rejection instead of an obsolete migration expectation.
New .068 root snapshot is old .067 plus EvidenceSourceAdmissionReceipt; old snapshots unchanged.

## Verification completed here
Evidence root: .local-test-evidence/2026-09-05/source-only-068/ (ignored).
- baseline.log:29 prior ingestion/root tests PASS.
- red.log: actual missing public receipt AttributeError before implementation (1FAIL).
- green-r6.log:36 source-only decisive tests PASS, including independent vectors, fresh/replay,
  clock/reopen, eight cross-mode cases, real SQLite no-job/analysis row+SQL write checks,
  four fault points with an independently successful business control and exact post-commit replay,
  three shared-key/two-connection races, old7.0/7.1 read-only reject, full-only mutation rejection
  plus full control, real11-source registration/short selection/source suppress/reopen,
  MEMORY-only forget of original USER propagating to source-only assistant, forged bindings.
- adjacent-r1.log:721 tests PASS in30.91s (36 above plus ingestion/durable jobs/short repository/
  history/short history/schema initialization/audit manifest/clock/rejection/root snapshot).
- schema72.log:4 historical-schema/current fresh-only checks PASS.
- mypy-r2.log:5 changed/intersecting source files PASS; changed-file ruff PASS.
- consumer-preflight-r2.log: real public source consumer8 stages PASS, installed=false;
  synthetic Host assistant authority ->11 source receipts ->1old selected group/newest10excluded,
  queue/executor traps idle, exact receipt after reopen, current suppression/reopen denial.
  This is source execution, not installed-wheel evidence and not the real Host producer.

Public two-manager startup retains real MemoryWriterConflict. Separate source-test-only fixture
releases the first writer lease to exercise two real SQLite connections: exactly one mode wins,
other exact mode conflict, original winner clock/receipt retained and loser creates no job.
This internal transaction-strength evidence is not public concurrent-writer support.

## Reproduction
From this worktree, let PY=.local-test-evidence/2026-09-05/source-only-068/devvenv/bin/python.
`$PY -m pytest tests/integration/test_source_only_admission.py -q`
`$PY -m pytest tests/integration/test_evidence_ingestion_v5.py tests/integration/test_durable_memory_jobs_v5.py tests/integration/test_short_horizon_repository_v5.py tests/integration/test_history_visibility.py tests/integration/test_short_history_visibility.py tests/integration/test_schema_v5_initialization.py tests/integration/test_audit_access_v6.py tests/integration/test_public_recall_clock.py tests/integration/test_public_recall_rejection.py tests/artifact/test_public_api_snapshot.py -q`
Historical-schema/current gate: `$PY -m pytest tests/integration/test_memory_061_schema_v7_1.py -q`.
Do not repeat the whole adjacent set absent a relevant change; these are scope/command records.

## Follow-up delivery facts
Source review ACCEPT, offline build/exact install+full package byte manifest PASS;
Host public-port wiring and actual11groups/11USER worker attempts/0assistant jobs PASS.
The fixed artifact and per-layer evidence are recorded in CANDIDATE-0.6.8.md.
028a27b adds4 same-mode identity conflicts (all PASS), with unchanged production source bytes. Current test-tool/source state is not main/native
integration, S3/program completion or selected-only source visibility. No release artifact frozen yet.
JOURNAL_VERDICT: COMPLETE — bounded SDK source-only candidate built/installed/public-tested;
Host leaf review and main/native integration are separately tracked and not implied.
