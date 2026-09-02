"""Disposable spike A2: Host-side composition drives DurableMemoryJobRunner
on the pinned Memory wheel (simple-harness-memory-sdk==0.6.0 / sdk==0.7.1).

Steps (1)-(6) per the assumption. Never fakes a pass: every step prints
observed values and raises on mismatch.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, cast

from simple_harness.contracts import JsonValue, canonical_json, fingerprint_json
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
    MemoryScopeRef,
    PrivacyClass,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveSignalAuthorityRef,
    ProspectiveSignalIntent,
    ProspectiveSignalKind,
    ProspectiveTimeTrigger,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    ValidTimeInterval,
    VerificationState,
    issue_prospective_signal_authority,
)
from simple_harness_memory import MemoryManager
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.jobs import (
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)
from simple_harness_memory.core.errors import MemoryOwnershipConflict
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.embedders.mock import HashEmbedder

SPIKE_DIR = Path(__file__).resolve().parent
SUBJECT = "deskpet-local-owner-v1"
NOW = time.time()
USER_TEXT = "从今以后每周五提醒我提交周报"
RESULTS: dict[str, tuple[str, str]] = {}


def record(step: str, ok: bool, detail: str, *, soft: bool = False) -> None:
    RESULTS[step] = ("PASS" if ok else "FAIL", detail)
    print(f"[{'PASS' if ok else 'FAIL'}] step {step}: {detail}")
    if not ok and not soft:
        raise AssertionError(f"step {step} failed: {detail}")


# ----------------------------------------------------------------- helpers ---
def _stable_id(namespace: str, *parts: str) -> str:
    payload = canonical_json(
        {"schema_version": 1, "namespace": namespace, "parts": list(parts)}
    )
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _principal() -> MemoryPrincipal:
    # Mirrors deskpet.memory.human_memory_v7.local_memory_principal
    return MemoryPrincipal(
        deployment_id="deskpet-local",
        household_id="deskpet-local-household",
        actor_id=SUBJECT,
        session_id="primary-conversation",
    )


def _placeholder_principal() -> MemoryPrincipal:
    # Ingestion/analysis paths insert principals(principal_id=dep=hh=actor=subject).
    return MemoryPrincipal(SUBJECT, SUBJECT, SUBJECT, "primary-conversation")


GOTCHAS: list[str] = []


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        run_id="run-1",
        subject=SUBJECT,
        recipient=DeliveryRecipient.USER_SELF,
        recipient_id=SUBJECT,
        intended_audience=IntendedAudience.USER_SELF,
        purpose=DisclosurePurpose.PERSONALIZATION,
        source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY,
        generation=DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _admitted() -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {"item_id": "message-1", "public_text": USER_TEXT}
    envelope = SanitizedEvidenceEnvelope(
        evidence_id="evidence-1",
        run_id="run-1",
        subject=SUBJECT,
        source_kind=EvidenceSourceKind.USER_MESSAGE,
        source_ref="turn-1/user",
        source_hash=hashlib.sha256(USER_TEXT.encode("utf-8")).hexdigest(),
        sanitized_payload=cast(dict, payload),
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(),
        evidence_refs=(),
    )
    receipt = SanitizedEvidenceReceipt(
        receipt_id="admission-1",
        run_id=envelope.run_id,
        subject=envelope.subject,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=envelope.disclosure_context,
        evidence_refs=envelope.evidence_refs,
        admitted_at=NOW - 120.0,
    )
    return envelope, receipt


def _span(envelope: SanitizedEvidenceEnvelope, receipt: SanitizedEvidenceReceipt) -> EvidenceSpanRef:
    text = cast(str, envelope.sanitized_payload["public_text"])
    return EvidenceSpanRef(
        span_id="span-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id="message-1",
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


def _prospective_operation(span: EvidenceSpanRef) -> MemoryMutationOperation:
    return MemoryMutationOperation(
        operation_id="create-prospective",
        kind=MemoryMutationKind.CREATE,
        memory_type=LongTermMemoryType.PROSPECTIVE,
        payload=ProspectiveMemoryPayload(
            "提交周报", ProspectiveTimeTrigger(NOW - 20.0, "Asia/Shanghai")
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


# ------------------------------------------------------ Host-side fakes ------
class HostDeliveryAuthority:
    """Implements simple_harness.runtime.MemoryAnalysisDeliveryAuthorityPort.

    MUST be the *same object* passed to build_human_memory_v7(analysis_delivery_authority=)
    and to DurableMemoryJobRunner(delivery_authority=) (wheel checks identity).
    """

    issuer_id = "deskpet-host-analysis-authority"

    def __init__(self) -> None:
        self.deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}
        self.verification_calls = 0

    def issue(self, request: MemoryAnalysisRequest, result: MemoryAnalysisResult) -> MemoryAnalysisResultEnvelope:
        provider_hash = hashlib.sha256(
            (result.provider_response_id or "provider-response-id-null").encode()
        ).hexdigest()
        delivery = MemoryAnalysisDeliveryReceipt(
            receipt_id=f"delivery-{request.job_id}-{request.attempt}",
            issuer_id=self.issuer_id,
            run_id=result.run_id,
            job_id=result.job_id,
            request_hash=result.request_hash,
            result_hash=result.result_hash,
            attempt=request.attempt,
            provider_response_id=result.provider_response_id,
            provider_response_hash=provider_hash,
            issued_at=time.time(),
            host_receipt_id=f"host-record-{request.job_id}-{request.attempt}",
            host_receipt_hash=hashlib.sha256(
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


class HostFakeExecutor:
    """Implements MemoryAnalysisExecutorPort.analyze_memory (fake LLM)."""

    def __init__(self, backend: Any, authority: HostDeliveryAuthority) -> None:
        self.backend = backend
        self.authority = authority
        self.calls = 0
        self.last_request: MemoryAnalysisRequest | None = None
        self.last_plan: MemoryMutationPlan | None = None

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        self.calls += 1
        self.last_request = request
        assert not self.backend.connection.in_transaction, "executor must run outside txn"
        spans: list[EvidenceSpanRef] = []
        for ref in request.ordered_evidence_refs:
            rec = await self.backend.read_ingested_evidence(ref.evidence_id)
            spans.append(_span(rec.envelope, rec.admission_receipt))
        plan = MemoryMutationPlan(
            plan_id="plan-1",
            run_id=request.run_id,
            turn_id=_stable_id("analysis-batch-turn", request.job_id),
            subject=request.subject,
            base_revision=1,
            outcome=MemoryMutationPlanOutcome.MUTATE,
            operations=(_prospective_operation(spans[0]),),
            disclosure_context=request.disclosure_context,
            evidence_refs=request.ordered_evidence_refs,
            idempotency_key=request.idempotency_key,
        )
        self.last_plan = plan
        result = MemoryAnalysisResult(
            job_id=request.job_id,
            run_id=request.run_id,
            request_hash=request.request_hash,
            provider_response_id="fake-provider-response-1",
            structured_result=plan.to_json(),
            input_tokens=100,
            output_tokens=50,
            cost_microunits=7,
            latency_ms=25,
        )
        return self.authority.issue(request, result)


class HostSeedAuthority:
    """evidence_authority + memory_action_authority + prospective_signal_authority."""

    def __init__(self, envelope, receipt, span) -> None:
        self._admitted = AdmittedEvidenceAuthority(
            envelope,
            receipt,
            EvidenceItemAuthority(
                schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
                authority_id="item-authority-1",
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
        self.signals: dict[str, object] = {}
        self.evidence_resolutions = 0
        self.signal_resolutions = 0

    async def resolve_admitted_evidence(self, span):
        self.evidence_resolutions += 1
        return self._admitted

    async def resolve_typed_observation(self, reference):
        raise ValueError("no typed observation is registered")

    async def resolve_memory_action_authority(self, reference):
        raise ValueError("no action authority is registered")

    async def resolve_prospective_signal_authority(self, reference):
        self.signal_resolutions += 1
        return self.signals[reference.authority_id]


def _grant(
    authority: HostSeedAuthority,
    *,
    memory_id: str,
    revision: int,
    kind: ProspectiveSignalKind,
    transition_from: ProspectiveLifecycleState,
    transition_to: ProspectiveLifecycleState,
    observed_at: float,
    signal_id: str,
    outbox_id: str | None = None,
    outbox_hash: str | None = None,
) -> ProspectiveSignalAuthorityRef:
    intent = ProspectiveSignalIntent(
        signal_id=signal_id,
        subject=SUBJECT,
        scope=MemoryScopeRef.personal(SUBJECT),
        target_memory_id=memory_id,
        target_revision=revision,
        signal_kind=kind,
        trigger=ProspectiveTimeTrigger(NOW - 20.0, "Asia/Shanghai"),
        scheduler_registration_ref="scheduler-registration-1",
        registration_revision=1,
        signal_receipt_id=f"receipt-{signal_id}",
        signal_receipt_hash=hashlib.sha256(signal_id.encode()).hexdigest(),
        observed_at=observed_at,
        transition_from=transition_from,
        transition_to=transition_to,
        outbox_id=outbox_id,
        outbox_payload_hash=outbox_hash,
        run_id="run-1",
        operation_id=f"operation-{signal_id}",
    )
    grant = issue_prospective_signal_authority(
        intent,
        authority_id=f"authority-{signal_id}",
        issued_at=NOW - 60.0,
        expires_at=NOW + 3600.0,
        nonce=f"nonce-{signal_id}",
        issuer_ref="host-prospective-signal:v1",
    )
    authority.signals[grant.authority_id] = grant
    return ProspectiveSignalAuthorityRef.from_authority(grant)


WORKER_CONFIG = MemoryJobWorkerConfig(
    batch_size=1,  # 1 job only; batch_size>1 would wait max_batch_wait_seconds
    idle_wait_seconds=0.01,
    max_batch_wait_seconds=0.0,
    lease_seconds=10.0,
    max_attempts=2,
    retry_delays_seconds=(1.0,),
    max_result_bytes=64 * 1024,
    analysis_budget=AnalysisBudget(4096, 1024, 30_000, 1_000_000),
    prompt_version="spike-prompt-v1",
    result_schema_version="spike-result-v1",
    policy_version="spike-policy-v1",
    validator_version="spike-validator-v1",
    provider_id="spike-provider",
    model_id="spike-model",
    model_config_hash="a" * 64,
)


async def _job_states(backend: Any) -> list[tuple[str, str, int]]:
    async with backend.connection.execute(
        "SELECT job_id,state,attempt_count FROM jobs ORDER BY job_id"
    ) as cursor:
        return [(str(r[0]), str(r[1]), int(r[2])) for r in await cursor.fetchall()]


async def _job_attempt_states(backend: Any) -> list[tuple[str, str]]:
    # `job_attempts` may not exist on this wheel; report whatever the schema has.
    async with backend.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%attempt%'"
    ) as cursor:
        tables = [str(r[0]) for r in await cursor.fetchall()]
    out: list[tuple[str, str]] = []
    for t in tables:
        async with backend.connection.execute(f"PRAGMA table_info({t})") as cursor:
            cols = [str(r[1]) for r in await cursor.fetchall()]
        col = "state" if "state" in cols else ("status" if "status" in cols else None)
        if col is None:
            out.append((t, f"<no state column: {cols}>"))
            continue
        async with backend.connection.execute(f"SELECT {col} FROM {t}") as cursor:
            out.extend((t, str(r[0])) for r in await cursor.fetchall())
    return out


async def main() -> int:
    db = SPIKE_DIR / f"spike_a2_{int(NOW)}.db"
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    seed = HostSeedAuthority(envelope, receipt, span)
    delivery_authority = HostDeliveryAuthority()

    # (1) build v7 via Host composition
    manager = await MemoryManager.build_human_memory_v7(
        db,
        analysis_delivery_authority=delivery_authority,
        evidence_authority=seed,
        memory_action_authority=seed,
        prospective_signal_authority=seed,
        classification_policy=InformationClassificationPolicy(
            policy_id="memory-classification-policy",
            policy_version="1",
            authority_ref="memory-policy-registry:classification/v1",
            required_privacy_class=PrivacyClass.PERSONAL,
            required_information_attributes=(),
        ),
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
    )
    backend = manager.backend
    record("1", backend is not None, f"built v7 manager; backend={type(backend).__name__}; db={db.name}")
    principal = _principal()
    scope = MemoryScope.personal(SUBJECT)
    try:
        # (2) ingest
        ingestion = await manager.ingest_committed_evidence(envelope, receipt)
        jobs = await _job_states(backend)
        host_principal = principal
        try:
            await manager.read_outbox(principal=host_principal, states=("pending",))
            print("  probe: Host deskpet-local principal ACCEPTED by read_outbox after ingest")
        except MemoryOwnershipConflict as exc:
            GOTCHAS.append(
                f"read_outbox with Host principal {host_principal!r} after ingest-only -> {exc} ; "
                "ingest inserts principals(dep=hh=actor=subject); only apply_memory_mutation_plan "
                "(caller-principal path) upgrades it. Using placeholder-identity principal instead."
            )
            print(f"  probe: Host principal rejected: {exc}; switching to placeholder principal")
            principal = _placeholder_principal()
        async with backend.connection.execute("SELECT principal_id,deployment_id,household_id,actor_id FROM principals") as cursor:
            print("  principals rows:", [tuple(r) for r in await cursor.fetchall()])
        outbox = await manager.read_outbox(principal=principal, states=("pending", "claimed", "applied", "dead_letter"))
        topics = [(e.topic, e.state) for e in outbox.entries]
        record(
            "2",
            len(jobs) == 1 and jobs[0][1] == "pending" and len(outbox.entries) == 1,
            f"ingestion_receipt={type(ingestion).__name__}; jobs={jobs}; outbox={topics}",
        )

        # (3) runner run_once -> applied
        executor = HostFakeExecutor(backend, delivery_authority)
        runner = DurableMemoryJobRunner(
            repository=backend,
            executor=executor,
            delivery_authority=delivery_authority,
            config=WORKER_CONFIG,
            worker_id="deskpet-worker-1",
            now=time.time,
        )
        outcome = await runner.run_once()
        jobs = await _job_states(backend)
        attempts = await _job_attempt_states(backend)
        async with backend.connection.execute(
            "SELECT invocation_id,output_reason_code,validation_receipt_json FROM llm_invocations"
        ) as cursor:
            inv = [(str(r[0])[:24], r[1], json.loads(str(r[2])).get("validation_status") if r[2] else None) for r in await cursor.fetchall()]
        record(
            "3",
            outcome is WorkerRunOutcome.APPLIED and all(j[1] == "applied" for j in jobs),
            f"outcome={outcome!s}; jobs={jobs}; attempt_tables={attempts}; executor.calls={executor.calls}; "
            f"authority.verification_calls={delivery_authority.verification_calls}; evidence_authority.resolve_admitted_evidence calls={seed.evidence_resolutions}; llm_invocations={inv}",
        )

        # (4a) as stated in A2: outbox after runner alone
        pending = await manager.read_outbox(principal=principal, states=("pending",))
        pending_topics = [(e.topic, e.state, e.outbox_id[:20]) for e in pending.entries]
        reg = [e for e in pending.entries if e.topic == "memory.prospective.registration.requested"]
        async with backend.connection.execute("SELECT COUNT(*) FROM cognitive_memory_heads") as cursor:
            heads_after_runner = int((await cursor.fetchone())[0])
        async with backend.connection.execute("SELECT batch_id,base_revision,committed_revision,plan_hash FROM accepted_analysis_plans") as cursor:
            accepted = [(str(r[0])[:30], r[1], r[2], str(r[3])[:16]) for r in await cursor.fetchall()]
        record(
            "4a",
            len(reg) == 1,
            f"runner-only: pending outbox={pending_topics}; cognitive_memory_heads={heads_after_runner}; accepted_analysis_plans={accepted}",
            soft=True,
        )
        if len(reg) != 1:
            GOTCHAS.append(
                "DurableMemoryJobRunner.run_once()==APPLIED only records accepted_analysis_plans + decision_records "
                "and marks the memory.mutation.requested outbox row 'applied'; it does NOT create cognitive_memory_heads "
                "nor emit memory.prospective.registration.requested. A separate caller-principal "
                "manager.apply_memory_mutation_plan(principal, scope, plan=<same plan>) is required (4b)."
            )
            # (4b) Host bridge: materialize the accepted plan through the mutation path
            assert executor.last_plan is not None
            apply_result = await manager.apply_memory_mutation_plan(
                principal=host_principal, scope=scope, plan=executor.last_plan
            )
            print(f"  4b apply_memory_mutation_plan -> outcome={apply_result.outcome!s} reason={getattr(apply_result, 'reason_code', None)}; evidence_authority.resolve_admitted_evidence calls now={seed.evidence_resolutions}")
            async with backend.connection.execute("SELECT principal_id,deployment_id,household_id,actor_id FROM principals") as cursor:
                print("  principals rows after 4b:", [tuple(r) for r in await cursor.fetchall()])
            try:
                pending = await manager.read_outbox(principal=host_principal, states=("pending",))
                principal = host_principal
                print("  4b: Host deskpet-local principal now ACCEPTED by read_outbox (row upgraded)")
            except MemoryOwnershipConflict as exc:
                print(f"  4b: Host principal still rejected: {exc}")
                pending = await manager.read_outbox(principal=principal, states=("pending",))
            pending_topics = [(e.topic, e.state, e.outbox_id[:20]) for e in pending.entries]
            reg = [e for e in pending.entries if e.topic == "memory.prospective.registration.requested"]
            async with backend.connection.execute(
                "SELECT cr.memory_id, cr.plan_hash, (SELECT COUNT(*) FROM accepted_analysis_plans ap WHERE ap.plan_hash=cr.plan_hash) "
                "FROM cognitive_memory_revisions cr"
            ) as cursor:
                lineage = [(str(r[0])[:16], str(r[1])[:16], int(r[2])) for r in await cursor.fetchall()]
            record(
                "4b",
                len(reg) == 1 and all(l[2] == 1 for l in lineage) and lineage,
                f"after Host apply_memory_mutation_plan: pending outbox={pending_topics}; "
                f"registration payload keys={sorted(reg[0].payload.keys()) if reg else None}; "
                f"cognitive_memory_revisions(memory_id,plan_hash,accepted_plan_hash_match)={lineage}",
            )

        # (5) second run_once idle, executor not called again
        outcome2 = await runner.run_once()
        record("5", outcome2 is WorkerRunOutcome.IDLE and executor.calls == 1, f"outcome2={outcome2!s}; executor.calls={executor.calls}")

        # (6) apply prospective signals -> occurrence inbox
        reg_entry = reg[0]
        payload = reg_entry.payload
        memory_id = str(payload.get("memory_id") or payload.get("target_memory_id") or "")
        if not memory_id:
            async with backend.connection.execute(
                "SELECT memory_id,current_revision FROM cognitive_memory_heads WHERE memory_type='prospective'"
            ) as cursor:
                row = await cursor.fetchone()
            memory_id = str(row[0])
        async with backend.connection.execute(
            "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?", (memory_id,)
        ) as cursor:
            row = await cursor.fetchone()
        revision = int(row[0])
        accepted = _grant(
            seed, memory_id=memory_id, revision=revision,
            kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
            transition_from=ProspectiveLifecycleState.PENDING,
            transition_to=ProspectiveLifecycleState.PENDING,
            observed_at=NOW - 30.0, signal_id="accepted-1",
            outbox_id=reg_entry.outbox_id, outbox_hash=reg_entry.payload_hash,
        )
        try:
            ack = await manager.apply_prospective_signal(principal=host_principal, scope=scope, reference=accepted)
            print("  probe: apply_prospective_signal ACCEPTED Host deskpet-local principal")
            signal_principal = host_principal
        except MemoryOwnershipConflict as exc:
            GOTCHAS.append(f"apply_prospective_signal with Host principal -> {exc}; using placeholder principal")
            print(f"  probe: apply_prospective_signal rejected Host principal: {exc}")
            signal_principal = principal
            ack = await manager.apply_prospective_signal(principal=signal_principal, scope=scope, reference=accepted)
        due = _grant(
            seed, memory_id=memory_id, revision=revision,
            kind=ProspectiveSignalKind.TIME_DUE,
            transition_from=ProspectiveLifecycleState.PENDING,
            transition_to=ProspectiveLifecycleState.TRIGGERED,
            observed_at=NOW - 20.0, signal_id="due-1",
        )
        applied = await manager.apply_prospective_signal(principal=signal_principal, scope=scope, reference=due)
        async with backend.connection.execute("SELECT principal_id,deployment_id,household_id,actor_id FROM principals") as cursor:
            print("  principals rows after signals:", [tuple(r) for r in await cursor.fetchall()])
        try:
            await manager.read_occurrence_inbox(principal=host_principal)
            print("  probe: read_occurrence_inbox ACCEPTED Host deskpet-local principal at end")
        except MemoryOwnershipConflict as exc:
            print(f"  probe: read_occurrence_inbox still rejects Host principal at end: {exc}")
        inbox = await manager.read_occurrence_inbox(principal=principal)
        entries = [(e.outcome, e.signal_kind, e.lifecycle_state, e.action_text, e.memory_id[:16]) for e in inbox.entries]
        matched = [e for e in inbox.entries if e.outcome == "matched"]
        after_outbox = await manager.read_outbox(principal=principal, states=("pending", "claimed", "applied", "dead_letter"))
        record(
            "6",
            len(matched) == 1 and matched[0].memory_id == memory_id and applied.lifecycle_state is ProspectiveLifecycleState.TRIGGERED,
            f"memory_id={memory_id[:16]}.. rev={revision}; ack=({ack.outcome!s},{ack.reason_code}); "
            f"due=({applied.outcome!s},{applied.lifecycle_state!s},{applied.reason_code}); inbox={entries}; "
            f"outbox_after={[(e.topic, e.state) for e in after_outbox.entries]}; signal_resolutions={seed.signal_resolutions}",
        )
    finally:
        await manager.close()
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        traceback.print_exc()
        code = 1
    print("\nGOTCHAS:")
    for g in GOTCHAS:
        print("  -", g)
    print("\nSUMMARY:")
    for k in ("1", "2", "3", "4a", "4b", "5", "6"):
        st, det = RESULTS.get(k, ("NOT-REACHED", ""))
        print(f"  step {k}: {st}")
    sys.exit(code)
