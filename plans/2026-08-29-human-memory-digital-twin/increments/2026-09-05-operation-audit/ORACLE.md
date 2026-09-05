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

## Native counterexample and price-provenance controls

2026-09-05 main-reported native observation, partial SDK run ref product-sdk-be6f...; full source
receipt identity has not been supplied here. Do not invent it or call this locally rerun evidence.
This case refines AC1/AC3/AC7, rather than changing recall thresholds or rewriting old jobs.

| Producer facts fixed before reader assertions | Required audit interpretation |
|---|---|
| Provider response succeeded; real job applied; canonical closure analysis_all_operations_rejected/no_mutation; actual no cognitive operation committed | Workflow applied; cognitive_effect=no_mutation with actual result/application bindings; zero cognitive-write successes; remember intent not proven satisfied |
| Real nonempty accepted mutation with committed operation and revision/receipt | Workflow and cognitive effect reported separately; written only from actual operation bindings |
| Job applied but result/application/mutation binding unavailable in the selected cut | cognitive_effect=unverified; neither assumed written nor inferred no_mutation from absence |
| Legacy Host reports cost_microunits=0 without a price source | reported cost0 retained, priced cost null, price_provenance=unavailable; no free-call claim or complete priced total |
| Independently bound, explicitly verified zero price (future billing slice control) | Only then may confirmed zero be distinguished from unavailable pricing; not inferred from workflow or token counters |

The decisive SDK fixture must genuinely execute the existing no_mutation analysis path through
DurableMemoryJobRunner to applied and preserve its result/application hashes; do not insert an
applied row, construct reader output, or rewrite an old native job. Pair it with an actual committed
mutation control. SDK source tests may independently check cognitive rows for the counterexample;
Host/public consumer asserts public result and operation receipt bindings. The reported native case
does not replace this deterministic execution test. Price handling is a contract boundary for unified
usage, not a claim that OA1 has implemented billing or independently verified the legacy Host values.

2026-09-05 resumed reader controls (before completion implementation): mixed real producers,
mutation rejection field rebinding despite unchanged hash, applied event foreign-result rebinding
with honestly recomputed event hash, required predecessor deletion, same-cut handoff→reclaim→retry.
No synthetic events or product output fed into expected projections. Typed decisions/results require
separate same-cut support prefixes so a deleted terminal is detected in a fresh snapshot without
letting later results reinterpret an old cursor. Existing independent generic HMAC vectors stay exact.

Additional resource bounds apply only to this new audit reader, not frozen recall/SDK admission:
100,000 covered rows remains; prior whole-backend integrity reuse additionally requires <=100,000
rows across the finite SDK validation catalog and <=64MiB logical database pages (including current
WAL snapshot). A SQLite progress handler limits the whole read transaction to10,000,000 VM steps
with1000-step granularity. Each limit has a distinct MemoryLimitError, no partial page, no consumed
grant on rollback, and progress handler reset before cleanup. These deliberately conservative bounds
may reject a large database even when the requested subject is small; they are finite resource guards,
not latency/P99 guarantees or user-goal completion. Unknown/corrupt inputs retain ordinary rejection.
A larger-data scalable reader remains a named limitation, not silent truncation/second authority.
