# Proposed0.6.9: existing-data schema upgrade + exact selected short sources

2026-09-05. DESIGN ONLY; no SDK/Host implementation, version edit or wheel build.
User authorized this necessary follow-up direction without another user confirmation. Independent
contract review must precede changes to known-schema acceptance/rejection. Base is frozen0.6.8
source5e8397b; wheel98a9c788 and all prior candidates stay byte-identical. The two increments can
share a successor0.6.9 artifact after separate decisive tests/review and one installed combination.
This proposal does not assert either feature already exists or currently accepts old databases.

Prior delivery: SDK5e8397b source ACCEPT; Host55b9e402 source ACCEPT;17 bounded Host tests PASS,
11 actual USER no_mutation analyses APPLIED and11assistant source-only admissions/0assistant jobs.
Final documentation heads: SDK84e8265; Host2779d0f8. No main/native production activation.

## Facts requiring a successor
- Current .068 schema7.2 has source_admission_receipts. Its read-only probe requires current table
  inventory and checksum; InitializationReceipt constructor also accepts only the current checksum.
  Simply adding a table or rewriting schema_meta cannot make an old root legitimately valid.
- Known7.0 lacks evidence_envelopes.analysis_lineage_json.7.1 has it; .063/.067 are7.1 roots.
  The previous7.0->7.1 implementation rewrote initialization/meta receipt hashes. Do not reuse that
  rewrite for this preservation contract.
- .067/.068 exact short history check already verifies real audit+attempt, selected membership,
  content hash, current chunk, complete ordered registration group, source binding, classification,
  expiry, suppression and terminal races. It internally reads exact evidence/registration links;
  those complete links are not available on a public selected-hit source result.

## A. Explicit official schema upgrade; preserve existing memory

Proposed public namespace: simple_harness_memory.migrations (existing official migration surface).
One operation; no automatic upgrade from normal builder/open and no Host SQL migration:

```python
async def migrate_human_memory_v7_to_v7_2(
    db_path: str | Path, *, backup_path: str | Path,
    expected_initialization_receipt_hash: str | None = None,
) -> HumanMemorySchemaUpgradeReceipt: ...
```

The optional expected hash is a caller compare-and-swap constraint, not a substitute for SDK
verification. SDK always verifies the complete actual source identity. No principal/Run/authority
fabrication: this is an offline database-schema operation preserving every subject, not Agent action
permission. The Host must close its Memory runtime; SDK obtains the existing exclusive writer lease.
No SDK worker/provider runs during migration. Old pending/claimed/retry jobs may exist, but no live
writer may own the root. Old .068 builder continues rejecting old roots until an explicitly supported
successor opens a root with the exact validated upgrade marker.

### Allowed transformation (strict finite allowlist)
1. Read-only preflight validates a known official7.0/7.1 catalog, exact pinned old checksum, complete
   original initialization receipt/meta/cursor authority binding, SQLite integrity/FKs and canonical
   evidence/cognitive/suppression/job/outbox/replay ledgers. Labels or table names alone are insufficient.
   Unknown/future/tampered/partial schemas fail before writable open, backup or mutation. No generic
   'checksum ignored' branch. Source validation must not depend on a future classification callback
   to manufacture acceptance; validate recorded canonical authority facts and original hashes.
2. Acquire writer lease and BEGIN IMMEDIATE, revalidate identity/current snapshot before any DDL
   or row writes. A WAL-aware pinned read connection for that quiescent pre-upgrade state supplies
   the SQLite backup; independently verify its contents. A new backup path is exclusive-create;
   a pre-existing path follows the exact-retry rules below, never overwrite. Reject live writer or
   stale expected identity. Do not copy/rebuild selected records into an empty database.
3. In one BEGIN IMMEDIATE transaction,7.1 adds the exact frozen .068 source receipt table/indexes/
   immutability triggers.7.0 additionally uses the exact existing official declaration
   ADD COLUMN analysis_lineage_json BLOB (implicit NULL, no explicit DEFAULT NULL). Do not
   backfill lineage, alter old rows, rename IDs, resanitize envelopes, update old receipt hashes,
   delete/complete/reschedule jobs or outbox, rotate cursor authority, or materialize cognitive data.
