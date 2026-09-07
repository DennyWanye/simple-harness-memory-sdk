# Standalone short history visibility source delivery — 2026-09-05

Approved bounded AC1/AC7 repair; base2877474 (sealed0.6.6 follow-up docs), independent branch
`feature/human-memory-short-history-visibility`. Contract f445c14 preceded production edits;
independent design ACCEPT preceded implementation. No schema/version/build/pin/main/push/tag,
Host/native/provider/full401 change. This source still carries inherited version0.6.6 until the
main executor allocates a new candidate; it is NOT the sealed0.6.6 artifact or installable identity.

## Result and exact boundary

New root `HistoryShortHorizonBinding(audit_id,chunk_ref,content_hash)` joins the existing1..256
history batch. SDK verifies owned canonical actual-success recall audit, exact started linkage,
selected membership plus eligible content hash, and absence of a timeout terminal for the same
attempt. It then checks current complete canonical chunk/source group, actual content hash,
expiry, disclosure/classification and evidence/entity/reverse cognitive MEMORY suppression.
No fake typed binding, new authority or durable grant. Old history/typed/current-use semantics
remain intact. No global cognitive policy is required for authoritative short-only classification;
that exception does not propagate to cold evidence or typed sources.

Real baseline before code:12 registered groups ->2 real standalone hits; ENTITY(project-alpha)
forget ->fresh recall0 hits while caller's naked chunk memory_id suppression candidate still
allows. This exposes missing caller lineage/exact public carrier, not an ignored supplied entity.
Exact negative/positive tests now pass, including memory_id forget ->original USER and old short
hidden together with unrelated source still visible. A source-only corruption test may deliberately
use backend connection/SQL; public fixture setup/check tests do not inspect SDK SQL. No fault test
is used as installed-wheel or Host proof. Early facade/fixture constructor corrections were setup
errors; red-r2 specifically fails because HistoryShortHorizonBinding was absent before production.

Host minimal integration after a newly allocated candidate exists:

```python
from simple_harness_memory import HistoryShortHorizonBinding

# At actual selection/use, retain this exact result/hit provenance alongside the content.
binding = HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
# Host independently verifies stored content bytes against hit.content_hash and records
# all actually retained memory-derived dependencies. SDK does not infer content provenance.
snapshot = await manager.check_history_visibility(
    principal=trusted_principal,
    disclosure_context=current_actual_host_request_disclosure,
    bindings=(binding,),  # batch the entire page/Context, including evidence/typed carriers
)
if not snapshot.items[0].visible:
    reject_or_remove_dependent_content_before_output()
```

The same check is necessary immediately before nextProvider sends, not merely terminal history
rendering. UI uses the actual request's USER_REVIEW context, no invented SDK execution Run.
Host retains source completeness and check-to-send ordering responsibilities. Recheck on every
output: authority_epoch/checked_at/policy_hash/snapshot_hash are observations, never cache grants
or complete DB revisions. No SDK lock extends across a later network await. Old typed execution
`authorize_recall_context_use` contracts are unchanged. No claim of Host/native/nextProvider E2E.

## Actual bounded validation

This executor:26 initial short source scenarios +2 purpose/policy controls PASS; adjacent93 PASS,
**121 distinct source tests** total. API4 repeated after strict duplicate-sensitive root assertion,
not counted extra. Independent Popper reran both current short files:28 PASS, and API snapshot
separately; source review ACCEPT, no P0/P1. Sole P2 (set-based snapshot could hide duplicate
exports) corrected to sorted exact old list plus one explicit pending export. Frozen JSON unchanged.
Three source files pass exact Harness-aware mypy; focused Ruff and git diff check pass. Final
helper typing-only JsonValue cast preserves runtime list values/order and hash preimage.

```sh
# cwd: /Users/denny/projects/simple-harness-memory-sdk-short-history-visibility
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest -q tests/integration/test_short_history_visibility.py tests/integration/test_short_history_visibility_faults.py
#28 source scenarios; deterministic development embedder, no provider/MPS.
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest -q tests/integration/test_history_visibility.py tests/integration/test_short_horizon_repository_v5.py tests/integration/test_suppression_v5.py tests/integration/test_public_recall_clock.py tests/integration/test_public_recall_rejection.py tests/artifact/test_public_api_snapshot.py
#93 adjacent scenarios.
uv tool run --offline mypy --python-executable /Users/denny/projects/simple-harness-memory-sdk-066-candidate/.local-test-evidence/2026-09-05/combined-066/venv/bin/python --follow-imports=silent src/simple_harness_memory/core/history.py src/simple_harness_memory/backends/history_visibility.py src/simple_harness_memory/backends/short_history_visibility.py
#3 source files PASS; no source installation into Host/native env.
```

Source tests use existing legal public DTO/authority constructors. Internal negative fixtures
cover duplicate/failed/cancelled/incomplete/deadline audit state, wrong attempt, nonresult IDs,
same-attempt terminal, missing/wrong source links and corrupted text/classification. These
synthetic fault states only assert denial/error, never manufacture successful product evidence.
Resource limits remain existing256 batch and bounded4096 linked rows; this does not promise
whole-query SQL CPU/IO/byte bounds. No original401/14attack/threshold/hash changes.

## Local evidence (ignored)

All paths below relative to `.local-test-evidence/2026-09-05/` in this independent tree.
- `short-history-baseline/result.json` SHA256 `85ea651cad2429f42c39dba58e9900197d63cc0d509cbfac8983203935e65da9`.
- `short-history-baseline/reproduce.py` SHA256 `5cca4c4a9a42f5b4322f24c415a50193c02f5ea9f847296fd3be4523e0b14322`.
- `short-history-validation/red-r2.log` SHA256 `071c20fff453f67299e7bbedbdc6482a732df8afb7829228eb63d67ccb7a1272`.
- `short-history-validation/green-r3.log` SHA256 `47531e22e0f11ade57b44b7d08b10b90243689f35436a7a2a6d5e018a5e9b8d1`.
- `short-history-validation/floors.log` SHA256 `33f2429d9a540f9df75b0fdecba4bdf0f9b0de8820043029b788c0c244c2cfd0`.
- `short-history-validation/adjacent.log` SHA256 `d14965c1d0d51e3e0a9078dcffb2614139bd6515cf8840c35aacd504eb8ec371`.
- `short-history-validation/root-api-final.log` SHA256 `452fada82e1df58d7f89fa99128aea691c519ad7daf4915a4bece62bd06ecbdf`.
- `short-history-validation/mypy-r2.log` SHA256 `8228fcc5ce46d42d01caf3cd941f4e9c5f2bcc372bb5b147a2f0572d2dd675a8`.

Independent review logs are Host ignored `independent-review/short-history-focused.log` and
`independent-review/short-history-api.log` in the reviewer-owned evidence location; those reported
independent runs are not relabeled as this executor's installed/public verification.

0.6.6 sealed wheel rehashed unchanged during this delivery:
`381d85437537ae1f58f04b84e8332b0774d1e3aff2c6529b3824126071135361`, build source
`9ec59438663272cd9e208de5d2e7b85bf0f40a5a`. Exact artifact and installed consumer commands remain
in the preceding history increment's CANDIDATE-0.6.6.md. Do not overwrite that wheel. Main executor
will allocate a distinct version after reviewed source commit, then separate installed-wheel and
Host nextProvider/history integration validation can follow. No new candidate wheel exists here.

VERDICT: COMPLETE for the authorized standalone short SDK source/contract/library review scope;
new version/artifact/Host integration and original S3/program acceptance remain separate.
