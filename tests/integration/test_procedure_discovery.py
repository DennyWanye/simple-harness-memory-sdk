"""Only new owner draft preview and exact current history binding contracts."""
from dataclasses import replace
import pytest
from simple_harness import DeliveryRecipient, IntendedAudience
from simple_harness.runtime import LongTermMemoryType, ProcedureLifecycleState, ProcedureMemoryPayload, ProcedureRiskLevel, RecallDecisionOutcome
from simple_harness.contracts import canonical_json
from simple_harness_memory import MemoryManager, MemoryScope, HistoryProcedureDraftBinding, SuppressionRequest, SuppressionScopeKind
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.lifecycle_results import UNBOUND_PROCEDURE_APPLICABILITY
from .test_procedure_observation_repository_v5 import _setup, _principal, _procedure_operation
from .test_cognitive_mutation_repository_v5 import _plan
from .test_typed_recall_v6 import _context as _recall_context, _recall_plan


@pytest.mark.asyncio
async def test_unbound_draft_preview_exact_history_and_forget(tmp_path):
    backend, _, evidence, memory_id, revision = await _setup(tmp_path/'draft.db',[20.0])
    manager=MemoryManager(backend,None)
    principal=_principal(); scope=MemoryScope.personal(principal.actor_id); context=evidence[0][0].disclosure_context
    try:
        page=await manager.discover_procedure_drafts(principal=principal,scope=scope,disclosure_context=context,query='publish')
        assert len(page.candidates)==1
        candidate=page.candidates[0]
        assert (candidate.memory_id,candidate.revision,candidate.lifecycle_state)==(memory_id,revision,'draft')
        assert candidate.steps==('review','publish')
        bounded=await manager.discover_procedure_drafts(principal=principal,scope=scope,
            disclosure_context=context,query='publish',max_bytes=256)
        assert len(canonical_json(bounded.to_json()).encode())<=256
        assert bounded.candidates==() and bounded.omitted_oversize==1
        assert bounded.next_after is None  # Exactly one target, honestly exhausted.
        after=await manager.discover_procedure_drafts(principal=principal,scope=scope,
            disclosure_context=context,query='publish',after=candidate.memory_id)
        assert after.candidates==() and after.scanned==0
        assert page.operation_observation.operation=='discover_procedure_drafts'
        assert page.operation_observation.request_hash is not None
        binding=HistoryProcedureDraftBinding(memory_id,revision,candidate.source_hash)
        async def visible(ref):
            return (await manager.check_history_visibility(principal=principal,disclosure_context=context,bindings=(ref,))).items[0].visible
        assert await visible(binding)
        assert not await visible(replace(binding,candidate_hash='0'*64))
        await manager.suppress(principal=principal,request=SuppressionRequest('forget-preview',principal.actor_id,
            SuppressionScopeKind.MEMORY,memory_id,'user_forget',20.0))
        assert not await visible(binding)
        assert not (await manager.discover_procedure_drafts(principal=principal,scope=scope,disclosure_context=context,query='publish')).candidates
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_discovery_rejects_nonself_invalid_bounds_and_no_match_is_not_hit(tmp_path):
    backend, _, evidence, _, _ = await _setup(tmp_path/'reject.db',[20.0])
    manager=MemoryManager(backend,None); principal=_principal(); scope=MemoryScope.personal(principal.actor_id)
    context=evidence[0][0].disclosure_context
    try:
        external=replace(context,recipient=DeliveryRecipient.EXTERNAL_PARTY,recipient_id='other',intended_audience=IntendedAudience.EXTERNAL)
        with pytest.raises(MemoryValidationError,match='self_disclosure_required') as caught:
            await manager.discover_procedure_drafts(principal=principal,scope=scope,disclosure_context=external,query='publish')
        assert caught.value.operation_observation.outcome=='rejected'
        with pytest.raises(MemoryValidationError,match='bounds_invalid'):
            await manager.discover_procedure_drafts(principal=principal,scope=scope,disclosure_context=context,query='',limit=9)
        page=await manager.discover_procedure_drafts(principal=principal,scope=scope,disclosure_context=context,query='not-present')
        assert page.candidates==() and page.next_after is None
    finally:
        await manager.close()