4. Add exactly one versioned upgrade marker in the existing schema_meta table (new key proposed
   source_admission_upgrade_v1); leave EVERY pre-existing meta key/value and initialization row
   unchanged. This avoids introducing another authority/ledger or changing frozen7.2 table DDL.
   Marker is insert-once through the official migrator; replay must verify the existing marker and
   schema, not overwrite it. Additional unknown meta keys still reject. Review must verify this
   narrow marker shape rather than accepting arbitrary migration metadata.
5. Verify target catalog and canonical data preservation before COMMIT. The new initializer treats
   (known historical initialization receipt + exact validated marker + exact target catalog) as the
   sole upgraded-root route. It returns the original initialization receipt with unchanged bytes/hash;
   effective schema7.2 is represented by the upgrade receipt/validated schema state, not a rewritten
   historical initialization receipt. InitializationReceipt may represent a finite set of verified
   historical checksum DTOs; database acceptance still requires full catalog/marker verification.
   Fresh .068/.0697.2 roots without a marker remain valid. A fake marker on an unupgraded catalog,
   missing marker on an old root, duplicate/unknown marker, unknown checksum or bad binding rejects.

### WAL-aware snapshot and finite catalog routes (Dirac P1 correction)
The .068 `_probe_existing_read_only` uses `mode=ro&immutable=1` and deliberately ignores WAL.
That optimization cannot decide complete old-data preservation, upgrade-marker existence, or
post-upgrade reopen. Successor migration AND normal initializer must instead use a WAL-aware
SQLite read transaction (`mode=ro`, no immutable flag; query_only, explicit BEGIN), so catalog,
initialization/marker, canonical rows and pending work are all from one committed snapshot.
Do not independently read main-file metadata then attach newer WAL business rows. Do not treat
an empty/stale main-file catalog as a fresh root while a committed WAL may contain the real root.

SQLite reads/reconstructs its own WAL index; SHM is coordination data, not a canonical authority.
No Host-side WAL parsing, main-only fallback, manual deletion/truncation/checkpoint to make a probe
pass, or read/write recovery of an unvalidated source. If SQLite cannot obtain a safe read-only
snapshot, return explicit snapshot-unavailable/busy rather than classify a valid WAL root as old,
corrupt or fresh. Rejection preserves main/WAL bytes and logical rows; a SQLite-managed SHM index
is not evidence that source data was migrated. A readable missing/stale-SHM fixture must exercise
SQLite's supported WAL-aware path; an actually unsupported read-only recovery is explicit BLOCKED,
not permission to ignore WAL. Supported platform behavior must be established before implementation
is called complete.

After the lease/BEGIN IMMEDIATE fence, compare the pinned pre-upgrade state again. Run SQLite backup
from a WAL-aware read snapshot of that same state; verify its canonical old-column roots, original
receipts and integrity against the source before schema changes. The backup must include ALL committed
WAL pages. Never copy only the main DB file. All original data and marker verification after COMMIT,
ACK loss and normal reopen uses this same WAL-aware initializer route. Successful checkpoint is not
an acceptance prerequisite: a committed marker/DDL still solely in WAL is a committed upgraded root.
Uncommitted WAL frames are not a marker; SQLite determines the committed boundary.

Freeze a finite physical-catalog fixture map before coding, including actual sqlite_master SQL,
PRAGMA table_xinfo/defaults, indexes/FKs and trigger definitions for supported SQLite versions:

| Source catalog | Known column state | Allowed target transform |
|---|---|---|
| Official fresh7.0 | No analysis_lineage_json | Official ADD COLUMN ... BLOB (implicit NULL) plus source receipt DDL |
| Official fresh7.1 (.063/.067) | BLOB, dflt_value absent, declared by fresh DDL | Source receipt DDL only |
| Official7.0->7.1 migration | BLOB, dflt_value absent, appended by former official ALTER | Source receipt DDL only; preserve its existing initialization receipt |
| Each above already upgraded | Exact corresponding appended catalog + validated marker | Exact replay, no catalog rewrite |
| Fresh frozen .0687.2 | Exact frozen DDL, no marker | Existing valid fresh-root route, no migration needed |

