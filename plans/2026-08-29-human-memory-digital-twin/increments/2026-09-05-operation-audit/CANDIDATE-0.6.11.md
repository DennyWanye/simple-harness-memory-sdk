# 0.6.11 privacy + bounded OA1 + current retry combination

2026-09-05. Explicitly authorized one isolated combination candidate, no push/tag/release/main.
Version0.6.11 had no local tag/branch/worktree, all-ref matching commit, public snapshot or Host
vendor wheel at reservation. No network release/publication is performed; no claim of registry-wide
reservation. Branch feat/human-memory-0611-combination; fixed parents:
- privacy exact0.6.10 source02f4020103c3166ffc2360b79bf90f662905d96c;
- independently ACCEPTed OA1 af49f2a1aefd54b6d9292e582bbac3b30770bae1, doccb1409d;
- independently ACCEPTed retry0947c0110d0f20271587b6fb4893adddd0f70414, doca7a0027.

Production merged automatically; manual overlap is only additive architecture histories and the
artifact API test.0.6.11 root snapshot independently specifies0.6.10 exports plus the nine reviewed
OA1 exports; old JSON snapshots unchanged. Privacy history authority/capability/guards, clock,
source-only/selected-short, migration and frozen hash domains remain. No new protocol or threshold.

Necessary combination source selection:116PASS12.54s (reader/mixed/jobs/observation/zeroSQL rejection,
clock/retry/privacy history/analysis/short/publicgraph/API). The three documented inherited damaged-DB
early-refusal test failures remain in original source evidence; this selection does not claim those
tests green or rerun full suites. Public consumer source smoke subsequently passes seven stages:
actual failed-first/current-second reclaim→real deterministic Host no_mutation application, OA1
same-cut pagination/reopen/shared authority/clock expiry, int5 versus string5 actual rejection carrier,
plus unchanged privacy cold/before/after/direct-no-mutation/legacy and exact short/final-use controls.
First consumer fixture mistakenly bound requester to actor as deployment/household; actual public
audit rejected it. Corrected to the actual principal fields; original failure log preserved.

Frozen consumer oracle is scripts/combination_public_consumer.py plus unchanged privacy helper
scripts. No test imports, private SDK imports/SQL, provider/UI/native or expected-output harvesting.
The public manager.backend is used only as the existing DurableJobRepositoryPort supplied to the
official runner; it is not a new private storage dependency. Application applied and no_mutation
are separate assertions. Historical cost0 is explicitly price_provenance=unavailable. SDK carrier
is observed but Host production persistence is false, all_operations_recorded remains false.

Artifact gates after this source commit: two offline builds byte-identical; clean isolated exact
official Memory/Harness wheels; pip check and exact dependency versions; consumer helpers copied to ignored consumer-tools and executed from /tmp with -I/no PYTHONPATH; package source→wheel→installed complete bytes/
origins and old snapshot/artifact invariance manifest. Frozen069 and0610 bytes must remain exact.
Original six native files belong only to the earlier copy gate timestamp; this candidate does not
compare them against stale hashes or touch active userdata. No native or Host all-operation claim.

Source command:
```sh
.local-test-evidence/2026-09-05/0611-combination/devvenv/bin/python -I -m pytest -q --tb=short --show-capture=no tests/integration/test_operation_audit.py tests/integration/test_operation_audit_jobs.py tests/integration/test_operation_audit_mixed.py tests/unit/test_operation_audit_page.py tests/integration/test_operation_observation.py tests/unit/test_operation_observation.py tests/integration/test_retry_current_attempt.py tests/integration/test_public_recall_rejection.py tests/integration/test_public_recall_clock.py tests/integration/test_duplicate_source_forget.py tests/integration/test_duplicate_source_analysis.py tests/integration/test_duplicate_source_short.py tests/integration/test_twin_graph_view_v6.py tests/artifact/test_twin_graph_isolation.py tests/artifact/test_public_api_snapshot.py
```
Raw evidence root `.local-test-evidence/2026-09-05/0611-combination/`, permanently ignored.
Current artifact/installed result remains pending until the manifest/report below is recorded.


## Fixed artifact and owner installed result

