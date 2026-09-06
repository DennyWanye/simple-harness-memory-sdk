"""New public preparation shares decisions without issuing observation authority."""
import pytest
from simple_harness.runtime import (
    ProcedureLifecycleState as State, ProcedureObservationAuthorityRef,
    issue_procedure_observation_authority,
)
from simple_harness_memory.core.errors import MemoryValidationError, MemoryWriterConflict
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.manager import MemoryManager
from .test_procedure_observation_repository_v5 import _setup, _grant, _principal


def input_fields(intent):
    return {name: getattr(intent, name) for name in (
        "observation_id", "target_memory_id", "target_revision", "kind", "applicability",
        "hazard", "task_scope_id", "evidence_span", "terminal_receipt_id", "terminal_receipt_hash",
        "outcome", "attributable", "observed_at", "run_id", "operation_id",
    )}


def source(authority, evidence, memory_id, revision, index):
    reference = _grant(authority, evidence, memory_id=memory_id, revision=revision,
                       index=index, transition_from=State.DRAFT, transition_to=State.DRAFT)
    # The helper supplies actual registered evidence; discard its test authority.
    return authority.procedure.pop(reference.authority_id).intent


def authorize(authority, intent, suffix):
    value = issue_procedure_observation_authority(intent, authority_id="prepared-" + suffix,
        issued_at=15, expires_at=10_000_000, nonce="prepared-nonce-" + suffix,
        issuer_ref="host-procedure-observation:v1")
    authority.procedure[value.authority_id] = value
    return ProcedureObservationAuthorityRef.from_authority(value)


@pytest.mark.asyncio
async def test_public_preparation_three_scopes_no_mutation_before_authority_and_stale_reject(tmp_path):
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "prepare.db", clock)
    manager = MemoryManager(backend, None)
    try:
        for index, expected in ((1, State.DRAFT), (3, State.ELIGIBLE_FOR_ACTIVATION), (4, State.ACTIVE)):
            proposal = source(authority, evidence, memory_id, revision, index)
            args = input_fields(proposal)
            resolutions = authority.procedure_resolutions
            prepared = await manager.prepare_procedure_observation(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), **args)
            assert prepared.transition_to is expected
            assert authority.procedure_resolutions == resolutions  # prepare never resolves a grant
            again = await manager.prepare_procedure_observation(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), **args)
            assert again == prepared
            ref = authorize(authority, prepared, str(index))
            result = await manager.record_procedure_observation(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=ref)
            assert result.lifecycle_state is expected
            assert result.independent_successes == {1: 1, 3: 2, 4: 3}[index]
            assert await manager.record_procedure_observation(
                principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=ref) == result
            with pytest.raises(MemoryWriterConflict):
                await manager.prepare_procedure_observation(
                    principal=_principal(), scope=MemoryScope.personal("actor-1"), **args)
            revision = result.committed_revision
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_public_preparation_rejects_false_terminal_and_foreign_scope(tmp_path):
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "reject.db", [20.0])
    manager = MemoryManager(backend, None)
    try:
        args = input_fields(source(authority, evidence, memory_id, revision, 1))
        with pytest.raises(MemoryValidationError, match="terminal_receipt_differs"):
            await manager.prepare_procedure_observation(principal=_principal(),
                scope=MemoryScope.personal("actor-1"), **{**args, "terminal_receipt_hash": "0" * 64})
        with pytest.raises(MemoryValidationError, match="task_scope_evidence_missing"):
            await manager.prepare_procedure_observation(principal=_principal(),
                scope=MemoryScope.personal("actor-1"), **{**args, "task_scope_id": "foreign-scope"})
        assert authority.procedure_resolutions == 0
    finally:
        await manager.close()
