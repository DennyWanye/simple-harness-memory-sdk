"""Only settlement/schema successor risks, using real public mutation/signal calls."""
import asyncio
import hashlib
import sqlite3
from dataclasses import replace

import pytest
import simple_harness_memory as m
from simple_harness_memory.backends import schema_v5 as old_schema, schema_v7_3, sqlite_v5
from simple_harness_memory.migrations import schema_upgrade as old_upgrade, settlement_upgrade as upgrade
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryValidationError, MemoryLegacySchemaUnsupported, MemoryOwnershipConflict
from simple_harness_memory.core.operation_audit import _hash
from tests.integration.test_prospective_outbox_source import world, revise, PRINCIPAL, SCOPE, State, Signal, _grant
from tests.integration.test_prospective_signal_source_v2 import applied_signal


async def legacy_case(tmp_path,monkeypatch):
    # Reproduce the frozen 7.2 schema/initializer contract with public operations.
    # This is a source fixture, not an installed-M616 or Host test.
    with monkeypatch.context() as patch:
        for key in ('REQUIRED_TABLES','SCHEMA_CHECKSUM','SCHEMA_VERSION_LABEL','InitializationReceipt'):
            patch.setattr(sqlite_v5,key,getattr(old_schema,key))
        patch.setattr(sqlite_v5,'_DDL',old_schema.ddl_statements())
        patch.setattr(upgrade,'probe_existing_root',old_upgrade.probe_existing_root)
        patch.setattr(upgrade,'inspect_root',old_upgrade.inspect_root)
        gen=world.__wrapped__(tmp_path)
        w=await anext(gen)
        try:
            entry,ref,authority,result=await applied_signal(w)
            source=await w['manager'].read_prospective_outbox_source_v2(principal=PRINCIPAL,
                outbox_id=entry.outbox_id,payload_hash=entry.payload_hash)
            init=w['manager']._backend.initialization_receipt
        finally: await gen.aclose()
    return w,entry,source,init


async def upgrade_open(w,init):
    receipt=await m.migrate_human_memory_v7_2_to_v7_3(w['path'],backup_path=w['path'].with_suffix('.backup'),
        expected_initialization_receipt_hash=init.receipt_hash)
    w['manager']=await m.build_human_memory_v7(w['path'],**w['kwargs'])
    return receipt


async def settle(w,entry,source,**changes):
    args=dict(principal=PRINCIPAL,outbox_id=entry.outbox_id,payload_hash=entry.payload_hash,
        expected_source_hash=source.source_hash)
    args.update(changes)
    return await w['manager'].settle_prospective_invalidation(**args)


def rows(path):
    with sqlite3.connect(path) as db:
        return db.execute('SELECT outbox_id,payload,payload_hash,created_at FROM outbox ORDER BY outbox_id').fetchall()


async def test_legacy_upgrade_terminal_reopen_preserves_original_and_observation(tmp_path,monkeypatch):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    before=rows(w['path'])
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await m.build_human_memory_v7(w['path'],**w['kwargs'])
    upgraded=await upgrade_open(w,init)
    try:
        assert upgraded.source_schema_checksum==old_schema.SCHEMA_CHECKSUM
        assert upgraded.target_schema_checksum==schema_v7_3.SCHEMA_CHECKSUM
        assert w['manager']._backend.initialization_receipt.to_json()==init.to_json()
        receipt=await settle(w,entry,source)
        assert type(receipt) is m.ProspectiveInvalidationNotRequiredReceipt
        assert receipt.signal_result_hash==source.target_source.apply_result.result_hash
        assert receipt.target_revision==2 and receipt.kind=='not_required'
        obs=receipt.operation_observation
        assert obs.operation=='settle_prospective_invalidation' and obs.reason=='not_required_persisted'
        assert obs.source_hash==receipt.receipt_hash
        assert obs.request_hash==_hash('memory.prospective.invalidation.settlement.request.v1',
            [entry.outbox_id,entry.payload_hash,source.source_hash])
        assert 'operation_observation' not in receipt.to_json()
        assert rows(w['path'])==before
        roots=await w['manager']._backend._canonical_manifest_roots_unlocked(PRINCIPAL.actor_id)
        assert any(r.table_name=='prospective_invalidation_terminal_receipts' for r in roots)
    finally: await w['manager'].close()
    assert await m.migrate_human_memory_v7_2_to_v7_3(w['path'],backup_path=w['path'].with_suffix('.backup'))==upgraded
    w['clock'][0]=10000
    w['manager']=await m.build_human_memory_v7(w['path'],**(w['kwargs']|{'prospective_signal_authority':None}))
    try:
        again=await settle(w,entry,source,principal=replace(PRINCIPAL,session_id='later-session'))
        assert again==receipt and again.receipt_hash==receipt.receipt_hash
        assert again.operation_observation.invocation_ref_hash!=obs.invocation_ref_hash
    finally: await w['manager'].close()


