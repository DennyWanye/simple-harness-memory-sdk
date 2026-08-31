"""Typed repository results for Procedure observations and Prospective signals."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import ProcedureLifecycleState, ProspectiveLifecycleState

from simple_harness_memory.core.errors import MemoryValidationError

UNBOUND_PROCEDURE_APPLICABILITY = "unbound:procedure-applicability:v2"


class LifecycleApplyOutcome(StrEnum):
    APPLIED = "applied"
    ACKNOWLEDGED = "acknowledged"
    IGNORED = "ignored"


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _revision(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise MemoryValidationError("decided_at_invalid")
    return float(value)


def _hash(domain: str, value: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(
        canonical_json({"domain": domain, "payload": dict(value)}).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProcedureObservationApplyResult:
    result_id: str
    observation_id: str
    decision_id: str
    memory_id: str
    base_revision: int
    committed_revision: int
    lifecycle_state: ProcedureLifecycleState
    independent_successes: int
    reason_code: str
    decided_at: float
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.result_id, "result_id"),
            (self.observation_id, "observation_id"),
            (self.decision_id, "decision_id"),
            (self.memory_id, "memory_id"),
            (self.reason_code, "reason_code"),
        ):
            _identifier(value, name)
        _revision(self.base_revision, "base_revision")
        _revision(self.committed_revision, "committed_revision")
        if self.committed_revision not in {self.base_revision, self.base_revision + 1}:
            raise MemoryValidationError("procedure_result_revision_invalid")
        object.__setattr__(
            self, "lifecycle_state", ProcedureLifecycleState(self.lifecycle_state)
        )
        if (
            isinstance(self.independent_successes, bool)
            or not isinstance(self.independent_successes, int)
            or self.independent_successes < 0
        ):
            raise MemoryValidationError("independent_successes_invalid")
        object.__setattr__(self, "decided_at", _time(self.decided_at))
        object.__setattr__(
            self,
            "result_hash",
            _hash("simple-harness-memory/procedure-observation-result/v1", self.to_json()),
        )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "result_id": self.result_id,
            "observation_id": self.observation_id,
            "decision_id": self.decision_id,
            "memory_id": self.memory_id,
            "base_revision": self.base_revision,
            "committed_revision": self.committed_revision,
            "lifecycle_state": self.lifecycle_state.value,
            "independent_successes": self.independent_successes,
            "reason_code": self.reason_code,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> ProcedureObservationApplyResult:
        expected = {
            "result_id", "observation_id", "decision_id", "memory_id", "base_revision",
            "committed_revision", "lifecycle_state", "independent_successes", "reason_code",
            "decided_at",
        }
        if set(value) != expected:
            raise MemoryValidationError("procedure_result_wire_invalid")
        return cls(
            _identifier(value["result_id"], "result_id"),
            _identifier(value["observation_id"], "observation_id"),
            _identifier(value["decision_id"], "decision_id"),
            _identifier(value["memory_id"], "memory_id"),
            _revision(value["base_revision"], "base_revision"),
            _revision(value["committed_revision"], "committed_revision"),
            ProcedureLifecycleState(value["lifecycle_state"]),
            _revision_or_zero(value["independent_successes"], "independent_successes"),
            _identifier(value["reason_code"], "reason_code"),
            _time(value["decided_at"]),
        )


def _revision_or_zero(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryValidationError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProspectiveSignalApplyResult:
    result_id: str
    signal_id: str
    decision_id: str
    memory_id: str
    base_revision: int
    committed_revision: int
    lifecycle_state: ProspectiveLifecycleState
    outcome: LifecycleApplyOutcome
    reason_code: str
    decided_at: float
    result_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.result_id, "result_id"),
            (self.signal_id, "signal_id"),
            (self.decision_id, "decision_id"),
            (self.memory_id, "memory_id"),
            (self.reason_code, "reason_code"),
        ):
            _identifier(value, name)
        _revision(self.base_revision, "base_revision")
        _revision(self.committed_revision, "committed_revision")
        if self.committed_revision not in {self.base_revision, self.base_revision + 1}:
            raise MemoryValidationError("prospective_result_revision_invalid")
        object.__setattr__(
            self, "lifecycle_state", ProspectiveLifecycleState(self.lifecycle_state)
        )
        object.__setattr__(self, "outcome", LifecycleApplyOutcome(self.outcome))
        object.__setattr__(self, "decided_at", _time(self.decided_at))
        object.__setattr__(
            self,
            "result_hash",
            _hash("simple-harness-memory/prospective-signal-result/v1", self.to_json()),
        )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "result_id": self.result_id,
            "signal_id": self.signal_id,
            "decision_id": self.decision_id,
            "memory_id": self.memory_id,
            "base_revision": self.base_revision,
            "committed_revision": self.committed_revision,
            "lifecycle_state": self.lifecycle_state.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, object]) -> ProspectiveSignalApplyResult:
        expected = {
            "result_id", "signal_id", "decision_id", "memory_id", "base_revision",
            "committed_revision", "lifecycle_state", "outcome", "reason_code", "decided_at",
        }
        if set(value) != expected:
            raise MemoryValidationError("prospective_result_wire_invalid")
        return cls(
            _identifier(value["result_id"], "result_id"),
            _identifier(value["signal_id"], "signal_id"),
            _identifier(value["decision_id"], "decision_id"),
            _identifier(value["memory_id"], "memory_id"),
            _revision(value["base_revision"], "base_revision"),
            _revision(value["committed_revision"], "committed_revision"),
            ProspectiveLifecycleState(value["lifecycle_state"]),
            LifecycleApplyOutcome(str(value["outcome"])),
            _identifier(value["reason_code"], "reason_code"),
            _time(value["decided_at"]),
        )


__all__ = (
    "LifecycleApplyOutcome",
    "ProcedureObservationApplyResult",
    "ProspectiveSignalApplyResult",
    "UNBOUND_PROCEDURE_APPLICABILITY",
)
