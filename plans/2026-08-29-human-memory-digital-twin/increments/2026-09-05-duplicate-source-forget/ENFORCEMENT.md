# Duplicate-source suppression — source review delivery, 2026-09-05

Current isolated source implements the shared gate and builder; **not a released/frozen successor,
installed-wheel proof, original native v1 forget PASS, or S3/program completion**. Base is frozen069
f92fac1, protocol8bd93c9, first executable56c6bf7, independently reviewed no-/text fix2b2fa47.
OA1 remains checkpointed separately. No version change, distribution wheel, tag, push, main merge,
Host/native environment installation or original database mutation.

## Public Host integration

```python
from simple_harness_memory import MemoryManager, build_human_memory_v7

version = getattr(MemoryManager, "history_source_enforcement_version", None)
if type(version) is not int or version != 1:
    raise RuntimeError("required_history_source_enforcement_unavailable")

manager = await build_human_memory_v7(
    db_path, history_source_authority=actual_host_history_source_authority,
    # retain the real existing evidence, action, analysis and classification ports
)
```

The same keyword is explicit on `MemoryManager.build_human_memory_v7`:
`history_source_authority: HistorySourceAuthorityPort | None = None`.
Invalid supplied authority fails construction before opening the database. No fallback ignores
this argument. Four root DTO/port names and canonical fields remain exactly as protocol8bd93c9.
Class capability1 distinguishes protocol-only8bd/old069, **but cannot replace exact reviewed source /
future wheel identity**. This branch still carries inherited packaging version0.6.9; do not build
or install it as a replacement for the frozen069 artifact.

The existing backend public `resolve_suppression(candidate, purpose, *, principal=None)` now
accepts the **actual** `MemoryPrincipal` for Host fact preparation. Its subject must equal the
candidate; do not fabricate session/run IDs. Existing positional candidate/purpose calls remain
valid. A subject-only call can deny exact affected sources but cannot establish atomic freshness
without the actual principal. Such calls must not be used to authorize fresh reassertion. Ordinary
legacy evidence-ID-only readers similarly retain conservative denial when they lack prepared
Host facts. SDK receipt/source admission is not a new execution run or a disclosure grant.

## One shared preparation and final resolver

`backends/history_source_guard.py` owns invocation-local context, not persistent authority:

1. `history_source_operation` only sets/resets a ContextVar; no database/Host access at function
   entry. Public admission checks therefore retain their original ordering and rejection receipts.
2. `prepare_history_source_context` reads the current active MEMORY directives and canonical USER
   support across every memory revision and true upstream evidence, within a short SQLite read
   transaction. It reads the full real S1 pair, never a caller-provided equivalence key/seed list.
   Lookup of other ingested USER sources uses subject/source-kind plus exact top-level `/text`
   equality against those real seeds, then validates canonical S1; cold batch sources use their
   supplied exact validated S1. No arbitrary recursive field scan, substring, trim or semantic test.
3. Release Memory transaction and lock, then resolve original Host cut and origin facts. Roundtrip
   returned DTOs through strict wire validation and bind actual S1 receipt/envelope/subject. Host
   proves init/turn/action facts; SDK alone chooses memory seeds and enforces current suppression.
4. Existing `_resolve_suppression_unlocked` pins direct and alias decisions to one SQLite snapshot.
   It reuses an existing caller transaction or owns a short read transaction when necessary. Its
   `_resolve_suppression_snapshot_unlocked` retains original direct-target checks and adds the same
   `duplicate_source_matches` check only when no direct refusal already decides the result.
   Current canonical seed catalog is rebuilt after prefetch, then cached only within the invocation
   with both connection `total_changes` and `PRAGMA data_version` checked at final use. External
   commits invalidate it across transactions. Current new/changed relevant bindings without
   prepared Host proof fail closed; they do not get a stale source grant.
5. The history observation's policy hash additionally binds actual consulted decision/seed and
   successful origin/cut proof hashes. This observation still grants no old typed result reuse or
   network-send lock; Host must retain its current-source outbound fence.

Source/cut namespace must agree across candidate, canonical seed and original action. Seed sequence
must be at/before the cut. Candidate `atomic` aftercut can continue through ordinary gates;
`legacy_before_only` aftercut cannot prove freshness. Missing/wrong pair, namespace or cut is
`history_source_cut_unverifiable` only for affected exact-profile aliases.

