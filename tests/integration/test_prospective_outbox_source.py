"""Public source facts over genuine mutation/outbox persistence, not signal grants."""
import asyncio
import hashlib
import sqlite3
from dataclasses import replace

import pytest
import pytest_asyncio
import simple_harness_memory as m
from simple_harness.runtime import (
    ExistingMemoryTarget, MemoryMutationKind, ProspectiveLifecycleState as State,
    ProspectiveMemoryPayload, ProspectiveTimeTrigger, ProspectiveSignalKind as Signal,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError, MemoryLimitError, MemoryOwnershipConflict, MemoryValidationError,
)
from simple_harness_memory.core.lifecycle_results import LifecycleApplyOutcome
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted, _span, _Authority, _classification_policy, _plan, _principal,
    _with_action_authorities,
)
from tests.integration.test_prospective_signal_repository_v5 import (
    _operation, _ProspectiveAuthority, _grant,
)

PRINCIPAL = _principal()
SCOPE = m.MemoryScope.personal(PRINCIPAL.actor_id)


@pytest_asyncio.fixture
async def world(tmp_path):
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _ProspectiveAuthority(_Authority(envelope, receipt, span))
    clock = [20.0]
    kwargs = dict(clock=lambda: clock[0], evidence_authority=authority,
        memory_action_authority=authority, prospective_signal_authority=authority,
        classification_policy=_classification_policy())
    path = tmp_path / 'memory.db'
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        await manager.ingest_committed_evidence(envelope, receipt)
        plan = _plan(envelope, _operation(span))
        result = await manager.apply_memory_mutation_plan(principal=PRINCIPAL, scope=SCOPE, plan=plan)
        assert result.receipt_ref is not None
        view = await manager.get_memory_mutation_receipt_view(principal=PRINCIPAL, receipt_ref=result.receipt_ref)
        entries = await manager.read_outbox(principal=PRINCIPAL)
        entry = next(e for e in entries if e.topic == 'memory.prospective.registration.requested')
        yield dict(manager=manager, path=path, kwargs=kwargs, clock=clock, authority=authority,
            envelope=envelope, span=span, plan=plan, ref=result.receipt_ref,
            memory_id=view.operations[0].memory_id, entry=entry)
    finally:
        await manager.close()


async def read(w, entry=None, **changes):
    entry = entry or w['entry']
    args = dict(principal=PRINCIPAL, outbox_id=entry.outbox_id, payload_hash=entry.payload_hash)
    args.update(changes)
    return await w['manager'].read_prospective_outbox_source(**args)


async def revise(w):
    op = replace(_operation(w['span']), operation_id='reschedule-op', kind=MemoryMutationKind.REVISE,
        target=ExistingMemoryTarget(w['memory_id'], 1),
        payload=ProspectiveMemoryPayload('send report later', ProspectiveTimeTrigger(40.0, 'Asia/Shanghai')),
        lifecycle_state=State.RESCHEDULED)
    plan = replace(_plan(w['envelope'], op, base_revision=2, plan_id='reschedule-plan',
        idempotency_key='reschedule-key'), run_id='run-2', turn_id='turn-2')
    plan = _with_action_authorities(plan, w['authority'].evidence)
    result = await w['manager'].apply_memory_mutation_plan(principal=PRINCIPAL, scope=SCOPE, plan=plan)
    assert result.receipt_ref is not None
    entries = await w['manager'].read_outbox(principal=PRINCIPAL)
    return next(e for e in entries if e.topic == 'memory.prospective.invalidation.requested'), plan


async def test_public_exact_source_reopen_read_only(world):
    w = world
    before = await w['manager'].read_outbox(principal=PRINCIPAL)
    source = await read(w)
    assert isinstance(source, m.ProspectiveOutboxSourceView)
    assert source.subject == PRINCIPAL.actor_id and source.target_scope == SCOPE
    assert source.target_run_id == w['plan'].run_id
    assert source.target_plan_hash == w['plan'].plan_hash
    assert source.target_operation_id == w['plan'].operations[0].operation_id
    assert source.target_operation_kind == 'create'
    assert source.target_mutation_receipt_ref == w['ref']
    assert source.target_memory_id == w['memory_id'] and source.target_revision == 1
    assert source.target_task_scope_id is None
    assert source.target_lifecycle_state == State.PENDING
    assert source.trigger == ProspectiveTimeTrigger(30.0, 'Asia/Shanghai')
    assert source.outbox_cause_status == 'not_persisted'
    assert 'grant' not in source.to_json() and 'source_hash' not in source.to_json()
    assert len(source.source_hash) == 64
    assert await w['manager'].read_outbox(principal=PRINCIPAL) == before
    assert w['authority'].resolutions == 0
    await w['manager'].close()
    w['clock'][0] = 400.0
    w['manager'] = await m.build_human_memory_v7(w['path'], **w['kwargs'])
    try:
        reopened = await read(w, principal=replace(PRINCIPAL, session_id='reopened'))
        assert reopened == source and reopened.source_hash == source.source_hash
    finally:
        await w['manager'].close()


