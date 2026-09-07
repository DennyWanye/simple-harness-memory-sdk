"""Operation-local Host facts plus current SQLite suppression, without a new ledger.

Only prepare calls Host, after releasing the database lock/transaction. Final checks
run in the existing candidate resolver and never call out. No equality grants use.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any

from simple_harness import EvidenceSourceKind

from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError
from simple_harness_memory.core.evidence import validate_sanitized_evidence
from simple_harness_memory.core.history import HistoryEvidenceBinding, history_hash
from simple_harness_memory.core.history_sources import (
    HistoryForgetCutReceipt,
    HistorySourceOriginReceipt,
)
from simple_harness_memory.core.identity import MemoryPrincipal

PROFILE = "user-message-text-exact/v1"
UNVERIFIABLE = "history_source_cut_unverifiable"


@dataclass
class _Operation:
    backend: Any
    pending: dict[str, HistoryEvidenceBinding] = field(default_factory=dict)
    origins: dict[str, HistorySourceOriginReceipt | None] = field(default_factory=dict)
    cuts: dict[str, HistoryForgetCutReceipt | None] = field(default_factory=dict)
    # Current catalog is first read AFTER Host prefetch; writes invalidate it.
    catalogs: dict[str, tuple[tuple[int, int], Any]] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    proof_hashes: set[str] = field(default_factory=set)


_active: ContextVar[_Operation | None] = ContextVar("history_source_operation", default=None)


def history_source_operation(method):
    """Establish invocation lifetime only; no reads before public admission checks."""
    @wraps(method)
    async def invoke(backend, *args, **kwargs):
        token = _active.set(_Operation(backend))
        try:
            return await method(backend, *args, **kwargs)
        finally:
            _active.reset(token)
    return invoke


def _work(backend):
    work = _active.get()
    return work if work is not None and work.backend is backend else None


def _identity(binding):
    return history_hash("memory.history.binding.v1", binding.to_json())


def exact_user_key(binding):
    """Fixed full /text profile, never display text or arbitrary recursive fields."""
    env = binding.envelope
    if env.source_kind is not EvidenceSourceKind.USER_MESSAGE:
        return None
    text = env.sanitized_payload.get("text")
    if type(text) is not str:
        return None
    return history_hash("memory.history.user-source-equivalence.v1", {
        "profile": PROFILE, "subject": env.subject,
        "source_kind": "user_message", "text": text,
    })


def _charge(budget):
    budget[0] += 1
    if budget[0] > 4096:
        raise MemoryLimitError("history_source_work_limit")


async def _ancestors(backend, subject, ids, pending, budget):
    stack = [(eid, None) for eid in ids]
    found: dict[str, HistoryEvidenceBinding] = {}
    while stack:
        _charge(budget)
        eid, expected_hash = stack.pop()
        binding = found.get(eid) or pending.get(eid)
        if binding is None:
            record = await backend._read_ingested_record(eid)
            if record is None:
                raise MemoryCorruptionError("history_source_lineage_missing")
            binding = HistoryEvidenceBinding(record.envelope, record.admission_receipt)
        validate_sanitized_evidence(
            binding.envelope, binding.receipt,
            supported_filter_policies=backend._supported_filter_policies,
        )
        if binding.envelope.subject != subject or (
            expected_hash is not None and binding.envelope.envelope_hash != expected_hash
        ):
            raise MemoryCorruptionError("history_source_lineage_binding_differs")
        if eid in found:
            continue
        found[eid] = binding
        stack.extend((ref.evidence_id, ref.content_hash) for ref in binding.envelope.evidence_refs)
    return found


async def _memory_sources(backend, subject, memory_id, budget):
    sources = {}
    async with backend._db.execute(
        "SELECT s.evidence_id,s.envelope_hash,s.sanitized_hash,s.admission_receipt_id,"
        "s.admission_receipt_hash FROM cognitive_evidence_spans s "
        "JOIN cognitive_memory_heads h ON h.memory_id=s.memory_id "
        "JOIN cognitive_memory_revisions r ON r.memory_id=s.memory_id AND r.revision=s.revision "
        "WHERE h.principal_id=? AND s.memory_id=? ORDER BY s.revision,s.ordinal",
        (subject, memory_id),
    ) as cursor:
        rows = []
        async for row in cursor:
            _charge(budget)
            rows.append(tuple(row))
    for eid, eh, sh, rid, rh in rows:
        record = await backend._read_ingested_record(eid)
        if record is None or (
            record.envelope.subject, record.envelope.envelope_hash,
            record.envelope.sanitized_hash, record.admission_receipt.receipt_id,
            record.admission_receipt.receipt_hash,
        ) != (subject, eh, sh, rid, rh):
            raise MemoryCorruptionError("history_source_support_binding_differs")
        sources[eid] = HistoryEvidenceBinding(record.envelope, record.admission_receipt)
    return await _ancestors(backend, subject, sources, sources, budget)


async def _catalog(backend, subject):
    """Active canonical directives with all-revision USER seeds, bounded once per read."""
    budget = [0]
    async with backend._db.execute(
        "SELECT d.directive_id FROM suppression_directives d "
        "WHERE d.principal_id=? AND d.event_kind='directive' AND d.scope_kind='memory' "
        "AND NOT EXISTS(SELECT 1 FROM suppression_directives r "
        "WHERE r.event_kind='revoke' AND r.supersedes_directive_id=d.directive_id) "
        "ORDER BY d.directive_id", (subject,),
    ) as cursor:
        ids = []
        async for row in cursor:
            _charge(budget)
            ids.append(str(row[0]))
    entries = []
    for did in ids:
        decision = await backend._read_suppression_decision(did)
        if decision is None:
            raise MemoryCorruptionError("history_source_directive_missing")
        sources = await _memory_sources(backend, subject, decision.scope_ref, budget)
        for binding in sources.values():
            key = exact_user_key(binding)
            if key is not None:
                entries.append((decision, binding, key))
    return entries


async def _current_catalog(backend, subject):
    work = _work(backend)
    # total_changes alone misses other connections. PRAGMA data_version is
    # connection-local and rechecked at every final use, including across TXs.
    async with backend._db.execute("PRAGMA data_version") as cursor:
        row = await cursor.fetchone()
    version = (backend._db.total_changes, int(row[0]))
    cached = None if work is None else work.catalogs.get(subject)
    if cached is None or cached[0] != version:
        entries = await _catalog(backend, subject)
        if work is not None:
            work.catalogs[subject] = (version, entries)
        return entries
    return cached[1]


async def prepare_history_source_context(backend, principal, *, pending=()):
    """Prepare exact-key relevant source facts; no Host call in SQLite transaction.

