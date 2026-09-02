"""Throwaway probe (read-only against repo): real ExecutionEvidenceIngress + CanonicalTaskScopeStore on a temp DB.
P1: terminal observer allocates next_sequence from ingested receipts while outbox rows are pending -> rows lost, gate passes.
P2: apply_mutation_plan accepts plan.run_id != run of evidence (cross-Run closure legal); no_mutation bumps revision.
P3: _reduce applies ops after task.complete (no transition validation)."""
import asyncio, json, sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/taiwan/PROJECTS/SimplaHarness/simple_harness/backend")
sys.path.insert(0, "/Users/taiwan/PROJECTS/SimplaHarness/simple_harness/backend/tests/task_scope")
import test_canonical_archive as fx  # reuse frozen fixtures
from deskpet.execution.evidence_ingress import ExecutionEvidenceIngress, TerminalWatermarkPending
from deskpet.task_scope.store import TaskScopeConflict
from deskpet.task_scope.protocol import canonical_hash

def execution(event_id, seq, kind, h, run_id="run-1"):
    d = fx._execution(event_id, seq, kind, h)
    d._raw["run_id"] = run_id; d._raw["disclosure_context"]["run_id"] = run_id
    d.run_id = run_id; d.disclosure_context = d._raw["disclosure_context"]
    d.evidence_hash = canonical_hash(d._raw)
    return d

def plan(plan_id, base, h, ops, run_id="run-1", outcome="mutate", closure_reason=None):
    d = fx._plan(plan_id=plan_id, base_revision=base, content_hash=h, operations=ops, outcome=outcome, closure_reason=closure_reason)
    d._raw["run_id"] = run_id; d._raw["disclosure_context"]["run_id"] = run_id
    d.run_id = run_id; d.disclosure_context = d._raw["disclosure_context"]
    d.plan_hash = canonical_hash(d._raw)
    return d

async def main():
    import os; base = os.environ.get("PROBE_BASE") or os.path.realpath("/private/tmp/claude-501/-Users-taiwan-PROJECTS-SimplaHarness/84cdd128-88f2-4c7d-9db9-64a64b8ed54e/scratchpad/spec-closure"); tmp = Path(tempfile.mkdtemp(prefix="spec-closure-", dir=base))
    db_path, store, h = await fx._ready(tmp)
    ingress = ExecutionEvidenceIngress(db_path)
    out = {}
    # ---- P1: race between outbox worker and terminal observer next_sequence ----
    await ingress.ingest(task_scope_id="scope-1", source_sequence=1, evidence=execution("prov-1", 1, "provider_invocation", h))
    with sqlite3.connect(db_path) as db:
        next_seq = db.execute("SELECT COALESCE(MAX(source_sequence),0)+1 FROM task_scope_execution_ingest_receipts WHERE run_id='run-1'").fetchone()[0]
    out["P1_observer_next_sequence_from_ingested_receipts"] = next_seq  # outbox still holds seq 2 (tool) and 3 (snapshot)
    term = await ingress.ingest(task_scope_id="scope-1", source_sequence=next_seq, evidence=execution("term-1", next_seq, "run_terminal", h))
    out["P1_terminal_watermark"] = {"durable": term.durable_source_sequence, "terminal": term.terminal_source_sequence}
    try:
        await ingress.ingest(task_scope_id="scope-1", source_sequence=2, evidence=execution("tool-2", 2, "tool_invocation", h))
        out["P1_late_row_seq2"] = "ACCEPTED"
    except TaskScopeConflict as e:
        out["P1_late_row_seq2"] = f"REJECTED:{e}"
    try:
        await ingress.ingest(task_scope_id="scope-1", source_sequence=3, evidence=execution("snap-3", 3, "context_snapshot", h))
        out["P1_late_row_seq3"] = "ACCEPTED"
    except TaskScopeConflict as e:
        out["P1_late_row_seq3"] = f"REJECTED:{e}"
    gate = await ingress.authorize_terminal("run-1")
    out["P1_terminal_gate_after_loss"] = {"durable": gate.durable_source_sequence, "terminal": gate.terminal_source_sequence, "verdict": "GATE PASSES while 2 Harness rows permanently lost"}
    # ---- P2: cross-Run closure plan (later Run submits plan for events of run-1) ----
    ops = [fx._operation("op-1", "decision.record", "README bumped to 1.2.0", "model_proposed", h)]
    r = await store.apply_mutation_plan(plan("plan-later", 1, h, ops, run_id="run-later"))
    out["P2_cross_run_plan"] = {"accepted": True, "committed_revision": r.committed_revision}
    r2 = await store.apply_mutation_plan(plan("plan-nomut", 2, h, [], run_id="run-later-2", outcome="no_mutation", closure_reason="closure_abandoned"))
    out["P2_no_mutation_bumps_revision"] = {"base": 2, "committed_revision": r2.committed_revision}
    # ---- P3: ops after task.complete ----
    r3 = await store.apply_mutation_plan(plan("plan-complete", r2.committed_revision, h, [fx._operation("c1", "task.complete", "done", "user_confirmed", h)]))
    r4 = await store.apply_mutation_plan(plan("plan-after-complete", r3.committed_revision, h, [fx._operation("s1", "plan.step.add", "more work", "model_proposed", h)]))
    with sqlite3.connect(db_path) as db:
        st = json.loads(db.execute("SELECT state_json FROM task_scope_canonical_revisions WHERE task_scope_id='scope-1' AND revision=?", (r4.committed_revision,)).fetchone()[0])
    out["P3_ops_after_task_complete"] = {"accepted": True, "status_after": st["status"], "revision": r4.committed_revision}
    # ---- P4: replay of an identical plan_id returns same receipt, provider-free ----
    r5 = await store.apply_mutation_plan(plan("plan-after-complete", r3.committed_revision, h, [fx._operation("s1", "plan.step.add", "more work", "model_proposed", h)]))
    out["P4_plan_id_replay_same_receipt"] = (r5 == r4)
    print(json.dumps(out, indent=1, ensure_ascii=False))

asyncio.run(main())
