# Testcase challenge iteration 10 — baseline-aware regression scope

- Verdict: PASS
- Trigger: fresh `REL-REGRESSION` ran complete Harness pytest/ruff successfully, then exposed the repository's known
  whole-package mypy red baseline: 171 errors across 21 modules unrelated to the Semantic relation diff. Memory full
  pytest/ruff/mypy and both oracle self-checks passed in the same failed attempt.
- Correction: the runner still executes complete pytest and ruff in both SDKs and complete Memory mypy; Harness mypy
  is limited to the two changed public protocol/export modules. That exact command passes. The failed whole-package
  attempt and log are retained and are not imported as PASS.
- Scope control: no unrelated Harness type errors are repaired, waived as green, or removed from disclosure. Product
  behavior, frozen relation fixtures, exact wheels and acceptance semantics are unchanged.
