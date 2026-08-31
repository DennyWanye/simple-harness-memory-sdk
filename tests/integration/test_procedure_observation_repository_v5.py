from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.runtime import (
    AdmittedEvidenceAuthority,
    ConflictStatus,
    ConversationEvidenceMetadata,
    ConversationEvidenceMetadataReceipt,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    ConversationEvidenceRole,
    ConversationToolCausalLink,
    EpistemicStatus,
    EvidenceItemAuthority,
    EvidenceSourceKind,
    EvidenceSpanRef,
    ExistingMemoryTarget,
    InformationAttribute,
    LongTermMemoryType,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryScopeRef,
    PrivacyClass,
    ProcedureApplicabilityContext,
    ProcedureHazard,
    ProcedureLifecycleState,
    ProcedureMemoryPayload,
    ProcedureObservationAuthority,
    ProcedureObservationAuthorityRef,
    ProcedureObservationIntent,
    ProcedureObservationKind,
    ProcedureObservationOutcome,
    ProcedureRiskLevel,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    ValidTimeInterval,
    VerificationState,
    issue_procedure_observation_authority,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _plan,
    _principal,
    _sha,
    _span,
    _with_action_authorities,
)

_TASK_BY_INDEX = {1: "task-1", 2: "task-1", 3: "task-2", 4: "task-3", 5: "task-4"}
_TERMINAL_BY_INDEX = {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}


class _LifecycleAuthority(_Authority):
    def __init__(
        self,
        evidence: list[
            tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt, EvidenceSpanRef]
        ],
    ) -> None:
        first_envelope, first_receipt, first_span = evidence[0]
        super().__init__(first_envelope, first_receipt, first_span)
        self._admitted = {
            envelope.evidence_id: AdmittedEvidenceAuthority(
                envelope, receipt, self._item_authority(span)
            )
            for envelope, receipt, span in evidence
        }
        self.registrations: dict[str, ConversationEvidenceRegistration] = {}
        self.procedure: dict[str, ProcedureObservationAuthority] = {}
        self.procedure_resolutions = 0

    @staticmethod
    def _item_authority(span: EvidenceSpanRef) -> EvidenceItemAuthority:
        from tests.integration.test_cognitive_mutation_repository_v5 import _item_authority

        return _item_authority(span)

    async def resolve_admitted_evidence(
        self, span: EvidenceSpanRef
    ) -> AdmittedEvidenceAuthority:
        self.admitted_resolution_count += 1
        return self._admitted[span.evidence_id]

    async def resolve_conversation_registration(
        self, reference: ConversationEvidenceRegistrationRef
    ) -> ConversationEvidenceRegistration:
        return self.registrations[reference.registration_id]

    async def resolve_procedure_observation_authority(
        self, reference: ProcedureObservationAuthorityRef
    ) -> ProcedureObservationAuthority:
        self.procedure_resolutions += 1
        return self.procedure[reference.authority_id]


def _procedure_operation(
    span: EvidenceSpanRef,
    *,
    operation_id: str = "create-procedure",
    kind: MemoryMutationKind = MemoryMutationKind.CREATE,
    target: ExistingMemoryTarget | None = None,
    lifecycle_state: ProcedureLifecycleState = ProcedureLifecycleState.DRAFT,
) -> MemoryMutationOperation:
    return MemoryMutationOperation(
        operation_id=operation_id,
        kind=kind,
        memory_type=LongTermMemoryType.PROCEDURE,
        payload=ProcedureMemoryPayload(
            "publish report", ("workspace",), ("review", "publish"), ProcedureRiskLevel.LOW
        ),
        target=target,
        depends_on_operation_ids=(),
        lifecycle_state=lifecycle_state,
        epistemic_status=EpistemicStatus.EXPLICIT_USER,
        conflict_status=ConflictStatus.UNCONTESTED,
        verification_state=VerificationState.SOURCE_BOUND,
        valid_time_interval=ValidTimeInterval(None, None),
        proposed_privacy_class=PrivacyClass.PERSONAL,
        proposed_information_attributes=(InformationAttribute.WORK,),
        evidence_spans=(span,),
        reason_code="procedure_test",
    )


