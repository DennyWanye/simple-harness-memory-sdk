"""Deterministic micro-spike (no provider): (A) accepted plan with 2 operations -> finalize outcome on wheel 0.6.0;
(B) 1-operation plan -> applied; (C) after runner, which user-observable read hangs/returns."""
import asyncio, json, sys, time, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import spike_value_last_hop as H  # helpers only (main guarded)
from simple_harness.runtime import MemoryAnalysisResult, MemoryMutationPlan, MemoryMutationPlanOutcome
from simple_harness_memory import MemoryManager
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.jobs import DurableMemoryJobRunner
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.embedders.mock import HashEmbedder
from simple_harness.runtime import PrivacyClass
SUBJECT = H.SUBJECT
class FakeExecutor:
    def __init__(self, backend, authority, proposals_by_item):
        self.backend, self.authority, self.proposals = backend, authority, proposals_by_item; self.calls = 0; self.plans = {}
    async def analyze_memory(self, request):
        self.calls += 1
        ops = []
        for ref in request.ordered_evidence_refs:
            rec = await self.backend.read_ingested_evidence(ref.evidence_id)
            env, rc = rec.envelope, rec.admission_receipt
            for i, p in enumerate(self.proposals[H.item_id_for(env)], start=1):
                ops.append(H.compile_operation(p, H.derive_span(env, rc, p["exact_quote"], f"span-{H.item_id_for(env)}-{i}")))
        async with self.backend.connection.execute("SELECT revision FROM analysis_apply_heads WHERE principal_id=?", (request.subject,)) as c:
            row = await c.fetchone()
        base = int(row[0]) if row else 1
        plan = MemoryMutationPlan(plan_id=f"plan-{request.job_id[-12:]}", run_id=request.run_id, turn_id=H._stable_id("analysis-batch-turn", request.job_id), subject=request.subject,
            base_revision=base, outcome=MemoryMutationPlanOutcome.MUTATE, operations=tuple(ops), disclosure_context=request.disclosure_context,
            evidence_refs=request.ordered_evidence_refs, idempotency_key=request.idempotency_key)
        self.plans[request.job_id] = plan
        result = MemoryAnalysisResult(job_id=request.job_id, run_id=request.run_id, request_hash=request.request_hash, provider_response_id=f"fake-{request.job_id[-8:]}",
            structured_result=plan.to_json(), input_tokens=1, output_tokens=1, cost_microunits=1, latency_ms=1)
        return self.authority.issue(request, result)

