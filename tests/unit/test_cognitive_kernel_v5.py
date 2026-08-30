from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest
from simple_harness.contracts import FrozenJsonValue, JsonValue, fingerprint_json
from simple_harness.runtime.disclosure_protocol import (
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    IntendedAudience,
)
from simple_harness.runtime.evidence_protocol import (
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    AdmittedEvidenceAuthority,
    EvidenceActorRole,
    EvidenceItemAuthority,
    EvidenceProvenance,
    EvidenceReasonCode,
    EvidenceSourceKind,
    EvidenceSpanRef,
    EvidenceSupportKind,
    ProposedTypedObservationRef,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    TypedObservationAuthorityReceipt,
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

from simple_harness_memory.core.cognitive import (
    ApplicabilityFingerprint,
    ConflictStatus,
    EpisodeState,
    EvidenceAuthorityAdapter,
    ProcedureEvidence,
    ProcedureEvidenceOutcome,
    ProcedureHazard,
    ProcedureState,
    SemanticClaim,
    qualify_procedure,
    transition_episode,
    transition_procedure,
    transition_semantic,
)
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        run_id="run-1",
        subject="user-1",
        recipient=DeliveryRecipient.USER_SELF,
        recipient_id="user-1",
        intended_audience=IntendedAudience.USER_SELF,
        purpose=DisclosurePurpose.PERSONALIZATION,
        source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY,
        generation=DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _admitted(text: str) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {"item_id": "message-1", "public_text": text}
    envelope = SanitizedEvidenceEnvelope(
        evidence_id="evidence-1",
        run_id="run-1",
        subject="user-1",
        source_kind=EvidenceSourceKind.USER_MESSAGE,
        source_ref="turn-1/user",
        source_hash="a" * 64,
        sanitized_payload=cast(Mapping[str, FrozenJsonValue], payload),
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(),
        evidence_refs=(),
    )
    receipt = SanitizedEvidenceReceipt(
        receipt_id="admission-1",
        run_id="run-1",
        subject="user-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=_disclosure(),
        evidence_refs=(),
        admitted_at=10.0,
    )
    return envelope, receipt


def _span(
    envelope: SanitizedEvidenceEnvelope,
    receipt: SanitizedEvidenceReceipt,
    *,
    support: EvidenceSupportKind = EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
    span_id: str = "span-1",
) -> EvidenceSpanRef:
    text = cast(str, envelope.sanitized_payload["public_text"])
    encoded = text.encode("utf-8")
    return EvidenceSpanRef(
        span_id=span_id,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        source_kind=EvidenceSourceKind.USER_MESSAGE,
        item_ordinal=1,
        item_id="message-1",
        item_json_pointer="/public_text",
        start_byte=0,
        end_byte=len(encoded),
        exact_quote=text,
        quote_hash=_sha(text),
        source_hash=envelope.source_hash,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=EvidenceActorRole.USER,
        provenance=EvidenceProvenance.AUTHENTICATED_USER,
        support_kind=support,
        typed_observation=None,
    )


def _item_authority(span: EvidenceSpanRef) -> EvidenceItemAuthority:
    return EvidenceItemAuthority(
        authority_id="item-authority-1",
        evidence_id=span.evidence_id,
        envelope_hash=span.envelope_hash,
        sanitized_hash=span.sanitized_hash,
        source_hash=span.source_hash,
        source_kind=span.source_kind,
        item_ordinal=span.item_ordinal,
        item_id=span.item_id,
        item_json_pointer=span.item_json_pointer,
        normalization_version=span.normalization_version,
        actor_role=span.actor_role,
        provenance=span.provenance,
        issuer_ref="host-evidence-store-1",
    )


class _Verifier:
    def __init__(
        self,
        admitted: AdmittedEvidenceAuthority,
        observation: TypedObservationAuthorityReceipt | None = None,
    ) -> None:
        self.admitted = admitted
        self.observation = observation
        self.calls = 0

    async def resolve_admitted_evidence(self, span: EvidenceSpanRef) -> AdmittedEvidenceAuthority:
        self.calls += 1
        return self.admitted

    async def resolve_typed_observation(
        self, reference: ProposedTypedObservationRef
    ) -> TypedObservationAuthorityReceipt:
        if self.observation is None:
            raise ValueError("not registered")
        return self.observation


async def _verified(
    *, support: EvidenceSupportKind = EvidenceSupportKind.EXPLICIT_USER_ASSERTION
):
    envelope, receipt = _admitted("我现在住在上海")
    span = _span(envelope, receipt, support=support)
    verifier = _Verifier(AdmittedEvidenceAuthority(envelope, receipt, _item_authority(span)))
    verified = await EvidenceAuthorityAdapter(verifier).verify((span,))
    assert verifier.calls == 1
    return verified


@pytest.mark.asyncio
async def test_evidence_boundary_requires_exact_harness_span_and_authority_resolution() -> None:
    verified = await _verified()
    assert len(verified.span_hashes) == 1

    envelope, receipt = _admitted("我现在住在上海")
    span = _span(envelope, receipt)
    forged = replace(span, admission_receipt_hash="f" * 64)
    verifier = _Verifier(AdmittedEvidenceAuthority(envelope, receipt, _item_authority(forged)))
    with pytest.raises(MemoryValidationError, match="evidence_authority_rejected"):
        await EvidenceAuthorityAdapter(verifier).verify((forged,))
    with pytest.raises(MemoryValidationError, match="harness_evidence_span_required"):
        await EvidenceAuthorityAdapter(verifier).verify((cast(EvidenceSpanRef, object()),))


@pytest.mark.asyncio
async def test_episode_uses_exact_payload_and_table_driven_transitions() -> None:
    evidence = await _verified()
    payload = EpisodeMemoryPayload(
        title="完成发布",
        participants=("user-1",),
        goals=("发布",),
        actions=("运行检查",),
        results=("成功",),
        impacts=(),
        occurred_start=10.0,
        occurred_end=20.0,
        thread_ref="thread-1",
    )
    candidate = EpisodeState(
        "episode-1",
        "user-1",
        MemoryScope.personal("user-1"),
        1,
        payload,
        EpisodeLifecycleState.CANDIDATE,
        evidence.span_hashes,
    )
    active = transition_episode(
        candidate,
        lifecycle_state=EpisodeLifecycleState.ACTIVE,
        evidence=evidence,
    )
    assert active.revision == 2
    assert active.lifecycle_state is EpisodeLifecycleState.ACTIVE
    with pytest.raises(MemoryValidationError, match="episode_transition_invalid"):
        transition_episode(
            active,
            lifecycle_state=EpisodeLifecycleState.REJECTED,
            evidence=evidence,
        )


@pytest.mark.asyncio
async def test_semantic_dimensions_are_independent_and_inference_cannot_supersede() -> None:
    evidence = await _verified()
    current = SemanticClaim(
        memory_id="sem-1",
        subject="user-1",
        scope=MemoryScope.personal("user-1"),
        revision=1,
        payload=SemanticMemoryPayload("user-1", "lives_in", "北京", ()),
        lifecycle_state=SemanticLifecycleState.ACTIVE,
        epistemic_status=EpistemicStatus.EXPLICIT_USER,
        conflict_status=ConflictStatus.UNCONTESTED,
        verification_state=VerificationState.USER_CONFIRMED,
        valid_time=ValidTimeInterval(1.0, None),
        evidence_span_hashes=evidence.span_hashes,
    )
    contested = transition_semantic(
        current,
        lifecycle_state=SemanticLifecycleState.ACTIVE,
        epistemic_status=EpistemicStatus.LLM_INFERENCE,
        conflict_status=ConflictStatus.CONTESTED,
        verification_state=VerificationState.UNVERIFIED,
        valid_time=ValidTimeInterval(1.0, None),
        evidence=evidence,
    )
    assert contested.lifecycle_state is SemanticLifecycleState.ACTIVE
    assert contested.conflict_status is ConflictStatus.CONTESTED

    with pytest.raises(MemoryValidationError, match="inference_cannot_supersede_explicit"):
        transition_semantic(
            current,
            lifecycle_state=SemanticLifecycleState.SUPERSEDED,
            epistemic_status=EpistemicStatus.LLM_INFERENCE,
            conflict_status=ConflictStatus.RESOLVED,
            verification_state=VerificationState.UNVERIFIED,
            valid_time=ValidTimeInterval(1.0, 2.0),
            evidence=evidence,
        )

    correction = await _verified(support=EvidenceSupportKind.EXPLICIT_USER_CORRECTION)
    superseded = transition_semantic(
        current,
        lifecycle_state=SemanticLifecycleState.SUPERSEDED,
        epistemic_status=EpistemicStatus.EXPLICIT_USER,
        conflict_status=ConflictStatus.RESOLVED,
        verification_state=VerificationState.USER_CONFIRMED,
        valid_time=ValidTimeInterval(1.0, 2.0),
        evidence=correction,
    )
    assert superseded.valid_time.valid_until == 2.0


def _procedure_evidence(
    applicability: ApplicabilityFingerprint,
    *,
    scope: str,
    receipt: str,
    outcome: ProcedureEvidenceOutcome = ProcedureEvidenceOutcome.SUCCESS,
) -> ProcedureEvidence:
    return ProcedureEvidence(
        task_scope_id=scope,
        terminal_receipt_id=receipt,
        terminal_receipt_hash=_sha(receipt),
        evidence_span_hash=_sha(f"span:{scope}:{receipt}"),
        occurred_at=100.0,
        procedure_revision=1,
        applicability_fingerprint=applicability.fingerprint,
        outcome=outcome,
        attributable=True,
    )


def test_procedure_requires_independent_runs_and_high_risk_never_auto_activates() -> None:
    applicability = ApplicabilityFingerprint("tool-x", "macos", "1.2", _sha("schema-v1"))
    repeated = (
        _procedure_evidence(applicability, scope="task-1", receipt="receipt-1"),
        _procedure_evidence(applicability, scope="task-1", receipt="retry"),
    )
    assert qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.NONE,
        proposed_risk_level=ProcedureRiskLevel.LOW,
        evidence=repeated,
        now=100.0,
    ).state is ProcedureLifecycleState.DRAFT

    independent = repeated + (
        _procedure_evidence(applicability, scope="task-2", receipt="receipt-2"),
        _procedure_evidence(applicability, scope="task-3", receipt="receipt-3"),
    )
    result = qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.NONE,
        proposed_risk_level=ProcedureRiskLevel.LOW,
        evidence=independent,
        now=100.0,
    )
    assert result.state is ProcedureLifecycleState.ACTIVE
    assert result.independent_successes == 3

    high_risk = qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.PAYMENT,
        proposed_risk_level=ProcedureRiskLevel.LOW,
        evidence=independent,
        now=100.0,
    )
    assert high_risk.state is ProcedureLifecycleState.DRAFT
    assert high_risk.reason_code == "procedure_high_risk_requires_user_confirmation"


