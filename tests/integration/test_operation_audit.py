"""Real non-LLM producers and sealed public audit, expectations saved before reads."""
from dataclasses import replace

import pytest

import simple_harness_memory as m
from simple_harness_memory.core.suppression import SealedAuditAccessDenied
from tests.integration.test_audit_access_v6 import _AuditAccessAuthority, _grant, _principal


async def _open(tmp_path, *, max_reads=20):
    authority = _AuditAccessAuthority()
    manager = await m.build_human_memory_v7(tmp_path/'memory.db', clock=lambda:40.0,
                                           audit_access_authority=authority)
    principal = _principal()
    await manager.register_principal_owner(principal, m.MemoryScope.personal(principal.actor_id))
    _, reference = _grant(authority, max_reads=max_reads)
    receipt = await manager.authorize_audit_access(principal=principal, authority_ref=reference)
    return manager, principal, receipt, authority


async def _suppress(manager, principal, key='1'):
    return await manager.suppress(principal=principal, request=m.SuppressionRequest(
        'request-'+key, principal.actor_id, m.SuppressionScopeKind.EVIDENCE, 'payload-secret-'+key,
        'user_forget', 40.0))


async def _read(manager, principal, receipt, **kwargs):
    return await manager.read_operation_audit(requester=principal, target_principal=principal,
                                            access_receipt=receipt, **kwargs)


async def test_real_suppression_and_empty_coverage_no_llm(tmp_path):
    manager, p, receipt, _ = await _open(tmp_path)
    try:
        decision = await _suppress(manager,p)
        expected=m.OperationAuditExpectation('suppression', m.operation_audit_ref_hash('suppression', decision.directive_id),decision.decision_hash)
        page = await _read(manager,p,receipt, expected=(expected,))
        assert len(page.items) == 1
        assert page.items[0].receipt_hash == decision.decision_hash
        assert page.expectation_results[0].status == 'matched'
        assert len(page.coverage) == 9
        assert {v.family:v.row_count for v in page.coverage}['job_transition'] == 0
        assert page.enumeration_complete and not page.all_operations_recorded
        assert 'payload-secret' not in str(page.to_json())
    finally:
        await manager.close()


async def test_snapshot_append_pagination_and_reopen(tmp_path):
    manager,p,receipt,authority=await _open(tmp_path)
    try:
        expected=[await _suppress(manager,p,str(n)) for n in range(3)]
        first=await _read(manager,p,receipt,limit=1)
        later=await _suppress(manager,p,'later')
        second=await _read(manager,p,receipt,limit=1,cursor=first.next_cursor)
        assert second.snapshot_hash == first.snapshot_hash
        await manager.close()
        manager=await m.build_human_memory_v7(tmp_path/'memory.db',clock=lambda:40.0,audit_access_authority=authority)
        replay=await _read(manager,p,receipt,limit=1,cursor=first.next_cursor)
        assert replay.to_json()==second.to_json() and replay.access_event_hash != second.access_event_hash
        third=await _read(manager,p,receipt,limit=1,cursor=second.next_cursor)
        assert third.enumeration_complete
        assert [v.receipt_hash for page in (first,second,third) for v in page.items] == [v.decision_hash for v in expected]
        fresh=await _read(manager,p,receipt)
        assert later.decision_hash in {v.receipt_hash for v in fresh.items}
    finally:
        await manager.close()


async def test_shared_budget_with_existing_manifest(tmp_path):
    manager,p,receipt,_=await _open(tmp_path,max_reads=1)
    try:
        await _read(manager,p,receipt)
        with pytest.raises(SealedAuditAccessDenied,match='exhausted'):
            await manager.export_canonical_state_manifest(requester=p,target_principal=p,access_receipt=receipt)
    finally:
        await manager.close()


async def test_missing_expected_is_not_empty_success_and_forged_cursor_denies(tmp_path):
    manager,p,receipt,_=await _open(tmp_path)
    try:
        expected=m.OperationAuditExpectation('suppression','a'*64,'b'*64)
        page=await _read(manager,p,receipt,expected=(expected,))
        assert page.expectation_results[0].status=='missing'
        with pytest.raises(m.MemoryValidationError,match='cursor_invalid'):
            await _read(manager,p,receipt,cursor=m.OperationAuditCursor('forged'))
        with pytest.raises(SealedAuditAccessDenied):
            await _read(manager,p,replace(receipt,max_reads=999))
    finally:
        await manager.close()
