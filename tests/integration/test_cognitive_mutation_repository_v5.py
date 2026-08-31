from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from simple_harness.contracts import FrozenJsonValue, JsonValue, canonical_json, fingerprint_json
from simple_harness.runtime import (
    EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
    AdmittedEvidenceAuthority,
    ConflictStatus,
    ConversationEvidenceMetadata,
    ConversationEvidenceMetadataReceipt,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    ConversationEvidenceRole,
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
    EvidenceItemAuthority,
    EvidenceProvenance,
    EvidenceReasonCode,
    EvidenceRef,
    EvidenceSourceKind,
    EvidenceSpanRef,
    EvidenceSupportKind,
    ExistingMemoryTarget,
    InformationAttribute,
    IntendedAudience,
    LongTermMemoryType,
    MemoryMutationApplyOutcome,
    MemoryMutationApplyReasonCode,
    MemoryMutationApplyReceiptRef,
    MemoryMutationApplyResult,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    MemoryMutationPlanOutcome,
    PrivacyClass,
    ProcedureLifecycleState,
    ProcedureMemoryPayload,
    ProcedureRiskLevel,
    ProposedTypedObservationRef,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveTimeTrigger,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    SemanticLifecycleState,
    SemanticMemoryPayload,
    TypedObservationAuthorityReceipt,
    ValidTimeInterval,
    VerificationState,
)
from simple_harness.runtime.evidence_protocol import (
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
)
from simple_harness.runtime.memory_action_protocol import (
    MemoryActionAuthority,
    MemoryActionAuthorityRef,
    issue_memory_action_authority,
)

