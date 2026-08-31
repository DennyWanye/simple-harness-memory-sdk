from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json

from simple_harness_memory.backends.schema_v5 import (
    CANONICAL_MANIFEST_DERIVED_EXCLUSIONS,
    REQUIRED_TABLES,
)
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.audit import (
    AuditAccessAuthorityRefV1,
    AuditTraceQuery,
    AuditTraceSelector,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
)
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.suppression import (
    SealedAuditAccessDecision,
    SealedAuditAccessDenied,
    SuppressionRequest,
    SuppressionRevokeRequest,
    SuppressionScopeKind,
)
from tests.integration.test_suppression_v5 import _audit_disclosure, _authority


class _AuditAccessAuthority:
    def __init__(self) -> None:
        self.decisions: dict[str, SealedAuditAccessDecision] = {}

    async def resolve_audit_access(
        self, reference: AuditAccessAuthorityRefV1
    ) -> SealedAuditAccessDecision:
        return self.decisions[reference.ref_hash]


def _principal() -> MemoryPrincipal:
    return MemoryPrincipal("actor-1", "actor-1", "actor-1", "session-1")


@pytest.mark.asyncio
async def test_manifest_coverage_registry_accounts_for_every_required_table(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "manifest-inventory.db", now=lambda: 40.0)
    await backend.initialize()
    try:
        roots = await backend._canonical_manifest_roots_unlocked("actor-1")
        included = {item.table_name for item in roots}
        assert len(included) == len(roots)
        assert included.isdisjoint(CANONICAL_MANIFEST_DERIVED_EXCLUSIONS)
        assert included | CANONICAL_MANIFEST_DERIVED_EXCLUSIONS == REQUIRED_TABLES
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_no_mutation_invocation_changes_canonical_manifest_roots(
    tmp_path: Path,
) -> None:
    from simple_harness_memory.core.jobs import DurableMemoryJobRunner, WorkerRunOutcome
    from tests.integration.test_durable_memory_jobs_v5 import (
        TEST_WORKER_CONFIG,
        _authority_backend,
        _Executor,
        _ingest,
    )

    authority = _AuditAccessAuthority()
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(
        tmp_path / "manifest-no-mutation.db",
        executor,
        now=lambda: 40.0,
        audit_access_authority=authority,
    )
    await backend.initialize()
    try:
        await _ingest(backend)
        _, reference = _grant(authority, decision_id="manifest-no-mutation", max_reads=3)
        receipt = await backend.authorize_audit_access(
            principal=_principal(), authority_ref=reference
        )
        before = await backend.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        runner = DurableMemoryJobRunner(
            backend,
            executor,
            executor,
            TEST_WORKER_CONFIG,
            "worker-manifest-no-mutation",
            lambda: 40.0,
        )
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        after = await backend.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        before_roots = {item.table_name: item for item in before.manifest.table_roots}
        after_roots = {item.table_name: item for item in after.manifest.table_roots}
        assert before_roots["llm_invocations"].row_count == 0
        assert after_roots["llm_invocations"].row_count == 1
        assert before_roots["llm_invocations"].root_hash != after_roots[
            "llm_invocations"
        ].root_hash
        assert before.manifest.payload_hash != after.manifest.payload_hash
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_cursor_authority_is_bound_to_initialization_receipt_on_reopen(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cursor-authority-tamper.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 40.0)
    receipt = await backend.initialize()
    assert len(receipt.audit_cursor_authority_hash) == 64
    await backend.close()

    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER audit_cursor_authority_immutable_update")
        connection.execute(
            "UPDATE audit_cursor_authority SET hmac_key_hex=? WHERE singleton=1",
            ("f" * 64,),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 40.0)
    with pytest.raises(MemoryCorruptionError, match="cursor authority hash"):
        await reopened.initialize()


