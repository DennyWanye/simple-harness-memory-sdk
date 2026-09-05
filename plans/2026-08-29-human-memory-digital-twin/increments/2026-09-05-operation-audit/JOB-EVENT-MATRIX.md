# OA1 job transition oracle — actual producer facts

2026-09-05. Read from exact basef92fac1 sqlite_v5.py actual _append_batch_events_unlocked call
sites; no new implementation. Each event is inserted for every actual analysis_batch_member with
job/attempt/batch/request binding and canonical event_hash. Rows are append-only. Event timestamp
is not a total order. This matrix is NOT a claim all invocation failures create events.

| Actual producer path | Durable event kind | Safe as-of inference |
|---|---|---|
| claim_analysis_batch new committed claim | provider_handoff | Actual attempt was handed off, not evidence provider ran/completed |
| claim_analysis_batch reclaim same batch/attempt | reclaimed | Lease recovery observed; no invented new attempt |
| commit_analysis_result first accepted result | result_committed | Canonical result was committed; no claim of application |
| commit_analysis_result same canonical result | result_replayed | Actual replay event, preserve it as separate event |
| commit_analysis_result conflicting result | result_divergent | Divergent result ignored; not replacement of original result |
| stale result/reject/failure/application/finalize | result_out_of_order | Ignored stale delivery; cannot turn it into terminal failure |
| prepare_analysis_application valid | application_staged | Actual accepted application receipt, not finalized applied |
| prepare_analysis_application invalid | application_rejected | Actual rejected application receipt, not generic call rejection |
| _record_analysis_invocation after durable mutation audit | mutation_audit_committed | Audit material committed; final application may still be pending |
| finalize_analysis_application | applied | Analysis workflow finalized; cognitive effect may be no_mutation, not necessarily a memory write |
| fail_analysis_batch below retry ceiling | retry_scheduled | Actual retry scheduling; no claim next attempt started |
| reject_analysis_result retryable/authority gap | authority_retry_scheduled | Distinguish authority recovery from provider retry |
| fail_analysis_batch/reject_analysis_result terminal all_dead | dead_letter | Actual batch terminal; per-job count/binding validated |

Required predecessors inside SAME snapshot cut:
- result_committed / result_replayed / result_divergent / reclaimed / result_out_of_order /
  application_staged / application_rejected / retry_scheduled / authority_retry_scheduled /
  dead_letter all have an actual batch/member/attempt with provider_handoff event.
- result_replayed/result_divergent additionally have the original result_committed event.
- application_staged/application_rejected have result_committed (prepare operates on a committed
  MemoryAnalysisResult, including application-level validation rejection).
- mutation_audit_committed has application_staged OR application_rejected, with matching result hash.
- applied has mutation_audit_committed plus the preceding application event/result_committed.
- No mandatory later event is inferred from an earlier event. An unclosed handoff can be in flight,
  interrupted or unobserved; expose unresolved, never infer applied/failed from current jobs.state.
- pending jobs without attempts have no job_attempt_events. Coverage explicitly states creation and
  pre-handoff failures are absent; no synthetic start added from a current jobs row.

Rejection paths may emit failure audit without accepted result_committed/application event; do not
apply the accepted-application predecessor chain to authority_retry_scheduled/dead_letter. Pin this
case using the existing real rejection fixture before reader assertions; no template outcome guessing.
Changing/removing a required earlier event while its later witness remains must surface a gap or
canonical corruption refusal. Deleting all evidence before the first trusted snapshot cannot be
proved by the reader alone; independent Host start/receipt/checkpoint is the required witness.

Observed real producer detail: applied may carry result_hash=None because finalization appends from
the originally handed-off claim. Reader permits exactly that actual absence on applied; an arbitrary
non-null foreign result_hash still rejects. Cognitive effect comes from independently validated
same-cut canonical result/application/mutation receipts, never a fabricated applied result field.

Separate inherited producer defect confirmed on unchanged f92fac1 source: fail first handoff,
schedule/claim a new second attempt, then expire its lease; claim_analysis_batch can reclaim the
first old failed batch because its recovery join includes historical members of the now-claimed job.
The reader does not repair/rewrite these events. Legal reclaim-before-retry is the positive cursor
control; the failing retry-before-reclaim probe/log is retained and reported for a separate producer
fix. An old attempt with an actual later reclaimed event is unresolved, never silently final/applied.

Native counterexample supplied by main (partial ref product-sdk-be6f...): actual provider success
and applied job with analysis_all_operations_rejected/no_mutation closure. The audit must preserve
`applied` and the canonical no-mutation effect together. It must not count this as cognitive-write
success or confirmation that a remember request was fulfilled. Bind the actual result/application
and any mutation receipts at the same snapshot cut; absent bindings mean unverified, not guessed
success or zero writes. Main's CREATE candidate v3 repair is separate; old jobs remain unchanged.
