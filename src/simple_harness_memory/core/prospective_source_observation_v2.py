"""V2 call metadata; frozen V1 observation and request hash domains stay unchanged."""
from dataclasses import dataclass, field, replace
import asyncio
import math
import time
from uuid import uuid4

from simple_harness_memory.core.errors import (
    MemoryCorruptionError, MemoryLimitError, MemoryOwnershipConflict, MemoryValidationError,
)
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.operation_audit import _digest, _hash


@dataclass(frozen=True, slots=True)
class ProspectiveSourceReadObservationV2:
    invocation_ref_hash: str
    request_hash: str | None
    claimed_owner_ref_hash: str | None
    source_hash: str | None
    outcome: str
    reason: str
    observed_at: float
    operation: str = "read_prospective_outbox_source_v2"
    persistence_status: str = "host_persistence_unverified"
    schema_version: int = 1
    observation_hash: str = field(init=False)

    def __post_init__(self):
        _digest(self.invocation_ref_hash)
        for value in (self.request_hash, self.claimed_owner_ref_hash, self.source_hash):
            if value is not None:
                _digest(value)
        pairs = {("observed", "source_verified"), ("rejected", "input_or_binding_rejected"),
            ("rejected", "ownership_rejected"), ("rejected", "source_corrupt"),
            ("rejected", "resource_limit"), ("failed", "source_read_failed"),
            ("cancelled", "source_read_cancelled")}
        if (type(self.schema_version) is not int or self.schema_version != 1
                or self.operation != "read_prospective_outbox_source_v2"
                or self.persistence_status != "host_persistence_unverified"
                or (self.outcome, self.reason) not in pairs
                or ((self.outcome == "observed") != (self.source_hash is not None))
                or type(self.observed_at) not in (int, float)
                or not math.isfinite(self.observed_at) or self.observed_at < 0):
            raise MemoryValidationError("prospective_source_observation_invalid")
        object.__setattr__(self, "observed_at", float(self.observed_at))
        object.__setattr__(self, "observation_hash",
            _hash("memory.prospective.source.observation.v2", self.to_json()))

    def to_json(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__
            if name != "observation_hash"}


def _bounded_string(value):
    if type(value) is not str or len(value) > 4096:
        return False
    try:
        return len(value.encode("utf-8")) <= 4096
    except UnicodeError:
        return False


async def observed_read(manager, *, principal, outbox_id, payload_hash):
    invocation = _hash("memory.prospective.source.invocation.v2", str(uuid4()))
    request = (_hash("memory.prospective.source.request.v2", [outbox_id, payload_hash])
        if _bounded_string(outbox_id) and _bounded_string(payload_hash) else None)
    owner = None
    if type(principal) is MemoryPrincipal:
        fields = [principal.deployment_id, principal.household_id, principal.actor_id, principal.session_id]
        if all(_bounded_string(value) for value in fields):
            owner = _hash("memory.prospective.source.claimed-owner.v1", fields)

    def observe(outcome, reason, source_hash=None):
        # Physical observation time; never the outbox's business emit time or a Run source.
        observation = ProspectiveSourceReadObservationV2(
            invocation, request, owner, source_hash, outcome, reason, time.time())
        manager._observability.emit(
            "memory.prospective_source_read.observed", operation=observation.operation,
            outcome="succeeded" if outcome == "observed" else "failed",
            entity_id=invocation, attributes={"fingerprint": observation.observation_hash,
                "stage": observation.reason, "to_state": observation.outcome, "state_version": 1})
        return observation

    try:
        result = await manager._backend.read_prospective_outbox_source_v2(
            principal=principal, outbox_id=outbox_id, payload_hash=payload_hash)
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            outcome, reason = "cancelled", "source_read_cancelled"
        elif isinstance(error, MemoryOwnershipConflict):
            outcome, reason = "rejected", "ownership_rejected"
        elif isinstance(error, MemoryCorruptionError):
            outcome, reason = "rejected", "source_corrupt"
        elif isinstance(error, MemoryLimitError):
            outcome, reason = "rejected", "resource_limit"
        elif isinstance(error, (MemoryValidationError, TypeError, ValueError)):
            outcome, reason = "rejected", "input_or_binding_rejected"
        else:
            outcome, reason = "failed", "source_read_failed"
        error.operation_observation = observe(outcome, reason)
        raise
    return replace(result, operation_observation=observe("observed", "source_verified", result.source_hash))
