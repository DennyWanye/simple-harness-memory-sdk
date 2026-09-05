"""Exact public selected-source observations; genuine repository selection."""

from dataclasses import replace

import pytest
import simple_harness as h

import simple_harness_memory as m
from tests.integration.test_short_history_visibility import _binding, _fixture, _forget
from tests.integration.test_short_horizon_repository_v5 import (
    NOW,
    PRINCIPAL,
    _Authority,
    _disclosure,
    _registration,
)


async def _sources(manager, bindings, *, context=None):
    return await manager.resolve_short_horizon_sources(
        principal=PRINCIPAL, disclosure_context=context or _disclosure(), bindings=bindings
    )


async def test_exact_sources_one_clock_and_reopen(tmp_path):
    path = tmp_path / "short.db"
    async with _fixture(path) as (manager, result, pairs, clock, kwargs, _):
        bindings = tuple(_binding(result, hit) for hit in result.hits)
        before = len(clock)
        observed = await _sources(manager, bindings)
        assert len(clock) == before + 1
        assert all(item.visible and item.complete for item in observed.items)
        actual = {ref.evidence_id for item in observed.items for ref in item.source_refs}
        assert actual == {pairs[0][0].envelope.evidence_id, pairs[1][0].envelope.evidence_id}
        for item in observed.items:
            assert len(item.source_refs) == 1
            ref = item.source_refs[0]
            reg = next(reg for reg, _ in pairs if reg.envelope.evidence_id == ref.evidence_id)
            assert ref.to_json() == dict(
                evidence_id=reg.envelope.evidence_id,
                envelope_hash=reg.envelope.envelope_hash,
                source_ref=reg.envelope.source_ref,
                source_hash=reg.envelope.source_hash,
                sanitized_hash=reg.envelope.sanitized_hash,
                admission_receipt_id=reg.admission_receipt.receipt_id,
                admission_receipt_hash=reg.admission_receipt.receipt_hash,
                registration_id=reg.registration_id,
                registration_hash=reg.registration_hash,
                item_ordinal=1,
                role="user",
            )
        assert observed.evaluated_at == NOW and observed.valid_until > NOW
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        assert await _sources(manager, bindings) == observed
    finally:
        await manager.close()


@pytest.mark.parametrize("field", ["audit_id", "chunk_ref", "content_hash"])
async def test_forged_triple_never_exposes_partial_sources(tmp_path, field):
    async with _fixture(tmp_path / "short.db") as (manager, result, *_):
        real = _binding(result)
        forged = replace(real, **{field: "0" * 64})
        observed = await _sources(manager, (forged, real))
        assert not observed.items[0].visible and not observed.items[0].complete
        assert observed.items[0].source_refs == ()
        assert observed.items[1].visible


@pytest.mark.parametrize("gate", ["source", "entity", "expiry", "disclosure"])
async def test_current_gate_never_returns_usable_sources(tmp_path, gate):
    async with _fixture(tmp_path / "short.db") as (manager, result, pairs, clock, *_):
        bindings = tuple(_binding(result, hit) for hit in result.hits)
        before = await _sources(manager, bindings)
        ref = before.items[0].source_refs[0]
        context = _disclosure()
        if gate == "source":
            await _forget(manager, m.SuppressionScopeKind.EVIDENCE, ref.evidence_id)
        elif gate == "entity":
            await _forget(manager, m.SuppressionScopeKind.ENTITY, "project-alpha")
        elif gate == "expiry":
            clock[0] = NOW + 5 * 86400 + 1
        else:
            context = replace(context, generation=h.DisclosureGeneration.STALE)
        after = await _sources(manager, bindings, context=context)
        assert not after.items[0].visible and after.items[0].source_refs == ()
        if gate == "source":
            assert after.items[1].visible and after.authority_epoch > before.authority_epoch


async def test_more_than_256_indexed_sources_do_not_poison_one_selected_hit(tmp_path):
    pairs = tuple(_registration(i) for i in range(1, 270))
    manager = await m.build_human_memory_v7(
        tmp_path / "many.db",
        clock=lambda: NOW,
        conversation_evidence_authority=_Authority(tuple(reg for reg, _ in pairs)),
    )
    try:
        for reg, ref in pairs:
            await manager.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
            await manager.register_conversation_evidence(ref)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 259
        result = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="note 1", disclosure_context=_disclosure(), limit=1
        )
        assert len(result.hits) == 1 and result.hits[0].content == "user: Project alpha note 1"
        binding = _binding(result)
        first = await _sources(manager, (binding,))
        assert first.items[0].source_refs[0].evidence_id == "evidence-1"
        await _forget(manager, m.SuppressionScopeKind.EVIDENCE, "evidence-200")
        after = await _sources(manager, (binding,))
        assert after.items[0].visible and after.items[0].source_refs == first.items[0].source_refs
        assert after.authority_epoch > first.authority_epoch
    finally:
        await manager.close()


async def test_memory_only_forget_denies_selected_source_with_unaffected_hit_control(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _classification_policy,
        _operation,
        _plan,
    )

    async with _fixture(tmp_path / "short.db", policy=_classification_policy()) as (
        manager,
        result,
        pairs,
        _clock,
        kwargs,
        span,
    ):
        applied = await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL,
            scope=m.MemoryScope.personal(PRINCIPAL.actor_id),
            plan=_plan(pairs[0][0].envelope, _operation(span)),
        )
        assert applied.outcome.value == "committed"
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL, receipt_ref=applied.receipt_ref
        )
        bindings = tuple(_binding(result, hit) for hit in result.hits)
        before = await _sources(manager, bindings)
        assert all(item.visible for item in before.items)
        await _forget(manager, m.SuppressionScopeKind.MEMORY, view.operations[0].memory_id)
        after = await _sources(manager, bindings)
        for previous, current in zip(before.items, after.items, strict=True):
            suppressed = previous.source_refs[0].evidence_id == pairs[0][0].envelope.evidence_id
            assert current.visible is not suppressed
            if suppressed:
                assert current.source_refs == () and current.reason == "history_suppressed"
