"""Fenced historical absence proof and durable invalidation terminal, never an ACK."""
import sqlite3
import time
from uuid import uuid4
from simple_harness.contracts import canonical_json
from simple_harness_memory.backends import prospective_sources as v1, prospective_sources_v2 as v2
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.mutation_receipts import _identifier, _digest
from simple_harness_memory.core.occurrence import OutboxEntryV1
from simple_harness_memory.core.prospective_settlement import (
    RegistrationRequiredView, ProspectiveInvalidationNotRequiredReceipt,
)
from simple_harness_memory.core.prospective_sources_v2 import ProspectiveSignalTargetSource

TABLE='prospective_invalidation_terminal_receipts'


def _bad():
    raise MemoryCorruptionError('prospective_settlement_binding_corrupt')


async def has_schema(db):
    return await v1._one(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)) is not None


async def registration_request(backend,db,principal,memory_id,revision,trigger_hash):
    """Bounded exact request, including noncanonical/duplicate target detection."""
    from simple_harness_memory.backends.sqlite_v5 import _stable_id
    identity=_stable_id('prospective-scheduler-outbox',memory_id,str(revision),'registration')
    oversized=await v1._one(db,"SELECT 1 FROM outbox WHERE topic='memory.prospective.registration.requested' "
        'AND length(CAST(payload AS BLOB))>? LIMIT 1',(v2.MAX_WIRE_BYTES,))
    if oversized is not None: raise MemoryLimitError('prospective_registration_wire_limit')
    malformed=await v1._one(db,"SELECT 1 FROM outbox WHERE topic='memory.prospective.registration.requested' "
        'AND NOT json_valid(payload) LIMIT 1',())
    if malformed is not None: _bad()
    async with db.execute("SELECT outbox_id FROM outbox WHERE outbox_id=? OR "
        "(topic='memory.prospective.registration.requested' AND json_extract(payload,'$.memory_id')=? "
        "AND json_extract(payload,'$.prospective_revision')=?) LIMIT 2",(identity,memory_id,revision)) as cursor:
        found=await cursor.fetchall()
    if not found: return None
    if len(found)!=1 or found[0][0]!=identity: _bad()
    row=await v2._bounded_row(db,'outbox','outbox_id',identity,('payload',))
    payload=v1._json(row['payload'])
    trigger,digest=backend._decode_prospective_trigger(canonical_json(payload.get('trigger')))
    expected=dict(schema_version=1,command='registration',memory_id=memory_id,
        prospective_revision=revision,registration_revision=revision,trigger=trigger.to_json(),trigger_hash=trigger_hash)
    if (payload!=expected or canonical_json(payload)!=row['payload'] or v2._sha(payload)!=row['payload_hash']
        or digest!=trigger_hash or row['topic']!='memory.prospective.registration.requested'
        or row['idempotency_key']!=identity or row['principal_id']!=principal.actor_id): _bad()
    from simple_harness_memory.core.prospective_settlement import _time
    for key in ('created_at','updated_at','next_attempt_at'): _time(row[key])
    return OutboxEntryV1(row['outbox_id'],row['topic'],row['idempotency_key'],row['state'],row['payload_hash'],
        row['attempt_count'],row['next_attempt_at'],row['created_at'],row['updated_at'],payload)


async def no_registration_event(db,memory_id,revision):
    if await v1._one(db,'SELECT 1 FROM prospective_scheduler_registrations WHERE memory_id=? '
        'AND (prospective_revision=? OR registration_revision=?) LIMIT 1',(memory_id,revision,revision)) is not None:
        _bad()


def identity(principal,source):
    return dict(deployment_id=principal.deployment_id,household_id=principal.household_id,subject=principal.actor_id,
        outbox_id=source.outbox_id,outbox_payload_hash=source.outbox_payload_hash,
        outbox_created_at=source.outbox_created_at,memory_id=source.target_memory_id,
        target_revision=source.target_revision,registration_revision=source.registration_revision,
        trigger_hash=source.trigger_hash,target_source_hash=source.source_hash)


def _eligible(source):
    if (type(source.target_source) is not ProspectiveSignalTargetSource
        or source.target_lifecycle_state.value in {'pending','rescheduled'}):
        raise MemoryValidationError('prospective_invalidation_absence_not_proven')


