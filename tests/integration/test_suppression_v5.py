from __future__ import annotations

import hashlib
import inspect
import sqlite3
from pathlib import Path

import pytest
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
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
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory.backends.sqlite_v5 import (
    SUPPRESSION_FAULT_POINTS,
    SQLiteHumanMemoryBackend,
)
from simple_harness_memory.core.audit import AuditAccessAuthorityRefV1
from simple_harness_memory.core.errors import MemoryIdempotencyConflict, MemoryValidationError
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SealedAuditAccessDecision,
    SealedAuditAccessDenied,
    SealedAuditAccessReceipt,
    SuppressionCandidate,
    SuppressionDenied,
    SuppressionRequest,
    SuppressionRevokeRequest,
    SuppressionScopeKind,
)


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure(subject: str = "actor-1") -> DisclosureContext:
    return DisclosureContext(
        "run-1",
        subject,
        DeliveryRecipient.USER_SELF,
        subject,
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "host-auth-1",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _audit_disclosure(subject: str = "actor-1") -> DisclosureContext:
    return DisclosureContext(
        "audit-run-1",
        subject,
        DeliveryRecipient.AUDIT_REVIEWER,
        "reviewer-1",
        IntendedAudience.AUDITOR,
        DisclosurePurpose.AUDIT,
        DisclosureSource.AUDIT_ACCESS_DECISION,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "audit-authority-1",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


class _SealedAccessAuthority:
    def __init__(self) -> None:
        self.decisions: dict[str, SealedAuditAccessDecision] = {}
        self.ordinal = 0

    async def resolve_audit_access(
        self, reference: AuditAccessAuthorityRefV1
    ) -> SealedAuditAccessDecision:
        return self.decisions[reference.ref_hash]

    def add(self, decision: SealedAuditAccessDecision) -> AuditAccessAuthorityRefV1:
        self.ordinal += 1
        reference = AuditAccessAuthorityRefV1(
            authority_id="host-audit-authority",
            issuer_ref="host-audit-issuer",
            nonce=f"nonce-{self.ordinal}",
            replay_identity=f"replay-{self.ordinal}",
            requester_deployment_id=decision.subject,
            requester_household_id=decision.subject,
            requester_actor_id=decision.subject,
            requester_session_id="session-1",
            target_deployment_id=decision.subject,
            target_household_id=decision.subject,
            target_actor_id=decision.subject,
            target_subject=decision.subject,
            decision_id=decision.decision_id,
            decision_hash=decision.decision_hash,
            scope_kind=decision.scope_kind,
            scope_ref=decision.scope_ref,
            issued_at=decision.issued_at,
            expires_at=decision.expires_at,
        )
        self.decisions[reference.ref_hash] = decision
        return reference


async def _authorize_audit(
    backend: SQLiteHumanMemoryBackend,
    authority: _SealedAccessAuthority,
    decision: SealedAuditAccessDecision,
) -> SealedAuditAccessReceipt:
    return await backend.authorize_audit_access(
        principal=MemoryPrincipal(
            decision.subject, decision.subject, decision.subject, "session-1"
        ),
        authority_ref=authority.add(decision),
    )


def _authority(
    evidence_id: str,
    *,
    subject: str = "actor-1",
) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {"public_text": f"public {evidence_id}"}
    source_ref = f"turn/{evidence_id}"
    source_hash = hashlib.sha256(f"source/{evidence_id}".encode()).hexdigest()
    evidence_ref = EvidenceRef(
        f"source-event-{evidence_id}",
        hashlib.sha256(f"event/{evidence_id}".encode()).hexdigest(),
        1,
    )
    envelope = SanitizedEvidenceEnvelope(
        evidence_id,
        "run-1",
        subject,
        EvidenceSourceKind.USER_MESSAGE,
        source_ref,
        source_hash,
        payload,
        _hash(payload),
        "credential-filter/v1",
        (),
        _disclosure(subject),
        (evidence_ref,),
    )
    receipt = SanitizedEvidenceReceipt(
        f"admission-{evidence_id}",
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


async def _raw_evidence_snapshot(backend: SQLiteHumanMemoryBackend) -> tuple[tuple[str, ...], ...]:
    async with backend.connection.execute(
        "SELECT evidence_id,source_hash,sanitized_hash,envelope_hash,hex(sanitized_payload) "
        "FROM evidence_envelopes ORDER BY evidence_id"
    ) as cursor:
        return tuple(tuple(str(value) for value in row) for row in await cursor.fetchall())


async def _counts(backend: SQLiteHumanMemoryBackend) -> tuple[int, int, int]:
    values: list[int] = []
    for table in ("suppression_directives", "suppression_targets", "outbox"):
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        values.append(int(row[0]))
    return values[0], values[1], values[2]


@pytest.mark.asyncio
async def test_exact_forget_denies_every_ordinary_entry_and_preserves_raw_evidence(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "exact.db", now=lambda: 30.0)
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    await backend.ingest_committed_evidence(*_authority("evidence-2"))
    before = await _raw_evidence_snapshot(backend)
    cached_candidate = SuppressionCandidate("actor-1", evidence_id="evidence-1")

    request = SuppressionRequest(
        "forget-1",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-1",
        "user_forget",
        30.0,
    )
    decision = await backend.suppress(request)
    assert await backend.suppress(request) == decision
    assert await _counts(backend) == (1, 1, 3)

    with pytest.raises(SuppressionDenied):
        await backend.read_ingested_evidence("evidence-1")
    with pytest.raises(SuppressionDenied):
        await backend.export_ingested_evidence("evidence-1")
    assert await backend.search_evidence_ids("actor-1") == ("evidence-2",)
    assert await backend.recall_evidence_ids("actor-1") == ("evidence-2",)
    assert await backend.projection_evidence_ids("actor-1") == ("evidence-2",)
    assert (await backend.export_ingested_evidence("evidence-2")).envelope.evidence_id == (
        "evidence-2"
    )
    assert (
        await backend.resolve_suppression(cached_candidate, OrdinaryMemoryPurpose.RECALL)
    ).denied
    assert await _raw_evidence_snapshot(backend) == before

    with pytest.raises(sqlite3.IntegrityError, match="immutable suppression"):
        await backend.connection.execute(
            "UPDATE suppression_directives SET reason_code='changed' WHERE directive_id=?",
            (decision.directive_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable suppression"):
        await backend.connection.execute(
            "DELETE FROM suppression_targets WHERE directive_id=?", (decision.directive_id,)
        )
    await backend.close()


@pytest.mark.asyncio
async def test_scope_and_purpose_matching_is_exact(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "scope.db", now=lambda: 30.0)
    await backend.initialize()
    cases = (
        (
            SuppressionScopeKind.MEMORY,
            "memory-1",
            SuppressionCandidate("actor-1", memory_id="memory-1"),
        ),
        (
            SuppressionScopeKind.ENTITY,
            "entity-1",
            SuppressionCandidate("actor-1", entity_ids=("entity-1",)),
        ),
    )
    for ordinal, (scope, scope_ref, candidate) in enumerate(cases, start=1):
        await backend.suppress(
            SuppressionRequest(
                f"forget-scope-{ordinal}",
                "actor-1",
                scope,
                scope_ref,
                "user_forget",
                30.0 + ordinal,
            )
        )
        assert (await backend.resolve_suppression(candidate, OrdinaryMemoryPurpose.READ)).denied

    await backend.suppress(
        SuppressionRequest(
            "forget-recall-only",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_forget",
            33.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    evidence = SuppressionCandidate("actor-1", evidence_id="evidence-1")
    assert (await backend.resolve_suppression(evidence, OrdinaryMemoryPurpose.RECALL)).denied
    assert not (await backend.resolve_suppression(evidence, OrdinaryMemoryPurpose.EXPORT)).denied
    assert not (await backend.resolve_suppression(evidence, OrdinaryMemoryPurpose.MUTATION)).denied
    await backend.suppress(
        SuppressionRequest(
            "forget-mutation-only",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-2",
            "user_forget",
            33.5,
            OrdinaryMemoryPurpose.MUTATION,
        )
    )
    mutation_evidence = SuppressionCandidate("actor-1", evidence_id="evidence-2")
    assert (
        await backend.resolve_suppression(mutation_evidence, OrdinaryMemoryPurpose.MUTATION)
    ).denied
    assert not (
        await backend.resolve_suppression(mutation_evidence, OrdinaryMemoryPurpose.READ)
    ).denied
    assert not (
        await backend.resolve_suppression(
            SuppressionCandidate("actor-1", evidence_id="evidence-3"),
            OrdinaryMemoryPurpose.RECALL,
        )
    ).denied
    await backend.suppress(
        SuppressionRequest(
            "forget-subject",
            "actor-2",
            SuppressionScopeKind.SUBJECT,
            "actor-2",
            "user_forget",
            34.0,
        )
    )
    assert (
        await backend.resolve_suppression(
            SuppressionCandidate("actor-2", evidence_id="evidence-9"),
            OrdinaryMemoryPurpose.READ,
        )
    ).denied
    assert not (
        await backend.resolve_suppression(
            SuppressionCandidate("actor-1", evidence_id="evidence-9"),
            OrdinaryMemoryPurpose.READ,
        )
    ).denied
    await backend.close()


@pytest.mark.asyncio
async def test_revoke_is_new_append_only_decision_and_reopen_restores_visibility(
    tmp_path: Path,
) -> None:
    path = tmp_path / "revoke.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    before = await _raw_evidence_snapshot(backend)
    directive = await backend.suppress(
        SuppressionRequest(
            "forget-1",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_forget",
            30.0,
        )
    )
    revoke_request = SuppressionRevokeRequest(
        "revoke-1", "actor-1", directive.directive_id, "user_restored", 31.0
    )
    revoke = await backend.revoke_suppression(revoke_request)
    assert await backend.revoke_suppression(revoke_request) == revoke
    assert (await backend.export_ingested_evidence("evidence-1")).envelope.evidence_id == (
        "evidence-1"
    )
    assert await _counts(backend) == (2, 2, 3)
    assert await _raw_evidence_snapshot(backend) == before
    with pytest.raises(MemoryIdempotencyConflict, match="already_revoked"):
        await backend.revoke_suppression(
            SuppressionRevokeRequest(
                "revoke-2", "actor-1", directive.directive_id, "user_restored", 32.0
            )
        )
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 40.0)
    await reopened.initialize()
    assert (await reopened.export_ingested_evidence("evidence-1")).envelope.evidence_id == (
        "evidence-1"
    )
    assert await _raw_evidence_snapshot(reopened) == before
    await reopened.close()


@pytest.mark.asyncio
async def test_rebuild_failure_and_worker_replay_never_weaken_synchronous_deny(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rebuild.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    before = await _raw_evidence_snapshot(backend)
    request = SuppressionRequest(
        "forget-1",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-1",
        "user_forget",
        30.0,
    )
    directive = await backend.suppress(request)
    await backend.connection.execute(
        "UPDATE outbox SET state='dead_letter' WHERE outbox_id=?",
        (directive.rebuild_outbox_id,),
    )
    assert await backend.suppress(request) == directive
    with pytest.raises(SuppressionDenied):
        await backend.export_ingested_evidence("evidence-1")
    assert await _raw_evidence_snapshot(backend) == before
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 40.0)
    await reopened.initialize()
    with pytest.raises(SuppressionDenied):
        await reopened.export_ingested_evidence("evidence-1")
    assert await _raw_evidence_snapshot(reopened) == before
    await reopened.close()


@pytest.mark.asyncio
async def test_sealed_audit_access_is_exact_limited_logged_and_not_an_ordinary_bypass(
    tmp_path: Path,
) -> None:
    clock = [40.0]
    path = tmp_path / "audit.db"
    access_authority = _SealedAccessAuthority()
    backend = SQLiteHumanMemoryBackend(
        path, now=lambda: clock[0], audit_access_authority=access_authority
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    await backend.ingest_committed_evidence(*_authority("evidence-2"))
    before = await _raw_evidence_snapshot(backend)
    await backend.suppress(
        SuppressionRequest(
            "forget-1",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_forget",
            30.0,
        )
    )
    with pytest.raises(SuppressionDenied):
        await backend.export_ingested_evidence("evidence-1")
    assert tuple(inspect.signature(backend.export_ingested_evidence).parameters) == ("evidence_id",)

    decision = SealedAuditAccessDecision(
        "audit-decision-1",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-1",
        "user_review",
        _audit_disclosure(),
        1,
        35.0,
        45.0,
    )
    reference = access_authority.add(decision)
    principal = MemoryPrincipal("actor-1", "actor-1", "actor-1", "session-1")
    receipt = await backend.authorize_audit_access(
        principal=principal, authority_ref=reference
    )
    assert (
        await backend.authorize_audit_access(
            principal=principal, authority_ref=reference
        )
        == receipt
    )
    await backend.close()

    backend = SQLiteHumanMemoryBackend(
        path, now=lambda: clock[0], audit_access_authority=access_authority
    )
    await backend.initialize()
    assert (await backend.export_sealed_evidence("evidence-1", receipt)).envelope.evidence_id == (
        "evidence-1"
    )
    with pytest.raises(SealedAuditAccessDenied, match="exhausted"):
        await backend.export_sealed_evidence("evidence-1", receipt)
    with pytest.raises(SuppressionDenied):
        await backend.export_ingested_evidence("evidence-1")

    wrong_scope = SealedAuditAccessDecision(
        "audit-decision-2",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-2",
        "user_review",
        _audit_disclosure(),
        1,
        35.0,
        45.0,
    )
    wrong_receipt = await _authorize_audit(backend, access_authority, wrong_scope)
    with pytest.raises(SealedAuditAccessDenied, match="scope_differs"):
        await backend.export_sealed_evidence("evidence-1", wrong_receipt)
    async with backend.connection.execute(
        "SELECT outcome,reason_code FROM sealed_audit_access_events ORDER BY rowid"
    ) as cursor:
        assert [tuple(row) for row in await cursor.fetchall()] == [
            ("granted", "sealed_audit_access_granted"),
            ("denied", "sealed_audit_access_exhausted"),
            ("denied", "sealed_audit_scope_differs"),
        ]
    assert await _raw_evidence_snapshot(backend) == before
    with pytest.raises(sqlite3.IntegrityError, match="immutable audit access"):
        await backend.connection.execute("DELETE FROM sealed_audit_access_receipts")
    with pytest.raises(sqlite3.IntegrityError, match="immutable audit event"):
        await backend.connection.execute("UPDATE sealed_audit_access_events SET outcome='granted'")
    await backend.close()


@pytest.mark.asyncio
async def test_expired_or_tampered_sealed_receipt_is_denied_and_logged(tmp_path: Path) -> None:
    clock = [40.0]
    access_authority = _SealedAccessAuthority()
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "expired.db",
        now=lambda: clock[0],
        audit_access_authority=access_authority,
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    decision = SealedAuditAccessDecision(
        "audit-decision-1",
        "actor-1",
        SuppressionScopeKind.SUBJECT,
        "actor-1",
        "user_review",
        _audit_disclosure(),
        2,
        35.0,
        45.0,
    )
    receipt = await _authorize_audit(backend, access_authority, decision)
    clock[0] = 50.0
    with pytest.raises(SealedAuditAccessDenied, match="expired"):
        await backend.export_sealed_evidence("evidence-1", receipt)
    tampered = SealedAuditAccessReceipt(
        receipt.access_receipt_id,
        receipt.decision_id,
        receipt.subject,
        receipt.scope_kind,
        receipt.scope_ref,
        receipt.purpose,
        "f" * 64,
        receipt.max_reads,
        receipt.issued_at,
        receipt.expires_at,
    )
    with pytest.raises(SealedAuditAccessDenied, match="receipt_differs"):
        await backend.export_sealed_evidence("evidence-1", tampered)
    async with backend.connection.execute(
        "SELECT reason_code FROM sealed_audit_access_events ORDER BY rowid"
    ) as cursor:
        assert [str(row[0]) for row in await cursor.fetchall()] == [
            "sealed_audit_access_expired",
            "sealed_audit_receipt_differs",
        ]
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", SUPPRESSION_FAULT_POINTS)
async def test_suppression_faults_are_atomic_or_replayable(
    tmp_path: Path, fault_point: str
) -> None:
    class InjectOnce:
        fired = False

        def __call__(self, point: str) -> None:
            if point == fault_point and not self.fired:
                self.fired = True
                raise RuntimeError(f"fault:{point}")

    path = tmp_path / f"fault-{fault_point.replace('.', '-')}.db"
    backend = SQLiteHumanMemoryBackend(path, fault_injector=InjectOnce(), now=lambda: 30.0)
    await backend.initialize()
    await backend.ingest_committed_evidence(*_authority("evidence-1"))
    request = SuppressionRequest(
        "forget-1",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-1",
        "user_forget",
        30.0,
    )
    with pytest.raises(RuntimeError, match="fault:suppression"):
        await backend.suppress(request)
    await backend.close()

    backend = SQLiteHumanMemoryBackend(path, now=lambda: 31.0)
    await backend.initialize()
    committed = fault_point == "suppression.after_commit"
    if committed:
        with pytest.raises(SuppressionDenied):
            await backend.export_ingested_evidence("evidence-1")
        assert (await backend.suppress(request)).request_id == request.request_id
    else:
        assert (await backend.export_ingested_evidence("evidence-1")).envelope.evidence_id == (
            "evidence-1"
        )
        assert (await backend.suppress(request)).request_id == request.request_id
        with pytest.raises(SuppressionDenied):
            await backend.export_ingested_evidence("evidence-1")
    await backend.close()


@pytest.mark.parametrize("schema_version", (True, 1.0, "1"))
def test_suppression_contracts_reject_non_exact_schema_versions(schema_version: object) -> None:
    with pytest.raises(MemoryValidationError, match="schema_unsupported"):
        SuppressionRequest(
            "forget-1",
            "actor-1",
            SuppressionScopeKind.SUBJECT,
            "actor-1",
            "user_forget",
            30.0,
            schema_version=schema_version,  # type: ignore[arg-type]
        )


def test_ordinary_disclosure_cannot_mint_sealed_audit_access() -> None:
    with pytest.raises(MemoryValidationError, match="sealed_audit_disclosure_authority_invalid"):
        SealedAuditAccessDecision(
            "audit-decision-1",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            "evidence-1",
            "user_review",
            _disclosure(),
            1,
            35.0,
            45.0,
        )
