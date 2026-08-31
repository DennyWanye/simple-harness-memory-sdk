from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    ConflictStatus,
    EpistemicStatus,
    EvidenceSpanRef,
    ExistingMemoryTarget,
    InformationAttribute,
    LongTermMemoryType,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryScopeRef,
    PrivacyClass,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveSignalAuthority,
    ProspectiveSignalAuthorityRef,
    ProspectiveSignalIntent,
    ProspectiveSignalKind,
    ProspectiveTimeTrigger,
    ValidTimeInterval,
    VerificationState,
    issue_prospective_signal_authority,
)

from simple_harness_memory.backends.sqlite_v5 import (
    PROSPECTIVE_SIGNAL_FAULT_POINTS,
    SQLiteHumanMemoryBackend,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryOwnershipConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.lifecycle_results import LifecycleApplyOutcome
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _Authority,
    _plan,
    _prepared,
    _principal,
    _with_action_authorities,
)


class _ProspectiveAuthority:
    def __init__(self, evidence: _Authority) -> None:
        self.evidence = evidence
        self.signals: dict[str, ProspectiveSignalAuthority] = {}
        self.resolutions = 0

    async def resolve_admitted_evidence(self, span: EvidenceSpanRef):
        return await self.evidence.resolve_admitted_evidence(span)

    async def resolve_typed_observation(self, reference):
        return await self.evidence.resolve_typed_observation(reference)

    async def resolve_memory_action_authority(self, reference):
        return await self.evidence.resolve_memory_action_authority(reference)

    async def resolve_prospective_signal_authority(
        self, reference: ProspectiveSignalAuthorityRef
    ) -> ProspectiveSignalAuthority:
        self.resolutions += 1
        return self.signals[reference.authority_id]


def _operation(span: EvidenceSpanRef) -> MemoryMutationOperation:
    return MemoryMutationOperation(
        operation_id="create-prospective",
        kind=MemoryMutationKind.CREATE,
        memory_type=LongTermMemoryType.PROSPECTIVE,
        payload=ProspectiveMemoryPayload(
            "send report", ProspectiveTimeTrigger(30.0, "Asia/Shanghai")
        ),
        target=None,
        depends_on_operation_ids=(),
        lifecycle_state=ProspectiveLifecycleState.PENDING,
        epistemic_status=EpistemicStatus.EXPLICIT_USER,
        conflict_status=ConflictStatus.UNCONTESTED,
        verification_state=VerificationState.SOURCE_BOUND,
        valid_time_interval=ValidTimeInterval(None, None),
        proposed_privacy_class=PrivacyClass.PERSONAL,
        proposed_information_attributes=(InformationAttribute.GOAL,),
        evidence_spans=(span,),
        reason_code="explicit_future_action",
    )