async def scenario(name, turns, proposals, do_reads):
    db = Path(__file__).resolve().parent / f"multiop_{name}_{int(time.time()*1000)}.db"
    delivery = H.HostDeliveryAuthority()
    manager = await MemoryManager.build_human_memory_v7(db, analysis_delivery_authority=delivery, evidence_authority=None,
        classification_policy=InformationClassificationPolicy(policy_id="memory-classification-policy", policy_version="1", authority_ref="memory-policy-registry:classification/v1", required_privacy_class=PrivacyClass.PERSONAL, required_information_attributes=()),
        short_horizon_embedder=HashEmbedder(32), allow_development_embedder=True)
    backend = manager.backend; backend._evidence_authority = H.HostEvidenceAuthority(backend)
    try:
        for i, (dk, text) in enumerate(turns, start=1):
            env, rc = H.host_turn_envelope(dk, text, policy="credential-filter/v1", run_id=f"run-{name}-{i}")
            await manager.ingest_committed_evidence(env, rc)
        ex = FakeExecutor(backend, delivery, proposals)
        runner = DurableMemoryJobRunner(repository=backend, executor=ex, delivery_authority=delivery, config=H.CONFIG, worker_id="w1", now=time.time)
        outs = []
        for _ in range(len(turns) + 1):
            try:
                outs.append(str(await asyncio.wait_for(runner.run_once(), 30)))
            except Exception as exc:  # noqa: BLE001
                outs.append(f"{type(exc).__name__}:{exc}")
        async with backend.connection.execute("SELECT state FROM jobs") as c: jobs = [r[0] for r in await c.fetchall()]
        async with backend.connection.execute("SELECT state FROM analysis_batches") as c: batches = [r[0] for r in await c.fetchall()]
        async with backend.connection.execute("SELECT decision_id, operation_id FROM decision_records ORDER BY decision_id") as c: decs = [(r[0][-10:], r[1]) for r in await c.fetchall()]
        plan_ops = [[op.operation_id for op in p.operations] for p in ex.plans.values()]
        print(f"[{name}] run_once={outs}; jobs={jobs}; batches={batches}; plan op order={plan_ops}; decision_records ORDER BY decision_id={decs}", flush=True)
        if do_reads:
            for label, coro in (("count heads", H.count(backend, "SELECT COUNT(*) FROM cognitive_memory_heads")),
                                ("read_outbox placeholder", manager.read_outbox(principal=MemoryPrincipal(SUBJECT, SUBJECT, SUBJECT, "s"), states=("pending",))),
                                ("read_occurrence_inbox placeholder", manager.read_occurrence_inbox(principal=MemoryPrincipal(SUBJECT, SUBJECT, SUBJECT, "s"))),
                                ("recall_short_horizon placeholder", manager.recall_short_horizon(principal=MemoryPrincipal(SUBJECT, SUBJECT, SUBJECT, "s"), query="周报", disclosure_context=H._disclosure("run-x"), limit=8, now=time.time()))):
                try:
                    r = await asyncio.wait_for(coro, 15)
                    summary = r if isinstance(r, int) else (getattr(r, "entries", None) is not None and [(e.topic if hasattr(e, "topic") else e.outcome) for e in r.entries]) or type(r).__name__
                    print(f"  [{name}] {label}: {summary}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{name}] {label}: {type(exc).__name__}: {exc}", flush=True)
            host = MemoryPrincipal(deployment_id="deskpet-local", household_id="deskpet-local-household", actor_id=SUBJECT, session_id="s")
            for job_id, plan in ex.plans.items():
                try:
                    res = await asyncio.wait_for(manager.apply_memory_mutation_plan(principal=host, scope=MemoryScope.personal(SUBJECT), plan=plan), 30)
                    print(f"  [{name}] apply {job_id[-8:]}: {res.outcome} {getattr(res,'reason_code',None)}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{name}] apply {job_id[-8:]}: {type(exc).__name__}: {exc}", flush=True)
            print(f"  [{name}] heads after apply:", await H.count(backend, "SELECT COUNT(*) FROM cognitive_memory_heads"), "analysis_head:", await H.count(backend, "SELECT revision FROM analysis_apply_heads"), "cognitive_head:", await H.count(backend, "SELECT revision FROM cognitive_apply_heads"), flush=True)
    finally:
        await asyncio.wait_for(manager.close(), 15)

async def main():
    sem2 = [{"operation_id": "remember-location-hangzhou-binjiang", "memory_type": "semantic", "exact_quote": "我住在杭州滨江", "reason_code": "f", "semantic": {"subject_entity": "user", "predicate": "residence_location", "object_value": "杭州滨江"}},
            {"operation_id": "remember-python-backend", "memory_type": "semantic", "exact_quote": "平时主要用 Python 写后端服务", "reason_code": "f", "semantic": {"subject_entity": "user", "predicate": "primary_technical_work", "object_value": "Python"}}]
    await scenario("two-ops", [H.TURNS[1]], {"dk-turn-0002": sem2}, do_reads=False)
    await scenario("two-ops-swapped-ids", [H.TURNS[1]], {"dk-turn-0002": [dict(sem2[0], operation_id="op-b"), dict(sem2[1], operation_id="op-a")]}, do_reads=False)
    await scenario("two-ops-sorted-ids", [H.TURNS[1]], {"dk-turn-0002": [dict(sem2[0], operation_id="op-a"), dict(sem2[1], operation_id="op-b")]}, do_reads=False)
    await scenario("one-op-reads", [H.TURNS[0]], {"dk-turn-0001": [{"operation_id": "op-1", "memory_type": "prospective", "exact_quote": "从今以后每周五提醒我提交周报", "reason_code": "r", "prospective": {"action": "提醒我提交周报", "trigger_at_iso": "2026-09-04T09:00:00+08:00", "timezone": "Asia/Shanghai"}}]}, do_reads=True)
    return 0
if __name__ == "__main__":
    try: code = asyncio.run(main())
    except BaseException: traceback.print_exc(); code = 1
    sys.exit(code)
