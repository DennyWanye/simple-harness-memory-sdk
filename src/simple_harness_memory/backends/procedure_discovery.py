"""Read-only draft discovery and current-use revalidation in real SDK snapshots."""
import hashlib
import json
import math
from simple_harness import DisclosureContext
from simple_harness.contracts import canonical_json
from simple_harness.runtime import ProcedureMemoryPayload
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError, MemoryValidationError
from simple_harness_memory.core.history import HistoryEvidenceBinding
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.procedure_discovery import (
    DISCOVERABLE_LIFECYCLE_STATES, ProcedureDraftCandidate, ProcedureDraftPage)
from simple_harness_memory.features.lexical import typed_recall_query_terms
from simple_harness_memory.backends.history_source_guard import history_source_operation, prepare_history_source_context
from simple_harness_memory.backends.sqlite_tx import (
    begin_transaction,
    rollback_transaction,
)


def self_context(backend, principal, context):
    return (type(context) is DisclosureContext and context.subject == principal.actor_id
        and context.recipient.value == "user_self" and context.recipient_id == principal.actor_id
        and context.intended_audience.value == "user_self"
        and backend._ordinary_recall_disclosure_allowed(context))


async def read_candidate(backend, principal, context, memory_id, revision, now, work):
    """Caller owns SDK transaction. Reconstruct exact canonical preview, no stale cache."""
    from simple_harness_memory.backends.history_visibility import _evidence, _purpose
    from simple_harness_memory.core.suppression import SuppressionCandidate
    if not self_context(backend, principal, context):
        return None, None
    async with backend._db.execute(
        "SELECT r.*,p.name,p.steps_json,p.applicability_json,p.risk_level,p.qualification_epoch,p.applicability_fingerprint "
        "FROM cognitive_memory_heads h JOIN cognitive_memory_revisions r "
        "ON r.memory_id=h.memory_id AND r.revision=h.current_revision JOIN procedure_records p "
        "ON p.memory_id=r.memory_id AND p.revision=r.revision WHERE h.memory_id=? AND h.current_revision=? "
        "AND h.memory_type='procedure' AND h.principal_id=? AND h.deployment_id=? AND h.household_id=? "
        "AND h.scope_kind='personal' AND h.scope_owner=?", (memory_id,revision,principal.actor_id,
            principal.deployment_id,principal.household_id,principal.actor_id)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None, None
    if tuple(row[key] for key in ("principal_id", "deployment_id", "household_id", "scope_kind", "scope_owner")) != (
            principal.actor_id, principal.deployment_id, principal.household_id, "personal", principal.actor_id):
        raise MemoryCorruptionError("procedure_draft_revision_owner_differs")
    if row["lifecycle_state"] not in DISCOVERABLE_LIFECYCLE_STATES:
        return None, None
    if (row["conflict_status"] != "uncontested" or row["effective_privacy_class"] == "restricted"
        or (row["valid_from"] is not None and now < row["valid_from"])
        or (row["valid_to"] is not None and now >= row["valid_to"])):
        return None, None
    if not backend._candidate_disclosure_allowed(context, row["effective_privacy_class"],
            tuple(json.loads(row["information_attributes_json"]))):
        return None, None
    if (await backend._resolve_suppression_unlocked(SuppressionCandidate(principal.actor_id,
            memory_id=memory_id), _purpose(context), evaluated_at=now)).denied:
        return None, None
    _, evidence_ids, _ = await backend._cognitive_recall_lineage_unlocked(memory_id,revision)
    if not evidence_ids:
        raise MemoryCorruptionError("procedure_draft_source_missing")
    for eid in evidence_ids:
        record = await backend._read_ingested_record(eid)
        if record is None:
            raise MemoryCorruptionError("procedure_draft_source_missing")
        reason = await _evidence(backend,principal,context,
            HistoryEvidenceBinding(record.envelope,record.admission_receipt),{},work)
        if reason != "history_visible":
            return None, None
    try:
        value=json.loads(row["content_json"]); payload=ProcedureMemoryPayload.from_json(value)
        if (canonical_json(value) != row["content_json"]
            or hashlib.sha256(row["content_json"].encode()).hexdigest() != row["content_hash"]
            or row["steps_json"] != canonical_json(list(payload.steps)) or row["name"] != payload.name
            or row["applicability_json"] != canonical_json(list(payload.applicability))
            or row["risk_level"] != payload.proposed_risk_level.value):
            raise ValueError("canonical payload differs")
    except (ValueError,TypeError,KeyError) as error:
        raise MemoryCorruptionError("procedure_draft_content_corrupt") from error
    value=ProcedureDraftCandidate(memory_id,revision,payload.name,tuple(payload.steps),tuple(payload.applicability),
        row["risk_level"],row["lifecycle_state"],row["qualification_epoch"],row["applicability_fingerprint"],row["content_hash"])
    return value, row["valid_to"]


def match_score(query, terms, candidate):
    """Term hits over the public text (name, applicability, steps); 0 means no match.

    Terms come from ``typed_recall_query_terms`` (the same ``\\w`` words plus CJK
    bigrams typed recall uses), so a Chinese query no longer has to appear
    verbatim. A whole-query substring hit keeps working and ranks above a
    partial term overlap of the same width.
    """
    text = (candidate.name + "\n" + "\n".join(candidate.applicability)
            + "\n" + "\n".join(candidate.steps)).casefold()
    hits = sum(1 for term in terms if term in text)
    return hits + (1 if query.casefold() in text else 0)


@history_source_operation
async def discover(backend, *, principal, scope, disclosure_context, query, after="", limit=8, max_bytes=32768):
    if type(principal) is not MemoryPrincipal or type(scope) is not MemoryScope:
        raise TypeError("canonical Procedure identity required")
    scope.authorize(principal)
    if scope != MemoryScope.personal(principal.actor_id) or not self_context(backend,principal,disclosure_context):
        raise MemoryValidationError("procedure_draft_self_disclosure_required")
    if (type(query) is not str or not query.strip() or "\x00" in query or len(query.encode())>512
        or type(after) is not str or "\x00" in after or len(after.encode())>1024
        or type(limit) is not int or not 1<=limit<=8 or type(max_bytes) is not int or not 256<=max_bytes<=32768):
        raise MemoryValidationError("procedure_draft_bounds_invalid")
    if backend._db is None or backend._receipt is None:
        raise RuntimeError("human-memory v7 backend is not initialized")
    await prepare_history_source_context(backend,principal)
    async with backend._write_lock:
        await begin_transaction(backend._db, "BEGIN")
        try:
            await backend._authorize_short_horizon_principal_unlocked(principal)
            now=float(backend._now())
            if not math.isfinite(now) or now<0: raise MemoryValidationError("procedure_clock_invalid")
            from simple_harness_memory.backends.history_visibility import _EvidenceWork
            work=_EvidenceWork(now)
            async with backend._db.execute("SELECT memory_id,current_revision FROM cognitive_memory_heads "
                "WHERE principal_id=? AND deployment_id=? AND household_id=? AND scope_kind='personal' AND scope_owner=? "
                "AND memory_type='procedure' AND memory_id>? ORDER BY memory_id LIMIT 129", (
                    principal.actor_id,principal.deployment_id,principal.household_id,principal.actor_id,after)) as cursor:
                rows=await cursor.fetchall()
            terms=typed_recall_query_terms(query)
            candidates=[]; scores=[]; scanned=0; oversized=0; last=after
            for memory_id,revision in rows[:128]:
                if len(memory_id.encode()) > 1024:
                    raise MemoryLimitError("procedure_draft_cursor_limit")
                value,_=await read_candidate(backend,principal,disclosure_context,memory_id,revision,now,work)
                score = 0 if value is None else match_score(query, terms, value)
                if score > 0:
                    # Reserve the exact next-page cursor even at the final row;
                    # no partial step text is returned to fit a page.
                    single = ProcedureDraftPage((value,), memory_id, 1).to_json()
                    proposed = ProcedureDraftPage(tuple((*candidates, value)), memory_id, scanned+1, oversized).to_json()
                    if len(canonical_json(single).encode()) > max_bytes:
                        oversized += 1
                    elif len(canonical_json(proposed).encode()) > max_bytes:
                        break
                    else:
                        candidates.append(value); scores.append(score)
                last=memory_id; scanned+=1
                if len(candidates)==limit: break
            # Rank within the page only: most term hits first, then scan order.
            # The cursor stays the scan-order memory_id, so paging never
            # repeats or skips a row whatever the ranking.
            ranked=[value for _,_,value in sorted(zip(scores,range(len(candidates)),candidates),
                key=lambda item:(-item[0],item[1]))]
            result=ProcedureDraftPage(tuple(ranked),last if scanned<len(rows) else None,scanned,oversized)
            # Filtered/oversized rows can still enlarge the cursor. Never return
            # an over-budget page or drop continuation and imply exhaustion.
            if len(canonical_json(result.to_json()).encode()) > max_bytes:
                raise MemoryLimitError("procedure_draft_page_budget")
            await backend._db.execute("COMMIT")
            return result
        except BaseException:
            await rollback_transaction(backend._db)
            raise