# ---- 0.6.25：发现面对已采用（ACTIVE/REINFORCED、UNBOUND）流程可见 + 中文词项匹配 ----

async def _add_procedure(backend, evidence, index, *, name, steps, applicability=('当前工作目录',),
                         lifecycle_state=ProcedureLifecycleState.ACTIVE):
    """Second-plan CREATE on already ingested evidence[index]; adoption-style state at birth."""
    envelope, _receipt, span = evidence[index]
    operation = replace(_procedure_operation(span, operation_id=f'create-procedure-{index}', lifecycle_state=lifecycle_state),
        payload=ProcedureMemoryPayload(name, tuple(applicability), tuple(steps), ProcedureRiskLevel.LOW))
    async with backend.connection.execute("SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'") as cursor:
        base_revision = int((await cursor.fetchone())[0])
    result = await backend.apply_memory_mutation_plan(principal=_principal(), scope=MemoryScope.personal('actor-1'),
        plan=_plan(envelope, operation, base_revision=base_revision, plan_id=f'plan-{index}', idempotency_key=f'idem-{index}'))
    assert result.outcome.value == 'committed'
    async with backend.connection.execute(
        "SELECT h.memory_id,h.current_revision,r.lifecycle_state,p.applicability_fingerprint FROM cognitive_memory_heads h "
        "JOIN cognitive_memory_revisions r ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
        "JOIN procedure_records p ON p.memory_id=r.memory_id AND p.revision=r.revision WHERE p.name=?", (name,)) as cursor:
        row = await cursor.fetchone()
    assert (row[2], row[3]) == (lifecycle_state.value, UNBOUND_PROCEDURE_APPLICABILITY)
    return str(row[0]), int(row[1])


async def _discover(manager, evidence, query, **kwargs):
    principal = _principal()
    return await manager.discover_procedure_drafts(principal=principal, scope=MemoryScope.personal(principal.actor_id),
        disclosure_context=evidence[0][0].disclosure_context, query=query, **kwargs)


