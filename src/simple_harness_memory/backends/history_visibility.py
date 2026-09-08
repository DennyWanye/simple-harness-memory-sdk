"""SQLite history checks sharing the backend's suppression and admission authority.

All helpers run under the caller's existing lock; batch checks additionally hold a
read transaction. Host proves dependency completeness. No new grants or writes.
"""

from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, cast

from simple_harness import DisclosureContext, TypedRecallResultV1
from simple_harness.contracts import JsonValue

from simple_harness_memory.backends.sqlite_tx import (
    begin_transaction,
    rollback_transaction,
)

from simple_harness_memory.backends.history_source_guard import (
    denial_reason,
    history_source_operation,
    prepare_history_source_context,
    proof_hashes,
)
from simple_harness_memory.core.errors import MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.evidence import validate_sanitized_evidence
from simple_harness_memory.core.history import (
    HistoryBinding,
    HistoryEvidenceBinding,
    HistoryRecallBinding,
    HistoryShortHorizonBinding,
    HistoryProcedureDraftBinding,
    HistoryVisibilityItem,
    HistoryVisibilitySnapshot,
    ProcedureApplicabilityAttestation,
    ProcedureApplicabilityReceipt,
    history_hash,
)
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose, SuppressionCandidate


async def _lineage_rows(cursor: Any, budget: list[int]) -> AsyncIterator[Any]:
    # fetchmany bounds Python materialization; the shared counter covers high
    # fanout/revision rows as well as nodes. It is not a SQLite CPU/IO deadline.
    while rows := await cursor.fetchmany(128):
        for row in rows:
            budget[0] += 1
            if budget[0] > 4096:
                raise MemoryLimitError("history_lineage_row_limit")
            yield row


async def evidence_targets(backend: Any, subject: str, evidence_id: str) -> set[tuple[str, str]]:
    """Canonical upstream evidence plus its reverse support, across all revisions.

    Iterative traversal terminates cycles. Never follow reverse edges into unrelated
    descendants or siblings. Targets belong to this subject, even for shared evidence.
    """
    targets: set[tuple[str, str]] = set()
    budget = [0]
    pending = [evidence_id]
    visited: set[str] = set()
    while pending:
        eid = pending.pop()
        if eid in visited:
            continue
        visited.add(eid)
        if len(visited) > 4096:
            raise MemoryLimitError("history_lineage_limit")
        targets.add(("evidence", eid))
        async with backend._db.execute(
            "SELECT l.target_evidence_id FROM evidence_links l "
            "JOIN evidence_envelopes e ON e.evidence_id=l.evidence_id "
            "JOIN evidence_envelopes p ON p.evidence_id=l.target_evidence_id "
            "WHERE l.evidence_id=? AND e.subject=? AND p.subject=? "
            "AND p.envelope_hash=l.target_content_hash",
            (eid, subject, subject),
        ) as cursor:
            async for row in _lineage_rows(cursor, budget):
                pending.append(str(row[0]))
    # A memory may support a derived evidence node, whose ancestors are the
    # original USER messages. Walk reverse edges solely to discover memory/entity
    # targets; do not turn descendant evidence IDs into direct evidence targets.
    pending = list(visited)
    descendants: set[str] = set()
    while pending:
        eid = pending.pop()
        if eid in descendants:
            continue
        descendants.add(eid)
        if len(descendants) > 4096:
            raise MemoryLimitError("history_lineage_limit")
        async with backend._db.execute(
            "SELECT l.evidence_id FROM evidence_links l "
            "JOIN evidence_envelopes e ON e.evidence_id=l.evidence_id "
            "JOIN evidence_envelopes p ON p.evidence_id=l.target_evidence_id "
            "WHERE l.target_evidence_id=? AND e.subject=? AND p.subject=? "
            "AND p.envelope_hash=l.target_content_hash",
            (eid, subject, subject),
        ) as cursor:
            async for row in _lineage_rows(cursor, budget):
                pending.append(str(row[0]))
        async with backend._db.execute(
            "SELECT DISTINCT s.memory_id,r.content_json FROM cognitive_evidence_spans s "
            "JOIN cognitive_memory_heads h ON h.memory_id=s.memory_id "
            "JOIN cognitive_memory_revisions r ON r.memory_id=s.memory_id "
            "AND r.revision=s.revision "
            "WHERE s.evidence_id=? AND h.principal_id=?",
            (eid, subject),
        ) as cursor:
            async for row in _lineage_rows(cursor, budget):
                targets.add(("memory", str(row[0])))
                targets.update(
                    ("entity", entity)
                    for entity in backend._mutation_entity_ids_from_content_json(str(row[1]))
                )
        async with backend._db.execute(
            "SELECT entities_json FROM conversation_evidence_registrations "
            "WHERE evidence_id=? AND principal_id=?",
            (eid, subject),
        ) as cursor:
            async for row in _lineage_rows(cursor, budget):
                targets.update(("entity", entity) for entity in json.loads(str(row[0])))
    return targets


