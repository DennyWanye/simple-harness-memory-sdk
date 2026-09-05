"""S5B-AC-2: IR-02/03 regressions with durable results and real materialization."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import MemoryAnalysisRequest, MemoryAnalysisResultEnvelope

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.jobs import WorkerRunOutcome

from .test_durable_memory_jobs_v5 import _result_envelope
from .test_memory_061_core import (
    WORKER_CONFIG,
    _build_pipeline,
    _evidence,
    _HostEvidenceAuthority,
    _HostExecutor,
    _ingest,
    _materialization_snapshot,
    _rows,
)


class _FactExecutor(_HostExecutor):
    """Scripted provider: one independent fact per admitted turn, fixed on delivery."""

    def __init__(self) -> None:
        super().__init__(())
        self.provider_calls = 0

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        if (request.request_hash, request.attempt) not in self.deliveries:
            self.provider_calls += 1
        evidence_id = request.ordered_evidence_refs[0].evidence_id
        predicate, value = (
            ("color", "blue") if evidence_id == "evidence-1" else ("drink", "green tea")
        )
        self.ops = ({
            "operation_id": f"fact-{evidence_id}", "evidence_id": evidence_id,
            "predicate": predicate, "object_value": value,
        },)
        return await super().analyze_memory(request)


@pytest.mark.parametrize("point", ["job.apply.before_commit", "job.apply.after_commit"])
async def test_later_turn_cannot_invalidate_recoverable_analysis(
    tmp_path: Path, point: str,
) -> None:
    """IR-02: two accepted facts/heads and exactly two calls after fault + new turn."""
    clock = [20.0]
    fired = False

    def fault(candidate: str) -> None:
        nonlocal fired
        if candidate == point and not fired:
            fired = True
            raise RuntimeError("transient apply failure")

    path = tmp_path / "recovery.db"
    executor = _FactExecutor()
    authority = _HostEvidenceAuthority()
    manager, runner = await _build_pipeline(
        path, executor, evidence_authority=authority, now=lambda: clock[0], fault_injector=fault,
    )
    try:
        await _ingest(manager, _evidence(1, text="我喜欢蓝色"), authority)
        with pytest.raises(RuntimeError, match="transient apply failure"):
            await runner.run_once()
        saved_result = await _rows(manager, "SELECT result_json,result_hash FROM analysis_batches")
        assert executor.provider_calls == 1
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [
            ("result_committed" if point.endswith("before_commit") else "audit_pending",)
        ]
        await _ingest(
            manager, _evidence(2, run_id="run-2", text="我喜欢绿茶"), authority,
        )
        raw = await _rows(manager, "SELECT evidence_id,envelope_hash FROM evidence_envelopes")
        # The next background tick occurs BEFORE the first lease expires (original repro).
        await runner.run_once()
    finally:
        await manager.close()

    clock[0] = 31.0
    manager, runner = await _build_pipeline(
        path, executor, evidence_authority=authority, now=lambda: clock[0],
    )
    try:
        # Reclaim saved result, then process the later turn. No sleeps or provider retries.
        for _ in range(3):
            await runner.run_once()
        receipts = await _rows(
            manager, "SELECT application_receipt_json FROM analysis_batches ORDER BY rowid",
        )
        assert [json.loads(str(row[0]))["validation_status"] for row in receipts] == [
            "accepted", "accepted",
        ]
        assert await _rows(manager, "SELECT COUNT(*) FROM accepted_analysis_plans") == [(2,)]
        snapshot = await _materialization_snapshot(manager)
        assert snapshot["heads"] == snapshot["revisions"] == 2
        assert snapshot["analysis_head"] == snapshot["cognitive_head"] == [(3,)]
        assert await _rows(
            manager, "SELECT DISTINCT evidence_id FROM cognitive_evidence_spans ORDER BY 1",
        ) == [("evidence-1",), ("evidence-2",)]
        for plan_json, result_json in await _rows(
            manager, "SELECT p.plan_json,b.result_json FROM accepted_analysis_plans p "
            "JOIN analysis_batches b ON b.batch_id=p.batch_id",
        ):
            assert json.loads(str(plan_json)) == json.loads(str(result_json))["structured_result"]
        assert await _rows(manager, "SELECT state,attempt_count FROM jobs") == [
            ("applied", 1), ("applied", 1),
        ]
        assert executor.provider_calls == executor.calls == 2
        assert executor.observed_heads == [1, 2]
        assert await _rows(
            manager, "SELECT result_json,result_hash FROM analysis_batches ORDER BY rowid LIMIT 1",
        ) == saved_result
        assert await _rows(
            manager, "SELECT evidence_id,envelope_hash FROM evidence_envelopes",
        ) == raw
        assert await runner.run_once() is WorkerRunOutcome.IDLE
        assert await _materialization_snapshot(manager) == snapshot
    finally:
        await manager.close()


async def test_no_mutation_reason_survives_audit_pending_recovery(tmp_path: Path) -> None:
    clock = [20.0]

    def fault(point: str) -> None:
        if point == "job.apply.after_commit":
            raise RuntimeError("restart before audit")

    payload: dict[str, JsonValue] = {
        "outcome": "no_mutation", "operations": [], "closure_reason": "model_no_change",
    }
    executor = _NoMutationExecutor(payload)
    path = tmp_path / "no-mutation-recovery.db"
    manager, runner = await _build_pipeline(
        path, executor, now=lambda: clock[0], fault_injector=fault,
    )
    try:
        await _ingest(manager, _evidence(1))
        with pytest.raises(RuntimeError, match="restart before audit"):
            await runner.run_once()
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [("audit_pending",)]
        saved = await _rows(manager, "SELECT plan_json,plan_hash FROM accepted_analysis_plans")
    finally:
        await manager.close()
    clock[0] = 31.0
    manager, runner = await _build_pipeline(path, executor, now=lambda: clock[0])
    try:
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        assert await _rows(
            manager, "SELECT plan_json,plan_hash FROM accepted_analysis_plans",
        ) == saved
        assert json.loads(str(saved[0][0])) == payload
        assert executor.calls == 1
        assert await _rows(manager, "SELECT COUNT(*) FROM cognitive_memory_heads") == [(0,)]
        assert await _rows(manager, "SELECT revision FROM analysis_apply_heads") == [(1,)]
    finally:
        await manager.close()


async def test_claims_serialize_same_principal_across_runs_without_blocking_other_principal(
    tmp_path: Path,
) -> None:
    executor = _FactExecutor()
    manager, _ = await _build_pipeline(tmp_path / "claims.db", executor, now=lambda: 20.0)
    backend = cast(SQLiteHumanMemoryBackend, manager.backend)
    try:
        await _ingest(manager, _evidence(1))
        await _ingest(manager, _evidence(2, run_id="run-2"))
        first, second = await asyncio.gather(*(
            backend.claim_analysis_batch(WORKER_CONFIG, worker)
            for worker in ("worker-1", "worker-2")
        ))
        assert sum(claim is not None for claim in (first, second)) == 1

        envelope, receipt = _evidence(3, run_id="run-3")
        disclosure = replace(
            envelope.disclosure_context, subject="actor-other", recipient_id="actor-other",
        )
        envelope = replace(envelope, subject="actor-other", disclosure_context=disclosure)
        receipt = replace(
            receipt, subject="actor-other", disclosure_context=disclosure,
            envelope_hash=envelope.envelope_hash,
        )
        await _ingest(manager, (envelope, receipt))
        other = await backend.claim_analysis_batch(WORKER_CONFIG, "worker-other")
        assert other is not None and other.subject == "actor-other"
    finally:
        await manager.close()


class _NoMutationExecutor(_HostExecutor):
    def __init__(self, payload: dict[str, JsonValue]) -> None:
        super().__init__((), no_mutation=True)
        self.payload = payload

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        envelope = await super().analyze_memory(request)
        envelope = _result_envelope(
            request, replace(envelope.result, structured_result=self.payload), self.issuer_id,
        )
        self.deliveries[(request.request_hash, request.attempt)] = envelope
        return envelope


@pytest.mark.parametrize(("extra", "accepted"), [
    ({}, True),
    ({"closure_reason": "model_no_change"}, True),
    ({"closure_reason": "仅寒暄，没有可记忆的新事实"}, True),
    ({"closure_reason": "analysis_response_unusable"}, False),
    ({"closure_reason": 12}, False),
    ({"closure_reason": None}, False),
    ({"closure_reason": "model_no_change", "extra": "unexpected"}, False),
    ({"closure_reason": "model_no_change", "operations": [{"kind": "create"}]}, False),
])
async def test_no_mutation_reason_is_validated_preserved_and_never_materialized(
    tmp_path: Path, extra: dict[str, JsonValue], accepted: bool,
) -> None:
    """IR-03: legitimate no-change stays distinct from an unusable provider response."""
    payload: dict[str, JsonValue] = {"outcome": "no_mutation", "operations": [], **extra}
    executor = _NoMutationExecutor(payload)
    authority = _HostEvidenceAuthority()
    path = tmp_path / "no-mutation.db"
    manager, runner = await _build_pipeline(path, executor, evidence_authority=authority)
    try:
        await _ingest(manager, _evidence(1, text="你好"), authority)
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        receipt = json.loads(str((await _rows(
            manager, "SELECT application_receipt_json FROM analysis_batches",
        ))[0][0]))
        assert receipt["validation_status"] == ("accepted" if accepted else "rejected")
        plans = await _rows(manager, "SELECT plan_json,plan_hash FROM accepted_analysis_plans")
        assert len(plans) == int(accepted)
        if accepted:
            assert json.loads(str(plans[0][0])) == payload
            assert plans[0][1] == hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        stored_rows = await _rows(manager, "SELECT result_json FROM analysis_batches")
        stored = json.loads(str(stored_rows[0][0]))
        assert stored["structured_result"] == payload
        snapshot = await _materialization_snapshot(manager)
        assert snapshot["heads"] == snapshot["revisions"] == snapshot["receipts"] == 0
        assert snapshot["analysis_head"] == [(1,)]
        assert snapshot["cognitive_head"] == []
        assert snapshot["outbox"] == [("memory.mutation.requested", "applied")]
        assert await _rows(manager, "SELECT COUNT(*) FROM decision_records") == [
            (0 if accepted else 1,)
        ]
        assert authority.resolutions == 0 and executor.calls == 1
    finally:
        await manager.close()
    manager, runner = await _build_pipeline(path, executor, evidence_authority=authority)
    try:
        assert await runner.run_once() is WorkerRunOutcome.IDLE
        assert await _materialization_snapshot(manager) == snapshot
        assert executor.calls == 1
    finally:
        await manager.close()
