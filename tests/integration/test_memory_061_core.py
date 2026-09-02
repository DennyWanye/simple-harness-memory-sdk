"""Memory 0.6.1 核心（S5b Task 4a）：设计冻结 §8 六项的 oracle。"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, cast

import pytest
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    AdmittedEvidenceAuthority,
    AnalysisBudget,
    ConflictStatus,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EpistemicStatus,
    EvidenceActorRole,
    EvidenceItemAuthority,
    EvidenceProvenance,
    EvidenceReasonCode,
    EvidenceRef,
    EvidenceSourceKind,
    EvidenceSpanRef,
    EvidenceSupportKind,
    InformationAttribute,
    IntendedAudience,
    LongTermMemoryType,
    MemoryAnalysisDeliveryReceipt,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
    MemoryAnalysisResultEnvelope,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    MemoryMutationPlanOutcome,
    PrivacyClass,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveTimeTrigger,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    SemanticLifecycleState,
    SemanticMemoryPayload,
    ValidTimeInterval,
    VerificationState,
)

from simple_harness_memory import MemoryManager
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.jobs import (
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.embedders.mock import HashEmbedder

SUBJECT = "actor-1"
HOST_POLICIES = frozenset(
    {"credential-filter/v1", "host-public-turn/v1", "host-typed-ingress/v1"}
)


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure(run_id: str = "run-1") -> DisclosureContext:
    return DisclosureContext(
        run_id,
        SUBJECT,
        DeliveryRecipient.USER_SELF,
        SUBJECT,
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "host-authority",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _evidence(
    index: int,
    *,
    filter_policy: str = "credential-filter/v1",
    text: str | None = None,
    run_id: str = "run-1",
) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {
        "item_id": f"message-{index}",
        "public_text": text if text is not None else f"preference-{index}",
    }
    envelope = SanitizedEvidenceEnvelope(
        f"evidence-{index}",
        run_id,
        SUBJECT,
        EvidenceSourceKind.USER_MESSAGE,
        f"turn-{index}/user",
        f"{index % 10}" * 64,
        payload,
        _hash(payload),
        filter_policy,
        (),
        _disclosure(run_id),
        (EvidenceRef(f"source-event-{index}", f"{(index + 2) % 10}" * 64, 1),),
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


def _classification_policy() -> InformationClassificationPolicy:
    return InformationClassificationPolicy(
        policy_id="memory-classification-policy",
        policy_version="1",
        authority_ref="memory-policy-registry:classification/v1",
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(),
    )


async def _build(db_path: Path, **kwargs: Any) -> MemoryManager:
    fault_injector = kwargs.pop("fault_injector", None)
    now = kwargs.pop("now", None)
    if fault_injector is not None or now is not None:
        # builder 不暴露故障注入/时钟；直接构造 backend 走同一 initialize 路径。
        from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
        from simple_harness_memory.core.manager import _NullWorldModel

        backend = SQLiteHumanMemoryBackend(
            db_path,
            fault_injector=fault_injector,
            now=now if now is not None else time.time,
            classification_policy=_classification_policy(),
            short_horizon_embedder=HashEmbedder(32),
            **kwargs,
        )
        await backend.initialize()
        return MemoryManager(backend, _NullWorldModel())
    return await MemoryManager.build_human_memory_v7(
        db_path,
        classification_policy=_classification_policy(),
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
        **kwargs,
    )


async def _count(manager: MemoryManager, sql: str, params: tuple[object, ...] = ()) -> int:
    backend = cast(Any, manager.backend)
    async with backend.connection.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


async def _rows(
    manager: MemoryManager, sql: str, params: tuple[object, ...] = ()
) -> list[tuple[object, ...]]:
    backend = cast(Any, manager.backend)
    async with backend.connection.execute(sql, params) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


def _stable_id(namespace: str, *parts: str) -> str:
    payload = canonical_json({"schema_version": 1, "namespace": namespace, "parts": list(parts)})
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


WORKER_CONFIG = MemoryJobWorkerConfig(
    batch_size=1,
    idle_wait_seconds=0.01,
    max_batch_wait_seconds=0.0,
    lease_seconds=10.0,
    max_attempts=2,
    retry_delays_seconds=(1.0,),
    max_result_bytes=64 * 1024,
    analysis_budget=AnalysisBudget(4096, 1024, 30_000, 1_000_000),
    prompt_version="test-prompt-v1",
    result_schema_version="test-result-v1",
    policy_version="test-policy-v1",
    validator_version="test-validator-v1",
    provider_id="worker-provider",
    model_id="worker-model",
    model_config_hash="a" * 64,
)


def _span(
    envelope: SanitizedEvidenceEnvelope, receipt: SanitizedEvidenceReceipt, span_id: str
) -> EvidenceSpanRef:
    text = str(envelope.sanitized_payload["public_text"])
    return EvidenceSpanRef(
        span_id=span_id,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id=str(envelope.sanitized_payload["item_id"]),
        item_json_pointer="/public_text",
        start_byte=0,
        end_byte=len(text.encode("utf-8")),
        exact_quote=text,
        quote_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        source_hash=envelope.source_hash,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=EvidenceActorRole.USER,
        provenance=EvidenceProvenance.AUTHENTICATED_USER,
        support_kind=EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
        typed_observation=None,
    )


class _HostEvidenceAuthority:
    """Host 解析器：从仓储读回 envelope/receipt 并签发 item authority。"""

    def __init__(self) -> None:
        self.backend: Any = None
        self.resolutions = 0

    async def resolve_admitted_evidence(self, span: EvidenceSpanRef) -> AdmittedEvidenceAuthority:
        self.resolutions += 1
        record = await self.backend.read_ingested_evidence(span.evidence_id)
        return AdmittedEvidenceAuthority(
            record.envelope,
            record.admission_receipt,
            EvidenceItemAuthority(
                schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
                authority_id=f"item-authority-{span.evidence_id}",
                evidence_id=span.evidence_id,
                envelope_hash=span.envelope_hash,
                sanitized_hash=span.sanitized_hash,
                source_hash=span.source_hash,
                source_kind=span.source_kind,
                item_ordinal=span.item_ordinal,
                item_id=span.item_id,
                item_json_pointer=span.item_json_pointer,
                normalization_version=span.normalization_version,
                actor_role=span.actor_role,
                provenance=span.provenance,
                required_privacy_class=PrivacyClass.PERSONAL,
                required_information_attributes=(),
                classification_authority_ref="host-classification-1",
                issuer_ref="host-evidence-1",
            ),
        )

    async def resolve_typed_observation(self, reference: object) -> object:
        raise ValueError("no typed observation is registered")


class _HostExecutor:
    """Host executor + delivery authority（同一对象，builder 与 runner 共用）。"""

    issuer_id = "host-analysis-authority"

    def __init__(self, ops: tuple[dict[str, Any], ...], *, no_mutation: bool = False) -> None:
        self.backend: Any = None
        self.ops = ops
        self.no_mutation = no_mutation
        self.calls = 0
        self.verification_calls = 0
        self.plans: dict[str, MemoryMutationPlan] = {}
        self.requests: list[MemoryAnalysisRequest] = []
        self.deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    async def _operation(self, spec: dict[str, Any], ordinal: int) -> MemoryMutationOperation:
        record = await self.backend.read_ingested_evidence(spec["evidence_id"])
        span = _span(record.envelope, record.admission_receipt, f"span-{ordinal}")
        if spec.get("memory_type") == "prospective":
            return MemoryMutationOperation(
                operation_id=spec["operation_id"],
                kind=MemoryMutationKind.CREATE,
                memory_type=LongTermMemoryType.PROSPECTIVE,
                payload=ProspectiveMemoryPayload(
                    spec.get("action", "提交周报"),
                    ProspectiveTimeTrigger(time.time() + 3600.0, "Asia/Shanghai"),
                ),
                target=None,
                depends_on_operation_ids=(),
                lifecycle_state=ProspectiveLifecycleState.PENDING,
                epistemic_status=EpistemicStatus.EXPLICIT_USER,
                conflict_status=ConflictStatus.UNCONTESTED,
                verification_state=VerificationState.SOURCE_BOUND,
                valid_time_interval=ValidTimeInterval(None, None),
                proposed_privacy_class=PrivacyClass.PERSONAL,
                proposed_information_attributes=(InformationAttribute.GOAL,),
                evidence_spans=(span,),
                reason_code="explicit_future_action",
            )
        return MemoryMutationOperation(
            operation_id=spec["operation_id"],
            kind=MemoryMutationKind.CREATE,
            memory_type=LongTermMemoryType.SEMANTIC,
            payload=SemanticMemoryPayload(
                subject_entity="user:self",
                predicate=spec.get("predicate", f"predicate-{ordinal}"),
                object_value=spec.get("object_value", f"value-{ordinal}"),
                qualifiers=(),
            ),
            target=None,
            depends_on_operation_ids=(),
            lifecycle_state=SemanticLifecycleState.ACTIVE,
            epistemic_status=EpistemicStatus.EXPLICIT_USER,
            conflict_status=ConflictStatus.UNCONTESTED,
            verification_state=VerificationState.SOURCE_BOUND,
            valid_time_interval=ValidTimeInterval(None, None),
            proposed_privacy_class=PrivacyClass.PERSONAL,
            proposed_information_attributes=(InformationAttribute.PREFERENCE,),
            evidence_spans=(span,),
            reason_code="explicit_user_preference",
        )

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        self.calls += 1
        self.requests.append(request)
        durable = self.deliveries.get((request.request_hash, request.attempt))
        if durable is not None:
            return durable
        assert not self.backend.connection.in_transaction
        structured: dict[str, JsonValue]
        if self.no_mutation:
            structured = {"outcome": "no_mutation", "operations": []}
        else:
            operations = tuple(
                [await self._operation(spec, index) for index, spec in enumerate(self.ops, 1)]
            )
            async with self.backend.connection.execute(
                "SELECT revision FROM analysis_apply_heads WHERE principal_id=?",
                (request.subject,),
            ) as cursor:
                head = await cursor.fetchone()
            plan = MemoryMutationPlan(
                plan_id=f"plan-{request.job_id[-12:]}",
                run_id=request.run_id,
                turn_id=_stable_id("analysis-batch-turn", request.job_id),
                subject=request.subject,
                base_revision=1 if head is None else int(head[0]),
                outcome=MemoryMutationPlanOutcome.MUTATE,
                operations=operations,
                disclosure_context=request.disclosure_context,
                evidence_refs=request.ordered_evidence_refs,
                idempotency_key=request.idempotency_key,
            )
            self.plans[request.job_id] = plan
            structured = plan.to_json()
        result = MemoryAnalysisResult(
            request.job_id,
            request.run_id,
            request.request_hash,
            f"provider-{request.job_id[-8:]}",
            structured,
            100,
            50,
            7,
            25,
        )
        provider_hash = hashlib.sha256(str(result.provider_response_id).encode()).hexdigest()
        delivery = MemoryAnalysisDeliveryReceipt(
            f"delivery-{request.job_id}-{request.attempt}",
            self.issuer_id,
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
        envelope = MemoryAnalysisResultEnvelope(result, delivery)
        self.deliveries[(request.request_hash, request.attempt)] = envelope
        return envelope

    async def verify_analysis_delivery(
        self, request: MemoryAnalysisRequest, envelope: MemoryAnalysisResultEnvelope
    ) -> None:
        self.verification_calls += 1
        envelope.verify_request(request)
        if envelope.delivery_receipt.issuer_id != self.issuer_id:
            raise ValueError("analysis delivery issuer differs")
        if self.deliveries.get((request.request_hash, request.attempt)) != envelope:
            raise ValueError("durable Host analysis delivery differs")


async def _build_pipeline(
    db_path: Path,
    executor: _HostExecutor,
    *,
    evidence_authority: _HostEvidenceAuthority | None = None,
    **kwargs: Any,
) -> tuple[MemoryManager, DurableMemoryJobRunner]:
    now = kwargs.get("now") or time.time
    manager = await _build(
        db_path,
        analysis_delivery_authority=executor,
        evidence_authority=evidence_authority,
        **kwargs,
    )
    executor.backend = manager.backend
    if evidence_authority is not None:
        evidence_authority.backend = manager.backend
    runner = DurableMemoryJobRunner(
        cast(Any, manager.backend), executor, executor, WORKER_CONFIG, "worker-1", now
    )
    return manager, runner


def _semantic_ops(
    *operation_ids: str, evidence_id: str = "evidence-1"
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"operation_id": operation_id, "evidence_id": evidence_id, "predicate": f"p-{index}"}
        for index, operation_id in enumerate(operation_ids, 1)
    )


# --------------------------------------------------------------------------- §8.1


@pytest.mark.asyncio
async def test_builder_passes_supported_filter_policies_to_backend(tmp_path: Path) -> None:
    manager = await _build(tmp_path / "policies.db", supported_filter_policies=HOST_POLICIES)
    try:
        receipt = await manager.ingest_committed_evidence(
            *_evidence(1, filter_policy="host-public-turn/v1")
        )
        assert receipt.evidence_id == "evidence-1"
        typed = await manager.ingest_committed_evidence(
            *_evidence(2, filter_policy="host-typed-ingress/v1")
        )
        assert typed.evidence_id == "evidence-2"
        assert await _count(manager, "SELECT COUNT(*) FROM evidence_envelopes") == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_builder_default_still_rejects_host_filter_policies(tmp_path: Path) -> None:
    manager = await _build(tmp_path / "default-policies.db")
    try:
        with pytest.raises(MemoryValidationError, match="evidence_filter_policy_unsupported"):
            await manager.ingest_committed_evidence(
                *_evidence(1, filter_policy="host-public-turn/v1")
            )
        accepted = await manager.ingest_committed_evidence(*_evidence(2))
        assert accepted.evidence_id == "evidence-2"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_builder_rejects_blank_filter_policy_set(tmp_path: Path) -> None:
    with pytest.raises(MemoryValidationError):
        await _build(tmp_path / "blank-policies.db", supported_filter_policies=frozenset({" "}))


# --------------------------------------------------------------------------- §8.2


MULTIOP_CASES: tuple[tuple[str, ...], ...] = (
    ("remember-location-hangzhou-binjiang", "remember-python-backend"),
    ("op-b", "op-a"),
    ("op-a", "op-b"),
    ("op-1",),
    ("zz", "aa", "mm"),
    ("op-3", "op-1", "op-2"),
)


def _hash_order_differs(batch_hint: str, operation_ids: tuple[str, ...]) -> bool:
    """plan.operations 规范序（无依赖时按 operation_id 排序）≠ decision_id hash 序。"""

    canonical = sorted(operation_ids)
    decision_ids = [_stable_id("analysis-decision", batch_hint, item) for item in canonical]
    return decision_ids != sorted(decision_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation_ids", list(MULTIOP_CASES))
async def test_multi_operation_plan_finalizes_regardless_of_decision_hash_order(
    tmp_path: Path, operation_ids: tuple[str, ...]
) -> None:
    executor = _HostExecutor(_semantic_ops(*operation_ids))
    manager, runner = await _build_pipeline(
        tmp_path / f"multiop-{len(operation_ids)}.db", executor
    )
    try:
        await manager.ingest_committed_evidence(*_evidence(1))
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        assert await runner.run_once() is WorkerRunOutcome.IDLE
        assert executor.calls == 1
        assert await _rows(manager, "SELECT state FROM jobs") == [("applied",)]
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [("applied",)]
        decisions = await _rows(
            manager, "SELECT operation_id FROM decision_records ORDER BY decision_id"
        )
        assert sorted(str(item[0]) for item in decisions) == sorted(operation_ids)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_spike_multiop_cases_include_a_hash_order_inversion(tmp_path: Path) -> None:
    """守卫：参数化 case 中至少一个 hash 序 ≠ plan 序，否则 oracle 退化为单序。"""

    executor = _HostExecutor(_semantic_ops("op-a", "op-b"))
    manager, runner = await _build_pipeline(tmp_path / "multiop-guard.db", executor)
    try:
        await manager.ingest_committed_evidence(*_evidence(1))
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        batch_id = str((await _rows(manager, "SELECT batch_id FROM analysis_batches"))[0][0])
        # batch_id 由 subject/batch_key/成员 job id 稳定派生，与 operation_id 无关，
        # 因此同一 DB 形状下每个 case 的 hash 序是确定的。
        assert any(_hash_order_differs(batch_id, case) for case in MULTIOP_CASES)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_multi_operation_finalize_boundary_replays_with_canonical_order(
    tmp_path: Path,
) -> None:
    """record 已落盘、finalize 提交前崩溃：reopen 后按规范序比较，无第二次 provider 调用。"""

    path = tmp_path / "multiop-finalize-boundary.db"
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.finalize.before_commit" and not fired:
            fired = True
            raise RuntimeError("multi-op finalize boundary")

    clock = [20.0]
    executor = _HostExecutor(_semantic_ops("zz", "aa", "mm"))
    manager, runner = await _build_pipeline(
        path, executor, fault_injector=fault, now=lambda: clock[0]
    )
    try:
        await manager.ingest_committed_evidence(*_evidence(1))
        with pytest.raises(RuntimeError, match="multi-op finalize boundary"):
            await runner.run_once()
    finally:
        await manager.close()

    clock[0] = 31.0  # lease_seconds=10 已过期，新 worker 可回收
    replay = _HostExecutor(_semantic_ops("zz", "aa", "mm"))
    replay.deliveries = executor.deliveries
    manager, runner = await _build_pipeline(path, replay, now=lambda: clock[0])
    try:
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        assert replay.calls == 0
        assert await runner.run_once() is WorkerRunOutcome.IDLE
        assert await _count(manager, "SELECT COUNT(*) FROM decision_records") == 3
        assert await _rows(manager, "SELECT state FROM analysis_batches") == [("applied",)]
    finally:
        await manager.close()