@dataclass
class _EvidenceWork:
    now: float
    memo: dict[tuple[str, str, str], str] = field(default_factory=dict)
    work: int = 0


async def _evidence(
    backend: Any,
    principal: MemoryPrincipal,
    context: DisclosureContext,
    binding: HistoryEvidenceBinding,
    batch: dict[str, HistoryEvidenceBinding],
    work: _EvidenceWork,
    seen: frozenset[str] = frozenset(),
) -> str:
    key = (
        binding.envelope.evidence_id,
        binding.envelope.envelope_hash,
        binding.receipt.receipt_hash,
    )
    if key in work.memo:
        return work.memo[key]
    work.work += 1 + len(binding.envelope.evidence_refs)
    if work.work > 4096:
        raise MemoryLimitError("history_lineage_work_limit")
    reason = await _evidence_uncached(backend, principal, context, binding, batch, work, seen)
    work.memo[key] = reason
    return reason


async def _evidence_uncached(
    backend: Any,
    principal: MemoryPrincipal,
    context: DisclosureContext,
    binding: HistoryEvidenceBinding,
    batch: dict[str, HistoryEvidenceBinding],
    work: _EvidenceWork,
    seen: frozenset[str] = frozenset(),
) -> str:
    reason = await _evidence_source_checks(backend, principal, context, binding, batch, work, seen)
    if reason != "history_visible":
        return reason
    envelope = binding.envelope
    policy = backend._classification_policy
    if policy is None:
        return "history_classification_unverifiable"
    # S1 proves sanitation, not permission to disclose arbitrary personal text to others.
    # Without item-level authority, admit only the authenticated subject's own audience.
    if context.recipient.value != "user_self" or context.recipient_id != principal.actor_id:
        return "history_disclosure_denied"
    if not backend._candidate_disclosure_allowed(
        context,
        policy.required_privacy_class.value,
        tuple(item.value for item in policy.required_information_attributes),
    ):
        return "history_disclosure_denied"
    async with backend._db.execute(
        "SELECT DISTINCT r.effective_privacy_class,r.information_attributes_json "
        "FROM cognitive_evidence_spans s JOIN cognitive_memory_heads h "
        "ON h.memory_id=s.memory_id JOIN cognitive_memory_revisions r "
        "ON r.memory_id=s.memory_id AND r.revision=s.revision "
        "WHERE s.evidence_id=? AND h.principal_id=?",
        (envelope.evidence_id, principal.actor_id),
    ) as cursor:
        for row in await cursor.fetchall():
            if not backend._candidate_disclosure_allowed(
                context, str(row[0]), tuple(json.loads(str(row[1])))
            ):
                return "history_disclosure_denied"
    async with backend._db.execute(
        "SELECT effective_privacy_class,information_attributes_json "
        "FROM conversation_evidence_registrations WHERE evidence_id=? AND principal_id=?",
        (envelope.evidence_id, principal.actor_id),
    ) as cursor:
        row = await cursor.fetchone()
        if (
            row is not None
            and row[0] is not None
            and not backend._candidate_disclosure_allowed(
                context, str(row[0]), tuple(json.loads(str(row[1])))
            )
        ):
            return "history_disclosure_denied"
    return "history_visible"


