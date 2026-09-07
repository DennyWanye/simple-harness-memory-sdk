"""Factual target lineage for an exact scheduler outbox command; never a grant."""
import math
from dataclasses import dataclass, field

from simple_harness.runtime import (
    MemoryMutationApplyReceiptRef, ProspectiveLifecycleState, prospective_trigger_hash,
)
from simple_harness_memory.core.history import history_hash
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.mutation_receipts import _digest, _identifier, _revision
from simple_harness_memory.core.prospective import normalize_trigger
from simple_harness_memory.core.prospective_source_observation import ProspectiveSourceReadObservationV1


@dataclass(frozen=True, slots=True)
class ProspectiveOutboxSourceView:
    subject: str
    outbox_id: str
    outbox_payload_hash: str
    outbox_created_at: float
    command: str
    target_memory_id: str
    target_revision: int
    registration_revision: int
    target_scope: MemoryScope
    target_task_scope_id: str | None
    target_lifecycle_state: ProspectiveLifecycleState
    target_run_id: str
    target_plan_id: str
    target_plan_hash: str
    target_operation_id: str
    target_operation_kind: str
    target_mutation_receipt_ref: MemoryMutationApplyReceiptRef
    trigger: object
    trigger_hash: str
    # No existing outbox column binds its generating mutation/signal. Target
    # lineage must not be silently promoted into the outbox's generating cause.
    outbox_cause_status: str = "not_persisted"
    schema_version: int = 1
    operation_observation: ProspectiveSourceReadObservationV1 | None = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        if (type(self.outbox_created_at) not in (int, float)
                or not math.isfinite(self.outbox_created_at) or self.outbox_created_at < 0):
            raise ValueError("prospective_outbox_created_at_invalid")
        object.__setattr__(self, "outbox_created_at", float(self.outbox_created_at))
        for field in ("subject", "outbox_id", "target_memory_id", "target_run_id", "target_plan_id",
                      "target_operation_id", "target_operation_kind"):
            _identifier(getattr(self, field), field)
        for field in ("outbox_payload_hash", "target_plan_hash", "trigger_hash"):
            _digest(getattr(self, field), field)
        _revision(self.target_revision, "target_revision")
        _revision(self.registration_revision, "registration_revision")
        if self.target_task_scope_id is not None:
            _identifier(self.target_task_scope_id, "target_task_scope_id")
        if (type(self.schema_version) is not int or self.schema_version != 1
                or self.registration_revision != self.target_revision or self.command not in {"registration", "invalidation"}
                or self.outbox_cause_status != "not_persisted"
                or type(self.target_scope) is not MemoryScope
                or type(self.target_mutation_receipt_ref) is not MemoryMutationApplyReceiptRef):
            raise ValueError("prospective_outbox_source_shape_invalid")
        object.__setattr__(self, "target_lifecycle_state", ProspectiveLifecycleState(self.target_lifecycle_state))
        trigger = normalize_trigger(self.trigger)
        if prospective_trigger_hash(trigger) != self.trigger_hash:
            raise ValueError("prospective_outbox_source_trigger_mismatch")
        object.__setattr__(self, "trigger", trigger)

    def to_json(self):
        return {
            "schema_version": 1, "subject": self.subject,
            "outbox_id": self.outbox_id, "outbox_payload_hash": self.outbox_payload_hash,
            "outbox_created_at": self.outbox_created_at,
            "command": self.command, "target_memory_id": self.target_memory_id,
            "target_revision": self.target_revision, "registration_revision": self.registration_revision,
            "target_scope": {"kind": self.target_scope.kind.value, "owner_id": self.target_scope.owner_id},
            "target_task_scope_id": self.target_task_scope_id,
            "target_lifecycle_state": self.target_lifecycle_state.value,
            "target_run_id": self.target_run_id, "target_plan_id": self.target_plan_id,
            "target_plan_hash": self.target_plan_hash, "target_operation_id": self.target_operation_id,
            "target_operation_kind": self.target_operation_kind,
            "target_mutation_receipt_ref": self.target_mutation_receipt_ref.to_json(),
            "trigger": self.trigger.to_json(), "trigger_hash": self.trigger_hash,
            "outbox_cause_status": self.outbox_cause_status,
        }

    @property
    def source_hash(self):
        return history_hash("memory.prospective.outbox.target-source.v1", self.to_json())
