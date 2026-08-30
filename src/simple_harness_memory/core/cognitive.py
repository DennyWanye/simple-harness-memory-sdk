"""Canonical cognitive state and evidence-bound transition rules.

The Host owns the public, model-facing wire protocol.  This module consumes
the exact ``simple-harness-sdk`` 0.7 payloads and evidence references; it does
not recreate a permissive Memory-local wire format.  The values below are the
canonical state held after a proposal has crossed the Host evidence authority
boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final

from simple_harness.runtime.evidence_protocol import (
    EvidenceAuthorityVerifierPort,
    EvidenceSpanRef,
    EvidenceSupportKind,
    verify_evidence_span,
)
from simple_harness.runtime.memory_protocol import (
    EpisodeLifecycleState,
    EpisodeMemoryPayload,
    EpistemicStatus,
    ProcedureLifecycleState,
    ProcedureMemoryPayload,
    ProcedureRiskLevel,
    SemanticLifecycleState,
    SemanticMemoryPayload,
    ValidTimeInterval,
    VerificationState,
)

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _positive_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError("revision_invalid")
    return value


def _digest(value: str, name: str) -> str:
    if len(value) != 64:
        raise MemoryValidationError(f"{name}_invalid")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise MemoryValidationError(f"{name}_invalid") from exc
    return value


def _evidence_hashes(value: tuple[str, ...]) -> tuple[str, ...]:
    if not value or len(value) != len(set(value)):
        raise MemoryValidationError("evidence_span_hashes_invalid")
    return tuple(_digest(item, "evidence_span_hash") for item in value)


_VERIFIED_EVIDENCE_GUARD: Final[object] = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedEvidenceSet:
    """Evidence spans proven through the Host authority port.

    Construction is intentionally private.  A caller must use
    :class:`EvidenceAuthorityAdapter`; merely constructing an ``EvidenceSpanRef``
    cannot grant evidence authority.
    """

    spans: tuple[EvidenceSpanRef, ...]

    def __init__(self, spans: tuple[EvidenceSpanRef, ...], guard: object) -> None:
        if guard is not _VERIFIED_EVIDENCE_GUARD:
            raise MemoryValidationError("evidence_authority_required")
        object.__setattr__(self, "spans", spans)

    @property
    def span_hashes(self) -> tuple[str, ...]:
        return tuple(span.span_hash for span in self.spans)


class EvidenceAuthorityAdapter:
    """Memory-side adapter to the exact Harness admitted-evidence authority."""

    def __init__(self, authority: EvidenceAuthorityVerifierPort) -> None:
        self._authority = authority

    async def verify(self, spans: tuple[EvidenceSpanRef, ...]) -> VerifiedEvidenceSet:
        if not spans:
            raise MemoryValidationError("evidence_required")
        if not all(isinstance(span, EvidenceSpanRef) for span in spans):
            raise MemoryValidationError("harness_evidence_span_required")
        span_ids = tuple(span.span_id for span in spans)
        span_hashes = tuple(span.span_hash for span in spans)
        if len(span_ids) != len(set(span_ids)) or len(span_hashes) != len(set(span_hashes)):
            raise MemoryValidationError("duplicate_evidence_span")
        try:
            for span in spans:
                await verify_evidence_span(span, self._authority)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("evidence_authority_rejected") from exc
        return VerifiedEvidenceSet(spans, _VERIFIED_EVIDENCE_GUARD)


class ConflictStatus(StrEnum):
    UNCONTESTED = "uncontested"
    CONTESTED = "contested"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class EpisodeState:
    memory_id: str
    subject: str
    scope: MemoryScope
    revision: int
    payload: EpisodeMemoryPayload
    lifecycle_state: EpisodeLifecycleState
    evidence_span_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.memory_id, "memory_id")
        _identifier(self.subject, "subject")
        _positive_revision(self.revision)
        if not isinstance(self.scope, MemoryScope):
            raise MemoryValidationError("scope_invalid")
        if not isinstance(self.payload, EpisodeMemoryPayload):
            raise MemoryValidationError("episode_payload_required")
        object.__setattr__(self, "lifecycle_state", EpisodeLifecycleState(self.lifecycle_state))
        object.__setattr__(
            self, "evidence_span_hashes", _evidence_hashes(self.evidence_span_hashes)
        )


_EPISODE_TRANSITIONS: Final[dict[EpisodeLifecycleState, frozenset[EpisodeLifecycleState]]] = {
    EpisodeLifecycleState.CANDIDATE: frozenset(
        {
            EpisodeLifecycleState.ACTIVE,
            EpisodeLifecycleState.REJECTED,
            EpisodeLifecycleState.FORGOTTEN,
        }
    ),
    EpisodeLifecycleState.ACTIVE: frozenset(
        {
            EpisodeLifecycleState.AMENDED,
            EpisodeLifecycleState.DISPUTED,
            EpisodeLifecycleState.SUPERSEDED,
            EpisodeLifecycleState.FORGOTTEN,
        }
    ),
    EpisodeLifecycleState.AMENDED: frozenset(
        {
            EpisodeLifecycleState.AMENDED,
            EpisodeLifecycleState.DISPUTED,
            EpisodeLifecycleState.SUPERSEDED,
            EpisodeLifecycleState.FORGOTTEN,
        }
    ),
    EpisodeLifecycleState.DISPUTED: frozenset(
        {
            EpisodeLifecycleState.AMENDED,
            EpisodeLifecycleState.SUPERSEDED,
            EpisodeLifecycleState.FORGOTTEN,
        }
    ),
    EpisodeLifecycleState.REJECTED: frozenset(),
    EpisodeLifecycleState.SUPERSEDED: frozenset(),
    EpisodeLifecycleState.FORGOTTEN: frozenset(),
}


def transition_episode(
    current: EpisodeState,
    *,
    lifecycle_state: EpisodeLifecycleState,
    evidence: VerifiedEvidenceSet,
    payload: EpisodeMemoryPayload | None = None,
) -> EpisodeState:
    """Apply one evidence-bound Episode transition."""

    target = EpisodeLifecycleState(lifecycle_state)
    if target not in _EPISODE_TRANSITIONS[current.lifecycle_state]:
        raise MemoryValidationError("episode_transition_invalid")
    if target is EpisodeLifecycleState.AMENDED and payload is None:
        raise MemoryValidationError("episode_amendment_payload_required")
    hashes = tuple(dict.fromkeys((*current.evidence_span_hashes, *evidence.span_hashes)))
    return replace(
        current,
        revision=current.revision + 1,
        payload=current.payload if payload is None else payload,
        lifecycle_state=target,
        evidence_span_hashes=hashes,
    )


@dataclass(frozen=True, slots=True)
class SemanticClaim:
    memory_id: str
    subject: str
    scope: MemoryScope
    revision: int
    payload: SemanticMemoryPayload
    lifecycle_state: SemanticLifecycleState
    epistemic_status: EpistemicStatus
    conflict_status: ConflictStatus
    verification_state: VerificationState
    valid_time: ValidTimeInterval
    evidence_span_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.memory_id, "memory_id")
        _identifier(self.subject, "subject")
        _positive_revision(self.revision)
        if not isinstance(self.scope, MemoryScope):
            raise MemoryValidationError("scope_invalid")
        if not isinstance(self.payload, SemanticMemoryPayload):
            raise MemoryValidationError("semantic_payload_required")
        object.__setattr__(self, "lifecycle_state", SemanticLifecycleState(self.lifecycle_state))
        object.__setattr__(self, "epistemic_status", EpistemicStatus(self.epistemic_status))
        object.__setattr__(self, "conflict_status", ConflictStatus(self.conflict_status))
        object.__setattr__(self, "verification_state", VerificationState(self.verification_state))
        if not isinstance(self.valid_time, ValidTimeInterval):
            raise MemoryValidationError("valid_time_invalid")
        object.__setattr__(
            self, "evidence_span_hashes", _evidence_hashes(self.evidence_span_hashes)
        )
        if (
            self.lifecycle_state is SemanticLifecycleState.SUPERSEDED
            and self.valid_time.valid_until is None
        ):
            raise MemoryValidationError("superseded_semantic_requires_valid_until")


_SEMANTIC_TRANSITIONS: Final[
    dict[SemanticLifecycleState, frozenset[SemanticLifecycleState]]
] = {
    SemanticLifecycleState.CANDIDATE: frozenset(
        {
            SemanticLifecycleState.ACTIVE,
            SemanticLifecycleState.REJECTED,
            SemanticLifecycleState.FORGOTTEN,
        }
    ),
    SemanticLifecycleState.ACTIVE: frozenset(
        {
            SemanticLifecycleState.ACTIVE,
            SemanticLifecycleState.SUPERSEDED,
            SemanticLifecycleState.FORGOTTEN,
        }
    ),
    SemanticLifecycleState.REJECTED: frozenset(),
    SemanticLifecycleState.SUPERSEDED: frozenset(),
    SemanticLifecycleState.FORGOTTEN: frozenset(),
}


def transition_semantic(
    current: SemanticClaim,
    *,
    lifecycle_state: SemanticLifecycleState,
    epistemic_status: EpistemicStatus,
    conflict_status: ConflictStatus,
    verification_state: VerificationState,
    valid_time: ValidTimeInterval,
    evidence: VerifiedEvidenceSet,
    payload: SemanticMemoryPayload | None = None,
) -> SemanticClaim:
    """Evolve a Semantic Claim without collapsing its independent dimensions."""

    target = SemanticLifecycleState(lifecycle_state)
    epistemic = EpistemicStatus(epistemic_status)
    if target not in _SEMANTIC_TRANSITIONS[current.lifecycle_state]:
        raise MemoryValidationError("semantic_transition_invalid")
    if (
        target is SemanticLifecycleState.SUPERSEDED
        and current.epistemic_status is EpistemicStatus.EXPLICIT_USER
        and epistemic is EpistemicStatus.LLM_INFERENCE
    ):
        raise MemoryValidationError("inference_cannot_supersede_explicit")
    if target is SemanticLifecycleState.SUPERSEDED and not any(
        span.support_kind is EvidenceSupportKind.EXPLICIT_USER_CORRECTION
        for span in evidence.spans
    ):
        raise MemoryValidationError("supersede_requires_explicit_correction")
    if target is SemanticLifecycleState.SUPERSEDED and valid_time.valid_until is None:
        raise MemoryValidationError("superseded_semantic_requires_valid_until")
    hashes = tuple(dict.fromkeys((*current.evidence_span_hashes, *evidence.span_hashes)))
    return replace(
        current,
        revision=current.revision + 1,
        payload=current.payload if payload is None else payload,
        lifecycle_state=target,
        epistemic_status=epistemic,
        conflict_status=ConflictStatus(conflict_status),
        verification_state=VerificationState(verification_state),
        valid_time=valid_time,
        evidence_span_hashes=hashes,
    )


class ProcedureEvidenceOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class ProcedureHazard(StrEnum):
    NONE = "none"
    PUBLISH = "publish"
    DELETE = "delete"
    PAYMENT = "payment"
    PERMISSION = "permission"


@dataclass(frozen=True, slots=True)
class ApplicabilityFingerprint:
    tool_id: str
    environment: str
    tool_version: str
    input_schema_hash: str
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        values = (
            _identifier(self.tool_id, "tool_id"),
            _identifier(self.environment, "environment"),
            _identifier(self.tool_version, "tool_version"),
            _digest(self.input_schema_hash, "input_schema_hash"),
        )
        material = "\x1f".join(values).encode("utf-8")
        object.__setattr__(self, "fingerprint", hashlib.sha256(material).hexdigest())


@dataclass(frozen=True, slots=True)
class ProcedureEvidence:
    task_scope_id: str
    terminal_receipt_id: str
    terminal_receipt_hash: str
    evidence_span_hash: str
    occurred_at: float
    procedure_revision: int
    applicability_fingerprint: str
    outcome: ProcedureEvidenceOutcome
    attributable: bool

    def __post_init__(self) -> None:
        _identifier(self.task_scope_id, "task_scope_id")
        _identifier(self.terminal_receipt_id, "terminal_receipt_id")
        _digest(self.terminal_receipt_hash, "terminal_receipt_hash")
        _digest(self.evidence_span_hash, "evidence_span_hash")
        if (
            isinstance(self.occurred_at, bool)
            or not isinstance(self.occurred_at, (int, float))
            or self.occurred_at < 0
        ):
            raise MemoryValidationError("procedure_evidence_time_invalid")
        object.__setattr__(self, "occurred_at", float(self.occurred_at))
        _positive_revision(self.procedure_revision)
        _digest(self.applicability_fingerprint, "applicability_fingerprint")
        object.__setattr__(self, "outcome", ProcedureEvidenceOutcome(self.outcome))
        if not isinstance(self.attributable, bool):
            raise MemoryValidationError("procedure_attribution_invalid")


@dataclass(frozen=True, slots=True)
class ProcedureState:
    memory_id: str
    subject: str
    scope: MemoryScope
    revision: int
    payload: ProcedureMemoryPayload
    lifecycle_state: ProcedureLifecycleState
    epistemic_status: EpistemicStatus
    applicability_fingerprint: str
    hazard: ProcedureHazard
    evidence_span_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.memory_id, "memory_id")
        _identifier(self.subject, "subject")
        _positive_revision(self.revision)
        if not isinstance(self.scope, MemoryScope):
            raise MemoryValidationError("scope_invalid")
        if not isinstance(self.payload, ProcedureMemoryPayload):
            raise MemoryValidationError("procedure_payload_required")
        object.__setattr__(
            self, "lifecycle_state", ProcedureLifecycleState(self.lifecycle_state)
        )
        object.__setattr__(self, "epistemic_status", EpistemicStatus(self.epistemic_status))
        object.__setattr__(
            self,
            "applicability_fingerprint",
            _digest(self.applicability_fingerprint, "applicability_fingerprint"),
        )
        object.__setattr__(self, "hazard", ProcedureHazard(self.hazard))
        object.__setattr__(
            self, "evidence_span_hashes", _evidence_hashes(self.evidence_span_hashes)
        )


@dataclass(frozen=True, slots=True)
class ProcedureQualification:
    state: ProcedureLifecycleState
    independent_successes: int
    reason_code: str


_ROLLING_90_DAYS_SECONDS: Final[float] = 90 * 86_400.0
_HIGH_RISK_HAZARDS: Final[frozenset[ProcedureHazard]] = frozenset(
    {
        ProcedureHazard.PUBLISH,
        ProcedureHazard.DELETE,
        ProcedureHazard.PAYMENT,
        ProcedureHazard.PERMISSION,
    }
)


_PROCEDURE_TRANSITIONS: Final[
    dict[ProcedureLifecycleState, frozenset[ProcedureLifecycleState]]
] = {
    ProcedureLifecycleState.DRAFT: frozenset(
        {
            ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
            ProcedureLifecycleState.ACTIVE,
            ProcedureLifecycleState.REVISED,
            ProcedureLifecycleState.INAPPLICABLE,
            ProcedureLifecycleState.SUPERSEDED,
            ProcedureLifecycleState.FORGOTTEN,
        }
    ),
    ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION: frozenset(
        {
            ProcedureLifecycleState.ACTIVE,
            ProcedureLifecycleState.REVISED,
            ProcedureLifecycleState.INAPPLICABLE,
            ProcedureLifecycleState.SUPERSEDED,
            ProcedureLifecycleState.FORGOTTEN,
        }
    ),
    ProcedureLifecycleState.ACTIVE: frozenset(
        {
            ProcedureLifecycleState.REINFORCED,
            ProcedureLifecycleState.REVISED,
            ProcedureLifecycleState.INAPPLICABLE,
            ProcedureLifecycleState.SUPERSEDED,
            ProcedureLifecycleState.FORGOTTEN,
        }
    ),
    ProcedureLifecycleState.REINFORCED: frozenset(
        {
            ProcedureLifecycleState.REINFORCED,
            ProcedureLifecycleState.REVISED,
            ProcedureLifecycleState.INAPPLICABLE,
            ProcedureLifecycleState.SUPERSEDED,
            ProcedureLifecycleState.FORGOTTEN,
        }
    ),
    ProcedureLifecycleState.REVISED: frozenset({ProcedureLifecycleState.DRAFT}),
    ProcedureLifecycleState.INAPPLICABLE: frozenset({ProcedureLifecycleState.DRAFT}),
    ProcedureLifecycleState.SUPERSEDED: frozenset(),
    ProcedureLifecycleState.FORGOTTEN: frozenset(),
}


def transition_procedure(
    current: ProcedureState,
    *,
    lifecycle_state: ProcedureLifecycleState,
    evidence: VerifiedEvidenceSet,
    payload: ProcedureMemoryPayload | None = None,
    applicability_fingerprint: str | None = None,
    epistemic_status: EpistemicStatus | None = None,
) -> ProcedureState:
    """Apply a legal, evidence-bound Procedure transition."""

    target = ProcedureLifecycleState(lifecycle_state)
    if target not in _PROCEDURE_TRANSITIONS[current.lifecycle_state]:
        raise MemoryValidationError("procedure_transition_invalid")
    if current.lifecycle_state in {
        ProcedureLifecycleState.REVISED,
        ProcedureLifecycleState.INAPPLICABLE,
    } and (payload is None or applicability_fingerprint is None):
        raise MemoryValidationError("procedure_new_revision_inputs_required")
    hashes = tuple(dict.fromkeys((*current.evidence_span_hashes, *evidence.span_hashes)))
    return replace(
        current,
        revision=current.revision + 1,
        payload=current.payload if payload is None else payload,
        lifecycle_state=target,
        epistemic_status=(
            current.epistemic_status
            if epistemic_status is None
            else EpistemicStatus(epistemic_status)
        ),
        applicability_fingerprint=(
            current.applicability_fingerprint
            if applicability_fingerprint is None
            else _digest(applicability_fingerprint, "applicability_fingerprint")
        ),
        evidence_span_hashes=hashes,
    )


def qualify_procedure(
    *,
    procedure_revision: int,
    applicability: ApplicabilityFingerprint,
    hazard: ProcedureHazard,
    proposed_risk_level: ProcedureRiskLevel,
    evidence: tuple[ProcedureEvidence, ...],
    now: float,
    current_applicability_fingerprint: str | None = None,
    explicit_user_evidence: VerifiedEvidenceSet | None = None,
) -> ProcedureQualification:
    """Deterministically qualify independent procedure evidence.

    This only changes memory eligibility.  It never grants tool, workspace, or
    external-effect permission.
    """

    _positive_revision(procedure_revision)
    if isinstance(now, bool) or now < 0:
        raise MemoryValidationError("procedure_evaluation_time_invalid")
    hazard = ProcedureHazard(hazard)
    risk = ProcedureRiskLevel(proposed_risk_level)
    if current_applicability_fingerprint is not None:
        _digest(current_applicability_fingerprint, "current_applicability_fingerprint")
        if current_applicability_fingerprint != applicability.fingerprint:
            return ProcedureQualification(
                ProcedureLifecycleState.INAPPLICABLE,
                0,
                "procedure_applicability_drift",
            )
    applicable = tuple(
        item
        for item in evidence
        if item.procedure_revision == procedure_revision
        and item.applicability_fingerprint == applicability.fingerprint
    )
    if any(
        item.attributable and item.outcome is ProcedureEvidenceOutcome.FAILURE
        for item in applicable
    ):
        return ProcedureQualification(
            ProcedureLifecycleState.REVISED,
            0,
            "procedure_attributable_failure",
        )
    if explicit_user_evidence is not None and any(
        span.support_kind
        in {
            EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
            EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
        }
        for span in explicit_user_evidence.spans
    ):
        return ProcedureQualification(
            ProcedureLifecycleState.ACTIVE,
            0,
            "procedure_explicit_user_confirmed",
        )

    cutoff = now - _ROLLING_90_DAYS_SECONDS
    successes = sorted(
        (
            item
            for item in applicable
            if item.attributable
            and item.outcome is ProcedureEvidenceOutcome.SUCCESS
            and cutoff <= item.occurred_at <= now
        ),
        key=lambda item: (item.occurred_at, item.task_scope_id, item.terminal_receipt_id),
    )
    independent: list[ProcedureEvidence] = []
    used_scopes: set[str] = set()
    used_receipts: set[str] = set()
    for item in successes:
        if item.task_scope_id in used_scopes or item.terminal_receipt_id in used_receipts:
            continue
        used_scopes.add(item.task_scope_id)
        used_receipts.add(item.terminal_receipt_id)
        independent.append(item)
    count = len(independent)
    if hazard in _HIGH_RISK_HAZARDS:
        return ProcedureQualification(
            ProcedureLifecycleState.DRAFT,
            count,
            "procedure_high_risk_requires_user_confirmation",
        )
    if risk is not ProcedureRiskLevel.LOW:
        return ProcedureQualification(
            ProcedureLifecycleState.DRAFT,
            count,
            "procedure_non_low_risk_requires_user_confirmation",
        )
    if count >= 3:
        return ProcedureQualification(
            ProcedureLifecycleState.ACTIVE,
            count,
            "procedure_three_independent_successes",
        )
    if count == 2:
        return ProcedureQualification(
            ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
            count,
            "procedure_two_independent_successes",
        )
    return ProcedureQualification(
        ProcedureLifecycleState.DRAFT,
        count,
        "procedure_insufficient_independent_evidence",
    )


__all__ = (
    "ApplicabilityFingerprint",
    "ConflictStatus",
    "EpisodeState",
    "EvidenceAuthorityAdapter",
    "ProcedureEvidence",
    "ProcedureEvidenceOutcome",
    "ProcedureHazard",
    "ProcedureQualification",
    "ProcedureState",
    "SemanticClaim",
    "VerifiedEvidenceSet",
    "qualify_procedure",
    "transition_episode",
    "transition_procedure",
    "transition_semantic",
)
