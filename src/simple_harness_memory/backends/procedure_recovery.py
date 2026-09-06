"""Bounded exact historical Procedure observation rebasing, never a new grant."""
import json
import hashlib
from simple_harness.contracts import canonical_json
from simple_harness.runtime import ProcedureObservationAuthority, ProcedureObservationAuthorityRef
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryWriterConflict, MemoryValidationError

MAX_OBSERVATION_REBASE = 128
_DEFINITION = ("principal_id", "deployment_id", "household_id", "scope_kind", "scope_owner",
    "content_json", "content_hash", "effective_privacy_class", "information_attributes_json",
    "epistemic_status", "conflict_status", "verification_state", "valid_from", "valid_to",
    "name", "steps_json", "applicability_json", "risk_level", "qualification_epoch")
_USABLE = {"draft", "eligible_for_activation", "active", "reinforced"}


async def compatible_revision(backend, *, principal, scope, memory_id, revision):
    """Caller owns the SDK write transaction; every intervening revision is proved."""
    db = backend._db
    async with db.execute("SELECT current_revision,memory_type FROM cognitive_memory_heads WHERE memory_id=? "
            "AND principal_id=? AND deployment_id=? AND household_id=? AND scope_kind=? AND scope_owner=?",
            (memory_id, principal.actor_id, principal.deployment_id, principal.household_id,
             scope.kind.value, scope.owner_id)) as cursor:
        head = await cursor.fetchone()
    if head is None or head[1] != "procedure" or head[0] < revision:
        raise MemoryWriterConflict("procedure_observation_rebase_target_unavailable")
    current = int(head[0])
    if current - revision > MAX_OBSERVATION_REBASE:
        raise MemoryValidationError("procedure_observation_rebase_limit")
    async with db.execute("SELECT r.*,p.name,p.steps_json,p.applicability_json,p.risk_level,p.qualification_epoch "
            "FROM cognitive_memory_revisions r JOIN procedure_records p "
            "ON p.memory_id=r.memory_id AND p.revision=r.revision "
            "WHERE r.memory_id=? AND r.revision BETWEEN ? AND ? ORDER BY r.revision",
            (memory_id, revision, current)) as cursor:
        rows = list(await cursor.fetchall())
    if len(rows) != current - revision + 1:
        raise MemoryCorruptionError("procedure_observation_rebase_chain_missing")
    first = rows[0]
    identity = (principal.actor_id, principal.deployment_id, principal.household_id, scope.kind.value, scope.owner_id)
    if tuple(first[key] for key in _DEFINITION[:5]) != identity:
        raise MemoryCorruptionError("procedure_observation_rebase_owner_differs")
    try:
        from simple_harness.runtime import ProcedureMemoryPayload
        payload = json.loads(first["content_json"])
        typed = ProcedureMemoryPayload.from_json(payload)
        if (canonical_json(payload) != first["content_json"]
                or hashlib.sha256(first["content_json"].encode()).hexdigest() != first["content_hash"]
                or typed.name != first["name"] or canonical_json(list(typed.steps)) != first["steps_json"]
                or canonical_json(list(typed.applicability)) != first["applicability_json"]
                or typed.proposed_risk_level.value != first["risk_level"]):
            raise ValueError("definition hash")
    except (TypeError, KeyError, ValueError) as error:
        raise MemoryCorruptionError("procedure_observation_rebase_definition_corrupt") from error
    for row in rows:
        if row["lifecycle_state"] not in _USABLE or any(row[key] != first[key] for key in _DEFINITION):
            raise MemoryWriterConflict("procedure_observation_rebase_definition_changed")
        if row["revision"] == revision:
            continue
        async with db.execute("SELECT authority_ref_json FROM procedure_observation_authority_consumptions "
                "WHERE target_memory_id=? AND target_revision=?", (memory_id, row["revision"] - 1)) as cursor:
            refs = list(await cursor.fetchall())
        if len(refs) != 1:
            raise MemoryWriterConflict("procedure_observation_rebase_non_observation_revision")
        reference = ProcedureObservationAuthorityRef.from_json(json.loads(refs[0][0]))
        result = await backend._read_procedure_result_unlocked(principal=principal, scope=scope, reference=reference)
        if result is None or result.committed_revision != row["revision"]:
            raise MemoryCorruptionError("procedure_observation_rebase_result_differs")
    return current


async def resolve_previous(backend, previous_reference):
    """Resolve expired credentials as historical source only; never authorize use."""
    if type(previous_reference) is not ProcedureObservationAuthorityRef or backend._procedure_observation_authority is None:
        raise MemoryValidationError("procedure_observation_previous_reference_invalid")
    authority = await backend._procedure_observation_authority.resolve_procedure_observation_authority(previous_reference)
    if type(authority) is not ProcedureObservationAuthority or ProcedureObservationAuthorityRef.from_authority(authority) != previous_reference:
        raise MemoryValidationError("procedure_observation_previous_reference_differs")
    return authority


async def check_previous_unlocked(backend, *, principal, scope, reference, authority, candidate, now):
    replay = await backend._read_procedure_result_unlocked(principal=principal, scope=scope, reference=reference)
    if replay is not None:
        # Caller must get that exact old result, not issue a fresh authority.
        raise MemoryWriterConflict("procedure_observation_previous_already_consumed")
    before, after = authority.intent.to_json(), candidate.to_json()
    for key in ("target_revision", "transition_from", "transition_to"):
        before.pop(key)
        after.pop(key)
    if canonical_json(before) != canonical_json(after) or candidate.target_revision < authority.intent.target_revision:
        raise MemoryValidationError("procedure_observation_previous_source_differs")
    if now < authority.issued_at:
        raise MemoryValidationError("procedure_observation_recovery_clock_regressed")
    if (now < authority.expires_at and candidate.target_revision == authority.intent.target_revision
            and candidate.transition_to == authority.intent.transition_to):
        raise MemoryWriterConflict("procedure_observation_previous_still_usable")


async def reject_duplicate_unlocked(backend, candidate):
    async with backend._db.execute("SELECT task_scope_id,terminal_receipt_id FROM procedure_observations "
            "WHERE memory_id=? AND qualification_epoch=(SELECT qualification_epoch FROM procedure_records "
            "WHERE memory_id=? AND revision=?) AND (task_scope_id=? OR terminal_receipt_id=?) LIMIT 1", (
                candidate.target_memory_id, candidate.target_memory_id, candidate.target_revision,
                candidate.task_scope_id, candidate.terminal_receipt_id)) as cursor:
        prior = await cursor.fetchone()
    if prior is not None:
        raise MemoryValidationError("procedure_observation_source_already_counted")
