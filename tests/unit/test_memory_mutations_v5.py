from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import cast

import pytest
from simple_harness.runtime import (
    ConflictStatus,
    CreatedByOperationTarget,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EpisodeLifecycleState,
    EpisodeMemoryPayload,
    EpistemicStatus,
    EvidenceActorRole,
    EvidenceProvenance,
    EvidenceRef,
    EvidenceSourceKind,
    EvidenceSpanRef,
    EvidenceSupportKind,
    ExistingMemoryTarget,
    InformationAttribute,
    IntendedAudience,
    LongTermMemoryType,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    MemoryMutationPlanOutcome,
    PrivacyClass,
    ProcedureLifecycleState,
    ProcedureMemoryPayload,
    ProcedureRiskLevel,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveTimeTrigger,
    SemanticLifecycleState,
    SemanticMemoryPayload,
    ValidTimeInterval,
    VerificationState,
)
from simple_harness.runtime.evidence_protocol import (
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
)

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.mutations import (
    compile_memory_mutation_plan,
    join_information_classification,
    validate_lifecycle_transition,
)


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


def _evidence_ref() -> EvidenceRef:
    return EvidenceRef("evidence-1", "b" * 64, 1)


def _span(
    *,
    support_kind: EvidenceSupportKind = EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
    actor_role: EvidenceActorRole = EvidenceActorRole.USER,
    provenance: EvidenceProvenance = EvidenceProvenance.AUTHENTICATED_USER,
) -> EvidenceSpanRef:
    quote = "Python 3.12"
    return EvidenceSpanRef(
        span_id=f"span-{support_kind.value}",
        evidence_id="evidence-1",
        envelope_hash="b" * 64,
        sanitized_hash="c" * 64,
        admission_receipt_id="admission-1",
        admission_receipt_hash="d" * 64,
        source_kind=(
            EvidenceSourceKind.USER_MESSAGE
            if actor_role is EvidenceActorRole.USER
            else EvidenceSourceKind.ASSISTANT_MESSAGE
        ),
        item_ordinal=1,
        item_id="message-1",
        item_json_pointer="/public_text",
        start_byte=7,
        end_byte=18,
        exact_quote=quote,
        quote_hash=_sha(quote),
        source_hash="e" * 64,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=actor_role,
        provenance=provenance,
        support_kind=support_kind,
        typed_observation=None,
    )


def _semantic_operation(
    operation_id: str = "semantic-create",
    *,
    kind: MemoryMutationKind = MemoryMutationKind.CREATE,
    target: ExistingMemoryTarget | CreatedByOperationTarget | None = None,
    depends_on: tuple[str, ...] = (),
    lifecycle_state: SemanticLifecycleState = SemanticLifecycleState.ACTIVE,
    epistemic_status: EpistemicStatus = EpistemicStatus.EXPLICIT_USER,
    verification_state: VerificationState = VerificationState.SOURCE_BOUND,
    evidence_spans: tuple[EvidenceSpanRef, ...] | None = None,
) -> MemoryMutationOperation:
    return MemoryMutationOperation(
        operation_id=operation_id,
        kind=kind,
        memory_type=LongTermMemoryType.SEMANTIC,
        payload=SemanticMemoryPayload(
            subject_entity="user:self",
            predicate="runtime_preference",
            object_value={"runtime": "python", "version": [3, 12]},
            qualifiers=("primary",),
        ),
        target=target,
        depends_on_operation_ids=depends_on,
        lifecycle_state=lifecycle_state,
        epistemic_status=epistemic_status,
        conflict_status=ConflictStatus.UNCONTESTED,
        verification_state=verification_state,
        valid_time_interval=ValidTimeInterval(10.0, None),
        proposed_privacy_class=PrivacyClass.PERSONAL,
        proposed_information_attributes=(InformationAttribute.PREFERENCE,),
        evidence_spans=(_span(),) if evidence_spans is None else evidence_spans,
        reason_code="explicit_user_assertion",
    )


def _plan(*operations: MemoryMutationOperation) -> MemoryMutationPlan:
    return MemoryMutationPlan(
        plan_id="mutation-plan-1",
        run_id="run-1",
        subject="user-1",
        base_revision=4,
        outcome=MemoryMutationPlanOutcome.MUTATE,
        operations=tuple(operations),
        disclosure_context=_disclosure(),
        evidence_refs=(_evidence_ref(),),
        idempotency_key="mutation-idempotency-1",
    )


