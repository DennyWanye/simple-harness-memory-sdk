"""Disposable spike (cluster-value-milestone-boundary): the unproven last hop.

Real provider (A1 adapter recipe) -> model-fillable MemoryMutationPlan *proposal*
(memory type, payload fields, exact_quote + evidence item id; no hashes/offsets)
-> deterministic Host-side EvidenceSpanRef derivation -> real MemoryMutationPlan
-> exact Memory 0.6.0 validator via DurableMemoryJobRunner (prepare_analysis_application)
-> then apply_memory_mutation_plan (true span verification + materialization).
API key is never printed."""
from __future__ import annotations
import asyncio, hashlib, json, sys, time, traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
import httpx
from simple_harness import thaw_json
from simple_harness.contracts import JsonValue, canonical_json, fingerprint_json
from simple_harness.contracts.identity import RequestId
from simple_harness.contracts.messages import Message, MessageRole
from simple_harness.providers.base import ProviderRequest, ProviderToolSpec, CancelToken
from simple_harness.runtime import (
    EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION, EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    AdmittedEvidenceAuthority, AnalysisBudget, ConflictStatus, DeliveryRecipient, DisclosureContext,
    DisclosureGeneration, DisclosurePurpose, DisclosureReasonCode, DisclosureSource, DisclosureTrust,
    EpistemicStatus, EvidenceActorRole, EvidenceItemAuthority, EvidenceProvenance, EvidenceReasonCode,
    EvidenceSourceKind, EvidenceSpanRef, EvidenceSupportKind, InformationAttribute, IntendedAudience,
    LongTermMemoryType, MemoryAnalysisDeliveryReceipt, MemoryAnalysisRequest, MemoryAnalysisResult,
    MemoryAnalysisResultEnvelope, MemoryMutationKind, MemoryMutationOperation, MemoryMutationPlan,
    MemoryMutationPlanOutcome, PrivacyClass, ProspectiveLifecycleState, ProspectiveMemoryPayload,
    ProspectiveTimeTrigger, SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt, SemanticLifecycleState,
    SemanticMemoryPayload, ValidTimeInterval, VerificationState,
)
from deskpet.sdk_adapters.provider import ProductProviderAdapter
from simple_harness_memory import MemoryManager
from simple_harness_memory.core.errors import MemoryValidationError, MemoryOwnershipConflict
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.jobs import DurableMemoryJobRunner, MemoryJobWorkerConfig, WorkerRunOutcome
from simple_harness_memory.core.mutations import InformationClassificationPolicy, compile_memory_mutation_plan
from simple_harness_memory.embedders.mock import HashEmbedder

SPIKE_DIR = Path(__file__).resolve().parent
RUNTIME = json.loads((Path.home() / "Library/Application Support/com.dennywanye.simpleharness/llm_runtime.json").read_text())
SUBJECT = "deskpet-local-owner-v1"
NOW = time.time()
TURNS = [  # Host-like sanitized turn payloads: key is `text` (human_memory_service.py:786-790)
    ("dk-turn-0001", "从今以后每周五提醒我提交周报"),
    ("dk-turn-0002", "我住在杭州滨江，平时主要用 Python 写后端服务。"),
]
if "--only-first" in sys.argv: TURNS = TURNS[:1]
N_TURNS = len(TURNS)
RESULTS: dict[str, tuple[str, str]] = {}
FACTS: list[str] = []
def record(step: str, ok: bool, detail: str) -> None:
    RESULTS[step] = ("PASS" if ok else "FAIL", detail)
    print(f"[{'PASS' if ok else 'FAIL'}] {step}: {detail}", flush=True)
def _stable_id(namespace: str, *parts: str) -> str:
    payload = canonical_json({"schema_version": 1, "namespace": namespace, "parts": list(parts)})
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

