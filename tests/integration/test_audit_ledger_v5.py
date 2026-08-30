from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import structlog
from simple_harness.runtime import (
    AnalysisBudget,
    AnalysisValidationStatus,
    EvidenceReasonCode,
    EvidenceRef,
    MemoryAnalysisReceipt,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.audit import (
    AuditTraceCursor,
    AuditTraceQuery,
    AuditTraceSelector,
    DecisionLedgerEntry,
    DecisionOutcome,
    OutputStorageStatus,
    PublicReasoningReference,
    ReasoningItemType,
)
from simple_harness_memory.core.errors import MemoryIdempotencyConflict, MemoryValidationError
from simple_harness_memory.core.suppression import (
    SealedAuditAccessDecision,
    SealedAuditAccessDenied,
    SuppressionDenied,
    SuppressionRequest,
    SuppressionScopeKind,
)
from tests.integration.test_suppression_v5 import (
    _audit_disclosure,
    _authority,
    _disclosure,
)


def _analysis_authority(
    evidence_ref: EvidenceRef,
    ordinal: int,
    *,
    structured_result: dict[str, object] | None = None,
    status: AnalysisValidationStatus = AnalysisValidationStatus.ACCEPTED,
) -> tuple[MemoryAnalysisRequest, MemoryAnalysisResult, MemoryAnalysisReceipt]:
    request = MemoryAnalysisRequest(
        f"job-{ordinal}",
        "run-1",
        "actor-1",
        (evidence_ref,),
        "memory-analysis-prompt/v1",
        "memory-mutation-plan/v1",
        "memory-policy/v1",
        "fixture-provider",
        "fixture-model",
        "a" * 64,
        ordinal,
        AnalysisBudget(1000, 500, 30000, 100000),
        _disclosure(),
        f"analysis-{ordinal}",
    )
    result = MemoryAnalysisResult(
        request.job_id,
        request.run_id,
        request.request_hash,
        f"provider-request-{ordinal}",
        structured_result
        or {"operations": [{"operation_id": f"operation-{ordinal}", "kind": "upsert"}]},
        100 + ordinal,
        20 + ordinal,
        1000 + ordinal,
        250 + ordinal,
    )
    accepted = status is AnalysisValidationStatus.ACCEPTED
    receipt = MemoryAnalysisReceipt(
        f"host-invocation-receipt-{ordinal}",
        request.job_id,
        request.run_id,
        request.request_hash,
        result.result_hash,
        "memory-validator/v1",
        status,
        (
            EvidenceReasonCode.VALIDATOR_ACCEPTED
            if accepted
            else EvidenceReasonCode.VALIDATOR_REJECTED,
        ),
        ordinal if accepted else None,
        100.0 + ordinal,
    )
    return request, result, receipt


def _decision(
    evidence_ref: EvidenceRef,
    ordinal: int,
    *,
    outcome: DecisionOutcome = DecisionOutcome.ACCEPTED,
) -> DecisionLedgerEntry:
    return DecisionLedgerEntry(
        f"decision-{ordinal}",
        f"operation-{ordinal}",
        "semantic_upsert",
        outcome,
        SuppressionScopeKind.MEMORY,
        f"memory-{ordinal}",
        {"operation": "semantic_upsert", "ordinal": ordinal},
        (f"memory-{ordinal}:revision:1",),
        (() if outcome is DecisionOutcome.REJECTED else (f"memory-{ordinal}:revision:2",)),
        (evidence_ref,),
        "validator_rejected" if outcome is DecisionOutcome.REJECTED else "validator_accepted",
        100.0 + ordinal,
    )


async def _ingest(
    backend: SQLiteHumanMemoryBackend, evidence_id: str
) -> EvidenceRef:
    envelope, receipt = _authority(evidence_id)
    await backend.ingest_committed_evidence(envelope, receipt)
    return EvidenceRef(evidence_id, envelope.sanitized_hash, 1)


@pytest.mark.asyncio
async def test_invocation_and_decision_lineage_is_replayable_immutable_and_queryable(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "audit-ledger.db", now=lambda: 120.0)
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    request, result, receipt = _analysis_authority(evidence_ref, 1)
    decision = _decision(evidence_ref, 1)
    reasoning = PublicReasoningReference(
        "reasoning-item-1",
        ReasoningItemType.REASONING,
        "b" * 64,
        "opaque-continuation-1",
    )

    record = await backend.record_memory_analysis(
        "invocation-1",
        "turn-1",
        request,
        result,
        receipt,
        (decision,),
        reasoning_refs=(reasoning,),
    )
    replay = await backend.record_memory_analysis(
        "invocation-1",
        "turn-1",
        request,
        result,
        receipt,
        (decision,),
        reasoning_refs=(reasoning,),
    )
    assert replay == record
    assert record.host_receipt.receipt_hash == receipt.receipt_hash
    assert record.public_output_hash is not None
    assert record.provider_request_id == result.provider_response_id
    assert record.input_tokens == result.input_tokens
    assert record.cost_microunits == result.cost_microunits

    selectors = (
        (AuditTraceSelector.TURN, "turn-1"),
        (AuditTraceSelector.INVOCATION, "invocation-1"),
        (AuditTraceSelector.DECISION, "decision-1"),
        (AuditTraceSelector.EVIDENCE, "evidence-1"),
    )
    for selector, selector_ref in selectors:
        page = await backend.export_audit_trace(
            AuditTraceQuery("actor-1", selector, selector_ref)
        )
        assert [item.invocation.invocation_id for item in page.items] == ["invocation-1"]
        assert page.items[0].decisions == (decision,)
        assert page.next_cursor is None

    async with backend.connection.execute("SELECT * FROM llm_reasoning_refs") as cursor:
        reasoning_row = await cursor.fetchone()
    assert reasoning_row is not None
    assert set(reasoning_row.keys()) == {
        "invocation_id",
        "ordinal",
        "provider_item_id",
        "item_type",
        "item_hash",
        "opaque_ref",
    }
    with pytest.raises(sqlite3.IntegrityError, match="immutable audit"):
        await backend.connection.execute(
            "UPDATE llm_invocations SET model_id='changed' WHERE invocation_id='invocation-1'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable audit"):
        await backend.connection.execute("DELETE FROM decision_records")
    await backend.close()


@pytest.mark.asyncio
async def test_stable_cursor_watermark_excludes_later_append(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "pagination.db", now=lambda: 120.0)
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    for ordinal in range(1, 4):
        request, result, receipt = _analysis_authority(evidence_ref, ordinal)
        await backend.record_memory_analysis(
            f"invocation-{ordinal}",
            "turn-page",
            request,
            result,
            receipt,
            (_decision(evidence_ref, ordinal),),
        )
    query = AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "turn-page")
    first = await backend.export_audit_trace(query, limit=1)
    assert first.next_cursor is not None

    request, result, receipt = _analysis_authority(evidence_ref, 4)
    await backend.record_memory_analysis(
        "invocation-4",
        "turn-page",
        request,
        result,
        receipt,
        (_decision(evidence_ref, 4),),
    )
    old_snapshot = [first.items[0].invocation.invocation_id]
    cursor: AuditTraceCursor | None = first.next_cursor
    while cursor is not None:
        page = await backend.export_audit_trace(query, limit=1, cursor=cursor)
        old_snapshot.extend(item.invocation.invocation_id for item in page.items)
        cursor = page.next_cursor
    assert old_snapshot == ["invocation-1", "invocation-2", "invocation-3"]
    fresh = await backend.export_audit_trace(query, limit=10)
    assert [item.invocation.invocation_id for item in fresh.items] == [
        "invocation-1",
        "invocation-2",
        "invocation-3",
        "invocation-4",
    ]
    assert first.next_cursor is not None
    with pytest.raises(MemoryValidationError, match="cursor_query_differs"):
        await backend.export_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "another-turn"),
            cursor=first.next_cursor,
        )
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("structured_result", "canary"),
    (
        ({"hidden_reasoning": "private-cot-canary"}, "private-cot-canary"),
        ({"operations": [{"value": "sk-private-audit-key-123456"}]}, "private-audit-key"),
    ),
)
async def test_invalid_private_output_records_rejection_without_body_anywhere(
    tmp_path: Path, structured_result: dict[str, object], canary: str
) -> None:
    path = tmp_path / f"unsafe-{canary}.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 120.0)
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    request, result, receipt = _analysis_authority(
        evidence_ref,
        1,
        structured_result=structured_result,
        status=AnalysisValidationStatus.REJECTED,
    )
    decision = _decision(evidence_ref, 1, outcome=DecisionOutcome.REJECTED)
    with structlog.testing.capture_logs() as logs:
        record = await backend.record_memory_analysis(
            "invocation-unsafe",
            "turn-unsafe",
            request,
            result,
            receipt,
            (decision,),
        )
    assert record.output_storage_status is OutputStorageStatus.REJECTED_UNSAFE
    assert record.public_output is None
    page = await backend.export_audit_trace(
        AuditTraceQuery("actor-1", AuditTraceSelector.INVOCATION, "invocation-unsafe")
    )
    assert page.items[0].decisions[0].outcome is DecisionOutcome.REJECTED
    assert canary not in json.dumps(logs, sort_keys=True)
    await backend.close()
    files = (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"))
    durable = b"".join(item.read_bytes() for item in files if item.exists())
    assert canary.encode() not in durable


@pytest.mark.asyncio
async def test_unsafe_output_claimed_accepted_is_rejected_before_any_audit_write(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "unsafe-accepted.db", now=lambda: 120.0)
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    request, result, receipt = _analysis_authority(
        evidence_ref,
        1,
        structured_result={"chain_of_thought": "must-never-persist"},
    )
    with pytest.raises(MemoryValidationError, match="unsafe_output_requires_rejected_decision"):
        await backend.record_memory_analysis(
            "invocation-unsafe",
            "turn-unsafe",
            request,
            result,
            receipt,
            (_decision(evidence_ref, 1),),
        )
    async with backend.connection.execute("SELECT COUNT(*) FROM llm_invocations") as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 0
    await backend.close()


@pytest.mark.asyncio
async def test_suppression_blocks_ordinary_trace_but_sealed_receipt_is_limited_and_logged(
    tmp_path: Path,
) -> None:
    clock = [120.0]
    backend = SQLiteHumanMemoryBackend(tmp_path / "sealed-trace.db", now=lambda: clock[0])
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    request, result, host_receipt = _analysis_authority(evidence_ref, 1)
    await backend.record_memory_analysis(
        "invocation-1",
        "turn-1",
        request,
        result,
        host_receipt,
        (_decision(evidence_ref, 1),),
    )
    await backend.suppress(
        SuppressionRequest(
            "forget-1",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_forget",
            110.0,
        )
    )
    query = AuditTraceQuery("actor-1", AuditTraceSelector.EVIDENCE, "evidence-1")
    with pytest.raises(SuppressionDenied):
        await backend.export_audit_trace(query)
    assert (
        await backend.export_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "turn-1")
        )
    ).items == ()

    access = await backend.issue_sealed_audit_access(
        SealedAuditAccessDecision(
            "trace-access-1",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_review",
            _audit_disclosure(),
            1,
            115.0,
            130.0,
        )
    )
    sealed = await backend.export_sealed_audit_trace(query, access)
    assert [item.invocation.invocation_id for item in sealed.items] == ["invocation-1"]
    with pytest.raises(SealedAuditAccessDenied, match="exhausted"):
        await backend.export_sealed_audit_trace(query, access)
    async with backend.connection.execute(
        "SELECT outcome,reason_code FROM audit_trace_access_events ORDER BY rowid"
    ) as cursor:
        assert [tuple(row) for row in await cursor.fetchall()] == [
            ("granted", "sealed_audit_trace_granted"),
            ("denied", "sealed_audit_access_exhausted"),
        ]
    await backend.close()


@pytest.mark.asyncio
async def test_replay_with_changed_decision_is_conflict(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "conflict.db", now=lambda: 120.0)
    await backend.initialize()
    evidence_ref = await _ingest(backend, "evidence-1")
    request, result, receipt = _analysis_authority(evidence_ref, 1)
    decision = _decision(evidence_ref, 1)
    await backend.record_memory_analysis(
        "invocation-1", "turn-1", request, result, receipt, (decision,)
    )
    changed = DecisionLedgerEntry(
        decision.decision_id,
        decision.operation_id,
        decision.operation_kind,
        decision.outcome,
        decision.target_kind,
        decision.target_ref,
        {"operation": "different"},
        decision.before_state_refs,
        decision.after_state_refs,
        decision.evidence_refs,
        decision.reason_code,
        decision.created_at,
    )
    with pytest.raises(MemoryIdempotencyConflict, match="replay_conflict"):
        await backend.record_memory_analysis(
            "invocation-1", "turn-1", request, result, receipt, (changed,)
        )
    await backend.close()
