"""New V2 source branches over actual public Memory signal transactions."""
import asyncio
import sqlite3
from dataclasses import replace

import pytest
import simple_harness_memory as m
from simple_harness.runtime import ProspectiveSignalAuthorityRef
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryValidationError, MemoryOwnershipConflict
from simple_harness_memory.core.operation_audit import _hash
from tests.integration.test_prospective_outbox_source import (
    world, read, revise, PRINCIPAL, SCOPE, State, Signal, _grant,
)


async def v2(w, entry=None, **changes):
    entry = entry or w['entry']
    return await w['manager'].read_prospective_outbox_source_v2(
        principal=changes.get('principal', PRINCIPAL), outbox_id=entry.outbox_id,
        payload_hash=changes.get('payload_hash', entry.payload_hash))


async def applied_signal(w):
    accepted = _grant(w['authority'], memory_id=w['memory_id'], revision=1,
        kind=Signal.REGISTRATION_ACCEPTED, transition_from=State.PENDING, transition_to=State.PENDING,
        observed_at=20.0, outbox_id=w['entry'].outbox_id, outbox_hash=w['entry'].payload_hash)
    await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=accepted)
    w['clock'][0] = 30.0
    reference = _grant(w['authority'], memory_id=w['memory_id'], revision=1,
        kind=Signal.TIME_DUE, transition_from=State.PENDING, transition_to=State.TRIGGERED, observed_at=30.0)
    # Separate Host authority fixture identity from the mutation's run/operation.
    authority = w['authority'].signals[reference.authority_id]
    authority = replace(authority, intent=replace(authority.intent,
        run_id='fixture-signal-run', operation_id='fixture-time-due-operation'))
    w['authority'].signals[authority.authority_id] = authority
    reference = ProspectiveSignalAuthorityRef.from_authority(authority)
    result = await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=reference)
    assert result.outcome.value == 'applied' and result.committed_revision == 2
    await revise(w, target_revision=2)
    entries = (await w['manager'].read_outbox(principal=PRINCIPAL)).entries
    invalidation = next(e for e in entries if e.topic == 'memory.prospective.invalidation.requested'
        and e.payload['prospective_revision'] == 2)
    return invalidation, reference, authority, result


async def test_v2_mutation_union_and_metadata_domains_without_v1_drift(world):
    old = await read(world)
    new = await v2(world)
    assert type(new) is m.ProspectiveOutboxSourceViewV2
    assert type(new.target_source) is m.MutationTargetSource
    assert new.target_source.mutation_receipt_ref == old.target_mutation_receipt_ref
    assert new.target_source.run_id == old.target_run_id
    assert new.source_hash != old.source_hash
    again = await read(world)
    assert again.to_json() == old.to_json() and again.source_hash == old.source_hash
    observation = new.operation_observation
    assert type(observation) is m.ProspectiveSourceReadObservationV2
    assert observation.operation == 'read_prospective_outbox_source_v2'
    assert observation.request_hash == _hash('memory.prospective.source.request.v2',
        [world['entry'].outbox_id, world['entry'].payload_hash])
    assert observation.claimed_owner_ref_hash == old.operation_observation.claimed_owner_ref_hash
    assert observation.request_hash != old.operation_observation.request_hash
    assert observation.observation_hash == _hash('memory.prospective.source.observation.v2', observation.to_json())
    with pytest.raises(MemoryValidationError) as denied:
        await v2(world, payload_hash='0'*64)
    assert denied.value.operation_observation.operation == observation.operation