async def _setup(path: Path, clock: list[float]):
    initial, envelope, receipt, span, evidence_authority = await _prepared(
        path.with_suffix(".seed"), now=lambda: clock[0]
    )
    await initial.close()
    authority = _ProspectiveAuthority(evidence_authority)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: clock[0],
        evidence_authority=authority,
        prospective_signal_authority=authority,
        memory_action_authority=authority,
        classification_policy=initial._classification_policy,
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    async with backend.connection.execute(
        "SELECT h.memory_id,h.current_revision,o.outbox_id,o.payload_hash "
        "FROM cognitive_memory_heads h JOIN outbox o ON o.principal_id=h.principal_id "
        "WHERE o.topic='memory.prospective.registration.requested'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return backend, authority, str(row[0]), int(row[1]), str(row[2]), str(row[3])


def _grant(
    authority: _ProspectiveAuthority,
    *,
    memory_id: str,
    revision: int,
    kind: ProspectiveSignalKind,
    transition_from: ProspectiveLifecycleState,
    transition_to: ProspectiveLifecycleState,
    observed_at: float,
    outbox_id: str | None = None,
    outbox_hash: str | None = None,
    signal_id: str | None = None,
    receipt_id: str | None = None,
    scheduler_ref: str = "scheduler-registration-1",
) -> ProspectiveSignalAuthorityRef:
    identity = signal_id or f"signal-{kind.value}-{revision}"
    receipt_id = receipt_id or f"receipt-{kind.value}-{revision}"
    intent = ProspectiveSignalIntent(
        signal_id=identity,
        subject="actor-1",
        scope=MemoryScopeRef.personal("actor-1"),
        target_memory_id=memory_id,
        target_revision=revision,
        signal_kind=kind,
        trigger=ProspectiveTimeTrigger(30.0, "Asia/Shanghai"),
        scheduler_registration_ref=scheduler_ref,
        registration_revision=1,
        signal_receipt_id=receipt_id,
        signal_receipt_hash=hashlib.sha256(receipt_id.encode()).hexdigest(),
        observed_at=observed_at,
        transition_from=transition_from,
        transition_to=transition_to,
        outbox_id=outbox_id,
        outbox_payload_hash=outbox_hash,
        run_id="run-1",
        operation_id=f"operation-{identity}",
    )
    grant = issue_prospective_signal_authority(
        intent,
        authority_id=f"authority-{identity}-{len(authority.signals)}",
        issued_at=10.0,
        expires_at=100.0,
        nonce=f"nonce-{identity}-{len(authority.signals)}",
        issuer_ref="host-prospective-signal:v1",
    )
    authority.signals[grant.authority_id] = grant
    return ProspectiveSignalAuthorityRef.from_authority(grant)


@pytest.mark.asyncio
async def test_prospective_registration_trigger_replay_and_invalidation(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / "prospective.db", clock
    )
    accepted = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    ack = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    assert ack.outcome is LifecycleApplyOutcome.ACKNOWLEDGED
    clock[0] = 30.0
    due = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.TIME_DUE,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.TRIGGERED,
        observed_at=30.0,
        signal_id="due-signal",
        receipt_id="due-receipt",
    )
    applied = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
    )
    assert applied.outcome is LifecycleApplyOutcome.APPLIED
    assert applied.lifecycle_state is ProspectiveLifecycleState.TRIGGERED
    assert applied.committed_revision == 2
    assert await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
    ) == applied
    assert authority.resolutions == 2
    with pytest.raises(MemoryOwnershipConflict, match="replay_binding_differs"):
        await backend.apply_prospective_signal(
            principal=MemoryPrincipal(
                "deployment-2", "household-2", "actor-1", "session-2"
            ),
            scope=MemoryScope.personal("actor-1"),
            reference=due,
        )

    duplicate = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.TIME_DUE,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.TRIGGERED,
        observed_at=30.0,
        signal_id="due-signal",
        receipt_id="due-receipt",
    )
    ignored = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=duplicate
    )
    assert ignored.outcome is LifecycleApplyOutcome.IGNORED
    async with backend.connection.execute(
        "SELECT outbox_id,payload_hash FROM outbox "
        "WHERE topic='memory.prospective.invalidation.requested'"
    ) as cursor:
        invalidation = await cursor.fetchone()
    assert invalidation is not None
    arbitrary = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.REGISTRATION_INVALIDATED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=30.0,
        outbox_id=str(invalidation[0]),
        outbox_hash=str(invalidation[1]),
        scheduler_ref="unaccepted-registration",
        signal_id="invalid-arbitrary-registration",
    )
    with pytest.raises(MemoryValidationError, match="registration_not_live"):
        await backend.apply_prospective_signal(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=arbitrary,
        )
    invalidated = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.REGISTRATION_INVALIDATED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=30.0,
        outbox_id=str(invalidation[0]),
        outbox_hash=str(invalidation[1]),
    )
    invalidation_result = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=invalidated
    )
    assert invalidation_result.outcome is LifecycleApplyOutcome.ACKNOWLEDGED
    await backend.close()