async def test_pending_registration_returns_actual_dependency_and_can_ack_cancel(world):
    w=world
    entry,_=await revise(w)
    source=await w['manager'].read_prospective_outbox_source_v2(principal=PRINCIPAL,
        outbox_id=entry.outbox_id,payload_hash=entry.payload_hash)
    required=await settle(w,entry,source)
    assert type(required) is m.RegistrationRequiredView
    assert required.registration_entry==w['entry']
    assert required.operation_observation.reason=='registration_required'
    for kind in (Signal.REGISTRATION_ACCEPTED,Signal.REGISTRATION_INVALIDATED):
        selected=w['entry'] if kind is Signal.REGISTRATION_ACCEPTED else entry
        ref=_grant(w['authority'],memory_id=w['memory_id'],revision=1,kind=kind,
            transition_from=State.PENDING,transition_to=State.PENDING,observed_at=20.0,
            outbox_id=selected.outbox_id,outbox_hash=selected.payload_hash)
        result=await w['manager'].apply_prospective_signal(principal=PRINCIPAL,scope=SCOPE,reference=ref)
        assert result.outcome.value=='acknowledged'
    assert type(await settle(w,entry,source)) is m.RegistrationRequiredView
    assert (await w['manager']._backend.connection.execute_fetchall(
        'SELECT count(*) FROM prospective_invalidation_terminal_receipts'))[0][0]==0


async def test_future_emit_keeps_original_cancel_without_new_empty_object(world):
    w=world
    accepted=_grant(w['authority'],memory_id=w['memory_id'],revision=1,kind=Signal.REGISTRATION_ACCEPTED,
        transition_from=State.PENDING,transition_to=State.PENDING,observed_at=20.0,
        outbox_id=w['entry'].outbox_id,outbox_hash=w['entry'].payload_hash)
    await w['manager'].apply_prospective_signal(principal=PRINCIPAL,scope=SCOPE,reference=accepted)
    w['clock'][0]=30
    due=_grant(w['authority'],memory_id=w['memory_id'],revision=1,kind=Signal.TIME_DUE,
        transition_from=State.PENDING,transition_to=State.TRIGGERED,observed_at=30.0)
    await w['manager'].apply_prospective_signal(principal=PRINCIPAL,scope=SCOPE,reference=due)
    await revise(w,target_revision=2)
    entries=(await w['manager'].read_outbox(principal=PRINCIPAL)).entries
    assert sorted((e.payload['command'],e.payload['prospective_revision']) for e in entries
        if e.topic.startswith('memory.prospective.'))==[
        ('invalidation',1),('registration',1),('registration',3)]


async def test_reject_wrong_identity_and_source_without_terminal(tmp_path,monkeypatch):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    await upgrade_open(w,init)
    try:
        for changes,error in (({'expected_source_hash':'0'*64},MemoryValidationError),
            ({'payload_hash':'0'*64},MemoryValidationError),
            ({'principal':replace(PRINCIPAL,deployment_id='foreign-deployment')},MemoryOwnershipConflict)):
            with pytest.raises(error) as denied: await settle(w,entry,source,**changes)
            assert denied.value.operation_observation.operation=='settle_prospective_invalidation'
        assert (await w['manager']._backend.connection.execute_fetchall(
            'SELECT count(*) FROM prospective_invalidation_terminal_receipts'))[0][0]==0
    finally: await w['manager'].close()


@pytest.mark.parametrize('point',['prospective_settlement.after_receipt','prospective_settlement.after_commit'])
async def test_terminal_rollback_or_lost_response_replays(tmp_path,monkeypatch,point):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    await upgrade_open(w,init)
    backend=w['manager']._backend
    def fault(value):
        if value==point: raise asyncio.CancelledError()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(backend,'_fault',fault)
            with pytest.raises(asyncio.CancelledError) as cancelled: await settle(w,entry,source)
            assert cancelled.value.operation_observation.outcome=='cancelled'
        persisted=await backend.connection.execute_fetchall('SELECT receipt_hash FROM prospective_invalidation_terminal_receipts')
        assert bool(persisted)==point.endswith('after_commit')
        receipt=await settle(w,entry,source)
        if persisted: assert receipt.receipt_hash==persisted[0][0]
        assert await settle(w,entry,source)==receipt
    finally: await w['manager'].close()