def _grant(
    authority: _AuditAccessAuthority,
    *,
    scope_kind: SuppressionScopeKind = SuppressionScopeKind.SUBJECT,
    scope_ref: str = "actor-1",
    max_reads: int = 3,
    decision_id: str = "audit-decision-1",
    issued_at: float = 35.0,
    expires_at: float = 45.0,
) -> tuple[SealedAuditAccessDecision, AuditAccessAuthorityRefV1]:
    decision = SealedAuditAccessDecision(
        decision_id,
        "actor-1",
        scope_kind,
        scope_ref,
        "user_review",
        _audit_disclosure(),
        max_reads,
        issued_at,
        expires_at,
    )
    reference = AuditAccessAuthorityRefV1(
        authority_id="host-audit-authority",
        issuer_ref="host-audit-issuer",
        nonce="nonce-1",
        replay_identity="replay-1",
        requester_deployment_id="actor-1",
        requester_household_id="actor-1",
        requester_actor_id="actor-1",
        requester_session_id="session-1",
        target_deployment_id="actor-1",
        target_household_id="actor-1",
        target_actor_id="actor-1",
        target_subject="actor-1",
        decision_id=decision.decision_id,
        decision_hash=decision.decision_hash,
        scope_kind=decision.scope_kind,
        scope_ref=decision.scope_ref,
        issued_at=decision.issued_at,
        expires_at=decision.expires_at,
    )
    authority.decisions[reference.ref_hash] = decision
    return decision, reference


