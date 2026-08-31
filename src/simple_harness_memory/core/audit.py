"""Public-only LLM invocation, decision, and stable audit trace contracts."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast

from simple_harness.contracts import (
    FrozenJsonValue,
    JsonValue,
    canonical_json,
    freeze_json,
    thaw_json,
)
from simple_harness.runtime import (
    EvidenceRef,
    MemoryAnalysisDeliveryReceipt,
    MemoryAnalysisReceipt,
)

from simple_harness_memory.core.errors import MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.suppression import SuppressionScopeKind

MAX_AUDIT_PUBLIC_BYTES = 256 * 1024
MAX_AUDIT_PUBLIC_NODES = 8192
MAX_AUDIT_PUBLIC_DEPTH = 32

_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:sk|key|tsk)-?[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(?:xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{10,})\b"),
    re.compile(r"\b(?:npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)
_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "setcookie",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "password",
        "privatekey",
        "clientsecret",
        "credential",
        "credentials",
        "token",
        "secret",
        "auth",
        "authentication",
        "reasoning",
        "reasoningcontent",
        "reasoningdetails",
        "internalreasoning",
        "hiddenreasoning",
        "chainofthought",
        "thoughts",
        "analysis",
        "analysistext",
        "thinking",
    }
)


class DecisionOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReasoningItemType(StrEnum):
    REASONING = "reasoning"
    THINKING = "thinking"
    REASONING_SUMMARY = "reasoning_summary"


class OutputStorageStatus(StrEnum):
    PUBLIC = "public"
    REJECTED_UNSAFE = "rejected_unsafe"


class AuditTraceSelector(StrEnum):
    TURN = "turn"
    INVOCATION = "invocation"
    DECISION = "decision"
    EVIDENCE = "evidence"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class AuditAccessAuthorityRefV1:
    """Opaque, replay-bound reference minted by an external audit authority."""

    authority_id: str
    issuer_ref: str
    nonce: str
    replay_identity: str
    requester_deployment_id: str
    requester_household_id: str
    requester_actor_id: str
    requester_session_id: str
    target_deployment_id: str
    target_household_id: str
    target_actor_id: str
    target_subject: str
    decision_id: str
    decision_hash: str
    scope_kind: SuppressionScopeKind
    scope_ref: str
    issued_at: float
    expires_at: float
    schema_version: int = 1
    ref_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise MemoryValidationError("audit_authority_ref_schema_unsupported")
        for value, name in (
            (self.authority_id, "audit_authority_id"),
            (self.issuer_ref, "audit_authority_issuer_ref"),
            (self.nonce, "audit_authority_nonce"),
            (self.replay_identity, "audit_authority_replay_identity"),
            (self.requester_deployment_id, "audit_authority_requester_deployment_id"),
            (self.requester_household_id, "audit_authority_requester_household_id"),
            (self.requester_actor_id, "audit_authority_requester_actor_id"),
            (self.requester_session_id, "audit_authority_requester_session_id"),
            (self.target_deployment_id, "audit_authority_target_deployment_id"),
            (self.target_household_id, "audit_authority_target_household_id"),
            (self.target_actor_id, "audit_authority_target_actor_id"),
            (self.target_subject, "audit_authority_target_subject"),
            (self.decision_id, "audit_authority_decision_id"),
            (self.scope_ref, "audit_authority_scope_ref"),
        ):
            _identifier(value, name)
        if self.target_actor_id != self.target_subject:
            raise MemoryValidationError("audit_authority_target_subject_differs")
        _digest(self.decision_hash, "audit_authority_decision_hash")
        object.__setattr__(self, "scope_kind", SuppressionScopeKind(self.scope_kind))
        issued_at = _timestamp(self.issued_at, "audit_authority_issued_at")
        expires_at = _timestamp(self.expires_at, "audit_authority_expires_at")
        if expires_at <= issued_at:
            raise MemoryValidationError("audit_authority_expiry_invalid")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "ref_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "authority_id": self.authority_id,
            "issuer_ref": self.issuer_ref,
            "nonce": self.nonce,
            "replay_identity": self.replay_identity,
            "requester_deployment_id": self.requester_deployment_id,
            "requester_household_id": self.requester_household_id,
            "requester_actor_id": self.requester_actor_id,
            "requester_session_id": self.requester_session_id,
            "target_deployment_id": self.target_deployment_id,
            "target_household_id": self.target_household_id,
            "target_actor_id": self.target_actor_id,
            "target_subject": self.target_subject,
            "decision_id": self.decision_id,
            "decision_hash": self.decision_hash,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_json(cls, value: Mapping[str, JsonValue]) -> AuditAccessAuthorityRefV1:
        try:
            return cls(
                authority_id=cast(str, value["authority_id"]),
                issuer_ref=cast(str, value["issuer_ref"]),
                nonce=cast(str, value["nonce"]),
                replay_identity=cast(str, value["replay_identity"]),
                requester_deployment_id=cast(str, value["requester_deployment_id"]),
                requester_household_id=cast(str, value["requester_household_id"]),
                requester_actor_id=cast(str, value["requester_actor_id"]),
                requester_session_id=cast(str, value["requester_session_id"]),
                target_deployment_id=cast(str, value["target_deployment_id"]),
                target_household_id=cast(str, value["target_household_id"]),
                target_actor_id=cast(str, value["target_actor_id"]),
                target_subject=cast(str, value["target_subject"]),
                decision_id=cast(str, value["decision_id"]),
                decision_hash=cast(str, value["decision_hash"]),
                scope_kind=SuppressionScopeKind(cast(str, value["scope_kind"])),
                scope_ref=cast(str, value["scope_ref"]),
                issued_at=cast(float, value["issued_at"]),
                expires_at=cast(float, value["expires_at"]),
                schema_version=cast(int, value.get("schema_version", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MemoryValidationError("audit_authority_ref_invalid") from exc


class AuditAccessAuthorityPort(Protocol):
    async def resolve_audit_access(
        self, reference: AuditAccessAuthorityRefV1
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AuditAggregateMetricsV1:
    """Fixed-schema aggregate over ordinary-visible trace rows only."""

    principal_ref_hash: str
    visible_invocations: int
    accepted_decisions: int
    rejected_decisions: int
    rejected_unsafe_outputs: int
    input_tokens: int
    output_tokens: int
    cost_microunits: int
    latency_ms: int
    schema_version: int = 1
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise MemoryValidationError("audit_metrics_schema_unsupported")
        _digest(self.principal_ref_hash, "audit_metrics_principal_ref_hash")
        for name in (
            "visible_invocations",
            "accepted_decisions",
            "rejected_decisions",
            "rejected_unsafe_outputs",
            "input_tokens",
            "output_tokens",
            "cost_microunits",
            "latency_ms",
        ):
            _non_negative_int(getattr(self, name), name)
        object.__setattr__(self, "payload_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "principal_ref_hash": self.principal_ref_hash,
            "visible_invocations": self.visible_invocations,
            "accepted_decisions": self.accepted_decisions,
            "rejected_decisions": self.rejected_decisions,
            "rejected_unsafe_outputs": self.rejected_unsafe_outputs,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microunits": self.cost_microunits,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True, slots=True)
class CanonicalStateTableRootV1:
    category: str
    table_name: str
    row_count: int
    root_hash: str
    first_leaf_hash: str | None
    last_leaf_hash: str | None

    def __post_init__(self) -> None:
        _reason(self.category, "manifest_category")
        _reason(self.table_name, "manifest_table_name")
        _non_negative_int(self.row_count, "manifest_row_count")
        _digest(self.root_hash, "manifest_root_hash")
        if self.row_count == 0:
            if self.first_leaf_hash is not None or self.last_leaf_hash is not None:
                raise MemoryValidationError("manifest_empty_canary_invalid")
        else:
            _digest(self.first_leaf_hash, "manifest_first_leaf_hash")
            _digest(self.last_leaf_hash, "manifest_last_leaf_hash")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "category": self.category,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "root_hash": self.root_hash,
            "first_leaf_hash": self.first_leaf_hash,
            "last_leaf_hash": self.last_leaf_hash,
        }


@dataclass(frozen=True, slots=True)
class CanonicalStateManifestV1:
    storage_schema_version: int
    schema_checksum: str
    initialization_receipt_hash: str
    principal_ref_hash: str
    table_roots: tuple[CanonicalStateTableRootV1, ...]
    total_row_count: int
    schema_version: int = 1
    payload_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise MemoryValidationError("state_manifest_schema_unsupported")
        if self.storage_schema_version != 6:
            raise MemoryValidationError("state_manifest_storage_schema_unsupported")
        for value, name in (
            (self.schema_checksum, "state_manifest_schema_checksum"),
            (self.initialization_receipt_hash, "state_manifest_initialization_receipt_hash"),
            (self.principal_ref_hash, "state_manifest_principal_ref_hash"),
        ):
            _digest(value, name)
        roots = tuple(self.table_roots)
        if not roots or not all(isinstance(item, CanonicalStateTableRootV1) for item in roots):
            raise MemoryValidationError("state_manifest_roots_invalid")
        if tuple((item.category, item.table_name) for item in roots) != tuple(
            sorted((item.category, item.table_name) for item in roots)
        ):
            raise MemoryValidationError("state_manifest_roots_not_canonical")
        if sum(item.row_count for item in roots) != self.total_row_count:
            raise MemoryValidationError("state_manifest_count_differs")
        object.__setattr__(self, "table_roots", roots)
        object.__setattr__(self, "payload_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "storage_schema_version": self.storage_schema_version,
            "schema_checksum": self.schema_checksum,
            "initialization_receipt_hash": self.initialization_receipt_hash,
            "principal_ref_hash": self.principal_ref_hash,
            "table_roots": [item.to_json() for item in self.table_roots],
            "total_row_count": self.total_row_count,
        }


@dataclass(frozen=True, slots=True)
class CanonicalStateManifestAccessV1:
    manifest: CanonicalStateManifestV1
    access_event_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, CanonicalStateManifestV1):
            raise TypeError("manifest must use CanonicalStateManifestV1")
        _digest(self.access_event_hash, "manifest_access_event_hash")


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _identifier(value: object, name: str, *, maximum: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode()) > maximum
        or any(pattern.search(value) for pattern in _CREDENTIAL_PATTERNS)
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _reason(value: object, name: str) -> str:
    if not isinstance(value, str) or _REASON_RE.fullmatch(value) is None:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
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


def _refs(value: object, name: str) -> tuple[EvidenceRef, ...]:
    if not isinstance(value, (tuple, list)) or not all(
        isinstance(item, EvidenceRef) for item in value
    ):
        raise TypeError(f"{name} must contain EvidenceRef values")
    refs = tuple(value)
    for item in refs:
        _identifier(item.evidence_id, f"{name}_evidence_id")
    if len({item.evidence_id for item in refs}) != len(refs):
        raise MemoryValidationError(f"{name}_duplicated")
    if refs and tuple(item.ordinal for item in refs) != tuple(range(1, len(refs) + 1)):
        raise MemoryValidationError(f"{name}_ordinal_invalid")
    return refs


def freeze_public_audit_object(
    value: Mapping[str, FrozenJsonValue] | Mapping[str, JsonValue],
) -> Mapping[str, FrozenJsonValue]:
    """Defensively reject credentials and hidden reasoning before persistence."""

    thawed = thaw_json(cast(FrozenJsonValue, value))
    if not isinstance(thawed, dict):
        raise MemoryValidationError("audit_public_output_invalid")
    encoded = canonical_json(thawed).encode()
    if len(encoded) > MAX_AUDIT_PUBLIC_BYTES:
        raise MemoryLimitError("audit_public_output_too_large")
    nodes = 0

    def visit(item: JsonValue, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_AUDIT_PUBLIC_NODES or depth > MAX_AUDIT_PUBLIC_DEPTH:
            raise MemoryLimitError("audit_public_output_structure_limit")
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                if normalized in _FORBIDDEN_KEYS or normalized.endswith(
                    (
                        "apikey",
                        "password",
                        "token",
                        "secret",
                        "credential",
                        "cookie",
                        "privatekey",
                    )
                ):
                    raise MemoryValidationError("audit_private_material_rejected")
                visit(nested, depth + 1)
        elif isinstance(item, list):
            for nested in item:
                visit(nested, depth + 1)
        elif isinstance(item, str) and any(
            pattern.search(item) for pattern in _CREDENTIAL_PATTERNS
        ):
            raise MemoryValidationError("audit_private_material_rejected")

    visit(cast(JsonValue, thawed), 0)
    frozen = freeze_json(cast(JsonValue, thawed))
    if not isinstance(frozen, Mapping):
        raise MemoryValidationError("audit_public_output_invalid")
    return frozen


@dataclass(frozen=True, slots=True)
class PublicReasoningReference:
    provider_item_id: str
    item_type: ReasoningItemType
    item_hash: str
    opaque_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.provider_item_id, "reasoning_provider_item_id")
        object.__setattr__(self, "item_type", ReasoningItemType(self.item_type))
        _digest(self.item_hash, "reasoning_item_hash")
        if self.opaque_ref is not None:
            _identifier(self.opaque_ref, "reasoning_opaque_ref")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "provider_item_id": self.provider_item_id,
            "item_type": self.item_type.value,
            "item_hash": self.item_hash,
            "opaque_ref": self.opaque_ref,
        }


@dataclass(frozen=True, slots=True)
class DecisionLedgerEntry:
    decision_id: str
    operation_id: str
    operation_kind: str
    outcome: DecisionOutcome
    target_kind: SuppressionScopeKind
    target_ref: str
    public_payload: Mapping[str, FrozenJsonValue]
    before_state_refs: tuple[str, ...]
    after_state_refs: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    reason_code: str
    created_at: float
    decision_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.decision_id, "decision_id"),
            (self.operation_id, "operation_id"),
            (self.operation_kind, "operation_kind"),
            (self.target_ref, "decision_target_ref"),
        ):
            _identifier(value, name)
        object.__setattr__(self, "outcome", DecisionOutcome(self.outcome))
        object.__setattr__(self, "target_kind", SuppressionScopeKind(self.target_kind))
        _reason(self.reason_code, "decision_reason_code")
        payload = freeze_public_audit_object(self.public_payload)
        before = tuple(_identifier(item, "before_state_ref") for item in self.before_state_refs)
        after = tuple(_identifier(item, "after_state_ref") for item in self.after_state_refs)
        if len(set(before)) != len(before) or len(set(after)) != len(after):
            raise MemoryValidationError("decision_state_refs_duplicated")
        evidence = _refs(self.evidence_refs, "decision_evidence_refs")
        if not evidence:
            raise MemoryValidationError("decision_evidence_refs_required")
        object.__setattr__(self, "public_payload", payload)
        object.__setattr__(self, "before_state_refs", before)
        object.__setattr__(self, "after_state_refs", after)
        object.__setattr__(self, "evidence_refs", evidence)
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "decision_created_at"))
        object.__setattr__(self, "decision_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "decision_id": self.decision_id,
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "outcome": self.outcome.value,
            "target_kind": self.target_kind.value,
            "target_ref": self.target_ref,
            "public_payload": thaw_json(cast(FrozenJsonValue, self.public_payload)),
            "before_state_refs": list(self.before_state_refs),
            "after_state_refs": list(self.after_state_refs),
            "evidence_refs": [item.to_json() for item in self.evidence_refs],
            "reason_code": self.reason_code,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class LLMInvocationAuditRecord:
    sequence: int
    invocation_id: str
    subject: str
    run_id: str
    turn_id: str
    job_id: str
    request_hash: str
    public_input_refs: tuple[EvidenceRef, ...]
    public_output: Mapping[str, FrozenJsonValue] | None
    public_output_hash: str | None
    output_storage_status: OutputStorageStatus
    output_reason_code: str
    provider_id: str
    model_id: str
    parameters_hash: str
    prompt_version: str
    result_schema_version: str
    policy_version: str
    validator_version: str
    provider_request_id: str | None
    delivery_receipt: MemoryAnalysisDeliveryReceipt | None
    validation_receipt: MemoryAnalysisReceipt
    result_hash: str
    input_tokens: int
    output_tokens: int
    cost_microunits: int
    latency_ms: int
    started_at: float
    completed_at: float
    reasoning_refs: tuple[PublicReasoningReference, ...]
    invocation_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise MemoryValidationError("invocation_sequence_invalid")
        for value, name in (
            (self.invocation_id, "invocation_id"),
            (self.subject, "invocation_subject"),
            (self.run_id, "invocation_run_id"),
            (self.turn_id, "invocation_turn_id"),
            (self.job_id, "invocation_job_id"),
            (self.provider_id, "invocation_provider_id"),
            (self.model_id, "invocation_model_id"),
            (self.prompt_version, "invocation_prompt_version"),
            (self.result_schema_version, "invocation_result_schema_version"),
            (self.policy_version, "invocation_policy_version"),
            (self.validator_version, "invocation_validator_version"),
        ):
            _identifier(value, name)
        for value, name in (
            (self.request_hash, "invocation_request_hash"),
            (self.parameters_hash, "invocation_parameters_hash"),
            (self.result_hash, "invocation_result_hash"),
        ):
            _digest(value, name)
        if self.provider_request_id is not None:
            _identifier(self.provider_request_id, "provider_request_id")
        refs = _refs(self.public_input_refs, "invocation_public_input_refs")
        if not refs:
            raise MemoryValidationError("invocation_public_input_refs_required")
        status = OutputStorageStatus(self.output_storage_status)
        object.__setattr__(self, "output_storage_status", status)
        if status is OutputStorageStatus.PUBLIC:
            if self.public_output is None or self.public_output_hash is None:
                raise MemoryValidationError("invocation_public_output_required")
            output = freeze_public_audit_object(self.public_output)
            if (
                _hash(thaw_json(cast(FrozenJsonValue, output)))
                != self.public_output_hash
            ):
                raise MemoryValidationError("invocation_public_output_hash_differs")
            object.__setattr__(self, "public_output", output)
        elif self.public_output is not None or self.public_output_hash is not None:
            raise MemoryValidationError("unsafe_output_body_must_not_persist")
        _reason(self.output_reason_code, "invocation_output_reason_code")
        if self.delivery_receipt is not None:
            if not isinstance(self.delivery_receipt, MemoryAnalysisDeliveryReceipt):
                raise TypeError("delivery_receipt must use MemoryAnalysisDeliveryReceipt")
            for value, name in (
                (self.delivery_receipt.receipt_id, "delivery_receipt_id"),
                (self.delivery_receipt.issuer_id, "delivery_receipt_issuer_id"),
                (self.delivery_receipt.run_id, "delivery_receipt_run_id"),
                (self.delivery_receipt.job_id, "delivery_receipt_job_id"),
                (self.delivery_receipt.host_receipt_id, "delivery_host_receipt_id"),
            ):
                _identifier(value, name)
            if self.delivery_receipt.provider_response_id is not None:
                _identifier(
                    self.delivery_receipt.provider_response_id,
                    "delivery_provider_response_id",
                )
            decoded_delivery = MemoryAnalysisDeliveryReceipt.from_json(
                self.delivery_receipt.to_json()
            )
            if (
                decoded_delivery.receipt_hash != self.delivery_receipt.receipt_hash
                or self.delivery_receipt.job_id != self.job_id
                or self.delivery_receipt.run_id != self.run_id
                or self.delivery_receipt.request_hash != self.request_hash
                or self.delivery_receipt.result_hash != self.result_hash
                or self.delivery_receipt.provider_response_id != self.provider_request_id
            ):
                raise MemoryValidationError("invocation_delivery_receipt_invalid")
        if not isinstance(self.validation_receipt, MemoryAnalysisReceipt):
            raise TypeError("validation_receipt must use MemoryAnalysisReceipt")
        _identifier(self.validation_receipt.receipt_id, "validation_receipt_id")
        if self.validation_receipt.receipt_hash != MemoryAnalysisReceipt.from_json(
            self.validation_receipt.to_json()
        ).receipt_hash:
            raise MemoryValidationError("invocation_validation_receipt_invalid")
        if (
            self.validation_receipt.job_id != self.job_id
            or self.validation_receipt.run_id != self.run_id
            or self.validation_receipt.request_hash != self.request_hash
            or self.validation_receipt.result_hash != self.result_hash
        ):
            raise MemoryValidationError("invocation_validation_receipt_lineage_differs")
        for name in ("input_tokens", "output_tokens", "cost_microunits", "latency_ms"):
            _non_negative_int(getattr(self, name), name)
        started = _timestamp(self.started_at, "invocation_started_at")
        completed = _timestamp(self.completed_at, "invocation_completed_at")
        if completed < started:
            raise MemoryValidationError("invocation_timing_invalid")
        reasoning = tuple(self.reasoning_refs)
        if not all(isinstance(item, PublicReasoningReference) for item in reasoning):
            raise TypeError("reasoning_refs must use PublicReasoningReference")
        if len({item.provider_item_id for item in reasoning}) != len(reasoning):
            raise MemoryValidationError("reasoning_refs_duplicated")
        object.__setattr__(self, "public_input_refs", refs)
        object.__setattr__(self, "reasoning_refs", reasoning)
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "completed_at", completed)
        object.__setattr__(self, "invocation_hash", _hash(self.hash_json()))

    def hash_json(self) -> dict[str, JsonValue]:
        value = self.to_json()
        value.pop("sequence")
        return value

    @property
    def public_input_hash(self) -> str:
        return _hash([item.to_json() for item in self.public_input_refs])

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "sequence": self.sequence,
            "invocation_id": self.invocation_id,
            "subject": self.subject,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "job_id": self.job_id,
            "request_hash": self.request_hash,
            "public_input_refs": [item.to_json() for item in self.public_input_refs],
            "public_input_hash": self.public_input_hash,
            "public_output": (
                None
                if self.public_output is None
                else thaw_json(cast(FrozenJsonValue, self.public_output))
            ),
            "public_output_hash": self.public_output_hash,
            "output_storage_status": self.output_storage_status.value,
            "output_reason_code": self.output_reason_code,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "parameters_hash": self.parameters_hash,
            "prompt_version": self.prompt_version,
            "result_schema_version": self.result_schema_version,
            "policy_version": self.policy_version,
            "validator_version": self.validator_version,
            "provider_request_id": self.provider_request_id,
            "delivery_receipt": (
                None if self.delivery_receipt is None else self.delivery_receipt.to_json()
            ),
            "validation_receipt": self.validation_receipt.to_json(),
            "result_hash": self.result_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_microunits": self.cost_microunits,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "reasoning_refs": [item.to_json() for item in self.reasoning_refs],
        }


@dataclass(frozen=True, slots=True)
class AuditTraceQuery:
    subject: str
    selector: AuditTraceSelector
    selector_ref: str

    def __post_init__(self) -> None:
        _identifier(self.subject, "audit_trace_subject")
        object.__setattr__(self, "selector", AuditTraceSelector(self.selector))
        _identifier(self.selector_ref, "audit_trace_selector_ref")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "subject": self.subject,
            "selector": self.selector.value,
            "selector_ref": self.selector_ref,
        }


@dataclass(frozen=True, slots=True)
class AuditTraceCursor:
    query_hash: str
    watermark_sequence: int
    last_sequence: int
    cursor_hash: str

    def __post_init__(self) -> None:
        _digest(self.query_hash, "audit_trace_query_hash")
        watermark = _non_negative_int(self.watermark_sequence, "watermark_sequence")
        last = _non_negative_int(self.last_sequence, "last_sequence")
        if last > watermark:
            raise MemoryValidationError("audit_trace_cursor_invalid")
        _digest(self.cursor_hash, "audit_trace_cursor_hash")

    def signing_payload(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 1,
            "query_hash": self.query_hash,
            "watermark_sequence": self.watermark_sequence,
            "last_sequence": self.last_sequence,
        }

    def to_json(self) -> dict[str, JsonValue]:
        return {**self.signing_payload(), "cursor_hash": self.cursor_hash}


@dataclass(frozen=True, slots=True)
class AuditTraceLineageRef:
    kind: str
    ref_hash: str

    def __post_init__(self) -> None:
        _reason(self.kind, "audit_lineage_kind")
        _digest(self.ref_hash, "audit_lineage_ref_hash")

    def to_json(self) -> dict[str, JsonValue]:
        return {"kind": self.kind, "ref_hash": self.ref_hash}


@dataclass(frozen=True, slots=True)
class AuditTraceItem:
    invocation: LLMInvocationAuditRecord
    decisions: tuple[DecisionLedgerEntry, ...]
    lineage_refs: tuple[AuditTraceLineageRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, LLMInvocationAuditRecord):
            raise TypeError("invocation must use LLMInvocationAuditRecord")
        decisions = tuple(self.decisions)
        if not all(isinstance(item, DecisionLedgerEntry) for item in decisions):
            raise TypeError("decisions must use DecisionLedgerEntry")
        lineage = tuple(self.lineage_refs)
        if not all(isinstance(item, AuditTraceLineageRef) for item in lineage):
            raise TypeError("lineage_refs must use AuditTraceLineageRef")
        if lineage != tuple(sorted(lineage, key=lambda item: (item.kind, item.ref_hash))):
            raise MemoryValidationError("audit_lineage_not_canonical")
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "lineage_refs", lineage)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "invocation": self.invocation.to_json(),
            "decisions": [item.to_json() for item in self.decisions],
            "lineage_refs": [item.to_json() for item in self.lineage_refs],
        }


@dataclass(frozen=True, slots=True)
class AuditTracePage:
    items: tuple[AuditTraceItem, ...]
    next_cursor: AuditTraceCursor | None
    page_hash: str = field(init=False)

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if not all(isinstance(item, AuditTraceItem) for item in items):
            raise TypeError("items must use AuditTraceItem")
        if self.next_cursor is not None and not isinstance(self.next_cursor, AuditTraceCursor):
            raise TypeError("next_cursor must use AuditTraceCursor")
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "page_hash", _hash(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "items": [item.to_json() for item in self.items],
            "next_cursor": None if self.next_cursor is None else self.next_cursor.to_json(),
        }


__all__ = (
    "AuditAccessAuthorityPort",
    "AuditAccessAuthorityRefV1",
    "AuditAggregateMetricsV1",
    "AuditTraceCursor",
    "AuditTraceItem",
    "AuditTraceLineageRef",
    "AuditTracePage",
    "AuditTraceQuery",
    "AuditTraceSelector",
    "CanonicalStateManifestV1",
    "CanonicalStateManifestAccessV1",
    "CanonicalStateTableRootV1",
    "DecisionLedgerEntry",
    "DecisionOutcome",
    "LLMInvocationAuditRecord",
    "OutputStorageStatus",
    "PublicReasoningReference",
    "ReasoningItemType",
    "freeze_public_audit_object",
)