def test_procedure_failure_drift_and_exact_payload_state() -> None:
    applicability = ApplicabilityFingerprint("tool-x", "prod", "1", _sha("schema-v1"))
    failed = _procedure_evidence(
        applicability,
        scope="task-1",
        receipt="receipt-1",
        outcome=ProcedureEvidenceOutcome.FAILURE,
    )
    result = qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.NONE,
        proposed_risk_level=ProcedureRiskLevel.LOW,
        evidence=(failed,),
        now=100.0,
    )
    assert result.state is ProcedureLifecycleState.REVISED
    assert qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.NONE,
        proposed_risk_level=ProcedureRiskLevel.LOW,
        evidence=(),
        now=100.0,
        current_applicability_fingerprint="f" * 64,
    ).state is ProcedureLifecycleState.INAPPLICABLE

    state = ProcedureState(
        memory_id="procedure-1",
        subject="user-1",
        scope=MemoryScope.personal("user-1"),
        revision=1,
        payload=ProcedureMemoryPayload(
            "发布流程",
            ("tool=release", "environment=prod"),
            ("运行测试", "发布"),
            ProcedureRiskLevel.HIGH,
        ),
        lifecycle_state=ProcedureLifecycleState.DRAFT,
        epistemic_status=EpistemicStatus.OBSERVED_BEHAVIOR,
        applicability_fingerprint=applicability.fingerprint,
        hazard=ProcedureHazard.PUBLISH,
        evidence_span_hashes=(failed.evidence_span_hash,),
    )
    assert state.payload.proposed_risk_level is ProcedureRiskLevel.HIGH


