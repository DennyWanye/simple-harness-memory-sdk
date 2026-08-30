from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
import structlog
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceReasonCode,
    EvidenceRef,
    EvidenceSourceKind,
    IntendedAudience,
    RemovedSpanSummary,
    RemovedSpanType,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory.backends.sqlite_v5 import (
    INGESTION_FAULT_POINTS,
    SQLiteHumanMemoryBackend,
)
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryValidationError,
)


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        "run-1",
        "actor-1",
        DeliveryRecipient.USER_SELF,
        "actor-1",
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "host-auth-1",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _authority(
    payload: dict[str, JsonValue],
    *,
    evidence_id: str = "evidence-1",
    source_ref: str = "turn-1/user",
    source_hash: str = "a" * 64,
    receipt_id: str = "admission-1",
    filter_policy: str = "credential-filter/v1",
    removed_spans: tuple[RemovedSpanSummary, ...] = (),
) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    evidence_ref = EvidenceRef("source-event-1", "d" * 64, 1)
    envelope = SanitizedEvidenceEnvelope(
        evidence_id,
        "run-1",
        "actor-1",
        EvidenceSourceKind.USER_MESSAGE,
        source_ref,
        source_hash,
        payload,
        _hash(payload),
        filter_policy,
        removed_spans,
        _disclosure(),
        (evidence_ref,),
    )
    receipt = SanitizedEvidenceReceipt(
        receipt_id,
        envelope.run_id,
        envelope.subject,
        envelope.evidence_id,
        envelope.envelope_hash,
        envelope.source_hash,
        envelope.sanitized_hash,
        envelope.filter_policy_version,
        True,
        (EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        envelope.disclosure_context,
        envelope.evidence_refs,
        10.0,
    )
    return envelope, receipt


async def _counts(backend: SQLiteHumanMemoryBackend) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in ("evidence_envelopes", "ingestion_receipts", "jobs", "outbox"):
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            result[table] = int(row[0])
    return result


@pytest.mark.asyncio
async def test_ingestion_is_atomic_replayable_immutable_and_exportable(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "evidence.db", now=lambda: 20.0)
    await backend.initialize()
    envelope, admission = _authority(
        {
            "public_text": "user prefers concise answers",
            "headers": {"user-agent": "simple-harness"},
            "tool": {"name": "read_file", "public_result": "ok"},
            "provider": {"model": "fixture", "public_request_id": "request-1"},
        }
    )

    first = await backend.ingest_committed_evidence(envelope, admission)
    replay = await backend.ingest_committed_evidence(envelope, admission)

    assert replay == first
    assert await _counts(backend) == {
        "evidence_envelopes": 1,
        "ingestion_receipts": 1,
        "jobs": 1,
        "outbox": 1,
    }
    exported = await backend.export_ingested_evidence(envelope.evidence_id)
    assert exported.envelope == envelope
    assert exported.admission_receipt == admission
    assert exported.ingestion_receipt == first
    assert exported.spans[0].content_hash == envelope.sanitized_hash
    with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
        await backend.connection.execute(
            "UPDATE evidence_envelopes SET subject='changed' WHERE evidence_id=?",
            (envelope.evidence_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
        await backend.connection.execute(
            "DELETE FROM ingestion_receipts WHERE evidence_id=?",
            (envelope.evidence_id,),
        )
    await backend.close()


@pytest.mark.asyncio
async def test_same_source_replay_with_different_hash_conflicts_without_partial_rows(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "conflict.db", now=lambda: 20.0)
    await backend.initialize()
    first = _authority({"public_text": "first"})
    conflict = _authority(
        {"public_text": "different"},
        evidence_id="evidence-2",
        source_hash="b" * 64,
        receipt_id="admission-2",
    )
    await backend.ingest_committed_evidence(*first)
    with pytest.raises(MemoryIdempotencyConflict, match="evidence_source_replay_conflict"):
        await backend.ingest_committed_evidence(*conflict)
    assert await _counts(backend) == {
        "evidence_envelopes": 1,
        "ingestion_receipts": 1,
        "jobs": 1,
        "outbox": 1,
    }
    await backend.close()


@pytest.mark.asyncio
async def test_same_source_and_hash_replays_first_receipt_without_resanitization_mutation(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "resanitize-replay.db", now=lambda: 20.0)
    await backend.initialize()
    first = _authority({"public_text": "first public projection"})
    replay_candidate = _authority(
        {"public_text": "new public projection must not replace immutable evidence"},
        evidence_id="evidence-2",
        receipt_id="admission-2",
    )
    first_receipt = await backend.ingest_committed_evidence(*first)
    replay_receipt = await backend.ingest_committed_evidence(*replay_candidate)
    assert replay_receipt == first_receipt
    assert (await backend.export_ingested_evidence("evidence-1")).envelope == first[0]
    with pytest.raises(KeyError, match="evidence_not_found"):
        await backend.export_ingested_evidence("evidence-2")
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "canary"),
    (
        (
            {"headers": {"Authorization": "Bearer private-token-123"}},
            "private-token-123",
        ),
        ({"headers": {"Cookie": "session=private-cookie"}}, "private-cookie"),
        ({"env": {"API_KEY": "sk-private-api-key"}}, "private-api-key"),
        ({"env": {"OPENAI_API_KEY": "sk-openai-private-key"}}, "openai-private-key"),
        ({"tool": {"arguments": {"password": "private-password"}}}, "private-password"),
        ({"provider": {"response": "Bearer provider-secret-123"}}, "provider-secret-123"),
        ({"provider": {"hidden_reasoning": "private-reasoning"}}, "private-reasoning"),
    ),
)
async def test_structured_credential_boundary_rejects_before_any_write_or_log_body(
    tmp_path: Path, payload: dict[str, JsonValue], canary: str
) -> None:
    path = tmp_path / "credential-reject.db"
    backend = SQLiteHumanMemoryBackend(path)
    await backend.initialize()
    envelope, receipt = _authority(payload)
    encoded = canonical_json(payload)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(MemoryValidationError, match="credential_boundary_rejected"):
            await backend.ingest_committed_evidence(envelope, receipt)
    assert await _counts(backend) == {
        "evidence_envelopes": 0,
        "ingestion_receipts": 0,
        "jobs": 0,
        "outbox": 0,
    }
    assert encoded not in json.dumps(logs, sort_keys=True)
    files = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
    durable_bytes = b"".join(item.read_bytes() for item in files if item.exists())
    assert canary.encode() not in durable_bytes
    await backend.close()


@pytest.mark.asyncio
async def test_unsanitized_source_canary_never_enters_db_wal_log_or_export(tmp_path: Path) -> None:
    path = tmp_path / "canary.db"
    raw_canaries = (
        "sk-credential-canary-123456",
        "Bearer authorization-canary-123456",
        "cookie=session-cookie-canary",
        "password=password-canary",
    )
    source_hash = hashlib.sha256("|".join(raw_canaries).encode()).hexdigest()
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    await backend.initialize()
    envelope, receipt = _authority(
        {"public_text": "credentials removed"},
        source_hash=source_hash,
        removed_spans=(
            RemovedSpanSummary(RemovedSpanType.API_KEY, 1),
            RemovedSpanSummary(RemovedSpanType.AUTHORIZATION_HEADER, 1),
            RemovedSpanSummary(RemovedSpanType.COOKIE, 1),
            RemovedSpanSummary(RemovedSpanType.PASSWORD, 1),
        ),
    )
    with structlog.testing.capture_logs() as logs:
        await backend.ingest_committed_evidence(envelope, receipt)
    exported = await backend.export_ingested_evidence(envelope.evidence_id)
    export_json = canonical_json(exported.envelope.to_json())
    log_json = json.dumps(logs, sort_keys=True)
    files = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
    durable_bytes = b"".join(item.read_bytes() for item in files if item.exists())
    for canary in raw_canaries:
        assert canary not in export_json
        assert canary not in log_json
        assert canary.encode() not in durable_bytes
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", INGESTION_FAULT_POINTS)
async def test_every_ingestion_fault_is_atomic_and_replayable(
    tmp_path: Path, fault_point: str
) -> None:
    fired = False

    def inject(point: str) -> None:
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise RuntimeError("injected-ingestion-fault")

    path = tmp_path / f"{fault_point.replace('.', '-')}.db"
    backend = SQLiteHumanMemoryBackend(path, fault_injector=inject, now=lambda: 20.0)
    await backend.initialize()
    authority = _authority({"public_text": "atomic evidence"})
    with pytest.raises(RuntimeError, match="injected-ingestion-fault"):
        await backend.ingest_committed_evidence(*authority)
    assert fired
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    await reopened.initialize()
    expected_count = 1 if fault_point == "ingestion.after_commit" else 0
    assert (await _counts(reopened))["evidence_envelopes"] == expected_count
    receipt = await reopened.ingest_committed_evidence(*authority)
    assert (await _counts(reopened))["evidence_envelopes"] == 1
    assert (await reopened.export_ingested_evidence("evidence-1")).ingestion_receipt == receipt
    await reopened.close()


@pytest.mark.asyncio
async def test_disk_full_failure_preserves_preexisting_committed_evidence(tmp_path: Path) -> None:
    enabled = False

    def inject(point: str) -> None:
        if enabled and point == "ingestion.before_commit":
            raise sqlite3.OperationalError("database or disk is full")

    backend = SQLiteHumanMemoryBackend(
        tmp_path / "disk-full.db", fault_injector=inject, now=lambda: 20.0
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority({"public_text": "preserved"}))
    enabled = True
    second = _authority(
        {"public_text": "must rollback"},
        evidence_id="evidence-2",
        source_ref="turn-2/user",
        source_hash="b" * 64,
        receipt_id="admission-2",
    )
    with pytest.raises(sqlite3.OperationalError, match="disk is full"):
        await backend.ingest_committed_evidence(*second)
    assert await _counts(backend) == {
        "evidence_envelopes": 1,
        "ingestion_receipts": 1,
        "jobs": 1,
        "outbox": 1,
    }
    assert (await backend.export_ingested_evidence("evidence-1")).envelope.sanitized_payload[
        "public_text"
    ] == "preserved"
    await backend.close()


@pytest.mark.asyncio
async def test_large_payload_requires_bounded_controlled_blob_reference(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "blob.db", now=lambda: 20.0)
    await backend.initialize()
    with pytest.raises(MemoryLimitError, match="controlled_blob_ref"):
        await backend.ingest_committed_evidence(
            *_authority({"public_text": "x" * (64 * 1024 + 1)})
        )
    blob = _authority(
        {
            "blob_ref": "memory-blob:artifact-1",
            "content_hash": "c" * 64,
            "byte_length": 2_000_000,
        }
    )
    await backend.ingest_committed_evidence(*blob)
    record = await backend.export_ingested_evidence("evidence-1")
    assert record.spans[0].public_payload is None
    assert record.spans[0].blob_ref == "memory-blob:artifact-1"
    await backend.close()


@pytest.mark.asyncio
async def test_receipt_and_filter_policy_must_exactly_bind_live_s1_envelope(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "authority.db")
    await backend.initialize()
    envelope, _ = _authority({"public_text": "safe"})
    _, wrong_receipt = _authority(
        {"public_text": "other"}, evidence_id="evidence-2", receipt_id="admission-2"
    )
    with pytest.raises(ValueError, match="does not bind"):
        await backend.ingest_committed_evidence(envelope, wrong_receipt)
    unsupported = _authority(
        {"public_text": "safe"},
        evidence_id="evidence-3",
        source_ref="turn-3/user",
        receipt_id="admission-3",
        filter_policy="credential-filter/future",
    )
    with pytest.raises(MemoryValidationError, match="filter_policy_unsupported"):
        await backend.ingest_committed_evidence(*unsupported)
    assert (await _counts(backend))["evidence_envelopes"] == 0
    await backend.close()
