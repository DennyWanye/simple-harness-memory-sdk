"""Append-only suppression and sealed audit access contracts."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    DeliveryRecipient,
    DisclosureContext,
    DisclosurePurpose,
    DisclosureSource,
    DisclosureTrust,
)

from simple_harness_memory.core.errors import MemoryErrorBase, MemoryValidationError


class SuppressionDenied(MemoryErrorBase):
    code = "memory_suppressed"


class SealedAuditAccessDenied(MemoryErrorBase):
    code = "sealed_audit_access_denied"


class SuppressionScopeKind(StrEnum):
    EVIDENCE = "evidence"
    MEMORY = "memory"
    ENTITY = "entity"
    SUBJECT = "subject"


class OrdinaryMemoryPurpose(StrEnum):
    READ = "read"
    SEARCH = "search"
    RECALL = "recall"
    MUTATION = "mutation"
    EXPORT = "export"
    PROJECTION = "projection"


class SuppressionAction(StrEnum):
    DIRECTIVE = "directive"
    REVOKE = "revoke"


class SealedAuditPurpose(StrEnum):
    EVIDENCE_AUDIT = "sealed_evidence_audit"


def _identifier(value: object, name: str, *, max_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode()) > max_bytes
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


_REASON_CODE_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


def _reason_code(value: object, name: str) -> str:
    if not isinstance(value, str) or _REASON_CODE_RE.fullmatch(value) is None:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _timestamp(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return float(value)


def _positive_int(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SuppressionRequest:
    request_id: str
    subject: str
    scope_kind: SuppressionScopeKind
    scope_ref: str
    reason_code: str
    requested_at: float
    purpose: OrdinaryMemoryPurpose | None = None
    schema_version: int = 1
    request_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise MemoryValidationError("suppression_request_schema_unsupported")
        for value, name in (
            (self.request_id, "suppression_request_id"),
            (self.subject, "suppression_subject"),
            (self.scope_ref, "suppression_scope_ref"),
        ):
            _identifier(value, name)
        _reason_code(self.reason_code, "suppression_reason_code")
        object.__setattr__(self, "scope_kind", SuppressionScopeKind(self.scope_kind))
        if self.scope_kind is SuppressionScopeKind.SUBJECT and self.scope_ref != self.subject:
            raise MemoryValidationError("subject_suppression_scope_differs")
        if self.purpose is not None:
            object.__setattr__(self, "purpose", OrdinaryMemoryPurpose(self.purpose))
        object.__setattr__(self, "requested_at", _timestamp(self.requested_at, "requested_at"))
        object.__setattr__(self, "request_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "subject": self.subject,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "reason_code": self.reason_code,
            "purpose": None if self.purpose is None else self.purpose.value,
            "requested_at": self.requested_at,
        }


@dataclass(frozen=True, slots=True)
class SuppressionRevokeRequest:
    request_id: str
    subject: str
    directive_id: str
    reason_code: str
    requested_at: float
    schema_version: int = 1
    request_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise MemoryValidationError("suppression_revoke_schema_unsupported")
        for value, name in (
            (self.request_id, "suppression_revoke_request_id"),
            (self.subject, "suppression_subject"),
            (self.directive_id, "suppression_directive_id"),
        ):
            _identifier(value, name)
        _reason_code(self.reason_code, "suppression_reason_code")
        object.__setattr__(self, "requested_at", _timestamp(self.requested_at, "requested_at"))
        object.__setattr__(self, "request_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "subject": self.subject,
            "directive_id": self.directive_id,
            "reason_code": self.reason_code,
            "requested_at": self.requested_at,
        }


@dataclass(frozen=True, slots=True)
class SuppressionDecision:
    directive_id: str
    request_id: str
    subject: str
    action: SuppressionAction
    scope_kind: SuppressionScopeKind
    scope_ref: str
    reason_code: str
    effective_at: float
    purpose: OrdinaryMemoryPurpose | None = None
    supersedes_directive_id: str | None = None
    rebuild_outbox_id: str = ""
    schema_version: int = 1
    decision_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise MemoryValidationError("suppression_decision_schema_unsupported")
        for value, name in (
            (self.directive_id, "suppression_directive_id"),
            (self.request_id, "suppression_request_id"),
            (self.subject, "suppression_subject"),
            (self.scope_ref, "suppression_scope_ref"),
            (self.rebuild_outbox_id, "suppression_rebuild_outbox_id"),
        ):
            _identifier(value, name)
        _reason_code(self.reason_code, "suppression_reason_code")
        object.__setattr__(self, "action", SuppressionAction(self.action))
        object.__setattr__(self, "scope_kind", SuppressionScopeKind(self.scope_kind))
        if self.scope_kind is SuppressionScopeKind.SUBJECT and self.scope_ref != self.subject:
            raise MemoryValidationError("subject_suppression_scope_differs")
        if self.purpose is not None:
            object.__setattr__(self, "purpose", OrdinaryMemoryPurpose(self.purpose))
        if self.action is SuppressionAction.DIRECTIVE:
            if self.supersedes_directive_id is not None:
                raise MemoryValidationError("directive_cannot_supersede")
        elif self.supersedes_directive_id is None:
            raise MemoryValidationError("revoke_requires_directive")
        if self.supersedes_directive_id is not None:
            _identifier(self.supersedes_directive_id, "superseded_directive_id")
        object.__setattr__(self, "effective_at", _timestamp(self.effective_at, "effective_at"))
        object.__setattr__(self, "decision_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "directive_id": self.directive_id,
            "request_id": self.request_id,
            "subject": self.subject,
            "action": self.action.value,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "reason_code": self.reason_code,
            "purpose": None if self.purpose is None else self.purpose.value,
            "supersedes_directive_id": self.supersedes_directive_id,
            "rebuild_outbox_id": self.rebuild_outbox_id,
            "effective_at": self.effective_at,
        }


@dataclass(frozen=True, slots=True)
class SuppressionCandidate:
    subject: str
    evidence_id: str | None = None
    memory_id: str | None = None
    entity_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.subject, "suppression_subject")
        for value, name in (
            (self.evidence_id, "suppression_evidence_id"),
            (self.memory_id, "suppression_memory_id"),
        ):
            if value is not None:
                _identifier(value, name)
        entities = tuple(_identifier(value, "suppression_entity_id") for value in self.entity_ids)
        if len(set(entities)) != len(entities):
            raise MemoryValidationError("suppression_entity_ids_duplicated")
        object.__setattr__(self, "entity_ids", entities)


@dataclass(frozen=True, slots=True)
class SuppressionResolution:
    denied: bool
    directive_ids: tuple[str, ...]
    checked_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.denied, bool) or self.denied != bool(self.directive_ids):
            raise MemoryValidationError("suppression_resolution_invalid")
        object.__setattr__(self, "checked_at", _timestamp(self.checked_at, "checked_at"))


@dataclass(frozen=True, slots=True)
class SealedAuditAccessDecision:
    decision_id: str
    subject: str
    scope_kind: SuppressionScopeKind
    scope_ref: str
    reason_code: str
    disclosure_context: DisclosureContext
    max_reads: int
    issued_at: float
    expires_at: float
    purpose: SealedAuditPurpose = SealedAuditPurpose.EVIDENCE_AUDIT
    schema_version: int = 1
    decision_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise MemoryValidationError("sealed_audit_decision_schema_unsupported")
        for value, name in (
            (self.decision_id, "audit_decision_id"),
            (self.subject, "audit_subject"),
            (self.scope_ref, "audit_scope_ref"),
        ):
            _identifier(value, name)
        _reason_code(self.reason_code, "audit_reason_code")
        object.__setattr__(self, "scope_kind", SuppressionScopeKind(self.scope_kind))
        object.__setattr__(self, "purpose", SealedAuditPurpose(self.purpose))
        if self.scope_kind not in {
            SuppressionScopeKind.EVIDENCE,
            SuppressionScopeKind.MEMORY,
            SuppressionScopeKind.SUBJECT,
        }:
            raise MemoryValidationError("sealed_audit_scope_unsupported")
        if self.scope_kind is SuppressionScopeKind.SUBJECT and self.scope_ref != self.subject:
            raise MemoryValidationError("audit_subject_scope_differs")
        if not isinstance(self.disclosure_context, DisclosureContext):
            raise TypeError("sealed audit decision requires DisclosureContext")
        context = self.disclosure_context
        if (
            context.subject != self.subject
            or context.purpose is not DisclosurePurpose.AUDIT
            or context.source is not DisclosureSource.AUDIT_ACCESS_DECISION
            or context.trust is not DisclosureTrust.TRUSTED_AUTHORITY
            or context.recipient is not DeliveryRecipient.AUDIT_REVIEWER
        ):
            raise MemoryValidationError("sealed_audit_disclosure_authority_invalid")
        object.__setattr__(
            self, "max_reads", _positive_int(self.max_reads, "max_reads", maximum=32)
        )
        issued_at = _timestamp(self.issued_at, "issued_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise MemoryValidationError("sealed_audit_expiry_invalid")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "decision_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "subject": self.subject,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "reason_code": self.reason_code,
            "disclosure_context": self.disclosure_context.to_json(),
            "max_reads": self.max_reads,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "purpose": self.purpose.value,
        }


@dataclass(frozen=True, slots=True)
class SealedAuditAccessReceipt:
    access_receipt_id: str
    decision_id: str
    subject: str
    scope_kind: SuppressionScopeKind
    scope_ref: str
    purpose: SealedAuditPurpose
    decision_hash: str
    max_reads: int
    issued_at: float
    expires_at: float
    schema_version: int = 1
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise MemoryValidationError("sealed_audit_receipt_schema_unsupported")
        for value, name in (
            (self.access_receipt_id, "audit_access_receipt_id"),
            (self.decision_id, "audit_decision_id"),
            (self.subject, "audit_subject"),
            (self.scope_ref, "audit_scope_ref"),
        ):
            _identifier(value, name)
        if (
            not isinstance(self.decision_hash, str)
            or _DIGEST_RE.fullmatch(self.decision_hash) is None
        ):
            raise MemoryValidationError("audit_decision_hash_invalid")
        object.__setattr__(self, "scope_kind", SuppressionScopeKind(self.scope_kind))
        object.__setattr__(self, "purpose", SealedAuditPurpose(self.purpose))
        if self.scope_kind not in {
            SuppressionScopeKind.EVIDENCE,
            SuppressionScopeKind.MEMORY,
            SuppressionScopeKind.SUBJECT,
        }:
            raise MemoryValidationError("sealed_audit_scope_unsupported")
        if self.scope_kind is SuppressionScopeKind.SUBJECT and self.scope_ref != self.subject:
            raise MemoryValidationError("audit_subject_scope_differs")
        object.__setattr__(
            self, "max_reads", _positive_int(self.max_reads, "max_reads", maximum=32)
        )
        issued_at = _timestamp(self.issued_at, "issued_at")
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise MemoryValidationError("sealed_audit_expiry_invalid")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "receipt_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "access_receipt_id": self.access_receipt_id,
            "decision_id": self.decision_id,
            "subject": self.subject,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "purpose": self.purpose.value,
            "decision_hash": self.decision_hash,
            "max_reads": self.max_reads,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


__all__ = (
    "OrdinaryMemoryPurpose",
    "SealedAuditAccessDecision",
    "SealedAuditAccessDenied",
    "SealedAuditAccessReceipt",
    "SealedAuditPurpose",
    "SuppressionAction",
    "SuppressionCandidate",
    "SuppressionDecision",
    "SuppressionDenied",
    "SuppressionRequest",
    "SuppressionResolution",
    "SuppressionRevokeRequest",
    "SuppressionScopeKind",
)