from simple_harness_memory.backends.sqlite_v5 import (
    COGNITIVE_CONFLICT_FAULT_POINTS,
    COGNITIVE_MUTATION_FAULT_POINTS,
    SQLiteHumanMemoryBackend,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryValidationError,
    MemoryWriterConflict,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionDenied,
    SuppressionRequest,
    SuppressionScopeKind,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disclosure(subject: str = "actor-1") -> DisclosureContext:
    return DisclosureContext(
        run_id="run-1",
        subject=subject,
        recipient=DeliveryRecipient.USER_SELF,
        recipient_id=subject,
        intended_audience=IntendedAudience.USER_SELF,
        purpose=DisclosurePurpose.PERSONALIZATION,
        source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY,
        generation=DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _admitted(
    *,
    source_kind: EvidenceSourceKind = EvidenceSourceKind.USER_MESSAGE,
    subject: str = "actor-1",
    evidence_id: str = "evidence-1",
) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {
        "item_id": "message-1",
        "public_text": "user prefers concise answers",
    }
    envelope = SanitizedEvidenceEnvelope(
        evidence_id=evidence_id,
        run_id="run-1",
        subject=subject,
        source_kind=source_kind,
        source_ref=(
            ("turn-1/user" if evidence_id == "evidence-1" else f"turn-{evidence_id}/user")
            if source_kind is EvidenceSourceKind.USER_MESSAGE
            else "provider-1/record-1"
        ),
        source_hash="a" * 64,
        sanitized_payload=cast(dict[str, FrozenJsonValue], payload),
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(subject),
        evidence_refs=(),
    )
    receipt = SanitizedEvidenceReceipt(
        receipt_id=("admission-1" if evidence_id == "evidence-1" else f"admission-{evidence_id}"),
        run_id=envelope.run_id,
        subject=envelope.subject,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=envelope.disclosure_context,
        evidence_refs=envelope.evidence_refs,
        admitted_at=10.0,
    )
    return envelope, receipt


def _span(
    envelope: SanitizedEvidenceEnvelope,
    receipt: SanitizedEvidenceReceipt,
    *,
    actor_role: EvidenceActorRole = EvidenceActorRole.USER,
    provenance: EvidenceProvenance = EvidenceProvenance.AUTHENTICATED_USER,
    support_kind: EvidenceSupportKind = EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
    typed_observation: ProposedTypedObservationRef | None = None,
) -> EvidenceSpanRef:
    text = cast(str, envelope.sanitized_payload["public_text"])
    return EvidenceSpanRef(
        span_id="span-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id="message-1",
        item_json_pointer="/public_text",
        start_byte=0,
        end_byte=len(text.encode("utf-8")),
        exact_quote=text,
        quote_hash=_sha(text),
        source_hash=envelope.source_hash,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=actor_role,
        provenance=provenance,
        support_kind=support_kind,
        typed_observation=typed_observation,
    )


def _item_authority(span: EvidenceSpanRef) -> EvidenceItemAuthority:
    return EvidenceItemAuthority(
        schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
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
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(),
        classification_authority_ref="host-classification-1",
        issuer_ref="host-evidence-1",
    )


def _classification_policy() -> InformationClassificationPolicy:
    return InformationClassificationPolicy(
        policy_id="memory-classification-policy",
        policy_version="1",
        authority_ref="memory-policy-registry:classification/v1",
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(),
    )


class _Authority:
    def __init__(
        self,
        envelope: SanitizedEvidenceEnvelope,
        receipt: SanitizedEvidenceReceipt,
        span: EvidenceSpanRef,
        typed_observation_receipt: TypedObservationAuthorityReceipt | None = None,
    ) -> None:
        self.admitted = AdmittedEvidenceAuthority(envelope, receipt, _item_authority(span))
        self.admitted_overrides: dict[str, AdmittedEvidenceAuthority] = {}
        self.admitted_resolution_count = 0
        self.typed_observation_receipt = typed_observation_receipt
        self.action_authorities: dict[str, MemoryActionAuthority] = {}
        self.action_resolution_count = 0
        self.action_resolution_hook: Callable[[], None] | None = None

    async def resolve_admitted_evidence(self, span: EvidenceSpanRef) -> AdmittedEvidenceAuthority:
        self.admitted_resolution_count += 1
        return self.admitted_overrides.get(span.evidence_id, self.admitted)

    def register_admitted(
        self,
        envelope: SanitizedEvidenceEnvelope,
        receipt: SanitizedEvidenceReceipt,
        span: EvidenceSpanRef,
    ) -> None:
        self.admitted_overrides[span.evidence_id] = AdmittedEvidenceAuthority(
            envelope, receipt, _item_authority(span)
        )

    async def resolve_typed_observation(
        self, reference: ProposedTypedObservationRef
    ) -> TypedObservationAuthorityReceipt:
        if self.typed_observation_receipt is None:
            raise ValueError("no typed observation is registered")
        return self.typed_observation_receipt

    async def resolve_memory_action_authority(
        self, reference: MemoryActionAuthorityRef
    ) -> MemoryActionAuthority:
        self.action_resolution_count += 1
        if self.action_resolution_hook is not None:
            self.action_resolution_hook()
        return self.action_authorities[reference.authority_id]


def _with_action_authorities(
    plan: MemoryMutationPlan,
    authority: Any,
    *,
    issued_at: float = 10.0,
    expires_at: float = 30.0,
    nonce_prefix: str = "action-nonce",
) -> MemoryMutationPlan:
    operations: list[MemoryMutationOperation] = []
    for operation in plan.operations:
        if operation.kind not in {
            MemoryMutationKind.REVISE,
            MemoryMutationKind.SUPERSEDE,
            MemoryMutationKind.SUPPRESS,
        }:
            operations.append(operation)
            continue
        intent = plan.action_intent(operation.operation_id)
        grant = issue_memory_action_authority(
            intent,
            authority_id=f"authority-{operation.operation_id}",
            issued_at=issued_at,
            expires_at=expires_at,
            nonce=f"{nonce_prefix}-{operation.operation_id}",
            issuer_ref="host-memory-action-authority:v1",
        )
        authority.action_authorities[grant.authority_id] = grant
        operations.append(
            replace(
                operation,
                action_authority_ref=MemoryActionAuthorityRef.from_authority(grant),
            )
        )
    return replace(plan, operations=tuple(operations))


def _operation(
    span: EvidenceSpanRef,
    *,
    operation_id: str = "create-1",
    kind: MemoryMutationKind = MemoryMutationKind.CREATE,
    target: ExistingMemoryTarget | CreatedByOperationTarget | None = None,
    depends_on: tuple[str, ...] = (),
    privacy: PrivacyClass = PrivacyClass.PUBLIC,
    attributes: tuple[InformationAttribute, ...] = (InformationAttribute.PREFERENCE,),
    epistemic_status: EpistemicStatus = EpistemicStatus.EXPLICIT_USER,
    conflict_status: ConflictStatus = ConflictStatus.UNCONTESTED,
    verification_state: VerificationState = VerificationState.SOURCE_BOUND,
) -> MemoryMutationOperation:
    return MemoryMutationOperation(
        operation_id=operation_id,
        kind=kind,
        memory_type=LongTermMemoryType.SEMANTIC,
        payload=SemanticMemoryPayload("user:self", "response_style", "concise", ("default",)),
        target=target,
        depends_on_operation_ids=depends_on,
        lifecycle_state=SemanticLifecycleState.ACTIVE,
        epistemic_status=epistemic_status,
        conflict_status=conflict_status,
        verification_state=verification_state,
        valid_time_interval=ValidTimeInterval(None, None),
        proposed_privacy_class=privacy,
        proposed_information_attributes=attributes,
        evidence_spans=(span,),
        reason_code="explicit_user_assertion",
    )


def _plan(
    envelope: SanitizedEvidenceEnvelope,
    *operations: MemoryMutationOperation,
    base_revision: int = 1,
    plan_id: str = "plan-1",
    idempotency_key: str = "idempotency-1",
) -> MemoryMutationPlan:
    return MemoryMutationPlan(
        plan_id=plan_id,
        run_id="run-1",
        turn_id="turn-1",
        subject=envelope.subject,
        base_revision=base_revision,
        outcome=MemoryMutationPlanOutcome.MUTATE,
        operations=tuple(operations),
        disclosure_context=_disclosure(envelope.subject),
        evidence_refs=(EvidenceRef(envelope.evidence_id, envelope.envelope_hash, 1),),
        idempotency_key=idempotency_key,
    )


async def _prepared(
    path: Path,
    *,
    fault=None,
    now: Callable[[], float] | None = None,
) -> tuple[
    SQLiteHumanMemoryBackend,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    EvidenceSpanRef,
    _Authority,
]:
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=now or (lambda: 20.0),
        fault_injector=fault,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    return backend, envelope, receipt, span, authority


def _principal(actor_id: str = "actor-1") -> MemoryPrincipal:
    return MemoryPrincipal("deployment-1", "household-1", actor_id, "session-1")


def _committed_receipt_ref(result: MemoryMutationApplyResult) -> MemoryMutationApplyReceiptRef:
    assert result.outcome is MemoryMutationApplyOutcome.COMMITTED
    assert result.receipt_ref is not None
    return result.receipt_ref


async def _cognitive_counts(backend: SQLiteHumanMemoryBackend) -> dict[str, int]:
    tables = (
        "cognitive_apply_heads",
        "cognitive_memory_heads",
        "cognitive_memory_revisions",
        "semantic_claims",
        "cognitive_evidence_spans",
        "cognitive_relations",
        "cognitive_classification_decisions",
        "cognitive_classification_evidence_authorities",
        "memory_action_authority_consumptions",
        "memory_mutation_receipts",
        "memory_mutation_decisions",
    )
    result: dict[str, int] = {}
    for table in tables:
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        result[table] = int(row[0])
    return result


def _tamper_immutable_table(path: Path, table: str, update_sql: str) -> None:
    connection = sqlite3.connect(path)
    try:
        triggers = [
            (str(name), str(sql))
            for name, sql in connection.execute(
                "SELECT name,sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=? ORDER BY name",
                (table,),
            )
        ]
        for name, _sql in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(update_sql)
        for _name, sql in triggers:
            connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def _tamper_classification_refs(path: Path, variant: str) -> None:
    connection = sqlite3.connect(path)
    try:
        triggers = [
            (str(name), str(sql))
            for name, sql in connection.execute(
                "SELECT name,sql FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name='memory_mutation_receipts' ORDER BY name"
            )
        ]
        row = connection.execute(
            "SELECT classification_decision_refs_json FROM memory_mutation_receipts"
        ).fetchone()
        assert row is not None
        refs = json.loads(str(row[0]))
        assert isinstance(refs, list) and len(refs) == 2
        if variant == "empty":
            refs = []
        elif variant == "subset":
            refs = refs[:1]
        elif variant == "duplicate":
            refs = [refs[0], refs[0]]
        elif variant == "out-of-order":
            refs = list(reversed(refs))
        else:  # pragma: no cover - test helper contract
            raise AssertionError(f"unknown refs tamper variant: {variant}")
        refs_json = canonical_json(refs)
        refs_hash = _sha(refs_json)
        for name, _sql in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        connection.execute(
            "UPDATE memory_mutation_receipts "
            "SET classification_decision_refs_json=?,classification_decisions_hash=?",
            (refs_json, refs_hash),
        )
        for _name, sql in triggers:
            connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_create_replay_resolve_and_restart_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "mutation.db"
    backend, envelope, _receipt, span, authority = await _prepared(path)
    plan = _plan(envelope, _operation(span))
    first = await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    assert authority.admitted_resolution_count == 1
    replay = await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    assert replay == first
    resolved = await backend.resolve_memory_mutation_apply_receipt(
        _committed_receipt_ref(first)
    )
    resolved.validate_plan(plan)
    assert await _cognitive_counts(backend) == {
        "cognitive_apply_heads": 1,
        "cognitive_memory_heads": 1,
        "cognitive_memory_revisions": 1,
        "semantic_claims": 1,
        "cognitive_evidence_spans": 1,
        "cognitive_relations": 0,
        "cognitive_classification_decisions": 1,
        "cognitive_classification_evidence_authorities": 1,
        "memory_action_authority_consumptions": 0,
        "memory_mutation_receipts": 1,
        "memory_mutation_decisions": 1,
    }
    async with backend.connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT effective_privacy_class,valid_from FROM cognitive_memory_revisions"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and (str(row[0]), row[1]) == ("personal", None)
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(
        path,
        evidence_authority=authority,
        classification_policy=_classification_policy(),
    )
    await reopened.initialize()
    assert (
        await reopened.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
        )
        == first
    )
    await reopened.close()


@pytest.mark.asyncio
async def test_action_authority_missing_then_valid_is_typed_atomic_and_auditable(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "action-authority.db"
    )
    created = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    assert created.outcome is MemoryMutationApplyOutcome.COMMITTED
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    proposed = _plan(
        envelope,
        _operation(
            span,
            operation_id="revise-authorized",
            kind=MemoryMutationKind.REVISE,
            target=ExistingMemoryTarget(memory_id, 1),
        ),
        base_revision=2,
        plan_id="revise-authorized-plan",
        idempotency_key="revise-authorized-key",
    )
    before = await _cognitive_counts(backend)
    needs = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=proposed,
    )
    assert needs.outcome is MemoryMutationApplyOutcome.NEEDS_USER_CONFIRMATION
    assert needs.reason_code is MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REQUIRED
    assert [item.intent for item in needs.confirmation_items] == [
        proposed.action_intent("revise-authorized")
    ]
    assert await _cognitive_counts(backend) == before

    authorized = _with_action_authorities(proposed, authority)
    committed = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=authorized,
    )
    assert committed.outcome is MemoryMutationApplyOutcome.COMMITTED
    assert authority.action_resolution_count == 1
    async with backend.connection.execute(
        "SELECT principal_id,plan_hash,canonical_operation_index,action_kind,"
        "target_memory_id,target_revision,intent_hash,authority_hash,nonce "
        "FROM memory_action_authority_consumptions"
    ) as cursor:
        consumption = await cursor.fetchone()
    assert consumption is not None
    assert tuple(consumption[:6]) == (
        "actor-1",
        authorized.plan_hash,
        1,
        "revise",
        memory_id,
        1,
    )
    assert all(isinstance(value, str) and value for value in consumption[6:])
    await backend.resolve_memory_mutation_apply_receipt(
        _committed_receipt_ref(committed)
    )
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("expired", "intent-mismatch"))
async def test_invalid_action_authority_returns_typed_rejected_without_mutation(
    tmp_path: Path,
    mode: str,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / f"action-rejected-{mode}.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    proposed = _plan(
        envelope,
        _operation(
            span,
            operation_id="revise-invalid",
            kind=MemoryMutationKind.REVISE,
            target=ExistingMemoryTarget(memory_id, 1),
        ),
        base_revision=2,
        plan_id="revise-invalid-plan",
        idempotency_key="revise-invalid-key",
    )
    if mode == "expired":
        submitted = _with_action_authorities(
            proposed, authority, issued_at=1.0, expires_at=10.0
        )
    else:
        other = replace(proposed, plan_id="other-plan")
        wrong = issue_memory_action_authority(
            other.action_intent("revise-invalid"),
            authority_id="authority-wrong-intent",
            issued_at=10.0,
            expires_at=30.0,
            nonce="wrong-intent-nonce",
            issuer_ref="host-memory-action-authority:v1",
        )
        authority.action_authorities[wrong.authority_id] = wrong
        submitted = replace(
            proposed,
            operations=(
                replace(
                    proposed.operations[0],
                    action_authority_ref=MemoryActionAuthorityRef.from_authority(wrong),
                ),
            ),
        )
    before = await _cognitive_counts(backend)
    rejected = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=submitted,
    )
    assert rejected.outcome is MemoryMutationApplyOutcome.REJECTED
    assert rejected.reason_code is MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED
    assert await _cognitive_counts(backend) == before
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits "
        "WHERE plan_id='revise-invalid-plan'"
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "mutation_action_authority_rejected"  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("resolver-crosses-expiry", "lookup-miss"))
async def test_action_authority_resolution_failure_is_typed_and_atomic(
    tmp_path: Path,
    mode: str,
) -> None:
    clock = [20.0]
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / f"action-resolution-{mode}.db",
        now=lambda: clock[0],
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    proposed = _plan(
        envelope,
        _operation(
            span,
            operation_id="revise-resolution-failure",
            kind=MemoryMutationKind.REVISE,
            target=ExistingMemoryTarget(memory_id, 1),
        ),
        base_revision=2,
        plan_id=f"action-resolution-{mode}-plan",
        idempotency_key=f"action-resolution-{mode}-key",
    )
    submitted = _with_action_authorities(
        proposed,
        authority,
        issued_at=10.0,
        expires_at=21.0,
        nonce_prefix=mode,
    )
    if mode == "resolver-crosses-expiry":
        authority.action_resolution_hook = lambda: clock.__setitem__(0, 22.0)
    else:
        authority.action_authorities.clear()
    before = await _cognitive_counts(backend)

    rejected = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=submitted,
    )

    assert rejected.outcome is MemoryMutationApplyOutcome.REJECTED
    assert rejected.reason_code is MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED
    assert await _cognitive_counts(backend) == before
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits WHERE plan_id=?",
        (submitted.plan_id,),
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "mutation_action_authority_rejected"  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
async def test_reopen_resolver_accepts_distinct_action_transaction_times(
    tmp_path: Path,
) -> None:
    clock = [19.9]

    def advancing_now() -> float:
        clock[0] += 0.1
        return clock[0]

    path = tmp_path / "action-distinct-times.db"
    backend, envelope, _receipt, span, authority = await _prepared(
        path,
        now=advancing_now,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    plan = _with_action_authorities(
        _plan(
            envelope,
            _operation(
                span,
                operation_id="revise-distinct-times",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(memory_id, 1),
            ),
            base_revision=2,
            plan_id="revise-distinct-times-plan",
            idempotency_key="revise-distinct-times-key",
        ),
        authority,
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=plan,
    )
    receipt_ref = _committed_receipt_ref(result)
    async with backend.connection.execute(
        "SELECT r.transaction_started_at,c.consumed_at,r.committed_at "
        "FROM memory_mutation_receipts r "
        "JOIN memory_action_authority_consumptions c ON c.plan_id=r.plan_id "
        "WHERE r.plan_id='revise-distinct-times-plan'"
    ) as cursor:
        times = await cursor.fetchone()
    assert times is not None
    assert float(times[0]) < float(times[1]) < float(times[2])
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path)
    await reopened.initialize()
    try:
        assert (
            await reopened.resolve_memory_mutation_apply_receipt(receipt_ref)
        ).receipt_hash == receipt_ref.receipt_hash
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_commit_clock_rollback_rejects_action_without_cognitive_writes(
    tmp_path: Path,
) -> None:
    scheduled_times: list[float] = []

    def controlled_now() -> float:
        return scheduled_times.pop(0) if scheduled_times else 20.0

    path = tmp_path / "action-clock-rollback.db"
    backend, envelope, _receipt, span, authority = await _prepared(
        path,
        now=controlled_now,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    plan = _with_action_authorities(
        _plan(
            envelope,
            _operation(
                span,
                operation_id="revise-clock-rollback",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(memory_id, 1),
            ),
            base_revision=2,
            plan_id="revise-clock-rollback-plan",
            idempotency_key="revise-clock-rollback-key",
        ),
        authority,
    )
    before = await _cognitive_counts(backend)
    scheduled_times.extend((20.0, 20.1, 21.0, 20.5))

    rejected = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=plan,
    )

    assert rejected.outcome is MemoryMutationApplyOutcome.REJECTED
    assert rejected.reason_code is MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED
    assert await _cognitive_counts(backend) == before
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path)
    await reopened.initialize()
    try:
        async with reopened.connection.execute(
            "SELECT COUNT(*) FROM memory_mutation_receipts WHERE plan_id=?",
            (plan.plan_id,),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
        async with reopened.connection.execute(
            "SELECT COUNT(*) FROM memory_action_authority_consumptions WHERE plan_id=?",
            (plan.plan_id,),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
        async with reopened.connection.execute(
            "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
            (memory_id,),
        ) as cursor:
            assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
        async with reopened.connection.execute(
            "SELECT reason_code FROM memory_mutation_rejection_audits WHERE plan_id=?",
            (plan.plan_id,),
        ) as cursor:
            assert str((await cursor.fetchone())[0]) == "mutation_action_authority_rejected"  # type: ignore[index]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_action_nonce_replay_across_changed_plan_is_typed_rejected(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "action-nonce-replay.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    first = _with_action_authorities(
        _plan(
            envelope,
            _operation(
                span,
                operation_id="revise-shared",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(memory_id, 1),
            ),
            base_revision=2,
            plan_id="first-action-plan",
            idempotency_key="first-action-key",
        ),
        authority,
        nonce_prefix="shared-nonce",
    )
    assert (
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=first,
        )
    ).outcome is MemoryMutationApplyOutcome.COMMITTED
    second = _with_action_authorities(
        _plan(
            envelope,
            _operation(
                span,
                operation_id="revise-shared",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(memory_id, 2),
            ),
            base_revision=3,
            plan_id="second-action-plan",
            idempotency_key="second-action-key",
        ),
        authority,
        nonce_prefix="shared-nonce",
    )
    rejected = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=second,
    )
    assert rejected.outcome is MemoryMutationApplyOutcome.REJECTED
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM memory_action_authority_consumptions"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "update_sql"),
    (
        (
            "memory_action_authority_consumptions",
            "UPDATE memory_action_authority_consumptions SET authority_hash='tampered'",
        ),
        (
            "memory_action_authority_consumptions",
            "UPDATE memory_action_authority_consumptions SET intent_json='{}'",
        ),
        (
            "memory_mutation_receipts",
            "UPDATE memory_mutation_receipts SET action_authority_refs_json='[]' "
            "WHERE plan_id='action-corruption-plan'",
        ),
        (
            "memory_mutation_decisions",
            "UPDATE memory_mutation_decisions "
            "SET action_authority_consumption_hash='tampered' "
            "WHERE operation_id='action-corruption-revise'",
        ),
    ),
)
async def test_reopen_resolver_rejects_action_authority_ledger_corruption(
    tmp_path: Path,
    table: str,
    update_sql: str,
) -> None:
    path = tmp_path / f"action-corruption-{table}.db"
    backend, envelope, _receipt, span, authority = await _prepared(path)
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    plan = _with_action_authorities(
        _plan(
            envelope,
            _operation(
                span,
                operation_id="action-corruption-revise",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(memory_id, 1),
            ),
            base_revision=2,
            plan_id="action-corruption-plan",
            idempotency_key="action-corruption-key",
        ),
        authority,
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=plan,
    )
    receipt_ref = _committed_receipt_ref(result)
    await backend.close()
    _tamper_immutable_table(path, table, update_sql)

    reopened = SQLiteHumanMemoryBackend(path)
    await reopened.initialize()
    try:
        with pytest.raises(MemoryCorruptionError):
            await reopened.resolve_memory_mutation_apply_receipt(receipt_ref)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_contest_creates_distinct_immutable_conflict_members(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "contest-exact-slot.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="contest-changed-payload",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("default",)
        ),
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="contest-changed-payload-plan",
            idempotency_key="contest-changed-payload-key",
        ),
    )
    assert result.outcome is MemoryMutationApplyOutcome.COMMITTED
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT g.incumbent_revision,g.challenger_revision,m.ordinal,m.role,m.revision,"
        "m.content_hash,m.evidence_set_hash FROM cognitive_conflict_groups g "
        "JOIN cognitive_conflict_members m ON m.group_id=g.group_id "
        "ORDER BY m.ordinal"
    ) as cursor:
        rows = tuple(await cursor.fetchall())
    assert [(int(row[0]), int(row[1]), int(row[2]), str(row[3]), int(row[4])) for row in rows] == [
        (1, 2, 1, "incumbent", 1),
        (1, 2, 2, "challenger", 2),
    ]
    assert str(rows[0][5]) != str(rows[1][5])
    assert str(rows[0][6]) != str(rows[1][6])
    await backend.close()

    _tamper_immutable_table(
        tmp_path / "contest-exact-slot.db",
        "cognitive_conflict_members",
        "UPDATE cognitive_conflict_members SET content_hash='tampered' WHERE ordinal=2",
    )
    reopened = SQLiteHumanMemoryBackend(tmp_path / "contest-exact-slot.db")
    with pytest.raises(MemoryCorruptionError, match="conflict member source differs"):
        await reopened.initialize()


