# Current attempt reclaim — source verification

2026-09-05. Independent source leaf from exact frozen0.6.10 source02f4020; oracle0d98296 before
production edit. No version change/build/wheel/DDL/public export/hash change/main/native write.
Inherited source version still0.6.10; this changed checkout is NOT its frozen artifact. Later combine
only after independent source acceptance and main version assignment.

Minimal production change: recovery selects an active batch only if every member matches its current
claimed job attempt, canonical batch/request/subject and lease token, with every lease expired.
Existing transaction/lease rotation and actual event producer are reused. Current-claim verification
also checks job attempt_count and the attempt request hash. Historical failed batches cannot redirect
the live retry's lease. No repair/rewrite of previously corrupted producer state or audit events.

Source oracle: six decisive cases actually failed on pre-fix source, with retained DBs under red-db.
After fix six pass; two real subprocess os._exit controls also pass. Covered current retry recovery
both before/after reopen, stale owner refusal, concurrent worker single winner, existing second-manager
writer-lock refusal, multi-member live/attempt/request mismatch refusing partial rotation, and exact
before/after-COMMIT recovery. Old failed attempts stay byte-identical. ACK loss after successful
COMMIT leaves a live lease that cannot be stolen; after expiry the same current batch/request resumes.
Initial crash fixture used an invalid zero-argument worker config and timed out; that failure remains
in crash.log. Fixed to the original explicit worker config and unconditional cleanup outside the
intentional os._exit points; no provider/model/native process was started.

Latest source selection: **107PASS/1 explicitly deselected inherited failure,6.02s**; mypy1source
and targeted ruff PASS. Covers new8 controls, adjacent durable job authority retry/result replay/
stale delivery/commit fault recovery, memory061, duplicate-source analysis enforcement, public graph
view and artifact isolation, and unchanged0.6.10 public API snapshot. Do not sum overlapping runs.

Unfiltered selection was107PASS/1FAIL6.38s. The same old test
`test_persisted_delivery_receipt_tamper_fails_closed_on_reclaim` reproduces on exact frozen0.6.10
src (git diff02f4020 -- src empty): tampered delivery hash now rejects during initialize's canonical
schema probe, before the old test's later claim assertion. Error remains the same
MemoryCorruptionError('stored analysis delivery authority differs'). Old test and refusal unchanged;
it is not claimed green or rewritten to soften the rejection. Both original/base logs retained.

The original frozen069 P1 is additionally rerun and **retained as a real DB**, never overwritten:
`.local-test-evidence/2026-09-05/retry-current-attempt/frozen069-retained-db/memory.db`.
No OA1 or patched code was imported; the log records frozen069 SDK source origin. Reclaimed batch
equals first failed batch and differs from second current batch. This supplements, not replaces,
the original OA1 jobs-red and frozen069 probe logs. No original native/userdata DB is read or changed.

| Ignored evidence under retry-current-attempt/ | SHA256 |
|---|---|
| red.log | 016b2ea18298639fd189e97be6ca25f330e431f00a544b108ec30ae06e3067d7 |
| green.log | 1444f14e032bc2c048f5f312448e5b0b3d84ea171f9f7bfda6f6152d983ccd1c |
| crash-r2.log | 8b832b125315e5bedfa40c773f6af8cf0b59fdb4c5225bfde1466fee34202ebf |
| scoped.log | 3946d4613d11186058bb9e874244da1f949caa1669e604d3f9b80fec2f2afc55 |
| scoped-r2.log | deb36f98c65efff3bd9c8a253c63f0b6325ada6746d930305da353c5525dd065 |
| frozen0610-adjacent-baseline.log | 1ce1e96f0d687e40203225b6f3dc2a3fea4c1fd8b54a075b717bb2b1ab3439b2 |
| frozen069-retained.log | df48420655d94cf74b9960acac8f274cae1d988d7c7fab650f16fcf14bc420b5 |
| frozen069-retained-db/memory.db | 2dcf009836bda86b194e0e11bb1b307d72d885ae1ffef75ac0f7e459e8111cc6 |

Re-run new decisive source tests (fresh tmpdirs, do not reuse retained red-db):
```sh
.local-test-evidence/2026-09-05/retry-current-attempt/venv/bin/python -I -m pytest -q tests/integration/test_retry_current_attempt.py
```
Exact adjacent selection:
```sh
.local-test-evidence/2026-09-05/retry-current-attempt/venv/bin/python -I -m pytest -q --tb=short --show-capture=no tests/integration/test_retry_current_attempt.py tests/integration/test_durable_memory_jobs_v5.py tests/integration/test_memory_061_core.py tests/integration/test_duplicate_source_analysis.py tests/integration/test_twin_graph_view_v6.py tests/artifact/test_twin_graph_isolation.py tests/artifact/test_public_api_snapshot.py -k 'not persisted_delivery_receipt_tamper_fails_closed_on_reclaim'
```
Environment is a separate offline editable source venv, exact official Harness0.7.2; no PYTHONPATH.
Required remaining: independent narrow source review; combination with independently ACCEPTed OA1
af49f2a1 (docHEADcb1409d) and assigned successor installed artifact gate. No partial wheel issued.
Graph public view is unchanged and its focused source regressions passed; no native graph claim.
