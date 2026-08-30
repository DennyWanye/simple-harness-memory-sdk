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
    from simple_harness_memory.core.suppression import (
        OrdinaryMemoryPurpose,
        SealedAuditAccessDecision,
        SealedAuditAccessReceipt,
        SuppressionCandidate,
        SuppressionDecision,
        SuppressionRequest,
        SuppressionResolution,
        SuppressionRevokeRequest,
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
SUPPRESSION_FAULT_POINTS = (
    "suppression.before_begin",
    "suppression.after_begin",
    "suppression.after_directive",
    "suppression.after_target",
    "suppression.before_outbox",
    "suppression.after_outbox",
    "suppression.before_commit",
    "suppression.after_commit",
)
logger = structlog.get_logger("simple_harness_memory.backends.sqlite_v5")
_DEFAULT_FILTER_POLICIES = frozenset({"credential-filter/v1"})


class SQLiteHumanMemoryBackend:
    """Own the fresh v5 SQLite root and suppression-first repository APIs."""

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
        """Ordinary export; active suppression always wins over exact identity."""

        from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

        return await self._ordinary_evidence_record(evidence_id, OrdinaryMemoryPurpose.EXPORT)

    async def read_ingested_evidence(self, evidence_id: str) -> IngestedEvidenceRecord:
        """Ordinary exact read with the same synchronous suppression authority."""

        from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

        return await self._ordinary_evidence_record(evidence_id, OrdinaryMemoryPurpose.READ)

    async def search_evidence_ids(self, subject: str) -> tuple[str, ...]:
        from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

        return await self._visible_evidence_ids(subject, OrdinaryMemoryPurpose.SEARCH)

    async def recall_evidence_ids(self, subject: str) -> tuple[str, ...]:
        from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

        return await self._visible_evidence_ids(subject, OrdinaryMemoryPurpose.RECALL)

    async def projection_evidence_ids(self, subject: str) -> tuple[str, ...]:
        from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

        return await self._visible_evidence_ids(subject, OrdinaryMemoryPurpose.PROJECTION)

    async def _ordinary_evidence_record(
        self, evidence_id: str, purpose: OrdinaryMemoryPurpose
    ) -> IngestedEvidenceRecord:
        from simple_harness_memory.core.suppression import (
            SuppressionCandidate,
            SuppressionDenied,
        )

        if not isinstance(evidence_id, str) or not evidence_id.strip() or "\x00" in evidence_id:
            raise MemoryValidationError("evidence_id_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            subject = await self._read_evidence_subject(evidence_id)
            if subject is None:
                raise KeyError("evidence_not_found")
            resolution = await self._resolve_suppression_unlocked(
                SuppressionCandidate(subject, evidence_id=evidence_id), purpose
            )
            if resolution.denied:
                raise SuppressionDenied()
            record = await self._read_ingested_record(evidence_id)
        if record is None:
            raise KeyError("evidence_not_found")
        return record

    async def _visible_evidence_ids(
        self, subject: str, purpose: OrdinaryMemoryPurpose
    ) -> tuple[str, ...]:
        from simple_harness_memory.core.suppression import SuppressionCandidate

        if not isinstance(subject, str) or not subject.strip() or "\x00" in subject:
            raise MemoryValidationError("suppression_subject_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            async with self._db.execute(
                "SELECT evidence_id FROM evidence_envelopes WHERE subject=? ORDER BY evidence_id",
                (subject,),
            ) as cursor:
                rows = await cursor.fetchall()
            visible: list[str] = []
            for row in rows:
                evidence_id = str(row["evidence_id"])
                resolution = await self._resolve_suppression_unlocked(
                    SuppressionCandidate(subject, evidence_id=evidence_id), purpose
                )
                if not resolution.denied:
                    visible.append(evidence_id)
        return tuple(visible)

    async def suppress(self, request: SuppressionRequest) -> SuppressionDecision:
        from simple_harness_memory.core.suppression import (
            SuppressionAction,
            SuppressionDecision,
            SuppressionRequest,
        )

        if type(request) is not SuppressionRequest:
            raise TypeError("request must use SuppressionRequest")
        directive_id = _stable_id("suppression-directive", request.subject, request.request_id)
        outbox_id = _stable_id("suppression-rebuild-outbox", directive_id)
        decision = SuppressionDecision(
            directive_id,
            request.request_id,
            request.subject,
            SuppressionAction.DIRECTIVE,
            request.scope_kind,
            request.scope_ref,
            request.reason_code,
            request.requested_at,
            request.purpose,
            None,
            outbox_id,
        )
        return await self._append_suppression_decision(decision)

    async def revoke_suppression(
        self, request: SuppressionRevokeRequest
    ) -> SuppressionDecision:
        from simple_harness_memory.core.suppression import (
            SuppressionAction,
            SuppressionDecision,
            SuppressionRevokeRequest,
        )

        if type(request) is not SuppressionRevokeRequest:
            raise TypeError("request must use SuppressionRevokeRequest")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            replay = await self._read_suppression_by_request(request.request_id)
            if replay is not None:
                if (
                    replay.action is not SuppressionAction.REVOKE
                    or replay.subject != request.subject
                    or replay.supersedes_directive_id != request.directive_id
                    or replay.reason_code != request.reason_code
                    or replay.effective_at != request.requested_at
                ):
                    raise MemoryIdempotencyConflict("suppression_request_replay_conflict")
                return replay
            original = await self._read_suppression_decision(request.directive_id)
            if (
                original is None
                or original.action is not SuppressionAction.DIRECTIVE
                or original.subject != request.subject
            ):
                raise MemoryValidationError("suppression_directive_not_found")
            async with self._db.execute(
                "SELECT 1 FROM suppression_directives WHERE event_kind='revoke' "
                "AND supersedes_directive_id=? LIMIT 1",
                (original.directive_id,),
            ) as cursor:
                if await cursor.fetchone() is not None:
                    raise MemoryIdempotencyConflict("suppression_directive_already_revoked")
            directive_id = _stable_id("suppression-revoke", request.subject, request.request_id)
            decision = SuppressionDecision(
                directive_id,
                request.request_id,
                request.subject,
                SuppressionAction.REVOKE,
                original.scope_kind,
                original.scope_ref,
                request.reason_code,
                request.requested_at,
                original.purpose,
                original.directive_id,
                _stable_id("suppression-rebuild-outbox", directive_id),
            )
            return await self._append_suppression_decision_unlocked(decision)

    async def resolve_suppression(
        self,
        candidate: SuppressionCandidate,
        purpose: OrdinaryMemoryPurpose,
    ) -> SuppressionResolution:
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        if type(candidate) is not SuppressionCandidate:
            raise TypeError("candidate must use SuppressionCandidate")
        if not isinstance(purpose, OrdinaryMemoryPurpose):
            raise TypeError("purpose must use OrdinaryMemoryPurpose")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            return await self._resolve_suppression_unlocked(candidate, purpose)

    async def _resolve_suppression_unlocked(
        self,
        candidate: SuppressionCandidate,
        purpose: OrdinaryMemoryPurpose,
    ) -> SuppressionResolution:
        from simple_harness_memory.core.suppression import (
            SuppressionResolution,
            SuppressionScopeKind,
        )

        assert self._db is not None
        targets = [(SuppressionScopeKind.SUBJECT.value, candidate.subject)]
        if candidate.evidence_id is not None:
            targets.append((SuppressionScopeKind.EVIDENCE.value, candidate.evidence_id))
        if candidate.memory_id is not None:
            targets.append((SuppressionScopeKind.MEMORY.value, candidate.memory_id))
        targets.extend((SuppressionScopeKind.ENTITY.value, item) for item in candidate.entity_ids)
        predicates = " OR ".join("(t.target_kind=? AND t.target_ref=?)" for _ in targets)
        parameters: list[object] = [candidate.subject, purpose.value]
        for target_kind, target_ref in targets:
            parameters.extend((target_kind, target_ref))
        async with self._db.execute(
            "SELECT DISTINCT d.directive_id FROM suppression_directives d "
            "JOIN suppression_targets t ON t.directive_id=d.directive_id "
            "WHERE d.principal_id=? AND d.event_kind='directive' "
            "AND (d.purpose IS NULL OR d.purpose=?) AND ("
            + predicates
            + ") AND NOT EXISTS(SELECT 1 FROM suppression_directives r "
            "WHERE r.event_kind='revoke' AND r.supersedes_directive_id=d.directive_id) "
            "ORDER BY d.directive_id",
            tuple(parameters),
        ) as cursor:
            directive_ids = tuple(str(row[0]) for row in await cursor.fetchall())
        return SuppressionResolution(bool(directive_ids), directive_ids, _timestamp(self._now()))

    async def _append_suppression_decision(
        self, decision: SuppressionDecision
    ) -> SuppressionDecision:
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            replay = await self._read_suppression_by_request(decision.request_id)
            if replay is not None:
                if replay != decision:
                    raise MemoryIdempotencyConflict("suppression_request_replay_conflict")
                return replay
            return await self._append_suppression_decision_unlocked(decision)

    async def _append_suppression_decision_unlocked(
        self, decision: SuppressionDecision
    ) -> SuppressionDecision:
        assert self._db is not None
        payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "directive_id": decision.directive_id,
            "subject": decision.subject,
            "action": decision.action.value,
            "scope_kind": decision.scope_kind.value,
            "scope_ref": decision.scope_ref,
        }
        payload_json = canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        begun = False
        committed = False
        try:
            self._fault("suppression.before_begin")
            await self._db.execute("BEGIN IMMEDIATE")
            begun = True
            self._fault("suppression.after_begin")
            await self._db.execute(
                "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,"
                "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
                (
                    decision.subject,
                    decision.subject,
                    decision.subject,
                    decision.subject,
                    decision.effective_at,
                ),
            )
            await self._db.execute(
                "INSERT INTO suppression_directives(directive_id,request_id,principal_id,"
                "event_kind,scope_kind,scope_ref,purpose,reason_code,decision_hash,"
                "supersedes_directive_id,effective_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision.directive_id,
                    decision.request_id,
                    decision.subject,
                    decision.action.value,
                    decision.scope_kind.value,
                    decision.scope_ref,
                    None if decision.purpose is None else decision.purpose.value,
                    decision.reason_code,
                    decision.decision_hash,
                    decision.supersedes_directive_id,
                    decision.effective_at,
                ),
            )
            self._fault("suppression.after_directive")
            await self._db.execute(
                "INSERT INTO suppression_targets(directive_id,ordinal,target_kind,target_ref) "
                "VALUES(?,1,?,?)",
                (decision.directive_id, decision.scope_kind.value, decision.scope_ref),
            )
            self._fault("suppression.after_target")
            self._fault("suppression.before_outbox")
            await self._db.execute(
                "INSERT INTO outbox(outbox_id,principal_id,topic,idempotency_key,payload,"
                "payload_hash,state,next_attempt_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'pending',?,?,?)",
                (
                    decision.rebuild_outbox_id,
                    decision.subject,
                    "memory.suppression.rebuild",
                    decision.directive_id,
                    payload_json,
                    payload_hash,
                    decision.effective_at,
                    decision.effective_at,
                    decision.effective_at,
                ),
            )
            self._fault("suppression.after_outbox")
            self._fault("suppression.before_commit")
            await self._db.execute("COMMIT")
            committed = True
            self._fault("suppression.after_commit")
        except BaseException:
            if begun and not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")
            raise
        logger.info(
            "memory.suppression_appended",
            directive_id_hash=_opaque_hash(decision.directive_id),
            subject_hash=_opaque_hash(decision.subject),
            action=decision.action.value,
        )
        return decision

    async def _read_suppression_by_request(
        self, request_id: str
    ) -> SuppressionDecision | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM suppression_directives WHERE request_id=?", (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _suppression_decision_from_row(row)

    async def _read_suppression_decision(
        self, directive_id: str
    ) -> SuppressionDecision | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM suppression_directives WHERE directive_id=?", (directive_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _suppression_decision_from_row(row)

    async def issue_sealed_audit_access(
        self, decision: SealedAuditAccessDecision
    ) -> SealedAuditAccessReceipt:
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDecision,
            SealedAuditAccessReceipt,
        )

        if type(decision) is not SealedAuditAccessDecision:
            raise TypeError("decision must use SealedAuditAccessDecision")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        receipt = SealedAuditAccessReceipt(
            _stable_id("sealed-audit-access", decision.subject, decision.decision_id),
            decision.decision_id,
            decision.subject,
            decision.scope_kind,
            decision.scope_ref,
            decision.purpose,
            decision.decision_hash,
            decision.max_reads,
            decision.issued_at,
            decision.expires_at,
        )
        async with self._write_lock:
            existing = await self._read_audit_access_by_decision(decision.decision_id)
            if existing is not None:
                if existing != receipt:
                    raise MemoryIdempotencyConflict("sealed_audit_decision_replay_conflict")
                return existing
            begun = False
            committed = False
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
                await self._db.execute(
                    "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,"
                    "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
                    (
                        decision.subject,
                        decision.subject,
                        decision.subject,
                        decision.subject,
                        decision.issued_at,
                    ),
                )
                await self._db.execute(
                    "INSERT INTO sealed_audit_access_receipts(access_receipt_id,decision_id,"
                    "principal_id,purpose,scope_kind,scope_ref,reason_code,"
                    "disclosure_context_json,decision_hash,max_reads,issued_at,expires_at,"
                    "receipt_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt.access_receipt_id,
                        receipt.decision_id,
                        receipt.subject,
                        receipt.purpose.value,
                        receipt.scope_kind.value,
                        receipt.scope_ref,
                        decision.reason_code,
                        canonical_json(decision.disclosure_context.to_json()),
                        receipt.decision_hash,
                        receipt.max_reads,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.receipt_hash,
                    ),
                )
                await self._db.execute("COMMIT")
                committed = True
            except BaseException:
                if begun and not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
                raise
        return receipt

    async def export_sealed_evidence(
        self,
        evidence_id: str,
        access_receipt: SealedAuditAccessReceipt,
    ) -> IngestedEvidenceRecord:
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDenied,
            SealedAuditAccessReceipt,
            SuppressionScopeKind,
        )

        if type(access_receipt) is not SealedAuditAccessReceipt:
            raise TypeError("access_receipt must use SealedAuditAccessReceipt")
        if not isinstance(evidence_id, str) or not evidence_id.strip() or "\x00" in evidence_id:
            raise MemoryValidationError("evidence_id_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        denial: str | None = None
        record: IngestedEvidenceRecord | None = None
        async with self._write_lock:
            stored = await self._read_audit_access_by_decision(access_receipt.decision_id)
            if stored != access_receipt:
                denial = "sealed_audit_receipt_differs"
            now = _timestamp(self._now())
            subject = await self._read_evidence_subject(evidence_id)
            if denial is None and subject is None:
                denial = "sealed_audit_evidence_not_found"
            elif denial is None and now >= access_receipt.expires_at:
                denial = "sealed_audit_access_expired"
            elif denial is None and access_receipt.subject != subject:
                denial = "sealed_audit_subject_differs"
            elif denial is None and access_receipt.scope_kind is SuppressionScopeKind.EVIDENCE and (
                access_receipt.scope_ref != evidence_id
            ):
                denial = "sealed_audit_scope_differs"
            elif denial is None and access_receipt.scope_kind is SuppressionScopeKind.SUBJECT and (
                access_receipt.scope_ref != subject
            ):
                denial = "sealed_audit_scope_differs"
            elif denial is None and access_receipt.scope_kind not in {
                SuppressionScopeKind.EVIDENCE,
                SuppressionScopeKind.SUBJECT,
            }:
                denial = "sealed_audit_scope_unsupported"
            async with self._db.execute(
                "SELECT COUNT(*) FROM sealed_audit_access_events WHERE access_receipt_id=? "
                "AND outcome='granted'",
                (access_receipt.access_receipt_id,),
            ) as cursor:
                usage = await cursor.fetchone()
            if denial is None and usage is not None and int(usage[0]) >= access_receipt.max_reads:
                denial = "sealed_audit_access_exhausted"
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                if denial is None:
                    record = await self._read_ingested_record(evidence_id)
                    if record is None:
                        denial = "sealed_audit_evidence_not_found"
                event_id = f"sealed-audit-event-{uuid4().hex}"
                event_payload: dict[str, JsonValue] = {
                    "schema_version": 1,
                    "event_id": event_id,
                    "access_receipt_id": access_receipt.access_receipt_id,
                    "evidence_id": evidence_id,
                    "purpose": access_receipt.purpose.value,
                    "outcome": "granted" if denial is None else "denied",
                    "reason_code": "sealed_audit_access_granted" if denial is None else denial,
                    "occurred_at": now,
                }
                await self._db.execute(
                    "INSERT INTO sealed_audit_access_events(event_id,access_receipt_id,"
                    "evidence_id,purpose,outcome,reason_code,occurred_at,event_hash) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        access_receipt.access_receipt_id,
                        evidence_id,
                        access_receipt.purpose.value,
                        "granted" if denial is None else "denied",
                        event_payload["reason_code"],
                        now,
                        hashlib.sha256(canonical_json(event_payload).encode()).hexdigest(),
                    ),
                )
                await self._db.execute("COMMIT")
                committed = True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
        if denial is not None or record is None:
            raise SealedAuditAccessDenied(denial)
        return record

    async def _read_audit_access_by_decision(
        self, decision_id: str
    ) -> SealedAuditAccessReceipt | None:
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessReceipt,
            SealedAuditPurpose,
            SuppressionScopeKind,
        )

        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM sealed_audit_access_receipts WHERE decision_id=?", (decision_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        receipt = SealedAuditAccessReceipt(
            str(row["access_receipt_id"]),
            str(row["decision_id"]),
            str(row["principal_id"]),
            SuppressionScopeKind(str(row["scope_kind"])),
            str(row["scope_ref"]),
            SealedAuditPurpose(str(row["purpose"])),
            str(row["decision_hash"]),
            int(row["max_reads"]),
            float(row["issued_at"]),
            float(row["expires_at"]),
        )
        if receipt.receipt_hash != str(row["receipt_hash"]):
            raise MemoryCorruptionError("stored sealed audit access receipt hash differs")
        return receipt

    async def _read_evidence_subject(self, evidence_id: str) -> str | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT subject FROM evidence_envelopes WHERE evidence_id=?", (evidence_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row["subject"])

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


def _suppression_decision_from_row(row: aiosqlite.Row) -> SuppressionDecision:
    from simple_harness_memory.core.suppression import (
        OrdinaryMemoryPurpose,
        SuppressionAction,
        SuppressionDecision,
        SuppressionScopeKind,
    )

    directive_id = str(row["directive_id"])
    decision = SuppressionDecision(
        directive_id,
        str(row["request_id"]),
        str(row["principal_id"]),
        SuppressionAction(str(row["event_kind"])),
        SuppressionScopeKind(str(row["scope_kind"])),
        str(row["scope_ref"]),
        str(row["reason_code"]),
        float(row["effective_at"]),
        None
        if row["purpose"] is None
        else OrdinaryMemoryPurpose(str(row["purpose"])),
        None
        if row["supersedes_directive_id"] is None
        else str(row["supersedes_directive_id"]),
        _stable_id("suppression-rebuild-outbox", directive_id),
    )
    if decision.decision_hash != str(row["decision_hash"]):
        raise MemoryCorruptionError("stored suppression decision hash differs")
    return decision


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
    "SUPPRESSION_FAULT_POINTS",
    "SQLiteHumanMemoryBackend",
)