@pytest.mark.asyncio
async def test_contest_rejects_same_content_or_reused_evidence(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "contest-same.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    same = _operation(
        span,
        operation_id="contest-same",
        kind=MemoryMutationKind.CONTEST,
        target=ExistingMemoryTarget(memory_id, 1),
        conflict_status=ConflictStatus.CONTESTED,
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope,
            same,
            base_revision=2,
            plan_id="contest-same-plan",
            idempotency_key="contest-same-key",
        ),
    )
    assert result.outcome is MemoryMutationApplyOutcome.REJECTED
    assert result.reason_code is MemoryMutationApplyReasonCode.VALIDATION_REJECTED
    await backend.close()


@pytest.mark.asyncio
async def test_conflict_resolution_appends_fact_and_never_rolls_back_head(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "contest-resolution.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]

    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="contest-resolution-create",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("default",)
        ),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="contest-resolution-plan",
            idempotency_key="contest-resolution-key",
        ),
    )

    resolution_envelope, resolution_receipt = _admitted(evidence_id="evidence-3")
    resolution_span = replace(
        _span(resolution_envelope, resolution_receipt),
        support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
    )
    authority.register_admitted(
        resolution_envelope, resolution_receipt, resolution_span
    )
    await backend.ingest_committed_evidence(resolution_envelope, resolution_receipt)
    resolve = replace(
        _operation(
            resolution_span,
            operation_id="resolve-to-incumbent",
            kind=MemoryMutationKind.REVISE,
            target=ExistingMemoryTarget(memory_id, 2),
            conflict_status=ConflictStatus.RESOLVED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "concise", ("default",)
        ),
        reason_code="explicit_user_correction",
    )
    resolution_plan = _with_action_authorities(
        _plan(
            resolution_envelope,
            resolve,
            base_revision=3,
            plan_id="resolve-plan",
            idempotency_key="resolve-key",
        ),
        authority,
        nonce_prefix="resolve",
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=resolution_plan,
    )
    assert result.outcome is MemoryMutationApplyOutcome.COMMITTED
    async with backend.connection.execute(
        "SELECT h.current_revision,r.conflict_status,r.content_hash FROM "
        "cognitive_memory_heads h JOIN cognitive_memory_revisions r "
        "ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
        "WHERE h.memory_id=?",
        (memory_id,),
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None
    assert (int(head[0]), str(head[1])) == (3, "resolved")
    async with backend.connection.execute(
        "SELECT content_hash FROM cognitive_memory_revisions "
        "WHERE memory_id=? AND revision=1",
        (memory_id,),
    ) as cursor:
        incumbent = await cursor.fetchone()
    assert incumbent is not None and str(head[2]) == str(incumbent[0])
    async with backend.connection.execute(
        "SELECT resolution_revision,resolution_kind,selected_member_ordinal "
        "FROM cognitive_conflict_resolutions"
    ) as cursor:
        resolution = await cursor.fetchone()
    assert resolution is not None
    assert (int(resolution[0]), str(resolution[1]), int(resolution[2])) == (
        3,
        "selected_incumbent",
        1,
    )
    await backend.close()

    _tamper_immutable_table(
        tmp_path / "contest-resolution.db",
        "cognitive_conflict_resolutions",
        "UPDATE cognitive_conflict_resolutions SET resolution_kind='replacement', "
        "selected_member_ordinal=NULL",
    )
    reopened = SQLiteHumanMemoryBackend(tmp_path / "contest-resolution.db")
    with pytest.raises(MemoryCorruptionError, match="conflict resolution differs"):
        await reopened.initialize()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", COGNITIVE_CONFLICT_FAULT_POINTS[:3])
async def test_conflict_creation_faults_rollback_group_members_and_head(
    tmp_path: Path, fault_point: str
) -> None:
    def fault(point: str) -> None:
        if point == fault_point:
            raise RuntimeError(point)

    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / f"conflict-fault-{fault_point.rsplit('_', 1)[-1]}.db",
        fault=fault,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="contest-fault",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("default",)
        ),
    )
    with pytest.raises(RuntimeError, match=fault_point):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                challenger_envelope,
                contest,
                base_revision=2,
                plan_id="contest-fault-plan",
                idempotency_key="contest-fault-key",
            ),
        )
    for table in (
        "cognitive_conflict_groups",
        "cognitive_conflict_members",
        "cognitive_conflict_resolutions",
        "cognitive_relations",
    ):
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT h.current_revision,COUNT(r.revision) FROM cognitive_memory_heads h "
        "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
        "WHERE h.memory_id=? GROUP BY h.current_revision",
        (memory_id,),
    ) as cursor:
        assert tuple(await cursor.fetchone()) == (1, 1)  # type: ignore[arg-type]
    await backend.close()