The equality lookup reads only canonical USER /text equal to an actual seed. It
does not infer text/lineage from selected chunk formatting or add an alias table.
"""
    work = _work(backend)
    if work is None:
        raise RuntimeError("history_source_operation_context_required")
    if type(principal) is not MemoryPrincipal:
        raise TypeError("history source principal must use MemoryPrincipal")
    for binding in pending:
        validate_sanitized_evidence(
            binding.envelope, binding.receipt,
            supported_filter_policies=backend._supported_filter_policies,
        )
        if binding.envelope.subject == principal.actor_id:
            work.pending[binding.envelope.evidence_id] = binding
    authority = backend._history_source_authority
    if authority is None:
        return
    async with backend._write_lock:
        await backend._db.execute("BEGIN")
        try:
            async with backend._db.execute(
                "SELECT deployment_id,household_id,actor_id FROM principals WHERE principal_id=?",
                (principal.actor_id,),
            ) as cursor:
                registered = await cursor.fetchone()
            if registered is not None and tuple(registered) != (principal.actor_id,) * 3:
                await backend._authorize_short_horizon_principal_unlocked(principal)
            entries = await _catalog(backend, principal.actor_id)
            sources = {_identity(b): b for _, b, _ in entries}
            texts = {b.envelope.sanitized_payload["text"] for _, b, _ in entries}
            budget = [len(sources)]
            for text in texts:
                async with backend._db.execute(
                    "SELECT evidence_id FROM evidence_envelopes WHERE subject=? "
                    "AND source_kind='user_message' "
                    "AND json_type(sanitized_payload,'$.text')='text' "
                    "AND json_extract(sanitized_payload,'$.text')=?",
                    (principal.actor_id, text),
                ) as cursor:
                    ids = []
                    async for row in cursor:
                        _charge(budget)
                        ids.append(str(row[0]))
                for eid in ids:
                    record = await backend._read_ingested_record(eid)
                    if record is None:
                        raise MemoryCorruptionError("history_source_binding_missing")
                    binding = HistoryEvidenceBinding(record.envelope, record.admission_receipt)
                    sources[_identity(binding)] = binding
            # All pending bindings are already exact S1 validated, including cold USER.
            for binding in work.pending.values():
                text = binding.envelope.sanitized_payload.get("text")
                if type(text) is str and text in texts:
                    _charge(budget)
                    sources[_identity(binding)] = binding
            await backend._db.execute("COMMIT")
        except BaseException:
            await backend._db.execute("ROLLBACK")
            raise
    for decision, _, _ in entries:
        if decision.decision_hash in work.cuts:
            continue
        try:
            cut = await authority.resolve_history_forget_cut(principal=principal, decision=decision)
            if type(cut) is HistoryForgetCutReceipt:
                cut = HistoryForgetCutReceipt.from_json(cut.to_json())
        except Exception:
            cut = None
        work.cuts[decision.decision_hash] = (
            cut if type(cut) is HistoryForgetCutReceipt and (
                cut.namespace.subject, cut.request_id, cut.scope_kind, cut.scope_ref
            ) == (decision.subject, decision.request_id, decision.scope_kind, decision.scope_ref)
            else None
        )
    for identity, binding in sources.items():
        if identity in work.origins:
            continue
        try:
            origin = await authority.resolve_history_source(
                principal=principal, envelope=binding.envelope, receipt=binding.receipt,
            )
            if type(origin) is HistorySourceOriginReceipt:
                origin = HistorySourceOriginReceipt.from_json(origin.to_json())
        except Exception:
            origin = None
        work.origins[identity] = origin if _origin_matches(origin, binding) else None


def _origin_matches(origin, binding):
    return type(origin) is HistorySourceOriginReceipt and (
        origin.namespace.subject, origin.evidence_id, origin.envelope_hash,
        origin.admission_receipt_id, origin.admission_receipt_hash,
    ) == (
        binding.envelope.subject, binding.envelope.evidence_id, binding.envelope.envelope_hash,
        binding.receipt.receipt_id, binding.receipt.receipt_hash,
    )


async def duplicate_source_matches(backend, candidate, purpose):
    """Called only under the existing candidate lock/transaction; never external I/O."""
    work = _work(backend)
    entries = await _current_catalog(backend, candidate.subject)
    entries = [e for e in entries if e[0].purpose is None or e[0].purpose is purpose]
    if not entries:
        return set()
    pending = {} if work is None else work.pending
    budget = [0]
    bindings = {}
    if candidate.evidence_id is not None:
        record = pending.get(candidate.evidence_id)
        if record is None:
            stored = await backend._read_ingested_record(candidate.evidence_id)
            if stored is not None:
                record = HistoryEvidenceBinding(stored.envelope, stored.admission_receipt)
        if record is not None:
            bindings.update(await _ancestors(
                backend, candidate.subject, [candidate.evidence_id],
                {**pending, candidate.evidence_id: record}, budget,
            ))
    if candidate.memory_id is not None:
        bindings.update(await _memory_sources(
            backend, candidate.subject, candidate.memory_id, budget,
        ))
    matched: set[str] = set()
    unverifiable = False
    for binding in bindings.values():
        key = exact_user_key(binding)
        if key is None:
            # Alias scope is the declared /text profile, not every USER envelope.
            # Direct targets and actual ancestors still enforce their own gates.
            continue
        for decision, seed, seed_key in entries:
            if key != seed_key:
                continue
            if work is not None:
                work.proof_hashes.update((decision.decision_hash, _identity(seed)))
            origin = None if work is None else work.origins.get(_identity(binding))
            seed_origin = None if work is None else work.origins.get(_identity(seed))
            cut = None if work is None else work.cuts.get(decision.decision_hash)
            proved = (origin is not None and seed_origin is not None and cut is not None
                      and origin.namespace == seed_origin.namespace == cut.namespace
                      and seed_origin.source_sequence <= cut.through_sequence)
            if proved:
                assert work is not None and origin is not None
                assert seed_origin is not None and cut is not None
                work.proof_hashes.update((origin.origin_hash, seed_origin.origin_hash,
                                          cut.cut_hash, decision.decision_hash))
                if origin.source_sequence <= cut.through_sequence:
                    matched.add(decision.directive_id)
                elif origin.proof_kind != "atomic":
                    matched.add(decision.directive_id)
                    unverifiable = True
            else:
                matched.add(decision.directive_id)
                unverifiable = True
    if work is not None and matched and candidate.evidence_id is not None:
        work.reasons[candidate.evidence_id] = UNVERIFIABLE if unverifiable else "history_suppressed"
    return matched


def denial_reason(backend, evidence_id):
    work = _work(backend)
    return "history_suppressed" if work is None else work.reasons.get(
        evidence_id, "history_suppressed",
    )


def proof_hashes(backend):
    work = _work(backend)
    return [] if work is None else sorted(work.proof_hashes)
