"""0.6.11 installed public consumer. Controlled Host facts, real SDK SQLite, no private SQL.

Reuses frozen privacy input constructors/behavior assertions, not old version assertions.
No tests/source-overlay imports, provider, UI, expected-output harvesting or Host coverage claim.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path

import simple_harness as h

import simple_harness_memory as m

spec = importlib.util.spec_from_file_location(
    "privacy_inputs", Path(__file__).with_name("duplicate_source_public_consumer.py")
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
f = p.f


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AuditAuthority:
    async def resolve_audit_access(self, reference):
        assert reference == self.reference
        return self.decision

    def __init__(self):
        principal = f._principal()
        disclosure = h.DisclosureContext(
            "audit-run",
            "actor-1",
            h.DeliveryRecipient.AUDIT_REVIEWER,
            "reviewer-1",
            h.IntendedAudience.AUDITOR,
            h.DisclosurePurpose.AUDIT,
            h.DisclosureSource.AUDIT_ACCESS_DECISION,
            h.DisclosureTrust.TRUSTED_AUTHORITY,
            h.DisclosureGeneration.CURRENT,
            "audit-authority-1",
            (h.DisclosureReasonCode.MINIMUM_NECESSARY,),
        )
        self.decision = m.SealedAuditAccessDecision(
            "audit-decision",
            "actor-1",
            m.SuppressionScopeKind.SUBJECT,
            "actor-1",
            "user_review",
            disclosure,
            32,
            35.0,
            1000.0,
        )
        self.reference = m.AuditAccessAuthorityRefV1(
            authority_id="host-audit",
            issuer_ref="host-issuer",
            nonce="nonce-1",
            replay_identity="replay-1",
            requester_deployment_id=principal.deployment_id,
            requester_household_id=principal.household_id,
            requester_actor_id=principal.actor_id,
            requester_session_id=principal.session_id,
            target_deployment_id=principal.deployment_id,
            target_household_id=principal.household_id,
            target_actor_id=principal.actor_id,
            target_subject="actor-1",
            decision_id=self.decision.decision_id,
            decision_hash=self.decision.decision_hash,
            scope_kind=self.decision.scope_kind,
            scope_ref=self.decision.scope_ref,
            issued_at=35.0,
            expires_at=1000.0,
        )


class Executor:
    """Deterministic Host execution/delivery fixture; no actual LLM invocation."""

    def __init__(self):
        self.deliveries = {}
        self.requests = []

    async def analyze_memory(self, request):
        self.requests.append(request)
        result = h.MemoryAnalysisResult(
            request.job_id,
            request.run_id,
            request.request_hash,
            "fixture-response",
            {"outcome": "no_mutation", "operations": []},
            100,
            50,
            0,
            25,
        )
        receipt = h.MemoryAnalysisDeliveryReceipt(
            "delivery-" + request.job_id,
            "fixture-host",
            request.run_id,
            request.job_id,
            request.request_hash,
            result.result_hash,
            request.attempt,
            result.provider_response_id,
            digest(result.provider_response_id),
            82.0,
            "host-record-" + request.job_id,
            digest(request.request_hash + result.result_hash),
        )
        envelope = h.MemoryAnalysisResultEnvelope(result, receipt)
        self.deliveries[(request.request_hash, request.attempt)] = envelope
        return envelope

    async def verify_analysis_delivery(self, request, envelope):
        envelope.verify_request(request)
        assert self.deliveries[(request.request_hash, request.attempt)] == envelope


async def audit_retry_case(folder):
    folder.mkdir()
    path, clock, principal = folder / "memory.db", [40.0], f._principal()
    authority, audit, executor = p.EvidenceAuthority(), AuditAuthority(), Executor()
    envelope, receipt = f._admitted(evidence_id="oa1-real-user")
    authority.register(m.HistoryEvidenceBinding(envelope, receipt), f._span(envelope, receipt))
    kwargs = dict(
        clock=lambda: clock[0],
        evidence_authority=authority,
        analysis_delivery_authority=executor,
        audit_access_authority=audit,
        classification_policy=f._classification_policy(),
    )
    manager = await m.build_human_memory_v7(path, **kwargs)
    config = m.MemoryJobWorkerConfig(
        1,
        0.01,
        0.0,
        10.0,
        2,
        (1.0,),
        65536,
        h.AnalysisBudget(4096, 1024, 30000, 1000000),
        "prompt-1",
        "result-1",
        "policy-1",
        "validator-1",
        "provider-1",
        "model-1",
        "a" * 64,
    )
    try:
        await manager.register_principal_owner(principal, m.MemoryScope.personal("actor-1"))
        await manager.ingest_committed_evidence(envelope, receipt)
        grant = await manager.authorize_audit_access(
            principal=principal, authority_ref=audit.reference
        )
        decisions = []
        for index in range(2):
            decisions.append(
                await manager.suppress(
                    principal=principal,
                    request=m.SuppressionRequest(
                        "forget-unused-" + str(index),
                        "actor-1",
                        m.SuppressionScopeKind.EVIDENCE,
                        "payload-secret-" + str(index),
                        "user_forget",
                        clock[0],
                    ),
                )
            )
        expected = tuple(
            m.OperationAuditExpectation(
                "suppression",
                m.operation_audit_ref_hash("suppression", d.directive_id),
                d.decision_hash,
            )
            for d in decisions
        )

        async def read(**extra):
            return await manager.read_operation_audit(
                requester=principal,
                target_principal=principal,
                access_receipt=grant,
                expected=expected,
                **extra,
            )

        first = await manager.backend.claim_analysis_batch(config, "first-owner")
        assert first is not None
        before = await read(limit=1)
        assert next(
            c for c in before.coverage if c.family == "job_transition"
        ).unresolved_ref_hashes
        assert (
            await manager.backend.fail_analysis_batch(first, "fixture-provider-failure", config)
            is m.WorkerRunOutcome.RETRY_SCHEDULED
        )
        clock[0] = 60.0
        second = await manager.backend.claim_analysis_batch(config, "second-owner")
        assert second is not None and second.batch_id != first.batch_id
        clock[0] = second.lease_expires_at + 1
        recovered = await manager.backend.claim_analysis_batch(config, "recover-owner")
        assert recovered is not None and recovered.batch_id == second.batch_id
        assert recovered.request == second.request and recovered.lease_token != second.lease_token
        assert (
            await manager.backend.fail_analysis_batch(second, "stale-owner", config)
            is m.WorkerRunOutcome.STALE_LEASE
        )
        clock[0] = recovered.lease_expires_at + 1
        runner = m.DurableMemoryJobRunner(
            manager.backend, executor, executor, config, "runner", lambda: clock[0]
        )
        assert await runner.run_once() is m.WorkerRunOutcome.APPLIED
        assert executor.requests == [second.request]
        fresh = await read()
        applied = [
            i for i in fresh.items if i.family == "job_transition" and i.event_kind == "applied"
        ]
        assert len(applied) == 1 and applied[0].cognitive_effect == "no_mutation"
        assert applied[0].effect_receipt_hashes and not applied[0].committed_operation_ref_hashes
        assert all(i.status == "matched" for i in fresh.expectation_results)
        assert not fresh.all_operations_recorded and len(fresh.coverage) == 9
        old = await read(limit=1, cursor=before.next_cursor)
        assert old.coverage == before.coverage and old.snapshot_hash == before.snapshot_hash
        assert "payload-secret" not in json.dumps(fresh.to_json())
        observation_hashes = []
        context = f._context(expires_at=200.0)
        plan = f._recall_plan(context, idempotency_key="protocol-probe")
        for protocol, reason in (
            (5, "typed_recall_protocol_unsupported"),
            ("5", "typed_recall_protocol_invalid"),
        ):
            try:
                await manager.execute_typed_recall(
                    principal=principal,
                    context=context,
                    plan=plan,
                    harness_protocol=protocol,
                    observation_context=m.MemoryOperationObservationContext(
                        "host-request", "host-attempt"
                    ),
                )
            except m.MemoryValidationError as error:
                assert str(error) == reason
                assert error.rejection_receipt.to_json()["reason"] == reason
                observed = error.operation_observation
                assert (
                    observed.candidate_query_started is False
                    and observed.candidate_query_count == 0
                )
                observation_hashes.append(observed.observation_hash)
            else:
                raise AssertionError("unsupported protocol admitted")
        await manager.close()
        manager = await m.build_human_memory_v7(path, **kwargs)
        replay = await read(limit=1, cursor=before.next_cursor)
        assert (
            replay.to_json() == old.to_json() and replay.access_event_hash != old.access_event_hash
        )
        clock[0] = 1000.0
        try:
            await read(cursor=before.next_cursor)
        except m.SealedAuditAccessDenied as error:
            assert str(error) == "sealed_audit_access_expired"
        else:
            raise AssertionError("expired grant admitted")
        return dict(
            stage="actual-retry-current-reclaim/applied-no-mutation/OA1-cut/reopen/clock-expiry/rejection",
            snapshot_hash=fresh.snapshot_hash,
            observation_hashes=observation_hashes,
            host_carrier_persistence_verified=False,
            price_provenance="unavailable",
        )
    finally:
        await manager.close()


async def run(args):
    assert "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    assert m.__version__ == "0.6.11" and h.__version__ == "0.7.2"
    assert sys.flags.isolated
    if not args.source_smoke:
        for module in (m, h):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        assert importlib.metadata.version("simple-harness-memory-sdk") == "0.6.11"
    args.output.mkdir(parents=True, exist_ok=False)
    stages = [await audit_retry_case(args.output / "audit-retry")]
    for mode in ("cold", "before", "after", "no_mutation", "legacy"):
        stages.append(await p.main_case(args.output / mode, mode))
    stages.append(await p.short_case(args.output))
    report = dict(
        status="PASS",
        version=m.__version__,
        installed=not args.source_smoke,
        stages=stages,
        memory_origin=m.__file__,
        harness_origin=h.__file__,
        all_operations_recorded=False,
        host_carrier_persistence_verified=False,
    )
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-smoke", action="store_true")
    asyncio.run(run(parser.parse_args()))