async def read_receipt(db,outbox_id,principal,source):
    row=await v1._one(db,f'SELECT receipt_id FROM {TABLE} WHERE outbox_id=?',(outbox_id,))
    if row is None: return None
    row=await v2._bounded_row(db,TABLE,'receipt_id',row[0],('receipt_json',))
    value=v1._json(row['receipt_json'])
    receipt=ProspectiveInvalidationNotRequiredReceipt.from_json(value)
    if canonical_json(value)!=row['receipt_json'] or receipt.receipt_hash!=row['receipt_hash']: _bad()
    expected=identity(principal,source)
    if any(getattr(receipt,key)!=item for key,item in expected.items()): _bad()
    _eligible(source)
    result=source.target_source.apply_result
    if receipt.signal_result_id!=result.result_id or receipt.signal_result_hash!=result.result_hash: _bad()
    columns=dict(receipt_id=receipt.receipt_id,outbox_id=outbox_id,principal_id=receipt.subject,
        deployment_id=receipt.deployment_id,household_id=receipt.household_id,memory_id=receipt.memory_id,
        target_revision=receipt.target_revision,registration_revision=receipt.registration_revision,
        payload_hash=receipt.outbox_payload_hash,target_source_hash=receipt.target_source_hash,
        trigger_hash=receipt.trigger_hash,kind=receipt.kind,reason=receipt.reason,checked_at=receipt.checked_at)
    if any(row[key]!=item for key,item in columns.items()): _bad()
    return receipt


async def _settle(backend,db,principal,outbox_id,payload_hash,expected_source_hash):
    source=await v2._read(backend,db,principal,outbox_id,payload_hash)
    if source.command!='invalidation' or source.source_hash!=expected_source_hash:
        raise MemoryValidationError('prospective_invalidation_source_differs')
    request=await registration_request(backend,db,principal,source.target_memory_id,source.target_revision,source.trigger_hash)
    stored=await read_receipt(db,outbox_id,principal,source)
    if request is not None:
        if stored is not None: _bad()
        return RegistrationRequiredView(**identity(principal,source),registration_entry=request)
    _eligible(source)
    await no_registration_event(db,source.target_memory_id,source.target_revision)
    if stored is not None: return stored
    result=source.target_source.apply_result
    receipt=ProspectiveInvalidationNotRequiredReceipt(**identity(principal,source),
        receipt_id='prospective-not-required:'+str(uuid4()),signal_result_id=result.result_id,
        signal_result_hash=result.result_hash,checked_at=time.time())
    backend._fault('prospective_settlement.after_absence')
    await db.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
        receipt.receipt_id,outbox_id,principal.actor_id,principal.deployment_id,principal.household_id,
        source.target_memory_id,source.target_revision,source.registration_revision,payload_hash,
        source.source_hash,source.trigger_hash,receipt.kind,receipt.reason,canonical_json(receipt.to_json()),
        receipt.receipt_hash,receipt.checked_at))
    backend._fault('prospective_settlement.after_receipt')
    return receipt


async def settle_prospective_invalidation(backend,*,principal,outbox_id,payload_hash,expected_source_hash):
    if type(principal) is not MemoryPrincipal: raise TypeError('principal must use MemoryPrincipal')
    for key in ('deployment_id','household_id','actor_id','session_id'): _identifier(getattr(principal,key),key)
    _identifier(outbox_id,'outbox_id');_digest(payload_hash,'payload_hash');_digest(expected_source_hash,'expected_source_hash')
    ticks=0
    def progress():
        nonlocal ticks
        ticks+=1000
        return ticks>=v2.MAX_SQL_STEPS
    async with backend._write_lock:
        db=backend._db
        if db is None or backend._receipt is None: raise RuntimeError('memory backend is not initialized')
        if not await has_schema(db): raise MemoryValidationError('prospective_settlement_requires_schema_7_3')
        await db.set_progress_handler(progress,1000)
        try:
            await db.execute('BEGIN IMMEDIATE')
            result=await _settle(backend,db,principal,outbox_id,payload_hash,expected_source_hash)
            backend._fault('prospective_settlement.before_commit')
            await db.execute('COMMIT')
            backend._fault('prospective_settlement.after_commit')
            return result
        except MemoryValidationError:
            raise
        except (KeyError,TypeError,ValueError) as exc:
            raise MemoryCorruptionError('prospective_settlement_wire_invalid') from exc
        except sqlite3.OperationalError as exc:
            if ticks>=v2.MAX_SQL_STEPS: raise MemoryLimitError('prospective_settlement_sql_budget') from exc
            raise
        finally:
            await db.set_progress_handler(None,0)
            await db.rollback()