class Registry:  # spike stand-in for LLMProviderRegistry (same Protocol as A1)
    def get_entry(self, provider_id):
        return SimpleNamespace(enabled=True, model=RUNTIME["model"], models=(), base_url=RUNTIME["base_url"], config_revision=1, incarnation_id="spike-inc")
    def resolve_api_key(self, provider_id):
        return RUNTIME["api_key"]

# ---- model-fillable proposal schema (no hashes / offsets / receipts) ----
TOOL = ProviderToolSpec(
    name="memory_mutation_propose",
    description="Propose long-term memory mutations grounded ONLY in the provided evidence items. Every operation must cite one evidence_item_id and an exact_quote that is a verbatim substring of that item's text. Use memory_type=prospective for future reminders/intentions, semantic for stable facts about the user. If nothing is worth remembering, return outcome=no_mutation with empty operations.",
    parameters={"type": "object", "additionalProperties": False, "required": ["outcome", "operations"],
        "properties": {
            "outcome": {"type": "string", "enum": ["mutate", "no_mutation"]},
            "operations": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["operation_id", "memory_type", "evidence_item_id", "exact_quote", "reason_code"],
                "properties": {
                    "operation_id": {"type": "string"},
                    "memory_type": {"type": "string", "enum": ["semantic", "prospective"]},
                    "semantic": {"type": "object", "additionalProperties": False, "required": ["subject_entity", "predicate", "object_value"],
                        "properties": {"subject_entity": {"type": "string"}, "predicate": {"type": "string"}, "object_value": {"type": "string"}}},
                    "prospective": {"type": "object", "additionalProperties": False, "required": ["action", "trigger_at_iso", "timezone"],
                        "properties": {"action": {"type": "string"}, "trigger_at_iso": {"type": "string", "description": "ISO-8601 with offset, the FIRST due time"}, "timezone": {"type": "string", "description": "IANA tz e.g. Asia/Shanghai"}}},
                    "evidence_item_id": {"type": "string"},
                    "exact_quote": {"type": "string", "description": "verbatim substring copied from the evidence text"},
                    "reason_code": {"type": "string"}}}}}})
SYSTEM = ("你是桌面工作台的主模型，正在做 post-turn 记忆分析。只根据给定证据项提出长期记忆变更；"
          "每条 operation 必须引用 evidence_item_id 并给出 exact_quote（必须是该证据 text 的逐字子串，不得改写）。"
          "未来意图/提醒用 prospective（给出首次到期的 ISO 时间和 IANA 时区），稳定事实用 semantic。只调用 memory_mutation_propose 一次，不要输出其他内容。")

def _disclosure(run_id: str) -> DisclosureContext:
    return DisclosureContext(run_id=run_id, subject=SUBJECT, recipient=DeliveryRecipient.USER_SELF, recipient_id=SUBJECT,
        intended_audience=IntendedAudience.USER_SELF, purpose=DisclosurePurpose.TASK_EXECUTION, source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY, generation=DisclosureGeneration.CURRENT, authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,))

def host_turn_envelope(delivery_key: str, text: str, *, policy: str, run_id: str):
    """Mirror human_memory_service.enqueue_turn (:786-848): payload keys schema_version/delivery_key/text."""
    payload: dict[str, JsonValue] = {"schema_version": 1, "delivery_key": delivery_key, "text": text}
    payload_hash = fingerprint_json(payload)
    evidence_id = f"evidence-{delivery_key}"
    disclosure = _disclosure(run_id)
    envelope = SanitizedEvidenceEnvelope(evidence_id=evidence_id, run_id=run_id, subject=SUBJECT, source_kind=EvidenceSourceKind.USER_MESSAGE,
        source_ref=f"foreground-turn:{delivery_key}", source_hash=payload_hash, sanitized_payload=cast(dict, payload), sanitized_hash=payload_hash,
        filter_policy_version=policy, removed_spans=(), disclosure_context=disclosure, evidence_refs=())
    receipt = SanitizedEvidenceReceipt(receipt_id=f"admission-{delivery_key}", run_id=run_id, subject=SUBJECT, evidence_id=evidence_id,
        envelope_hash=envelope.envelope_hash, source_hash=payload_hash, sanitized_hash=payload_hash, filter_policy_version=policy, accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,), disclosure_context=disclosure, evidence_refs=(), admitted_at=NOW - 120.0)
    return envelope, receipt

