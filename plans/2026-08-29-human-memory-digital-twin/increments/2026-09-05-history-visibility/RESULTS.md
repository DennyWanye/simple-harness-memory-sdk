# History visibility source candidate — 2026-09-05

Base main8675352 / Memory0.6.3, branch feature/human-memory-history-visibility. User authorized
bounded AC1/AC7 remember/forget closure; source candidate only. No version, schema, wheel, pin,
Host main, frozen401/acceptance, provider/UI or paused runner edits. No claim that S3/S6/program
or Host/native history forget acceptance is complete.

The baseline real SQLite reproduction showed MEMORY suppression denied a memory while allowing
its original USER evidence via resolve_suppression, ordinary read and projection. The source fix
uses the existing suppression ledger, canonical upstream evidence and reverse support across all
revisions. It also handles memory support on derived evidence, so USER ancestors cannot revive it.
No original evidence rows or hashes are deleted/rewritten; ordinary suppression remains distinct
from explicit sealed audit. A source_ref or admission receipt cannot acquire a new identity to
bypass known lineage. Purpose-specific matching and revoke retain their existing semantics.

Public root exports added: HistoryBinding, HistoryEvidenceBinding, HistoryRecallBinding,
HistoryVisibilityItem, HistoryVisibilitySnapshot. Manager and cognitive backend expose:

```python
snapshot = await manager.check_history_visibility(
    principal=current_principal,
    disclosure_context=actual_host_request_disclosure,
    bindings=(
        HistoryEvidenceBinding(verified_s1_envelope, verified_s1_receipt),
        HistoryRecallBinding(result_id, result_hash, item_id, result_item_hash),
    ),
)
# Map each binding_hash back to the Host's actual source/message dependency.
# A message is eligible only if ALL its required sources are visible.
# Preserve ordinary unrelated USER dialogue with a valid S1 pair before analysis.
```

Bindings do not grant permission to substitute result text or omit causal dependencies. Host
retains the verified original S1 pair and actual recall result/item bindings, proves message
provenance, and supplies the real current request subject/recipient/audience/purpose/trust. UI
USER_REVIEW is an ordinary READ purpose and does not require a fabricated execution Run. Other
supported ordinary purposes use RECALL suppression. Whole-envelope evidence bindings currently
allow only the authenticated subject's own audience under current classification; unsupported
procedure applicability remains history_source_stale. Missing parent lineage, nonselected/unknown
result carrier, current head/hash/state/expiry/type mismatch, disclosure denial and suppression
fail closed. This API returns no historical content and creates no new authority or durable grant.

Output: ordered items(binding_hash,visible,reason), request_hash, checked_at, earliest known
valid_until or None, authority_epoch, policy_hash, schema_version1; snapshot_hash binds to_json().
The hash algorithm is SHA256(canonical_json({domain,payload})), using distinct memory.history.*.v1
domains. These values bind an observation, not a durable snapshot handle/lease. Registration can
change visibility at unchanged epoch/time/policy hash. Host must fresh-check complete dependencies
at each actual output boundary, after slow reads, and own check-to-output ordering. Old typed
paging/current-use receipt replay, run, turn and expiry gates are unchanged.

Batch1..256; one trusted time sample and one read transaction under the existing single-writer
lock. Shared dependency DAG checks memoize within this snapshot; unique node+edge work4096,
depth64. Each canonical reverse traversal consumes at most4096 fetched rows via fetchmany128;
node count also capped4096. Suppression target filtering uses SQL in250-pair chunks, with4096
matched directives maximum. Overflow raises or denies, never silently truncates to ALLOW.
These are not an entire batch SQL CPU/IO/byte bound or a p95 performance acceptance result.

## Current source verification

Python3.12 from Host read-only backend/.venv, source loaded from this worktree with PYTHONPATH;
Harness dependency0.7.2. Not installed-candidate/exact-wheel evidence. Commands run from this tree:

```sh
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_history_visibility.py tests/integration/test_suppression_v5.py tests/integration/test_typed_recall_v6.py tests/artifact/test_public_api_snapshot.py -q
# 68 passed, before three resource tests were appended; same source.
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_history_visibility.py -k 'second_sql_chunk or row_budget' -q
# 3 passed, 21 deselected. Combined final history tests:24; focused baseline+history:71.
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_cognitive_mutation_repository_v5.py -k 'suppression or suppressed or revise or classification' -q
# 23 passed,55 deselected. Total distinct verified tests across these scopes:94.
uv tool run --offline mypy src/simple_harness_memory/core/history.py src/simple_harness_memory/backends/history_visibility.py --follow-imports=silent
# 2 source files passed. Ruff changed/new scope passed; sqlite_v5 has an unchanged base UP031
# at its pre-existing query formatting (line1008), excluded from this bounded lint report.
```

The old0.6.3 public snapshot JSON is preserved; its regression asserts the exact five additive
unversioned candidate exports and all old exports. Main will allocate candidate version/new
snapshot/wheel later. No current package release is represented by this unversioned source diff.

Independent CLI read-only review found P1 source/admission identity and P2 repeated DAG work;
both fixed with decisive regressions. Independent task review confirmed cold USER zero DML,
single-writer snapshot ordering, unchanged-epoch registration visibility changes, DAG memo and
three lineage tests. Follow-up read-only review accepted target SQL chunking, fail-closed row
budget and single clock propagation; no new P0/P1 blocker reported. This is scoped source review,
not independent installed-candidate, full audit or Host wiring acceptance.

Ignored local evidence in this SDK tree: .local-test-evidence/2026-09-05/history-visibility/.

| Evidence | SHA256 |
|---|---|
| baseline-result.json | b4908c2825c3d5bd7a4141752fc18156d404eaadff00a2742a82f9dfc78c1fff |
| red.log (5 missing-API failures before implementation) | 62e96cdd676a424f30bea94fb943ff31cc409306f7c8e1efe164fc2e50384d41 |
| derived-red.log | 8e7e3db9fff099c53c42cde07477ac5b5d3566e370c33b6104b4eaf53e9145a4 |
| final-focused.log | 12bcdb43494efa86f5bde374dfac6e86cb1588de6a734f149c5ffd4a08010d5e |
| mutation-regression.log | c2fa93aaa5a3615b79fbddf794c2eb1b95eec7a52a3def8e63c48df85d8718ea |
| resource-regression.log | 1607853608be88f57f5a3ff5302767ba69be762aff17c518bacb9ace1a99678d |
| independent-review.log (initial CLI findings) | ac95b53e99a5cd82570fe9705ebb3791595c1726bde80e6adc8c32ae1f42e467 |

Independent task report is Host ignored
.local-test-evidence/2026-09-05/independent-review/history-visibility-contract/REVIEW.md,
SHA a3d0e5bf51241c19318f50317ec9a625da7bcb435cfa1a12dfd83ed7cfa3d204;
its remaining early P2 wording is superseded by the reviewed chunk/budget follow-up above.
Raw probe/log/DB artifacts remain ignored; no raw evidence committed.
