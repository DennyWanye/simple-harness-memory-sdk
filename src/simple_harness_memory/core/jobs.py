"""Durable batched memory-analysis worker with explicit, caller-owned policy."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    AnalysisBudget,
    MemoryAnalysisDeliveryAuthorityPort,
    MemoryAnalysisDeliveryReceipt,
    MemoryAnalysisExecutorPort,
    MemoryAnalysisReceipt,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
    MemoryAnalysisResultEnvelope,
)

from simple_harness_memory.core.audit import (
    DecisionLedgerEntry,
    PublicReasoningReference,
    freeze_public_audit_object,
)
from simple_harness_memory.core.errors import MemoryLimitError, MemoryValidationError


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _non_negative_seconds(value: object, name: str, *, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < (0 if not positive else 0.000_001)
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return float(value)


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode()) > 1024
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class MemoryJobWorkerConfig:
    """No field has a production default; S5 composition must provide every value."""

    batch_size: int
    idle_wait_seconds: float
    max_batch_wait_seconds: float
    lease_seconds: float
    max_attempts: int
    retry_delays_seconds: tuple[float, ...]
    max_result_bytes: int
    analysis_budget: AnalysisBudget
    prompt_version: str
    result_schema_version: str
    policy_version: str
    validator_version: str
    provider_id: str
    model_id: str
    model_config_hash: str

    def __post_init__(self) -> None:
        _positive_int(self.batch_size, "worker_batch_size")
        _non_negative_seconds(self.idle_wait_seconds, "worker_idle_wait", positive=True)
        _non_negative_seconds(self.max_batch_wait_seconds, "worker_max_batch_wait")
        _non_negative_seconds(self.lease_seconds, "worker_lease", positive=True)
        _positive_int(self.max_attempts, "worker_max_attempts")
        _positive_int(self.max_result_bytes, "worker_max_result_bytes")
        delays = tuple(
            _non_negative_seconds(value, "worker_retry_delay")
            for value in self.retry_delays_seconds
        )
        if len(delays) != self.max_attempts - 1:
            raise MemoryValidationError("worker_retry_schedule_length_differs")
        if not isinstance(self.analysis_budget, AnalysisBudget):
            raise TypeError("analysis_budget must use AnalysisBudget")
        for value, name in (
            (self.prompt_version, "worker_prompt_version"),
            (self.result_schema_version, "worker_result_schema_version"),
            (self.policy_version, "worker_policy_version"),
            (self.validator_version, "worker_validator_version"),
            (self.provider_id, "worker_provider_id"),
            (self.model_id, "worker_model_id"),
        ):
            _identifier(value, name)
        if (
            not isinstance(self.model_config_hash, str)
            or len(self.model_config_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.model_config_hash)
        ):
            raise MemoryValidationError("worker_model_config_hash_invalid")
        object.__setattr__(self, "idle_wait_seconds", float(self.idle_wait_seconds))
        object.__setattr__(self, "max_batch_wait_seconds", float(self.max_batch_wait_seconds))
        object.__setattr__(self, "lease_seconds", float(self.lease_seconds))
        object.__setattr__(self, "retry_delays_seconds", delays)


@dataclass(frozen=True, slots=True)
class AnalysisBatchClaim:
    batch_id: str
    subject: str
    batch_key: str
    evidence_watermark: str
    job_ids: tuple[str, ...]
    lease_token: str
    lease_expires_at: float
    request: MemoryAnalysisRequest
    envelope: MemoryAnalysisResultEnvelope | None = None
    application: AnalysisApplication | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.batch_id, "analysis_batch_id"),
            (self.subject, "analysis_subject"),
            (self.batch_key, "analysis_batch_key"),
            (self.evidence_watermark, "analysis_evidence_watermark"),
            (self.lease_token, "analysis_lease_token"),
        ):
            _identifier(value, name)
        jobs = tuple(_identifier(item, "analysis_job_id") for item in self.job_ids)
        if not jobs or len(set(jobs)) != len(jobs):
            raise MemoryValidationError("analysis_job_ids_invalid")
        if not isinstance(self.request, MemoryAnalysisRequest):
            raise TypeError("request must use MemoryAnalysisRequest")
        if self.envelope is not None and not isinstance(
            self.envelope, MemoryAnalysisResultEnvelope
        ):
            raise TypeError("envelope must use MemoryAnalysisResultEnvelope")
        if self.application is not None and not isinstance(self.application, AnalysisApplication):
            raise TypeError("application must use AnalysisApplication")
        if self.application is not None and self.envelope is None:
            raise MemoryValidationError("analysis_application_requires_envelope")
        object.__setattr__(self, "job_ids", jobs)
        object.__setattr__(
            self,
            "lease_expires_at",
            _non_negative_seconds(self.lease_expires_at, "analysis_lease_expires_at"),
        )

    @property
    def result(self) -> MemoryAnalysisResult | None:
        return None if self.envelope is None else self.envelope.result


@dataclass(frozen=True, slots=True)
class AnalysisApplication:
    invocation_id: str
    turn_id: str
    receipt: MemoryAnalysisReceipt
    decisions: tuple[DecisionLedgerEntry, ...]
    reasoning_refs: tuple[PublicReasoningReference, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.invocation_id, "analysis_invocation_id")
        _identifier(self.turn_id, "analysis_turn_id")
        if not isinstance(self.receipt, MemoryAnalysisReceipt):
            raise TypeError("receipt must use MemoryAnalysisReceipt")
        decisions = tuple(self.decisions)
        reasoning = tuple(self.reasoning_refs)
        if not all(isinstance(item, DecisionLedgerEntry) for item in decisions):
            raise TypeError("decisions must contain DecisionLedgerEntry values")
        if not all(isinstance(item, PublicReasoningReference) for item in reasoning):
            raise TypeError("reasoning_refs must contain PublicReasoningReference values")
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "reasoning_refs", reasoning)


@dataclass(frozen=True, slots=True)
class RejectedAnalysisAudit:
    """Public-only metadata for a provider result that must not be persisted."""

    result_hash: str
    provider_response_id: str | None
    input_tokens: int
    output_tokens: int
    cost_microunits: int
    latency_ms: int
    delivery_receipt: MemoryAnalysisDeliveryReceipt | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.result_hash, str)
            or len(self.result_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.result_hash)
        ):
            raise MemoryValidationError("rejected_analysis_result_hash_invalid")
        if self.provider_response_id is not None:
            _identifier(self.provider_response_id, "rejected_analysis_provider_response_id")
        for name in ("input_tokens", "output_tokens", "cost_microunits", "latency_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MemoryValidationError(f"rejected_analysis_{name}_invalid")
        if self.delivery_receipt is not None:
            if not isinstance(self.delivery_receipt, MemoryAnalysisDeliveryReceipt):
                raise TypeError("delivery_receipt must use MemoryAnalysisDeliveryReceipt")
            if (
                self.delivery_receipt.result_hash != self.result_hash
                or self.delivery_receipt.provider_response_id != self.provider_response_id
            ):
                raise MemoryValidationError("rejected_analysis_delivery_lineage_differs")


def _rejected_result_audit(result: object, request_hash: str) -> RejectedAnalysisAudit:
    """Extract bounded public metadata without retaining an invalid result body."""

    if type(result) is MemoryAnalysisResult:
        typed_result = cast(MemoryAnalysisResult, result)
        canonical_result_hash = hashlib.sha256(
            canonical_json(typed_result.to_json()).encode()
        ).hexdigest()
        return RejectedAnalysisAudit(
            canonical_result_hash,
            typed_result.provider_response_id,
            typed_result.input_tokens,
            typed_result.output_tokens,
            typed_result.cost_microunits,
            typed_result.latency_ms,
        )
    result_type = f"{request_hash}:{type(result).__module__}.{type(result).__qualname__}"
    return RejectedAnalysisAudit(
        hashlib.sha256(result_type.encode()).hexdigest(),
        None,
        0,
        0,
        0,
        0,
    )


def _rejected_envelope_audit(
    envelope: MemoryAnalysisResultEnvelope,
) -> RejectedAnalysisAudit:
    """Retain only public metrics plus a previously authority-verified delivery receipt."""

    result = envelope.result
    return RejectedAnalysisAudit(
        result.result_hash,
        result.provider_response_id,
        result.input_tokens,
        result.output_tokens,
        result.cost_microunits,
        result.latency_ms,
        envelope.delivery_receipt,
    )


class AnalysisResultCommitOutcome(StrEnum):
    COMMITTED = "committed"
    REPLAYED = "replayed"
    DIVERGENT = "divergent"
    STALE_LEASE = "stale_lease"


class AnalysisDeliveryAuthorityTransientError(RuntimeError):
    """A Host delivery-authority outage that is safe to retry within job policy."""


class _AnalysisDeliveryAdmission:
    """Opaque in-process capability; repository identity registration is the authority."""

    __slots__ = ()


class _AnalysisDeliveryAuthorityRegistration:
    """Opaque registration proving the runner uses the repository-bound authority."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class AnalysisResultCommit:
    outcome: AnalysisResultCommitOutcome
    canonical_envelope: MemoryAnalysisResultEnvelope | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", AnalysisResultCommitOutcome(self.outcome))
        if self.canonical_envelope is not None and not isinstance(
            self.canonical_envelope, MemoryAnalysisResultEnvelope
        ):
            raise TypeError("canonical_envelope must use MemoryAnalysisResultEnvelope")

    @property
    def canonical_result(self) -> MemoryAnalysisResult | None:
        return None if self.canonical_envelope is None else self.canonical_envelope.result