async def test_signal_source_actual_result_historical_reopen_and_lost_ack(world):
    w = world
    entry, reference, authority, result = await applied_signal(w)
    with pytest.raises(MemoryValidationError, match='prospective_target_mutation_source_unavailable'):
        await read(w, entry)
    source = await v2(w, entry)
    origin = source.target_source
    assert type(origin) is m.ProspectiveSignalTargetSource
    assert origin.apply_result == result
    assert origin.apply_result.result_id != w['ref'].receipt_id
    assert origin.apply_result.result_id != origin.upstream_signal_receipt_id
    assert origin.run_id == authority.intent.run_id != w['plan'].run_id
    assert origin.operation_id == authority.intent.operation_id
    assert origin.authority_hash == authority.authority_hash
    assert origin.upstream_signal_receipt_hash == authority.intent.signal_receipt_hash
    assert source.target_revision == 2 and source.target_lifecycle_state == State.TRIGGERED
    assert source.outbox_cause_status == 'not_persisted'
    assert not hasattr(origin, 'mutation_receipt_ref') and not hasattr(origin, 'plan_id')
    assert 'operation_observation' not in source.to_json()
    await w['manager'].close()
    w['clock'][0] = authority.expires_at + 100
    w['manager'] = await m.build_human_memory_v7(w['path'], **(w['kwargs'] | {'prospective_signal_authority': None}))
    try:
        reopened = await v2(w, entry)
        assert reopened == source and reopened.source_hash == source.source_hash
        # Public same-ref replay comes before new authority/expiry checks, with no resolver.
        replay = await w['manager'].apply_prospective_signal(principal=PRINCIPAL, scope=SCOPE, reference=reference)
        assert replay == result
    finally:
        await w['manager'].close()


@pytest.mark.parametrize('table,column', [
    ('prospective_signal_authority_consumptions', 'consumption_hash'),
    ('prospective_signal_decisions', 'decision_hash'),
    ('prospective_signal_results', 'result_hash'),
    ('prospective_trigger_events', 'event_hash'),
])
async def test_signal_source_rejects_actual_chain_tamper(world, table, column):
    entry, reference, authority, result = await applied_signal(world)
    with sqlite3.connect(world['path']) as db:
        db.execute(f'DROP TRIGGER {table}_immutable_update')
        # Only the TIME_DUE producer row, not registration ACK's separate consumption.
        cid, = db.execute('SELECT consumption_id FROM prospective_signal_authority_consumptions WHERE authority_id=?',
            (authority.authority_id,)).fetchone()
        db.execute(f'UPDATE {table} SET {column}=? WHERE consumption_id=?', ('0'*64, cid))
    with pytest.raises(MemoryCorruptionError) as corrupt:
        await v2(world, entry)
    assert corrupt.value.operation_observation.operation == 'read_prospective_outbox_source_v2'
    assert corrupt.value.operation_observation.reason == 'source_corrupt'
    # The intentionally damaged DB must also fail integrity validation on close.
    with pytest.raises(MemoryCorruptionError):
        await world['manager'].close()


async def test_signal_target_wrong_identity_and_trace_rejected(world):
    entry, reference, authority, result = await applied_signal(world)
    with pytest.raises(MemoryOwnershipConflict):
        await v2(world, entry, principal=replace(PRINCIPAL, deployment_id='foreign'))
    with sqlite3.connect(world['path']) as db:
        db.execute('DROP TRIGGER cognitive_memory_revisions_immutable_update')
        db.execute('UPDATE cognitive_memory_revisions SET operation_id=? WHERE memory_id=? AND revision=2',
            ('not-the-signal-operation', world['memory_id']))
    with pytest.raises(MemoryCorruptionError):
        await v2(world, entry)
    with pytest.raises(MemoryCorruptionError):
        await world['manager'].close()


async def test_v2_cancel_observation_and_connection_cleanup(world, monkeypatch):
    from simple_harness_memory.backends import prospective_sources_v2 as module
    original = module._read
    entered = asyncio.Event()
    async def slow(*args):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(module, '_read', slow)
    task = asyncio.create_task(v2(world))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as cancelled:
        await task
    assert cancelled.value.operation_observation.operation == 'read_prospective_outbox_source_v2'
    assert cancelled.value.operation_observation.outcome == 'cancelled'
    monkeypatch.setattr(module, '_read', original)
    assert (await v2(world)).target_source.kind == 'mutation'
