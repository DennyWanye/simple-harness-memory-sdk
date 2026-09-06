"""Payload-free invocation outcome carrier for Host persistence (OA1 boundary)."""
from dataclasses import dataclass, field, replace
import asyncio
import math
import time
from uuid import uuid4
from dataclasses import asdict
from simple_harness import DisclosureContext
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.errors import MemoryOwnershipConflict, MemoryLimitError

from simple_harness_memory.core.operation_audit import _hash, _digest
from simple_harness_memory.core.input_visibility import CurrentInputBindingV1


@dataclass(frozen=True, slots=True)
class CurrentInputObservationV1:
    invocation_ref_hash: str
    request_hash: str | None
    snapshot_hash: str | None
    outcome: str
    observed_at: float
    operation: str = "check_current_input_visibility"
    persistence_status: str = "host_persistence_unverified"
    observation_hash: str = field(init=False)

    def __post_init__(self):
        _digest(self.invocation_ref_hash)
        for value in (self.request_hash, self.snapshot_hash):
            if value is not None:
                _digest(value)
        if (self.outcome not in {"input_usable", "input_denied", "rejected", "failed", "cancelled"}
                or self.operation != "check_current_input_visibility"
                or self.persistence_status != "host_persistence_unverified"
                or type(self.observed_at) not in (float, int) or not math.isfinite(self.observed_at)
                or self.observed_at < 0
                or ((self.outcome in {"input_usable", "input_denied"}) != (self.snapshot_hash is not None))):
            raise ValueError("current_input_observation_invalid")
        object.__setattr__(self, "observation_hash", _hash("memory.current-input.observation.v1", self.to_json()))

    def to_json(self):
        return {"schema_version": 1, **{name: getattr(self, name) for name in self.__dataclass_fields__
            if name != "observation_hash"}}


async def observed_check(manager, *, principal, disclosure_context, binding):
    invocation = _hash("memory.current-input.invocation.v1", str(uuid4()))
    request = None
    if type(binding) is CurrentInputBindingV1:
        try:
            if type(principal) is MemoryPrincipal and type(disclosure_context) is DisclosureContext:
                request = _hash("memory.current-input.request.v1", {"principal": asdict(principal),
                    "disclosure": disclosure_context.to_json(), "binding_hash": binding.binding_hash})
        except (ValueError, TypeError):
            pass

    def observe(outcome, snapshot=None):
        record = CurrentInputObservationV1(invocation, request, snapshot, outcome, time.time())
        manager._observability.emit("memory.current_input.observed", operation=record.operation,
            outcome="succeeded" if outcome == "input_usable" else "failed", entity_id=invocation,
            attributes={"fingerprint": record.observation_hash, "stage": outcome, "state_version": 1})
        return record

    try:
        result = await manager._backend.check_current_input_visibility(
            principal=principal, disclosure_context=disclosure_context, binding=binding)
    except BaseException as error:
        outcome = ("cancelled" if isinstance(error, asyncio.CancelledError) else
            "rejected" if isinstance(error, (TypeError, ValueError, MemoryOwnershipConflict, MemoryLimitError)) else "failed")
        error.operation_observation = observe(outcome)
        raise
    return replace(result, operation_observation=observe(
        "input_usable" if result.invocation_input_allowed else "input_denied", result.snapshot_hash))