async def _evidence_source_checks(
    backend, principal, context, binding, batch, work, seen,
):
    """Shared S1/canonical/upstream/reverse-suppression checks; not a use grant."""
    if len(seen) >= 64:
        return "history_lineage_limit"
    envelope, receipt = binding.envelope, binding.receipt
    validate_sanitized_evidence(
        envelope, receipt, supported_filter_policies=backend._supported_filter_policies
    )
    if envelope.subject != principal.actor_id:
        return "history_subject_mismatch"
    if envelope.evidence_id in seen:
        return "history_lineage_cycle"
    canonical = await backend._read_ingestion_by_source(envelope.subject, envelope.source_ref)
    if canonical is not None and canonical.evidence_id != envelope.evidence_id:
        return "history_binding_mismatch"
    admitted = await backend._read_ingestion_by_admission_receipt(receipt.receipt_id)
    if admitted is not None and (
        admitted.evidence_id != envelope.evidence_id
        or admitted.admission_receipt_hash != receipt.receipt_hash
    ):
        return "history_binding_mismatch"
    source_records = await backend._read_source_admission_binding(
        subject=envelope.subject, source_ref=envelope.source_ref,
        admission_receipt_id=receipt.receipt_id
    )
    if any(r.envelope != envelope or r.admission_receipt != receipt for r in source_records):
        return "history_binding_mismatch"
    record = await backend._read_ingested_record(envelope.evidence_id)
    if record is not None and (record.envelope != envelope or record.admission_receipt != receipt):
        return "history_binding_mismatch"
    # Check all explicitly evidenced dependencies, including pending siblings in this batch.
    for ref in envelope.evidence_refs:
        parent = batch.get(ref.evidence_id)
        if parent is None:
            stored = await backend._read_ingested_record(ref.evidence_id)
            if stored is None:
                return "history_lineage_unverifiable"
            parent = HistoryEvidenceBinding(stored.envelope, stored.admission_receipt)
        if parent.envelope.envelope_hash != ref.content_hash:
            return "history_binding_mismatch"
        reason = await _evidence(
            backend, principal, context, parent, batch, work, seen | {envelope.evidence_id}
        )
        if reason != "history_visible":
            return reason
    if (
        await backend._resolve_suppression_unlocked(
            SuppressionCandidate(principal.actor_id, evidence_id=envelope.evidence_id),
            _purpose(context),
            evaluated_at=work.now,
        )
    ).denied:
        return denial_reason(backend, envelope.evidence_id)
    return "history_visible"


def _purpose(context: DisclosureContext) -> OrdinaryMemoryPurpose:
    return (
        OrdinaryMemoryPurpose.READ
        if context.purpose.value == "user_review"
        else OrdinaryMemoryPurpose.RECALL
    )


@dataclass
class _Applicability:
    """One call's presented offline attestation, plus what it actually admitted.

    ``admitted`` is reset by the batch loop before every binding, so the receipt names
    exactly the bindings this attestation carried, in the caller's binding order.
    """

    fingerprints: frozenset[str]
    admitted: bool = False


async def _applied_procedure_applicability(
    backend: Any, memory_id: str, revision: int, fingerprints: frozenset[str]
) -> bool:
    """Corroborate an offline attestation against Memory's own observation audit.

    0.6.36 (F-S1b).  The presented set is caller-controlled, so on its own it would
    degrade the Procedure applicability gate to "the caller says yes".  ``procedure_uses``
    lives in the Host; ``procedure_observations`` is Memory's own append-only,
    immutable-triggered record of the observations it consumed.  A Procedure endpoint is
    therefore admitted offline only where its bound fingerprint is (a) not the unbound
    sentinel, (b) presented by the caller, and (c) carried by at least one successful,
    attributable observation Memory itself committed for that memory.  Set membership and
    ``EXISTS`` are order-free, so the answer does not depend on row order or clocks.

    What this does **not** re-derive is "still applicable *now*": there is no live tool
    set off-Run.  See S3 §2-补2 for the adjudication of that trade.
    """

    from simple_harness_memory.core.lifecycle_results import UNBOUND_PROCEDURE_APPLICABILITY

    async with backend._db.execute(
        "SELECT applicability_fingerprint FROM procedure_records WHERE memory_id=? AND revision=?",
        (memory_id, revision),
    ) as cursor:
        record = await cursor.fetchone()
    if record is None:
        return False
    fingerprint = str(record[0])
    if fingerprint == UNBOUND_PROCEDURE_APPLICABILITY or fingerprint not in fingerprints:
        return False
    async with backend._db.execute(
        "SELECT 1 FROM procedure_observations WHERE memory_id=? AND applicability_fingerprint=? "
        "AND outcome='success' AND attributable=1 LIMIT 1",
        (memory_id, fingerprint),
    ) as cursor:
        return await cursor.fetchone() is not None


