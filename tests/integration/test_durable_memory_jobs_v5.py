from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
import structlog
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    AnalysisBudget,
    AnalysisValidationStatus,
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
    LongTermMemoryType,
    MemoryAnalysisDeliveryAuthorityPort,
    MemoryAnalysisDeliveryReceipt,
    MemoryAnalysisReceipt,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
    MemoryAnalysisResultEnvelope,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.audit import AuditTraceQuery, AuditTraceSelector
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryValidationError,
    MemoryWriterConflict,
)
from simple_harness_memory.core.jobs import (
    AnalysisBatchClaim,
    AnalysisDeliveryAuthorityTransientError,
    AnalysisResultCommitOutcome,
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    RejectedAnalysisAudit,
    WorkerRunOutcome,
)

# Test-only fixture policy. These values are intentionally not production defaults.
TEST_WORKER_CONFIG = MemoryJobWorkerConfig(
    batch_size=2,
    idle_wait_seconds=0.01,
    max_batch_wait_seconds=5.0,
    lease_seconds=10.0,
    max_attempts=2,
    retry_delays_seconds=(3.0,),
    max_result_bytes=64 * 1024,
    analysis_budget=AnalysisBudget(4096, 1024, 30_000, 1_000_000),
    prompt_version="test-prompt-v1",
    result_schema_version="test-result-v1",
    policy_version="test-policy-v1",
    validator_version="test-validator-v1",
    provider_id="test-provider",
    model_id="test-model",
    model_config_hash="a" * 64,
)
PRIVATE_REASONING_CANARY = "hidden-chain-of-thought-canary"
PRIVATE_CREDENTIAL_CANARY = "ghp_012345678901234567890123456789"
OVERSIZE_BODY_CANARY = "oversize-provider-body-canary"


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
        "host-authority",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _authority(index: int) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {"public_text": f"preference-{index}"}
    envelope = SanitizedEvidenceEnvelope(
        f"evidence-{index}",
        "run-1",
        "actor-1",
        EvidenceSourceKind.USER_MESSAGE,
        f"turn-{index}/user",
        f"{index}" * 64,
        payload,
        _hash(payload),
        "credential-filter/v1",
        (),
        _disclosure(),
        (EvidenceRef(f"source-event-{index}", f"{index + 2}" * 64, 1),),
    )
    receipt = SanitizedEvidenceReceipt(
        f"admission-{index}",
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


class _Executor:
    issuer_id = "test-host-analysis-authority"

    def __init__(
        self,
        backend: SQLiteHumanMemoryBackend | None,
        *,
        no_mutation: bool = False,
        error: Exception | None = None,
        private: bool = False,
        base_revision: int = 1,
        structured_override: dict[str, JsonValue] | None = None,
        provider_response_id: str | None = "provider-response-default",
        delivery_mutation: str | None = None,
        deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] | None = None,
        issuer_id: str | None = None,
        authority_error: Exception | None = None,
    ) -> None:
        self.backend = backend
        self.no_mutation = no_mutation
        self.error = error
        self.private = private
        self.base_revision = base_revision
        self.structured_override = structured_override
        self.provider_response_id = provider_response_id
        self.delivery_mutation = delivery_mutation
        if issuer_id is not None:
            self.issuer_id = issuer_id
        self.authority_error = authority_error
        self.calls = 0
        self.provider_calls = 0
        self.verification_calls = 0
        self.deliveries = deliveries if deliveries is not None else {}

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        self.calls += 1
        assert self.backend is not None
        assert not self.backend.connection.in_transaction
        durable = self.deliveries.get((request.request_hash, request.attempt))
        if durable is not None:
            return durable
        self.provider_calls += 1
        if self.error is not None:
            raise self.error
        structured: dict[str, JsonValue]
        if self.structured_override is not None:
            structured = self.structured_override
        elif self.private:
            structured = {
                "reasoning": PRIVATE_REASONING_CANARY
            }
        elif self.no_mutation:
            structured = {"outcome": "no_mutation", "operations": []}
        else:
            operation = MemoryMutationOperation(
                "operation-1",
                MemoryMutationKind.CREATE,
                LongTermMemoryType.SEMANTIC,
                None,
                "User prefers concise answers.",
                request.ordered_evidence_refs,
                "explicit_user_preference",
            )
            structured = MemoryMutationPlan(
                "plan-1",
                request.run_id,
                request.subject,
                self.base_revision,
                (operation,),
                request.disclosure_context,
                request.ordered_evidence_refs,
                request.idempotency_key,
            ).to_json()
        result = MemoryAnalysisResult(
            request.job_id,
            request.run_id,
            request.request_hash,
            self.provider_response_id,
            structured,
            100,
            50,
            7,
            25,
        )
        envelope = _result_envelope(request, result, self.issuer_id)
        self.deliveries[(request.request_hash, request.attempt)] = envelope
        if self.delivery_mutation == "issuer":
            return MemoryAnalysisResultEnvelope(
                result,
                replace(envelope.delivery_receipt, issuer_id="forged-host-issuer"),
            )
        if self.delivery_mutation == "host_hash":
            return MemoryAnalysisResultEnvelope(
                result,
                replace(envelope.delivery_receipt, host_receipt_hash="f" * 64),
            )
        if self.delivery_mutation == "attempt":
            return MemoryAnalysisResultEnvelope(
                result,
                replace(envelope.delivery_receipt, attempt=request.attempt + 1),
            )
        return envelope

    async def verify_analysis_delivery(
        self, request: MemoryAnalysisRequest, envelope: MemoryAnalysisResultEnvelope
    ) -> None:
        self.verification_calls += 1
        assert self.backend is not None
        assert not self.backend.connection.in_transaction
        if self.authority_error is not None:
            raise self.authority_error
        envelope.verify_request(request)
        if envelope.delivery_receipt.issuer_id != self.issuer_id:
            raise ValueError("analysis delivery issuer differs")
        if self.deliveries.get((request.request_hash, request.attempt)) != envelope:
            raise ValueError("durable Host analysis delivery differs")


class _RejectedResultExecutor:
    issuer_id = "test-host-analysis-authority"

    def __init__(self, backend: SQLiteHumanMemoryBackend | None, mode: str) -> None:
        self.backend = backend
        self.mode = mode
        self.deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}
        self.verification_calls = 0

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        assert self.backend is not None
        assert not self.backend.connection.in_transaction
        if self.mode == "type":
            return cast(MemoryAnalysisResultEnvelope, object())
        if self.mode == "private":
            structured: dict[str, JsonValue] = {
                "safe": PRIVATE_CREDENTIAL_CANARY
            }
        elif self.mode == "oversize":
            structured = {"safe": OVERSIZE_BODY_CANARY + ("x" * 4096)}
        else:
            structured = {"outcome": "no_mutation", "operations": []}
        result = MemoryAnalysisResult(
            "wrong-job" if self.mode == "lineage" else request.job_id,
            request.run_id,
            request.request_hash,
            f"provider-rejected-{self.mode}",
            structured,
            10,
            5,
            3,
            7,
        )
        if self.mode == "hash":
            object.__setattr__(result, "result_hash", "f" * 64)
        envelope = _result_envelope(request, result, self.issuer_id)
        self.deliveries[(request.request_hash, request.attempt)] = envelope
        return envelope

    async def verify_analysis_delivery(
        self, request: MemoryAnalysisRequest, envelope: MemoryAnalysisResultEnvelope
    ) -> None:
        self.verification_calls += 1
        assert self.backend is not None
        assert not self.backend.connection.in_transaction
        envelope.verify_request(request)
        if envelope.delivery_receipt.issuer_id != self.issuer_id:
            raise ValueError("analysis delivery issuer differs")
        if self.deliveries.get((request.request_hash, request.attempt)) != envelope:
            raise ValueError("durable Host analysis delivery differs")