@pytest.mark.parametrize(
    ("memory_type", "payload", "lifecycle"),
    (
        (
            LongTermMemoryType.EPISODE,
            EpisodeMemoryPayload(
                "runtime decision",
                ("user:self",),
                ("upgrade",),
                ("choose 3.12",),
                ("selected",),
                ("future tasks use 3.12",),
                10.0,
                11.0,
                "thread-1",
            ),
            EpisodeLifecycleState.ACTIVE,
        ),
        (
            LongTermMemoryType.SEMANTIC,
            SemanticMemoryPayload(
                "user:self", "runtime_preference", "Python 3.12", ("primary",)
            ),
            SemanticLifecycleState.ACTIVE,
        ),
        (
            LongTermMemoryType.PROCEDURE,
            ProcedureMemoryPayload(
                "release checklist",
                ("software release",),
                ("test", "publish"),
                ProcedureRiskLevel.HIGH,
            ),
            ProcedureLifecycleState.ACTIVE,
        ),
        (
            LongTermMemoryType.PROSPECTIVE,
            ProspectiveMemoryPayload(
                "write changelog", ProspectiveTimeTrigger(100.0, "Asia/Shanghai")
            ),
            ProspectiveLifecycleState.PENDING,
        ),
    ),
)
def test_exact_harness_four_payloads_and_lifecycles_compile(
    memory_type: LongTermMemoryType,
    payload: (
        EpisodeMemoryPayload
        | SemanticMemoryPayload
        | ProcedureMemoryPayload
        | ProspectiveMemoryPayload
    ),
    lifecycle: (
        EpisodeLifecycleState
        | SemanticLifecycleState
        | ProcedureLifecycleState
        | ProspectiveLifecycleState
    ),
) -> None:
    operation = replace(
        _semantic_operation(),
        memory_type=memory_type,
        payload=payload,
        lifecycle_state=lifecycle,
    )
    compiled = compile_memory_mutation_plan(_plan(operation))
    assert compiled.operations[0].operation is operation


def test_forward_dependency_is_stably_topologically_compiled() -> None:
    create = _semantic_operation("create")
    revise = _semantic_operation(
        "revise",
        kind=MemoryMutationKind.REVISE,
        target=CreatedByOperationTarget("create"),
        depends_on=("create",),
    )
    compiled = compile_memory_mutation_plan(_plan(revise, create))
    assert tuple(item.operation_id for item in compiled.operations) == (
        "create",
        "revise",
    )


def test_exact_harness_wire_rejects_unknown_self_cycle_and_created_type_mismatch() -> None:
    with pytest.raises(ValueError, match="unknown"):
        _plan(_semantic_operation("unknown", depends_on=("missing",)))

    with pytest.raises(ValueError, match="depend on self"):
        _semantic_operation("self", depends_on=("self",))

    first = _semantic_operation(
        "first",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget("memory-1", 1),
        depends_on=("second",),
    )
    second = _semantic_operation(
        "second",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget("memory-2", 1),
        depends_on=("first",),
    )
    with pytest.raises(ValueError, match="cycle"):
        _plan(first, second)

    episode_create = replace(
        _semantic_operation("episode-create"),
        memory_type=LongTermMemoryType.EPISODE,
        payload=EpisodeMemoryPayload(
            "decision",
            ("user:self",),
            ("ship",),
            ("test",),
            ("green",),
            ("released",),
            10.0,
            11.0,
            "thread-1",
        ),
        lifecycle_state=EpisodeLifecycleState.ACTIVE,
    )
    semantic_consumer = _semantic_operation(
        "semantic-consumer",
        kind=MemoryMutationKind.REVISE,
        target=CreatedByOperationTarget("episode-create"),
        depends_on=("episode-create",),
    )
    with pytest.raises(ValueError, match="same memory_type"):
        _plan(semantic_consumer, episode_create)

    with pytest.raises(ValueError, match="lifecycle_state"):
        replace(
            _semantic_operation(),
            lifecycle_state=cast(SemanticLifecycleState, EpisodeLifecycleState.ACTIVE),
        )