@pytest.mark.asyncio
async def test_prospective_expire_requires_registration_and_never_executes_action(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / "prospective-expire.db", clock
    )
    accepted = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    clock[0] = 40.0
    expired = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.EXPIRED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.EXPIRED,
        observed_at=40.0,
    )
    result = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=expired
    )
    assert result.lifecycle_state is ProspectiveLifecycleState.EXPIRED
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM outbox WHERE topic LIKE '%.action.%'"
    ) as cursor:
        action_rows = await cursor.fetchone()
    assert action_rows is not None and int(action_rows[0]) == 0
    await backend.close()


@pytest.mark.asyncio
async def test_prospective_reschedule_and_cancel_emit_only_scheduler_outbox(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, memory_id, _revision, _outbox_id, _outbox_hash = await _setup(
        tmp_path / "prospective-reschedule.db", clock
    )
    admitted = authority.evidence.admitted
    from tests.integration.test_cognitive_mutation_repository_v5 import _span

    source_span = _span(admitted.envelope, admitted.receipt)
    revise = replace(
        _operation(source_span),
        operation_id="reschedule-prospective",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 1),
        payload=ProspectiveMemoryPayload(
            "send report later", ProspectiveTimeTrigger(40.0, "Asia/Shanghai")
        ),
        lifecycle_state=ProspectiveLifecycleState.RESCHEDULED,
    )
    reschedule_plan = _with_action_authorities(
        _plan(
            admitted.envelope,
            revise,
            base_revision=2,
            plan_id="reschedule-plan",
            idempotency_key="reschedule-key",
        ),
        authority.evidence,
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=reschedule_plan,
    )
    cancel = replace(
        revise,
        operation_id="cancel-prospective",
        kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(memory_id, 2),
        lifecycle_state=ProspectiveLifecycleState.CANCELLED,
    )
    cancel_plan = _with_action_authorities(
        _plan(
            admitted.envelope,
            cancel,
            base_revision=3,
            plan_id="cancel-plan",
            idempotency_key="cancel-key",
        ),
        authority.evidence,
        nonce_prefix="cancel-action",
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), plan=cancel_plan
    )
    async with backend.connection.execute(
        "SELECT topic,COUNT(*) FROM outbox WHERE topic LIKE 'memory.prospective.%' "
        "GROUP BY topic ORDER BY topic"
    ) as cursor:
        rows = await cursor.fetchall()
    assert [(str(row[0]), int(row[1])) for row in rows] == [
        ("memory.prospective.invalidation.requested", 2),
        ("memory.prospective.registration.requested", 2),
    ]
    await backend.close()


