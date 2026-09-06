"""New per-call public observations preserve original result wire/hash."""
import asyncio
import pytest
from simple_harness_memory import MemoryScope, ProcedureOperationObservationV1, ProcedureObservationApplyResult
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.procedure_operation_observation import procedure_operation_binding
from simple_harness_memory.core.errors import MemoryWriterConflict
from .test_procedure_observation_repository_v5 import _setup, _principal
from .test_procedure_observation_preparation import source, input_fields, authorize


def check(value, operation, args, *, outcome):
    obs = value.operation_observation
    assert type(obs) is ProcedureOperationObservationV1
    assert obs.observation_hash == ProcedureOperationObservationV1(**obs.to_json()).observation_hash
    assert (obs.request_hash, obs.claimed_owner_ref_hash) == procedure_operation_binding(
        operation, _principal(), MemoryScope.personal("actor-1"), args)
    assert obs.operation == operation and obs.outcome == outcome
    assert obs.persistence_status == "host_persistence_unverified"


@pytest.mark.asyncio
async def test_actual_prepare_consume_replay_and_rejection_observations(tmp_path):
    backend, authority, evidence, memory_id, revision = await _setup(tmp_path / "audit.db", [20.0])
    manager = MemoryManager(backend, None)
    identity = dict(principal=_principal(), scope=MemoryScope.personal("actor-1"))
    try:
        args = input_fields(source(authority, evidence, memory_id, revision, 1))
        prepared = await manager.prepare_procedure_observation(**identity, **args)
        check(prepared, "prepare_procedure_observation", args, outcome="observed")
        reference = authorize(authority, prepared.intent, "audit")
        applied = await manager.record_procedure_observation(**identity, reference=reference)
        check(applied, "record_procedure_observation", {"reference": reference}, outcome="observed")
        replay = await manager.record_procedure_observation(**identity, reference=reference)
        assert replay == applied
        assert replay.operation_observation.invocation_ref_hash != applied.operation_observation.invocation_ref_hash
        assert replay.result_hash == applied.result_hash == ProcedureObservationApplyResult.from_json(applied.to_json()).result_hash
        with pytest.raises(MemoryWriterConflict) as error:
            await manager.read_procedure_use_target(**identity, memory_id=memory_id, revision=revision)
        check(error.value, "read_procedure_use_target", dict(memory_id=memory_id, revision=revision), outcome="rejected")
        assert error.value.operation_observation.source_hash is None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_actual_public_wrapper_records_backend_cancel_and_error():
    class Backend:
        error = asyncio.CancelledError()
        async def read_procedure_use_target(self, **kwargs):
            raise self.error
    backend = Backend()
    manager = MemoryManager(backend, None)
    args = dict(memory_id="exact-procedure", revision=1)
    for failure, outcome in ((asyncio.CancelledError(), "cancelled"), (RuntimeError("physical read failed"), "failed")):
        backend.error = failure
        with pytest.raises(type(failure)) as raised:
            await manager.read_procedure_use_target(principal=_principal(), scope=MemoryScope.personal("actor-1"), **args)
        assert raised.value is failure
        check(failure, "read_procedure_use_target", args, outcome=outcome)