@pytest.mark.asyncio
async def test_procedure_transition_table_prevents_illegal_state_jump() -> None:
    evidence = await _verified()
    applicability = ApplicabilityFingerprint("tool-x", "prod", "1", _sha("schema-v1"))
    state = ProcedureState(
        memory_id="procedure-1",
        subject="user-1",
        scope=MemoryScope.personal("user-1"),
        revision=1,
        payload=ProcedureMemoryPayload(
            "检查流程",
            ("tool=check",),
            ("运行检查",),
            ProcedureRiskLevel.LOW,
        ),
        lifecycle_state=ProcedureLifecycleState.DRAFT,
        epistemic_status=EpistemicStatus.OBSERVED_BEHAVIOR,
        applicability_fingerprint=applicability.fingerprint,
        hazard=ProcedureHazard.NONE,
        evidence_span_hashes=evidence.span_hashes,
    )
    active = transition_procedure(
        state,
        lifecycle_state=ProcedureLifecycleState.ACTIVE,
        evidence=evidence,
    )
    assert active.lifecycle_state is ProcedureLifecycleState.ACTIVE
    with pytest.raises(MemoryValidationError, match="procedure_transition_invalid"):
        transition_procedure(
            active,
            lifecycle_state=ProcedureLifecycleState.DRAFT,
            evidence=evidence,
        )


@pytest.mark.asyncio
async def test_high_risk_procedure_only_activates_with_authority_verified_user_evidence() -> None:
    evidence = await _verified()
    applicability = ApplicabilityFingerprint("tool-x", "prod", "1", _sha("schema-v1"))
    result = qualify_procedure(
        procedure_revision=1,
        applicability=applicability,
        hazard=ProcedureHazard.PUBLISH,
        proposed_risk_level=ProcedureRiskLevel.HIGH,
        evidence=(),
        now=100.0,
        explicit_user_evidence=evidence,
    )
    assert result.state is ProcedureLifecycleState.ACTIVE
    assert result.reason_code == "procedure_explicit_user_confirmed"
