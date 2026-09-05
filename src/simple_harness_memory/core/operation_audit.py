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


FAMILIES = (
    "mutation_commit",
    "mutation_rejection",
    "typed_request",
    "typed_attempt",
    "typed_terminal",
    "recall_context_use",
    "short_recall",
    "suppression",
    "job_transition",
)
COVERAGE_VERSION = "oa1.v1"


@dataclass(frozen=True, slots=True)
class OperationAuditItemV1:
    family: str
    event_kind: str
    event_ref_hash: str
    operation_ref_hash: str
    attempt_ref_hash: str | None
    occurred_at: float
    outcome: str
    receipt_hash: str
    cognitive_effect: str = "not_applicable"
    effect_receipt_hashes: tuple[str, ...] = ()
    committed_operation_ref_hashes: tuple[str, ...] = ()
    item_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.family not in FAMILIES or self.outcome not in (
            "committed",
            "rejected",
            "started",
            "observed",
            "unknown",
        ):
            raise MemoryValidationError("operation_audit_item_scope_invalid")
        _identifier(self.event_kind)
        if len(self.event_kind) > 64 or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in self.event_kind
        ):
            raise MemoryValidationError("operation_audit_kind_invalid")
        for digest in (self.event_ref_hash, self.operation_ref_hash, self.receipt_hash):
            _digest(digest)
        if self.attempt_ref_hash is not None:
            _digest(self.attempt_ref_hash)
        if self.cognitive_effect not in ("written", "no_mutation", "unverified", "not_applicable"):
            raise MemoryValidationError("operation_audit_effect_invalid")
        for name in ("effect_receipt_hashes", "committed_operation_ref_hashes"):
            values = tuple(getattr(self, name))
            for value in values:
                _digest(value)
            if values != tuple(sorted(set(values))):
                raise MemoryValidationError("operation_audit_effect_refs_invalid")
            object.__setattr__(self, name, values)
        if self.cognitive_effect == "written" and not self.committed_operation_ref_hashes:
            raise MemoryValidationError("operation_audit_written_receipt_missing")
        if self.cognitive_effect in ("written", "no_mutation") and not self.effect_receipt_hashes:
            raise MemoryValidationError("operation_audit_effect_receipt_missing")
        if (
            type(self.occurred_at) not in (int, float)
            or not math.isfinite(self.occurred_at)
            or self.occurred_at < 0
        ):
            raise MemoryValidationError("operation_audit_time_invalid")
        object.__setattr__(self, "occurred_at", float(self.occurred_at))
        object.__setattr__(
            self, "item_hash", _hash("memory.operation.audit.item.v1", self.to_json())
        )

    def to_json(self) -> dict[str, Any]:
        return {
            name: list(value) if isinstance(value, tuple) else value
            for name in self.__dataclass_fields__
            if name != "item_hash"
            for value in (getattr(self, name),)
        }


@dataclass(frozen=True, slots=True)
class OperationAuditExpectation:
    family: str
    event_ref_hash: str
    receipt_hash: str

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise MemoryValidationError("operation_audit_family_invalid")
        _digest(self.event_ref_hash)
        _digest(self.receipt_hash)

    def to_json(self) -> dict[str, str]:
        return dict(
            family=self.family, event_ref_hash=self.event_ref_hash, receipt_hash=self.receipt_hash
        )


@dataclass(frozen=True, slots=True)
class OperationAuditCursor:
    token: str

    def __post_init__(self) -> None:
        if type(self.token) is not str or not 1 <= len(self.token) <= 16384:
            raise MemoryValidationError("operation_audit_cursor_invalid")

    def to_json(self) -> dict[str, str]:
        return {"token": self.token}


@dataclass(frozen=True, slots=True)
class OperationAuditCoverage:
    family: str
    row_count: int
    root_hash: str
    supported_event_kinds: tuple[str, ...]
    exclusions: tuple[str, ...]
    unresolved_ref_hashes: tuple[str, ...] = ()
    missing_event_ref_hashes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.family not in FAMILIES or type(self.row_count) is not int or self.row_count < 0:
            raise MemoryValidationError("operation_audit_coverage_invalid")
        _digest(self.root_hash)
        for name in (
            "supported_event_kinds",
            "exclusions",
            "unresolved_ref_hashes",
            "missing_event_ref_hashes",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def to_json(self) -> dict[str, Any]:
        return {
            name: list(value) if isinstance(value, tuple) else value
            for name in self.__dataclass_fields__
            for value in (getattr(self, name),)
        }


@dataclass(frozen=True, slots=True)
class OperationAuditExpectationResult:
    expectation: OperationAuditExpectation
    status: str

    def to_json(self) -> dict[str, Any]:
        return {"expectation": self.expectation.to_json(), "status": self.status}


@dataclass(frozen=True, slots=True)
class OperationAuditPage:
    principal_ref_hash: str
    snapshot_hash: str
    items: tuple[OperationAuditItemV1, ...]
    coverage: tuple[OperationAuditCoverage, ...]
    expectation_results: tuple[OperationAuditExpectationResult, ...]
    next_cursor: OperationAuditCursor | None
    access_event_hash: str
    schema_version: int = field(default=1, init=False)
    coverage_version: str = field(default=COVERAGE_VERSION, init=False)
    all_operations_recorded: bool = field(default=False, init=False)
    page_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (self.principal_ref_hash, self.snapshot_hash, self.access_event_hash):
            _digest(value)
        for name in ("items", "coverage", "expectation_results"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(
            self, "page_hash", _hash("memory.operation.audit.page.v1", self.to_json())
        )

    @property
    def enumeration_complete(self) -> bool:
        return self.next_cursor is None

    def to_json(self) -> dict[str, Any]:
        # Access event is a distinct current read, not part of replay-stable data.
        return dict(
            schema_version=1,
            coverage_version=self.coverage_version,
            principal_ref_hash=self.principal_ref_hash,
            snapshot_hash=self.snapshot_hash,
            items=[v.to_json() for v in self.items],
            coverage=[v.to_json() for v in self.coverage],
            expectation_results=[v.to_json() for v in self.expectation_results],
            next_cursor=None if self.next_cursor is None else self.next_cursor.to_json(),
            enumeration_complete=self.enumeration_complete,
            all_operations_recorded=False,
        )
