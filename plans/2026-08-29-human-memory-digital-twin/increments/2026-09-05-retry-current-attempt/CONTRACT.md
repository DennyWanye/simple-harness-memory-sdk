# Retry/reclaim current attempt binding — narrow successor

2026-09-05. Authorized successor from frozen privacy0.6.10 source02f4020, in independent
feat/human-memory-retry-current-attempt tree. No version/wheel/pin/DDL/receipt or hash changes.
OA1 reader5260759 is independently under review in its original tree; later combination only.

P1 actual counterexample: first provider handoff fails and schedules retry; second claim has a new
batch/request/attempt. When second lease expires, recovery's historical batch-members join can pick
the old failed first batch and rotate the live job lease against the wrong attempt. Frozen069
f92fac1 reproduces; its evidence/DB must remain unchanged. No rewriting previous emitted events.

Minimal invariant: a reclaimable batch is active (handed_off/result_committed/audit_pending), has
members, and EVERY member is the currently claimed job attempt with matching batch/request/subject
and lease token, active attempt state, and an expired lease. Selection and rotating the whole batch
remain inside the existing BEGIN IMMEDIATE/one-writer transaction. No selecting an arbitrary expired
member and then renewing partially live/foreign attempts. Current-claim validation also requires
jobs.attempt_count==member.job_attempt and the attempt's canonical request_hash==batch.request_hash.

Reclaim preserves actual batch/request/member/attempt identities and committed result/application
receipts; only the existing lease fields and an actual reclaimed event change. A failed/applied
historical attempt remains byte-identical. Stale owner delivery/failure retains STALE_LEASE and real
out-of-order audit. Authority retry (same batch, future lease deadline) and durable result recovery
keep existing behavior. No second job ledger, new authority, schema migration or historical repair.

Oracle before implementation:
- Real ingest→first claim→actual failure RETRY_SCHEDULED→second claim→expiry→reclaim selects second,
  rotates lease, preserves exact request/member/attempt; first failed rows untouched; close/reopen.
- Two workers concurrently claim an expired current attempt: exactly one new lease; other returns
  None while it is live. A second manager cannot bypass the existing OS writer lock. Old-owner
  failure/delivery cannot alter current lease/state; actual current owner can continue normally.
- Multi-member batch: every member must be current and expired. A live member or altered current
  attempt/request binding prevents a partial reclaim; no lease/event change on that path.
- True child-process os._exit at existing job.claim.before_commit vs after_commit: reopen observes
  respectively old lease/no reclaim event or new lease/exactly one reclaim event. A live committed
  lease is not immediately stolen on ACK loss; after expiry reclaims same current batch/request.
- Adjacent accepted-result/authority-retry/crash/stale delivery tests remain unchanged. No full
  production/UI or OA1-completeness assertion. Public graph projection has no code-path change;
  focused public graph regressions suffice for this leaf.

Source tests may inspect actual SDK store rows to verify atomicity and unchanged history. Host must
continue using public APIs; no Host SQL or fabricated evidence. Raw red/green/crash DBs stay ignored.
