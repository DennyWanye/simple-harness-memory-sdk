# Memory operation audit — bounded successor OA1

2026-09-05. Status: design challenge requested; implementation not started.
Base exact `f92fac121d2d9ce195b5715d272023e5aec920e3`. Branch
`feat/human-memory-operation-audit`. No version assignment/build/pin in this slice.
Frozen069/068 and Host/native environments untouched. Main explicitly authorized this separate
slice, including a typed safe observer for pre-DB rejection; no repeated user approval needed.
Execution: one owner, four dependent tasks (contract/oracle, read projection, rejection observer,
focused regression and independent review). Only SDK source/tests/docs owned here.

## Goal and bounded completion

Give Host a public, payload-free account of actual durable Memory operations that do not necessarily
have LLM invocation audits. Provide a typed handoff of actual pre-candidate rejection witnesses to
Host's own durable request/attempt observation, without granting Memory authority or touching Memory
DB before admission. OA1 completion means this bounded public surface is consumable; it never means
all Agent operations are recorded. Host persistence wiring and additional operation families remain
explicit required follow-ups, not permanent waivers. No reconstruction from logger text.

Current public evidence: get_memory_mutation_receipt_view requires an already known receipt;
export_audit_trace pages llm_invocations only; read_outbox projects current outbox state, not every
job transition. Existing internal immutable receipts/events supply the new projection's authority.
We do not invent missing historical start/finish events, deduplicate actual retries into one call,
or label exact product replay as evidence that a new invocation was durably recorded.

## 1. Durable read API

Proposed public Manager method:
```python
async def read_operation_audit(
    *, requester: MemoryPrincipal, target_principal: MemoryPrincipal,
    access_receipt: SealedAuditAccessReceipt,
    limit: int = 100, cursor: OperationAuditCursor | None = None,
    expected: tuple[OperationAuditExpectation, ...] = (),
) -> OperationAuditPage: ...
```

Reuse existing trusted audit authority, SUBJECT grant, exact requester/target identity, expiry,
max_reads and hash-only access-event accounting. Do not create a second authority or let caller
mint a sealed decision. The read is diagnostic/audit only, never Agent context or execution permission.
An audit SUBJECT grant that already allows canonical hash manifests may authorize this narrower
hash-only receipt projection; every successful page consumes one shared read. Denial records remain
in the existing audit-access mechanism. Refactor common authorization transaction code as necessary,
without changing old trace/manifest hash domains or historical receipt bytes. Required challenge:
verify this scope reuse and all shared-budget readers cannot escape counting new reads.

All queries and validators are inside SDK. Host never receives SQL/table selectors, raw rows, prompts,
query text, memory text, target IDs, job payloads, error messages, stack traces, or provider payloads.
Public refs are domain-separated hashes of real source IDs. Metadata permits only fixed family/kind,
verified receipt hash, opaque operation/attempt refs, finite outcome classification and timestamps.
Unknown product reason strings are hashed; no arbitrary text copied to the feed. Hash metadata is
still sealed, including for forgotten sources. One subject per request; cross-subject join checked.

`OperationAuditItemV1`: family, event_kind, event_ref_hash, operation_ref_hash,
attempt_ref_hash|null, occurred_at, outcome (committed/rejected/started/observed/unknown),
receipt_hash, item_hash. Values are rebuilt from actual durable data; an item is never fabricated
from a logger, current jobs.state, or expected receipt supplied by the caller.

`OperationAuditExpectation`: family, event_ref_hash, receipt_hash. Up to100 exact expected facts
captured by Host from genuine operation returns; not authority to manufacture events. Report matched,
missing or mismatched after inspecting the entire bounded snapshot, not just the current page.
A missing expected receipt is an observable gap, never implicitly a PASS or silent empty page.

`OperationAuditPage`: schema_version=1, principal_ref_hash, coverage_version,
snapshot_hash, items, coverage, expectation_results, next_cursor, page_hash, access_event_hash.
`coverage` gives per-family status, actual count and root, supported event kinds, known exclusions,
plus unresolved linkage findings. Pagination completion is named `enumeration_complete`, not
`complete` or `all_operations_recorded`. Global `all_operations_recorded` is always false for OA1.

### Explicit source registry (no user-defined selectors)
| Family | Existing authoritative records | What coverage means / exclusions |
|---|---|---|
| mutation_commit | memory_mutation_receipts | Actual committed receipt, including no_mutation; does not imply every call admission/start exists |
| mutation_rejection | memory_mutation_rejection_audits | Persisted business refusal only; pre-authority type/owner failures may be absent |
| typed_request / typed_attempt | typed_recall_requests / typed_recall_attempts | Actual durable admission and each attempt; no fabricated per-call replay event |
| typed_terminal | typed_recall_terminals + real decision/result binding | completed/rejected/deadline_exceeded; absent terminal is unresolved, never inferred success |
| recall_context_use | recall_context_use_receipts | Actual accepted final-use receipt; rejected final-use calls are not all persisted |
| short_recall | short_horizon_audit actual recall_started/recall/recall_terminal | Preserve real starts/outcomes and unresolved starts; projection/build/cleanup excluded in OA1 |
| suppression | suppression_directives + suppression_targets | Actual directive/revoke with recomputed canonical decision; denied suppress calls are not all persisted |
| job_transition | job_attempt_events + real job/attempt/batch bindings | Actual emitted transition events, not fabricated from mutable job state; pending creation/no-attempt and unsupported transitions explicitly unobserved |