@pytest.mark.asyncio
async def test_authority_ref_required_and_exact_replay_is_durable(tmp_path: Path) -> None:
    authority = _AuditAccessAuthority()
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "authority.db",
        now=lambda: 40.0,
        audit_access_authority=authority,
    )
    await backend.initialize()
    try:
        await backend.ingest_committed_evidence(*_authority("evidence-1"))
        decision, reference = _grant(authority)
        with pytest.raises(SealedAuditAccessDenied, match="authority_ref_required"):
            await backend.issue_sealed_audit_access(decision)
        receipt = await backend.authorize_audit_access(
            principal=_principal(), authority_ref=reference
        )
        assert (
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=reference
            )
            == receipt
        )
        async with backend.connection.execute(
            "SELECT outcome,reason_code FROM audit_access_authority_events ORDER BY rowid"
        ) as cursor:
            assert [tuple(row) for row in await cursor.fetchall()] == [
                ("denied", "audit_access_authority_ref_required"),
                ("granted", "audit_access_authority_granted"),
                ("granted", "audit_access_authority_replayed"),
            ]
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_manifest_snapshot_excludes_current_access_event_but_includes_prior_events(
    tmp_path: Path,
) -> None:
    authority = _AuditAccessAuthority()
    path = tmp_path / "manifest.db"
    backend = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await backend.initialize()
    try:
        await backend.ingest_committed_evidence(*_authority("evidence-1"))
        _, reference = _grant(authority, max_reads=4)
        receipt = await backend.authorize_audit_access(
            principal=_principal(), authority_ref=reference
        )
        first = await backend.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        second = await backend.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        first_roots = {item.table_name: item for item in first.manifest.table_roots}
        second_roots = {item.table_name: item for item in second.manifest.table_roots}
        assert first.manifest.payload_hash != second.manifest.payload_hash
        assert first_roots["canonical_manifest_access_events"].row_count == 0
        assert second_roots["canonical_manifest_access_events"].row_count == 1
        assert {
            name: item.root_hash
            for name, item in first_roots.items()
            if name != "canonical_manifest_access_events"
        } == {
            name: item.root_hash
            for name, item in second_roots.items()
            if name != "canonical_manifest_access_events"
        }
        assert first.access_event_hash != second.access_event_hash
        assert all(not hasattr(item, "row_ids") for item in first.manifest.table_roots)
    finally:
        await backend.close()

    reopened = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await reopened.initialize()
    try:
        third = await reopened.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        third_roots = {item.table_name: item for item in third.manifest.table_roots}
        assert third_roots["canonical_manifest_access_events"].row_count == 2
        assert third.manifest.payload_hash != second.manifest.payload_hash
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_metrics_and_trace_require_exact_public_principal(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "metrics.db", now=lambda: 40.0)
    await backend.initialize()
    try:
        await backend.ingest_committed_evidence(*_authority("evidence-1"))
        metrics = await backend.get_audit_aggregate_metrics(principal=_principal())
        assert metrics.visible_invocations == 0
        assert set(metrics.to_json()) == {
            "schema_version",
            "principal_ref_hash",
            "visible_invocations",
            "accepted_decisions",
            "rejected_decisions",
            "rejected_unsafe_outputs",
            "input_tokens",
            "output_tokens",
            "cost_microunits",
            "latency_ms",
        }
        with pytest.raises(MemoryOwnershipConflict, match="principal"):
            await backend.export_audit_trace(
                AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "turn-1"),
                principal=MemoryPrincipal("other", "other", "other", "session"),
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_clean_public_builder_exposes_seed_and_audit_facade(tmp_path: Path) -> None:
    from simple_harness_memory import (
        AuditAggregateMetricsV1,
        MemoryManager,
        build_human_memory_v6,
    )

    authority = _AuditAccessAuthority()
    manager = await build_human_memory_v6(
        tmp_path / "public.db", audit_access_authority=authority
    )
    assert isinstance(manager, MemoryManager)
    try:
        await manager.ingest_committed_evidence(*_authority("evidence-1"))
        current_time = time.time()
        _, reference = _grant(
            authority,
            decision_id="public-evidence-access",
            issued_at=current_time - 1.0,
            expires_at=current_time + 100.0,
        )
        receipt = await manager.authorize_audit_access(
            principal=_principal(), authority_ref=reference
        )
        record = await manager.export_sealed_evidence(
            requester=_principal(),
            evidence_id="evidence-1",
            access_receipt=receipt,
        )
        assert record.envelope.evidence_id == "evidence-1"
        metrics = await manager.get_audit_aggregate_metrics(principal=_principal())
        assert isinstance(metrics, AuditAggregateMetricsV1)
        suppression = await manager.suppress(
            principal=_principal(),
            request=SuppressionRequest(
                "forget-public",
                "actor-1",
                SuppressionScopeKind.EVIDENCE,
                "evidence-1",
                "user_forget",
                41.0,
            ),
        )
        await manager.revoke_suppression(
            principal=_principal(),
            request=SuppressionRevokeRequest(
                "revoke-public",
                "actor-1",
                suppression.directive_id,
                "user_restore",
                42.0,
            ),
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_authority_resolver_and_identity_mismatches_are_denied(
    tmp_path: Path,
) -> None:
    authority = _AuditAccessAuthority()
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "mismatch.db",
        now=lambda: 40.0,
        audit_access_authority=authority,
    )
    await backend.initialize()
    try:
        await backend.ingest_committed_evidence(*_authority("evidence-1"))
        decision, reference = _grant(authority)
        missing = replace(reference, nonce="missing")
        with pytest.raises(SealedAuditAccessDenied, match="resolution_failed"):
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=missing
            )
        for field_name, value in (
            ("requester_deployment_id", "wrong-deployment"),
            ("requester_household_id", "wrong-household"),
            ("requester_actor_id", "wrong-actor"),
            ("requester_session_id", "wrong-session"),
            ("target_deployment_id", "wrong-target-deployment"),
            ("target_household_id", "wrong-target-household"),
        ):
            changed = replace(reference, **{field_name: value})
            authority.decisions[changed.ref_hash] = decision
            with pytest.raises(SealedAuditAccessDenied, match="principal|target"):
                await backend.authorize_audit_access(
                    principal=_principal(), authority_ref=changed
                )
        changed_scope = replace(reference, scope_ref="different-memory")
        authority.decisions[changed_scope.ref_hash] = decision
        with pytest.raises(SealedAuditAccessDenied, match="binding_differs"):
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=changed_scope
            )
        changed_target = replace(
            reference,
            target_actor_id="different-target",
            target_subject="different-target",
        )
        authority.decisions[changed_target.ref_hash] = decision
        with pytest.raises(SealedAuditAccessDenied, match="binding_differs"):
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=changed_target
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_authority_time_replay_and_cross_api_max_reads(tmp_path: Path) -> None:
    clock = [40.0]
    authority = _AuditAccessAuthority()
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "limits.db",
        now=lambda: clock[0],
        audit_access_authority=authority,
    )
    await backend.initialize()
    try:
        await backend.ingest_committed_evidence(*_authority("evidence-1"))
        for decision_id, issued_at, expires_at, reason in (
            ("future", 41.0, 50.0, "not_yet_valid"),
            ("expired", 20.0, 40.0, "expired"),
        ):
            _, timed_ref = _grant(
                authority,
                decision_id=decision_id,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            with pytest.raises(SealedAuditAccessDenied, match=reason):
                await backend.authorize_audit_access(
                    principal=_principal(), authority_ref=timed_ref
                )
        _, reference = _grant(
            authority, decision_id="bounded", max_reads=2
        )
        receipt = await backend.authorize_audit_access(
            principal=_principal(), authority_ref=reference
        )
        stolen_requester = MemoryPrincipal(
            "actor-1", "actor-1", "actor-1", "stolen-session"
        )
        with pytest.raises(SealedAuditAccessDenied, match="requester_differs"):
            await backend.export_sealed_evidence(
                "evidence-1", receipt, requester=stolen_requester
            )
        with pytest.raises(SealedAuditAccessDenied, match="requester_differs"):
            await backend.export_sealed_audit_trace(
                AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "no-turn"),
                receipt,
                requester=stolen_requester,
            )
        changed = replace(reference, nonce="changed-nonce")
        authority.decisions[changed.ref_hash] = authority.decisions[reference.ref_hash]
        with pytest.raises(MemoryIdempotencyConflict, match="replay_conflict"):
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=changed
            )
        assert (
            await backend.export_sealed_evidence(
                "evidence-1", receipt, requester=_principal()
            )
        ).envelope.evidence_id == "evidence-1"
        await backend.export_sealed_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "no-turn"),
            receipt,
            requester=_principal(),
        )
        with pytest.raises(SealedAuditAccessDenied, match="exhausted"):
            await backend.export_canonical_state_manifest(
                requester=_principal(),
                target_principal=_principal(),
                access_receipt=receipt,
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_manifest_root_is_independently_recomputable_and_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    authority = _AuditAccessAuthority()
    path = tmp_path / "tamper.db"
    backend = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    _, reference = _grant(authority)
    receipt = await backend.authorize_audit_access(
        principal=_principal(), authority_ref=reference
    )
    access = await backend.export_canonical_state_manifest(
        requester=_principal(), target_principal=_principal(), access_receipt=receipt
    )
    evidence_root = next(
        item
        for item in access.manifest.table_roots
        if item.table_name == "evidence_envelopes"
    )
    async with backend.connection.execute(
        "SELECT * FROM evidence_envelopes WHERE principal_id=? ORDER BY evidence_id",
        ("actor-1",),
    ) as cursor:
        raw = list(await cursor.fetchall())
    assert len(raw) == 1
    row = dict(raw[0])
    leaf = hashlib.sha256(
        canonical_json(
            {"schema_version": 1, "table": "evidence_envelopes", "row": row}
        ).encode()
    ).hexdigest()
    expected_root = hashlib.sha256(
        canonical_json(
            {
                "schema_version": 1,
                "table": "evidence_envelopes",
                "leaves": [leaf],
            }
        ).encode()
    ).hexdigest()
    assert evidence_root.root_hash == expected_root
    await backend.close()

    raw_db = sqlite3.connect(path)
    raw_db.execute("DROP TRIGGER evidence_envelopes_immutable_update")
    raw_db.execute(
        "UPDATE evidence_envelopes SET envelope_hash=? WHERE evidence_id=?",
        ("f" * 64, "evidence-1"),
    )
    raw_db.commit()
    raw_db.close()
    corrupted = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await corrupted.initialize()
    try:
        with pytest.raises(MemoryCorruptionError, match="hash|schema"):
            await corrupted.export_canonical_state_manifest(
                requester=_principal(),
                target_principal=_principal(),
                access_receipt=receipt,
            )
        async with corrupted.connection.execute(
            "SELECT reason_code FROM canonical_manifest_access_events ORDER BY rowid DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == "canonical_manifest_integrity_rejected"
    finally:
        await corrupted.close()


@pytest.mark.asyncio
async def test_memory_selector_and_suppressed_metrics_match_nonexistent(
    tmp_path: Path,
) -> None:
    from tests.integration.test_audit_ledger_v5 import (
        _analysis_authority,
        _audit_backend,
        _decision,
        _ingest,
        _record_memory_analysis,
    )

    backend = _audit_backend(tmp_path / "memory-trace.db", now=lambda: 120.0)
    await backend.initialize()
    try:
        evidence_ref = await _ingest(backend, "evidence-1")
        request, result, delivery, validation = _analysis_authority(evidence_ref, 1)
        await _record_memory_analysis(
            backend,
            "invocation-create",
            "turn-create",
            request,
            result,
            delivery,
            validation,
            (_decision(evidence_ref, 1),),
        )
        page = await backend.export_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.MEMORY, "memory-1"),
            principal=_principal(),
        )
        assert [item.invocation.invocation_id for item in page.items] == [
            "invocation-create"
        ]
        assert page.items[0].decisions[0].target_ref == "memory-1"
        await backend.suppress(
            SuppressionRequest(
                "hide-memory",
                "actor-1",
                SuppressionScopeKind.MEMORY,
                "memory-1",
                "user_forget",
                121.0,
            )
        )
        suppressed = await backend.get_audit_aggregate_metrics(
            principal=_principal()
        )
    finally:
        await backend.close()

    empty = SQLiteHumanMemoryBackend(tmp_path / "empty-metrics.db", now=lambda: 120.0)
    await empty.initialize()
    try:
        await empty.ingest_committed_evidence(*_authority("evidence-unused"))
        nonexistent = await empty.get_audit_aggregate_metrics(principal=_principal())
        assert suppressed.to_json() == nonexistent.to_json()
    finally:
        await empty.close()


