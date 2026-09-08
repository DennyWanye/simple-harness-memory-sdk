"""Exact standalone short proof within the existing history read transaction."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from simple_harness import DisclosureContext
from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError
from simple_harness_memory.core.history import HistoryShortHorizonBinding
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.short_horizon import (
    SHORT_HORIZON_RETENTION_SECONDS,
    ShortHorizonIndexError,
    resolve_short_horizon_projection_row,
    short_horizon_segment_payload_fields,
)
from simple_harness_memory.core.suppression import SuppressionCandidate


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def _audit(backend: Any, audit_id: str, subject: str) -> dict[str, Any] | None:
    async with backend._db.execute(
        "SELECT * FROM short_horizon_audit WHERE audit_id=? AND principal_id=?",
        (audit_id, subject),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    payload = backend._canonical_audit_object(row["audit_json"], "short history audit")
    if (
        _sha(str(row["audit_json"])) != row["audit_hash"]
        or any(
            payload.get(key) != row[key]
            for key in row.keys()
            if key not in {"audit_json", "audit_hash"}
        )
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("details"), dict)
    ):
        raise MemoryCorruptionError("short history audit binding differs")
    return payload


async def check_short(
    backend: Any,
    principal: MemoryPrincipal,
    context: DisclosureContext,
    binding: HistoryShortHorizonBinding,
    now: float,
    *,
    sources: list[Any] | None = None,
) -> tuple[str, float | None]:
    from simple_harness_memory.backends.sqlite_v5 import _opaque_hash

    mismatch = ("history_binding_mismatch", None)
    audit = await _audit(backend, binding.audit_id, principal.actor_id)
    if (
        audit is None
        or audit["event_kind"] != "recall"
        or audit["degradation_code"]
        not in {
            None,
            "VECTOR_DEGRADED",
            "NO_ACTIVE_GENERATION",
            "STALE_ACTIVE_GENERATION",
        }
    ):
        return mismatch
    details = audit["details"]
    if details.get("gate_outcome") is not None:
        return mismatch
    attempt_id = details.get("attempt_audit_id")
    if not isinstance(attempt_id, str):
        return mismatch
    attempt = await _audit(backend, attempt_id, principal.actor_id)
    if (
        attempt is None
        or attempt["event_kind"] != "recall_started"
        or any(
            attempt[key] != audit[key]
            for key in ("principal_id", "query_hash", "disclosure_context_hash")
        )
        or attempt["details"].get("gate_outcome") != "in_progress"
    ):
        return mismatch
    # A timeout can race a committed result. A terminal for that exact attempt
    # disqualifies it; merely observing selected entries is never enough.
    async with backend._db.execute(
        "SELECT 1 FROM short_horizon_audit WHERE principal_id=? AND event_kind='recall_terminal' "
        "AND json_extract(audit_json,'$.details.attempt_audit_id')=? LIMIT 1",
        (principal.actor_id, attempt_id),
    ) as cursor:
        if await cursor.fetchone() is not None:
            return mismatch
    opaque = _opaque_hash(binding.chunk_ref)
    selected, eligible = details.get("selected"), details.get("eligible")
    if not isinstance(selected, list) or not isinstance(eligible, list):
        raise MemoryCorruptionError("short history selection invalid")
    for entries in (selected, eligible):
        if any(
            not isinstance(x, dict) or not isinstance(x.get("chunk_ref_hash"), str) for x in entries
        ):
            raise MemoryCorruptionError("short history selection invalid")
        keys = [x["chunk_ref_hash"] for x in entries]
        if len(keys) != len(set(keys)):
            raise MemoryCorruptionError("short history selection duplicate")
    if len(eligible) != audit["eligible_count"] or not {x["chunk_ref_hash"] for x in selected} <= {
        x["chunk_ref_hash"] for x in eligible
    }:
        raise MemoryCorruptionError("short history selection membership differs")
    if not any(x["chunk_ref_hash"] == opaque for x in selected) or not any(
        x["chunk_ref_hash"] == opaque and x.get("content_hash") == binding.content_hash
        for x in eligible
    ):
        return mismatch
    return await check_selected_chunk(
        backend, principal, context, chunk_ref=binding.chunk_ref,
        content_hash=binding.content_hash, now=now, sources=sources,
    )


async def check_selected_chunk(
    backend: Any, principal: MemoryPrincipal, context: DisclosureContext, *,
    chunk_ref: str, content_hash: str, now: float, sources: list[Any] | None = None,
) -> tuple[str, float | None]:
    """Validate a chunk after a caller proves durable selection in this transaction."""
    from simple_harness_memory.backends.history_visibility import _purpose

    mismatch = ("history_binding_mismatch", None)
    stale = ("history_source_stale", None)
    denied = ("history_disclosure_denied", None)
    async with backend._db.execute(
        "SELECT * FROM short_horizon_chunks WHERE chunk_id=? AND principal_id=?",
        (chunk_ref, principal.actor_id),
    ) as cursor:
        chunk = await cursor.fetchone()
    if (
        chunk is None
        or not float(chunk["occurred_at"]) <= now < float(chunk["expires_at"])
        or (
            chunk["content_hash"] != content_hash
            or _sha(str(chunk["public_text"])) != content_hash
        )
    ):
        return stale
    # LEFT JOIN retains missing/mismatched references instead of silently dropping them.
    async with backend._db.execute(
        "SELECT r.*, e.evidence_id AS linked_id,e.envelope_hash AS linked_hash,"
        "en.envelope_hash AS stored_hash,en.subject AS stored_subject "
        "FROM short_horizon_chunk_evidence e LEFT JOIN conversation_evidence_registrations r "
        "ON r.registration_id=e.registration_id LEFT JOIN evidence_envelopes en "
        "ON en.evidence_id=e.evidence_id WHERE e.chunk_id=? ORDER BY e.item_ordinal",
        (chunk_ref,),
    ) as cursor:
        rows = tuple(await cursor.fetchmany(4097))
    if len(rows) > 4096:
        raise MemoryLimitError("history_lineage_row_limit")
    if not rows or any(
        row["principal_id"] != principal.actor_id
        or row["stored_subject"] != principal.actor_id
        or row["evidence_id"] != row["linked_id"]
        or row["envelope_hash"] != row["linked_hash"]
        or row["stored_hash"] != row["linked_hash"]
        or row["subject"] != chunk["subject"]
        or row["primary_conversation_id"] != chunk["primary_conversation_id"]
        for row in rows
    ):
        return stale
    # 0.6.30：分段 chunk 的 causal_group_id 列是投影键 ``id\x1fk/K``；按键重推该段内容，
    # 0.6.29 遗留的整组单行在下次重建前仍可见（与 _validate_short_horizon_integrity 同规则）。
    try:
        derived = resolve_short_horizon_projection_row(
            str(chunk["causal_group_id"]),
            [(str(row["role"]), str(row["public_text"])) for row in rows],
        )
    except ShortHorizonIndexError:
        return stale
    if any(row["causal_group_id"] != derived.causal_group_id for row in rows):
        return stale
    if not backend._short_horizon_group_is_complete(rows):
        return stale
    for row in rows:
        backend._assert_short_horizon_registration_metadata_binding(row)
        if not row["classification_authority_ref"] or row["evidence_item_authority_json"] is None:
            return denied
        if not backend._candidate_disclosure_allowed(
            context,
            str(row["effective_privacy_class"]),
            tuple(json.loads(str(row["information_attributes_json"]))),
        ):
            return denied
    # Rebind the derived chunk to its complete canonical group. This also detects
    # losing a dependency while retaining otherwise valid text/hash columns.
    content = derived.content
    refs = sorted({str(row["classification_authority_ref"]) for row in rows})
    attrs = sorted({x for row in rows for x in json.loads(str(row["information_attributes_json"]))})
    rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
    privacy = max((str(row["effective_privacy_class"]) for row in rows), key=rank.__getitem__)
    occurred = max(float(row["occurred_at"]) for row in rows)
    payload: dict[str, JsonValue] = dict(
        subject=str(chunk["subject"]),
        primary_conversation_id=str(chunk["primary_conversation_id"]),
        causal_group_id=derived.causal_group_id,
        registration_hashes=[str(row["registration_hash"]) for row in rows],
        content_hash=_sha(content),
        effective_privacy_class=privacy,
        information_attributes=attrs,
        classification_authority_refs=cast(JsonValue, refs),
        **short_horizon_segment_payload_fields(derived.segment_ordinal, derived.segment_count),
    )
    if (
        "short:" + _sha(canonical_json(payload)) != chunk_ref
        or _sha(content) != content_hash
        or privacy != chunk["effective_privacy_class"]
        or attrs != json.loads(str(chunk["information_attributes_json"]))
        or refs != json.loads(str(chunk["classification_authority_refs_json"]))
        or occurred != float(chunk["occurred_at"])
        or occurred + SHORT_HORIZON_RETENTION_SECONDS != float(chunk["expires_at"])
    ):
        return stale
    if not backend._candidate_disclosure_allowed(context, privacy, tuple(attrs)):
        return denied
    policy = backend._classification_policy
    if policy is not None and not backend._candidate_disclosure_allowed(
        context,
        policy.required_privacy_class.value,
        tuple(x.value for x in policy.required_information_attributes),
    ):
        return denied
    candidates = [SuppressionCandidate(principal.actor_id, memory_id=chunk_ref)]
    candidates.extend(
        SuppressionCandidate(
            principal.actor_id,
            evidence_id=str(row["evidence_id"]),
            entity_ids=tuple(json.loads(str(row["entities_json"]))),
        )
        for row in rows
    )
    for candidate in candidates:
        if (
            await backend._resolve_suppression_unlocked(
                candidate,
                _purpose(context),
                evaluated_at=now,
            )
        ).denied:
            return "history_suppressed", None
    if sources is not None:
        from simple_harness_memory.core.short_sources import ShortHorizonSourceRef

        # Reuse canonical registration validation for exactly this selected group,
        # never scan all indexed roots to answer one selected binding.
        await backend._validate_short_horizon_integrity_unlocked(selected_registrations=rows)
        projected_refs = []
        for row in rows:
            record = await backend._read_ingested_record(str(row["evidence_id"]))
            if record is None:
                return stale
            envelope, admission = record.envelope, record.admission_receipt
            metadata = json.loads(str(row["metadata_json"]))
            if any(metadata.get(key) != value for key, value in {
                "evidence_id": envelope.evidence_id, "envelope_hash": envelope.envelope_hash,
                "subject": envelope.subject, "run_id": envelope.run_id,
                "source_hash": envelope.source_hash, "sanitized_hash": envelope.sanitized_hash,
                "admission_receipt_id": admission.receipt_id,
                "admission_receipt_hash": admission.receipt_hash,
            }.items()):
                return mismatch
            if (row["admission_receipt_id"] != admission.receipt_id
                    or row["admission_receipt_hash"] != admission.receipt_hash):
                return mismatch
            projected_refs.append(ShortHorizonSourceRef(
                envelope.evidence_id, envelope.envelope_hash, envelope.source_ref,
                envelope.source_hash, envelope.sanitized_hash, admission.receipt_id,
                admission.receipt_hash, str(row["registration_id"]),
                str(row["registration_hash"]), int(row["item_ordinal"]), str(row["role"])))
        sources.extend(projected_refs)  # publish only after ALL members validated
    return "history_visible", float(chunk["expires_at"])