async def _setup(path: Path, clock: list[float], count: int = 7):
    evidence: list[
        tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt, EvidenceSpanRef]
    ] = []
    for index in range(1, count + 1):
        envelope, receipt = _admitted(
            source_kind=EvidenceSourceKind.TOOL_RESULT,
            evidence_id=f"procedure-evidence-{index}",
        )
        envelope = replace(
            envelope,
            source_ref=f"provider/procedure-{index}",
            source_hash=_sha(f"procedure-source-{index}"),
        )
        receipt = replace(
            receipt,
            envelope_hash=envelope.envelope_hash,
            source_hash=envelope.source_hash,
        )
        evidence.append((envelope, receipt, _span(envelope, receipt)))
    authority = _LifecycleAuthority(evidence)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: clock[0],
        evidence_authority=authority,
        conversation_evidence_authority=authority,
        procedure_observation_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    for index, (envelope, receipt, _span_ref) in enumerate(evidence, start=1):
        await backend.ingest_committed_evidence(envelope, receipt)
        link = ConversationToolCausalLink(
            f"tool-call-{index}",
            "publish",
            1,
            f"terminal-{_TERMINAL_BY_INDEX.get(index, index)}",
            _sha(f"terminal-{_TERMINAL_BY_INDEX.get(index, index)}"),
        )
        metadata = ConversationEvidenceMetadata(
            metadata_id=f"procedure-metadata-{index}",
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
            causal_group_id=f"procedure-group-{index}",
            causal_group_sequence=index,
            item_ordinal=2,
            group_item_count=2,
            ordered_group_manifest_hash=_sha(f"manifest-{index}"),
            role=ConversationEvidenceRole.TOOL,
            occurred_at=10.0,
            task_scope_id=_TASK_BY_INDEX.get(index, f"task-{index}"),
            tool_causal_link=link,
            entities=(),
        )
        metadata_receipt = ConversationEvidenceMetadataReceipt(
            receipt_id=f"procedure-metadata-receipt-{index}",
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
            f"procedure-registration-{index}",
            envelope,
            receipt,
            metadata,
            metadata_receipt,
        )
        authority.registrations[registration.registration_id] = registration
        await backend.register_conversation_evidence(
            ConversationEvidenceRegistrationRef(
                registration.registration_id,
                registration.registration_hash,
                envelope.evidence_id,
                envelope.envelope_hash,
            )
        )
    first_envelope, _first_receipt, first_span = evidence[0]
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(first_envelope, _procedure_operation(first_span)),
    )
    assert result.receipt_ref is not None
    async with backend.connection.execute(
        "SELECT memory_id,current_revision FROM cognitive_memory_heads"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return backend, authority, evidence, str(row[0]), int(row[1])


def _grant(
    authority: _LifecycleAuthority,
    evidence: list[
        tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt, EvidenceSpanRef]
    ],
    *,
    memory_id: str,
    revision: int,
    index: int,
    transition_from: ProcedureLifecycleState,
    transition_to: ProcedureLifecycleState,
    task_scope_id: str | None = None,
    terminal_index: int | None = None,
    attributable: bool = True,
    observed_at: float = 19.0,
) -> ProcedureObservationAuthorityRef:
    terminal_index = (
        _TERMINAL_BY_INDEX.get(index, index)
        if terminal_index is None
        else terminal_index
    )
    span = evidence[index - 1][2]
    intent = ProcedureObservationIntent(
        observation_id=f"observation-{index}-{revision}-{task_scope_id or index}",
        subject="actor-1",
        scope=MemoryScopeRef.personal("actor-1"),
        target_memory_id=memory_id,
        target_revision=revision,
        kind=ProcedureObservationKind.TERMINAL_OUTCOME,
        applicability=ProcedureApplicabilityContext("publish", "macos", "1", "a" * 64),
        risk_level=ProcedureRiskLevel.LOW,
        hazard=ProcedureHazard.NONE,
        task_scope_id=task_scope_id or _TASK_BY_INDEX.get(index, f"task-{index}"),
        evidence_span=span,
        terminal_receipt_id=f"terminal-{terminal_index}",
        terminal_receipt_hash=_sha(f"terminal-{terminal_index}"),
        outcome=ProcedureObservationOutcome.SUCCESS,
        attributable=attributable,
        observed_at=observed_at,
        transition_from=transition_from,
        transition_to=transition_to,
        run_id="run-1",
        operation_id=f"observe-{index}-{revision}",
    )
    grant = issue_procedure_observation_authority(
        intent,
        authority_id=f"procedure-authority-{index}-{revision}-{task_scope_id or index}",
        issued_at=15.0,
        expires_at=10_000_000.0,
        nonce=f"procedure-nonce-{index}-{revision}-{task_scope_id or index}",
        issuer_ref="host-procedure-observation:v1",
    )
    authority.procedure[grant.authority_id] = grant
    return ProcedureObservationAuthorityRef.from_authority(grant)


