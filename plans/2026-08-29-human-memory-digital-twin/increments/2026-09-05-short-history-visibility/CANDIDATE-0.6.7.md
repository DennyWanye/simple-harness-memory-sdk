# Authorized 0.6.7 candidate — 2026-09-05

User/main explicitly allocated0.6.7 to reviewed clean e19161ba718836fdd9a8555bfc0de0aece368198.
This independent tree/branch freezes version/root snapshot and a real installed consumer only;
no SDK behavior changes, no push/tag/release/main/Host native environment changes. Keep all old
snapshot JSON and sealed0.6.6 wheel381d8543 unchanged. Baseline121 source tests/review accepted;
user explicitly says not to rerun that suite. No agent/provider/model load or original401 rerun.

Oracle before candidate edits/build: root0.6.7 == exact frozen0.6.6 sorted exports plus one
HistoryShortHorizonBinding; retain all prior history/clock/rejection capabilities. Add0.6.7 JSON,
no old JSON edits or protocol/hash/threshold changes. ReadAGENTS check: no SDK/ancestorAGENTS;
read architecture/index and packaging runbook; previous historical publisher literals remain
historical, not candidate authorities. No local0.6.7 branch/tag/artifact allocation found before
creating this candidate. Execution is serial because freeze/build/install depend on exact bytes.

Installed public consumer assertions, independently fixed before implementation:
1. Retain existing cold USER->ingest->typed recall/exact replay->memory-only forget->reopen;
   trustedclock backdated expiry and int5/string5 protocol rejection assertions unchanged.
2. In another real SQLite DB, twelve authorized Host conversation registrations yield exactly
   two standalone short hits (newest ten causal groups remain in working context). Verify their
   actual content SHA and audit IDs; exact real triples both visible. No source/test/private SQL
   imports at runtime; explicit synthetic Host admission callbacks are test inputs, not mocked SDK.
3. Wrong audit/chunk/content hash and eligible-but-unselected triple deny. Wrong subject/current
   disclosure denies; clock reaching exact short expiry denies then return trusted clock to fixture
   baseline in a separate observation (not an old snapshot replay) before suppression tests.
4. Materialize one real semantic memory from the first short source through public mutation.
   Only MEMORY(memory_id) forget: first short and original evidence/typed item deny, independent
   second short/evidence remains visible. Reopen keeps this exact state. Next EVIDENCE(second)
   suppression denies remaining short, and a second reopen retains deny. No directive copied into
   other scopes to force the expected result; no product outputs used to synthesize oracle values.
5. Build once offline from clean committed reviewed source with SOURCE_DATE_EPOCH315532800.
   Exact Harness0.7.2 wheel53bded3f remains input. New isolated venv, SDK installation from exact
   local wheels (offline cached dependency pins), consumer with -I from external cwd/noPYTHONPATH.
   Compare every Memory/Harness package file with committed source, wheel and installed bytes;
   verify metadata/direct_url/module provenance/pipcheck and record ignored manifest and SHA.

Required checks: root snapshot/version4 tests only, consumer lint/typing, source consumer smoke
before final build, bounded review of consumer/version/snapshot delta; then installed smoke and
byte identity. Review already accepted product e19161ba remains inherited evidence, not a claim
that this new wheel has already passed. Test results/commands and DoD are appended after actual
execution. No machine-gate or program completion claim.

Pre-build checks: root/version4 tests PASS; new public short consumer source preflight11 stages
PASS (exact selection, forged/unselected/subject/disclosure, expiry, mixed typed/evidence,
memory-only forget/reopen, source forget/reopen). Legal full principal registration was added
through public register_principal_owner after preflight identified a subject-placeholder setup
omission; no product code changed. Consumer mypy uses MYPYPATH=src for this candidate's new root
symbol and the exact Harness-aware dependency interpreter; this is source typing only, never
installed runtime PYTHONPATH. Prior121 source cases intentionally not rerun.

## Frozen artifact delivered — 2026-09-05

- Build source `fa6badd086d089e3e1752df45993ce0ccba98377`, clean before one offline build.
- Wheel `.local-test-evidence/2026-09-05/candidate-067/build1/simple_harness_memory_sdk-0.6.7-py3-none-any.whl`.
- Wheel SHA256 `7dd224c29923ab1346a78bb8529d9426559bb1e3a38b8c0964f57cc8687e9c3d`.
- Manifest `.local-test-evidence/2026-09-05/candidate-067/combination-manifest.json`, SHA256
  `f3ad2e1b4a5347bd7f58e42b6fff08dbd38d52fdaa65d8021b270c913dea590c`.
- Dirac independent prebuild delta ACCEPT of this exact source (consumer/version/snapshot);
  reviewed short product e19161ba inherited unchanged except version. Review report:
  `/Users/denny/projects/simple_harness-primary-api/.local-test-evidence/2026-09-05/memory-067-delta-review/REVIEW.md`.
