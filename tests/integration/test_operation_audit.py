"""Real non-LLM producers and sealed public audit, expectations saved before reads."""

from dataclasses import replace

import pytest

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryCorruptionError
from simple_harness_memory.core.suppression import SealedAuditAccessDenied
from tests.integration.test_audit_access_v6 import _AuditAccessAuthority, _grant, _principal


async def _open(tmp_path, *, max_reads=20, clock=None):
    authority = _AuditAccessAuthority()
    manager = await m.build_human_memory_v7(
        tmp_path / "memory.db", clock=clock or (lambda: 40.0), audit_access_authority=authority
    )
    principal = _principal()
    await manager.register_principal_owner(principal, m.MemoryScope.personal(principal.actor_id))
    _, reference = _grant(authority, max_reads=max_reads)
    receipt = await manager.authorize_audit_access(principal=principal, authority_ref=reference)
    return manager, principal, receipt, authority


async def _suppress(manager, principal, key="1"):
    return await manager.suppress(
        principal=principal,
        request=m.SuppressionRequest(
            "request-" + key,
            principal.actor_id,
            m.SuppressionScopeKind.EVIDENCE,
            "payload-secret-" + key,
            "user_forget",
            40.0,
        ),
    )


async def _read(manager, principal, receipt, **kwargs):
    return await manager.read_operation_audit(
        requester=principal, target_principal=principal, access_receipt=receipt, **kwargs
    )


async def test_real_suppression_and_empty_coverage_no_llm(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path)
    try:
        decision = await _suppress(manager, p)
        expected = m.OperationAuditExpectation(
            "suppression",
            m.operation_audit_ref_hash("suppression", decision.directive_id),
            decision.decision_hash,
        )
        page = await _read(manager, p, receipt, expected=(expected,))
        assert len(page.items) == 1
        assert page.items[0].receipt_hash == decision.decision_hash
        assert page.expectation_results[0].status == "matched"
        assert len(page.coverage) == 9
        assert {v.family: v.row_count for v in page.coverage}["job_transition"] == 0
        assert page.enumeration_complete and not page.all_operations_recorded
        assert "payload-secret" not in str(page.to_json())
    finally:
        await manager.close()


async def test_snapshot_append_pagination_and_reopen(tmp_path):
    manager, p, receipt, authority = await _open(tmp_path)
    try:
        expected = [await _suppress(manager, p, str(n)) for n in range(3)]
        first = await _read(manager, p, receipt, limit=1)
        later = await _suppress(manager, p, "later")
        second = await _read(manager, p, receipt, limit=1, cursor=first.next_cursor)
        assert second.snapshot_hash == first.snapshot_hash
        await manager.close()
        manager = await m.build_human_memory_v7(
            tmp_path / "memory.db", clock=lambda: 40.0, audit_access_authority=authority
        )
        replay = await _read(manager, p, receipt, limit=1, cursor=first.next_cursor)
        assert (
            replay.to_json() == second.to_json()
            and replay.access_event_hash != second.access_event_hash
        )
        third = await _read(manager, p, receipt, limit=1, cursor=second.next_cursor)
        assert third.enumeration_complete
        assert [v.receipt_hash for page in (first, second, third) for v in page.items] == [
            v.decision_hash for v in expected
        ]
        fresh = await _read(manager, p, receipt)
        assert later.decision_hash in {v.receipt_hash for v in fresh.items}
    finally:
        await manager.close()


async def test_shared_budget_with_existing_manifest(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path, max_reads=1)
    try:
        await _read(manager, p, receipt)
        with pytest.raises(SealedAuditAccessDenied, match="exhausted"):
            await manager.export_canonical_state_manifest(
                requester=p, target_principal=p, access_receipt=receipt
            )
    finally:
        await manager.close()


async def test_missing_expected_is_not_empty_success_and_forged_cursor_denies(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path)
    try:
        expected = m.OperationAuditExpectation("suppression", "a" * 64, "b" * 64)
        page = await _read(manager, p, receipt, expected=(expected,))
        assert page.expectation_results[0].status == "missing"
        with pytest.raises(m.MemoryValidationError, match="cursor_invalid"):
            await _read(manager, p, receipt, cursor=m.OperationAuditCursor("forged"))
        with pytest.raises(SealedAuditAccessDenied):
            await _read(manager, p, replace(receipt, max_reads=receipt.max_reads + 1))
    finally:
        await manager.close()


async def test_manifest_first_consumes_operation_reader_budget(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path, max_reads=1)
    try:
        await manager.export_canonical_state_manifest(
            requester=p,
            target_principal=p,
            access_receipt=receipt,
        )
        with pytest.raises(SealedAuditAccessDenied, match="exhausted"):
            await _read(manager, p, receipt)
    finally:
        await manager.close()