@pytest.mark.asyncio
async def test_conflict_resolution_fault_rolls_back_new_revision_and_fact(
    tmp_path: Path,
) -> None:
    armed = False

    def fault(point: str) -> None:
        if armed and point == "mutation.after_conflict_resolution":
            raise RuntimeError(point)

    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "conflict-resolution-fault.db", fault=fault
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="contest-before-resolution-fault",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("default",)
        ),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="contest-before-resolution-fault-plan",
            idempotency_key="contest-before-resolution-fault-key",
        ),
    )
    resolution_envelope, resolution_receipt = _admitted(evidence_id="evidence-3")
    resolution_span = replace(
        _span(resolution_envelope, resolution_receipt),
        support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
    )
    authority.register_admitted(
        resolution_envelope, resolution_receipt, resolution_span
    )
    await backend.ingest_committed_evidence(resolution_envelope, resolution_receipt)
    resolve = replace(
        _operation(
            resolution_span,
            operation_id="resolution-fault",
            kind=MemoryMutationKind.REVISE,
            target=ExistingMemoryTarget(memory_id, 2),
            conflict_status=ConflictStatus.RESOLVED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "concise", ("default",)
        ),
        reason_code="explicit_user_correction",
    )
    plan = _with_action_authorities(
        _plan(
            resolution_envelope,
            resolve,
            base_revision=3,
            plan_id="resolution-fault-plan",
            idempotency_key="resolution-fault-key",
        ),
        authority,
        nonce_prefix="resolution-fault",
    )
    armed = True
    with pytest.raises(RuntimeError, match="mutation.after_conflict_resolution"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=plan,
        )
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM cognitive_conflict_resolutions"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM cognitive_memory_revisions WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "update_sql"),
    (
        ("memory_mutation_receipts", "UPDATE memory_mutation_receipts SET run_id='tampered'"),
        (
            "cognitive_classification_decisions",
            "UPDATE cognitive_classification_decisions SET policy_version='tampered'",
        ),
        (
            "cognitive_classification_evidence_authorities",
            "UPDATE cognitive_classification_evidence_authorities SET issuer_ref='tampered'",
        ),
        (
            "cognitive_memory_revisions",
            "UPDATE cognitive_memory_revisions SET information_attributes_json='[]'",
        ),
        (
            "memory_mutation_decisions",
            "UPDATE memory_mutation_decisions SET reason_code='tampered'",
        ),
        (
            "cognitive_classification_decisions",
            "UPDATE cognitive_classification_decisions SET decision_json='{}'",
        ),
        (
            "memory_mutation_decisions",
            "UPDATE memory_mutation_decisions SET decision_json='{}'",
        ),
        (
            "cognitive_classification_evidence_authorities",
            "UPDATE cognitive_classification_evidence_authorities "
            "SET authority_hash='0000000000000000000000000000000000000000000000000000000000000000'",
        ),
        (
            "memory_mutation_receipts",
            "UPDATE memory_mutation_receipts SET receipt_json='{}'",
        ),
        (
            "memory_mutation_receipts",
            "UPDATE memory_mutation_receipts SET authority_ref='tampered-authority'",
        ),
        (
            "memory_mutation_decisions",
            "DELETE FROM memory_mutation_decisions",
        ),
        (
            "memory_mutation_decisions",
            "INSERT INTO memory_mutation_decisions("
            "decision_id,receipt_id,operation_id,outcome,reason_code,before_ref,after_ref,"
            "classification_decision_id,classification_decision_hash,decision_json,decision_hash) "
            "SELECT 'extra-decision',receipt_id,'extra-operation','committed','extra',NULL,"
            "after_ref,"
            "classification_decision_id,classification_decision_hash,'{}',"
            "'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' "
            "FROM memory_mutation_decisions LIMIT 1",
        ),
    ),
)
async def test_reopen_resolver_recomputes_every_receipt_classification_layer(
    tmp_path: Path,
    table: str,
    update_sql: str,
) -> None:
    path = tmp_path / f"corrupt-{table}.db"
    backend, envelope, _receipt, span, _authority = await _prepared(path)
    plan = _plan(envelope, _operation(span))
    reference = await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    await backend.close()
    _tamper_immutable_table(path, table, update_sql)

    reopened = SQLiteHumanMemoryBackend(path)
    await reopened.initialize()
    try:
        with pytest.raises(MemoryCorruptionError):
            await reopened.resolve_memory_mutation_apply_receipt(
                _committed_receipt_ref(reference)
            )
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ("empty", "subset", "duplicate", "out-of-order"))
async def test_reopen_resolver_rejects_classification_ref_set_corruption(
    tmp_path: Path,
    variant: str,
) -> None:
    path = tmp_path / f"corrupt-refs-{variant}.db"
    backend, envelope, _receipt, span, _authority = await _prepared(path)
    create = _operation(span, operation_id="create-ref")
    create_second = _operation(span, operation_id="create-ref-second")
    plan = _plan(envelope, create_second, create)
    reference = await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    await backend.close()
    _tamper_classification_refs(path, variant)

    reopened = SQLiteHumanMemoryBackend(path)
    await reopened.initialize()
    try:
        with pytest.raises(MemoryCorruptionError):
            await reopened.resolve_memory_mutation_apply_receipt(
                _committed_receipt_ref(reference)
            )
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_classification_policy_and_exact_evidence_authority_join_and_audit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "classification.db"
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    authority.admitted = AdmittedEvidenceAuthority(
        envelope,
        receipt,
        replace(
            _item_authority(span),
            required_privacy_class=PrivacyClass.RESTRICTED,
            required_information_attributes=(InformationAttribute.HEALTH,),
            classification_authority_ref="host-health-classifier:v1",
        ),
    )
    policy = InformationClassificationPolicy(
        policy_id="memory-classification-policy",
        policy_version="2",
        authority_ref="memory-policy-registry:classification/v2",
        required_privacy_class=PrivacyClass.SENSITIVE,
        required_information_attributes=(InformationAttribute.GOAL,),
    )
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: 20.0,
        evidence_authority=authority,
        classification_policy=policy,
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    reference = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    assert authority.admitted_resolution_count == 1
    async with backend.connection.execute(
        "SELECT policy_hash,effective_privacy_class,effective_attributes_json,decision_hash "
        "FROM cognitive_classification_decisions"
    ) as cursor:
        decision = await cursor.fetchone()
    assert decision is not None
    assert str(decision[0]) == policy.policy_hash
    assert str(decision[1]) == "restricted"
    assert str(decision[2]) == '["goal","health","preference"]'
    async with backend.connection.execute(
        "SELECT authority_schema_version,classification_authority_ref,"
        "required_privacy_class,required_attributes_json "
        "FROM cognitive_classification_evidence_authorities"
    ) as cursor:
        evidence_authority = await cursor.fetchone()
    assert evidence_authority is not None
    assert int(evidence_authority[0]) == EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION
    assert tuple(str(item) for item in evidence_authority[1:]) == (
        "host-health-classifier:v1",
        "restricted",
        '["health"]',
    )
    resolved = await backend.resolve_memory_mutation_apply_receipt(
        _committed_receipt_ref(reference)
    )
    assert f"classification:{str(decision[3])}" not in resolved.authority_ref
    async with backend.connection.execute(
        "SELECT classification_decisions_hash,action_authorities_hash,"
        "transaction_started_at FROM memory_mutation_receipts"
    ) as cursor:
        aggregate_row = await cursor.fetchone()
    assert aggregate_row is not None
    transaction_hash = hashlib.sha256(
        canonical_json(
            {"transaction_started_at": float(aggregate_row[2])}
        ).encode("utf-8")
    ).hexdigest()
    aggregate_hash = hashlib.sha256(
        canonical_json(
            {
                "action_authorities_hash": str(aggregate_row[1]),
                "classification_decisions_hash": str(aggregate_row[0]),
                "transaction_started_hash": transaction_hash,
            }
        ).encode("utf-8")
    ).hexdigest()
    assert resolved.authority_ref.endswith(f"mutation:{aggregate_hash}")
    with pytest.raises(sqlite3.IntegrityError, match="immutable cognitive classification decision"):
        await backend.connection.execute(
            "UPDATE cognitive_classification_decisions SET effective_privacy_class='public'"
        )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="immutable cognitive classification evidence authority",
    ):
        await backend.connection.execute(
            "DELETE FROM cognitive_classification_evidence_authorities"
        )
    await backend.close()