def test_compiler_is_strict_atomic_when_one_operation_is_invalid() -> None:
    valid = _semantic_operation("valid")
    inference_span = _span(
        support_kind=EvidenceSupportKind.MODEL_INFERENCE,
        actor_role=EvidenceActorRole.ASSISTANT,
        provenance=EvidenceProvenance.MODEL_OUTPUT,
    )
    invalid = _semantic_operation(
        "invalid",
        lifecycle_state=SemanticLifecycleState.ACTIVE,
        epistemic_status=EpistemicStatus.LLM_INFERENCE,
        verification_state=VerificationState.UNVERIFIED,
        evidence_spans=(inference_span,),
    )
    with pytest.raises(
        MemoryValidationError, match="mutation_inference_cannot_be_authoritative"
    ):
        compile_memory_mutation_plan(_plan(valid, invalid))


def test_inference_provenance_conflicts_are_rejected_not_downgraded() -> None:
    inferred = _semantic_operation(
        lifecycle_state=SemanticLifecycleState.CANDIDATE,
        epistemic_status=EpistemicStatus.LLM_INFERENCE,
        verification_state=VerificationState.UNVERIFIED,
    )
    with pytest.raises(
        MemoryValidationError, match="mutation_inference_provenance_required"
    ):
        compile_memory_mutation_plan(_plan(inferred))

    inference_span = _span(
        support_kind=EvidenceSupportKind.MODEL_INFERENCE,
        actor_role=EvidenceActorRole.ASSISTANT,
        provenance=EvidenceProvenance.MODEL_OUTPUT,
    )
    falsely_verified = replace(
        inferred,
        evidence_spans=(inference_span,),
        verification_state=VerificationState.USER_CONFIRMED,
    )
    with pytest.raises(MemoryValidationError, match="mutation_inference_must_be_unverified"):
        compile_memory_mutation_plan(_plan(falsely_verified))

    valid_candidate = replace(inferred, evidence_spans=(inference_span,))
    assert compile_memory_mutation_plan(_plan(valid_candidate)).operations


def test_privacy_floor_and_information_attributes_only_join_upward() -> None:
    operation = _semantic_operation()
    classification = join_information_classification(
        operation,
        trusted_privacy_floors=(
            PrivacyClass.PUBLIC,
            PrivacyClass.SENSITIVE,
            PrivacyClass.RESTRICTED,
        ),
        trusted_attribute_sets=(
            (InformationAttribute.HEALTH,),
            (InformationAttribute.FINANCIAL, InformationAttribute.PREFERENCE),
        ),
    )
    assert classification.privacy_class is PrivacyClass.RESTRICTED
    assert classification.information_attributes == (
        InformationAttribute.FINANCIAL,
        InformationAttribute.HEALTH,
        InformationAttribute.PREFERENCE,
    )
    with pytest.raises(MemoryValidationError, match="trusted_privacy_floor_required"):
        join_information_classification(operation, trusted_privacy_floors=())


def test_repository_resolved_transition_tuple_is_validated_without_authority_maps() -> None:
    supersede = _semantic_operation(
        "supersede",
        kind=MemoryMutationKind.SUPERSEDE,
        target=ExistingMemoryTarget("semantic-1", 7),
        lifecycle_state=SemanticLifecycleState.SUPERSEDED,
        evidence_spans=(
            _span(support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION),
        ),
    )
    validate_lifecycle_transition(
        memory_type=LongTermMemoryType.SEMANTIC,
        current_lifecycle=SemanticLifecycleState.ACTIVE,
        operation=supersede,
    )
    with pytest.raises(MemoryValidationError, match="target_memory_type_mismatch"):
        validate_lifecycle_transition(
            memory_type=LongTermMemoryType.EPISODE,
            current_lifecycle=EpisodeLifecycleState.ACTIVE,
            operation=supersede,
        )
    with pytest.raises(MemoryValidationError, match="lifecycle_transition_invalid"):
        validate_lifecycle_transition(
            memory_type=LongTermMemoryType.SEMANTIC,
            current_lifecycle=SemanticLifecycleState.SUPERSEDED,
            operation=supersede,
        )


def test_no_mutation_compiles_to_an_empty_strict_plan() -> None:
    plan = MemoryMutationPlan(
        plan_id="no-mutation-plan",
        run_id="run-1",
        subject="user-1",
        base_revision=4,
        outcome=MemoryMutationPlanOutcome.NO_MUTATION,
        operations=(),
        disclosure_context=_disclosure(),
        evidence_refs=(_evidence_ref(),),
        idempotency_key="no-mutation-idempotency",
    )
    assert compile_memory_mutation_plan(plan).operations == ()