async def test_changed_known_prefix_is_not_replaced_by_later_append(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path)
    try:
        first = await _suppress(manager, p, "first")
        await _suppress(manager, p, "second")
        page = await _read(manager, p, receipt, limit=1)
        await _suppress(manager, p, "later")
        # Deliberate disposable SDK corruption: remove a pinned canonical event.
        # Normal production deletes are correctly rejected by immutable triggers.
        for trigger in (
            "suppression_targets_immutable_delete",
            "suppression_directives_immutable_delete",
        ):
            await manager.backend.connection.execute(f"DROP TRIGGER {trigger}")
        await manager.backend.connection.execute(
            "DELETE FROM suppression_targets WHERE directive_id=?",
            (first.directive_id,),
        )
        await manager.backend.connection.execute(
            "DELETE FROM suppression_directives WHERE directive_id=?",
            (first.directive_id,),
        )
        await manager.backend.connection.commit()
        with pytest.raises(MemoryCorruptionError, match="pinned_history_differs"):
            await _read(manager, p, receipt, cursor=page.next_cursor)
    finally:
        await manager.close()


async def test_expected_hash_mismatch_is_reported_without_payload(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path)
    try:
        decision = await _suppress(manager, p)
        expected = m.OperationAuditExpectation(
            "suppression",
            m.operation_audit_ref_hash("suppression", decision.directive_id),
            "b" * 64,
        )
        page = await _read(manager, p, receipt, expected=(expected,))
        assert page.expectation_results[0].status == "mismatched"
        assert decision.scope_ref not in str(page.to_json())
    finally:
        await manager.close()


@pytest.mark.parametrize(
    "no_mutation,heads,effect", [(True, 0, "no_mutation"), (False, 1, "written")]
)
async def test_real_job_effect_and_handoff_snapshot_stays_pinned(
    tmp_path, no_mutation, heads, effect
):
    from tests.integration.test_memory_061_core import (
        _build_pipeline,
        _evidence,
        _HostEvidenceAuthority,
        _HostExecutor,
        _ingest,
        _materialization_snapshot,
    )

    audit, evidence = _AuditAccessAuthority(), _HostEvidenceAuthority()
    snapshots = []

    class Executor(_HostExecutor):
        async def analyze_memory(self, request):
            snapshots.append(await _read(manager, p, receipt, limit=1))
            return await super().analyze_memory(request)

    executor = Executor(
        ({"evidence_id": "evidence-1", "operation_id": "actual-create"},), no_mutation=no_mutation
    )
    manager, runner = await _build_pipeline(
        tmp_path / "memory.db",
        executor,
        evidence_authority=evidence,
        audit_access_authority=audit,
        now=lambda: 40.0,
    )
    p = _principal()
    try:
        await _ingest(manager, _evidence(1), evidence)
        _, grant = _grant(audit, max_reads=20)
        receipt = await manager.authorize_audit_access(principal=p, authority_ref=grant)
        await _suppress(manager, p, "unrelated1")
        await _suppress(manager, p, "unrelated2")
        assert await runner.run_once() is m.WorkerRunOutcome.APPLIED
        actual = await _materialization_snapshot(manager)
        assert actual["heads"] == heads
        first = snapshots[0]
        pinned_job = next(c for c in first.coverage if c.family == "job_transition")
        assert pinned_job.unresolved_ref_hashes and not pinned_job.missing_event_ref_hashes
        replay = await _read(manager, p, receipt, limit=1, cursor=first.next_cursor)
        assert replay.snapshot_hash == first.snapshot_hash
        assert replay.coverage == first.coverage
        fresh = await _read(manager, p, receipt)
        applied = [
            i for i in fresh.items if i.family == "job_transition" and i.event_kind == "applied"
        ]
        assert len(applied) == 1 and applied[0].cognitive_effect == effect
        assert bool(applied[0].committed_operation_ref_hashes) is (heads == 1)
        assert applied[0].effect_receipt_hashes
        assert not next(
            c for c in fresh.coverage if c.family == "job_transition"
        ).unresolved_ref_hashes
        assert fresh.all_operations_recorded is False
    finally:
        await manager.close()


async def test_expired_real_grant_is_denied_on_cursor_replay(tmp_path):
    now = [40.0]
    manager, p, receipt, _ = await _open(tmp_path, clock=lambda: now[0])
    try:
        await _suppress(manager, p, "1")
        await _suppress(manager, p, "2")
        page = await _read(manager, p, receipt, limit=1)
        now[0] = receipt.expires_at
        with pytest.raises(SealedAuditAccessDenied, match="expired"):
            await _read(manager, p, receipt, cursor=page.next_cursor)
    finally:
        await manager.close()