class _AlwaysAcceptAuthority:
    def __init__(self) -> None:
        self.calls = 0

    async def verify_analysis_delivery(
        self,
        request: MemoryAnalysisRequest,
        envelope: MemoryAnalysisResultEnvelope,
    ) -> None:
        self.calls += 1
        envelope.verify_request(request)


def _authority_backend(
    db_path: Path,
    authority: _Executor | _RejectedResultExecutor,
    **kwargs: Any,
) -> SQLiteHumanMemoryBackend:
    backend = SQLiteHumanMemoryBackend(
        db_path, analysis_delivery_authority=authority, **kwargs
    )
    authority.backend = backend
    return backend


def _result_envelope(
    request: MemoryAnalysisRequest,
    result: MemoryAnalysisResult,
    issuer_id: str,
) -> MemoryAnalysisResultEnvelope:
    provider_hash = hashlib.sha256(
        (result.provider_response_id or "provider-response-id-null").encode()
    ).hexdigest()
    delivery = MemoryAnalysisDeliveryReceipt(
        f"delivery-{request.job_id}-{request.attempt}",
        issuer_id,
        result.run_id,
        result.job_id,
        result.request_hash,
        result.result_hash,
        request.attempt,
        result.provider_response_id,
        provider_hash,
        19.0,
        f"host-record-{request.job_id}-{request.attempt}",
        hashlib.sha256(
            f"{request.request_hash}:{result.result_hash}:{request.attempt}".encode()
        ).hexdigest(),
    )
    return MemoryAnalysisResultEnvelope(result, delivery)


async def _admit(
    backend: SQLiteHumanMemoryBackend,
    claim: AnalysisBatchClaim,
    envelope: MemoryAnalysisResultEnvelope,
    authority: MemoryAnalysisDeliveryAuthorityPort,
) -> Any:
    registration = backend.register_analysis_delivery_authority(authority)
    return await backend.admit_analysis_delivery(claim, envelope, registration)


async def _ingest(backend: SQLiteHumanMemoryBackend, count: int = 2) -> None:
    for index in range(1, count + 1):
        await backend.ingest_committed_evidence(*_authority(index))


async def _ingest_indexes(
    backend: SQLiteHumanMemoryBackend, indexes: tuple[int, ...]
) -> None:
    for index in indexes:
        await backend.ingest_committed_evidence(*_authority(index))


@pytest.mark.asyncio
async def test_batch_analysis_runs_outside_transaction_and_cas_applies_once(
    tmp_path: Path,
) -> None:
    executor = _Executor(None)
    backend = _authority_backend(tmp_path / "jobs.db", executor, now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    before = await backend.export_ingested_evidence("evidence-1")
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )

    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    assert executor.calls == 1
    assert executor.verification_calls == 1
    assert await backend.export_ingested_evidence("evidence-1") == before
    for table, expected in (
        ("analysis_batches", 1),
        ("analysis_batch_members", 2),
        ("accepted_analysis_plans", 1),
        ("llm_invocations", 1),
    ):
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        assert row is not None and int(row[0]) == expected
    async with backend.connection.execute(
        "SELECT state FROM jobs ORDER BY job_id"
    ) as cursor:
        assert [str(row[0]) for row in await cursor.fetchall()] == ["applied", "applied"]
    async with backend.connection.execute("SELECT revision FROM analysis_apply_heads") as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 2
    async with backend.connection.execute(
        "SELECT delivery_receipt_json,validation_receipt_json FROM llm_invocations"
    ) as cursor:
        receipts = await cursor.fetchone()
    assert receipts is not None
    assert json.loads(str(receipts[0]))["issuer_id"] == executor.issuer_id
    assert json.loads(str(receipts[1]))["validator_version"] == (
        TEST_WORKER_CONFIG.validator_version
    )
    await backend.close()