Target logical schema checksum alone is not a physical catalog verifier. The new marker binds
source_catalog_id/target_catalog_id from this finite map plus exact added_ddl_hash. Known fresh and
known appended SQL representations may differ; never normalize arbitrary SQL/defaults into an
allowlisted shape, rebuild tables to resemble fresh DDL, or accept a label/checksum without matching
its catalog. The earlier proposal's explicit DEFAULT NULL was not implemented; it is corrected to
existing official BLOB with implicit NULL to avoid creating an unnecessary new default variant.
An unlisted explicit-default/custom/future shape remains rejected until separately reviewed.

### Preservation hash lifetime and backup exact retry
`preserved_old_columns_root_hash` attests the HISTORICAL migration boundary. Compare source vs
backup and pre-upgrade vs post-DDL old-column projections inside the fenced migration. It includes
all pre-existing columns/rows/meta entries and excludes only the precisely authorized added column,
new source table and marker. Store the first successful equality hash in the immutable receipt.
After commit, normal job progress, cognitive writes, suppression or source admission may legitimately
change current rows. Reopen/repeated migrate validate original initialization identity, catalog and
marker hash/bindings plus current canonical integrity; they MUST NOT compare the current database
root to that historical preservation hash. No periodic rollback to the old snapshot is authorized.

Before commit, a prior crash can leave a backup file but no marker. Retry does not trust its name:
under the same writer fence, independently validate the existing backup's complete known catalog,
original initialization/cursor identity, SQLite integrity and complete old-column canonical roots
against the CURRENT pre-upgrade snapshot. If all match, reuse those exact bytes and bind their actual
SHA256 in the committed receipt. Never recreate/overwrite the backup. Partial/corrupt backup, different
identity or intervening source data changes produce an explicit backup conflict with source and
backup unchanged; caller may supply a different unused backup path. No new preparation ledger or
fictional previous-success receipt is needed. Exact match, not merely matching initialization ID,
is required. After a committed marker exists, exact replay returns that original receipt without
creating/replacing a backup. Its backup hash is a historical backup fact; normal reopen does not
require the external backup still to be at its original location, and replay must not assert a
missing/moved/changed backup has just been verified. Restore always separately verifies backup bytes.

### New upgrade receipt/marker (freeze independent vectors before implementation)
Fields: protocol='memory.schema.source-admission-upgrade.v1', receipt_id,
source_schema_checksum, target_schema_checksum, source_catalog_id, target_catalog_id,
original_initialization_receipt_id,
original_initialization_receipt_hash, added_ddl_hash, preserved_old_columns_root_hash,
backup_sha256, committed_at, receipt_hash. ID binds original initialization receipt+source/target
checksums under a new versioned ID domain. Receipt hash is H(C({domain,payload})), C sorted UTF8 JSON,
not NUL; original initialization and business receipt algorithms stay unchanged. The marker contains
this exact receipt. Backup location is an operational output, not database identity. First committed
clock/receipt remains fixed. Exact repeated upgrade returns it without changing data/creating a new
backup; changed expected identity or marker conflicts. After COMMIT/ACK loss, replay returns the
committed marker, never rewrites old/new state by choice. Before commit, failure rolls back DDL and
marker; source remains an independently readable old root with its old wheel. Recovery must never
claim old-reader downgrade support after migration: the verified backup is the old-version fallback.

Important hash distinction: all EXISTING stored object canonical hashes, cognitive IDs, evidence,
mutation/recall/analysis receipts, initialization receipt and suppression facts remain exact. New
whole-database schema/manifest hashes necessarily differ. For7.0, a freshly exported table root may
also reflect the added NULL column; compare OLD-column canonical projections, not promise identical
new-schema manifest hashes.7.1 old table projections remain unchanged; the new source receipt root
starts empty. No historical audit/manifest receipt is rewritten to pretend the new schema is old.

### A acceptance oracle
- **W1 nonempty committed WAL control:** real old public SDK commits cognitive data, suppression
  and pending jobs/outbox into WAL with autocheckpoint disabled; prove main-only reads omit at least
  one committed business fact, while the real WAL-aware old public control sees all expected facts.
  Leave committed WAL across process termination without cleanup/checkpoint. Official migration and
  verified backup must preserve the complete WAL-visible state, then reopen with unchanged IDs,
  old receipt bytes and suppression decisions. Do not use the main-only view as the oracle.
