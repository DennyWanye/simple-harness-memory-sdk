"""Explicit recovery options preserve strict default and public receipt semantics."""
from dataclasses import replace
import pytest
from simple_harness.runtime import ExistingMemoryTarget, MemoryMutationKind, ProcedureLifecycleState
from simple_harness_memory import SuppressionRequest, SuppressionScopeKind
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.errors import MemoryValidationError, MemoryWriterConflict
from simple_harness_memory.core.suppression import SuppressionDenied
from .test_procedure_observation_repository_v5 import _setup, _principal, _procedure_operation, _plan, _with_action_authorities
from .test_procedure_observation_preparation import input_fields, source, authorize

SCOPE = MemoryScope.personal("actor-1")


@pytest.mark.asyncio
async def test_explicit_rebase_proves_observation_chain_and_rejects_real_revision(tmp_path):
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "rebase.db", clock)
    manager = MemoryManager(backend, None)
    try:
        first = await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE,
            **input_fields(source(authority, evidence, memory_id, revision, 1)))
        result = await manager.record_procedure_observation(principal=_principal(), scope=SCOPE,
            reference=authorize(authority, first.intent, "first"))
        args = input_fields(source(authority, evidence, memory_id, revision, 3))
        with pytest.raises(MemoryWriterConflict):
            await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE, **args)
        prepared = await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE,
            **args, allow_observation_rebase=True)
        assert prepared.intent.target_revision == result.committed_revision
        current = await manager.read_procedure_use_target(principal=_principal(), scope=SCOPE,
            memory_id=memory_id, revision=revision, allow_observation_rebase=True)
        assert current.revision == result.committed_revision
        operation = _procedure_operation(evidence[3][2], operation_id="revise-recovery-target",
            kind=MemoryMutationKind.REVISE, target=ExistingMemoryTarget(memory_id, current.revision),
            lifecycle_state=ProcedureLifecycleState.REVISED)
        plan = _with_action_authorities(_plan(evidence[3][0], operation, base_revision=2,
            plan_id="recovery-revise", idempotency_key="recovery-revise"), authority, issued_at=19, expires_at=30)
        await manager.apply_memory_mutation_plan(principal=_principal(), scope=SCOPE, plan=plan)
        with pytest.raises(MemoryWriterConflict, match="rebase_definition_changed"):
            await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE,
                **args, allow_observation_rebase=True)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_expired_reference_is_source_only_and_same_source_renewal_is_bounded(tmp_path):
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "expired.db", clock)
    manager = MemoryManager(backend, None)
    try:
        args = input_fields(source(authority, evidence, memory_id, revision, 1))
        prepared = await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE, **args)
        initial = authorize(authority, prepared.intent, "expire")
        value = replace(authority.procedure.pop(initial.authority_id), expires_at=21.0)
        authority.procedure[value.authority_id] = value
        from simple_harness.runtime import ProcedureObservationAuthorityRef
        previous = ProcedureObservationAuthorityRef.from_authority(value)
        with pytest.raises(MemoryWriterConflict, match="previous_still_usable"):
            await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE, **args,
                allow_observation_rebase=True, previous_reference=previous)
        clock[0] = 22.0
        with pytest.raises(MemoryValidationError, match="authority_rejected"):
            await manager.record_procedure_observation(principal=_principal(), scope=SCOPE, reference=previous)
        with pytest.raises(MemoryValidationError, match="previous_source_differs"):
            await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE,
                **{**args, "operation_id": "substitute-operation"},
                allow_observation_rebase=True, previous_reference=previous)
        again = await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE, **args,
            allow_observation_rebase=True, previous_reference=previous)
        current = authorize(authority, again.intent, "renewed")
        result = await manager.record_procedure_observation(principal=_principal(), scope=SCOPE, reference=current)
        assert result.independent_successes == 1
        with pytest.raises(MemoryWriterConflict, match="previous_already_consumed"):
            await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE, **args,
                allow_observation_rebase=True, previous_reference=current)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_forget_after_preparation_cannot_be_overridden_by_old_authority(tmp_path):
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "forget.db", clock)
    manager = MemoryManager(backend, None)
    try:
        prepared = await manager.prepare_procedure_observation(principal=_principal(), scope=SCOPE,
            **input_fields(source(authority, evidence, memory_id, revision, 1)))
        reference = authorize(authority, prepared.intent, "before-forget")
        await manager.suppress(request=SuppressionRequest("forget-prepared-target", "actor-1",
            SuppressionScopeKind.MEMORY, memory_id, "user_forget", clock[0]), principal=_principal())
        with pytest.raises(SuppressionDenied):
            await manager.record_procedure_observation(principal=_principal(), scope=SCOPE, reference=reference)
    finally:
        await manager.close()
