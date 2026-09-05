# Authorized 0.6.6 combined candidate — 2026-09-05

User authorized a new isolated candidate combining history a96a5008, public clock16dc707 and
scoped pre-candidate rejection30743bb. No push/tag/main, no overwrite of frozen0.6.3/0.6.5 wheels,
no Host native environment changes. Local branch/tag/artifact checks found no0.6.6 allocation.
Scope is library packaging and deterministic consumers; no401/full-suite/provider/native claim.

Oracle fixed before candidate version/build:
- Preserve all five history root DTO exports and full reverse-source suppression semantics, including
  cold USER allow, ingested-but-unanalyzed allow, memory-only forget -> original USER deny,
  unrelated USER allow, reopen deny. SDK-generated content never fills expected results.
- Preserve optional trusted builder clock and default wall-clock behavior; malformed clock rejected.
- Preserve TypedRecallRejectionV1 and strict integer harness_protocol=4; int5 produces
  typed_recall_protocol_unsupported with invocation-bound protocol receipt; string5 is type invalid.
  Existing candidate-stage exceptions remain without fabricated admission receipts.
- Public exports are the frozen0.6.5 root plus exactly five history exports. Preserve every historical
  snapshot JSON, add0.6.6 JSON, keep existing schema/protocol/hash/thresholds unchanged.
- Production intersections are additive Manager/Protocol/root exports/sqlite methods. Initial
  cherry-pick conflicts were documentation-only; preserve newer history/main facts and record
  combined candidate explicitly. No API semantic conflict found at integration inspection.
- Review a clean source commit before final build. Build with hatchling1.32.0 and fixed
  SOURCE_DATE_EPOCH315532800, no local uv source substitution. Use frozen Harness0.7.2 wheel
  SHA53bded3fea87168e5d2ad9e49fea5f99e1c1edb1d6077b2a52dd62716692f9ed.
- Install exact wheels into a new venv; run outside source with -I/noPYTHONPATH; assert SDK module
  provenance and source/wheel/installed bytes, metadata, pip check. Execute real public cold->
  ingest->memory-only-forget->reopen plus trusted clock and protocol rejection. No product SQL or
  private backend access in the installed consumer. Raw logs/DB/manifests remain ignored.

Historical build-and-release.md fixed0.6.2/oldHarness and the metadata writer's0.6.1 literal are
historical inputs, superseded for this explicitly authorized candidate. Keep historical receipt
files unchanged. This candidate records its exact clean source, wheel and input identity in ignored
metadata and a concise result journal; no full historical CI publisher/matrix acceptance is implied.

Known independent-short boundary (not added to this candidate): `ShortHorizonRecallHit` from
standalone `recall_short_horizon` has chunk_ref/content_hash and a result audit_id, not a typed
result/item binding. No current public API resolves that tuple for historical current visibility.
Host must not read SDK SQL or fabricate a typed binding. A follow-up additive
HistoryShortHorizonBinding(audit_id,chunk_ref,content_hash) could reuse this batch: verify the owned
successful recall audit's selected opaque chunk hash plus eligible content hash, then current
chunk existence/expiry/classification/disclosure/evidence/entity reverse suppression. Unknown,
nonselected, cross-subject, changed hash, expired and suppressed inputs deny. No second authority
or old audit-as-current-grant. This gap is separate from typed-short/history evidence support.

Source verification before final wheel build (this combined tree, Host Python3.12 read-only driver):

```sh
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_history_visibility.py tests/integration/test_public_recall_clock.py tests/integration/test_public_recall_rejection.py tests/integration/test_memory_062_schema_cutover.py tests/artifact/test_public_api_snapshot.py -q
#64 passed: history24+clock3+rejection30+schema3+API4.
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_suppression_v5.py tests/integration/test_typed_recall_v6.py -q
#43 passed.
PYTHONPATH=src:. /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest tests/integration/test_cognitive_mutation_repository_v5.py -k 'suppression or suppressed or revise or classification' -q
#23 passed,55 deselected. Total distinct source tests130.
```

Exact Harness0.7.2-aware mypy for history DTO/helper, recall and consumer:4 source files passed;
consumer/API/helper Ruff passed. A typing-only cast of the existing request binding-hash list
fixes JSON list invariance without altering content/order/hash. Affected history24 passed again,
not counted as extra scenarios. Initial README candidate-version assertion failure and preliminary
typecheck errors are retained in local work history; no full-suite/native/provider verdict.

Planned build/install commands (run only from clean reviewed source):