@pytest.mark.asyncio
async def test_nullable_provider_response_id_keeps_verified_delivery_authority(
    tmp_path: Path,
) -> None:
    executor = _Executor(None, no_mutation=True, provider_response_id=None)
    backend = _authority_backend(
        tmp_path / "nullable-provider.db", executor, now=lambda: 20.0
    )
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )

    assert await runner.run_once() is WorkerRunOutcome.APPLIED

    async with backend.connection.execute(
        "SELECT provider_request_id,delivery_receipt_json FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] is None
    assert json.loads(str(row[1]))["provider_response_id"] is None
    assert executor.verification_calls == 1
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery_mutation", ("issuer", "host_hash", "attempt"))
async def test_forged_or_wrong_delivery_is_contract_attempt_without_delivery_receipt(
    tmp_path: Path, delivery_mutation: str
) -> None:
    executor = _Executor(
        None, no_mutation=True, delivery_mutation=delivery_mutation
    )
    backend = _authority_backend(
        tmp_path / f"delivery-{delivery_mutation}.db",
        executor,
        now=lambda: 20.0,
    )
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )

    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER

    async with backend.connection.execute(
        "SELECT delivery_receipt_id,delivery_receipt_json,delivery_receipt_hash,"
        "validation_receipt_json,output_reason_code FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None and row[1] is None and row[2] is None
    assert json.loads(str(row[3]))["validation_status"] == "rejected"
    assert str(row[4]) in {
        "analysis_envelope_lineage_invalid",
        "analysis_delivery_authority_rejected",
    }
    async with backend.connection.execute(
        "SELECT delivery_receipt_json,result_json FROM analysis_batches"
    ) as cursor:
        batch = await cursor.fetchone()
    assert batch is not None and batch[0] is None and batch[1] is None
    await backend.close()


@pytest.mark.asyncio
async def test_direct_forged_commit_and_fake_authority_admission_fail_closed(
    tmp_path: Path,
) -> None:
    fake_authority = _AlwaysAcceptAuthority()
    unbound = SQLiteHumanMemoryBackend(
        tmp_path / "unbound-direct-forged.db", now=lambda: 20.0
    )
    try:
        with pytest.raises(MemoryValidationError, match="authority_not_bound"):
            unbound.register_analysis_delivery_authority(fake_authority)
    finally:
        await unbound.close()

    trusted = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "direct-forged.db", trusted, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await trusted.analyze_memory(claim.request)
        backend.register_analysis_delivery_authority(trusted)
        with pytest.raises(MemoryValidationError, match="identity_differs"):
            backend.register_analysis_delivery_authority(fake_authority)
        with pytest.raises(MemoryValidationError, match="registration_invalid"):
            await backend.admit_analysis_delivery(
                claim, envelope, cast(Any, object())
            )
        assert fake_authority.calls == 0
        with pytest.raises(MemoryValidationError, match="admission_invalid"):
            await backend.commit_analysis_result(
                claim, envelope, cast(Any, object())
            )
        async with backend.connection.execute(
            "SELECT result_json,delivery_receipt_json FROM analysis_batches"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] is None and row[1] is None
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_admission_is_bound_to_claim_envelope_and_each_purpose_once(
    tmp_path: Path,
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "admission-binding.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        registration = backend.register_analysis_delivery_authority(authority)
        admission = await backend.admit_analysis_delivery(
            claim, envelope, registration
        )
        wrong_claim = replace(claim, lease_token="wrong-lease-token")
        with pytest.raises(MemoryValidationError, match="admission_invalid"):
            await backend.commit_analysis_result(wrong_claim, envelope, admission)

        wrong_result = MemoryAnalysisResult(
            claim.request.job_id,
            claim.request.run_id,
            claim.request.request_hash,
            "provider-response-wrong-envelope",
            {"outcome": "no_mutation", "operations": []},
            1,
            1,
            1,
            1,
        )
        wrong_envelope = _result_envelope(
            claim.request, wrong_result, authority.issuer_id
        )
        with pytest.raises(MemoryValidationError, match="admission_invalid"):
            await backend.commit_analysis_result(claim, wrong_envelope, admission)

        committed = await backend.commit_analysis_result(claim, envelope, admission)
        assert committed.outcome is AnalysisResultCommitOutcome.COMMITTED
        with pytest.raises(MemoryValidationError, match="admission_replayed"):
            await backend.commit_analysis_result(claim, envelope, admission)

        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None
        audit_admission = await backend.admit_analysis_application(
            claim, envelope, application
        )
        with pytest.raises(MemoryValidationError, match="admission_invalid"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                cast(Any, object()),
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                application.decisions,
            )
        await backend.record_memory_analysis(
            claim,
            envelope,
            audit_admission,
            application.invocation_id,
            application.turn_id,
            claim.request,
            envelope.result,
            envelope.delivery_receipt,
            application.receipt,
            application.decisions,
        )
        with pytest.raises(MemoryValidationError, match="admission_replayed"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                application.decisions,
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_mutation_audit_rejects_handed_off_and_result_committed_phases(
    tmp_path: Path,
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "audit-phase-order.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        receipt = MemoryAnalysisReceipt(
            "caller-created-receipt",
            claim.request.job_id,
            claim.request.run_id,
            claim.request.request_hash,
            envelope.result.result_hash,
            TEST_WORKER_CONFIG.validator_version,
            AnalysisValidationStatus.ACCEPTED,
            (EvidenceReasonCode.VALIDATOR_ACCEPTED,),
            1,
            20.0,
        )
        commit_admission = await _admit(backend, claim, envelope, authority)
        with pytest.raises(MemoryWriterConflict, match="audit_phase_invalid"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                commit_admission,
                "caller-invocation",
                "caller-turn",
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                receipt,
                (),
            )
        assert (
            await backend.commit_analysis_result(claim, envelope, commit_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED

        replay_admission = await _admit(backend, claim, envelope, authority)
        with pytest.raises(MemoryWriterConflict, match="audit_phase_invalid"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                replay_admission,
                "caller-invocation",
                "caller-turn",
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                receipt,
                (),
            )
        async with backend.connection.execute(
            "SELECT state,application_receipt_hash FROM analysis_batches"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and tuple(row) == ("result_committed", None)
        async with backend.connection.execute("SELECT COUNT(*) FROM llm_invocations") as cursor:
            count = await cursor.fetchone()
        assert count is not None and int(count[0]) == 0
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_mutation_audit_rejects_caller_receipt_and_changed_decisions(
    tmp_path: Path,
) -> None:
    authority = _Executor(None)
    backend = _authority_backend(
        tmp_path / "audit-application-authority.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None and application.decisions
        with pytest.raises(MemoryValidationError, match="application_differs"):
            await backend.admit_analysis_application(
                claim,
                envelope,
                replace(application, invocation_id="cross-application-replay"),
            )
        audit_admission = await backend.admit_analysis_application(
            claim, envelope, application
        )

        forged_receipt = replace(
            application.receipt, validator_version="caller-validator/v1"
        )
        with pytest.raises(MemoryValidationError, match="application_differs"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                forged_receipt,
                application.decisions,
            )
        changed_decisions = (
            replace(application.decisions[0], reason_code="caller_changed_decision"),
        )
        with pytest.raises(MemoryValidationError, match="application_differs"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                changed_decisions,
            )
        await backend.record_memory_analysis(
            claim,
            envelope,
            audit_admission,
            application.invocation_id,
            application.turn_id,
            claim.request,
            envelope.result,
            envelope.delivery_receipt,
            application.receipt,
            application.decisions,
        )
        assert await backend.finalize_analysis_application(claim, application)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_generic_shadow_capability_cannot_authorize_mutation_finalize(
    tmp_path: Path,
) -> None:
    authority = _Executor(None)
    backend = _authority_backend(
        tmp_path / "generic-shadow.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        commit_admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, commit_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None

        shadow_claim = replace(claim, batch_id="generic-shadow-batch")
        generic_admission = await _admit(
            backend, shadow_claim, envelope, authority
        )
        with pytest.raises(
            MemoryValidationError, match="generic_audit_mutation_lineage_forbidden"
        ):
            await backend.record_llm_invocation(
                shadow_claim,
                envelope,
                generic_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                application.decisions,
            )
        with pytest.raises(MemoryWriterConflict, match="audit_not_durable"):
            await backend.finalize_analysis_application(claim, application)
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM llm_invocations"
        ) as cursor:
            count = await cursor.fetchone()
        assert count is not None and int(count[0]) == 0
        async with backend.connection.execute(
            "SELECT state FROM analysis_batches"
        ) as cursor:
            batch = await cursor.fetchone()
        assert batch is not None and str(batch[0]) == "audit_pending"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_old_handed_off_capability_cannot_reject_after_phase_advances(
    tmp_path: Path,
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "stale-reject.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        stale_admission = await _admit(backend, claim, envelope, authority)
        winning_admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, winning_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        rejected = RejectedAnalysisAudit(
            envelope.result.result_hash,
            envelope.result.provider_response_id,
            envelope.result.input_tokens,
            envelope.result.output_tokens,
            envelope.result.cost_microunits,
            envelope.result.latency_ms,
            envelope.delivery_receipt,
        )
        with pytest.raises(MemoryWriterConflict, match="rejection_phase_invalid"):
            await backend.reject_analysis_result(
                claim,
                rejected,
                "stale_rejection_attempt",
                TEST_WORKER_CONFIG.validator_version,
                stale_admission,
            )
        async with backend.connection.execute(
            "SELECT state FROM analysis_batches"
        ) as cursor:
            committed_phase = await cursor.fetchone()
        assert committed_phase is not None and str(committed_phase[0]) == "result_committed"

        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None
        with pytest.raises(MemoryWriterConflict, match="rejection_phase_invalid"):
            await backend.reject_analysis_result(
                claim,
                rejected,
                "stale_rejection_attempt",
                TEST_WORKER_CONFIG.validator_version,
                stale_admission,
            )
        async with backend.connection.execute(
            "SELECT state,result_hash,application_receipt_hash FROM analysis_batches"
        ) as cursor:
            batch = await cursor.fetchone()
        assert batch is not None
        assert tuple(batch) == (
            "audit_pending",
            envelope.result.result_hash,
            application.receipt.receipt_hash,
        )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_result_capability_survives_cancellation_before_consume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "result-pre-consume-cancel.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        admission = await _admit(backend, claim, envelope, authority)
        consume = backend._consume_analysis_delivery_admission
        cancelled = False

        async def cancel_before_consume(*args: object, **kwargs: object) -> None:
            nonlocal cancelled
            if kwargs.get("purpose") == "commit" and not cancelled:
                cancelled = True
                raise asyncio.CancelledError
            await consume(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            backend, "_consume_analysis_delivery_admission", cancel_before_consume
        )
        with pytest.raises(asyncio.CancelledError):
            await backend.commit_analysis_result(claim, envelope, admission)
        async with backend.connection.execute(
            "SELECT state,result_json FROM analysis_batches"
        ) as cursor:
            before_retry = await cursor.fetchone()
        assert before_retry is not None and tuple(before_retry) == ("handed_off", None)

        monkeypatch.setattr(backend, "_consume_analysis_delivery_admission", consume)
        committed = await backend.commit_analysis_result(claim, envelope, admission)
        assert committed.outcome is AnalysisResultCommitOutcome.COMMITTED
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_audit_capability_survives_cancellation_before_consume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "audit-pre-consume-cancel.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        commit_admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, commit_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None
        audit_admission = await backend.admit_analysis_application(
            claim, envelope, application
        )
        consume = backend._consume_analysis_delivery_admission
        cancelled = False

        async def cancel_before_consume(*args: object, **kwargs: object) -> None:
            nonlocal cancelled
            if kwargs.get("purpose") == "audit" and not cancelled:
                cancelled = True
                raise asyncio.CancelledError
            await consume(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            backend, "_consume_analysis_delivery_admission", cancel_before_consume
        )
        with pytest.raises(asyncio.CancelledError):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                application.decisions,
            )
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM llm_invocations"
        ) as cursor:
            invocation_count = await cursor.fetchone()
        assert invocation_count is not None and int(invocation_count[0]) == 0

        monkeypatch.setattr(backend, "_consume_analysis_delivery_admission", consume)
        await backend.record_memory_analysis(
            claim,
            envelope,
            audit_admission,
            application.invocation_id,
            application.turn_id,
            claim.request,
            envelope.result,
            envelope.delivery_receipt,
            application.receipt,
            application.decisions,
        )
        assert await backend.finalize_analysis_application(claim, application)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_caller_created_rejected_receipt_and_decisions_are_not_authority(
    tmp_path: Path,
) -> None:
    authority = _Executor(
        None,
        structured_override={"outcome": "refusal", "operations": []},
    )
    backend = _authority_backend(
        tmp_path / "caller-rejected-authority.db", authority, now=lambda: 20.0
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        commit_admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, commit_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None
        assert (
            application.receipt.validation_status
            is AnalysisValidationStatus.REJECTED
        )
        assert application.decisions
        audit_admission = await backend.admit_analysis_application(
            claim, envelope, application
        )

        caller_receipt = replace(
            application.receipt, validator_version="caller-rejected-validator/v1"
        )
        with pytest.raises(MemoryValidationError, match="application_differs"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                caller_receipt,
                application.decisions,
            )
        caller_decisions = (
            replace(
                application.decisions[0],
                reason_code="caller_rejected_decision",
            ),
        )
        with pytest.raises(MemoryValidationError, match="application_differs"):
            await backend.record_memory_analysis(
                claim,
                envelope,
                audit_admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                envelope.result,
                envelope.delivery_receipt,
                application.receipt,
                caller_decisions,
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("event_mode", ("duplicate", "wrong_result", "cross_batch"))
async def test_invalid_mutation_audit_events_cannot_satisfy_finalize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_mode: str,
) -> None:
    authority = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / f"invalid-audit-event-{event_mode}.db",
        authority,
        now=lambda: 20.0,
    )
    try:
        await backend.initialize()
        await _ingest(backend)
        claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
        assert claim is not None
        envelope = await authority.analyze_memory(claim.request)
        commit_admission = await _admit(backend, claim, envelope, authority)
        assert (
            await backend.commit_analysis_result(claim, envelope, commit_admission)
        ).outcome is AnalysisResultCommitOutcome.COMMITTED
        application = await backend.prepare_analysis_application(
            claim, envelope.result, TEST_WORKER_CONFIG.validator_version
        )
        assert application is not None
        audit_admission = await backend.admit_analysis_application(
            claim, envelope, application
        )

        append_events = backend._append_batch_events_unlocked

        async def omit_valid_mutation_link(
            batch_id: str,
            event_kind: str,
            reason_code: str,
            occurred_at: float,
            result_hash: str | None = None,
        ) -> None:
            if event_kind != "mutation_audit_committed":
                await append_events(
                    batch_id, event_kind, reason_code, occurred_at, result_hash
                )

        monkeypatch.setattr(
            backend, "_append_batch_events_unlocked", omit_valid_mutation_link
        )
        await backend.record_memory_analysis(
            claim,
            envelope,
            audit_admission,
            application.invocation_id,
            application.turn_id,
            claim.request,
            envelope.result,
            envelope.delivery_receipt,
            application.receipt,
            application.decisions,
        )
        monkeypatch.setattr(backend, "_append_batch_events_unlocked", append_events)

        event_batch_id = claim.batch_id
        if event_mode == "cross_batch":
            await _ingest_indexes(backend, (3, 4))
            other_claim = await backend.claim_analysis_batch(
                TEST_WORKER_CONFIG, "worker-2"
            )
            assert other_claim is not None and other_claim.batch_id != claim.batch_id
            event_batch_id = other_claim.batch_id
        async with backend.connection.execute(
            "SELECT job_id,job_attempt FROM analysis_batch_members "
            "WHERE batch_id=? ORDER BY ordinal",
            (claim.batch_id,),
        ) as cursor:
            members = tuple(await cursor.fetchall())
        assert len(members) == len(claim.job_ids)
        repeats = 2 if event_mode == "duplicate" else 1
        fake_result_hash = (
            "0" * 64
            if event_mode == "wrong_result"
            else envelope.result.result_hash
        )
        for copy_index in range(repeats):
            for ordinal, member in enumerate(members, start=1):
                event_id = f"fake-{event_mode}-{copy_index}-{ordinal}"
                event_hash = hashlib.sha256(event_id.encode()).hexdigest()
                await backend.connection.execute(
                    "INSERT INTO job_attempt_events(event_id,batch_id,job_id,attempt,"
                    "event_kind,reason_code,request_hash,result_hash,occurred_at,event_hash) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        event_batch_id,
                        str(member["job_id"]),
                        int(member["job_attempt"]),
                        "mutation_audit_committed",
                        "analysis_mutation_audit_committed",
                        claim.request.request_hash,
                        fake_result_hash,
                        20.0,
                        event_hash,
                    ),
                )
        await backend.connection.commit()

        with pytest.raises(
            MemoryWriterConflict, match="mutation_audit_authority_missing"
        ):
            await backend.finalize_analysis_application(claim, application)
        async with backend.connection.execute(
            "SELECT state FROM analysis_batches WHERE batch_id=?", (claim.batch_id,)
        ) as cursor:
            batch = await cursor.fetchone()
        assert batch is not None and str(batch[0]) == "audit_pending"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_verified_delivery_with_credential_metadata_is_rejected_without_body(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delivery-private-metadata.db"
    private_issuer = "ghp_012345678901234567890123456789"
    executor = _Executor(None, no_mutation=True, issuer_id=private_issuer)
    backend = _authority_backend(path, executor, now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )

    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    assert executor.verification_calls == 1
    async with backend.connection.execute(
        "SELECT delivery_receipt_json,validation_receipt_json,output_reason_code "
        "FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None
    assert json.loads(str(row[1]))["validation_status"] == "rejected"
    assert str(row[2]) == "analysis_delivery_public_metadata_invalid"
    async with backend.connection.execute(
        "SELECT result_json,delivery_receipt_json FROM analysis_batches"
    ) as cursor:
        batch = await cursor.fetchone()
    assert batch is not None and batch[0] is None and batch[1] is None
    database_bytes = path.read_bytes()
    wal_path = Path(f"{path}-wal")
    wal_bytes = wal_path.read_bytes() if wal_path.exists() else b""
    assert private_issuer.encode() not in database_bytes + wal_bytes
    await backend.close()


@pytest.mark.asyncio
async def test_no_mutation_is_accepted_and_audited_without_decisions(tmp_path: Path) -> None:
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "no-mutation.db", executor, now=lambda: 20.0
    )
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend,
        executor,
        executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    async with backend.connection.execute("SELECT COUNT(*) FROM decision_records") as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 0
    async with backend.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 1
    async with backend.connection.execute(
        "SELECT base_revision,committed_revision,plan_json FROM accepted_analysis_plans"
    ) as cursor:
        no_mutation = await cursor.fetchone()
    assert no_mutation is not None
    assert int(no_mutation[0]) == int(no_mutation[1]) == 1
    assert json.loads(str(no_mutation[2])) == {"operations": [], "outcome": "no_mutation"}
    await backend.close()


@pytest.mark.asyncio
async def test_no_mutation_does_not_stale_the_next_real_mutation_base_revision(
    tmp_path: Path,
) -> None:
    deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}
    no_mutation_executor = _Executor(None, no_mutation=True, deliveries=deliveries)
    backend = _authority_backend(
        tmp_path / "no-mutation-then-plan.db",
        no_mutation_executor,
        now=lambda: 20.0,
    )
    await backend.initialize()
    await _ingest(backend)
    no_mutation_runner = DurableMemoryJobRunner(
        backend,
        no_mutation_executor,
        no_mutation_executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    assert await no_mutation_runner.run_once() is WorkerRunOutcome.APPLIED

    await _ingest_indexes(backend, (3, 4))
    mutation_executor = _Executor(backend, base_revision=1, deliveries=deliveries)
    mutation_runner = DurableMemoryJobRunner(
        backend,
        mutation_executor,
        no_mutation_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: 20.0,
    )
    assert await mutation_runner.run_once() is WorkerRunOutcome.APPLIED

    async with backend.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 2
    async with backend.connection.execute(
        "SELECT base_revision,committed_revision,plan_json FROM accepted_analysis_plans "
        "ORDER BY created_at,batch_id"
    ) as cursor:
        plans = tuple(await cursor.fetchall())
    assert len(plans) == 2
    revisions = {(int(row[0]), int(row[1])) for row in plans}
    assert revisions == {(1, 1), (1, 2)}
    assert sum(json.loads(str(row[2])).get("outcome") == "no_mutation" for row in plans) == 1
    await backend.close()


@pytest.mark.asyncio
async def test_result_replay_divergence_and_stale_lease_are_audited_not_applied(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "result-cas.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend)
    claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
    assert claim is not None
    envelope = await executor.analyze_memory(claim.request)
    result = envelope.result
    first_admission = await _admit(backend, claim, envelope, executor)
    first = await backend.commit_analysis_result(claim, envelope, first_admission)
    replay_admission = await _admit(backend, claim, envelope, executor)
    replay = await backend.commit_analysis_result(claim, envelope, replay_admission)
    assert first.outcome is AnalysisResultCommitOutcome.COMMITTED
    assert replay.outcome is AnalysisResultCommitOutcome.REPLAYED
    divergent = MemoryAnalysisResult(
        result.job_id,
        result.run_id,
        result.request_hash,
        "provider-response-divergent",
        {"outcome": "no_mutation", "operations": [], "extra": "different"},
        100,
        50,
        7,
        25,
    )
    divergent_envelope = _result_envelope(claim.request, divergent, executor.issuer_id)
    executor.deliveries[(claim.request.request_hash, claim.request.attempt)] = divergent_envelope
    divergent_admission = await _admit(backend, claim, divergent_envelope, executor)
    divergence = await backend.commit_analysis_result(
        claim, divergent_envelope, divergent_admission
    )
    assert divergence.outcome is AnalysisResultCommitOutcome.DIVERGENT
    assert divergence.canonical_result == result

    clock[0] = 31.0
    reclaimed = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-2")
    assert reclaimed is not None and reclaimed.lease_token != claim.lease_token
    executor.deliveries[(claim.request.request_hash, claim.request.attempt)] = envelope
    stale_admission = await _admit(backend, claim, envelope, executor)
    stale = await backend.commit_analysis_result(claim, envelope, stale_admission)
    assert stale.outcome is AnalysisResultCommitOutcome.STALE_LEASE
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds_after_expiry", (0.0, 1.0))
async def test_expired_lease_without_reclaim_cannot_commit_result(
    tmp_path: Path, seconds_after_expiry: float
) -> None:
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "expired.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend)
    claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-old")
    assert claim is not None
    envelope = await executor.analyze_memory(claim.request)
    clock[0] = claim.lease_expires_at + seconds_after_expiry

    admission = await _admit(backend, claim, envelope, executor)
    committed = await backend.commit_analysis_result(claim, envelope, admission)

    assert committed.outcome is AnalysisResultCommitOutcome.STALE_LEASE
    async with backend.connection.execute(
        "SELECT result_json,state FROM analysis_batches"
    ) as cursor:
        batch = await cursor.fetchone()
    assert batch is not None and batch[0] is None and str(batch[1]) == "handed_off"
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM analysis_apply_heads"
    ) as cursor:
        head_count = await cursor.fetchone()
    assert head_count is not None and int(head_count[0]) == 0
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ("member_expiry", "attempt_token"))
async def test_partial_member_lease_or_attempt_tamper_invalidates_whole_claim(
    tmp_path: Path, tamper: str
) -> None:
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / f"partial-{tamper}.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend)
    claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-old")
    assert claim is not None
    envelope = await executor.analyze_memory(claim.request)
    if tamper == "member_expiry":
        await backend.connection.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE job_id=?",
            (clock[0], claim.job_ids[0]),
        )
    else:
        await backend.connection.execute(
            "UPDATE job_attempts SET lease_token='tampered' WHERE job_id=?",
            (claim.job_ids[0],),
        )
    await backend.connection.commit()

    admission = await _admit(backend, claim, envelope, executor)
    committed = await backend.commit_analysis_result(claim, envelope, admission)

    assert committed.outcome is AnalysisResultCommitOutcome.STALE_LEASE
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM job_attempt_events WHERE reason_code="
        "'analysis_stale_lease_result_ignored'"
    ) as cursor:
        events = await cursor.fetchone()
    assert events is not None and int(events[0]) == 2
    await backend.close()


@pytest.mark.asyncio
async def test_expiry_between_result_prepare_and_finalize_never_applies_late(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "phase-expiry.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend)
    claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-old")
    assert claim is not None
    envelope = await executor.analyze_memory(claim.request)
    result = envelope.result
    admission = await _admit(backend, claim, envelope, executor)
    assert (
        await backend.commit_analysis_result(claim, envelope, admission)
    ).outcome is AnalysisResultCommitOutcome.COMMITTED
    clock[0] = claim.lease_expires_at
    assert (
        await backend.prepare_analysis_application(
            claim, result, TEST_WORKER_CONFIG.validator_version
        )
        is None
    )
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM analysis_apply_heads"
    ) as cursor:
        head_count = await cursor.fetchone()
    assert head_count is not None and int(head_count[0]) == 0

    clock[0] = 40.0
    reclaimed = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-new")
    assert reclaimed is not None and reclaimed.result is not None
    assert reclaimed.envelope is not None
    application = await backend.prepare_analysis_application(
        reclaimed, reclaimed.result, TEST_WORKER_CONFIG.validator_version
    )
    assert application is not None
    replay_admission = await _admit(
        backend, reclaimed, reclaimed.envelope, executor
    )
    await backend.record_memory_analysis(
        reclaimed,
        reclaimed.envelope,
        replay_admission,
        application.invocation_id,
        application.turn_id,
        reclaimed.request,
        reclaimed.result,
        reclaimed.envelope.delivery_receipt,
        application.receipt,
        application.decisions,
    )
    clock[0] = reclaimed.lease_expires_at
    assert not await backend.finalize_analysis_application(reclaimed, application)
    async with backend.connection.execute("SELECT state FROM jobs") as cursor:
        assert {str(row[0]) for row in await cursor.fetchall()} == {"claimed"}
    await backend.close()


@pytest.mark.asyncio
async def test_executor_failure_retries_then_dead_letters_with_explicit_schedule(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    executor = _Executor(None, error=TimeoutError())
    backend = _authority_backend(
        tmp_path / "retry.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    assert await runner.run_once() is WorkerRunOutcome.RETRY_SCHEDULED
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    clock[0] = 23.0
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    assert executor.calls == 2
    async with backend.connection.execute("SELECT DISTINCT state FROM jobs") as cursor:
        assert [str(row[0]) for row in await cursor.fetchall()] == ["dead_letter"]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authority_error", "reason_code"),
    (
        (TimeoutError("Host authority timeout"), "analysis_delivery_authority_timeout"),
        (
            AnalysisDeliveryAuthorityTransientError("Host authority unavailable"),
            "analysis_delivery_authority_transient",
        ),
    ),
)
async def test_authority_transient_is_audited_and_retried_not_dead_lettered(
    tmp_path: Path,
    authority_error: Exception,
    reason_code: str,
) -> None:
    clock = [20.0]
    path = tmp_path / f"{reason_code}.db"
    durable_deliveries: dict[
        tuple[str, int], MemoryAnalysisResultEnvelope
    ] = {}
    authority = _Executor(
        None,
        no_mutation=True,
        authority_error=authority_error,
        deliveries=durable_deliveries,
    )
    backend = _authority_backend(path, authority, now=lambda: clock[0])
    try:
        await backend.initialize()
        await _ingest(backend)
        runner = DurableMemoryJobRunner(
            backend,
            authority,
            authority,
            TEST_WORKER_CONFIG,
            "worker-1",
            lambda: clock[0],
        )

        assert await runner.run_once() is WorkerRunOutcome.RETRY_SCHEDULED
        async with backend.connection.execute(
            "SELECT output_reason_code,delivery_receipt_json FROM llm_invocations"
        ) as cursor:
            rejected = await cursor.fetchone()
        assert rejected is None
        async with backend.connection.execute(
            "SELECT DISTINCT event_kind,reason_code FROM job_attempt_events "
            "WHERE event_kind='authority_retry_scheduled'"
        ) as cursor:
            retry_events = tuple(await cursor.fetchall())
        assert retry_events
        assert {(str(row[0]), str(row[1])) for row in retry_events} == {
            ("authority_retry_scheduled", reason_code)
        }
        async with backend.connection.execute("SELECT DISTINCT state FROM jobs") as cursor:
            assert {str(row[0]) for row in await cursor.fetchall()} == {"claimed"}
        async with backend.connection.execute(
            "SELECT attempt,request_hash,result_json,delivery_receipt_json "
            "FROM analysis_batches"
        ) as cursor:
            pending = await cursor.fetchone()
        assert pending is not None
        assert int(pending[0]) == 1 and str(pending[1])
        assert pending[2] is None and pending[3] is None
    finally:
        await backend.close()

    clock[0] = 23.0
    replay_authority = _Executor(
        None,
        no_mutation=True,
        deliveries=durable_deliveries,
    )
    reopened = _authority_backend(path, replay_authority, now=lambda: clock[0])
    try:
        await reopened.initialize()
        replay_runner = DurableMemoryJobRunner(
            reopened,
            replay_authority,
            replay_authority,
            TEST_WORKER_CONFIG,
            "worker-2",
            lambda: clock[0],
        )
        assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
        assert authority.provider_calls == 1
        assert replay_authority.provider_calls == 0
        assert replay_authority.calls == 1
        async with reopened.connection.execute(
            "SELECT attempt,request_hash FROM analysis_batches"
        ) as cursor:
            resumed = await cursor.fetchone()
        assert resumed is not None
        assert (int(resumed[0]), str(resumed[1])) == (int(pending[0]), str(pending[1]))
        async with reopened.connection.execute(
            "SELECT output_reason_code FROM llm_invocations ORDER BY invocation_sequence"
        ) as cursor:
            reasons = [str(row[0]) for row in await cursor.fetchall()]
        assert reasons == ["analysis_validator_accepted"]
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_authority_retry_budget_dead_letters_without_persisting_unverified_body(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authority-budget.db"
    clock = [20.0]
    durable_deliveries: dict[
        tuple[str, int], MemoryAnalysisResultEnvelope
    ] = {}
    first_authority = _Executor(
        None,
        structured_override={"safe": PRIVATE_CREDENTIAL_CANARY},
        authority_error=AnalysisDeliveryAuthorityTransientError("Host unavailable"),
        deliveries=durable_deliveries,
    )
    first = _authority_backend(path, first_authority, now=lambda: clock[0])
    with structlog.testing.capture_logs() as captured_logs:
        try:
            await first.initialize()
            await _ingest(first)
            first_runner = DurableMemoryJobRunner(
                first,
                first_authority,
                first_authority,
                TEST_WORKER_CONFIG,
                "worker-1",
                lambda: clock[0],
            )
            assert await first_runner.run_once() is WorkerRunOutcome.RETRY_SCHEDULED
        finally:
            await first.close()

        clock[0] = 23.0
        replay_authority = _Executor(
            None,
            structured_override={"safe": PRIVATE_CREDENTIAL_CANARY},
            authority_error=AnalysisDeliveryAuthorityTransientError("Host unavailable"),
            deliveries=durable_deliveries,
        )
        reopened = _authority_backend(path, replay_authority, now=lambda: clock[0])
        try:
            await reopened.initialize()
            replay_runner = DurableMemoryJobRunner(
                reopened,
                replay_authority,
                replay_authority,
                TEST_WORKER_CONFIG,
                "worker-2",
                lambda: clock[0],
            )
            assert await replay_runner.run_once() is WorkerRunOutcome.DEAD_LETTER
            assert first_authority.provider_calls == 1
            assert replay_authority.provider_calls == 0
            async with reopened.connection.execute(
                "SELECT output_reason_code,delivery_receipt_json FROM llm_invocations "
                "ORDER BY invocation_sequence"
            ) as cursor:
                audit_rows = tuple(await cursor.fetchall())
            assert len(audit_rows) == 1
            assert {str(row[0]) for row in audit_rows} == {
                "analysis_delivery_authority_transient"
            }
            assert all(row[1] is None for row in audit_rows)
            async with reopened.connection.execute(
                "SELECT result_json,delivery_receipt_json,state FROM analysis_batches"
            ) as cursor:
                batch = await cursor.fetchone()
            assert batch is not None
            assert batch[0] is None and batch[1] is None and str(batch[2]) == "failed"
        finally:
            await reopened.close()

    durable_bytes = b"".join(
        item.read_bytes()
        for item in (path, path.with_name(path.name + "-wal"))
        if item.exists()
    )
    assert PRIVATE_CREDENTIAL_CANARY.encode() not in durable_bytes
    assert PRIVATE_CREDENTIAL_CANARY not in repr(captured_logs)


@pytest.mark.asyncio
async def test_authority_retry_commit_crash_reopens_same_request_without_provider_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authority-retry-crash.db"
    clock = [20.0]
    fired = False
    deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.fail.after_commit" and not fired:
            fired = True
            raise RuntimeError("crash after authority retry commit")

    first_authority = _Executor(
        None,
        no_mutation=True,
        authority_error=TimeoutError("Host authority timeout"),
        deliveries=deliveries,
    )
    first = _authority_backend(
        path, first_authority, now=lambda: clock[0], fault_injector=fault
    )
    try:
        await first.initialize()
        await _ingest(first)
        first_runner = DurableMemoryJobRunner(
            first,
            first_authority,
            first_authority,
            TEST_WORKER_CONFIG,
            "worker-1",
            lambda: clock[0],
        )
        with pytest.raises(RuntimeError, match="authority retry commit"):
            await first_runner.run_once()
    finally:
        await first.close()

    clock[0] = 23.0
    replay_authority = _Executor(None, no_mutation=True, deliveries=deliveries)
    reopened = _authority_backend(path, replay_authority, now=lambda: clock[0])
    try:
        await reopened.initialize()
        replay_runner = DurableMemoryJobRunner(
            reopened,
            replay_authority,
            replay_authority,
            TEST_WORKER_CONFIG,
            "worker-2",
            lambda: clock[0],
        )
        assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
        assert first_authority.provider_calls == 1
        assert replay_authority.provider_calls == 0
        async with reopened.connection.execute(
            "SELECT COUNT(DISTINCT request_hash),MIN(attempt),MAX(attempt) "
            "FROM analysis_batches"
        ) as cursor:
            lineage = await cursor.fetchone()
        assert lineage is not None and tuple(lineage) == (1, 1, 1)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_private_result_is_dead_lettered_without_body_in_db_wal_or_logs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private-result.db"
    executor = _Executor(None, private=True)
    backend = _authority_backend(path, executor, now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend,
        executor,
        executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    await backend.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    durable = b"".join(
        item.read_bytes()
        for item in (path, path.with_name(path.name + "-wal"))
        if item.exists()
    )
    assert b"hidden-chain-of-thought-canary" not in durable
    async with backend.connection.execute(
        "SELECT result_json FROM analysis_batches"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] is None
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("type", "hash", "lineage", "private", "oversize"))
async def test_every_rejected_provider_result_has_one_public_only_audit_record(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / f"rejected-{mode}.db"
    executor = _RejectedResultExecutor(None, mode)
    backend = _authority_backend(path, executor, now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    config = (
        replace(TEST_WORKER_CONFIG, max_result_bytes=100)
        if mode == "oversize"
        else TEST_WORKER_CONFIG
    )
    runner = DurableMemoryJobRunner(
        backend,
        executor,
        executor,
        config,
        "worker-1",
        lambda: 20.0,
    )

    with structlog.testing.capture_logs() as captured_logs:
        assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER

    async with backend.connection.execute(
        "SELECT request_hash,public_output_json,public_output_hash,output_storage_status,"
        "output_reason_code,provider_id,model_id,delivery_receipt_json,"
        "validation_receipt_json FROM llm_invocations"
    ) as cursor:
        invocation = await cursor.fetchone()
        assert invocation is not None and await cursor.fetchone() is None
    expected_reason = {
        "type": "analysis_envelope_type_invalid",
        "hash": "analysis_envelope_lineage_invalid",
        "lineage": "analysis_envelope_lineage_invalid",
        "private": "analysis_result_private_material",
        "oversize": "analysis_result_oversize",
    }[mode]
    assert str(invocation[0])
    assert invocation[1] is None and invocation[2] is None
    assert str(invocation[3]) == "rejected_unsafe"
    assert str(invocation[4]) == expected_reason
    assert str(invocation[5]) == TEST_WORKER_CONFIG.provider_id
    assert str(invocation[6]) == TEST_WORKER_CONFIG.model_id
    if mode in {"private", "oversize"}:
        assert json.loads(str(invocation[7]))["issuer_id"] == executor.issuer_id
    else:
        assert invocation[7] is None
    receipt = json.loads(str(invocation[8]))
    assert receipt["validation_status"] == "rejected"
    assert receipt["committed_revision"] is None
    async with backend.connection.execute(
        "SELECT outcome,reason_code,canonical_payload FROM decision_records"
    ) as cursor:
        decision = await cursor.fetchone()
        assert decision is not None and await cursor.fetchone() is None
    assert str(decision[0]) == "rejected"
    assert str(decision[1]) == expected_reason
    assert json.loads(str(decision[2])) == {}
    async with backend.connection.execute("SELECT state FROM jobs") as cursor:
        assert {str(row[0]) for row in await cursor.fetchall()} == {"dead_letter"}
    database_bytes = path.read_bytes()
    wal_path = Path(f"{path}-wal")
    wal_bytes = wal_path.read_bytes() if wal_path.exists() else b""
    if mode in {"private", "oversize"}:
        async with backend.connection.execute(
            "SELECT invocation_id FROM llm_invocations"
        ) as cursor:
            invocation_id = await cursor.fetchone()
        assert invocation_id is not None
        exported = await backend.export_audit_trace(
            AuditTraceQuery(
                "actor-1",
                AuditTraceSelector.INVOCATION,
                str(invocation_id[0]),
            )
        )
        canary = (
            PRIVATE_CREDENTIAL_CANARY
            if mode == "private"
            else OVERSIZE_BODY_CANARY
        ).encode()
        inspected = (
            database_bytes
            + wal_bytes
            + repr(captured_logs).encode()
            + repr(exported).encode()
        )
        assert canary not in inspected
    await backend.close()


@pytest.mark.asyncio
async def test_rejected_audit_and_dead_letter_commit_atomically_across_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rejected-crash.db"
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.fail.after_commit" and not fired:
            fired = True
            raise RuntimeError("fault after rejected audit commit")

    executor = _RejectedResultExecutor(None, "private")
    first = _authority_backend(
        path, executor, now=lambda: 20.0, fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    runner = DurableMemoryJobRunner(
        first,
        executor,
        executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    with pytest.raises(RuntimeError, match="fault after rejected audit commit"):
        await runner.run_once()
    await first.close()

    replay_executor = _RejectedResultExecutor(None, "private")
    reopened = _authority_backend(path, replay_executor, now=lambda: 40.0)
    await reopened.initialize()
    replay = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: 40.0,
    )
    assert await replay.run_once() is WorkerRunOutcome.IDLE
    for table in ("llm_invocations", "decision_records"):
        async with reopened.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        assert row is not None and int(row[0]) == 1
    async with reopened.connection.execute("SELECT state FROM jobs") as cursor:
        assert {str(row[0]) for row in await cursor.fetchall()} == {"dead_letter"}
    assert b"ghp_012345678901234567890123456789" not in path.read_bytes()
    await reopened.close()


@pytest.mark.asyncio
async def test_crash_after_result_commit_reopens_without_second_provider_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reopen.db"
    clock = [20.0]
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.result.after_commit" and not fired:
            fired = True
            raise RuntimeError("crash after durable result")

    executor = _Executor(None, no_mutation=True)
    first = _authority_backend(
        path, executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    runner = DurableMemoryJobRunner(
        first, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    with pytest.raises(RuntimeError, match="crash after durable result"):
        await runner.run_once()
    await first.close()

    clock[0] = 31.0
    replay_executor = _Executor(
        None, no_mutation=True, deliveries=executor.deliveries
    )
    reopened = _authority_backend(
        path, replay_executor, now=lambda: clock[0]
    )
    await reopened.initialize()
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
    assert executor.calls == 1
    assert executor.provider_calls == 1
    assert replay_executor.calls == 0
    assert replay_executor.provider_calls == 0
    assert replay_executor.verification_calls == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_audit_pending_restart_uses_repository_without_host_reverification(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit-pending-restart.db"
    clock = [20.0]
    fired = False
    deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.audit.after_commit" and not fired:
            fired = True
            raise RuntimeError("crash after mutation audit commit")

    first_executor = _Executor(None, no_mutation=True, deliveries=deliveries)
    first = _authority_backend(
        path, first_executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    first_runner = DurableMemoryJobRunner(
        first,
        first_executor,
        first_executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: clock[0],
    )
    with pytest.raises(RuntimeError, match="mutation audit commit"):
        await first_runner.run_once()
    async with first.connection.execute(
        "SELECT state,attempt,result_hash FROM analysis_batches"
    ) as cursor:
        before = await cursor.fetchone()
    assert before is not None and str(before[0]) == "audit_pending"
    await first.close()

    clock[0] = 31.0
    unavailable_host = _Executor(
        None,
        no_mutation=True,
        deliveries=deliveries,
        authority_error=AnalysisDeliveryAuthorityTransientError("must not be called"),
    )
    reopened = _authority_backend(path, unavailable_host, now=lambda: clock[0])
    await reopened.initialize()
    replay_runner = DurableMemoryJobRunner(
        reopened,
        unavailable_host,
        unavailable_host,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
    assert unavailable_host.calls == 0
    assert unavailable_host.provider_calls == 0
    assert unavailable_host.verification_calls == 0
    async with reopened.connection.execute(
        "SELECT state,attempt,result_hash FROM analysis_batches"
    ) as cursor:
        after = await cursor.fetchone()
    assert after is not None
    assert tuple(after) == ("applied", int(before[1]), str(before[2]))
    await reopened.close()


@pytest.mark.asyncio
async def test_crash_before_memory_commit_replays_same_host_delivery_without_provider(
    tmp_path: Path,
) -> None:
    path = tmp_path / "host-delivery-replay.db"
    clock = [20.0]
    fired = False
    durable_deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.result.before_commit" and not fired:
            fired = True
            raise RuntimeError("crash before Memory result commit")

    executor = _Executor(None, no_mutation=True, deliveries=durable_deliveries)
    first = _authority_backend(
        path, executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    runner = DurableMemoryJobRunner(
        first, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    with pytest.raises(RuntimeError, match="before Memory result commit"):
        await runner.run_once()
    assert executor.calls == 1
    assert executor.provider_calls == 1
    assert executor.verification_calls == 1
    assert len(durable_deliveries) == 1
    await first.close()

    clock[0] = 31.0
    replay_executor = _Executor(
        None,
        no_mutation=True,
        deliveries=durable_deliveries,
    )
    reopened = _authority_backend(
        path, replay_executor, now=lambda: clock[0]
    )
    await reopened.initialize()
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
    assert replay_executor.calls == 1
    assert replay_executor.provider_calls == 0
    assert replay_executor.verification_calls == 1
    async with reopened.connection.execute(
        "SELECT delivery_receipt_json,validation_receipt_json FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert json.loads(str(row[0]))["host_receipt_id"].startswith("host-record-")
    assert json.loads(str(row[1]))["validator_version"] == (
        TEST_WORKER_CONFIG.validator_version
    )
    await reopened.close()


@pytest.mark.asyncio
async def test_persisted_delivery_receipt_tamper_fails_closed_on_reclaim(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delivery-tamper.db"
    clock = [20.0]
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.result.after_commit" and not fired:
            fired = True
            raise RuntimeError("crash after durable result")

    executor = _Executor(None, no_mutation=True)
    first = _authority_backend(
        path, executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    runner = DurableMemoryJobRunner(
        first, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    with pytest.raises(RuntimeError, match="crash after durable result"):
        await runner.run_once()
    await first.connection.execute(
        "UPDATE analysis_batches SET delivery_receipt_hash=?",
        ("0" * 64,),
    )
    await first.connection.commit()
    await first.close()

    clock[0] = 31.0
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: clock[0])
    await reopened.initialize()
    with pytest.raises(MemoryCorruptionError, match="delivery authority differs"):
        await reopened.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-2")
    await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault_point", "advance_clock", "expected_replay_calls", "expected_outcome"),
    (
        ("job.claim.after_commit", True, 1, WorkerRunOutcome.APPLIED),
        ("job.result.after_capability_consume", True, 1, WorkerRunOutcome.APPLIED),
        ("job.apply.before_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.apply.after_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.audit.after_capability_consume", True, 0, WorkerRunOutcome.APPLIED),
        ("job.audit.before_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.audit.after_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.finalize.before_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.finalize.after_commit", False, 0, WorkerRunOutcome.IDLE),
    ),
)
async def test_commit_boundary_fault_matrix_is_reclaim_safe(
    tmp_path: Path,
    fault_point: str,
    advance_clock: bool,
    expected_replay_calls: int,
    expected_outcome: WorkerRunOutcome,
) -> None:
    path = tmp_path / f"fault-{fault_point}.db"
    clock = [20.0]
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise RuntimeError(f"fault at {point}")

    first_executor = _Executor(None, no_mutation=True)
    first = _authority_backend(
        path, first_executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    first_runner = DurableMemoryJobRunner(
        first,
        first_executor,
        first_executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: clock[0],
    )
    with pytest.raises(RuntimeError, match="fault at"):
        await first_runner.run_once()
    await first.close()

    if advance_clock:
        clock[0] = 31.0
    replay_executor = _Executor(
        None, no_mutation=True, deliveries=first_executor.deliveries
    )
    reopened = _authority_backend(
        path, replay_executor, now=lambda: clock[0]
    )
    await reopened.initialize()
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is expected_outcome
    assert replay_executor.calls == expected_replay_calls
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 1
    async with reopened.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_accepted_mutation_recovers_after_finalize_boundary_without_reanalysis(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accepted-mutation-finalize-recovery.db"
    clock = [20.0]
    fired = False
    deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.finalize.before_commit" and not fired:
            fired = True
            raise RuntimeError("accepted mutation finalize boundary")

    first_executor = _Executor(None, deliveries=deliveries)
    first = _authority_backend(
        path, first_executor, now=lambda: clock[0], fault_injector=fault
    )
    await first.initialize()
    await _ingest(first)
    first_runner = DurableMemoryJobRunner(
        first,
        first_executor,
        first_executor,
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: clock[0],
    )
    with pytest.raises(RuntimeError, match="accepted mutation finalize boundary"):
        await first_runner.run_once()
    assert first_executor.provider_calls == 1
    await first.close()

    clock[0] = 31.0
    replay_executor = _Executor(None, deliveries=deliveries)
    reopened = _authority_backend(path, replay_executor, now=lambda: clock[0])
    await reopened.initialize()
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
    assert replay_executor.calls == 0
    assert replay_executor.provider_calls == 0
    assert replay_executor.verification_calls == 0
    async with reopened.connection.execute(
        "SELECT state FROM analysis_batches"
    ) as cursor:
        batch = await cursor.fetchone()
    assert batch is not None and str(batch[0]) == "applied"
    async with reopened.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 2
    for table in ("accepted_analysis_plans", "llm_invocations", "decision_records"):
        async with reopened.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            count = await cursor.fetchone()
        assert count is not None and int(count[0]) == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_partial_batch_waits_for_explicit_max_wait_and_shutdown_is_immediate(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "max-wait.db", executor, now=lambda: clock[0]
    )
    await backend.initialize()
    await _ingest(backend, count=1)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    clock[0] = 25.0
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    stop = asyncio.Event()
    stop.set()
    await runner.run_until_stopped(stop)
    assert executor.calls == 1
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executor_kwargs",
    (
        {"base_revision": 99},
        {"structured_override": {"outcome": "refusal", "operations": []}},
    ),
)
async def test_revision_drift_and_safe_refusal_are_rejected_and_audited(
    tmp_path: Path, executor_kwargs: dict[str, object]
) -> None:
    executor = _Executor(None, **executor_kwargs)  # type: ignore[arg-type]
    backend = _authority_backend(
        tmp_path / "rejected.db", executor, now=lambda: 20.0
    )
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    async with backend.connection.execute(
        "SELECT delivery_receipt_json,validation_receipt_json FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert json.loads(str(row[0]))["issuer_id"] == executor.issuer_id
    receipt = json.loads(str(row[1]))
    assert receipt["validation_status"] == "rejected"
    assert receipt["committed_revision"] is None
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM accepted_analysis_plans"
    ) as cursor:
        count = await cursor.fetchone()
    assert count is not None and int(count[0]) == 0
    async with backend.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 1
    async with backend.connection.execute(
        "SELECT outcome FROM decision_records"
    ) as cursor:
        decision = await cursor.fetchone()
    assert decision is not None and str(decision[0]) == "rejected"
    await backend.close()


@pytest.mark.asyncio
async def test_oversize_result_is_rejected_before_durable_body_write(tmp_path: Path) -> None:
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "oversize.db", executor, now=lambda: 20.0
    )
    await backend.initialize()
    await _ingest(backend)
    config = replace(TEST_WORKER_CONFIG, max_result_bytes=100)
    runner = DurableMemoryJobRunner(
        backend,
        executor,
        executor,
        config,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    async with backend.connection.execute(
        "SELECT result_json,state FROM analysis_batches"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] is None and str(row[1]) == "failed"
    await backend.close()


def test_worker_policy_requires_every_value_and_has_no_product_defaults() -> None:
    parameters = inspect.signature(MemoryJobWorkerConfig).parameters.values()
    assert parameters
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)
    with pytest.raises(TypeError):
        MemoryJobWorkerConfig()  # type: ignore[call-arg]