# ---- deterministic Host-side span derivation (the missing layer) ----
def item_id_for(envelope: SanitizedEvidenceEnvelope) -> str:
    return str(envelope.sanitized_payload["delivery_key"])

def derive_span(envelope: SanitizedEvidenceEnvelope, receipt: SanitizedEvidenceReceipt, exact_quote: str, span_id: str) -> EvidenceSpanRef:
    text = cast(str, envelope.sanitized_payload["text"])
    idx = text.find(exact_quote)
    if not exact_quote or idx < 0:
        raise ValueError("quote_not_verbatim")
    start = len(text[:idx].encode("utf-8"))
    end = start + len(exact_quote.encode("utf-8"))
    return EvidenceSpanRef(span_id=span_id, evidence_id=envelope.evidence_id, envelope_hash=envelope.envelope_hash, sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id, admission_receipt_hash=receipt.receipt_hash, source_kind=envelope.source_kind, item_ordinal=1,
        item_id=item_id_for(envelope), item_json_pointer="/text", start_byte=start, end_byte=end, exact_quote=exact_quote,
        quote_hash=hashlib.sha256(exact_quote.encode("utf-8")).hexdigest(), source_hash=envelope.source_hash,
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1, actor_role=EvidenceActorRole.USER,
        provenance=EvidenceProvenance.AUTHENTICATED_USER, support_kind=EvidenceSupportKind.EXPLICIT_USER_ASSERTION, typed_observation=None)

def compile_operation(proposal: dict, span: EvidenceSpanRef) -> MemoryMutationOperation:
    mt = proposal["memory_type"]
    if mt == "prospective":
        p = proposal.get("prospective") or {}
        at = datetime.fromisoformat(str(p["trigger_at_iso"])).timestamp()
        payload: Any = ProspectiveMemoryPayload(str(p["action"]), ProspectiveTimeTrigger(at, str(p["timezone"])))
        lifecycle: Any = ProspectiveLifecycleState.PENDING
        attrs = (InformationAttribute.GOAL,)
        memory_type = LongTermMemoryType.PROSPECTIVE
    elif mt == "semantic":
        s = proposal.get("semantic") or {}
        payload = SemanticMemoryPayload(str(s["subject_entity"]), str(s["predicate"]), str(s["object_value"]), ())
        lifecycle = SemanticLifecycleState.ACTIVE
        attrs = ()
        memory_type = LongTermMemoryType.SEMANTIC
    else:
        raise ValueError(f"unsupported memory_type {mt}")
    return MemoryMutationOperation(operation_id=str(proposal["operation_id"]), kind=MemoryMutationKind.CREATE, memory_type=memory_type,
        payload=payload, target=None, depends_on_operation_ids=(), lifecycle_state=lifecycle, epistemic_status=EpistemicStatus.EXPLICIT_USER,
        conflict_status=ConflictStatus.UNCONTESTED, verification_state=VerificationState.SOURCE_BOUND, valid_time_interval=ValidTimeInterval(None, None),
        proposed_privacy_class=PrivacyClass.PERSONAL, proposed_information_attributes=attrs, evidence_spans=(span,),
        reason_code=str(proposal.get("reason_code") or "explicit_user_statement"))

