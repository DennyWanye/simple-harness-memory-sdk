"""Payload-free operation observations. Host persistence is a separate authority."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from simple_harness_memory.core.errors import MemoryValidationError


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(domain: str, payload: Any) -> str:
    return hashlib.sha256(_canonical({"domain": domain, "payload": payload}).encode()).hexdigest()


def operation_audit_ref_hash(kind: str, value: str) -> str:
    """Hash a real source reference; this utility grants no authority."""
    _identifier(kind)
    _identifier(value)
    return _hash("memory.operation.audit.ref.v1", {"kind": kind, "value": value})


def _identifier(value: object) -> None:
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise MemoryValidationError("operation_audit_identifier_invalid")


def _digest(value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise MemoryValidationError("operation_audit_digest_invalid")


@dataclass(frozen=True, slots=True)
class MemoryOperationObservationContext:
    host_request_ref: str
    host_attempt_ref: str

    def __post_init__(self) -> None:
        _identifier(self.host_request_ref)
        _identifier(self.host_attempt_ref)


_REASONS = {
    "protocol": frozenset(
        (
            "typed_recall_protocol_invalid",
            "typed_recall_protocol_unsupported",
            "typed_recall_input_type_invalid",
        )
    ),
    "ownership": frozenset(("typed_recall_subject_not_owned",)),
    "narrowing": frozenset(("typed_recall_narrowing_rejected",)),
    "idempotency": frozenset(("IDEMPOTENCY_CONFLICT",)),
}


@dataclass(frozen=True, slots=True)
class MemoryOperationObservationV1:
    schema_version: int
    operation: str
    host_request_ref_hash: str
    host_attempt_ref_hash: str
    invocation_ref_hash: str
    request_hash: str | None
    context_hash: str | None
    plan_hash: str | None
    stage: str
    reason: str
    candidate_query_started: bool
    candidate_query_count: int
    observed_at: float
    persistence_status: str = "host_persistence_unverified"
    observation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise MemoryValidationError("operation_observation_version_invalid")
        if (
            self.operation != "execute_typed_recall"
            or self.persistence_status != "host_persistence_unverified"
        ):
            raise MemoryValidationError("operation_observation_scope_invalid")
        for value in (
            self.host_request_ref_hash,
            self.host_attempt_ref_hash,
            self.invocation_ref_hash,
        ):
            _digest(value)
        for optional_digest in (self.request_hash, self.context_hash, self.plan_hash):
            if optional_digest is not None:
                _digest(optional_digest)
        if self.stage not in _REASONS or self.reason not in _REASONS[self.stage]:
            raise MemoryValidationError("operation_observation_reason_invalid")
        if (
            self.candidate_query_started is not False
            or type(self.candidate_query_count) is not int
            or self.candidate_query_count != 0
        ):
            raise MemoryValidationError("operation_observation_candidate_scope_invalid")
        if (
            type(self.observed_at) not in (int, float)
            or not math.isfinite(self.observed_at)
            or self.observed_at < 0
        ):
            raise MemoryValidationError("operation_observation_time_invalid")
        object.__setattr__(self, "observed_at", float(self.observed_at))
        object.__setattr__(
            self, "observation_hash", _hash("memory.operation.audit.observation.v1", self.to_json())
        )

    def to_json(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "observation_hash"
        }


def _observe_rejection(
    error: Exception, context: MemoryOperationObservationContext, now: float
) -> None:
    from simple_harness_memory.core.recall import TypedRecallRejectionV1

    witness = getattr(error, "rejection_receipt", None)
    if type(witness) is not TypedRecallRejectionV1 or witness.schema_version != 1:
        return
    if witness.candidate_query_started is not False or witness.candidate_query_count != 0:
        return
    reason = witness.reason
    if witness.stage == "protocol" and reason in (
        "principal must use MemoryPrincipal",
        "context must use RecallContext",
        "plan must use RecallPlan",
    ):
        reason = "typed_recall_input_type_invalid"
    elif witness.stage == "narrowing":
        # Do not forward arbitrary exception text. The actual witness stays on error.
        reason = "typed_recall_narrowing_rejected"
    if witness.stage not in _REASONS or reason not in _REASONS[witness.stage]:
        return
    error.operation_observation = MemoryOperationObservationV1(  # type: ignore[attr-defined]
        1,
        "execute_typed_recall",
        operation_audit_ref_hash("host_request", context.host_request_ref),
        operation_audit_ref_hash("host_attempt", context.host_attempt_ref),
        operation_audit_ref_hash("invocation", witness.invocation_id),
        witness.request_hash,
        witness.context_hash,
        witness.plan_hash,
        witness.stage,
        reason,
        False,
        0,
        now,
    )
