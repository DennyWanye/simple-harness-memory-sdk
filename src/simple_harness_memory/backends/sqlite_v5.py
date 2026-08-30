"""Fail-closed initializer for the fresh human-memory v1 SQLite root."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import math
import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import uuid4

import aiosqlite
import structlog
from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.backends.schema_v5 import (
    REQUIRED_TABLES,
    SCHEMA_CHECKSUM,
    SCHEMA_EPOCH,
    SCHEMA_VERSION,
    InitializationReceipt,
    ddl_statements,
)
from simple_harness_memory.backends.storage import secure_sqlite_path, verify_sqlite_path
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLegacySchemaUnsupported,
    MemoryValidationError,
    MemoryWriterConflict,
)

if TYPE_CHECKING:
    from simple_harness.runtime import SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt

    from simple_harness_memory.core.evidence import (
        EvidenceIngestionReceipt,
        IngestedEvidenceRecord,
    )

FaultInjector = Callable[[str], None]
_DDL = ddl_statements()
INITIALIZATION_FAULT_POINTS = (
    "before_begin",
    "after_begin",
    *(
        point
        for index in range(len(_DDL))
        for point in (f"before_ddl.{index}", f"after_ddl.{index}")
    ),
    "before_receipt",
    "after_receipt",
    "before_meta",
    "after_meta",
    "before_commit",
    "after_commit",
)
INGESTION_FAULT_POINTS = (
    "ingestion.before_begin",
    "ingestion.after_begin",
    "ingestion.after_principal",
    "ingestion.after_envelope",
    "ingestion.after_items",
    "ingestion.after_links",
    "ingestion.after_receipt",
    "ingestion.after_job",
    "ingestion.after_outbox",
    "ingestion.before_commit",
    "ingestion.after_commit",
)
logger = structlog.get_logger("simple_harness_memory.backends.sqlite_v5")
_DEFAULT_FILTER_POLICIES = frozenset({"credential-filter/v1"})


class SQLiteHumanMemoryBackend:
    """Own the v5 SQLite root lifecycle without exposing unfinished S2 APIs."""

    def __init__(
        self,
        db_path: str | os.PathLike[str],
        *,
        fault_injector: FaultInjector | None = None,
        now: Callable[[], float] = time.time,
        supported_filter_policies: frozenset[str] = _DEFAULT_FILTER_POLICIES,
    ) -> None:
        self._db_path = Path(db_path)
        self._fault_injector = fault_injector
        self._now = now
        self._db: aiosqlite.Connection | None = None
        self._secure_path: Path | None = None
        self._writer_lock_file: Any | None = None
        self._initialize_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._receipt: InitializationReceipt | None = None
        self._busy_timeout_ms = 5000
        if not supported_filter_policies or any(
            not isinstance(item, str) or not item.strip() for item in supported_filter_policies
        ):
            raise MemoryValidationError("supported filter policies are invalid")
        self._supported_filter_policies = frozenset(supported_filter_policies)

    @property
    def initialization_receipt(self) -> InitializationReceipt | None:
        return self._receipt

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        return self._db

    async def initialize(self) -> InitializationReceipt:
        async with self._initialize_lock:
            if self._db is not None and self._receipt is not None:
                return self._receipt
            classification, probed_receipt = _probe_existing_read_only(self._db_path)
            if classification == "unsupported":
                raise MemoryLegacySchemaUnsupported()
            try:
                self._secure_path = secure_sqlite_path(self._db_path)
                self._acquire_writer_lease()
                self._db = await aiosqlite.connect(str(self._secure_path), isolation_level=None)
                self._db.row_factory = aiosqlite.Row
                current = await self._classify_open_connection()
                if current is not None:
                    if probed_receipt is not None and current != probed_receipt:
                        raise MemoryCorruptionError("initialization receipt changed during open")
                    receipt = current
                else:
                    receipt = await self._initialize_fresh()
                await self._db.execute("PRAGMA foreign_keys = ON")
                async with self._db.execute("PRAGMA foreign_keys") as cursor:
                    enabled = await cursor.fetchone()
                if enabled is None or int(enabled[0]) != 1:
                    raise MemoryCorruptionError("foreign key enforcement unavailable")
                async with self._db.execute("PRAGMA journal_mode = WAL") as cursor:
                    journal = await cursor.fetchone()
                if journal is None or str(journal[0]).lower() != "wal":
                    raise MemoryCorruptionError("WAL journal mode unavailable")
                await self._db.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
                await self._validate_integrity()
                verify_sqlite_path(self._secure_path)
                self._receipt = receipt
                return receipt
            except BaseException:
                await self._close_after_failure()
                raise

    async def close(self) -> None:
        async with self._initialize_lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
            self._receipt = None
            self._release_writer_lease()

    async def ingest_committed_evidence(
        self,
        envelope: SanitizedEvidenceEnvelope,
        receipt: SanitizedEvidenceReceipt,
    ) -> EvidenceIngestionReceipt:
        """Atomically admit immutable public evidence and its first mutation work."""

        from simple_harness_memory.core.evidence import (
            EvidenceIngestionReceipt,
            validate_sanitized_evidence,
        )

        span = validate_sanitized_evidence(
            envelope,
            receipt,
            supported_filter_policies=tuple(self._supported_filter_policies),
        )
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        accepted_at = _timestamp(self._now())
        principal_id = envelope.subject
        ingestion_receipt_id = _stable_id(
            "evidence-ingestion", principal_id, envelope.source_ref, envelope.envelope_hash
        )
        mutation_job_id = _stable_id("evidence-mutation-job", envelope.evidence_id)
        outbox_id = _stable_id("evidence-mutation-outbox", envelope.evidence_id)
        ingestion_receipt = EvidenceIngestionReceipt(
            ingestion_receipt_id,
            envelope.evidence_id,
            envelope.source_ref,
            envelope.source_hash,
            envelope.sanitized_hash,
            envelope.envelope_hash,
            receipt.receipt_id,
            receipt.receipt_hash,
            mutation_job_id,
            outbox_id,
            accepted_at,
        )
        envelope_json = envelope.to_json()
        payload_json = canonical_json(envelope_json["sanitized_payload"])
        disclosure_json = canonical_json(envelope_json["disclosure_context"])
        removed_spans_json = canonical_json(envelope_json["removed_spans"])
        admission_receipt_json = canonical_json(receipt.to_json())
        mutation_payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "evidence_id": envelope.evidence_id,
            "envelope_hash": envelope.envelope_hash,
            "source_hash": envelope.source_hash,
        }
        mutation_payload_json = canonical_json(mutation_payload)
        mutation_payload_hash = hashlib.sha256(
            mutation_payload_json.encode("utf-8")
        ).hexdigest()
        outbox_payload: dict[str, JsonValue] = {
            **mutation_payload,
            "job_id": mutation_job_id,
        }
        outbox_payload_json = canonical_json(outbox_payload)
        outbox_payload_hash = hashlib.sha256(outbox_payload_json.encode("utf-8")).hexdigest()

        async with self._write_lock:
            existing = await self._read_ingestion_by_source(principal_id, envelope.source_ref)
            if existing is not None:
                return _verify_replay(existing, envelope)
            admitted = await self._read_ingestion_by_admission_receipt(receipt.receipt_id)
            if admitted is not None:
                raise MemoryIdempotencyConflict("evidence_admission_receipt_conflict")
            begun = False
            committed = False
            try:
                self._fault("ingestion.before_begin")
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
                self._fault("ingestion.after_begin")
                await self._db.execute(
                    "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,"
                    "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
                    (principal_id, principal_id, principal_id, principal_id, accepted_at),
                )
                self._fault("ingestion.after_principal")
                await self._db.execute(
                    "INSERT INTO evidence_envelopes("
                    "evidence_id,principal_id,run_id,subject,source_kind,source_ref,source_hash,"
                    "sanitized_hash,envelope_hash,filter_policy_version,disclosure_json,"
                    "disclosure_hash,removed_spans_json,sanitized_payload,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        envelope.evidence_id,
                        principal_id,
                        envelope.run_id,
                        envelope.subject,
                        envelope.source_kind.value,
                        envelope.source_ref,
                        envelope.source_hash,
                        envelope.sanitized_hash,
                        envelope.envelope_hash,
                        envelope.filter_policy_version,
                        disclosure_json,
                        envelope.disclosure_context.context_hash,
                        removed_spans_json,
                        payload_json,
                        accepted_at,
                    ),
                )
                self._fault("ingestion.after_envelope")
                await self._db.execute(
                    "INSERT INTO evidence_items(evidence_id,ordinal,item_kind,content_hash,"
                    "public_payload,blob_ref) VALUES(?,?,?,?,?,?)",
                    (
                        envelope.evidence_id,
                        span.ordinal,
                        span.item_kind,
                        span.content_hash,
                        None if span.public_payload is None else payload_json,
                        span.blob_ref,
                    ),
                )
                self._fault("ingestion.after_items")
                await self._db.executemany(
                    "INSERT INTO evidence_links(evidence_id,ordinal,target_evidence_id,"
                    "target_content_hash) VALUES(?,?,?,?)",
                    (
                        (
                            envelope.evidence_id,
                            ref.ordinal,
                            ref.evidence_id,
                            ref.content_hash,
                        )
                        for ref in envelope.evidence_refs
                    ),
                )
                self._fault("ingestion.after_links")
                await self._db.execute(
                    "INSERT INTO ingestion_receipts(receipt_id,evidence_id,source_hash,"
                    "envelope_hash,admission_receipt_id,admission_receipt_json,"
                    "admission_receipt_hash,receipt_hash,accepted_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        ingestion_receipt.receipt_id,
                        envelope.evidence_id,
                        envelope.source_hash,
                        envelope.envelope_hash,
                        receipt.receipt_id,
                        admission_receipt_json,
                        receipt.receipt_hash,
                        ingestion_receipt.receipt_hash,
                        accepted_at,
                    ),
                )
                self._fault("ingestion.after_receipt")
                await self._db.execute(
                    "INSERT INTO jobs(job_id,principal_id,job_kind,idempotency_key,payload,"
                    "payload_hash,state,next_attempt_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,'pending',?,?,?)",
                    (
                        mutation_job_id,
                        principal_id,
                        "analyze_evidence",
                        envelope.evidence_id,
                        mutation_payload_json,
                        mutation_payload_hash,
                        accepted_at,
                        accepted_at,
                        accepted_at,
                    ),
                )
                self._fault("ingestion.after_job")
                await self._db.execute(
                    "INSERT INTO outbox(outbox_id,principal_id,topic,idempotency_key,payload,"
                    "payload_hash,state,next_attempt_at,created_at,updated_at) "
                    "VALUES(?,?,?, ?,?,?,'pending',?,?,?)",
                    (
                        outbox_id,
                        principal_id,
                        "memory.mutation.requested",
                        envelope.evidence_id,
                        outbox_payload_json,
                        outbox_payload_hash,
                        accepted_at,
                        accepted_at,
                        accepted_at,
                    ),
                )
                self._fault("ingestion.after_outbox")
                self._fault("ingestion.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("ingestion.after_commit")
            except BaseException:
                if begun and not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
                logger.warning(
                    "memory.evidence_ingestion_rejected",
                    stable_code="evidence_ingestion_failed",
                    evidence_id_hash=_opaque_hash(envelope.evidence_id),
                    source_ref_hash=_opaque_hash(envelope.source_ref),
                )
                raise
        logger.info(
            "memory.evidence_ingested",
            evidence_id_hash=_opaque_hash(envelope.evidence_id),
            source_ref_hash=_opaque_hash(envelope.source_ref),
            envelope_hash=envelope.envelope_hash,
        )
        return ingestion_receipt

    async def export_ingested_evidence(self, evidence_id: str) -> IngestedEvidenceRecord:
        """Export one exact immutable record; Task 3 will wrap ordinary access in suppression."""

        if not isinstance(evidence_id, str) or not evidence_id.strip() or "\x00" in evidence_id:
            raise MemoryValidationError("evidence_id_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            record = await self._read_ingested_record(evidence_id)
        if record is None:
            raise KeyError("evidence_not_found")
        return record

    async def _read_ingestion_by_source(
        self, principal_id: str, source_ref: str
    ) -> EvidenceIngestionReceipt | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT e.*,r.receipt_id,r.admission_receipt_id,r.admission_receipt_hash,"
            "r.receipt_hash,r.accepted_at FROM evidence_envelopes e JOIN ingestion_receipts r "
            "ON r.evidence_id=e.evidence_id WHERE e.principal_id=? AND e.source_ref=?",
            (principal_id, source_ref),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _ingestion_receipt_from_row(row)

    async def _read_ingestion_by_admission_receipt(
        self, admission_receipt_id: str
    ) -> EvidenceIngestionReceipt | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT e.*,r.receipt_id,r.admission_receipt_id,r.admission_receipt_hash,"
            "r.receipt_hash,r.accepted_at FROM evidence_envelopes e JOIN ingestion_receipts r "
            "ON r.evidence_id=e.evidence_id WHERE r.admission_receipt_id=?",
            (admission_receipt_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _ingestion_receipt_from_row(row)

    async def _read_ingested_record(self, evidence_id: str) -> IngestedEvidenceRecord | None:
        from simple_harness.runtime import (
            EvidenceRef,
            SanitizedEvidenceEnvelope,
            SanitizedEvidenceReceipt,
        )

        from simple_harness_memory.core.evidence import (
            EvidenceSpan,
            IngestedEvidenceRecord,
            validate_sanitized_evidence,
        )

        assert self._db is not None
        async with self._db.execute(
            "SELECT e.*,r.receipt_id,r.admission_receipt_id,r.admission_receipt_json,"
            "r.admission_receipt_hash,r.receipt_hash,r.accepted_at FROM evidence_envelopes e "
            "JOIN ingestion_receipts r ON r.evidence_id=e.evidence_id WHERE e.evidence_id=?",
            (evidence_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        async with self._db.execute(
            "SELECT ordinal,target_evidence_id,target_content_hash FROM evidence_links "
            "WHERE evidence_id=? ORDER BY ordinal",
            (evidence_id,),
        ) as cursor:
            link_rows = await cursor.fetchall()
        async with self._db.execute(
            "SELECT ordinal,item_kind,content_hash,public_payload,blob_ref FROM evidence_items "
            "WHERE evidence_id=? ORDER BY ordinal",
            (evidence_id,),
        ) as cursor:
            item_rows = await cursor.fetchall()
        envelope_payload: dict[str, object] = {
            "schema_version": 1,
            "evidence_id": str(row["evidence_id"]),
            "run_id": str(row["run_id"]),
            "subject": str(row["subject"]),
            "source_kind": str(row["source_kind"]),
            "source_ref": str(row["source_ref"]),
            "source_hash": str(row["source_hash"]),
            "sanitized_payload": json.loads(str(row["sanitized_payload"])),
            "sanitized_hash": str(row["sanitized_hash"]),
            "filter_policy_version": str(row["filter_policy_version"]),
            "removed_spans": json.loads(str(row["removed_spans_json"])),
            "disclosure_context": json.loads(str(row["disclosure_json"])),
            "evidence_refs": [
                EvidenceRef(
                    str(link["target_evidence_id"]),
                    str(link["target_content_hash"]),
                    int(link["ordinal"]),
                ).to_json()
                for link in link_rows
            ],
        }
        envelope = SanitizedEvidenceEnvelope.from_json(envelope_payload)
        if envelope.envelope_hash != str(row["envelope_hash"]):
            raise MemoryCorruptionError("stored evidence envelope hash differs")
        admission_payload = json.loads(str(row["admission_receipt_json"]))
        if not isinstance(admission_payload, dict):
            raise MemoryCorruptionError("stored evidence admission receipt is invalid")
        admission_receipt = SanitizedEvidenceReceipt.from_json(admission_payload)
        admission_receipt.verify(envelope)
        if admission_receipt.receipt_hash != str(row["admission_receipt_hash"]):
            raise MemoryCorruptionError("stored evidence admission receipt hash differs")
        spans = tuple(
            EvidenceSpan(
                int(item["ordinal"]),
                str(item["item_kind"]),
                str(item["content_hash"]),
                public_payload=(
                    None
                    if item["public_payload"] is None
                    else json.loads(str(item["public_payload"]))
                ),
                blob_ref=None if item["blob_ref"] is None else str(item["blob_ref"]),
            )
            for item in item_rows
        )
        expected_span = validate_sanitized_evidence(
            envelope,
            admission_receipt,
            supported_filter_policies=tuple(self._supported_filter_policies),
        )
        if spans != (expected_span,):
            raise MemoryCorruptionError("stored evidence span differs")
        ingestion_receipt = _ingestion_receipt_from_row(row)
        return IngestedEvidenceRecord(envelope, admission_receipt, ingestion_receipt, spans)

    async def _classify_open_connection(self) -> InitializationReceipt | None:
        assert self._db is not None
        tables = await _async_table_names(self._db)
        if not tables:
            return None
        if tables != REQUIRED_TABLES:
            raise MemoryLegacySchemaUnsupported()
        meta = await _async_meta(self._db)
        return await _async_receipt(self._db, meta)

    async def _initialize_fresh(self) -> InitializationReceipt:
        assert self._db is not None
        receipt = InitializationReceipt(f"init-{uuid4().hex}", self._now())
        begun = False
        committed = False
        try:
            self._fault("before_begin")
            await self._db.execute("BEGIN IMMEDIATE")
            begun = True
            self._fault("after_begin")
            for index, statement in enumerate(_DDL):
                self._fault(f"before_ddl.{index}")
                await self._db.execute(statement)
                self._fault(f"after_ddl.{index}")
            self._fault("before_receipt")
            await self._db.execute(
                "INSERT INTO initialization_receipts("
                "singleton,receipt_id,schema_version,schema_epoch,schema_checksum,created_at,"
                "receipt_hash) VALUES(1,?,?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    receipt.schema_version,
                    receipt.schema_epoch,
                    receipt.schema_checksum,
                    receipt.created_at,
                    receipt.receipt_hash,
                ),
            )
            self._fault("after_receipt")
            self._fault("before_meta")
            await self._db.executemany(
                "INSERT INTO schema_meta(key,value) VALUES(?,?)",
                (
                    ("schema_version", str(SCHEMA_VERSION)),
                    ("schema_epoch", SCHEMA_EPOCH),
                    ("schema_checksum", SCHEMA_CHECKSUM),
                    ("initialization_receipt_id", receipt.receipt_id),
                    ("initialization_receipt_hash", receipt.receipt_hash),
                ),
            )
            self._fault("after_meta")
            self._fault("before_commit")
            await self._db.execute("COMMIT")
            committed = True
            self._fault("after_commit")
            return receipt
        except BaseException:
            if begun and not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")
            raise

    async def _validate_integrity(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA integrity_check") as cursor:
            integrity = await cursor.fetchone()
        if integrity is None or str(integrity[0]) != "ok":
            raise MemoryCorruptionError("human-memory v5 integrity check failed")
        async with self._db.execute("PRAGMA foreign_key_check") as cursor:
            if await cursor.fetchone() is not None:
                raise MemoryCorruptionError("human-memory v5 foreign key check failed")

    async def _close_after_failure(self) -> None:
        if self._db is not None:
            with suppress(Exception):
                await self._db.close()
            self._db = None
        self._receipt = None
        self._release_writer_lease()

    def _fault(self, point: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(point)

    def _acquire_writer_lease(self) -> None:
        if self._writer_lock_file is not None:
            return
        assert self._secure_path is not None
        lock_path = self._secure_path.with_name(self._secure_path.name + ".writer.lock")
        lock_path.touch(mode=0o600, exist_ok=True)
        handle = lock_path.open("r+b")
        try:
            _platform_writer_lock(handle, acquire=True)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise MemoryWriterConflict() from exc
        self._writer_lock_file = handle

    def _release_writer_lease(self) -> None:
        handle = self._writer_lock_file
        if handle is None:
            return
        try:
            _platform_writer_lock(handle, acquire=False)
        finally:
            handle.close()
            self._writer_lock_file = None


def _timestamp(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise MemoryValidationError("evidence_timestamp_invalid")
    return float(value)


def _stable_id(namespace: str, *parts: str) -> str:
    payload = canonical_json(
        {
            "schema_version": 1,
            "namespace": namespace,
            "parts": list(parts),
        }
    )
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _opaque_hash(value: str) -> str:
    return hashlib.sha256(f"memory-log/v1|{value}".encode()).hexdigest()


def _ingestion_receipt_from_row(row: aiosqlite.Row) -> EvidenceIngestionReceipt:
    from simple_harness_memory.core.evidence import EvidenceIngestionReceipt

    evidence_id = str(row["evidence_id"])
    receipt = EvidenceIngestionReceipt(
        str(row["receipt_id"]),
        evidence_id,
        str(row["source_ref"]),
        str(row["source_hash"]),
        str(row["sanitized_hash"]),
        str(row["envelope_hash"]),
        str(row["admission_receipt_id"]),
        str(row["admission_receipt_hash"]),
        _stable_id("evidence-mutation-job", evidence_id),
        _stable_id("evidence-mutation-outbox", evidence_id),
        float(row["accepted_at"]),
    )
    if receipt.receipt_hash != str(row["receipt_hash"]):
        raise MemoryCorruptionError("stored evidence ingestion receipt hash differs")
    return receipt


def _verify_replay(
    existing: EvidenceIngestionReceipt,
    envelope: SanitizedEvidenceEnvelope,
) -> EvidenceIngestionReceipt:
    if existing.source_hash != envelope.source_hash:
        raise MemoryIdempotencyConflict("evidence_source_replay_conflict")
    logger.info(
        "memory.evidence_ingestion_replayed",
        evidence_id_hash=_opaque_hash(envelope.evidence_id),
        source_ref_hash=_opaque_hash(envelope.source_ref),
        envelope_hash=envelope.envelope_hash,
    )
    return existing


def _probe_existing_read_only(
    raw_path: Path,
) -> tuple[str, InitializationReceipt | None]:
    path = _absolute_safe_probe_path(raw_path)
    if not path.exists() or path.stat().st_size == 0:
        return "fresh", None
    # immutable prevents SQLite from creating WAL/SHM sidecars while classifying
    # a legacy target. Schema metadata is committed to the main file before this
    # backend enables WAL, so the probe never needs a journal to identify v5.
    uri = f"file:{quote(os.fspath(path), safe='/')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    except sqlite3.Error as exc:
        raise MemoryLegacySchemaUnsupported() from exc
    connection.row_factory = sqlite3.Row
    try:
        tables = _sync_table_names(connection)
        if not tables:
            return "fresh", None
        if tables != REQUIRED_TABLES:
            return "unsupported", None
        meta = _sync_meta(connection)
        return "v5", _sync_receipt(connection, meta)
    except (MemoryCorruptionError, sqlite3.Error, TypeError, ValueError) as exc:
        raise MemoryLegacySchemaUnsupported() from exc
    finally:
        connection.close()


def _absolute_safe_probe_path(raw_path: Path) -> Path:
    if os.fspath(raw_path) == ":memory:":
        raise MemoryValidationError(":memory: is not a durable storage path")
    path = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
    parent = path.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise MemoryValidationError("database parent directory is unsafe")
    if path.is_symlink():
        raise MemoryValidationError("database path must not be a symlink")
    if path.exists() and not path.is_file():
        raise MemoryValidationError("database path must be a regular file")
    return path


def _sync_table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


async def _async_table_names(connection: aiosqlite.Connection) -> set[str]:
    async with connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


def _sync_meta(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT key,value FROM schema_meta")
    }


async def _async_meta(connection: aiosqlite.Connection) -> dict[str, str]:
    async with connection.execute("SELECT key,value FROM schema_meta") as cursor:
        return {str(row[0]): str(row[1]) for row in await cursor.fetchall()}


def _validate_meta(meta: dict[str, str]) -> None:
    expected = {
        "schema_version": str(SCHEMA_VERSION),
        "schema_epoch": SCHEMA_EPOCH,
        "schema_checksum": SCHEMA_CHECKSUM,
    }
    if set(meta) != {
        *expected,
        "initialization_receipt_id",
        "initialization_receipt_hash",
    } or any(meta.get(key) != value for key, value in expected.items()):
        raise MemoryLegacySchemaUnsupported()


def _receipt_from_row(
    row: sqlite3.Row | aiosqlite.Row, meta: dict[str, str]
) -> InitializationReceipt:
    _validate_meta(meta)
    receipt = InitializationReceipt(
        str(row["receipt_id"]),
        float(row["created_at"]),
        int(row["schema_version"]),
        str(row["schema_epoch"]),
        str(row["schema_checksum"]),
    )
    if str(row["receipt_hash"]) != receipt.receipt_hash:
        raise MemoryCorruptionError("initialization receipt hash differs")
    if meta.get("initialization_receipt_id") != receipt.receipt_id:
        raise MemoryCorruptionError("initialization receipt id differs")
    if meta.get("initialization_receipt_hash") != receipt.receipt_hash:
        raise MemoryCorruptionError("initialization receipt meta hash differs")
    return receipt


def _sync_receipt(
    connection: sqlite3.Connection, meta: dict[str, str]
) -> InitializationReceipt:
    rows = connection.execute("SELECT * FROM initialization_receipts").fetchall()
    if len(rows) != 1:
        raise MemoryCorruptionError("initialization receipt cardinality differs")
    return _receipt_from_row(rows[0], meta)


async def _async_receipt(
    connection: aiosqlite.Connection, meta: dict[str, str]
) -> InitializationReceipt:
    async with connection.execute("SELECT * FROM initialization_receipts") as cursor:
        rows = list(await cursor.fetchall())
    if len(rows) != 1:
        raise MemoryCorruptionError("initialization receipt cardinality differs")
    return _receipt_from_row(rows[0], meta)


def _platform_writer_lock(handle: Any, *, acquire: bool) -> None:
    if os.name == "nt":
        msvcrt: Any = importlib.import_module("msvcrt")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        mode = msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK
        msvcrt.locking(handle.fileno(), mode, 1)
        return
    import fcntl

    mode = fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN
    fcntl.flock(handle.fileno(), mode)


__all__ = (
    "INGESTION_FAULT_POINTS",
    "INITIALIZATION_FAULT_POINTS",
    "SQLiteHumanMemoryBackend",
)
