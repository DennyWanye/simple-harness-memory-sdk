# Testcase challenge iteration 09 — gate metadata schema alignment

- Verdict: PASS
- Trigger: the first fresh gate run proved that updated `attach-evidence` accepts only the fixed identity envelope
  (`root_run_id` / optional `session_id`); wheel hashes are frozen business facts, not top-level evidence identity fields.
- Correction: keep `root_run_id` as the required run identity and require both exact wheel SHA-256 values as named
  business facts. No testcase, fixture, runner, product behavior, candidate identity or acceptance condition changed.
- Evidence retention: the superseded `gate-run-20260901` and its successful public execution remain intact; a new run is
  initialized from the corrected, compiled manifest. Historical PASS is not imported into the new run.
