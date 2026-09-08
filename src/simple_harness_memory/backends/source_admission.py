"""Source-only transaction; shares S1 storage, never the analysis scheduler."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from simple_harness.contracts import canonical_json

from simple_harness_memory.backends.sqlite_tx import begin_transaction
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.evidence import (
    EvidenceSourceAdmissionReceipt,
    _sha256_json,
    validate_sanitized_evidence,
)
from simple_harness_memory.core.identity import MemoryPrincipal


async def check_other_mode(backend: Any, envelope: Any, receipt: Any, *, source: bool) -> None:
    table = "ingestion_receipts" if source else "source_admission_receipts"
    async with backend._db.execute(
        f"SELECT 1 FROM {table} r JOIN evidence_envelopes e ON e.evidence_id=r.evidence_id "
        "WHERE (e.subject=? AND e.source_ref=?) OR e.evidence_id=? OR r.admission_receipt_id=?",
        (envelope.subject, envelope.source_ref, envelope.evidence_id, receipt.receipt_id),
    ) as cursor:
        if await cursor.fetchone() is not None:
            raise MemoryIdempotencyConflict("evidence_admission_mode_conflict")


def source_receipt_from_row(row: Any) -> EvidenceSourceAdmissionReceipt:
    result = EvidenceSourceAdmissionReceipt(
        **{
            key: row[key]
            for key in (
                "receipt_id",
                "evidence_id",
                "subject",
                "source_ref",
                "source_hash",
                "sanitized_hash",
                "envelope_hash",
                "admission_receipt_id",
                "admission_receipt_hash",
                "accepted_at",
            )
        }
    )
    if result.receipt_hash != row["receipt_hash"] or result.receipt_id != source_receipt_id(
        result.subject,
        result.source_ref,
        result.envelope_hash,
        result.admission_receipt_id,
        result.admission_receipt_hash,
    ):
        raise MemoryCorruptionError("stored evidence source admission receipt hash differs")
    return result


def source_receipt_id(
    subject: str,
    source_ref: str,
    envelope_hash: str,
    admission_receipt_id: str,
    admission_receipt_hash: str,
) -> str:
    return "source-admission:" + _sha256_json(
        {
            "domain": "memory.evidence.source-admission.id.v1",
            "payload": dict(
                subject=subject,
                source_ref=source_ref,
                envelope_hash=envelope_hash,
                admission_receipt_id=admission_receipt_id,
                admission_receipt_hash=admission_receipt_hash,
            ),
        }
    )


async def admit(
    backend: Any, *, principal: MemoryPrincipal, envelope: Any, receipt: Any
) -> EvidenceSourceAdmissionReceipt:
    span = validate_sanitized_evidence(
        envelope, receipt, supported_filter_policies=tuple(backend._supported_filter_policies)
    )
    if (
        type(envelope).from_json(envelope.to_json()).envelope_hash != envelope.envelope_hash
        or type(receipt).from_json(receipt.to_json()).receipt_hash != receipt.receipt_hash
    ):
        raise MemoryValidationError("evidence_source_live_hash_mismatch")
    if type(principal) is not MemoryPrincipal:
        raise TypeError("principal must be MemoryPrincipal")
    # Reconstruct to validate a forged live dataclass as well as ordinary constructors.
    MemoryPrincipal(
        principal.deployment_id, principal.household_id, principal.actor_id, principal.session_id
    )
    if principal.actor_id != envelope.subject:
        raise MemoryOwnershipConflict("evidence_source_subject_mismatch")
    db = backend.connection
    async with backend._write_lock:
        await begin_transaction(db)
        committed = False
        try:
            await backend._authorize_short_horizon_principal_unlocked(principal)
            await check_other_mode(backend, envelope, receipt, source=True)
            async with db.execute(
                "SELECT e.evidence_id FROM evidence_envelopes e "
                "LEFT JOIN source_admission_receipts r ON r.evidence_id=e.evidence_id "
                "WHERE (e.subject=? AND e.source_ref=?) OR e.evidence_id=? "
                "OR r.admission_receipt_id=?",
                (envelope.subject, envelope.source_ref, envelope.evidence_id, receipt.receipt_id),
            ) as cursor:
                existing = await cursor.fetchall()
            if existing:
                if len(existing) != 1:
                    raise MemoryIdempotencyConflict("evidence_source_admission_conflict")
                record = await backend._read_ingested_record(str(existing[0][0]))
                if record is None:
                    raise MemoryCorruptionError("stored source admission missing")
                if record.envelope != envelope or record.admission_receipt != receipt:
                    raise MemoryIdempotencyConflict("evidence_source_admission_conflict")
                if type(record.ingestion_receipt) is not EvidenceSourceAdmissionReceipt:
                    raise MemoryCorruptionError("stored source admission mode differs")
                await db.execute("COMMIT")
                committed = True
                return record.ingestion_receipt
            result = EvidenceSourceAdmissionReceipt(
                receipt_id=source_receipt_id(
                    envelope.subject,
                    envelope.source_ref,
                    envelope.envelope_hash,
                    receipt.receipt_id,
                    receipt.receipt_hash,
                ),
                evidence_id=envelope.evidence_id,
                subject=envelope.subject,
                source_ref=envelope.source_ref,
                source_hash=envelope.source_hash,
                sanitized_hash=envelope.sanitized_hash,
                envelope_hash=envelope.envelope_hash,
                admission_receipt_id=receipt.receipt_id,
                admission_receipt_hash=receipt.receipt_hash,
                accepted_at=backend._now(),
            )
            payload = canonical_json(envelope.to_json()["sanitized_payload"])
            await db.execute(
                "INSERT INTO evidence_envelopes(evidence_id,principal_id,run_id,"
                "subject,source_kind,"
                "source_ref,source_hash,sanitized_hash,envelope_hash,filter_policy_version,"
                "disclosure_json,disclosure_hash,removed_spans_json,sanitized_payload,created_at,"
                "analysis_lineage_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    envelope.evidence_id,
                    envelope.subject,
                    envelope.run_id,
                    envelope.subject,
                    envelope.source_kind.value,
                    envelope.source_ref,
                    envelope.source_hash,
                    envelope.sanitized_hash,
                    envelope.envelope_hash,
                    envelope.filter_policy_version,
                    canonical_json(envelope.disclosure_context.to_json()),
                    envelope.disclosure_context.context_hash,
                    canonical_json([x.to_json() for x in envelope.removed_spans]),
                    payload,
                    result.accepted_at,
                ),
            )
            backend._fault("source_admission.after_envelope")
            await db.execute(
                "INSERT INTO evidence_items(evidence_id,ordinal,item_kind,content_hash,"
                "public_payload,blob_ref) VALUES(?,?,?,?,?,?)",
                (
                    envelope.evidence_id,
                    span.ordinal,
                    span.item_kind,
                    span.content_hash,
                    None if span.public_payload is None else payload,
                    span.blob_ref,
                ),
            )
            await db.executemany(
                "INSERT INTO evidence_links(evidence_id,ordinal,target_evidence_id,"
                "target_content_hash) VALUES(?,?,?,?)",
                (
                    (envelope.evidence_id, x.ordinal, x.evidence_id, x.content_hash)
                    for x in envelope.evidence_refs
                ),
            )
            await db.execute(
                "INSERT INTO source_admission_receipts(receipt_id,evidence_id,source_hash,"
                "envelope_hash,admission_receipt_id,admission_receipt_json,admission_receipt_hash,"
                "receipt_hash,accepted_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    result.receipt_id,
                    envelope.evidence_id,
                    envelope.source_hash,
                    envelope.envelope_hash,
                    receipt.receipt_id,
                    canonical_json(receipt.to_json()),
                    receipt.receipt_hash,
                    result.receipt_hash,
                    result.accepted_at,
                ),
            )
            backend._fault("source_admission.after_receipt")
            backend._fault("source_admission.before_commit")
            await db.execute("COMMIT")
            committed = True
            backend._fault("source_admission.after_commit")
            return result
        except BaseException:
            if not committed:
                with suppress(Exception):
                    await db.execute("ROLLBACK")
            raise