@pytest.mark.asyncio
async def test_prospective_ack_rejects_wrong_lifecycle_and_tampered_outbox(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / "prospective-invalid-ack.db", clock
    )
    wrong_state = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.RESCHEDULED,
        transition_to=ProspectiveLifecycleState.RESCHEDULED,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    with pytest.raises(MemoryValidationError, match="lifecycle_differs"):
        await backend.apply_prospective_signal(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=wrong_state,
        )
    async with backend.connection.execute(
        "SELECT payload FROM outbox WHERE outbox_id=?", (outbox_id,)
    ) as cursor:
        original_payload_row = await cursor.fetchone()
    assert original_payload_row is not None
    async with backend.connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='outbox_identity_immutable_update'"
    ) as cursor:
        trigger_row = await cursor.fetchone()
    assert trigger_row is not None
    trigger_sql = str(trigger_row[0])
    await backend.connection.execute("DROP TRIGGER outbox_identity_immutable_update")
    await backend.connection.execute(
        "UPDATE outbox SET payload='{}' WHERE outbox_id=?", (outbox_id,)
    )
    valid_shape = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
        signal_id="tampered-outbox",
    )
    with pytest.raises(MemoryValidationError, match="outbox_binding_differs"):
        await backend.apply_prospective_signal(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=valid_shape,
        )
    await backend.connection.execute(
        "UPDATE outbox SET payload=? WHERE outbox_id=?",
        (str(original_payload_row[0]), outbox_id),
    )
    await backend.connection.execute(trigger_sql)
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", PROSPECTIVE_SIGNAL_FAULT_POINTS)
async def test_prospective_faults_are_atomic_or_durably_replayable(
    tmp_path: Path, fault_point: str
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / f"prospective-fault-{fault_point}.db", clock
    )
    accepted = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    clock[0] = 30.0
    due = _grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.TIME_DUE,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.TRIGGERED,
        observed_at=30.0,
        signal_id=f"fault-due-{fault_point}",
    )

    def inject(actual: str) -> None:
        if actual == fault_point:
            raise RuntimeError(fault_point)

    backend._fault_injector = inject
    with pytest.raises(RuntimeError, match=fault_point):
        await backend.apply_prospective_signal(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
        )
    backend._fault_injector = None
    async with backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None
    if fault_point == "prospective.after_commit":
        assert int(head[0]) == 2
        replay = await backend.apply_prospective_signal(
            principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
        )
        assert replay.committed_revision == 2
    else:
        assert int(head[0]) == 1
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM prospective_trigger_events"
        ) as cursor:
            count = await cursor.fetchone()
        assert count is not None and int(count[0]) == 0
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ("registration", "outbox"))
async def test_prospective_audit_chain_tamper_fails_close_and_reopen(
    tmp_path: Path, variant: str
) -> None:
    clock = [20.0]
    path = tmp_path / f"prospective-audit-{variant}.db"
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        path, clock
    )
    accepted = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    if variant == "registration":
        await backend.connection.execute(
            "DROP TRIGGER prospective_scheduler_registrations_immutable_update"
        )
        await backend.connection.execute(
            "UPDATE prospective_scheduler_registrations SET event_hash=?", ("0" * 64,)
        )
        expected = "prospective registration hash"
    else:
        await backend.connection.execute("DROP TRIGGER outbox_identity_immutable_update")
        await backend.connection.execute(
            "UPDATE outbox SET payload_hash=? WHERE outbox_id=?", ("0" * 64, outbox_id)
        )
        expected = "prospective (registration outbox differs|outbox hash)"
    with pytest.raises(MemoryCorruptionError, match=expected):
        await backend.close()
    reopened = SQLiteHumanMemoryBackend(
        path,
        now=lambda: clock[0],
        evidence_authority=authority,
        prospective_signal_authority=authority,
        classification_policy=backend._classification_policy,
    )
    with pytest.raises(MemoryCorruptionError, match=expected):
        await reopened.initialize()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ("rewrite", "delete"))
async def test_prospective_replay_rejects_result_chain_tamper(
    tmp_path: Path, tamper: str
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = await _setup(
        tmp_path / "prospective-replay-rehash.db", clock
    )
    reference = _grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    result = await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=reference
    )
    if tamper == "rewrite":
        forged = replace(result, reason_code="forged_but_rehashed")
        await backend.connection.execute(
            "DROP TRIGGER prospective_signal_results_immutable_update"
        )
        await backend.connection.execute(
            "UPDATE prospective_signal_results SET result_json=?,result_hash=?",
            (canonical_json(forged.to_json()), forged.result_hash),
        )
        expected = "prospective result chain"
    else:
        await backend.connection.execute(
            "DROP TRIGGER prospective_signal_results_immutable_delete"
        )
        await backend.connection.execute("DELETE FROM prospective_signal_results")
        expected = "prospective audit chain cardinality"
    with pytest.raises(MemoryCorruptionError, match=expected):
        await backend.apply_prospective_signal(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            reference=reference,
        )
    with pytest.raises(MemoryCorruptionError, match=expected):
        await backend.close()
