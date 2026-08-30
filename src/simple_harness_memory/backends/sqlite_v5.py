"""Fail-closed initializer for the fresh human-memory v1 SQLite root."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote
from uuid import uuid4

import aiosqlite
import structlog
from simple_harness.contracts import FrozenJsonValue, JsonValue, canonical_json, thaw_json

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
    MemoryLimitError,
    MemoryValidationError,
    MemoryWriterConflict,
)

if TYPE_CHECKING:
    from simple_harness.runtime import (
        MemoryAnalysisDeliveryReceipt,
        MemoryAnalysisReceipt,
        MemoryAnalysisRequest,
        MemoryAnalysisResult,
        MemoryAnalysisResultEnvelope,
        SanitizedEvidenceEnvelope,
        SanitizedEvidenceReceipt,
    )

    from simple_harness_memory.core.audit import (
        AuditTraceCursor,
        AuditTraceItem,
        AuditTracePage,
        AuditTraceQuery,
        DecisionLedgerEntry,
        LLMInvocationAuditRecord,
        PublicReasoningReference,
    )
    from simple_harness_memory.core.evidence import (
        EvidenceIngestionReceipt,
        IngestedEvidenceRecord,
    )
    from simple_harness_memory.core.jobs import (
        AnalysisApplication,
        AnalysisBatchClaim,
        AnalysisResultCommit,
        MemoryJobWorkerConfig,
        RejectedAnalysisAudit,
        WorkerRunOutcome,
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
JOB_FAULT_POINTS = (
    "job.claim.after_begin",
    "job.claim.before_commit",
    "job.claim.after_commit",
    "job.result.before_commit",
    "job.result.after_commit",
    "job.apply.before_commit",
    "job.apply.after_commit",
    "job.finalize.before_commit",
    "job.finalize.after_commit",
    "job.fail.before_commit",
    "job.fail.after_commit",
)
logger = structlog.get_logger("simple_harness_memory.backends.sqlite_v5")
_DEFAULT_FILTER_POLICIES = frozenset({"credential-filter/v1"})
_AUDIT_IDENTIFIER_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:sk|key|tsk)-?[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(?:xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{10,})\b"),
    re.compile(r"\b(?:npm_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
)


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
        self._audit_cursor_hmac_key: bytes | None = None
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
                self._audit_cursor_hmac_key = await self._read_audit_cursor_hmac_key()
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
            self._audit_cursor_hmac_key = None
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
        mutation_batch_key = _stable_id(
            "evidence-analysis-batch-key",
            principal_id,
            envelope.run_id,
            envelope.disclosure_context.context_hash,
        )
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
                    "INSERT INTO jobs(job_id,principal_id,job_kind,batch_key,evidence_watermark,"
                    "idempotency_key,payload,payload_hash,state,next_attempt_at,created_at,"
                    "updated_at) VALUES(?,?,?,?,?,?,?,?, 'pending',?,?,?)",
                    (
                        mutation_job_id,
                        principal_id,
                        "analyze_evidence",
                        mutation_batch_key,
                        envelope.evidence_id,
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

    async def claim_analysis_batch(
        self,
        config: MemoryJobWorkerConfig,
        worker_id: str,
    ) -> AnalysisBatchClaim | None:
        from simple_harness.runtime import DisclosureContext, EvidenceRef, MemoryAnalysisRequest

        from simple_harness_memory.core.jobs import MemoryJobWorkerConfig

        if type(config) is not MemoryJobWorkerConfig:
            raise TypeError("config must use MemoryJobWorkerConfig")
        _audit_identifier(worker_id, "worker_id")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            self._fault("job.claim.after_begin")
            committed = False
            try:
                now = _timestamp(self._now())
                lease_token = f"analysis-lease-{uuid4().hex}"
                lease_expires_at = now + config.lease_seconds
                async with self._db.execute(
                    "SELECT DISTINCT b.batch_id FROM analysis_batches b "
                    "JOIN analysis_batch_members m ON m.batch_id=b.batch_id "
                    "JOIN jobs j ON j.job_id=m.job_id WHERE j.state='claimed' AND "
                    "j.lease_expires_at<=? "
                    "ORDER BY b.created_at,b.batch_id LIMIT 1",
                    (now,),
                ) as cursor:
                    recover_row = await cursor.fetchone()
                if recover_row is not None:
                    batch_id = str(recover_row["batch_id"])
                    await self._db.execute(
                        "UPDATE jobs SET lease_owner=?,lease_token=?,lease_expires_at=?,"
                        "updated_at=? WHERE job_id IN (SELECT job_id FROM analysis_batch_members "
                        "WHERE batch_id=?) AND state='claimed'",
                        (worker_id, lease_token, lease_expires_at, now, batch_id),
                    )
                    await self._db.execute(
                        "UPDATE job_attempts SET lease_token=? WHERE batch_id=? "
                        "AND state!='applied'",
                        (lease_token, batch_id),
                    )
                    await self._append_batch_events_unlocked(
                        batch_id, "reclaimed", "analysis_lease_reclaimed", now
                    )
                    self._fault("job.claim.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("job.claim.after_commit")
                    return await self._read_analysis_claim_unlocked(
                        batch_id, lease_token, lease_expires_at
                    )

                threshold = now - config.max_batch_wait_seconds
                async with self._db.execute(
                    "SELECT principal_id,batch_key,COUNT(*) AS job_count,"
                    "MIN(created_at) AS oldest FROM jobs WHERE state='pending' "
                    "AND next_attempt_at<=? GROUP BY principal_id,batch_key "
                    "HAVING COUNT(*)>=? OR MIN(created_at)<=? "
                    "ORDER BY oldest,principal_id,batch_key LIMIT 1",
                    (now, config.batch_size, threshold),
                ) as cursor:
                    group_row = await cursor.fetchone()
                if group_row is None:
                    await self._db.execute("COMMIT")
                    committed = True
                    return None
                subject = str(group_row["principal_id"])
                batch_key = str(group_row["batch_key"])
                async with self._db.execute(
                    "SELECT * FROM jobs WHERE state='pending' AND next_attempt_at<=? "
                    "AND principal_id=? AND batch_key=? ORDER BY created_at,job_id LIMIT ?",
                    (now, subject, batch_key, config.batch_size),
                ) as cursor:
                    job_rows = await cursor.fetchall()
                if not job_rows:
                    raise MemoryCorruptionError("eligible analysis batch has no jobs")
                evidence_refs: list[EvidenceRef] = []
                run_id: str | None = None
                disclosure: DisclosureContext | None = None
                member_attempts: list[int] = []
                for ordinal, job_row in enumerate(job_rows, start=1):
                    payload = json.loads(str(job_row["payload"]))
                    if not isinstance(payload, dict) or not isinstance(
                        payload.get("evidence_id"), str
                    ):
                        raise MemoryCorruptionError("analysis job payload is malformed")
                    payload_json = canonical_json(payload)
                    if (
                        hashlib.sha256(payload_json.encode()).hexdigest()
                        != str(job_row["payload_hash"])
                        or str(job_row["evidence_watermark"]) != payload["evidence_id"]
                    ):
                        raise MemoryCorruptionError("analysis job payload hash differs")
                    evidence_id = str(payload["evidence_id"])
                    async with self._db.execute(
                        "SELECT run_id,subject,sanitized_hash,disclosure_json,source_ref,"
                        "envelope_hash,source_hash "
                        "FROM evidence_envelopes WHERE evidence_id=?",
                        (evidence_id,),
                    ) as cursor:
                        evidence_row = await cursor.fetchone()
                    if evidence_row is None or str(evidence_row["subject"]) != subject:
                        raise MemoryCorruptionError("analysis job evidence is unavailable")
                    expected_payload: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "evidence_id": evidence_id,
                        "envelope_hash": str(evidence_row["envelope_hash"]),
                        "source_hash": str(evidence_row["source_hash"]),
                    }
                    if payload != expected_payload:
                        raise MemoryCorruptionError("analysis job evidence lineage differs")
                    current_run = str(evidence_row["run_id"])
                    current_disclosure_json = json.loads(str(evidence_row["disclosure_json"]))
                    if not isinstance(current_disclosure_json, dict):
                        raise MemoryCorruptionError("analysis disclosure is malformed")
                    current_disclosure = DisclosureContext.from_json(current_disclosure_json)
                    if run_id is None:
                        run_id = current_run
                        disclosure = current_disclosure
                    elif current_run != run_id or current_disclosure != disclosure:
                        raise MemoryCorruptionError("analysis batch authority differs")
                    evidence_refs.append(
                        EvidenceRef(
                            evidence_id,
                            str(evidence_row["sanitized_hash"]),
                            ordinal,
                        )
                    )
                    member_attempts.append(int(job_row["attempt_count"]) + 1)
                assert run_id is not None and disclosure is not None
                batch_attempt = max(member_attempts)
                member_identity = canonical_json(
                    [
                        {"job_id": str(row["job_id"]), "attempt": attempt}
                        for row, attempt in zip(job_rows, member_attempts, strict=True)
                    ]
                )
                batch_id = _stable_id("analysis-batch", subject, batch_key, member_identity)
                request = MemoryAnalysisRequest(
                    batch_id,
                    run_id,
                    subject,
                    tuple(evidence_refs),
                    config.prompt_version,
                    config.result_schema_version,
                    config.policy_version,
                    config.provider_id,
                    config.model_id,
                    config.model_config_hash,
                    batch_attempt,
                    config.analysis_budget,
                    disclosure,
                    batch_id,
                )
                await self._db.execute(
                    "INSERT INTO analysis_batches(batch_id,principal_id,batch_key,"
                    "evidence_watermark,attempt,"
                    "request_json,request_hash,state,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,'handed_off',?,?)",
                    (
                        batch_id,
                        subject,
                        batch_key,
                        evidence_refs[-1].evidence_id,
                        batch_attempt,
                        canonical_json(request.to_json()),
                        request.request_hash,
                        now,
                        now,
                    ),
                )
                for ordinal, (job_row, evidence_ref, member_attempt) in enumerate(
                    zip(job_rows, evidence_refs, member_attempts, strict=True), start=1
                ):
                    job_id = str(job_row["job_id"])
                    await self._db.execute(
                        "UPDATE jobs SET state='claimed',lease_owner=?,lease_token=?,"
                        "lease_expires_at=?,attempt_count=?,updated_at=? WHERE job_id=? "
                        "AND state='pending'",
                        (
                            worker_id,
                            lease_token,
                            lease_expires_at,
                            member_attempt,
                            now,
                            job_id,
                        ),
                    )
                    await self._db.execute(
                        "INSERT INTO analysis_batch_members(batch_id,ordinal,job_id,job_attempt,"
                        "evidence_id,content_hash) VALUES(?,?,?,?,?,?)",
                        (
                            batch_id,
                            ordinal,
                            job_id,
                            member_attempt,
                            evidence_ref.evidence_id,
                            evidence_ref.content_hash,
                        ),
                    )
                    await self._db.execute(
                        "INSERT INTO job_attempts(job_id,attempt,batch_id,lease_token,request_hash,"
                        "state,started_at) VALUES(?,?,?,?,?,'handed_off',?)",
                        (
                            job_id,
                            member_attempt,
                            batch_id,
                            lease_token,
                            request.request_hash,
                            now,
                        ),
                    )
                await self._append_batch_events_unlocked(
                    batch_id, "provider_handoff", "analysis_provider_handoff", now
                )
                self._fault("job.claim.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.claim.after_commit")
                return await self._read_analysis_claim_unlocked(
                    batch_id, lease_token, lease_expires_at
                )
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _read_analysis_claim_unlocked(
        self,
        batch_id: str,
        lease_token: str,
        lease_expires_at: float,
    ) -> AnalysisBatchClaim:
        from simple_harness.runtime import (
            MemoryAnalysisDeliveryReceipt,
            MemoryAnalysisRequest,
            MemoryAnalysisResult,
            MemoryAnalysisResultEnvelope,
        )

        from simple_harness_memory.core.jobs import AnalysisBatchClaim

        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM analysis_batches WHERE batch_id=?", (batch_id,)
        ) as cursor:
            batch = await cursor.fetchone()
        if batch is None:
            raise MemoryCorruptionError("analysis batch disappeared")
        request_json = json.loads(str(batch["request_json"]))
        if not isinstance(request_json, dict):
            raise MemoryCorruptionError("stored analysis request is malformed")
        request = MemoryAnalysisRequest.from_json(request_json)
        if request.request_hash != str(batch["request_hash"]):
            raise MemoryCorruptionError("stored analysis request hash differs")
        result: MemoryAnalysisResult | None = None
        envelope: MemoryAnalysisResultEnvelope | None = None
        if batch["result_json"] is not None:
            result_json = json.loads(str(batch["result_json"]))
            if not isinstance(result_json, dict):
                raise MemoryCorruptionError("stored analysis result is malformed")
            result = MemoryAnalysisResult.from_json(result_json)
            if result.result_hash != str(batch["result_hash"]):
                raise MemoryCorruptionError("stored analysis result hash differs")
            delivery_json = json.loads(str(batch["delivery_receipt_json"]))
            if not isinstance(delivery_json, dict):
                raise MemoryCorruptionError("stored delivery receipt is malformed")
            delivery_receipt = MemoryAnalysisDeliveryReceipt.from_json(delivery_json)
            envelope = MemoryAnalysisResultEnvelope(result, delivery_receipt)
            if (
                delivery_receipt.receipt_hash != str(batch["delivery_receipt_hash"])
                or envelope.envelope_hash != str(batch["result_envelope_hash"])
            ):
                raise MemoryCorruptionError("stored analysis delivery authority differs")
        elif any(
            batch[name] is not None
            for name in (
                "delivery_receipt_json",
                "delivery_receipt_hash",
                "result_envelope_hash",
            )
        ):
            raise MemoryCorruptionError("stored analysis delivery is partial")
        async with self._db.execute(
            "SELECT * FROM analysis_batch_members WHERE batch_id=? ORDER BY ordinal",
            (batch_id,),
        ) as cursor:
            members = tuple(await cursor.fetchall())
        if (
            not members
            or str(batch["evidence_watermark"]) != str(members[-1]["evidence_id"])
        ):
            raise MemoryCorruptionError("analysis evidence watermark differs")
        application = None
        if batch["application_receipt_json"] is not None:
            application = await self._application_from_batch_unlocked(batch, request, result)
        return AnalysisBatchClaim(
            batch_id,
            str(batch["principal_id"]),
            str(batch["batch_key"]),
            str(batch["evidence_watermark"]),
            tuple(str(item["job_id"]) for item in members),
            lease_token,
            lease_expires_at,
            request,
            envelope,
            application,
        )

    async def _append_batch_events_unlocked(
        self,
        batch_id: str,
        event_kind: str,
        reason_code: str,
        occurred_at: float,
        result_hash: str | None = None,
    ) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT b.request_hash,m.job_id,m.job_attempt FROM analysis_batches b "
            "JOIN analysis_batch_members m ON m.batch_id=b.batch_id "
            "WHERE b.batch_id=? ORDER BY m.ordinal",
            (batch_id,),
        ) as cursor:
            members = await cursor.fetchall()
        if not members:
            raise MemoryCorruptionError("analysis batch has no members")
        for member in members:
            event_id = f"job-event-{uuid4().hex}"
            payload: dict[str, JsonValue] = {
                "schema_version": 1,
                "event_id": event_id,
                "batch_id": batch_id,
                "job_id": str(member["job_id"]),
                "attempt": int(member["job_attempt"]),
                "event_kind": event_kind,
                "reason_code": reason_code,
                "request_hash": str(member["request_hash"]),
                "result_hash": result_hash,
                "occurred_at": occurred_at,
            }
            await self._db.execute(
                "INSERT INTO job_attempt_events(event_id,batch_id,job_id,attempt,event_kind,"
                "reason_code,request_hash,result_hash,occurred_at,event_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    batch_id,
                    member["job_id"],
                    member["job_attempt"],
                    event_kind,
                    reason_code,
                    member["request_hash"],
                    result_hash,
                    occurred_at,
                    hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
                ),
            )

    async def _analysis_claim_is_current_unlocked(
        self, claim: AnalysisBatchClaim, now: float
    ) -> bool:
        assert self._db is not None
        placeholders = ",".join("?" for _ in claim.job_ids)
        async with self._db.execute(
            "SELECT COUNT(*) AS member_count,"
            f"SUM(CASE WHEN j.job_id IN ({placeholders}) "
            "AND j.state='claimed' AND j.lease_token=? AND j.lease_expires_at>? "
            "AND a.lease_token=? AND a.state IN "
            "('handed_off','result_committed','audit_pending') THEN 1 ELSE 0 END) "
            "AS current_count FROM analysis_batch_members m "
            "JOIN jobs j ON j.job_id=m.job_id "
            "JOIN job_attempts a ON a.job_id=m.job_id AND a.attempt=m.job_attempt "
            "AND a.batch_id=m.batch_id "
            "JOIN analysis_batches b ON b.batch_id=m.batch_id "
            "WHERE m.batch_id=? AND b.principal_id=? AND b.request_hash=? "
            "AND b.evidence_watermark=? AND b.state IN "
            "('handed_off','result_committed','audit_pending')",
            (
                *claim.job_ids,
                claim.lease_token,
                now,
                claim.lease_token,
                claim.batch_id,
                claim.subject,
                claim.request.request_hash,
                claim.evidence_watermark,
            ),
        ) as cursor:
            row = await cursor.fetchone()
        return (
            row is not None
            and int(row["member_count"]) == len(claim.job_ids)
            and int(row["current_count"] or 0) == len(claim.job_ids)
        )

    async def commit_analysis_result(
        self, claim: AnalysisBatchClaim, envelope: MemoryAnalysisResultEnvelope
    ) -> AnalysisResultCommit:
        from simple_harness.runtime import (
            MemoryAnalysisDeliveryReceipt,
            MemoryAnalysisResult,
            MemoryAnalysisResultEnvelope,
        )

        from simple_harness_memory.core.audit import freeze_public_audit_object
        from simple_harness_memory.core.jobs import (
            AnalysisBatchClaim,
            AnalysisResultCommit,
            AnalysisResultCommitOutcome,
        )

        if (
            type(claim) is not AnalysisBatchClaim
            or type(envelope) is not MemoryAnalysisResultEnvelope
        ):
            raise TypeError("claim and envelope must use analysis protocol types")
        decoded_envelope = MemoryAnalysisResultEnvelope.from_json(envelope.to_json())
        if decoded_envelope.envelope_hash != envelope.envelope_hash:
            raise MemoryValidationError("analysis_envelope_hash_differs")
        envelope.verify_request(claim.request)
        freeze_public_audit_object(
            {"delivery_receipt": envelope.delivery_receipt.to_json()}
        )
        result = envelope.result
        decoded = MemoryAnalysisResult.from_json(result.to_json())
        if decoded.result_hash != result.result_hash:
            raise MemoryValidationError("analysis_result_hash_differs")
        if (
            result.job_id != claim.request.job_id
            or result.run_id != claim.request.run_id
            or result.request_hash != claim.request.request_hash
        ):
            raise MemoryValidationError("analysis_result_lineage_differs")
        freeze_public_audit_object(result.structured_result)
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                now = _timestamp(self._now())
                if not await self._analysis_claim_is_current_unlocked(claim, now):
                    await self._append_batch_events_unlocked(
                        claim.batch_id,
                        "result_out_of_order",
                        "analysis_stale_lease_result_ignored",
                        now,
                        result.result_hash,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return AnalysisResultCommit(
                        AnalysisResultCommitOutcome.STALE_LEASE, None
                    )
                async with self._db.execute(
                    "SELECT result_json,result_hash,delivery_receipt_json,"
                    "delivery_receipt_hash,result_envelope_hash FROM analysis_batches "
                    "WHERE batch_id=?",
                    (claim.batch_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise MemoryCorruptionError("analysis batch disappeared")
                if row["result_json"] is not None:
                    stored_value = json.loads(str(row["result_json"]))
                    if not isinstance(stored_value, dict):
                        raise MemoryCorruptionError("stored analysis result malformed")
                    canonical = MemoryAnalysisResult.from_json(stored_value)
                    if canonical.result_hash != str(row["result_hash"]):
                        raise MemoryCorruptionError("stored analysis result hash differs")
                    delivery_value = json.loads(str(row["delivery_receipt_json"]))
                    if not isinstance(delivery_value, dict):
                        raise MemoryCorruptionError("stored delivery receipt malformed")
                    canonical_delivery = MemoryAnalysisDeliveryReceipt.from_json(delivery_value)
                    canonical_envelope = MemoryAnalysisResultEnvelope(
                        canonical, canonical_delivery
                    )
                    if (
                        canonical_delivery.receipt_hash
                        != str(row["delivery_receipt_hash"])
                        or canonical_envelope.envelope_hash
                        != str(row["result_envelope_hash"])
                    ):
                        raise MemoryCorruptionError("stored analysis envelope hash differs")
                    if canonical_envelope.envelope_hash == envelope.envelope_hash:
                        outcome = AnalysisResultCommitOutcome.REPLAYED
                        event_kind = "result_replayed"
                        reason = "analysis_result_replayed"
                    else:
                        outcome = AnalysisResultCommitOutcome.DIVERGENT
                        event_kind = "result_divergent"
                        reason = "analysis_divergent_result_ignored"
                    await self._append_batch_events_unlocked(
                        claim.batch_id, event_kind, reason, now, result.result_hash
                    )
                    self._fault("job.result.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("job.result.after_commit")
                    return AnalysisResultCommit(outcome, canonical_envelope)
                await self._db.execute(
                    "UPDATE analysis_batches SET result_json=?,result_hash=?,"
                    "delivery_receipt_json=?,delivery_receipt_hash=?,result_envelope_hash=?,"
                    "state='result_committed',updated_at=? WHERE batch_id=?",
                    (
                        canonical_json(result.to_json()),
                        result.result_hash,
                        canonical_json(envelope.delivery_receipt.to_json()),
                        envelope.delivery_receipt.receipt_hash,
                        envelope.envelope_hash,
                        now,
                        claim.batch_id,
                    ),
                )
                await self._db.execute(
                    "UPDATE job_attempts SET result_hash=?,state='result_committed' "
                    "WHERE batch_id=?",
                    (result.result_hash, claim.batch_id),
                )
                await self._append_batch_events_unlocked(
                    claim.batch_id,
                    "result_committed",
                    "analysis_result_committed",
                    now,
                    result.result_hash,
                )
                self._fault("job.result.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.result.after_commit")
                return AnalysisResultCommit(AnalysisResultCommitOutcome.COMMITTED, envelope)
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def reject_analysis_result(
        self,
        claim: AnalysisBatchClaim,
        audit: RejectedAnalysisAudit,
        reason_code: str,
        validator_version: str,
    ) -> WorkerRunOutcome:
        from simple_harness.runtime import (
            AnalysisValidationStatus,
            EvidenceReasonCode,
            MemoryAnalysisReceipt,
        )

        from simple_harness_memory.core.audit import (
            DecisionLedgerEntry,
            DecisionOutcome,
            LLMInvocationAuditRecord,
            OutputStorageStatus,
        )
        from simple_harness_memory.core.jobs import (
            AnalysisBatchClaim,
            RejectedAnalysisAudit,
            WorkerRunOutcome,
        )
        from simple_harness_memory.core.suppression import SuppressionScopeKind

        if type(claim) is not AnalysisBatchClaim or type(audit) is not RejectedAnalysisAudit:
            raise TypeError("claim and audit must use analysis job protocol types")
        _audit_identifier(reason_code, "reason_code")
        _audit_identifier(validator_version, "validator_version")
        if audit.delivery_receipt is not None:
            delivery = audit.delivery_receipt
            if (
                delivery.job_id != claim.request.job_id
                or delivery.run_id != claim.request.run_id
                or delivery.request_hash != claim.request.request_hash
                or delivery.attempt != claim.request.attempt
            ):
                raise MemoryValidationError("rejected_analysis_delivery_lineage_differs")
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                now = _timestamp(self._now())
                if not await self._analysis_claim_is_current_unlocked(claim, now):
                    await self._append_batch_events_unlocked(
                        claim.batch_id,
                        "result_out_of_order",
                        "analysis_stale_lease_result_ignored",
                        now,
                        audit.result_hash,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return WorkerRunOutcome.STALE_LEASE
                receipt = MemoryAnalysisReceipt(
                    _stable_id(
                        "analysis-rejected-receipt",
                        claim.batch_id,
                        claim.request.request_hash,
                        audit.result_hash,
                        reason_code,
                    ),
                    claim.request.job_id,
                    claim.request.run_id,
                    claim.request.request_hash,
                    audit.result_hash,
                    validator_version,
                    AnalysisValidationStatus.REJECTED,
                    (EvidenceReasonCode.VALIDATOR_REJECTED,),
                    None,
                    now,
                )
                invocation_id = _stable_id(
                    "analysis-rejected-invocation",
                    claim.batch_id,
                    claim.request.request_hash,
                )
                decision = DecisionLedgerEntry(
                    _stable_id("analysis-rejected-decision", claim.batch_id),
                    _stable_id("analysis-rejected-operation", claim.batch_id),
                    "analysis_result",
                    DecisionOutcome.REJECTED,
                    SuppressionScopeKind.SUBJECT,
                    claim.subject,
                    {},
                    (),
                    (),
                    claim.request.ordered_evidence_refs,
                    reason_code,
                    now,
                )
                record = LLMInvocationAuditRecord(
                    1,
                    invocation_id,
                    claim.subject,
                    claim.request.run_id,
                    _stable_id("analysis-batch-turn", claim.batch_id),
                    claim.request.job_id,
                    claim.request.request_hash,
                    claim.request.ordered_evidence_refs,
                    None,
                    None,
                    OutputStorageStatus.REJECTED_UNSAFE,
                    reason_code,
                    claim.request.provider_id,
                    claim.request.model_id,
                    claim.request.model_config_hash,
                    claim.request.prompt_version,
                    claim.request.result_schema_version,
                    claim.request.policy_version,
                    validator_version,
                    audit.provider_response_id,
                    audit.delivery_receipt,
                    receipt,
                    audit.result_hash,
                    audit.input_tokens,
                    audit.output_tokens,
                    audit.cost_microunits,
                    audit.latency_ms,
                    max(0.0, now - (audit.latency_ms / 1000.0)),
                    now,
                    (),
                )
                existing = await self._read_invocation(invocation_id)
                if existing is None:
                    await self._append_invocation_unlocked(
                        record, (decision,), manage_transaction=False
                    )
                else:
                    stored_decisions = await self._read_decisions(invocation_id)
                    if (
                        existing.invocation_hash != record.invocation_hash
                        or stored_decisions != (decision,)
                    ):
                        raise MemoryIdempotencyConflict(
                            "rejected_analysis_invocation_replay_conflict"
                        )
                await self._db.execute(
                    "UPDATE jobs SET state='dead_letter',lease_owner=NULL,lease_token=NULL,"
                    "lease_expires_at=NULL,last_error_code=?,updated_at=? WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?)",
                    (reason_code, now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE job_attempts SET state='failed',reason_code=?,completed_at=? "
                    "WHERE batch_id=?",
                    (reason_code, now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE analysis_batches SET state='failed',updated_at=? WHERE batch_id=?",
                    (now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE outbox SET state='dead_letter',updated_at=? WHERE "
                    "idempotency_key IN (SELECT idempotency_key FROM jobs WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?))",
                    (now, claim.batch_id),
                )
                await self._append_batch_events_unlocked(
                    claim.batch_id, "dead_letter", reason_code, now, audit.result_hash
                )
                self._fault("job.fail.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.fail.after_commit")
                return WorkerRunOutcome.DEAD_LETTER
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def fail_analysis_batch(
        self,
        claim: AnalysisBatchClaim,
        reason_code: str,
        config: MemoryJobWorkerConfig,
    ) -> WorkerRunOutcome:
        from simple_harness_memory.core.jobs import (
            AnalysisBatchClaim,
            MemoryJobWorkerConfig,
            WorkerRunOutcome,
        )

        if type(claim) is not AnalysisBatchClaim or type(config) is not MemoryJobWorkerConfig:
            raise TypeError("claim and config must use analysis job protocol types")
        _audit_identifier(reason_code, "reason_code")
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                now = _timestamp(self._now())
                if not await self._analysis_claim_is_current_unlocked(claim, now):
                    await self._append_batch_events_unlocked(
                        claim.batch_id,
                        "result_out_of_order",
                        "analysis_stale_lease_failure_ignored",
                        now,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return WorkerRunOutcome.STALE_LEASE
                async with self._db.execute(
                    "SELECT job_id,attempt_count FROM jobs WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?)",
                    (claim.batch_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                all_dead = True
                for row in rows:
                    attempt = int(row["attempt_count"])
                    dead = attempt >= config.max_attempts
                    all_dead = all_dead and dead
                    retry_at = now if dead else now + config.retry_delays_seconds[attempt - 1]
                    await self._db.execute(
                        "UPDATE jobs SET state=?,lease_owner=NULL,lease_token=NULL,"
                        "lease_expires_at=NULL,last_error_code=?,next_attempt_at=?,updated_at=? "
                        "WHERE job_id=?",
                        (
                            "dead_letter" if dead else "pending",
                            reason_code,
                            retry_at,
                            now,
                            row["job_id"],
                        ),
                    )
                    if dead:
                        await self._db.execute(
                            "UPDATE outbox SET state='dead_letter',updated_at=? WHERE "
                            "idempotency_key=(SELECT idempotency_key FROM jobs WHERE job_id=?)",
                            (now, row["job_id"]),
                        )
                await self._db.execute(
                    "UPDATE job_attempts SET state='failed',reason_code=?,completed_at=? "
                    "WHERE batch_id=?",
                    (reason_code, now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE analysis_batches SET state='failed',updated_at=? WHERE batch_id=?",
                    (now, claim.batch_id),
                )
                await self._append_batch_events_unlocked(
                    claim.batch_id,
                    "dead_letter" if all_dead else "retry_scheduled",
                    reason_code,
                    now,
                )
                self._fault("job.fail.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.fail.after_commit")
                return (
                    WorkerRunOutcome.DEAD_LETTER
                    if all_dead
                    else WorkerRunOutcome.RETRY_SCHEDULED
                )
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def prepare_analysis_application(
        self,
        claim: AnalysisBatchClaim,
        result: MemoryAnalysisResult,
        validator_version: str,
    ) -> AnalysisApplication | None:
        from simple_harness.runtime import (
            AnalysisValidationStatus,
            EvidenceReasonCode,
            MemoryAnalysisReceipt,
            MemoryMutationPlan,
        )

        from simple_harness_memory.core.jobs import AnalysisBatchClaim

        if type(claim) is not AnalysisBatchClaim:
            raise TypeError("claim must use AnalysisBatchClaim")
        _audit_identifier(validator_version, "validator_version")
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                now = _timestamp(self._now())
                if not await self._analysis_claim_is_current_unlocked(claim, now):
                    await self._append_batch_events_unlocked(
                        claim.batch_id,
                        "result_out_of_order",
                        "analysis_stale_lease_application_ignored",
                        now,
                        result.result_hash,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return None
                async with self._db.execute(
                    "SELECT * FROM analysis_batches WHERE batch_id=?", (claim.batch_id,)
                ) as cursor:
                    batch = await cursor.fetchone()
                if batch is None or str(batch["result_hash"]) != result.result_hash:
                    raise MemoryWriterConflict("analysis_result_not_canonical")
                if batch["application_receipt_json"] is not None:
                    application = await self._application_from_batch_unlocked(
                        batch, claim.request, result
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return application

                plan: MemoryMutationPlan | None = None
                no_mutation = False
                try:
                    structured = thaw_json(cast(FrozenJsonValue, result.structured_result))
                    if not isinstance(structured, dict):
                        raise ValueError("structured result is not an object")
                    no_mutation = (
                        set(structured) == {"outcome", "operations"}
                        and structured.get("outcome") == "no_mutation"
                        and structured.get("operations") == []
                    )
                    if not no_mutation:
                        plan = MemoryMutationPlan.from_json(structured)
                except (KeyError, TypeError, ValueError):
                    plan = None
                    no_mutation = False
                valid = no_mutation or plan is not None
                if plan is not None:
                    valid = (
                        plan.run_id == claim.request.run_id
                        and plan.subject == claim.request.subject
                        and plan.idempotency_key == claim.request.idempotency_key
                        and plan.disclosure_context == claim.request.disclosure_context
                        and plan.evidence_refs == claim.request.ordered_evidence_refs
                        and all(
                            all(
                                claim.request.ordered_evidence_refs[ref.ordinal - 1] == ref
                                for ref in operation.evidence_refs
                            )
                            for operation in plan.operations
                        )
                    )
                await self._db.execute(
                    "INSERT INTO analysis_apply_heads(principal_id,revision,updated_at) "
                    "VALUES(?,1,?) ON CONFLICT(principal_id) DO NOTHING",
                    (claim.subject, now),
                )
                async with self._db.execute(
                    "SELECT revision FROM analysis_apply_heads WHERE principal_id=?",
                    (claim.subject,),
                ) as cursor:
                    head_row = await cursor.fetchone()
                if head_row is None:
                    raise MemoryCorruptionError("analysis apply head missing")
                base_revision = int(head_row["revision"])
                valid = valid and (
                    no_mutation
                    or (plan is not None and plan.base_revision == base_revision)
                )
                committed_revision: int | None = None
                if valid:
                    if plan is not None:
                        committed_revision = base_revision + 1
                        update = await self._db.execute(
                            "UPDATE analysis_apply_heads SET revision=?,updated_at=? "
                            "WHERE principal_id=? AND revision=?",
                            (committed_revision, now, claim.subject, base_revision),
                        )
                        if update.rowcount != 1:
                            valid = False
                            committed_revision = None
                        else:
                            await self._db.execute(
                                "INSERT INTO accepted_analysis_plans(batch_id,principal_id,"
                                "base_revision,committed_revision,plan_json,plan_hash,created_at) "
                                "VALUES(?,?,?,?,?,?,?)",
                                (
                                    claim.batch_id,
                                    claim.subject,
                                    plan.base_revision,
                                    committed_revision,
                                    canonical_json(plan.to_json()),
                                    plan.plan_hash,
                                    now,
                                ),
                            )
                    else:
                        committed_revision = base_revision
                        no_mutation_value: dict[str, JsonValue] = {
                            "outcome": "no_mutation",
                            "operations": [],
                        }
                        no_mutation_json = canonical_json(no_mutation_value)
                        await self._db.execute(
                            "INSERT INTO accepted_analysis_plans(batch_id,principal_id,"
                            "base_revision,committed_revision,plan_json,plan_hash,created_at) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (
                                claim.batch_id,
                                claim.subject,
                                base_revision,
                                committed_revision,
                                no_mutation_json,
                                hashlib.sha256(no_mutation_json.encode()).hexdigest(),
                                now,
                            ),
                        )
                receipt = MemoryAnalysisReceipt(
                    _stable_id(
                        "analysis-application-receipt",
                        claim.batch_id,
                        claim.request.request_hash,
                        result.result_hash,
                    ),
                    claim.request.job_id,
                    claim.request.run_id,
                    claim.request.request_hash,
                    result.result_hash,
                    validator_version,
                    (
                        AnalysisValidationStatus.ACCEPTED
                        if valid
                        else AnalysisValidationStatus.REJECTED
                    ),
                    (
                        EvidenceReasonCode.VALIDATOR_ACCEPTED,
                    )
                    if valid
                    else (EvidenceReasonCode.VALIDATOR_REJECTED,),
                    committed_revision,
                    now,
                )
                await self._db.execute(
                    "UPDATE analysis_batches SET state='audit_pending',"
                    "application_receipt_json=?,application_receipt_hash=?,updated_at=? "
                    "WHERE batch_id=?",
                    (
                        canonical_json(receipt.to_json()),
                        receipt.receipt_hash,
                        now,
                        claim.batch_id,
                    ),
                )
                await self._db.execute(
                    "UPDATE job_attempts SET state='audit_pending' WHERE batch_id=?",
                    (claim.batch_id,),
                )
                await self._append_batch_events_unlocked(
                    claim.batch_id,
                    "application_staged" if valid else "application_rejected",
                    "analysis_validator_accepted" if valid else "analysis_validator_rejected",
                    now,
                    result.result_hash,
                )
                self._fault("job.apply.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.apply.after_commit")
                async with self._db.execute(
                    "SELECT * FROM analysis_batches WHERE batch_id=?", (claim.batch_id,)
                ) as cursor:
                    stored_batch = await cursor.fetchone()
                if stored_batch is None:
                    raise MemoryCorruptionError("analysis batch disappeared after application")
                return await self._application_from_batch_unlocked(
                    stored_batch, claim.request, result
                )
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _application_from_batch_unlocked(
        self,
        batch: aiosqlite.Row,
        request: MemoryAnalysisRequest,
        result: MemoryAnalysisResult | None,
    ) -> AnalysisApplication:
        from simple_harness.runtime import (
            AnalysisValidationStatus,
            MemoryAnalysisReceipt,
            MemoryMutationPlan,
        )

        from simple_harness_memory.core.audit import DecisionLedgerEntry, DecisionOutcome
        from simple_harness_memory.core.jobs import AnalysisApplication
        from simple_harness_memory.core.suppression import SuppressionScopeKind

        if result is None or batch["application_receipt_json"] is None:
            raise MemoryCorruptionError("analysis application is incomplete")
        receipt_value = json.loads(str(batch["application_receipt_json"]))
        if not isinstance(receipt_value, dict):
            raise MemoryCorruptionError("stored analysis receipt is malformed")
        receipt = MemoryAnalysisReceipt.from_json(receipt_value)
        if receipt.receipt_hash != str(batch["application_receipt_hash"]):
            raise MemoryCorruptionError("stored analysis receipt hash differs")
        now = receipt.committed_at
        decisions: list[DecisionLedgerEntry] = []
        if receipt.validation_status is AnalysisValidationStatus.ACCEPTED:
            assert self._db is not None
            async with self._db.execute(
                "SELECT * FROM accepted_analysis_plans WHERE batch_id=?",
                (str(batch["batch_id"]),),
            ) as cursor:
                plan_row = await cursor.fetchone()
            if plan_row is None:
                raise MemoryCorruptionError("accepted analysis plan is missing")
            plan_value = json.loads(str(plan_row["plan_json"]))
            if not isinstance(plan_value, dict):
                raise MemoryCorruptionError("accepted analysis plan is malformed")
            if (
                set(plan_value) == {"outcome", "operations"}
                and plan_value.get("outcome") == "no_mutation"
                and plan_value.get("operations") == []
            ):
                expected_hash = hashlib.sha256(canonical_json(plan_value).encode()).hexdigest()
                if expected_hash != str(plan_row["plan_hash"]):
                    raise MemoryCorruptionError("accepted no-mutation hash differs")
                plan = None
            else:
                plan = MemoryMutationPlan.from_json(plan_value)
                if plan.plan_hash != str(plan_row["plan_hash"]):
                    raise MemoryCorruptionError("accepted analysis plan hash differs")
            if plan is not None:
                operations = plan.operations
            else:
                operations = ()
            for operation in operations:
                assert plan is not None
                target_ref = operation.target_memory_id or _stable_id(
                    "proposed-memory", plan.plan_id, operation.operation_id
                )
                decisions.append(
                    DecisionLedgerEntry(
                        _stable_id(
                            "analysis-decision",
                            str(batch["batch_id"]),
                            operation.operation_id,
                        ),
                        operation.operation_id,
                        operation.kind.value,
                        DecisionOutcome.ACCEPTED,
                        SuppressionScopeKind.MEMORY,
                        target_ref,
                        operation.to_json(),
                        () if operation.target_memory_id is None else (operation.target_memory_id,),
                        (
                            f"analysis-plan:{plan.plan_hash}:revision:"
                            f"{receipt.committed_revision}",
                        ),
                        operation.evidence_refs or plan.evidence_refs,
                        "analysis_operation_staged",
                        now,
                    )
                )
        else:
            decisions.append(
                DecisionLedgerEntry(
                    _stable_id("analysis-decision-rejected", str(batch["batch_id"])),
                    _stable_id("analysis-operation-rejected", str(batch["batch_id"])),
                    "analysis_plan",
                    DecisionOutcome.REJECTED,
                    SuppressionScopeKind.SUBJECT,
                    request.subject,
                    {},
                    (),
                    (),
                    request.ordered_evidence_refs,
                    "analysis_validator_rejected",
                    now,
                )
            )
        batch_id = str(batch["batch_id"])
        return AnalysisApplication(
            _stable_id("analysis-invocation", batch_id, request.request_hash),
            _stable_id("analysis-batch-turn", batch_id),
            receipt,
            tuple(decisions),
        )

    async def finalize_analysis_application(
        self, claim: AnalysisBatchClaim, application: AnalysisApplication
    ) -> bool:
        from simple_harness_memory.core.jobs import AnalysisApplication, AnalysisBatchClaim

        if type(claim) is not AnalysisBatchClaim or type(application) is not AnalysisApplication:
            raise TypeError("claim and application must use analysis protocol types")
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                now = _timestamp(self._now())
                async with self._db.execute(
                    "SELECT state,application_receipt_hash FROM analysis_batches "
                    "WHERE batch_id=?",
                    (claim.batch_id,),
                ) as cursor:
                    batch = await cursor.fetchone()
                if batch is None:
                    raise MemoryCorruptionError("analysis batch disappeared")
                if str(batch["application_receipt_hash"]) != application.receipt.receipt_hash:
                    raise MemoryIdempotencyConflict("analysis_application_receipt_differs")
                if str(batch["state"]) == "applied":
                    await self._db.execute("COMMIT")
                    committed = True
                    return True
                if not await self._analysis_claim_is_current_unlocked(claim, now):
                    await self._append_batch_events_unlocked(
                        claim.batch_id,
                        "result_out_of_order",
                        "analysis_stale_lease_finalize_ignored",
                        now,
                        claim.result.result_hash if claim.result is not None else None,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return False
                async with self._db.execute(
                    "SELECT validation_receipt_hash FROM llm_invocations "
                    "WHERE invocation_id=?",
                    (application.invocation_id,),
                ) as cursor:
                    invocation = await cursor.fetchone()
                if (
                    invocation is None
                    or str(invocation["validation_receipt_hash"])
                    != application.receipt.receipt_hash
                ):
                    raise MemoryWriterConflict("analysis_audit_not_durable")
                await self._db.execute(
                    "UPDATE jobs SET state='applied',lease_owner=NULL,lease_token=NULL,"
                    "lease_expires_at=NULL,last_error_code=NULL,updated_at=? WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?)",
                    (now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE job_attempts SET state='applied',completed_at=? WHERE batch_id=?",
                    (now, claim.batch_id),
                )
                async with self._db.execute(
                    "SELECT o.*,j.job_id,j.payload AS job_payload FROM outbox o JOIN jobs j "
                    "ON j.principal_id=o.principal_id AND j.idempotency_key=o.idempotency_key "
                    "WHERE j.job_id IN (SELECT job_id FROM analysis_batch_members "
                    "WHERE batch_id=?)",
                    (claim.batch_id,),
                ) as cursor:
                    outbox_rows = tuple(await cursor.fetchall())
                if len(outbox_rows) != len(claim.job_ids):
                    raise MemoryCorruptionError("analysis outbox membership differs")
                for outbox_row in outbox_rows:
                    outbox_value = json.loads(str(outbox_row["payload"]))
                    job_value = json.loads(str(outbox_row["job_payload"]))
                    if (
                        not isinstance(outbox_value, dict)
                        or not isinstance(job_value, dict)
                        or str(outbox_row["topic"]) != "memory.mutation.requested"
                        or str(outbox_row["principal_id"]) != claim.subject
                        or outbox_value != {**job_value, "job_id": str(outbox_row["job_id"])}
                        or hashlib.sha256(canonical_json(outbox_value).encode()).hexdigest()
                        != str(outbox_row["payload_hash"])
                    ):
                        raise MemoryCorruptionError("analysis outbox payload differs")
                await self._db.execute(
                    "UPDATE outbox SET state='applied',lease_owner=NULL,lease_token=NULL,"
                    "lease_expires_at=NULL,updated_at=? WHERE idempotency_key IN "
                    "(SELECT idempotency_key FROM jobs WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?))",
                    (now, claim.batch_id),
                )
                await self._db.execute(
                    "UPDATE analysis_batches SET state='applied',updated_at=? WHERE batch_id=?",
                    (now, claim.batch_id),
                )
                await self._append_batch_events_unlocked(
                    claim.batch_id,
                    "applied",
                    "analysis_application_applied",
                    now,
                    claim.result.result_hash if claim.result is not None else None,
                )
                self._fault("job.finalize.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.finalize.after_commit")
                return True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def record_memory_analysis(
        self,
        invocation_id: str,
        turn_id: str,
        request: MemoryAnalysisRequest,
        result: MemoryAnalysisResult,
        delivery_receipt: MemoryAnalysisDeliveryReceipt,
        validation_receipt: MemoryAnalysisReceipt,
        decisions: tuple[DecisionLedgerEntry, ...],
        *,
        reasoning_refs: tuple[PublicReasoningReference, ...] = (),
    ) -> LLMInvocationAuditRecord:
        """Append one public-only Host analysis invocation and its decisions atomically."""

        from simple_harness.runtime import (
            AnalysisValidationStatus,
            MemoryAnalysisDeliveryReceipt,
            MemoryAnalysisReceipt,
            MemoryAnalysisRequest,
            MemoryAnalysisResult,
        )

        from simple_harness_memory.core.audit import (
            DecisionLedgerEntry,
            DecisionOutcome,
            LLMInvocationAuditRecord,
            OutputStorageStatus,
            PublicReasoningReference,
            freeze_public_audit_object,
        )

        if type(request) is not MemoryAnalysisRequest:
            raise TypeError("request must use MemoryAnalysisRequest")
        if type(result) is not MemoryAnalysisResult:
            raise TypeError("result must use MemoryAnalysisResult")
        if type(delivery_receipt) is not MemoryAnalysisDeliveryReceipt:
            raise TypeError("delivery_receipt must use MemoryAnalysisDeliveryReceipt")
        if type(validation_receipt) is not MemoryAnalysisReceipt:
            raise TypeError("validation_receipt must use MemoryAnalysisReceipt")
        decoded_request = MemoryAnalysisRequest.from_json(request.to_json())
        decoded_result = MemoryAnalysisResult.from_json(result.to_json())
        decoded_delivery = MemoryAnalysisDeliveryReceipt.from_json(delivery_receipt.to_json())
        decoded_receipt = MemoryAnalysisReceipt.from_json(validation_receipt.to_json())
        if (
            decoded_request.request_hash != request.request_hash
            or decoded_result.result_hash != result.result_hash
            or decoded_delivery.receipt_hash != delivery_receipt.receipt_hash
            or decoded_receipt.receipt_hash != validation_receipt.receipt_hash
        ):
            raise MemoryValidationError("analysis_authority_hash_differs")
        delivery_receipt.verify_result(request, result)
        _audit_identifier(invocation_id, "invocation_id")
        _audit_identifier(turn_id, "turn_id")
        decisions = tuple(decisions)
        reasoning_refs = tuple(reasoning_refs)
        if not all(type(item) is DecisionLedgerEntry for item in decisions):
            raise TypeError("decisions must use DecisionLedgerEntry")
        if not all(type(item) is PublicReasoningReference for item in reasoning_refs):
            raise TypeError("reasoning_refs must use PublicReasoningReference")
        if (
            result.job_id != request.job_id
            or result.run_id != request.run_id
            or result.request_hash != request.request_hash
            or delivery_receipt.job_id != request.job_id
            or delivery_receipt.run_id != request.run_id
            or delivery_receipt.request_hash != request.request_hash
            or delivery_receipt.result_hash != result.result_hash
            or delivery_receipt.provider_response_id != result.provider_response_id
            or validation_receipt.job_id != request.job_id
            or validation_receipt.run_id != request.run_id
            or validation_receipt.request_hash != request.request_hash
            or validation_receipt.result_hash != result.result_hash
        ):
            raise MemoryValidationError("analysis_authority_lineage_differs")
        request_evidence = {
            item.evidence_id: item.content_hash for item in request.ordered_evidence_refs
        }
        for decision in decisions:
            if any(
                request_evidence.get(item.evidence_id) != item.content_hash
                for item in decision.evidence_refs
            ):
                raise MemoryValidationError("decision_evidence_lineage_differs")
            if (
                decision.target_kind.value == "subject"
                and decision.target_ref != request.subject
            ):
                raise MemoryValidationError("decision_subject_target_differs")
        if validation_receipt.validation_status is not AnalysisValidationStatus.ACCEPTED and any(
            item.outcome is DecisionOutcome.ACCEPTED for item in decisions
        ):
            raise MemoryValidationError("rejected_analysis_cannot_accept_operation")
        public_output: Mapping[str, FrozenJsonValue] | None
        public_output_hash: str | None
        output_status = OutputStorageStatus.PUBLIC
        try:
            public_output = freeze_public_audit_object(result.structured_result)
            public_output_json = thaw_json(cast(FrozenJsonValue, public_output))
            assert isinstance(public_output_json, dict)
            public_output_hash = hashlib.sha256(
                canonical_json(public_output_json).encode()
            ).hexdigest()
            output_reason = validation_receipt.reason_codes[0].value
        except (MemoryLimitError, MemoryValidationError):
            if validation_receipt.validation_status is AnalysisValidationStatus.ACCEPTED or not any(
                item.outcome is DecisionOutcome.REJECTED for item in decisions
            ):
                raise MemoryValidationError("unsafe_output_requires_rejected_decision") from None
            public_output = None
            public_output_hash = None
            output_status = OutputStorageStatus.REJECTED_UNSAFE
            output_reason = "audit_private_material_rejected"
        if validation_receipt.validation_status is AnalysisValidationStatus.ACCEPTED:
            assert public_output is not None
            _validate_accepted_operation_decisions(public_output, decisions)

        completed_at = float(validation_receipt.committed_at)
        started_at = max(0.0, completed_at - (result.latency_ms / 1000.0))
        expected = LLMInvocationAuditRecord(
            1,
            invocation_id,
            request.subject,
            request.run_id,
            turn_id,
            request.job_id,
            request.request_hash,
            request.ordered_evidence_refs,
            public_output,
            public_output_hash,
            output_status,
            output_reason,
            request.provider_id,
            request.model_id,
            request.model_config_hash,
            request.prompt_version,
            request.result_schema_version,
            request.policy_version,
            validation_receipt.validator_version,
            result.provider_response_id,
            delivery_receipt,
            validation_receipt,
            result.result_hash,
            result.input_tokens,
            result.output_tokens,
            result.cost_microunits,
            result.latency_ms,
            started_at,
            completed_at,
            reasoning_refs,
        )
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            for evidence_ref in request.ordered_evidence_refs:
                async with self._db.execute(
                    "SELECT subject,sanitized_hash FROM evidence_envelopes WHERE evidence_id=?",
                    (evidence_ref.evidence_id,),
                ) as cursor:
                    evidence_row = await cursor.fetchone()
                if (
                    evidence_row is None
                    or str(evidence_row["subject"]) != request.subject
                    or str(evidence_row["sanitized_hash"]) != evidence_ref.content_hash
                ):
                    raise MemoryValidationError("analysis_evidence_lineage_differs")
            existing = await self._read_invocation(invocation_id)
            if existing is not None:
                stored_decisions = await self._read_decisions(invocation_id)
                if (
                    existing.invocation_hash != expected.invocation_hash
                    or stored_decisions != decisions
                ):
                    raise MemoryIdempotencyConflict("analysis_invocation_replay_conflict")
                return existing
            async with self._db.execute(
                "SELECT invocation_id FROM llm_invocations WHERE principal_id=? "
                "AND request_hash=?",
                (request.subject, request.request_hash),
            ) as cursor:
                if await cursor.fetchone() is not None:
                    raise MemoryIdempotencyConflict("analysis_request_replay_conflict")
            await self._append_invocation_unlocked(expected, decisions)
            stored = await self._read_invocation(invocation_id)
            if stored is None or stored.invocation_hash != expected.invocation_hash:
                raise MemoryCorruptionError("stored analysis invocation differs")
        logger.info(
            "memory.analysis_invocation_recorded",
            invocation_id_hash=_opaque_hash(invocation_id),
            request_hash=request.request_hash,
            validation_status=validation_receipt.validation_status.value,
        )
        return stored

    async def _append_invocation_unlocked(
        self,
        record: LLMInvocationAuditRecord,
        decisions: tuple[DecisionLedgerEntry, ...],
        *,
        manage_transaction: bool = True,
    ) -> None:
        assert self._db is not None
        input_refs_json = canonical_json(
            [item.to_json() for item in record.public_input_refs]
        )
        input_hash = hashlib.sha256(input_refs_json.encode()).hexdigest()
        output_json = (
            None
            if record.public_output is None
            else canonical_json(thaw_json(cast(FrozenJsonValue, record.public_output)))
        )
        begun = False
        committed = False
        try:
            if manage_transaction:
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
            await self._db.execute(
                "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,"
                "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
                (
                    record.subject,
                    record.subject,
                    record.subject,
                    record.subject,
                    record.completed_at,
                ),
            )
            await self._db.execute(
                "INSERT INTO llm_invocations(invocation_id,principal_id,run_id,turn_id,job_id,"
                "request_hash,public_input_refs_json,public_input_hash,public_output_json,"
                "public_output_hash,output_storage_status,output_reason_code,provider_id,model_id,"
                "parameters_hash,prompt_version,schema_version,policy_version,validator_version,"
                "provider_request_id,delivery_receipt_id,delivery_receipt_json,"
                "delivery_receipt_hash,validation_receipt_id,validation_receipt_json,"
                "validation_receipt_hash,"
                "result_hash,input_tokens,output_tokens,cost_microunits,latency_ms,started_at,"
                "completed_at,invocation_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.invocation_id,
                    record.subject,
                    record.run_id,
                    record.turn_id,
                    record.job_id,
                    record.request_hash,
                    input_refs_json,
                    input_hash,
                    output_json,
                    record.public_output_hash,
                    record.output_storage_status.value,
                    record.output_reason_code,
                    record.provider_id,
                    record.model_id,
                    record.parameters_hash,
                    record.prompt_version,
                    record.result_schema_version,
                    record.policy_version,
                    record.validator_version,
                    record.provider_request_id,
                    (
                        None
                        if record.delivery_receipt is None
                        else record.delivery_receipt.receipt_id
                    ),
                    (
                        None
                        if record.delivery_receipt is None
                        else canonical_json(record.delivery_receipt.to_json())
                    ),
                    (
                        None
                        if record.delivery_receipt is None
                        else record.delivery_receipt.receipt_hash
                    ),
                    record.validation_receipt.receipt_id,
                    canonical_json(record.validation_receipt.to_json()),
                    record.validation_receipt.receipt_hash,
                    record.result_hash,
                    record.input_tokens,
                    record.output_tokens,
                    record.cost_microunits,
                    record.latency_ms,
                    record.started_at,
                    record.completed_at,
                    record.invocation_hash,
                ),
            )
            await self._db.executemany(
                "INSERT INTO llm_invocation_evidence_refs(invocation_id,ordinal,evidence_id,"
                "content_hash) VALUES(?,?,?,?)",
                (
                    (
                        record.invocation_id,
                        item.ordinal,
                        item.evidence_id,
                        item.content_hash,
                    )
                    for item in record.public_input_refs
                ),
            )
            await self._db.executemany(
                "INSERT INTO llm_reasoning_refs(invocation_id,ordinal,provider_item_id,item_type,"
                "item_hash,opaque_ref) VALUES(?,?,?,?,?,?)",
                (
                    (
                        record.invocation_id,
                        ordinal,
                        item.provider_item_id,
                        item.item_type.value,
                        item.item_hash,
                        item.opaque_ref,
                    )
                    for ordinal, item in enumerate(record.reasoning_refs, start=1)
                ),
            )
            for decision in decisions:
                payload_json = canonical_json(
                    thaw_json(cast(FrozenJsonValue, decision.public_payload))
                )
                await self._db.execute(
                    "INSERT INTO decision_records(decision_id,invocation_id,principal_id,"
                    "operation_id,operation_kind,outcome,target_kind,target_ref,canonical_payload,"
                    "payload_hash,before_refs_json,after_refs_json,reason_code,created_at,"
                    "decision_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        decision.decision_id,
                        record.invocation_id,
                        record.subject,
                        decision.operation_id,
                        decision.operation_kind,
                        decision.outcome.value,
                        decision.target_kind.value,
                        decision.target_ref,
                        payload_json,
                        hashlib.sha256(payload_json.encode()).hexdigest(),
                        canonical_json(list(decision.before_state_refs)),
                        canonical_json(list(decision.after_state_refs)),
                        decision.reason_code,
                        decision.created_at,
                        decision.decision_hash,
                    ),
                )
                await self._db.executemany(
                    "INSERT INTO decision_evidence_refs(decision_id,ordinal,evidence_id,"
                    "content_hash) VALUES(?,?,?,?)",
                    (
                        (
                            decision.decision_id,
                            item.ordinal,
                            item.evidence_id,
                            item.content_hash,
                        )
                        for item in decision.evidence_refs
                    ),
                )
            if manage_transaction:
                await self._db.execute("COMMIT")
                committed = True
        except BaseException:
            if begun and not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")
            raise

    async def export_audit_trace(
        self,
        query: AuditTraceQuery,
        *,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        """Ordinary trace export; active suppression removes the whole linked item."""

        return await self._export_audit_trace(query, limit=limit, cursor=cursor)

    async def export_sealed_audit_trace(
        self,
        query: AuditTraceQuery,
        access_receipt: SealedAuditAccessReceipt,
        *,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        """Purpose-bound sealed trace export with an append-only access event."""

        return await self._export_audit_trace(
            query,
            limit=limit,
            cursor=cursor,
            access_receipt=access_receipt,
        )

    async def _export_audit_trace(
        self,
        query: AuditTraceQuery,
        *,
        limit: int,
        cursor: AuditTraceCursor | None,
        access_receipt: SealedAuditAccessReceipt | None = None,
    ) -> AuditTracePage:
        from simple_harness_memory.core.audit import (
            AuditTraceCursor,
            AuditTraceItem,
            AuditTracePage,
            AuditTraceQuery,
            AuditTraceSelector,
        )

        if type(query) is not AuditTraceQuery:
            raise TypeError("query must use AuditTraceQuery")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise MemoryValidationError("audit_trace_limit_invalid")
        if cursor is not None and type(cursor) is not AuditTraceCursor:
            raise TypeError("cursor must use AuditTraceCursor")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        mode = "sealed" if access_receipt is not None else "ordinary"
        query_hash = hashlib.sha256(
            canonical_json({"schema_version": 1, "mode": mode, "query": query.to_json()}).encode()
        ).hexdigest()
        if cursor is not None and cursor.query_hash != query_hash:
            raise MemoryValidationError("audit_trace_cursor_query_differs")
        if cursor is not None and not self._verify_audit_cursor(cursor):
            raise MemoryValidationError("audit_trace_cursor_signature_invalid")
        predicate, parameters = _audit_trace_predicate(query)
        async with self._write_lock:
            if cursor is None:
                async with self._db.execute(
                    "SELECT COALESCE(MAX(i.invocation_sequence),0) FROM llm_invocations i "
                    "WHERE i.principal_id=? AND " + predicate,
                    (query.subject, *parameters),
                ) as db_cursor:
                    watermark_row = await db_cursor.fetchone()
                watermark = 0 if watermark_row is None else int(watermark_row[0])
                last_sequence = 0
            else:
                watermark = cursor.watermark_sequence
                last_sequence = cursor.last_sequence
            items: list[AuditTraceItem] = []
            while last_sequence < watermark and len(items) < limit:
                async with self._db.execute(
                    "SELECT i.invocation_id,i.invocation_sequence FROM llm_invocations i "
                    "WHERE i.principal_id=? AND i.invocation_sequence>? "
                    "AND i.invocation_sequence<=? AND "
                    + predicate
                    + " ORDER BY i.invocation_sequence LIMIT 100",
                    (query.subject, last_sequence, watermark, *parameters),
                ) as db_cursor:
                    rows = await db_cursor.fetchall()
                if not rows:
                    last_sequence = watermark
                    break
                for row in rows:
                    last_sequence = int(row["invocation_sequence"])
                    invocation = await self._read_invocation(str(row["invocation_id"]))
                    if invocation is None:
                        raise MemoryCorruptionError("audit trace invocation disappeared")
                    decisions = await self._read_decisions(invocation.invocation_id)
                    item = AuditTraceItem(invocation, decisions)
                    if access_receipt is None and await self._trace_item_denied_unlocked(item):
                        continue
                    items.append(item)
                    if len(items) == limit:
                        break
            next_cursor = (
                self._issue_audit_cursor(query_hash, watermark, last_sequence)
                if last_sequence < watermark
                else None
            )
            page = AuditTracePage(tuple(items), next_cursor)
            if access_receipt is not None:
                await self._authorize_sealed_trace_unlocked(
                    query,
                    query_hash,
                    page,
                    access_receipt,
                )
            elif query.selector is AuditTraceSelector.EVIDENCE:
                from simple_harness_memory.core.suppression import (
                    OrdinaryMemoryPurpose,
                    SuppressionCandidate,
                    SuppressionDenied,
                )

                resolution = await self._resolve_suppression_unlocked(
                    SuppressionCandidate(query.subject, evidence_id=query.selector_ref),
                    OrdinaryMemoryPurpose.EXPORT,
                )
                if resolution.denied:
                    raise SuppressionDenied()
        return page

    async def _trace_item_denied_unlocked(self, item: AuditTraceItem) -> bool:
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
            SuppressionScopeKind,
        )

        subject = item.invocation.subject
        for evidence in item.invocation.public_input_refs:
            if (
                await self._resolve_suppression_unlocked(
                    SuppressionCandidate(subject, evidence_id=evidence.evidence_id),
                    OrdinaryMemoryPurpose.EXPORT,
                )
            ).denied:
                return True
        for decision in item.decisions:
            candidate = SuppressionCandidate(
                subject,
                evidence_id=(
                    decision.target_ref
                    if decision.target_kind is SuppressionScopeKind.EVIDENCE
                    else None
                ),
                memory_id=(
                    decision.target_ref
                    if decision.target_kind is SuppressionScopeKind.MEMORY
                    else None
                ),
                entity_ids=(
                    (decision.target_ref,)
                    if decision.target_kind is SuppressionScopeKind.ENTITY
                    else ()
                ),
            )
            if (
                await self._resolve_suppression_unlocked(
                    candidate, OrdinaryMemoryPurpose.EXPORT
                )
            ).denied:
                return True
        return False

    async def _authorize_sealed_trace_unlocked(
        self,
        query: AuditTraceQuery,
        query_hash: str,
        page: AuditTracePage,
        access_receipt: SealedAuditAccessReceipt,
    ) -> None:
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDenied,
            SealedAuditAccessReceipt,
            SuppressionScopeKind,
        )

        if type(access_receipt) is not SealedAuditAccessReceipt:
            raise TypeError("access_receipt must use SealedAuditAccessReceipt")
        assert self._db is not None
        stored = await self._read_audit_access_by_decision(access_receipt.decision_id)
        denial: str | None = None
        if stored != access_receipt:
            denial = "sealed_audit_receipt_differs"
        now = _timestamp(self._now())
        evidence_ids = {
            ref.evidence_id
            for item in page.items
            for ref in item.invocation.public_input_refs
        }
        evidence_ids.update(
            ref.evidence_id
            for item in page.items
            for decision in item.decisions
            for ref in decision.evidence_refs
        )
        if query.selector.value == "evidence":
            evidence_ids.add(query.selector_ref)
        if denial is None and now >= access_receipt.expires_at:
            denial = "sealed_audit_access_expired"
        elif denial is None and now < access_receipt.issued_at:
            denial = "sealed_audit_access_not_yet_valid"
        elif denial is None and access_receipt.subject != query.subject:
            denial = "sealed_audit_subject_differs"
        elif denial is None and access_receipt.scope_kind is SuppressionScopeKind.SUBJECT:
            if access_receipt.scope_ref != query.subject:
                denial = "sealed_audit_scope_differs"
        elif denial is None and access_receipt.scope_kind is SuppressionScopeKind.EVIDENCE:
            if not evidence_ids or evidence_ids != {access_receipt.scope_ref}:
                denial = "sealed_audit_scope_differs"
        if denial is None:
            for evidence_id in evidence_ids:
                if await self._read_evidence_subject(evidence_id) != query.subject:
                    denial = "sealed_audit_evidence_scope_differs"
                    break
        async with self._db.execute(
            "SELECT (SELECT COUNT(*) FROM sealed_audit_access_events "
            "WHERE access_receipt_id=? AND outcome='granted') + "
            "(SELECT COUNT(*) FROM audit_trace_access_events "
            "WHERE access_receipt_id=? AND outcome='granted')",
            (access_receipt.access_receipt_id, access_receipt.access_receipt_id),
        ) as db_cursor:
            usage_row = await db_cursor.fetchone()
        usage = 0 if usage_row is None else int(usage_row[0])
        if denial is None and usage >= access_receipt.max_reads:
            denial = "sealed_audit_access_exhausted"
        event_id = f"audit-trace-event-{uuid4().hex}"
        event_payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "event_id": event_id,
            "access_receipt_id": access_receipt.access_receipt_id,
            "query_hash": query_hash,
            "outcome": "granted" if denial is None else "denied",
            "reason_code": "sealed_audit_trace_granted" if denial is None else denial,
            "occurred_at": now,
        }
        await self._db.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            await self._db.execute(
                "INSERT INTO audit_trace_access_events(event_id,access_receipt_id,query_hash,"
                "outcome,reason_code,occurred_at,event_hash) VALUES(?,?,?,?,?,?,?)",
                (
                    event_id,
                    access_receipt.access_receipt_id,
                    query_hash,
                    event_payload["outcome"],
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
        if denial is not None:
            raise SealedAuditAccessDenied(denial)

    async def _read_invocation(
        self, invocation_id: str
    ) -> LLMInvocationAuditRecord | None:
        from simple_harness.runtime import (
            EvidenceRef,
            MemoryAnalysisDeliveryReceipt,
            MemoryAnalysisReceipt,
        )

        from simple_harness_memory.core.audit import (
            LLMInvocationAuditRecord,
            OutputStorageStatus,
            PublicReasoningReference,
            ReasoningItemType,
        )

        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM llm_invocations WHERE invocation_id=?", (invocation_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        async with self._db.execute(
            "SELECT * FROM llm_invocation_evidence_refs WHERE invocation_id=? ORDER BY ordinal",
            (invocation_id,),
        ) as cursor:
            evidence_rows = await cursor.fetchall()
        refs = tuple(
            EvidenceRef(str(item["evidence_id"]), str(item["content_hash"]), int(item["ordinal"]))
            for item in evidence_rows
        )
        async with self._db.execute(
            "SELECT * FROM llm_reasoning_refs WHERE invocation_id=? ORDER BY ordinal",
            (invocation_id,),
        ) as cursor:
            reasoning_rows = await cursor.fetchall()
        reasoning = tuple(
            PublicReasoningReference(
                str(item["provider_item_id"]),
                ReasoningItemType(str(item["item_type"])),
                str(item["item_hash"]),
                None if item["opaque_ref"] is None else str(item["opaque_ref"]),
            )
            for item in reasoning_rows
        )
        public_output_value = (
            None
            if row["public_output_json"] is None
            else json.loads(str(row["public_output_json"]))
        )
        if public_output_value is not None and not isinstance(public_output_value, dict):
            raise MemoryCorruptionError("stored public output is not an object")
        delivery_receipt = None
        if row["delivery_receipt_json"] is not None:
            delivery_json = json.loads(str(row["delivery_receipt_json"]))
            if not isinstance(delivery_json, dict):
                raise MemoryCorruptionError("stored delivery receipt is not an object")
            delivery_receipt = MemoryAnalysisDeliveryReceipt.from_json(delivery_json)
        validation_json = json.loads(str(row["validation_receipt_json"]))
        if not isinstance(validation_json, dict):
            raise MemoryCorruptionError("stored validation receipt is not an object")
        validation_receipt = MemoryAnalysisReceipt.from_json(validation_json)
        record = LLMInvocationAuditRecord(
            int(row["invocation_sequence"]),
            str(row["invocation_id"]),
            str(row["principal_id"]),
            str(row["run_id"]),
            str(row["turn_id"]),
            str(row["job_id"]),
            str(row["request_hash"]),
            refs,
            public_output_value,
            None if row["public_output_hash"] is None else str(row["public_output_hash"]),
            OutputStorageStatus(str(row["output_storage_status"])),
            str(row["output_reason_code"]),
            str(row["provider_id"]),
            str(row["model_id"]),
            str(row["parameters_hash"]),
            str(row["prompt_version"]),
            str(row["schema_version"]),
            str(row["policy_version"]),
            str(row["validator_version"]),
            None if row["provider_request_id"] is None else str(row["provider_request_id"]),
            delivery_receipt,
            validation_receipt,
            str(row["result_hash"]),
            int(row["input_tokens"]),
            int(row["output_tokens"]),
            int(row["cost_microunits"]),
            int(row["latency_ms"]),
            float(row["started_at"]),
            float(row["completed_at"]),
            reasoning,
        )
        expected_input_json = canonical_json([item.to_json() for item in refs])
        if (
            expected_input_json != str(row["public_input_refs_json"])
            or hashlib.sha256(expected_input_json.encode()).hexdigest()
            != str(row["public_input_hash"])
            or (
                delivery_receipt is None
                and any(
                    row[name] is not None
                    for name in ("delivery_receipt_id", "delivery_receipt_hash")
                )
            )
            or (
                delivery_receipt is not None
                and (
                    delivery_receipt.receipt_id != str(row["delivery_receipt_id"])
                    or delivery_receipt.receipt_hash
                    != str(row["delivery_receipt_hash"])
                )
            )
            or validation_receipt.receipt_id != str(row["validation_receipt_id"])
            or validation_receipt.receipt_hash != str(row["validation_receipt_hash"])
            or record.invocation_hash != str(row["invocation_hash"])
        ):
            raise MemoryCorruptionError("stored analysis invocation hash differs")
        return record

    async def _read_decisions(self, invocation_id: str) -> tuple[DecisionLedgerEntry, ...]:
        from simple_harness.runtime import EvidenceRef

        from simple_harness_memory.core.audit import DecisionLedgerEntry, DecisionOutcome
        from simple_harness_memory.core.suppression import SuppressionScopeKind

        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM decision_records WHERE invocation_id=? ORDER BY decision_id",
            (invocation_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        decisions: list[DecisionLedgerEntry] = []
        for row in rows:
            async with self._db.execute(
                "SELECT * FROM decision_evidence_refs WHERE decision_id=? ORDER BY ordinal",
                (str(row["decision_id"]),),
            ) as cursor:
                evidence_rows = await cursor.fetchall()
            payload = json.loads(str(row["canonical_payload"]))
            before = json.loads(str(row["before_refs_json"]))
            after = json.loads(str(row["after_refs_json"]))
            if (
                not isinstance(payload, dict)
                or not isinstance(before, list)
                or not all(isinstance(item, str) for item in before)
                or not isinstance(after, list)
                or not all(isinstance(item, str) for item in after)
            ):
                raise MemoryCorruptionError("stored decision payload is malformed")
            decision = DecisionLedgerEntry(
                str(row["decision_id"]),
                str(row["operation_id"]),
                str(row["operation_kind"]),
                DecisionOutcome(str(row["outcome"])),
                SuppressionScopeKind(str(row["target_kind"])),
                str(row["target_ref"]),
                payload,
                tuple(before),
                tuple(after),
                tuple(
                    EvidenceRef(
                        str(item["evidence_id"]),
                        str(item["content_hash"]),
                        int(item["ordinal"]),
                    )
                    for item in evidence_rows
                ),
                str(row["reason_code"]),
                float(row["created_at"]),
            )
            if (
                hashlib.sha256(canonical_json(payload).encode()).hexdigest()
                != str(row["payload_hash"])
                or decision.decision_hash != str(row["decision_hash"])
            ):
                raise MemoryCorruptionError("stored decision hash differs")
            decisions.append(decision)
        return tuple(decisions)

    async def issue_sealed_audit_access(
        self, decision: SealedAuditAccessDecision
    ) -> SealedAuditAccessReceipt:
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDecision,
            SealedAuditAccessDenied,
            SealedAuditAccessReceipt,
        )

        if type(decision) is not SealedAuditAccessDecision:
            raise TypeError("decision must use SealedAuditAccessDecision")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        now = _timestamp(self._now())
        if decision.issued_at > now:
            raise SealedAuditAccessDenied("sealed_audit_decision_not_yet_valid")
        if now >= decision.expires_at:
            raise SealedAuditAccessDenied("sealed_audit_decision_expired")
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
            elif denial is None and now < access_receipt.issued_at:
                denial = "sealed_audit_access_not_yet_valid"
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
                "SELECT (SELECT COUNT(*) FROM sealed_audit_access_events "
                "WHERE access_receipt_id=? AND outcome='granted') + "
                "(SELECT COUNT(*) FROM audit_trace_access_events "
                "WHERE access_receipt_id=? AND outcome='granted')",
                (access_receipt.access_receipt_id, access_receipt.access_receipt_id),
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
            await self._db.execute(
                "INSERT INTO audit_cursor_authority(singleton,hmac_key_hex) VALUES(1,?)",
                (secrets.token_hex(32),),
            )
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

    async def _read_audit_cursor_hmac_key(self) -> bytes:
        assert self._db is not None
        async with self._db.execute(
            "SELECT hmac_key_hex FROM audit_cursor_authority WHERE singleton=1"
        ) as cursor:
            rows = list(await cursor.fetchall())
        if len(rows) != 1:
            raise MemoryCorruptionError("audit cursor authority cardinality differs")
        try:
            key = bytes.fromhex(str(rows[0][0]))
        except ValueError as exc:
            raise MemoryCorruptionError("audit cursor authority is invalid") from exc
        if len(key) != 32:
            raise MemoryCorruptionError("audit cursor authority is invalid")
        return key

    def _issue_audit_cursor(
        self, query_hash: str, watermark_sequence: int, last_sequence: int
    ) -> AuditTraceCursor:
        from simple_harness_memory.core.audit import AuditTraceCursor

        signature = self._audit_cursor_signature(
            query_hash, watermark_sequence, last_sequence
        )
        return AuditTraceCursor(
            query_hash, watermark_sequence, last_sequence, signature
        )

    def _verify_audit_cursor(self, cursor: AuditTraceCursor) -> bool:
        expected = self._audit_cursor_signature(
            cursor.query_hash, cursor.watermark_sequence, cursor.last_sequence
        )
        return hmac.compare_digest(cursor.cursor_hash, expected)

    def _audit_cursor_signature(
        self, query_hash: str, watermark_sequence: int, last_sequence: int
    ) -> str:
        if self._audit_cursor_hmac_key is None:
            raise RuntimeError("audit cursor authority is unavailable")
        payload = canonical_json(
            {
                "schema_version": 1,
                "query_hash": query_hash,
                "watermark_sequence": watermark_sequence,
                "last_sequence": last_sequence,
            }
        ).encode()
        return hmac.new(self._audit_cursor_hmac_key, payload, hashlib.sha256).hexdigest()

    async def _close_after_failure(self) -> None:
        if self._db is not None:
            with suppress(Exception):
                await self._db.close()
            self._db = None
        self._receipt = None
        self._audit_cursor_hmac_key = None
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


def _audit_identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode()) > 1024
        or any(pattern.search(value) for pattern in _AUDIT_IDENTIFIER_CREDENTIAL_PATTERNS)
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _validate_accepted_operation_decisions(
    structured_result: Mapping[str, FrozenJsonValue],
    decisions: tuple[DecisionLedgerEntry, ...],
) -> None:
    output = thaw_json(cast(FrozenJsonValue, structured_result))
    if not isinstance(output, dict):
        raise MemoryValidationError("analysis_operations_invalid")
    operations = output.get("operations")
    if not isinstance(operations, list):
        raise MemoryValidationError("analysis_operations_invalid")
    if not operations:
        if output.get("outcome") != "no_mutation":
            raise MemoryValidationError("analysis_zero_operations_outcome_invalid")
        if decisions:
            raise MemoryValidationError("analysis_operation_decisions_differ")
        return
    if output.get("outcome") == "no_mutation":
        raise MemoryValidationError("analysis_zero_operations_outcome_invalid")
    expected: dict[str, str] = {}
    for operation in operations:
        if not isinstance(operation, dict):
            raise MemoryValidationError("analysis_operation_invalid")
        operation_id = _audit_identifier(operation.get("operation_id"), "operation_id")
        operation_kind = _audit_identifier(operation.get("kind"), "operation_kind")
        if operation_id in expected:
            raise MemoryValidationError("analysis_operation_duplicated")
        expected[operation_id] = operation_kind
    actual = {decision.operation_id: decision.operation_kind for decision in decisions}
    if len(actual) != len(decisions) or actual.keys() != expected.keys():
        raise MemoryValidationError("analysis_operation_decisions_differ")
    if any(
        actual[operation_id] != operation_kind
        for operation_id, operation_kind in expected.items()
    ):
        raise MemoryValidationError("analysis_operation_kind_differs")


def _audit_trace_predicate(query: AuditTraceQuery) -> tuple[str, tuple[object, ...]]:
    from simple_harness_memory.core.audit import AuditTraceSelector

    if query.selector is AuditTraceSelector.TURN:
        return "i.turn_id=?", (query.selector_ref,)
    if query.selector is AuditTraceSelector.INVOCATION:
        return "i.invocation_id=?", (query.selector_ref,)
    if query.selector is AuditTraceSelector.DECISION:
        return (
            "EXISTS(SELECT 1 FROM decision_records d WHERE d.invocation_id=i.invocation_id "
            "AND d.decision_id=?)",
            (query.selector_ref,),
        )
    return (
        "(EXISTS(SELECT 1 FROM llm_invocation_evidence_refs er "
        "WHERE er.invocation_id=i.invocation_id AND er.evidence_id=?) OR "
        "EXISTS(SELECT 1 FROM decision_records d JOIN decision_evidence_refs dr "
        "ON dr.decision_id=d.decision_id WHERE d.invocation_id=i.invocation_id "
        "AND dr.evidence_id=?))",
        (query.selector_ref, query.selector_ref),
    )


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