# ---- Host authorities ----
class HostDeliveryAuthority:
    issuer_id = "deskpet-host-analysis-authority"
    def __init__(self) -> None:
        self.deliveries: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}
        self.verification_calls = 0
    def issue(self, request: MemoryAnalysisRequest, result: MemoryAnalysisResult) -> MemoryAnalysisResultEnvelope:
        prh = hashlib.sha256((result.provider_response_id or "provider-response-id-null").encode()).hexdigest()
        delivery = MemoryAnalysisDeliveryReceipt(receipt_id=f"delivery-{request.job_id}-{request.attempt}", issuer_id=self.issuer_id, run_id=result.run_id,
            job_id=result.job_id, request_hash=result.request_hash, result_hash=result.result_hash, attempt=request.attempt,
            provider_response_id=result.provider_response_id, provider_response_hash=prh, issued_at=time.time(),
            host_receipt_id=f"host-record-{request.job_id}-{request.attempt}",
            host_receipt_hash=hashlib.sha256(f"{request.request_hash}:{result.result_hash}:{request.attempt}".encode()).hexdigest())
        env = MemoryAnalysisResultEnvelope(result, delivery)
        self.deliveries[(request.request_hash, request.attempt)] = env
        return env
    async def verify_analysis_delivery(self, request, envelope) -> None:
        self.verification_calls += 1
        envelope.verify_request(request)
        if envelope.delivery_receipt.issuer_id != self.issuer_id or self.deliveries.get((request.request_hash, request.attempt)) != envelope:
            raise ValueError("durable Host analysis delivery differs")

class HostEvidenceAuthority:
    """evidence_authority: resolve spans against the ingested envelope/receipt (Host rule = same derivation)."""
    def __init__(self, backend: Any) -> None:
        self.backend = backend; self.resolutions = 0; self.cache: dict[str, tuple[Any, Any]] = {}  # Host-side durable envelope/receipt (state.db analogue)
    async def resolve_admitted_evidence(self, span):
        self.resolutions += 1
        # NOTE: must NOT read through the Memory backend: resolver runs inside apply's BEGIN IMMEDIATE/_write_lock (deadlock observed: TimeoutError in spike_multiop_finalize.py)
        env, rcpt = self.cache[span.evidence_id]
        return AdmittedEvidenceAuthority(env, rcpt, EvidenceItemAuthority(schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
            authority_id=f"item-authority-{env.evidence_id}", evidence_id=env.evidence_id, envelope_hash=env.envelope_hash, sanitized_hash=env.sanitized_hash,
            source_hash=env.source_hash, source_kind=env.source_kind, item_ordinal=1, item_id=item_id_for(env), item_json_pointer="/text",
            normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1, actor_role=EvidenceActorRole.USER, provenance=EvidenceProvenance.AUTHENTICATED_USER,
            required_privacy_class=PrivacyClass.PERSONAL, required_information_attributes=(), classification_authority_ref="host-classification-1", issuer_ref="host-evidence-1"))
    async def resolve_typed_observation(self, reference): raise ValueError("none")
    async def resolve_memory_action_authority(self, reference): raise ValueError("none")
    async def resolve_prospective_signal_authority(self, reference): raise ValueError("none")

