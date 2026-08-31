"""Strict typed-recall candidate, ranking, budget, and Host-wire builders.

This module deliberately contains no database access.  SQLite owns identity,
suppression, current-head, replay, and final-use authority; these pure values
make the post-gate selection deterministic and independently testable.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simple_harness.contracts import JsonValue, canonical_json, fingerprint_json

if TYPE_CHECKING:
    from simple_harness.runtime import (
        RecallContext,
        RecallDecisionV4,
        RecallPlan,
        TypedRecallResultV1,
    )


RRF_K = 60
RRF_WEIGHTS = {
    "vector": 0.40,
    "full_text": 0.30,
    "entity": 0.15,
    "task_scope": 0.10,
    "temporal": 0.05,
}
SUPPORTED_SELECTOR_DOMAINS = frozenset(
    {"memory_type", "task_scope", "entity", "time", "short_horizon"}
)
SUPPORTED_RETRIEVAL_MODES = frozenset({"full_text", "vector"})


def _digest(domain: str, value: JsonValue) -> str:
    return hashlib.sha256(
        canonical_json({"domain": domain, "payload": value}).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class RecallCandidate:
    """A fully eligible, content-bearing candidate.

    Constructing this value does not grant read authority.  It may only leave
    Memory inside a durable ``TypedRecallResultV1``.
    """

    source_kind: str
    source_ref: str
    source_revision: int | None
    memory_type: str | None
    public_payload: dict[str, JsonValue]
    source_content_hash: str
    effective_privacy_class: str
    information_attributes: tuple[str, ...]
    evidence_manifest_hash: str
    source_task_scope_ids: tuple[str, ...]
    active_task_scope_id: str | None
    source_time: float
    authority_expires_at: float
    lane_ranks: tuple[tuple[str, int], ...]

    @property
    def public_payload_hash(self) -> str:
        return fingerprint_json(self.public_payload)

    @property
    def exact_key(self) -> tuple[object, ...]:
        if self.source_kind == "cognitive_memory":
            return (self.source_kind, self.source_ref, self.source_revision)
        return (self.source_kind, self.source_ref, self.source_content_hash)

    @property
    def cross_scope(self) -> bool:
        return bool(self.source_task_scope_ids) and (
            self.active_task_scope_id is None
            or any(
                scope != self.active_task_scope_id for scope in self.source_task_scope_ids
            )
        )

    @property
    def score(self) -> float:
        ranks = dict(self.lane_ranks)
        return round(
            sum(
                weight / (RRF_K + ranks[lane])
                for lane, weight in RRF_WEIGHTS.items()
                if lane in ranks
            ),
            12,
        )

    @property
    def matched_lane_count(self) -> int:
        return len(dict(self.lane_ranks))

    def provider_budget_value(self) -> dict[str, JsonValue]:
        return {
            "source_kind": self.source_kind,
            "memory_type": self.memory_type,
            "payload": self.public_payload,
        }


@dataclass(frozen=True, slots=True)
class RecallSelection:
    selected: tuple[RecallCandidate, ...]
    truncated: bool
    encoded_bytes: int
    conservative_tokens: int


@dataclass(frozen=True, slots=True)
class RecallConfirmationCandidate:
    conflict_group_id: str
    conflict_group_hash: str
    members: tuple[RecallCandidate, ...]

    def __post_init__(self) -> None:
        if len(self.members) != 2:
            raise ValueError("Memory conflict confirmation group requires exactly two members")


@dataclass(frozen=True, slots=True)
class RecallConfirmationSelection:
    selected: tuple[RecallConfirmationCandidate, ...]
    truncated: bool
    encoded_bytes: int
    conservative_tokens: int


@dataclass(frozen=True, slots=True)
class TypedRecallExecution:
    decision: RecallDecisionV4
    result: TypedRecallResultV1
    candidate_query_started: bool
    candidate_query_count: int
    replayed: bool
    unsupported_capabilities: tuple[str, ...] = ()
    degradation_codes: tuple[str, ...] = ()


def capability_rejections(plan: RecallPlan) -> tuple[str, ...]:
    """Return every unsupported member in the frozen deterministic order."""

    method = getattr(plan, "unsupported_capabilities", None)
    if callable(method):
        values = tuple(method())
        if all(isinstance(item, str) for item in values):
            return values
    domains = {str(getattr(item, "value", item)) for item in plan.selector_domains}
    modes = {str(getattr(item, "value", item)) for item in plan.retrieval_modes}
    ordered = (
        *(f"selector:{item}" for item in ("event", "environment", "task_phase")),
        *(f"retrieval:{item}" for item in ("exact", "temporal", "graph")),
    )
    present = {f"selector:{item}" for item in domains - SUPPORTED_SELECTOR_DOMAINS}
    present |= {f"retrieval:{item}" for item in modes - SUPPORTED_RETRIEVAL_MODES}
    return tuple(item for item in ordered if item in present)


def rank_candidates(candidates: tuple[RecallCandidate, ...]) -> tuple[RecallCandidate, ...]:
    """Apply exact dedupe, narrow cross-source merge, and stable weighted RRF."""

    exact: dict[tuple[object, ...], RecallCandidate] = {}
    for candidate in candidates:
        previous = exact.get(candidate.exact_key)
        if previous is None or candidate.score > previous.score:
            exact[candidate.exact_key] = candidate
    cross_source: dict[tuple[str, str], RecallCandidate] = {}
    for candidate in exact.values():
        key = (candidate.public_payload_hash, candidate.evidence_manifest_hash)
        previous = cross_source.get(key)
        if previous is None or _stable_key(candidate) < _stable_key(previous):
            cross_source[key] = candidate
    return tuple(sorted(cross_source.values(), key=_stable_key))


def _stable_key(candidate: RecallCandidate) -> tuple[object, ...]:
    return (
        -candidate.score,
        -candidate.matched_lane_count,
        -candidate.source_time,
        candidate.source_kind,
        candidate.memory_type or "",
        candidate.source_ref,
        candidate.source_revision or 0,
    )


def apply_budget(
    candidates: tuple[RecallCandidate, ...],
    *,
    max_items: int,
    max_bytes: int,
    max_tokens: int,
) -> RecallSelection:
    """Greedily select whole payloads; an oversize item never blocks a later fit."""

    selected: list[RecallCandidate] = []
    truncated = False
    encoded_bytes = 2
    tokens = 1
    for candidate in candidates:
        if len(selected) >= max_items:
            truncated = True
            continue
        proposed = [item.provider_budget_value() for item in (*selected, candidate)]
        encoded = canonical_json(proposed)  # type: ignore[arg-type]
        size = len(encoded.encode("utf-8"))
        conservative = max(1, len(encoded), math.ceil(size / 3))
        if size > max_bytes or conservative > max_tokens:
            truncated = True
            continue
        selected.append(candidate)
        encoded_bytes = size
        tokens = conservative
    return RecallSelection(tuple(selected), truncated, encoded_bytes, tokens)


def apply_confirmation_budget(
    confirmations: tuple[RecallConfirmationCandidate, ...],
    *,
    max_items: int,
    max_bytes: int,
    max_tokens: int,
) -> RecallConfirmationSelection:
    """Select complete groups while charging every provider-visible member."""

    selected: list[RecallConfirmationCandidate] = []
    selected_member_count = 0
    truncated = False
    encoded_bytes = 2
    tokens = 1
    for confirmation in confirmations:
        proposed_groups = (*selected, confirmation)
        proposed = [
            item.provider_budget_value()
            for group in proposed_groups
            for item in group.members
        ]
        encoded = canonical_json(proposed)  # type: ignore[arg-type]
        size = len(encoded.encode("utf-8"))
        conservative = max(1, len(encoded), math.ceil(size / 3))
        if (
            selected_member_count + len(confirmation.members) > max_items
            or size > max_bytes
            or conservative > max_tokens
        ):
            truncated = True
            continue
        selected.append(confirmation)
        selected_member_count += len(confirmation.members)
        encoded_bytes = size
        tokens = conservative
    return RecallConfirmationSelection(tuple(selected), truncated, encoded_bytes, tokens)


def request_hash(*, principal_id: str, context: RecallContext, plan: RecallPlan) -> str:
    """Domain-separated replay key over the complete public authority and budget."""

    return _digest(
        "simple-harness-memory/typed-recall-request/v1",
        {
            "harness_protocol": "recall-v4",
            "memory_protocol": "typed-recall-v1",
            "principal_id": principal_id,
            "context": context.to_json(),
            "plan": plan.to_json(),
        },
    )


def build_host_execution(
    *,
    request_digest: str,
    context: RecallContext,
    plan: RecallPlan,
    candidates: tuple[RecallCandidate, ...],
    authority_epoch: int,
    policy_hash: str,
    evaluated_at: float,
    authority_expires_at: float,
    candidate_count: int,
    truncated: bool,
    rejected: bool = False,
    rejection_reason: str = "recall_invalid_plan",
    unsupported_capabilities: tuple[str, ...] = (),
    degradation_codes: tuple[str, ...] = (),
) -> TypedRecallExecution:
    """Build canonical Harness v4 decision/result values lazily.

    Lazy import keeps the Memory package import-pure while the Host SDK v4
    wheel is upgraded independently.
    """

    from simple_harness.runtime import (
        LongTermMemoryType,
        PrivacyClass,
        RecallCandidateCountStage,
        RecallDecisionOutcome,
        RecallDecisionV4,
        RecallItemKind,
        RecallReasonCode,
        RecallSelectedItemV4,
        RecallSourceKind,
        TypedRecallResultItemV1,
        TypedRecallResultV1,
    )
    from simple_harness.runtime.information_classification_protocol import (
        InformationAttribute,
    )

    selected_wire = tuple(
        RecallSelectedItemV4(
            item_id=f"recall-item:{request_digest[:24]}:{ordinal}",
            ordinal=ordinal,
            item_kind=RecallItemKind.SELECTED,
            source_kind=RecallSourceKind(candidate.source_kind),
            source_ref=candidate.source_ref,
            source_content_hash=candidate.source_content_hash,
            public_payload_hash=candidate.public_payload_hash,
            memory_type=(
                None
                if candidate.memory_type is None
                else LongTermMemoryType(candidate.memory_type)
            ),
            source_revision=candidate.source_revision,
            chunk_ref=(
                candidate.source_ref
                if candidate.source_kind == RecallSourceKind.SHORT_HORIZON.value
                else None
            ),
        )
        for ordinal, candidate in enumerate(candidates, start=1)
    )
    if rejected:
        outcome = RecallDecisionOutcome.REJECTED
        reasons = (RecallReasonCode(rejection_reason),)
        visible_count = 0
    elif selected_wire:
        outcome = RecallDecisionOutcome.RECALL
        allowed = {
            RecallReasonCode.USER_PREFERENCE_DEPENDENCY,
            RecallReasonCode.PAST_EVENT_DEPENDENCY,
            RecallReasonCode.USER_FACT_DEPENDENCY,
            RecallReasonCode.PROCEDURE_DEPENDENCY,
            RecallReasonCode.FUTURE_INTENTION_DEPENDENCY,
            RecallReasonCode.SHORT_HORIZON_DEPENDENCY,
            RecallReasonCode.TASK_RESUME_DEPENDENCY,
        }
        reasons = tuple(item for item in plan.reason_codes if item in allowed)
        if not reasons:
            reasons = (RecallReasonCode.USER_FACT_DEPENDENCY,)
        visible_count = candidate_count
    else:
        outcome = RecallDecisionOutcome.NO_RECALL
        reasons = (
            RecallReasonCode.BUDGET_EXHAUSTED
            if truncated
            else RecallReasonCode.NO_ELIGIBLE_MEMORY,
        )
        visible_count = 0
    decision = RecallDecisionV4(
        decision_id=f"recall-decision:{request_digest[:32]}",
        run_id=plan.run_id,
        subject=plan.subject,
        context_hash=plan.context_hash,
        context_revision=plan.context_revision,
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        outcome=outcome,
        selected_items=selected_wire,
        confirmation_groups=(),
        filtered_candidate_count=visible_count,
        candidate_count_stage=RecallCandidateCountStage.AFTER_ALL_ELIGIBILITY_GATES,
        disclosure_context=plan.disclosure_context,
        evidence_refs=plan.evidence_refs,
        reason_codes=reasons,
        decided_at=evaluated_at,
    )
    result_items = tuple(
        TypedRecallResultItemV1(
            selected_item=wire,
            public_payload=candidate.public_payload,
            effective_privacy_class=PrivacyClass(candidate.effective_privacy_class),
            information_attributes=tuple(
                InformationAttribute(item) for item in candidate.information_attributes
            ),
            score=candidate.score,
            evidence_manifest_hash=candidate.evidence_manifest_hash,
            source_task_scope_ids=candidate.source_task_scope_ids,
            active_task_scope_id=candidate.active_task_scope_id,
            cross_scope=candidate.cross_scope,
        )
        for wire, candidate in zip(selected_wire, candidates, strict=True)
    )
    result = TypedRecallResultV1(
        result_id=f"recall-result:{request_digest[:32]}",
        decision_id=decision.decision_id,
        decision_hash=decision.decision_hash,
        authority_epoch=authority_epoch,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        authority_expires_at=authority_expires_at,
        items=result_items,
        confirmation_groups=(),
        truncated=truncated,
        reason_codes=reasons,
    )
    result.validate_decision(decision)
    decision.validate_bindings(context, plan, current_time=evaluated_at)
    return TypedRecallExecution(
        decision,
        result,
        candidate_query_started=not rejected,
        candidate_query_count=1 if not rejected else 0,
        replayed=False,
        unsupported_capabilities=unsupported_capabilities,
        degradation_codes=degradation_codes,
    )


def build_host_confirmation_execution(
    *,
    request_digest: str,
    context: RecallContext,
    plan: RecallPlan,
    confirmations: tuple[RecallConfirmationCandidate, ...],
    authority_epoch: int,
    policy_hash: str,
    evaluated_at: float,
    authority_expires_at: float,
    truncated: bool = False,
    degradation_codes: tuple[str, ...] = (),
) -> TypedRecallExecution:
    """Build complete atomic confirmation carriers; never expose one side."""

    from simple_harness.runtime import (
        LongTermMemoryType,
        PrivacyClass,
        RecallCandidateCountStage,
        RecallConfirmationGroupV4,
        RecallConfirmationMemberV4,
        RecallDecisionOutcome,
        RecallDecisionV4,
        RecallItemKind,
        RecallReasonCode,
        TypedRecallConfirmationGroupV1,
        TypedRecallConfirmationMemberV1,
        TypedRecallResultV1,
    )
    from simple_harness.runtime.information_classification_protocol import (
        InformationAttribute,
    )

    groups: list[RecallConfirmationGroupV4] = []
    typed_groups: list[TypedRecallConfirmationGroupV1] = []
    for group_ordinal, confirmation in enumerate(confirmations, start=1):
        members = tuple(
            RecallConfirmationMemberV4(
                item_id=(
                    f"recall-confirmation:{request_digest[:18]}:"
                    f"{group_ordinal}:{member_ordinal}"
                ),
                ordinal=member_ordinal,
                item_kind=RecallItemKind.CONFIRMATION_MEMBER,
                source_ref=item.source_ref,
                source_revision=item.source_revision or 0,
                memory_type=LongTermMemoryType(item.memory_type or ""),
                source_content_hash=item.source_content_hash,
                public_payload_hash=item.public_payload_hash,
            )
            for member_ordinal, item in enumerate(confirmation.members, start=1)
        )
        group = RecallConfirmationGroupV4(
            confirmation.conflict_group_id,
            confirmation.conflict_group_hash,
            group_ordinal,
            members,
        )
        typed_members = tuple(
            TypedRecallConfirmationMemberV1(
                member=member,
                public_payload=item.public_payload,
                effective_privacy_class=PrivacyClass(item.effective_privacy_class),
                information_attributes=tuple(
                    InformationAttribute(value) for value in item.information_attributes
                ),
                evidence_manifest_hash=item.evidence_manifest_hash,
                source_task_scope_ids=item.source_task_scope_ids,
                active_task_scope_id=item.active_task_scope_id,
                cross_scope=item.cross_scope,
            )
            for member, item in zip(members, confirmation.members, strict=True)
        )
        groups.append(group)
        typed_groups.append(TypedRecallConfirmationGroupV1(group, typed_members))
    dependency_reasons = tuple(
        item
        for item in plan.reason_codes
        if item
        in {
            RecallReasonCode.USER_PREFERENCE_DEPENDENCY,
            RecallReasonCode.PAST_EVENT_DEPENDENCY,
            RecallReasonCode.USER_FACT_DEPENDENCY,
            RecallReasonCode.PROCEDURE_DEPENDENCY,
            RecallReasonCode.FUTURE_INTENTION_DEPENDENCY,
            RecallReasonCode.TASK_RESUME_DEPENDENCY,
        }
    ) or (RecallReasonCode.USER_FACT_DEPENDENCY,)
    reasons = (*dependency_reasons, RecallReasonCode.NEEDS_USER_CONFIRMATION)
    if truncated:
        reasons = (*reasons, RecallReasonCode.BUDGET_EXHAUSTED)
    decision = RecallDecisionV4(
        decision_id=f"recall-decision:{request_digest[:32]}",
        run_id=plan.run_id,
        subject=plan.subject,
        context_hash=plan.context_hash,
        context_revision=plan.context_revision,
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        outcome=RecallDecisionOutcome.NEEDS_USER_CONFIRMATION,
        selected_items=(),
        confirmation_groups=tuple(groups),
        filtered_candidate_count=sum(len(group.members) for group in groups),
        candidate_count_stage=RecallCandidateCountStage.AFTER_ALL_ELIGIBILITY_GATES,
        disclosure_context=plan.disclosure_context,
        evidence_refs=plan.evidence_refs,
        reason_codes=reasons,
        decided_at=evaluated_at,
    )
    result = TypedRecallResultV1(
        result_id=f"recall-result:{request_digest[:32]}",
        decision_id=decision.decision_id,
        decision_hash=decision.decision_hash,
        authority_epoch=authority_epoch,
        policy_hash=policy_hash,
        evaluated_at=evaluated_at,
        authority_expires_at=authority_expires_at,
        items=(),
        confirmation_groups=tuple(typed_groups),
        truncated=truncated,
        reason_codes=reasons,
    )
    result.validate_decision(decision)
    decision.validate_bindings(context, plan, current_time=evaluated_at)
    return TypedRecallExecution(
        decision,
        result,
        True,
        len(confirmations),
        False,
        degradation_codes=degradation_codes,
    )


__all__ = (
    "RRF_K",
    "RRF_WEIGHTS",
    "RecallCandidate",
    "RecallConfirmationCandidate",
    "RecallConfirmationSelection",
    "RecallSelection",
    "TypedRecallExecution",
    "apply_budget",
    "apply_confirmation_budget",
    "build_host_execution",
    "build_host_confirmation_execution",
    "capability_rejections",
    "rank_candidates",
    "request_hash",
)