| Entry family | Prepare / final use | Verified scope |
|---|---|---|
| `check_history_visibility` / `resolve_short_horizon_sources` | prepare before final batch snapshot; evidence ancestors, owned typed item and exact standalone short all reach shared resolver | cold/late/derived/history/short source controls |
| `resolve_suppression` | actual optional principal prepares; shared final snapshot always checks | direct old deny / atomic new allow / reopen |
| standalone short recall and projection rebuild | prepare before candidate lock; actual candidate origins checked by same resolver | real12 groups,2 old hits; duplicate memory-only forget removes both; recent10 exclusion unchanged |
| typed collect / confirmation / final context-use | prepare after protocol/type/ownership/narrowing and durable admission/exact replay; original final source checks call shared resolver | new atomic mutation→typed selection→history→final-use/exact replay; original typed suite |
| typed page | preserves content-free result-bound page semantics; it is not a current-use grant | original page/binding tests; actual content use is separately gated |
| caller mutation / procedure / prospective | prepare after existing admission/authority validation, before mutation transaction | actual atomic reassert CREATE vs legacy reject; shared existing candidate gates |
| background analysis materialization | prefetch only current canonical result-committed batch; final lease/result/phase checks repeat in application transaction | real runner applied vs actual cognitive effect asserted separately |
| ordinary read/search/projection/export/twin/audit | shared final resolver; principal-bearing twin prepares; legacy subject-only paths cannot infer a principal | ordinary/history adjacent suites; unsupported legacy fresh-use limitation above |

Source-only admission persists immutable input without creating an analysis job or permission grant;
registration persists proven grouping facts. Actual indexing/recall/ordinary use must pass the gates
above. No new ledger, DDL, implicit migration or old receipt/decision hash changes.

## Scope correction and known gates

Dirac found56c6bf7 overblocked legitimate unrelated USER envelopes without `/text`. Independent
public reproduction and this branch's red control both showed `[False,False]` instead of
`[True,False]` for unrelated USER / USER with real forgotten parent. Fix2b2fa47 removes only the
subject-wide alias inference: envelopes outside the declared whole-/text profile do not acquire
an alias edge. Direct IDs and actual ancestors remain enforced. Dirac independently accepted this
specific fix; that scoped result is not full enforcement acceptance.

**Existing native v1 action without original cut:** exact affected sources remain UNVERIFIABLE,
including later atomic same-text sources. Without explicit revoke or an additional trusted
source-after-original-action proof, the old directive continues to block same-text reassertion.
Do not describe this behavior as supported old-library fresh reassertion or temporary when no
unblocking mechanism exists. A new v2 closed loop with full original cutoff is a separate positive
case. No old hash rewriting, fabricated cut, current-MAX/time inference or automatic revoke.

**Cost:** there is no matching index on the top-level JSON `/text` equality predicate. The4096
return/traversal work cap does not bound SQLite rows scanned, scan count across seed texts, bytes
or P99 latency. The finite source tests below are correctness evidence only, not performance
acceptance. No thresholds were raised.

**Host liveness:** main reported the legitimate legacy late-enqueue case refuses Context preparation
with zero additional Provider requests, but leaves the turn/HostRun CLAIMED with sdk_run_id=NULL and may block FIFO. That Host regression
remains red; main is implementing a genuine pre-SDK Host FAILED/SETTLED receipt path.
The retained Host summary hash is e4f9629435cc210941fb1aebb857d9e245eacab739e326b5c55578d8b68abddf
(main-provided evidence; not independently re-run here). SDK refusal must not be weakened to conceal it. No full privacy/product/native PASS.

## Verification on this machine

Final targeted batch **206 PASS,15.14s**, ruff PASS, mypy4 changed production sources PASS. This is
one de-duplicated batch, not the sum of earlier17/18/94/40 runs. It includes:

- 22 new real-database controls: old pending/cold/late ingestion, actual dependent answer, atomic
  vs legacy late enqueue, wrong proofs, ACK replay/reopen, all-revision seed after genuine REVISE,
  unrelated whitespace and no-/text profile controls, real standalone/typed short selection,
  mutation→typed→final-use, and background workflow-versus-cognitive-effect assertions.
- 24 configured-authority/capability checks, including reuse of original13 attack mappings and10
  protocol zero-SQL tests with the new port actually supplied (not merely None).
