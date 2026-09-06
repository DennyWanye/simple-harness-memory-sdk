"""Only new owner draft preview and exact current history binding contracts."""
from dataclasses import replace
import pytest
from simple_harness import DeliveryRecipient, IntendedAudience
from simple_harness.contracts import canonical_json
from simple_harness_memory import MemoryManager, MemoryScope, HistoryProcedureDraftBinding, SuppressionRequest, SuppressionScopeKind
from simple_harness_memory.core.errors import MemoryValidationError
from .test_procedure_observation_repository_v5 import _setup, _principal


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