@pytest.mark.asyncio
async def test_adopted_active_unbound_procedure_is_discoverable_draft_stays_and_suppressed_hides(tmp_path):
    backend, _, evidence, draft_id, _ = await _setup(tmp_path / 'adopted.db', [20.0])
    manager = MemoryManager(backend, None)
    try:
        active_id, active_rev = await _add_procedure(backend, evidence, 1, name='松柏记录文件流程',
            steps=('在当前工作目录写 record.txt', '把同样内容再写一份 backup.txt'))
        page = await _discover(manager, evidence, '松柏记录')
        assert [(c.memory_id, c.revision, c.lifecycle_state) for c in page.candidates] == [(active_id, active_rev, 'active')]
        assert page.candidates[0].applicability_fingerprint == UNBOUND_PROCEDURE_APPLICABILITY
        # The English DRAFT is still discoverable, exactly as before.
        draft_page = await _discover(manager, evidence, 'publish')
        assert [(c.memory_id, c.lifecycle_state) for c in draft_page.candidates] == [(draft_id, 'draft')]
        # Forgetting the adopted procedure hides it from discovery like a draft.
        await manager.suppress(principal=_principal(), request=SuppressionRequest('forget-adopted', 'actor-1',
            SuppressionScopeKind.MEMORY, active_id, 'user_forget', 20.0))
        assert (await _discover(manager, evidence, '松柏记录')).candidates == ()
        assert [c.memory_id for c in (await _discover(manager, evidence, 'publish')).candidates] == [draft_id]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_chinese_terms_match_name_applicability_and_steps_and_rank_by_hits(tmp_path):
    backend, _, evidence, _, _ = await _setup(tmp_path / 'cjk.db', [20.0])
    manager = MemoryManager(backend, None)
    try:
        pine_id, _ = await _add_procedure(backend, evidence, 1, name='松柏记录文件流程',
            steps=('在当前工作目录写 record.txt', '把同样内容再写一份 backup.txt'))
        spruce_id, _ = await _add_procedure(backend, evidence, 2, name='云杉归档',
            applicability=('材料到齐以后',), steps=('列出目录清单', '把清单写进 archive.txt'))
        ids = lambda page: [c.memory_id for c in page.candidates]
        assert ids(await _discover(manager, evidence, '松柏记录')) == [pine_id]  # bigram terms, not verbatim
        assert ids(await _discover(manager, evidence, '松柏 备份')) == [pine_id]  # one term hit still discovers
        assert ids(await _discover(manager, evidence, '归档')) == [spruce_id]
        assert ids(await _discover(manager, evidence, '到齐')) == [spruce_id]  # applicability text is searchable
        assert ids(await _discover(manager, evidence, '云杉归档')) == [spruce_id]  # zero hits on the pine procedure
        assert ids(await _discover(manager, evidence, '银杏整理')) == []
        assert ids(await _discover(manager, evidence, 'BACKUP')) == [pine_id]  # casefold ASCII word kept
        # Ranking is by term hits, in both directions, independent of memory_id order.
        assert ids(await _discover(manager, evidence, '归档清单记录')) == [spruce_id, pine_id]
        assert ids(await _discover(manager, evidence, '记录文件归档')) == [pine_id, spruce_id]
        assert [c.lifecycle_state for c in (await _discover(manager, evidence, '记录文件归档')).candidates] == ['active', 'active']
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_pagination_cursor_is_scan_order_without_duplicates_or_gaps(tmp_path):
    backend, _, evidence, draft_id, _ = await _setup(tmp_path / 'page.db', [20.0])
    manager = MemoryManager(backend, None)
    try:
        expected = {draft_id}
        for index, name in ((1, '记录一'), (2, '记录二'), (3, '记录三')):
            memory_id, _ = await _add_procedure(backend, evidence, index, name=name, steps=('review', 'publish'))
            expected.add(memory_id)
        seen = []; after = ''
        for _ in range(8):
            page = await _discover(manager, evidence, 'publish', after=after, limit=1)
            seen.extend(c.memory_id for c in page.candidates)
            assert len(page.candidates) <= 1
            if page.next_after is None:
                break
            assert page.next_after > after  # cursor advances in scan order
            after = page.next_after
        assert len(seen) == len(set(seen)) == 4 and set(seen) == expected
        assert sorted(seen) == seen  # scan-order cursor: equal scores keep memory_id order across pages
        whole = await _discover(manager, evidence, 'publish')
        assert [c.memory_id for c in whole.candidates] == seen and whole.next_after is None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_typed_recall_still_no_recall_for_unbound_adopted_procedure(tmp_path):
    """Discovery widened; applicable recall did not: UNBOUND fingerprint stays gated."""
    backend, _, evidence, _, _ = await _setup(tmp_path / 'recall.db', [20.0])
    manager = MemoryManager(backend, None)
    try:
        pine_id, _ = await _add_procedure(backend, evidence, 1, name='松柏记录文件流程',
            steps=('在当前工作目录写 record.txt', '把同样内容再写一份 backup.txt'))
        assert [c.memory_id for c in (await _discover(manager, evidence, '松柏记录')).candidates] == [pine_id]
        context = _recall_context(query='松柏记录', memory_types=(LongTermMemoryType.PROCEDURE,),
            procedure_applicability_fingerprints=())
        result = await backend.execute_typed_recall(principal=_principal(), context=context,
            plan=_recall_plan(context, idempotency_key='idem-unbound-adopted'))
        assert result.decision.outcome is RecallDecisionOutcome.NO_RECALL
    finally:
        await manager.close()