Fixed source **d520765d160b10566539230806284d2bef364dfe**; later commits only record delivery docs.
Wheel: `.local-test-evidence/2026-09-05/0611-combination/build1/simple_harness_memory_sdk-0.6.11-py3-none-any.whl`
SHA256 **d290cbfceb98932735da229f5475713898338ddd7fb3ca498f20256a2d99b8e1**.
Independent build2 has identical bytes. Exact Harness0.7.2 source2b8428465cbd41032ba024a0b7199183161f5ecd,
wheel53bded3fea87168e5d2ad9e49fea5f99e1c1edb1d6077b2a52dd62716692f9ed.

Owner isolated installed consumer: **7 public stages PASS**, no source overlay or PYTHONPATH.
Consumer scripts were copied byte-for-byte from the fixed commit to ignored consumer-tools and run
with cwd/tmp; both SDK package roots and all213 inspected import origins are inside the newvenv.
Exact source→wheel→installed equality verified for **Memory72 + Harness151 files**, including
matching wheel inventory/distribution RECORD paths and METADATA/WHEEL.16 exact installed dependency
versions match runtime-dependencies.txt plus the two SDKs; pip check PASS. Other dependency metadata
hashes are recorded, not claimed as independently rebuilt third-party sources. uv's direct_url archive
hash field may be absent: this is recorded honestly; explicit --require-hashes install and complete
SDK bytes supply artifact provenance. No edited/native/Host venv consumed this candidate.

15 older JSON snapshots and frozen069 cf1490…/0610 ff73a1… wheels retain exact bytes. No live native
file is compared/read here. Original failure logs/DBs remain in their original leaves; the candidate
source consumer's initial requester-identity fixture failure is also preserved. Same committed source
API check4PASS0.17s; mypy4source PASS. Source116 and API4 overlap; do not sum counts.

| Ignored evidence under0611-combination/ | SHA256 |
|---|---|
| combination-manifest.json | c19df83a0c87a308b6e02534de0883378812d31cf716e0c59c3e38392b3633d6 |
| installed-public/result.json | 6eea7f15c5ac27b6f357bded2fc4d92a3e87c0c61567a916b8cee6980269df33 |
| installed-public.log | 214f21a3801ce1b2e5df873ba50400dec08e666ca766b771567e2bd54f74b062 |
| combination-source.log | b72332a6e753eb0e02c35c11195830137ac10be5065e2d0892f0989acb4bd75e |
| consumer-source-r1.log (original failure) | fca57388660f3ffd84b16f553fa5b69fa64188567e6bc2bd834c33cf5552e581 |

Reproducible build commands, from fixed clean source (choose NEW output paths when rerunning):
```sh
uv build --offline --no-sources --wheel --out-dir .local-test-evidence/2026-09-05/0611-combination/build1
uv build --offline --no-sources --wheel --out-dir .local-test-evidence/2026-09-05/0611-combination/build2
uv pip install --offline --no-sources --python .local-test-evidence/2026-09-05/0611-combination/venv/bin/python -r .local-test-evidence/2026-09-05/0611-combination/runtime-dependencies.txt
uv pip install --offline --no-deps --require-hashes --python .local-test-evidence/2026-09-05/0611-combination/venv/bin/python -r .local-test-evidence/2026-09-05/0611-combination/exact-wheels.txt
uv pip check --python .local-test-evidence/2026-09-05/0611-combination/venv/bin/python
```
Public consumer and identity commands, cwd/tmp (choose a NEW consumer output directory):
```sh
/Users/denny/projects/simple-harness-memory-sdk-0611-candidate/.local-test-evidence/2026-09-05/0611-combination/venv/bin/python -I /Users/denny/projects/simple-harness-memory-sdk-0611-candidate/.local-test-evidence/2026-09-05/0611-combination/consumer-tools/combination_public_consumer.py /Users/denny/projects/simple-harness-memory-sdk-0611-candidate/.local-test-evidence/2026-09-05/0611-combination/installed-public
/Users/denny/projects/simple-harness-memory-sdk-0611-candidate/.local-test-evidence/2026-09-05/0611-combination/venv/bin/python -I /Users/denny/projects/simple-harness-memory-sdk-0611-candidate/.local-test-evidence/2026-09-05/0611-combination/verify_candidate.py
```

Artifact bytes are fixed and sent to main. Dirac independent installed scoped review is pending;
underlying OA1/retry/privacy source leaves are already independently accepted. Host OA1 carrier
persistence/outbox, full-operation coverage, old malformed-job repair, latency and native product
acceptance remain separate. No push/tag/release, no change to frozen candidate bytes.
