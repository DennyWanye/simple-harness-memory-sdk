"""Real standalone hits; public fixture setup, no fabricated typed result/authority."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
import simple_harness as h

import simple_harness_memory as m
from simple_harness_memory.embedders.mock import HashEmbedder
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _Authority as MutationAuthority,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_short_horizon_repository_v5 import (
    NOW,
    PRINCIPAL,
    _Authority,
    _disclosure,
    _registration,
)


@asynccontextmanager
async def _fixture(path, *, policy=None, close_corruption=None):
    pairs = tuple(_registration(i) for i in range(1, 13))
    first = pairs[0][0]
    span = _span(first.envelope, first.admission_receipt)
    mutation = MutationAuthority(first.envelope, first.admission_receipt, span)
    mutation.admitted = h.AdmittedEvidenceAuthority(
        first.envelope, first.admission_receipt, first.recall_item_authority
    )
    clock = [NOW]

    def now():
        clock.append(None)  # count calls without altering trusted time
        return clock[0]

    kwargs = dict(
        clock=now,
        conversation_evidence_authority=_Authority(tuple(x[0] for x in pairs)),
        evidence_authority=mutation,
        classification_policy=policy,
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
    )
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        for registration, ref in pairs:
            await manager.ingest_committed_evidence(
                registration.envelope, registration.admission_receipt
            )
            await manager.register_conversation_evidence(ref)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 2
        result = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="Project alpha", disclosure_context=_disclosure()
        )
        assert len(result.hits) == 2
        assert result.degradation_code.value == "NO_ACTIVE_GENERATION"
        assert result.fts_count == 2
        yield manager, result, pairs, clock, kwargs, span
    finally:
        if close_corruption:
            from simple_harness_memory.core.errors import MemoryCorruptionError

            with pytest.raises(MemoryCorruptionError, match=close_corruption):
                await manager.close()
        else:
            await manager.close()


def _binding(result, hit=None):
    hit = hit or result.hits[0]
    return m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)


async def _check(manager, *bindings, context=None, principal=PRINCIPAL):
    return await manager.check_history_visibility(
        principal=principal, disclosure_context=context or _disclosure(), bindings=bindings
    )


async def _forget(manager, kind, target, *, purpose=None, key="forget-1"):
    return await manager.suppress(
        principal=PRINCIPAL,
        request=m.SuppressionRequest(
            key, PRINCIPAL.actor_id, kind, target, "user_forget", NOW, purpose=purpose
        ),
    )


@pytest.mark.asyncio
async def test_exact_standalone_hit_new_host_request_without_cognitive_policy_and_reopen(tmp_path):
    path = tmp_path / "history.db"
    async with _fixture(path) as (manager, result, pairs, clock, kwargs, _):
        binding = _binding(result)
        context = replace(
            _disclosure(), run_id="actual-new-request", purpose=h.DisclosurePurpose.USER_REVIEW
        )
        before = len(clock)
        snapshot = await _check(manager, binding, context=context)
        assert len(clock) == before + 1
        assert snapshot.items[0].visible
        assert snapshot.items[0].reason == "history_visible"
        assert NOW < snapshot.valid_until <= NOW + 5 * 86400
        assert binding.to_json() == dict(
            kind="short_horizon",
            audit_id=result.audit_id,
            chunk_ref=result.hits[0].chunk_ref,
            content_hash=result.hits[0].content_hash,
        )
    reopened = await m.build_human_memory_v7(path, **kwargs)
    try:
        assert (await _check(reopened, binding, context=context)).items[0].visible
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["entity", "evidence", "subject", "memory"])
async def test_current_suppression_uses_canonical_short_lineage(tmp_path, scope):
    async with _fixture(tmp_path / "history.db") as (manager, result, pairs, *_):
        # The first two causal groups, never the newest ten, are projected.
        hit = next(
            x
            for x in result.hits
            if x.content == "user: " + pairs[0][0].envelope.sanitized_payload["public_text"]
        )
        binding = _binding(result, hit)
        targets = dict(
            entity="project-alpha", evidence="evidence-1", subject="actor-1", memory=hit.chunk_ref
        )
        assert (await _check(manager, binding)).items[0].visible
        decision = await _forget(manager, m.SuppressionScopeKind(scope), targets[scope])
        denied = await _check(manager, binding)
        assert denied.items[0].reason == "history_suppressed"
        assert not denied.items[0].visible
        await manager.revoke_suppression(
            principal=PRINCIPAL,
            request=m.SuppressionRevokeRequest(
                "restore-1", PRINCIPAL.actor_id, decision.directive_id, "user_restore", NOW
            ),
        )
        assert (await _check(manager, binding)).items[0].visible


@pytest.mark.asyncio
async def test_reverse_cognitive_memory_forget_keeps_old_short_and_original_user_visible(
    tmp_path,
):
    """2026-09-07 决定：遗忘认知记忆不隐藏其来源的短期历史与原始 USER 证据；
    EVIDENCE 范围压制仍会隐藏（对照）。"""
    async with _fixture(tmp_path / "history.db", policy=_classification_policy()) as (
        manager,
        result,
        pairs,
        _,
        _,
        span,
    ):
        first, second = pairs[0][0], pairs[1][0]
        applied = await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL,
            scope=m.MemoryScope.personal("actor-1"),
            plan=_plan(first.envelope, _operation(span)),
        )
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL, receipt_ref=applied.receipt_ref
        )
        first_hit = next(
            x
            for x in result.hits
            if x.content == "user: " + first.envelope.sanitized_payload["public_text"]
        )
        second_hit = next(
            x
            for x in result.hits
            if x.content == "user: " + second.envelope.sanitized_payload["public_text"]
        )
        bindings = (
            _binding(result, first_hit),
            _binding(result, second_hit),
            m.HistoryEvidenceBinding(first.envelope, first.admission_receipt),
            m.HistoryEvidenceBinding(second.envelope, second.admission_receipt),
        )
        assert all(x.visible for x in (await _check(manager, *bindings)).items)
        await _forget(manager, m.SuppressionScopeKind.MEMORY, view.operations[0].memory_id)
        snapshot = await _check(manager, *bindings)
        assert [x.visible for x in snapshot.items] == [True, True, True, True]
        # Control: an explicit EVIDENCE directive on the same source still hides
        # exactly its short chunk and original user evidence, never the second pair.
        await _forget(
            manager, m.SuppressionScopeKind.EVIDENCE, first.envelope.evidence_id, key="forget-2"
        )
        hidden = await _check(manager, *bindings)
        assert [x.visible for x in hidden.items] == [False, True, False, True]


@pytest.mark.asyncio
async def test_expiry_uses_one_current_clock_and_rejects_at_boundary(tmp_path):
    async with _fixture(tmp_path / "history.db") as (manager, result, _, clock, *_):
        bindings = tuple(_binding(result, hit) for hit in result.hits)
        first = await _check(manager, *bindings)
        clock[0] = first.valid_until - 0.001
        assert all(x.visible for x in (await _check(manager, *bindings)).items)
        clock[0] = first.valid_until
        at_boundary = await _check(manager, *bindings)
        assert not all(x.visible for x in at_boundary.items)
        assert any(x.reason == "history_source_stale" for x in at_boundary.items)
        clock[0] = NOW + 5 * 86400
        assert not any(x.visible for x in (await _check(manager, *bindings)).items)
        await manager.backend.cleanup_short_horizon(principal=PRINCIPAL)
        assert not any(x.visible for x in (await _check(manager, *bindings)).items)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["hash", "chunk", "audit", "owner", "disclosure"])
async def test_exact_selection_and_current_disclosure_rejects(tmp_path, change):
    async with _fixture(tmp_path / "history.db") as (manager, result, *_):
        binding = _binding(result)
        principal, context = PRINCIPAL, _disclosure()
        reason = "history_binding_mismatch"
        if change == "hash":
            binding = replace(binding, content_hash="0" * 64)
        if change == "chunk":
            binding = replace(binding, chunk_ref="short:unknown")
        if change == "audit":
            binding = replace(binding, audit_id="short-audit:unknown")
        if change == "owner":
            principal = m.MemoryPrincipal("other", "other", "other", "session-1")
            context = replace(context, subject="other", recipient_id="other")
        if change == "disclosure":
            context = replace(
                context,
                recipient=h.DeliveryRecipient.TASK_COLLABORATOR,
                intended_audience=h.IntendedAudience.TASK_COLLABORATORS,
                recipient_id="someone-else",
                purpose=h.DisclosurePurpose.TASK_EXECUTION,
            )
            reason = "history_disclosure_denied"
        item = (await _check(manager, binding, context=context, principal=principal)).items[0]
        assert not item.visible and item.reason == reason


@pytest.mark.asyncio
async def test_eligible_but_not_selected_is_not_proof(tmp_path):
    async with _fixture(tmp_path / "history.db") as (manager, result, *_):
        limited = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="Project alpha", disclosure_context=_disclosure(), limit=1
        )
        assert limited.eligible_count == 2 and len(limited.hits) == 1
        unselected = next(x for x in result.hits if x.chunk_ref != limited.hits[0].chunk_ref)
        item = (await _check(manager, _binding(limited, unselected))).items[0]
        assert not item.visible and item.reason == "history_binding_mismatch"


@pytest.mark.asyncio
async def test_mixed_batch_one_snapshot_and_fresh_outbound_recheck(tmp_path, monkeypatch):
    import asyncio

    from tests.integration.test_cognitive_mutation_repository_v5 import _admitted
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    async with _fixture(tmp_path / "mixed.db", policy=_classification_policy()) as (
        manager,
        result,
        pairs,
        clock,
        *_,
    ):
        context = _context(
            query="Project alpha",
            short_horizon=True,
            expires_at=NOW + 100,
            selectors=(h.RecallSelectorDomain.MEMORY_TYPE, h.RecallSelectorDomain.SHORT_HORIZON),
        )
        execution = await manager.execute_typed_recall(
            principal=PRINCIPAL,
            context=context,
            plan=_recall_plan(context, idempotency_key="mixed"),
        )
        assert len(execution.result.items) == 2
        typed = execution.result.items[0]
        envelope, receipt = _admitted(evidence_id="unrelated-cold")
        bindings = (
            _binding(result),
            m.HistoryRecallBinding(
                execution.result.result_id,
                execution.result.result_hash,
                typed.selected_item.item_id,
                typed.result_item_hash,
            ),
            m.HistoryEvidenceBinding(envelope, receipt),
        )
        backend = manager.backend
        entered, release = asyncio.Event(), asyncio.Event()
        original = backend._resolve_suppression_unlocked
        calls = 0

        async def pause(*args, **kwargs):
            nonlocal calls
            value = await original(*args, **kwargs)
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return value

        monkeypatch.setattr(backend, "_resolve_suppression_unlocked", pause)
        checking = asyncio.create_task(_check(manager, *bindings))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            forgetting = asyncio.create_task(
                _forget(manager, m.SuppressionScopeKind.ENTITY, "project-alpha")
            )
            await asyncio.sleep(0)
            assert not forgetting.done()
            before_clock = len(clock)
            release.set()
            before = await checking
            # No extra clock sample within the remainder of this mixed batch.
            assert len(clock) == before_clock
            await forgetting
            after = await _check(manager, *bindings)
            assert [x.visible for x in before.items] == [True, True, True]
            assert [x.visible for x in after.items] == [False, False, True]
            assert after.authority_epoch > before.authority_epoch
            assert before.request_hash == after.request_hash
        finally:
            release.set()
            await checking


@pytest.mark.asyncio
async def test_purpose_scoped_forget_keeps_existing_read_recall_distinction(tmp_path):
    from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose

    async with _fixture(tmp_path / "purpose.db") as (manager, result, *_):
        binding = _binding(result)
        await _forget(
            manager,
            m.SuppressionScopeKind.ENTITY,
            "project-alpha",
            purpose=OrdinaryMemoryPurpose.RECALL,
        )
        assert not (await _check(manager, binding)).items[0].visible
        review = replace(
            _disclosure(), run_id="actual-ui-request", purpose=h.DisclosurePurpose.USER_REVIEW
        )
        assert (await _check(manager, binding, context=review)).items[0].visible


@pytest.mark.asyncio
async def test_short_only_policy_does_not_relax_cold_evidence_floor(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import _admitted

    async with _fixture(tmp_path / "floors.db") as (manager, result, *_):
        envelope, receipt = _admitted(evidence_id="unrelated-cold")
        snapshot = await _check(
            manager, _binding(result), m.HistoryEvidenceBinding(envelope, receipt)
        )
        assert [item.visible for item in snapshot.items] == [True, False]
        assert snapshot.items[1].reason == "history_classification_unverifiable"
