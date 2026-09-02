"""Memory 0.6.2：多 evidence analysis batch 中 operation 可引用任一成员 evidence（S5b Task 5）。

Host Task 4 真实/确定性车道发现：两条 evidence 一 batch、operation 只引用第二条时，
0.6.1 的 decision 构造把按 batch ordinal 过滤出的子集直接交给 ``DecisionLedgerEntry``，
``_refs`` 要求 ordinal 恰为 1..n → ``decision_evidence_refs_ordinal_invalid``。
期望：operation 的 evidence 只要落在 batch 成员集合内即接受并物化；引用成员集合外的
evidence 仍拒绝。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, cast

import pytest

from simple_harness_memory.core.jobs import DurableMemoryJobRunner, WorkerRunOutcome
from tests.integration.test_memory_061_core import (
    BATCH_CONFIG,
    WORKER_CONFIG,
    _build_pipeline,
    _count,
    _evidence,
    _HostEvidenceAuthority,
    _HostExecutor,
    _ingest,
    _materialization_snapshot,
    _rows,
    _semantic_ops,
)


async def _two_evidence_pipeline(
    db_path: Path, executor: _HostExecutor, config: Any
) -> tuple[Any, DurableMemoryJobRunner, _HostEvidenceAuthority]:
    authority = _HostEvidenceAuthority()
    manager, _ = await _build_pipeline(db_path, executor, evidence_authority=authority)
    runner = DurableMemoryJobRunner(
        cast(Any, manager.backend), executor, executor, config, "worker-1", time.time
    )
    await _ingest(manager, _evidence(1), authority)
    await _ingest(manager, _evidence(2), authority)
    return manager, runner, authority


@pytest.mark.asyncio
async def test_operation_may_cite_only_the_second_batch_evidence(tmp_path: Path) -> None:
    """复现：两条 evidence 一 batch，op 只引第二条 → 0.6.1 拒绝；0.6.2 接受并物化。"""

    executor = _HostExecutor(_semantic_ops("op-second", evidence_id="evidence-2"))
    manager, runner, authority = await _two_evidence_pipeline(
        tmp_path / "second-only.db", executor, BATCH_CONFIG
    )
    try:
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        request = executor.requests[0]
        assert [item.evidence_id for item in request.ordered_evidence_refs] == [
            "evidence-1",
            "evidence-2",
        ]
        assert authority.resolutions >= 1
        snapshot = await _materialization_snapshot(manager)
        assert snapshot["heads"] == 1 and snapshot["revisions"] == 1
        assert snapshot["receipts"] == 1
        assert snapshot["analysis_head"] == [(2,)] and snapshot["cognitive_head"] == [(2,)]
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [("applied",)]
        assert await _rows(manager, "SELECT DISTINCT state FROM jobs") == [("applied",)]
        decisions = await _rows(
            manager,
            "SELECT d.operation_id,d.outcome,r.ordinal,r.evidence_id FROM decision_records d "
            "JOIN decision_evidence_refs r ON r.decision_id=d.decision_id ORDER BY 1,3",
        )
        assert decisions == [("op-second", "accepted", 1, "evidence-2")]
        assert await _rows(
            manager,
            "SELECT DISTINCT evidence_id FROM cognitive_evidence_spans ORDER BY 1",
        ) == [("evidence-2",)]
        # 幂等：再次 run_once IDLE、零新增物化。
        assert await runner.run_once() is WorkerRunOutcome.IDLE
        assert await _materialization_snapshot(manager) == snapshot
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_operations_cite_distinct_batch_members_in_batch_order(tmp_path: Path) -> None:
    """两 op 各引一条成员 evidence：decision 的 evidence_refs 逐条重编 ordinal（1..n）。"""

    executor = _HostExecutor(
        (
            {"operation_id": "op-first", "evidence_id": "evidence-1", "predicate": "p-1"},
            {"operation_id": "op-second", "evidence_id": "evidence-2", "predicate": "p-2"},
        )
    )
    manager, runner, _ = await _two_evidence_pipeline(
        tmp_path / "both-members.db", executor, BATCH_CONFIG
    )
    try:
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        snapshot = await _materialization_snapshot(manager)
        assert snapshot["heads"] == 2 and snapshot["revisions"] == 2
        decisions = await _rows(
            manager,
            "SELECT d.operation_id,r.ordinal,r.evidence_id FROM decision_records d "
            "JOIN decision_evidence_refs r ON r.decision_id=d.decision_id ORDER BY 1,2",
        )
        assert decisions == [
            ("op-first", 1, "evidence-1"),
            ("op-second", 1, "evidence-2"),
        ]
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [("applied",)]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_operation_citing_evidence_outside_batch_is_still_rejected(
    tmp_path: Path,
) -> None:
    """反例：batch 只含 evidence-1，op 引用 evidence-2（plan.evidence_refs 越出成员集合）→ 拒绝。"""

    executor = _HostExecutor(
        _semantic_ops("op-outside", evidence_id="evidence-2"),
        extra_evidence_ids=("evidence-2",),
    )
    manager, runner, authority = await _two_evidence_pipeline(
        tmp_path / "outside-batch.db", executor, WORKER_CONFIG
    )
    try:
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        request = executor.requests[0]
        assert [item.evidence_id for item in request.ordered_evidence_refs] == ["evidence-1"]
        assert authority.resolutions == 0
        snapshot = await _materialization_snapshot(manager)
        assert snapshot["heads"] == 0 and snapshot["revisions"] == 0
        assert snapshot["receipts"] == 0
        assert await _count(manager, "SELECT COUNT(*) FROM accepted_analysis_plans") == 0
        events = await _rows(
            manager,
            "SELECT DISTINCT event_kind,reason_code FROM job_attempt_events "
            "WHERE event_kind='application_rejected'",
        )
        assert events == [("application_rejected", "analysis_validator_rejected")]
        receipt = await _rows(manager, "SELECT application_receipt_json FROM analysis_batches")
        assert len(receipt) == 1 and '"validation_status":"rejected"' in str(receipt[0][0])
        decisions = await _rows(
            manager,
            "SELECT d.outcome,r.ordinal,r.evidence_id FROM decision_records d "
            "JOIN decision_evidence_refs r ON r.decision_id=d.decision_id ORDER BY 2",
        )
        assert decisions == [("rejected", 1, "evidence-1")]
    finally:
        await manager.close()
