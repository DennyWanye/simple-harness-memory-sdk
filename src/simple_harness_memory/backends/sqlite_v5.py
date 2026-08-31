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
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
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
    MemoryErrorBase,
    MemoryIdempotencyConflict,
    MemoryLegacySchemaUnsupported,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemoryValidationError,
    MemoryWriterConflict,
)

if TYPE_CHECKING:
    from simple_harness.runtime import (
        ConversationEvidenceAuthorityVerifierPort,
        EvidenceAuthorityVerifierPort,
        MemoryActionAuthority,
        MemoryActionAuthorityPort,
        MemoryActionAuthorityRef,
        MemoryAnalysisDeliveryAuthorityPort,
        MemoryAnalysisDeliveryReceipt,
        MemoryAnalysisReceipt,
        MemoryAnalysisRequest,
        MemoryAnalysisResult,
        MemoryAnalysisResultEnvelope,
        MemoryMutationApplyReceipt,
        MemoryMutationApplyReceiptRef,
        MemoryMutationApplyResult,
        MemoryMutationOperation,
        MemoryMutationPlan,
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
    from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
    from simple_harness_memory.core.jobs import (
        AnalysisApplication,
        AnalysisBatchClaim,
        AnalysisResultCommit,
        MemoryJobWorkerConfig,
        RejectedAnalysisAudit,
        WorkerRunOutcome,
        _AnalysisDeliveryAdmission,
        _AnalysisDeliveryAuthorityRegistration,
    )
    from simple_harness_memory.core.mutations import InformationClassificationPolicy
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
    "job.result.after_capability_consume",
    "job.apply.before_commit",
    "job.apply.after_commit",
    "job.audit.after_capability_consume",
    "job.audit.before_commit",
    "job.audit.after_commit",
    "job.finalize.before_commit",
    "job.finalize.after_commit",
    "job.fail.before_commit",
    "job.fail.after_commit",
)
COGNITIVE_MUTATION_FAULT_POINTS = (
    "mutation.before_begin",
    "mutation.after_begin",
    "mutation.after_evidence",
    "mutation.after_operation",
    "mutation.after_operations",
    "mutation.after_receipt",
    "mutation.after_outbox",
    "mutation.before_commit",
    "mutation.after_commit",
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


@dataclass(slots=True)
class _DeliveryAdmissionState:
    admission: object
    authority: object
    batch_id: str
    lease_token: str
    request_hash: str
    envelope_hash: str
    result_hash: str
    delivery_receipt_hash: str
    purpose: str
    application_receipt_hash: str | None = None
    application_decisions_hash: str | None = None
    available: bool = True


class SQLiteHumanMemoryBackend:
    """Own the fresh v5 SQLite root and suppression-first repository APIs."""

    def __init__(
        self,
        db_path: str | os.PathLike[str],
        *,
        fault_injector: FaultInjector | None = None,
        now: Callable[[], float] = time.time,
        supported_filter_policies: frozenset[str] = _DEFAULT_FILTER_POLICIES,
        analysis_delivery_authority: MemoryAnalysisDeliveryAuthorityPort | None = None,
        evidence_authority: EvidenceAuthorityVerifierPort | None = None,
        conversation_evidence_authority: ConversationEvidenceAuthorityVerifierPort | None = None,
        classification_policy: InformationClassificationPolicy | None = None,
        memory_action_authority: MemoryActionAuthorityPort | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._fault_injector = fault_injector
        self._now = now
        self._db: aiosqlite.Connection | None = None
        self._secure_path: Path | None = None
        self._writer_lock_file: Any | None = None
        self._initialize_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._authority_registration_lock = threading.Lock()
        self._delivery_admissions: dict[int, _DeliveryAdmissionState] = {}
        self._receipt: InitializationReceipt | None = None
        self._audit_cursor_hmac_key: bytes | None = None
        self._busy_timeout_ms = 5000
        if not supported_filter_policies or any(
            not isinstance(item, str) or not item.strip() for item in supported_filter_policies
        ):
            raise MemoryValidationError("supported filter policies are invalid")
        self._supported_filter_policies = frozenset(supported_filter_policies)
        self._analysis_delivery_authority = analysis_delivery_authority
        self._evidence_authority = evidence_authority
        self._conversation_evidence_authority = conversation_evidence_authority
        self._classification_policy = classification_policy
        self._memory_action_authority = memory_action_authority
        self._analysis_delivery_authority_registration: object | None = None
        if analysis_delivery_authority is not None:
            verify = getattr(analysis_delivery_authority, "verify_analysis_delivery", None)
            if not callable(verify):
                raise TypeError(
                    "analysis_delivery_authority must implement MemoryAnalysisDeliveryAuthorityPort"
                )
            from simple_harness_memory.core.jobs import (
                _AnalysisDeliveryAuthorityRegistration,
            )

            self._analysis_delivery_authority_registration = (
                _AnalysisDeliveryAuthorityRegistration()
            )
        if evidence_authority is not None:
            for method_name in (
                "resolve_admitted_evidence",
                "resolve_typed_observation",
            ):
                if not callable(getattr(evidence_authority, method_name, None)):
                    raise TypeError(
                        "evidence_authority must implement EvidenceAuthorityVerifierPort"
                    )
        if conversation_evidence_authority is not None and not callable(
            getattr(conversation_evidence_authority, "resolve_conversation_registration", None)
        ):
            raise TypeError(
                "conversation_evidence_authority must implement "
                "ConversationEvidenceAuthorityVerifierPort"
            )
        if classification_policy is not None:
            from simple_harness_memory.core.mutations import InformationClassificationPolicy

            if type(classification_policy) is not InformationClassificationPolicy:
                raise TypeError("classification_policy must use InformationClassificationPolicy")
        if memory_action_authority is not None and not callable(
            getattr(memory_action_authority, "resolve_memory_action_authority", None)
        ):
            raise TypeError(
                "memory_action_authority must implement MemoryActionAuthorityPort"
            )

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
            async with self._admission_lock:
                self._delivery_admissions.clear()
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
        mutation_payload_hash = hashlib.sha256(mutation_payload_json.encode("utf-8")).hexdigest()
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

    async def revoke_suppression(self, request: SuppressionRevokeRequest) -> SuppressionDecision:
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

    async def register_conversation_evidence(self, reference: object) -> object:
        """Persist one exact Host-authorized conversation registration."""

        from simple_harness.runtime import (
            ConversationEvidenceRegistration,
            ConversationEvidenceRegistrationRef,
            verify_conversation_evidence_registration,
        )

        if type(reference) is not ConversationEvidenceRegistrationRef:
            raise TypeError("reference must use ConversationEvidenceRegistrationRef")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        if self._conversation_evidence_authority is None:
            raise MemoryValidationError("conversation_evidence_authority_required")
        registration = (
            await self._conversation_evidence_authority.resolve_conversation_registration(reference)
        )
        if type(registration) is not ConversationEvidenceRegistration:
            raise MemoryValidationError("conversation_registration_authority_rejected")

        class _PinnedAuthority:
            async def resolve_conversation_registration(self, requested: object) -> object:
                if requested != reference:
                    raise ValueError("conversation registration reference changed")
                return registration

        try:
            metadata = await verify_conversation_evidence_registration(
                reference, cast(Any, _PinnedAuthority())
            )
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("conversation_registration_authority_rejected") from exc
        envelope = registration.envelope
        admission = registration.admission_receipt
        metadata_receipt = registration.metadata_receipt
        registered_at = _timestamp(self._now())
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                async with self._db.execute(
                    "SELECT e.envelope_hash,e.run_id,e.subject,e.source_hash,"
                    "e.sanitized_hash,i.admission_receipt_id,i.admission_receipt_hash "
                    "FROM evidence_envelopes e JOIN ingestion_receipts i "
                    "ON i.evidence_id=e.evidence_id WHERE e.evidence_id=?",
                    (envelope.evidence_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                expected = (
                    envelope.envelope_hash,
                    envelope.run_id,
                    envelope.subject,
                    envelope.source_hash,
                    envelope.sanitized_hash,
                    admission.receipt_id,
                    admission.receipt_hash,
                )
                actual = None if row is None else tuple(str(row[index]) for index in range(7))
                if actual != expected:
                    raise MemoryValidationError("conversation_registration_evidence_differs")
                async with self._db.execute(
                    "SELECT registration_hash FROM conversation_evidence_registrations "
                    "WHERE registration_id=? OR evidence_id=?",
                    (registration.registration_id, envelope.evidence_id),
                ) as cursor:
                    existing = await cursor.fetchone()
                if existing is not None:
                    if str(existing[0]) != registration.registration_hash:
                        raise MemoryIdempotencyConflict(
                            "conversation_registration_identity_conflict"
                        )
                    await self._db.execute("COMMIT")
                    committed = True
                    return reference
                tool_causal_link_json = (
                    None
                    if metadata.tool_causal_link is None
                    else canonical_json(metadata.tool_causal_link.to_json())
                )
                await self._db.execute(
                    "INSERT INTO conversation_evidence_registrations("
                    "registration_id,registration_hash,principal_id,evidence_id,envelope_hash,"
                    "admission_receipt_id,admission_receipt_hash,metadata_id,metadata_hash,"
                    "metadata_json,metadata_receipt_id,metadata_receipt_hash,"
                    "metadata_receipt_json,authority_issuer_id,run_id,subject,conversation_id,"
                    "primary_conversation_id,causal_group_id,causal_group_sequence,item_ordinal,"
                    "group_item_count,ordered_group_manifest_hash,role,occurred_at,task_scope_id,"
                    "tool_causal_link_json,entities_json,registration_json,registered_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        registration.registration_id,
                        registration.registration_hash,
                        envelope.subject,
                        envelope.evidence_id,
                        envelope.envelope_hash,
                        admission.receipt_id,
                        admission.receipt_hash,
                        metadata.metadata_id,
                        metadata.metadata_hash,
                        canonical_json(metadata.to_json()),
                        metadata_receipt.receipt_id,
                        metadata_receipt.receipt_hash,
                        canonical_json(metadata_receipt.to_json()),
                        metadata.authority_issuer_id,
                        metadata.run_id,
                        metadata.subject,
                        metadata.conversation_id,
                        metadata.primary_conversation_id,
                        metadata.causal_group_id,
                        metadata.causal_group_sequence,
                        metadata.item_ordinal,
                        metadata.group_item_count,
                        metadata.ordered_group_manifest_hash,
                        metadata.role.value,
                        metadata.occurred_at,
                        metadata.task_scope_id,
                        tool_causal_link_json,
                        canonical_json(list(metadata.entities)),
                        canonical_json(registration.to_json()),
                        registered_at,
                    ),
                )
                await self._db.execute("COMMIT")
                committed = True
                return reference
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def apply_memory_mutation_plan(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        plan: MemoryMutationPlan,
    ) -> MemoryMutationApplyResult:
        """Apply one exact Harness plan as a repository-owned transaction."""

        from simple_harness.runtime import (
            EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
            CreatedByOperationTarget,
            EvidenceItemAuthority,
            ExistingMemoryTarget,
            InformationAttribute,
            LongTermMemoryType,
            MemoryActionAuthority,
            MemoryMutationApplyOutcome,
            MemoryMutationApplyReasonCode,
            MemoryMutationApplyReceipt,
            MemoryMutationApplyReceiptRef,
            MemoryMutationApplyResult,
            MemoryMutationKind,
            MemoryMutationPlan,
            MemoryMutationPlanOutcome,
            PrivacyClass,
            verify_evidence_span,
        )
        from simple_harness.runtime.memory_action_protocol import (
            MEMORY_ACTION_AUTHORITY_SCHEMA_VERSION,
            verify_memory_action_authority,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
        from simple_harness_memory.core.mutations import (
            InformationClassificationPolicy,
            compile_memory_mutation_plan,
            join_information_classification,
            validate_lifecycle_transition,
        )
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
            SuppressionDenied,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(scope) is not MemoryScope:
            raise TypeError("scope must use MemoryScope")
        if type(plan) is not MemoryMutationPlan:
            raise TypeError("plan must use MemoryMutationPlan")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            try:
                scope.authorize(principal)
                if plan.subject != principal.actor_id:
                    raise MemoryOwnershipConflict("mutation_subject_not_owned")
                if self._evidence_authority is None:
                    raise MemoryValidationError("evidence_authority_required")
                if type(self._classification_policy) is not InformationClassificationPolicy:
                    raise MemoryValidationError("classification_policy_required")
            except BaseException as preflight_exc:
                try:
                    await self._append_mutation_rejection_audit_unlocked(
                        plan,
                        authenticated_principal_id=principal.actor_id,
                        exc=preflight_exc,
                    )
                except Exception as audit_exc:
                    raise MemoryCorruptionError("mutation_rejection_audit_failed") from audit_exc
                raise
        classification_policy = self._classification_policy
        assert type(classification_policy) is InformationClassificationPolicy

        async with self._write_lock:
            begun = False
            committed = False
            try:
                self._fault("mutation.before_begin")
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
                self._fault("mutation.after_begin")

                prior_result = await self._read_mutation_apply_result_unlocked(plan)
                if (
                    prior_result is not None
                    and type(prior_result) is MemoryMutationApplyResult
                    and prior_result.outcome is not MemoryMutationApplyOutcome.COMMITTED
                ):
                    await self._db.execute("COMMIT")
                    committed = True
                    return prior_result

                replay = await self._read_mutation_receipt_by_idempotency_unlocked(
                    plan.subject, plan.idempotency_key
                )
                if replay is not None:
                    stored_plan_hash, stored_receipt = replay
                    if stored_plan_hash != plan.plan_hash:
                        raise MemoryIdempotencyConflict("mutation_idempotency_hash_conflict")
                    stored_receipt.validate_plan(plan)
                    stored_result = await self._read_mutation_apply_result_unlocked(plan)
                    if type(stored_result) is not MemoryMutationApplyResult:
                        raise MemoryCorruptionError("committed mutation apply result is missing")
                    assert stored_result is not None
                    if (
                        stored_result.outcome is not MemoryMutationApplyOutcome.COMMITTED
                        or stored_result.receipt_ref
                        != MemoryMutationApplyReceiptRef(
                            stored_receipt.receipt_id,
                            stored_receipt.receipt_hash,
                        )
                    ):
                        raise MemoryCorruptionError("committed mutation apply result differs")
                    await self._db.execute("COMMIT")
                    committed = True
                    return stored_result

                compiled = compile_memory_mutation_plan(plan)
                transaction_at = _timestamp(self._now())
                await self._db.execute(
                    "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,"
                    "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
                    (
                        plan.subject,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        transaction_at,
                    ),
                )
                await self._verify_plan_evidence_refs_unlocked(plan)
                async with self._db.execute(
                    "SELECT revision FROM cognitive_apply_heads WHERE principal_id=?",
                    (plan.subject,),
                ) as cursor:
                    head_row = await cursor.fetchone()
                current_apply_revision = 1 if head_row is None else int(head_row[0])
                if current_apply_revision != plan.base_revision:
                    raise MemoryWriterConflict("cognitive_apply_head_stale")
                if head_row is None:
                    await self._db.execute(
                        "INSERT INTO cognitive_apply_heads(principal_id,revision,updated_at) "
                        "VALUES(?,?,?)",
                        (plan.subject, current_apply_revision, transaction_at),
                    )

                verified_authorities: dict[str, EvidenceItemAuthority] = {}
                verified_span_origins: dict[str, tuple[object, ...]] = {}
                for compiled_operation in compiled.operations:
                    operation = compiled_operation.operation
                    for span in operation.evidence_spans:
                        if span.span_hash in verified_authorities:
                            continue
                        try:
                            authority = await verify_evidence_span(span, self._evidence_authority)
                        except (TypeError, ValueError) as exc:
                            raise MemoryValidationError("evidence_authority_rejected") from exc
                        if (
                            type(authority) is not EvidenceItemAuthority
                            or authority.schema_version != EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION
                        ):
                            raise MemoryValidationError("evidence_authority_rejected")
                        origins = await self._verify_mutation_span_unlocked(
                            subject=plan.subject,
                            span=span,
                        )
                        verified_authorities[span.span_hash] = authority
                        verified_span_origins[span.span_hash] = origins
                self._fault("mutation.after_evidence")

                protected_kinds = {
                    MemoryMutationKind.REVISE,
                    MemoryMutationKind.SUPERSEDE,
                    MemoryMutationKind.SUPPRESS,
                }
                missing_action_authorities: list[str] = []
                verified_action_authorities: list[
                    tuple[
                        int,
                        MemoryMutationOperation,
                        MemoryActionAuthorityRef,
                        MemoryActionAuthority,
                        float,
                    ]
                ] = []
                action_authority_failure: MemoryValidationError | None = None
                for canonical_index, compiled_operation in enumerate(
                    compiled.operations, start=1
                ):
                    operation = compiled_operation.operation
                    if operation.kind not in protected_kinds:
                        continue
                    if not isinstance(operation.target, ExistingMemoryTarget):
                        raise MemoryValidationError("memory_action_exact_target_required")
                    async with self._db.execute(
                        "SELECT current_revision FROM cognitive_memory_heads "
                        "WHERE principal_id=? AND memory_id=?",
                        (plan.subject, operation.target.memory_id),
                    ) as cursor:
                        action_target_row = await cursor.fetchone()
                    if action_target_row is None:
                        raise MemoryValidationError("mutation_target_not_found")
                    if int(action_target_row[0]) != operation.target.revision:
                        raise MemoryWriterConflict("cognitive_target_revision_stale")
                    intent = plan.action_intent(operation.operation_id)
                    if intent.canonical_operation_index != canonical_index:
                        raise MemoryCorruptionError("memory action canonical index differs")
                    reference = operation.action_authority_ref
                    if reference is None:
                        missing_action_authorities.append(operation.operation_id)
                        continue
                    if self._memory_action_authority is None:
                        action_authority_failure = MemoryValidationError(
                            "action_authority_rejected"
                        )
                        break
                    try:
                        verification_started_at = _timestamp(self._now())
                        verified_action = await verify_memory_action_authority(
                            intent,
                            reference,
                            self._memory_action_authority,
                            current_time=verification_started_at,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        action_authority_failure = MemoryValidationError(
                            "action_authority_rejected"
                        )
                        action_authority_failure.__cause__ = exc
                        break
                    if (
                        type(verified_action) is not MemoryActionAuthority
                        or verified_action.schema_version
                        != MEMORY_ACTION_AUTHORITY_SCHEMA_VERSION
                    ):
                        action_authority_failure = MemoryValidationError(
                            "action_authority_rejected"
                        )
                        break
                    consumed_at = _timestamp(self._now())
                    if not (
                        verified_action.issued_at
                        <= consumed_at
                        < verified_action.expires_at
                    ):
                        action_authority_failure = MemoryValidationError(
                            "action_authority_rejected"
                        )
                        break
                    verified_action_authorities.append(
                        (
                            canonical_index,
                            operation,
                            reference,
                            verified_action,
                            consumed_at,
                        )
                    )

                if missing_action_authorities or action_authority_failure is not None:
                    if action_authority_failure is not None:
                        action_exc = action_authority_failure
                        action_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.REJECTED,
                            reason_code=(
                                MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED
                            ),
                            decided_at=_timestamp(self._now()),
                        )
                    else:
                        action_exc = MemoryValidationError("action_authority_required")
                        action_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.NEEDS_USER_CONFIRMATION,
                            reason_code=(
                                MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REQUIRED
                            ),
                            decided_at=_timestamp(self._now()),
                            confirmation_operation_ids=tuple(missing_action_authorities),
                        )
                    await self._db.execute("ROLLBACK")
                    begun = False
                    try:
                        await self._append_mutation_rejection_audit_unlocked(
                            plan,
                            authenticated_principal_id=principal.actor_id,
                            exc=action_exc,
                            apply_result=action_result,
                        )
                    except Exception as audit_exc:
                        raise MemoryCorruptionError(
                            "mutation_rejection_audit_failed"
                        ) from audit_exc
                    return cast(MemoryMutationApplyResult, action_result)

                action_consumptions: dict[str, tuple[str, str]] = {}
                for canonical_index, operation, reference, authority, consumed_at in (
                    verified_action_authorities
                ):
                    intent = plan.action_intent(operation.operation_id)
                    consumption_id = _stable_id(
                        "memory-action-authority-consumption",
                        plan.subject,
                        plan.plan_id,
                        operation.operation_id,
                    )
                    consumption_json: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "consumption_id": consumption_id,
                        "principal_id": plan.subject,
                        "plan_id": plan.plan_id,
                        "plan_hash": plan.plan_hash,
                        "plan_intent_hash": plan.plan_intent_hash,
                        "operation_id": operation.operation_id,
                        "canonical_operation_index": canonical_index,
                        "action_kind": operation.kind.value,
                        "target_memory_id": intent.target_memory_id,
                        "target_revision": intent.target_revision,
                        "intent": intent.to_json(),
                        "intent_hash": intent.intent_hash,
                        "authority_ref": reference.to_json(),
                        "authority_ref_hash": reference.ref_hash,
                        "authority": authority.to_json(),
                        "authority_hash": authority.authority_hash,
                        "consumed_at": consumed_at,
                    }
                    consumption_hash = hashlib.sha256(
                        canonical_json(consumption_json).encode("utf-8")
                    ).hexdigest()
                    try:
                        await self._db.execute(
                            "INSERT INTO memory_action_authority_consumptions("
                            "consumption_id,principal_id,plan_id,plan_hash,plan_intent_hash,"
                            "operation_id,canonical_operation_index,action_kind,target_memory_id,"
                            "target_revision,intent_json,intent_hash,authority_ref_json,"
                            "authority_ref_hash,authority_schema_version,authority_id,"
                            "authority_hash,issuer_ref,nonce,replay_identity,authority_json,"
                            "issued_at,expires_at,consumed_at,consumption_hash) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                consumption_id,
                                plan.subject,
                                plan.plan_id,
                                plan.plan_hash,
                                plan.plan_intent_hash,
                                operation.operation_id,
                                canonical_index,
                                operation.kind.value,
                                intent.target_memory_id,
                                intent.target_revision,
                                canonical_json(intent.to_json()),
                                intent.intent_hash,
                                canonical_json(reference.to_json()),
                                reference.ref_hash,
                                authority.schema_version,
                                authority.authority_id,
                                authority.authority_hash,
                                authority.issuer_ref,
                                authority.nonce,
                                authority.replay_identity,
                                canonical_json(authority.to_json()),
                                authority.issued_at,
                                authority.expires_at,
                                consumed_at,
                                consumption_hash,
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        raise MemoryValidationError("action_authority_replayed") from exc
                    action_consumptions[operation.operation_id] = (
                        consumption_id,
                        consumption_hash,
                    )

                created_by_operation: dict[str, str] = {}
                operation_results: dict[str, tuple[str, int, int | None]] = {}
                classification_results: dict[str, tuple[str, str]] = {}
                for compiled_operation in compiled.operations:
                    operation = compiled_operation.operation
                    target_memory_id: str | None = None
                    target_revision: int | None = None
                    target_type: LongTermMemoryType | None = None
                    target_lifecycle: Any = None
                    target_privacy: PrivacyClass | None = None
                    target_attributes: tuple[InformationAttribute, ...] = ()
                    target_content_json: str | None = None

                    if operation.kind is MemoryMutationKind.CREATE:
                        memory_id = _stable_id(
                            "cognitive-memory",
                            plan.subject,
                            plan.plan_id,
                            operation.operation_id,
                        )
                        revision = 1
                    else:
                        if isinstance(operation.target, ExistingMemoryTarget):
                            target_memory_id = operation.target.memory_id
                            expected_revision = operation.target.revision
                        elif isinstance(operation.target, CreatedByOperationTarget):
                            try:
                                target_memory_id = created_by_operation[
                                    operation.target.operation_id
                                ]
                            except KeyError as exc:
                                raise MemoryValidationError(
                                    "mutation_created_target_not_materialized"
                                ) from exc
                            expected_revision = None
                        else:  # pragma: no cover - exact Harness DTO prevents this
                            raise MemoryValidationError("mutation_target_required")
                        async with self._db.execute(
                            "SELECT h.memory_type,h.current_revision,r.lifecycle_state,"
                            "r.effective_privacy_class,r.information_attributes_json,"
                            "r.content_json,r.epistemic_status,r.verification_state,"
                            "r.valid_from,r.valid_to FROM cognitive_memory_heads h "
                            "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
                            "AND r.revision=h.current_revision "
                            "WHERE h.principal_id=? AND h.memory_id=?",
                            (plan.subject, target_memory_id),
                        ) as cursor:
                            target_row = await cursor.fetchone()
                        if target_row is None:
                            raise MemoryValidationError("mutation_target_not_found")
                        target_type = LongTermMemoryType(str(target_row[0]))
                        target_revision = int(target_row[1])
                        if expected_revision is not None and target_revision != expected_revision:
                            raise MemoryWriterConflict("cognitive_target_revision_stale")
                        lifecycle_type = type(operation.lifecycle_state)
                        target_lifecycle = lifecycle_type(str(target_row[2]))
                        validate_lifecycle_transition(
                            memory_type=target_type,
                            current_lifecycle=target_lifecycle,
                            operation=operation,
                        )
                        target_privacy = PrivacyClass(str(target_row[3]))
                        raw_attributes = json.loads(str(target_row[4]))
                        if not isinstance(raw_attributes, list):
                            raise MemoryCorruptionError(
                                "cognitive information attributes are invalid"
                            )
                        target_attributes = tuple(
                            InformationAttribute(str(item)) for item in raw_attributes
                        )
                        target_content_json = str(target_row[5])
                        if operation.kind is MemoryMutationKind.CONTEST:
                            if not isinstance(operation.target, ExistingMemoryTarget):
                                raise MemoryValidationError(
                                    "mutation_contest_exact_slot_required"
                                )
                            proposed_content_json = (
                                None
                                if operation.payload is None
                                else canonical_json(operation.payload.to_json())
                            )
                            if (
                                proposed_content_json != target_content_json
                                or operation.lifecycle_state.value != str(target_row[2])
                                or operation.epistemic_status.value != str(target_row[6])
                                or operation.verification_state.value != str(target_row[7])
                                or operation.valid_time_interval.valid_from != target_row[8]
                                or operation.valid_time_interval.valid_until != target_row[9]
                            ):
                                raise MemoryValidationError(
                                    "mutation_contest_exact_slot_required"
                                )
                        memory_id = target_memory_id
                        revision = target_revision + 1

                    target_entity_ids = self._mutation_entity_ids_from_content_json(
                        target_content_json
                    )
                    entity_ids = tuple(
                        dict.fromkeys(
                            (
                                *target_entity_ids,
                                *self._mutation_entity_ids(operation.payload),
                            )
                        )
                    )
                    for span in operation.evidence_spans:
                        resolution = await self._resolve_suppression_unlocked(
                            SuppressionCandidate(
                                plan.subject,
                                evidence_id=span.evidence_id,
                                memory_id=target_memory_id,
                                entity_ids=entity_ids,
                            ),
                            OrdinaryMemoryPurpose.MUTATION,
                        )
                        if resolution.denied:
                            raise SuppressionDenied()

                    operation_authorities = tuple(
                        verified_authorities[span.span_hash] for span in operation.evidence_spans
                    )
                    privacy_floors = [classification_policy.required_privacy_class]
                    privacy_floors.extend(
                        authority.required_privacy_class for authority in operation_authorities
                    )
                    if target_privacy is not None:
                        privacy_floors.append(target_privacy)
                    classification = join_information_classification(
                        operation,
                        trusted_privacy_floors=tuple(privacy_floors),
                        trusted_attribute_sets=(
                            classification_policy.required_information_attributes,
                            *(
                                authority.required_information_attributes
                                for authority in operation_authorities
                            ),
                            target_attributes,
                        ),
                    )
                    origins_by_registration: dict[str, tuple[str, str, str]] = {}
                    for span in operation.evidence_spans:
                        for origin in verified_span_origins[span.span_hash]:
                            task_scope_id, evidence_id, registration_id = cast(
                                tuple[str, str, str], origin
                            )
                            origins_by_registration[registration_id] = (
                                task_scope_id,
                                evidence_id,
                                registration_id,
                            )
                    distinct_scopes = {value[0] for value in origins_by_registration.values()}
                    revision_task_scope = (
                        next(iter(distinct_scopes)) if len(distinct_scopes) == 1 else None
                    )

                    if operation.kind is MemoryMutationKind.CREATE:
                        await self._db.execute(
                            "INSERT INTO cognitive_memory_heads(memory_id,principal_id,"
                            "memory_type,current_revision,created_at,updated_at) "
                            "VALUES(?,?,?,?,?,?)",
                            (
                                memory_id,
                                plan.subject,
                                operation.memory_type.value,
                                revision,
                                transaction_at,
                                transaction_at,
                            ),
                        )
                    content_json = (
                        target_content_json
                        if operation.payload is None
                        else canonical_json(operation.payload.to_json())
                    )
                    if content_json is None:
                        raise MemoryCorruptionError("cognitive target content is missing")
                    content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
                    await self._db.execute(
                        "INSERT INTO cognitive_memory_revisions(memory_id,principal_id,revision,"
                        "plan_id,plan_hash,operation_id,task_scope_id,lifecycle_state,"
                        "epistemic_status,conflict_status,"
                        "verification_state,effective_privacy_class,"
                        "information_attributes_json,content_json,content_hash,valid_from,"
                        "valid_to,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            memory_id,
                            plan.subject,
                            revision,
                            plan.plan_id,
                            plan.plan_hash,
                            operation.operation_id,
                            revision_task_scope,
                            operation.lifecycle_state.value,
                            operation.epistemic_status.value,
                            operation.conflict_status.value,
                            operation.verification_state.value,
                            classification.privacy_class.value,
                            canonical_json(
                                [item.value for item in classification.information_attributes]
                            ),
                            content_json,
                            content_hash,
                            operation.valid_time_interval.valid_from,
                            operation.valid_time_interval.valid_until,
                            transaction_at,
                        ),
                    )
                    if operation.payload is None:
                        assert target_memory_id is not None and target_revision is not None
                        await self._copy_cognitive_payload_unlocked(
                            operation.memory_type.value,
                            target_memory_id,
                            target_revision,
                            memory_id,
                            revision,
                        )
                    else:
                        await self._insert_cognitive_payload_unlocked(
                            memory_id, revision, operation.payload
                        )
                    await self._insert_cognitive_evidence_unlocked(
                        memory_id, revision, operation.evidence_spans
                    )
                    classification_decision_id = _stable_id(
                        "cognitive-classification-decision",
                        plan.subject,
                        plan.plan_id,
                        operation.operation_id,
                    )
                    authority_inputs: list[JsonValue] = []
                    for ordinal, (span, authority) in enumerate(
                        zip(operation.evidence_spans, operation_authorities, strict=True),
                        start=1,
                    ):
                        authority_inputs.append(
                            {
                                "ordinal": ordinal,
                                "span_hash": span.span_hash,
                                "evidence_id": span.evidence_id,
                                "authority": authority.to_json(),
                                "authority_hash": authority.authority_hash,
                            }
                        )
                    target_input: JsonValue = (
                        None
                        if target_memory_id is None
                        else {
                            "memory_id": target_memory_id,
                            "revision": target_revision,
                            "privacy_class": (
                                None if target_privacy is None else target_privacy.value
                            ),
                            "information_attributes": [item.value for item in target_attributes],
                        }
                    )
                    classification_json: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "classification_decision_id": classification_decision_id,
                        "principal_id": plan.subject,
                        "plan_id": plan.plan_id,
                        "plan_hash": plan.plan_hash,
                        "operation_id": operation.operation_id,
                        "memory_ref": f"{memory_id}@{revision}",
                        "policy": classification_policy.to_json(),
                        "policy_hash": classification_policy.policy_hash,
                        "evidence_authorities": authority_inputs,
                        "target": target_input,
                        "proposal": {
                            "privacy_class": operation.proposed_privacy_class.value,
                            "information_attributes": [
                                item.value for item in operation.proposed_information_attributes
                            ],
                        },
                        "effective": {
                            "privacy_class": classification.privacy_class.value,
                            "information_attributes": [
                                item.value for item in classification.information_attributes
                            ],
                        },
                    }
                    classification_decision_hash = hashlib.sha256(
                        canonical_json(classification_json).encode("utf-8")
                    ).hexdigest()
                    await self._db.execute(
                        "INSERT INTO cognitive_classification_decisions("
                        "classification_decision_id,principal_id,plan_id,plan_hash,operation_id,"
                        "memory_id,memory_revision,policy_id,policy_version,policy_authority_ref,"
                        "policy_hash,policy_privacy_class,policy_attributes_json,"
                        "target_memory_id,target_revision,target_privacy_class,"
                        "target_attributes_json,proposed_privacy_class,proposed_attributes_json,"
                        "effective_privacy_class,effective_attributes_json,decision_json,"
                        "decision_hash,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            classification_decision_id,
                            plan.subject,
                            plan.plan_id,
                            plan.plan_hash,
                            operation.operation_id,
                            memory_id,
                            revision,
                            classification_policy.policy_id,
                            classification_policy.policy_version,
                            classification_policy.authority_ref,
                            classification_policy.policy_hash,
                            classification_policy.required_privacy_class.value,
                            canonical_json(
                                [
                                    item.value
                                    for item in (
                                        classification_policy.required_information_attributes
                                    )
                                ]
                            ),
                            target_memory_id,
                            target_revision,
                            None if target_privacy is None else target_privacy.value,
                            canonical_json([item.value for item in target_attributes]),
                            operation.proposed_privacy_class.value,
                            canonical_json(
                                [item.value for item in operation.proposed_information_attributes]
                            ),
                            classification.privacy_class.value,
                            canonical_json(
                                [item.value for item in classification.information_attributes]
                            ),
                            canonical_json(classification_json),
                            classification_decision_hash,
                            transaction_at,
                        ),
                    )
                    await self._db.executemany(
                        "INSERT INTO cognitive_classification_evidence_authorities("
                        "classification_decision_id,ordinal,span_hash,evidence_id,"
                        "authority_schema_version,authority_id,authority_hash,issuer_ref,"
                        "classification_authority_ref,required_privacy_class,"
                        "required_attributes_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            (
                                classification_decision_id,
                                ordinal,
                                span.span_hash,
                                span.evidence_id,
                                authority.schema_version,
                                authority.authority_id,
                                authority.authority_hash,
                                authority.issuer_ref,
                                authority.classification_authority_ref,
                                authority.required_privacy_class.value,
                                canonical_json(
                                    [
                                        item.value
                                        for item in authority.required_information_attributes
                                    ]
                                ),
                            )
                            for ordinal, (span, authority) in enumerate(
                                zip(
                                    operation.evidence_spans,
                                    operation_authorities,
                                    strict=True,
                                ),
                                start=1,
                            )
                        ),
                    )
                    await self._db.executemany(
                        "INSERT INTO cognitive_revision_task_scope_origins("
                        "memory_id,revision,task_scope_id,evidence_id,registration_id) "
                        "VALUES(?,?,?,?,?)",
                        (
                            (memory_id, revision, task_scope_id, evidence_id, registration_id)
                            for task_scope_id, evidence_id, registration_id in sorted(
                                origins_by_registration.values()
                            )
                        ),
                    )

                    if target_memory_id is not None and target_revision is not None:
                        relation_kind = {
                            MemoryMutationKind.REVISE: "amends",
                            MemoryMutationKind.SUPERSEDE: "supersedes",
                            MemoryMutationKind.CONTEST: "contests",
                            MemoryMutationKind.SUPPRESS: "relates_to",
                        }[operation.kind]
                        relation_id = _stable_id(
                            "cognitive-relation",
                            plan.subject,
                            plan.plan_id,
                            operation.operation_id,
                            relation_kind,
                            memory_id,
                            str(revision),
                            target_memory_id,
                            str(target_revision),
                        )
                        relation_json: dict[str, JsonValue] = {
                            "relation_id": relation_id,
                            "principal_id": plan.subject,
                            "plan_id": plan.plan_id,
                            "plan_hash": plan.plan_hash,
                            "relation_kind": relation_kind,
                            "source_memory_id": memory_id,
                            "source_revision": revision,
                            "target_memory_id": target_memory_id,
                            "target_revision": target_revision,
                            "operation_id": operation.operation_id,
                        }
                        relation_hash = hashlib.sha256(
                            canonical_json(relation_json).encode("utf-8")
                        ).hexdigest()
                        await self._db.execute(
                            "INSERT INTO cognitive_relations(relation_id,principal_id,"
                            "plan_id,plan_hash,source_memory_id,source_revision,relation_kind,"
                            "target_memory_id,target_revision,operation_id,created_at,"
                            "relation_hash) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                relation_id,
                                plan.subject,
                                plan.plan_id,
                                plan.plan_hash,
                                memory_id,
                                revision,
                                relation_kind,
                                target_memory_id,
                                target_revision,
                                operation.operation_id,
                                transaction_at,
                                relation_hash,
                            ),
                        )
                        update = await self._db.execute(
                            "UPDATE cognitive_memory_heads SET current_revision=?,updated_at=? "
                            "WHERE principal_id=? AND memory_id=? AND current_revision=?",
                            (
                                revision,
                                transaction_at,
                                plan.subject,
                                memory_id,
                                target_revision,
                            ),
                        )
                        if update.rowcount != 1:
                            raise MemoryWriterConflict("cognitive_target_cas_failed")

                    created_by_operation[operation.operation_id] = memory_id
                    operation_results[operation.operation_id] = (
                        memory_id,
                        revision,
                        target_revision,
                    )
                    classification_results[operation.operation_id] = (
                        classification_decision_id,
                        classification_decision_hash,
                    )
                    self._fault("mutation.after_operation")

                self._fault("mutation.after_operations")
                committed_at = _timestamp(self._now())
                if any(
                    not authority.issued_at
                    <= transaction_at
                    <= consumed_at
                    <= committed_at
                    < authority.expires_at
                    for _, _, _, authority, consumed_at in verified_action_authorities
                ):
                    raise MemoryValidationError("action_authority_rejected")
                committed_revision = plan.base_revision + (
                    1 if plan.outcome is MemoryMutationPlanOutcome.MUTATE else 0
                )
                if plan.outcome is MemoryMutationPlanOutcome.MUTATE:
                    update = await self._db.execute(
                        "UPDATE cognitive_apply_heads SET revision=?,updated_at=? "
                        "WHERE principal_id=? AND revision=?",
                        (
                            committed_revision,
                            committed_at,
                            plan.subject,
                            plan.base_revision,
                        ),
                    )
                    if update.rowcount != 1:
                        raise MemoryWriterConflict("cognitive_apply_head_cas_failed")

                receipt_id = _stable_id(
                    "memory-mutation-receipt", plan.subject, plan.idempotency_key
                )
                classification_decision_refs: list[JsonValue] = [
                    {
                        "operation_id": operation_id,
                        "classification_decision_id": classification_results[operation_id][0],
                        "classification_decision_hash": classification_results[operation_id][1],
                    }
                    for operation_id in (item.operation_id for item in compiled.operations)
                ]
                classification_decision_refs_json = canonical_json(classification_decision_refs)
                classification_decisions_hash = hashlib.sha256(
                    classification_decision_refs_json.encode("utf-8")
                ).hexdigest()
                action_authority_refs: list[JsonValue] = [
                    {
                        "operation_id": item.operation_id,
                        "action_authority_consumption_id": action_consumptions[
                            item.operation_id
                        ][0],
                        "action_authority_consumption_hash": action_consumptions[
                            item.operation_id
                        ][1],
                    }
                    for item in (compiled_item.operation for compiled_item in compiled.operations)
                    if item.operation_id in action_consumptions
                ]
                action_authority_refs_json = canonical_json(action_authority_refs)
                action_authorities_hash = hashlib.sha256(
                    action_authority_refs_json.encode("utf-8")
                ).hexdigest()
                transaction_started_hash = hashlib.sha256(
                    canonical_json(
                        {"transaction_started_at": transaction_at}
                    ).encode("utf-8")
                ).hexdigest()
                mutation_authority_hash = hashlib.sha256(
                    canonical_json(
                        {
                            "action_authorities_hash": action_authorities_hash,
                            "classification_decisions_hash": (
                                classification_decisions_hash
                            ),
                            "transaction_started_hash": transaction_started_hash,
                        }
                    ).encode("utf-8")
                ).hexdigest()
                receipt = MemoryMutationApplyReceipt(
                    receipt_id=receipt_id,
                    authority_ref=(
                        f"sqlite-human-memory:{self._receipt.receipt_id}:"
                        f"mutation:{mutation_authority_hash}"
                    ),
                    plan_id=plan.plan_id,
                    plan_hash=plan.plan_hash,
                    run_id=plan.run_id,
                    subject=plan.subject,
                    base_revision=plan.base_revision,
                    committed_revision=committed_revision,
                    canonical_operation_ids=tuple(
                        item.operation_id for item in compiled.operations
                    ),
                    apply_mode=plan.apply_mode,
                    committed_at=committed_at,
                )
                receipt.validate_plan(plan)
                await self._db.execute(
                    "INSERT INTO memory_mutation_receipts(receipt_id,principal_id,"
                    "authority_ref,plan_id,plan_hash,run_id,subject,idempotency_key,"
                    "plan_outcome,plan_json,base_revision,committed_revision,"
                    "canonical_operation_ids_json,apply_mode,classification_decision_refs_json,"
                    "classification_decisions_hash,action_authority_refs_json,"
                    "action_authorities_hash,transaction_started_at,receipt_json,"
                    "receipt_hash,committed_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt.receipt_id,
                        plan.subject,
                        receipt.authority_ref,
                        plan.plan_id,
                        plan.plan_hash,
                        plan.run_id,
                        plan.subject,
                        plan.idempotency_key,
                        plan.outcome.value,
                        canonical_json(plan.to_json()),
                        plan.base_revision,
                        receipt.committed_revision,
                        canonical_json(list(receipt.canonical_operation_ids)),
                        plan.apply_mode.value,
                        classification_decision_refs_json,
                        classification_decisions_hash,
                        action_authority_refs_json,
                        action_authorities_hash,
                        transaction_at,
                        canonical_json(receipt.to_json()),
                        receipt.receipt_hash,
                        committed_at,
                    ),
                )
                for compiled_operation in compiled.operations:
                    operation = compiled_operation.operation
                    memory_id, after_revision, before_revision = operation_results[
                        operation.operation_id
                    ]
                    before_ref = (
                        None if before_revision is None else f"{memory_id}@{before_revision}"
                    )
                    decision_id = _stable_id(
                        "memory-mutation-decision",
                        receipt.receipt_id,
                        operation.operation_id,
                    )
                    classification_decision_id, classification_decision_hash = (
                        classification_results[operation.operation_id]
                    )
                    action_consumption = action_consumptions.get(operation.operation_id)
                    decision_json: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "decision_id": decision_id,
                        "operation_id": operation.operation_id,
                        "outcome": "committed",
                        "reason_code": operation.reason_code,
                        "before_ref": before_ref,
                        "after_ref": f"{memory_id}@{after_revision}",
                        "classification_decision_id": classification_decision_id,
                        "classification_decision_hash": classification_decision_hash,
                        "action_authority_consumption_id": (
                            None if action_consumption is None else action_consumption[0]
                        ),
                        "action_authority_consumption_hash": (
                            None if action_consumption is None else action_consumption[1]
                        ),
                    }
                    decision_hash = hashlib.sha256(
                        canonical_json(decision_json).encode("utf-8")
                    ).hexdigest()
                    await self._db.execute(
                        "INSERT INTO memory_mutation_decisions(decision_id,receipt_id,"
                        "operation_id,outcome,reason_code,before_ref,after_ref,"
                        "classification_decision_id,classification_decision_hash,"
                        "action_authority_consumption_id,action_authority_consumption_hash,"
                        "decision_json,decision_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            decision_id,
                            receipt.receipt_id,
                            operation.operation_id,
                            "committed",
                            operation.reason_code,
                            before_ref,
                            f"{memory_id}@{after_revision}",
                            classification_decision_id,
                            classification_decision_hash,
                            None if action_consumption is None else action_consumption[0],
                            None if action_consumption is None else action_consumption[1],
                            canonical_json(decision_json),
                            decision_hash,
                        ),
                    )
                self._fault("mutation.after_receipt")

                if plan.outcome is MemoryMutationPlanOutcome.MUTATE:
                    outbox_payload: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "receipt_id": receipt.receipt_id,
                        "receipt_hash": receipt.receipt_hash,
                        "plan_id": plan.plan_id,
                        "committed_revision": committed_revision,
                    }
                    outbox_json = canonical_json(outbox_payload)
                    await self._db.execute(
                        "INSERT INTO outbox(outbox_id,principal_id,topic,idempotency_key,"
                        "payload,payload_hash,state,next_attempt_at,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,'pending',?,?,?)",
                        (
                            _stable_id("memory-mutation-outbox", receipt.receipt_id),
                            plan.subject,
                            "memory.cognitive.committed",
                            receipt.receipt_id,
                            outbox_json,
                            hashlib.sha256(outbox_json.encode("utf-8")).hexdigest(),
                            committed_at,
                            committed_at,
                            committed_at,
                        ),
                    )
                receipt_ref = MemoryMutationApplyReceiptRef(
                    receipt.receipt_id, receipt.receipt_hash
                )
                apply_result = _mutation_apply_result(
                    plan,
                    outcome=MemoryMutationApplyOutcome.COMMITTED,
                    reason_code=(
                        MemoryMutationApplyReasonCode.COMMITTED
                        if plan.outcome is MemoryMutationPlanOutcome.MUTATE
                        else MemoryMutationApplyReasonCode.NO_MUTATION
                    ),
                    decided_at=committed_at,
                    receipt_ref=receipt_ref,
                )
                await self._insert_mutation_apply_result_unlocked(plan, apply_result)
                self._fault("mutation.after_outbox")
                self._fault("mutation.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("mutation.after_commit")
                return cast(MemoryMutationApplyResult, apply_result)
            except BaseException as exc:
                if not committed:
                    if begun:
                        with suppress(Exception):
                            await self._db.execute("ROLLBACK")
                    noncommitted_result: MemoryMutationApplyResult | None = None
                    if (
                        type(exc) is MemoryValidationError
                        and str(exc)
                        in {"action_authority_rejected", "action_authority_replayed"}
                    ):
                        noncommitted_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.REJECTED,
                            reason_code=(
                                MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED
                            ),
                            decided_at=_timestamp(self._now()),
                        )
                    elif (
                        type(exc) is MemoryValidationError
                        and str(exc).startswith("mutation_contest_")
                    ):
                        noncommitted_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.REJECTED,
                            reason_code=(
                                MemoryMutationApplyReasonCode.VALIDATION_REJECTED
                            ),
                            decided_at=_timestamp(self._now()),
                        )
                    try:
                        await self._append_mutation_rejection_audit_unlocked(
                            plan,
                            authenticated_principal_id=principal.actor_id,
                            exc=exc,
                            apply_result=noncommitted_result,
                        )
                    except Exception as audit_exc:
                        raise MemoryCorruptionError(
                            "mutation_rejection_audit_failed"
                        ) from audit_exc
                    if noncommitted_result is not None:
                        return cast(MemoryMutationApplyResult, noncommitted_result)
                raise

    async def resolve_memory_mutation_apply_receipt(
        self, receipt_ref: MemoryMutationApplyReceiptRef
    ) -> MemoryMutationApplyReceipt:
        """Resolve an immutable Harness apply receipt by exact reference."""

        from simple_harness.runtime import MemoryMutationApplyReceiptRef

        if type(receipt_ref) is not MemoryMutationApplyReceiptRef:
            raise TypeError("receipt_ref must use MemoryMutationApplyReceiptRef")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._db.execute(
            "SELECT * FROM memory_mutation_receipts WHERE receipt_id=?",
            (receipt_ref.receipt_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise KeyError("memory_mutation_receipt_not_found")
        if str(row["receipt_hash"]) != receipt_ref.receipt_hash:
            raise MemoryValidationError("memory_mutation_receipt_ref_hash_mismatch")
        try:
            _plan_hash, receipt = await self._decode_and_verify_mutation_receipt_row_unlocked(
                row, expected_receipt_hash=receipt_ref.receipt_hash
            )
        except MemoryCorruptionError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise MemoryCorruptionError("stored mutation receipt verification failed") from exc
        return receipt

    async def _read_mutation_receipt_by_idempotency_unlocked(
        self, principal_id: str, idempotency_key: str
    ) -> tuple[str, MemoryMutationApplyReceipt] | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM memory_mutation_receipts WHERE principal_id=? AND idempotency_key=?",
            (principal_id, idempotency_key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return await self._decode_and_verify_mutation_receipt_row_unlocked(row)
        except MemoryCorruptionError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise MemoryCorruptionError("stored mutation receipt verification failed") from exc

    async def _decode_and_verify_mutation_receipt_row_unlocked(
        self,
        row: aiosqlite.Row,
        *,
        expected_receipt_hash: str | None = None,
    ) -> tuple[str, MemoryMutationApplyReceipt]:
        from simple_harness.runtime import MemoryMutationApplyReceipt, MemoryMutationPlan

        try:
            raw_receipt = json.loads(str(row["receipt_json"]))
            raw_plan = json.loads(str(row["plan_json"]))
            if not isinstance(raw_receipt, dict) or not isinstance(raw_plan, dict):
                raise ValueError("stored wire must be an object")
            receipt = MemoryMutationApplyReceipt.from_json(raw_receipt)
            plan = MemoryMutationPlan.from_json(raw_plan)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("stored mutation receipt wire is invalid") from exc
        receipt_json = canonical_json(receipt.to_json())
        plan_json = canonical_json(plan.to_json())
        if receipt_json != str(row["receipt_json"]):
            raise MemoryCorruptionError("stored mutation receipt canonical JSON differs")
        if plan_json != str(row["plan_json"]):
            raise MemoryCorruptionError("stored mutation plan canonical JSON differs")
        if (
            receipt.receipt_hash != str(row["receipt_hash"])
            or (expected_receipt_hash is not None and receipt.receipt_hash != expected_receipt_hash)
            or plan.plan_hash != str(row["plan_hash"])
        ):
            raise MemoryCorruptionError("stored mutation receipt or plan hash differs")
        try:
            receipt.validate_plan(plan)
        except (TypeError, ValueError) as exc:
            raise MemoryCorruptionError("stored mutation receipt plan binding differs") from exc
        expected_columns = (
            receipt.receipt_id,
            receipt.authority_ref,
            receipt.plan_id,
            receipt.plan_hash,
            receipt.run_id,
            receipt.subject,
            plan.idempotency_key,
            plan.outcome.value,
            receipt.base_revision,
            receipt.committed_revision,
            plan.apply_mode.value,
            receipt.receipt_hash,
            receipt.committed_at,
        )
        actual_columns = (
            str(row["receipt_id"]),
            str(row["authority_ref"]),
            str(row["plan_id"]),
            str(row["plan_hash"]),
            str(row["run_id"]),
            str(row["subject"]),
            str(row["idempotency_key"]),
            str(row["plan_outcome"]),
            int(row["base_revision"]),
            int(row["committed_revision"]),
            str(row["apply_mode"]),
            str(row["receipt_hash"]),
            float(row["committed_at"]),
        )
        if actual_columns != expected_columns or str(row["principal_id"]) != plan.subject:
            raise MemoryCorruptionError("stored mutation receipt duplicated columns differ")
        try:
            operation_ids = json.loads(str(row["canonical_operation_ids_json"]))
        except json.JSONDecodeError as exc:
            raise MemoryCorruptionError("stored canonical operation IDs are invalid") from exc
        if operation_ids != list(receipt.canonical_operation_ids) or canonical_json(
            operation_ids
        ) != str(row["canonical_operation_ids_json"]):
            raise MemoryCorruptionError("stored canonical operation IDs differ")
        await self._verify_classification_receipt_chain_unlocked(row, receipt, plan)
        return plan.plan_hash, receipt

    async def _verify_classification_receipt_chain_unlocked(
        self,
        receipt_row: aiosqlite.Row,
        receipt: MemoryMutationApplyReceipt,
        plan: MemoryMutationPlan,
    ) -> None:
        from simple_harness.runtime import (
            EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
            EvidenceActorRole,
            EvidenceItemAuthority,
            EvidenceProvenance,
            EvidenceSourceKind,
            InformationAttribute,
            PrivacyClass,
        )
        from simple_harness.runtime.memory_action_protocol import (
            MEMORY_ACTION_AUTHORITY_SCHEMA_VERSION,
            MemoryActionAuthority,
            MemoryActionAuthorityRef,
        )

        from simple_harness_memory.core.mutations import (
            InformationClassificationPolicy,
            join_information_classification,
        )

        assert self._db is not None
        assert self._receipt is not None
        receipt_id = receipt.receipt_id
        authority_ref = str(receipt_row["authority_ref"])
        refs_json = str(receipt_row["classification_decision_refs_json"])
        refs_hash = str(receipt_row["classification_decisions_hash"])
        if hashlib.sha256(refs_json.encode("utf-8")).hexdigest() != refs_hash:
            raise MemoryCorruptionError("classification decision refs hash differs")
        action_refs_json = str(receipt_row["action_authority_refs_json"])
        action_refs_hash = str(receipt_row["action_authorities_hash"])
        if hashlib.sha256(action_refs_json.encode("utf-8")).hexdigest() != action_refs_hash:
            raise MemoryCorruptionError("action authority refs hash differs")
        transaction_started_at = float(receipt_row["transaction_started_at"])
        if transaction_started_at > receipt.committed_at:
            raise MemoryCorruptionError("mutation transaction timestamp differs")
        transaction_started_hash = hashlib.sha256(
            canonical_json(
                {"transaction_started_at": transaction_started_at}
            ).encode("utf-8")
        ).hexdigest()
        mutation_authority_hash = hashlib.sha256(
            canonical_json(
                {
                    "action_authorities_hash": action_refs_hash,
                    "classification_decisions_hash": refs_hash,
                    "transaction_started_hash": transaction_started_hash,
                }
            ).encode("utf-8")
        ).hexdigest()
        expected_authority_ref = (
            f"sqlite-human-memory:{self._receipt.receipt_id}:"
            f"mutation:{mutation_authority_hash}"
        )
        if authority_ref != receipt.authority_ref or authority_ref != expected_authority_ref:
            raise MemoryCorruptionError("receipt authority classification binding differs")
        try:
            refs = json.loads(refs_json)
        except json.JSONDecodeError as exc:
            raise MemoryCorruptionError("classification decision refs are malformed") from exc
        if not isinstance(refs, list) or canonical_json(refs) != refs_json:
            raise MemoryCorruptionError("classification decision refs are malformed")
        operation_ids = tuple(receipt.canonical_operation_ids)
        if len(refs) != len(operation_ids):
            raise MemoryCorruptionError("classification decision refs cardinality differs")
        operations = {item.operation_id: item for item in plan.operations}
        protected_operations = [
            item
            for item in plan.operations
            if item.kind.value in {"revise", "supersede", "suppress"}
        ]
        try:
            action_refs = json.loads(action_refs_json)
        except json.JSONDecodeError as exc:
            raise MemoryCorruptionError("action authority refs are malformed") from exc
        if (
            not isinstance(action_refs, list)
            or canonical_json(action_refs) != action_refs_json
            or len(action_refs) != len(protected_operations)
        ):
            raise MemoryCorruptionError("action authority refs cardinality differs")
        action_consumptions: dict[str, tuple[str, str]] = {}
        for operation, action_value in zip(
            protected_operations, action_refs, strict=True
        ):
            if not isinstance(action_value, dict) or set(action_value) != {
                "operation_id",
                "action_authority_consumption_id",
                "action_authority_consumption_hash",
            }:
                raise MemoryCorruptionError("action authority ref is malformed")
            consumption_id = action_value.get("action_authority_consumption_id")
            consumption_hash = action_value.get("action_authority_consumption_hash")
            if (
                action_value.get("operation_id") != operation.operation_id
                or not isinstance(consumption_id, str)
                or not isinstance(consumption_hash, str)
                or operation.operation_id in action_consumptions
            ):
                raise MemoryCorruptionError("action authority ref order differs")
            async with self._db.execute(
                "SELECT * FROM memory_action_authority_consumptions WHERE consumption_id=?",
                (consumption_id,),
            ) as cursor:
                consumption = await cursor.fetchone()
            if consumption is None:
                raise MemoryCorruptionError("action authority consumption is missing")
            try:
                intent_value = json.loads(str(consumption["intent_json"]))
                reference_value = json.loads(str(consumption["authority_ref_json"]))
                authority_value = json.loads(str(consumption["authority_json"]))
                if not all(
                    isinstance(value, dict)
                    for value in (intent_value, reference_value, authority_value)
                ):
                    raise ValueError("action authority wire is not an object")
                authority = MemoryActionAuthority.from_json(authority_value)
                reference = MemoryActionAuthorityRef.from_json(reference_value)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise MemoryCorruptionError("action authority wire is invalid") from exc
            intent = plan.action_intent(operation.operation_id)
            canonical_index = plan.operations.index(operation) + 1
            consumed_at = float(consumption["consumed_at"])
            if (
                intent_value != intent.to_json()
                or authority.intent != intent
                or MemoryActionAuthorityRef.from_authority(authority) != reference
                or authority.schema_version != MEMORY_ACTION_AUTHORITY_SCHEMA_VERSION
                or operation.action_authority_ref != reference
                or intent.canonical_operation_index != canonical_index
                or not authority.issued_at
                <= transaction_started_at
                <= consumed_at
                <= receipt.committed_at
                < authority.expires_at
            ):
                raise MemoryCorruptionError("action authority binding differs")
            expected_consumption_json: dict[str, JsonValue] = {
                "schema_version": 1,
                "consumption_id": consumption_id,
                "principal_id": plan.subject,
                "plan_id": plan.plan_id,
                "plan_hash": plan.plan_hash,
                "plan_intent_hash": plan.plan_intent_hash,
                "operation_id": operation.operation_id,
                "canonical_operation_index": canonical_index,
                "action_kind": operation.kind.value,
                "target_memory_id": intent.target_memory_id,
                "target_revision": intent.target_revision,
                "intent": intent.to_json(),
                "intent_hash": intent.intent_hash,
                "authority_ref": reference.to_json(),
                "authority_ref_hash": reference.ref_hash,
                "authority": authority.to_json(),
                "authority_hash": authority.authority_hash,
                "consumed_at": consumed_at,
            }
            recomputed_consumption_hash = hashlib.sha256(
                canonical_json(expected_consumption_json).encode("utf-8")
            ).hexdigest()
            consumption_columns = (
                str(consumption["principal_id"]),
                str(consumption["plan_id"]),
                str(consumption["plan_hash"]),
                str(consumption["plan_intent_hash"]),
                str(consumption["operation_id"]),
                int(consumption["canonical_operation_index"]),
                str(consumption["action_kind"]),
                str(consumption["target_memory_id"]),
                int(consumption["target_revision"]),
                str(consumption["intent_json"]),
                str(consumption["intent_hash"]),
                str(consumption["authority_ref_json"]),
                str(consumption["authority_ref_hash"]),
                int(consumption["authority_schema_version"]),
                str(consumption["authority_id"]),
                str(consumption["authority_hash"]),
                str(consumption["issuer_ref"]),
                str(consumption["nonce"]),
                str(consumption["replay_identity"]),
                str(consumption["authority_json"]),
                float(consumption["issued_at"]),
                float(consumption["expires_at"]),
                consumed_at,
                str(consumption["consumption_hash"]),
            )
            expected_consumption_columns = (
                plan.subject,
                plan.plan_id,
                plan.plan_hash,
                plan.plan_intent_hash,
                operation.operation_id,
                canonical_index,
                operation.kind.value,
                intent.target_memory_id,
                intent.target_revision,
                canonical_json(intent.to_json()),
                intent.intent_hash,
                canonical_json(reference.to_json()),
                reference.ref_hash,
                authority.schema_version,
                authority.authority_id,
                authority.authority_hash,
                authority.issuer_ref,
                authority.nonce,
                authority.replay_identity,
                canonical_json(authority.to_json()),
                authority.issued_at,
                authority.expires_at,
                consumed_at,
                recomputed_consumption_hash,
            )
            if (
                consumption_columns != expected_consumption_columns
                or recomputed_consumption_hash != consumption_hash
            ):
                raise MemoryCorruptionError("action authority consumption differs")
            async with self._db.execute(
                "SELECT COUNT(*) FROM memory_action_authority_consumptions "
                "WHERE replay_identity=? OR (issuer_ref=? AND nonce=?)",
                (authority.replay_identity, authority.issuer_ref, authority.nonce),
            ) as cursor:
                duplicate_row = await cursor.fetchone()
            if duplicate_row is None or int(duplicate_row[0]) != 1:
                raise MemoryCorruptionError("action authority replay fence differs")
            action_consumptions[operation.operation_id] = (
                consumption_id,
                consumption_hash,
            )
        seen_decisions: set[str] = set()
        for expected_operation_id, value in zip(operation_ids, refs, strict=True):
            if not isinstance(value, dict) or set(value) != {
                "operation_id",
                "classification_decision_id",
                "classification_decision_hash",
            }:
                raise MemoryCorruptionError("classification decision ref is malformed")
            decision_id = value.get("classification_decision_id")
            decision_hash = value.get("classification_decision_hash")
            operation_id = value.get("operation_id")
            if (
                operation_id != expected_operation_id
                or not isinstance(decision_id, str)
                or not isinstance(decision_hash, str)
                or decision_id in seen_decisions
            ):
                raise MemoryCorruptionError("classification decision ref order differs")
            seen_decisions.add(decision_id)
            operation = operations.get(operation_id)
            if operation is None:
                raise MemoryCorruptionError("classification operation is missing")
            async with self._db.execute(
                "SELECT * FROM cognitive_classification_decisions "
                "WHERE classification_decision_id=?",
                (decision_id,),
            ) as cursor:
                parent = await cursor.fetchone()
            if parent is None:
                raise MemoryCorruptionError("classification decision chain differs")
            try:
                decision_json = json.loads(str(parent["decision_json"]))
            except json.JSONDecodeError as exc:
                raise MemoryCorruptionError("classification decision JSON is invalid") from exc
            if not isinstance(decision_json, dict):
                raise MemoryCorruptionError("classification decision JSON is invalid")
            if (
                set(decision_json)
                != {
                    "schema_version",
                    "classification_decision_id",
                    "principal_id",
                    "plan_id",
                    "plan_hash",
                    "operation_id",
                    "memory_ref",
                    "policy",
                    "policy_hash",
                    "evidence_authorities",
                    "target",
                    "proposal",
                    "effective",
                }
                or decision_json.get("schema_version") != 1
            ):
                raise MemoryCorruptionError("classification decision shape differs")
            canonical_decision_json = canonical_json(decision_json)
            recomputed_decision_hash = hashlib.sha256(
                canonical_decision_json.encode("utf-8")
            ).hexdigest()
            if (
                canonical_decision_json != str(parent["decision_json"])
                or recomputed_decision_hash != str(parent["decision_hash"])
                or recomputed_decision_hash != decision_hash
            ):
                raise MemoryCorruptionError("classification decision hash differs")
            policy_value = decision_json.get("policy")
            proposal_value = decision_json.get("proposal")
            effective_value = decision_json.get("effective")
            authority_values = decision_json.get("evidence_authorities")
            target_value = decision_json.get("target")
            if (
                not isinstance(policy_value, dict)
                or not isinstance(proposal_value, dict)
                or not isinstance(effective_value, dict)
                or not isinstance(authority_values, list)
            ):
                raise MemoryCorruptionError("classification decision inputs are invalid")
            try:
                policy = InformationClassificationPolicy(
                    policy_id=str(policy_value["policy_id"]),
                    policy_version=str(policy_value["policy_version"]),
                    authority_ref=str(policy_value["authority_ref"]),
                    required_privacy_class=PrivacyClass(
                        str(policy_value["required_privacy_class"])
                    ),
                    required_information_attributes=tuple(
                        InformationAttribute(str(item))
                        for item in policy_value["required_information_attributes"]
                    ),
                    schema_version=int(policy_value["schema_version"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("classification policy wire is invalid") from exc
            if (
                policy.to_json() != policy_value
                or decision_json.get("policy_hash") != policy.policy_hash
            ):
                raise MemoryCorruptionError("classification policy hash differs")
            policy_attributes_json = canonical_json(
                [item.value for item in policy.required_information_attributes]
            )
            parent_common = (
                str(parent["classification_decision_id"]),
                str(parent["principal_id"]),
                str(parent["plan_id"]),
                str(parent["plan_hash"]),
                str(parent["operation_id"]),
                str(parent["policy_id"]),
                str(parent["policy_version"]),
                str(parent["policy_authority_ref"]),
                str(parent["policy_hash"]),
                str(parent["policy_privacy_class"]),
                str(parent["policy_attributes_json"]),
            )
            expected_parent_common = (
                decision_id,
                plan.subject,
                plan.plan_id,
                plan.plan_hash,
                operation_id,
                policy.policy_id,
                policy.policy_version,
                policy.authority_ref,
                policy.policy_hash,
                policy.required_privacy_class.value,
                policy_attributes_json,
            )
            if parent_common != expected_parent_common:
                raise MemoryCorruptionError("classification parent duplicated columns differ")
            if float(parent["created_at"]) != transaction_started_at:
                raise MemoryCorruptionError("classification decision timestamp differs")
            memory_id = str(parent["memory_id"])
            memory_revision = int(parent["memory_revision"])
            if decision_json.get("memory_ref") != f"{memory_id}@{memory_revision}":
                raise MemoryCorruptionError("classification memory reference differs")
            if any(
                decision_json.get(key) != expected
                for key, expected in (
                    ("classification_decision_id", decision_id),
                    ("principal_id", plan.subject),
                    ("plan_id", plan.plan_id),
                    ("plan_hash", plan.plan_hash),
                    ("operation_id", operation_id),
                )
            ):
                raise MemoryCorruptionError("classification decision identity differs")

            async with self._db.execute(
                "SELECT * FROM cognitive_classification_evidence_authorities "
                "WHERE classification_decision_id=? ORDER BY ordinal",
                (decision_id,),
            ) as cursor:
                child_rows = tuple(await cursor.fetchall())
            if len(child_rows) != len(authority_values) or len(child_rows) != len(
                operation.evidence_spans
            ):
                raise MemoryCorruptionError("classification evidence authority count differs")
            authorities: list[EvidenceItemAuthority] = []
            for child_ordinal, (child, authority_value, span) in enumerate(
                zip(
                    child_rows,
                    authority_values,
                    operation.evidence_spans,
                    strict=True,
                ),
                start=1,
            ):
                if not isinstance(authority_value, dict) or set(authority_value) != {
                    "ordinal",
                    "span_hash",
                    "evidence_id",
                    "authority",
                    "authority_hash",
                }:
                    raise MemoryCorruptionError("classification authority input is malformed")
                raw_authority = authority_value.get("authority")
                if not isinstance(raw_authority, dict):
                    raise MemoryCorruptionError("classification authority wire is malformed")
                try:
                    authority = EvidenceItemAuthority(
                        schema_version=int(raw_authority["schema_version"]),
                        authority_id=str(raw_authority["authority_id"]),
                        evidence_id=str(raw_authority["evidence_id"]),
                        envelope_hash=str(raw_authority["envelope_hash"]),
                        sanitized_hash=str(raw_authority["sanitized_hash"]),
                        source_hash=str(raw_authority["source_hash"]),
                        source_kind=EvidenceSourceKind(str(raw_authority["source_kind"])),
                        item_ordinal=int(raw_authority["item_ordinal"]),
                        item_id=str(raw_authority["item_id"]),
                        item_json_pointer=str(raw_authority["item_json_pointer"]),
                        normalization_version=str(raw_authority["normalization_version"]),
                        actor_role=EvidenceActorRole(str(raw_authority["actor_role"])),
                        provenance=EvidenceProvenance(str(raw_authority["provenance"])),
                        required_privacy_class=PrivacyClass(
                            str(raw_authority["required_privacy_class"])
                        ),
                        required_information_attributes=tuple(
                            InformationAttribute(str(item))
                            for item in raw_authority["required_information_attributes"]
                        ),
                        classification_authority_ref=str(
                            raw_authority["classification_authority_ref"]
                        ),
                        issuer_ref=str(raw_authority["issuer_ref"]),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise MemoryCorruptionError("classification authority wire is invalid") from exc
                if authority.schema_version != EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION:
                    raise MemoryCorruptionError("classification authority schema differs")
                expected_authority_input: dict[str, JsonValue] = {
                    "ordinal": child_ordinal,
                    "span_hash": span.span_hash,
                    "evidence_id": span.evidence_id,
                    "authority": authority.to_json(),
                    "authority_hash": authority.authority_hash,
                }
                if authority_value != expected_authority_input:
                    raise MemoryCorruptionError("classification authority input differs")
                child_columns = (
                    str(child["classification_decision_id"]),
                    int(child["ordinal"]),
                    str(child["span_hash"]),
                    str(child["evidence_id"]),
                    int(child["authority_schema_version"]),
                    str(child["authority_id"]),
                    str(child["authority_hash"]),
                    str(child["issuer_ref"]),
                    str(child["classification_authority_ref"]),
                    str(child["required_privacy_class"]),
                    str(child["required_attributes_json"]),
                )
                expected_child_columns = (
                    decision_id,
                    child_ordinal,
                    span.span_hash,
                    span.evidence_id,
                    authority.schema_version,
                    authority.authority_id,
                    authority.authority_hash,
                    authority.issuer_ref,
                    authority.classification_authority_ref,
                    authority.required_privacy_class.value,
                    canonical_json(
                        [item.value for item in authority.required_information_attributes]
                    ),
                )
                if child_columns != expected_child_columns:
                    raise MemoryCorruptionError("classification authority columns differ")
                authority_span_binding = (
                    authority.evidence_id,
                    authority.envelope_hash,
                    authority.sanitized_hash,
                    authority.source_hash,
                    authority.source_kind,
                    authority.item_ordinal,
                    authority.item_id,
                    authority.item_json_pointer,
                    authority.normalization_version,
                    authority.actor_role,
                    authority.provenance,
                )
                span_binding = (
                    span.evidence_id,
                    span.envelope_hash,
                    span.sanitized_hash,
                    span.source_hash,
                    span.source_kind,
                    span.item_ordinal,
                    span.item_id,
                    span.item_json_pointer,
                    span.normalization_version,
                    span.actor_role,
                    span.provenance,
                )
                if authority_span_binding != span_binding:
                    raise MemoryCorruptionError("classification authority span binding differs")
                async with self._db.execute(
                    "SELECT * FROM cognitive_evidence_spans WHERE memory_id=? AND revision=? "
                    "AND ordinal=?",
                    (memory_id, memory_revision, child_ordinal),
                ) as cursor:
                    stored_span = await cursor.fetchone()
                typed = span.typed_observation
                stored_span_columns = (
                    None
                    if stored_span is None
                    else (
                        str(stored_span["span_id"]),
                        str(stored_span["evidence_id"]),
                        str(stored_span["envelope_hash"]),
                        str(stored_span["sanitized_hash"]),
                        str(stored_span["admission_receipt_id"]),
                        str(stored_span["admission_receipt_hash"]),
                        int(stored_span["evidence_item_ordinal"]),
                        str(stored_span["evidence_item_id"]),
                        str(stored_span["evidence_item_json_pointer"]),
                        int(stored_span["byte_start"]),
                        int(stored_span["byte_end"]),
                        str(stored_span["exact_quote"]),
                        str(stored_span["quote_hash"]),
                        str(stored_span["source_hash"]),
                        str(stored_span["normalization_version"]),
                        str(stored_span["actor_role"]),
                        str(stored_span["provenance"]),
                        str(stored_span["source_kind"]),
                        str(stored_span["support_kind"]),
                        stored_span["observation_schema_id"],
                        stored_span["observation_schema_version"],
                        stored_span["observation_registered_schema_hash"],
                        stored_span["observation_receipt_id"],
                        stored_span["observation_receipt_hash"],
                        stored_span["observation_authority_issuer_id"],
                        stored_span["observation_json_pointer"],
                        stored_span["observation_value_hash"],
                    )
                )
                expected_span_columns = (
                    span.span_id,
                    span.evidence_id,
                    span.envelope_hash,
                    span.sanitized_hash,
                    span.admission_receipt_id,
                    span.admission_receipt_hash,
                    span.item_ordinal,
                    span.item_id,
                    span.item_json_pointer,
                    span.start_byte,
                    span.end_byte,
                    span.exact_quote,
                    span.quote_hash,
                    span.source_hash,
                    span.normalization_version,
                    span.actor_role.value,
                    span.provenance.value,
                    span.source_kind.value,
                    span.support_kind.value,
                    None if typed is None else typed.schema_id,
                    None if typed is None else typed.schema_version,
                    None if typed is None else typed.registered_schema_hash,
                    None if typed is None else typed.observation_receipt_id,
                    None if typed is None else typed.observation_receipt_hash,
                    None if typed is None else typed.authority_issuer_id,
                    None if typed is None else typed.json_pointer,
                    None if typed is None else typed.value_hash,
                )
                if stored_span_columns != expected_span_columns:
                    raise MemoryCorruptionError("classification evidence span differs")
                authorities.append(authority)

            target_privacy: PrivacyClass | None = None
            target_attributes: tuple[InformationAttribute, ...] = ()
            if target_value is None:
                if (
                    parent["target_memory_id"] is not None
                    or parent["target_revision"] is not None
                    or parent["target_privacy_class"] is not None
                    or str(parent["target_attributes_json"]) != "[]"
                ):
                    raise MemoryCorruptionError("classification target columns differ")
            elif isinstance(target_value, dict):
                if set(target_value) != {
                    "memory_id",
                    "revision",
                    "privacy_class",
                    "information_attributes",
                }:
                    raise MemoryCorruptionError("classification target shape differs")
                try:
                    target_memory_id = str(target_value["memory_id"])
                    target_revision = int(target_value["revision"])
                    target_privacy = PrivacyClass(str(target_value["privacy_class"]))
                    target_attributes = tuple(
                        InformationAttribute(str(item))
                        for item in target_value["information_attributes"]
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise MemoryCorruptionError("classification target wire is invalid") from exc
                expected_target_columns = (
                    target_memory_id,
                    target_revision,
                    target_privacy.value,
                    canonical_json([item.value for item in target_attributes]),
                )
                actual_target_columns = (
                    str(parent["target_memory_id"]),
                    int(parent["target_revision"]),
                    str(parent["target_privacy_class"]),
                    str(parent["target_attributes_json"]),
                )
                if actual_target_columns != expected_target_columns:
                    raise MemoryCorruptionError("classification target columns differ")
                async with self._db.execute(
                    "SELECT effective_privacy_class,information_attributes_json "
                    "FROM cognitive_memory_revisions WHERE memory_id=? AND revision=?",
                    (target_memory_id, target_revision),
                ) as cursor:
                    target_row = await cursor.fetchone()
                if target_row is None or (str(target_row[0]), str(target_row[1])) != (
                    target_privacy.value,
                    expected_target_columns[3],
                ):
                    raise MemoryCorruptionError("classification target snapshot differs")
            else:
                raise MemoryCorruptionError("classification target wire is invalid")

            expected_proposal: dict[str, JsonValue] = {
                "privacy_class": operation.proposed_privacy_class.value,
                "information_attributes": [
                    item.value for item in operation.proposed_information_attributes
                ],
            }
            if proposal_value != expected_proposal or (
                str(parent["proposed_privacy_class"]),
                str(parent["proposed_attributes_json"]),
            ) != (
                operation.proposed_privacy_class.value,
                canonical_json(expected_proposal["information_attributes"]),
            ):
                raise MemoryCorruptionError("classification proposal differs")
            joined = join_information_classification(
                operation,
                trusted_privacy_floors=(
                    policy.required_privacy_class,
                    *(item.required_privacy_class for item in authorities),
                    *((target_privacy,) if target_privacy is not None else ()),
                ),
                trusted_attribute_sets=(
                    policy.required_information_attributes,
                    *(item.required_information_attributes for item in authorities),
                    target_attributes,
                ),
            )
            expected_effective: dict[str, JsonValue] = {
                "privacy_class": joined.privacy_class.value,
                "information_attributes": [item.value for item in joined.information_attributes],
            }
            effective_attributes_json = canonical_json(expected_effective["information_attributes"])
            if effective_value != expected_effective or (
                str(parent["effective_privacy_class"]),
                str(parent["effective_attributes_json"]),
            ) != (joined.privacy_class.value, effective_attributes_json):
                raise MemoryCorruptionError("classification effective join differs")
            async with self._db.execute(
                "SELECT principal_id,plan_id,plan_hash,operation_id,effective_privacy_class,"
                "information_attributes_json FROM cognitive_memory_revisions "
                "WHERE memory_id=? AND revision=?",
                (memory_id, memory_revision),
            ) as cursor:
                revision_row = await cursor.fetchone()
            if revision_row is None or tuple(str(item) for item in revision_row) != (
                plan.subject,
                plan.plan_id,
                plan.plan_hash,
                operation_id,
                joined.privacy_class.value,
                effective_attributes_json,
            ):
                raise MemoryCorruptionError("classification memory snapshot differs")

            async with self._db.execute(
                "SELECT * FROM memory_mutation_decisions WHERE receipt_id=? AND operation_id=?",
                (receipt_id, operation_id),
            ) as cursor:
                mutation_decision = await cursor.fetchone()
            if mutation_decision is None:
                raise MemoryCorruptionError("mutation decision is missing")
            try:
                mutation_json = json.loads(str(mutation_decision["decision_json"]))
            except json.JSONDecodeError as exc:
                raise MemoryCorruptionError("mutation decision JSON is invalid") from exc
            mutation_hash = hashlib.sha256(
                canonical_json(mutation_json).encode("utf-8")
            ).hexdigest()
            expected_before_ref = (
                None
                if target_value is None
                else f"{target_value['memory_id']}@{target_value['revision']}"
            )
            expected_mutation_json: dict[str, JsonValue] = {
                "schema_version": 1,
                "decision_id": str(mutation_decision["decision_id"]),
                "operation_id": operation_id,
                "outcome": "committed",
                "reason_code": operation.reason_code,
                "before_ref": expected_before_ref,
                "after_ref": f"{memory_id}@{memory_revision}",
                "classification_decision_id": decision_id,
                "classification_decision_hash": decision_hash,
                "action_authority_consumption_id": (
                    None
                    if operation_id not in action_consumptions
                    else action_consumptions[operation_id][0]
                ),
                "action_authority_consumption_hash": (
                    None
                    if operation_id not in action_consumptions
                    else action_consumptions[operation_id][1]
                ),
            }
            mutation_columns = (
                str(mutation_decision["receipt_id"]),
                str(mutation_decision["operation_id"]),
                str(mutation_decision["outcome"]),
                str(mutation_decision["reason_code"]),
                mutation_decision["before_ref"],
                str(mutation_decision["after_ref"]),
                str(mutation_decision["classification_decision_id"]),
                str(mutation_decision["classification_decision_hash"]),
                mutation_decision["action_authority_consumption_id"],
                mutation_decision["action_authority_consumption_hash"],
                str(mutation_decision["decision_hash"]),
            )
            if (
                mutation_json != expected_mutation_json
                or canonical_json(mutation_json) != str(mutation_decision["decision_json"])
                or mutation_hash != str(mutation_decision["decision_hash"])
                or mutation_columns
                != (
                    receipt_id,
                    operation_id,
                    "committed",
                    operation.reason_code,
                    expected_mutation_json["before_ref"],
                    expected_mutation_json["after_ref"],
                    decision_id,
                    decision_hash,
                    expected_mutation_json["action_authority_consumption_id"],
                    expected_mutation_json["action_authority_consumption_hash"],
                    mutation_hash,
                )
            ):
                raise MemoryCorruptionError("mutation decision duplicated data differs")
        async with self._db.execute(
            "SELECT COUNT(*) FROM memory_mutation_decisions WHERE receipt_id=?",
            (receipt_id,),
        ) as cursor:
            mutation_count_row = await cursor.fetchone()
        if mutation_count_row is None or int(mutation_count_row[0]) != len(refs):
            raise MemoryCorruptionError("mutation decision cardinality differs")
        async with self._db.execute(
            "SELECT COUNT(*) FROM cognitive_classification_decisions "
            "WHERE principal_id=? AND plan_id=? AND plan_hash=?",
            (plan.subject, plan.plan_id, plan.plan_hash),
        ) as cursor:
            classification_count_row = await cursor.fetchone()
        if classification_count_row is None or int(classification_count_row[0]) != len(refs):
            raise MemoryCorruptionError("classification decision cardinality differs")
        async with self._db.execute(
            "SELECT COUNT(*) FROM memory_action_authority_consumptions "
            "WHERE principal_id=? AND plan_id=? AND plan_hash=?",
            (plan.subject, plan.plan_id, plan.plan_hash),
        ) as cursor:
            action_count_row = await cursor.fetchone()
        if action_count_row is None or int(action_count_row[0]) != len(action_refs):
            raise MemoryCorruptionError("action authority consumption cardinality differs")
        committed_result = await self._read_mutation_apply_result_unlocked(plan)
        from simple_harness.runtime import (
            MemoryMutationApplyOutcome,
            MemoryMutationApplyReceiptRef,
            MemoryMutationApplyResult,
        )

        if type(committed_result) is not MemoryMutationApplyResult:
            raise MemoryCorruptionError("committed mutation apply result differs")
        assert committed_result is not None
        if (
            committed_result.outcome is not MemoryMutationApplyOutcome.COMMITTED
            or committed_result.receipt_ref
            != MemoryMutationApplyReceiptRef(receipt.receipt_id, receipt.receipt_hash)
        ):
            raise MemoryCorruptionError("committed mutation apply result differs")

    async def _append_mutation_rejection_audit_unlocked(
        self,
        plan: object,
        *,
        authenticated_principal_id: str,
        exc: BaseException,
        apply_result: MemoryMutationApplyResult | None = None,
    ) -> None:
        """Persist the first exact rejection for a plan after its apply rollback."""

        assert self._db is not None
        policy = self._classification_policy
        if type(exc) is MemoryIdempotencyConflict:
            reason_code = "mutation_idempotency_conflict"
        elif type(exc) is MemoryWriterConflict:
            reason_code = "mutation_writer_conflict"
        elif isinstance(exc, MemoryOwnershipConflict):
            reason_code = "mutation_scope_or_ownership_rejected"
        elif getattr(exc, "code", None) == "memory_suppressed":
            reason_code = "mutation_suppression_rejected"
        elif type(exc) is MemoryValidationError:
            reason_code = {
                "classification_policy_required": "mutation_classification_policy_missing",
                "evidence_authority_required": "mutation_evidence_authority_missing",
                "evidence_authority_rejected": "mutation_evidence_authority_rejected",
                "action_authority_required": "mutation_action_authority_required",
                "action_authority_rejected": "mutation_action_authority_rejected",
                "action_authority_replayed": "mutation_action_authority_replayed",
                "mutation_contest_exact_slot_required": "mutation_contest_rejected",
                "mutation_contest_exact_target_required": "mutation_contest_rejected",
                "mutation_contest_lifecycle_must_be_unchanged": (
                    "mutation_contest_rejected"
                ),
                "mutation_contest_requires_contested_state": (
                    "mutation_contest_rejected"
                ),
            }.get(str(exc), "mutation_epistemic_or_validation_rejected")
        else:
            if isinstance(exc, MemoryErrorBase):
                reason_code = "mutation_memory_policy_rejected"
            elif isinstance(exc, sqlite3.Error):
                reason_code = "mutation_storage_failure"
            elif isinstance(exc, (TypeError, ValueError)):
                reason_code = "mutation_input_rejected"
            else:
                reason_code = "mutation_repository_failure"
        exception_type = type(exc).__name__
        exception_fingerprint = hashlib.sha256(
            f"{exception_type}\x00{reason_code}".encode()
        ).hexdigest()
        rejection_id = _stable_id(
            "memory-mutation-rejection",
            authenticated_principal_id,
            str(getattr(plan, "idempotency_key")),
            str(getattr(plan, "plan_hash")),
        )
        rejected_at = _timestamp(self._now())
        rejection_json: dict[str, JsonValue] = {
            "schema_version": 1,
            "rejection_id": rejection_id,
            "principal_id": authenticated_principal_id,
            "proposed_subject_hash": _opaque_hash(str(getattr(plan, "subject"))),
            "plan_id": str(getattr(plan, "plan_id")),
            "plan_hash": str(getattr(plan, "plan_hash")),
            "idempotency_key": str(getattr(plan, "idempotency_key")),
            "base_revision": int(getattr(plan, "base_revision")),
            "policy_id": None if policy is None else policy.policy_id,
            "policy_hash": None if policy is None else policy.policy_hash,
            "reason_code": reason_code,
            "exception_type": exception_type,
            "exception_fingerprint": exception_fingerprint,
            "rejected_at": rejected_at,
        }
        if apply_result is not None:
            from simple_harness.runtime import MemoryMutationApplyResult

            if type(apply_result) is not MemoryMutationApplyResult:
                raise TypeError("apply_result must use MemoryMutationApplyResult")
            apply_result.validate_plan(cast(Any, plan))
            rejection_json["apply_result_id"] = apply_result.result_id
            rejection_json["apply_result_hash"] = apply_result.result_hash
        rejection_hash = hashlib.sha256(canonical_json(rejection_json).encode("utf-8")).hexdigest()
        await self._db.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            if apply_result is not None:
                await self._insert_mutation_apply_result_unlocked(
                    cast(Any, plan),
                    apply_result,
                )
            await self._db.execute(
                "INSERT INTO memory_mutation_rejection_audits("
                "rejection_id,principal_id,plan_id,plan_hash,idempotency_key,base_revision,"
                "policy_id,policy_hash,reason_code,rejection_json,rejection_hash,rejected_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(rejection_id) DO NOTHING",
                (
                    rejection_id,
                    authenticated_principal_id,
                    str(getattr(plan, "plan_id")),
                    str(getattr(plan, "plan_hash")),
                    str(getattr(plan, "idempotency_key")),
                    int(getattr(plan, "base_revision")),
                    None if policy is None else policy.policy_id,
                    None if policy is None else policy.policy_hash,
                    reason_code,
                    canonical_json(rejection_json),
                    rejection_hash,
                    rejected_at,
                ),
            )
            self._fault("mutation.rejection_audit.before_commit")
            await self._db.execute("COMMIT")
            committed = True
        finally:
            if not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")

    async def _insert_mutation_apply_result_unlocked(
        self,
        plan: MemoryMutationPlan,
        result: MemoryMutationApplyResult,
    ) -> None:
        from simple_harness.runtime import MemoryMutationApplyResult, MemoryMutationPlan

        assert self._db is not None
        if type(plan) is not MemoryMutationPlan or type(result) is not MemoryMutationApplyResult:
            raise TypeError("strict mutation plan and apply result are required")
        result.validate_plan(plan)
        result_json = canonical_json(result.to_json())
        await self._db.execute(
            "INSERT INTO memory_mutation_apply_results("
            "result_id,principal_id,plan_id,plan_hash,idempotency_key,outcome,reason_code,"
            "receipt_id,result_json,result_hash,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.result_id,
                plan.subject,
                plan.plan_id,
                plan.plan_hash,
                plan.idempotency_key,
                result.outcome.value,
                result.reason_code.value,
                None if result.receipt_ref is None else result.receipt_ref.receipt_id,
                result_json,
                result.result_hash,
                result.decided_at,
            ),
        )

    async def _read_mutation_apply_result_unlocked(
        self,
        plan: MemoryMutationPlan,
    ) -> MemoryMutationApplyResult | None:
        from simple_harness.runtime import MemoryMutationApplyResult, MemoryMutationPlan

        assert self._db is not None
        if type(plan) is not MemoryMutationPlan:
            raise TypeError("plan must use MemoryMutationPlan")
        async with self._db.execute(
            "SELECT * FROM memory_mutation_apply_results "
            "WHERE principal_id=? AND idempotency_key=? AND plan_hash=?",
            (plan.subject, plan.idempotency_key, plan.plan_hash),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row["result_json"]))
            if not isinstance(value, dict):
                raise ValueError("result wire is not an object")
            result = MemoryMutationApplyResult.from_json(value)
            result.validate_plan(plan)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("stored mutation apply result is invalid") from exc
        expected = (
            result.result_id,
            result.plan_id,
            result.plan_hash,
            result.outcome.value,
            result.reason_code.value,
            None if result.receipt_ref is None else result.receipt_ref.receipt_id,
            canonical_json(result.to_json()),
            result.result_hash,
            result.decided_at,
        )
        actual = (
            str(row["result_id"]),
            str(row["plan_id"]),
            str(row["plan_hash"]),
            str(row["outcome"]),
            str(row["reason_code"]),
            None if row["receipt_id"] is None else str(row["receipt_id"]),
            str(row["result_json"]),
            str(row["result_hash"]),
            float(row["decided_at"]),
        )
        if actual != expected:
            raise MemoryCorruptionError("stored mutation apply result columns differ")
        return result

    async def _verify_plan_evidence_refs_unlocked(self, plan: object) -> None:
        assert self._db is not None
        subject = str(getattr(plan, "subject"))
        for reference in getattr(plan, "evidence_refs"):
            async with self._db.execute(
                "SELECT principal_id,subject,envelope_hash FROM evidence_envelopes "
                "WHERE evidence_id=?",
                (reference.evidence_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise MemoryValidationError("mutation_evidence_not_admitted")
            if (str(row[0]), str(row[1])) != (subject, subject):
                from simple_harness_memory.core.errors import MemoryOwnershipConflict

                raise MemoryOwnershipConflict("mutation_evidence_not_owned")
            if str(row[2]) != reference.content_hash:
                raise MemoryValidationError("mutation_evidence_ref_hash_mismatch")

    async def _verify_mutation_span_unlocked(
        self, *, subject: str, span: Any
    ) -> tuple[tuple[str, str, str], ...]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT e.principal_id,e.subject,e.source_kind,e.source_hash,e.sanitized_hash,"
            "e.envelope_hash,i.content_hash,r.admission_receipt_id,"
            "r.admission_receipt_hash FROM evidence_envelopes e "
            "JOIN evidence_items i ON i.evidence_id=e.evidence_id AND i.ordinal=? "
            "JOIN ingestion_receipts r ON r.evidence_id=e.evidence_id "
            "WHERE e.evidence_id=?",
            (getattr(span, "item_ordinal"), getattr(span, "evidence_id")),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise MemoryValidationError("mutation_evidence_span_not_admitted")
        if (str(row[0]), str(row[1])) != (subject, subject):
            from simple_harness_memory.core.errors import MemoryOwnershipConflict

            raise MemoryOwnershipConflict("mutation_evidence_span_not_owned")
        exact = (
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[7]),
            str(row[8]),
        )
        proposed = (
            getattr(span, "source_kind").value,
            getattr(span, "source_hash"),
            getattr(span, "sanitized_hash"),
            getattr(span, "envelope_hash"),
            getattr(span, "admission_receipt_id"),
            getattr(span, "admission_receipt_hash"),
        )
        if exact != proposed:
            raise MemoryValidationError("mutation_evidence_span_db_binding_mismatch")
        if not str(row[6]):
            raise MemoryCorruptionError("admitted evidence item hash is missing")
        async with self._db.execute(
            "SELECT task_scope_id,evidence_id,registration_id "
            "FROM conversation_evidence_registrations WHERE principal_id=? "
            "AND evidence_id=? AND task_scope_id IS NOT NULL ORDER BY registration_id",
            (subject, getattr(span, "evidence_id")),
        ) as cursor:
            origins = await cursor.fetchall()
        return tuple((str(row[0]), str(row[1]), str(row[2])) for row in origins)

    @staticmethod
    def _mutation_entity_ids(payload: object | None) -> tuple[str, ...]:
        if payload is None:
            return ()
        subject_entity = getattr(payload, "subject_entity", None)
        if isinstance(subject_entity, str):
            return (subject_entity,)
        participants = getattr(payload, "participants", ())
        if isinstance(participants, tuple) and all(isinstance(item, str) for item in participants):
            return tuple(dict.fromkeys(participants))
        return ()

    @staticmethod
    def _mutation_entity_ids_from_content_json(
        content_json: str | None,
    ) -> tuple[str, ...]:
        if content_json is None:
            return ()
        try:
            payload = json.loads(content_json)
        except (TypeError, ValueError) as exc:
            raise MemoryCorruptionError("cognitive target content is invalid") from exc
        if not isinstance(payload, dict):
            raise MemoryCorruptionError("cognitive target content is invalid")
        subject_entity = payload.get("subject_entity")
        if isinstance(subject_entity, str) and subject_entity:
            return (subject_entity,)
        participants = payload.get("participants", [])
        if isinstance(participants, list) and all(
            isinstance(item, str) and item for item in participants
        ):
            return tuple(dict.fromkeys(participants))
        return ()

    async def _insert_cognitive_payload_unlocked(
        self, memory_id: str, revision: int, payload: object
    ) -> None:
        from simple_harness.runtime import (
            EpisodeMemoryPayload,
            ProcedureMemoryPayload,
            ProspectiveEventTrigger,
            ProspectiveMemoryPayload,
            ProspectiveTimeTrigger,
            SemanticMemoryPayload,
        )

        assert self._db is not None
        if isinstance(payload, EpisodeMemoryPayload):
            await self._db.execute(
                "INSERT INTO episode_records(memory_id,revision,title,thread_ref,"
                "participants_json,goals_json,actions_json,results_json,impacts_json,"
                "occurred_start,occurred_end) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    payload.title,
                    payload.thread_ref,
                    canonical_json(list(payload.participants)),
                    canonical_json(list(payload.goals)),
                    canonical_json(list(payload.actions)),
                    canonical_json(list(payload.results)),
                    canonical_json(list(payload.impacts)),
                    payload.occurred_start,
                    payload.occurred_end,
                ),
            )
        elif isinstance(payload, SemanticMemoryPayload):
            value_json = canonical_json(payload.to_json()["object_value"])
            await self._db.execute(
                "INSERT INTO semantic_claims(memory_id,revision,subject_entity,predicate,"
                "object_json,object_hash,qualifiers_json) VALUES(?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    payload.subject_entity,
                    payload.predicate,
                    value_json,
                    payload.object_value_hash,
                    canonical_json(list(payload.qualifiers)),
                ),
            )
        elif isinstance(payload, ProcedureMemoryPayload):
            applicability_json = canonical_json(list(payload.applicability))
            await self._db.execute(
                "INSERT INTO procedure_records(memory_id,revision,name,applicability_json,"
                "steps_json,risk_level,applicability_fingerprint) VALUES(?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    payload.name,
                    applicability_json,
                    canonical_json(list(payload.steps)),
                    payload.proposed_risk_level.value,
                    hashlib.sha256(applicability_json.encode("utf-8")).hexdigest(),
                ),
            )
        elif isinstance(payload, ProspectiveMemoryPayload):
            trigger = payload.trigger
            if isinstance(trigger, ProspectiveTimeTrigger):
                trigger_kind = "time"
                due_at = trigger.trigger_at
            elif isinstance(trigger, ProspectiveEventTrigger):
                trigger_kind = "event"
                due_at = None
            else:  # pragma: no cover - exact Harness DTO prevents this
                raise MemoryValidationError("prospective_trigger_invalid")
            await self._db.execute(
                "INSERT INTO prospective_records(memory_id,revision,action_text,trigger_kind,"
                "trigger_json,scheduler_registration_ref,due_at) VALUES(?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    payload.action,
                    trigger_kind,
                    canonical_json(trigger.to_json()),
                    None,
                    due_at,
                ),
            )
        else:
            raise MemoryValidationError("cognitive_payload_type_invalid")

    async def _copy_cognitive_payload_unlocked(
        self,
        memory_type: str,
        source_memory_id: str,
        source_revision: int,
        memory_id: str,
        revision: int,
    ) -> None:
        assert self._db is not None
        table_columns = {
            "episode": (
                "episode_records",
                "title,thread_ref,participants_json,goals_json,actions_json,results_json,"
                "impacts_json,occurred_start,occurred_end",
            ),
            "semantic": (
                "semantic_claims",
                "subject_entity,predicate,object_json,object_hash,qualifiers_json",
            ),
            "procedure": (
                "procedure_records",
                "name,applicability_json,steps_json,risk_level,applicability_fingerprint,"
                "success_evidence_count,failure_evidence_count",
            ),
            "prospective": (
                "prospective_records",
                "action_text,trigger_kind,trigger_json,scheduler_registration_ref,due_at",
            ),
        }
        try:
            table, columns = table_columns[memory_type]
        except KeyError as exc:
            raise MemoryCorruptionError("cognitive memory type is invalid") from exc
        result = await self._db.execute(
            f"INSERT INTO {table}(memory_id,revision,{columns}) "
            f"SELECT ?,?,{columns} FROM {table} WHERE memory_id=? AND revision=?",
            (memory_id, revision, source_memory_id, source_revision),
        )
        if result.rowcount != 1:
            raise MemoryCorruptionError("cognitive typed payload is missing")

    async def _insert_cognitive_evidence_unlocked(
        self, memory_id: str, revision: int, spans: tuple[Any, ...]
    ) -> None:
        assert self._db is not None
        for ordinal, span in enumerate(spans, start=1):
            observation = getattr(span, "typed_observation")
            observation_values = (
                (None,) * 8
                if observation is None
                else (
                    observation.schema_id,
                    observation.schema_version,
                    observation.registered_schema_hash,
                    observation.observation_receipt_id,
                    observation.observation_receipt_hash,
                    observation.authority_issuer_id,
                    observation.json_pointer,
                    observation.value_hash,
                )
            )
            await self._db.execute(
                "INSERT INTO cognitive_evidence_spans(memory_id,revision,ordinal,span_id,"
                "evidence_id,envelope_hash,sanitized_hash,admission_receipt_id,"
                "admission_receipt_hash,evidence_item_ordinal,evidence_item_id,"
                "evidence_item_json_pointer,byte_start,byte_end,exact_quote,quote_hash,"
                "source_hash,normalization_version,actor_role,provenance,source_kind,"
                "support_kind,observation_schema_id,observation_schema_version,"
                "observation_registered_schema_hash,observation_receipt_id,"
                "observation_receipt_hash,observation_authority_issuer_id,"
                "observation_json_pointer,observation_value_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    ordinal,
                    span.span_id,
                    span.evidence_id,
                    span.envelope_hash,
                    span.sanitized_hash,
                    span.admission_receipt_id,
                    span.admission_receipt_hash,
                    span.item_ordinal,
                    span.item_id,
                    span.item_json_pointer,
                    span.start_byte,
                    span.end_byte,
                    span.exact_quote,
                    span.quote_hash,
                    span.source_hash,
                    span.normalization_version,
                    span.actor_role.value,
                    span.provenance.value,
                    span.source_kind.value,
                    span.support_kind.value,
                    *observation_values,
                ),
            )

    async def _read_suppression_by_request(self, request_id: str) -> SuppressionDecision | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM suppression_directives WHERE request_id=?", (request_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _suppression_decision_from_row(row)

    async def _read_suppression_decision(self, directive_id: str) -> SuppressionDecision | None:
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
                            str(evidence_row["envelope_hash"]),
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
            if delivery_receipt.receipt_hash != str(
                batch["delivery_receipt_hash"]
            ) or envelope.envelope_hash != str(batch["result_envelope_hash"]):
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
        if not members or str(batch["evidence_watermark"]) != str(members[-1]["evidence_id"]):
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

    def register_analysis_delivery_authority(
        self, authority: MemoryAnalysisDeliveryAuthorityPort
    ) -> _AnalysisDeliveryAuthorityRegistration:
        """Return a capability only for the constructor-bound Host authority."""

        from simple_harness_memory.core.jobs import (
            _AnalysisDeliveryAuthorityRegistration,
        )

        verify = getattr(authority, "verify_analysis_delivery", None)
        if not callable(verify):
            raise TypeError("authority must implement MemoryAnalysisDeliveryAuthorityPort")
        with self._authority_registration_lock:
            if self._analysis_delivery_authority is None:
                raise MemoryValidationError("analysis_delivery_authority_not_bound")
            if authority is not self._analysis_delivery_authority:
                raise MemoryValidationError("analysis_delivery_authority_identity_differs")
            registration = self._analysis_delivery_authority_registration
            if type(registration) is not _AnalysisDeliveryAuthorityRegistration:
                raise MemoryCorruptionError("analysis delivery authority registration is invalid")
            return registration

    async def admit_analysis_delivery(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        registration: _AnalysisDeliveryAuthorityRegistration,
    ) -> _AnalysisDeliveryAdmission:
        """Verify Host durable authority outside SQLite and issue an identity capability."""

        from simple_harness.runtime import MemoryAnalysisResultEnvelope

        from simple_harness_memory.core.audit import freeze_public_audit_object
        from simple_harness_memory.core.jobs import (
            AnalysisBatchClaim,
            _AnalysisDeliveryAdmission,
            _AnalysisDeliveryAuthorityRegistration,
        )

        if (
            type(claim) is not AnalysisBatchClaim
            or type(envelope) is not MemoryAnalysisResultEnvelope
        ):
            raise TypeError("claim and envelope must use analysis protocol types")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        if self._db.in_transaction:
            raise MemoryWriterConflict("analysis_authority_called_inside_transaction")
        if (
            self._analysis_delivery_authority is None
            or registration is not self._analysis_delivery_authority_registration
            or type(registration) is not _AnalysisDeliveryAuthorityRegistration
        ):
            raise MemoryValidationError("analysis_delivery_authority_registration_invalid")
        envelope.verify_request(claim.request)
        await self._analysis_delivery_authority.verify_analysis_delivery(claim.request, envelope)
        if self._db.in_transaction:
            raise MemoryWriterConflict("analysis_authority_opened_memory_transaction")
        freeze_public_audit_object({"delivery_receipt": envelope.delivery_receipt.to_json()})
        async with self._write_lock:
            async with self._db.execute(
                "SELECT * FROM analysis_batches WHERE batch_id=?", (claim.batch_id,)
            ) as cursor:
                batch = await cursor.fetchone()
            purpose = "generic_audit"
            application_receipt_hash: str | None = None
            application_decisions_hash: str | None = None
            if batch is not None:
                batch_phase = str(batch["state"])
                if batch_phase == "handed_off":
                    purpose = "commit"
                elif batch_phase == "result_committed":
                    purpose = "commit_replay"
                elif batch_phase == "audit_pending":
                    application = await self._application_from_batch_unlocked(
                        batch, claim.request, envelope.result
                    )
                    purpose = "audit"
                    application_receipt_hash = application.receipt.receipt_hash
                    application_decisions_hash = _analysis_decisions_hash(
                        cast(tuple[object, ...], application.decisions)
                    )
                elif batch_phase == "applied":
                    purpose = "applied_replay"
                else:
                    raise MemoryValidationError("analysis_delivery_batch_phase_invalid")
        admission = _AnalysisDeliveryAdmission()
        state = _DeliveryAdmissionState(
            admission,
            self._analysis_delivery_authority,
            claim.batch_id,
            claim.lease_token,
            claim.request.request_hash,
            envelope.envelope_hash,
            envelope.result.result_hash,
            envelope.delivery_receipt.receipt_hash,
            purpose,
            application_receipt_hash,
            application_decisions_hash,
        )
        async with self._admission_lock:
            self._delivery_admissions[id(admission)] = state
        return admission

    async def discard_analysis_delivery_admission(
        self, admission: _AnalysisDeliveryAdmission
    ) -> None:
        async with self._admission_lock:
            state = self._delivery_admissions.get(id(admission))
            if state is not None and state.admission is admission:
                self._delivery_admissions.pop(id(admission), None)

    async def admit_analysis_application(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        application: AnalysisApplication,
    ) -> _AnalysisDeliveryAdmission:
        """Issue the audit phase capability from the already verified durable result."""

        from simple_harness.runtime import MemoryAnalysisResultEnvelope

        from simple_harness_memory.core.jobs import (
            AnalysisApplication,
            AnalysisBatchClaim,
            _AnalysisDeliveryAdmission,
        )

        if (
            type(claim) is not AnalysisBatchClaim
            or type(envelope) is not MemoryAnalysisResultEnvelope
            or type(application) is not AnalysisApplication
        ):
            raise TypeError("claim, envelope, and application must use analysis types")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v5 backend is not initialized")
        async with self._write_lock:
            now = _timestamp(self._now())
            if not await self._analysis_claim_is_current_unlocked(claim, now):
                raise MemoryWriterConflict("analysis_audit_claim_not_current")
            async with self._db.execute(
                "SELECT * FROM analysis_batches WHERE batch_id=?", (claim.batch_id,)
            ) as cursor:
                batch = await cursor.fetchone()
            if batch is None or str(batch["state"]) != "audit_pending":
                raise MemoryWriterConflict("analysis_audit_phase_invalid")
            if (
                envelope.result.result_hash != str(batch["result_hash"])
                or envelope.envelope_hash != str(batch["result_envelope_hash"])
                or envelope.delivery_receipt.receipt_hash != str(batch["delivery_receipt_hash"])
            ):
                raise MemoryValidationError("analysis_audit_durable_lineage_differs")
            canonical_application = await self._application_from_batch_unlocked(
                batch, claim.request, envelope.result
            )
            if canonical_application != application:
                raise MemoryValidationError("analysis_application_differs")
        admission = _AnalysisDeliveryAdmission()
        state = _DeliveryAdmissionState(
            admission,
            self._analysis_delivery_authority,
            claim.batch_id,
            claim.lease_token,
            claim.request.request_hash,
            envelope.envelope_hash,
            envelope.result.result_hash,
            envelope.delivery_receipt.receipt_hash,
            "audit",
            canonical_application.receipt.receipt_hash,
            _analysis_decisions_hash(cast(tuple[object, ...], canonical_application.decisions)),
        )
        async with self._admission_lock:
            self._delivery_admissions[id(admission)] = state
        return admission

    async def _consume_analysis_delivery_admission(
        self,
        admission: object,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope | None,
        *,
        purpose: str,
        result_hash: str | None = None,
        delivery_receipt_hash: str | None = None,
        application_receipt_hash: str | None = None,
        application_decisions_hash: str | None = None,
    ) -> None:
        async with self._admission_lock:
            state = self._delivery_admissions.get(id(admission))
            if (
                state is None
                or state.admission is not admission
                or state.batch_id != claim.batch_id
                or state.lease_token != claim.lease_token
                or state.request_hash != claim.request.request_hash
                or (envelope is not None and state.envelope_hash != envelope.envelope_hash)
                or (result_hash is not None and state.result_hash != result_hash)
                or (
                    delivery_receipt_hash is not None
                    and state.delivery_receipt_hash != delivery_receipt_hash
                )
                or (
                    application_receipt_hash is not None
                    and state.application_receipt_hash != application_receipt_hash
                )
                or (
                    application_decisions_hash is not None
                    and state.application_decisions_hash != application_decisions_hash
                )
            ):
                raise MemoryValidationError("analysis_delivery_admission_invalid")
            allowed = {
                "commit": {"commit", "commit_replay"},
                "reject": {"commit", "commit_replay"},
                "audit": {"audit"},
                "generic_audit": {"generic_audit"},
                "applied_replay": {"applied_replay"},
            }
            if purpose not in allowed or state.purpose not in allowed[purpose]:
                raise MemoryValidationError("analysis_delivery_admission_phase_differs")
            if not state.available:
                raise MemoryValidationError("analysis_delivery_admission_replayed")
            state.available = False

    async def commit_analysis_result(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        admission: _AnalysisDeliveryAdmission,
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
        freeze_public_audit_object({"delivery_receipt": envelope.delivery_receipt.to_json()})
        await self._consume_analysis_delivery_admission(
            admission, claim, envelope, purpose="commit"
        )
        self._fault("job.result.after_capability_consume")
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
                    return AnalysisResultCommit(AnalysisResultCommitOutcome.STALE_LEASE, None)
                async with self._db.execute(
                    "SELECT result_json,result_hash,delivery_receipt_json,"
                    "delivery_receipt_hash,result_envelope_hash,state FROM analysis_batches "
                    "WHERE batch_id=?",
                    (claim.batch_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise MemoryCorruptionError("analysis batch disappeared")
                if row["result_json"] is not None:
                    if str(row["state"]) not in {
                        "result_committed",
                        "audit_pending",
                        "applied",
                    }:
                        raise MemoryWriterConflict("analysis_result_phase_invalid")
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
                    canonical_envelope = MemoryAnalysisResultEnvelope(canonical, canonical_delivery)
                    if canonical_delivery.receipt_hash != str(
                        row["delivery_receipt_hash"]
                    ) or canonical_envelope.envelope_hash != str(row["result_envelope_hash"]):
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
                if str(row["state"]) != "handed_off":
                    raise MemoryWriterConflict("analysis_result_phase_invalid")
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
        admission: _AnalysisDeliveryAdmission | None = None,
        retry_config: MemoryJobWorkerConfig | None = None,
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
            MemoryJobWorkerConfig,
            RejectedAnalysisAudit,
            WorkerRunOutcome,
        )
        from simple_harness_memory.core.suppression import SuppressionScopeKind

        if type(claim) is not AnalysisBatchClaim or type(audit) is not RejectedAnalysisAudit:
            raise TypeError("claim and audit must use analysis job protocol types")
        _audit_identifier(reason_code, "reason_code")
        _audit_identifier(validator_version, "validator_version")
        if retry_config is not None and type(retry_config) is not MemoryJobWorkerConfig:
            raise TypeError("retry_config must use MemoryJobWorkerConfig")
        if audit.delivery_receipt is not None:
            delivery = audit.delivery_receipt
            if (
                delivery.job_id != claim.request.job_id
                or delivery.run_id != claim.request.run_id
                or delivery.request_hash != claim.request.request_hash
                or delivery.attempt != claim.request.attempt
            ):
                raise MemoryValidationError("rejected_analysis_delivery_lineage_differs")
            if admission is None:
                raise MemoryValidationError("analysis_delivery_admission_required")
        elif admission is not None:
            raise MemoryValidationError("analysis_delivery_admission_without_receipt")
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
                async with self._db.execute(
                    "SELECT state,result_json,application_receipt_json "
                    "FROM analysis_batches WHERE batch_id=?",
                    (claim.batch_id,),
                ) as cursor:
                    batch_phase = await cursor.fetchone()
                if (
                    batch_phase is None
                    or str(batch_phase["state"]) != "handed_off"
                    or batch_phase["result_json"] is not None
                    or batch_phase["application_receipt_json"] is not None
                ):
                    raise MemoryWriterConflict("analysis_rejection_phase_invalid")
                if audit.delivery_receipt is not None:
                    assert admission is not None
                    await self._consume_analysis_delivery_admission(
                        admission,
                        claim,
                        None,
                        purpose="reject",
                        result_hash=audit.result_hash,
                        delivery_receipt_hash=audit.delivery_receipt.receipt_hash,
                    )
                authority_retry_ordinal = 0
                if retry_config is not None:
                    async with self._db.execute(
                        "SELECT COUNT(*) FROM job_attempt_events WHERE batch_id=? "
                        "AND job_id=? AND event_kind='authority_retry_scheduled'",
                        (claim.batch_id, claim.job_ids[0]),
                    ) as cursor:
                        retry_row = await cursor.fetchone()
                    if retry_row is None:
                        raise MemoryCorruptionError(
                            "analysis authority retry audit count is unavailable"
                        )
                    authority_retry_ordinal = int(retry_row[0]) + 1
                    if authority_retry_ordinal < retry_config.max_attempts:
                        retry_at = (
                            now + retry_config.retry_delays_seconds[authority_retry_ordinal - 1]
                        )
                        await self._db.execute(
                            "UPDATE jobs SET state='claimed',lease_owner=NULL,"
                            "lease_token=?,lease_expires_at=?,last_error_code=?,"
                            "next_attempt_at=?,updated_at=? WHERE job_id IN "
                            "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?)",
                            (
                                claim.lease_token,
                                retry_at,
                                reason_code,
                                retry_at,
                                now,
                                claim.batch_id,
                            ),
                        )
                        await self._append_batch_events_unlocked(
                            claim.batch_id,
                            "authority_retry_scheduled",
                            reason_code,
                            now,
                            audit.result_hash,
                        )
                        self._fault("job.fail.before_commit")
                        await self._db.execute("COMMIT")
                        committed = True
                        self._fault("job.fail.after_commit")
                        return WorkerRunOutcome.RETRY_SCHEDULED
                receipt = MemoryAnalysisReceipt(
                    _stable_id(
                        "analysis-rejected-receipt",
                        claim.batch_id,
                        claim.request.request_hash,
                        audit.result_hash,
                        reason_code,
                        str(authority_retry_ordinal),
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
                    reason_code,
                    str(authority_retry_ordinal),
                )
                decision = DecisionLedgerEntry(
                    _stable_id(
                        "analysis-rejected-decision",
                        claim.batch_id,
                        reason_code,
                        str(authority_retry_ordinal),
                    ),
                    _stable_id(
                        "analysis-rejected-operation",
                        claim.batch_id,
                        reason_code,
                        str(authority_retry_ordinal),
                    ),
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
                    if existing.invocation_hash != record.invocation_hash or stored_decisions != (
                        decision,
                    ):
                        raise MemoryIdempotencyConflict(
                            "rejected_analysis_invocation_replay_conflict"
                        )
                all_dead = (
                    retry_config is None or authority_retry_ordinal >= retry_config.max_attempts
                )
                async with self._db.execute(
                    "SELECT job_id FROM jobs WHERE job_id IN "
                    "(SELECT job_id FROM analysis_batch_members WHERE batch_id=?)",
                    (claim.batch_id,),
                ) as cursor:
                    failure_rows = await cursor.fetchall()
                for row in failure_rows:
                    if all_dead or retry_config is None:
                        retry_at = now
                    else:
                        retry_at = (
                            now + retry_config.retry_delays_seconds[authority_retry_ordinal - 1]
                        )
                    await self._db.execute(
                        "UPDATE jobs SET state=?,lease_owner=NULL,lease_token=NULL,"
                        "lease_expires_at=NULL,last_error_code=?,next_attempt_at=?,updated_at=? "
                        "WHERE job_id=?",
                        (
                            "dead_letter" if all_dead else "claimed",
                            reason_code,
                            retry_at,
                            now,
                            row["job_id"],
                        ),
                    )
                    if not all_dead:
                        await self._db.execute(
                            "UPDATE jobs SET lease_token=?,lease_expires_at=? WHERE job_id=?",
                            (claim.lease_token, retry_at, row["job_id"]),
                        )
                    else:
                        await self._db.execute(
                            "UPDATE outbox SET state='dead_letter',updated_at=? WHERE "
                            "idempotency_key=(SELECT idempotency_key FROM jobs WHERE job_id=?)",
                            (now, row["job_id"]),
                        )
                if all_dead:
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
                    "dead_letter" if all_dead else "authority_retry_scheduled",
                    reason_code,
                    now,
                    audit.result_hash,
                )
                self._fault("job.fail.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._fault("job.fail.after_commit")
                return (
                    WorkerRunOutcome.DEAD_LETTER if all_dead else WorkerRunOutcome.RETRY_SCHEDULED
                )
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
                    WorkerRunOutcome.DEAD_LETTER if all_dead else WorkerRunOutcome.RETRY_SCHEDULED
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
                    if str(batch["state"]) not in {"audit_pending", "applied"}:
                        raise MemoryWriterConflict("analysis_application_phase_invalid")
                    application = await self._application_from_batch_unlocked(
                        batch, claim.request, result
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return application
                if str(batch["state"]) != "result_committed":
                    raise MemoryWriterConflict("analysis_application_phase_invalid")

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
                    no_mutation or (plan is not None and plan.base_revision == base_revision)
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
                    (EvidenceReasonCode.VALIDATOR_ACCEPTED,)
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
            ExistingMemoryTarget,
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
                target_memory_id = (
                    operation.target.memory_id
                    if isinstance(operation.target, ExistingMemoryTarget)
                    else None
                )
                target_ref = target_memory_id or _stable_id(
                    "proposed-memory", plan.plan_id, operation.operation_id
                )
                operation_evidence_ids = {span.evidence_id for span in operation.evidence_spans}
                operation_evidence_refs = tuple(
                    reference
                    for reference in plan.evidence_refs
                    if reference.evidence_id in operation_evidence_ids
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
                        () if target_memory_id is None else (target_memory_id,),
                        (f"analysis-plan:{plan.plan_hash}:revision:{receipt.committed_revision}",),
                        operation_evidence_refs,
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
        from simple_harness.runtime import MemoryAnalysisResult

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
                    "SELECT * FROM analysis_batches WHERE batch_id=?",
                    (claim.batch_id,),
                ) as cursor:
                    batch = await cursor.fetchone()
                if batch is None:
                    raise MemoryCorruptionError("analysis batch disappeared")
                if str(batch["state"]) not in {"audit_pending", "applied"}:
                    raise MemoryWriterConflict("analysis_finalize_phase_invalid")
                result_value = json.loads(str(batch["result_json"]))
                if not isinstance(result_value, dict):
                    raise MemoryCorruptionError("analysis durable result malformed")
                canonical_result = MemoryAnalysisResult.from_json(result_value)
                canonical_application = await self._application_from_batch_unlocked(
                    batch, claim.request, canonical_result
                )
                if canonical_application != application:
                    raise MemoryIdempotencyConflict("analysis_application_differs")
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
                    "SELECT validation_receipt_hash FROM llm_invocations WHERE invocation_id=?",
                    (application.invocation_id,),
                ) as cursor:
                    invocation = await cursor.fetchone()
                if (
                    invocation is None
                    or str(invocation["validation_receipt_hash"])
                    != application.receipt.receipt_hash
                ):
                    raise MemoryWriterConflict("analysis_audit_not_durable")
                stored_decisions = await self._read_decisions(application.invocation_id)
                if stored_decisions != canonical_application.decisions:
                    raise MemoryWriterConflict("analysis_audit_decisions_differ")
                async with self._db.execute(
                    "SELECT COUNT(*) AS event_count,"
                    "COUNT(DISTINCT job_id) AS job_count FROM job_attempt_events "
                    "WHERE batch_id=? AND event_kind='mutation_audit_committed' "
                    "AND reason_code='analysis_mutation_audit_committed' "
                    "AND result_hash=?",
                    (claim.batch_id, canonical_result.result_hash),
                ) as cursor:
                    audit_link = await cursor.fetchone()
                if (
                    audit_link is None
                    or int(audit_link["event_count"]) != len(claim.job_ids)
                    or int(audit_link["job_count"]) != len(claim.job_ids)
                ):
                    raise MemoryWriterConflict("analysis_mutation_audit_authority_missing")
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
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        admission: _AnalysisDeliveryAdmission,
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
        """Record only the exact repository-staged mutation application."""

        return await self._record_analysis_invocation(
            claim,
            envelope,
            admission,
            invocation_id,
            turn_id,
            request,
            result,
            delivery_receipt,
            validation_receipt,
            decisions,
            reasoning_refs=reasoning_refs,
            require_durable_application=True,
        )

    async def record_llm_invocation(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        admission: _AnalysisDeliveryAdmission,
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
        """Record generic invocation evidence without granting mutation authority."""

        return await self._record_analysis_invocation(
            claim,
            envelope,
            admission,
            invocation_id,
            turn_id,
            request,
            result,
            delivery_receipt,
            validation_receipt,
            decisions,
            reasoning_refs=reasoning_refs,
            require_durable_application=False,
        )

    async def _record_analysis_invocation(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        admission: _AnalysisDeliveryAdmission,
        invocation_id: str,
        turn_id: str,
        request: MemoryAnalysisRequest,
        result: MemoryAnalysisResult,
        delivery_receipt: MemoryAnalysisDeliveryReceipt,
        validation_receipt: MemoryAnalysisReceipt,
        decisions: tuple[DecisionLedgerEntry, ...],
        *,
        reasoning_refs: tuple[PublicReasoningReference, ...],
        require_durable_application: bool,
    ) -> LLMInvocationAuditRecord:
        """Append one public-only Host analysis invocation and its decisions atomically."""

        from simple_harness.runtime import (
            AnalysisValidationStatus,
            MemoryAnalysisDeliveryReceipt,
            MemoryAnalysisReceipt,
            MemoryAnalysisRequest,
            MemoryAnalysisResult,
            MemoryAnalysisResultEnvelope,
        )

        from simple_harness_memory.core.audit import (
            DecisionLedgerEntry,
            DecisionOutcome,
            LLMInvocationAuditRecord,
            OutputStorageStatus,
            PublicReasoningReference,
            freeze_public_audit_object,
        )
        from simple_harness_memory.core.jobs import AnalysisBatchClaim

        if (
            type(claim) is not AnalysisBatchClaim
            or type(envelope) is not MemoryAnalysisResultEnvelope
        ):
            raise TypeError("claim and envelope must use analysis protocol types")
        if type(request) is not MemoryAnalysisRequest:
            raise TypeError("request must use MemoryAnalysisRequest")
        if type(result) is not MemoryAnalysisResult:
            raise TypeError("result must use MemoryAnalysisResult")
        if type(delivery_receipt) is not MemoryAnalysisDeliveryReceipt:
            raise TypeError("delivery_receipt must use MemoryAnalysisDeliveryReceipt")
        if type(validation_receipt) is not MemoryAnalysisReceipt:
            raise TypeError("validation_receipt must use MemoryAnalysisReceipt")
        if envelope.result != result or envelope.delivery_receipt != delivery_receipt:
            raise MemoryValidationError("analysis_envelope_audit_lineage_differs")
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
            if decision.target_kind.value == "subject" and decision.target_ref != request.subject:
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
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                admission_purpose = "generic_audit"
                application_receipt_hash: str | None = None
                application_decisions_hash: str | None = None
                if require_durable_application:
                    now = _timestamp(self._now())
                    if not await self._analysis_claim_is_current_unlocked(claim, now):
                        raise MemoryWriterConflict("analysis_audit_claim_not_current")
                    async with self._db.execute(
                        "SELECT * FROM analysis_batches WHERE batch_id=?",
                        (claim.batch_id,),
                    ) as cursor:
                        batch = await cursor.fetchone()
                    if batch is None:
                        raise MemoryWriterConflict("analysis_audit_batch_missing")
                    if str(batch["state"]) != "audit_pending":
                        raise MemoryWriterConflict("analysis_audit_phase_invalid")
                    request_value = json.loads(str(batch["request_json"]))
                    result_value = json.loads(str(batch["result_json"]))
                    if not isinstance(request_value, dict) or not isinstance(result_value, dict):
                        raise MemoryCorruptionError("analysis durable authority malformed")
                    canonical_request = MemoryAnalysisRequest.from_json(request_value)
                    canonical_result = MemoryAnalysisResult.from_json(result_value)
                    if (
                        canonical_request != claim.request
                        or canonical_request != request
                        or canonical_request.request_hash != str(batch["request_hash"])
                        or canonical_result != result
                        or canonical_result.result_hash != str(batch["result_hash"])
                        or envelope.envelope_hash != str(batch["result_envelope_hash"])
                        or delivery_receipt.receipt_hash != str(batch["delivery_receipt_hash"])
                    ):
                        raise MemoryValidationError("analysis_audit_durable_lineage_differs")
                    canonical_application = await self._application_from_batch_unlocked(
                        batch, canonical_request, canonical_result
                    )
                    if (
                        canonical_application.invocation_id != invocation_id
                        or canonical_application.turn_id != turn_id
                        or canonical_application.receipt != validation_receipt
                        or canonical_application.decisions != decisions
                        or canonical_application.reasoning_refs != reasoning_refs
                    ):
                        raise MemoryValidationError("analysis_application_differs")
                    admission_purpose = "audit"
                    application_receipt_hash = canonical_application.receipt.receipt_hash
                    application_decisions_hash = _analysis_decisions_hash(
                        cast(tuple[object, ...], canonical_application.decisions)
                    )
                else:
                    async with self._db.execute(
                        "SELECT batch_id FROM analysis_batches WHERE request_hash=? OR batch_id=?",
                        (request.request_hash, request.job_id),
                    ) as cursor:
                        if await cursor.fetchone() is not None:
                            raise MemoryValidationError("generic_audit_mutation_lineage_forbidden")
                await self._consume_analysis_delivery_admission(
                    admission,
                    claim,
                    envelope,
                    purpose=admission_purpose,
                    application_receipt_hash=application_receipt_hash,
                    application_decisions_hash=application_decisions_hash,
                )
                self._fault("job.audit.after_capability_consume")
                for evidence_ref in request.ordered_evidence_refs:
                    async with self._db.execute(
                        "SELECT subject,envelope_hash FROM evidence_envelopes WHERE evidence_id=?",
                        (evidence_ref.evidence_id,),
                    ) as cursor:
                        evidence_row = await cursor.fetchone()
                    if (
                        evidence_row is None
                        or str(evidence_row["subject"]) != request.subject
                        or str(evidence_row["envelope_hash"]) != evidence_ref.content_hash
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
                    if require_durable_application:
                        async with self._db.execute(
                            "SELECT COUNT(*) AS event_count,"
                            "COUNT(DISTINCT job_id) AS job_count "
                            "FROM job_attempt_events WHERE batch_id=? "
                            "AND event_kind='mutation_audit_committed' "
                            "AND reason_code='analysis_mutation_audit_committed' "
                            "AND result_hash=?",
                            (claim.batch_id, result.result_hash),
                        ) as cursor:
                            audit_link = await cursor.fetchone()
                        if (
                            audit_link is None
                            or int(audit_link["event_count"]) != len(claim.job_ids)
                            or int(audit_link["job_count"]) != len(claim.job_ids)
                        ):
                            raise MemoryWriterConflict("analysis_mutation_audit_authority_missing")
                    self._fault("job.audit.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("job.audit.after_commit")
                    stored = existing
                else:
                    async with self._db.execute(
                        "SELECT invocation_id FROM llm_invocations WHERE principal_id=? "
                        "AND request_hash=?",
                        (request.subject, request.request_hash),
                    ) as cursor:
                        if await cursor.fetchone() is not None:
                            raise MemoryIdempotencyConflict("analysis_request_replay_conflict")
                    await self._append_invocation_unlocked(
                        expected, decisions, manage_transaction=False
                    )
                    candidate = await self._read_invocation(invocation_id)
                    if candidate is None or candidate.invocation_hash != expected.invocation_hash:
                        raise MemoryCorruptionError("stored analysis invocation differs")
                    stored = candidate
                    if require_durable_application:
                        await self._append_batch_events_unlocked(
                            claim.batch_id,
                            "mutation_audit_committed",
                            "analysis_mutation_audit_committed",
                            _timestamp(self._now()),
                            result.result_hash,
                        )
                    self._fault("job.audit.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("job.audit.after_commit")
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
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
        input_refs_json = canonical_json([item.to_json() for item in record.public_input_refs])
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
                await self._resolve_suppression_unlocked(candidate, OrdinaryMemoryPurpose.EXPORT)
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
            ref.evidence_id for item in page.items for ref in item.invocation.public_input_refs
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

    async def _read_invocation(self, invocation_id: str) -> LLMInvocationAuditRecord | None:
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
                    or delivery_receipt.receipt_hash != str(row["delivery_receipt_hash"])
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
            if hashlib.sha256(canonical_json(payload).encode()).hexdigest() != str(
                row["payload_hash"]
            ) or decision.decision_hash != str(row["decision_hash"]):
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
            elif (
                denial is None
                and access_receipt.scope_kind is SuppressionScopeKind.EVIDENCE
                and (access_receipt.scope_ref != evidence_id)
            ):
                denial = "sealed_audit_scope_differs"
            elif (
                denial is None
                and access_receipt.scope_kind is SuppressionScopeKind.SUBJECT
                and (access_receipt.scope_ref != subject)
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
            COGNITIVE_MEMORY_SCHEMA_VERSION,
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
            "schema_version": COGNITIVE_MEMORY_SCHEMA_VERSION,
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

        signature = self._audit_cursor_signature(query_hash, watermark_sequence, last_sequence)
        return AuditTraceCursor(query_hash, watermark_sequence, last_sequence, signature)

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
        async with self._admission_lock:
            self._delivery_admissions.clear()
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
        actual[operation_id] != operation_kind for operation_id, operation_kind in expected.items()
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


def _analysis_decisions_hash(decisions: tuple[object, ...]) -> str:
    """Bind an audit capability to repository-reconstructed decisions."""

    values: list[JsonValue] = []
    for decision in decisions:
        to_json = getattr(decision, "to_json", None)
        if not callable(to_json):
            raise MemoryValidationError("analysis_application_decisions_invalid")
        value = to_json()
        if not isinstance(value, dict):
            raise MemoryValidationError("analysis_application_decisions_invalid")
        values.append(cast(JsonValue, value))
    return hashlib.sha256(canonical_json(values).encode()).hexdigest()


def _opaque_hash(value: str) -> str:
    return hashlib.sha256(f"memory-log/v1|{value}".encode()).hexdigest()


def _mutation_apply_result(
    plan: MemoryMutationPlan,
    *,
    outcome: object,
    reason_code: object,
    decided_at: float,
    receipt_ref: MemoryMutationApplyReceiptRef | None = None,
    confirmation_operation_ids: tuple[str, ...] = (),
) -> MemoryMutationApplyResult:
    from simple_harness.runtime import (
        MemoryActionConfirmationItem,
        MemoryMutationApplyOutcome,
        MemoryMutationApplyReasonCode,
        MemoryMutationApplyReceiptRef,
        MemoryMutationApplyResult,
        MemoryMutationPlan,
    )

    if type(plan) is not MemoryMutationPlan:
        raise TypeError("plan must use MemoryMutationPlan")
    parsed_outcome = MemoryMutationApplyOutcome(outcome)
    parsed_reason = MemoryMutationApplyReasonCode(reason_code)
    if receipt_ref is not None and type(receipt_ref) is not MemoryMutationApplyReceiptRef:
        raise TypeError("receipt_ref must use MemoryMutationApplyReceiptRef")
    confirmations = tuple(
        MemoryActionConfirmationItem(plan.action_intent(operation_id))
        for operation_id in confirmation_operation_ids
    )
    result = MemoryMutationApplyResult(
        result_id=_stable_id(
            "memory-mutation-apply-result",
            plan.subject,
            plan.plan_hash,
            parsed_outcome.value,
        ),
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        run_id=plan.run_id,
        turn_id=plan.turn_id,
        subject=plan.subject,
        outcome=parsed_outcome,
        receipt_ref=cast(Any, receipt_ref),
        confirmation_items=confirmations,
        reason_code=parsed_reason,
        decided_at=decided_at,
    )
    result.validate_plan(plan)
    return result


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
        None if row["purpose"] is None else OrdinaryMemoryPurpose(str(row["purpose"])),
        None if row["supersedes_directive_id"] is None else str(row["supersedes_directive_id"]),
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
        str(row[0]): str(row[1]) for row in connection.execute("SELECT key,value FROM schema_meta")
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


def _sync_receipt(connection: sqlite3.Connection, meta: dict[str, str]) -> InitializationReceipt:
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
    "COGNITIVE_MUTATION_FAULT_POINTS",
    "INGESTION_FAULT_POINTS",
    "INITIALIZATION_FAULT_POINTS",
    "SUPPRESSION_FAULT_POINTS",
    "SQLiteHumanMemoryBackend",
)
