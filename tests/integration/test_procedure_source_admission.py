"""Procedure source-only terminal admission, not a general mutation permit."""
from dataclasses import replace
import pytest
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.errors import MemoryValidationError
from .test_procedure_observation_repository_v5 import _setup, _principal, _procedure_operation, _plan
from .test_procedure_observation_preparation import input_fields, source, authorize


@pytest.mark.asyncio
async def test_public_source_only_terminal_prepares_consumes_without_analysis_job(tmp_path):
    backend, authority, evidence, memory_id, revision = await _setup(
        tmp_path / "source-only.db", [20.0], count=2, source_only_indices=(2,))
    manager = MemoryManager(backend, None)
    try:
        args = input_fields(source(authority, evidence, memory_id, revision, 2))
        prepared = await manager.prepare_procedure_observation(principal=_principal(),
            scope=MemoryScope.personal("actor-1"), **args)
        result = await manager.record_procedure_observation(principal=_principal(),
            scope=MemoryScope.personal("actor-1"), reference=authorize(authority, prepared.intent, "source-only"))
        assert result.independent_successes == 1
        # Read-only evidence assertion: source admission must not turn into full ingestion.
        async with backend.connection.execute("SELECT count(*) FROM ingestion_receipts WHERE evidence_id=?",
                (evidence[1][0].evidence_id,)) as cursor:
            assert (await cursor.fetchone())[0] == 0
        async with backend.connection.execute("SELECT count(*) FROM source_admission_receipts WHERE evidence_id=?",
                (evidence[1][0].evidence_id,)) as cursor:
            assert (await cursor.fetchone())[0] == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_source_only_receipt_scope_binding_and_ordinary_mutation_gate_remain_strict(tmp_path):
    backend, authority, evidence, memory_id, revision = await _setup(
        tmp_path / "source-reject.db", [20.0], count=2, source_only_indices=(2,))
    manager = MemoryManager(backend, None)
    try:
        args = input_fields(source(authority, evidence, memory_id, revision, 2))
        for change, reason in (({"evidence_span": replace(args["evidence_span"], admission_receipt_hash="0" * 64)},
                                "span_db_binding_mismatch"),
                               ({"task_scope_id": "foreign-scope"}, "task_scope_evidence_missing"),
                               ({"terminal_receipt_hash": "0" * 64}, "terminal_receipt_differs")):
            with pytest.raises(MemoryValidationError, match=reason):
                await manager.prepare_procedure_observation(principal=_principal(),
                    scope=MemoryScope.personal("actor-1"), **{**args, **change})
        envelope, _, span = evidence[1]
        # Public ordinary mutation still requires full ingestion. No source-only
        # row is converted or given analysis lineage to bypass its admission gate.
        with pytest.raises(MemoryValidationError, match="mutation_evidence_span_not_admitted"):
            await manager.apply_memory_mutation_plan(principal=_principal(), scope=MemoryScope.personal("actor-1"),
                plan=_plan(envelope, _procedure_operation(span), base_revision=2,
                    plan_id="source-only-mutation", idempotency_key="source-only-mutation"))
        assert authority.procedure_resolutions == 0
    finally:
        await manager.close()