class WorkerRunOutcome(StrEnum):
    IDLE = "idle"
    APPLIED = "applied"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTER = "dead_letter"
    STALE_LEASE = "stale_lease"


class DurableJobRepositoryPort(Protocol):
    async def claim_analysis_batch(
        self, config: MemoryJobWorkerConfig, worker_id: str
    ) -> AnalysisBatchClaim | None: ...

    def register_analysis_delivery_authority(
        self, authority: MemoryAnalysisDeliveryAuthorityPort
    ) -> _AnalysisDeliveryAuthorityRegistration: ...

    async def admit_analysis_delivery(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        registration: _AnalysisDeliveryAuthorityRegistration,
    ) -> _AnalysisDeliveryAdmission: ...

    async def discard_analysis_delivery_admission(
        self, admission: _AnalysisDeliveryAdmission
    ) -> None: ...

    async def commit_analysis_result(
        self,
        claim: AnalysisBatchClaim,
        envelope: MemoryAnalysisResultEnvelope,
        admission: _AnalysisDeliveryAdmission,
    ) -> AnalysisResultCommit: ...

    async def reject_analysis_result(
        self,
        claim: AnalysisBatchClaim,
        audit: RejectedAnalysisAudit,
        reason_code: str,
        validator_version: str,
        admission: _AnalysisDeliveryAdmission | None = None,
        retry_config: MemoryJobWorkerConfig | None = None,
    ) -> WorkerRunOutcome: ...

    async def prepare_analysis_application(
        self,
        claim: AnalysisBatchClaim,
        result: MemoryAnalysisResult,
        validator_version: str,
    ) -> AnalysisApplication | None: ...

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
    ) -> object: ...

    async def finalize_analysis_application(
        self, claim: AnalysisBatchClaim, application: AnalysisApplication
    ) -> bool: ...

    async def fail_analysis_batch(
        self,
        claim: AnalysisBatchClaim,
        reason_code: str,
        config: MemoryJobWorkerConfig,
    ) -> WorkerRunOutcome: ...


