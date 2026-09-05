"""Bounded, sealed projection of existing durable operation facts. No producer ledger."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.operation_audit import (
    COVERAGE_VERSION, FAMILIES, OperationAuditCoverage, OperationAuditCursor,
    OperationAuditExpectation, OperationAuditExpectationResult, OperationAuditItemV1,
    OperationAuditPage, _canonical, _hash, operation_audit_ref_hash as ref,
)
from simple_harness_memory.core.suppression import SealedAuditAccessDenied, SuppressionScopeKind

# Static internal schema registry. Neither table/SQL names nor raw reference IDs escape.
_SPECS = (
    ('memory_mutation_receipts', '', 't.principal_id', 'receipt_id', 'receipt_hash', 'committed_at'),
    ('memory_mutation_rejection_audits', '', 't.principal_id', 'rejection_id', 'rejection_hash', 'rejected_at'),
    ('typed_recall_requests', '', 't.principal_id', 'request_id', 'request_hash', 'created_at'),
    ('typed_recall_attempts', 'JOIN typed_recall_requests p ON p.request_id=t.request_id', 'p.principal_id', 'attempt_id', 'attempt_hash', 'started_at'),
    ('typed_recall_terminals', 'JOIN typed_recall_requests p ON p.request_id=t.request_id', 'p.principal_id', 'request_id', 'terminal_hash', 'created_at'),
    ('recall_context_use_receipts', '', 't.principal_id', 'receipt_id', 'receipt_hash', 'authorized_at'),
    ('short_horizon_audit', '', 't.principal_id', 'audit_id', 'audit_hash', 'created_at'),
    ('suppression_directives', '', 't.principal_id', 'directive_id', 'decision_hash', 'effective_at'),
    ('job_attempt_events', 'JOIN jobs p ON p.job_id=t.job_id', 'p.principal_id', 'event_id', 'event_hash', 'occurred_at'),
)
_JOB_KINDS = ('provider_handoff', 'reclaimed', 'result_committed', 'result_replayed',
              'result_divergent', 'result_out_of_order', 'application_staged',
              'application_rejected', 'mutation_audit_committed', 'applied',
              'retry_scheduled', 'authority_retry_scheduled', 'dead_letter')
_SHORT_KINDS = ('recall_started', 'recall', 'recall_terminal')
_KINDS = (
    ('mutate', 'no_mutation'), ('rejected',), ('admitted',), ('started',),
    ('completed', 'rejected', 'deadline_exceeded'), ('authorized',), _SHORT_KINDS,
    ('directive', 'revoke'), _JOB_KINDS,
)
_EXCLUSIONS = (
    ('per_call_start_and_exact_replay_unobserved',), ('pre_admission_rejections_unobserved',),
    ('pre_db_rejections_host_persistence_unverified',), ('per_call_exact_replay_unobserved',),
    ('unterminated_attempts_unresolved',), ('rejected_use_calls_unobserved',),
    ('projection_generation_cleanup_excluded',), ('denied_suppression_calls_unobserved',),
    ('pending_creation_pre_handoff_unobserved', 'not_all_job_calls_emit_events'),
)
_MAX_ROWS = 100_000


def _wire(v: Any) -> Any:
    if isinstance(v, bytes):
        return {'blob_hex': v.hex()}
    if isinstance(v, dict):
        return {k: _wire(value) for k, value in v.items()}
    if isinstance(v, (tuple, list)):
        return [_wire(value) for value in v]
    return v


def _root(rows: Any) -> str:
    return _hash('memory.operation.audit.root.v1', _wire(rows))


def _principal(principal: Any) -> str:
    return _hash('memory.operation.audit.principal.v1', {
        key: getattr(principal, key) for key in ('deployment_id', 'household_id', 'actor_id', 'session_id')})


def _sign(backend: Any, payload: dict[str, Any]) -> str:
    key = backend._audit_cursor_hmac_key
    if key is None:
        raise MemoryCorruptionError('operation_audit_cursor_authority_missing')
    encoded = _canonical({'domain': 'memory.operation.audit.cursor.v1', 'payload': payload}).encode()
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


def _cursor(backend: Any, payload: dict[str, Any]) -> OperationAuditCursor:
    token = base64.urlsafe_b64encode(_canonical({'payload': payload, 'signature': _sign(backend, payload)}).encode()).decode()
    return OperationAuditCursor(token)


def _decode(backend: Any, cursor: OperationAuditCursor, query_hash: str) -> dict[str, Any]:
    try:
        value = json.loads(base64.b64decode(cursor.token, altchars=b'-_', validate=True))
        payload = value['payload']
        if set(value) != {'payload', 'signature'} or not hmac.compare_digest(value['signature'], _sign(backend, payload)):
            raise ValueError()
        if payload['schema_version'] != 1 or payload['query_hash'] != query_hash:
            raise ValueError()
        if set(payload) != {'schema_version', 'query_hash', 'cuts', 'support_root_hash', 'offset'}:
            raise ValueError()
        if type(payload['offset']) is not int or payload['offset'] < 0:
            raise ValueError()
        if [r[0] for r in payload['cuts']] != list(FAMILIES):
            raise ValueError()
        if any(type(r[1]) is not int or not 0 <= r[1] <= _MAX_ROWS for r in payload['cuts']):
            raise ValueError()
        return payload
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise MemoryValidationError('operation_audit_cursor_invalid') from exc


async def _rows(db: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with db.execute(sql, params) as cursor:
        return [dict(r) for r in await cursor.fetchall()]


async def _capture(backend: Any, subject: str, cut: dict[str, Any] | None):
    db = backend.connection
    lanes, cuts = {}, []
    total = 0
    for index, (family, spec) in enumerate(zip(FAMILIES, _SPECS, strict=True)):
        table, join, owner, _, _, _ = spec
        n = _MAX_ROWS + 1 if cut is None else cut['cuts'][index][1]
        where = " AND t.event_kind IN ('recall_started','recall','recall_terminal')" if family == 'short_recall' else ''
        rows = await _rows(db, f'SELECT t.* FROM {table} t {join} WHERE {owner}=?{where} ORDER BY t.rowid LIMIT ?', (subject, n))
        total += len(rows)
        if total > _MAX_ROWS:
            raise MemoryLimitError('operation_audit_snapshot_limit_exceeded')
        actual = [family, len(rows), _root(rows)]
        if cut is not None and actual != cut['cuts'][index]:
            raise MemoryCorruptionError('operation_audit_pinned_history_differs')
        lanes[family] = rows
        cuts.append(actual)
    return lanes, cuts


async def _support(backend: Any, lanes: dict[str, Any], subject: str):
    """Immutable identities plus ONLY phase values witnessed inside the pinned cut."""
    db = backend.connection
    support: dict[str, Any] = {'typed': [], 'suppression': [], 'jobs': {}}
    for row in lanes['typed_terminal']:
        for table, key, value in (
            ('typed_recall_decisions', 'request_id', row['request_id']),
            ('typed_recall_results', 'request_id', row['request_id']),
        ):
            support['typed'].extend(await _rows(db, f'SELECT * FROM {table} WHERE {key}=?', (value,)))
    for row in lanes['suppression']:
        support['suppression'].extend(await _rows(db, 'SELECT * FROM suppression_targets WHERE directive_id=? ORDER BY ordinal', (row['directive_id'],)))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in lanes['job_transition']:
        grouped.setdefault(event['batch_id'], []).append(event)
    for batch_id, events in grouped.items():
        rows = await _rows(db, 'SELECT * FROM analysis_batches WHERE batch_id=? AND principal_id=?', (batch_id, subject))
        if len(rows) != 1:
            raise MemoryCorruptionError('operation_audit_job_batch_missing')
        batch = rows[0]
        kinds = {r['event_kind'] for r in events}
        value = {k: batch[k] for k in ('batch_id', 'principal_id', 'request_hash', 'request_json')}
        value['members'] = await _rows(db, 'SELECT * FROM analysis_batch_members WHERE batch_id=? ORDER BY ordinal', (batch_id,))
        value['attempts'] = await _rows(db, 'SELECT job_id,attempt,batch_id,request_hash,started_at FROM job_attempts WHERE batch_id=? ORDER BY job_id,attempt', (batch_id,))
        # No fresh batch.state/lease or late-populated values can reinterpret a cursor.
        if 'result_committed' in kinds:
            value.update({k: batch[k] for k in ('result_json', 'result_hash')})
        if kinds & {'application_staged', 'application_rejected'}:
            value.update({k: batch[k] for k in ('application_receipt_json', 'application_receipt_hash')})
        support['jobs'][batch_id] = value
    return support


def _job_findings(events: list[dict[str, Any]], support: dict[str, Any]):
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault((event['batch_id'], event['job_id'], event['attempt']), []).append(event)
    missing, unresolved = set(), set()
    for (batch_id, job_id, attempt), members in grouped.items():
        batch = support['jobs'][batch_id]
        valid_member = any(r['job_id'] == job_id and r['job_attempt'] == attempt for r in batch['members'])
        valid_attempt = any(r['job_id'] == job_id and r['attempt'] == attempt and r['request_hash'] == batch['request_hash'] for r in batch['attempts'])
        kinds = {r['event_kind'] for r in members}
        reference = ref('job_attempt', f'{job_id}:{attempt}')
        if not valid_member or not valid_attempt or any(r['request_hash'] != batch['request_hash'] for r in members):
            raise MemoryCorruptionError('operation_audit_job_lineage_differs')
        if not kinds <= set(_JOB_KINDS):
            raise MemoryCorruptionError('operation_audit_job_kind_unknown')
        required = {'provider_handoff'}
        if kinds & {'result_replayed', 'result_divergent', 'application_staged', 'application_rejected', 'mutation_audit_committed', 'applied'}:
            required.add('result_committed')
        if 'applied' in kinds:
            required.add('mutation_audit_committed')
        if not required <= kinds or (kinds & {'mutation_audit_committed', 'applied'} and not kinds & {'application_staged', 'application_rejected'}):
            missing.add(reference)
        if not kinds & {'applied', 'dead_letter', 'retry_scheduled', 'authority_retry_scheduled'}:
            unresolved.add(reference)
    return tuple(sorted(unresolved)), tuple(sorted(missing))


async def _items(backend: Any, lanes: dict[str, Any], support: dict[str, Any]):
    result: dict[str, list[OperationAuditItemV1]] = {f: [] for f in FAMILIES}
    for family, spec, kinds in zip(FAMILIES, _SPECS, _KINDS, strict=True):
        _, _, _, identity, digest, timestamp = spec
        for row in lanes[family]:
            event = row[identity]
            operation, attempt = event, None
            kind, outcome, effect = kinds[0], 'committed', 'not_applicable'
            receipts: tuple[str, ...] = ()
            operations: tuple[str, ...] = ()
            if family == 'mutation_commit':
                _, receipt = await backend._decode_and_verify_mutation_receipt_row_unlocked(row)
                kind = row['plan_outcome']
                operation = row['plan_id']
                receipts = (row['receipt_hash'],)
                operations = tuple(sorted({ref('mutation_operation', v) for v in receipt.canonical_operation_ids}))
                effect = 'written' if operations else 'no_mutation'
            elif family == 'mutation_rejection':
                operation, outcome = row['plan_id'], 'rejected'
            elif family == 'typed_request':
                outcome = 'started'
            elif family == 'typed_attempt':
                operation, attempt, outcome = row['request_id'], row['attempt_id'], 'started'
            elif family == 'typed_terminal':
                operation, attempt, kind = row['request_id'], row['attempt_id'], row['terminal_kind']
                outcome = 'committed' if kind == 'completed' else 'rejected'
            elif family == 'recall_context_use':
                operation = row['provider_attempt_id']
            elif family == 'short_recall':
                kind = row['event_kind']
                details = json.loads(row['audit_json']).get('details', {})
                operation = details.get('attempt_audit_id') or row['audit_id']
                attempt = operation
                outcome = 'started' if kind == 'recall_started' else 'rejected' if kind == 'recall_terminal' else 'observed'
            elif family == 'suppression':
                kind, operation = row['event_kind'], row['request_id']
            elif family == 'job_transition':
                kind, operation = row['event_kind'], row['batch_id']
                attempt = f"{row['job_id']}:{row['attempt']}"
                outcome = 'started' if kind == 'provider_handoff' else 'committed' if kind == 'applied' else 'observed'
                effect = 'unverified'
                batch = support['jobs'][row['batch_id']]
                if batch.get('application_receipt_hash') and batch.get('result_hash'):
                    receipts = tuple(sorted((batch['application_receipt_hash'], batch['result_hash'])))
                    application = json.loads(batch['application_receipt_json'])
                    analysis = json.loads(batch['result_json'])
                    structured = analysis.get('structured_result')
                    if application.get('validation_status') == 'accepted' and isinstance(structured, dict) and structured.get('outcome') == 'no_mutation':
                        effect = 'no_mutation'
                    elif application.get('validation_status') == 'accepted':
                        # Only actual committed receipts captured in the same cut can prove writes.
                        from simple_harness import MemoryMutationPlan

                        # The canonical plan wire excludes its computed plan_hash.
                        # Rebuild the public DTO; never look for an invented output field.
                        plan = MemoryMutationPlan.from_json(structured)
                        plan_hash = plan.plan_hash
                        matched = [r for r in lanes['mutation_commit'] if r['plan_hash'] == plan_hash]
                        refs: set[str] = set()
                        for r in matched:
                            _, mutation = await backend._decode_and_verify_mutation_receipt_row_unlocked(r)
                            mutation.validate_plan(plan)
                            refs.update(ref('mutation_operation', op) for op in mutation.canonical_operation_ids)
                        if refs:
                            effect, operations = 'written', tuple(sorted(refs))
                            receipts = tuple(sorted(set(receipts) | {r['receipt_hash'] for r in matched}))
            if kind not in kinds:
                raise MemoryCorruptionError('operation_audit_event_kind_invalid')
            result[family].append(OperationAuditItemV1(
                family, kind, ref(family, event), ref(family + '_operation', operation),
                None if attempt is None else ref('job_attempt' if family == 'job_transition' else 'recall_attempt', attempt),
                row[timestamp], outcome, row[digest], effect, receipts, operations))
    return result


async def _denial(backend: Any, requester: Any, target: Any, receipt: Any, now: float) -> str | None:
    stored = await backend._read_audit_access_by_decision(receipt.decision_id)
    authority = await backend._read_audit_authority_ref_by_decision(receipt.decision_id)
    if stored != receipt or authority is None:
        return 'sealed_audit_receipt_differs'
    if any(getattr(authority, 'requester_' + k) != getattr(requester, k) for k in ('deployment_id', 'household_id', 'actor_id', 'session_id')):
        return 'sealed_audit_requester_differs'
    if any(getattr(authority, 'target_' + k) != getattr(target, k) for k in ('deployment_id', 'household_id', 'actor_id')) or authority.target_subject != target.actor_id:
        return 'sealed_audit_target_differs'
    if receipt.scope_kind is not SuppressionScopeKind.SUBJECT or receipt.scope_ref != target.actor_id or receipt.subject != target.actor_id:
        return 'operation_audit_subject_scope_required'
    if now < receipt.issued_at:
        return 'sealed_audit_access_not_yet_valid'
    if now >= receipt.expires_at:
        return 'sealed_audit_access_expired'
    rows = await _rows(backend.connection, "SELECT (SELECT COUNT(*) FROM sealed_audit_access_events WHERE access_receipt_id=? AND outcome='granted') + (SELECT COUNT(*) FROM audit_trace_access_events WHERE access_receipt_id=? AND outcome='granted') + (SELECT COUNT(*) FROM canonical_manifest_access_events WHERE access_receipt_id=? AND outcome='granted') AS n", (receipt.access_receipt_id,) * 3)
    return 'sealed_audit_access_exhausted' if rows[0]['n'] >= receipt.max_reads else None


async def _access_event(backend: Any, receipt: Any, query_hash: str, denial: str | None, now: float) -> str:
    payload = dict(schema_version=1, event_id='operation-audit-access-' + uuid4().hex,
                   access_receipt_id=receipt.access_receipt_id, query_hash=query_hash,
                   outcome='denied' if denial else 'granted',
                   reason_code=denial or 'operation_audit_access_granted', occurred_at=now)
    digest = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    await backend.connection.execute('INSERT INTO audit_trace_access_events(event_id,access_receipt_id,query_hash,outcome,reason_code,occurred_at,event_hash) VALUES(?,?,?,?,?,?,?)', (*[payload[k] for k in ('event_id', 'access_receipt_id', 'query_hash', 'outcome', 'reason_code', 'occurred_at')], digest))
    return digest


async def read_operation_audit(backend: Any, *, requester: Any, target_principal: Any,
                               access_receipt: Any, limit: int = 100,
                               cursor: OperationAuditCursor | None = None,
                               expected: tuple[OperationAuditExpectation, ...] = ()) -> OperationAuditPage:
    from simple_harness_memory.backends.upgrade_validation import validate_backend
    from simple_harness_memory.core.identity import MemoryPrincipal
    from simple_harness_memory.core.suppression import SealedAuditAccessReceipt

    if type(requester) is not MemoryPrincipal or type(target_principal) is not MemoryPrincipal or type(access_receipt) is not SealedAuditAccessReceipt:
        raise TypeError('operation audit requires public principal and sealed receipt types')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise MemoryValidationError('operation_audit_limit_invalid')
    if type(expected) is not tuple or len(expected) > 100 or any(type(v) is not OperationAuditExpectation for v in expected):
        raise MemoryValidationError('operation_audit_expectations_invalid')
    if cursor is not None and type(cursor) is not OperationAuditCursor:
        raise MemoryValidationError('operation_audit_cursor_invalid')
    principal_hash = _principal(target_principal)
    query = dict(schema_version=1, requester_ref_hash=_principal(requester), target_ref_hash=principal_hash,
                 access_receipt_hash=access_receipt.receipt_hash, expected=[v.to_json() for v in expected], coverage_version=COVERAGE_VERSION)
    query_hash = _hash('memory.operation.audit.query.v1', query)
    async with backend._write_lock:
        await backend._authorize_short_horizon_principal_unlocked(requester)
        await backend._authorize_short_horizon_principal_unlocked(target_principal)
        db = backend.connection
        await db.execute('BEGIN IMMEDIATE')
        try:
            now = float(backend._now())
            denial = await _denial(backend, requester, target_principal, access_receipt, now)
            if denial:
                await _access_event(backend, access_receipt, query_hash, denial, now)
                await db.execute('COMMIT')
                raise SealedAuditAccessDenied(denial)
            cut = None if cursor is None else _decode(backend, cursor, query_hash)
            lanes, cuts = await _capture(backend, target_principal.actor_id, cut)
            # Current integrity validation cannot supply historical coverage state.
            await validate_backend(backend)
            support = await _support(backend, lanes, target_principal.actor_id)
            support_hash = _root(support)
            if cut is not None and cut['support_root_hash'] != support_hash:
                raise MemoryCorruptionError('operation_audit_pinned_support_differs')
            items = await _items(backend, lanes, support)
            unresolved_jobs, missing_jobs = _job_findings(lanes['job_transition'], support)
            terminal_attempts = {r['attempt_id'] for r in lanes['typed_terminal']}
            unresolved_typed = tuple(sorted(ref('recall_attempt', r['attempt_id']) for r in lanes['typed_attempt'] if r['attempt_id'] not in terminal_attempts))
            coverage = tuple(OperationAuditCoverage(family, cuts[i][1], cuts[i][2], _KINDS[i], _EXCLUSIONS[i],
                unresolved_jobs if family == 'job_transition' else unresolved_typed if family == 'typed_attempt' else (),
                missing_jobs if family == 'job_transition' else ()) for i, family in enumerate(FAMILIES))
            flat = [v for family in FAMILIES for v in items[family]]
            seen = {(v.family, v.event_ref_hash): v.receipt_hash for v in flat}
            findings = tuple(OperationAuditExpectationResult(v, 'matched' if seen.get((v.family, v.event_ref_hash)) == v.receipt_hash else 'mismatched' if (v.family, v.event_ref_hash) in seen else 'missing') for v in expected)
            offset = 0 if cut is None else cut['offset']
            if offset > len(flat):
                raise MemoryValidationError('operation_audit_cursor_invalid')
            payload = dict(schema_version=1, query_hash=query_hash, cuts=cuts, support_root_hash=support_hash, offset=offset + limit)
            next_cursor = _cursor(backend, payload) if offset + limit < len(flat) else None
            snapshot_hash = _hash('memory.operation.audit.snapshot.v1', dict(query_hash=query_hash, cuts=cuts, support_root_hash=support_hash, coverage=[v.to_json() for v in coverage]))
            event_hash = await _access_event(backend, access_receipt, query_hash, None, now)
            page = OperationAuditPage(principal_hash, snapshot_hash, tuple(flat[offset:offset+limit]), coverage, findings, next_cursor, event_hash)
            await db.execute('COMMIT')
            return page
        except BaseException:
            if db.in_transaction:
                await db.execute('ROLLBACK')
            raise