@pytest.mark.asyncio
async def test_missing_classification_policy_fails_closed_with_durable_rejection(
    tmp_path: Path,
) -> None:
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "missing-policy.db",
        now=lambda: 20.0,
        evidence_authority=_Authority(envelope, receipt, span),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    with pytest.raises(MemoryValidationError, match="classification_policy_required"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    async with backend.connection.execute(
        "SELECT reason_code,policy_id,policy_hash,rejection_json "
        "FROM memory_mutation_rejection_audits"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert str(row[0]) == "mutation_classification_policy_missing"
    assert row[1] is None and row[2] is None
    assert "classification_policy_required" not in str(row[3])
    await backend.close()


@pytest.mark.asyncio
async def test_initialized_typed_preflight_rejections_are_durable_and_specific(
    tmp_path: Path,
) -> None:
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    missing_authority = SQLiteHumanMemoryBackend(
        tmp_path / "missing-evidence-authority.db",
        now=lambda: 20.0,
        classification_policy=_classification_policy(),
    )
    await missing_authority.initialize()
    with pytest.raises(MemoryValidationError, match="evidence_authority_required"):
        await missing_authority.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    async with missing_authority.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits"
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "mutation_evidence_authority_missing"  # type: ignore[index]
    await missing_authority.close()

    scoped, envelope, _receipt, span, _authority = await _prepared(tmp_path / "scope-rejected.db")
    with pytest.raises(MemoryOwnershipConflict):
        await scoped.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("different-actor"),
            plan=_plan(envelope, _operation(span)),
        )
    subject_mismatch_plan = _plan(
        envelope,
        _operation(span, operation_id="subject-mismatch-operation"),
        plan_id="subject-mismatch-plan",
        idempotency_key="subject-mismatch-key",
    )
    with pytest.raises(MemoryOwnershipConflict, match="mutation_subject_not_owned"):
        await scoped.apply_memory_mutation_plan(
            principal=replace(_principal(), actor_id="different-actor"),
            scope=MemoryScope.personal("different-actor"),
            plan=subject_mismatch_plan,
        )
    async with scoped.connection.execute(
        "SELECT principal_id,plan_id,reason_code,rejection_json "
        "FROM memory_mutation_rejection_audits ORDER BY plan_id"
    ) as cursor:
        rows = await cursor.fetchall()
    reasons = [str(row[2]) for row in rows]
    assert reasons == [
        "mutation_scope_or_ownership_rejected",
        "mutation_scope_or_ownership_rejected",
    ]
    subject_mismatch = next(row for row in rows if str(row[1]) == "subject-mismatch-plan")
    rejection = json.loads(str(subject_mismatch[3]))
    assert str(subject_mismatch[0]) == "different-actor"
    assert rejection["principal_id"] == "different-actor"
    assert rejection["proposed_subject_hash"] == _sha("memory-log/v1|actor-1")
    assert "actor-1" not in str(subject_mismatch[3])
    await scoped.close()


@pytest.mark.asyncio
async def test_rejection_reason_and_fingerprint_ignore_sensitive_exception_text_across_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stable-rejection.db"

    def first_fault(point: str) -> None:
        if point == "mutation.after_evidence":
            raise RuntimeError("private-secret-alpha")

    backend, envelope, _receipt, span, authority = await _prepared(path, fault=first_fault)
    with pytest.raises(RuntimeError, match="private-secret-alpha"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    await backend.close()

    def second_fault(point: str) -> None:
        if point == "mutation.after_evidence":
            raise RuntimeError("private-secret-beta")

    reopened = SQLiteHumanMemoryBackend(
        path,
        now=lambda: 30.0,
        fault_injector=second_fault,
        evidence_authority=authority,
        classification_policy=_classification_policy(),
    )
    await reopened.initialize()
    with pytest.raises(RuntimeError, match="private-secret-beta"):
        await reopened.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                envelope,
                _operation(span, operation_id="create-2"),
                plan_id="plan-2",
                idempotency_key="idempotency-2",
            ),
        )
    async with reopened.connection.execute(
        "SELECT reason_code,rejection_json FROM memory_mutation_rejection_audits "
        "ORDER BY rejected_at"
    ) as cursor:
        rows = tuple(await cursor.fetchall())
    assert len(rows) == 2
    decoded = [json.loads(str(row[1])) for row in rows]
    assert {str(row[0]) for row in rows} == {"mutation_repository_failure"}
    assert len({item["exception_fingerprint"] for item in decoded}) == 1
    assert all("private-secret" not in str(item) for item in decoded)
    await reopened.close()


