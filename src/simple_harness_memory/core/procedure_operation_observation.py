"""Public per-invocation Procedure observations, without a new business ledger."""
import asyncio
import math
import time
from dataclasses import dataclass, field, replace
from uuid import uuid4

from simple_harness.runtime import (
    DisclosureContext, EvidenceSpanRef, ProcedureApplicabilityContext, ProcedureObservationAuthorityRef,
    ProcedureObservationIntent, ProcedureObservationKind, ProcedureObservationOutcome,
    ProcedureHazard,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.errors import (
    MemoryCorruptionError, MemoryLimitError, MemoryOwnershipConflict,
    MemoryValidationError, MemoryWriterConflict,
)
from simple_harness_memory.core.suppression import SuppressionDenied
from simple_harness_memory.core.operation_audit import _digest, _hash

OPERATIONS = frozenset({"discover_procedure_drafts", "prepare_procedure_observation", "read_procedure_use_target", "record_procedure_observation"})


def error_outcome(error):
    if isinstance(error, asyncio.CancelledError):
        return "cancelled", "operation_cancelled"
    if isinstance(error, MemoryOwnershipConflict):
        return "rejected", "ownership_rejected"
    if isinstance(error, SuppressionDenied):
        return "rejected", "visibility_rejected"
    if isinstance(error, MemoryCorruptionError):
        return "rejected", "source_corrupt"
    if isinstance(error, MemoryWriterConflict):
        return "rejected", "current_binding_rejected"
    if isinstance(error, MemoryLimitError):
        return "rejected", "resource_limit"
    if isinstance(error, (MemoryValidationError, TypeError, ValueError)):
        return "rejected", "input_or_binding_rejected"
    return "failed", "operation_failed"


def procedure_operation_binding(operation, principal, scope, arguments):
    """Hash only bounded public values; invalid custom objects stay unbound."""
    if operation not in OPERATIONS:
        raise ValueError("procedure_operation_invalid")
    def wire(value):
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        if type(value) is str and len(value.encode()) <= 16384:
            return value
        if type(value) in (ProcedureObservationKind, ProcedureObservationOutcome, ProcedureHazard):
            return value.value
        if type(value) in (DisclosureContext, EvidenceSpanRef, ProcedureApplicabilityContext, ProcedureObservationAuthorityRef):
            return value.to_json()
        raise ValueError("unbound argument")
    owner = None
    try:
        if type(principal) is MemoryPrincipal:
            owner = _hash("memory.procedure.operation.claimed-owner.v1", [wire(getattr(principal, key))
                for key in ("deployment_id", "household_id", "actor_id", "session_id")])
        if type(scope) is not MemoryScope:
            return None, owner
        payload = {"operation": operation, "scope": [scope.kind.value, wire(scope.owner_id)],
                   "arguments": {key: wire(value) for key, value in arguments.items()}}
        from simple_harness.contracts import canonical_json
        if len(canonical_json(payload).encode()) > 65536:
            return None, owner
        return _hash("memory.procedure.operation.request.v1", payload), owner
    except (TypeError, ValueError, UnicodeError):
        return None, owner


@dataclass(frozen=True, slots=True)
class ProcedureOperationObservationV1:
    operation: str
    invocation_ref_hash: str
    request_hash: str | None
    claimed_owner_ref_hash: str | None
    source_hash: str | None
    outcome: str
    reason: str
    observed_at: float
    persistence_status: str = "host_persistence_unverified"
    schema_version: int = 1
    observation_hash: str = field(init=False)

    def __post_init__(self):
        for value in (self.invocation_ref_hash, self.request_hash, self.claimed_owner_ref_hash, self.source_hash):
            if value is not None:
                _digest(value)
        pairs = {("observed", "source_verified"), ("cancelled", "operation_cancelled"),
                 ("failed", "operation_failed"), *(("rejected", reason) for reason in (
                     "ownership_rejected", "visibility_rejected", "source_corrupt", "current_binding_rejected",
                     "resource_limit", "input_or_binding_rejected"))}
        if (self.operation not in OPERATIONS or self.invocation_ref_hash is None
                or type(self.schema_version) is not int or self.schema_version != 1
                or self.persistence_status != "host_persistence_unverified"
                or (self.outcome, self.reason) not in pairs
                or ((self.outcome == "observed") != (self.source_hash is not None))
                or type(self.observed_at) not in (int, float)
                or not math.isfinite(self.observed_at) or self.observed_at < 0):
            raise MemoryValidationError("procedure_operation_observation_invalid")
        object.__setattr__(self, "observed_at", float(self.observed_at))
        object.__setattr__(self, "observation_hash", _hash("memory.procedure.operation.observation.v1", self.to_json()))

    def to_json(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__ if key != "observation_hash"}


@dataclass(frozen=True, slots=True)
class PreparedProcedureObservation:
    intent: ProcedureObservationIntent
    operation_observation: ProcedureOperationObservationV1

    def __post_init__(self):
        if (type(self.intent) is not ProcedureObservationIntent
                or type(self.operation_observation) is not ProcedureOperationObservationV1
                or self.operation_observation.operation != "prepare_procedure_observation"
                or self.operation_observation.outcome != "observed"
                or self.operation_observation.source_hash != self.intent.intent_hash):
            raise MemoryValidationError("prepared_procedure_observation_invalid")

    @property
    def source_hash(self):
        return self.intent.intent_hash

    def to_json(self):
        return {"intent": self.intent.to_json(), "operation_observation": self.operation_observation.to_json()}


async def observed_procedure_call(manager, operation, *, principal, scope, **arguments):
    binding = procedure_operation_binding(operation, principal, scope, arguments)
    invocation = _hash("memory.procedure.operation.invocation.v1", str(uuid4()))
    def observe(outcome, reason, source_hash=None):
        value = ProcedureOperationObservationV1(operation, invocation, *binding, source_hash, outcome, reason, time.time())
        manager._observability.emit("memory.procedure_operation.observed", operation=operation,
            outcome="succeeded" if outcome == "observed" else "failed", entity_id=invocation,
            attributes={"fingerprint": value.observation_hash, "stage": reason,
                        "to_state": outcome, "state_version": 1})
        return value
    try:
        result = await getattr(manager._backend, operation)(principal=principal, scope=scope, **arguments)
    except BaseException as error:
        error.operation_observation = observe(*error_outcome(error))
        raise
    if operation == "prepare_procedure_observation":
        return PreparedProcedureObservation(result, observe("observed", "source_verified", result.intent_hash))
    source_hash = result.result_hash if operation == "record_procedure_observation" else result.source_hash
    return replace(result, operation_observation=observe("observed", "source_verified", source_hash))