- **W2 upgrade commit before checkpoint control:** with complete no-fault business assertions already
  green, inject process death immediately after migration COMMIT and before checkpoint/ACK, leaving
  valid marker/DDL in committed WAL while main still has the old catalog. New initializer must open
  the upgraded root and repeated migration must return the exact committed first receipt. No manual
  WAL cleanup or mandatory checkpoint. Compare to pre-COMMIT death: no committed marker, old root
  remains valid and retry follows verified backup reuse/conflict. These are separate required cases.
- **W3 catalog variants:** instantiate every finite source route above using its actual official
  fresh/migration producer; assert exact default metadata and SQL/catalog identity before/after.
  Explicit DEFAULT NULL/custom extra columns/triggers are negative controls, not silently normalized.
- **W4 historical root:** migrate successfully, then perform real new source admission, a permitted
  cognitive update, suppression and pending-job progress; reopen/replay upgrade still succeeds with
  the original marker/receipt even though the current root differs. New integrity corruption rejects.
- **W5 backup retry:** verified backup + precommit failure -> exact retry reuses its bytes; partial
  backup, different database, or same initialization identity with changed business state -> explicit
  conflict/no overwrite. Committed-marker replay remains exact independently of a moved backup;
  no claim of current backup validity. Original/source/backup bytes and outcomes are asserted.
- Complete nonempty old fixtures generated with the exact corresponding official old public SDK
  source/wheel (at least7.0, .0637.1, .0677.1), not a current empty DB relabeled with old metadata.
  Include principal identity, original S1/full receipts, nonempty cognitive IDs/revisions/evidence
  spans, active MEMORY-only/EVIDENCE/entity suppression and applicable revocations, pending jobs,
  pending outbox, existing exact replay/analysis receipts, and applicable short registrations/audits.
  Record original known expected business assertions and old-column canonical roots BEFORE migration.
  If a historical fixture capability truly did not exist, mark that version's inapplicability explicitly;
  other versions still cover the complete required state. Missing fixture is BLOCKED, not synthetic PASS.
- Old public read/recall shows unaffected memory and denies forgotten original USER/linked assistant;
  after upgrade, same IDs/content/receipt bytes and denials remain, old replay is exact, pending work
  resumes once through actual executor/delivery authority, with no migration-time attempt increments.
  Reopen preserves all facts. A new assistant source admission/registration creates zero new jobs.
- Known fresh .0687.2 and repeated upgrade are controls; dual mode conflicts remain EXACTLY unchanged.
  Old full-ingested assistant jobs are retained, not converted/deleted. This migration does not cure
  previously enqueued invalid Host jobs or authorize source-only replay of a full-mode identity.
- Unknown/future checksum, altered schema/trigger/column, corrupt canonical row/receipt/cursor binding,
  partial marker/table, busy writer, stale expected identity and reused conflicting marker all reject;
  rejected root/main/WAL bytes and old row states unchanged, no worker/provider calls.
- Faults after backup, after ALTER/create-table, after marker, before COMMIT: rollback with old public
  no-fault control still usable. Commit-ACK loss: exact durable upgrade receipt; crash/reopen/retry
  never erases pending work or changes IDs. No-fault control must first satisfy business assertions.

## B. Exact selected-hit source projection; stop global all-roots blocking

Proposed root public facade:

```python
async def MemoryManager.resolve_short_horizon_sources(
    self, *, principal: MemoryPrincipal, disclosure_context: DisclosureContext,
    bindings: tuple[HistoryShortHorizonBinding, ...],
) -> ShortHorizonSourceSnapshot: ...
```

Input is the real (audit_id,chunk_ref,content_hash) triple; no query rerun, text matching, fabricated
new Run or typed result binding. The current actual Host UI/provider request supplies disclosure.
One trusted-clock read and one database snapshot covers the whole requested batch. Reuse/refactor
existing exact short validation into a shared internal function; do not reimplement typed recall or
copy chunk hashing/group logic into Host. Existing check_history_visibility outcomes/reasons and
.067/.068 carriers remain unchanged. A source list is an observation, never a renewed execution grant.