@pytest.mark.asyncio
async def test_storage_rejection_reason_is_distinct_and_content_free(tmp_path: Path) -> None:
    def fault(point: str) -> None:
        if point == "mutation.after_evidence":
            raise sqlite3.OperationalError("private-storage-detail")

    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "storage-rejection.db", fault=fault
    )
    with pytest.raises(sqlite3.OperationalError, match="private-storage-detail"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    async with backend.connection.execute(
        "SELECT reason_code,rejection_json FROM memory_mutation_rejection_audits"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and str(row[0]) == "mutation_storage_failure"
    assert "private-storage-detail" not in str(row[1])
    await backend.close()


@pytest.mark.asyncio
async def test_rejection_audit_failure_is_exposed_and_not_misreported(
    tmp_path: Path,
) -> None:
    def fault(point: str) -> None:
        if point in {
            "mutation.after_evidence",
            "mutation.rejection_audit.before_commit",
        }:
            raise RuntimeError(point)

    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "rejection-audit-failure.db", fault=fault
    )
    with pytest.raises(MemoryCorruptionError, match="mutation_rejection_audit_failed"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    assert all(value == 0 for value in (await _cognitive_counts(backend)).values())
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM memory_mutation_rejection_audits"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
async def test_cognitive_outbox_identity_is_immutable(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "outbox-immutable.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable outbox identity"):
        await backend.connection.execute(
            "UPDATE outbox SET payload='{}' WHERE topic='memory.cognitive.committed'"
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable outbox"):
        await backend.connection.execute(
            "DELETE FROM outbox WHERE topic='memory.cognitive.committed'"
        )
    await backend.close()


@pytest.mark.asyncio
async def test_concurrent_same_plan_has_one_commit_and_exact_replays(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(tmp_path / "concurrent.db")
    plan = _plan(envelope, _operation(span))

    async def apply_once():
        return await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
        )

    references = await asyncio.gather(*(apply_once() for _ in range(8)))
    assert len(set(references)) == 1
    counts = await _cognitive_counts(backend)
    assert counts["memory_mutation_receipts"] == 1
    assert counts["cognitive_memory_revisions"] == 1
    await backend.close()


@pytest.mark.asyncio
async def test_formal_conversation_registration_drives_task_scope_origin(
    tmp_path: Path,
) -> None:
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    metadata = ConversationEvidenceMetadata(
        metadata_id="conversation-metadata-1",
        authority_issuer_id="host-conversation-registry",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        run_id=envelope.run_id,
        subject=envelope.subject,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        conversation_id="primary-conversation",
        primary_conversation_id="primary-conversation",
        causal_group_id="causal-group-1",
        causal_group_sequence=1,
        item_ordinal=1,
        group_item_count=1,
        ordered_group_manifest_hash="9" * 64,
        role=ConversationEvidenceRole.USER,
        occurred_at=10.0,
        task_scope_id="task-scope-1",
        tool_causal_link=None,
        entities=("user:self",),
    )
    metadata_receipt = ConversationEvidenceMetadataReceipt(
        receipt_id="conversation-metadata-receipt-1",
        metadata_id=metadata.metadata_id,
        authority_issuer_id=metadata.authority_issuer_id,
        evidence_id=metadata.evidence_id,
        envelope_hash=metadata.envelope_hash,
        admission_receipt_id=metadata.admission_receipt_id,
        admission_receipt_hash=metadata.admission_receipt_hash,
        run_id=metadata.run_id,
        subject=metadata.subject,
        source_hash=metadata.source_hash,
        sanitized_hash=metadata.sanitized_hash,
        metadata_hash=metadata.metadata_hash,
        issuer_ref=metadata.authority_issuer_id,
        accepted=True,
    )
    registration = ConversationEvidenceRegistration(
        "conversation-registration-1",
        envelope,
        receipt,
        metadata,
        metadata_receipt,
    )
    reference = ConversationEvidenceRegistrationRef(
        registration.registration_id,
        registration.registration_hash,
        envelope.evidence_id,
        envelope.envelope_hash,
    )

    class _ConversationAuthority:
        async def resolve_conversation_registration(
            self, requested: ConversationEvidenceRegistrationRef
        ) -> ConversationEvidenceRegistration:
            assert requested == reference
            return registration

    backend = SQLiteHumanMemoryBackend(
        tmp_path / "task-scope-origin.db",
        now=lambda: 20.0,
        evidence_authority=_Authority(envelope, receipt, span),
        conversation_evidence_authority=_ConversationAuthority(),
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    assert await backend.register_conversation_evidence(reference) == reference
    assert await backend.register_conversation_evidence(reference) == reference
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT r.task_scope_id,o.task_scope_id,o.evidence_id,o.registration_id "
        "FROM cognitive_memory_revisions r "
        "JOIN cognitive_revision_task_scope_origins o "
        "ON o.memory_id=r.memory_id AND o.revision=r.revision"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert tuple(str(item) for item in row) == (
        "task-scope-1",
        "task-scope-1",
        envelope.evidence_id,
        registration.registration_id,
    )
    await backend.close()


@pytest.mark.asyncio
async def test_verified_external_typed_authority_applies_at_repository(
    tmp_path: Path,
) -> None:
    envelope, receipt = _admitted(source_kind=EvidenceSourceKind.PROVIDER_RECORD)
    typed_receipt = TypedObservationAuthorityReceipt(
        receipt_id="typed-observation-receipt-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        item_ordinal=1,
        item_id="message-1",
        item_json_pointer="/public_text",
        schema_id="observation/provider-preference",
        schema_version=1,
        registered_schema_hash="1" * 64,
        json_pointer="/public_text",
        value_hash=fingerprint_json("user prefers concise answers"),
        accepted=True,
        issuer_ref="provider-observation-authority",
    )
    typed_ref = ProposedTypedObservationRef(
        schema_id=typed_receipt.schema_id,
        schema_version=typed_receipt.schema_version,
        registered_schema_hash=typed_receipt.registered_schema_hash,
        observation_receipt_id=typed_receipt.receipt_id,
        observation_receipt_hash=typed_receipt.receipt_hash,
        authority_issuer_id=typed_receipt.issuer_ref,
        json_pointer=typed_receipt.json_pointer,
        value_hash=typed_receipt.value_hash,
    )
    span = _span(
        envelope,
        receipt,
        actor_role=EvidenceActorRole.EXTERNAL,
        provenance=EvidenceProvenance.EXTERNAL_SOURCE,
        support_kind=EvidenceSupportKind.TYPED_OBSERVATION,
        typed_observation=typed_ref,
    )
    authority = _Authority(envelope, receipt, span, typed_receipt)
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "external-typed.db",
        now=lambda: 20.0,
        evidence_authority=authority,
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    operation = _operation(
        span,
        epistemic_status=EpistemicStatus.VERIFIED_EXTERNAL,
        verification_state=VerificationState.SOURCE_VERIFIED,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, operation),
    )
    async with backend.connection.execute(
        "SELECT observation_receipt_id,observation_receipt_hash,"
        "observation_authority_issuer_id FROM cognitive_evidence_spans"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert tuple(str(item) for item in row) == (
        typed_receipt.receipt_id,
        typed_receipt.receipt_hash,
        typed_receipt.issuer_ref,
    )
    await backend.close()


@pytest.mark.asyncio
async def test_no_mutation_receipt_does_not_advance_head_or_emit_state(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, _span_value, _authority = await _prepared(
        tmp_path / "no-mutation.db"
    )
    plan = MemoryMutationPlan(
            plan_id="no-mutation-plan",
            run_id="run-1",
            turn_id="turn-1",
            subject="actor-1",
        base_revision=1,
        outcome=MemoryMutationPlanOutcome.NO_MUTATION,
        operations=(),
        disclosure_context=_disclosure(),
        evidence_refs=(EvidenceRef(envelope.evidence_id, envelope.envelope_hash, 1),),
        idempotency_key="no-mutation-key",
    )
    reference = await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    receipt = await backend.resolve_memory_mutation_apply_receipt(
        _committed_receipt_ref(reference)
    )
    receipt.validate_plan(plan)
    assert receipt.committed_revision == 1
    counts = await _cognitive_counts(backend)
    assert counts["cognitive_apply_heads"] == 1
    assert counts["cognitive_memory_heads"] == 0
    assert counts["memory_mutation_receipts"] == 1
    assert counts["memory_mutation_decisions"] == 0
    async with backend.connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM outbox WHERE topic='memory.cognitive.committed'"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("memory_type", "payload", "lifecycle", "typed_table"),
    (
        (
            LongTermMemoryType.EPISODE,
            EpisodeMemoryPayload(
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
            EpisodeLifecycleState.ACTIVE,
            "episode_records",
        ),
        (
            LongTermMemoryType.SEMANTIC,
            SemanticMemoryPayload("user:self", "style", "concise", ()),
            SemanticLifecycleState.ACTIVE,
            "semantic_claims",
        ),
        (
            LongTermMemoryType.PROCEDURE,
            ProcedureMemoryPayload(
                "release", ("repository",), ("test", "publish"), ProcedureRiskLevel.HIGH
            ),
            ProcedureLifecycleState.ACTIVE,
            "procedure_records",
        ),
        (
            LongTermMemoryType.PROSPECTIVE,
            ProspectiveMemoryPayload(
                "write changelog", ProspectiveTimeTrigger(100.0, "Asia/Shanghai")
            ),
            ProspectiveLifecycleState.PENDING,
            "prospective_records",
        ),
    ),
)
async def test_all_four_cognitive_payloads_materialize_typed_rows(
    tmp_path: Path,
    memory_type: LongTermMemoryType,
    payload: object,
    lifecycle: object,
    typed_table: str,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / f"type-{memory_type.value}.db"
    )
    operation = replace(
        _operation(span),
        memory_type=memory_type,
        payload=payload,
        lifecycle_state=lifecycle,
    )
    plan = _plan(envelope, operation)
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    async with backend.connection.execute(f"SELECT COUNT(*) FROM {typed_table}") as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    await backend.close()


@pytest.mark.asyncio
async def test_hash_conflict_and_stale_apply_head_fail_closed(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(tmp_path / "conflict.db")
    first = _plan(envelope, _operation(span))
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=first
    )
    conflict = _plan(
        envelope,
        replace(_operation(span), reason_code="different_reason"),
        plan_id="different-plan",
        idempotency_key=first.idempotency_key,
    )
    with pytest.raises(MemoryIdempotencyConflict, match="mutation_idempotency_hash_conflict"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=conflict
        )
    stale = _plan(
        envelope,
        replace(_operation(span), operation_id="create-stale"),
        plan_id="stale-plan",
        idempotency_key="stale-key",
    )
    with pytest.raises(MemoryWriterConflict, match="cognitive_apply_head_stale"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=stale
        )
    assert (await _cognitive_counts(backend))["memory_mutation_receipts"] == 1
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits"
    ) as cursor:
        reasons = {str(row[0]) for row in await cursor.fetchall()}
    assert reasons == {"mutation_idempotency_conflict", "mutation_writer_conflict"}
    await backend.close()


@pytest.mark.asyncio
async def test_separate_plans_may_reuse_operation_id_without_identity_collision(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(tmp_path / "operation-scope.db")
    first = _plan(envelope, _operation(span, operation_id="shared-operation"))
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=first
    )
    second = _plan(
        envelope,
        _operation(span, operation_id="shared-operation"),
        base_revision=2,
        plan_id="plan-2",
        idempotency_key="idempotency-2",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=second
    )
    async with backend.connection.execute(
        "SELECT principal_id,plan_id,operation_id FROM cognitive_memory_revisions ORDER BY plan_id"
    ) as cursor:
        rows = await cursor.fetchall()
    assert [tuple(str(item) for item in row) for row in rows] == [
        ("actor-1", "plan-1", "shared-operation"),
        ("actor-1", "plan-2", "shared-operation"),
    ]
    await backend.close()


@pytest.mark.asyncio
async def test_relation_identity_is_scoped_by_principal_plan_and_exact_revisions(
    tmp_path: Path,
) -> None:
    first_envelope, first_receipt = _admitted(subject="actor-1", evidence_id="evidence-actor-1")
    second_envelope, second_receipt = _admitted(subject="actor-2", evidence_id="evidence-actor-2")
    first_span = _span(first_envelope, first_receipt)
    second_span = _span(second_envelope, second_receipt)
    authorities = {
        first_envelope.evidence_id: AdmittedEvidenceAuthority(
            first_envelope, first_receipt, _item_authority(first_span)
        ),
        second_envelope.evidence_id: AdmittedEvidenceAuthority(
            second_envelope, second_receipt, _item_authority(second_span)
        ),
    }

    class _MultiAuthority:
        def __init__(self) -> None:
            self.action_authorities: dict[str, MemoryActionAuthority] = {}

        async def resolve_admitted_evidence(
            self, requested: EvidenceSpanRef
        ) -> AdmittedEvidenceAuthority:
            return authorities[requested.evidence_id]

        async def resolve_typed_observation(
            self, reference: ProposedTypedObservationRef
        ) -> TypedObservationAuthorityReceipt:
            raise ValueError("no typed observation is registered")

        async def resolve_memory_action_authority(
            self, reference: MemoryActionAuthorityRef
        ) -> MemoryActionAuthority:
            return self.action_authorities[reference.authority_id]

    multi_authority = _MultiAuthority()
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "relation-identity.db",
        now=lambda: 20.0,
        evidence_authority=multi_authority,
        memory_action_authority=multi_authority,
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(first_envelope, first_receipt)
    await backend.ingest_committed_evidence(second_envelope, second_receipt)
    for envelope, span, actor in (
        (first_envelope, first_span, "actor-1"),
        (second_envelope, second_span, "actor-2"),
    ):
        await backend.apply_memory_mutation_plan(
            principal=_principal(actor),
            scope=MemoryScope.personal(actor),
            plan=_plan(
                envelope,
                _operation(span, operation_id="create-shared"),
                plan_id="create-plan",
                idempotency_key=f"create-{actor}",
            ),
        )
        async with backend.connection.execute(
            "SELECT memory_id FROM cognitive_memory_heads WHERE principal_id=?",
            (actor,),
        ) as cursor:
            memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
        await backend.apply_memory_mutation_plan(
            principal=_principal(actor),
            scope=MemoryScope.personal(actor),
                plan=_with_action_authorities(
                    _plan(
                        envelope,
                        _operation(
                            span,
                            operation_id="relation-shared",
                            kind=MemoryMutationKind.REVISE,
                            target=ExistingMemoryTarget(memory_id, 1),
                        ),
                        base_revision=2,
                        plan_id="relation-plan",
                        idempotency_key=f"relation-{actor}",
                    ),
                    multi_authority,
                    nonce_prefix=f"relation-{actor}",
                ),
        )
        if actor == "actor-1":
            await backend.apply_memory_mutation_plan(
                principal=_principal(actor),
                scope=MemoryScope.personal(actor),
                    plan=_with_action_authorities(
                        _plan(
                            envelope,
                            _operation(
                                span,
                                operation_id="relation-shared",
                                kind=MemoryMutationKind.REVISE,
                                target=ExistingMemoryTarget(memory_id, 2),
                            ),
                            base_revision=3,
                            plan_id="relation-plan-2",
                            idempotency_key="relation-actor-1-2",
                        ),
                        multi_authority,
                        nonce_prefix="relation-actor-1-2",
                    ),
            )
    async with backend.connection.execute(
        "SELECT principal_id,plan_id,operation_id,source_revision,target_revision "
        "FROM cognitive_relations ORDER BY principal_id,plan_id"
    ) as cursor:
        rows = [tuple(row) for row in await cursor.fetchall()]
    assert rows == [
        ("actor-1", "relation-plan", "relation-shared", 2, 1),
        ("actor-1", "relation-plan-2", "relation-shared", 3, 2),
        ("actor-2", "relation-plan", "relation-shared", 2, 1),
    ]
    await backend.close()


@pytest.mark.asyncio
async def test_supersede_and_contest_relations_use_plan_scoped_identity(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(tmp_path / "relation-kinds.db")
    correction = replace(
        span,
        support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
    )
    authority.admitted = AdmittedEvidenceAuthority(envelope, _receipt, _item_authority(correction))
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope,
            _operation(correction, operation_id="semantic-create"),
            plan_id="semantic-create-plan",
            idempotency_key="semantic-create-key",
        ),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads WHERE memory_type='semantic'"
    ) as cursor:
        semantic_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    supersede = replace(
        _operation(correction, operation_id="relation-action"),
        kind=MemoryMutationKind.SUPERSEDE,
        target=ExistingMemoryTarget(semantic_id, 1),
        lifecycle_state=SemanticLifecycleState.SUPERSEDED,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_with_action_authorities(
            _plan(
                envelope,
                supersede,
                base_revision=2,
                plan_id="supersede-plan",
                idempotency_key="supersede-key",
            ),
            authority,
            nonce_prefix="supersede",
        ),
    )
    episode_create = replace(
        _operation(correction, operation_id="episode-create"),
        memory_type=LongTermMemoryType.EPISODE,
        payload=EpisodeMemoryPayload(
            "decision", ("user:self",), ("ship",), (), (), (), 10.0, 11.0, "thread-1"
        ),
        lifecycle_state=EpisodeLifecycleState.ACTIVE,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope,
            episode_create,
            base_revision=3,
            plan_id="episode-create-plan",
            idempotency_key="episode-create-key",
        ),
    )
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads WHERE memory_type='episode'"
    ) as cursor:
        episode_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = replace(
        _span(challenger_envelope, challenger_receipt),
        support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
    )
    authority.register_admitted(
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        episode_create,
        operation_id="relation-action",
        kind=MemoryMutationKind.CONTEST,
        target=ExistingMemoryTarget(episode_id, 1),
        payload=EpisodeMemoryPayload(
            "different decision",
            ("user:self",),
            ("do not ship",),
            (),
            (),
            (),
            10.0,
            11.0,
            "thread-1",
        ),
        lifecycle_state=EpisodeLifecycleState.ACTIVE,
        conflict_status=ConflictStatus.CONTESTED,
        evidence_spans=(challenger_span,),
        reason_code="explicit_user_correction",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            challenger_envelope,
            contest,
            base_revision=4,
            plan_id="contest-plan",
            idempotency_key="contest-key",
        ),
    )
    async with backend.connection.execute(
        "SELECT plan_id,operation_id,relation_kind FROM cognitive_relations ORDER BY plan_id"
    ) as cursor:
        rows = [tuple(str(item) for item in row) for row in await cursor.fetchall()]
    assert rows == [
        ("contest-plan", "relation-action", "contests"),
        ("supersede-plan", "relation-action", "supersedes"),
    ]
    await backend.close()