async def test_terminal_two_connection_registration_guard(tmp_path,monkeypatch):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    await upgrade_open(w,init)
    attempts=[]
    def concurrent(point):
        if point!='prospective_settlement.after_absence': return
        db=sqlite3.connect(w['path'],timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError,match='locked'):
                db.execute('BEGIN IMMEDIATE')
            attempts.append('writer_fenced')
        finally: db.close()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(w['manager']._backend,'_fault',concurrent)
            await settle(w,entry,source)
        assert attempts==['writer_fenced']
        import json
        from simple_harness.contracts import canonical_json
        from simple_harness_memory.backends.sqlite_v5 import _stable_id
        payload=dict(entry.payload);payload['command']='registration'
        wire=canonical_json(payload);identity=_stable_id('prospective-scheduler-outbox',w['memory_id'],'2','registration')
        with sqlite3.connect(w['path']) as db:
            with pytest.raises(sqlite3.IntegrityError,match='already not required'):
                db.execute("INSERT INTO outbox(outbox_id,principal_id,topic,idempotency_key,payload,payload_hash,state,next_attempt_at,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',30,30,30)",
                    (identity,PRINCIPAL.actor_id,'memory.prospective.registration.requested',identity,wire,hashlib.sha256(wire.encode()).hexdigest()))
        forged_ack=_grant(w['authority'],memory_id=w['memory_id'],revision=2,
            kind=Signal.REGISTRATION_INVALIDATED,transition_from=State.TRIGGERED,
            transition_to=State.TRIGGERED,observed_at=30.0,outbox_id=entry.outbox_id,outbox_hash=entry.payload_hash)
        with pytest.raises(MemoryValidationError,match='already_not_required'):
            await w['manager'].apply_prospective_signal(principal=PRINCIPAL,scope=SCOPE,reference=forged_ack)
    finally: await w['manager'].close()


async def test_receipt_tamper_rejected_on_replay_close_and_reopen(tmp_path,monkeypatch):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    await upgrade_open(w,init)
    try:
        await settle(w,entry,source)
        with sqlite3.connect(w['path']) as db:
            sql=db.execute("SELECT sql FROM sqlite_master WHERE name='prospective_terminal_no_update'").fetchone()[0]
            db.execute('DROP TRIGGER prospective_terminal_no_update')
            db.execute("UPDATE prospective_invalidation_terminal_receipts SET receipt_hash=?",('0'*64,))
            db.execute(sql)
        with pytest.raises(MemoryCorruptionError): await settle(w,entry,source)
    finally:
        with pytest.raises(MemoryCorruptionError): await w['manager'].close()
    with pytest.raises(MemoryCorruptionError): await m.build_human_memory_v7(w['path'],**w['kwargs'])


@pytest.mark.parametrize('point',['after_ddl','before_commit','after_commit'])
async def test_upgrade_fault_preserves_old_receipt_and_retries(tmp_path,monkeypatch,point):
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    before=rows(w['path'])
    def fault(value):
        if value==point: raise RuntimeError('injected upgrade response loss')
    with monkeypatch.context() as patch:
        patch.setattr(upgrade,'_fault',fault)
        with pytest.raises(RuntimeError,match='injected'): await upgrade_open(w,init)
    with sqlite3.connect(w['path']) as db:
        assert db.execute('SELECT receipt_hash FROM initialization_receipts').fetchone()[0]==init.receipt_hash
        assert (db.execute("SELECT 1 FROM schema_meta WHERE key=?",(upgrade.MARKER_KEY,)).fetchone() is not None)==(point=='after_commit')
    assert rows(w['path'])==before
    await upgrade_open(w,init)
    await w['manager'].close()


async def test_upgrade_rejects_unknown_and_wrong_backup_unchanged(tmp_path,monkeypatch):
    bad=tmp_path/'unknown.db';bad.write_bytes(b'not a sqlite database')
    original=bad.read_bytes()
    with pytest.raises((sqlite3.DatabaseError,MemoryLegacySchemaUnsupported)):
        await m.migrate_human_memory_v7_2_to_v7_3(bad,backup_path=tmp_path/'bad.backup')
    assert bad.read_bytes()==original
    w,entry,source,init=await legacy_case(tmp_path,monkeypatch)
    backup=w['path'].with_suffix('.backup');backup.write_bytes(b'unrelated bytes')
    before=rows(w['path'])
    with pytest.raises((sqlite3.DatabaseError,MemoryLegacySchemaUnsupported)):
        await upgrade_open(w,init)
    assert rows(w['path'])==before and backup.read_bytes()==b'unrelated bytes'
