"""Pure compilation rules for the strict Harness cognitive mutation protocol.

The public wire format belongs to :mod:`simple_harness.runtime`.  This module
does not duplicate that format and deliberately owns no identity, evidence,
revision, suppression, or idempotency authority.  A repository first resolves
those facts from canonical storage, then uses the pure helpers here before it
commits the whole plan atomically.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Final

from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    ConflictStatus,
    EpisodeLifecycleState,
    EpistemicStatus,
    EvidenceActorRole,
    EvidenceProvenance,
    EvidenceSupportKind,
    ExistingMemoryTarget,
    InformationAttribute,
    LongTermMemoryType,
    MemoryMutationApplyMode,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    MemoryMutationPlanOutcome,
    PrivacyClass,
    ProcedureLifecycleState,
    ProspectiveLifecycleState,
    SemanticLifecycleState,
    VerificationState,
)
from simple_harness.runtime.memory_protocol import CognitiveLifecycleState

from simple_harness_memory.core.errors import MemoryValidationError

_PRIVACY_ORDER: Final[dict[PrivacyClass, int]] = {
    PrivacyClass.PUBLIC: 0,
    PrivacyClass.PERSONAL: 1,
    PrivacyClass.SENSITIVE: 2,
    PrivacyClass.RESTRICTED: 3,
}


def _policy_identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


_INITIAL_LIFECYCLES: Final[dict[LongTermMemoryType, frozenset[CognitiveLifecycleState]]] = {
    LongTermMemoryType.EPISODE: frozenset(
        {EpisodeLifecycleState.CANDIDATE, EpisodeLifecycleState.ACTIVE}
    ),
    LongTermMemoryType.SEMANTIC: frozenset(
        {SemanticLifecycleState.CANDIDATE, SemanticLifecycleState.ACTIVE}
    ),
    LongTermMemoryType.PROCEDURE: frozenset(
        {ProcedureLifecycleState.DRAFT, ProcedureLifecycleState.ACTIVE}
    ),
    LongTermMemoryType.PROSPECTIVE: frozenset(
        {ProspectiveLifecycleState.CANDIDATE, ProspectiveLifecycleState.PENDING}
    ),
}

_LIFECYCLE_TRANSITIONS: Final[
    dict[LongTermMemoryType, dict[CognitiveLifecycleState, frozenset[CognitiveLifecycleState]]]
] = {
    LongTermMemoryType.EPISODE: {
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
    },
    LongTermMemoryType.SEMANTIC: {
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
    },
    LongTermMemoryType.PROCEDURE: {
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
    },
    LongTermMemoryType.PROSPECTIVE: {
        ProspectiveLifecycleState.CANDIDATE: frozenset(
            {
                ProspectiveLifecycleState.PENDING,
                ProspectiveLifecycleState.CANCELLED,
                ProspectiveLifecycleState.EXPIRED,
                ProspectiveLifecycleState.FORGOTTEN,
            }
        ),
        ProspectiveLifecycleState.PENDING: frozenset(
            {
                ProspectiveLifecycleState.TRIGGERED,
                ProspectiveLifecycleState.RESCHEDULED,
                ProspectiveLifecycleState.CANCELLED,
                ProspectiveLifecycleState.EXPIRED,
                ProspectiveLifecycleState.SUPERSEDED,
                ProspectiveLifecycleState.FORGOTTEN,
            }
        ),
        ProspectiveLifecycleState.TRIGGERED: frozenset(
            {
                ProspectiveLifecycleState.IN_PROGRESS,
                ProspectiveLifecycleState.COMPLETED,
                ProspectiveLifecycleState.RESCHEDULED,
                ProspectiveLifecycleState.CANCELLED,
                ProspectiveLifecycleState.FORGOTTEN,
            }
        ),
        ProspectiveLifecycleState.IN_PROGRESS: frozenset(
            {
                ProspectiveLifecycleState.COMPLETED,
                ProspectiveLifecycleState.RESCHEDULED,
                ProspectiveLifecycleState.CANCELLED,
                ProspectiveLifecycleState.FORGOTTEN,
            }
        ),
        ProspectiveLifecycleState.RESCHEDULED: frozenset(
            {
                ProspectiveLifecycleState.PENDING,
                ProspectiveLifecycleState.TRIGGERED,
                ProspectiveLifecycleState.CANCELLED,
                ProspectiveLifecycleState.EXPIRED,
                ProspectiveLifecycleState.SUPERSEDED,
                ProspectiveLifecycleState.FORGOTTEN,
            }
        ),
        ProspectiveLifecycleState.COMPLETED: frozenset(),
        ProspectiveLifecycleState.CANCELLED: frozenset(),
        ProspectiveLifecycleState.EXPIRED: frozenset(),
        ProspectiveLifecycleState.SUPERSEDED: frozenset(),
        ProspectiveLifecycleState.FORGOTTEN: frozenset(),
    },
}


@dataclass(frozen=True, slots=True)
class EffectiveInformationClassification:
    """Deterministic join of proposal labels and repository-resolved floors."""

    privacy_class: PrivacyClass
    information_attributes: tuple[InformationAttribute, ...]


@dataclass(frozen=True, slots=True)
class InformationClassificationPolicy:
    """Memory-owned explicit authority floor for every cognitive mutation."""

    policy_id: str
    policy_version: str
    authority_ref: str
    required_privacy_class: PrivacyClass
    required_information_attributes: tuple[InformationAttribute, ...]
    schema_version: int = 1
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise MemoryValidationError("classification_policy_schema_unsupported")
        for value, name in (
            (self.policy_id, "classification_policy_id"),
            (self.policy_version, "classification_policy_version"),
            (self.authority_ref, "classification_policy_authority_ref"),
        ):
            _policy_identifier(value, name)
        privacy = PrivacyClass(self.required_privacy_class)
        try:
            attributes = tuple(
                sorted(
                    {InformationAttribute(item) for item in self.required_information_attributes},
                    key=lambda item: item.value,
                )
            )
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("classification_policy_attributes_invalid") from exc
        if len(attributes) != len(self.required_information_attributes) or len(attributes) > 32:
            raise MemoryValidationError("classification_policy_attributes_invalid")
        object.__setattr__(self, "required_privacy_class", privacy)
        object.__setattr__(self, "required_information_attributes", attributes)
        object.__setattr__(
            self,
            "policy_hash",
            hashlib.sha256(canonical_json(self.to_json()).encode("utf-8")).hexdigest(),
        )

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "authority_ref": self.authority_ref,
            "required_privacy_class": self.required_privacy_class.value,
            "required_information_attributes": [
                item.value for item in self.required_information_attributes
            ],
        }


@dataclass(frozen=True, slots=True)
class CompiledMemoryMutationOperation:
    """An exact Harness operation that passed pure semantic validation."""

    operation: MemoryMutationOperation

    @property
    def operation_id(self) -> str:
        return self.operation.operation_id


@dataclass(frozen=True, slots=True)
class CompiledMemoryMutationPlan:
    """Canonical apply order for one indivisible Harness mutation plan."""

    plan: MemoryMutationPlan
    operations: tuple[CompiledMemoryMutationOperation, ...]

    def __post_init__(self) -> None:
        if self.plan.apply_mode is not MemoryMutationApplyMode.STRICT_ATOMIC:
            raise MemoryValidationError("mutation_apply_mode_not_strict_atomic")
        expected = tuple(item.operation_id for item in self.plan.topological_operations())
        actual = tuple(item.operation_id for item in self.operations)
        if actual != expected:
            raise MemoryValidationError("mutation_compiled_order_differs")


def join_information_classification(
    operation: MemoryMutationOperation,
    *,
    trusted_privacy_floors: tuple[PrivacyClass, ...],
    trusted_attribute_sets: tuple[tuple[InformationAttribute, ...], ...] = (),
) -> EffectiveInformationClassification:
    """Join classifications after the repository has resolved trusted inputs.

    This function does not discover or trust those inputs.  Passing every
    policy, Host, target, evidence, and proposal floor is the repository's
    transaction-local responsibility.
    """

    if not isinstance(operation, MemoryMutationOperation):
        raise MemoryValidationError("harness_memory_mutation_operation_required")
    if not trusted_privacy_floors:
        raise MemoryValidationError("trusted_privacy_floor_required")
    floors = tuple(PrivacyClass(item) for item in trusted_privacy_floors)
    attributes = {
        InformationAttribute(item) for values in trusted_attribute_sets for item in values
    }
    attributes.update(operation.proposed_information_attributes)
    return EffectiveInformationClassification(
        privacy_class=max(
            (operation.proposed_privacy_class, *floors),
            key=_PRIVACY_ORDER.__getitem__,
        ),
        information_attributes=tuple(sorted(attributes, key=lambda item: item.value)),
    )


def validate_lifecycle_transition(
    *,
    memory_type: LongTermMemoryType,
    current_lifecycle: CognitiveLifecycleState,
    operation: MemoryMutationOperation,
) -> None:
    """Validate a transition using repository-resolved current state.

    The repository remains authoritative for the target record, its revision,
    and its type.  This helper only validates the supplied transition tuple.
    """

    memory_type = LongTermMemoryType(memory_type)
    if operation.memory_type is not memory_type:
        raise MemoryValidationError("mutation_target_memory_type_mismatch")
    if operation.kind is MemoryMutationKind.CONTEST:
        if not isinstance(operation.target, ExistingMemoryTarget):
            raise MemoryValidationError("mutation_contest_exact_target_required")
        if operation.lifecycle_state != current_lifecycle:
            raise MemoryValidationError("mutation_contest_lifecycle_must_be_unchanged")
        if operation.conflict_status is not ConflictStatus.CONTESTED:
            raise MemoryValidationError("mutation_contest_requires_contested_state")
        return
    transitions = _LIFECYCLE_TRANSITIONS[memory_type]
    if current_lifecycle not in transitions:
        raise MemoryValidationError("mutation_current_lifecycle_type_mismatch")
    if operation.lifecycle_state not in transitions[current_lifecycle]:
        raise MemoryValidationError("mutation_lifecycle_transition_invalid")
    _validate_kind_lifecycle(operation, is_create=False)


def compile_memory_mutation_plan(
    plan: MemoryMutationPlan,
) -> CompiledMemoryMutationPlan:
    """Compile an exact strict-v2 Harness plan without consulting authority.

    All operations are validated before a compiled value is returned.  There
    is no partial outcome: one invalid operation rejects the whole plan.
    """

    if not isinstance(plan, MemoryMutationPlan):
        raise MemoryValidationError("harness_memory_mutation_plan_required")
    if plan.apply_mode is not MemoryMutationApplyMode.STRICT_ATOMIC:
        raise MemoryValidationError("mutation_apply_mode_not_strict_atomic")
    if plan.outcome is MemoryMutationPlanOutcome.NO_MUTATION:
        return CompiledMemoryMutationPlan(plan, ())

    compiled: list[CompiledMemoryMutationOperation] = []
    for operation in plan.topological_operations():
        _validate_operation(operation)
        compiled.append(CompiledMemoryMutationOperation(operation))
    return CompiledMemoryMutationPlan(plan, tuple(compiled))


def _validate_operation(operation: MemoryMutationOperation) -> None:
    if operation.kind is MemoryMutationKind.CREATE:
        _validate_kind_lifecycle(operation, is_create=True)
    else:
        _validate_kind_lifecycle(operation, is_create=False)
    _validate_epistemic_provenance(operation)


def _validate_kind_lifecycle(operation: MemoryMutationOperation, *, is_create: bool) -> None:
    lifecycle = operation.lifecycle_state
    if is_create:
        if lifecycle not in _INITIAL_LIFECYCLES[operation.memory_type]:
            raise MemoryValidationError("mutation_create_lifecycle_invalid")
        return

    if operation.kind is MemoryMutationKind.SUPPRESS:
        if lifecycle.value != "forgotten":
            raise MemoryValidationError("mutation_suppress_requires_forgotten")
    elif operation.kind is MemoryMutationKind.SUPERSEDE:
        if lifecycle.value != "superseded":
            raise MemoryValidationError("mutation_supersede_requires_superseded")
    elif operation.kind is MemoryMutationKind.CONTEST:
        if not isinstance(operation.target, ExistingMemoryTarget):
            raise MemoryValidationError("mutation_contest_exact_target_required")
        is_contested = (
            lifecycle is EpisodeLifecycleState.DISPUTED
            or operation.conflict_status is ConflictStatus.CONTESTED
        )
        if not is_contested:
            raise MemoryValidationError("mutation_contest_requires_contested_state")
    elif operation.kind is MemoryMutationKind.REVISE:
        if lifecycle.value in {"forgotten", "superseded"}:
            raise MemoryValidationError("mutation_revise_terminal_lifecycle_invalid")


def _validate_epistemic_provenance(operation: MemoryMutationOperation) -> None:
    spans = operation.evidence_spans
    authenticated_user_assertion = any(
        span.support_kind
        in {
            EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
            EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
        }
        and span.actor_role is EvidenceActorRole.USER
        and span.provenance is EvidenceProvenance.AUTHENTICATED_USER
        for span in spans
    )
    authenticated_user_correction = any(
        span.support_kind is EvidenceSupportKind.EXPLICIT_USER_CORRECTION
        and span.actor_role is EvidenceActorRole.USER
        and span.provenance is EvidenceProvenance.AUTHENTICATED_USER
        for span in spans
    )
    trusted_external_observation = any(
        span.support_kind is EvidenceSupportKind.TYPED_OBSERVATION
        and span.typed_observation is not None
        and span.actor_role is EvidenceActorRole.EXTERNAL
        and span.provenance is EvidenceProvenance.EXTERNAL_SOURCE
        for span in spans
    )
    trusted_behavior_observation = any(
        (
            span.support_kind is EvidenceSupportKind.TYPED_OBSERVATION
            and span.typed_observation is not None
            and span.actor_role is EvidenceActorRole.TOOL
            and span.provenance is EvidenceProvenance.TRUSTED_TOOL
        )
        or (
            span.support_kind is EvidenceSupportKind.RUNTIME_EVENT
            and span.actor_role is EvidenceActorRole.RUNTIME
            and span.provenance is EvidenceProvenance.HOST_RUNTIME
        )
        for span in spans
    )
    trusted_typed_observation = any(
        span.support_kind is EvidenceSupportKind.TYPED_OBSERVATION
        and span.typed_observation is not None
        and span.provenance in {EvidenceProvenance.TRUSTED_TOOL, EvidenceProvenance.EXTERNAL_SOURCE}
        and span.actor_role in {EvidenceActorRole.TOOL, EvidenceActorRole.EXTERNAL}
        for span in spans
    )

    if operation.epistemic_status is EpistemicStatus.EXPLICIT_USER:
        if not authenticated_user_assertion:
            raise MemoryValidationError("mutation_explicit_user_provenance_required")

    if operation.epistemic_status is EpistemicStatus.VERIFIED_EXTERNAL:
        if not trusted_external_observation:
            raise MemoryValidationError("mutation_verified_external_authority_required")
        if operation.verification_state is not VerificationState.SOURCE_VERIFIED:
            raise MemoryValidationError("mutation_verified_external_state_invalid")

    if operation.epistemic_status is EpistemicStatus.OBSERVED_BEHAVIOR:
        if not trusted_behavior_observation:
            raise MemoryValidationError("mutation_observed_behavior_authority_required")

    if operation.epistemic_status is EpistemicStatus.UNKNOWN:
        if operation.kind in {
            MemoryMutationKind.SUPERSEDE,
            MemoryMutationKind.SUPPRESS,
        }:
            raise MemoryValidationError("mutation_unknown_cannot_change_authority")
        if operation.lifecycle_state.value not in {"candidate", "draft"}:
            raise MemoryValidationError("mutation_unknown_cannot_be_authoritative")
        if operation.verification_state is not VerificationState.UNVERIFIED:
            raise MemoryValidationError("mutation_unknown_must_be_unverified")

    if operation.epistemic_status is EpistemicStatus.LLM_INFERENCE:
        if not any(
            span.support_kind is EvidenceSupportKind.MODEL_INFERENCE
            and span.actor_role is EvidenceActorRole.ASSISTANT
            and span.provenance is EvidenceProvenance.MODEL_OUTPUT
            for span in spans
        ):
            raise MemoryValidationError("mutation_inference_provenance_required")
        if operation.lifecycle_state.value not in {"candidate", "draft"}:
            raise MemoryValidationError("mutation_inference_cannot_be_authoritative")
        if operation.verification_state is not VerificationState.UNVERIFIED:
            raise MemoryValidationError("mutation_inference_must_be_unverified")

    if (
        operation.verification_state
        in {
            VerificationState.SOURCE_VERIFIED,
            VerificationState.REPEATED_OBSERVATION,
        }
        and not trusted_typed_observation
    ):
        raise MemoryValidationError("mutation_verified_requires_typed_observation")

    if operation.kind is MemoryMutationKind.SUPPRESS and not authenticated_user_correction:
        raise MemoryValidationError("mutation_suppress_requires_user_forget_authority")

    if operation.kind is MemoryMutationKind.SUPERSEDE and not (
        authenticated_user_correction or trusted_external_observation
    ):
        raise MemoryValidationError("mutation_supersede_authority_required")

    if (
        operation.memory_type is LongTermMemoryType.PROSPECTIVE
        and operation.lifecycle_state is ProspectiveLifecycleState.PENDING
        and operation.epistemic_status is EpistemicStatus.LLM_INFERENCE
    ):
        raise MemoryValidationError("mutation_inference_cannot_schedule_prospective")

    if (
        operation.memory_type is LongTermMemoryType.PROCEDURE
        and operation.lifecycle_state is ProcedureLifecycleState.ACTIVE
        and operation.epistemic_status is not EpistemicStatus.EXPLICIT_USER
    ):
        raise MemoryValidationError("mutation_observed_procedure_cannot_activate")


__all__ = (
    "CompiledMemoryMutationOperation",
    "CompiledMemoryMutationPlan",
    "EffectiveInformationClassification",
    "InformationClassificationPolicy",
    "compile_memory_mutation_plan",
    "join_information_classification",
    "validate_lifecycle_transition",
)