@pytest.mark.asyncio
async def test_stale_target_rejects_and_target_privacy_attributes_join_upward(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(tmp_path / "target.db")
    create = _operation(
        span,
        privacy=PrivacyClass.RESTRICTED,
        attributes=(InformationAttribute.HEALTH,),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, create),
    )
    async with backend.connection.execute("SELECT memory_id FROM cognitive_memory_heads") as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    stale = _operation(
        span,
        operation_id="revise-stale",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 99),
    )
    with pytest.raises(MemoryWriterConflict, match="cognitive_target_revision_stale"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                envelope,
                stale,
                base_revision=2,
                plan_id="stale-target",
                idempotency_key="stale-target-key",
            ),
        )
    revise = replace(
        stale,
        operation_id="revise-good",
        target=ExistingMemoryTarget(memory_id, 1),
        proposed_privacy_class=PrivacyClass.PUBLIC,
        proposed_information_attributes=(InformationAttribute.PREFERENCE,),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_with_action_authorities(
            _plan(
                envelope,
                revise,
                base_revision=2,
                plan_id="revise-plan",
                idempotency_key="revise-key",
            ),
            authority,
        ),
    )
    async with backend.connection.execute(
        "SELECT effective_privacy_class,information_attributes_json "
        "FROM cognitive_memory_revisions WHERE memory_id=? AND revision=2",
        (memory_id,),
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert str(row[0]) == "restricted"
    assert str(row[1]) == '["health","preference"]'
    await backend.close()


@pytest.mark.asyncio
async def test_suppress_without_payload_still_checks_target_payload_entities(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "target-entity-suppression.db"
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute("SELECT memory_id FROM cognitive_memory_heads") as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    await backend.suppress(
        SuppressionRequest(
            "suppress-old-entity",
            "actor-1",
            SuppressionScopeKind.ENTITY,
            "user:self",
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.MUTATION,
        )
    )
    correction_span = replace(span, support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION)
    suppress_operation = replace(
        _operation(correction_span),
        kind=MemoryMutationKind.SUPPRESS,
        payload=None,
        target=ExistingMemoryTarget(memory_id, 1),
        lifecycle_state=SemanticLifecycleState.FORGOTTEN,
        reason_code="explicit_user_forget",
    )
    with pytest.raises(SuppressionDenied):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_with_action_authorities(
                _plan(
                    envelope,
                    suppress_operation,
                    base_revision=2,
                    plan_id="forget-plan",
                    idempotency_key="forget-key",
                ),
                authority,
            ),
        )
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    assert (await _cognitive_counts(backend))["memory_mutation_receipts"] == 1
    await backend.close()


@pytest.mark.asyncio
async def test_forward_dependency_materializes_in_topological_order(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(tmp_path / "forward.db")
    create = _operation(span, operation_id="create-forward")
    dependent_create = _operation(
        span,
        operation_id="create-dependent",
        depends_on=("create-forward",),
    )
    plan = _plan(envelope, dependent_create, create)
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads"
    ) as cursor:
        assert [int(row[0]) for row in await cursor.fetchall()] == [1, 1]
    async with backend.connection.execute(
        "SELECT operation_id,before_ref,after_ref FROM memory_mutation_decisions "
        "ORDER BY operation_id"
    ) as cursor:
        rows = await cursor.fetchall()
    by_operation = {str(row[0]): (row[1], str(row[2])) for row in rows}
    assert by_operation["create-forward"][0] is None
    assert by_operation["create-forward"][1].endswith("@1")
    assert by_operation["create-dependent"][0] is None
    assert by_operation["create-dependent"][1].endswith("@1")
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault_point",
    tuple(point for point in COGNITIVE_MUTATION_FAULT_POINTS if point != "mutation.after_commit"),
)
async def test_every_precommit_fault_rolls_back_all_cognitive_rows(
    tmp_path: Path, fault_point: str
) -> None:
    def fault(point: str) -> None:
        if point == fault_point:
            raise RuntimeError(point)

    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / f"fault-{fault_point.replace('.', '-')}.db", fault=fault
    )
    with pytest.raises(RuntimeError, match=fault_point):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
    assert all(value == 0 for value in (await _cognitive_counts(backend)).values())
    await backend.close()


