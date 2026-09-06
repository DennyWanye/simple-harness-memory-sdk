"""Bounded read-only verification inside Memory, not a Host SQL escape hatch."""
import hashlib
import json
import sqlite3

import aiosqlite
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    MemoryMutationApplyReceipt, MemoryMutationApplyReceiptRef, MemoryMutationPlan,
    ProspectiveLifecycleState,
)
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError, MemoryOwnershipConflict, MemoryValidationError
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.mutation_receipts import _digest, _identifier
from simple_harness_memory.core.prospective_sources import ProspectiveOutboxSourceView

MAX_WIRE_BYTES = 1_048_576
MAX_SQL_STEPS = 200_000


def _corrupt():
    raise MemoryCorruptionError("prospective_outbox_source_binding_corrupt")


def _json(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_WIRE_BYTES:
        raise MemoryLimitError("prospective_outbox_source_wire_limit")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise MemoryCorruptionError("prospective_outbox_source_json_invalid") from exc
    if not isinstance(value, dict) or canonical_json(value) != raw:
        _corrupt()
    return value


async def _one(db, sql, args):
    async with db.execute(sql, args) as cursor:
        return await cursor.fetchone()


async def _read(backend, db, principal, outbox_id, payload_hash):
    from simple_harness_memory.backends.sqlite_v5 import _stable_id
    owner = await _one(db, "SELECT deployment_id,household_id,actor_id FROM principals WHERE principal_id=?", (principal.actor_id,))
    if owner is None or tuple(owner) != (principal.deployment_id, principal.household_id, principal.actor_id):
        raise MemoryOwnershipConflict("prospective_outbox_source_not_owned")
    outbox = await _one(db, "SELECT outbox_id,principal_id,topic,payload_hash,"
        "substr(payload,1,?) AS payload FROM outbox WHERE outbox_id=? AND principal_id=?",
        (MAX_WIRE_BYTES + 1, outbox_id, principal.actor_id))
    if outbox is None:
        raise MemoryValidationError("prospective_outbox_source_not_found")
    payload = _json(outbox["payload"])
    if (outbox["payload_hash"] != payload_hash
            or hashlib.sha256(canonical_json(payload).encode()).hexdigest() != payload_hash):
        raise MemoryValidationError("prospective_outbox_source_payload_hash_mismatch")
    keys = {"schema_version", "command", "memory_id", "prospective_revision", "registration_revision", "trigger", "trigger_hash"}
    if set(payload) != keys or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        _corrupt()
    kind, memory_id, revision = payload["command"], payload["memory_id"], payload["prospective_revision"]
    _identifier(memory_id, "target_memory_id")
    if (kind not in {"registration", "invalidation"} or type(revision) is not int or revision < 1
            or type(payload["registration_revision"]) is not int or payload["registration_revision"] != revision
            or outbox["topic"] != f"memory.prospective.{kind}.requested"
            or outbox_id != _stable_id("prospective-scheduler-outbox", memory_id, str(revision), kind)):
        _corrupt()
    target = await _one(db, "SELECT r.principal_id,r.deployment_id,r.household_id,r.scope_kind,r.scope_owner,"
        "r.plan_id,r.plan_hash,r.operation_id,r.task_scope_id,r.lifecycle_state,r.content_hash,"
        "substr(r.content_json,1,1048577) AS content_json,h.memory_type,"
        "substr(p.trigger_json,1,1048577) AS trigger_json FROM cognitive_memory_revisions r "
        "JOIN cognitive_memory_heads h ON h.memory_id=r.memory_id "
        "JOIN prospective_records p ON p.memory_id=r.memory_id AND p.revision=r.revision "
        "WHERE r.memory_id=? AND r.revision=?", (memory_id, revision))
    if target is None or target["memory_type"] != "prospective":
        _corrupt()
    if (target["principal_id"], target["deployment_id"], target["household_id"]) != (
            principal.actor_id, principal.deployment_id, principal.household_id):
        raise MemoryOwnershipConflict("prospective_outbox_source_not_owned")
    scope = MemoryScope(target["scope_kind"], target["scope_owner"])
    scope.authorize(principal)
    content = _json(target["content_json"])
    if hashlib.sha256(canonical_json(content).encode()).hexdigest() != target["content_hash"]:
        _corrupt()
    _json(target["trigger_json"])
    trigger, trigger_hash = backend._decode_prospective_trigger(target["trigger_json"])
    if payload["trigger"] != trigger.to_json() or payload["trigger_hash"] != trigger_hash or content.get("trigger") != trigger.to_json():
        _corrupt()
    # There is no plan-id index on historical receipt storage. Limit VM work
    # as well as returned rows; large stores fail explicitly, never scan forever.
    async with db.execute("SELECT receipt_id,length(CAST(plan_json AS BLOB)) AS plan_bytes,"
        "length(CAST(receipt_json AS BLOB)) AS receipt_bytes FROM memory_mutation_receipts "
        "WHERE principal_id=? AND plan_id=? AND plan_hash=? LIMIT 2",
        (principal.actor_id, target["plan_id"], target["plan_hash"])) as cursor:
        candidates = await cursor.fetchall()
    if not candidates:
        # Signal-produced revisions have a synthetic plan id; don't invent a
        # mutation receipt or reinterpret a previous revision as this target.
        raise MemoryValidationError("prospective_target_mutation_source_unavailable")
    if len(candidates) != 1:
        _corrupt()
    if max(candidates[0]["plan_bytes"], candidates[0]["receipt_bytes"]) > MAX_WIRE_BYTES:
        raise MemoryLimitError("prospective_outbox_source_wire_limit")
    stored = await _one(db, "SELECT receipt_id,authority_ref,principal_id,plan_id,plan_hash,run_id,subject,idempotency_key,plan_outcome,base_revision,committed_revision,apply_mode,receipt_hash,committed_at,plan_json,receipt_json,substr(canonical_operation_ids_json,1,1048577) AS canonical_operation_ids_json FROM memory_mutation_receipts WHERE receipt_id=?", (candidates[0]["receipt_id"],))
    raw_plan, raw_receipt = _json(stored["plan_json"]), _json(stored["receipt_json"])
    plan = MemoryMutationPlan.from_json(raw_plan)
    receipt = MemoryMutationApplyReceipt.from_json(raw_receipt)
    receipt.validate_plan(plan)
    if plan.to_json() != raw_plan or receipt.to_json() != raw_receipt:
        _corrupt()
    for field in ("receipt_id", "authority_ref", "plan_id", "plan_hash", "run_id", "subject",
                  "base_revision", "committed_revision", "receipt_hash", "committed_at"):
        if getattr(receipt, field) != stored[field]:
            _corrupt()
    if (stored["principal_id"] != principal.actor_id
            or stored["apply_mode"] != plan.apply_mode.value
            or stored["plan_outcome"] != plan.outcome.value):
        _corrupt()
    operation_ids_raw = stored["canonical_operation_ids_json"]
    if len(operation_ids_raw.encode("utf-8")) > MAX_WIRE_BYTES:
        raise MemoryLimitError("prospective_outbox_source_wire_limit")
    if canonical_json(json.loads(operation_ids_raw)) != operation_ids_raw:
        _corrupt()
    if (receipt.receipt_id != stored["receipt_id"] or receipt.receipt_hash != stored["receipt_hash"]
            or plan.plan_id != target["plan_id"] or plan.plan_hash != target["plan_hash"]
            or plan.run_id != stored["run_id"] or plan.subject != principal.actor_id
            or receipt.subject != stored["subject"] or plan.idempotency_key != stored["idempotency_key"]
            or json.loads(stored["canonical_operation_ids_json"]) != list(receipt.canonical_operation_ids)):
        _corrupt()
    matches = [op for op in plan.operations if op.operation_id == target["operation_id"]]
    if len(matches) != 1 or target["operation_id"] not in receipt.canonical_operation_ids:
        _corrupt()
    operation = matches[0]
    if operation.memory_type.value != "prospective" or operation.lifecycle_state.value != target["lifecycle_state"]:
        _corrupt()
    if operation.payload is not None and operation.payload.to_json().get("trigger") != trigger.to_json():
        _corrupt()
    decision = await _one(db, "SELECT substr(decision_json,1,1048577) AS decision_json,decision_hash,outcome,after_ref FROM memory_mutation_decisions "
        "WHERE receipt_id=? AND operation_id=?", (receipt.receipt_id, operation.operation_id))
    if decision is None:
        _corrupt()
    raw_decision = _json(decision["decision_json"])
    if (hashlib.sha256(canonical_json(raw_decision).encode()).hexdigest() != decision["decision_hash"]
            or raw_decision.get("operation_id") != operation.operation_id
            or raw_decision.get("after_ref") != f"{memory_id}@{revision}"
            or raw_decision.get("outcome") != "committed"
            or raw_decision.get("reason_code") != operation.reason_code
            or decision["after_ref"] != raw_decision["after_ref"] or decision["outcome"] != "committed"):
        _corrupt()
    return ProspectiveOutboxSourceView(principal.actor_id, outbox_id, payload_hash, kind,
        memory_id, revision, payload["registration_revision"], scope, target["task_scope_id"],
        ProspectiveLifecycleState(target["lifecycle_state"]), receipt.run_id, plan.plan_id, plan.plan_hash,
        operation.operation_id, operation.kind.value, MemoryMutationApplyReceiptRef(receipt.receipt_id, receipt.receipt_hash),
        trigger, trigger_hash)


async def read_prospective_outbox_source(backend, *, principal, outbox_id, payload_hash):
    if type(principal) is not MemoryPrincipal:
        raise TypeError("principal must use MemoryPrincipal")
    _identifier(outbox_id, "outbox_id")
    _digest(payload_hash, "outbox_payload_hash")
    if backend._db is None or backend._receipt is None:
        raise RuntimeError("human-memory v7 backend is not initialized")
    ticks = 0
    def progress():
        nonlocal ticks
        ticks += 1000
        return ticks >= MAX_SQL_STEPS
    async with backend._write_lock:
        if backend._db is None or backend._receipt is None:
            raise RuntimeError("human-memory v7 backend is not initialized")
        async with aiosqlite.connect(backend._db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1.0) as db:
            db.row_factory = aiosqlite.Row
            await db.set_progress_handler(progress, 1000)
            try:
                await db.execute("BEGIN")
                return await _read(backend, db, principal, outbox_id, payload_hash)
            except MemoryValidationError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("prospective_outbox_source_wire_invalid") from exc
            except sqlite3.OperationalError as exc:
                if ticks >= MAX_SQL_STEPS:
                    raise MemoryLimitError("prospective_outbox_source_sql_budget") from exc
                raise
            finally:
                await db.set_progress_handler(None, 0)
                await db.rollback()
