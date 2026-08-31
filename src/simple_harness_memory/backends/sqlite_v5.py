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
        DisclosureContext,
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
        ProcedureObservationAuthorityPort,
        ProcedureObservationAuthorityRef,
        ProspectiveSignalAuthorityPort,
        ProspectiveSignalAuthorityRef,
        RecallContext,
        RecallContextUseAuthorizationRequestV1,
        RecallContextUseReceiptV1,
        RecallPlan,
        RecallResultPageRequestV1,
        RecallResultPageV1,
        SanitizedEvidenceEnvelope,
        SanitizedEvidenceReceipt,
    )

    from simple_harness_memory.cognitive.twin_builder import (
        TwinGraphRecordInput,
        TwinGraphView,
    )
    from simple_harness_memory.core.audit import (
        AuditAccessAuthorityPort,
        AuditAccessAuthorityRefV1,
        AuditAggregateMetricsV1,
        AuditTraceCursor,
        AuditTraceItem,
        AuditTraceLineageRef,
        AuditTracePage,
        AuditTraceQuery,
        CanonicalStateManifestAccessV1,
        CanonicalStateTableRootV1,
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
    from simple_harness_memory.core.lifecycle_results import (
        ProcedureObservationApplyResult,
        ProspectiveSignalApplyResult,
    )
    from simple_harness_memory.core.mutations import InformationClassificationPolicy
    from simple_harness_memory.core.recall import (
        RecallCandidate,
        RecallConfirmationCandidate,
        TypedRecallExecution,
    )
    from simple_harness_memory.core.short_horizon import (
        ShortHorizonGenerationBuildResult,
        ShortHorizonProjectionBuildResult,
        ShortHorizonRecallResult,
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
    from simple_harness_memory.embedders.base import Embedder

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
COGNITIVE_CONFLICT_FAULT_POINTS = (
    "mutation.after_conflict_group",
    "mutation.after_conflict_member_1",
    "mutation.after_conflict_member_2",
    "mutation.after_conflict_resolution",
)
TYPED_RECALL_FAULT_POINTS = (
    "typed_recall.after_request",
    "typed_recall.after_attempt",
    "typed_recall.after_decision_header",
    "typed_recall.after_decision_item",
    "typed_recall.after_result_header",
    "typed_recall.after_result_item",
    "typed_recall.after_terminal",
    "typed_recall.before_commit",
    "typed_recall.after_commit",
)
PROCEDURE_OBSERVATION_FAULT_POINTS = (
    "procedure.before_begin",
    "procedure.after_begin",
    "procedure.after_consumption",
    "procedure.after_observation",
    "procedure.after_revision",
    "procedure.after_decision",
    "procedure.before_commit",
    "procedure.after_commit",
)
PROSPECTIVE_SIGNAL_FAULT_POINTS = (
    "prospective.before_begin",
    "prospective.after_begin",
    "prospective.after_consumption",
    "prospective.after_event",
    "prospective.after_revision",
    "prospective.after_decision",
    "prospective.before_commit",
    "prospective.after_commit",
)
logger = structlog.get_logger("simple_harness_memory.backends.sqlite_v5")
_DEFAULT_FILTER_POLICIES = frozenset({"credential-filter/v1"})
_RECALL_POLICY_HASH = hashlib.sha256(
    canonical_json(
        {
            "policy": "typed-recall-eligibility/v1",
            "schema": 6,
            "rrf_k": 60,
            "weights": {
                "vector": 0.40,
                "full_text": 0.30,
                "entity": 0.15,
                "task_scope": 0.10,
                "temporal": 0.05,
            },
        }
    ).encode("utf-8")
).hexdigest()
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
    """Own the fresh v6 SQLite root and suppression-first repository APIs."""

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
        procedure_observation_authority: ProcedureObservationAuthorityPort | None = None,
        prospective_signal_authority: ProspectiveSignalAuthorityPort | None = None,
        short_horizon_embedder: Embedder | None = None,
        audit_access_authority: AuditAccessAuthorityPort | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._fault_injector = fault_injector
        self._now = now
        self._db: aiosqlite.Connection | None = None
        self._secure_path: Path | None = None
        self._writer_lock_file: Any | None = None
        self._initialize_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._short_horizon_recall_lifecycle_lock = asyncio.Lock()
        self._short_horizon_recall_idle = asyncio.Event()
        self._short_horizon_recall_idle.set()
        self._short_horizon_active_recalls = 0
        self._short_horizon_closing = False
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
        self._procedure_observation_authority = procedure_observation_authority
        self._prospective_signal_authority = prospective_signal_authority
        self._short_horizon_embedder = short_horizon_embedder
        self._audit_access_authority = audit_access_authority
        self._short_horizon_cache: object | None = None
        self._short_horizon_audit_tasks: set[asyncio.Task[str]] = set()
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
            raise TypeError("memory_action_authority must implement MemoryActionAuthorityPort")
        if procedure_observation_authority is not None and not callable(
            getattr(
                procedure_observation_authority,
                "resolve_procedure_observation_authority",
                None,
            )
        ):
            raise TypeError(
                "procedure_observation_authority must implement ProcedureObservationAuthorityPort"
            )
        if prospective_signal_authority is not None and not callable(
            getattr(prospective_signal_authority, "resolve_prospective_signal_authority", None)
        ):
            raise TypeError(
                "prospective_signal_authority must implement ProspectiveSignalAuthorityPort"
            )
        if audit_access_authority is not None and not callable(
            getattr(audit_access_authority, "resolve_audit_access", None)
        ):
            raise TypeError(
                "audit_access_authority must implement AuditAccessAuthorityPort"
            )

    @property
    def initialization_receipt(self) -> InitializationReceipt | None:
        return self._receipt

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
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
                await self._load_short_horizon_cache_unlocked()
                self._audit_cursor_hmac_key = await self._read_audit_cursor_hmac_key()
                verify_sqlite_path(self._secure_path)
                self._receipt = receipt
                self._short_horizon_closing = False
                return receipt
            except BaseException:
                await self._close_after_failure()
                raise

    async def close(self) -> None:
        async with self._initialize_lock:
            async with self._short_horizon_recall_lifecycle_lock:
                self._short_horizon_closing = True
            await self._short_horizon_recall_idle.wait()
            try:
                await self._drain_short_horizon_audit_tasks()
                if self._db is not None:
                    await self._validate_integrity()
            finally:
                if self._db is not None:
                    await self._db.close()
                    self._db = None
                self._receipt = None
                self._audit_cursor_hmac_key = None
                self._short_horizon_cache = None
                self._short_horizon_audit_tasks.clear()
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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

    async def get_twin_graph_view(self, *, principal: MemoryPrincipal) -> TwinGraphView:
        """Return a suppression-first, display-only graph over canonical memory rows."""

        from simple_harness_memory.cognitive.twin_builder import (
            TwinGraphRelationInput,
            build_twin_graph_view,
        )
        from simple_harness_memory.core.identity import MemoryPrincipal

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        generated_at = _timestamp(self._now())
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            async with self._db.execute(
                "SELECT g.group_id,m.ordinal,h.current_revision AS head_revision,"
                "h.memory_type,r.* FROM cognitive_conflict_groups g "
                "JOIN cognitive_conflict_members m ON m.group_id=g.group_id "
                "JOIN cognitive_memory_heads h ON h.memory_id=m.memory_id "
                "JOIN cognitive_memory_revisions r ON r.memory_id=m.memory_id "
                "AND r.revision=m.revision "
                "LEFT JOIN cognitive_conflict_resolutions x ON x.group_id=g.group_id "
                "WHERE g.principal_id=? AND h.principal_id=? AND h.deployment_id=? "
                "AND h.household_id=? AND h.current_revision=g.challenger_revision "
                "AND x.group_id IS NULL ORDER BY g.group_id,m.ordinal",
                (
                    principal.actor_id,
                    principal.actor_id,
                    principal.deployment_id,
                    principal.household_id,
                ),
            ) as cursor:
                conflict_rows = tuple(await cursor.fetchall())
            conflict_keys = {
                (str(row["memory_id"]), int(row["revision"])) for row in conflict_rows
            }
            async with self._db.execute(
                "SELECT h.current_revision AS head_revision,h.memory_type,r.* "
                "FROM cognitive_memory_heads h JOIN cognitive_memory_revisions r "
                "ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
                "WHERE h.principal_id=? AND h.deployment_id=? AND h.household_id=? "
                "ORDER BY h.memory_id",
                (
                    principal.actor_id,
                    principal.deployment_id,
                    principal.household_id,
                ),
            ) as cursor:
                current_rows = tuple(await cursor.fetchall())
            records = [
                await self._twin_graph_record_input_unlocked(
                    row, conflict_group_id=str(row["group_id"])
                )
                for row in conflict_rows
            ]
            records.extend(
                [
                    await self._twin_graph_record_input_unlocked(
                        row, conflict_group_id=None
                    )
                    for row in current_rows
                    if (str(row["memory_id"]), int(row["revision"])) not in conflict_keys
                ]
            )
            async with self._db.execute(
                "SELECT rel.* FROM cognitive_relations rel "
                "JOIN cognitive_memory_heads source ON source.memory_id=rel.source_memory_id "
                "JOIN cognitive_memory_heads target ON target.memory_id=rel.target_memory_id "
                "WHERE rel.principal_id=? AND source.principal_id=? "
                "AND target.principal_id=? AND source.deployment_id=? "
                "AND target.deployment_id=? AND source.household_id=? "
                "AND target.household_id=? ORDER BY rel.relation_id",
                (
                    principal.actor_id,
                    principal.actor_id,
                    principal.actor_id,
                    principal.deployment_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.household_id,
                ),
            ) as cursor:
                relation_rows = tuple(await cursor.fetchall())
            relations = tuple(
                TwinGraphRelationInput(
                    str(row["relation_id"]),
                    str(row["relation_kind"]),
                    str(row["source_memory_id"]),
                    int(row["source_revision"]),
                    str(row["target_memory_id"]),
                    int(row["target_revision"]),
                    str(row["relation_hash"]),
                )
                for row in relation_rows
            )
        return build_twin_graph_view(
            subject=principal.actor_id,
            generated_at=generated_at,
            records=tuple(records),
            relations=relations,
        )

    async def _twin_graph_record_input_unlocked(
        self, row: aiosqlite.Row, *, conflict_group_id: str | None
    ) -> TwinGraphRecordInput:
        from simple_harness_memory.cognitive.twin_builder import (
            TwinGraphRecordInput,
            TwinGraphSourceRef,
        )
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        assert self._db is not None
        memory_id = str(row["memory_id"])
        revision = int(row["revision"])
        content_json = str(row["content_json"])
        try:
            content = json.loads(content_json)
            attributes = json.loads(str(row["information_attributes_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("twin graph canonical record is invalid") from exc
        if (
            not isinstance(content, dict)
            or canonical_json(content) != content_json
            or hashlib.sha256(content_json.encode("utf-8")).hexdigest()
            != str(row["content_hash"])
            or not isinstance(attributes, list)
            or not all(isinstance(item, str) for item in attributes)
        ):
            raise MemoryCorruptionError("twin graph canonical record differs")
        async with self._db.execute(
            "SELECT evidence_id,span_id,source_kind,quote_hash "
            "FROM cognitive_evidence_spans WHERE memory_id=? AND revision=? "
            "ORDER BY evidence_id,span_id",
            (memory_id, revision),
        ) as cursor:
            source_rows = tuple(await cursor.fetchall())
        if not source_rows:
            raise MemoryCorruptionError("twin graph canonical record has no source")
        source_refs = tuple(
            TwinGraphSourceRef(
                hashlib.sha256(str(source["evidence_id"]).encode("utf-8")).hexdigest(),
                hashlib.sha256(str(source["span_id"]).encode("utf-8")).hexdigest(),
                str(source["source_kind"]),
                str(source["quote_hash"]),
            )
            for source in source_rows
        )
        entity_ids = self._mutation_entity_ids_from_content_json(content_json)
        suppressed = (
            await self._resolve_suppression_unlocked(
                SuppressionCandidate(
                    str(row["principal_id"]),
                    memory_id=memory_id,
                    entity_ids=entity_ids,
                ),
                OrdinaryMemoryPurpose.PROJECTION,
            )
        ).denied
        for source in source_rows:
            suppressed = suppressed or (
                await self._resolve_suppression_unlocked(
                    SuppressionCandidate(
                        str(row["principal_id"]), evidence_id=str(source["evidence_id"])
                    ),
                    OrdinaryMemoryPurpose.PROJECTION,
                )
            ).denied
        sensitive_attributes = {
            "identity",
            "relationship",
            "family",
            "health",
            "location",
            "financial",
        }
        redact_content = str(row["effective_privacy_class"]) in {
            "sensitive",
            "restricted",
        } or bool(sensitive_attributes.intersection(attributes))
        suppressed = suppressed or str(row["effective_privacy_class"]) == "restricted"
        return TwinGraphRecordInput(
            memory_id,
            revision,
            int(row["head_revision"]),
            str(row["memory_type"]),
            str(row["lifecycle_state"]),
            str(row["epistemic_status"]),
            str(row["conflict_status"]),
            str(row["verification_state"]),
            None if row["valid_from"] is None else float(row["valid_from"]),
            None if row["valid_to"] is None else float(row["valid_to"]),
            content,
            str(row["content_hash"]),
            source_refs,
            conflict_group_id,
            suppressed,
            redact_content,
        )

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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
            raise RuntimeError("human-memory v6 backend is not initialized")
        async with self._write_lock:
            async with self._db.execute(
                "SELECT evidence_id FROM evidence_envelopes WHERE subject=? ORDER BY evidence_id",
                (subject,),
            ) as cursor:
                rows = list(await cursor.fetchall())
            visible: list[str] = []
            for row in rows:
                evidence_id = str(row["evidence_id"])
                resolution = await self._resolve_suppression_unlocked(
                    SuppressionCandidate(subject, evidence_id=evidence_id), purpose
                )
                if not resolution.denied:
                    visible.append(evidence_id)
        return tuple(visible)

    async def suppress(
        self,
        request: SuppressionRequest,
        *,
        principal: MemoryPrincipal | None = None,
    ) -> SuppressionDecision:
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
        return await self._append_suppression_decision(decision, principal=principal)

    async def revoke_suppression(
        self,
        request: SuppressionRevokeRequest,
        *,
        principal: MemoryPrincipal | None = None,
    ) -> SuppressionDecision:
        from simple_harness_memory.core.suppression import (
            SuppressionAction,
            SuppressionDecision,
            SuppressionRevokeRequest,
        )

        if type(request) is not SuppressionRevokeRequest:
            raise TypeError("request must use SuppressionRevokeRequest")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        async with self._write_lock:
            if principal is not None:
                await self._authorize_short_horizon_principal_unlocked(principal)
                if request.subject != principal.actor_id:
                    raise MemoryOwnershipConflict("suppression_principal_rejected")
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
        self,
        decision: SuppressionDecision,
        *,
        principal: MemoryPrincipal | None = None,
    ) -> SuppressionDecision:
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        async with self._write_lock:
            if principal is not None:
                await self._authorize_short_horizon_principal_unlocked(principal)
                if decision.subject != principal.actor_id:
                    raise MemoryOwnershipConflict("suppression_principal_rejected")
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
            await self._advance_recall_authority_unlocked(
                decision.subject,
                event_kind="suppression_changed",
                source_ref=decision.directive_id,
                now=decision.effective_at,
            )
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
        typed_reference = cast(ConversationEvidenceRegistrationRef, reference)
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
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

        metadata = registration.metadata
        expected_reference = (
            registration.registration_id,
            registration.registration_hash,
            registration.envelope.evidence_id,
            registration.envelope.envelope_hash,
        )
        actual_reference = (
            typed_reference.registration_id,
            typed_reference.registration_hash,
            typed_reference.evidence_id,
            typed_reference.envelope_hash,
        )
        if expected_reference != actual_reference:
            raise MemoryValidationError("conversation_registration_authority_rejected")
        if registration.short_horizon_eligible:
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
                item_authority = registration.recall_item_authority
                from simple_harness_memory.core.short_horizon import (
                    resolve_authorized_public_text,
                )

                public_text = (
                    None
                    if item_authority is None
                    else resolve_authorized_public_text(envelope.sanitized_payload, metadata)
                )
                await self._db.execute(
                    "INSERT INTO conversation_evidence_registrations("
                    "registration_id,registration_hash,principal_id,evidence_id,envelope_hash,"
                    "admission_receipt_id,admission_receipt_hash,metadata_id,metadata_hash,"
                    "metadata_json,metadata_receipt_id,metadata_receipt_hash,"
                    "metadata_receipt_json,authority_issuer_id,run_id,subject,conversation_id,"
                    "primary_conversation_id,causal_group_id,causal_group_sequence,item_ordinal,"
                    "group_item_count,ordered_group_manifest_hash,role,occurred_at,task_scope_id,"
                    "tool_causal_link_json,entities_json,conversation_schema_version,"
                    "public_text_json_pointer,public_text,public_text_hash,"
                    "public_text_normalization_version,evidence_item_authority_id,"
                    "evidence_item_authority_hash,evidence_item_authority_json,"
                    "effective_privacy_class,information_attributes_json,"
                    "classification_authority_ref,registration_json,registered_at) VALUES("
                    + ",".join("?" for _ in range(41))
                    + ")",
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
                        registration.schema_version,
                        metadata.public_text_json_pointer,
                        public_text,
                        metadata.public_text_hash,
                        metadata.public_text_normalization_version,
                        None if item_authority is None else item_authority.authority_id,
                        None if item_authority is None else item_authority.authority_hash,
                        None
                        if item_authority is None
                        else canonical_json(item_authority.to_json()),
                        None
                        if metadata.effective_privacy_class is None
                        else metadata.effective_privacy_class.value,
                        None
                        if metadata.information_attributes is None
                        else canonical_json(
                            [item.value for item in metadata.information_attributes]
                        ),
                        metadata.classification_authority_ref,
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

    async def rebuild_short_horizon_projection(
        self, *, principal: MemoryPrincipal, now: float | None = None
    ) -> ShortHorizonProjectionBuildResult:
        """Rebuild disposable five-day chunks from immutable Host registrations."""

        from simple_harness.runtime import InformationAttribute, PrivacyClass

        from simple_harness_memory.core.identity import MemoryPrincipal
        from simple_harness_memory.core.short_horizon import (
            RECENT_CAUSAL_GROUP_LIMIT,
            SHORT_HORIZON_RETENTION_SECONDS,
            ShortHorizonProjectionBuildResult,
        )
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        effective_now = _timestamp(self._now() if now is None else now)
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            async with self._db.execute(
                "SELECT r.*,e.source_ref AS evidence_source_ref "
                "FROM conversation_evidence_registrations r JOIN evidence_envelopes e "
                "ON e.evidence_id=r.evidence_id WHERE r.principal_id=? "
                "AND r.public_text IS NOT NULL "
                "ORDER BY primary_conversation_id,"
                "causal_group_sequence,item_ordinal",
                (principal.actor_id,),
            ) as cursor:
                rows = tuple(await cursor.fetchall())
            try:
                for row in rows:
                    self._assert_short_horizon_registration_metadata_binding(row)
            except MemoryCorruptionError:
                await self._append_short_horizon_audit_transaction(
                    principal_id=principal.actor_id,
                    event_kind="projection_rejected",
                    details={"reason_code": "registration_metadata_binding_differs"},
                    created_at=effective_now,
                )
                raise
            groups: dict[tuple[str, str, str], list[aiosqlite.Row]] = {}
            for row in rows:
                groups.setdefault(
                    (
                        str(row["subject"]),
                        str(row["primary_conversation_id"]),
                        str(row["causal_group_id"]),
                    ),
                    [],
                ).append(row)
            complete_groups: dict[tuple[str, str, str], tuple[aiosqlite.Row, ...]] = {}
            try:
                for key, group_rows in groups.items():
                    items = tuple(sorted(group_rows, key=lambda item: int(item["item_ordinal"])))
                    if self._short_horizon_group_is_complete(items):
                        complete_groups[key] = items
            except MemoryCorruptionError:
                await self._append_short_horizon_audit_transaction(
                    principal_id=principal.actor_id,
                    event_kind="projection_rejected",
                    details={"reason_code": "causal_group_metadata_inconsistent"},
                    created_at=effective_now,
                )
                raise
            recent: set[tuple[str, str, str]] = set()
            by_conversation: dict[tuple[str, str], list[tuple[int, str]]] = {}
            for (subject, conversation_id, group_id), items in complete_groups.items():
                by_conversation.setdefault((subject, conversation_id), []).append(
                    (int(items[0]["causal_group_sequence"]), group_id)
                )
            for (subject, conversation_id), values in by_conversation.items():
                recent.update(
                    (subject, conversation_id, group_id)
                    for _, group_id in sorted(values, reverse=True)[:RECENT_CAUSAL_GROUP_LIMIT]
                )
            projection: list[dict[str, object]] = []
            privacy_rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
            for key, items in complete_groups.items():
                if key in recent:
                    continue
                first = items[0]
                occurred_at = max(float(item["occurred_at"]) for item in items)
                expires_at = occurred_at + SHORT_HORIZON_RETENTION_SECONDS
                if occurred_at > effective_now or effective_now > expires_at:
                    continue
                suppressed = False
                for item in items:
                    entities = tuple(json.loads(str(item["entities_json"])))
                    resolution = await self._resolve_suppression_unlocked(
                        SuppressionCandidate(
                            subject=principal.actor_id,
                            evidence_id=str(item["evidence_id"]),
                            entity_ids=entities,
                        ),
                        OrdinaryMemoryPurpose.PROJECTION,
                    )
                    if resolution.denied:
                        suppressed = True
                        break
                if suppressed:
                    continue
                content = "\n".join(f"{item['role']}: {item['public_text']}" for item in items)
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                aggregate_privacy = max(
                    (str(item["effective_privacy_class"]) for item in items),
                    key=privacy_rank.__getitem__,
                )
                attributes = sorted(
                    {
                        value
                        for item in items
                        for value in json.loads(str(item["information_attributes_json"]))
                    }
                )
                classification_refs = sorted(
                    {str(item["classification_authority_ref"]) for item in items}
                )
                chunk_payload = {
                    "subject": principal.actor_id,
                    "primary_conversation_id": key[1],
                    "causal_group_id": key[2],
                    "registration_hashes": [str(item["registration_hash"]) for item in items],
                    "content_hash": content_hash,
                    "effective_privacy_class": aggregate_privacy,
                    "information_attributes": attributes,
                    "classification_authority_refs": classification_refs,
                }
                projection.append(
                    {
                        "chunk_id": "short:"
                        + hashlib.sha256(
                            canonical_json(cast(JsonValue, chunk_payload)).encode()
                        ).hexdigest(),
                        "items": items,
                        "content": content,
                        "content_hash": content_hash,
                        "occurred_at": occurred_at,
                        "expires_at": expires_at,
                        "privacy": PrivacyClass(aggregate_privacy).value,
                        "attributes": [InformationAttribute(value).value for value in attributes],
                        "classification_refs": classification_refs,
                    }
                )
            async with self._db.execute(
                "SELECT chunk_id,content_hash FROM short_horizon_chunks "
                "WHERE principal_id=? ORDER BY chunk_id",
                (principal.actor_id,),
            ) as cursor:
                existing_projection = tuple(
                    (str(row[0]), str(row[1])) for row in await cursor.fetchall()
                )
            desired_projection = tuple(
                sorted((str(item["chunk_id"]), str(item["content_hash"])) for item in projection)
            )
            removed_chunk_count = len(
                {chunk_id for chunk_id, _ in existing_projection}
                - {chunk_id for chunk_id, _ in desired_projection}
            )
            registration_manifest_hash = hashlib.sha256(
                canonical_json(
                    cast(
                        JsonValue,
                        [
                            {
                                "registration_id_hash": _opaque_hash(str(row["registration_id"])),
                                "registration_hash": str(row["registration_hash"]),
                            }
                            for row in rows
                        ],
                    )
                ).encode()
            ).hexdigest()
            projection_manifest_hash = hashlib.sha256(
                canonical_json(
                    cast(JsonValue, [list(item) for item in desired_projection])
                ).encode()
            ).hexdigest()
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                if existing_projection == desired_projection:
                    audit_id = await self._append_short_horizon_audit_unlocked(
                        principal_id=principal.actor_id,
                        event_kind="projection_rebuilt",
                        eligible_count=len(projection),
                        details={
                            "registration_count": len(rows),
                            "registration_manifest_hash": registration_manifest_hash,
                            "chunk_manifest_hash": projection_manifest_hash,
                            "removed_chunk_count": 0,
                            "replayed": True,
                        },
                        created_at=effective_now,
                    )
                    await self._db.execute("COMMIT")
                    committed = True
                    return ShortHorizonProjectionBuildResult(len(projection), 0, audit_id)
                await self._db.execute(
                    "DELETE FROM short_horizon_chunks WHERE principal_id=?",
                    (principal.actor_id,),
                )
                for projection_item in projection:
                    projection_items = cast(tuple[aiosqlite.Row, ...], projection_item["items"])
                    first = projection_items[0]
                    await self._db.execute(
                        "INSERT INTO short_horizon_chunks(chunk_id,principal_id,subject,"
                        "primary_conversation_id,causal_group_id,causal_group_sequence,roles_json,"
                        "task_scope_ids_json,entities_json,source_refs_json,"
                        "effective_privacy_class,information_attributes_json,"
                        "classification_authority_refs_json,public_text,content_hash,occurred_at,"
                        "expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            projection_item["chunk_id"],
                            principal.actor_id,
                            principal.actor_id,
                            first["primary_conversation_id"],
                            first["causal_group_id"],
                            first["causal_group_sequence"],
                            canonical_json(
                                cast(JsonValue, [str(row["role"]) for row in projection_items])
                            ),
                            canonical_json(
                                cast(
                                    JsonValue,
                                    sorted(
                                        {
                                            str(row["task_scope_id"])
                                            for row in projection_items
                                            if row["task_scope_id"] is not None
                                        }
                                    ),
                                )
                            ),
                            canonical_json(
                                cast(
                                    JsonValue,
                                    sorted(
                                        {
                                            value
                                            for row in projection_items
                                            for value in json.loads(str(row["entities_json"]))
                                        }
                                    ),
                                )
                            ),
                            canonical_json(
                                cast(
                                    JsonValue,
                                    [str(row["evidence_source_ref"]) for row in projection_items],
                                )
                            ),
                            projection_item["privacy"],
                            canonical_json(cast(JsonValue, projection_item["attributes"])),
                            canonical_json(cast(JsonValue, projection_item["classification_refs"])),
                            projection_item["content"],
                            projection_item["content_hash"],
                            projection_item["occurred_at"],
                            projection_item["expires_at"],
                            effective_now,
                        ),
                    )
                    for row in projection_items:
                        await self._db.execute(
                            "INSERT INTO short_horizon_chunk_evidence(chunk_id,item_ordinal,"
                            "registration_id,evidence_id,envelope_hash) VALUES(?,?,?,?,?)",
                            (
                                projection_item["chunk_id"],
                                row["item_ordinal"],
                                row["registration_id"],
                                row["evidence_id"],
                                row["envelope_hash"],
                            ),
                        )
                self._fault("short_horizon.projection.before_audit")
                audit_id = await self._append_short_horizon_audit_unlocked(
                    principal_id=principal.actor_id,
                    event_kind="projection_rebuilt",
                    eligible_count=len(projection),
                    details={
                        "registration_count": len(rows),
                        "registration_manifest_hash": registration_manifest_hash,
                        "chunk_manifest_hash": projection_manifest_hash,
                        "removed_chunk_count": removed_chunk_count,
                        "replayed": False,
                    },
                    created_at=effective_now,
                )
                await self._advance_recall_authority_unlocked(
                    principal.actor_id,
                    event_kind="short_horizon_projection_changed",
                    source_ref=projection_manifest_hash,
                    now=effective_now,
                )
                self._fault("short_horizon.projection.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._short_horizon_cache = None
                return ShortHorizonProjectionBuildResult(
                    len(projection), removed_chunk_count, audit_id
                )
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def rebuild_short_horizon_generation(
        self, *, now: float | None = None
    ) -> ShortHorizonGenerationBuildResult:
        """Build and atomically activate the repository's exact durable vector generation."""

        from simple_harness_memory.core.short_horizon import ShortHorizonGenerationBuildResult
        from simple_harness_memory.embedders.base import EMBEDDING_FORMAT_VERSION, encode_vector

        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        if self._short_horizon_embedder is None:
            raise MemoryValidationError("short_horizon_embedder_required")
        effective_now = _timestamp(self._now() if now is None else now)
        embedder = self._short_horizon_embedder
        async with self._write_lock:
            async with self._db.execute(
                "SELECT chunk_id,principal_id,public_text,content_hash "
                "FROM short_horizon_chunks "
                "ORDER BY chunk_id"
            ) as cursor:
                rows = tuple(await cursor.fetchall())
            manifest_hash = self._short_horizon_manifest_hash(rows)
            lineage = embedder.lineage
            async with self._db.execute(
                "SELECT generation_id FROM short_horizon_generations "
                "WHERE state='active' AND lineage_id=? AND content_hash=?",
                (lineage.lineage_id, manifest_hash),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                await self._load_short_horizon_cache_unlocked()
                audit_id = await self._append_short_horizon_audit_transaction(
                    principal_id="system",
                    event_kind="generation_activated",
                    generation_id=str(existing[0]),
                    generation_state="active",
                    vector_count=len(rows),
                    details={
                        "chunk_manifest_hash": manifest_hash,
                        "lineage_id_hash": _opaque_hash(lineage.lineage_id),
                        "replayed": True,
                    },
                    created_at=effective_now,
                )
                return ShortHorizonGenerationBuildResult(
                    str(existing[0]), len(rows), True, True, audit_id
                )
            if not rows:
                audit_id = await self._append_short_horizon_audit_transaction(
                    principal_id="system",
                    event_kind="generation_activated",
                    generation_state="empty",
                    details={
                        "chunk_manifest_hash": manifest_hash,
                        "lineage_id_hash": _opaque_hash(lineage.lineage_id),
                        "replayed": False,
                    },
                    created_at=effective_now,
                )
                return ShortHorizonGenerationBuildResult(None, 0, False, False, audit_id)
            vectors = await embedder.embed_batch([str(row["public_text"]) for row in rows])
            embedder.validate_vectors(vectors, expected_count=len(rows))
            encoded_vectors = tuple(encode_vector(vector) for vector in vectors)
            vector_hashes = tuple(
                hashlib.sha256(encoded).hexdigest() for encoded in encoded_vectors
            )
            vector_manifest_hash = self._short_horizon_vector_manifest_hash(
                tuple(
                    (str(row["chunk_id"]), vector_hash)
                    for row, vector_hash in zip(rows, vector_hashes, strict=True)
                )
            )
            generation_id = f"short-gen:{uuid4().hex}"
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                await self._ensure_system_principal_unlocked(effective_now)
                await self._db.execute(
                    "INSERT INTO embedding_lineages(lineage_id,kind,provider,model,revision,"
                    "dimension,normalized,format_version,fingerprint,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(lineage_id) DO NOTHING",
                    (
                        lineage.lineage_id,
                        lineage.kind,
                        lineage.provider,
                        lineage.model,
                        lineage.revision,
                        lineage.dimension,
                        1 if lineage.normalization == "l2" else 0,
                        EMBEDDING_FORMAT_VERSION,
                        lineage.format_fingerprint,
                        effective_now,
                    ),
                )
                await self._db.execute(
                    "INSERT INTO short_horizon_generations(generation_id,lineage_id,state,"
                    "content_hash,vector_manifest_hash,created_at) VALUES(?,?,'building',?,?,?)",
                    (
                        generation_id,
                        lineage.lineage_id,
                        manifest_hash,
                        vector_manifest_hash,
                        effective_now,
                    ),
                )
                for row, encoded_vector, vector_hash in zip(
                    rows, encoded_vectors, vector_hashes, strict=True
                ):
                    await self._db.execute(
                        "INSERT INTO short_horizon_vectors(chunk_id,generation_id,embedding,"
                        "embedding_hash,dimension) VALUES(?,?,?,?,?)",
                        (
                            row["chunk_id"],
                            generation_id,
                            encoded_vector,
                            vector_hash,
                            lineage.dimension,
                        ),
                    )
                self._fault("short_horizon.generation.before_activate")
                await self._db.execute(
                    "UPDATE short_horizon_generations SET state='retired' WHERE state='active'"
                )
                await self._db.execute(
                    "UPDATE short_horizon_generations SET state='active',activated_at=? "
                    "WHERE generation_id=? AND state='building'",
                    (effective_now, generation_id),
                )
                audit_id = await self._append_short_horizon_audit_unlocked(
                    principal_id="system",
                    event_kind="generation_activated",
                    generation_id=generation_id,
                    generation_state="active",
                    vector_count=len(rows),
                    details={
                        "chunk_manifest_hash": manifest_hash,
                        "lineage_id_hash": _opaque_hash(lineage.lineage_id),
                        "replayed": False,
                    },
                    created_at=effective_now,
                )
                for principal_id in sorted({str(row["principal_id"]) for row in rows}):
                    await self._advance_recall_authority_unlocked(
                        principal_id,
                        event_kind="short_horizon_generation_changed",
                        source_ref=generation_id,
                        now=effective_now,
                    )
                self._fault("short_horizon.generation.before_commit")
                await self._db.execute("COMMIT")
                committed = True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
            await self._load_short_horizon_cache_unlocked()
            return ShortHorizonGenerationBuildResult(
                generation_id, len(rows), True, False, audit_id
            )

    async def recall_short_horizon(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        limit: int = 10,
        deadline_ms: int = 2_000,
        now: float | None = None,
    ) -> ShortHorizonRecallResult:
        """Account the caller deadline from entry, including queueing for write work."""

        from simple_harness_memory.core.short_horizon import SHORT_HORIZON_HARD_DEADLINE_MS

        if (
            isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or not 1 <= deadline_ms <= SHORT_HORIZON_HARD_DEADLINE_MS
        ):
            raise MemoryLimitError("short_horizon_deadline_invalid")
        started = time.monotonic()
        await self._begin_short_horizon_recall()
        try:
            return await self._recall_short_horizon_lifecycle_locked(
                principal=principal,
                query=query,
                disclosure_context=disclosure_context,
                limit=limit,
                deadline_ms=deadline_ms,
                now=now,
                started=started,
                deadline=started + deadline_ms / 1_000,
            )
        finally:
            await self._finish_short_horizon_recall()

    async def _recall_short_horizon_for_typed_plan(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        plan: RecallPlan,
        limit: int,
        now: float,
        deadline_monotonic: float,
    ) -> ShortHorizonRecallResult:
        """Use the frozen typed-recall cap without widening the legacy public API."""

        started = time.monotonic()
        remaining_ms = max(1, min(2_000, int((deadline_monotonic - started) * 1_000)))
        await self._begin_short_horizon_recall()
        try:
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError
            return await self._recall_short_horizon_lifecycle_locked(
                principal=principal,
                query=query,
                disclosure_context=disclosure_context,
                limit=limit,
                deadline_ms=remaining_ms,
                now=now,
                started=started,
                deadline=deadline_monotonic,
                max_limit=128,
                typed_plan=plan,
            )
        finally:
            await self._finish_short_horizon_recall()

    async def _recall_short_horizon_lifecycle_locked(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        limit: int = 10,
        deadline_ms: int = 2_000,
        now: float | None = None,
        started: float,
        deadline: float,
        max_limit: int = 100,
        typed_plan: RecallPlan | None = None,
    ) -> ShortHorizonRecallResult:
        """Return before one absolute caller deadline with a durable audit trail.

        A committed ``recall_started`` record explains an in-flight request. If
        the caller deadline wins, a detached terminal audit is queued, links back
        to that start record, and never delays the caller.
        """

        from simple_harness.runtime import DisclosureContext

        from simple_harness_memory.core.identity import MemoryPrincipal
        from simple_harness_memory.core.short_horizon import (
            SHORT_HORIZON_HARD_DEADLINE_MS,
            ShortHorizonDegradationCode,
            ShortHorizonRecallResult,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(disclosure_context) is not DisclosureContext:
            raise TypeError("disclosure_context must use DisclosureContext")
        if not isinstance(query, str) or not query.strip() or "\x00" in query:
            raise MemoryValidationError("short_horizon_query_invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= max_limit
        ):
            raise MemoryLimitError("short_horizon_limit_invalid")
        if (
            isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or not 1 <= deadline_ms <= SHORT_HORIZON_HARD_DEADLINE_MS
        ):
            raise MemoryLimitError("short_horizon_deadline_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")

        effective_now = _timestamp(self._now() if now is None else now)
        started_audit_id = f"short-audit:{uuid4().hex}"
        attempt_task = asyncio.create_task(
            self._record_short_horizon_recall_attempt(
                principal=principal,
                audit_id=started_audit_id,
                disclosure_context_hash=disclosure_context.context_hash,
                query_hash=hashlib.sha256(query.encode()).hexdigest(),
                deadline_ms=deadline_ms,
                created_at=effective_now,
            )
        )
        self._track_short_horizon_audit_task(attempt_task)
        try:
            await asyncio.wait_for(
                asyncio.shield(attempt_task),
                timeout=max(0.0, deadline - time.monotonic()),
            )
        except TimeoutError:
            self._schedule_short_horizon_recall_terminal(
                principal=principal,
                attempt_audit_id=started_audit_id,
                disclosure_context_hash=disclosure_context.context_hash,
                query_hash=hashlib.sha256(query.encode()).hexdigest(),
                deadline_ms=deadline_ms,
                created_at=effective_now,
            )
            return ShortHorizonRecallResult(
                (),
                started_audit_id,
                0,
                0,
                0,
                0,
                None,
                ShortHorizonDegradationCode.DEADLINE_EXCEEDED,
            )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(
                self._recall_short_horizon_after_start(
                    principal=principal,
                    query=query,
                    disclosure_context=disclosure_context,
                    limit=limit,
                    deadline_ms=deadline_ms,
                    now=effective_now,
                    started=started,
                    deadline=deadline,
                    attempt_audit_id=started_audit_id,
                    max_limit=max_limit,
                    typed_plan=typed_plan,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            self._schedule_short_horizon_recall_terminal(
                principal=principal,
                attempt_audit_id=started_audit_id,
                disclosure_context_hash=disclosure_context.context_hash,
                query_hash=hashlib.sha256(query.encode()).hexdigest(),
                deadline_ms=deadline_ms,
                created_at=effective_now,
            )
            return ShortHorizonRecallResult(
                (),
                started_audit_id,
                0,
                0,
                0,
                0,
                None,
                ShortHorizonDegradationCode.DEADLINE_EXCEEDED,
            )

    async def _recall_short_horizon_after_start(
        self,
        *,
        principal: MemoryPrincipal,
        query: str,
        disclosure_context: DisclosureContext,
        limit: int = 10,
        deadline_ms: int = 2_000,
        now: float | None = None,
        started: float,
        deadline: float,
        attempt_audit_id: str,
        max_limit: int = 100,
        typed_plan: RecallPlan | None = None,
    ) -> ShortHorizonRecallResult:
        """Recall from one gated universe; generation and cache stay repository-private."""

        from simple_harness.runtime import (
            DeliveryRecipient,
            DisclosureContext,
            DisclosureGeneration,
            DisclosureTrust,
            InformationAttribute,
            PrivacyClass,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal
        from simple_harness_memory.core.short_horizon import (
            SHORT_HORIZON_HARD_DEADLINE_MS,
            ShortHorizonDegradationCode,
            ShortHorizonRecallHit,
            ShortHorizonRecallResult,
            _ExactVectorGenerationCache,
        )
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(disclosure_context) is not DisclosureContext:
            raise TypeError("disclosure_context must use DisclosureContext")
        disclosure = cast(Any, disclosure_context)
        disclosure_allowed = (
            disclosure.subject == principal.actor_id
            and disclosure.trust is DisclosureTrust.TRUSTED_AUTHORITY
            and disclosure.generation is DisclosureGeneration.CURRENT
        )
        if not isinstance(query, str) or not query.strip() or "\x00" in query:
            raise MemoryValidationError("short_horizon_query_invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= max_limit
        ):
            raise MemoryLimitError("short_horizon_limit_invalid")
        if (
            isinstance(deadline_ms, bool)
            or not isinstance(deadline_ms, int)
            or not 1 <= deadline_ms <= SHORT_HORIZON_HARD_DEADLINE_MS
        ):
            raise MemoryLimitError("short_horizon_deadline_invalid")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        effective_now = _timestamp(self._now() if now is None else now)
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            if not disclosure_allowed:
                await self._append_short_horizon_audit_transaction(
                    principal_id=principal.actor_id,
                    event_kind="recall",
                    disclosure_context_hash=disclosure.context_hash,
                    query_hash=hashlib.sha256(query.encode()).hexdigest(),
                    eligible_count=0,
                    degradation_code="DISCLOSURE_REJECTED",
                    details={
                        "candidate_count": 0,
                        "time_filtered_count": 0,
                        "privacy_filtered_count": 0,
                        "classification_filtered_count": 0,
                        "suppression_filtered_count": 0,
                        "eligible": [],
                        "fts_lane": [],
                        "entity_time_lane": [],
                        "vector_lane": [],
                        "selected": [],
                        "gate_outcome": "disclosure_rejected",
                        "attempt_audit_id": attempt_audit_id,
                    },
                    created_at=effective_now,
                )
                raise MemoryOwnershipConflict("short_horizon_disclosure_rejected")
            async with self._db.execute(
                "SELECT COUNT(*) FROM short_horizon_chunks WHERE principal_id=?",
                (principal.actor_id,),
            ) as cursor:
                total_row = await cursor.fetchone()
            assert total_row is not None
            total_count = int(total_row[0])
            async with self._db.execute(
                "SELECT * FROM short_horizon_chunks WHERE principal_id=? "
                "AND occurred_at<=? AND expires_at>? ORDER BY occurred_at DESC,chunk_id",
                (principal.actor_id, effective_now, effective_now),
            ) as cursor:
                candidate_rows = tuple(await cursor.fetchall())
            universe: list[aiosqlite.Row] = []
            privacy_filtered_count = 0
            classification_filtered_count = 0
            suppression_filtered_count = 0
            self_delivery = (
                disclosure.recipient is DeliveryRecipient.USER_SELF
                and disclosure.recipient_id == principal.actor_id
            )
            for row in candidate_rows:
                privacy = PrivacyClass(str(row["effective_privacy_class"]))
                if privacy is not PrivacyClass.PUBLIC and not self_delivery:
                    privacy_filtered_count += 1
                    continue
                attributes = json.loads(str(row["information_attributes_json"]))
                classification_refs = json.loads(str(row["classification_authority_refs_json"]))
                if (
                    not isinstance(attributes, list)
                    or any(not isinstance(value, str) for value in attributes)
                    or not isinstance(classification_refs, list)
                    or not classification_refs
                ):
                    raise MemoryCorruptionError("short horizon classification binding invalid")
                tuple(InformationAttribute(value) for value in attributes)
                if typed_plan is not None:
                    if not self._candidate_disclosure_allowed(
                        typed_plan.disclosure_context,
                        str(row["effective_privacy_class"]),
                        tuple(str(value) for value in attributes),
                    ):
                        classification_filtered_count += 1
                        continue
                    scopes = set(json.loads(str(row["task_scope_ids_json"])))
                    entities = {
                        str(value).casefold()
                        for value in json.loads(str(row["entities_json"]))
                    }
                    if typed_plan.task_scope_ids and not scopes & set(
                        typed_plan.task_scope_ids
                    ):
                        classification_filtered_count += 1
                        continue
                    if typed_plan.entity_constraints and not entities & {
                        value.casefold() for value in typed_plan.entity_constraints
                    }:
                        classification_filtered_count += 1
                        continue
                    occurred_at = float(row["occurred_at"])
                    if (
                        typed_plan.earliest_occurred_at is not None
                        and occurred_at < typed_plan.earliest_occurred_at
                    ) or (
                        typed_plan.latest_occurred_at is not None
                        and occurred_at > typed_plan.latest_occurred_at
                    ):
                        classification_filtered_count += 1
                        continue
                async with self._db.execute(
                    "SELECT e.evidence_id,r.entities_json FROM short_horizon_chunk_evidence e "
                    "JOIN conversation_evidence_registrations r "
                    "ON r.registration_id=e.registration_id WHERE e.chunk_id=?",
                    (row["chunk_id"],),
                ) as cursor:
                    evidence_rows = tuple(await cursor.fetchall())
                suppressed = False
                for evidence in evidence_rows:
                    resolution = await self._resolve_suppression_unlocked(
                        SuppressionCandidate(
                            subject=principal.actor_id,
                            evidence_id=str(evidence["evidence_id"]),
                            memory_id=str(row["chunk_id"]),
                            entity_ids=tuple(json.loads(str(evidence["entities_json"]))),
                        ),
                        OrdinaryMemoryPurpose.RECALL,
                    )
                    if resolution.denied:
                        suppressed = True
                        break
                if not suppressed:
                    universe.append(row)
                else:
                    suppression_filtered_count += 1
            universe_by_ref = {str(row["chunk_id"]): row for row in universe}
            fts_refs: list[str] = []
            if time.monotonic() < deadline and universe:
                terms = tuple(dict.fromkeys(re.findall(r"[\w]+", query.casefold())))
                if terms:
                    fts_query = " OR ".join(
                        f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms
                    )
                    await self._db.execute(
                        "CREATE TEMP TABLE IF NOT EXISTS short_horizon_eligible_tmp("
                        "chunk_id TEXT PRIMARY KEY) WITHOUT ROWID"
                    )
                    await self._db.execute("DELETE FROM short_horizon_eligible_tmp")
                    await self._db.executemany(
                        "INSERT INTO short_horizon_eligible_tmp(chunk_id) VALUES(?)",
                        ((chunk_id,) for chunk_id in universe_by_ref),
                    )
                    async with self._db.execute(
                        "SELECT f.chunk_id FROM short_horizon_fts f "
                        "JOIN short_horizon_eligible_tmp e ON e.chunk_id=f.chunk_id "
                        "WHERE short_horizon_fts MATCH ? "
                        "ORDER BY bm25(short_horizon_fts),f.chunk_id",
                        (fts_query,),
                    ) as cursor:
                        fts_refs = [str(row[0]) for row in await cursor.fetchall()]
            query_terms = set(re.findall(r"[\w]+", query.casefold()))
            entity_time_refs = sorted(
                universe_by_ref,
                key=lambda ref: (
                    -len(
                        query_terms
                        & {
                            str(value).casefold()
                            for value in json.loads(str(universe_by_ref[ref]["entities_json"]))
                        }
                    ),
                    -float(universe_by_ref[ref]["occurred_at"]),
                    ref,
                ),
            )
            vector_hits: tuple[Any, ...] = ()
            used_generation_id: str | None = None
            degradation: ShortHorizonDegradationCode | None = None
            active_generation_id = await self._active_short_horizon_generation_unlocked()
            current_manifest = await self._current_short_horizon_manifest_hash_unlocked()
            active_lineage_id: str | None = None
            if active_generation_id is None:
                degradation = ShortHorizonDegradationCode.NO_ACTIVE_GENERATION
            else:
                async with self._db.execute(
                    "SELECT content_hash,lineage_id FROM short_horizon_generations "
                    "WHERE generation_id=?",
                    (active_generation_id,),
                ) as cursor:
                    active_row = await cursor.fetchone()
                if active_row is not None:
                    active_lineage_id = str(active_row["lineage_id"])
                if active_row is None or str(active_row[0]) != current_manifest:
                    degradation = ShortHorizonDegradationCode.STALE_ACTIVE_GENERATION
                elif time.monotonic() >= deadline:
                    degradation = ShortHorizonDegradationCode.DEADLINE_EXCEEDED
                elif isinstance(self._short_horizon_cache, _ExactVectorGenerationCache):
                    try:
                        if self._short_horizon_embedder is None:
                            raise MemoryValidationError("short_horizon_embedder_required")
                        # Keep a bounded reserve for immutable completion audit/return
                        # work.  If the vector lane consumes the entire caller budget,
                        # the outer deadline would cancel the audit and erase the
                        # useful non-vector fallback result.
                        audit_reserve = min(
                            0.050,
                            max(0.001, (deadline - started) * 0.25),
                        )
                        remaining = deadline - time.monotonic() - audit_reserve
                        if remaining <= 0:
                            raise TimeoutError
                        query_vector = await asyncio.wait_for(
                            self._short_horizon_embedder.embed(query), timeout=remaining
                        )
                        vector_hits = self._short_horizon_cache.exact_search(
                            query_vector,
                            active_generation_id=active_generation_id,
                            eligible_refs=frozenset(universe_by_ref),
                            limit=max(limit * 4, limit),
                            deadline_monotonic=deadline,
                        )
                        used_generation_id = active_generation_id
                    except (TimeoutError, ValueError):
                        degradation = ShortHorizonDegradationCode.DEADLINE_EXCEEDED
                else:
                    degradation = ShortHorizonDegradationCode.VECTOR_DEGRADED
            ranks: dict[str, float] = {}
            for lane in (
                fts_refs,
                entity_time_refs,
                [hit.memory_ref for hit in vector_hits],
            ):
                for rank, ref in enumerate(lane, start=1):
                    ranks[ref] = ranks.get(ref, 0.0) + 1.0 / (60 + rank)
            ranked_refs = sorted(ranks, key=lambda ref: (-ranks[ref], ref))[:limit]
            hits = tuple(
                ShortHorizonRecallHit(
                    chunk_ref=ref,
                    content=str(universe_by_ref[ref]["public_text"]),
                    content_hash=str(universe_by_ref[ref]["content_hash"]),
                    score=ranks[ref],
                    occurred_at=float(universe_by_ref[ref]["occurred_at"]),
                    effective_privacy_class=PrivacyClass(
                        str(universe_by_ref[ref]["effective_privacy_class"])
                    ),
                    information_attributes=tuple(
                        InformationAttribute(value)
                        for value in json.loads(
                            str(universe_by_ref[ref]["information_attributes_json"])
                        )
                    ),
                    classification_authority_refs=tuple(
                        json.loads(str(universe_by_ref[ref]["classification_authority_refs_json"]))
                    ),
                )
                for ref in ranked_refs
            )
            audit_id = await self._append_short_horizon_audit_transaction(
                principal_id=principal.actor_id,
                event_kind="recall",
                disclosure_context_hash=disclosure.context_hash,
                query_hash=hashlib.sha256(query.encode()).hexdigest(),
                generation_id=used_generation_id or active_generation_id,
                generation_state="used" if used_generation_id else "degraded",
                eligible_count=len(universe),
                fts_count=len(fts_refs),
                entity_time_count=len(entity_time_refs),
                vector_count=len(vector_hits),
                degradation_code=None if degradation is None else degradation.value,
                details={
                    "candidate_count": len(universe) if typed_plan is not None else total_count,
                    "time_filtered_count": (
                        0 if typed_plan is not None else total_count - len(candidate_rows)
                    ),
                    "privacy_filtered_count": (
                        0 if typed_plan is not None else privacy_filtered_count
                    ),
                    "classification_filtered_count": (
                        0 if typed_plan is not None else classification_filtered_count
                    ),
                    "suppression_filtered_count": (
                        0 if typed_plan is not None else suppression_filtered_count
                    ),
                    "eligible": [
                        {
                            "chunk_ref_hash": _opaque_hash(ref),
                            "content_hash": str(row["content_hash"]),
                        }
                        for ref, row in sorted(universe_by_ref.items())
                    ],
                    "fts_lane": [
                        {"chunk_ref_hash": _opaque_hash(ref), "rank": rank}
                        for rank, ref in enumerate(fts_refs, start=1)
                    ],
                    "entity_time_lane": [
                        {"chunk_ref_hash": _opaque_hash(ref), "rank": rank}
                        for rank, ref in enumerate(entity_time_refs, start=1)
                    ],
                    "vector_lane": [
                        {
                            "chunk_ref_hash": _opaque_hash(hit.memory_ref),
                            "score": hit.score,
                            "rank": rank,
                        }
                        for rank, hit in enumerate(vector_hits, start=1)
                    ],
                    "selected": [
                        {
                            "chunk_ref_hash": _opaque_hash(ref),
                            "score": ranks[ref],
                            "rank": rank,
                        }
                        for rank, ref in enumerate(ranked_refs, start=1)
                    ],
                    "active_generation_id_hash": (
                        None if active_generation_id is None else _opaque_hash(active_generation_id)
                    ),
                    "used_generation_id_hash": (
                        None if used_generation_id is None else _opaque_hash(used_generation_id)
                    ),
                    "lineage_id_hash": (
                        None if active_lineage_id is None else _opaque_hash(active_lineage_id)
                    ),
                    "manifest_hash": current_manifest,
                    "deadline_ms": deadline_ms,
                    "elapsed_ms": max(0.0, (time.monotonic() - started) * 1_000),
                    "attempt_audit_id": attempt_audit_id,
                },
                created_at=effective_now,
            )
            return ShortHorizonRecallResult(
                hits,
                audit_id,
                len(universe),
                len(fts_refs),
                len(entity_time_refs),
                len(vector_hits),
                used_generation_id,
                degradation,
            )

    async def cleanup_short_horizon(
        self, *, principal: MemoryPrincipal, now: float | None = None
    ) -> int:
        """Delete only expired derived rows; immutable registration/evidence remains."""

        from simple_harness_memory.core.identity import MemoryPrincipal

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        effective_now = _timestamp(self._now() if now is None else now)
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                async with self._db.execute(
                    "SELECT COUNT(*) FROM short_horizon_chunks "
                    "WHERE principal_id=? AND expires_at<?",
                    (principal.actor_id, effective_now),
                ) as cursor:
                    count_row = await cursor.fetchone()
                assert count_row is not None
                count = int(count_row[0])
                await self._db.execute(
                    "DELETE FROM short_horizon_chunks WHERE principal_id=? AND expires_at<?",
                    (principal.actor_id, effective_now),
                )
                await self._append_short_horizon_audit_unlocked(
                    principal_id=principal.actor_id,
                    event_kind="cleanup",
                    eligible_count=count,
                    details={"removed_chunk_count": count},
                    created_at=effective_now,
                )
                if count:
                    await self._advance_recall_authority_unlocked(
                        principal.actor_id,
                        event_kind="short_horizon_cleanup",
                        source_ref=f"cleanup:{effective_now}:{count}",
                        now=effective_now,
                    )
                self._fault("short_horizon.cleanup.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                self._short_horizon_cache = None
                return count
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def execute_typed_recall(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float | None = None,
    ) -> TypedRecallExecution:
        """Execute strict RecallPlan v4 with durable replay before candidate access."""

        from simple_harness.runtime import RecallContext, RecallPlan

        from simple_harness_memory.core.identity import MemoryPrincipal
        from simple_harness_memory.core.recall import (
            TypedRecallExecution,
            apply_budget,
            apply_confirmation_budget,
            build_host_execution,
            capability_rejections,
            rank_candidates,
            request_hash,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(context) is not RecallContext:
            raise TypeError("context must use RecallContext")
        if type(plan) is not RecallPlan:
            raise TypeError("plan must use RecallPlan")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        started_monotonic = time.monotonic()
        deadline_monotonic = started_monotonic + plan.budget.deadline_ms / 1_000
        effective_now = _timestamp(self._now() if now is None else now)
        if context.subject != principal.actor_id or plan.subject != principal.actor_id:
            raise MemoryOwnershipConflict("typed_recall_subject_not_owned")
        plan.validate_narrowing(context, current_time=effective_now)
        digest = request_hash(principal_id=principal.actor_id, context=context, plan=plan)
        replay, request_id, attempt_id = await self._admit_typed_recall_request(
            principal=principal,
            context=context,
            plan=plan,
            request_digest=digest,
            now=effective_now,
        )
        if replay is not None:
            return replay
        if time.monotonic() >= deadline_monotonic:
            await self._persist_typed_recall_timeout(
                request_id=request_id, attempt_id=attempt_id, now=effective_now
            )
            raise TimeoutError("DEADLINE_EXCEEDED")

        unsupported = capability_rejections(plan)
        degradation_codes: list[str] = []
        if (
            any(mode.value == "vector" for mode in plan.retrieval_modes)
            and plan.requested_memory_types
        ):
            degradation_codes.append("cognitive_vector_unavailable")
        globally_denied = not self._ordinary_recall_disclosure_allowed(plan.disclosure_context)
        if unsupported or globally_denied:
            async with self._write_lock:
                epoch, policy_hash = await self._recall_authority_unlocked(principal.actor_id)
                execution = build_host_execution(
                    request_digest=digest,
                    context=context,
                    plan=plan,
                    candidates=(),
                    authority_epoch=epoch,
                    policy_hash=policy_hash,
                    evaluated_at=effective_now,
                    authority_expires_at=context.expires_at,
                    candidate_count=0,
                    truncated=False,
                    rejected=True,
                    rejection_reason=(
                        "recall_invalid_plan" if unsupported else "recall_disclosure_denied"
                    ),
                    unsupported_capabilities=unsupported,
                    degradation_codes=tuple(degradation_codes),
                )
                await self._persist_typed_recall_terminal_unlocked(
                    request_id=request_id,
                    attempt_id=attempt_id,
                    execution=execution,
                    terminal_kind="rejected",
                    now=effective_now,
                    deadline_monotonic=deadline_monotonic,
                )
            return execution

        async with self._write_lock:
            collected_epoch, collected_policy_hash = await self._recall_authority_unlocked(
                principal.actor_id
            )

        try:
            confirmations = await asyncio.wait_for(
                self._collect_typed_recall_confirmation(
                    principal=principal,
                    context=context,
                    plan=plan,
                    now=effective_now,
                    deadline_monotonic=deadline_monotonic,
                ),
                timeout=max(0.0, deadline_monotonic - time.monotonic()),
            )
        except TimeoutError:
            await self._persist_typed_recall_timeout(
                request_id=request_id, attempt_id=attempt_id, now=effective_now
            )
            raise TimeoutError("DEADLINE_EXCEEDED") from None
        if confirmations:
            from simple_harness_memory.core.recall import build_host_confirmation_execution

            confirmation_selection = apply_confirmation_budget(
                confirmations,
                max_items=plan.budget.max_items,
                max_bytes=plan.budget.max_bytes,
                max_tokens=plan.budget.max_tokens,
            )
            if confirmation_selection.selected:
                async with self._write_lock:
                    epoch, policy_hash = await self._recall_authority_unlocked(
                        principal.actor_id
                    )
                    if (epoch, policy_hash) != (
                        collected_epoch,
                        collected_policy_hash,
                    ):
                        raise MemoryValidationError("RECALL_AUTHORITY_STALE")
                    execution = build_host_confirmation_execution(
                        request_digest=digest,
                        context=context,
                        plan=plan,
                        confirmations=confirmation_selection.selected,
                        authority_epoch=epoch,
                        policy_hash=policy_hash,
                        evaluated_at=effective_now,
                        authority_expires_at=min(
                            context.expires_at,
                            *(
                                item.authority_expires_at
                                for group in confirmation_selection.selected
                                for item in group.members
                            ),
                        ),
                        truncated=confirmation_selection.truncated,
                        degradation_codes=tuple(degradation_codes),
                    )
                    await self._validate_recall_context_use_sources_unlocked(
                        principal_id=principal.actor_id,
                        result=execution.result,
                        decision=execution.decision,
                        supplied_item_ids=frozenset(
                            member.member.item_id
                            for group in execution.result.confirmation_groups
                            for member in group.members
                        ),
                        procedure_applicability_fingerprints=frozenset(
                            context.procedure_applicability_fingerprints
                        ),
                        now=effective_now,
                    )
                    await self._persist_typed_recall_terminal_unlocked(
                        request_id=request_id,
                        attempt_id=attempt_id,
                        execution=execution,
                        terminal_kind="completed",
                        now=effective_now,
                        deadline_monotonic=deadline_monotonic,
                    )
                return execution

        try:
            candidates = await asyncio.wait_for(
                self._collect_typed_recall_candidates(
                    principal=principal,
                    context=context,
                    plan=plan,
                    now=effective_now,
                    deadline_monotonic=deadline_monotonic,
                ),
                timeout=max(0.0, deadline_monotonic - time.monotonic()),
            )
        except TimeoutError:
            await self._persist_typed_recall_timeout(
                request_id=request_id, attempt_id=attempt_id, now=effective_now
            )
            raise TimeoutError("DEADLINE_EXCEEDED") from None
        if time.monotonic() >= deadline_monotonic:
            await self._persist_typed_recall_timeout(
                request_id=request_id, attempt_id=attempt_id, now=effective_now
            )
            raise TimeoutError("DEADLINE_EXCEEDED")
        short_candidates: tuple[RecallCandidate, ...] = ()
        if plan.include_short_horizon:
            try:
                short_candidates, short_degradation = (
                    await self._collect_typed_recall_short_candidates(
                    principal=principal,
                    context=context,
                    plan=plan,
                    now=effective_now,
                    deadline_monotonic=deadline_monotonic,
                    )
                )
                if short_degradation is not None:
                    degradation_codes.append(short_degradation)
            except TimeoutError:
                await self._persist_typed_recall_timeout(
                    request_id=request_id, attempt_id=attempt_id, now=effective_now
                )
                raise TimeoutError("DEADLINE_EXCEEDED") from None
        candidates = (*candidates, *short_candidates)
        ranked = rank_candidates(candidates)
        selection = apply_budget(
            ranked,
            max_items=plan.budget.max_items,
            max_bytes=plan.budget.max_bytes,
            max_tokens=plan.budget.max_tokens,
        )
        expiry = min(
            (context.expires_at, *(item.authority_expires_at for item in selection.selected))
        )
        if expiry <= effective_now:
            await self._persist_typed_recall_timeout(
                request_id=request_id, attempt_id=attempt_id, now=effective_now
            )
            raise TimeoutError("DEADLINE_EXCEEDED")
        async with self._write_lock:
            epoch, policy_hash = await self._recall_authority_unlocked(principal.actor_id)
            if (epoch, policy_hash) != (collected_epoch, collected_policy_hash):
                raise MemoryValidationError("RECALL_AUTHORITY_STALE")
            execution = build_host_execution(
                request_digest=digest,
                context=context,
                plan=plan,
                candidates=selection.selected,
                authority_epoch=epoch,
                policy_hash=policy_hash,
                evaluated_at=effective_now,
                authority_expires_at=expiry,
                candidate_count=len(ranked),
                truncated=selection.truncated or bool(confirmations),
                degradation_codes=tuple(dict.fromkeys(degradation_codes)),
            )
            assert isinstance(execution, TypedRecallExecution)
            await self._validate_recall_context_use_sources_unlocked(
                principal_id=principal.actor_id,
                result=execution.result,
                decision=execution.decision,
                supplied_item_ids=frozenset(
                    item.selected_item.item_id for item in execution.result.items
                ),
                procedure_applicability_fingerprints=frozenset(
                    context.procedure_applicability_fingerprints
                ),
                now=effective_now,
            )
            await self._persist_typed_recall_terminal_unlocked(
                request_id=request_id,
                attempt_id=attempt_id,
                execution=execution,
                terminal_kind="completed",
                now=effective_now,
                deadline_monotonic=deadline_monotonic,
            )
        return execution

    async def _collect_typed_recall_short_candidates(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float,
        deadline_monotonic: float,
    ) -> tuple[tuple[RecallCandidate, ...], str | None]:
        """Reuse the authority-filtered short-horizon search and preserve its lanes."""

        from simple_harness_memory.core.recall import RecallCandidate

        assert self._db is not None
        result = await self._recall_short_horizon_for_typed_plan(
            principal=principal,
            query=plan.query,
            disclosure_context=plan.disclosure_context,
            plan=plan,
            limit=min(128, max(32, 8 * plan.budget.max_items)),
            now=now,
            deadline_monotonic=deadline_monotonic,
        )
        degradation = (
            None if result.degradation_code is None else result.degradation_code.value
        )
        if degradation == "DEADLINE_EXCEEDED":
            raise TimeoutError
        async with self._write_lock:
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError
            async with self._db.execute(
                "SELECT audit_json FROM short_horizon_audit WHERE audit_id=?",
                (result.audit_id,),
            ) as cursor:
                audit_row = await cursor.fetchone()
            if audit_row is None:
                raise MemoryCorruptionError("typed recall short-horizon audit missing")
            raw_audit_json = audit_row[0]
            if isinstance(raw_audit_json, bytes):
                raw_audit_json = raw_audit_json.decode()
            audit_payload = json.loads(str(raw_audit_json))
            if not isinstance(audit_payload, dict):
                raise MemoryCorruptionError("typed recall short-horizon audit invalid")
            details = audit_payload.get("details")
            if not isinstance(details, dict):
                raise MemoryCorruptionError("typed recall short-horizon audit invalid")
            eligible_audit = details.get("eligible", [])
            if not isinstance(eligible_audit, list):
                raise MemoryCorruptionError("typed recall short-horizon eligible set invalid")
            eligible_hashes = {
                str(item["chunk_ref_hash"])
                for item in eligible_audit
                if isinstance(item, dict) and "chunk_ref_hash" in item
            }
            lane_hashes: dict[str, list[str]] = {}
            requested_audit_lanes = {
                "fts_lane": "full_text",
                "vector_lane": "vector",
            }
            for audit_lane, lane_name in requested_audit_lanes.items():
                requested = any(
                    mode.value == lane_name for mode in plan.retrieval_modes
                )
                if not requested:
                    continue
                raw_lane = details.get(audit_lane, [])
                if not isinstance(raw_lane, list):
                    raise MemoryCorruptionError("typed recall short-horizon lane invalid")
                lane_hashes[lane_name] = [
                    str(item["chunk_ref_hash"])
                    for item in raw_lane
                    if isinstance(item, dict) and "chunk_ref_hash" in item
                ]
            async with self._db.execute(
                "SELECT * FROM short_horizon_chunks WHERE principal_id=? "
                "AND occurred_at<=? AND expires_at>? ORDER BY chunk_id",
                (principal.actor_id, now, now),
            ) as cursor:
                rows = tuple(await cursor.fetchall())
            eligible_rows: dict[str, aiosqlite.Row] = {}
            entity_constraints = {item.casefold() for item in plan.entity_constraints}
            for row in rows:
                if time.monotonic() >= deadline_monotonic:
                    raise TimeoutError
                ref_hash = _opaque_hash(str(row["chunk_id"]))
                if ref_hash not in eligible_hashes:
                    continue
                attributes = tuple(
                    sorted(json.loads(str(row["information_attributes_json"])))
                )
                if not self._candidate_disclosure_allowed(
                    plan.disclosure_context,
                    str(row["effective_privacy_class"]),
                    attributes,
                ):
                    continue
                scopes = tuple(json.loads(str(row["task_scope_ids_json"])))
                if plan.task_scope_ids and not set(scopes) & set(plan.task_scope_ids):
                    continue
                entities = {
                    str(item).casefold()
                    for item in json.loads(str(row["entities_json"]))
                }
                if entity_constraints and not entity_constraints & entities:
                    continue
                occurred_at = float(row["occurred_at"])
                if (
                    plan.earliest_occurred_at is not None
                    and occurred_at < plan.earliest_occurred_at
                ) or (
                    plan.latest_occurred_at is not None
                    and occurred_at > plan.latest_occurred_at
                ):
                    continue
                eligible_rows[ref_hash] = row

            if entity_constraints:
                lane_hashes["entity"] = [
                    ref_hash
                    for ref_hash, _row in sorted(
                        eligible_rows.items(),
                        key=lambda item: (
                            -len(
                                entity_constraints
                                & {
                                    str(value).casefold()
                                    for value in json.loads(
                                        str(item[1]["entities_json"])
                                    )
                                }
                            ),
                            item[0],
                        ),
                    )
                ]
            if (
                plan.earliest_occurred_at is not None
                or plan.latest_occurred_at is not None
            ):
                anchor = plan.latest_occurred_at or plan.earliest_occurred_at or now
                lane_hashes["temporal"] = [
                    ref_hash
                    for ref_hash, _row in sorted(
                        eligible_rows.items(),
                        key=lambda item: (
                            abs(float(item[1]["occurred_at"]) - anchor),
                            -float(item[1]["occurred_at"]),
                            item[0],
                        ),
                    )
                ]
            if plan.task_scope_ids:
                requested_scopes = set(plan.task_scope_ids)
                lane_hashes["task_scope"] = [
                    ref_hash
                    for ref_hash, _row in sorted(
                        eligible_rows.items(),
                        key=lambda item: (
                            -len(
                                requested_scopes
                                & set(json.loads(str(item[1]["task_scope_ids_json"])))
                            ),
                            item[0],
                        ),
                    )
                ]
            lane_cap = min(128, max(32, 8 * plan.budget.max_items))
            ranks_by_lane = {
                lane: {
                    ref_hash: rank
                    for rank, ref_hash in enumerate(
                        (item for item in hashes if item in eligible_rows), start=1
                    )
                    if rank <= lane_cap
                }
                for lane, hashes in lane_hashes.items()
            }
            selected_hashes = {
                ref_hash for ranks in ranks_by_lane.values() for ref_hash in ranks
            }
            candidates: list[RecallCandidate] = []
            for ref_hash in sorted(selected_hashes):
                if time.monotonic() >= deadline_monotonic:
                    raise TimeoutError
                row = eligible_rows[ref_hash]
                chunk_ref = str(row["chunk_id"])
                scopes = tuple(json.loads(str(row["task_scope_ids_json"])))
                hit_attributes = tuple(
                    sorted(json.loads(str(row["information_attributes_json"])))
                )
                async with self._db.execute(
                    "SELECT evidence_id,envelope_hash FROM short_horizon_chunk_evidence "
                    "WHERE chunk_id=? ORDER BY item_ordinal",
                    (chunk_ref,),
                ) as cursor:
                    evidence_rows = tuple(await cursor.fetchall())
                if not evidence_rows:
                    raise MemoryCorruptionError("typed recall short-horizon lineage missing")
                lane_ranks = tuple(
                    (lane, ranks[ref_hash])
                    for lane, ranks in ranks_by_lane.items()
                    if ref_hash in ranks
                )
                if not lane_ranks:
                    continue
                evidence_manifest_hash = hashlib.sha256(
                    canonical_json(
                        cast(JsonValue, sorted({str(item[0]) for item in evidence_rows}))
                    ).encode()
                ).hexdigest()
                candidates.append(
                    RecallCandidate(
                        source_kind="short_horizon",
                        source_ref=chunk_ref,
                        source_revision=None,
                        memory_type=None,
                        public_payload={
                            "content": str(row["public_text"]),
                            "occurred_at": float(row["occurred_at"]),
                        },
                        source_content_hash=str(row["content_hash"]),
                        effective_privacy_class=str(row["effective_privacy_class"]),
                        information_attributes=hit_attributes,
                        evidence_manifest_hash=evidence_manifest_hash,
                        source_task_scope_ids=scopes,
                        active_task_scope_id=context.active_task_scope_id,
                        source_time=float(row["occurred_at"]),
                        authority_expires_at=min(context.expires_at, float(row["expires_at"])),
                        lane_ranks=lane_ranks,
                    )
                )
        from simple_harness_memory.core.recall import rank_candidates

        return rank_candidates(tuple(candidates))[:128], degradation

    async def page_typed_recall_result(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallResultPageRequestV1,
    ) -> RecallResultPageV1:
        """Page only a durable typed result; naked source references are never accepted."""

        from simple_harness.runtime import (
            RecallPageBindingKind,
            RecallPageConfirmationGroupBindingV1,
            RecallPageConfirmationMemberBindingV1,
            RecallPageSelectedItemBindingV1,
            RecallResultPageBindingV1,
            RecallResultPageRequestV1,
            RecallResultPageV1,
            TypedRecallResultV1,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(request) is not RecallResultPageRequestV1:
            raise TypeError("request must use RecallResultPageRequestV1")
        typed_request = cast(RecallResultPageRequestV1, request)
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        async with self._write_lock:
            async with self._db.execute(
                "SELECT r.result_json,r.result_hash,r.authority_expires_at "
                "FROM typed_recall_results r JOIN typed_recall_requests q "
                "ON q.request_id=r.request_id WHERE r.result_id=? AND q.principal_id=?",
                (typed_request.result_id, principal.actor_id),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None or str(row["result_hash"]) != typed_request.result_hash:
                raise MemoryValidationError("typed_recall_result_binding_invalid")
            raw_result = json.loads(str(row["result_json"]))
            if not isinstance(raw_result, dict):
                raise MemoryCorruptionError("typed recall result body invalid")
            result = TypedRecallResultV1.from_json(raw_result)
            if result.result_hash != str(row["result_hash"]):
                raise MemoryCorruptionError("typed recall result hash differs")
            trusted_now = _timestamp(self._now())
            if (
                typed_request.requested_at < result.evaluated_at
                or typed_request.requested_at > trusted_now
                or trusted_now >= result.authority_expires_at
            ):
                raise MemoryValidationError("typed_recall_result_expired")
            carriers: list[RecallResultPageBindingV1] = [
                RecallPageSelectedItemBindingV1(
                    RecallPageBindingKind.SELECTED_ITEM,
                    ordinal,
                    item.selected_item.item_id,
                    item.result_item_hash,
                )
                for ordinal, item in enumerate(result.items, start=1)
            ]
            carriers.extend(
                RecallPageConfirmationGroupBindingV1(
                    RecallPageBindingKind.CONFIRMATION_GROUP,
                    group.group,
                    group.result_group_hash,
                    tuple(
                        RecallPageConfirmationMemberBindingV1(
                            member.member.ordinal,
                            member.member.item_id,
                            member.result_member_hash,
                        )
                        for member in group.members
                    ),
                )
                for group in result.confirmation_groups
            )
            if typed_request.item_offset >= len(carriers):
                raise MemoryValidationError("typed_recall_page_offset_invalid")
            selected: list[RecallResultPageBindingV1] = []
            byte_count = 0
            for carrier in carriers[
                typed_request.item_offset : typed_request.item_offset
                + typed_request.max_items
            ]:
                size = len(canonical_json(carrier.to_json()).encode())
                if byte_count + size > typed_request.max_bytes:
                    break
                selected.append(carrier)
                byte_count += size
            if not selected:
                raise MemoryLimitError("typed_recall_page_budget_too_small")
            page = RecallResultPageV1(
                _stable_id(
                    "typed-recall-page",
                    typed_request.result_hash,
                    str(typed_request.page_ordinal),
                    str(typed_request.item_offset),
                    str(typed_request.max_items),
                    str(typed_request.max_bytes),
                ),
                typed_request.result_id,
                typed_request.result_hash,
                typed_request.page_ordinal,
                typed_request.item_offset,
                tuple(selected),
                byte_count,
                typed_request.item_offset + len(selected) == len(carriers),
            )
        return page

    async def authorize_recall_context_use(
        self,
        *,
        principal: MemoryPrincipal,
        request: RecallContextUseAuthorizationRequestV1,
        now: float | None = None,
    ) -> RecallContextUseReceiptV1:
        """Fence final provider use against the current recall authority epoch."""

        from simple_harness.runtime import (
            RecallContext,
            RecallContextUseAuthorizationRequestV1,
            RecallContextUseReceiptV1,
            RecallDecisionV4,
            TypedRecallResultV1,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(request) is not RecallContextUseAuthorizationRequestV1:
            raise TypeError("request must use RecallContextUseAuthorizationRequestV1")
        typed_request = cast(RecallContextUseAuthorizationRequestV1, request)
        if typed_request.subject != principal.actor_id:
            raise MemoryOwnershipConflict("typed_recall_context_use_subject_not_owned")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        effective_now = _timestamp(self._now() if now is None else now)
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                async with self._db.execute(
                    "SELECT * FROM recall_context_use_receipts WHERE principal_id=? "
                    "AND provider_attempt_id=?",
                    (principal.actor_id, typed_request.provider_attempt_id),
                ) as cursor:
                    replay_row = await cursor.fetchone()
                if replay_row is not None:
                    if str(replay_row["request_hash"]) != typed_request.request_hash:
                        raise MemoryIdempotencyConflict(
                            "RECALL_CONTEXT_USE_IDEMPOTENCY_CONFLICT"
                        )
                    raw_receipt = json.loads(str(replay_row["receipt_json"]))
                    if not isinstance(raw_receipt, dict):
                        raise MemoryCorruptionError("recall context-use receipt invalid")
                    replay = RecallContextUseReceiptV1.from_json(raw_receipt)
                    if replay.receipt_hash != str(replay_row["receipt_hash"]):
                        raise MemoryCorruptionError("recall context-use receipt hash differs")
                    replay.validate_request(typed_request)
                    await self._db.execute("COMMIT")
                    committed = True
                    return replay
                async with self._db.execute(
                    "SELECT r.*,q.principal_id,q.request_json AS recall_request_json "
                    "FROM typed_recall_results r "
                    "JOIN typed_recall_requests q ON q.request_id=r.request_id "
                    "WHERE r.result_id=?",
                    (typed_request.result_id,),
                ) as cursor:
                    result_row = await cursor.fetchone()
                if (
                    result_row is None
                    or str(result_row["principal_id"]) != principal.actor_id
                    or str(result_row["result_hash"]) != typed_request.result_hash
                    or str(result_row["decision_id"]) != typed_request.decision_id
                ):
                    raise MemoryValidationError("typed_recall_context_use_binding_invalid")
                async with self._db.execute(
                    "SELECT * FROM typed_recall_decisions WHERE decision_id=?",
                    (typed_request.decision_id,),
                ) as cursor:
                    decision_row = await cursor.fetchone()
                if (
                    decision_row is None
                    or str(decision_row["decision_hash"]) != typed_request.decision_hash
                ):
                    raise MemoryValidationError("typed_recall_context_use_binding_invalid")
                raw_decision = json.loads(str(decision_row["decision_json"]))
                raw_result = json.loads(str(result_row["result_json"]))
                if not isinstance(raw_decision, dict) or not isinstance(raw_result, dict):
                    raise MemoryCorruptionError("typed recall context-use body invalid")
                decision = RecallDecisionV4.from_json(raw_decision)
                result = TypedRecallResultV1.from_json(raw_result)
                raw_recall_request = json.loads(str(result_row["recall_request_json"]))
                if not isinstance(raw_recall_request, dict):
                    raise MemoryCorruptionError("typed recall request body invalid")
                raw_context = raw_recall_request.get("context")
                if not isinstance(raw_context, dict):
                    raise MemoryCorruptionError("typed recall context body invalid")
                stored_context = RecallContext.from_json(raw_context)
                if (
                    decision.decision_hash != typed_request.decision_hash
                    or result.result_hash != typed_request.result_hash
                ):
                    raise MemoryCorruptionError("typed recall context-use hash differs")
                result.validate_decision(decision)
                if (
                    typed_request.run_id != decision.run_id
                    or typed_request.subject != decision.subject
                    or typed_request.turn_id != stored_context.turn_id
                    or stored_context.run_id != decision.run_id
                    or stored_context.subject != decision.subject
                    or stored_context.context_hash != decision.context_hash
                    or stored_context.context_revision != decision.context_revision
                ):
                    raise MemoryValidationError(
                        "typed_recall_context_use_invocation_binding_invalid"
                    )
                epoch, policy_hash = await self._recall_authority_unlocked(
                    principal.actor_id
                )
                if (
                    epoch != result.authority_epoch
                    or policy_hash != result.policy_hash
                    or effective_now >= result.authority_expires_at
                ):
                    raise MemoryValidationError("RECALL_AUTHORITY_STALE")
                expected = {
                    item.selected_item.item_id: item.result_item_hash
                    for item in result.items
                }
                confirmation_groups: list[set[str]] = []
                for group in result.confirmation_groups:
                    member_ids = {member.member.item_id for member in group.members}
                    confirmation_groups.append(member_ids)
                    expected.update(
                        {
                            member.member.item_id: member.result_member_hash
                            for member in group.members
                        }
                    )
                supplied = {
                    item.item_id: item.item_hash for item in typed_request.item_bindings
                }
                if any(
                    expected.get(item_id) != item_hash
                    for item_id, item_hash in supplied.items()
                ):
                    raise MemoryValidationError("typed_recall_context_use_item_invalid")
                for member_ids in confirmation_groups:
                    if member_ids & supplied.keys() and not member_ids <= supplied.keys():
                        raise MemoryValidationError(
                            "typed_recall_confirmation_group_must_be_complete"
                        )
                await self._validate_recall_context_use_sources_unlocked(
                    principal_id=principal.actor_id,
                    result=result,
                    decision=decision,
                    supplied_item_ids=frozenset(supplied),
                    procedure_applicability_fingerprints=frozenset(
                        stored_context.procedure_applicability_fingerprints
                    ),
                    now=effective_now,
                )
                receipt = RecallContextUseReceiptV1(
                    _stable_id(
                        "recall-context-use-receipt",
                        principal.actor_id,
                        typed_request.provider_attempt_id,
                    ),
                    typed_request.request_hash,
                    principal.actor_id,
                    typed_request.run_id,
                    typed_request.turn_id,
                    typed_request.provider_attempt_id,
                    typed_request.decision_id,
                    typed_request.decision_hash,
                    typed_request.result_id,
                    typed_request.result_hash,
                    typed_request.item_bindings,
                    typed_request.snapshot_manifest_hash,
                    epoch,
                    policy_hash,
                    effective_now,
                    result.authority_expires_at,
                )
                await self._db.execute(
                    "INSERT INTO recall_context_use_receipts(receipt_id,principal_id,"
                    "provider_attempt_id,request_hash,request_json,receipt_json,receipt_hash,"
                    "authority_epoch,policy_hash,authorized_at,expires_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt.receipt_id,
                        principal.actor_id,
                        typed_request.provider_attempt_id,
                        typed_request.request_hash,
                        canonical_json(typed_request.to_json()),
                        canonical_json(receipt.to_json()),
                        receipt.receipt_hash,
                        epoch,
                        policy_hash,
                        effective_now,
                        receipt.expires_at,
                    ),
                )
                self._fault("typed_recall.context_use.before_commit")
                await self._db.execute("COMMIT")
                committed = True
                return receipt
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _validate_recall_context_use_sources_unlocked(
        self,
        *,
        principal_id: str,
        result: Any,
        decision: Any,
        supplied_item_ids: frozenset[str],
        procedure_applicability_fingerprints: frozenset[str],
        now: float,
    ) -> None:
        """Re-evaluate every bound durable source under the suppression transaction."""

        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        assert self._db is not None
        bound: list[tuple[Any, Any, bool]] = [
            (item.selected_item, item, False)
            for item in result.items
            if item.selected_item.item_id in supplied_item_ids
        ]
        bound.extend(
            (member.member, member, True)
            for group in result.confirmation_groups
            for member in group.members
            if member.member.item_id in supplied_item_ids
        )
        for source, typed_item, confirmation_member in bound:
            if confirmation_member or source.source_kind.value == "cognitive_memory":
                if confirmation_member:
                    query = (
                        "SELECT r.*,h.memory_type AS memory_type FROM cognitive_memory_revisions r "
                        "JOIN cognitive_memory_heads h ON h.memory_id=r.memory_id "
                        "JOIN cognitive_conflict_members m ON m.memory_id=r.memory_id "
                        "AND m.revision=r.revision JOIN cognitive_conflict_groups g "
                        "ON g.group_id=m.group_id LEFT JOIN cognitive_conflict_resolutions x "
                        "ON x.group_id=g.group_id WHERE r.memory_id=? AND r.revision=? "
                        "AND h.principal_id=? AND h.current_revision=g.challenger_revision "
                        "AND x.group_id IS NULL"
                    )
                else:
                    query = (
                        "SELECT r.*,h.memory_type AS memory_type FROM cognitive_memory_revisions r "
                        "JOIN cognitive_memory_heads h ON h.memory_id=r.memory_id "
                        "WHERE r.memory_id=? AND r.revision=? AND h.principal_id=? "
                        "AND h.current_revision=r.revision"
                    )
                async with self._db.execute(
                    query,
                    (source.source_ref, source.source_revision, principal_id),
                ) as cursor:
                    row = await cursor.fetchone()
                if (
                    row is None
                    or str(row["content_hash"]) != source.source_content_hash
                    or not self._cognitive_recall_state_allowed(
                        row, allow_contested=confirmation_member
                    )
                    or not self._cognitive_recall_valid_at(row, now)
                    or str(row["effective_privacy_class"])
                    != typed_item.effective_privacy_class.value
                    or tuple(sorted(json.loads(str(row["information_attributes_json"]))))
                    != tuple(item.value for item in typed_item.information_attributes)
                ):
                    raise MemoryValidationError("RECALL_AUTHORITY_STALE")
                if not await self._cognitive_recall_type_authority_allowed_unlocked(
                    row,
                    procedure_applicability_fingerprints=(
                        procedure_applicability_fingerprints
                    ),
                ):
                    raise MemoryValidationError("RECALL_AUTHORITY_STALE")
                _scopes, evidence_ids, _manifest = (
                    await self._cognitive_recall_lineage_unlocked(
                        source.source_ref, source.source_revision
                    )
                )
                suppressed = (
                    await self._resolve_suppression_unlocked(
                        SuppressionCandidate(principal_id, memory_id=source.source_ref),
                        OrdinaryMemoryPurpose.RECALL,
                    )
                ).denied
                for evidence_id in evidence_ids:
                    suppressed = suppressed or (
                        await self._resolve_suppression_unlocked(
                            SuppressionCandidate(principal_id, evidence_id=evidence_id),
                            OrdinaryMemoryPurpose.RECALL,
                        )
                    ).denied
                if suppressed or not self._candidate_disclosure_allowed(
                    decision.disclosure_context,
                    typed_item.effective_privacy_class.value,
                    tuple(item.value for item in typed_item.information_attributes),
                ):
                    raise MemoryValidationError("RECALL_AUTHORITY_STALE")
                continue
            async with self._db.execute(
                "SELECT * FROM short_horizon_chunks WHERE chunk_id=? AND principal_id=?",
                (source.source_ref, principal_id),
            ) as cursor:
                row = await cursor.fetchone()
            if (
                row is None
                or now >= float(row["expires_at"])
                or str(row["content_hash"]) != source.source_content_hash
                or str(row["effective_privacy_class"])
                != typed_item.effective_privacy_class.value
                or tuple(sorted(json.loads(str(row["information_attributes_json"]))))
                != tuple(item.value for item in typed_item.information_attributes)
            ):
                raise MemoryValidationError("RECALL_AUTHORITY_STALE")
            if not self._candidate_disclosure_allowed(
                decision.disclosure_context,
                typed_item.effective_privacy_class.value,
                tuple(item.value for item in typed_item.information_attributes),
            ):
                raise MemoryValidationError("RECALL_AUTHORITY_STALE")
            async with self._db.execute(
                "SELECT evidence_id FROM short_horizon_chunk_evidence WHERE chunk_id=?",
                (source.source_ref,),
            ) as cursor:
                evidence_ids = tuple(str(item[0]) for item in await cursor.fetchall())
            if not evidence_ids:
                raise MemoryValidationError("RECALL_AUTHORITY_STALE")
            for evidence_id in evidence_ids:
                if (
                    await self._resolve_suppression_unlocked(
                        SuppressionCandidate(principal_id, evidence_id=evidence_id),
                        OrdinaryMemoryPurpose.RECALL,
                    )
                ).denied:
                    raise MemoryValidationError("RECALL_AUTHORITY_STALE")

    async def _collect_typed_recall_confirmation(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float,
        deadline_monotonic: float,
    ) -> tuple[RecallConfirmationCandidate, ...]:
        from simple_harness_memory.core.recall import (
            RecallCandidate,
            RecallConfirmationCandidate,
        )
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        assert self._db is not None
        requested = {item.value for item in plan.requested_memory_types}
        found: list[
            tuple[RecallConfirmationCandidate, str, dict[str, float], float]
        ] = []
        async with self._write_lock:
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError
            async with self._db.execute(
                "SELECT g.* FROM cognitive_conflict_groups g "
                "JOIN cognitive_memory_heads h ON h.memory_id=g.memory_id "
                "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
                "AND r.revision=h.current_revision "
                "LEFT JOIN cognitive_conflict_resolutions x ON x.group_id=g.group_id "
                "WHERE g.principal_id=? AND h.current_revision=g.challenger_revision "
                "AND r.conflict_status='contested' AND x.group_id IS NULL "
                "ORDER BY g.created_at DESC,g.group_id",
                (principal.actor_id,),
            ) as cursor:
                groups = tuple(await cursor.fetchall())
            for group in groups:
                if time.monotonic() >= deadline_monotonic:
                    raise TimeoutError
                async with self._db.execute(
                    "SELECT m.*,r.*,h.memory_type AS memory_type "
                    "FROM cognitive_conflict_members m "
                    "JOIN cognitive_memory_revisions r ON r.memory_id=m.memory_id "
                    "AND r.revision=m.revision "
                    "JOIN cognitive_memory_heads h ON h.memory_id=m.memory_id "
                    "WHERE m.group_id=? ORDER BY m.ordinal",
                    (group["group_id"],),
                ) as cursor:
                    member_rows = tuple(await cursor.fetchall())
                if len(member_rows) != 2 or str(member_rows[0]["memory_type"]) not in requested:
                    continue
                members: list[RecallCandidate] = []
                group_has_requested_lane = False
                group_lane_scores: dict[str, float] = {}
                group_source_time = 0.0
                complete = True
                for row in member_rows:
                    if time.monotonic() >= deadline_monotonic:
                        raise TimeoutError
                    if (
                        str(row["memory_type"]) not in requested
                        or not self._cognitive_recall_state_allowed(
                            row, allow_contested=True
                        )
                        or not self._cognitive_recall_valid_at(row, now)
                    ):
                        complete = False
                        break
                    if not await self._cognitive_recall_type_authority_allowed_unlocked(
                        row,
                        procedure_applicability_fingerprints=frozenset(
                            context.procedure_applicability_fingerprints
                        ),
                    ):
                        complete = False
                        break
                    scopes, evidence_ids, evidence_hash = (
                        await self._cognitive_recall_lineage_unlocked(
                            str(row["memory_id"]), int(row["revision"])
                        )
                    )
                    if not evidence_ids or (
                        plan.task_scope_ids and not set(scopes) & set(plan.task_scope_ids)
                    ):
                        complete = False
                        break
                    denied = (
                        await self._resolve_suppression_unlocked(
                            SuppressionCandidate(
                                principal.actor_id, memory_id=str(row["memory_id"])
                            ),
                            OrdinaryMemoryPurpose.RECALL,
                        )
                    ).denied
                    for evidence_id in evidence_ids:
                        denied = denied or (
                            await self._resolve_suppression_unlocked(
                                SuppressionCandidate(principal.actor_id, evidence_id=evidence_id),
                                OrdinaryMemoryPurpose.RECALL,
                            )
                        ).denied
                    payload, source_time = await self._cognitive_public_payload_unlocked(row)
                    time_bounds = await self._cognitive_recall_time_bounds_unlocked(row)
                    time_requested = (
                        plan.earliest_occurred_at is not None
                        or plan.latest_occurred_at is not None
                    )
                    if time_requested and time_bounds is None:
                        complete = False
                        break
                    if time_bounds is not None:
                        time_start, time_end, source_time = time_bounds
                    else:
                        time_start = time_end = source_time
                    attrs = tuple(json.loads(str(row["information_attributes_json"])))
                    payload_text = canonical_json(payload).casefold()
                    query_terms = tuple(
                        term
                        for term in re.findall(
                            r"[\w\u3400-\u9fff]+", plan.query.casefold()
                        )
                        if term
                    )
                    lexical_score = sum(payload_text.count(term) for term in query_terms)
                    query_match = lexical_score > 0
                    entity_match = bool(plan.entity_constraints) and (
                        self._cognitive_typed_entity_match(
                            str(row["memory_type"]), payload, plan.entity_constraints
                        )
                    )
                    if plan.entity_constraints and not entity_match:
                        complete = False
                        break
                    if (
                        plan.earliest_occurred_at is not None
                        and time_end < plan.earliest_occurred_at
                    ) or (
                        plan.latest_occurred_at is not None
                        and time_start > plan.latest_occurred_at
                    ):
                        complete = False
                        break
                    if (
                        denied
                        or not self._candidate_disclosure_allowed(
                            plan.disclosure_context,
                            str(row["effective_privacy_class"]),
                            attrs,
                        )
                    ):
                        complete = False
                        break
                    lane_names: list[str] = []
                    if query_match and any(
                        mode.value == "full_text" for mode in plan.retrieval_modes
                    ):
                        lane_names.append("full_text")
                        group_lane_scores["full_text"] = max(
                            group_lane_scores.get("full_text", 0.0),
                            float(lexical_score),
                        )
                    if entity_match:
                        lane_names.append("entity")
                        group_lane_scores["entity"] = 1.0
                    if plan.task_scope_ids and set(scopes) & set(plan.task_scope_ids):
                        lane_names.append("task_scope")
                        scope_score = float(len(set(scopes) & set(plan.task_scope_ids)))
                        if context.active_task_scope_id in scopes:
                            scope_score += 1.0
                        group_lane_scores["task_scope"] = max(
                            group_lane_scores.get("task_scope", 0.0), scope_score
                        )
                    if (
                        plan.earliest_occurred_at is not None
                        or plan.latest_occurred_at is not None
                    ):
                        lane_names.append("temporal")
                        anchor = plan.latest_occurred_at or plan.earliest_occurred_at or now
                        temporal_score = 1.0 / (1.0 + abs(source_time - anchor))
                        group_lane_scores["temporal"] = max(
                            group_lane_scores.get("temporal", 0.0), temporal_score
                        )
                    group_has_requested_lane = group_has_requested_lane or bool(lane_names)
                    group_source_time = max(group_source_time, source_time)
                    members.append(
                        RecallCandidate(
                            "cognitive_memory",
                            str(row["memory_id"]),
                            int(row["revision"]),
                            str(row["memory_type"]),
                            payload,
                            str(row["content_hash"]),
                            str(row["effective_privacy_class"]),
                            tuple(sorted(set(attrs))),
                            evidence_hash,
                            scopes,
                            context.active_task_scope_id,
                            source_time,
                            (
                                context.expires_at
                                if row["valid_to"] is None
                                else min(context.expires_at, float(row["valid_to"]))
                            ),
                            tuple((lane, 1) for lane in lane_names),
                        )
                    )
                if complete and len(members) == 2 and group_has_requested_lane:
                    found.append(
                        (
                            RecallConfirmationCandidate(
                            str(group["group_id"]),
                            str(group["group_hash"]),
                            tuple(members),
                            ),
                            str(member_rows[0]["memory_type"]),
                            group_lane_scores,
                            group_source_time,
                        )
                    )
        lane_cap_items = min(128, max(32, 8 * plan.budget.max_items))
        lane_cap_groups = max(1, lane_cap_items // 2)
        lane_ranks: dict[str, dict[str, int]] = {}
        for memory_type in sorted({item[1] for item in found}):
            for lane in ("full_text", "entity", "task_scope", "temporal"):
                lane_items = [
                    item
                    for item in found
                    if item[1] == memory_type and lane in item[2]
                ]
                lane_items.sort(
                    key=lambda item: (
                        -item[2][lane],
                        -item[3],
                        item[0].conflict_group_id,
                    )
                )
                lane_ranks.setdefault(lane, {}).update(
                    {
                        item[0].conflict_group_id: rank
                        for rank, item in enumerate(
                            lane_items[:lane_cap_groups], start=1
                        )
                    }
                )
        weights = {
            "full_text": 0.30,
            "entity": 0.15,
            "task_scope": 0.10,
            "temporal": 0.05,
        }
        ranked = sorted(
            (
                item
                for item in found
                if any(
                    item[0].conflict_group_id in ranks
                    for ranks in lane_ranks.values()
                )
            ),
            key=lambda item: (
                -round(
                    sum(
                        weights[lane] / (60 + ranks[item[0].conflict_group_id])
                        for lane, ranks in lane_ranks.items()
                        if item[0].conflict_group_id in ranks
                    ),
                    12,
                ),
                -sum(
                    item[0].conflict_group_id in ranks
                    for ranks in lane_ranks.values()
                ),
                -item[3],
                item[0].conflict_group_id,
            ),
        )
        per_type_count: dict[str, int] = {}
        bounded: list[RecallConfirmationCandidate] = []
        for candidate, memory_type, _scores, _source_time in ranked:
            if per_type_count.get(memory_type, 0) + 2 > 128:
                continue
            bounded.append(candidate)
            per_type_count[memory_type] = per_type_count.get(memory_type, 0) + 2
        return tuple(bounded)

    async def _admit_typed_recall_request(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        request_digest: str,
        now: float,
    ) -> tuple[TypedRecallExecution | None, str, str]:
        from simple_harness.runtime import RecallDecisionV4, TypedRecallResultV1

        from simple_harness_memory.core.recall import TypedRecallExecution

        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                await self._ensure_typed_recall_principal_unlocked(principal, now)
                await self._ensure_recall_authority_unlocked(principal.actor_id, now)
                async with self._db.execute(
                    "SELECT * FROM typed_recall_requests WHERE principal_id=? "
                    "AND idempotency_key=?",
                    (principal.actor_id, plan.idempotency_key),
                ) as cursor:
                    request_row = await cursor.fetchone()
                if request_row is not None:
                    if str(request_row["request_hash"]) != request_digest:
                        raise MemoryIdempotencyConflict("IDEMPOTENCY_CONFLICT")
                    async with self._db.execute(
                        "SELECT * FROM typed_recall_terminals WHERE request_id=?",
                        (request_row["request_id"],),
                    ) as cursor:
                        terminal = await cursor.fetchone()
                    if terminal is not None:
                        if str(terminal["terminal_kind"]) == "deadline_exceeded":
                            raise TimeoutError("DEADLINE_EXCEEDED")
                        async with self._db.execute(
                            "SELECT decision_json FROM typed_recall_decisions "
                            "WHERE decision_id=?",
                            (terminal["decision_id"],),
                        ) as cursor:
                            decision_row = await cursor.fetchone()
                        async with self._db.execute(
                            "SELECT result_json FROM typed_recall_results WHERE result_id=?",
                            (terminal["result_id"],),
                        ) as cursor:
                            result_row = await cursor.fetchone()
                        if decision_row is None or result_row is None:
                            raise MemoryCorruptionError("typed recall terminal body missing")
                        decision_json = json.loads(str(decision_row[0]))
                        result_json = json.loads(str(result_row[0]))
                        if not isinstance(decision_json, dict) or not isinstance(result_json, dict):
                            raise MemoryCorruptionError("typed recall terminal body invalid")
                        decision = RecallDecisionV4.from_json(decision_json)
                        result = TypedRecallResultV1.from_json(result_json)
                        result.validate_decision(decision)
                        await self._db.execute("COMMIT")
                        committed = True
                        return (
                            TypedRecallExecution(
                                decision,
                                result,
                                False,
                                0,
                                True,
                                tuple(json.loads(str(terminal["unsupported_capabilities_json"]))),
                                tuple(json.loads(str(terminal["degradation_codes_json"]))),
                            ),
                            str(request_row["request_id"]),
                            str(terminal["attempt_id"]),
                        )
                    if now >= float(request_row["deadline_at"]):
                        async with self._db.execute(
                            "SELECT attempt_id FROM typed_recall_attempts WHERE request_id=? "
                            "ORDER BY attempt_ordinal DESC LIMIT 1",
                            (request_row["request_id"],),
                        ) as cursor:
                            attempt = await cursor.fetchone()
                        if attempt is None:
                            raise MemoryCorruptionError("typed recall attempt missing")
                        await self._insert_typed_recall_timeout_unlocked(
                            str(request_row["request_id"]), str(attempt[0]), now
                        )
                        await self._db.execute("COMMIT")
                        committed = True
                        raise TimeoutError("DEADLINE_EXCEEDED")
                    request_id = str(request_row["request_id"])
                    async with self._db.execute(
                        "SELECT COALESCE(MAX(attempt_ordinal),0)+1 FROM typed_recall_attempts "
                        "WHERE request_id=?",
                        (request_id,),
                    ) as cursor:
                        ordinal_row = await cursor.fetchone()
                    assert ordinal_row is not None
                    attempt_ordinal = int(ordinal_row[0])
                else:
                    request_id = _stable_id(
                        "typed-recall-request", principal.actor_id, plan.idempotency_key
                    )
                    request_json = canonical_json(
                        {
                            "schema_version": 1,
                            "principal_id": principal.actor_id,
                            "context": context.to_json(),
                            "plan": plan.to_json(),
                        }
                    )
                    await self._db.execute(
                        "INSERT INTO typed_recall_requests(request_id,principal_id,"
                        "idempotency_key,request_hash,request_json,deadline_at,created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            request_id,
                            principal.actor_id,
                            plan.idempotency_key,
                            request_digest,
                            request_json,
                            now + plan.budget.deadline_ms / 1000,
                            now,
                        ),
                    )
                    self._fault("typed_recall.after_request")
                    attempt_ordinal = 1
                attempt_id = _stable_id(
                    "typed-recall-attempt", request_id, str(attempt_ordinal)
                )
                attempt_json: dict[str, JsonValue] = {
                    "request_id": request_id,
                    "attempt_id": attempt_id,
                    "attempt_ordinal": attempt_ordinal,
                    "started_at": now,
                }
                await self._db.execute(
                    "INSERT INTO typed_recall_attempts(attempt_id,request_id,attempt_ordinal,"
                    "started_at,attempt_hash) VALUES(?,?,?,?,?)",
                    (
                        attempt_id,
                        request_id,
                        attempt_ordinal,
                        now,
                        hashlib.sha256(canonical_json(attempt_json).encode()).hexdigest(),
                    ),
                )
                self._fault("typed_recall.after_attempt")
                await self._db.execute("COMMIT")
                committed = True
                return None, request_id, attempt_id
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _collect_typed_recall_candidates(
        self,
        *,
        principal: MemoryPrincipal,
        context: RecallContext,
        plan: RecallPlan,
        now: float,
        deadline_monotonic: float,
    ) -> tuple[RecallCandidate, ...]:
        from simple_harness_memory.core.recall import RecallCandidate
        from simple_harness_memory.core.suppression import (
            OrdinaryMemoryPurpose,
            SuppressionCandidate,
        )

        assert self._db is not None
        requested_types = tuple(item.value for item in plan.requested_memory_types)
        candidates: list[RecallCandidate] = []
        lane_scores: dict[tuple[tuple[object, ...], str], float] = {}
        async with self._write_lock:
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError
            placeholders = ",".join("?" for _ in requested_types)
            if requested_types:
                async with self._db.execute(
                    "SELECT r.*,h.memory_type AS memory_type FROM cognitive_memory_heads h "
                    "JOIN cognitive_memory_revisions r "
                    "ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
                    f"WHERE h.principal_id=? AND h.memory_type IN ({placeholders}) "
                    "AND (r.valid_from IS NULL OR r.valid_from<=?) "
                    "AND (r.valid_to IS NULL OR ?<r.valid_to) "
                    "ORDER BY h.memory_type,h.memory_id",
                    (principal.actor_id, *requested_types, now, now),
                ) as cursor:
                    rows = tuple(await cursor.fetchall())
            else:
                rows = ()
            for row in rows:
                if time.monotonic() >= deadline_monotonic:
                    raise TimeoutError
                if not self._cognitive_recall_state_allowed(row):
                    continue
                if not await self._cognitive_recall_type_authority_allowed_unlocked(
                    row,
                    procedure_applicability_fingerprints=frozenset(
                        context.procedure_applicability_fingerprints
                    ),
                ):
                    continue
                scopes, evidence_ids, evidence_hash = await self._cognitive_recall_lineage_unlocked(
                    str(row["memory_id"]), int(row["revision"])
                )
                if plan.task_scope_ids and not set(scopes) & set(plan.task_scope_ids):
                    continue
                suppressed = (
                    await self._resolve_suppression_unlocked(
                        SuppressionCandidate(
                            principal.actor_id, memory_id=str(row["memory_id"])
                        ),
                        OrdinaryMemoryPurpose.RECALL,
                    )
                ).denied
                if not suppressed:
                    for evidence_id in evidence_ids:
                        if (
                            await self._resolve_suppression_unlocked(
                                SuppressionCandidate(principal.actor_id, evidence_id=evidence_id),
                                OrdinaryMemoryPurpose.RECALL,
                            )
                        ).denied:
                            suppressed = True
                            break
                if suppressed:
                    continue
                payload, source_time = await self._cognitive_public_payload_unlocked(row)
                time_bounds = await self._cognitive_recall_time_bounds_unlocked(row)
                time_requested = (
                    plan.earliest_occurred_at is not None
                    or plan.latest_occurred_at is not None
                )
                if time_requested and time_bounds is None:
                    continue
                if time_bounds is not None:
                    time_start, time_end, source_time = time_bounds
                else:
                    time_start = time_end = source_time
                attrs = tuple(json.loads(str(row["information_attributes_json"])))
                payload_text = canonical_json(payload).casefold()
                entity_match = self._cognitive_typed_entity_match(
                    str(row["memory_type"]), payload, plan.entity_constraints
                )
                if plan.entity_constraints and not entity_match:
                    continue
                if (
                    plan.earliest_occurred_at is not None
                    and time_end < plan.earliest_occurred_at
                ) or (
                    plan.latest_occurred_at is not None
                    and time_start > plan.latest_occurred_at
                ):
                    continue
                if not self._candidate_disclosure_allowed(
                    plan.disclosure_context,
                    str(row["effective_privacy_class"]),
                    attrs,
                ):
                    continue
                lane_values: list[tuple[str, float]] = []
                query_terms = tuple(
                    term
                    for term in re.findall(r"[\w\u3400-\u9fff]+", plan.query.casefold())
                    if term
                )
                lexical_score = sum(payload_text.count(term) for term in query_terms)
                if (
                    any(mode.value == "full_text" for mode in plan.retrieval_modes)
                    and lexical_score
                ):
                    lane_values.append(("full_text", float(lexical_score)))
                entity_score = int(entity_match)
                if entity_score:
                    lane_values.append(("entity", float(entity_score)))
                if plan.task_scope_ids and set(scopes) & set(plan.task_scope_ids):
                    scope_score = len(set(scopes) & set(plan.task_scope_ids))
                    if context.active_task_scope_id in scopes:
                        scope_score += 1
                    lane_values.append(("task_scope", float(scope_score)))
                if plan.earliest_occurred_at is not None or plan.latest_occurred_at is not None:
                    anchor = plan.latest_occurred_at or plan.earliest_occurred_at or now
                    lane_values.append(
                        ("temporal", 1.0 / (1.0 + abs(source_time - anchor)))
                    )
                if not lane_values:
                    continue
                candidate = RecallCandidate(
                        source_kind="cognitive_memory",
                        source_ref=str(row["memory_id"]),
                        source_revision=int(row["revision"]),
                        memory_type=str(row["memory_type"]),
                        public_payload=payload,
                        source_content_hash=str(row["content_hash"]),
                        effective_privacy_class=str(row["effective_privacy_class"]),
                        information_attributes=tuple(sorted(set(attrs))),
                        evidence_manifest_hash=evidence_hash,
                        source_task_scope_ids=scopes,
                        active_task_scope_id=context.active_task_scope_id,
                        source_time=source_time,
                        authority_expires_at=(
                            context.expires_at
                            if row["valid_to"] is None
                            else min(context.expires_at, float(row["valid_to"]))
                        ),
                        lane_ranks=tuple((name, 1) for name, _score in lane_values),
                )
                candidates.append(candidate)
                lane_scores.update(
                    {
                        (candidate.exact_key, lane): score
                        for lane, score in lane_values
                    }
                )
        # Assign deterministic per-lane ranks after every eligibility gate.
        ranked_lanes: dict[str, dict[tuple[object, ...], int]] = {}
        lane_cap = min(128, max(32, 8 * plan.budget.max_items))
        for lane in ("full_text", "entity", "task_scope", "temporal"):
            if time.monotonic() >= deadline_monotonic:
                raise TimeoutError
            for memory_type in requested_types:
                lane_items = [
                    item
                    for item in candidates
                    if item.memory_type == memory_type and lane in dict(item.lane_ranks)
                ]
                lane_items.sort(
                    key=lambda item: (
                        -lane_scores[(item.exact_key, lane)],
                        item.exact_key,
                    )
                )
                ranked_lanes.setdefault(lane, {}).update(
                    {
                        item.exact_key: rank
                        for rank, item in enumerate(lane_items[:lane_cap], start=1)
                    }
                )
        normalized = tuple(
            RecallCandidate(
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                source_revision=item.source_revision,
                memory_type=item.memory_type,
                public_payload=item.public_payload,
                source_content_hash=item.source_content_hash,
                effective_privacy_class=item.effective_privacy_class,
                information_attributes=item.information_attributes,
                evidence_manifest_hash=item.evidence_manifest_hash,
                source_task_scope_ids=item.source_task_scope_ids,
                active_task_scope_id=item.active_task_scope_id,
                source_time=item.source_time,
                authority_expires_at=item.authority_expires_at,
                lane_ranks=tuple(
                    (lane, ranks[item.exact_key])
                    for lane, ranks in ranked_lanes.items()
                    if item.exact_key in ranks
                ),
            )
            for item in candidates
            if any(item.exact_key in ranks for ranks in ranked_lanes.values())
        )
        by_type: dict[str | None, list[RecallCandidate]] = {}
        for item in normalized:
            by_type.setdefault(item.memory_type, []).append(item)
        bounded: list[RecallCandidate] = []
        from simple_harness_memory.core.recall import rank_candidates

        for memory_type in sorted(by_type, key=lambda item: "" if item is None else item):
            bounded.extend(rank_candidates(tuple(by_type[memory_type]))[:128])
        return tuple(bounded)

    async def _cognitive_recall_lineage_unlocked(
        self, memory_id: str, revision: int
    ) -> tuple[tuple[str, ...], tuple[str, ...], str]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT task_scope_id,evidence_id FROM cognitive_revision_task_scope_origins "
            "WHERE memory_id=? AND revision=? ORDER BY task_scope_id,registration_id",
            (memory_id, revision),
        ) as cursor:
            origin_rows = tuple(await cursor.fetchall())
        async with self._db.execute(
            "SELECT evidence_id,span_id,quote_hash FROM cognitive_evidence_spans "
            "WHERE memory_id=? AND revision=? ORDER BY ordinal",
            (memory_id, revision),
        ) as cursor:
            evidence_rows = tuple(await cursor.fetchall())
        scopes = tuple(dict.fromkeys(str(row[0]) for row in origin_rows))
        evidence_ids = tuple(dict.fromkeys(str(row[0]) for row in evidence_rows))
        manifest = cast(JsonValue, sorted({str(row[0]) for row in evidence_rows}))
        return scopes, evidence_ids, hashlib.sha256(canonical_json(manifest).encode()).hexdigest()

    @staticmethod
    def _cognitive_typed_entity_match(
        memory_type: str,
        payload: Mapping[str, JsonValue],
        constraints: tuple[str, ...],
    ) -> bool:
        if not constraints:
            return False
        typed_values: list[str] = []
        if memory_type == "episode":
            participants = payload.get("participants")
            if isinstance(participants, list):
                typed_values.extend(str(item) for item in participants)
        elif memory_type == "semantic":
            typed_values.append(str(payload.get("subject_entity", "")))
            object_value = payload.get("object_value")
            if isinstance(object_value, str):
                typed_values.append(object_value)
            elif isinstance(object_value, dict):
                for key in ("entity_id", "entity_ref"):
                    entity_value = object_value.get(key)
                    if isinstance(entity_value, str):
                        typed_values.append(entity_value)
        elif memory_type == "procedure":
            applicability = payload.get("applicability")
            if isinstance(applicability, list):
                typed_values.extend(str(item) for item in applicability)
        else:
            trigger = payload.get("trigger")
            if isinstance(trigger, dict):
                authority_ref = trigger.get("event_authority_ref")
                if isinstance(authority_ref, str):
                    typed_values.append(authority_ref)
        normalized = {item.casefold() for item in typed_values}
        return any(item.casefold() in normalized for item in constraints)

    async def _cognitive_recall_time_bounds_unlocked(
        self, row: aiosqlite.Row
    ) -> tuple[float, float, float] | None:
        assert self._db is not None
        memory_type = str(row["memory_type"])
        memory_id = str(row["memory_id"])
        revision = int(row["revision"])
        if memory_type == "episode":
            async with self._db.execute(
                "SELECT occurred_start,occurred_end FROM episode_records "
                "WHERE memory_id=? AND revision=?",
                (memory_id, revision),
            ) as cursor:
                typed = await cursor.fetchone()
            if typed is None:
                return None
            start = float(typed[0])
            end = start if typed[1] is None else float(typed[1])
            return start, end, start
        if memory_type == "semantic":
            anchor = float(row["created_at"])
            start = anchor if row["valid_from"] is None else float(row["valid_from"])
            end = float("inf") if row["valid_to"] is None else float(row["valid_to"])
            return start, end, anchor
        if memory_type == "procedure":
            async with self._db.execute(
                "SELECT MAX(source_time) FROM ("
                "SELECT occurred_at AS source_time FROM procedure_observations "
                "WHERE memory_id=? AND procedure_revision<=? AND attributable=1 "
                "UNION ALL SELECT e.created_at AS source_time "
                "FROM cognitive_evidence_spans s JOIN evidence_envelopes e "
                "ON e.evidence_id=s.evidence_id WHERE s.memory_id=? AND s.revision=?"
                ")",
                (memory_id, revision, memory_id, revision),
            ) as cursor:
                typed = await cursor.fetchone()
            if typed is None or typed[0] is None:
                return None
            anchor = float(typed[0])
            return anchor, anchor, anchor
        async with self._db.execute(
            "SELECT due_at FROM prospective_records WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        ) as cursor:
            typed = await cursor.fetchone()
        if typed is None:
            return None
        if typed[0] is not None and str(row["lifecycle_state"]) in {"pending", "rescheduled"}:
            anchor = float(typed[0])
            return anchor, anchor, anchor
        async with self._db.execute(
            "SELECT MAX(decided_at) FROM prospective_signal_decisions "
            "WHERE memory_id=? AND committed_revision<=?",
            (memory_id, revision),
        ) as cursor:
            transition = await cursor.fetchone()
        if transition is None or transition[0] is None:
            return None
        anchor = float(transition[0])
        return anchor, anchor, anchor

    async def _cognitive_recall_type_authority_allowed_unlocked(
        self,
        row: aiosqlite.Row,
        *,
        procedure_applicability_fingerprints: frozenset[str],
    ) -> bool:
        """Fail closed on type-specific current runtime authorities."""

        from simple_harness_memory.core.lifecycle_results import (
            UNBOUND_PROCEDURE_APPLICABILITY,
        )

        assert self._db is not None
        memory_type = str(row["memory_type"])
        if memory_type == "procedure":
            async with self._db.execute(
                "SELECT applicability_fingerprint FROM procedure_records "
                "WHERE memory_id=? AND revision=?",
                (row["memory_id"], row["revision"]),
            ) as cursor:
                procedure = await cursor.fetchone()
            return bool(
                procedure is not None
                and str(procedure[0]) != UNBOUND_PROCEDURE_APPLICABILITY
                and str(procedure[0]) in procedure_applicability_fingerprints
            )
        if memory_type != "prospective":
            return True
        async with self._db.execute(
            "SELECT trigger_json FROM prospective_records "
            "WHERE memory_id=? AND revision=?",
            (row["memory_id"], row["revision"]),
        ) as cursor:
            prospective = await cursor.fetchone()
        if prospective is None:
            return False
        _trigger, trigger_hash = self._decode_prospective_trigger(
            str(prospective["trigger_json"])
        )
        if str(row["lifecycle_state"]) in {"triggered", "in_progress"}:
            async with self._db.execute(
                "SELECT 1 FROM prospective_signal_decisions d "
                "JOIN prospective_trigger_events e ON e.consumption_id=d.consumption_id "
                "WHERE d.memory_id=? AND d.committed_revision<=? "
                "AND d.transition_to IN ('triggered','in_progress') "
                "AND e.trigger_fingerprint=? AND e.outcome='matched' "
                "ORDER BY d.committed_revision DESC LIMIT 1",
                (row["memory_id"], row["revision"], trigger_hash),
            ) as cursor:
                return await cursor.fetchone() is not None
        async with self._db.execute(
            "SELECT state,trigger_hash FROM prospective_scheduler_registrations "
            "WHERE memory_id=? AND prospective_revision=? "
            "ORDER BY occurred_at DESC,registration_revision DESC LIMIT 1",
            (row["memory_id"], row["revision"]),
        ) as cursor:
            registration = await cursor.fetchone()
        return bool(
            registration is not None
            and str(registration["state"]) == "accepted"
            and str(registration["trigger_hash"]) == trigger_hash
        )

    async def _cognitive_public_payload_unlocked(
        self, row: aiosqlite.Row
    ) -> tuple[dict[str, JsonValue], float]:
        assert self._db is not None
        memory_id = str(row["memory_id"])
        revision = int(row["revision"])
        memory_type = str(row["memory_type"])
        table_by_type = {
            "episode": "episode_records",
            "semantic": "semantic_claims",
            "procedure": "procedure_records",
            "prospective": "prospective_records",
        }
        async with self._db.execute(
            f"SELECT * FROM {table_by_type[memory_type]} WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        ) as cursor:
            payload_row = await cursor.fetchone()
        if payload_row is None:
            raise MemoryCorruptionError("typed recall payload missing")
        if memory_type == "episode":
            return (
                {
                    "title": str(payload_row["title"]),
                    "participants": json.loads(str(payload_row["participants_json"])),
                    "goals": json.loads(str(payload_row["goals_json"])),
                    "actions": json.loads(str(payload_row["actions_json"])),
                    "results": json.loads(str(payload_row["results_json"])),
                    "impacts": json.loads(str(payload_row["impacts_json"])),
                    "occurred_start": float(payload_row["occurred_start"]),
                    "occurred_end": payload_row["occurred_end"],
                },
                float(payload_row["occurred_start"]),
            )
        if memory_type == "semantic":
            return (
                {
                    "subject_entity": str(payload_row["subject_entity"]),
                    "predicate": str(payload_row["predicate"]),
                    "object_value": json.loads(str(payload_row["object_json"])),
                    "qualifiers": json.loads(str(payload_row["qualifiers_json"])),
                },
                float(row["created_at"]),
            )
        if memory_type == "procedure":
            return (
                {
                    "name": str(payload_row["name"]),
                    "applicability": json.loads(str(payload_row["applicability_json"])),
                    "steps": json.loads(str(payload_row["steps_json"])),
                    "effective_risk": str(payload_row["risk_level"]),
                },
                float(row["created_at"]),
            )
        return (
            {
                "action": str(payload_row["action_text"]),
                "trigger": json.loads(str(payload_row["trigger_json"])),
            },
            float(payload_row["due_at"] or row["created_at"]),
        )

    @staticmethod
    def _cognitive_recall_state_allowed(
        row: aiosqlite.Row, *, allow_contested: bool = False
    ) -> bool:
        lifecycle = {
            "episode": {"active", "amended"},
            "semantic": {"active"},
            "procedure": {"active", "reinforced"},
            "prospective": {"pending", "triggered", "in_progress", "rescheduled"},
        }
        memory_type = str(row["memory_type"])
        allowed_conflicts = {"uncontested", "resolved"}
        if allow_contested:
            allowed_conflicts.add("contested")
        if str(row["lifecycle_state"]) not in lifecycle[memory_type] or str(
            row["conflict_status"]
        ) not in allowed_conflicts:
            return False
        epistemic = str(row["epistemic_status"])
        verification = str(row["verification_state"])
        if memory_type in {"episode", "semantic"}:
            return (epistemic, verification) in {
                ("explicit_user", "source_bound"),
                ("explicit_user", "user_confirmed"),
                ("verified_external", "source_verified"),
                ("observed_behavior", "source_verified"),
                ("observed_behavior", "repeated_observation"),
            }
        if memory_type == "procedure":
            return (epistemic, verification) in {
                ("explicit_user", "source_bound"),
                ("explicit_user", "user_confirmed"),
                ("observed_behavior", "repeated_observation"),
            }
        return epistemic == "explicit_user" and verification in {
            "source_bound",
            "user_confirmed",
        }

    @staticmethod
    def _cognitive_recall_valid_at(row: aiosqlite.Row, now: float) -> bool:
        return (row["valid_from"] is None or float(row["valid_from"]) <= now) and (
            row["valid_to"] is None or now < float(row["valid_to"])
        )

    @staticmethod
    def _ordinary_recall_disclosure_allowed(disclosure: DisclosureContext) -> bool:
        return (
            disclosure.recipient.value in {"user_self", "household", "task_collaborator"}
            and disclosure.purpose.value
            in {"task_execution", "personalization", "task_resume", "user_review"}
            and disclosure.trust.value == "trusted_authority"
            and disclosure.generation.value == "current"
        )

    @staticmethod
    def _candidate_disclosure_allowed(
        disclosure: DisclosureContext, privacy: str, attributes: tuple[str, ...]
    ) -> bool:
        recipient = disclosure.recipient.value
        purpose = disclosure.purpose.value
        if recipient == "user_self":
            return purpose in {
                "task_execution",
                "personalization",
                "task_resume",
                "user_review",
            } and privacy in {"public", "personal", "sensitive"}
        sensitive = {"identity", "relationship", "family", "health", "location", "financial"}
        return (
            recipient in {"household", "task_collaborator"}
            and purpose in {"task_execution", "task_resume"}
            and privacy == "public"
            and not sensitive.intersection(attributes)
        )

    async def _ensure_typed_recall_principal_unlocked(
        self, principal: MemoryPrincipal, now: float
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,created_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO NOTHING",
            (
                principal.actor_id,
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
                now,
            ),
        )
        await self._authorize_short_horizon_principal_unlocked(principal)

    async def _ensure_recall_authority_unlocked(self, principal_id: str, now: float) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT 1 FROM recall_authority_heads WHERE principal_id=?", (principal_id,)
        ) as cursor:
            if await cursor.fetchone() is not None:
                return
        event_id = _stable_id("recall-authority-event", principal_id, "1")
        payload: dict[str, JsonValue] = {
            "event_id": event_id,
            "principal_id": principal_id,
            "previous_epoch": 0,
            "authority_epoch": 1,
            "event_kind": "initialized",
            "source_ref_hash": hashlib.sha256(b"fresh-v6").hexdigest(),
            "policy_hash": _RECALL_POLICY_HASH,
            "created_at": now,
        }
        event_hash = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        await self._db.execute(
            "INSERT INTO recall_authority_events(event_id,principal_id,previous_epoch,"
            "authority_epoch,event_kind,source_ref_hash,policy_hash,event_json,event_hash,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                principal_id,
                0,
                1,
                "initialized",
                payload["source_ref_hash"],
                _RECALL_POLICY_HASH,
                canonical_json(payload),
                event_hash,
                now,
            ),
        )
        await self._db.execute(
            "INSERT INTO recall_authority_heads(principal_id,authority_epoch,policy_hash,"
            "updated_at) VALUES(?,?,?,?)",
            (principal_id, 1, _RECALL_POLICY_HASH, now),
        )

    async def _recall_authority_unlocked(self, principal_id: str) -> tuple[int, str]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT authority_epoch,policy_hash FROM recall_authority_heads "
            "WHERE principal_id=?",
            (principal_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise MemoryCorruptionError("recall authority head missing")
        return int(row[0]), str(row[1])

    async def _advance_recall_authority_unlocked(
        self,
        principal_id: str,
        *,
        event_kind: str,
        source_ref: str,
        now: float,
    ) -> tuple[int, str]:
        """Append one immutable authority event and CAS the mutable head in one tx."""

        assert self._db is not None
        await self._ensure_recall_authority_unlocked(principal_id, now)
        previous_epoch, previous_policy_hash = await self._recall_authority_unlocked(
            principal_id
        )
        authority_epoch = previous_epoch + 1
        event_id = _stable_id(
            "recall-authority-event", principal_id, str(authority_epoch), source_ref
        )
        payload: dict[str, JsonValue] = {
            "event_id": event_id,
            "principal_id": principal_id,
            "previous_epoch": previous_epoch,
            "authority_epoch": authority_epoch,
            "event_kind": event_kind,
            "source_ref_hash": _opaque_hash(source_ref),
            "policy_hash": _RECALL_POLICY_HASH,
            "previous_policy_hash": previous_policy_hash,
            "created_at": now,
        }
        event_json = canonical_json(payload)
        event_hash = hashlib.sha256(event_json.encode()).hexdigest()
        await self._db.execute(
            "INSERT INTO recall_authority_events(event_id,principal_id,previous_epoch,"
            "authority_epoch,event_kind,source_ref_hash,policy_hash,event_json,event_hash,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                principal_id,
                previous_epoch,
                authority_epoch,
                event_kind,
                payload["source_ref_hash"],
                _RECALL_POLICY_HASH,
                event_json,
                event_hash,
                now,
            ),
        )
        cursor = await self._db.execute(
            "UPDATE recall_authority_heads SET authority_epoch=?,policy_hash=?,updated_at=? "
            "WHERE principal_id=? AND authority_epoch=? AND policy_hash=?",
            (
                authority_epoch,
                _RECALL_POLICY_HASH,
                now,
                principal_id,
                previous_epoch,
                previous_policy_hash,
            ),
        )
        if cursor.rowcount != 1:
            raise MemoryWriterConflict("recall_authority_head_cas_conflict")
        return authority_epoch, _RECALL_POLICY_HASH

    async def _persist_typed_recall_terminal_unlocked(
        self,
        *,
        request_id: str,
        attempt_id: str,
        execution: TypedRecallExecution,
        terminal_kind: str,
        now: float,
        deadline_monotonic: float,
    ) -> None:
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            if time.monotonic() >= deadline_monotonic:
                await self._insert_typed_recall_timeout_unlocked(
                    request_id, attempt_id, now
                )
                await self._db.execute("COMMIT")
                committed = True
                raise TimeoutError("DEADLINE_EXCEEDED")
            decision = execution.decision
            result = execution.result
            await self._db.execute(
                "INSERT INTO typed_recall_decisions(decision_id,request_id,decision_json,"
                "decision_hash,created_at) VALUES(?,?,?,?,?)",
                (
                    decision.decision_id,
                    request_id,
                    canonical_json(decision.to_json()),
                    decision.decision_hash,
                    now,
                ),
            )
            self._fault("typed_recall.after_decision_header")
            flat_decision_items = list(decision.selected_items)
            flat_decision_items.extend(
                member for group in decision.confirmation_groups for member in group.members
            )
            for ordinal, item in enumerate(flat_decision_items, start=1):
                await self._db.execute(
                    "INSERT INTO typed_recall_decision_items(decision_id,ordinal,item_id,"
                    "item_kind,item_json,item_hash) VALUES(?,?,?,?,?,?)",
                    (
                        decision.decision_id,
                        ordinal,
                        item.item_id,
                        item.item_kind.value,
                        canonical_json(item.to_json()),
                        item.item_hash,
                    ),
                )
                self._fault("typed_recall.after_decision_item")
            await self._db.execute(
                "INSERT INTO typed_recall_results(result_id,request_id,decision_id,"
                "authority_epoch,policy_hash,result_json,result_hash,authority_expires_at,"
                "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    result.result_id,
                    request_id,
                    decision.decision_id,
                    result.authority_epoch,
                    result.policy_hash,
                    canonical_json(result.to_json()),
                    result.result_hash,
                    result.authority_expires_at,
                    now,
                ),
            )
            self._fault("typed_recall.after_result_header")
            for ordinal, item in enumerate(result.items, start=1):
                await self._db.execute(
                    "INSERT INTO typed_recall_result_items(result_id,ordinal,item_id,"
                    "result_item_json,result_item_hash) VALUES(?,?,?,?,?)",
                    (
                        result.result_id,
                        ordinal,
                        item.selected_item.item_id,
                        canonical_json(item.to_json()),
                        item.result_item_hash,
                    ),
                )
                self._fault("typed_recall.after_result_item")
            for group_ordinal, typed_group in enumerate(
                result.confirmation_groups, start=1
            ):
                await self._db.execute(
                    "INSERT INTO typed_recall_confirmation_groups(result_id,ordinal,"
                    "group_id,group_json,group_hash) VALUES(?,?,?,?,?)",
                    (
                        result.result_id,
                        group_ordinal,
                        typed_group.group.conflict_group_id,
                        canonical_json(typed_group.to_json()),
                        typed_group.result_group_hash,
                    ),
                )
                for member_ordinal, typed_member in enumerate(typed_group.members, start=1):
                    await self._db.execute(
                        "INSERT INTO typed_recall_confirmation_members(result_id,"
                        "group_ordinal,member_ordinal,item_id,member_json,member_hash) "
                        "VALUES(?,?,?,?,?,?)",
                        (
                            result.result_id,
                            group_ordinal,
                            member_ordinal,
                            typed_member.member.item_id,
                            canonical_json(typed_member.to_json()),
                            typed_member.result_member_hash,
                        ),
                    )
                    self._fault("typed_recall.after_result_item")
            terminal_json: dict[str, JsonValue] = {
                "request_id": request_id,
                "attempt_id": attempt_id,
                "terminal_kind": terminal_kind,
                "decision_id": decision.decision_id,
                "decision_hash": decision.decision_hash,
                "result_id": result.result_id,
                "result_hash": result.result_hash,
                "candidate_query_started": execution.candidate_query_started,
                "candidate_query_count": execution.candidate_query_count,
                "unsupported_capabilities": list(execution.unsupported_capabilities),
                "degradation_codes": list(execution.degradation_codes),
                "created_at": now,
            }
            terminal_hash = hashlib.sha256(canonical_json(terminal_json).encode()).hexdigest()
            await self._db.execute(
                "INSERT INTO typed_recall_terminals(request_id,attempt_id,terminal_kind,"
                "decision_id,decision_hash,result_id,result_hash,candidate_query_started,"
                "candidate_query_count,"
                "unsupported_capabilities_json,degradation_codes_json,terminal_json,"
                "terminal_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    attempt_id,
                    terminal_kind,
                    decision.decision_id,
                    decision.decision_hash,
                    result.result_id,
                    result.result_hash,
                    int(execution.candidate_query_started),
                    execution.candidate_query_count,
                    canonical_json(list(execution.unsupported_capabilities)),
                    canonical_json(list(execution.degradation_codes)),
                    canonical_json(terminal_json),
                    terminal_hash,
                    now,
                ),
            )
            self._fault("typed_recall.after_terminal")
            self._fault("typed_recall.before_commit")
            if time.monotonic() >= deadline_monotonic:
                await self._db.execute("ROLLBACK")
                await self._db.execute("BEGIN IMMEDIATE")
                await self._insert_typed_recall_timeout_unlocked(
                    request_id, attempt_id, now
                )
                await self._db.execute("COMMIT")
                committed = True
                raise TimeoutError("DEADLINE_EXCEEDED")
            await self._db.execute("COMMIT")
            committed = True
            self._fault("typed_recall.after_commit")
        finally:
            if not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")

    async def _persist_typed_recall_timeout(
        self, *, request_id: str, attempt_id: str, now: float
    ) -> None:
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                await self._insert_typed_recall_timeout_unlocked(request_id, attempt_id, now)
                await self._db.execute("COMMIT")
                committed = True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _insert_typed_recall_timeout_unlocked(
        self, request_id: str, attempt_id: str, now: float
    ) -> None:
        assert self._db is not None
        terminal_json: dict[str, JsonValue] = {
            "request_id": request_id,
            "attempt_id": attempt_id,
            "terminal_kind": "deadline_exceeded",
            "candidate_query_started": False,
            "candidate_query_count": 0,
            "unsupported_capabilities": [],
            "degradation_codes": [],
            "created_at": now,
        }
        await self._db.execute(
            "INSERT INTO typed_recall_terminals(request_id,attempt_id,terminal_kind,"
            "decision_id,decision_hash,result_id,result_hash,candidate_query_started,"
            "candidate_query_count,"
            "unsupported_capabilities_json,degradation_codes_json,terminal_json,terminal_hash,"
            "created_at) VALUES(?,?,\'deadline_exceeded\',NULL,NULL,NULL,NULL,0,0,?,?,?,?,?)",
            (
                request_id,
                attempt_id,
                "[]",
                "[]",
                canonical_json(terminal_json),
                hashlib.sha256(canonical_json(terminal_json).encode()).hexdigest(),
                now,
            ),
        )

    async def record_procedure_observation(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProcedureObservationAuthorityRef,
    ) -> ProcedureObservationApplyResult:
        """Consume one ref-only Host observation and atomically advance Procedure state."""

        from simple_harness.runtime import (
            ProcedureHazard,
            ProcedureLifecycleState,
            ProcedureObservationAuthorityRef,
            ProcedureObservationKind,
            ProcedureObservationOutcome,
            ProcedureRiskLevel,
            verify_procedure_observation_authority,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
        from simple_harness_memory.core.lifecycle_results import (
            UNBOUND_PROCEDURE_APPLICABILITY,
            ProcedureObservationApplyResult,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(scope) is not MemoryScope:
            raise TypeError("scope must use MemoryScope")
        if type(reference) is not ProcedureObservationAuthorityRef:
            raise TypeError("reference must use ProcedureObservationAuthorityRef")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        scope.authorize(principal)
        try:
            replay = await self._read_procedure_result_unlocked(
                principal=principal, scope=scope, reference=reference
            )
        except MemoryErrorBase as exc:
            await self._append_lifecycle_rejection_audit(
                table="procedure_observation_rejections",
                domain="procedure-observation",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code=str(exc),
            )
            raise
        if replay is not None:
            return replay
        if self._procedure_observation_authority is None:
            await self._append_lifecycle_rejection_audit(
                table="procedure_observation_rejections",
                domain="procedure-observation",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code="procedure_observation_authority_required",
            )
            raise MemoryValidationError("procedure_observation_authority_required")
        try:
            resolved_at = _timestamp(self._now())
            authority = await verify_procedure_observation_authority(
                reference,
                self._procedure_observation_authority,
                current_time=resolved_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            await self._append_lifecycle_rejection_audit(
                table="procedure_observation_rejections",
                domain="procedure-observation",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code="procedure_observation_authority_rejected",
            )
            raise MemoryValidationError("procedure_observation_authority_rejected") from exc
        intent = authority.intent
        try:
            if intent.subject != principal.actor_id:
                raise MemoryOwnershipConflict("procedure_observation_subject_differs")
            if (intent.scope.kind.value, intent.scope.owner_id) != (
                scope.kind.value,
                scope.owner_id,
            ):
                raise MemoryOwnershipConflict("procedure_observation_scope_differs")
            async with self._write_lock:
                self._fault("procedure.before_begin")
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
                committed = False
                try:
                    self._fault("procedure.after_begin")
                    replay = await self._read_procedure_result_unlocked(
                        principal=principal, scope=scope, reference=reference
                    )
                    if replay is not None:
                        await self._db.execute("COMMIT")
                        committed = True
                        return replay
                    consumed_at = _timestamp(self._now())
                    if consumed_at < authority.issued_at or consumed_at >= authority.expires_at:
                        raise MemoryValidationError("procedure_observation_authority_expired")
                    async with self._db.execute(
                        "SELECT h.memory_type,h.current_revision,h.scope_kind,h.scope_owner,"
                        "r.lifecycle_state,p.risk_level,p.qualification_epoch,"
                        "p.applicability_fingerprint,p.bound_hazard "
                        "FROM cognitive_memory_heads h JOIN cognitive_memory_revisions r "
                        "ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
                        "JOIN procedure_records p ON p.memory_id=r.memory_id "
                        "AND p.revision=r.revision WHERE h.principal_id=? "
                        "AND h.deployment_id=? AND h.household_id=? AND h.memory_id=?",
                        (
                            principal.actor_id,
                            principal.deployment_id,
                            principal.household_id,
                            intent.target_memory_id,
                        ),
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise MemoryValidationError("procedure_observation_target_not_found")
                    if str(row[0]) != "procedure":
                        raise MemoryValidationError("procedure_observation_target_type_differs")
                    if (str(row[2]), str(row[3])) != (
                        scope.kind.value,
                        scope.owner_id,
                    ):
                        raise MemoryOwnershipConflict("procedure_observation_scope_differs")
                    base_revision = int(row[1])
                    if base_revision != intent.target_revision:
                        raise MemoryWriterConflict("procedure_observation_revision_stale")
                    current_state = ProcedureLifecycleState(str(row[4]))
                    if current_state is not intent.transition_from:
                        raise MemoryWriterConflict("procedure_observation_lifecycle_stale")
                    if str(row[5]) != intent.risk_level.value:
                        raise MemoryValidationError("procedure_observation_risk_differs")
                    qualification_epoch = str(row[6])
                    current_fingerprint = str(row[7])
                    current_hazard = None if row[8] is None else str(row[8])
                    await self._verify_procedure_evidence_unlocked(intent)
                    if intent.observed_at > consumed_at:
                        raise MemoryValidationError("procedure_observation_occurred_at_future")
                    bound_fingerprint = current_fingerprint
                    bound_hazard = current_hazard
                    reason_code = "procedure_observation_recorded"
                    if current_fingerprint == UNBOUND_PROCEDURE_APPLICABILITY:
                        bound_fingerprint = intent.applicability.fingerprint
                        bound_hazard = intent.hazard.value
                        reason_code = "procedure_applicability_bound"
                    fingerprint_matches = bound_fingerprint == intent.applicability.fingerprint
                    hazard_matches = bound_hazard == intent.hazard.value
                    window_start = max(0.0, consumed_at - 90.0 * 24.0 * 60.0 * 60.0)
                    async with self._db.execute(
                        "SELECT COUNT(*),SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END) "
                        "FROM procedure_observations WHERE memory_id=? "
                        "AND qualification_epoch=? AND applicability_fingerprint=? "
                        "AND occurred_at>=? AND occurred_at<=? AND ("
                        "(outcome='success' AND attributable=1) OR outcome='failure')",
                        (
                            intent.target_memory_id,
                            qualification_epoch,
                            bound_fingerprint,
                            window_start,
                            consumed_at,
                        ),
                    ) as cursor:
                        count_row = await cursor.fetchone()
                    if count_row is None:
                        raise MemoryCorruptionError("procedure evidence count is missing")
                    failure_count = int(count_row[1] or 0)
                    success_count = int(count_row[0]) - failure_count
                    counts_in_window = (
                        intent.observed_at >= window_start and intent.observed_at <= consumed_at
                    )
                    next_state = current_state
                    if not fingerprint_matches or not hazard_matches:
                        next_state = ProcedureLifecycleState.INAPPLICABLE
                        reason_code = "procedure_applicability_or_hazard_drift"
                    elif intent.kind is ProcedureObservationKind.TERMINAL_OUTCOME:
                        if intent.outcome is ProcedureObservationOutcome.FAILURE:
                            if counts_in_window:
                                failure_count += 1
                            if intent.attributable:
                                next_state = ProcedureLifecycleState.REVISED
                                reason_code = "procedure_attributable_failure"
                            else:
                                reason_code = "procedure_non_attributable_failure"
                        elif intent.outcome is ProcedureObservationOutcome.SUCCESS:
                            if intent.attributable and counts_in_window:
                                success_count += 1
                            if (
                                intent.attributable
                                and intent.risk_level is ProcedureRiskLevel.LOW
                                and intent.hazard is ProcedureHazard.NONE
                            ):
                                threshold_state = (
                                    ProcedureLifecycleState.DRAFT
                                    if success_count < 2
                                    else ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION
                                    if success_count < 3
                                    else ProcedureLifecycleState.ACTIVE
                                )
                                ranks = {
                                    ProcedureLifecycleState.DRAFT: 0,
                                    ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION: 1,
                                    ProcedureLifecycleState.ACTIVE: 2,
                                    ProcedureLifecycleState.REINFORCED: 3,
                                }
                                if current_state in ranks and (
                                    ranks[threshold_state] > ranks[current_state]
                                ):
                                    next_state = threshold_state
                                reason_code = "procedure_low_risk_success"
                            else:
                                reason_code = (
                                    "procedure_non_attributable_success"
                                    if not intent.attributable
                                    else "procedure_unsafe_auto_activation_blocked"
                                )
                    if next_state is not intent.transition_to:
                        raise MemoryValidationError(
                            "procedure_observation_expected_transition_differs"
                        )
                    (
                        consumption_id,
                        consumption_hash,
                    ) = await self._insert_procedure_consumption_unlocked(
                        principal.actor_id, reference, authority, consumed_at
                    )
                    self._fault("procedure.after_consumption")
                    observation_json = intent.to_json()
                    observation_hash = hashlib.sha256(
                        canonical_json(observation_json).encode("utf-8")
                    ).hexdigest()
                    await self._db.execute(
                        "INSERT INTO procedure_observations(observation_id,consumption_id,"
                        "principal_id,memory_id,procedure_revision,task_scope_id,"
                        "qualification_epoch,"
                        "terminal_receipt_id,terminal_receipt_hash,applicability_fingerprint,"
                        "outcome,attributable,occurred_at,evidence_id,evidence_span_hash,"
                        "observation_json,observation_hash) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            intent.observation_id,
                            consumption_id,
                            principal.actor_id,
                            intent.target_memory_id,
                            base_revision,
                            intent.task_scope_id,
                            qualification_epoch,
                            intent.terminal_receipt_id,
                            intent.terminal_receipt_hash,
                            intent.applicability.fingerprint,
                            None if intent.outcome is None else intent.outcome.value,
                            int(intent.attributable),
                            intent.observed_at,
                            intent.evidence_span.evidence_id,
                            intent.evidence_span.span_hash,
                            canonical_json(observation_json),
                            observation_hash,
                        ),
                    )
                    self._fault("procedure.after_observation")
                    committed_revision = base_revision + 1
                    await self._copy_cognitive_revision_unlocked(
                        memory_id=intent.target_memory_id,
                        base_revision=base_revision,
                        committed_revision=committed_revision,
                        lifecycle_state=next_state.value,
                        operation_id=intent.operation_id,
                        plan_id=_stable_id("procedure-observation-plan", authority.authority_id),
                        plan_hash=intent.intent_hash,
                        created_at=consumed_at,
                    )
                    await self._copy_procedure_payload_unlocked(
                        memory_id=intent.target_memory_id,
                        base_revision=base_revision,
                        committed_revision=committed_revision,
                        qualification_epoch=qualification_epoch,
                        applicability_fingerprint=bound_fingerprint,
                        bound_hazard=bound_hazard,
                        success_count=success_count,
                        failure_count=failure_count,
                    )
                    self._fault("procedure.after_revision")
                    update = await self._db.execute(
                        "UPDATE cognitive_memory_heads SET current_revision=?,updated_at=? "
                        "WHERE principal_id=? AND scope_kind=? AND scope_owner=? "
                        "AND deployment_id=? AND household_id=? "
                        "AND memory_id=? AND current_revision=?",
                        (
                            committed_revision,
                            consumed_at,
                            principal.actor_id,
                            scope.kind.value,
                            scope.owner_id,
                            principal.deployment_id,
                            principal.household_id,
                            intent.target_memory_id,
                            base_revision,
                        ),
                    )
                    if update.rowcount != 1:
                        raise MemoryWriterConflict("procedure_observation_cas_failed")
                    decision_id = _stable_id(
                        "procedure-observation-decision", authority.authority_id
                    )
                    decision_json: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "decision_id": decision_id,
                        "consumption_id": consumption_id,
                        "consumption_hash": consumption_hash,
                        "memory_id": intent.target_memory_id,
                        "base_revision": base_revision,
                        "committed_revision": committed_revision,
                        "transition_from": current_state.value,
                        "transition_to": next_state.value,
                        "independent_successes": success_count,
                        "reason_code": reason_code,
                    }
                    decision_hash = hashlib.sha256(
                        canonical_json(decision_json).encode("utf-8")
                    ).hexdigest()
                    await self._db.execute(
                        "INSERT INTO procedure_observation_decisions(decision_id,"
                        "consumption_id,memory_id,base_revision,committed_revision,"
                        "transition_from,transition_to,independent_successes,reason_code,"
                        "decision_json,decision_hash,decided_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            decision_id,
                            consumption_id,
                            intent.target_memory_id,
                            base_revision,
                            committed_revision,
                            current_state.value,
                            next_state.value,
                            success_count,
                            reason_code,
                            canonical_json(decision_json),
                            decision_hash,
                            consumed_at,
                        ),
                    )
                    result = ProcedureObservationApplyResult(
                        _stable_id("procedure-observation-result", authority.authority_id),
                        intent.observation_id,
                        decision_id,
                        intent.target_memory_id,
                        base_revision,
                        committed_revision,
                        next_state,
                        success_count,
                        reason_code,
                        consumed_at,
                    )
                    await self._db.execute(
                        "INSERT INTO procedure_observation_results(result_id,consumption_id,"
                        "replay_identity,result_json,result_hash,decided_at) VALUES(?,?,?,?,?,?)",
                        (
                            result.result_id,
                            consumption_id,
                            authority.replay_identity,
                            canonical_json(result.to_json()),
                            result.result_hash,
                            result.decided_at,
                        ),
                    )
                    self._fault("procedure.after_decision")
                    before_commit = _timestamp(self._now())
                    if before_commit >= authority.expires_at:
                        raise MemoryValidationError("procedure_observation_authority_expired")
                    await self._advance_recall_authority_unlocked(
                        principal.actor_id,
                        event_kind="procedure_changed",
                        source_ref=result.result_id,
                        now=consumed_at,
                    )
                    self._fault("procedure.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("procedure.after_commit")
                    return result
                except BaseException:
                    if begun and not committed:
                        with suppress(Exception):
                            await self._db.execute("ROLLBACK")
                    raise
        except (MemoryErrorBase, sqlite3.IntegrityError) as exc:
            reason = (
                str(exc) if isinstance(exc, MemoryErrorBase) else "procedure_observation_replayed"
            )
            await self._append_lifecycle_rejection_audit(
                table="procedure_observation_rejections",
                domain="procedure-observation",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code=reason,
            )
            if isinstance(exc, MemoryErrorBase):
                raise
            raise MemoryValidationError(reason) from exc

    async def apply_prospective_signal(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProspectiveSignalAuthorityRef,
    ) -> ProspectiveSignalApplyResult:
        """Consume one Host scheduler/runtime signal without owning clock or action execution."""

        from simple_harness.runtime import (
            ProspectiveLifecycleState,
            ProspectiveSignalAuthorityRef,
            ProspectiveSignalKind,
            verify_prospective_signal_authority,
        )

        from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
        from simple_harness_memory.core.lifecycle_results import (
            LifecycleApplyOutcome,
            ProspectiveSignalApplyResult,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(scope) is not MemoryScope:
            raise TypeError("scope must use MemoryScope")
        if type(reference) is not ProspectiveSignalAuthorityRef:
            raise TypeError("reference must use ProspectiveSignalAuthorityRef")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        scope.authorize(principal)
        try:
            replay = await self._read_prospective_result_unlocked(
                principal=principal, scope=scope, reference=reference
            )
        except MemoryErrorBase as exc:
            await self._append_lifecycle_rejection_audit(
                table="prospective_signal_rejections",
                domain="prospective-signal",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code=str(exc),
            )
            raise
        if replay is not None:
            return replay
        if self._prospective_signal_authority is None:
            await self._append_lifecycle_rejection_audit(
                table="prospective_signal_rejections",
                domain="prospective-signal",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code="prospective_signal_authority_required",
            )
            raise MemoryValidationError("prospective_signal_authority_required")
        try:
            resolved_at = _timestamp(self._now())
            authority = await verify_prospective_signal_authority(
                reference,
                self._prospective_signal_authority,
                current_time=resolved_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            await self._append_lifecycle_rejection_audit(
                table="prospective_signal_rejections",
                domain="prospective-signal",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code="prospective_signal_authority_rejected",
            )
            raise MemoryValidationError("prospective_signal_authority_rejected") from exc
        intent = authority.intent
        try:
            if intent.subject != principal.actor_id:
                raise MemoryOwnershipConflict("prospective_signal_subject_differs")
            if (intent.scope.kind.value, intent.scope.owner_id) != (
                scope.kind.value,
                scope.owner_id,
            ):
                raise MemoryOwnershipConflict("prospective_signal_scope_differs")
            async with self._write_lock:
                self._fault("prospective.before_begin")
                await self._db.execute("BEGIN IMMEDIATE")
                committed = False
                try:
                    self._fault("prospective.after_begin")
                    replay = await self._read_prospective_result_unlocked(
                        principal=principal, scope=scope, reference=reference
                    )
                    if replay is not None:
                        await self._db.execute("COMMIT")
                        committed = True
                        return replay
                    consumed_at = _timestamp(self._now())
                    if consumed_at < authority.issued_at or consumed_at >= authority.expires_at:
                        raise MemoryValidationError("prospective_signal_authority_expired")
                    if intent.observed_at > consumed_at:
                        raise MemoryValidationError("prospective_signal_observed_at_future")
                    async with self._db.execute(
                        "SELECT h.memory_type,h.current_revision,h.scope_kind,h.scope_owner,"
                        "r.lifecycle_state,p.trigger_json FROM cognitive_memory_heads h "
                        "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
                        "AND r.revision=? JOIN prospective_records p ON p.memory_id=r.memory_id "
                        "AND p.revision=r.revision WHERE h.principal_id=? "
                        "AND h.deployment_id=? AND h.household_id=? AND h.memory_id=?",
                        (
                            intent.target_revision,
                            principal.actor_id,
                            principal.deployment_id,
                            principal.household_id,
                            intent.target_memory_id,
                        ),
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise MemoryValidationError("prospective_signal_target_not_found")
                    if str(row[0]) != "prospective":
                        raise MemoryValidationError("prospective_signal_target_type_differs")
                    if (str(row[2]), str(row[3])) != (
                        scope.kind.value,
                        scope.owner_id,
                    ):
                        raise MemoryOwnershipConflict("prospective_signal_scope_differs")
                    stored_trigger, stored_trigger_hash = self._decode_prospective_trigger(
                        str(row[5])
                    )
                    if (
                        stored_trigger_hash != intent.trigger_hash
                        or cast(Any, stored_trigger).to_json() != intent.trigger.to_json()
                    ):
                        raise MemoryValidationError("prospective_signal_trigger_differs")
                    current_revision = int(row[1])
                    target_state = ProspectiveLifecycleState(str(row[4]))
                    ack_kinds = {
                        ProspectiveSignalKind.REGISTRATION_ACCEPTED,
                        ProspectiveSignalKind.REGISTRATION_INVALIDATED,
                    }
                    is_ack = intent.signal_kind in ack_kinds
                    if is_ack:
                        if target_state is not intent.transition_from:
                            raise MemoryValidationError("prospective_signal_lifecycle_differs")
                        await self._verify_prospective_outbox_unlocked(intent)
                        if intent.signal_kind is ProspectiveSignalKind.REGISTRATION_INVALIDATED:
                            await self._verify_live_prospective_registration_unlocked(intent)
                    stale = not is_ack and (
                        current_revision != intent.target_revision
                        or target_state is not intent.transition_from
                    )
                    occurrence_duplicate = False
                    if not is_ack:
                        async with self._db.execute(
                            "SELECT 1 FROM prospective_trigger_events WHERE occurrence_key=?",
                            (intent.occurrence_key,),
                        ) as cursor:
                            occurrence_duplicate = await cursor.fetchone() is not None
                        if not stale and not occurrence_duplicate:
                            await self._verify_live_prospective_registration_unlocked(intent)
                    (
                        consumption_id,
                        consumption_hash,
                    ) = await self._insert_prospective_consumption_unlocked(
                        principal.actor_id, reference, authority, consumed_at
                    )
                    self._fault("prospective.after_consumption")
                    base_revision = intent.target_revision
                    committed_revision = base_revision
                    next_state = target_state
                    outcome = LifecycleApplyOutcome.ACKNOWLEDGED
                    reason_code = "prospective_registration_acknowledged"
                    if is_ack:
                        await self._insert_prospective_registration_event_unlocked(
                            consumption_id=consumption_id,
                            principal_id=principal.actor_id,
                            intent=intent,
                            occurred_at=consumed_at,
                        )
                    elif stale or occurrence_duplicate:
                        outcome = LifecycleApplyOutcome.IGNORED
                        reason_code = (
                            "prospective_occurrence_already_applied"
                            if occurrence_duplicate
                            else "prospective_signal_stale"
                        )
                        if not occurrence_duplicate:
                            await self._insert_prospective_trigger_event_unlocked(
                                consumption_id=consumption_id,
                                principal_id=principal.actor_id,
                                intent=intent,
                                outcome="ignored",
                                reason_code=reason_code,
                            )
                    else:
                        outcome = LifecycleApplyOutcome.APPLIED
                        next_state = intent.transition_to
                        reason_code = (
                            "prospective_expired"
                            if intent.signal_kind is ProspectiveSignalKind.EXPIRED
                            else "prospective_trigger_matched"
                        )
                        committed_revision = base_revision + 1
                        await self._copy_cognitive_revision_unlocked(
                            memory_id=intent.target_memory_id,
                            base_revision=base_revision,
                            committed_revision=committed_revision,
                            lifecycle_state=next_state.value,
                            operation_id=intent.operation_id,
                            plan_id=_stable_id("prospective-signal-plan", authority.authority_id),
                            plan_hash=intent.intent_hash,
                            created_at=consumed_at,
                        )
                        await self._copy_cognitive_payload_unlocked(
                            "prospective",
                            intent.target_memory_id,
                            base_revision,
                            intent.target_memory_id,
                            committed_revision,
                        )
                        await self._append_prospective_mutation_outbox_unlocked(
                            principal_id=principal.actor_id,
                            memory_id=intent.target_memory_id,
                            revision=committed_revision,
                            lifecycle_state=next_state.value,
                            previous_revision=base_revision,
                            previous_lifecycle_state=target_state.value,
                            created_at=consumed_at,
                        )
                        update = await self._db.execute(
                            "UPDATE cognitive_memory_heads SET current_revision=?,updated_at=? "
                            "WHERE principal_id=? AND scope_kind=? AND scope_owner=? "
                            "AND deployment_id=? AND household_id=? "
                            "AND memory_id=? AND current_revision=?",
                            (
                                committed_revision,
                                consumed_at,
                                principal.actor_id,
                                scope.kind.value,
                                scope.owner_id,
                                principal.deployment_id,
                                principal.household_id,
                                intent.target_memory_id,
                                base_revision,
                            ),
                        )
                        if update.rowcount != 1:
                            raise MemoryWriterConflict("prospective_signal_cas_failed")
                        await self._insert_prospective_trigger_event_unlocked(
                            consumption_id=consumption_id,
                            principal_id=principal.actor_id,
                            intent=intent,
                            outcome=(
                                "expired"
                                if intent.signal_kind is ProspectiveSignalKind.EXPIRED
                                else "matched"
                            ),
                            reason_code=reason_code,
                        )
                        self._fault("prospective.after_revision")
                    self._fault("prospective.after_event")
                    decision_id = _stable_id("prospective-signal-decision", authority.authority_id)
                    decision_json: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "decision_id": decision_id,
                        "consumption_id": consumption_id,
                        "consumption_hash": consumption_hash,
                        "memory_id": intent.target_memory_id,
                        "base_revision": base_revision,
                        "committed_revision": committed_revision,
                        "transition_from": target_state.value,
                        "transition_to": next_state.value,
                        "outcome": outcome.value,
                        "reason_code": reason_code,
                    }
                    decision_hash = hashlib.sha256(
                        canonical_json(decision_json).encode("utf-8")
                    ).hexdigest()
                    await self._db.execute(
                        "INSERT INTO prospective_signal_decisions(decision_id,consumption_id,"
                        "memory_id,base_revision,committed_revision,transition_from,transition_to,"
                        "outcome,reason_code,decision_json,decision_hash,decided_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            decision_id,
                            consumption_id,
                            intent.target_memory_id,
                            base_revision,
                            committed_revision,
                            target_state.value,
                            next_state.value,
                            outcome.value,
                            reason_code,
                            canonical_json(decision_json),
                            decision_hash,
                            consumed_at,
                        ),
                    )
                    result = ProspectiveSignalApplyResult(
                        _stable_id("prospective-signal-result", authority.authority_id),
                        intent.signal_id,
                        decision_id,
                        intent.target_memory_id,
                        base_revision,
                        committed_revision,
                        next_state,
                        outcome,
                        reason_code,
                        consumed_at,
                    )
                    await self._db.execute(
                        "INSERT INTO prospective_signal_results(result_id,consumption_id,"
                        "replay_identity,result_json,result_hash,decided_at) VALUES(?,?,?,?,?,?)",
                        (
                            result.result_id,
                            consumption_id,
                            authority.replay_identity,
                            canonical_json(result.to_json()),
                            result.result_hash,
                            result.decided_at,
                        ),
                    )
                    self._fault("prospective.after_decision")
                    if _timestamp(self._now()) >= authority.expires_at:
                        raise MemoryValidationError("prospective_signal_authority_expired")
                    await self._advance_recall_authority_unlocked(
                        principal.actor_id,
                        event_kind="prospective_changed",
                        source_ref=result.result_id,
                        now=consumed_at,
                    )
                    self._fault("prospective.before_commit")
                    await self._db.execute("COMMIT")
                    committed = True
                    self._fault("prospective.after_commit")
                    return result
                except BaseException:
                    if not committed:
                        with suppress(Exception):
                            await self._db.execute("ROLLBACK")
                    raise
        except (MemoryErrorBase, sqlite3.IntegrityError) as exc:
            reason = str(exc) if isinstance(exc, MemoryErrorBase) else "prospective_signal_replayed"
            await self._append_lifecycle_rejection_audit(
                table="prospective_signal_rejections",
                domain="prospective-signal",
                principal_id=principal.actor_id,
                authority_ref_hash=reference.ref_hash,
                reason_code=reason,
            )
            if isinstance(exc, MemoryErrorBase):
                raise
            raise MemoryValidationError(reason) from exc

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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
                    "created_at) VALUES(?,?,?,?,?) ON CONFLICT(principal_id) DO UPDATE SET "
                    "deployment_id=excluded.deployment_id,household_id=excluded.household_id,"
                    "actor_id=excluded.actor_id WHERE principals.deployment_id="
                    "principals.principal_id AND principals.household_id=principals.principal_id "
                    "AND principals.actor_id=principals.principal_id",
                    (
                        plan.subject,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        transaction_at,
                    ),
                )
                async with self._db.execute(
                    "SELECT deployment_id,household_id,actor_id FROM principals "
                    "WHERE principal_id=?",
                    (plan.subject,),
                ) as cursor:
                    principal_row = await cursor.fetchone()
                if principal_row is None or tuple(str(item) for item in principal_row) != (
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                ):
                    raise MemoryOwnershipConflict("cognitive principal binding differs")
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
                for canonical_index, compiled_operation in enumerate(compiled.operations, start=1):
                    operation = compiled_operation.operation
                    if operation.kind not in protected_kinds:
                        continue
                    if not isinstance(operation.target, ExistingMemoryTarget):
                        raise MemoryValidationError("memory_action_exact_target_required")
                    async with self._db.execute(
                        "SELECT current_revision FROM cognitive_memory_heads "
                        "WHERE principal_id=? AND deployment_id=? AND household_id=? "
                        "AND scope_kind=? AND scope_owner=? "
                        "AND memory_id=?",
                        (
                            plan.subject,
                            principal.deployment_id,
                            principal.household_id,
                            scope.kind.value,
                            scope.owner_id,
                            operation.target.memory_id,
                        ),
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
                        or verified_action.schema_version != MEMORY_ACTION_AUTHORITY_SCHEMA_VERSION
                    ):
                        action_authority_failure = MemoryValidationError(
                            "action_authority_rejected"
                        )
                        break
                    consumed_at = _timestamp(self._now())
                    if not (verified_action.issued_at <= consumed_at < verified_action.expires_at):
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
                            reason_code=(MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED),
                            decided_at=_timestamp(self._now()),
                        )
                    else:
                        action_exc = MemoryValidationError("action_authority_required")
                        action_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.NEEDS_USER_CONFIRMATION,
                            reason_code=(MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REQUIRED),
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
                for (
                    canonical_index,
                    operation,
                    reference,
                    authority,
                    consumed_at,
                ) in verified_action_authorities:
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
                    target_content_hash: str | None = None
                    target_conflict_status: str | None = None
                    active_conflict_row: aiosqlite.Row | None = None

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
                            "r.valid_from,r.valid_to,h.scope_kind,h.scope_owner,"
                            "r.scope_kind,r.scope_owner,r.conflict_status,r.content_hash "
                            "FROM cognitive_memory_heads h "
                            "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
                            "AND r.revision=h.current_revision "
                            "WHERE h.principal_id=? AND h.deployment_id=? "
                            "AND h.household_id=? AND h.scope_kind=? AND h.scope_owner=? "
                            "AND h.memory_id=?",
                            (
                                plan.subject,
                                principal.deployment_id,
                                principal.household_id,
                                scope.kind.value,
                                scope.owner_id,
                                target_memory_id,
                            ),
                        ) as cursor:
                            target_row = await cursor.fetchone()
                        if target_row is None:
                            raise MemoryValidationError("mutation_target_not_found")
                        target_type = LongTermMemoryType(str(target_row[0]))
                        target_revision = int(target_row[1])
                        if str(target_row[10]) != str(target_row[12]) or str(target_row[11]) != str(
                            target_row[13]
                        ):
                            raise MemoryCorruptionError("cognitive head and revision scope differ")
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
                        target_conflict_status = str(target_row[14])
                        target_content_hash = str(target_row[15])
                        async with self._db.execute(
                            "SELECT g.* FROM cognitive_conflict_groups g "
                            "LEFT JOIN cognitive_conflict_resolutions x ON x.group_id=g.group_id "
                            "WHERE g.principal_id=? AND g.memory_id=? "
                            "AND g.challenger_revision=? AND x.group_id IS NULL",
                            (plan.subject, target_memory_id, target_revision),
                        ) as cursor:
                            active_conflict_row = await cursor.fetchone()
                        if target_conflict_status == "contested" and active_conflict_row is None:
                            raise MemoryCorruptionError(
                                "contested head has no active conflict group"
                            )
                        if operation.kind is MemoryMutationKind.CONTEST:
                            if not isinstance(operation.target, ExistingMemoryTarget):
                                raise MemoryValidationError("mutation_contest_exact_slot_required")
                            if active_conflict_row is not None:
                                raise MemoryValidationError(
                                    "mutation_contest_nested_group_rejected"
                                )
                            proposed_content_json = (
                                None
                                if operation.payload is None
                                else canonical_json(operation.payload.to_json())
                            )
                            if (
                                proposed_content_json is None
                                or proposed_content_json == target_content_json
                                or operation.lifecycle_state.value != str(target_row[2])
                                or operation.epistemic_status.value != str(target_row[6])
                                or operation.verification_state.value != str(target_row[7])
                                or operation.valid_time_interval.valid_from != target_row[8]
                                or operation.valid_time_interval.valid_until != target_row[9]
                            ):
                                raise MemoryValidationError("mutation_contest_exact_slot_required")
                            async with self._db.execute(
                                "SELECT span_id,evidence_id FROM cognitive_evidence_spans "
                                "WHERE memory_id=? AND revision=? ORDER BY ordinal",
                                (target_memory_id, target_revision),
                            ) as cursor:
                                incumbent_evidence = {
                                    (str(row[0]), str(row[1]))
                                    for row in await cursor.fetchall()
                                }
                            if not incumbent_evidence:
                                raise MemoryCorruptionError(
                                    "conflict incumbent has no evidence"
                                )
                            challenger_evidence = {
                                (span.span_id, span.evidence_id)
                                for span in operation.evidence_spans
                            }
                            if not challenger_evidence or challenger_evidence <= incumbent_evidence:
                                raise MemoryValidationError(
                                    "mutation_contest_distinct_evidence_required"
                                )
                        elif active_conflict_row is not None:
                            if operation.kind is MemoryMutationKind.REVISE:
                                if operation.conflict_status.value != "resolved":
                                    raise MemoryValidationError(
                                        "mutation_conflict_resolution_state_required"
                                    )
                            elif operation.kind not in {
                                MemoryMutationKind.SUPERSEDE,
                                MemoryMutationKind.SUPPRESS,
                            }:
                                raise MemoryValidationError(
                                    "mutation_active_conflict_resolution_required"
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
                            "deployment_id,household_id,scope_kind,scope_owner,memory_type,"
                            "current_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (
                                memory_id,
                                plan.subject,
                                principal.deployment_id,
                                principal.household_id,
                                scope.kind.value,
                                scope.owner_id,
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
                        "deployment_id,household_id,scope_kind,scope_owner,plan_id,plan_hash,"
                        "operation_id,task_scope_id,"
                        "lifecycle_state,"
                        "epistemic_status,conflict_status,"
                        "verification_state,effective_privacy_class,"
                        "information_attributes_json,content_json,content_hash,valid_from,"
                        "valid_to,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            memory_id,
                            plan.subject,
                            revision,
                            principal.deployment_id,
                            principal.household_id,
                            scope.kind.value,
                            scope.owner_id,
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
                            memory_id,
                            revision,
                            operation.payload,
                            new_procedure_epoch=operation.kind
                            in {
                                MemoryMutationKind.CREATE,
                                MemoryMutationKind.REVISE,
                            },
                        )
                    if operation.memory_type is LongTermMemoryType.PROSPECTIVE:
                        await self._append_prospective_mutation_outbox_unlocked(
                            principal_id=plan.subject,
                            memory_id=memory_id,
                            revision=revision,
                            lifecycle_state=operation.lifecycle_state.value,
                            previous_revision=target_revision,
                            previous_lifecycle_state=(
                                None if target_lifecycle is None else target_lifecycle.value
                            ),
                            created_at=transaction_at,
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
                        if operation.kind is MemoryMutationKind.CONTEST:
                            if target_content_hash is None:
                                raise MemoryCorruptionError(
                                    "conflict incumbent content hash is missing"
                                )
                            await self._insert_cognitive_conflict_group_unlocked(
                                principal_id=plan.subject,
                                memory_id=memory_id,
                                incumbent_revision=target_revision,
                                challenger_revision=revision,
                                incumbent_content_hash=target_content_hash,
                                challenger_content_hash=content_hash,
                                plan_id=plan.plan_id,
                                plan_hash=plan.plan_hash,
                                operation_id=operation.operation_id,
                                created_at=transaction_at,
                            )
                        elif active_conflict_row is not None:
                            await self._insert_cognitive_conflict_resolution_unlocked(
                                group_row=active_conflict_row,
                                principal_id=plan.subject,
                                memory_id=memory_id,
                                resolution_revision=revision,
                                resolution_content_hash=content_hash,
                                operation_kind=operation.kind.value,
                                plan_id=plan.plan_id,
                                plan_hash=plan.plan_hash,
                                operation_id=operation.operation_id,
                                created_at=transaction_at,
                            )
                        update = await self._db.execute(
                            "UPDATE cognitive_memory_heads SET current_revision=?,updated_at=? "
                            "WHERE principal_id=? AND scope_kind=? AND scope_owner=? "
                            "AND deployment_id=? AND household_id=? "
                            "AND memory_id=? AND current_revision=?",
                            (
                                revision,
                                transaction_at,
                                plan.subject,
                                scope.kind.value,
                                scope.owner_id,
                                principal.deployment_id,
                                principal.household_id,
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
                        "action_authority_consumption_id": action_consumptions[item.operation_id][
                            0
                        ],
                        "action_authority_consumption_hash": action_consumptions[item.operation_id][
                            1
                        ],
                    }
                    for item in (compiled_item.operation for compiled_item in compiled.operations)
                    if item.operation_id in action_consumptions
                ]
                action_authority_refs_json = canonical_json(action_authority_refs)
                action_authorities_hash = hashlib.sha256(
                    action_authority_refs_json.encode("utf-8")
                ).hexdigest()
                transaction_started_hash = hashlib.sha256(
                    canonical_json({"transaction_started_at": transaction_at}).encode("utf-8")
                ).hexdigest()
                mutation_authority_hash = hashlib.sha256(
                    canonical_json(
                        {
                            "action_authorities_hash": action_authorities_hash,
                            "classification_decisions_hash": (classification_decisions_hash),
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
                if plan.outcome is MemoryMutationPlanOutcome.MUTATE:
                    await self._advance_recall_authority_unlocked(
                        principal.actor_id,
                        event_kind="cognitive_memory_changed",
                        source_ref=receipt.receipt_id,
                        now=committed_at,
                    )
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
                    if type(exc) is MemoryValidationError and str(exc) in {
                        "action_authority_rejected",
                        "action_authority_replayed",
                    }:
                        noncommitted_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.REJECTED,
                            reason_code=(MemoryMutationApplyReasonCode.ACTION_AUTHORITY_REJECTED),
                            decided_at=_timestamp(self._now()),
                        )
                    elif type(exc) is MemoryValidationError and str(exc).startswith(
                        "mutation_contest_"
                    ):
                        noncommitted_result = _mutation_apply_result(
                            plan,
                            outcome=MemoryMutationApplyOutcome.REJECTED,
                            reason_code=(MemoryMutationApplyReasonCode.VALIDATION_REJECTED),
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
        await self._validate_cognitive_conflict_integrity_unlocked()
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
            canonical_json({"transaction_started_at": transaction_started_at}).encode("utf-8")
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
            f"sqlite-human-memory:{self._receipt.receipt_id}:mutation:{mutation_authority_hash}"
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
        for operation, action_value in zip(protected_operations, action_refs, strict=True):
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
                "mutation_contest_lifecycle_must_be_unchanged": ("mutation_contest_rejected"),
                "mutation_contest_requires_contested_state": ("mutation_contest_rejected"),
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
        self,
        memory_id: str,
        revision: int,
        payload: object,
        *,
        new_procedure_epoch: bool = False,
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
            from simple_harness_memory.core.lifecycle_results import (
                UNBOUND_PROCEDURE_APPLICABILITY,
            )

            applicability_json = canonical_json(list(payload.applicability))
            if new_procedure_epoch or revision == 1:
                qualification_epoch = _stable_id(
                    "procedure-qualification-epoch", memory_id, str(revision)
                )
                applicability_fingerprint = UNBOUND_PROCEDURE_APPLICABILITY
                bound_hazard = None
            else:
                async with self._db.execute(
                    "SELECT qualification_epoch,applicability_fingerprint,bound_hazard "
                    "FROM procedure_records WHERE memory_id=? AND revision=?",
                    (memory_id, revision - 1),
                ) as cursor:
                    prior = await cursor.fetchone()
                if prior is None:
                    raise MemoryCorruptionError("prior procedure payload is missing")
                qualification_epoch = str(prior[0])
                applicability_fingerprint = str(prior[1])
                bound_hazard = None if prior[2] is None else str(prior[2])
            await self._db.execute(
                "INSERT INTO procedure_records(memory_id,revision,name,applicability_json,"
                "steps_json,risk_level,qualification_epoch,applicability_fingerprint,"
                "bound_hazard) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    memory_id,
                    revision,
                    payload.name,
                    applicability_json,
                    canonical_json(list(payload.steps)),
                    payload.proposed_risk_level.value,
                    qualification_epoch,
                    applicability_fingerprint,
                    bound_hazard,
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

    async def _append_prospective_mutation_outbox_unlocked(
        self,
        *,
        principal_id: str,
        memory_id: str,
        revision: int,
        lifecycle_state: str,
        previous_revision: int | None,
        previous_lifecycle_state: str | None,
        created_at: float,
    ) -> None:
        """Emit durable scheduler commands; Memory never owns a clock or action runner."""

        from simple_harness.runtime import (
            ProspectiveEventTrigger,
            ProspectiveLifecycleState,
            ProspectiveTimeTrigger,
            prospective_trigger_hash,
        )

        assert self._db is not None
        db = self._db

        async def append(kind: str, target_revision: int) -> None:
            async with db.execute(
                "SELECT trigger_json FROM prospective_records WHERE memory_id=? AND revision=?",
                (memory_id, target_revision),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise MemoryCorruptionError("prospective payload is missing")
            raw = json.loads(str(row[0]))
            if not isinstance(raw, dict):
                raise MemoryCorruptionError("prospective trigger is invalid")
            discriminator = raw.get("trigger_kind")
            try:
                trigger = (
                    ProspectiveTimeTrigger.from_json(raw)
                    if discriminator == "time"
                    else ProspectiveEventTrigger.from_json(raw)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("prospective trigger is invalid") from exc
            trigger_hash = prospective_trigger_hash(trigger)
            payload: dict[str, JsonValue] = {
                "schema_version": 1,
                "command": kind,
                "memory_id": memory_id,
                "prospective_revision": target_revision,
                "registration_revision": target_revision,
                "trigger": trigger.to_json(),
                "trigger_hash": trigger_hash,
            }
            payload_json = canonical_json(payload)
            outbox_id = _stable_id(
                "prospective-scheduler-outbox", memory_id, str(target_revision), kind
            )
            await db.execute(
                "INSERT INTO outbox(outbox_id,principal_id,topic,idempotency_key,payload,"
                "payload_hash,state,next_attempt_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,'pending',?,?,?)",
                (
                    outbox_id,
                    principal_id,
                    f"memory.prospective.{kind}.requested",
                    outbox_id,
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                    created_at,
                    created_at,
                    created_at,
                ),
            )

        live_states = {
            ProspectiveLifecycleState.PENDING.value,
            ProspectiveLifecycleState.TRIGGERED.value,
            ProspectiveLifecycleState.IN_PROGRESS.value,
            ProspectiveLifecycleState.RESCHEDULED.value,
        }
        if previous_revision is not None and previous_lifecycle_state in live_states:
            await append("invalidation", previous_revision)
        if lifecycle_state in {
            ProspectiveLifecycleState.PENDING.value,
            ProspectiveLifecycleState.RESCHEDULED.value,
        }:
            await append("registration", revision)

    async def _read_procedure_result_unlocked(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProcedureObservationAuthorityRef,
    ) -> ProcedureObservationApplyResult | None:
        from simple_harness_memory.core.lifecycle_results import (
            ProcedureObservationApplyResult,
        )

        assert self._db is not None
        async with self._db.execute(
            "SELECT x.result_json,x.result_hash,c.principal_id,c.authority_ref_json,"
            "c.authority_ref_hash,h.scope_kind,h.scope_owner,h.deployment_id,"
            "h.household_id,h.principal_id "
            "FROM procedure_observation_authority_consumptions c "
            "LEFT JOIN procedure_observation_results x "
            "ON c.consumption_id=x.consumption_id JOIN cognitive_memory_heads h "
            "ON h.memory_id=c.target_memory_id WHERE c.replay_identity=?",
            (reference.replay_identity,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        if (
            str(row[2]) != principal.actor_id
            or str(row[3]) != canonical_json(reference.to_json())
            or str(row[4]) != reference.ref_hash
            or (str(row[5]), str(row[6])) != (scope.kind.value, scope.owner_id)
            or (str(row[7]), str(row[8]), str(row[9]))
            != (principal.deployment_id, principal.household_id, principal.actor_id)
        ):
            raise MemoryOwnershipConflict("procedure_observation_replay_binding_differs")
        await self._validate_lifecycle_integrity_unlocked(
            procedure_replay_identity=reference.replay_identity
        )
        try:
            raw = json.loads(str(row[0]))
            if not isinstance(raw, dict):
                raise ValueError("stored result is not an object")
            result = ProcedureObservationApplyResult.from_json(raw)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("stored procedure observation result is invalid") from exc
        if canonical_json(result.to_json()) != str(row[0]) or result.result_hash != str(row[1]):
            raise MemoryCorruptionError("stored procedure observation result differs")
        return result

    async def _append_lifecycle_rejection_audit(
        self,
        *,
        table: str,
        domain: str,
        principal_id: str,
        authority_ref_hash: str,
        reason_code: str,
    ) -> None:
        if table not in {
            "procedure_observation_rejections",
            "prospective_signal_rejections",
        }:
            raise MemoryCorruptionError("lifecycle rejection table is invalid")
        assert self._db is not None
        rejected_at = _timestamp(self._now())
        rejection_id = _stable_id(domain + "-rejection", principal_id, authority_ref_hash)
        rejection: dict[str, JsonValue] = {
            "schema_version": 1,
            "rejection_id": rejection_id,
            "principal_id_hash": _opaque_hash(principal_id),
            "authority_ref_hash": authority_ref_hash,
            "reason_code": reason_code,
            "rejected_at": rejected_at,
        }
        rejection_json = canonical_json(rejection)
        rejection_hash = hashlib.sha256(rejection_json.encode("utf-8")).hexdigest()
        async with self._write_lock:
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                await self._db.execute(
                    f"INSERT OR IGNORE INTO {table}(rejection_id,principal_id,"
                    "authority_ref_hash,reason_code,rejection_json,rejection_hash,rejected_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        rejection_id,
                        principal_id,
                        authority_ref_hash,
                        reason_code,
                        rejection_json,
                        rejection_hash,
                        rejected_at,
                    ),
                )
                await self._db.execute("COMMIT")
            except BaseException:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")
                raise

    async def _verify_procedure_evidence_unlocked(self, intent: object) -> None:
        span = getattr(intent, "evidence_span")
        origins = await self._verify_mutation_span_unlocked(
            subject=str(getattr(intent, "subject")), span=span
        )
        exact_origin = tuple(
            origin for origin in origins if origin[0] == getattr(intent, "task_scope_id")
        )
        if not exact_origin:
            raise MemoryValidationError("procedure_observation_task_scope_evidence_missing")
        assert self._db is not None
        async with self._db.execute(
            "SELECT run_id,tool_causal_link_json FROM conversation_evidence_registrations "
            "WHERE principal_id=? AND evidence_id=? AND task_scope_id=?",
            (
                getattr(intent, "subject"),
                span.evidence_id,
                getattr(intent, "task_scope_id"),
            ),
        ) as cursor:
            rows = list(await cursor.fetchall())
        if len(rows) != 1 or str(rows[0][0]) != getattr(intent, "run_id"):
            raise MemoryValidationError("procedure_observation_evidence_binding_differs")
        terminal_id = getattr(intent, "terminal_receipt_id")
        terminal_hash = getattr(intent, "terminal_receipt_hash")
        if terminal_id is None:
            return
        raw_link = rows[0][1]
        if raw_link is None:
            raise MemoryValidationError("procedure_observation_terminal_receipt_missing")
        try:
            link = json.loads(str(raw_link))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("conversation tool causal link is invalid") from exc
        if not isinstance(link, dict) or (
            link.get("terminal_receipt_id"),
            link.get("terminal_receipt_hash"),
        ) != (terminal_id, terminal_hash):
            raise MemoryValidationError("procedure_observation_terminal_receipt_differs")

    async def _insert_procedure_consumption_unlocked(
        self, principal_id: str, reference: object, authority: object, consumed_at: float
    ) -> tuple[str, str]:
        assert self._db is not None
        intent = getattr(authority, "intent")
        consumption_id = _stable_id(
            "procedure-observation-consumption", getattr(authority, "authority_id")
        )
        consumption: dict[str, JsonValue] = {
            "schema_version": 1,
            "consumption_id": consumption_id,
            "principal_id": principal_id,
            "authority_ref": getattr(reference, "to_json")(),
            "authority_ref_hash": getattr(reference, "ref_hash"),
            "authority": getattr(authority, "to_json")(),
            "authority_hash": getattr(authority, "authority_hash"),
            "consumed_at": consumed_at,
        }
        consumption_hash = hashlib.sha256(canonical_json(consumption).encode("utf-8")).hexdigest()
        await self._db.execute(
            "INSERT INTO procedure_observation_authority_consumptions(consumption_id,"
            "principal_id,authority_id,authority_hash,issuer_ref,nonce,replay_identity,"
            "authority_ref_json,authority_ref_hash,authority_json,intent_hash,"
            "target_memory_id,target_revision,issued_at,expires_at,consumed_at,"
            "consumption_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                consumption_id,
                principal_id,
                getattr(authority, "authority_id"),
                getattr(authority, "authority_hash"),
                getattr(authority, "issuer_ref"),
                getattr(authority, "nonce"),
                getattr(authority, "replay_identity"),
                canonical_json(getattr(reference, "to_json")()),
                getattr(reference, "ref_hash"),
                canonical_json(getattr(authority, "to_json")()),
                getattr(intent, "intent_hash"),
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(authority, "issued_at"),
                getattr(authority, "expires_at"),
                consumed_at,
                consumption_hash,
            ),
        )
        return consumption_id, consumption_hash

    async def _copy_cognitive_revision_unlocked(
        self,
        *,
        memory_id: str,
        base_revision: int,
        committed_revision: int,
        lifecycle_state: str,
        operation_id: str,
        plan_id: str,
        plan_hash: str,
        created_at: float,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO cognitive_memory_revisions(memory_id,principal_id,deployment_id,"
            "household_id,scope_kind,scope_owner,revision,plan_id,plan_hash,operation_id,task_scope_id,"
            "lifecycle_state,epistemic_status,conflict_status,verification_state,"
            "effective_privacy_class,information_attributes_json,content_json,content_hash,"
            "valid_from,valid_to,created_at) SELECT memory_id,principal_id,deployment_id,"
            "household_id,scope_kind,scope_owner,?, ?, ?, ?,task_scope_id,?,"
            "epistemic_status,conflict_status,"
            "verification_state,effective_privacy_class,information_attributes_json,"
            "content_json,content_hash,valid_from,valid_to,? FROM cognitive_memory_revisions "
            "WHERE memory_id=? AND revision=?",
            (
                committed_revision,
                plan_id,
                plan_hash,
                operation_id,
                lifecycle_state,
                created_at,
                memory_id,
                base_revision,
            ),
        )
        await self._db.execute(
            "INSERT INTO cognitive_evidence_spans SELECT ?,?,ordinal,span_id,evidence_id,"
            "envelope_hash,sanitized_hash,admission_receipt_id,admission_receipt_hash,"
            "evidence_item_ordinal,evidence_item_id,evidence_item_json_pointer,byte_start,"
            "byte_end,exact_quote,quote_hash,source_hash,normalization_version,actor_role,"
            "provenance,source_kind,support_kind,observation_schema_id,"
            "observation_schema_version,observation_registered_schema_hash,"
            "observation_receipt_id,observation_receipt_hash,observation_authority_issuer_id,"
            "observation_json_pointer,observation_value_hash FROM cognitive_evidence_spans "
            "WHERE memory_id=? AND revision=?",
            (memory_id, committed_revision, memory_id, base_revision),
        )
        await self._db.execute(
            "INSERT INTO cognitive_revision_task_scope_origins "
            "SELECT ?,?,task_scope_id,evidence_id,registration_id "
            "FROM cognitive_revision_task_scope_origins WHERE memory_id=? AND revision=?",
            (memory_id, committed_revision, memory_id, base_revision),
        )

    async def _copy_procedure_payload_unlocked(
        self,
        *,
        memory_id: str,
        base_revision: int,
        committed_revision: int,
        applicability_fingerprint: str,
        bound_hazard: str | None,
        qualification_epoch: str,
        success_count: int,
        failure_count: int,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO procedure_records(memory_id,revision,name,applicability_json,"
            "steps_json,risk_level,qualification_epoch,applicability_fingerprint,bound_hazard,"
            "success_evidence_count,failure_evidence_count) SELECT memory_id,?,name,"
            "applicability_json,steps_json,risk_level,?,?,?,?,? FROM procedure_records "
            "WHERE memory_id=? AND revision=?",
            (
                committed_revision,
                qualification_epoch,
                applicability_fingerprint,
                bound_hazard,
                success_count,
                failure_count,
                memory_id,
                base_revision,
            ),
        )

    async def _read_prospective_result_unlocked(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        reference: ProspectiveSignalAuthorityRef,
    ) -> ProspectiveSignalApplyResult | None:
        from simple_harness_memory.core.lifecycle_results import ProspectiveSignalApplyResult

        assert self._db is not None
        async with self._db.execute(
            "SELECT x.result_json,x.result_hash,c.principal_id,c.authority_ref_json,"
            "c.authority_ref_hash,h.scope_kind,h.scope_owner,h.deployment_id,"
            "h.household_id,h.principal_id "
            "FROM prospective_signal_authority_consumptions c "
            "LEFT JOIN prospective_signal_results x "
            "ON c.consumption_id=x.consumption_id JOIN cognitive_memory_heads h "
            "ON h.memory_id=c.target_memory_id WHERE c.replay_identity=?",
            (reference.replay_identity,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        if (
            str(row[2]) != principal.actor_id
            or str(row[3]) != canonical_json(reference.to_json())
            or str(row[4]) != reference.ref_hash
            or (str(row[5]), str(row[6])) != (scope.kind.value, scope.owner_id)
            or (str(row[7]), str(row[8]), str(row[9]))
            != (principal.deployment_id, principal.household_id, principal.actor_id)
        ):
            raise MemoryOwnershipConflict("prospective_signal_replay_binding_differs")
        await self._validate_lifecycle_integrity_unlocked(
            prospective_replay_identity=reference.replay_identity
        )
        try:
            raw = json.loads(str(row[0]))
            if not isinstance(raw, dict):
                raise ValueError("stored result is not an object")
            result = ProspectiveSignalApplyResult.from_json(raw)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("stored prospective signal result is invalid") from exc
        if canonical_json(result.to_json()) != str(row[0]) or result.result_hash != str(row[1]):
            raise MemoryCorruptionError("stored prospective signal result differs")
        return result

    @staticmethod
    def _decode_prospective_trigger(value: str) -> tuple[object, str]:
        from simple_harness.runtime import (
            ProspectiveEventTrigger,
            ProspectiveTimeTrigger,
            prospective_trigger_hash,
        )

        try:
            raw = json.loads(value)
            if not isinstance(raw, dict):
                raise ValueError("trigger is not an object")
            trigger = (
                ProspectiveTimeTrigger.from_json(raw)
                if raw.get("trigger_kind") == "time"
                else ProspectiveEventTrigger.from_json(raw)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("prospective trigger is invalid") from exc
        return trigger, prospective_trigger_hash(trigger)

    async def _verify_prospective_outbox_unlocked(self, intent: object) -> None:
        from simple_harness.runtime import ProspectiveSignalKind

        assert self._db is not None
        async with self._db.execute(
            "SELECT topic,payload,payload_hash,principal_id FROM outbox WHERE outbox_id=?",
            (getattr(intent, "outbox_id"),),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise MemoryValidationError("prospective_signal_outbox_not_found")
        kind = getattr(intent, "signal_kind")
        command = (
            "registration"
            if kind is ProspectiveSignalKind.REGISTRATION_ACCEPTED
            else "invalidation"
        )
        if (
            str(row[0]) != f"memory.prospective.{command}.requested"
            or str(row[2]) != getattr(intent, "outbox_payload_hash")
            or str(row[3]) != getattr(intent, "subject")
        ):
            raise MemoryValidationError("prospective_signal_outbox_binding_differs")
        try:
            payload = json.loads(str(row[1]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("prospective scheduler outbox is invalid") from exc
        if (
            not isinstance(payload, dict)
            or canonical_json(payload) != str(row[1])
            or hashlib.sha256(str(row[1]).encode("utf-8")).hexdigest() != str(row[2])
            or (
                payload.get("command"),
                payload.get("memory_id"),
                payload.get("prospective_revision"),
                payload.get("registration_revision"),
                payload.get("trigger_hash"),
            )
            != (
                command,
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(intent, "registration_revision"),
                getattr(intent, "trigger_hash"),
            )
        ):
            raise MemoryValidationError("prospective_signal_outbox_binding_differs")

    async def _verify_live_prospective_registration_unlocked(self, intent: object) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT state,trigger_hash FROM prospective_scheduler_registrations "
            "WHERE memory_id=? AND prospective_revision=? AND registration_revision=? "
            "AND scheduler_registration_ref=? ORDER BY occurred_at DESC",
            (
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(intent, "registration_revision"),
                getattr(intent, "scheduler_registration_ref"),
            ),
        ) as cursor:
            rows = list(await cursor.fetchall())
        if (
            not rows
            or str(rows[0][0]) != "accepted"
            or str(rows[0][1]) != getattr(intent, "trigger_hash")
        ):
            raise MemoryValidationError("prospective_scheduler_registration_not_live")
        if any(str(row[0]) == "invalidated" for row in rows):
            raise MemoryValidationError("prospective_scheduler_registration_not_live")

    async def _insert_prospective_consumption_unlocked(
        self, principal_id: str, reference: object, authority: object, consumed_at: float
    ) -> tuple[str, str]:
        assert self._db is not None
        intent = getattr(authority, "intent")
        consumption_id = _stable_id(
            "prospective-signal-consumption", getattr(authority, "authority_id")
        )
        consumption: dict[str, JsonValue] = {
            "schema_version": 1,
            "consumption_id": consumption_id,
            "principal_id": principal_id,
            "authority_ref": getattr(reference, "to_json")(),
            "authority_ref_hash": getattr(reference, "ref_hash"),
            "authority": getattr(authority, "to_json")(),
            "authority_hash": getattr(authority, "authority_hash"),
            "consumed_at": consumed_at,
        }
        consumption_hash = hashlib.sha256(canonical_json(consumption).encode("utf-8")).hexdigest()
        await self._db.execute(
            "INSERT INTO prospective_signal_authority_consumptions(consumption_id,"
            "principal_id,authority_id,authority_hash,issuer_ref,nonce,replay_identity,"
            "authority_ref_json,authority_ref_hash,authority_json,intent_hash,"
            "target_memory_id,target_revision,issued_at,expires_at,consumed_at,"
            "consumption_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                consumption_id,
                principal_id,
                getattr(authority, "authority_id"),
                getattr(authority, "authority_hash"),
                getattr(authority, "issuer_ref"),
                getattr(authority, "nonce"),
                getattr(authority, "replay_identity"),
                canonical_json(getattr(reference, "to_json")()),
                getattr(reference, "ref_hash"),
                canonical_json(getattr(authority, "to_json")()),
                getattr(intent, "intent_hash"),
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(authority, "issued_at"),
                getattr(authority, "expires_at"),
                consumed_at,
                consumption_hash,
            ),
        )
        return consumption_id, consumption_hash

    async def _insert_prospective_registration_event_unlocked(
        self,
        *,
        consumption_id: str,
        principal_id: str,
        intent: object,
        occurred_at: float,
    ) -> None:
        from simple_harness.runtime import ProspectiveSignalKind

        assert self._db is not None
        state = (
            "accepted"
            if getattr(intent, "signal_kind") is ProspectiveSignalKind.REGISTRATION_ACCEPTED
            else "invalidated"
        )
        event_id = _stable_id("prospective-registration-event", consumption_id)
        event: dict[str, JsonValue] = {
            "schema_version": 1,
            "registration_event_id": event_id,
            "memory_id": getattr(intent, "target_memory_id"),
            "prospective_revision": getattr(intent, "target_revision"),
            "scheduler_registration_ref": getattr(intent, "scheduler_registration_ref"),
            "registration_revision": getattr(intent, "registration_revision"),
            "state": state,
            "trigger_hash": getattr(intent, "trigger_hash"),
            "outbox_id": getattr(intent, "outbox_id"),
            "outbox_payload_hash": getattr(intent, "outbox_payload_hash"),
        }
        event_json = canonical_json(event)
        await self._db.execute(
            "INSERT INTO prospective_scheduler_registrations(registration_event_id,"
            "consumption_id,principal_id,memory_id,prospective_revision,"
            "scheduler_registration_ref,registration_revision,state,trigger_hash,outbox_id,"
            "outbox_payload_hash,event_json,event_hash,occurred_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                consumption_id,
                principal_id,
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(intent, "scheduler_registration_ref"),
                getattr(intent, "registration_revision"),
                state,
                getattr(intent, "trigger_hash"),
                getattr(intent, "outbox_id"),
                getattr(intent, "outbox_payload_hash"),
                event_json,
                hashlib.sha256(event_json.encode("utf-8")).hexdigest(),
                occurred_at,
            ),
        )

    async def _insert_prospective_trigger_event_unlocked(
        self,
        *,
        consumption_id: str,
        principal_id: str,
        intent: object,
        outcome: str,
        reason_code: str,
    ) -> None:
        assert self._db is not None
        event_id = _stable_id("prospective-trigger-event", consumption_id)
        event: dict[str, JsonValue] = {
            "schema_version": 1,
            "event_id": event_id,
            "memory_id": getattr(intent, "target_memory_id"),
            "prospective_revision": getattr(intent, "target_revision"),
            "trigger_hash": getattr(intent, "trigger_hash"),
            "event_ref": getattr(intent, "signal_receipt_id"),
            "occurrence_key": getattr(intent, "occurrence_key"),
            "signal_kind": getattr(intent, "signal_kind").value,
            "outcome": outcome,
            "reason_code": reason_code,
            "occurred_at": getattr(intent, "observed_at"),
        }
        event_json = canonical_json(event)
        await self._db.execute(
            "INSERT INTO prospective_trigger_events(event_id,consumption_id,principal_id,"
            "memory_id,prospective_revision,trigger_fingerprint,event_ref,occurrence_key,"
            "signal_kind,outcome,reason_code,occurred_at,event_json,event_hash) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                consumption_id,
                principal_id,
                getattr(intent, "target_memory_id"),
                getattr(intent, "target_revision"),
                getattr(intent, "trigger_hash"),
                getattr(intent, "signal_receipt_id"),
                getattr(intent, "occurrence_key"),
                getattr(intent, "signal_kind").value,
                outcome,
                reason_code,
                getattr(intent, "observed_at"),
                event_json,
                hashlib.sha256(event_json.encode("utf-8")).hexdigest(),
            ),
        )

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
                "name,applicability_json,steps_json,risk_level,qualification_epoch,"
                "applicability_fingerprint,bound_hazard,success_evidence_count,"
                "failure_evidence_count",
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

    async def _cognitive_evidence_set_hash_unlocked(
        self, memory_id: str, revision: int
    ) -> str:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM cognitive_evidence_spans WHERE memory_id=? AND revision=? "
            "ORDER BY ordinal",
            (memory_id, revision),
        ) as cursor:
            rows = tuple(await cursor.fetchall())
        if not rows:
            raise MemoryCorruptionError("cognitive conflict member has no evidence")
        manifest = [
            {key: row[key] for key in row.keys() if key not in {"memory_id", "revision"}}
            for row in rows
        ]
        return hashlib.sha256(canonical_json(cast(Any, manifest)).encode("utf-8")).hexdigest()

    async def _insert_cognitive_conflict_group_unlocked(
        self,
        *,
        principal_id: str,
        memory_id: str,
        incumbent_revision: int,
        challenger_revision: int,
        incumbent_content_hash: str,
        challenger_content_hash: str,
        plan_id: str,
        plan_hash: str,
        operation_id: str,
        created_at: float,
    ) -> str:
        assert self._db is not None
        incumbent_evidence_hash = await self._cognitive_evidence_set_hash_unlocked(
            memory_id, incumbent_revision
        )
        challenger_evidence_hash = await self._cognitive_evidence_set_hash_unlocked(
            memory_id, challenger_revision
        )
        group_id = _stable_id(
            "cognitive-conflict-group",
            principal_id,
            memory_id,
            str(incumbent_revision),
            str(challenger_revision),
            plan_id,
            operation_id,
        )
        members: list[dict[str, JsonValue]] = []
        for ordinal, role, revision, content_hash, evidence_hash in (
            (
                1,
                "incumbent",
                incumbent_revision,
                incumbent_content_hash,
                incumbent_evidence_hash,
            ),
            (
                2,
                "challenger",
                challenger_revision,
                challenger_content_hash,
                challenger_evidence_hash,
            ),
        ):
            member_payload: dict[str, JsonValue] = {
                "group_id": group_id,
                "ordinal": ordinal,
                "role": role,
                "principal_id": principal_id,
                "memory_id": memory_id,
                "revision": revision,
                "content_hash": content_hash,
                "evidence_set_hash": evidence_hash,
            }
            member_payload["member_hash"] = hashlib.sha256(
                canonical_json(member_payload).encode("utf-8")
            ).hexdigest()
            members.append(member_payload)
        group_payload: dict[str, JsonValue] = {
            "group_id": group_id,
            "principal_id": principal_id,
            "memory_id": memory_id,
            "incumbent_revision": incumbent_revision,
            "challenger_revision": challenger_revision,
            "creation_plan_id": plan_id,
            "creation_plan_hash": plan_hash,
            "operation_id": operation_id,
            "created_at": created_at,
            "member_hashes": [str(member["member_hash"]) for member in members],
        }
        group_hash = hashlib.sha256(
            canonical_json(group_payload).encode("utf-8")
        ).hexdigest()
        await self._db.execute(
            "INSERT INTO cognitive_conflict_groups(group_id,principal_id,memory_id,"
            "incumbent_revision,challenger_revision,creation_plan_id,creation_plan_hash,"
            "operation_id,created_at,group_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                group_id,
                principal_id,
                memory_id,
                incumbent_revision,
                challenger_revision,
                plan_id,
                plan_hash,
                operation_id,
                created_at,
                group_hash,
            ),
        )
        self._fault("mutation.after_conflict_group")
        for member in members:
            await self._db.execute(
                "INSERT INTO cognitive_conflict_members(group_id,ordinal,role,principal_id,"
                "memory_id,revision,content_hash,evidence_set_hash,member_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    member["group_id"],
                    member["ordinal"],
                    member["role"],
                    member["principal_id"],
                    member["memory_id"],
                    member["revision"],
                    member["content_hash"],
                    member["evidence_set_hash"],
                    member["member_hash"],
                ),
            )
            self._fault(f"mutation.after_conflict_member_{member['ordinal']}")
        return group_id

    async def _insert_cognitive_conflict_resolution_unlocked(
        self,
        *,
        group_row: aiosqlite.Row,
        principal_id: str,
        memory_id: str,
        resolution_revision: int,
        resolution_content_hash: str,
        operation_kind: str,
        plan_id: str,
        plan_hash: str,
        operation_id: str,
        created_at: float,
    ) -> None:
        assert self._db is not None
        group_id = str(group_row["group_id"])
        async with self._db.execute(
            "SELECT ordinal,content_hash FROM cognitive_conflict_members "
            "WHERE group_id=? ORDER BY ordinal",
            (group_id,),
        ) as cursor:
            members = tuple(await cursor.fetchall())
        if len(members) != 2:
            raise MemoryCorruptionError("conflict member cardinality differs")
        selected_ordinal: int | None = None
        if operation_kind == "supersede":
            resolution_kind = "superseded"
        elif operation_kind == "suppress":
            resolution_kind = "forgotten"
        elif resolution_content_hash == str(members[0]["content_hash"]):
            resolution_kind = "selected_incumbent"
            selected_ordinal = 1
        elif resolution_content_hash == str(members[1]["content_hash"]):
            resolution_kind = "selected_challenger"
            selected_ordinal = 2
        else:
            resolution_kind = "replacement"
        resolution_payload: dict[str, JsonValue] = {
            "group_id": group_id,
            "principal_id": principal_id,
            "memory_id": memory_id,
            "resolution_revision": resolution_revision,
            "resolution_kind": resolution_kind,
            "selected_member_ordinal": selected_ordinal,
            "plan_id": plan_id,
            "plan_hash": plan_hash,
            "operation_id": operation_id,
            "created_at": created_at,
        }
        resolution_hash = hashlib.sha256(
            canonical_json(resolution_payload).encode("utf-8")
        ).hexdigest()
        await self._db.execute(
            "INSERT INTO cognitive_conflict_resolutions(group_id,principal_id,memory_id,"
            "resolution_revision,resolution_kind,selected_member_ordinal,plan_id,plan_hash,"
            "operation_id,created_at,resolution_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                group_id,
                principal_id,
                memory_id,
                resolution_revision,
                resolution_kind,
                selected_ordinal,
                plan_id,
                plan_hash,
                operation_id,
                created_at,
                resolution_hash,
            ),
        )
        self._fault("mutation.after_conflict_resolution")

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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
        principal: MemoryPrincipal | None = None,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        """Ordinary trace export; active suppression removes the whole linked item."""

        return await self._export_audit_trace(
            query, principal=principal, limit=limit, cursor=cursor
        )

    async def export_sealed_audit_trace(
        self,
        query: AuditTraceQuery,
        access_receipt: SealedAuditAccessReceipt,
        *,
        principal: MemoryPrincipal | None = None,
        limit: int = 20,
        cursor: AuditTraceCursor | None = None,
    ) -> AuditTracePage:
        """Purpose-bound sealed trace export with an append-only access event."""

        return await self._export_audit_trace(
            query,
            principal=principal,
            limit=limit,
            cursor=cursor,
            access_receipt=access_receipt,
        )

    async def get_audit_aggregate_metrics(
        self, *, principal: MemoryPrincipal
    ) -> AuditAggregateMetricsV1:
        """Return fixed, ordinary-visible aggregates without caller-defined grouping."""

        from simple_harness_memory.core.audit import (
            AuditAggregateMetricsV1,
            AuditTraceItem,
            DecisionOutcome,
            OutputStorageStatus,
        )

        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            async with self._db.execute(
                "SELECT invocation_id FROM llm_invocations WHERE principal_id=? "
                "ORDER BY invocation_sequence",
                (principal.actor_id,),
            ) as cursor:
                rows = list(await cursor.fetchall())
            if len(rows) > 100_000:
                raise MemoryLimitError("audit_metrics_row_limit_exceeded")
            visible = accepted = rejected = unsafe = 0
            input_tokens = output_tokens = cost = latency = 0
            for row in rows:
                invocation = await self._read_invocation(str(row["invocation_id"]))
                if invocation is None:
                    raise MemoryCorruptionError("audit metrics invocation disappeared")
                decisions = await self._read_decisions(invocation.invocation_id)
                if await self._trace_item_denied_unlocked(
                    AuditTraceItem(invocation, decisions)
                ):
                    continue
                visible += 1
                accepted += sum(
                    item.outcome is DecisionOutcome.ACCEPTED for item in decisions
                )
                rejected += sum(
                    item.outcome is DecisionOutcome.REJECTED for item in decisions
                )
                unsafe += invocation.output_storage_status is OutputStorageStatus.REJECTED_UNSAFE
                input_tokens += invocation.input_tokens
                output_tokens += invocation.output_tokens
                cost += invocation.cost_microunits
                latency += invocation.latency_ms
        return AuditAggregateMetricsV1(
            principal_ref_hash=_principal_ref_hash(principal),
            visible_invocations=visible,
            accepted_decisions=accepted,
            rejected_decisions=rejected,
            rejected_unsafe_outputs=unsafe,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_microunits=cost,
            latency_ms=latency,
        )

    async def export_canonical_state_manifest(
        self,
        *,
        requester: MemoryPrincipal,
        target_principal: MemoryPrincipal,
        access_receipt: SealedAuditAccessReceipt,
    ) -> CanonicalStateManifestAccessV1:
        """Build a sealed, hash-only canonical state manifest in one snapshot."""

        from simple_harness_memory.core.audit import (
            CanonicalStateManifestAccessV1,
            CanonicalStateManifestV1,
        )
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDenied,
            SuppressionScopeKind,
        )

        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        if type(requester) is not type(target_principal):
            raise TypeError("requester and target_principal must use MemoryPrincipal")
        denial: str | None = None
        event_hash: str | None = None
        manifest: CanonicalStateManifestV1 | None = None
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(requester)
            await self._authorize_short_horizon_principal_unlocked(target_principal)
            stored = await self._read_audit_access_by_decision(access_receipt.decision_id)
            authority_ref = await self._read_audit_authority_ref_by_decision(
                access_receipt.decision_id
            )
            now = _timestamp(self._now())
            if stored != access_receipt or authority_ref is None:
                denial = "sealed_audit_receipt_differs"
            elif (
                authority_ref.requester_deployment_id != requester.deployment_id
                or authority_ref.requester_household_id != requester.household_id
                or authority_ref.requester_actor_id != requester.actor_id
                or authority_ref.requester_session_id != requester.session_id
            ):
                denial = "sealed_audit_requester_differs"
            elif (
                authority_ref.target_deployment_id != target_principal.deployment_id
                or authority_ref.target_household_id != target_principal.household_id
                or authority_ref.target_actor_id != target_principal.actor_id
                or authority_ref.target_subject != target_principal.actor_id
            ):
                denial = "sealed_audit_target_differs"
            elif access_receipt.scope_kind is not SuppressionScopeKind.SUBJECT:
                denial = "canonical_manifest_subject_scope_required"
            elif access_receipt.scope_ref != target_principal.actor_id:
                denial = "sealed_audit_scope_differs"
            elif now < access_receipt.issued_at:
                denial = "sealed_audit_access_not_yet_valid"
            elif now >= access_receipt.expires_at:
                denial = "sealed_audit_access_expired"
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                async with self._db.execute(
                    "SELECT (SELECT COUNT(*) FROM sealed_audit_access_events "
                    "WHERE access_receipt_id=? AND outcome='granted') + "
                    "(SELECT COUNT(*) FROM audit_trace_access_events "
                    "WHERE access_receipt_id=? AND outcome='granted') + "
                    "(SELECT COUNT(*) FROM canonical_manifest_access_events "
                    "WHERE access_receipt_id=? AND outcome='granted')",
                    (access_receipt.access_receipt_id,) * 3,
                ) as cursor:
                    usage_row = await cursor.fetchone()
                if (
                    denial is None
                    and usage_row is not None
                    and int(usage_row[0]) >= access_receipt.max_reads
                ):
                    denial = "sealed_audit_access_exhausted"
                if denial is None:
                    await self._validate_integrity()
                    await self._validate_manifest_principal_integrity_unlocked(
                        target_principal.actor_id
                    )
                    roots = await self._canonical_manifest_roots_unlocked(
                        target_principal.actor_id
                    )
                    manifest = CanonicalStateManifestV1(
                        storage_schema_version=SCHEMA_VERSION,
                        schema_checksum=SCHEMA_CHECKSUM,
                        initialization_receipt_hash=self._receipt.receipt_hash,
                        principal_ref_hash=_principal_ref_hash(target_principal),
                        table_roots=roots,
                        total_row_count=sum(item.row_count for item in roots),
                    )
                event_hash = await self._append_manifest_access_event_unlocked(
                    access_receipt_id=access_receipt.access_receipt_id,
                    manifest_payload_hash=("0" * 64 if manifest is None else manifest.payload_hash),
                    outcome="denied" if denial is not None else "granted",
                    reason_code=(
                        denial
                        if denial is not None
                        else "canonical_manifest_access_granted"
                    ),
                    occurred_at=now,
                )
                await self._db.execute("COMMIT")
                committed = True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
        if denial is not None or manifest is None or event_hash is None:
            raise SealedAuditAccessDenied(denial or "canonical_manifest_access_denied")
        return CanonicalStateManifestAccessV1(manifest, event_hash)

    async def _validate_manifest_principal_integrity_unlocked(
        self, principal_id: str
    ) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT evidence_id FROM evidence_envelopes WHERE principal_id=? "
            "ORDER BY evidence_id",
            (principal_id,),
        ) as cursor:
            evidence_rows = await cursor.fetchall()
        for row in evidence_rows:
            if await self._read_ingested_record(str(row["evidence_id"])) is None:
                raise MemoryCorruptionError("manifest evidence row disappeared")
        async with self._db.execute(
            "SELECT invocation_id FROM llm_invocations WHERE principal_id=? "
            "ORDER BY invocation_sequence",
            (principal_id,),
        ) as cursor:
            invocation_rows = await cursor.fetchall()
        for row in invocation_rows:
            invocation_id = str(row["invocation_id"])
            if await self._read_invocation(invocation_id) is None:
                raise MemoryCorruptionError("manifest invocation disappeared")
            await self._read_decisions(invocation_id)

    async def _canonical_manifest_roots_unlocked(
        self, principal_id: str
    ) -> tuple[CanonicalStateTableRootV1, ...]:
        from simple_harness_memory.core.audit import CanonicalStateTableRootV1

        assert self._db is not None
        specs = (
            (
                "current_heads",
                "cognitive_memory_heads",
                "SELECT t.* FROM cognitive_memory_heads t WHERE t.principal_id=? "
                "ORDER BY t.memory_id",
            ),
            (
                "current_heads",
                "recall_authority_heads",
                "SELECT t.* FROM recall_authority_heads t WHERE t.principal_id=? "
                "ORDER BY t.principal_id",
            ),
            (
                "decisions",
                "decision_records",
                "SELECT t.* FROM decision_records t WHERE t.principal_id=? "
                "ORDER BY t.decision_id",
            ),
            (
                "decisions",
                "memory_mutation_decisions",
                "SELECT t.* FROM memory_mutation_decisions t "
                "JOIN memory_mutation_receipts r ON r.receipt_id=t.receipt_id "
                "WHERE r.principal_id=? ORDER BY t.decision_id",
            ),
            (
                "decisions",
                "typed_recall_decisions",
                "SELECT t.* FROM typed_recall_decisions t JOIN typed_recall_requests r "
                "ON r.request_id=t.request_id WHERE r.principal_id=? "
                "ORDER BY t.decision_id",
            ),
            (
                "decisions",
                "cognitive_classification_decisions",
                "SELECT t.* FROM cognitive_classification_decisions t "
                "WHERE t.principal_id=? ORDER BY t.classification_decision_id",
            ),
            (
                "receipts",
                "ingestion_receipts",
                "SELECT t.* FROM ingestion_receipts t JOIN evidence_envelopes e "
                "ON e.evidence_id=t.evidence_id WHERE e.principal_id=? "
                "ORDER BY t.receipt_id",
            ),
            (
                "receipts",
                "memory_mutation_receipts",
                "SELECT t.* FROM memory_mutation_receipts t WHERE t.principal_id=? "
                "ORDER BY t.receipt_id",
            ),
            (
                "receipts",
                "recall_context_use_receipts",
                "SELECT t.* FROM recall_context_use_receipts t WHERE t.principal_id=? "
                "ORDER BY t.receipt_id",
            ),
            (
                "results",
                "memory_mutation_apply_results",
                "SELECT t.* FROM memory_mutation_apply_results t "
                "WHERE t.principal_id=? ORDER BY t.result_id",
            ),
            (
                "results",
                "typed_recall_results",
                "SELECT t.* FROM typed_recall_results t JOIN typed_recall_requests r "
                "ON r.request_id=t.request_id WHERE r.principal_id=? "
                "ORDER BY t.result_id",
            ),
            (
                "rows",
                "cognitive_memory_revisions",
                "SELECT t.* FROM cognitive_memory_revisions t WHERE t.principal_id=? "
                "ORDER BY t.memory_id,t.revision",
            ),
            (
                "rows",
                "evidence_envelopes",
                "SELECT t.* FROM evidence_envelopes t WHERE t.principal_id=? "
                "ORDER BY t.evidence_id",
            ),
            (
                "rows",
                "episode_records",
                "SELECT t.* FROM episode_records t JOIN cognitive_memory_revisions r "
                "ON r.memory_id=t.memory_id AND r.revision=t.revision "
                "WHERE r.principal_id=? ORDER BY t.memory_id,t.revision",
            ),
            (
                "rows",
                "semantic_claims",
                "SELECT t.* FROM semantic_claims t JOIN cognitive_memory_revisions r "
                "ON r.memory_id=t.memory_id AND r.revision=t.revision "
                "WHERE r.principal_id=? ORDER BY t.memory_id,t.revision",
            ),
            (
                "rows",
                "procedure_records",
                "SELECT t.* FROM procedure_records t JOIN cognitive_memory_revisions r "
                "ON r.memory_id=t.memory_id AND r.revision=t.revision "
                "WHERE r.principal_id=? ORDER BY t.memory_id,t.revision",
            ),
            (
                "rows",
                "prospective_records",
                "SELECT t.* FROM prospective_records t JOIN cognitive_memory_revisions r "
                "ON r.memory_id=t.memory_id AND r.revision=t.revision "
                "WHERE r.principal_id=? ORDER BY t.memory_id,t.revision",
            ),
            (
                "rows",
                "cognitive_relations",
                "SELECT t.* FROM cognitive_relations t WHERE t.principal_id=? "
                "ORDER BY t.relation_id",
            ),
            (
                "rows",
                "cognitive_conflict_groups",
                "SELECT t.* FROM cognitive_conflict_groups t WHERE t.principal_id=? "
                "ORDER BY t.group_id",
            ),
            (
                "rows",
                "cognitive_conflict_members",
                "SELECT t.* FROM cognitive_conflict_members t "
                "JOIN cognitive_conflict_groups g ON g.group_id=t.group_id "
                "WHERE g.principal_id=? ORDER BY t.group_id,t.ordinal",
            ),
            (
                "rows",
                "cognitive_conflict_resolutions",
                "SELECT t.* FROM cognitive_conflict_resolutions t "
                "WHERE t.principal_id=? ORDER BY t.group_id",
            ),
            (
                "rows",
                "cognitive_evidence_spans",
                "SELECT t.* FROM cognitive_evidence_spans t "
                "JOIN cognitive_memory_revisions r ON r.memory_id=t.memory_id "
                "AND r.revision=t.revision WHERE r.principal_id=? "
                "ORDER BY t.memory_id,t.revision,t.ordinal",
            ),
            (
                "rows",
                "suppression_directives",
                "SELECT t.* FROM suppression_directives t WHERE t.principal_id=? "
                "ORDER BY t.directive_id",
            ),
            (
                "rows",
                "suppression_targets",
                "SELECT t.* FROM suppression_targets t JOIN suppression_directives d "
                "ON d.directive_id=t.directive_id WHERE d.principal_id=? "
                "ORDER BY t.directive_id,t.ordinal",
            ),
            (
                "rows",
                "typed_recall_requests",
                "SELECT t.* FROM typed_recall_requests t WHERE t.principal_id=? "
                "ORDER BY t.request_id",
            ),
            (
                "rows",
                "typed_recall_attempts",
                "SELECT t.* FROM typed_recall_attempts t JOIN typed_recall_requests r "
                "ON r.request_id=t.request_id WHERE r.principal_id=? "
                "ORDER BY t.request_id,t.attempt_ordinal",
            ),
            (
                "rows",
                "typed_recall_decision_items",
                "SELECT t.* FROM typed_recall_decision_items t "
                "JOIN typed_recall_decisions d ON d.decision_id=t.decision_id "
                "JOIN typed_recall_requests r ON r.request_id=d.request_id "
                "WHERE r.principal_id=? ORDER BY t.decision_id,t.ordinal,t.item_id",
            ),
            (
                "rows",
                "typed_recall_result_items",
                "SELECT t.* FROM typed_recall_result_items t JOIN typed_recall_results x "
                "ON x.result_id=t.result_id JOIN typed_recall_requests r "
                "ON r.request_id=x.request_id WHERE r.principal_id=? "
                "ORDER BY t.result_id,t.ordinal",
            ),
            (
                "rows",
                "typed_recall_confirmation_groups",
                "SELECT t.* FROM typed_recall_confirmation_groups t "
                "JOIN typed_recall_results x ON x.result_id=t.result_id "
                "JOIN typed_recall_requests r ON r.request_id=x.request_id "
                "WHERE r.principal_id=? ORDER BY t.result_id,t.ordinal",
            ),
            (
                "rows",
                "typed_recall_confirmation_members",
                "SELECT t.* FROM typed_recall_confirmation_members t "
                "JOIN typed_recall_results x ON x.result_id=t.result_id "
                "JOIN typed_recall_requests r ON r.request_id=x.request_id "
                "WHERE r.principal_id=? "
                "ORDER BY t.result_id,t.group_ordinal,t.member_ordinal",
            ),
            (
                "rows",
                "memory_action_authority_consumptions",
                "SELECT t.* FROM memory_action_authority_consumptions t "
                "WHERE t.principal_id=? ORDER BY t.consumption_id",
            ),
            (
                "terminals",
                "typed_recall_terminals",
                "SELECT t.* FROM typed_recall_terminals t JOIN typed_recall_requests r "
                "ON r.request_id=t.request_id WHERE r.principal_id=? ORDER BY t.request_id",
            ),
        )
        roots: list[CanonicalStateTableRootV1] = []
        for category, table_name, sql in specs:
            async with self._db.execute(sql, (principal_id,)) as cursor:
                rows = await cursor.fetchall()
            leaves = tuple(
                hashlib.sha256(
                    canonical_json(
                        {
                            "schema_version": 1,
                            "table": table_name,
                            "row": _canonical_manifest_row(row),
                        }
                    ).encode()
                ).hexdigest()
                for row in rows
            )
            root_hash = hashlib.sha256(
                canonical_json(
                    {
                        "schema_version": 1,
                        "table": table_name,
                        "leaves": list(leaves),
                    }
                ).encode()
            ).hexdigest()
            roots.append(
                CanonicalStateTableRootV1(
                    category=category,
                    table_name=table_name,
                    row_count=len(leaves),
                    root_hash=root_hash,
                    first_leaf_hash=None if not leaves else leaves[0],
                    last_leaf_hash=None if not leaves else leaves[-1],
                )
            )
        return tuple(sorted(roots, key=lambda item: (item.category, item.table_name)))

    async def _append_manifest_access_event_unlocked(
        self,
        *,
        access_receipt_id: str,
        manifest_payload_hash: str,
        outcome: str,
        reason_code: str,
        occurred_at: float,
    ) -> str:
        assert self._db is not None
        event_id = f"canonical-manifest-event-{uuid4().hex}"
        payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "event_id": event_id,
            "access_receipt_id": access_receipt_id,
            "manifest_payload_hash": manifest_payload_hash,
            "outcome": outcome,
            "reason_code": reason_code,
            "occurred_at": occurred_at,
        }
        event_hash = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        await self._db.execute(
            "INSERT INTO canonical_manifest_access_events(event_id,access_receipt_id,"
            "manifest_payload_hash,outcome,reason_code,occurred_at,event_hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                event_id,
                access_receipt_id,
                manifest_payload_hash,
                outcome,
                reason_code,
                occurred_at,
                event_hash,
            ),
        )
        return event_hash

    async def _export_audit_trace(
        self,
        query: AuditTraceQuery,
        *,
        principal: MemoryPrincipal | None,
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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
            if principal is not None:
                await self._authorize_short_horizon_principal_unlocked(principal)
                if query.subject != principal.actor_id:
                    raise MemoryOwnershipConflict("audit_trace_principal_rejected")
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
                    lineage_refs = (
                        await self._read_memory_trace_lineage_unlocked(
                            query.selector_ref, invocation.invocation_id
                        )
                        if query.selector is AuditTraceSelector.MEMORY
                        else ()
                    )
                    item = AuditTraceItem(invocation, decisions, lineage_refs)
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

    async def _read_memory_trace_lineage_unlocked(
        self, memory_id: str, invocation_id: str
    ) -> tuple[AuditTraceLineageRef, ...]:
        from simple_harness_memory.core.audit import AuditTraceLineageRef

        assert self._db is not None
        queries = (
            (
                "canonical_memory_revision",
                "SELECT cr.content_hash FROM cognitive_memory_revisions cr "
                "WHERE cr.memory_id=? ORDER BY cr.revision",
                (memory_id,),
            ),
            (
                "accepted_plan",
                "SELECT ap.plan_hash FROM accepted_analysis_plans ap "
                "JOIN cognitive_memory_revisions cr ON cr.principal_id=ap.principal_id "
                "AND cr.plan_hash=ap.plan_hash WHERE cr.memory_id=? ORDER BY ap.plan_hash",
                (memory_id,),
            ),
            (
                "proposal",
                "SELECT COALESCE(b.result_hash,b.request_hash) FROM analysis_batches b "
                "JOIN accepted_analysis_plans ap ON ap.batch_id=b.batch_id "
                "JOIN cognitive_memory_revisions cr ON cr.principal_id=ap.principal_id "
                "AND cr.plan_hash=ap.plan_hash WHERE cr.memory_id=? AND EXISTS("
                "SELECT 1 FROM llm_invocations i WHERE i.invocation_id=? "
                "AND i.request_hash=b.request_hash) ORDER BY b.batch_id",
                (memory_id, invocation_id),
            ),
            (
                "mutation_receipt",
                "SELECT mr.receipt_hash FROM memory_mutation_receipts mr "
                "JOIN cognitive_classification_decisions cd ON cd.principal_id=mr.principal_id "
                "AND cd.plan_id=mr.plan_id WHERE cd.memory_id=? ORDER BY mr.receipt_id",
                (memory_id,),
            ),
            (
                "mutation_decision",
                "SELECT md.decision_hash FROM memory_mutation_decisions md "
                "JOIN cognitive_classification_decisions cd "
                "ON cd.classification_decision_id=md.classification_decision_id "
                "WHERE cd.memory_id=? ORDER BY md.decision_id",
                (memory_id,),
            ),
            (
                "classification",
                "SELECT decision_hash FROM cognitive_classification_decisions "
                "WHERE memory_id=? ORDER BY memory_revision",
                (memory_id,),
            ),
            (
                "evidence",
                "SELECT DISTINCT evidence_id FROM cognitive_evidence_spans "
                "WHERE memory_id=? ORDER BY evidence_id",
                (memory_id,),
            ),
        )
        refs: set[tuple[str, str]] = set()
        for kind, sql, params in queries:
            async with self._db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                value = str(row[0])
                refs.add(
                    (
                        kind,
                        hashlib.sha256(
                            canonical_json(
                                {
                                    "schema_version": 1,
                                    "kind": kind,
                                    "durable_ref": value,
                                }
                            ).encode()
                        ).hexdigest(),
                    )
                )
        return tuple(AuditTraceLineageRef(*item) for item in sorted(refs))

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
        elif denial is None and access_receipt.scope_kind is SuppressionScopeKind.MEMORY:
            if query.selector.value != "memory" or query.selector_ref != access_receipt.scope_ref:
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
            "WHERE access_receipt_id=? AND outcome='granted') + "
            "(SELECT COUNT(*) FROM canonical_manifest_access_events "
            "WHERE access_receipt_id=? AND outcome='granted')",
            (access_receipt.access_receipt_id,) * 3,
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
        """Deprecated self-mint path; authority references are mandatory in v6."""

        from simple_harness_memory.core.suppression import SealedAuditAccessDenied

        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        subject = getattr(decision, "subject", "invalid")
        ref_hash = hashlib.sha256(
            canonical_json(
                {
                    "schema_version": 1,
                    "domain": "audit-access-self-mint-denial",
                    "decision_hash": getattr(decision, "decision_hash", None),
                }
            ).encode()
        ).hexdigest()
        await self._record_audit_authority_event(
            principal_id=subject if isinstance(subject, str) and subject else "invalid",
            authority_ref_hash=ref_hash,
            outcome="denied",
            reason_code="audit_access_authority_ref_required",
        )
        raise SealedAuditAccessDenied("audit_access_authority_ref_required")

    async def authorize_audit_access(
        self,
        *,
        principal: MemoryPrincipal,
        authority_ref: AuditAccessAuthorityRefV1,
    ) -> SealedAuditAccessReceipt:
        from simple_harness_memory.core.audit import AuditAccessAuthorityRefV1
        from simple_harness_memory.core.identity import MemoryPrincipal
        from simple_harness_memory.core.suppression import (
            SealedAuditAccessDecision,
            SealedAuditAccessDenied,
            SealedAuditAccessReceipt,
        )

        if type(principal) is not MemoryPrincipal:
            raise TypeError("principal must use MemoryPrincipal")
        if type(authority_ref) is not AuditAccessAuthorityRefV1:
            raise TypeError("authority_ref must use AuditAccessAuthorityRefV1")
        if self._db is None or self._receipt is None:
            raise RuntimeError("human-memory v6 backend is not initialized")
        denial: str | None = None
        decision: object | None = None
        if self._audit_access_authority is None:
            denial = "audit_access_authority_unavailable"
        else:
            try:
                decision = await self._audit_access_authority.resolve_audit_access(authority_ref)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                denial = "audit_access_authority_resolution_failed"
        if denial is None and type(decision) is not SealedAuditAccessDecision:
            denial = "audit_access_authority_decision_invalid"
        if denial is None:
            assert isinstance(decision, SealedAuditAccessDecision)
            if (
                authority_ref.requester_deployment_id != principal.deployment_id
                or authority_ref.requester_household_id != principal.household_id
                or authority_ref.requester_actor_id != principal.actor_id
                or authority_ref.requester_session_id != principal.session_id
            ):
                denial = "audit_access_principal_differs"
            elif (
                authority_ref.decision_id != decision.decision_id
                or authority_ref.decision_hash != decision.decision_hash
                or authority_ref.target_subject != decision.subject
                or authority_ref.scope_kind is not decision.scope_kind
                or authority_ref.scope_ref != decision.scope_ref
                or authority_ref.issued_at != decision.issued_at
                or authority_ref.expires_at != decision.expires_at
            ):
                denial = "audit_access_authority_binding_differs"
        now = _timestamp(self._now())
        if denial is None and authority_ref.issued_at > now:
            denial = "sealed_audit_decision_not_yet_valid"
        if denial is None and now >= authority_ref.expires_at:
            denial = "sealed_audit_decision_expired"
        if denial is not None:
            await self._record_audit_authority_event(
                principal_id=principal.actor_id,
                authority_ref_hash=authority_ref.ref_hash,
                outcome="denied",
                reason_code=denial,
            )
            raise SealedAuditAccessDenied(denial)
        assert isinstance(decision, SealedAuditAccessDecision)
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
        ref_json = canonical_json(authority_ref.to_json())
        consumption_hash = hashlib.sha256(
            canonical_json(
                {
                    "schema_version": 1,
                    "authority_ref_hash": authority_ref.ref_hash,
                    "decision_hash": decision.decision_hash,
                    "receipt_hash": receipt.receipt_hash,
                    "principal_ref_hash": _principal_ref_hash(principal),
                }
            ).encode()
        ).hexdigest()
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            async with self._db.execute(
                "SELECT 1 FROM principals WHERE principal_id=? AND deployment_id=? "
                "AND household_id=? AND actor_id=?",
                (
                    authority_ref.target_subject,
                    authority_ref.target_deployment_id,
                    authority_ref.target_household_id,
                    authority_ref.target_actor_id,
                ),
            ) as target_cursor:
                if await target_cursor.fetchone() is None:
                    await self._append_audit_authority_event_unlocked(
                        principal_id=principal.actor_id,
                        authority_ref_hash=authority_ref.ref_hash,
                        outcome="denied",
                        reason_code="audit_access_target_principal_rejected",
                        occurred_at=now,
                    )
                    await self._db.commit()
                    raise SealedAuditAccessDenied("audit_access_target_principal_rejected")
            existing = await self._read_audit_access_by_decision(decision.decision_id)
            if existing is not None:
                stored_ref = await self._read_audit_authority_ref_by_decision(
                    decision.decision_id
                )
                if stored_ref != authority_ref:
                    await self._append_audit_authority_event_unlocked(
                        principal_id=principal.actor_id,
                        authority_ref_hash=authority_ref.ref_hash,
                        outcome="denied",
                        reason_code="audit_access_authority_replay_differs",
                        occurred_at=now,
                    )
                    await self._db.commit()
                    raise MemoryIdempotencyConflict(
                        "sealed_audit_authority_replay_conflict"
                    )
                if existing != receipt:
                    raise MemoryIdempotencyConflict("sealed_audit_decision_replay_conflict")
                await self._append_audit_authority_event_unlocked(
                    principal_id=principal.actor_id,
                    authority_ref_hash=authority_ref.ref_hash,
                    outcome="granted",
                    reason_code="audit_access_authority_replayed",
                    occurred_at=now,
                )
                await self._db.commit()
                return existing
            async with self._db.execute(
                "SELECT decision_id FROM sealed_audit_access_receipts WHERE "
                "authority_ref_hash=? OR (issuer_ref=? AND nonce=?) OR replay_identity=?",
                (
                    authority_ref.ref_hash,
                    authority_ref.issuer_ref,
                    authority_ref.nonce,
                    authority_ref.replay_identity,
                ),
            ) as collision_cursor:
                collision = await collision_cursor.fetchone()
            if collision is not None:
                await self._append_audit_authority_event_unlocked(
                    principal_id=principal.actor_id,
                    authority_ref_hash=authority_ref.ref_hash,
                    outcome="denied",
                    reason_code="audit_access_authority_replay_collision",
                    occurred_at=now,
                )
                await self._db.commit()
                raise MemoryIdempotencyConflict(
                    "sealed_audit_authority_replay_conflict"
                )
            begun = False
            committed = False
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                begun = True
                await self._db.execute(
                    "INSERT INTO sealed_audit_access_receipts(access_receipt_id,decision_id,"
                    "principal_id,purpose,scope_kind,scope_ref,reason_code,"
                    "disclosure_context_json,decision_hash,authority_ref_json,authority_ref_hash,"
                    "authority_id,issuer_ref,nonce,replay_identity,consumption_hash,max_reads,"
                    "issued_at,expires_at,receipt_hash) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                        ref_json,
                        authority_ref.ref_hash,
                        authority_ref.authority_id,
                        authority_ref.issuer_ref,
                        authority_ref.nonce,
                        authority_ref.replay_identity,
                        consumption_hash,
                        receipt.max_reads,
                        receipt.issued_at,
                        receipt.expires_at,
                        receipt.receipt_hash,
                    ),
                )
                await self._append_audit_authority_event_unlocked(
                    principal_id=principal.actor_id,
                    authority_ref_hash=authority_ref.ref_hash,
                    outcome="granted",
                    reason_code="audit_access_authority_granted",
                    occurred_at=now,
                )
                await self._db.execute("COMMIT")
                committed = True
            except BaseException:
                if begun and not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")
                raise
        return receipt

    async def _record_audit_authority_event(
        self,
        *,
        principal_id: str,
        authority_ref_hash: str,
        outcome: str,
        reason_code: str,
    ) -> None:
        assert self._db is not None
        async with self._write_lock:
            await self._db.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                await self._append_audit_authority_event_unlocked(
                    principal_id=principal_id,
                    authority_ref_hash=authority_ref_hash,
                    outcome=outcome,
                    reason_code=reason_code,
                    occurred_at=_timestamp(self._now()),
                )
                await self._db.execute("COMMIT")
                committed = True
            finally:
                if not committed:
                    with suppress(Exception):
                        await self._db.execute("ROLLBACK")

    async def _append_audit_authority_event_unlocked(
        self,
        *,
        principal_id: str,
        authority_ref_hash: str,
        outcome: str,
        reason_code: str,
        occurred_at: float,
    ) -> None:
        assert self._db is not None
        event_id = f"audit-authority-event-{uuid4().hex}"
        payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "event_id": event_id,
            "principal_ref_hash": hashlib.sha256(principal_id.encode()).hexdigest(),
            "authority_ref_hash": authority_ref_hash,
            "outcome": outcome,
            "reason_code": reason_code,
            "occurred_at": occurred_at,
        }
        await self._db.execute(
            "INSERT INTO audit_access_authority_events(event_id,principal_id,"
            "authority_ref_hash,outcome,reason_code,occurred_at,event_hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                event_id,
                principal_id,
                authority_ref_hash,
                outcome,
                reason_code,
                occurred_at,
                hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
            ),
        )

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
            raise RuntimeError("human-memory v6 backend is not initialized")
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
                "WHERE access_receipt_id=? AND outcome='granted') + "
                "(SELECT COUNT(*) FROM canonical_manifest_access_events "
                "WHERE access_receipt_id=? AND outcome='granted')",
                (access_receipt.access_receipt_id,) * 3,
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
        ref_value = json.loads(str(row["authority_ref_json"]))
        if not isinstance(ref_value, dict):
            raise MemoryCorruptionError("stored audit authority ref malformed")
        from simple_harness_memory.core.audit import AuditAccessAuthorityRefV1

        authority_ref = AuditAccessAuthorityRefV1.from_json(ref_value)
        expected_consumption_hash = hashlib.sha256(
            canonical_json(
                {
                    "schema_version": 1,
                    "authority_ref_hash": authority_ref.ref_hash,
                    "decision_hash": receipt.decision_hash,
                    "receipt_hash": receipt.receipt_hash,
                    "principal_ref_hash": _principal_ref_hash_values(
                        authority_ref.requester_deployment_id,
                        authority_ref.requester_household_id,
                        authority_ref.requester_actor_id,
                        authority_ref.requester_session_id,
                    ),
                }
            ).encode()
        ).hexdigest()
        if (
            receipt.receipt_hash != str(row["receipt_hash"])
            or canonical_json(authority_ref.to_json()) != str(row["authority_ref_json"])
            or authority_ref.ref_hash != str(row["authority_ref_hash"])
            or authority_ref.decision_id != receipt.decision_id
            or authority_ref.decision_hash != receipt.decision_hash
            or authority_ref.target_subject != receipt.subject
            or authority_ref.scope_kind is not receipt.scope_kind
            or authority_ref.scope_ref != receipt.scope_ref
            or authority_ref.issued_at != receipt.issued_at
            or authority_ref.expires_at != receipt.expires_at
            or authority_ref.authority_id != str(row["authority_id"])
            or authority_ref.issuer_ref != str(row["issuer_ref"])
            or authority_ref.nonce != str(row["nonce"])
            or authority_ref.replay_identity != str(row["replay_identity"])
            or expected_consumption_hash != str(row["consumption_hash"])
        ):
            raise MemoryCorruptionError("stored sealed audit access receipt hash differs")
        return receipt

    async def _read_audit_authority_ref_by_decision(
        self, decision_id: str
    ) -> AuditAccessAuthorityRefV1 | None:
        from simple_harness_memory.core.audit import AuditAccessAuthorityRefV1

        assert self._db is not None
        async with self._db.execute(
            "SELECT authority_ref_json FROM sealed_audit_access_receipts WHERE decision_id=?",
            (decision_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        value = json.loads(str(row["authority_ref_json"]))
        if not isinstance(value, dict):
            raise MemoryCorruptionError("stored audit authority ref malformed")
        return AuditAccessAuthorityRefV1.from_json(value)

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

    @staticmethod
    def _short_horizon_manifest_hash(rows: tuple[aiosqlite.Row, ...]) -> str:
        return hashlib.sha256(
            canonical_json(
                [
                    {"chunk_id": str(row["chunk_id"]), "content_hash": str(row["content_hash"])}
                    for row in rows
                ]
            ).encode()
        ).hexdigest()

    @staticmethod
    def _short_horizon_vector_manifest_hash(
        rows: tuple[tuple[str, str], ...],
    ) -> str:
        return hashlib.sha256(
            canonical_json(
                [
                    {"chunk_id": chunk_id, "embedding_hash": embedding_hash}
                    for chunk_id, embedding_hash in sorted(rows)
                ]
            ).encode()
        ).hexdigest()

    @staticmethod
    def _short_horizon_group_is_complete(rows: tuple[aiosqlite.Row, ...]) -> bool:
        """Reject mixed Host metadata; allow only genuinely in-flight incomplete groups."""

        if not rows:
            raise MemoryCorruptionError("short horizon causal group is empty")
        first = rows[0]
        expected = (
            str(first["subject"]),
            str(first["primary_conversation_id"]),
            str(first["causal_group_id"]),
            int(first["causal_group_sequence"]),
            int(first["group_item_count"]),
            str(first["ordered_group_manifest_hash"]),
        )
        if expected[4] < 1 or any(
            (
                str(row["subject"]),
                str(row["primary_conversation_id"]),
                str(row["causal_group_id"]),
                int(row["causal_group_sequence"]),
                int(row["group_item_count"]),
                str(row["ordered_group_manifest_hash"]),
            )
            != expected
            for row in rows
        ):
            raise MemoryCorruptionError("short horizon causal group metadata differs")
        ordinals = {int(row["item_ordinal"]) for row in rows}
        registrations = {str(row["registration_id"]) for row in rows}
        evidence_ids = {str(row["evidence_id"]) for row in rows}
        if len(registrations) != len(rows) or len(evidence_ids) != len(rows):
            raise MemoryCorruptionError("short horizon causal group contains duplicates")
        return ordinals == set(range(1, expected[4] + 1))

    @staticmethod
    def _assert_short_horizon_registration_metadata_binding(row: aiosqlite.Row) -> None:
        """Bind projection-routing columns back to immutable Host metadata."""

        from simple_harness.runtime import ConversationEvidenceMetadata

        try:
            raw_metadata = json.loads(str(row["metadata_json"]))
            if not isinstance(raw_metadata, dict):
                raise ValueError("metadata must be an object")
            metadata = ConversationEvidenceMetadata.from_json(raw_metadata)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("conversation registration metadata is invalid") from exc
        expected_tool_link = (
            None
            if metadata.tool_causal_link is None
            else canonical_json(metadata.tool_causal_link.to_json())
        )
        if (
            str(row["principal_id"]) != metadata.subject
            or str(row["run_id"]) != metadata.run_id
            or str(row["subject"]) != metadata.subject
            or str(row["conversation_id"]) != metadata.conversation_id
            or str(row["primary_conversation_id"]) != metadata.primary_conversation_id
            or str(row["causal_group_id"]) != metadata.causal_group_id
            or int(row["causal_group_sequence"]) != metadata.causal_group_sequence
            or int(row["item_ordinal"]) != metadata.item_ordinal
            or int(row["group_item_count"]) != metadata.group_item_count
            or str(row["ordered_group_manifest_hash"]) != metadata.ordered_group_manifest_hash
            or str(row["role"]) != metadata.role.value
            or float(row["occurred_at"]) != metadata.occurred_at
            or row["task_scope_id"] != metadata.task_scope_id
            or str(row["tool_causal_link_json"] or "") != (expected_tool_link or "")
            or str(row["entities_json"]) != canonical_json(list(metadata.entities))
        ):
            raise MemoryCorruptionError("conversation registration metadata binding differs")

    async def _current_short_horizon_manifest_hash_unlocked(self) -> str:
        assert self._db is not None
        async with self._db.execute(
            "SELECT chunk_id,content_hash FROM short_horizon_chunks ORDER BY chunk_id"
        ) as cursor:
            return self._short_horizon_manifest_hash(tuple(await cursor.fetchall()))

    async def _active_short_horizon_generation_unlocked(self) -> str | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT generation_id FROM short_horizon_generations WHERE state='active'"
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else str(row[0])

    async def _load_short_horizon_cache_unlocked(self) -> None:
        from simple_harness_memory.core.short_horizon import _ExactVectorGenerationCache
        from simple_harness_memory.embedders.base import decode_vector

        if self._db is None:
            self._short_horizon_cache = None
            return
        async with self._db.execute(
            "SELECT g.generation_id,g.lineage_id,g.content_hash,g.vector_manifest_hash,l.dimension "
            "FROM short_horizon_generations g JOIN embedding_lineages l "
            "ON l.lineage_id=g.lineage_id WHERE g.state='active'"
        ) as cursor:
            generation = await cursor.fetchone()
        if generation is None:
            self._short_horizon_cache = None
            return
        current_manifest = await self._current_short_horizon_manifest_hash_unlocked()
        if str(generation["content_hash"]) != current_manifest:
            self._short_horizon_cache = None
            return
        async with self._db.execute(
            "SELECT c.chunk_id,v.embedding,v.embedding_hash,v.dimension "
            "FROM short_horizon_chunks c "
            "LEFT JOIN short_horizon_vectors v ON v.chunk_id=c.chunk_id "
            "AND v.generation_id=? ORDER BY c.chunk_id",
            (generation["generation_id"],),
        ) as cursor:
            rows = tuple(await cursor.fetchall())
        if not rows or any(row["embedding"] is None for row in rows):
            raise MemoryCorruptionError("active short horizon generation is incomplete")
        dimension = int(generation["dimension"])
        if any(int(row["dimension"]) != dimension for row in rows):
            raise MemoryCorruptionError("active short horizon vector dimension differs")
        try:
            vectors = [decode_vector(bytes(row["embedding"])) for row in rows]
            if any(
                not isinstance(vector, list)
                or len(vector) != dimension
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    for value in vector
                )
                or not any(float(value) != 0.0 for value in vector)
                for vector in vectors
            ):
                raise ValueError("active short horizon vector values are invalid")
            vector_rows = tuple((str(row["chunk_id"]), str(row["embedding_hash"])) for row in rows)
            if any(
                hashlib.sha256(bytes(row["embedding"])).hexdigest() != str(row["embedding_hash"])
                for row in rows
            ) or self._short_horizon_vector_manifest_hash(vector_rows) != str(
                generation["vector_manifest_hash"]
            ):
                raise ValueError("active short horizon vector hashes are invalid")
            self._short_horizon_cache = _ExactVectorGenerationCache(
                generation_id=str(generation["generation_id"]),
                lineage_id=str(generation["lineage_id"]),
                memory_refs=[str(row["chunk_id"]) for row in rows],
                vectors=vectors,
            )
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError("active short horizon vectors are invalid") from exc

    async def _ensure_system_principal_unlocked(self, created_at: float) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT INTO principals(principal_id,deployment_id,household_id,actor_id,created_at) "
            "VALUES('system','system','system','system',?) ON CONFLICT(principal_id) DO NOTHING",
            (created_at,),
        )

    async def _authorize_short_horizon_principal_unlocked(self, principal: MemoryPrincipal) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT 1 FROM principals WHERE principal_id=? AND deployment_id=? "
            "AND household_id=? AND actor_id=?",
            (
                principal.actor_id,
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
            ),
        ) as cursor:
            if await cursor.fetchone() is None:
                raise MemoryOwnershipConflict("short_horizon_principal_rejected")

    async def _record_short_horizon_recall_attempt(
        self,
        *,
        principal: MemoryPrincipal,
        audit_id: str,
        disclosure_context_hash: str,
        query_hash: str,
        deadline_ms: int,
        created_at: float,
    ) -> str:
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            return await self._append_short_horizon_audit_transaction(
                audit_id=audit_id,
                principal_id=principal.actor_id,
                event_kind="recall_started",
                disclosure_context_hash=disclosure_context_hash,
                query_hash=query_hash,
                details={"deadline_ms": deadline_ms, "gate_outcome": "in_progress"},
                created_at=created_at,
            )

    def _schedule_short_horizon_recall_terminal(
        self,
        *,
        principal: MemoryPrincipal,
        attempt_audit_id: str,
        disclosure_context_hash: str,
        query_hash: str,
        deadline_ms: int,
        created_at: float,
    ) -> None:
        """Queue a terminal audit for a caller-timed-out recall without blocking it."""

        terminal_task = asyncio.create_task(
            self._record_short_horizon_recall_terminal(
                principal=principal,
                attempt_audit_id=attempt_audit_id,
                disclosure_context_hash=disclosure_context_hash,
                query_hash=query_hash,
                deadline_ms=deadline_ms,
                created_at=created_at,
            )
        )
        self._track_short_horizon_audit_task(terminal_task)

    async def _record_short_horizon_recall_terminal(
        self,
        *,
        principal: MemoryPrincipal,
        attempt_audit_id: str,
        disclosure_context_hash: str,
        query_hash: str,
        deadline_ms: int,
        created_at: float,
    ) -> str:
        async with self._write_lock:
            await self._authorize_short_horizon_principal_unlocked(principal)
            return await self._append_short_horizon_audit_transaction(
                principal_id=principal.actor_id,
                event_kind="recall_terminal",
                disclosure_context_hash=disclosure_context_hash,
                query_hash=query_hash,
                degradation_code="DEADLINE_EXCEEDED",
                details={
                    "attempt_audit_id": attempt_audit_id,
                    "deadline_ms": deadline_ms,
                    "gate_outcome": "deadline_exceeded",
                },
                created_at=created_at,
            )

    async def _begin_short_horizon_recall(self) -> None:
        """Admit one recall before close can snapshot its audit obligations."""

        async with self._short_horizon_recall_lifecycle_lock:
            if self._short_horizon_closing or self._db is None or self._receipt is None:
                raise RuntimeError("human-memory v6 backend is not initialized")
            self._short_horizon_active_recalls += 1
            self._short_horizon_recall_idle.clear()

    async def _finish_short_horizon_recall(self) -> None:
        async with self._short_horizon_recall_lifecycle_lock:
            if self._short_horizon_active_recalls < 1:
                raise AssertionError("short horizon recall lifecycle underflow")
            self._short_horizon_active_recalls -= 1
            if self._short_horizon_active_recalls == 0:
                self._short_horizon_recall_idle.set()

    def _track_short_horizon_audit_task(self, task: asyncio.Task[str]) -> None:
        """Keep detached audit work alive until close can verify its durable result."""

        self._short_horizon_audit_tasks.add(task)
        task.add_done_callback(self._short_horizon_audit_tasks.discard)

    async def _drain_short_horizon_audit_tasks(self) -> None:
        """Persist every returned-call audit before releasing the SQLite connection."""

        while self._short_horizon_audit_tasks:
            tasks = tuple(self._short_horizon_audit_tasks)
            await asyncio.gather(*tasks)

    async def _append_short_horizon_audit_transaction(self, **kwargs: object) -> str:
        assert self._db is not None
        await self._db.execute("BEGIN IMMEDIATE")
        committed = False
        try:
            audit_id = await self._append_short_horizon_audit_unlocked(**kwargs)
            await self._db.execute("COMMIT")
            committed = True
            return audit_id
        finally:
            if not committed:
                with suppress(Exception):
                    await self._db.execute("ROLLBACK")

    async def _append_short_horizon_audit_unlocked(
        self,
        *,
        principal_id: object,
        event_kind: object,
        disclosure_context_hash: object = None,
        query_hash: object = None,
        generation_id: object = None,
        generation_state: object = None,
        eligible_count: object = 0,
        fts_count: object = 0,
        entity_time_count: object = 0,
        vector_count: object = 0,
        degradation_code: object = None,
        details: object = None,
        created_at: object,
        audit_id: object = None,
    ) -> str:
        assert self._db is not None
        principal_value = str(principal_id)
        created = _timestamp(created_at)
        if principal_value == "system":
            await self._ensure_system_principal_unlocked(created)
        if details is None:
            detail_value: dict[str, JsonValue] = {}
        elif isinstance(details, dict):
            detail_value = cast(dict[str, JsonValue], details)
        else:
            raise TypeError("short horizon audit details must be a dictionary")
        audit_id_value = f"short-audit:{uuid4().hex}" if audit_id is None else str(audit_id)
        if not audit_id_value.startswith("short-audit:") or len(audit_id_value) > 128:
            raise MemoryValidationError("short_horizon_audit_id_invalid")
        payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "audit_id": audit_id_value,
            "principal_id": principal_value,
            "event_kind": str(event_kind),
            "disclosure_context_hash": cast(str | None, disclosure_context_hash),
            "query_hash": cast(str | None, query_hash),
            "generation_id": cast(str | None, generation_id),
            "generation_state": cast(str | None, generation_state),
            "eligible_count": int(cast(int, eligible_count)),
            "fts_count": int(cast(int, fts_count)),
            "entity_time_count": int(cast(int, entity_time_count)),
            "vector_count": int(cast(int, vector_count)),
            "degradation_code": cast(str | None, degradation_code),
            "details": detail_value,
            "created_at": created,
        }
        audit_json = canonical_json(payload)
        audit_hash = hashlib.sha256(audit_json.encode()).hexdigest()
        await self._db.execute(
            "INSERT INTO short_horizon_audit(audit_id,principal_id,event_kind,"
            "disclosure_context_hash,query_hash,generation_id,generation_state,eligible_count,"
            "fts_count,entity_time_count,vector_count,degradation_code,audit_json,audit_hash,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id_value,
                principal_value,
                event_kind,
                disclosure_context_hash,
                query_hash,
                generation_id,
                generation_state,
                eligible_count,
                fts_count,
                entity_time_count,
                vector_count,
                degradation_code,
                audit_json,
                audit_hash,
                created,
            ),
        )
        return audit_id_value

    async def _validate_integrity(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA integrity_check") as cursor:
            integrity = await cursor.fetchone()
        if integrity is None or str(integrity[0]) != "ok":
            raise MemoryCorruptionError("human-memory v6 integrity check failed")
        async with self._db.execute("PRAGMA foreign_key_check") as cursor:
            if await cursor.fetchone() is not None:
                raise MemoryCorruptionError("human-memory v6 foreign key check failed")
        async with self._db.execute(
            "SELECT 1 FROM cognitive_memory_heads h "
            "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
            "WHERE h.principal_id<>r.principal_id "
            "OR h.deployment_id<>r.deployment_id OR h.household_id<>r.household_id "
            "OR h.scope_kind<>r.scope_kind "
            "OR h.scope_owner<>r.scope_owner LIMIT 1"
        ) as cursor:
            if await cursor.fetchone() is not None:
                raise MemoryCorruptionError("cognitive memory scope integrity check failed")
        await self._validate_cognitive_conflict_integrity_unlocked()
        await self._validate_short_horizon_integrity_unlocked()
        await self._validate_lifecycle_integrity_unlocked()
        await self._validate_audit_access_integrity_unlocked()
        await self._validate_typed_recall_integrity_unlocked()

    async def _validate_audit_access_integrity_unlocked(self) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT decision_id FROM sealed_audit_access_receipts ORDER BY decision_id"
        ) as cursor:
            receipts = await cursor.fetchall()
        for row in receipts:
            if await self._read_audit_access_by_decision(str(row["decision_id"])) is None:
                raise MemoryCorruptionError("sealed audit receipt disappeared")
        for table_name, payload_hash_column in (
            ("audit_access_authority_events", "authority_ref_hash"),
            ("canonical_manifest_access_events", "manifest_payload_hash"),
        ):
            async with self._db.execute(
                f"SELECT * FROM {table_name} ORDER BY event_id"
            ) as cursor:
                events = await cursor.fetchall()
            for row in events:
                if table_name == "audit_access_authority_events":
                    payload: dict[str, JsonValue] = {
                        "schema_version": 1,
                        "event_id": str(row["event_id"]),
                        "principal_ref_hash": hashlib.sha256(
                            str(row["principal_id"]).encode()
                        ).hexdigest(),
                        payload_hash_column: str(row[payload_hash_column]),
                        "outcome": str(row["outcome"]),
                        "reason_code": str(row["reason_code"]),
                        "occurred_at": float(row["occurred_at"]),
                    }
                else:
                    payload = {
                        "schema_version": 1,
                        "event_id": str(row["event_id"]),
                        "access_receipt_id": str(row["access_receipt_id"]),
                        payload_hash_column: str(row[payload_hash_column]),
                        "outcome": str(row["outcome"]),
                        "reason_code": str(row["reason_code"]),
                        "occurred_at": float(row["occurred_at"]),
                    }
                if hashlib.sha256(canonical_json(payload).encode()).hexdigest() != str(
                    row["event_hash"]
                ):
                    raise MemoryCorruptionError("audit access event hash differs")

    async def _validate_typed_recall_integrity_unlocked(self) -> None:
        """Recompute every typed Recall hash and ordered body projection on reopen."""

        assert self._db is not None
        async with self._db.execute(
            "SELECT (SELECT COUNT(*) FROM typed_recall_requests) + "
            "(SELECT COUNT(*) FROM recall_context_use_receipts) + "
            "(SELECT COUNT(*) FROM recall_authority_events)"
        ) as cursor:
            populated = await cursor.fetchone()
        if populated is None or int(populated[0]) == 0:
            return

        from simple_harness.runtime import (
            RecallContext,
            RecallContextUseAuthorizationRequestV1,
            RecallContextUseReceiptV1,
            RecallDecisionV4,
            RecallPlan,
            TypedRecallResultV1,
        )

        from simple_harness_memory.core.recall import request_hash

        async with self._db.execute(
            "SELECT * FROM recall_authority_events ORDER BY principal_id,authority_epoch"
        ) as cursor:
            events = tuple(await cursor.fetchall())
        latest: dict[str, tuple[int, str]] = {}
        for event in events:
            raw = str(event["event_json"])
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or hashlib.sha256(canonical_json(payload).encode()).hexdigest()
                != str(event["event_hash"])
                or canonical_json(payload) != raw
                or payload.get("event_id") != event["event_id"]
                or payload.get("principal_id") != event["principal_id"]
                or payload.get("previous_epoch") != event["previous_epoch"]
                or payload.get("authority_epoch") != event["authority_epoch"]
                or payload.get("event_kind") != event["event_kind"]
                or payload.get("source_ref_hash") != event["source_ref_hash"]
                or payload.get("policy_hash") != event["policy_hash"]
                or payload.get("created_at") != event["created_at"]
                or (
                    int(event["previous_epoch"]) > 0
                    and payload.get("previous_policy_hash")
                    != latest.get(str(event["principal_id"]), (0, ""))[1]
                )
            ):
                raise MemoryCorruptionError("typed recall authority event differs")
            principal_id = str(event["principal_id"])
            expected_previous = latest.get(principal_id, (0, ""))[0]
            if int(event["previous_epoch"]) != expected_previous:
                raise MemoryCorruptionError("typed recall authority chain differs")
            latest[principal_id] = (
                int(event["authority_epoch"]),
                str(event["policy_hash"]),
            )
        async with self._db.execute("SELECT * FROM recall_authority_heads") as cursor:
            heads = tuple(await cursor.fetchall())
        if any(
            latest.get(str(row["principal_id"]))
            != (int(row["authority_epoch"]), str(row["policy_hash"]))
            for row in heads
        ) or set(latest) != {str(row["principal_id"]) for row in heads}:
            raise MemoryCorruptionError("typed recall authority head differs")

        async with self._db.execute("SELECT * FROM typed_recall_requests") as cursor:
            requests = tuple(await cursor.fetchall())
        requests_by_id = {str(row["request_id"]): row for row in requests}
        request_bindings: dict[str, tuple[RecallContext, RecallPlan]] = {}
        for row in requests:
            raw = str(row["request_json"])
            payload = json.loads(raw)
            if not isinstance(payload, dict) or canonical_json(payload) != raw:
                raise MemoryCorruptionError("typed recall request body differs")
            context_raw = payload.get("context")
            plan_raw = payload.get("plan")
            if not isinstance(context_raw, dict) or not isinstance(plan_raw, dict):
                raise MemoryCorruptionError("typed recall request binding missing")
            context = RecallContext.from_json(context_raw)
            plan = RecallPlan.from_json(plan_raw)
            if (
                payload.get("principal_id") != row["principal_id"]
                or plan.idempotency_key != row["idempotency_key"]
                or row["request_id"]
                != _stable_id(
                    "typed-recall-request",
                    str(row["principal_id"]),
                    str(row["idempotency_key"]),
                )
                or float(row["deadline_at"])
                != float(row["created_at"]) + plan.budget.deadline_ms / 1_000
                or request_hash(
                    principal_id=str(row["principal_id"]), context=context, plan=plan
                )
                != row["request_hash"]
            ):
                raise MemoryCorruptionError("typed recall request hash differs")
            request_bindings[str(row["request_id"])] = (context, plan)
        async with self._db.execute("SELECT * FROM typed_recall_attempts") as cursor:
            attempts = tuple(await cursor.fetchall())
        attempt_requests: dict[str, str] = {}
        for row in attempts:
            attempt_payload: dict[str, JsonValue] = {
                "request_id": str(row["request_id"]),
                "attempt_id": str(row["attempt_id"]),
                "attempt_ordinal": int(row["attempt_ordinal"]),
                "started_at": float(row["started_at"]),
            }
            if (
                str(row["request_id"]) not in requests_by_id
                or row["attempt_id"]
                != _stable_id(
                    "typed-recall-attempt",
                    str(row["request_id"]),
                    str(row["attempt_ordinal"]),
                )
                or hashlib.sha256(canonical_json(attempt_payload).encode()).hexdigest()
                != row["attempt_hash"]
            ):
                raise MemoryCorruptionError("typed recall attempt hash differs")
            attempt_requests[str(row["attempt_id"])] = str(row["request_id"])

        async with self._db.execute("SELECT * FROM typed_recall_decisions") as cursor:
            decision_rows = tuple(await cursor.fetchall())
        decisions: dict[str, RecallDecisionV4] = {}
        decision_requests: dict[str, str] = {}
        for row in decision_rows:
            raw = str(row["decision_json"])
            payload = json.loads(raw)
            if not isinstance(payload, dict) or canonical_json(payload) != raw:
                raise MemoryCorruptionError("typed recall decision body differs")
            decision = RecallDecisionV4.from_json(payload)
            request_row = requests_by_id.get(str(row["request_id"]))
            binding = request_bindings.get(str(row["request_id"]))
            if (
                request_row is None
                or binding is None
                or decision.decision_id != row["decision_id"]
                or decision.decision_hash != row["decision_hash"]
                or decision.decided_at != row["created_at"]
            ):
                raise MemoryCorruptionError("typed recall decision hash differs")
            try:
                decision.validate_bindings(
                    binding[0], binding[1], current_time=decision.decided_at
                )
            except (TypeError, ValueError) as exc:
                raise MemoryCorruptionError("typed recall decision binding differs") from exc
            async with self._db.execute(
                "SELECT * FROM typed_recall_decision_items WHERE decision_id=? "
                "ORDER BY ordinal",
                (decision.decision_id,),
            ) as cursor:
                item_rows = tuple(await cursor.fetchall())
            expected_items = (*decision.selected_items, *(
                member for group in decision.confirmation_groups for member in group.members
            ))
            if len(item_rows) != len(expected_items):
                raise MemoryCorruptionError("typed recall decision items differ")
            for ordinal, (item_row, item) in enumerate(
                zip(item_rows, expected_items, strict=True), start=1
            ):
                if (
                    int(item_row["ordinal"]) != ordinal
                    or item_row["item_id"] != item.item_id
                    or item_row["item_kind"] != item.item_kind.value
                    or item_row["item_hash"] != item.item_hash
                    or str(item_row["item_json"]) != canonical_json(item.to_json())
                ):
                    raise MemoryCorruptionError("typed recall decision item hash differs")
            decisions[decision.decision_id] = decision
            decision_requests[decision.decision_id] = str(row["request_id"])

        async with self._db.execute("SELECT * FROM typed_recall_results") as cursor:
            result_rows = tuple(await cursor.fetchall())
        results: dict[str, TypedRecallResultV1] = {}
        for row in result_rows:
            raw = str(row["result_json"])
            payload = json.loads(raw)
            if not isinstance(payload, dict) or canonical_json(payload) != raw:
                raise MemoryCorruptionError("typed recall result body differs")
            result = TypedRecallResultV1.from_json(payload)
            decision = decisions.get(result.decision_id)
            if (
                decision is None
                or result.result_id != row["result_id"]
                or result.decision_id != row["decision_id"]
                or str(row["request_id"])
                != decision_requests.get(result.decision_id)
                or result.result_hash != row["result_hash"]
                or result.authority_epoch != row["authority_epoch"]
                or result.policy_hash != row["policy_hash"]
                or result.authority_expires_at != row["authority_expires_at"]
                or result.evaluated_at != row["created_at"]
            ):
                raise MemoryCorruptionError("typed recall result hash differs")
            result.validate_decision(decision)
            async with self._db.execute(
                "SELECT * FROM typed_recall_result_items WHERE result_id=? ORDER BY ordinal",
                (result.result_id,),
            ) as cursor:
                item_rows = tuple(await cursor.fetchall())
            if len(item_rows) != len(result.items):
                raise MemoryCorruptionError("typed recall result items differ")
            for ordinal, (item_row, item) in enumerate(
                zip(item_rows, result.items, strict=True), start=1
            ):
                if (
                    int(item_row["ordinal"]) != ordinal
                    or item_row["item_id"] != item.selected_item.item_id
                    or item_row["result_item_hash"] != item.result_item_hash
                    or str(item_row["result_item_json"]) != canonical_json(item.to_json())
                ):
                    raise MemoryCorruptionError("typed recall result item hash differs")
            for ordinal, group in enumerate(result.confirmation_groups, start=1):
                async with self._db.execute(
                    "SELECT * FROM typed_recall_confirmation_groups WHERE result_id=? "
                    "AND ordinal=?",
                    (result.result_id, ordinal),
                ) as cursor:
                    group_row = await cursor.fetchone()
                if (
                    group_row is None
                    or group_row["group_id"] != group.group.conflict_group_id
                    or group_row["group_hash"] != group.result_group_hash
                    or str(group_row["group_json"]) != canonical_json(group.to_json())
                ):
                    raise MemoryCorruptionError("typed recall confirmation group differs")
                async with self._db.execute(
                    "SELECT * FROM typed_recall_confirmation_members WHERE result_id=? "
                    "AND group_ordinal=? ORDER BY member_ordinal",
                    (result.result_id, ordinal),
                ) as cursor:
                    member_rows = tuple(await cursor.fetchall())
                if len(member_rows) != len(group.members):
                    raise MemoryCorruptionError("typed recall confirmation members differ")
                for member_ordinal, (member_row, member) in enumerate(
                    zip(member_rows, group.members, strict=True), start=1
                ):
                    if (
                        int(member_row["member_ordinal"]) != member_ordinal
                        or member_row["item_id"] != member.member.item_id
                        or member_row["member_hash"] != member.result_member_hash
                        or str(member_row["member_json"])
                        != canonical_json(member.to_json())
                    ):
                        raise MemoryCorruptionError(
                            "typed recall confirmation member differs"
                        )
            async with self._db.execute(
                "SELECT COUNT(*),COALESCE(MIN(ordinal),0),COALESCE(MAX(ordinal),0) "
                "FROM typed_recall_confirmation_groups WHERE result_id=?",
                (result.result_id,),
            ) as cursor:
                group_count_row = await cursor.fetchone()
            assert group_count_row is not None
            expected_group_count = len(result.confirmation_groups)
            if (
                int(group_count_row[0]) != expected_group_count
                or (
                    expected_group_count > 0
                    and (int(group_count_row[1]), int(group_count_row[2]))
                    != (1, expected_group_count)
                )
            ):
                raise MemoryCorruptionError("typed recall confirmation cardinality differs")
            results[result.result_id] = result

        async with self._db.execute("SELECT * FROM typed_recall_terminals") as cursor:
            terminals = tuple(await cursor.fetchall())
        for row in terminals:
            raw = str(row["terminal_json"])
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or canonical_json(payload) != raw
                or hashlib.sha256(raw.encode()).hexdigest() != row["terminal_hash"]
                or payload.get("request_id") != row["request_id"]
                or payload.get("attempt_id") != row["attempt_id"]
                or payload.get("terminal_kind") != row["terminal_kind"]
                or str(row["request_id"]) not in requests_by_id
                or attempt_requests.get(str(row["attempt_id"])) != row["request_id"]
                or payload.get("decision_id") != row["decision_id"]
                or payload.get("decision_hash") != row["decision_hash"]
                or payload.get("result_id") != row["result_id"]
                or payload.get("result_hash") != row["result_hash"]
                or payload.get("created_at") != row["created_at"]
                or payload.get("candidate_query_started")
                != bool(row["candidate_query_started"])
                or payload.get("candidate_query_count") != row["candidate_query_count"]
                or payload.get("unsupported_capabilities")
                != json.loads(str(row["unsupported_capabilities_json"]))
                or payload.get("degradation_codes")
                != json.loads(str(row["degradation_codes_json"]))
            ):
                raise MemoryCorruptionError("typed recall terminal hash differs")
            if row["result_id"] is not None:
                result = results.get(str(row["result_id"]))
                decision = decisions.get(str(row["decision_id"]))
                if (
                    result is None
                    or decision is None
                    or result.decision_id != decision.decision_id
                    or decision_requests.get(decision.decision_id) != row["request_id"]
                    or payload.get("decision_id") != row["decision_id"]
                    or payload.get("decision_hash") != decision.decision_hash
                    or payload.get("result_id") != row["result_id"]
                    or payload.get("result_hash") != result.result_hash
                    or row["created_at"] != decision.decided_at
                    or row["created_at"] != result.evaluated_at
                ):
                    raise MemoryCorruptionError("typed recall terminal result missing")
            elif any(
                row[column] is not None
                for column in ("decision_id", "decision_hash", "result_hash")
            ):
                raise MemoryCorruptionError("typed recall terminal null result differs")

        async with self._db.execute("SELECT * FROM recall_context_use_receipts") as cursor:
            receipt_rows = tuple(await cursor.fetchall())
        for row in receipt_rows:
            request_payload = json.loads(str(row["request_json"]))
            receipt_payload = json.loads(str(row["receipt_json"]))
            if not isinstance(request_payload, dict) or not isinstance(receipt_payload, dict):
                raise MemoryCorruptionError("recall context-use body differs")
            if (
                canonical_json(request_payload) != str(row["request_json"])
                or canonical_json(receipt_payload) != str(row["receipt_json"])
            ):
                raise MemoryCorruptionError("recall context-use canonical body differs")
            request = RecallContextUseAuthorizationRequestV1.from_json(request_payload)
            receipt = RecallContextUseReceiptV1.from_json(receipt_payload)
            receipt.validate_request(request)
            decision = decisions.get(request.decision_id)
            result = results.get(request.result_id)
            expected_bindings: dict[str, str] = {}
            if result is not None:
                expected_bindings.update(
                    {
                        item.selected_item.item_id: item.result_item_hash
                        for item in result.items
                    }
                )
                expected_bindings.update(
                    {
                        member.member.item_id: member.result_member_hash
                        for group in result.confirmation_groups
                        for member in group.members
                    }
                )
            requested_item_ids = {binding.item_id for binding in request.item_bindings}
            incomplete_confirmation = bool(
                result is not None
                and any(
                    bool(
                        requested_item_ids
                        & {member.member.item_id for member in group.members}
                    )
                    and not {
                        member.member.item_id for member in group.members
                    }.issubset(requested_item_ids)
                    for group in result.confirmation_groups
                )
            )
            if (
                request.request_hash != row["request_hash"]
                or receipt.receipt_hash != row["receipt_hash"]
                or receipt.authority_epoch != row["authority_epoch"]
                or receipt.policy_hash != row["policy_hash"]
                or receipt.authorized_at != row["authorized_at"]
                or receipt.expires_at != row["expires_at"]
                or receipt.receipt_id != row["receipt_id"]
                or receipt.provider_attempt_id != row["provider_attempt_id"]
                or receipt.subject != row["principal_id"]
                or decision is None
                or result is None
                or request.decision_hash != decision.decision_hash
                or request.result_hash != result.result_hash
                or result.decision_id != decision.decision_id
                or requests_by_id[
                    decision_requests[decision.decision_id]
                ]["principal_id"]
                != row["principal_id"]
                or request.subject != decision.subject
                or request.run_id != decision.run_id
                or incomplete_confirmation
                or any(
                    expected_bindings.get(binding.item_id) != binding.item_hash
                    for binding in request.item_bindings
                )
            ):
                raise MemoryCorruptionError("recall context-use hash differs")

    async def _validate_cognitive_conflict_integrity_unlocked(self) -> None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT * FROM cognitive_conflict_groups ORDER BY group_id"
        ) as cursor:
            groups = tuple(await cursor.fetchall())
        active_group_keys: set[tuple[str, int]] = set()
        for group in groups:
            group_id = str(group["group_id"])
            principal_id = str(group["principal_id"])
            memory_id = str(group["memory_id"])
            incumbent_revision = int(group["incumbent_revision"])
            challenger_revision = int(group["challenger_revision"])
            async with self._db.execute(
                "SELECT * FROM cognitive_conflict_members WHERE group_id=? "
                "ORDER BY ordinal",
                (group_id,),
            ) as cursor:
                members = tuple(await cursor.fetchall())
            if (
                len(members) != 2
                or [int(row["ordinal"]) for row in members] != [1, 2]
                or [str(row["role"]) for row in members]
                != ["incumbent", "challenger"]
                or [int(row["revision"]) for row in members]
                != [incumbent_revision, challenger_revision]
                or any(
                    str(row["principal_id"]) != principal_id
                    or str(row["memory_id"]) != memory_id
                    for row in members
                )
            ):
                raise MemoryCorruptionError("conflict member cardinality differs")
            member_hashes: list[str] = []
            for member in members:
                revision = int(member["revision"])
                async with self._db.execute(
                    "SELECT principal_id,content_hash,conflict_status FROM "
                    "cognitive_memory_revisions WHERE memory_id=? AND revision=?",
                    (memory_id, revision),
                ) as cursor:
                    revision_row = await cursor.fetchone()
                evidence_hash = await self._cognitive_evidence_set_hash_unlocked(
                    memory_id, revision
                )
                if (
                    revision_row is None
                    or str(revision_row["principal_id"]) != principal_id
                    or str(revision_row["content_hash"]) != str(member["content_hash"])
                    or evidence_hash != str(member["evidence_set_hash"])
                ):
                    raise MemoryCorruptionError("conflict member source differs")
                if int(member["ordinal"]) == 2 and str(
                    revision_row["conflict_status"]
                ) != "contested":
                    raise MemoryCorruptionError("conflict challenger state differs")
                member_payload: dict[str, JsonValue] = {
                    "group_id": group_id,
                    "ordinal": int(member["ordinal"]),
                    "role": str(member["role"]),
                    "principal_id": principal_id,
                    "memory_id": memory_id,
                    "revision": revision,
                    "content_hash": str(member["content_hash"]),
                    "evidence_set_hash": evidence_hash,
                }
                member_hash = hashlib.sha256(
                    canonical_json(member_payload).encode("utf-8")
                ).hexdigest()
                if member_hash != str(member["member_hash"]):
                    raise MemoryCorruptionError("conflict member hash differs")
                member_hashes.append(member_hash)
            group_payload: dict[str, JsonValue] = {
                "group_id": group_id,
                "principal_id": principal_id,
                "memory_id": memory_id,
                "incumbent_revision": incumbent_revision,
                "challenger_revision": challenger_revision,
                "creation_plan_id": str(group["creation_plan_id"]),
                "creation_plan_hash": str(group["creation_plan_hash"]),
                "operation_id": str(group["operation_id"]),
                "created_at": float(group["created_at"]),
                "member_hashes": [cast(JsonValue, value) for value in member_hashes],
            }
            if hashlib.sha256(
                canonical_json(group_payload).encode("utf-8")
            ).hexdigest() != str(group["group_hash"]):
                raise MemoryCorruptionError("conflict group hash differs")
            async with self._db.execute(
                "SELECT * FROM cognitive_relations WHERE principal_id=? AND plan_id=? "
                "AND operation_id=? AND relation_kind='contests' AND source_memory_id=? "
                "AND source_revision=? AND target_memory_id=? AND target_revision=?",
                (
                    principal_id,
                    group["creation_plan_id"],
                    group["operation_id"],
                    memory_id,
                    challenger_revision,
                    memory_id,
                    incumbent_revision,
                ),
            ) as cursor:
                relations = tuple(await cursor.fetchall())
            if len(relations) != 1:
                raise MemoryCorruptionError("conflict relation cardinality differs")
            relation = relations[0]
            relation_payload: dict[str, JsonValue] = {
                "relation_id": str(relation["relation_id"]),
                "principal_id": principal_id,
                "plan_id": str(relation["plan_id"]),
                "plan_hash": str(relation["plan_hash"]),
                "relation_kind": "contests",
                "source_memory_id": memory_id,
                "source_revision": challenger_revision,
                "target_memory_id": memory_id,
                "target_revision": incumbent_revision,
                "operation_id": str(relation["operation_id"]),
            }
            if hashlib.sha256(
                canonical_json(relation_payload).encode("utf-8")
            ).hexdigest() != str(relation["relation_hash"]):
                raise MemoryCorruptionError("conflict relation hash differs")
            async with self._db.execute(
                "SELECT * FROM cognitive_conflict_resolutions WHERE group_id=?",
                (group_id,),
            ) as cursor:
                resolution = await cursor.fetchone()
            async with self._db.execute(
                "SELECT current_revision FROM cognitive_memory_heads "
                "WHERE principal_id=? AND memory_id=?",
                (principal_id, memory_id),
            ) as cursor:
                head = await cursor.fetchone()
            if head is None:
                raise MemoryCorruptionError("conflict memory head is missing")
            if resolution is None:
                if int(head["current_revision"]) != challenger_revision:
                    raise MemoryCorruptionError("active conflict head differs")
                active_group_keys.add((memory_id, challenger_revision))
                continue
            resolution_payload: dict[str, JsonValue] = {
                "group_id": group_id,
                "principal_id": principal_id,
                "memory_id": memory_id,
                "resolution_revision": int(resolution["resolution_revision"]),
                "resolution_kind": str(resolution["resolution_kind"]),
                "selected_member_ordinal": resolution["selected_member_ordinal"],
                "plan_id": str(resolution["plan_id"]),
                "plan_hash": str(resolution["plan_hash"]),
                "operation_id": str(resolution["operation_id"]),
                "created_at": float(resolution["created_at"]),
            }
            if (
                hashlib.sha256(
                    canonical_json(resolution_payload).encode("utf-8")
                ).hexdigest()
                != str(resolution["resolution_hash"])
                or int(head["current_revision"])
                < int(resolution["resolution_revision"])
            ):
                raise MemoryCorruptionError("conflict resolution differs")
            async with self._db.execute(
                "SELECT conflict_status FROM cognitive_memory_revisions "
                "WHERE memory_id=? AND revision=?",
                (memory_id, int(resolution["resolution_revision"])),
            ) as cursor:
                resolution_revision = await cursor.fetchone()
            if (
                resolution_revision is None
                or str(resolution_revision["conflict_status"]) == "contested"
            ):
                raise MemoryCorruptionError("conflict resolution state differs")
            selected = resolution["selected_member_ordinal"]
            if selected is not None:
                async with self._db.execute(
                    "SELECT r.content_hash FROM cognitive_memory_revisions r "
                    "WHERE r.memory_id=? AND r.revision=?",
                    (memory_id, int(resolution["resolution_revision"])),
                ) as cursor:
                    resolved_revision = await cursor.fetchone()
                if (
                    resolved_revision is None
                    or str(resolved_revision["content_hash"])
                    != str(members[int(selected) - 1]["content_hash"])
                ):
                    raise MemoryCorruptionError("selected conflict member differs")
        async with self._db.execute(
            "SELECT h.memory_id,h.current_revision FROM cognitive_memory_heads h "
            "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id "
            "AND r.revision=h.current_revision WHERE r.conflict_status='contested'"
        ) as cursor:
            contested_heads = {
                (str(row["memory_id"]), int(row["current_revision"]))
                for row in await cursor.fetchall()
            }
        if contested_heads != active_group_keys:
            raise MemoryCorruptionError("active conflict group set differs")

    async def _validate_short_horizon_integrity_unlocked(self) -> None:
        from simple_harness.runtime import (
            EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
            ConversationEvidenceMetadata,
            ConversationEvidenceMetadataReceipt,
            EvidenceActorRole,
            EvidenceItemAuthority,
            EvidenceProvenance,
            EvidenceSourceKind,
            InformationAttribute,
            PrivacyClass,
        )

        from simple_harness_memory.core.short_horizon import SHORT_HORIZON_RETENTION_SECONDS

        assert self._db is not None

        def canonical_object(value: object, name: str) -> dict[str, object]:
            try:
                parsed = json.loads(str(value))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise MemoryCorruptionError(f"{name} JSON is invalid") from exc
            if not isinstance(parsed, dict) or canonical_json(cast(Any, parsed)) != str(value):
                raise MemoryCorruptionError(f"{name} JSON is not canonical")
            return cast(dict[str, object], parsed)

        def canonical_array(value: object, name: str) -> list[object]:
            try:
                parsed = json.loads(str(value))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise MemoryCorruptionError(f"{name} JSON is invalid") from exc
            if not isinstance(parsed, list) or canonical_json(cast(Any, parsed)) != str(value):
                raise MemoryCorruptionError(f"{name} JSON is not canonical")
            return cast(list[object], parsed)

        async with self._db.execute(
            "SELECT * FROM conversation_evidence_registrations ORDER BY registration_id"
        ) as cursor:
            registrations = tuple(await cursor.fetchall())
        for row in registrations:
            metadata_json = canonical_object(row["metadata_json"], "conversation metadata")
            receipt_json = canonical_object(
                row["metadata_receipt_json"], "conversation metadata receipt"
            )
            registration_json = canonical_object(
                row["registration_json"], "conversation registration"
            )
            try:
                metadata = ConversationEvidenceMetadata.from_json(metadata_json)
                metadata_receipt = ConversationEvidenceMetadataReceipt.from_json(receipt_json)
            except (TypeError, ValueError) as exc:
                raise MemoryCorruptionError(
                    "conversation registration authority is invalid"
                ) from exc
            self._assert_short_horizon_registration_metadata_binding(row)
            if (
                metadata.metadata_hash != str(row["metadata_hash"])
                or metadata_receipt.receipt_hash != str(row["metadata_receipt_hash"])
                or metadata_receipt.metadata_hash != metadata.metadata_hash
                or int(row["conversation_schema_version"]) != 3
            ):
                raise MemoryCorruptionError("conversation registration metadata differs")
            expected_summary = {
                "schema_version": 3,
                "registration_id": str(row["registration_id"]),
                "evidence_id": str(row["evidence_id"]),
                "envelope_hash": str(row["envelope_hash"]),
                "admission_receipt_id": str(row["admission_receipt_id"]),
                "admission_receipt_hash": str(row["admission_receipt_hash"]),
                "metadata": metadata.to_json(),
                "metadata_receipt": metadata_receipt.to_json(),
                "recall_item_authority": None,
            }
            authority_json_value = row["evidence_item_authority_json"]
            if authority_json_value is not None:
                authority_json = canonical_object(
                    authority_json_value, "conversation item authority"
                )
                try:
                    authority = EvidenceItemAuthority(
                        schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
                        authority_id=cast(str, authority_json["authority_id"]),
                        evidence_id=cast(str, authority_json["evidence_id"]),
                        envelope_hash=cast(str, authority_json["envelope_hash"]),
                        sanitized_hash=cast(str, authority_json["sanitized_hash"]),
                        source_hash=cast(str, authority_json["source_hash"]),
                        source_kind=EvidenceSourceKind(cast(str, authority_json["source_kind"])),
                        item_ordinal=cast(int, authority_json["item_ordinal"]),
                        item_id=cast(str, authority_json["item_id"]),
                        item_json_pointer=cast(str, authority_json["item_json_pointer"]),
                        normalization_version=cast(str, authority_json["normalization_version"]),
                        actor_role=EvidenceActorRole(cast(str, authority_json["actor_role"])),
                        provenance=EvidenceProvenance(cast(str, authority_json["provenance"])),
                        required_privacy_class=PrivacyClass(
                            cast(str, authority_json["required_privacy_class"])
                        ),
                        required_information_attributes=tuple(
                            InformationAttribute(cast(str, item))
                            for item in cast(
                                list[object],
                                authority_json["required_information_attributes"],
                            )
                        ),
                        classification_authority_ref=cast(
                            str, authority_json["classification_authority_ref"]
                        ),
                        issuer_ref=cast(str, authority_json["issuer_ref"]),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise MemoryCorruptionError("conversation item authority is invalid") from exc
                if (
                    authority.authority_hash != str(row["evidence_item_authority_hash"])
                    or authority.authority_id != str(row["evidence_item_authority_id"])
                    or metadata.public_text_json_pointer != row["public_text_json_pointer"]
                    or metadata.public_text_hash != row["public_text_hash"]
                    or metadata.evidence_item_authority_hash != authority.authority_hash
                    or metadata.effective_privacy_class.value != str(row["effective_privacy_class"])
                    or [item.value for item in metadata.information_attributes or ()]
                    != canonical_array(row["information_attributes_json"], "information attributes")
                    or metadata.classification_authority_ref != row["classification_authority_ref"]
                    or hashlib.sha256(str(row["public_text"]).encode()).hexdigest()
                    != metadata.public_text_hash
                ):
                    raise MemoryCorruptionError("conversation recall authority differs")
                expected_summary["recall_item_authority"] = authority.to_json()
            elif any(
                row[name] is not None
                for name in (
                    "public_text_json_pointer",
                    "public_text",
                    "public_text_hash",
                    "effective_privacy_class",
                    "classification_authority_ref",
                )
            ):
                raise MemoryCorruptionError("conversation recall fields are partial")
            expected_registration_hash = hashlib.sha256(
                canonical_json(
                    {
                        "domain": "simple-harness/conversation-evidence-registration/v3",
                        "payload": cast(Any, expected_summary),
                    }
                ).encode()
            ).hexdigest()
            if registration_json != expected_summary or expected_registration_hash != str(
                row["registration_hash"]
            ):
                raise MemoryCorruptionError("conversation registration root differs")

        registrations_by_group: dict[tuple[str, str, str], tuple[aiosqlite.Row, ...]] = {}
        raw_groups: dict[tuple[str, str, str], list[aiosqlite.Row]] = {}
        for row in registrations:
            raw_groups.setdefault(
                (
                    str(row["subject"]),
                    str(row["primary_conversation_id"]),
                    str(row["causal_group_id"]),
                ),
                [],
            ).append(row)
        for key, raw_rows in raw_groups.items():
            group_rows = tuple(sorted(raw_rows, key=lambda item: int(item["item_ordinal"])))
            if self._short_horizon_group_is_complete(group_rows):
                registrations_by_group[key] = group_rows

        async with self._db.execute(
            "SELECT * FROM short_horizon_chunks ORDER BY chunk_id"
        ) as cursor:
            chunks = tuple(await cursor.fetchall())
        async with self._db.execute(
            "SELECT chunk_id,public_text FROM short_horizon_fts ORDER BY chunk_id,public_text"
        ) as cursor:
            fts_rows = tuple((str(row[0]), str(row[1])) for row in await cursor.fetchall())
        expected_fts_rows = tuple(
            sorted((str(chunk["chunk_id"]), str(chunk["public_text"])) for chunk in chunks)
        )
        if fts_rows != expected_fts_rows:
            raise MemoryCorruptionError("short horizon FTS mirror differs")
        privacy_rank = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
        for chunk in chunks:
            async with self._db.execute(
                "SELECT r.*,e.evidence_id AS chunk_evidence_id,"
                "e.envelope_hash AS chunk_evidence_envelope_hash,"
                "en.source_ref AS evidence_source_ref FROM short_horizon_chunk_evidence e "
                "JOIN conversation_evidence_registrations r "
                "ON r.registration_id=e.registration_id JOIN evidence_envelopes en "
                "ON en.evidence_id=e.evidence_id WHERE e.chunk_id=? "
                "ORDER BY e.item_ordinal",
                (chunk["chunk_id"],),
            ) as cursor:
                items = tuple(await cursor.fetchall())
            if not items:
                raise MemoryCorruptionError("short horizon chunk has no evidence")
            group_key = (
                str(chunk["subject"]),
                str(chunk["primary_conversation_id"]),
                str(chunk["causal_group_id"]),
            )
            expected_group = registrations_by_group.get(group_key)
            if (
                expected_group is None
                or not self._short_horizon_group_is_complete(items)
                or {str(row["registration_id"]) for row in items}
                != {str(row["registration_id"]) for row in expected_group}
            ):
                raise MemoryCorruptionError("short horizon chunk causal group differs")
            content = "\n".join(f"{row['role']}: {row['public_text']}" for row in items)
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            privacy = max(
                (str(row["effective_privacy_class"]) for row in items),
                key=privacy_rank.__getitem__,
            )
            attributes = sorted(
                {
                    str(value)
                    for row in items
                    for value in canonical_array(
                        row["information_attributes_json"], "registration attributes"
                    )
                }
            )
            classification_refs = sorted(
                {str(row["classification_authority_ref"]) for row in items}
            )
            roles = [str(row["role"]) for row in items]
            task_scope_ids = sorted(
                {str(row["task_scope_id"]) for row in items if row["task_scope_id"] is not None}
            )
            entities = sorted(
                {
                    str(value)
                    for row in items
                    for value in canonical_array(row["entities_json"], "registration entities")
                }
            )
            source_refs = [str(row["evidence_source_ref"]) for row in items]
            occurred_at = max(float(row["occurred_at"]) for row in items)
            payload = {
                "subject": str(chunk["subject"]),
                "primary_conversation_id": str(chunk["primary_conversation_id"]),
                "causal_group_id": str(chunk["causal_group_id"]),
                "registration_hashes": [str(row["registration_hash"]) for row in items],
                "content_hash": content_hash,
                "effective_privacy_class": privacy,
                "information_attributes": attributes,
                "classification_authority_refs": classification_refs,
            }
            expected_chunk_id = (
                "short:" + hashlib.sha256(canonical_json(cast(Any, payload)).encode()).hexdigest()
            )
            if (
                str(chunk["chunk_id"]) != expected_chunk_id
                or str(chunk["public_text"]) != content
                or str(chunk["content_hash"]) != content_hash
                or str(chunk["effective_privacy_class"]) != privacy
                or int(chunk["causal_group_sequence"]) != int(items[0]["causal_group_sequence"])
                or canonical_array(chunk["roles_json"], "chunk roles") != roles
                or canonical_array(chunk["task_scope_ids_json"], "chunk task scopes")
                != task_scope_ids
                or canonical_array(chunk["entities_json"], "chunk entities") != entities
                or canonical_array(chunk["source_refs_json"], "chunk source refs") != source_refs
                or canonical_array(chunk["information_attributes_json"], "chunk attributes")
                != attributes
                or canonical_array(
                    chunk["classification_authority_refs_json"],
                    "chunk classification refs",
                )
                != classification_refs
                or float(chunk["occurred_at"]) != occurred_at
                or float(chunk["expires_at"]) != occurred_at + SHORT_HORIZON_RETENTION_SECONDS
                or any(
                    str(row["chunk_evidence_id"]) != str(row["evidence_id"])
                    or str(row["chunk_evidence_envelope_hash"]) != str(row["envelope_hash"])
                    for row in items
                )
            ):
                raise MemoryCorruptionError("short horizon chunk projection differs")

        async with self._db.execute(
            "SELECT * FROM short_horizon_audit ORDER BY audit_id"
        ) as cursor:
            audits = tuple(await cursor.fetchall())
        parsed_audits: dict[str, dict[str, object]] = {}
        for row in audits:
            audit = canonical_object(row["audit_json"], "short horizon audit")
            parsed_audits[str(row["audit_id"])] = audit
            details = audit.get("details")
            if (
                hashlib.sha256(str(row["audit_json"]).encode()).hexdigest()
                != str(row["audit_hash"])
                or audit.get("audit_id") != row["audit_id"]
                or audit.get("principal_id") != row["principal_id"]
                or audit.get("event_kind") != row["event_kind"]
                or audit.get("eligible_count") != row["eligible_count"]
                or audit.get("fts_count") != row["fts_count"]
                or audit.get("entity_time_count") != row["entity_time_count"]
                or audit.get("vector_count") != row["vector_count"]
                or audit.get("disclosure_context_hash") != row["disclosure_context_hash"]
                or audit.get("query_hash") != row["query_hash"]
                or audit.get("generation_id") != row["generation_id"]
                or audit.get("generation_state") != row["generation_state"]
                or audit.get("degradation_code") != row["degradation_code"]
                or audit.get("created_at") != row["created_at"]
                or not isinstance(details, dict)
            ):
                raise MemoryCorruptionError("short horizon audit differs")
            if row["event_kind"] == "recall" and (
                not isinstance(details.get("eligible"), list)
                or len(details["eligible"]) != int(row["eligible_count"])
                or not isinstance(details.get("fts_lane"), list)
                or len(details["fts_lane"]) != int(row["fts_count"])
                or not isinstance(details.get("entity_time_lane"), list)
                or len(details["entity_time_lane"]) != int(row["entity_time_count"])
                or not isinstance(details.get("vector_lane"), list)
                or len(details["vector_lane"]) != int(row["vector_count"])
                or not isinstance(details.get("selected"), list)
            ):
                raise MemoryCorruptionError("short horizon recall audit differs")
        for row in audits:
            event_kind = str(row["event_kind"])
            if event_kind not in {"recall", "recall_terminal"}:
                continue
            details = parsed_audits[str(row["audit_id"])]["details"]
            assert isinstance(details, dict)
            attempt_audit_id = details.get("attempt_audit_id")
            attempt = (
                None
                if not isinstance(attempt_audit_id, str)
                else parsed_audits.get(attempt_audit_id)
            )
            if (
                attempt is None
                or attempt.get("event_kind") != "recall_started"
                or attempt.get("principal_id") != row["principal_id"]
                or attempt.get("query_hash") != row["query_hash"]
                or attempt.get("disclosure_context_hash") != row["disclosure_context_hash"]
            ):
                raise MemoryCorruptionError("short horizon recall audit lineage differs")
            if event_kind == "recall_terminal" and (
                details.get("gate_outcome") != "deadline_exceeded"
                or row["degradation_code"] != "DEADLINE_EXCEEDED"
            ):
                raise MemoryCorruptionError("short horizon terminal audit differs")
        await self._load_short_horizon_cache_unlocked()

    @staticmethod
    def _canonical_audit_object(value: object, name: str) -> dict[str, JsonValue]:
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MemoryCorruptionError(f"{name} JSON is invalid") from exc
        if not isinstance(parsed, dict) or canonical_json(parsed) != str(value):
            raise MemoryCorruptionError(f"{name} JSON is not canonical")
        return cast(dict[str, JsonValue], parsed)

    async def _validate_cognitive_lifecycle_target_unlocked(
        self,
        *,
        intent: Any,
        committed_revision: int,
        transition_to: str,
        memory_type: str,
        authority_id: str,
        plan_domain: str,
    ) -> None:
        """Bind one Host lifecycle intent to immutable cognitive state."""

        assert self._db is not None
        async with self._db.execute(
            "SELECT h.principal_id,h.deployment_id,h.household_id,h.scope_kind,"
            "h.scope_owner,h.memory_type,h.current_revision,r.principal_id,"
            "r.deployment_id,r.household_id,r.scope_kind,r.scope_owner,r.lifecycle_state "
            "FROM cognitive_memory_heads h JOIN cognitive_memory_revisions r "
            "ON r.memory_id=h.memory_id AND r.revision=? WHERE h.memory_id=?",
            (intent.target_revision, intent.target_memory_id),
        ) as cursor:
            target = await cursor.fetchone()
        if target is None:
            raise MemoryCorruptionError("lifecycle cognitive target is missing")
        head_identity = tuple(str(target[index]) for index in range(6))
        revision_identity = tuple(str(target[index]) for index in range(7, 12))
        if (
            head_identity[:5] != revision_identity
            or head_identity[0] != intent.subject
            or head_identity[3:5] != (intent.scope.kind.value, intent.scope.owner_id)
            or head_identity[5] != memory_type
            or str(target[12]) != intent.transition_from.value
            or int(target[6]) < committed_revision
        ):
            raise MemoryCorruptionError("lifecycle cognitive target differs")
        if committed_revision == intent.target_revision:
            if transition_to != str(target[12]):
                raise MemoryCorruptionError("lifecycle cognitive state differs")
            return
        if committed_revision != intent.target_revision + 1:
            raise MemoryCorruptionError("lifecycle committed revision differs")
        async with self._db.execute(
            "SELECT principal_id,deployment_id,household_id,scope_kind,scope_owner,"
            "lifecycle_state,plan_id,plan_hash,operation_id FROM cognitive_memory_revisions "
            "WHERE memory_id=? AND revision=?",
            (intent.target_memory_id, committed_revision),
        ) as cursor:
            committed = await cursor.fetchone()
        if committed is None or (
            tuple(str(committed[index]) for index in range(5)) != head_identity[:5]
            or str(committed[5]) != transition_to
            or str(committed[6]) != _stable_id(plan_domain, authority_id)
            or str(committed[7]) != intent.intent_hash
            or str(committed[8]) != intent.operation_id
        ):
            raise MemoryCorruptionError("lifecycle committed cognitive revision differs")

    async def _validate_lifecycle_integrity_unlocked(
        self,
        *,
        procedure_replay_identity: str | None = None,
        prospective_replay_identity: str | None = None,
    ) -> None:
        """Recompute both Host-authority audit chains on every open and close."""

        if procedure_replay_identity is not None and prospective_replay_identity is not None:
            raise MemoryCorruptionError("lifecycle replay validator is ambiguous")

        from simple_harness.runtime import (
            ProcedureObservationAuthority,
            ProcedureObservationAuthorityRef,
            ProspectiveSignalAuthority,
            ProspectiveSignalAuthorityRef,
        )

        from simple_harness_memory.core.lifecycle_results import (
            UNBOUND_PROCEDURE_APPLICABILITY,
            ProcedureObservationApplyResult,
            ProspectiveSignalApplyResult,
        )

        assert self._db is not None
        procedure_epoch_query = (
            "SELECT memory_id,revision,qualification_epoch FROM procedure_records"
        )
        procedure_epoch_params: tuple[object, ...] = ()
        if procedure_replay_identity is not None:
            procedure_epoch_query = (
                "SELECT p.memory_id,p.revision,p.qualification_epoch "
                "FROM procedure_records p JOIN "
                "procedure_observation_authority_consumptions c "
                "ON c.target_memory_id=p.memory_id AND c.target_revision=p.revision "
                "WHERE c.replay_identity=?"
            )
            procedure_epoch_params = (procedure_replay_identity,)
        if prospective_replay_identity is not None:
            procedure_epochs: dict[tuple[str, int], str] = {}
        else:
            async with self._db.execute(procedure_epoch_query, procedure_epoch_params) as cursor:
                procedure_epochs = {
                    (str(row[0]), int(row[1])): str(row[2]) for row in await cursor.fetchall()
                }

        procedure_consumptions: list[sqlite3.Row]
        if prospective_replay_identity is not None:
            procedure_consumptions = []
        else:
            procedure_query = "SELECT * FROM procedure_observation_authority_consumptions"
            procedure_params: tuple[object, ...] = ()
            if procedure_replay_identity is not None:
                procedure_query += " WHERE replay_identity=?"
                procedure_params = (procedure_replay_identity,)
            async with self._db.execute(procedure_query, procedure_params) as cursor:
                procedure_consumptions = list(await cursor.fetchall())
        procedure_ids: set[str] = set()
        procedure_authorities: dict[str, tuple[object, str, float]] = {}
        for row in procedure_consumptions:
            consumption_id = str(row["consumption_id"])
            if consumption_id in procedure_ids:
                raise MemoryCorruptionError("procedure consumption cardinality differs")
            procedure_ids.add(consumption_id)
            ref_json = self._canonical_audit_object(
                row["authority_ref_json"], "procedure authority ref"
            )
            authority_json = self._canonical_audit_object(
                row["authority_json"], "procedure authority"
            )
            try:
                reference = ProcedureObservationAuthorityRef.from_json(ref_json)
                authority = ProcedureObservationAuthority.from_json(authority_json)
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("procedure authority chain is invalid") from exc
            if ProcedureObservationAuthorityRef.from_authority(authority) != reference:
                raise MemoryCorruptionError("procedure authority ref differs")
            intent = authority.intent
            expected_columns = (
                str(row["principal_id"]),
                str(row["authority_id"]),
                str(row["authority_hash"]),
                str(row["issuer_ref"]),
                str(row["nonce"]),
                str(row["replay_identity"]),
                str(row["authority_ref_hash"]),
                str(row["intent_hash"]),
                str(row["target_memory_id"]),
                int(row["target_revision"]),
                float(row["issued_at"]),
                float(row["expires_at"]),
            )
            actual_columns = (
                intent.subject,
                authority.authority_id,
                authority.authority_hash,
                authority.issuer_ref,
                authority.nonce,
                authority.replay_identity,
                reference.ref_hash,
                intent.intent_hash,
                intent.target_memory_id,
                intent.target_revision,
                authority.issued_at,
                authority.expires_at,
            )
            if expected_columns != actual_columns:
                raise MemoryCorruptionError("procedure consumption columns differ")
            consumed_at = float(row["consumed_at"])
            if not authority.issued_at <= consumed_at < authority.expires_at:
                raise MemoryCorruptionError("procedure consumption time differs")
            consumption: dict[str, JsonValue] = {
                "schema_version": 1,
                "consumption_id": consumption_id,
                "principal_id": intent.subject,
                "authority_ref": reference.to_json(),
                "authority_ref_hash": reference.ref_hash,
                "authority": authority.to_json(),
                "authority_hash": authority.authority_hash,
                "consumed_at": consumed_at,
            }
            consumption_hash = hashlib.sha256(
                canonical_json(consumption).encode("utf-8")
            ).hexdigest()
            if str(row["consumption_hash"]) != consumption_hash:
                raise MemoryCorruptionError("procedure consumption hash differs")
            procedure_authorities[consumption_id] = (
                authority,
                consumption_hash,
                consumed_at,
            )

        procedure_chain_where = (
            "" if procedure_replay_identity is None else " WHERE consumption_id=?"
        )
        procedure_chain_params: tuple[object, ...] = (
            () if procedure_replay_identity is None else tuple(procedure_ids)
        )
        async with self._db.execute(
            "SELECT * FROM procedure_observations" + procedure_chain_where,
            procedure_chain_params,
        ) as cursor:
            observations = list(await cursor.fetchall())
        observation_by_consumption = {str(row["consumption_id"]): row for row in observations}
        async with self._db.execute(
            "SELECT * FROM procedure_observation_decisions" + procedure_chain_where,
            procedure_chain_params,
        ) as cursor:
            decisions = list(await cursor.fetchall())
        decision_by_consumption = {str(row["consumption_id"]): row for row in decisions}
        async with self._db.execute(
            "SELECT * FROM procedure_observation_results" + procedure_chain_where,
            procedure_chain_params,
        ) as cursor:
            results = list(await cursor.fetchall())
        result_by_consumption = {str(row["consumption_id"]): row for row in results}
        if not (
            set(observation_by_consumption)
            == set(decision_by_consumption)
            == set(result_by_consumption)
            == procedure_ids
        ):
            raise MemoryCorruptionError("procedure audit chain cardinality differs")
        for consumption_id in procedure_ids:
            authority, consumption_hash, consumed_at = procedure_authorities[consumption_id]
            intent = cast(Any, authority).intent
            observation = observation_by_consumption[consumption_id]
            observation_json = self._canonical_audit_object(
                observation["observation_json"], "procedure observation"
            )
            if (
                observation_json != intent.to_json()
                or str(observation["observation_hash"])
                != hashlib.sha256(canonical_json(observation_json).encode("utf-8")).hexdigest()
            ):
                raise MemoryCorruptionError("procedure observation hash differs")
            observation_columns = (
                str(observation["observation_id"]),
                str(observation["principal_id"]),
                str(observation["memory_id"]),
                int(observation["procedure_revision"]),
                str(observation["qualification_epoch"]),
                str(observation["task_scope_id"]),
                None
                if observation["terminal_receipt_id"] is None
                else str(observation["terminal_receipt_id"]),
                None
                if observation["terminal_receipt_hash"] is None
                else str(observation["terminal_receipt_hash"]),
                str(observation["applicability_fingerprint"]),
                None if observation["outcome"] is None else str(observation["outcome"]),
                bool(observation["attributable"]),
                float(observation["occurred_at"]),
                str(observation["evidence_id"]),
                str(observation["evidence_span_hash"]),
            )
            expected_observation = (
                intent.observation_id,
                intent.subject,
                intent.target_memory_id,
                intent.target_revision,
                procedure_epochs.get((intent.target_memory_id, intent.target_revision)),
                intent.task_scope_id,
                intent.terminal_receipt_id,
                intent.terminal_receipt_hash,
                intent.applicability.fingerprint,
                None if intent.outcome is None else intent.outcome.value,
                intent.attributable,
                intent.observed_at,
                intent.evidence_span.evidence_id,
                intent.evidence_span.span_hash,
            )
            if observation_columns != expected_observation:
                raise MemoryCorruptionError("procedure observation columns differ")
            if intent.observed_at > consumed_at:
                raise MemoryCorruptionError("procedure observation time differs")
            async with self._db.execute(
                "SELECT risk_level,qualification_epoch,applicability_fingerprint,"
                "bound_hazard FROM procedure_records WHERE memory_id=? AND revision=?",
                (intent.target_memory_id, intent.target_revision),
            ) as cursor:
                base_record = await cursor.fetchone()
            if base_record is None or str(base_record[0]) != intent.risk_level.value:
                raise MemoryCorruptionError("procedure authority payload differs")
            qualification_epoch = str(base_record[1])
            bound_fingerprint = str(base_record[2])
            bound_hazard = None if base_record[3] is None else str(base_record[3])
            expected_reason = "procedure_observation_recorded"
            if bound_fingerprint == UNBOUND_PROCEDURE_APPLICABILITY:
                bound_fingerprint = intent.applicability.fingerprint
                bound_hazard = intent.hazard.value
                expected_reason = "procedure_applicability_bound"
            fingerprint_matches = bound_fingerprint == intent.applicability.fingerprint
            hazard_matches = bound_hazard == intent.hazard.value
            window_start = max(0.0, consumed_at - 90.0 * 24.0 * 60.0 * 60.0)
            async with self._db.execute(
                "SELECT COUNT(*),SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END) "
                "FROM procedure_observations WHERE memory_id=? "
                "AND qualification_epoch=? AND applicability_fingerprint=? "
                "AND procedure_revision<=? AND occurred_at>=? AND occurred_at<=? AND ("
                "(outcome='success' AND attributable=1) OR outcome='failure')",
                (
                    intent.target_memory_id,
                    qualification_epoch,
                    bound_fingerprint,
                    intent.target_revision,
                    window_start,
                    consumed_at,
                ),
            ) as cursor:
                count_row = await cursor.fetchone()
            if count_row is None:
                raise MemoryCorruptionError("procedure evidence count is missing")
            expected_failures = int(count_row[1] or 0)
            expected_successes = int(count_row[0]) - expected_failures
            expected_transition = intent.transition_from.value
            if not fingerprint_matches or not hazard_matches:
                expected_transition = "inapplicable"
                expected_reason = "procedure_applicability_or_hazard_drift"
            elif intent.kind.value == "terminal_outcome":
                if intent.outcome is not None and intent.outcome.value == "failure":
                    if intent.attributable:
                        expected_transition = "revised"
                        expected_reason = "procedure_attributable_failure"
                    else:
                        expected_reason = "procedure_non_attributable_failure"
                elif intent.outcome is not None and intent.outcome.value == "success":
                    if (
                        intent.attributable
                        and intent.risk_level.value == "low"
                        and intent.hazard.value == "none"
                    ):
                        threshold = (
                            "draft"
                            if expected_successes < 2
                            else "eligible_for_activation"
                            if expected_successes < 3
                            else "active"
                        )
                        ranks = {
                            "draft": 0,
                            "eligible_for_activation": 1,
                            "active": 2,
                            "reinforced": 3,
                        }
                        if (
                            intent.transition_from.value in ranks
                            and ranks[threshold] > ranks[intent.transition_from.value]
                        ):
                            expected_transition = threshold
                        expected_reason = "procedure_low_risk_success"
                    else:
                        expected_reason = (
                            "procedure_non_attributable_success"
                            if not intent.attributable
                            else "procedure_unsafe_auto_activation_blocked"
                        )
            decision = decision_by_consumption[consumption_id]
            decision_json = self._canonical_audit_object(
                decision["decision_json"], "procedure decision"
            )
            expected_decision: dict[str, JsonValue] = {
                "schema_version": 1,
                "decision_id": str(decision["decision_id"]),
                "consumption_id": consumption_id,
                "consumption_hash": consumption_hash,
                "memory_id": str(decision["memory_id"]),
                "base_revision": int(decision["base_revision"]),
                "committed_revision": int(decision["committed_revision"]),
                "transition_from": str(decision["transition_from"]),
                "transition_to": str(decision["transition_to"]),
                "independent_successes": int(decision["independent_successes"]),
                "reason_code": str(decision["reason_code"]),
            }
            if (
                decision_json != expected_decision
                or str(decision["decision_hash"])
                != hashlib.sha256(canonical_json(expected_decision).encode("utf-8")).hexdigest()
            ):
                raise MemoryCorruptionError("procedure decision hash differs")
            if (
                str(decision["memory_id"]) != intent.target_memory_id
                or int(decision["base_revision"]) != intent.target_revision
                or int(decision["committed_revision"]) != intent.target_revision + 1
                or str(decision["transition_from"]) != intent.transition_from.value
                or str(decision["transition_to"]) != intent.transition_to.value
                or str(decision["transition_to"]) != expected_transition
                or int(decision["independent_successes"]) != expected_successes
                or str(decision["reason_code"]) != expected_reason
                or str(decision["decision_id"])
                != _stable_id(
                    "procedure-observation-decision",
                    cast(Any, authority).authority_id,
                )
            ):
                raise MemoryCorruptionError("procedure decision authority binding differs")
            await self._validate_cognitive_lifecycle_target_unlocked(
                intent=intent,
                committed_revision=int(decision["committed_revision"]),
                transition_to=str(decision["transition_to"]),
                memory_type="procedure",
                authority_id=cast(Any, authority).authority_id,
                plan_domain="procedure-observation-plan",
            )
            async with self._db.execute(
                "SELECT qualification_epoch,applicability_fingerprint,bound_hazard,"
                "success_evidence_count,failure_evidence_count FROM procedure_records "
                "WHERE memory_id=? AND revision=?",
                (intent.target_memory_id, int(decision["committed_revision"])),
            ) as cursor:
                committed_record = await cursor.fetchone()
            if committed_record is None or (
                str(committed_record[0]) != qualification_epoch
                or str(committed_record[1]) != bound_fingerprint
                or (None if committed_record[2] is None else str(committed_record[2]))
                != bound_hazard
                or int(committed_record[3]) != expected_successes
                or int(committed_record[4]) != expected_failures
            ):
                raise MemoryCorruptionError("procedure committed payload differs")
            result_row = result_by_consumption[consumption_id]
            result_json = self._canonical_audit_object(
                result_row["result_json"], "procedure result"
            )
            try:
                result = ProcedureObservationApplyResult.from_json(result_json)
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("procedure result is invalid") from exc
            if (
                canonical_json(result.to_json()) != str(result_row["result_json"])
                or result.result_hash != str(result_row["result_hash"])
                or result.result_id != str(result_row["result_id"])
                or result.result_id
                != _stable_id("procedure-observation-result", cast(Any, authority).authority_id)
                or str(result_row["replay_identity"]) != cast(Any, authority).replay_identity
                or result.observation_id != intent.observation_id
                or result.decision_id != str(decision["decision_id"])
                or result.memory_id != str(decision["memory_id"])
                or result.base_revision != int(decision["base_revision"])
                or result.committed_revision != int(decision["committed_revision"])
                or result.lifecycle_state.value != str(decision["transition_to"])
                or result.independent_successes != int(decision["independent_successes"])
                or result.reason_code != str(decision["reason_code"])
                or result.decided_at != float(result_row["decided_at"])
                or result.decided_at != float(decision["decided_at"])
            ):
                raise MemoryCorruptionError("procedure result chain differs")

        if procedure_replay_identity is not None:
            return
        await self._validate_prospective_integrity_unlocked(
            ProspectiveSignalAuthority,
            ProspectiveSignalAuthorityRef,
            ProspectiveSignalApplyResult,
            replay_identity=prospective_replay_identity,
        )

    async def _validate_prospective_integrity_unlocked(
        self,
        authority_type: Any,
        reference_type: Any,
        result_type: Any,
        *,
        replay_identity: str | None = None,
    ) -> None:
        assert self._db is not None
        consumption_query = "SELECT * FROM prospective_signal_authority_consumptions"
        consumption_params: tuple[object, ...] = ()
        if replay_identity is not None:
            consumption_query += " WHERE replay_identity=?"
            consumption_params = (replay_identity,)
        async with self._db.execute(consumption_query, consumption_params) as cursor:
            consumptions = list(await cursor.fetchall())
        ids: set[str] = set()
        authorities: dict[str, tuple[object, str]] = {}
        for row in consumptions:
            consumption_id = str(row["consumption_id"])
            ids.add(consumption_id)
            ref_json = self._canonical_audit_object(
                row["authority_ref_json"], "prospective authority ref"
            )
            authority_json = self._canonical_audit_object(
                row["authority_json"], "prospective authority"
            )
            try:
                reference = reference_type.from_json(ref_json)
                authority = authority_type.from_json(authority_json)
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("prospective authority chain is invalid") from exc
            if reference_type.from_authority(authority) != reference:
                raise MemoryCorruptionError("prospective authority ref differs")
            intent = authority.intent
            columns = (
                str(row["principal_id"]),
                str(row["authority_id"]),
                str(row["authority_hash"]),
                str(row["issuer_ref"]),
                str(row["nonce"]),
                str(row["replay_identity"]),
                str(row["authority_ref_hash"]),
                str(row["intent_hash"]),
                str(row["target_memory_id"]),
                int(row["target_revision"]),
                float(row["issued_at"]),
                float(row["expires_at"]),
            )
            expected = (
                intent.subject,
                authority.authority_id,
                authority.authority_hash,
                authority.issuer_ref,
                authority.nonce,
                authority.replay_identity,
                reference.ref_hash,
                intent.intent_hash,
                intent.target_memory_id,
                intent.target_revision,
                authority.issued_at,
                authority.expires_at,
            )
            if columns != expected:
                raise MemoryCorruptionError("prospective consumption columns differ")
            consumed_at = float(row["consumed_at"])
            if not authority.issued_at <= consumed_at < authority.expires_at:
                raise MemoryCorruptionError("prospective consumption time differs")
            consumption: dict[str, JsonValue] = {
                "schema_version": 1,
                "consumption_id": consumption_id,
                "principal_id": intent.subject,
                "authority_ref": reference.to_json(),
                "authority_ref_hash": reference.ref_hash,
                "authority": authority.to_json(),
                "authority_hash": authority.authority_hash,
                "consumed_at": consumed_at,
            }
            consumption_hash = hashlib.sha256(
                canonical_json(consumption).encode("utf-8")
            ).hexdigest()
            if str(row["consumption_hash"]) != consumption_hash:
                raise MemoryCorruptionError("prospective consumption hash differs")
            authorities[consumption_id] = (authority, consumption_hash)

        chain_where = "" if replay_identity is None else " WHERE consumption_id=?"
        chain_params: tuple[object, ...] = () if replay_identity is None else tuple(ids)
        async with self._db.execute(
            "SELECT * FROM prospective_signal_decisions" + chain_where,
            chain_params,
        ) as cursor:
            decision_rows = list(await cursor.fetchall())
        decisions = {str(row["consumption_id"]): row for row in decision_rows}
        async with self._db.execute(
            "SELECT * FROM prospective_signal_results" + chain_where,
            chain_params,
        ) as cursor:
            result_rows = list(await cursor.fetchall())
        results = {str(row["consumption_id"]): row for row in result_rows}
        if set(decisions) != ids or set(results) != ids:
            raise MemoryCorruptionError("prospective audit chain cardinality differs")
        async with self._db.execute(
            "SELECT * FROM prospective_scheduler_registrations" + chain_where,
            chain_params,
        ) as cursor:
            registration_rows = list(await cursor.fetchall())
        registrations = {str(row["consumption_id"]): row for row in registration_rows}
        async with self._db.execute(
            "SELECT * FROM prospective_trigger_events" + chain_where,
            chain_params,
        ) as cursor:
            trigger_rows = list(await cursor.fetchall())
        triggers = {str(row["consumption_id"]): row for row in trigger_rows}
        for consumption_id in ids:
            authority, consumption_hash = authorities[consumption_id]
            intent = cast(Any, authority).intent
            decision = decisions[consumption_id]
            decision_json = self._canonical_audit_object(
                decision["decision_json"], "prospective decision"
            )
            expected_decision: dict[str, JsonValue] = {
                "schema_version": 1,
                "decision_id": str(decision["decision_id"]),
                "consumption_id": consumption_id,
                "consumption_hash": consumption_hash,
                "memory_id": str(decision["memory_id"]),
                "base_revision": int(decision["base_revision"]),
                "committed_revision": int(decision["committed_revision"]),
                "transition_from": str(decision["transition_from"]),
                "transition_to": str(decision["transition_to"]),
                "outcome": str(decision["outcome"]),
                "reason_code": str(decision["reason_code"]),
            }
            if (
                decision_json != expected_decision
                or str(decision["decision_hash"])
                != hashlib.sha256(canonical_json(expected_decision).encode("utf-8")).hexdigest()
            ):
                raise MemoryCorruptionError("prospective decision hash differs")
            decision_outcome = str(decision["outcome"])
            if (
                str(decision["decision_id"])
                != _stable_id("prospective-signal-decision", cast(Any, authority).authority_id)
                or str(decision["memory_id"]) != intent.target_memory_id
                or int(decision["base_revision"]) != intent.target_revision
                or str(decision["transition_from"]) != intent.transition_from.value
                or (
                    decision_outcome == "applied"
                    and (
                        int(decision["committed_revision"]) != intent.target_revision + 1
                        or str(decision["transition_to"]) != intent.transition_to.value
                    )
                )
                or (
                    decision_outcome == "acknowledged"
                    and (
                        int(decision["committed_revision"]) != intent.target_revision
                        or str(decision["transition_to"]) != intent.transition_to.value
                    )
                )
                or (
                    decision_outcome == "ignored"
                    and int(decision["committed_revision"]) != intent.target_revision
                )
            ):
                raise MemoryCorruptionError("prospective decision authority binding differs")
            await self._validate_cognitive_lifecycle_target_unlocked(
                intent=intent,
                committed_revision=int(decision["committed_revision"]),
                transition_to=str(decision["transition_to"]),
                memory_type="prospective",
                authority_id=cast(Any, authority).authority_id,
                plan_domain="prospective-signal-plan",
            )
            result_row = results[consumption_id]
            result_json = self._canonical_audit_object(
                result_row["result_json"], "prospective result"
            )
            try:
                result = result_type.from_json(result_json)
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryCorruptionError("prospective result is invalid") from exc
            if (
                canonical_json(result.to_json()) != str(result_row["result_json"])
                or result.result_hash != str(result_row["result_hash"])
                or result.result_id != str(result_row["result_id"])
                or result.result_id
                != _stable_id("prospective-signal-result", cast(Any, authority).authority_id)
                or str(result_row["replay_identity"]) != cast(Any, authority).replay_identity
                or result.signal_id != intent.signal_id
                or result.decision_id != str(decision["decision_id"])
                or result.memory_id != str(decision["memory_id"])
                or result.base_revision != int(decision["base_revision"])
                or result.committed_revision != int(decision["committed_revision"])
                or result.lifecycle_state.value != str(decision["transition_to"])
                or result.outcome.value != decision_outcome
                or result.reason_code != str(decision["reason_code"])
                or result.decided_at != float(result_row["decided_at"])
                or result.decided_at != float(decision["decided_at"])
            ):
                raise MemoryCorruptionError("prospective result chain differs")
            registration = registrations.get(consumption_id)
            trigger = triggers.get(consumption_id)
            if str(decision["outcome"]) == "acknowledged":
                if (
                    intent.signal_kind.value
                    not in {"registration_accepted", "registration_invalidated"}
                    or registration is None
                    or trigger is not None
                ):
                    raise MemoryCorruptionError("prospective registration cardinality differs")
                event_json = self._canonical_audit_object(
                    registration["event_json"], "prospective registration event"
                )
                if (
                    str(registration["event_hash"])
                    != hashlib.sha256(canonical_json(event_json).encode("utf-8")).hexdigest()
                ):
                    raise MemoryCorruptionError("prospective registration hash differs")
                registration_event_columns = (
                    event_json.get("registration_event_id"),
                    event_json.get("memory_id"),
                    event_json.get("prospective_revision"),
                    event_json.get("scheduler_registration_ref"),
                    event_json.get("registration_revision"),
                    event_json.get("state"),
                    event_json.get("trigger_hash"),
                    event_json.get("outbox_id"),
                    event_json.get("outbox_payload_hash"),
                )
                stored_registration_columns = (
                    str(registration["registration_event_id"]),
                    str(registration["memory_id"]),
                    int(registration["prospective_revision"]),
                    str(registration["scheduler_registration_ref"]),
                    int(registration["registration_revision"]),
                    str(registration["state"]),
                    str(registration["trigger_hash"]),
                    str(registration["outbox_id"]),
                    str(registration["outbox_payload_hash"]),
                )
                expected_registration_state = (
                    "accepted"
                    if intent.signal_kind.value == "registration_accepted"
                    else "invalidated"
                )
                expected_registration_columns = (
                    _stable_id("prospective-registration-event", consumption_id),
                    intent.target_memory_id,
                    intent.target_revision,
                    intent.scheduler_registration_ref,
                    intent.registration_revision,
                    expected_registration_state,
                    intent.trigger_hash,
                    intent.outbox_id,
                    intent.outbox_payload_hash,
                )
                if (
                    registration_event_columns != stored_registration_columns
                    or stored_registration_columns != expected_registration_columns
                    or str(registration["consumption_id"]) != consumption_id
                    or str(registration["principal_id"]) != intent.subject
                    or float(registration["occurred_at"]) != float(decision["decided_at"])
                    or decision_outcome != "acknowledged"
                    or str(decision["reason_code"]) != "prospective_registration_acknowledged"
                ):
                    raise MemoryCorruptionError("prospective registration columns differ")
                async with self._db.execute(
                    "SELECT principal_id,topic,idempotency_key,payload,payload_hash "
                    "FROM outbox WHERE outbox_id=?",
                    (intent.outbox_id,),
                ) as cursor:
                    outbox = await cursor.fetchone()
                command = (
                    "registration" if expected_registration_state == "accepted" else "invalidation"
                )
                expected_outbox_payload: dict[str, JsonValue] = {
                    "schema_version": 1,
                    "command": command,
                    "memory_id": intent.target_memory_id,
                    "prospective_revision": intent.target_revision,
                    "registration_revision": intent.registration_revision,
                    "trigger": intent.trigger.to_json(),
                    "trigger_hash": intent.trigger_hash,
                }
                if outbox is None or (
                    str(outbox[0]) != intent.subject
                    or str(outbox[1]) != f"memory.prospective.{command}.requested"
                    or str(outbox[2]) != intent.outbox_id
                    or str(outbox[3]) != canonical_json(expected_outbox_payload)
                    or str(outbox[4]) != intent.outbox_payload_hash
                    or str(outbox[4]) != hashlib.sha256(str(outbox[3]).encode("utf-8")).hexdigest()
                ):
                    raise MemoryCorruptionError("prospective registration outbox differs")
                if expected_registration_state == "invalidated":
                    async with self._db.execute(
                        "SELECT 1 FROM prospective_scheduler_registrations "
                        "WHERE memory_id=? AND prospective_revision=? "
                        "AND registration_revision=? AND scheduler_registration_ref=? "
                        "AND trigger_hash=? AND state='accepted'",
                        (
                            intent.target_memory_id,
                            intent.target_revision,
                            intent.registration_revision,
                            intent.scheduler_registration_ref,
                            intent.trigger_hash,
                        ),
                    ) as cursor:
                        accepted = await cursor.fetchone()
                    if accepted is None:
                        raise MemoryCorruptionError(
                            "prospective invalidation registration is not live"
                        )
            elif str(decision["reason_code"]) == "prospective_occurrence_already_applied":
                if decision_outcome != "ignored" or registration is not None or trigger is not None:
                    raise MemoryCorruptionError("prospective duplicate cardinality differs")
            else:
                if registration is not None or trigger is None:
                    raise MemoryCorruptionError("prospective trigger cardinality differs")
                event_json = self._canonical_audit_object(
                    trigger["event_json"], "prospective trigger event"
                )
                if (
                    str(trigger["event_hash"])
                    != hashlib.sha256(canonical_json(event_json).encode("utf-8")).hexdigest()
                ):
                    raise MemoryCorruptionError("prospective trigger hash differs")
                trigger_event_columns = (
                    event_json.get("event_id"),
                    event_json.get("memory_id"),
                    event_json.get("prospective_revision"),
                    event_json.get("trigger_hash"),
                    event_json.get("event_ref"),
                    event_json.get("occurrence_key"),
                    event_json.get("signal_kind"),
                    event_json.get("outcome"),
                    event_json.get("reason_code"),
                    event_json.get("occurred_at"),
                )
                stored_trigger_columns = (
                    str(trigger["event_id"]),
                    str(trigger["memory_id"]),
                    int(trigger["prospective_revision"]),
                    str(trigger["trigger_fingerprint"]),
                    str(trigger["event_ref"]),
                    str(trigger["occurrence_key"]),
                    str(trigger["signal_kind"]),
                    str(trigger["outcome"]),
                    str(trigger["reason_code"]),
                    float(trigger["occurred_at"]),
                )
                expected_trigger_columns = (
                    _stable_id("prospective-trigger-event", consumption_id),
                    intent.target_memory_id,
                    intent.target_revision,
                    intent.trigger_hash,
                    intent.signal_receipt_id,
                    intent.occurrence_key,
                    intent.signal_kind.value,
                    str(trigger["outcome"]),
                    str(trigger["reason_code"]),
                    intent.observed_at,
                )
                if (
                    trigger_event_columns != stored_trigger_columns
                    or stored_trigger_columns != expected_trigger_columns
                    or str(trigger["consumption_id"]) != consumption_id
                    or str(trigger["principal_id"]) != intent.subject
                    or str(trigger["reason_code"]) != str(decision["reason_code"])
                    or (str(trigger["outcome"]) == "ignored" and decision_outcome != "ignored")
                    or (
                        str(trigger["outcome"]) in {"matched", "expired"}
                        and decision_outcome != "applied"
                    )
                    or (
                        str(trigger["outcome"]) == "ignored"
                        and str(trigger["reason_code"]) != "prospective_signal_stale"
                    )
                    or (
                        str(trigger["outcome"]) == "matched"
                        and (
                            intent.signal_kind.value not in {"time_due", "event_occurred"}
                            or str(trigger["reason_code"]) != "prospective_trigger_matched"
                        )
                    )
                    or (
                        str(trigger["outcome"]) == "expired"
                        and (
                            intent.signal_kind.value != "expired"
                            or str(trigger["reason_code"]) != "prospective_expired"
                        )
                    )
                ):
                    raise MemoryCorruptionError("prospective trigger columns differ")

        if replay_identity is None:
            async with self._db.execute(
                "SELECT payload,payload_hash FROM outbox WHERE topic LIKE 'memory.prospective.%'"
            ) as cursor:
                outbox_rows = list(await cursor.fetchall())
            for row in outbox_rows:
                payload = self._canonical_audit_object(row["payload"], "prospective outbox")
                if (
                    str(row["payload_hash"])
                    != hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
                ):
                    raise MemoryCorruptionError("prospective outbox hash differs")

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
    if query.selector is AuditTraceSelector.MEMORY:
        return (
            "(EXISTS(SELECT 1 FROM decision_records d WHERE "
            "d.invocation_id=i.invocation_id AND d.principal_id=i.principal_id "
            "AND d.target_kind='memory' AND d.target_ref=?) OR "
            "EXISTS(SELECT 1 FROM cognitive_memory_revisions cr "
            "JOIN accepted_analysis_plans ap ON ap.principal_id=cr.principal_id "
            "AND ap.plan_hash=cr.plan_hash "
            "JOIN analysis_batches b ON b.batch_id=ap.batch_id "
            "WHERE cr.principal_id=i.principal_id AND cr.memory_id=? "
            "AND b.request_hash=i.request_hash))",
            (query.selector_ref, query.selector_ref),
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


def _principal_ref_hash(principal: MemoryPrincipal) -> str:
    return _principal_ref_hash_values(
        principal.deployment_id,
        principal.household_id,
        principal.actor_id,
        principal.session_id,
    )


def _principal_ref_hash_values(
    deployment_id: str, household_id: str, actor_id: str, session_id: str
) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "schema_version": 1,
                "deployment_id": deployment_id,
                "household_id": household_id,
                "actor_id": actor_id,
                "session_id": session_id,
            }
        ).encode()
    ).hexdigest()


def _canonical_manifest_row(row: sqlite3.Row | aiosqlite.Row) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key in row.keys():
        value = row[key]
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                value = hashlib.sha256(value).hexdigest()
        if value is None or isinstance(value, (str, int, float)):
            normalized: JsonValue = value
        else:
            raise MemoryCorruptionError("canonical manifest row type unsupported")
        if isinstance(normalized, str) and (
            key.endswith("_json") or key in {"canonical_payload", "payload"}
        ):
            try:
                parsed = json.loads(normalized)
            except (TypeError, ValueError) as exc:
                raise MemoryCorruptionError(
                    "canonical manifest stored json malformed"
                ) from exc
            if canonical_json(parsed) != normalized:
                raise MemoryCorruptionError("canonical manifest stored json differs")
        result[str(key)] = normalized
    return result


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
    "COGNITIVE_CONFLICT_FAULT_POINTS",
    "COGNITIVE_MUTATION_FAULT_POINTS",
    "INGESTION_FAULT_POINTS",
    "INITIALIZATION_FAULT_POINTS",
    "SUPPRESSION_FAULT_POINTS",
    "SQLiteHumanMemoryBackend",
)