@pytest.mark.asyncio
async def test_after_commit_fault_is_recoverable_by_exact_idempotent_replay(
    tmp_path: Path,
) -> None:
    raised = False

    def fault(point: str) -> None:
        nonlocal raised
        if point == "mutation.after_commit" and not raised:
            raised = True
            raise RuntimeError(point)

    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "after-commit.db", fault=fault
    )
    plan = _plan(envelope, _operation(span))
    with pytest.raises(RuntimeError, match="mutation.after_commit"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
        )
    await backend.close()
    reopened = SQLiteHumanMemoryBackend(
        tmp_path / "after-commit.db",
        evidence_authority=_authority,
        classification_policy=_classification_policy(),
    )
    await reopened.initialize()
    reference = await reopened.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    (
        await reopened.resolve_memory_mutation_apply_receipt(
            _committed_receipt_ref(reference)
        )
    ).validate_plan(plan)
    assert (await _cognitive_counts(reopened))["memory_mutation_receipts"] == 1
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM outbox WHERE topic='memory.cognitive.committed'"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # type: ignore[index]
    await reopened.close()


@pytest.mark.asyncio
async def test_second_operation_fault_rolls_back_first_operation(tmp_path: Path) -> None:
    operation_count = 0

    def fault(point: str) -> None:
        nonlocal operation_count
        if point == "mutation.after_operation":
            operation_count += 1
            if operation_count == 2:
                raise RuntimeError("late-operation-fault")

    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "late.db", fault=fault
    )
    create = _operation(span, operation_id="create-late")
    dependent_create = _operation(
        span,
        operation_id="create-late-dependent",
        depends_on=("create-late",),
    )
    with pytest.raises(RuntimeError, match="late-operation-fault"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, create, dependent_create),
        )
    assert all(value == 0 for value in (await _cognitive_counts(backend)).values())
    await backend.close()


@pytest.mark.asyncio
async def test_forged_authority_and_mutation_suppression_fail_before_state(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(tmp_path / "authority.db")
    forged_span = replace(span, admission_receipt_hash="f" * 64)
    forged = _plan(envelope, replace(_operation(span), evidence_spans=(forged_span,)))
    with pytest.raises(MemoryValidationError, match="evidence_authority_rejected"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=forged
        )
    assert all(value == 0 for value in (await _cognitive_counts(backend)).values())
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits"
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "mutation_evidence_authority_rejected"  # type: ignore[index]

    await backend.suppress(
        SuppressionRequest(
            "mutation-suppression",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            envelope.evidence_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.MUTATION,
        )
    )
    with pytest.raises(SuppressionDenied):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(
                envelope,
                _operation(span),
                plan_id="suppressed-plan",
                idempotency_key="suppressed-key",
            ),
        )
    assert all(value == 0 for value in (await _cognitive_counts(backend)).values())
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits WHERE plan_id='suppressed-plan'"
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "mutation_suppression_rejected"  # type: ignore[index]
    await backend.close()