class HostRealExecutor:
    """MemoryAnalysisExecutorPort over the REAL provider through ProductProviderAdapter."""
    def __init__(self, backend, authority: HostDeliveryAuthority, adapter: ProductProviderAdapter) -> None:
        self.backend, self.authority, self.adapter = backend, authority, adapter
        self.calls = 0; self.plans: dict[str, MemoryMutationPlan] = {}; self.raw: list[dict] = []; self.derivation_failures: list[str] = []
    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResultEnvelope:
        self.calls += 1
        assert not self.backend.connection.in_transaction
        items = []
        admitted: dict[str, tuple[Any, Any]] = {}
        for ref in request.ordered_evidence_refs:
            rec = await self.backend.read_ingested_evidence(ref.evidence_id)
            admitted[item_id_for(rec.envelope)] = (rec.envelope, rec.admission_receipt)
            items.append({"evidence_item_id": item_id_for(rec.envelope), "text": rec.envelope.sanitized_payload["text"]})
        req = ProviderRequest(request_id=RequestId(f"spike-value-{request.job_id[-12:]}-{request.attempt}"),
            messages=(Message(role=MessageRole.SYSTEM, content=SYSTEM),
                      Message(role=MessageRole.USER, content="[analysis evidence]\n" + json.dumps({"now_iso": datetime.now().astimezone().isoformat(timespec='seconds'), "evidence_items": items}, ensure_ascii=False, indent=1))),
            tools=(TOOL,), max_output_tokens=800)
        t0 = time.monotonic()
        resp = await self.adapter.invoke(req, cancel=CancelToken())
        print(f"  provider: elapsed={time.monotonic()-t0:.1f}s finish={resp.finish_reason} model={resp.model} usage={resp.usage} tool_calls={len(resp.tool_calls)} text={resp.message.content!r:.80}", flush=True)
        proposal = None
        for call in resp.tool_calls:
            args = thaw_json(call.arguments)
            print("  raw tool call:", json.dumps({"name": call.name, "arguments": args}, ensure_ascii=False), flush=True)
            if call.name == "memory_mutation_propose": proposal = args
        self.raw.append({"job_id": request.job_id, "proposal": proposal})
        operations: list[MemoryMutationOperation] = []
        if proposal and proposal.get("outcome") == "mutate":
            for i, op in enumerate(proposal.get("operations", []), start=1):
                try:
                    env, rcpt = admitted[str(op["evidence_item_id"])]
                    span = derive_span(env, rcpt, str(op["exact_quote"]), span_id=f"span-{request.job_id[-8:]}-{i}")
                    operations.append(compile_operation(op, span))
                except Exception as exc:  # noqa: BLE001
                    self.derivation_failures.append(f"{request.job_id[-8:]}/op{i}: {type(exc).__name__}: {exc}")
        async with self.backend.connection.execute("SELECT revision FROM analysis_apply_heads WHERE principal_id=?", (request.subject,)) as c:
            row = await c.fetchone()
        base_revision = int(row[0]) if row else 1  # GAP: MemoryAnalysisRequest carries no base_revision; no port API exposes analysis_apply_heads
        print(f"  base_revision from analysis_apply_heads (raw SQL) = {base_revision}", flush=True)
        if operations:
            plan = MemoryMutationPlan(plan_id=f"plan-{request.job_id[-12:]}", run_id=request.run_id, turn_id=_stable_id("analysis-batch-turn", request.job_id),
                subject=request.subject, base_revision=base_revision, outcome=MemoryMutationPlanOutcome.MUTATE, operations=tuple(operations),
                disclosure_context=request.disclosure_context, evidence_refs=request.ordered_evidence_refs, idempotency_key=request.idempotency_key)
            compiled = compile_memory_mutation_plan(plan)  # early Memory-side compile (no authority)
            print(f"  compile_memory_mutation_plan: {len(compiled.operations)} ops OK", flush=True)
            self.plans[request.job_id] = plan
            structured = plan.to_json()
        else:
            structured = {"outcome": "no_mutation", "operations": []}
        result = MemoryAnalysisResult(job_id=request.job_id, run_id=request.run_id, request_hash=request.request_hash, provider_response_id=str(getattr(resp, "response_id", None) or f"resp-{request.job_id[-8:]}"),
            structured_result=structured, input_tokens=int(getattr(resp.usage, "input_tokens", 0) or 0), output_tokens=int(getattr(resp.usage, "output_tokens", 0) or 0), cost_microunits=1, latency_ms=int((time.monotonic()-t0)*1000))
        return self.authority.issue(request, result)

CONFIG = MemoryJobWorkerConfig(batch_size=1, idle_wait_seconds=0.01, max_batch_wait_seconds=0.0, lease_seconds=180.0, max_attempts=1, retry_delays_seconds=(),
    max_result_bytes=64 * 1024, analysis_budget=AnalysisBudget(8192, 1024, 170_000, 1_000_000), prompt_version="spike-analysis-prompt-v1",
    result_schema_version="spike-proposal-v1", policy_version="spike-policy-v1", validator_version="spike-validator-v1", provider_id="spike-provider",
    model_id=RUNTIME["model"], model_config_hash="b" * 64)

