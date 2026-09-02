"""Throwaway probe: Memory 0.6.0 analysis retry / reclaim key behaviour.

P1: executor failure -> retry -> NEW batch_id/request_hash/attempt/idempotency_key,
    but evidence-set key (request minus job_id/attempt/idempotency_key) is stable.
P2: membership growth between retries -> evidence-set key changes (per-evidence check needed).
P3: crash during executor call (BaseException) -> lease reclaim -> SAME request re-delivered.
P4: after refusing the reclaimed request -> fail -> attempt+1 -> new key, same evidence set.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from simple_harness.runtime import (
    AnalysisBudget,
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
    MemoryAnalysisDeliveryReceipt,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
    MemoryAnalysisResultEnvelope,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.jobs import (
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)
from simple_harness.contracts import canonical_json


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        "run-1", "actor-1", DeliveryRecipient.USER_SELF, "actor-1",
        IntendedAudience.USER_SELF, DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST, DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT, "host-authority",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _evidence(index: int):
    payload = {"item_id": f"message-{index}", "public_text": f"preference-{index}"}
    envelope = SanitizedEvidenceEnvelope(
        f"evidence-{index}", "run-1", "actor-1", EvidenceSourceKind.USER_MESSAGE,
        f"turn-{index}/user", f"{index}" * 64, payload, _hash(payload),
        "credential-filter/v1", (), _disclosure(),
        (EvidenceRef(f"source-event-{index}", f"{index + 2}" * 64, 1),),
    )
    receipt = SanitizedEvidenceReceipt(
        f"admission-{index}", envelope.run_id, envelope.subject, envelope.evidence_id,
        envelope.envelope_hash, envelope.source_hash, envelope.sanitized_hash,
        envelope.filter_policy_version, True,
        (EvidenceReasonCode.SANITIZED_AND_ACCEPTED,), envelope.disclosure_context,
        envelope.evidence_refs, 10.0,
    )
    return envelope, receipt


CONFIG = MemoryJobWorkerConfig(
    batch_size=1, idle_wait_seconds=0.01, max_batch_wait_seconds=0.0, lease_seconds=10.0,
    max_attempts=3, retry_delays_seconds=(3.0, 3.0), max_result_bytes=64 * 1024,
    analysis_budget=AnalysisBudget(4096, 1024, 30_000, 1_000_000),
    prompt_version="probe-prompt-v1", result_schema_version="probe-result-v1",
    policy_version="probe-policy-v1", validator_version="probe-validator-v1",
    provider_id="worker-const-provider", model_id="worker-const-model",
    model_config_hash="a" * 64,
)

# Attempt-independent key a Host could derive: everything in the request except
# job_id (= batch_id, embeds member attempts), attempt, idempotency_key (= batch_id).
def evidence_set_key(request: MemoryAnalysisRequest) -> str:
    body = request.to_json()
    for name in ("job_id", "attempt", "idempotency_key"):
        body.pop(name)
    return _hash(body)


class HostCrash(BaseException):
    """Simulates the Host process dying mid-provider-call (not an Exception)."""


class Executor:
    issuer_id = "probe-host-authority"

    def __init__(self, mode: str, ledger: dict[tuple[str, int], MemoryAnalysisResultEnvelope]):
        self.mode = mode
        self.ledger = ledger
        self.requests: list[MemoryAnalysisRequest] = []
        self.provider_calls = 0

    async def analyze_memory(self, request):
        self.requests.append(request)
        durable = self.ledger.get((request.request_hash, request.attempt))
        if durable is not None:
            return durable
        if self.mode == "fail":
            raise RuntimeError("host: sent_unknown unresolved -> definite failure")
        if self.mode == "crash":
            raise HostCrash()
        self.provider_calls += 1
        result = MemoryAnalysisResult(
            request.job_id, request.run_id, request.request_hash, "chatcmpl-probe",
            {"outcome": "no_mutation", "operations": []}, 10, 5, 3, 7,
        )
        delivery = MemoryAnalysisDeliveryReceipt(
            f"delivery-{request.job_id}-{request.attempt}", self.issuer_id, result.run_id,
            result.job_id, result.request_hash, result.result_hash, request.attempt,
            result.provider_response_id,
            hashlib.sha256(b"chatcmpl-probe").hexdigest(), 19.0,
            f"host-record-{request.job_id}-{request.attempt}",
            hashlib.sha256(f"{request.request_hash}:{request.attempt}".encode()).hexdigest(),
        )
        envelope = MemoryAnalysisResultEnvelope(result, delivery)
        self.ledger[(request.request_hash, request.attempt)] = envelope
        return envelope

    async def verify_analysis_delivery(self, request, envelope):
        envelope.verify_request(request)
        if self.ledger.get((request.request_hash, request.attempt)) != envelope:
            raise ValueError("durable Host analysis delivery differs")


def summary(r: MemoryAnalysisRequest) -> dict[str, Any]:
    return {
        "job_id": r.job_id[:28], "attempt": r.attempt, "request_hash": r.request_hash[:12],
        "idempotency_key": r.idempotency_key[:28],
        "evidence": [e.evidence_id for e in r.ordered_evidence_refs],
        "provider_id": r.provider_id, "model_id": r.model_id,
        "evidence_set_key": evidence_set_key(r)[:12],
    }


async def rows(backend, sql):
    async with backend.connection.execute(sql) as cur:
        return [tuple(r) for r in await cur.fetchall()]


async def main() -> None:
    out = Path(__file__).with_name(f"probe_{int(time.time())}.db")
    clock = [100.0]
    ledger: dict[tuple[str, int], MemoryAnalysisResultEnvelope] = {}

    # ---------- P1 + P2 ----------
    ex = Executor("fail", ledger)
    backend = SQLiteHumanMemoryBackend(out, analysis_delivery_authority=ex, now=lambda: clock[0])
    await backend.initialize()
    await backend.ingest_committed_evidence(*_evidence(1))
    runner = DurableMemoryJobRunner(backend, ex, ex, CONFIG, "worker-1", lambda: clock[0])
    o1 = await runner.run_once()
    print("P1 first run_once ->", o1, "request:", json.dumps(summary(ex.requests[0])))
    print("   batches:", await rows(backend, "SELECT substr(batch_id,1,28),attempt,state FROM analysis_batches"))
    print("   jobs:", await rows(backend, "SELECT substr(job_id,1,28),state,attempt_count,next_attempt_at FROM jobs"))
    # membership growth before retry
    await backend.ingest_committed_evidence(*_evidence(2))
    clock[0] = 104.0  # past retry delay (3s)
    CONFIG2 = CONFIG  # batch_size=1 -> the retry batch will contain only ONE job; use batch_size 2 to show growth
    from dataclasses import replace as _replace
    cfg_grow = _replace(CONFIG, batch_size=2)
    runner2 = DurableMemoryJobRunner(backend, ex, ex, cfg_grow, "worker-1", lambda: clock[0])
    o2 = await runner2.run_once()
    print("P1/P2 retry run_once ->", o2, "request:", json.dumps(summary(ex.requests[1])))
    r0, r1 = ex.requests[0], ex.requests[1]
    print("   same batch_id?", r0.job_id == r1.job_id, "| same request_hash?", r0.request_hash == r1.request_hash,
          "| same idempotency_key?", r0.idempotency_key == r1.idempotency_key,
          "| same evidence_set_key?", evidence_set_key(r0) == evidence_set_key(r1))
    print("   batches:", await rows(backend, "SELECT substr(batch_id,1,28),attempt,state FROM analysis_batches ORDER BY created_at"))
    print("   provider_calls:", ex.provider_calls)
    await backend.close()

    # ---------- P1b: same membership retry -> evidence_set_key stable ----------
    out_b = Path(__file__).with_name(f"probe_b_{int(time.time())}.db")
    clock[0] = 200.0
    exb = Executor("fail", {})
    bb = SQLiteHumanMemoryBackend(out_b, analysis_delivery_authority=exb, now=lambda: clock[0])
    await bb.initialize()
    await bb.ingest_committed_evidence(*_evidence(1))
    rb = DurableMemoryJobRunner(bb, exb, exb, CONFIG, "worker-1", lambda: clock[0])
    await rb.run_once(); clock[0] = 204.0; await rb.run_once(); clock[0] = 208.0; o = await rb.run_once()
    ks = [evidence_set_key(r) for r in exb.requests]
    print("P1b same-membership retries -> last outcome", o, "attempts", [r.attempt for r in exb.requests],
          "distinct request_hash", len({r.request_hash for r in exb.requests}),
          "distinct evidence_set_key", len(set(ks)))
    print("   jobs:", await rows(bb, "SELECT substr(job_id,1,28),state,attempt_count,last_error_code FROM jobs"))
    await bb.close()

    # ---------- P3 + P4: crash mid-call -> lease reclaim -> same request ----------
    out2 = Path(__file__).with_name(f"probe_c_{int(time.time())}.db")
    clock[0] = 300.0
    ledger2: dict = {}
    exc = Executor("crash", ledger2)
    b2 = SQLiteHumanMemoryBackend(out2, analysis_delivery_authority=exc, now=lambda: clock[0])
    await b2.initialize()
    await b2.ingest_committed_evidence(*_evidence(1))
    r2 = DurableMemoryJobRunner(b2, exc, exc, CONFIG, "worker-1", lambda: clock[0])
    try:
        await r2.run_once()
    except HostCrash:
        print("P3 host crashed mid-call; jobs:", await rows(b2, "SELECT substr(job_id,1,28),state,attempt_count,lease_expires_at FROM jobs"))
    await b2.close()
    # restart Host after lease expiry with a ledger that has the row in 'sent_unknown' (no envelope)
    clock[0] = 311.0
    exr = Executor("fail", ledger2)   # Host refuses: sent_unknown unresolved -> raise
    b3 = SQLiteHumanMemoryBackend(out2, analysis_delivery_authority=exr, now=lambda: clock[0])
    await b3.initialize()
    r3 = DurableMemoryJobRunner(b3, exr, exr, CONFIG, "worker-2", lambda: clock[0])
    o3 = await r3.run_once()
    a, b = exc.requests[0], exr.requests[0]
    print("P3 reclaim run_once ->", o3, "| same batch_id?", a.job_id == b.job_id,
          "| same request_hash?", a.request_hash == b.request_hash, "| same attempt?", a.attempt == b.attempt)
    print("   events:", await rows(b3, "SELECT event_kind,reason_code FROM job_attempt_events ORDER BY occurred_at"))
    clock[0] = 315.0
    o4 = await r3.run_once()
    c = exr.requests[-1]
    print("P4 after refusal run_once ->", o4, "| new attempt", c.attempt, "| same request_hash as crashed?",
          a.request_hash == c.request_hash, "| same evidence_set_key?", evidence_set_key(a) == evidence_set_key(c))
    clock[0] = 319.0
    o5 = await r3.run_once()
    print("P4 third ->", o5, "jobs:", await rows(b3, "SELECT substr(job_id,1,28),state,attempt_count,last_error_code FROM jobs"),
          "outbox:", await rows(b3, "SELECT topic,state FROM outbox"))
    print("   total Host provider_calls across all executors:", exc.provider_calls + exr.provider_calls)
    await b3.close()


try:
    asyncio.run(main())
except BaseException:
    import traceback; traceback.print_exc()
finally:
    import os, sys; sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
