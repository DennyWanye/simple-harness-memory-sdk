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

### Execution outcome is separate from cognitive effect and price

An `applied` job event proves completion of the analysis application workflow, not creation or
correction of a cognitive memory. `mutation_audit_committed` likewise means audit material was
committed, not necessarily a cognitive write. Any derived business summary must expose a separate
`cognitive_effect` of `written`, `no_mutation`, `unverified`, or `not_applicable`, with its actual
same-cut result/application/mutation receipt hash bindings. `written` requires a verified committed
mutation operation/revision; a successful provider response, job state, or assistant claim is
insufficient. `no_mutation` requires the canonical no-mutation result/application binding; absence
of a mutation receipt alone is `unverified`, never proof of zero writes. Do not infer intent success
from accepted analysis validation: a valid no-mutation closure can fail the user's remember intent.

Main reported a real native remember run (partial SDK run ref `product-sdk-be6f...`): provider
response succeeded and job applied, but closure was `analysis_all_operations_rejected/no_mutation`
and no cognitive memory was added. Preserve the facts independently: workflow applied, cognitive
effect no_mutation when bound, remember intent unsatisfied. Do not rewrite the old job or use the
main executor's separate CREATE empty-field v3 repair to relabel this historical outcome. This is
a reported native counterexample, not an independently rerun native result of OA1.

OA1 does not add unified billing. Any later usage projection MUST distinguish the stored value
from priced/billed truth. The legacy HostMemoryAnalysisExecutor `cost_microunits=0` is a placeholder
without price provenance: retain reported_cost_microunits=0 if exposing the historical field,
but priced_cost_microunits=null and price_provenance=unavailable. Never render it as confirmed free,
sum it as known zero, or make a fully priced total from incomplete entries. A verified zero price
requires independent price/billing provenance bound to the actual usage/invocation. Existing token
usage, workflow status and cognitive effect do not supply that missing price evidence. Do not
modify old invocation hashes/records to add invented provenance.

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
snapshot cut/root/count and last position. A cut exposes only per-family count/root, never SQL
row IDs/names. Internal append ordering selects the first pinned count; cursor item positions are
registry/ordinal positions. Changed prefix or a deletion filled by later appended rows fails its root. Global traversal uses fixed family order then stable
internal append position, not a timestamp pretending to be total operation chronology. Each item
exposes source timestamp separately. New appends are outside the cursor cut; same cursor after
close/reopen returns same next data page when grants remain valid. Recheck grant/usage on every
page; audit access_event_hash can change on each read even when data page is identical.

All coverage, linkage and required-event conclusions are AS-OF that same first cut, derived only
from immutable phase witnesses at/below it. Never use fresh mutable jobs.state/batch.state or later
terminal rows to reinterpret an old page. Mutable lease/result columns are excluded from pinned
link projections; immutable job identity/batch member bindings form separately pinned support roots.
An attempt unresolved on page1 stays unresolved on every page/reopen of that snapshot even if a
real terminal arrives meanwhile; only a fresh snapshot may report the later event. Current checks
are restricted to authority and integrity, not recomputation of historical coverage from live state.
Detect changed/deleted pinned history by recomputing each prefix root/count before emitting data.
Reject forged/wrong-subject/wrong-query cursors; revoked/expired/exhausted grants fail normally.
Host sees an opaque serialized cursor, not private database row IDs or table names. No full persistent
snapshot copy or new producer ledger is required. Empty result still reports every registry family.

Initial bounded implementation retains100-item pages and a finite SDK scan guard at100,000 rows
across covered families. Exceeding guard raises a distinct limit error with no partial page or claim
of coverage; counts never silently truncate. This is a new audit resource bound, not a change to
recall401 cells, semantic thresholds, latest10, five-day window, or source256 bound. Scalability beyond
this bound remains a named next-slice requirement if real data reaches it.

## 2. Typed safe handoff for pre-candidate rejection