```sh
SOURCE_DATE_EPOCH=315532800 uv build --wheel --no-sources --offline --python /Users/denny/projects/simple_harness/backend/.venv/bin/python --out-dir .local-test-evidence/2026-09-05/combined-066/build1
uv pip install --offline --python .local-test-evidence/2026-09-05/combined-066/venv/bin/python .local-test-evidence/2026-09-05/combined-066/build1/simple_harness_memory_sdk-0.6.6-py3-none-any.whl
# Execute with -I from an external working directory, using the absolute script/output paths:
.local-test-evidence/2026-09-05/combined-066/venv/bin/python -I scripts/verify_history_candidate.py --output .local-test-evidence/2026-09-05/combined-066/installed-public
```

Consumer expected values are fixed independently: cold/ingested/materialized[true,true],
memory-only-forget/reopen[false,true], typed payload concise, trusted checked_at20/101,
int5 unsupported and string5 invalid invocation-bound protocol receipts, expired page rejected.
The consumer asserts every loaded SDK module is in the isolated venv. Final wheel identity and
source/wheel/installed byte comparison are recorded after actual execution, not predicted here.

## Exact artifact delivered — 2026-09-05

- Reviewed clean source: `9ec59438663272cd9e208de5d2e7b85bf0f40a5a`.
- Wheel: `.local-test-evidence/2026-09-05/combined-066/build1/simple_harness_memory_sdk-0.6.6-py3-none-any.whl`.
- SHA256: `381d85437537ae1f58f04b84e8332b0774d1e3aff2c6529b3824126071135361`.
- Independent combined-source/consumer review ACCEPT before build, no new P0/P1 blocker.
- One clean deterministic wheel build. Offline installation first lacked cached NumPy; installed
  ordinary registry dependencies using exact versions from the source-test runtime constraints,
  preserving both local exact Memory/Harness wheels. This was an environment cache miss, not a
  product failure; the failed offline resolver log is retained. Host native venv was not modified.
- Installed public consumer PASS from `/private/tmp` with isolated venv Python `-I`: cold USER,
  ingested without analysis, public mutation/typed recall, memory-only forget, unrelated USER
  control, reopen, int5 unsupported/string5 invalid protocol witnesses and clock-expired paging.
-77 imported SDK modules all belong to this new env. Complete Memory63/Harness151 package files
  match committed source, exact wheel and installed bytes. Harness source is
  `2b8428465cbd41032ba024a0b7199183161f5ecd`, wheel SHA53bded3fea87168e5d2ad9e49fea5f99e1c1edb1d6077b2a52dd62716692f9ed.
- `uv pip check` passed16 packages. Original0.6.3 wheel6b20ae5b... and0.6.5 wheel0977159d...
  were rehashed unchanged; their source worktrees/main were not merged or modified.

Actual installed command (external cwd; noPYTHONPATH):

```sh
/Users/denny/projects/simple-harness-memory-sdk-066-candidate/.local-test-evidence/2026-09-05/combined-066/venv/bin/python -I /Users/denny/projects/simple-harness-memory-sdk-066-candidate/scripts/verify_history_candidate.py --output /Users/denny/projects/simple-harness-memory-sdk-066-candidate/.local-test-evidence/2026-09-05/combined-066/installed-public
```

For replay choose a fresh output directory because the script deliberately refuses an existing DB.
Exact source tests130 are distinct source scenarios; the7 named installed stages are a separate
real public consumer lifecycle, not added to that test count. No full1157/401/multi-platform/native
suite rerun; no performance threshold claim. Host/native integration and independent-short exact
carrier remain outside this wheel's completed scope. Follow-up documentation commits do not
change the build source or artifact bytes.

Ignored evidence SHA256:
- installed-identity.json:17900fc9619401db5cf83aed4eb3d0c77e2e352ef9f8589be4b1879d3570a1ae
- installed-public.log:c016a87c4bdb7f90cd6107046efe243df2c224d2dd93b530c6d039d5c9ba66bc
- source-focused.log:ce8dbec1cda220cbc8803a086cbaeb7eaa2795ac68034c6f9c44fc542170263d
- adjacent-recall.log:ead1532d392816003e1bd232da3c6ba2da8739fe3c348f4fbdfd9e01db184332
- adjacent-mutation.log:1e51ba7460a91be857ec9b20cb76596dc546fd523dd1b19a64edd83b2e61ea4d
- pip-check.log:4749bcf18812bb18f602216d1a1e90e276167fb1d8353757dd7676f23c55fe19

Retrospective: merge intersections were documentation/version identity, not a reason to repeat
approval or full suites; exact dependency-aware typing caught one JSON variance annotation and
avoided pretending a tool-only environment was the product runtime. New short carrier work stays
in a separate candidate instead of changing an already delivered wheel.

VERDICT: COMPLETE — authorized0.6.6 isolated combined wheel/source/public-consumer scope only;
no Host/native/program release verdict or machine-gate receipt.
