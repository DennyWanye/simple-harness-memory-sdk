# Memory0.6.10 privacy successor candidate

2026-09-05. User authorized the artifact/installed gate after Dirac complete fixed-source scoped
ACCEPT53099e7 (productionc9bdd22). Local branches/tags/cached remote refs and candidate build roots
have maximum version0.6.9;0.6.10 is unused locally and allocated here under that authorization.
No registry publish check or release claim; no push/tag/native/main or frozen069 change.

The candidate preserves069 source-only admission,7.0/7.1→7.2 official migration, selected-short
source read, clock and rejection capabilities. Only production change since reviewed source is
__version__; four existing history origin/cut exports receive their own0.6.10 snapshot. Prior
snapshot JSON stays byte-exact. README/changelog reflect this isolated successor.

Public consumer oracle: cold/before/after ingestion old duplicate and real dependent answer deny
following MEMORY-only forget; no-/text unrelated USER stays visible; same action/decision/cut stays
exact after fresh atomic same-text input; legacy late-enqueue and missing original v1 cut remain
unverifiable. Direct NO_MUTATION receipt plus empty typed recall proves the earlier source did not
materialize before later CREATE. This is a minimal public control, not native analysis-job replay.
Short public actual-source1/2 separation, old typed current-use rejection vs exact historical ACK,
source13 atomic aftercut plus ten later groups, final-use and reopen are required. Source-only
fixture metadata does not establish actual Host producer proof. Numeric thresholds unchanged.

Before freeze: root snapshot4PASS0.13s; six public consumer source stages PASS. Initial consumer
errors retained ignored: empty MUTATE factory construction, nonempty-operation-only receipt-view
misuse, missing explicit principal owner, and residual test-helper import. They are not product
privacy failures. The consumer now uses the existing public apply-receipt authority for NO_MUTATION,
no source/test imports or SDK private SQL/fields. Installed gate remains separate.

Two offline wheels must match byte-for-byte, then install with exact wheel hashes into a fresh
venv with no PYTHONPATH/PYTHONHOME and run python -I. Full Memory/Harness source→wheel→installed
package bytes, import origins, metadata and old snapshots must agree. Raw manifests/logs/DBs are
ignored under .local-test-evidence/2026-09-05/privacy-0610/.

Original native input is read only as filesystem bytes and copied with WAL/SHM. Exact Host S1
pairs are exported from the disposable Host copy; successor performs only public migration/build/
history checks on the disposable Memory copy. Original files must retain hashes and mtimes. Old
v1 action receives no invented cut; all three known USER bindings must deny, old duplicate reason
history_source_cut_unverifiable, reopen same policy. This does not prove native fresh reassert or
Host late-enqueue liveness. Installed and native-copy results will be recorded after actual runs.

## Fixed artifact and installed result

- Exact source: `02f4020103c3166ffc2360b79bf90f662905d96c` (clean at both builds).
- Wheel: `.local-test-evidence/2026-09-05/privacy-0610/build1/simple_harness_memory_sdk-0.6.10-py3-none-any.whl`.
- Wheel SHA256: `ff73a1a2a891b2a85a45c054d88af14edc6a709de17427103c076059b8ac4854`.
- Second independent offline build is byte-identical. Harness0.7.2 source
  `2b8428465cbd41032ba024a0b7199183161f5ecd`, wheel SHA
  `53bded3fea87168e5d2ad9e49fea5f99e1c1edb1d6077b2a52dd62716692f9ed` unchanged.
- `combination-manifest.json` SHA256:
  `72f45096c6fdbe57962d45dd1385c2ca8aa3e9919a2acaeac6faf401aae8c11f`.
- Isolated installed public consumer: six stages PASS; real copy history/reopen: two stages PASS.
  These are scenario stages, not additional source-case totals. Committed root snapshot4PASS.
- Complete package equality: Memory70/Harness151 files source→wheel→installed;211 runtime module
  origins in the new venv; installed metadata versions/direct wheel paths exact; pipcheckPASS.
  No PYTHONPATH/PYTHONHOME, editable runtime, test imports or SDK private SQL in consumers.
- All previous root snapshots unchanged fromf92fac1, frozen069 wheel SHA rechecked unchanged.
- Native exact original input main/WAL/SHM for Memory and Host: six hashes/sizes/mtimes unchanged
  after copy/validation. The disposable Memory copy may checkpoint normally. No new cut/action
  was synthesized for these old three USER sources; old unmaterialized duplicate denies with
  history_source_cut_unverifiable. This is actual-old-data public-read evidence, not a new native
  forget/reassert loop or Host CLAIMED→SETTLED proof.

Ignored reports relative to the privacy-0610 evidence root:

| Report | SHA256 |
|---|---|
| installed-public/result.json | f1f8b904338a41aa3696b88f17c3ec236c409a8bfe6cedda4ad952f82ad1f386 |
| native-public.json | e726e2bc283887a14af5dcb6231c13f896c2f113b180593a08ddd951bfda1bd1 |
| native-inputs.json | 8f440284885ad09514e8197f66b4da10b86c15fc7cb1b28199a99e1293b56c1d |

Exact commands from this worktree (use a new output directory when re-running consumers;
never overwrite the frozen build1/build2):

```sh
SOURCE_DATE_EPOCH=315532800 uv build --offline --no-sources --wheel --out-dir .local-test-evidence/2026-09-05/privacy-0610/build1
SOURCE_DATE_EPOCH=315532800 uv build --offline --no-sources --wheel --out-dir .local-test-evidence/2026-09-05/privacy-0610/build2
uv venv .local-test-evidence/2026-09-05/privacy-0610/venv --python .local-test-evidence/2026-09-05/duplicate-source-forget/venv/bin/python
uv pip install --offline --python .local-test-evidence/2026-09-05/privacy-0610/venv/bin/python --no-deps --require-hashes -r .local-test-evidence/2026-09-05/privacy-0610/exact-wheels.txt
uv pip install --offline --no-sources --python .local-test-evidence/2026-09-05/privacy-0610/venv/bin/python simple-harness-memory-sdk==0.6.10 simple-harness-sdk==0.7.2
uv pip check --python .local-test-evidence/2026-09-05/privacy-0610/venv/bin/python
.local-test-evidence/2026-09-05/privacy-0610/venv/bin/python -I scripts/duplicate_source_public_consumer.py .local-test-evidence/2026-09-05/privacy-0610/installed-public
.local-test-evidence/2026-09-05/privacy-0610/venv/bin/python -I scripts/duplicate_native_copy_public_consumer.py .local-test-evidence/2026-09-05/privacy-0610/native-copy/human_memory_v7.db .local-test-evidence/2026-09-05/privacy-0610/native-inputs.json .local-test-evidence/2026-09-05/privacy-0610/native-public.json
.local-test-evidence/2026-09-05/privacy-0610/venv/bin/python -I .local-test-evidence/2026-09-05/privacy-0610/verify_candidate.py
```

Independent full source scoped ACCEPT is53099e7; current owner installed gate is PASS. Main has
received the exact artifact for separate vendor/pin/owner-installed and actual Host combination.
No claim of independent installed ACCEPT until received. OA1 resumes only in its separate tree;
this artifact/source stays frozen. No push/tag/release/main/native changes.

JOURNAL_VERDICT: BOUNDED_ARTIFACT_INSTALLED_PASS; original program/native/Host legacy liveness gates
remain separate. Retrospective: reuse public input factories, but strip all source-test imports
and authorize the real principal before the first installed attempt; retained harness input errors
must not be counted as product failures or hidden by expected-result rewrites.