@pytest.mark.asyncio
async def test_memory_selector_reconstructs_create_final_id_lineage(tmp_path: Path) -> None:
    from simple_harness.runtime import MemoryMutationPlan

    from simple_harness_memory.core.identity import MemoryScope
    from simple_harness_memory.core.jobs import DurableMemoryJobRunner, WorkerRunOutcome
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _Authority as _CognitiveAuthority,
    )
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _classification_policy,
        _span,
    )
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _principal as _cognitive_principal,
    )
    from tests.integration.test_durable_memory_jobs_v5 import (
        TEST_WORKER_CONFIG,
        _authority,
        _authority_backend,
        _Executor,
    )

    evidence = (_authority(1), _authority(2))
    envelope, admission = evidence[0]
    cognitive_authority = _CognitiveAuthority(envelope, admission, _span(envelope, admission))
    executor = _Executor(None)
    backend = _authority_backend(
        tmp_path / "create-lineage.db",
        executor,
        now=lambda: 20.0,
        evidence_authority=cognitive_authority,
        memory_action_authority=cognitive_authority,
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    try:
        for evidence_envelope, evidence_admission in evidence:
            await backend.ingest_committed_evidence(evidence_envelope, evidence_admission)
        runner = DurableMemoryJobRunner(
            backend,
            executor,
            executor,
            TEST_WORKER_CONFIG,
            "worker-create-lineage",
            lambda: 20.0,
        )
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        async with backend.connection.execute(
            "SELECT plan_json FROM accepted_analysis_plans"
        ) as cursor:
            plan_row = await cursor.fetchone()
        assert plan_row is not None
        plan = MemoryMutationPlan.from_json(json.loads(str(plan_row["plan_json"])))
        evidence_by_id = {item[0].evidence_id: item for item in evidence}
        for evidence_span in plan.operations[0].evidence_spans:
            evidence_envelope, evidence_admission = evidence_by_id[evidence_span.evidence_id]
            cognitive_authority.register_admitted(
                evidence_envelope,
                evidence_admission,
                evidence_span,
            )
        result = await backend.apply_memory_mutation_plan(
            principal=_cognitive_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=plan,
        )
        assert result.receipt_ref is not None
        async with backend.connection.execute(
            "SELECT memory_id FROM cognitive_memory_heads WHERE principal_id=?",
            ("actor-1",),
        ) as cursor:
            memory_row = await cursor.fetchone()
        assert memory_row is not None
        final_memory_id = str(memory_row["memory_id"])
        page = await backend.export_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.MEMORY, final_memory_id),
            principal=_cognitive_principal(),
        )
        assert len(page.items) == 1
        assert {item.kind for item in page.items[0].lineage_refs} >= {
            "proposal",
            "accepted_plan",
            "mutation_receipt",
            "mutation_decision",
            "classification",
            "canonical_memory_revision",
            "evidence",
        }
        assert all(len(item.ref_hash) == 64 for item in page.items[0].lineage_refs)
    finally:
        await backend.close()