async def test_historical_invalidation_preserves_old_run_state_and_requires_registration(world):
    w = world
    original = await read(w)
    invalidation, new_plan = await revise(w)
    old = await read(w, invalidation)
    assert old.command == 'invalidation'
    assert old.target_revision == old.registration_revision == 1
    assert old.target_lifecycle_state == State.PENDING
    assert old.target_run_id == original.target_run_id != new_plan.run_id
    assert old.target_operation_id == original.target_operation_id
    assert old.target_mutation_receipt_ref == original.target_mutation_receipt_ref
    registrations = [e for e in await w['manager'].read_outbox(principal=PRINCIPAL)
        if e.topic == 'memory.prospective.registration.requested' and e.outbox_id != w['entry'].outbox_id]
    new = await read(w, registrations[0])
    assert new.target_lifecycle_state == State.RESCHEDULED and new.target_run_id == 'run-2'
    assert new.target_revision == 2
    rejected = _grant(w['authority'], memory_id=w['memory_id'], revision=1,
        kind=Signal.REGISTRATION_INVALIDATED, transition_from=old.target_lifecycle_state,
        transition_to=old.target_lifecycle_state, observed_at=20.0,
        outbox_id=invalidation.outbox_id, outbox_hash=invalidation.payload_hash)
    with pytest.raises(MemoryValidationError, match='registration_not_live'):
        await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=rejected)
    accepted = _grant(w['authority'], memory_id=w['memory_id'], revision=1,
        kind=Signal.REGISTRATION_ACCEPTED, transition_from=State.PENDING, transition_to=State.PENDING,
        observed_at=20.0, outbox_id=w['entry'].outbox_id, outbox_hash=w['entry'].payload_hash)
    ack = await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=accepted)
    assert ack.outcome == LifecycleApplyOutcome.ACKNOWLEDGED
    ack = await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=rejected)
    assert ack.outcome == LifecycleApplyOutcome.ACKNOWLEDGED
    assert await read(w, invalidation) == old


@pytest.mark.parametrize('field', ['actor_id', 'deployment_id', 'household_id'])
async def test_foreign_identity_rejected(world, field):
    with pytest.raises(MemoryOwnershipConflict):
        await read(world, principal=replace(PRINCIPAL, **{field: 'foreign'}))


@pytest.mark.parametrize('changes', [dict(payload_hash='0'*64), dict(outbox_id='missing'),
    dict(outbox_id='bad\x00id'), dict(outbox_id='x'*1025), dict(payload_hash='bad')])
async def test_exact_args_no_fallback(world, changes):
    with pytest.raises(MemoryValidationError):
        await read(world, **changes)


@pytest.mark.parametrize('sql', [
    "UPDATE outbox SET topic='memory.prospective.invalidation.requested' WHERE topic='memory.prospective.registration.requested'",
    "DROP TRIGGER cognitive_memory_revisions_immutable_update; UPDATE cognitive_memory_revisions SET content_hash='bad'",
    "DROP TRIGGER memory_mutation_receipts_immutable_update; UPDATE memory_mutation_receipts SET run_id='other-run'",
    "DROP TRIGGER memory_mutation_decisions_immutable_update; UPDATE memory_mutation_decisions SET decision_hash='bad'",
])
async def test_persisted_corruption_rejected(world, sql):
    # SDK-owned test DB fault injection only; public Host never performs SQL.
    with sqlite3.connect(world['path']) as db:
        db.executescript(sql)
    with pytest.raises(MemoryCorruptionError):
        await read(world)


async def test_sql_budget_failure_and_cancel_release_connection(world, monkeypatch):
    from simple_harness_memory.backends import prospective_sources as module
    monkeypatch.setattr(module, 'MAX_SQL_STEPS', 1)
    with pytest.raises(MemoryLimitError, match='sql_budget'):
        await read(world)
    monkeypatch.setattr(module, 'MAX_SQL_STEPS', 200_000)
    original = module._read
    entered = asyncio.Event()
    async def slow(*args):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(module, '_read', slow)
    task = asyncio.create_task(read(world))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(module, '_read', original)
    assert (await read(world)).target_revision == 1


async def test_wire_budget_rejects_without_mutation(world, monkeypatch):
    from simple_harness_memory.backends import prospective_sources as module
    monkeypatch.setattr(module, 'MAX_WIRE_BYTES', 16)
    with pytest.raises(MemoryLimitError):
        await read(world)


async def test_signal_derived_target_has_no_invented_mutation_source(world):
    w = world
    accepted = _grant(w['authority'], memory_id=w['memory_id'], revision=1,
        kind=Signal.REGISTRATION_ACCEPTED, transition_from=State.PENDING, transition_to=State.PENDING,
        observed_at=20.0, outbox_id=w['entry'].outbox_id, outbox_hash=w['entry'].payload_hash)
    await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=accepted)
    w['clock'][0] = 30.0
    due = _grant(w['authority'], memory_id=w['memory_id'], revision=1, kind=Signal.TIME_DUE,
        transition_from=State.PENDING, transition_to=State.TRIGGERED, observed_at=30.0)
    result = await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=due)
    assert result.committed_revision == 2
    expired = _grant(w['authority'], memory_id=w['memory_id'], revision=2, kind=Signal.EXPIRED,
        transition_from=State.TRIGGERED, transition_to=State.EXPIRED, observed_at=30.0)
    await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=expired)
    entries = await w['manager'].read_outbox(principal=PRINCIPAL)
    invalidation = next(e for e in entries if e.topic == 'memory.prospective.invalidation.requested'
        and e.payload['prospective_revision'] == 2)
    with pytest.raises(MemoryValidationError, match='prospective_target_mutation_source_unavailable'):
        await read(w, invalidation)