Snapshot fields: schema_version=1, subject, request_hash (full principal/current disclosure/ordered
triples), evaluated_at, authority_epoch, policy_hash, valid_until, items, snapshot_hash.
Each item: binding_hash, visible, reason, complete, source_refs. Visible items contain the entire
ordered canonical group; source ref fields are evidence_id,envelope_hash,source_ref,source_hash,
sanitized_hash,admission_receipt_id,admission_receipt_hash,registration_id,registration_hash,
item_ordinal,role. These are source identities/provenance metadata, not raw text or Agent display data.
New snapshot/ref hashes use separately frozen versioned domains; old audit/chunk/result hashes unchanged.

SDK verifies actual terminal selection membership and reconstructs canonical group/envelope/receipt
bindings (either real full or source-only receipt) before returning refs. Subject/ownership/disclosure/
expiry/current source+entity+reverse MEMORY suppression all use SDK's existing authority. Invalid,
unselected, expired, suppressed, incomplete or corrupt bindings never return a partial usable source
list. Denied result has complete=false and empty refs; existing exact denial or corruption semantics
are retained. No 'cell/hash differs' substitute for a real gate. The complete refs must agree with all
source registrations in the validated group, not just any individually valid member.

Host consumes refs only for the actual selected hits, resolves exact immutable S1 from its own store,
and follows actual evidence_refs to original USER/terminal ancestors using existing Host source proofs.
Then it uses existing public check_history_visibility for those exact short+evidence bindings and its
existing final outbound fence. It never reads SDK SQL or infers sources from similar text/chunk IDs.
Absent Host proof drops only that hit; ordinary non-memory history keeps its established behavior.
Unrelated indexed roots no longer enter the guard. Missing proof must not be relabeled as an unrelated
source; partial proofs never authorize output. Returning direct refs alone does not certify cold Host
terminal ancestry: the subsequent verified S1 history check is required.

Keep existing limits (256 history bindings/4096 lineage work, original retention/latest10/budget).
Global index may exceed256 roots while a selected two-message group and its few ancestors fit normally.
A genuinely oversized selected lineage remains failclosed for that hit; no truncation, threshold
increase or use of mixed epochs as one snapshot. If batches are needed, retain complete per-hit groups
and enforce common current policy/expiry at the existing final check. The source snapshot cannot
promise immunity to arbitrary future policy changes after observation.

### B acceptance oracle
- Real production11+complete groups/actual audit selection: public refs equal exactly selected group
  registered sources, in actual order, complete S1/metadata binding. Recent10 excluded, no extra roots.
- More than256 indexed roots with a small selected group: unrelated forgotten evidence/memory/root
  does NOT block that independent hit. Forget selected USER, assistant, terminal ancestor, reverse
  MEMORY or entity: actual nextProvider guard denies selected content; unaffected selected hit and
  ordinary non-memory conversation stay readable. Do not rely solely on history terminal rendering.
- Wrong/unselected triple, wrong subject/disclosure, expired chunk, missing/duplicate/changed group
  member, receipt or source hash, lost audit terminal race: real deny and no partial usable refs.
- Reopen/exact old audit and migrated old databases behave identically; policy epoch/expiry change
  between source observation and outbound check invalidates stale permission. Host missing public
  source port is unavailable with no allroots or private-SQL fallback disguised as selected-only.

## Combination and order
First A contract challenge+old complete fixture RED; implement only official SDK upgrade/initializer
compatibility and decisive fault/replay controls. Separately freeze B DTO vectors+selection-source
oracle and implement read-only projection/shared validation. Keep commits independent; then a single
clean .069 candidate can include both without changing .068 bytes. Final installed combination:
old nonempty .063/.067 DB -> public upgrade -> exact old cognitive/forget/jobs+reopen -> new source-only
assistant registration -> actual selected-source refs -> Host exact-source guard/nextProvider denial
and unrelated-hit allow. Main production cutover waits for this full old-data path, not a fresh-only
SDK smoke. No build/version allocation in this plan-only checkpoint; user approval is already carried
forward, and independent review handles routine contract correctness without another user confirmation.

## 2026-09-05 contract challenge follow-up
Dirac found a P1 in024cb4c: immutable main-only probing cannot validate committed WAL or discover
an uncheckpointed committed migration marker. This revision corrects the PLAN ONLY and freezes W1/W2
before implementation, plus catalog variants, historical-root lifetime and backup-retry controls.
No .068 source/wheel, SDK rejection behavior, Host code, version or product test execution changed.
Follow-up independent contract review is pending; this entry is not an implementation ACCEPT.