@pytest.mark.asyncio
async def test_procedure_qualification_epoch_counts_independent_recent_successes(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await _setup(
        tmp_path / "procedure.db", clock
    )
    first = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=revision,
        index=1,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    result = await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=first
    )
    assert result.independent_successes == 1
    assert authority.procedure_resolutions == 1
    assert await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=first
    ) == result
    assert authority.procedure_resolutions == 1

    duplicate_scope = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=2,
        index=2,
        task_scope_id="task-1",
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
    )
    with pytest.raises(MemoryValidationError, match="procedure_observation_replayed"):
        await backend.record_procedure_observation(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=duplicate_scope,
        )

    duplicate_receipt = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=2,
        index=5,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
    )
    with pytest.raises(MemoryValidationError, match="procedure_observation_replayed"):
        await backend.record_procedure_observation(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=duplicate_receipt,
        )

    second = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=2,
        index=3,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
    )
    second_result = await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=second
    )
    assert second_result.independent_successes == 2
    third = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=3,
        index=4,
        transition_from=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
        transition_to=ProcedureLifecycleState.ACTIVE,
    )
    third_result = await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=third
    )
    assert third_result.lifecycle_state is ProcedureLifecycleState.ACTIVE
    assert third_result.independent_successes == 3
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(DISTINCT qualification_epoch) FROM procedure_records),"
        "p.bound_hazard FROM procedure_records p JOIN cognitive_memory_heads h "
        "ON h.memory_id=p.memory_id AND h.current_revision=p.revision"
    ) as cursor:
        epoch_row = await cursor.fetchone()
    assert epoch_row is not None and tuple(epoch_row) == (1, "none")
    await backend.close()


@pytest.mark.asyncio
async def test_procedure_window_non_attributable_future_and_new_epoch(
    tmp_path: Path,
) -> None:
    clock = [100.0 * 24.0 * 60.0 * 60.0]
    backend, authority, evidence, memory_id, _revision = await _setup(
        tmp_path / "procedure-window.db", clock
    )
    old = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=1,
        index=1,
        observed_at=clock[0] - 91.0 * 24.0 * 60.0 * 60.0,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    old_result = await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=old
    )
    assert old_result.independent_successes == 0
    non_attributable = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=2,
        index=2,
        attributable=False,
        observed_at=clock[0],
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    non_result = await backend.record_procedure_observation(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        reference=non_attributable,
    )
    assert non_result.independent_successes == 0
    future = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=3,
        index=3,
        observed_at=clock[0] + 1.0,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    with pytest.raises(MemoryValidationError, match="occurred_at_future"):
        await backend.record_procedure_observation(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=future,
        )

    revise = _procedure_operation(
        evidence[3][2],
        operation_id="revise-procedure",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 3),
        lifecycle_state=ProcedureLifecycleState.REVISED,
    )
    plan = _with_action_authorities(
        _plan(
            evidence[3][0],
            revise,
            base_revision=2,
            plan_id="revise-procedure-plan",
            idempotency_key="revise-procedure-key",
        ),
        authority,
        issued_at=clock[0] - 1.0,
        expires_at=clock[0] + 10.0,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=plan
    )
    redraft = _procedure_operation(
        evidence[4][2],
        operation_id="redraft-procedure",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 4),
    )
    redraft_plan = _with_action_authorities(
        _plan(
            evidence[4][0],
            redraft,
            base_revision=3,
            plan_id="redraft-procedure-plan",
            idempotency_key="redraft-procedure-key",
        ),
        authority,
        issued_at=clock[0] - 1.0,
        expires_at=clock[0] + 10.0,
        nonce_prefix="redraft-action",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=redraft_plan
    )
    async with backend.connection.execute(
        "SELECT COUNT(DISTINCT qualification_epoch) FROM procedure_records"
    ) as cursor:
        epochs = await cursor.fetchone()
    assert epochs is not None and int(epochs[0]) == 3
    fresh = _grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=5,
        index=6,
        observed_at=clock[0],
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    fresh_result = await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=fresh
    )
    assert fresh_result.independent_successes == 1
    await backend.close()