At minimum cross-check typed terminal→attempt/request/decision/result; attempt ordinal continuity;
suppression target binding and revoke→prior directive; job event→batch/member/attempt/request hash.
Required job events are selected from actual producer control paths before coding. A legitimately
in-flight operation is `unresolved`, not automatically corrupt/failed; missing mandatory event for an
already committed phase is `missing_required_event`. Independently retained expected receipts and
checkpoint roots detect deleted/changed known history. No claim to detect simultaneous complete
DB-owner rewriting, or a never-recorded invocation before first trusted observation.

### Stable cursor, reopen and limits

Reuse existing per-database audit HMAC key; no Host cursor signing secret. Cursor binds exact full
requester/target, access receipt identity, registry version, expected-set hash, immutable per-family
snapshot cut/root/count and last position. Global traversal uses fixed family order then stable
internal append position, not a timestamp pretending to be total operation chronology. Each item
exposes source timestamp separately. New appends are outside the cursor cut; same cursor after
close/reopen returns same next data page when grants remain valid. Recheck grant/usage on every
page; audit access_event_hash can change on each read even when data page is identical.

Detect changed/deleted pinned history by recomputing each prefix root/count before emitting data.
Reject forged/wrong-subject/wrong-query cursors; revoked/expired/exhausted grants fail normally.
Host sees an opaque serialized cursor, not private database row IDs or table names. No full persistent
snapshot copy or new producer ledger is required. Empty result still reports every registry family.

Initial bounded implementation retains100-item pages and a finite SDK scan guard at100,000 rows
across covered families. Exceeding guard raises a distinct limit error with no partial page or claim
of coverage; counts never silently truncate. This is a new audit resource bound, not a change to
recall401 cells, semantic thresholds, latest10, five-day window, or source256 bound. Scalability beyond
this bound remains a named next-slice requirement if real data reaches it.

## 2. Typed safe observer for pre-candidate rejection

Expose immutable `MemoryOperationObservationV1` and typed async `MemoryOperationObserver` protocol.
Manager builder accepts optional `operation_observer`; execute_typed_recall accepts optional
`observation_context: MemoryOperationObservationContext` containing opaque Host request/attempt refs.
Pass neither new kw to legacy backend. Actual Manager gate/backend exceptions are observed only at
this outer invocation boundary, once. Operation succeeds/fails according to the existing public
contract regardless of observer availability; no fabricated invocation Run or Memory receipt.

Host persists request/attempt start BEFORE calling Memory and provides corresponding context.
Only an actual existing `TypedRecallRejectionV1` is projected in OA1: schema/version, hash refs,
SDK witness invocation_id hashed, canonical request/context/plan digests where genuinely available,
finite stage/reason, candidate_query_started=false/count0, observed_at, observation_hash.
Never use repr/str of untrusted arbitrary inputs or exceptions; a generic DBfault/cancel without an
actual witness remains outside rejection-receipt coverage. Unsupported integer5 remains protocol
unsupported, string inputs remain type-invalid. No DB access/lease/query/ledger write is added by
this observer, including in before-DB protocol failure. Observer runs outside SQLite transactions.

Await observer delivery before propagating the ORIGINAL product exception, class/code/message and
rejection_receipt unchanged. Observer cannot replace product outcome or alter frozen witness.
If callback fails/cancels/times out, retain the immutable observation on the original exception with
explicit delivery status; do not recursively observe observer errors or log payloads. Bounded delivery
and external cancellation semantics must be pinned in oracle before implementation. Callback success
means `observer_delivered`, not `host_durably_persisted`; only an independently verified Host store
can support the latter claim. Manager configured without observer/context reports this coverage gap.

OA1 does not create a general audit event sink which callers can use to inject Memory facts. Host
observations remain a separate request-attempt journal, linked by observation hash to actual Memory
witness. Their presence never changes typed recall admission, authorization, hashing or idempotency.

## 3. Acceptance (7 MUST, oracle first)

1. Real non-LLM operation fixture produces expected durable families/receipt bindings without relying
   on any LLM invocation record; query returns these exact hash facts and explicit coverage.
2. Mixed pagination stays deterministic under tied/reversed clocks, concurrent later appends, close/
   reopen and cursor replay; no omission/duplication inside pinned snapshot; forgery/subject mismatch deny.
3. Delete/change a known event in a disposable damaged DB or omit a mandated transition in fault-injected
   producer: pinned-root / expected-receipt / cross-link check detects it. Empty and partial coverage are
   truthful; legitimately pending work is unresolved, not synthetic terminal success.
4. Existing audit authority and shared budget apply; forged/expired/foreign grants deny; no payload
   appears even for suppression targets or malicious reason strings. Audit-read observer is nonrecursive.
5. Real pre-DB int5/type-invalid rejection invokes observer exactly once with original finite witness,
   zero SDK SQL trace/lease access. Host callback failure cannot mutate exception or silently claim persisted.
6. A tiny real Host-owned SQLite observation store fixture (separate from SDK DB) persists start then actual
   observed rejection; crash/reopen sees deterministic attempt correlation. Missing Host wiring is explicitly
   uncovered. This is consumer evidence, not production Host integration or a new Memory authority.
7. Existing mutation/recall/suppression/job public behavior and canonical receipts remain unchanged;
   focused adjacent tests/API checks pass. No version/wheel/main change; source review gates candidate.

Follow-up required for user's all-operation goal: production Host start/terminal journaling and
observer outbox/recovery; all remaining operation entry points and nonreceipt exceptional exits;
new invocation exact-replay observations; end-to-end completeness comparisons. None waived by OA1.
