"""Public durable typed selection, real SQLite transactions, no model imports."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, replace

import pytest
import simple_harness as h
import simple_harness_memory as m

from simple_harness_memory.core.history import history_hash
from tests.integration.test_short_history_visibility import _fixture, _forget
from tests.integration.test_short_horizon_repository_v5 import NOW, PRINCIPAL, _disclosure
from tests.integration.test_cognitive_mutation_repository_v5 import _classification_policy, _operation, _plan
from tests.integration.test_typed_recall_v6 import _context, _recall_plan


async def typed(manager, *, limit=8, short=True, key='typed-source'):
    context = _context(query='Project alpha', short_horizon=short, expires_at=NOW + 100,
                       selectors=(h.RecallSelectorDomain.MEMORY_TYPE, h.RecallSelectorDomain.SHORT_HORIZON) if short else (h.RecallSelectorDomain.MEMORY_TYPE,),
                       budget=h.RecallBudget(limit, 16384, 2048, 1000))
    execution = await manager.execute_typed_recall(
        principal=PRINCIPAL, context=context,
        plan=_recall_plan(context, idempotency_key=key, requested_memory_types=() if short else None, selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,) if short else None),
    )
    return execution.result


def binding(result, item=None):
    item = item or result.items[0]
    return m.HistoryRecallBinding(result.result_id, result.result_hash,
                                 item.selected_item.item_id, item.result_item_hash)


async def sources(manager, bindings, *, principal=PRINCIPAL, context=None):
    return await manager.resolve_typed_short_horizon_sources(
        principal=principal, disclosure_context=context or _disclosure(), bindings=bindings)


@asynccontextmanager
async def setup(path):
    async with _fixture(path, policy=_classification_policy()) as fixture:
        result = await typed(fixture[0])
        assert len(result.items) == 2
        yield fixture, result


async def test_exact_duplicate_domain_clock_and_reopen(tmp_path):
    path = tmp_path / 'typed.db'
    async with setup(path) as ((manager, standalone, pairs, clock, kwargs, _), result):
        bindings = tuple(binding(result, item) for item in result.items)
        count = len(clock)
        observed = await sources(manager, (*bindings, bindings[0]))
        assert len(clock) == count + 1
        assert observed.items[0] == observed.items[-1]
        assert all(x.visible and x.complete for x in observed.items)
        assert observed.items[0].binding_hash == history_hash('memory.typed.short.sources.binding.v1', bindings[0].to_json())
        assert observed.request_hash == history_hash('memory.typed.short.sources.request.v1', {
            'principal': asdict(PRINCIPAL), 'disclosure': _disclosure().to_json(),
            'bindings': [x.to_json() for x in (*bindings, bindings[0])],
        })
        for item in observed.items:
            ref = item.source_refs[0]
            reg = next(reg for reg, _ in pairs if reg.envelope.evidence_id == ref.evidence_id)
            assert ref.envelope_hash == reg.envelope.envelope_hash
            assert ref.source_hash == reg.envelope.source_hash
            assert ref.registration_hash == reg.registration_hash
            assert ref.admission_receipt_hash == reg.admission_receipt.receipt_hash
            assert ref.source_ref == reg.envelope.source_ref
        legacy = await manager.resolve_short_horizon_sources(principal=PRINCIPAL,
            disclosure_context=_disclosure(), bindings=(m.HistoryShortHorizonBinding(
                standalone.audit_id, standalone.hits[0].chunk_ref, standalone.hits[0].content_hash),))
        assert observed.request_hash != legacy.request_hash
    reopened = await m.build_human_memory_v7(path, **kwargs)
    try:
        assert await sources(reopened, (*bindings, bindings[0])) == observed
    finally:
        await reopened.close()


@pytest.mark.parametrize('field', ['result_id', 'result_hash', 'item_id', 'item_hash'])
async def test_forged_four_tuple_keeps_valid_sibling(tmp_path, field):
    async with setup(tmp_path / 'typed.db') as ((manager, *_), result):
        real = binding(result)
        fake = replace(real, **{field: '0' * 64})
        observed = await sources(manager, (fake, real))
        assert not observed.items[0].visible and observed.items[0].source_refs == ()
        assert observed.items[1].visible


async def test_eligible_but_not_selected_and_cognitive_never_expand(tmp_path):
    async with setup(tmp_path / 'typed.db') as ((manager, _, pairs, _, _, span), result):
        limited = await typed(manager, limit=1, key='one')
        assert len(limited.items) == 1
        excluded = next(i for i in result.items if i.selected_item.item_id != limited.items[0].selected_item.item_id)
        denied = await sources(manager, (binding(limited, excluded),))
        assert not denied.items[0].visible and denied.items[0].source_refs == ()
        applied = await manager.apply_memory_mutation_plan(principal=PRINCIPAL,
            scope=m.MemoryScope.personal(PRINCIPAL.actor_id), plan=_plan(pairs[0][0].envelope, _operation(span)))
        assert applied.outcome.value == 'committed'
        # Actual cognitive query, not a forged source kind on a short result.
        context = _context(query='concise', expires_at=NOW + 100)
        execution = await manager.execute_typed_recall(principal=PRINCIPAL, context=context,
            plan=_recall_plan(context, idempotency_key='cognitive'))
        assert execution.result.items
        assert execution.result.items[0].selected_item.source_kind.value == 'cognitive_memory'
        denied = await sources(manager, (binding(execution.result),))
        assert not denied.items[0].visible and denied.items[0].source_refs == ()


@pytest.mark.parametrize('gate', ['actor', 'subject', 'expiry', 'disclosure', 'evidence'])
async def test_current_gates_deny_refs(tmp_path, gate):
    """2026-09-07 决定：MEMORY 遗忘不再是拒绝来源引用的门禁，已移出本参数化（见下方专门测试）。"""
    async with setup(tmp_path / 'typed.db') as ((manager, _, pairs, clock, _, span), result):
        bindings = tuple(binding(result, item) for item in result.items)
        before = await sources(manager, bindings)
        principal, context = PRINCIPAL, _disclosure()
        if gate == 'actor':
            principal = replace(PRINCIPAL, actor_id='other')
        elif gate == 'subject':
            context = replace(context, subject='other')
        elif gate == 'expiry':
            clock[0] = NOW + 5 * 86400 + 1
        elif gate == 'disclosure':
            context = replace(context, generation=h.DisclosureGeneration.STALE)
        else:
            target = before.items[0].source_refs[0].evidence_id
            await _forget(manager, m.SuppressionScopeKind.EVIDENCE, target)
        observed = await sources(manager, bindings, principal=principal, context=context)
        assert any(not item.visible for item in observed.items)
        assert all(item.source_refs == () for item in observed.items if not item.visible)
        if gate == 'evidence':
            assert any(item.visible for item in observed.items)
            assert observed.authority_epoch > before.authority_epoch


async def test_memory_forget_keeps_typed_short_source_refs_with_evidence_control(tmp_path):
    """2026-09-07 决定：MEMORY 遗忘不拒绝类型化短期来源引用（引用与遗忘前完全一致）；
    同一来源的 EVIDENCE 压制仍拒绝（对照）。"""
    async with setup(tmp_path / 'typed.db') as ((manager, _, pairs, _, _, span), result):
        bindings = tuple(binding(result, item) for item in result.items)
        before = await sources(manager, bindings)
        assert all(item.visible for item in before.items)
        applied = await manager.apply_memory_mutation_plan(principal=PRINCIPAL,
            scope=m.MemoryScope.personal(PRINCIPAL.actor_id),
            plan=_plan(pairs[0][0].envelope, _operation(span)))
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL, receipt_ref=applied.receipt_ref)
        await _forget(manager, m.SuppressionScopeKind.MEMORY, view.operations[0].memory_id)
        kept = await sources(manager, bindings)
        assert all(item.visible for item in kept.items)
        assert [x.source_refs for x in kept.items] == [x.source_refs for x in before.items]
        assert kept.authority_epoch > before.authority_epoch
        await _forget(manager, m.SuppressionScopeKind.EVIDENCE,
                      before.items[0].source_refs[0].evidence_id, key='forget-2')
        observed = await sources(manager, bindings)
        assert any(not item.visible for item in observed.items)
        assert any(item.visible for item in observed.items)
        assert all(item.source_refs == () for item in observed.items if not item.visible)


async def test_wrong_binding_port_type_rejected(tmp_path):
    async with setup(tmp_path / 'typed.db') as ((manager, standalone, *_), result):
        with pytest.raises(TypeError):
            await sources(manager, (m.HistoryShortHorizonBinding(standalone.audit_id,
                standalone.hits[0].chunk_ref, standalone.hits[0].content_hash),))
        with pytest.raises(TypeError):
            await sources(manager, [binding(result)])


@pytest.mark.parametrize('cancel', [False, True])
async def test_transaction_atomic_forget_or_cancel(tmp_path, monkeypatch, cancel):
    import simple_harness_memory.backends.short_history_visibility as module
    async with setup(tmp_path / 'typed.db') as ((manager, *_), result):
        bindings = tuple(binding(result, item) for item in result.items)
        before = await sources(manager, bindings)
        entered, release = asyncio.Event(), asyncio.Event()
        original = module.check_selected_chunk
        async def paused(*args, **kwargs):
            outcome = await original(*args, **kwargs)
            if not entered.is_set():
                entered.set()
                await release.wait()
            return outcome
        monkeypatch.setattr(module, 'check_selected_chunk', paused)
        pending = asyncio.create_task(sources(manager, bindings))
        forget = None
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                forget = asyncio.create_task(_forget(manager, m.SuppressionScopeKind.EVIDENCE,
                    before.items[0].source_refs[0].evidence_id))
                await asyncio.sleep(.01)
                assert not forget.done()
                release.set()
                observed = await pending
                assert all(item.visible for item in observed.items)
                assert observed.authority_epoch == before.authority_epoch
                await forget
            release.set()
            after = await sources(manager, bindings)
            assert all(item.visible for item in after.items) if cancel else not after.items[0].visible
        finally:
            release.set()
            for task in (pending, forget):
                if task is not None and not task.done(): task.cancel()
            await asyncio.gather(*(task for task in (pending, forget) if task is not None), return_exceptions=True)


@pytest.mark.parametrize('field', ['deployment_id', 'household_id'])
async def test_same_actor_wrong_principal_rejected(tmp_path, field):
    from simple_harness_memory.core.errors import MemoryOwnershipConflict
    async with setup(tmp_path / 'typed.db') as ((manager, *_), result):
        with pytest.raises(MemoryOwnershipConflict):
            await sources(manager, (binding(result),), principal=replace(PRINCIPAL, **{field: 'wrong'}))


@pytest.mark.parametrize('fault', ['wrong_link', 'empty_refs', 'changed_text'])
async def test_actual_typed_selection_does_not_excuse_corrupt_lineage(tmp_path, fault):
    # Corrupt only a derived projection; no raw S1 deletion/restamping or DDL.
    async with _fixture(tmp_path / 'typed.db', policy=_classification_policy(),
                        close_corruption='short horizon chunk') as (manager, *_):
        result = await typed(manager)
        real = binding(result)
        assert (await sources(manager, (real,))).items[0].visible
        statements = {
            'wrong_link': "UPDATE short_horizon_chunk_evidence SET envelope_hash='wrong' WHERE chunk_id=?",
            'empty_refs': "UPDATE short_horizon_chunks SET classification_authority_refs_json='[]' WHERE chunk_id=?",
            'changed_text': "UPDATE short_horizon_chunks SET public_text='changed' WHERE chunk_id=?",
        }
        await manager.backend.connection.execute(statements[fault], (result.items[0].selected_item.source_ref,))
        await manager.backend.connection.commit()
        denied = await sources(manager, (real,))
        assert not denied.items[0].visible and denied.items[0].source_refs == ()
