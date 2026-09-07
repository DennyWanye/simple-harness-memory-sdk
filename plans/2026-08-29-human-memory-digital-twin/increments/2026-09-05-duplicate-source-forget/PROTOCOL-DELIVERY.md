# History source/cut protocol leaf — 2026-09-05

Historical protocol-only state at8bd93c9. Builder and shared enforcement have since been added;
[current source review delivery](ENFORCEMENT.md) supersedes the implementation status below.
The four DTO/port wire contracts remain unchanged.

Only four public carriers/port are implemented, from frozen069 f92fac1 in the isolated
`feat/human-memory-duplicate-source-forget` tree. This is NOT a new version/wheel, builder support,
current suppression implementation, installed consumer, native fix, or S3/program completion.
Frozen069 snapshot and wheel are unchanged; the source API test explicitly accounts for the four
unversioned successor additions. Host can import these source contracts for its own isolated tests.

```python
from simple_harness_memory import (
    HistorySourceNamespace, HistorySourceOriginReceipt,
    HistoryForgetCutReceipt, HistorySourceAuthorityPort, SuppressionScopeKind,
)

namespace = HistorySourceNamespace(
    store_epoch=verified_initialization_receipt_sha256,
    subject=actual_subject,
    source_stream=f"primary:{actual_primary_conversation_id}:foreground_turns",
)
origin = HistorySourceOriginReceipt(
    namespace=namespace, source_sequence=immutable_turn_row.enqueue_sequence,
    evidence_id=envelope.evidence_id, envelope_hash=envelope.envelope_hash,
    admission_receipt_id=s1_receipt.receipt_id,
    admission_receipt_hash=s1_receipt.receipt_hash,
    proof_kind="atomic",  # ONLY independently verified same-TX first admission
)
cut = HistoryForgetCutReceipt(
    namespace=namespace, through_sequence=original_v2_action_cut,
    request_id=original_request_id, scope_kind=SuppressionScopeKind.MEMORY,
    scope_ref=original_memory_id, action_ref=action_envelope.evidence_id,
    action_hash=action_envelope.envelope_hash,
)
```

Authority async keyword-only signatures are fixed in
`src/simple_harness_memory/core/history_sources.py` and [CONTRACT.md](CONTRACT.md).
Host verifies full immutable S1/turn/init/action records, returns exact source or original action
facts; no Memory ingest prerequisite, fake Run, permission grant, or equality-key input. SDK
enforcement/builder hookup will follow separately; do not pass the future builder kw to069.

`origin_hash` / `cut_hash` use SHA256 of canonical UTF8 JSON `{domain,payload:to_json()}`;
domains `memory.history.source-origin.v1` / `memory.history.forget-cut.v1`. No NUL, normalization,
or computed digest in payload. Exact field sets, limits, legacy/atomic decision table and literal
vectors are fixed in the contract. No original hashes are rewritten. action payload contains raw
cut facts, not its future S1 envelope hash or cut_hash, avoiding self-reference.

Validation on this machine: oracle commit491b813 precedes carriers, with expected missing-root
ImportError recorded in ignored `protocol-red.log`. Independent stdlib literal vectors preceded
implementation. Source tests: **38 PASS (0.20s)** for immutable DTOs, literal hashes, strict wire
shape/types/proof kinds/scope, public async signatures and preserved frozen root API. Ruff PASS;
mypy one new source file PASS. No test here exercises suppression or authenticates Host facts.

Re-run from this tree (isolated source env; exact Harness0.7.2, editable THIS Memory tree):

```sh
.local-test-evidence/2026-09-05/duplicate-source-forget/venv/bin/python -I -m pytest -q tests/unit/test_history_source_contract.py tests/artifact/test_public_api_snapshot.py
.local-test-evidence/2026-09-05/duplicate-source-forget/venv/bin/mypy --follow-imports=silent src/simple_harness_memory/core/history_sources.py
```

Remaining: actual SDK two-phase public enforcement (Host callbacks outside SDK SQLite transaction),
all affected public entry coverage and real database red→green; Host authority/actioncut/atomic
source producer integration; new independently assigned candidate and installed verification.
Legacy v1 action without original cut remains matching-source UNVERIFIABLE, never native old
forget PASS. New genuine v2 remember/revise/forget evidence is separate. Delayed old S1 enqueue
retains legacy_before_only; sequence after cut must not be mistaken for new admission. No backfill.