class DurableMemoryJobRunner:
    """Calls only the Host executor outside transactions; all state stays in the repository."""

    def __init__(
        self,
        repository: DurableJobRepositoryPort,
        executor: MemoryAnalysisExecutorPort,
        delivery_authority: MemoryAnalysisDeliveryAuthorityPort,
        config: MemoryJobWorkerConfig,
        worker_id: str,
        now: Callable[[], float],
    ) -> None:
        if not isinstance(config, MemoryJobWorkerConfig):
            raise TypeError("config must use MemoryJobWorkerConfig")
        _identifier(worker_id, "worker_id")
        self._repository = repository
        self._executor = executor
        self._delivery_authority = delivery_authority
        self._delivery_authority_registration = (
            repository.register_analysis_delivery_authority(delivery_authority)
        )
        self._config = config
        self._worker_id = worker_id
        self._now = now

    async def run_once(self) -> WorkerRunOutcome:
        claim = await self._repository.claim_analysis_batch(self._config, self._worker_id)
        if claim is None:
            return WorkerRunOutcome.IDLE
        envelope = claim.envelope
        result = claim.result
        application = claim.application
        admission: _AnalysisDeliveryAdmission | None = None
        if application is None:
            if envelope is None:
                try:
                    candidate = await self._executor.analyze_memory(claim.request)
                except asyncio.CancelledError:
                    raise
                except TimeoutError:
                    return await self._repository.fail_analysis_batch(
                        claim, "analysis_executor_timeout", self._config
                    )
                except Exception:
                    return await self._repository.fail_analysis_batch(
                        claim, "analysis_executor_failed", self._config
                    )
                if type(candidate) is not MemoryAnalysisResultEnvelope:
                    return await self._repository.reject_analysis_result(
                        claim,
                        _rejected_result_audit(candidate, claim.request.request_hash),
                        "analysis_envelope_type_invalid",
                        self._config.validator_version,
                    )
                envelope = cast(MemoryAnalysisResultEnvelope, candidate)
                try:
                    decoded_envelope = MemoryAnalysisResultEnvelope.from_json(
                        envelope.to_json()
                    )
                    envelope.verify_request(claim.request)
                    if (
                        decoded_envelope.envelope_hash != envelope.envelope_hash
                        or decoded_envelope.result.result_hash != envelope.result.result_hash
                        or decoded_envelope.delivery_receipt.receipt_hash
                        != envelope.delivery_receipt.receipt_hash
                    ):
                        raise MemoryValidationError("analysis_envelope_hash_differs")
                except (TypeError, ValueError, MemoryValidationError):
                    return await self._repository.reject_analysis_result(
                        claim, _rejected_result_audit(envelope, claim.request.request_hash),
                        "analysis_envelope_lineage_invalid",
                        self._config.validator_version,
                    )
            assert envelope is not None
            try:
                admission = await self._repository.admit_analysis_delivery(
                    claim, envelope, self._delivery_authority_registration
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                return await self._repository.reject_analysis_result(
                    claim,
                    _rejected_result_audit(envelope, claim.request.request_hash),
                    "analysis_delivery_authority_timeout",
                    self._config.validator_version,
                    retry_config=self._config,
                )
            except AnalysisDeliveryAuthorityTransientError:
                return await self._repository.reject_analysis_result(
                    claim,
                    _rejected_result_audit(envelope, claim.request.request_hash),
                    "analysis_delivery_authority_transient",
                    self._config.validator_version,
                    retry_config=self._config,
                )
            except (MemoryLimitError, MemoryValidationError):
                return await self._repository.reject_analysis_result(
                    claim,
                    _rejected_result_audit(envelope, claim.request.request_hash),
                    "analysis_delivery_public_metadata_invalid",
                    self._config.validator_version,
                )
            except Exception:
                return await self._repository.reject_analysis_result(
                    claim,
                    _rejected_result_audit(envelope, claim.request.request_hash),
                    "analysis_delivery_authority_rejected",
                    self._config.validator_version,
                )
        else:
            assert envelope is not None
            try:
                admission = await self._repository.admit_analysis_delivery(
                    claim, envelope, self._delivery_authority_registration
                )
            except asyncio.CancelledError:
                raise
            except (TimeoutError, AnalysisDeliveryAuthorityTransientError):
                return await self._repository.fail_analysis_batch(
                    claim, "analysis_delivery_replay_authority_transient", self._config
                )
            except Exception:
                return await self._repository.fail_analysis_batch(
                    claim, "analysis_delivery_replay_authority_rejected", self._config
                )
        assert admission is not None and envelope is not None
        try:
            if application is None:
                result = envelope.result
                try:
                    freeze_public_audit_object(result.structured_result)
                except (MemoryLimitError, MemoryValidationError):
                    return await self._repository.reject_analysis_result(
                        claim,
                        _rejected_envelope_audit(envelope),
                        "analysis_result_private_material",
                        self._config.validator_version,
                        admission,
                    )
                encoded = canonical_json(result.to_json()).encode()
                if len(encoded) > self._config.max_result_bytes:
                    return await self._repository.reject_analysis_result(
                        claim,
                        _rejected_envelope_audit(envelope),
                        "analysis_result_oversize",
                        self._config.validator_version,
                        admission,
                    )
                if claim.envelope is None:
                    commit = await self._repository.commit_analysis_result(
                        claim, envelope, admission
                    )
                    if commit.outcome in {
                        AnalysisResultCommitOutcome.STALE_LEASE,
                        AnalysisResultCommitOutcome.DIVERGENT,
                    }:
                        return WorkerRunOutcome.STALE_LEASE
                    if commit.canonical_envelope is None:
                        return WorkerRunOutcome.STALE_LEASE
                    envelope = commit.canonical_envelope
                    result = envelope.result
                application = await self._repository.prepare_analysis_application(
                    claim, result, self._config.validator_version
                )
                if application is None:
                    return WorkerRunOutcome.STALE_LEASE
            assert result is not None and application is not None
            await self._repository.record_memory_analysis(
                claim,
                envelope,
                admission,
                application.invocation_id,
                application.turn_id,
                claim.request,
                result,
                envelope.delivery_receipt,
                application.receipt,
                application.decisions,
                reasoning_refs=application.reasoning_refs,
            )
            finalized = await self._repository.finalize_analysis_application(
                claim, application
            )
            return WorkerRunOutcome.APPLIED if finalized else WorkerRunOutcome.STALE_LEASE
        finally:
            await self._repository.discard_analysis_delivery_admission(admission)

    async def run_until_stopped(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            outcome = await self.run_once()
            if outcome is WorkerRunOutcome.IDLE:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._config.idle_wait_seconds)
                except TimeoutError:
                    continue


__all__ = (
    "AnalysisApplication",
    "AnalysisBatchClaim",
    "AnalysisDeliveryAuthorityTransientError",
    "AnalysisResultCommit",
    "AnalysisResultCommitOutcome",
    "DurableJobRepositoryPort",
    "DurableMemoryJobRunner",
    "MemoryJobWorkerConfig",
    "RejectedAnalysisAudit",
    "WorkerRunOutcome",
)