async def _recall(
    backend: Any,
    principal: MemoryPrincipal,
    context: DisclosureContext,
    binding: HistoryRecallBinding,
    now: float,
    *, sources: list[Any] | None = None,
    applicability: _Applicability | None = None,
) -> tuple[str, float | None]:
    async with backend._db.execute(
        "SELECT r.result_json,r.result_hash FROM typed_recall_results r "
        "JOIN typed_recall_requests q ON q.request_id=r.request_id "
        "WHERE r.result_id=? AND q.principal_id=?",
        (binding.result_id, principal.actor_id),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or str(row[1]) != binding.result_hash:
        return "history_binding_mismatch", None
    result = TypedRecallResultV1.from_json(json.loads(str(row[0])))
    if result.result_hash != binding.result_hash or (
        sources is not None and result.result_id != binding.result_id
    ):
        return "history_binding_mismatch", None
    item = next((x for x in result.items if x.selected_item.item_id == binding.item_id), None)
    revalidated = frozenset({binding.item_id})
    if item is not None:
        if item.result_item_hash != binding.item_hash:
            return "history_binding_mismatch", None
        source = item.selected_item
    else:
        # 0.6.31（F-O-1）：confirmation group 的成员同样是该 durable result 里已向模型披露的
        # exact item（S3 §5.1 `RECALL_CONFIRMATION` fragment 带完整 binding），因此可以被
        # 历史绑定。绑定按 `result_member_hash` 逐字核对；成员的重校验走同一
        # `_validate_recall_context_use_sources_unlocked` 的 confirmation 分支（要求 group
        # 仍 active、head 仍为 challenger、无 resolution），任一不成立即 stale。
        member = None
        for group in result.confirmation_groups:
            for x in group.members:
                if x.member.item_id == binding.item_id:
                    member = x
                    # §5.2 整组原子：任何一侧不可见即整组不可见，所以重校验的是整个 group。
                    revalidated = frozenset(y.member.item_id for y in group.members)
        if member is None or member.result_member_hash != binding.item_hash:
            return "history_binding_mismatch", None
        source = member.member
    # A source-expansion request is strictly short-only. Never expose cognitive
    # lineage even though ordinary history visibility also accepts cognitive items.
    if sources is not None and (
        item is None or item.selected_item.source_kind.value != "short_horizon"
    ):
        return "history_binding_mismatch", None
    # Existing source checker enforces head/status/type/hash/expiry/current disclosure.
    # Never reuse the old runtime fingerprints a stored RecallContext happened to carry:
    # the only applicability admitted here is one the caller presented for THIS call, with
    # an explicit provenance (0.6.36 / F-S1b). Absent one, the set stays empty and every
    # Procedure source is stale exactly as it was through 0.6.35.
    try:
        await backend._validate_recall_context_use_sources_unlocked(
            principal_id=principal.actor_id,
            result=result,
            decision=SimpleNamespace(disclosure_context=context),
            supplied_item_ids=revalidated,
            procedure_applicability_fingerprints=(
                frozenset() if applicability is None else applicability.fingerprints
            ),
            now=now,
            suppression_purpose=_purpose(context),
        )
    except MemoryValidationError as exc:
        if str(exc) != "RECALL_AUTHORITY_STALE":
            raise
        return "history_source_stale", None
    policy = backend._classification_policy
    if policy is None or not backend._candidate_disclosure_allowed(
        context,
        policy.required_privacy_class.value,
        tuple(x.value for x in policy.required_information_attributes),
    ):
        return "history_disclosure_denied", None
    if sources is not None:
        from simple_harness_memory.backends.short_history_visibility import check_selected_chunk

        return await check_selected_chunk(
            backend, principal, context, chunk_ref=source.source_ref,
            content_hash=source.source_content_hash, now=now, sources=sources,
        )
    # confirmation 成员没有 source_kind 字段：它按 §5.1 只能是认知记忆（带 exact revision）。
    if item is None or source.source_kind.value == "cognitive_memory":
        async with backend._db.execute(
            "SELECT r.valid_to,h.memory_type FROM cognitive_memory_revisions r "
            "JOIN cognitive_memory_heads h ON h.memory_id=r.memory_id "
            "WHERE r.memory_id=? AND r.revision=?",
            (source.source_ref, source.source_revision),
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None and str(row[1]) == "procedure":
            # Only an attestation can have got a Procedure this far (the gate above reads
            # an empty set otherwise), so this is where the widening is paid for: the
            # presented fingerprint must also be one Memory itself observed.
            if applicability is None or not await _applied_procedure_applicability(
                backend, source.source_ref, int(source.source_revision),
                applicability.fingerprints,
            ):
                return "history_source_stale", None
            applicability.admitted = True
    else:
        async with backend._db.execute(
            "SELECT expires_at FROM short_horizon_chunks WHERE chunk_id=?", (source.source_ref,)
        ) as cursor:
            row = await cursor.fetchone()
    return "history_visible", None if row is None or row[0] is None else float(row[0])


@history_source_operation
async def check_history_visibility(
    backend: Any,
    *,
    principal: MemoryPrincipal,
    disclosure_context: DisclosureContext,
    bindings: tuple[HistoryBinding, ...],
    procedure_applicability: ProcedureApplicabilityAttestation | None = None,
    _short_sources: list[tuple[Any, ...]] | None = None,
    _require_principal_binding: bool = False,
    _current_input: tuple[HistoryEvidenceBinding, str] | None = None,
) -> HistoryVisibilitySnapshot:
    if type(principal) is not MemoryPrincipal or type(disclosure_context) is not DisclosureContext:
        raise TypeError("history requires canonical principal and DisclosureContext")
    if procedure_applicability is not None and (
        type(procedure_applicability) is not ProcedureApplicabilityAttestation
    ):
        raise TypeError("history requires a canonical ProcedureApplicabilityAttestation")
    if procedure_applicability is not None and _current_input is not None:
        # The current-input entry point observes one exact request item and grants no
        # ordinary disclosure at all; it must never become a second door for Procedures.
        raise MemoryValidationError("history_current_input_rejects_procedure_applicability")
    applicability = (
        None
        if procedure_applicability is None
        else _Applicability(frozenset(procedure_applicability.fingerprints))
    )
    context = DisclosureContext.from_json(disclosure_context.to_json())
    if type(bindings) is not tuple or not 1 <= len(bindings) <= 256:
        raise MemoryLimitError("history_batch_requires_1_to_256_bindings")
    batch: dict[str, HistoryEvidenceBinding] = {}
    identities: dict[tuple[str, ...], HistoryEvidenceBinding] = {}
    hashes = []
    for binding in bindings:
        if type(binding) not in (
            HistoryEvidenceBinding,
            HistoryRecallBinding,
            HistoryShortHorizonBinding,
            HistoryProcedureDraftBinding,
        ):
            raise TypeError("history binding type invalid")
        if isinstance(binding, HistoryEvidenceBinding):
            validate_sanitized_evidence(
                binding.envelope,
                binding.receipt,
                supported_filter_policies=backend._supported_filter_policies,
            )
            eid = binding.envelope.evidence_id
            if eid in batch and batch[eid] != binding:
                raise MemoryValidationError("history_duplicate_identity_conflict")
            for identity in (
                ("source", binding.envelope.subject, binding.envelope.source_ref),
                ("admission", binding.receipt.receipt_id),
            ):
                if identity in identities and identities[identity] != binding:
                    raise MemoryValidationError("history_duplicate_identity_conflict")
                identities[identity] = binding
            batch[eid] = binding
        hashes.append(history_hash("memory.history.binding.v1", binding.to_json()))
    if backend._db is None or backend._receipt is None:
        raise RuntimeError("human-memory v7 backend is not initialized")
    await prepare_history_source_context(backend, principal, pending=tuple(batch.values()))
    async with backend._write_lock:
        await begin_transaction(backend._db, "BEGIN")
        try:
            async with backend._db.execute(
                "SELECT deployment_id,household_id,actor_id FROM principals WHERE principal_id=?",
                (principal.actor_id,),
            ) as cursor:
                registered = await cursor.fetchone()
                # S1 ingestion uses subject-only placeholder identity. Match the existing
                # mutation admission convention without promoting it during a read.
                if _current_input is not None or (registered is not None and (
                    _require_principal_binding or tuple(registered) != (principal.actor_id,) * 3
                )):
                    await backend._authorize_short_horizon_principal_unlocked(principal)
            now = float(backend._now())
            if not math.isfinite(now) or now < 0:
                raise MemoryValidationError("history_clock_invalid")
            async with backend._db.execute(
                "SELECT authority_epoch,policy_hash FROM recall_authority_heads "
                "WHERE principal_id=?",
                (principal.actor_id,),
            ) as cursor:
                authority = await cursor.fetchone()
            policy_hash = history_hash(
                "memory.history.policy.v1",
                {
                    "recall_policy": None if authority is None else str(authority[1]),
                    "classification": None
                    if backend._classification_policy is None
                    else backend._classification_policy.policy_hash,
                },
            )
            if _current_input is not None:
                policy_hash = history_hash("memory.current-input.batch-policy.v1", {
                    "ordinary_policy": policy_hash, "input_authority_hash": _current_input[1]})
            items = []
            deadlines = []
            admitted: list[str] = []
            work = _EvidenceWork(now)
            for binding, binding_hash in zip(bindings, hashes, strict=True):
                deadline = None
                if applicability is not None:
                    applicability.admitted = False
                sources: list[Any] | None = [] if _short_sources is not None else None
                if context.subject != principal.actor_id:
                    reason = "history_subject_mismatch"
                elif _current_input is not None and type(binding) is HistoryEvidenceBinding and binding == _current_input[0]:
                    # Only the new purpose-verifying entry point supplies this
                    # exact non-inheritable item. Parents/recall/short remain ordinary.
                    reason = await _evidence_source_checks(backend, principal, context,
                        binding, batch, work, frozenset())
                elif (
                    not backend._ordinary_recall_disclosure_allowed(context)
                    or (
                        context.recipient.value == "user_self"
                        and context.recipient_id != principal.actor_id
                    )
                ):
                    reason = "history_disclosure_denied"
                elif isinstance(binding, HistoryEvidenceBinding):
                    reason = await _evidence(backend, principal, context, binding, batch, work)
                elif isinstance(binding, HistoryProcedureDraftBinding):
                    from simple_harness_memory.backends.procedure_discovery import read_candidate
                    candidate, deadline = await read_candidate(backend, principal, context,
                        binding.memory_id, binding.revision, now, work)
                    reason = "history_visible" if candidate is not None and candidate.source_hash == binding.candidate_hash else "history_source_stale"
                elif isinstance(binding, HistoryShortHorizonBinding):
                    from simple_harness_memory.backends.short_history_visibility import check_short

                    try:
                        reason, deadline = await check_short(
                            backend, principal, context, binding, now, sources=sources)
                    except MemoryLimitError:
                        if _short_sources is None:
                            raise
                        reason, deadline = "history_lineage_unverifiable", None
                        sources = []
                else:
                    try:
                        reason, deadline = await _recall(
                            backend, principal, context, binding, now, sources=sources,
                            applicability=applicability)
                    except MemoryLimitError:
                        if _short_sources is None:
                            raise
                        reason, deadline = "history_lineage_unverifiable", None
                        sources = []
                items.append(
                    HistoryVisibilityItem(binding_hash, reason == "history_visible", reason)
                )
                if (
                    applicability is not None
                    and applicability.admitted
                    and reason == "history_visible"
                ):
                    admitted.append(binding_hash)
                if _short_sources is not None:
                    _short_sources.append(tuple(sources or ()))
                if deadline is not None:
                    deadlines.append(deadline)
            snapshot = HistoryVisibilitySnapshot(
                principal.actor_id,
                history_hash(
                    "memory.history.request.v1",
                    {
                        "principal": asdict(principal),
                        "disclosure": context.to_json(),
                        "bindings": cast(JsonValue, hashes),
                        **({"input_authority_hash": _current_input[1]} if _current_input is not None else {}),
                        **(
                            {}
                            if procedure_applicability is None
                            else {"procedure_applicability": procedure_applicability.to_json()}
                        ),
                    },
                ),
                now,
                min(deadlines) if deadlines else None,
                0 if authority is None else int(authority[0]),
                history_hash("memory.history.source-policy.v1", {
                    "ordinary_policy": policy_hash, "source_proofs": proof_hashes(backend),
                }) if proof_hashes(backend) else policy_hash,
                tuple(items),
                procedure_applicability=(
                    None
                    if procedure_applicability is None
                    else ProcedureApplicabilityReceipt(
                        procedure_applicability.provenance.value,
                        procedure_applicability.attestation_hash,
                        len(procedure_applicability.fingerprints),
                        tuple(admitted),
                    )
                ),
            )
            await backend._db.execute("COMMIT")
            return snapshot
        except BaseException:
            await rollback_transaction(backend._db)
            raise


async def resolve_short_horizon_sources(
    backend: Any, *, principal: MemoryPrincipal, disclosure_context: DisclosureContext,
    bindings: tuple[HistoryShortHorizonBinding, ...],
):
    from simple_harness_memory.core.short_sources import (
        ShortHorizonSourceItem,
        ShortHorizonSourceSnapshot,
    )

    if type(bindings) is not tuple or any(
        type(x) is not HistoryShortHorizonBinding for x in bindings
    ):
        raise TypeError("short sources require exact HistoryShortHorizonBinding tuple")
    sources: list[tuple[Any, ...]] = []
    observed = await check_history_visibility(
        backend, principal=principal, disclosure_context=disclosure_context,
        bindings=bindings, _short_sources=sources)
    return ShortHorizonSourceSnapshot(
        subject=observed.subject,
        request_hash=history_hash("memory.short.sources.request.v1", {
            "principal": asdict(principal), "disclosure": disclosure_context.to_json(),
            "bindings": [binding.to_json() for binding in bindings]}),
        evaluated_at=observed.checked_at, authority_epoch=observed.authority_epoch,
        policy_hash=observed.policy_hash, valid_until=observed.valid_until,
        items=tuple(ShortHorizonSourceItem(
            history_hash("memory.short.sources.binding.v1", binding.to_json()),
            item.visible, item.reason, item.visible, refs)
            for binding, item, refs in zip(bindings, observed.items, sources, strict=True)))


async def resolve_typed_short_horizon_sources(
    backend: Any, *, principal: MemoryPrincipal, disclosure_context: DisclosureContext,
    bindings: tuple[HistoryRecallBinding, ...],
):
    """Expand only exact selected typed-short items in one current read transaction."""
    from simple_harness_memory.core.short_sources import (
        ShortHorizonSourceItem, ShortHorizonSourceSnapshot,
    )

    if type(bindings) is not tuple or any(type(x) is not HistoryRecallBinding for x in bindings):
        raise TypeError("typed short sources require exact HistoryRecallBinding tuple")
    sources: list[tuple[Any, ...]] = []
    observed = await check_history_visibility(
        backend, principal=principal, disclosure_context=disclosure_context,
        bindings=bindings, _short_sources=sources, _require_principal_binding=True,
    )
    return ShortHorizonSourceSnapshot(
        subject=observed.subject,
        request_hash=history_hash("memory.typed.short.sources.request.v1", {
            "principal": asdict(principal), "disclosure": disclosure_context.to_json(),
            "bindings": [binding.to_json() for binding in bindings],
        }),
        evaluated_at=observed.checked_at, authority_epoch=observed.authority_epoch,
        policy_hash=observed.policy_hash, valid_until=observed.valid_until,
        items=tuple(ShortHorizonSourceItem(
            history_hash("memory.typed.short.sources.binding.v1", binding.to_json()),
            item.visible, item.reason, item.visible, refs,
        ) for binding, item, refs in zip(bindings, observed.items, sources, strict=True)),
    )
