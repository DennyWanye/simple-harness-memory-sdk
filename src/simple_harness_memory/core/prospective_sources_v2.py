"""Explicit mutation/signal target lineage; no substitute mutation receipts."""
import math
from dataclasses import dataclass, field
from simple_harness.runtime import MemoryMutationApplyReceiptRef, ProspectiveLifecycleState, prospective_trigger_hash
from simple_harness_memory.core.history import history_hash
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.lifecycle_results import ProspectiveSignalApplyResult, LifecycleApplyOutcome
from simple_harness_memory.core.mutation_receipts import _identifier, _digest, _revision
from simple_harness_memory.core.prospective import normalize_trigger


@dataclass(frozen=True, slots=True)
class MutationTargetSource:
    mutation_receipt_ref: MemoryMutationApplyReceiptRef
    plan_id: str
    plan_hash: str
    run_id: str
    operation_id: str
    operation_kind: str
    kind: str = field(default="mutation", init=False)

    def __post_init__(self):
        if type(self.mutation_receipt_ref) is not MemoryMutationApplyReceiptRef:
            raise TypeError("mutation_receipt_ref must be the actual mutation receipt type")
        for name in ("plan_id", "run_id", "operation_id", "operation_kind"):
            _identifier(getattr(self, name), name)
        _digest(self.plan_hash, "plan_hash")

    def to_json(self):
        return {name: (value.to_json() if name == "mutation_receipt_ref" else value)
            for name in self.__dataclass_fields__ for value in (getattr(self, name),)}


@dataclass(frozen=True, slots=True)
class ProspectiveSignalTargetSource:
    apply_result: ProspectiveSignalApplyResult
    signal_kind: str
    intent_hash: str
    authority_id: str
    authority_hash: str
    authority_ref_hash: str
    consumption_id: str
    consumption_hash: str
    decision_id: str
    decision_hash: str
    upstream_signal_receipt_id: str
    upstream_signal_receipt_hash: str
    run_id: str
    operation_id: str
    kind: str = field(default="prospective_signal", init=False)

    def __post_init__(self):
        if (type(self.apply_result) is not ProspectiveSignalApplyResult
                or self.apply_result.outcome is not LifecycleApplyOutcome.APPLIED
                or self.apply_result.committed_revision != self.apply_result.base_revision + 1
                or self.decision_id != self.apply_result.decision_id
                or self.signal_kind not in {"time_due", "event_occurred", "expired"}):
            raise ValueError("prospective_signal_target_source_invalid")
        for name in ("authority_id", "consumption_id", "decision_id", "upstream_signal_receipt_id",
                     "run_id", "operation_id"):
            _identifier(getattr(self, name), name)
        for name in ("intent_hash", "authority_hash", "authority_ref_hash", "consumption_hash",
                     "decision_hash", "upstream_signal_receipt_hash"):
            _digest(getattr(self, name), name)

    def to_json(self):
        return {name: (value.to_json() if name == "apply_result" else value)
            for name in self.__dataclass_fields__ for value in (getattr(self, name),)} | {
                "apply_result_hash": self.apply_result.result_hash}


@dataclass(frozen=True, slots=True)
class ProspectiveOutboxSourceViewV2:
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
    trigger: object
    trigger_hash: str
    target_source: MutationTargetSource | ProspectiveSignalTargetSource
    outbox_cause_status: str = "not_persisted"
    schema_version: int = 2
    operation_observation: object | None = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        for name in ("subject", "outbox_id", "target_memory_id"):
            _identifier(getattr(self, name), name)
        for name in ("outbox_payload_hash", "trigger_hash"):
            _digest(getattr(self, name), name)
        _revision(self.target_revision, "target_revision")
        _revision(self.registration_revision, "registration_revision")
        if self.target_task_scope_id is not None:
            _identifier(self.target_task_scope_id, "target_task_scope_id")
        if (type(self.schema_version) is not int or self.schema_version != 2
                or self.command not in {"registration", "invalidation"}
                or self.outbox_cause_status != "not_persisted"
                or self.registration_revision != self.target_revision
                or type(self.target_scope) is not MemoryScope
                or type(self.target_source) not in (MutationTargetSource, ProspectiveSignalTargetSource)
                or type(self.outbox_created_at) not in (int, float)
                or not math.isfinite(self.outbox_created_at) or self.outbox_created_at < 0):
            raise ValueError("prospective_outbox_source_v2_invalid")
        object.__setattr__(self, "outbox_created_at", float(self.outbox_created_at))
        object.__setattr__(self, "target_lifecycle_state", ProspectiveLifecycleState(self.target_lifecycle_state))
        trigger = normalize_trigger(self.trigger)
        if prospective_trigger_hash(trigger) != self.trigger_hash:
            raise ValueError("prospective_outbox_source_v2_trigger_invalid")
        object.__setattr__(self, "trigger", trigger)
        if type(self.target_source) is ProspectiveSignalTargetSource:
            result = self.target_source.apply_result
            if (result.memory_id != self.target_memory_id
                    or result.committed_revision != self.target_revision
                    or result.lifecycle_state != self.target_lifecycle_state):
                raise ValueError("prospective_signal_target_result_differs")

    def to_json(self):
        return {name: getattr(self, name) for name in (
            "schema_version", "subject", "outbox_id", "outbox_payload_hash", "outbox_created_at",
            "command", "target_memory_id", "target_revision", "registration_revision",
            "target_task_scope_id", "trigger_hash", "outbox_cause_status")} | {
            "target_scope": {"kind": self.target_scope.kind.value, "owner_id": self.target_scope.owner_id},
            "target_lifecycle_state": self.target_lifecycle_state.value, "trigger": self.trigger.to_json(),
            "target_source": self.target_source.to_json()}

    @property
    def source_hash(self):
        return history_hash("memory.prospective.outbox.target-source.v2", self.to_json())
