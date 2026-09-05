# OA1 independent oracle before implementation

2026-09-05, base f92fac1. Status: scenarios fixed for challenge; SDK implementation absent.
Do not generate expected items from reader output or bless logger lines as operation facts.

- Build real SDK fixtures using public producer APIs and actual receipts. Save expected family and
  receipt hashes from producer returns before invoking the new reader. SDK tests may inspect SQLite
  solely for fault injection/SQL trace assertions; public consumer and Host never do.
- The primary fixture must contain committed mutation/no_mutation, a persisted mutation rejection,
  typed attempt and terminal, short actual recall, suppress+revoke, and real job transition receipts;
  no synthetic inserts to claim operation execution. Exact existing mutation/short/job fixtures can
  supply legal authority setup, but public producer calls must execute in this test.
- For mutable jobs, write a finite event matrix from actual _append_analysis_event call sites;
  pin per-path required persisted events before reader implementation. Claim and final state alone
  cannot manufacture missing historical transition events. Open attempts remain explicitly unresolved.
- Paging fixture uses limit1/2 with known multiset of producer receipt identities; compare full union
  to pre-recorded expected set, not a second reader call. Add a later real operation between pages and
  verify it only appears in a fresh snapshot; reopen old cursor yields same data page.
- Damage only disposable test copies: known receipt deletion/rebinding; job event whose real batch/
  request/attempt disagrees; typed terminal/result mismatch. Either SDK canonical corruption refusal
  or explicit missing-required-event result is the oracle, never empty enumeration_complete.
- Supplied expected nonexistent hash reports missing; mismatched real ref/hash reports mismatch.
  Expected records do not authorize creation or turn absent history into a successful event.
- Sealed access budget at1 allows first page and rejects second (even replay); adequate budget allows
  stable data while access_event_hash changes. Verify all existing readers share the same budget.
- Payload sentinel placed in actual evidence text, query text, target IDs and freeform error text:
  serialized pages/cursors/observer DTOs contain none. ID domain hashes are not plaintext IDs.
- Real protocol int5 and string'5' produce distinct existing reasons; SQLtrace + backend call trap
  assert no invocation of backend for either. Host receives exactly the actual frozen rejection
  projection on the same exception; original exception/rejection_receipt is unchanged. SDK creates
  no task or callback. External cancellation remains CancelledError; Host store errors leave a
  durable started/unresolved attempt, no false completion or Memory receipt.
- Independent consumer store is a separate temporary Host SQLite file. Persist real Host request and
  attempt before SDK dispatch; observe int5 refusal, persist observation keyed by actual witness hash;
  reopen and compare. A killed consumer before observation leaves a detectable started/unresolved
  attempt, never a fabricated refusal or PASS. No SDK imports in the storage helper beyond public DTOs.

Before coding, challenge must settle: sealed subject-scope reuse; immutable cut validation and race
semantics; exact job-event required matrix; synchronous carrier/no-new-task cancellation behavior; finite family/root
hash encoding vectors. Hash encoding uses existing project H(C({domain,payload})) for NEW domains
only. Frozen old receipt/hash algorithms remain exact. Independent literal vector inputs and stdlib
hash generator will be committed before implementation; product output cannot fill oracle values.

Minimal first red: import public OperationAuditPage/MemoryOperationObservationV1 and invoke reader
against a real nonempty fixture: API is absent on f92fac1. This documents missing surface only,
not product behavior coverage. Then test each AC red→green on decisive batches; no401/full-suite rerun.

Challenge-required paging control: real claim → first limit1/2 page with unresolved operation → real
terminal/application phase commit → remaining old pages and reopen old cursor. Their coverage and
pinned roots remain exact old-cut unresolved; a fresh snapshot includes the new terminal. No current
jobs.state or fresh terminal join may change the historical interpretation. Support identity roots
are pinned too; row-count cuts are validated by prefix roots, not exposed SQL IDs.