async def count(backend, sql, *a):
    async with backend.connection.execute(sql, a) as c:
        r = await c.fetchone(); return r[0] if r else None

async def main() -> int:
    db = SPIKE_DIR / f"spike_value_{int(NOW)}.db"
    delivery = HostDeliveryAuthority()
    manager = await MemoryManager.build_human_memory_v7(db, analysis_delivery_authority=delivery, evidence_authority=None,
        classification_policy=InformationClassificationPolicy(policy_id="memory-classification-policy", policy_version="1", authority_ref="memory-policy-registry:classification/v1",
            required_privacy_class=PrivacyClass.PERSONAL, required_information_attributes=()), short_horizon_embedder=HashEmbedder(32), allow_development_embedder=True)
    backend = manager.backend
    ev_auth = HostEvidenceAuthority(backend)
    backend._evidence_authority = ev_auth  # spike-only: builder accepts evidence_authority=; bound after backend exists so the resolver can read the store
    adapter = ProductProviderAdapter(Registry(), provider_id="spike-provider", client=httpx.AsyncClient(timeout=170), price_resolver=lambda p, m: (1000, 2000, "spike-price-v1"), model=RUNTIME["model"], model_params={})
    print("target:", adapter.target.provider_id, adapter.target.model, flush=True)
    host_principal = MemoryPrincipal(deployment_id="deskpet-local", household_id="deskpet-local-household", actor_id=SUBJECT, session_id="primary-conversation")
    placeholder = MemoryPrincipal(SUBJECT, SUBJECT, SUBJECT, "primary-conversation")
    scope = MemoryScope.personal(SUBJECT)
    try:
        # (1) Host's REAL filter policy on the exact wheel
        env0, rc0 = host_turn_envelope("dk-policy-probe", "探针", policy="host-public-turn/v1", run_id="run-probe")
        try:
            await manager.ingest_committed_evidence(env0, rc0)
            record("1-host-policy", True, "host-public-turn/v1 accepted by ingest_committed_evidence")
        except MemoryValidationError as exc:
            record("1-host-policy", False, f"ingest_committed_evidence(host-public-turn/v1) -> MemoryValidationError({exc}); backend supported_filter_policies={sorted(backend._supported_filter_policies)}; build_human_memory_v7 has no supported_filter_policies kwarg")
        # (2) ingest Host-shaped payloads (key `text`) under the only supported policy, one run per turn (=> one job/batch each)
        admitted = []
        for i, (dk, text) in enumerate(TURNS, start=1):
            env, rc = host_turn_envelope(dk, text, policy="credential-filter/v1", run_id=f"run-{i}")
            await manager.ingest_committed_evidence(env, rc); admitted.append((env, rc)); ev_auth.cache[env.evidence_id] = (env, rc)
        record("2-ingest", (await count(backend, "SELECT COUNT(*) FROM jobs")) == N_TURNS, f"jobs={await count(backend,'SELECT COUNT(*) FROM jobs')} payload keys={sorted(admitted[0][0].sanitized_payload)}")
        # (3) real provider through the real runner/validator
        executor = HostRealExecutor(backend, delivery, adapter)
        runner = DurableMemoryJobRunner(repository=backend, executor=executor, delivery_authority=delivery, config=CONFIG, worker_id="deskpet-worker-1", now=time.time)
        outcomes = []
        for _ in range(N_TURNS):
            try: outcomes.append(str(await runner.run_once()))
            except Exception as exc: outcomes.append(f"{type(exc).__name__}:{exc}")
        idle = str(await runner.run_once())
        async with backend.connection.execute("SELECT invocation_id,output_reason_code,validation_receipt_json FROM llm_invocations") as c:
            inv = [(str(r[0])[-8:], r[1], (json.loads(str(r[2])) or {}).get("validation_status") if r[2] else None) for r in await c.fetchall()]
        accepted_rows = await count(backend, "SELECT COUNT(*) FROM accepted_analysis_plans")
        mutate_accepted = [k for k, v in {r[0]: r[2] for r in inv}.items() if v == "accepted"]
        record("3-validator", outcomes == ["applied"] * N_TURNS and idle == "idle" and executor.calls == N_TURNS and all(v == "accepted" for _, _, v in inv) and len(executor.plans) == N_TURNS,
               f"run_once={outcomes}+{idle}; provider calls={executor.calls}; llm_invocations={inv}; accepted_analysis_plans={accepted_rows}; plans with ops={len(executor.plans)}; derivation_failures={executor.derivation_failures}")
        # (4) accepted-but-not-materialized: user-observable reads
        print("  step4: counting heads", flush=True)
        heads = await asyncio.wait_for(count(backend, "SELECT COUNT(*) FROM cognitive_memory_heads"), 20)
        print("  step4: read_outbox(placeholder)", flush=True)
        pend = await asyncio.wait_for(manager.read_outbox(principal=placeholder, states=("pending",)), 20)
        record("4-not-materialized", heads == 0 and not pend.entries, f"after runner APPLIED x2: cognitive_memory_heads={heads}; pending outbox={[(e.topic) for e in pend.entries]}; analysis_apply_heads={await count(backend,'SELECT revision FROM analysis_apply_heads')}")
        # (5) Host bridge: apply the SAME plans (true span verification via evidence_authority + materialization)
        applied = []
        for job_id, plan in executor.plans.items():
            try:
                print(f"  step5: apply plan for job {job_id[-8:]} base_revision={plan.base_revision}", flush=True)
                res = await asyncio.wait_for(manager.apply_memory_mutation_plan(principal=host_principal, scope=scope, plan=plan), 30)
                applied.append((job_id[-8:], str(res.outcome), getattr(res, "reason_code", None)))
            except Exception as exc:  # noqa: BLE001
                applied.append((job_id[-8:], type(exc).__name__, str(exc)))
        heads2 = await count(backend, "SELECT COUNT(*) FROM cognitive_memory_heads")
        async with backend.connection.execute("SELECT h.memory_type, r.content_json FROM cognitive_memory_heads h JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id AND r.revision=h.current_revision") as c:
            contents = [(str(r[0]), json.loads(str(r[1]))) for r in await c.fetchall()]
        print("  step5: read_outbox(host_principal)", flush=True)
        pend2 = await asyncio.wait_for(manager.read_outbox(principal=host_principal, states=("pending",)), 20)
        ok5 = bool(applied) and all(a[1] == "committed" for a in applied)
        record("5-apply-materialize", ok5, f"apply results={applied}; evidence_authority.resolve calls={ev_auth.resolutions}; cognitive_memory_heads={heads2}; pending outbox={[e.topic for e in pend2.entries]}; contents={json.dumps(contents, ensure_ascii=False)[:600]}")
        # (6) two heads drift check: analysis_apply_heads vs cognitive_apply_heads after apply
        print("  heads: analysis_apply_heads=", await count(backend, "SELECT revision FROM analysis_apply_heads"), " cognitive_apply_heads=", await count(backend, "SELECT revision FROM cognitive_apply_heads"), flush=True)
        # (7) negative: a non-verbatim quote cannot be derived (deterministic layer fails closed)
        try:
            derive_span(admitted[0][0], admitted[0][1], "每周五提醒我交周报", "span-neg"); record("7-nonverbatim", False, "derived a span for a paraphrase")
        except ValueError as exc:
            record("7-nonverbatim", True, f"paraphrased quote -> {exc}")
        (SPIKE_DIR / "raw_model_output.json").write_text(json.dumps(executor.raw, ensure_ascii=False, indent=1))
    finally:
        await adapter._client.aclose() if hasattr(adapter, "_client") else None
        await manager.close()
    return 0

if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        traceback.print_exc(); code = 1
    print("\nSUMMARY:")
    for k, (st, _) in RESULTS.items(): print(f"  {k}: {st}")
    sys.exit(code)