- original30 public rejection/trap/SQL tests plus focused history/short/typed/analysis and root
  contract regressions. No full SDK suite,401 runner, provider, model loading or native/UI run.

External-write controls first assert the normal second-manager writer lease refusal. A deliberate
**source-test-only lease handoff** then leaves the first real connection open while a second real
manager commits through public suppress. One test inserts during Host await; another exercises a
populated same-operation cache across two read transactions with unchanged first-connection
total_changes. Both deny after the new commit. This does not claim two concurrent production
writers are supported. No Host private SQL or original database edits were used.

Dirac's short-path evidence challenge was addressed by expanding the existing short test,
then running only that test: **1 PASS,0.45s**, ruff PASS. This is not an additional unique test
on top of206. Before forget, public selected-source resolution proves the two hits have distinct
exact sources evidence-1 and evidence-2, with only evidence-2 materializing the forgotten memory.
After forget, both standalone and typed historical bindings deny; a new provider attempt using
the old typed result rejects with RECALL_AUTHORITY_STALE. The original attempt returns its exact
historical receipt, which does not grant current use. A new atomic same-text source13 after cut2,
followed by ten complete groups, becomes standalone/typed visible and passes fresh final-use
authorization while the old bindings remain denied. These are real SQLite/public SDK fixture
controls, not proof of Host-produced complete groups or native execution. Production code remains
at c9bdd22. Dirac independently accepted the complete fixed-source scope at
53099e736f9321964f7ae663b7df866a9cc67f5e on2026-09-05, with no remaining current P0/P1
identified. Review covered shared ordinary/typed/short resolution, final read transactions,
all-revision and background paths, configured-authority pre-admission zero-SQL controls, and
these supplemental short assertions. Dirac independently checked both owner log hashes rather
than re-running206; the independent no-/text reproduction separately went red→green.
This ACCEPT is source-scoped: controlled Host Origins fixtures and source tests do not establish
installed artifact identity, actual Host authority correctness, legacy liveness or native completion.

Main separately reported source-overlay actual Host API/history/reopen/next physical MockTransport
request tests on56c6 and2b2fa47 (latest36PASS32.98s, then direct-principal aligned6PASS8.62s).
Those are collaborator evidence, not re-run here, installed evidence or native proof.

Raw ignored evidence under `.local-test-evidence/2026-09-05/duplicate-source-forget/`:

| File | SHA256 |
|---|---|
| enforcement-red.log | 13a9def0ad41b5352a91463c04fd54aa7d8c3c494d080494d3845f9e93b7e066 |
| other-profile-red.log | 2c571dce62b8e0b9470f3bc5007d7aaae9ce7a0a89f8e247fbff8d02235a3308 |
| enforcement-targeted.log | 1fedc8561226259433839e443cf2ed32cd96804af98f348bbc74ad45891bf230 |
| short-review-controls.log | 718af798eb1450a812074f301573c1f498edd3575a2450f85ee649d7e03c3c72 |

Re-run from this isolated tree, exact Harness0.7.2 + editable source environment (not wheel proof):

```sh
.local-test-evidence/2026-09-05/duplicate-source-forget/venv/bin/python -I -m pytest -q --tb=short --show-capture=no tests/unit/test_history_source_contract.py tests/artifact/test_public_api_snapshot.py tests/integration/test_duplicate_source_forget.py tests/integration/test_duplicate_source_short.py tests/integration/test_duplicate_source_analysis.py tests/integration/test_history_source_pre_admission.py tests/integration/test_history_visibility.py tests/integration/test_public_recall_rejection.py tests/integration/test_short_history_visibility.py tests/integration/test_short_history_visibility_faults.py tests/integration/test_typed_recall_v6.py tests/integration/test_analysis_recovery_correctness.py tests/integration/test_memory_062_analysis_evidence_refs.py
```

The supplemental short control alone uses the same command with only
`tests/integration/test_duplicate_source_short.py`; no repeat of the206 batch was needed.

Next gates: separately assigned successor artifact/installed bytes and consumers; Host legacy late-enqueue
liveness and final genuine native loop. Frozen069 and original native data remain unchanged.

2026-09-05 artifact gate update: [fixed0.6.10](CANDIDATE-0.6.10.md) completes owner double-offline/
installed/public native-copy gates. The remaining Host/native and legacy limitations above remain.