Expose immutable `MemoryOperationObservationV1` and `MemoryOperationObservationContext` DTOs.
`execute_typed_recall` accepts optional `observation_context` with opaque Host request/attempt refs;
this Manager-only kw is never forwarded to a legacy backend. At its outer invocation boundary,
project an ACTUAL existing TypedRecallRejectionV1 exactly once and attach the immutable projection
as `exception.operation_observation`, then synchronously re-raise the ORIGINAL exception. Class,
code, message and rejection_receipt remain unchanged. No observer callback, task, await, timeout,
queue or Memory DB access is introduced. Caller input is not used to mint a Memory admission receipt.

This is a typed handoff to the calling Host observer, not execution of arbitrary Host callbacks
inside SDK. Host persists start before dispatch, catches the original rejection, and sends the typed
carrier to its own persistence/outbox policy. It can use its existing bounded storage worker. A
Host callback/store failure cannot change the already produced SDK exception. It leaves the Host
attempt unresolved. External cancellation retains existing CancelledError behavior: SDK adds no
BaseException catch; a cancellation without an actual rejection receipt is not relabeled a rejection.
There is no new suspension between attaching a witnessed rejection and re-raising it, nor a task to
leak if a Host callback ignores cancellation. Late persistence is solely a Host receipt/outbox fact.

Projection contains schema/version, operation='execute_typed_recall', domain-hashed Host request/
attempt refs, domain-hashed SDK witness invocation_id, actual canonical request/context/plan digests
where available, finite stage/reason, candidate_query_started=false/count0, observed_at, observation_hash.
Malformed optional observation context rejects at the DTO constructor BEFORE the product call;
original existing invocation behavior without the kw is unchanged. Exact original pre-candidate
witness type plus finite supported stage/reason combinations are required for projection. Generic
DBfault/corruption/timeout/cancel without that witness receives no synthetic observation.
Never call repr/str on arbitrary bad product input or error objects. Int5 remains protocol unsupported;
string'5' remains protocol invalid. Context absent means uncorrelated observation coverage, not a new
invented Host request/attempt. Hashes and witness imply observation only, never durable persistence.

No new builder option is needed. No callback subscription means no duplicate delivery at nested
Manager/backend gates. Host absence always appears in coverage as `host_persistence_unverified`.
OA1 consumer tests a real separate Host SQLite store, but only production Host wiring can close this
required follow-up; no permanent waiver. Host observation never changes Memory protocol/hash,
admission/authorization/idempotency, and no public event-injection sink is added.

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
5. Real pre-DB int5/type-invalid rejection carries exactly one typed projection of its original finite
   witness, zero SDK SQL trace/lease access. No new task/callback is executed by SDK; original
   CancelledError behavior is retained. Host persistence failure remains explicit and cannot claim persisted.
6. A tiny real Host-owned SQLite observation store fixture (separate from SDK DB) persists start then actual
   observed rejection; crash/reopen sees deterministic attempt correlation. Missing Host wiring is explicitly
   uncovered. This is consumer evidence, not production Host integration or a new Memory authority.
7. Existing mutation/recall/suppression/job public behavior and canonical receipts remain unchanged;
   focused adjacent tests/API checks pass. No version/wheel/main change; source review gates candidate.

Follow-up required for user's all-operation goal: production Host start/terminal journaling and
observer outbox/recovery; all remaining operation entry points and nonreceipt exceptional exits;
new invocation exact-replay observations; end-to-end completeness comparisons. None waived by OA1.

## Challenge correction 2026-09-05

Dirac challenged initial5d21636: mutable phase validation could drift a pinned cursor; arbitrary async
observer callbacks cannot be forcibly time-bounded safely. Resolved contract by freezing all coverage
and dependencies at one cut, and replacing SDK-executed callbacks with an immutable synchronous
exception carrier consumed by the Host observer. This is a scoped design correction, not a change
to frozen product evidence or 069 bytes. The earlier proposal remains in Git history for review.
