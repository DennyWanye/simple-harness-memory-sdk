"""Exact, bounded signal provenance beside the frozen mutation-only reader."""
import hashlib
import sqlite3
import aiosqlite
from simple_harness.contracts import canonical_json
from simple_harness.runtime import ProspectiveSignalAuthority, ProspectiveSignalAuthorityRef
from simple_harness_memory.backends import prospective_sources as v1
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.lifecycle_results import ProspectiveSignalApplyResult
from simple_harness_memory.core.mutation_receipts import _identifier, _digest
from simple_harness_memory.core.prospective_sources_v2 import (
    MutationTargetSource, ProspectiveSignalTargetSource, ProspectiveOutboxSourceViewV2,
)

MAX_SQL_STEPS = 200_000
MAX_WIRE_BYTES = 1_048_576


def _bad():
    raise MemoryCorruptionError("prospective_signal_source_binding_corrupt")


def _check(row, expected):
    if row is None or any(row[key] != value for key, value in expected.items()):
        _bad()


def _sha(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


async def _bounded_row(db, table, key, identity, wires):
    # All selectors are static internal call sites, never caller SQL/column names.
    sizes = ','.join(f'length(CAST({name} AS BLOB)) AS {name}' for name in wires)
    size = await v1._one(db, f'SELECT {sizes} FROM {table} WHERE {key}=?', (identity,))
    if size is None:
        _bad()
    if any(size[name] is None or size[name] > MAX_WIRE_BYTES for name in wires):
        raise MemoryLimitError("prospective_signal_source_wire_limit")
    return await v1._one(db, f'SELECT * FROM {table} WHERE {key}=?', (identity,))


def _from_mutation(source):
    origin = MutationTargetSource(source.target_mutation_receipt_ref, source.target_plan_id,
        source.target_plan_hash, source.target_run_id, source.target_operation_id, source.target_operation_kind)
    return ProspectiveOutboxSourceViewV2(**{name: getattr(source, name) for name in (
        'subject', 'outbox_id', 'outbox_payload_hash', 'outbox_created_at', 'command', 'target_memory_id',
        'target_revision', 'registration_revision', 'target_scope', 'target_task_scope_id',
        'target_lifecycle_state', 'trigger', 'trigger_hash')}, target_source=origin)


async def _signal(backend, db, principal, outbox_id, payload_hash):
    from simple_harness_memory.backends.sqlite_v5 import _stable_id
    # V1 already checked ownership, exact outbox, target content and trigger in this snapshot.
    outbox = await v1._one(db, 'SELECT payload,created_at FROM outbox WHERE outbox_id=?', (outbox_id,))
    payload = v1._json(outbox['payload'])
    target, trigger, trigger_hash, origin = await signal_target(backend, db, principal, payload)
    return ProspectiveOutboxSourceViewV2(principal.actor_id, outbox_id, payload_hash, outbox['created_at'],
        payload['command'], payload['memory_id'], payload['prospective_revision'], payload['registration_revision'],
        MemoryScope(target['scope_kind'], target['scope_owner']), target['task_scope_id'],
        target['lifecycle_state'], trigger, trigger_hash, origin)


async def signal_target(backend, db, principal, payload):
    from simple_harness_memory.backends.sqlite_v5 import _stable_id
    memory_id, revision = payload['memory_id'], payload['prospective_revision']
    async with db.execute('SELECT d.consumption_id FROM prospective_signal_decisions d '
        'JOIN prospective_signal_authority_consumptions c ON c.consumption_id=d.consumption_id '
        'WHERE d.memory_id=? AND d.committed_revision=? AND d.outcome=\'applied\' '
        'AND c.principal_id=? LIMIT 2', (memory_id, revision, principal.actor_id)) as cursor:
        candidates = await cursor.fetchall()
    if not candidates:
        raise MemoryValidationError('prospective_target_signal_source_unavailable')
    if len(candidates) != 1:
        _bad()
    cid = candidates[0]['consumption_id']
    c = await _bounded_row(db, 'prospective_signal_authority_consumptions', 'consumption_id', cid,
        ('authority_json', 'authority_ref_json'))
    authority_wire, ref_wire = v1._json(c['authority_json']), v1._json(c['authority_ref_json'])
    authority = ProspectiveSignalAuthority.from_json(authority_wire)
    reference = ProspectiveSignalAuthorityRef.from_json(ref_wire)
    if (authority.to_json() != authority_wire or reference.to_json() != ref_wire
            or ProspectiveSignalAuthorityRef.from_authority(authority) != reference):
        _bad()
    intent = authority.intent
    _check(c, dict(consumption_id=_stable_id('prospective-signal-consumption', authority.authority_id),
        principal_id=principal.actor_id, authority_id=authority.authority_id,
        authority_hash=authority.authority_hash, issuer_ref=authority.issuer_ref, nonce=authority.nonce,
        replay_identity=authority.replay_identity, authority_ref_hash=reference.ref_hash,
        intent_hash=intent.intent_hash, target_memory_id=memory_id, target_revision=intent.target_revision,
        issued_at=authority.issued_at, expires_at=authority.expires_at))
    if intent.subject != principal.actor_id or not authority.issued_at <= c['consumed_at'] < authority.expires_at:
        _bad()
    consumed = dict(schema_version=1, consumption_id=cid, principal_id=principal.actor_id,
        authority_ref=reference.to_json(), authority_ref_hash=reference.ref_hash,
        authority=authority.to_json(), authority_hash=authority.authority_hash, consumed_at=c['consumed_at'])
    if _sha(consumed) != c['consumption_hash']:
        _bad()
    d = await _bounded_row(db, 'prospective_signal_decisions', 'consumption_id', cid, ('decision_json',))
    expected = dict(schema_version=1, decision_id=_stable_id('prospective-signal-decision', authority.authority_id),
        consumption_id=cid, consumption_hash=c['consumption_hash'], memory_id=memory_id,
        base_revision=intent.target_revision, committed_revision=revision,
        transition_from=intent.transition_from.value, transition_to=intent.transition_to.value,
        outcome='applied', reason_code='prospective_expired' if intent.signal_kind.value == 'expired'
        else 'prospective_trigger_matched')
    if (intent.signal_kind.value not in {'time_due', 'event_occurred', 'expired'}
            or revision != intent.target_revision + 1 or intent.target_memory_id != memory_id
            or v1._json(d['decision_json']) != expected or d['decision_hash'] != _sha(expected)):
        _bad()
    _check(d, {key: value for key, value in expected.items() if key not in {'schema_version', 'consumption_hash'}})
    _check(d, dict(decided_at=c['consumed_at']))
    r = await _bounded_row(db, 'prospective_signal_results', 'consumption_id', cid, ('result_json',))
    result = ProspectiveSignalApplyResult.from_json(v1._json(r['result_json']))
    expected_result = ProspectiveSignalApplyResult(
        _stable_id('prospective-signal-result', authority.authority_id), intent.signal_id,
        d['decision_id'], memory_id, intent.target_revision, revision, intent.transition_to,
        'applied', expected['reason_code'], c['consumed_at'])
    if result != expected_result or result.result_hash != r['result_hash']:
        _bad()
    _check(r, dict(result_id=result.result_id, replay_identity=authority.replay_identity,
        consumption_id=cid, decided_at=result.decided_at))
    event = await _bounded_row(db, 'prospective_trigger_events', 'consumption_id', cid, ('event_json',))
    expected_event = dict(schema_version=1, event_id=_stable_id('prospective-trigger-event', cid),
        memory_id=memory_id, prospective_revision=intent.target_revision, trigger_hash=intent.trigger_hash,
        event_ref=intent.signal_receipt_id, occurrence_key=intent.occurrence_key, signal_kind=intent.signal_kind.value,
        outcome='expired' if intent.signal_kind.value == 'expired' else 'matched',
        reason_code=expected['reason_code'], occurred_at=intent.observed_at)
    if v1._json(event['event_json']) != expected_event or event['event_hash'] != _sha(expected_event):
        _bad()
    _check(event, {key: value for key, value in expected_event.items() if key not in {'schema_version', 'trigger_hash'}})
    _check(event, dict(consumption_id=cid, principal_id=principal.actor_id, trigger_fingerprint=intent.trigger_hash))
    unexpected = await v1._one(db, 'SELECT 1 FROM prospective_scheduler_registrations WHERE consumption_id=?', (cid,))
    if unexpected is not None:
        _bad()
    fields = ('principal_id,deployment_id,household_id,scope_kind,scope_owner,task_scope_id,'
        'content_json,content_hash,plan_id,plan_hash,operation_id,lifecycle_state,created_at')
    size = await v1._one(db, 'SELECT length(CAST(content_json AS BLOB)) FROM cognitive_memory_revisions '
        'WHERE memory_id=? AND revision=?', (memory_id, revision))
    if size is None:
        _bad()
    if size[0] > MAX_WIRE_BYTES:
        raise MemoryLimitError('prospective_signal_source_wire_limit')
    target = await v1._one(db, f'SELECT {fields} FROM cognitive_memory_revisions WHERE memory_id=? AND revision=?',
        (memory_id, revision))
    # Bound base content before fetching. Only the immediate factual copy edge is required.
    size = await v1._one(db, 'SELECT length(CAST(content_json AS BLOB)) FROM cognitive_memory_revisions '
        'WHERE memory_id=? AND revision=?', (memory_id, intent.target_revision))
    if size is None:
        _bad()
    if size[0] > MAX_WIRE_BYTES:
        raise MemoryLimitError('prospective_signal_source_wire_limit')
    base = await v1._one(db, f'SELECT {fields} FROM cognitive_memory_revisions WHERE memory_id=? AND revision=?',
        (memory_id, intent.target_revision))
    _check(target, dict(principal_id=principal.actor_id, deployment_id=principal.deployment_id,
        household_id=principal.household_id, scope_kind=intent.scope.kind.value, scope_owner=intent.scope.owner_id,
        plan_id=_stable_id('prospective-signal-plan', authority.authority_id), plan_hash=intent.intent_hash,
        operation_id=intent.operation_id, lifecycle_state=intent.transition_to.value, created_at=c['consumed_at']))
    _check(base, dict(lifecycle_state=intent.transition_from.value))
    for key in ('principal_id', 'deployment_id', 'household_id', 'scope_kind', 'scope_owner',
                'task_scope_id', 'content_json', 'content_hash'):
        if base[key] != target[key]:
            _bad()
    if _sha(v1._json(base['content_json'])) != base['content_hash']:
        _bad()
    trigger, trigger_hash = backend._decode_prospective_trigger(canonical_json(payload['trigger']))
    if trigger.to_json() != intent.trigger.to_json() or trigger_hash != intent.trigger_hash:
        _bad()
    origin = ProspectiveSignalTargetSource(result, intent.signal_kind.value, intent.intent_hash,
        authority.authority_id, authority.authority_hash, reference.ref_hash, cid, c['consumption_hash'],
        d['decision_id'], d['decision_hash'], intent.signal_receipt_id, intent.signal_receipt_hash,
        intent.run_id, intent.operation_id)
    return target, trigger, trigger_hash, origin


async def _read(backend, db, principal, outbox_id, payload_hash):
    try:
        source = await v1._read(backend, db, principal, outbox_id, payload_hash)
    except MemoryValidationError as exc:
        if str(exc) != 'prospective_target_mutation_source_unavailable':
            raise
        return await _signal(backend, db, principal, outbox_id, payload_hash)
    return _from_mutation(source)


async def read_prospective_outbox_source_v2(backend, *, principal, outbox_id, payload_hash):
    if type(principal) is not MemoryPrincipal:
        raise TypeError('principal must use MemoryPrincipal')
    _identifier(outbox_id, 'outbox_id')
    _digest(payload_hash, 'outbox_payload_hash')
    ticks = 0
    def progress():
        nonlocal ticks
        ticks += 1000
        return ticks >= MAX_SQL_STEPS
    async with backend._write_lock:
        if backend._db is None or backend._receipt is None:
            raise RuntimeError('human-memory v7 backend is not initialized')
        async with aiosqlite.connect(backend._db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1.0) as db:
            db.row_factory = aiosqlite.Row
            await db.set_progress_handler(progress, 1000)
            try:
                await db.execute('BEGIN')
                return await _read(backend, db, principal, outbox_id, payload_hash)
            except MemoryValidationError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError('prospective_signal_source_wire_invalid') from exc
            except sqlite3.OperationalError as exc:
                if ticks >= MAX_SQL_STEPS:
                    raise MemoryLimitError('prospective_source_v2_sql_budget') from exc
                raise
            finally:
                await db.set_progress_handler(None, 0)
                await db.rollback()