- Source4 API tests, consumer mypy/Ruff and new source-public11 stages passed; user-directed121
  baseline not rerun. Final installed consumer18 stages = retained7 + short11, PASS with real
  SQLite/public Manager and synthetic trusted Host input DTOs. No private product SQL/mocked SDK.
- New venv Python3.12.13, explicit exact local Memory0.6.7/Harness0.7.2, fully offline cached
  dependency install. External cwd `/private/tmp`, `env -u PYTHONPATH -u PYTHONHOME ... -I`.
  78 imported SDK modules all in this env. Complete Memory64/Harness151 package file inventories
  and every source/wheel/installed byte matched. Distribution metadata/version/direct_url exact
  local paths checked; `uv pip check`16 packages compatible. All old snapshot JSON unchanged.
- uv leaves `direct_url.archive_info` empty even with hash-locked installation. Initial verifier
  wrongly required this optional metadata; retained both failed logs, then corrected the verifier
  to report absent hash honestly. Both SDKs were explicitly reinstalled from the SAME wheels with
  `--offline --no-deps --require-hashes` using exact-wheels.txt. No wheel rebuild/overwriting.
  Post-install full package/metadata byte equality supplies exact tested-code continuity; no
  duplicate behavioral run is claimed. Manifest records empty archive_info and hash-lock input.
- Old0.6.6 wheel rehashed `381d85437537ae1f58f04b84e8332b0774d1e3aff2c6529b3824126071135361`.
  Host/native env, main, tags/releases untouched. Carver and main directly notified with exact
  artifact and manifest identities immediately after checks; Host v2 wiring uses a separate tree.

Commands (candidate cwd unless noted):

```sh
SOURCE_DATE_EPOCH=315532800 uv build --wheel --no-sources --offline --python /Users/denny/projects/simple_harness/backend/.venv/bin/python --out-dir .local-test-evidence/2026-09-05/candidate-067/build1
uv pip install --offline --no-deps --require-hashes --python .local-test-evidence/2026-09-05/candidate-067/venv/bin/python -r .local-test-evidence/2026-09-05/candidate-067/exact-wheels.txt
# Run from /private/tmp; choose a NEW output directory for replay:
env -u PYTHONPATH -u PYTHONHOME /Users/denny/projects/simple-harness-memory-sdk-067-candidate/.local-test-evidence/2026-09-05/candidate-067/venv/bin/python -I /Users/denny/projects/simple-harness-memory-sdk-067-candidate/scripts/verify_history_candidate.py --output /Users/denny/projects/simple-harness-memory-sdk-067-candidate/.local-test-evidence/2026-09-05/candidate-067/installed-public
uv pip check --python .local-test-evidence/2026-09-05/candidate-067/venv/bin/python
```

Do not rerun the build command into this sealed build1. Replay the installed consumer with fresh
DB/output paths instead. BUILD_INFO.txt records real build start/end UTC and fixed source epoch.
Source/build/install/consumer/identity logs and raw DB remain ignored. Key local evidence SHA256:
- `build1/BUILD_INFO.txt`: `a1140fc4484ec575aa648d12508e299548edf2494fa3ca4b9de361eb695f8212`.
- `build1/SHA256SUMS`: `2ae77e3873dd7a63c58bed9ace188b2b4ad3fe9925311ad53b4973f48def57c9`.
- `installed-public/public-smoke.json`: `ea607ba6a2425053ddf90e0ae8a7198ae4b173e8e8dce9a0ff0676f96c3928ec`.
- `installed-public.log`: `35718b3690d341d74cb016c5ceaa66337ff9d51b3e769cb9d47b0b688216f13b`.
- `installed-bytes-r3.log`: `802e7815806ede0dfcf191c22f061f4ce07c6cfdbc11ca5adfcbc70c3edc4245`.
- `source-continuity.json`: `dc3ad7f2b95e107b406c64c78bb6340ff8599c144266624cb70382332538166a`.
- `exact-wheels.txt`: `3317e1b7500daaf1ef65a53167e9d3731309eba3c54420a035069a9b456c0faa`.
- `install-hash-locked.log`: `767ea9265d8cf9d2c0c611e7b27720f675304c01858467eee0e0127297108cdc`.
- `pip-check.log`: `60bb3d148b7cb295c95a6126be8bf7ce8836d6e6ba8cddfbf28025d115b0d3e6`.

Remaining boundaries: SDK candidate/library consumption is proven; real Host conversation source
registration and nextProvider/history UI integration are separate. No claim that Host already has
short lane data. No public model/provider/UI/performance/full401/program completion verdict.

Retrospective: reusing the reviewed product and restricting testing to packaging/public consumers
avoided repeating121 tests. The local CLI review connection timed out; it was stopped when Dirac
became available, preventing duplicate audits. Optional installer metadata is not evidence of a
product failure; direct source/installed byte comparison and explicit hash-locked install are the
actual provenance checks. No new user confirmation was needed.

VERDICT: SHIPPED — isolated0.6.7 candidate wheel/public-consumer scope only, no release or program
verdict — 2026-09-05 — tested source fa6badd086d089e3e1752df45993ce0ccba98377.