async def guard_registration(db,memory_id,revision):
    if await has_schema(db) and await v1._one(db,f'SELECT 1 FROM {TABLE} WHERE memory_id=? AND target_revision=?',
        (memory_id,revision)) is not None:
        raise MemoryValidationError('prospective_registration_already_not_required')


async def _skip_no_object_invalidation(backend,principal_id,memory_id,revision):
    """Only skip a fully verified old signal target; no fake outbox is constructed."""
    db=backend._db
    if not await has_schema(db): return False  # legacy validation/7.2 source retains its emit contract
    row=await v1._one(db,'SELECT deployment_id,household_id,principal_id,lifecycle_state '
        'FROM cognitive_memory_revisions WHERE memory_id=? AND revision=?',(memory_id,revision))
    if row is None or row['principal_id']!=principal_id: _bad()
    principal=MemoryPrincipal(row['deployment_id'],row['household_id'],principal_id,'sdk:historical-target-validation')
    size=await v1._one(db,'SELECT length(CAST(trigger_json AS BLOB)) FROM prospective_records WHERE memory_id=? AND revision=?',(memory_id,revision))
    if size is None: _bad()
    if size[0]>v2.MAX_WIRE_BYTES: raise MemoryLimitError('prospective_registration_wire_limit')
    trigger_row=await v1._one(db,'SELECT trigger_json FROM prospective_records WHERE memory_id=? AND revision=?',(memory_id,revision))
    trigger,trigger_hash=backend._decode_prospective_trigger(trigger_row[0])
    request=await registration_request(backend,db,principal,memory_id,revision,trigger_hash)
    if request is not None:
        await guard_registration(db,memory_id,revision)
        return False
    candidate=await v1._one(db,"SELECT 1 FROM prospective_signal_decisions WHERE memory_id=? AND committed_revision=? AND outcome='applied' LIMIT 1",(memory_id,revision))
    if candidate is None: return False
    payload={'memory_id':memory_id,'prospective_revision':revision,'trigger':trigger.to_json()}
    target,_,_,_=await v2.signal_target(backend,db,principal,payload)
    if target['lifecycle_state'] in {'pending','rescheduled'}:
        raise MemoryCorruptionError('signal_registration_request_missing')
    await no_registration_event(db,memory_id,revision)
    return True


async def _validate_integrity(backend):
    db=backend._db
    if not await has_schema(db): return
    async with db.execute(f'SELECT outbox_id,payload_hash,deployment_id,household_id,principal_id FROM {TABLE}') as cursor:
        # Stream receipts; each chain still uses the source reader's bounded JSON rules.
        async for row in cursor:
            principal=MemoryPrincipal(row['deployment_id'],row['household_id'],row['principal_id'],'sdk:terminal-integrity')
            source=await v2._read(backend,db,principal,row['outbox_id'],row['payload_hash'])
            if source.command!='invalidation': _bad()
            if await read_receipt(db,row['outbox_id'],principal,source) is None: _bad()
            if await registration_request(backend,db,principal,source.target_memory_id,source.target_revision,source.trigger_hash) is not None: _bad()
            await no_registration_event(db,source.target_memory_id,source.target_revision)


async def skip_no_object_invalidation(backend,principal_id,memory_id,revision):
    ticks=0
    def progress():
        nonlocal ticks
        ticks+=1000
        return ticks>=v2.MAX_SQL_STEPS
    await backend._db.set_progress_handler(progress,1000)
    try:
        return await _skip_no_object_invalidation(backend,principal_id,memory_id,revision)
    except sqlite3.OperationalError as exc:
        if ticks>=v2.MAX_SQL_STEPS: raise MemoryLimitError('prospective_emit_proof_sql_budget') from exc
        raise
    finally:
        await backend._db.set_progress_handler(None,0)


async def validate_integrity(backend):
    try:
        await _validate_integrity(backend)
    except (MemoryValidationError, KeyError, TypeError, ValueError) as exc:
        raise MemoryCorruptionError('prospective_terminal_integrity_invalid') from exc
