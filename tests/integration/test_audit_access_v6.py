from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json

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
async def test_manifest_is_stable_and_access_event_does_not_pollute_root(
    tmp_path: Path,
) -> None:
    authority = _AuditAccessAuthority()
    path = tmp_path / "manifest.db"
    backend = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await backend.initialize()
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
    assert first.manifest.payload_hash == second.manifest.payload_hash
    assert first.access_event_hash != second.access_event_hash
    assert all(
        not hasattr(item, "row_ids") for item in first.manifest.table_roots
    )
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(
        path, now=lambda: 40.0, audit_access_authority=authority
    )
    await reopened.initialize()
    try:
        third = await reopened.export_canonical_state_manifest(
            requester=_principal(), target_principal=_principal(), access_receipt=receipt
        )
        assert third.manifest.payload_hash == first.manifest.payload_hash
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

    manager = await build_human_memory_v6(tmp_path / "public.db")
    assert isinstance(manager, MemoryManager)
    try:
        await manager.ingest_committed_evidence(*_authority("evidence-1"))
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
        changed = replace(reference, nonce="changed-nonce")
        authority.decisions[changed.ref_hash] = authority.decisions[reference.ref_hash]
        with pytest.raises(MemoryIdempotencyConflict, match="replay_conflict"):
            await backend.authorize_audit_access(
                principal=_principal(), authority_ref=changed
            )
        assert (
            await backend.export_sealed_evidence("evidence-1", receipt)
        ).envelope.evidence_id == "evidence-1"
        await backend.export_sealed_audit_trace(
            AuditTraceQuery("actor-1", AuditTraceSelector.TURN, "no-turn"),
            receipt,
            principal=_principal(),
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
    finally:
        await corrupted.close()
