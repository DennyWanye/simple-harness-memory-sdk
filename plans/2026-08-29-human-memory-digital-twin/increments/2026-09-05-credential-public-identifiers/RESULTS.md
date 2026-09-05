# Public identifier credential scan — source results

Date: 2026-09-05. Base: frozen0611 docHEAD323cbff (artifact d520765).
Oracle-first commit556551d; isolated successor tree only. Production change is
confined to core/evidence.py; no public DTO/hash/receipt/DDL/version change yet.

- Corrected red: 5 intended public-label failures, 34 other controls pass.
- Source gate: 160PASS/12.73s including new public source admission/history/
  suppression/reopen, evidence ingestion, audit scan, history visibility, recall
  rejection and history pre-admission zero-SQL gates.
- Ruff both changed Python files PASS; mypy evidence.py PASS.
- Actual original native0610 Host public factory/history page on copied current
  Host+Memory+Harness DB/WAL/SHM reproduces nested PrimaryReadError /
  PrimaryVisibilityError / evidence_credential_boundary_rejected.
- Same captured inputs with successor Memory source overlay: factory page and
  manager reopen both PASS, 8items (4USER/3assistant/1tool), containing actual
  original autumn USER and latest actual assistant. No new CREATE/RunStart or
  Provider call. The read-only settled-reader adapter uses actual public SDK
  Context and existing Host terminal event semantics, verified by actual Host
  terminal identity; runtime ingress/main identity guard is neither started nor
  overridden. This is copy/public-factory evidence, not native UI or installed.
- Ten original database/side-file hashes unchanged; copied Host S1/receipt/turn/
  terminal row digests and Harness run-event count unchanged after probes.

Initial test-authoring failures and corrected red retained. The first green
run exposed a test expectation error: public wrong-subject history returns a
nonvisible item with history_subject_mismatch rather than raising; corrected
to assert that exact existing contract. No product subject gate was changed.

Commands (repository root):
```sh
/Users/denny/projects/simple_harness/backend/.venv/bin/python -I -c 'import sys;sys.path[:0]=["src","."];import pytest;raise SystemExit(pytest.main(["-q","tests/integration/test_public_identifier_credential_boundary.py","tests/integration/test_evidence_ingestion_v5.py","tests/integration/test_audit_ledger_v5.py","tests/integration/test_history_visibility.py","tests/integration/test_public_recall_rejection.py","tests/integration/test_history_source_pre_admission.py","--tb=short"]))'
/Users/denny/projects/simple-harness-memory-sdk/.venv/bin/ruff check src/simple_harness_memory/core/evidence.py tests/integration/test_public_identifier_credential_boundary.py
/Users/denny/projects/simple-harness-memory-sdk/.venv/bin/mypy --follow-imports=silent src/simple_harness_memory/core/evidence.py
```

Raw evidence is ignored at .local-test-evidence/2026-09-05/credential-public-identifiers/:
source-red.log, source-red-r2.log, source-green-r1.log, source-adjacent.log,
page-native0610-red-result.json, page-source-green-result.json, native_page_probe.py,
native-input-manifest.json. Machine SHA index: source-evidence-index.json.

Independent fixedsource review pending, then one authorized version0.6.12
build/installed gate. 0610/0611 bytes, original userdata and main remain untouched.
Other ordinary-word false positives are outside this finite vocabulary repair.
System SQLite3.51 mode=ro issue stays separate; native3.50.4 controls pass.
