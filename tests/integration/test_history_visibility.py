"""AC1/AC7 decisive database contract; no provider or Host execution claims."""

from dataclasses import replace

import pytest
import simple_harness as h

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryLimitError
from simple_harness_memory.core.suppression import SuppressionCandidate, SuppressionDenied
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _classification_policy,
    _disclosure,
    _operation,
    _plan,
    _prepared,
    _principal,
)


async def _memory(backend, envelope, span):
    applied = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=m.MemoryScope.personal("actor-1"),
        plan=_plan(envelope, _operation(span)),
    )
    view = await backend.get_memory_mutation_receipt_view(
        principal=_principal(), receipt_ref=applied.receipt_ref
    )
    return view.operations[0].memory_id


async def _forget(backend, kind, target, key="forget"):
    return await backend.suppress(
        m.SuppressionRequest(key, "actor-1", kind, target, "user_forget", 20.0),
        principal=_principal(),
    )


def _binding(envelope, receipt):
    return m.HistoryEvidenceBinding(envelope, receipt)


@pytest.mark.asyncio
async def test_memory_forget_denies_original_user_ordinary_paths_and_history(tmp_path):
    backend, envelope, receipt, span, _ = await _prepared(tmp_path / "history.db")
    manager = m.MemoryManager(backend, None)
    try:
        mid = await _memory(backend, envelope, span)
        before = await manager.check_history_visibility(
            principal=_principal(),
            disclosure_context=_disclosure(),
            bindings=(_binding(envelope, receipt),),
        )
        assert before.items[0].visible
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        with pytest.raises(SuppressionDenied):
            await backend.read_ingested_evidence(envelope.evidence_id)
        assert envelope.evidence_id not in await backend.projection_evidence_ids("actor-1")
        after = await manager.check_history_visibility(
            principal=_principal(),
            disclosure_context=_disclosure(),
            bindings=(_binding(envelope, receipt),),
        )
        assert not after.items[0].visible and after.items[0].reason == "history_suppressed"
        assert after.authority_epoch > before.authority_epoch
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cold_host_admission_is_visible_without_sdk_ingestion_or_fake_run(tmp_path):
    manager = await m.build_human_memory_v7(
        tmp_path / "cold.db", classification_policy=_classification_policy()
    )
    envelope, receipt = _admitted()
    context = replace(
        _disclosure(),
        run_id="actual-ui-history-request-42",
        purpose=h.DisclosurePurpose.USER_REVIEW,
    )
    try:
        result = await manager.check_history_visibility(
            principal=_principal(),
            disclosure_context=context,
            bindings=(_binding(envelope, receipt),),
        )
        assert result.items[0].visible and result.items[0].reason == "history_visible"
        assert result.authority_epoch == 0
        with pytest.raises(KeyError):
            await manager.backend.read_ingested_evidence(envelope.evidence_id)
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,target", [("evidence", "evidence-1"), ("entity", "user:self"), ("subject", "actor-1")]
)
async def test_current_suppression_scopes_and_unrelated_user_control(tmp_path, scope, target):
    backend, envelope, receipt, span, _ = await _prepared(tmp_path / "scopes.db")
    manager = m.MemoryManager(backend, None)
    unrelated, unrelated_receipt = _admitted(evidence_id="unrelated")
    try:
        await _memory(backend, envelope, span)
        await _forget(backend, m.SuppressionScopeKind(scope), target)
        result = await manager.check_history_visibility(
            principal=_principal(),
            disclosure_context=_disclosure(),
            bindings=(_binding(envelope, receipt), _binding(unrelated, unrelated_receipt)),
        )
        assert [item.visible for item in result.items] == [False, scope != "subject"]
    finally:
        await manager.close()


async def _check(backend, *bindings, context=None, principal=None):
    return await backend.check_history_visibility(
        principal=principal or _principal(),
        disclosure_context=context or _disclosure(),
        bindings=tuple(bindings),
    )


def _rebind(envelope, receipt, **changes):
    envelope = replace(envelope, **changes)
    receipt = replace(
        receipt,
        envelope_hash=envelope.envelope_hash,
        subject=envelope.subject,
        sanitized_hash=envelope.sanitized_hash,
        evidence_refs=envelope.evidence_refs,
        disclosure_context=envelope.disclosure_context,
    )
    return _binding(envelope, receipt)


@pytest.mark.asyncio
async def test_assistant_lineage_pending_and_ingested_with_unrelated_control(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "descendants.db")
    child, child_receipt = _admitted(evidence_id="assistant")
    child_binding = _rebind(
        child,
        child_receipt,
        source_kind=h.EvidenceSourceKind.ASSISTANT_MESSAGE,
        evidence_refs=(h.EvidenceRef(env.evidence_id, env.envelope_hash, 1),),
    )
    unrelated, unrelated_receipt = _admitted(evidence_id="unrelated")
    try:
        mid = await _memory(backend, env, span)
        assert (await _check(backend, child_binding)).items[0].visible
        await backend.ingest_committed_evidence(child_binding.envelope, child_binding.receipt)
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        result = await _check(backend, child_binding, _binding(unrelated, unrelated_receipt))
        assert [x.visible for x in result.items] == [False, True]
        with pytest.raises(SuppressionDenied):
            await backend.read_ingested_evidence(child.evidence_id)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_missing_or_mismatched_parent_and_valid_pending_batch(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "parents.db")
    parent, parent_receipt = _admitted(evidence_id="pending-parent")
    child, child_receipt = _admitted(evidence_id="child")
    linked = _rebind(
        child,
        child_receipt,
        evidence_refs=(h.EvidenceRef(parent.evidence_id, parent.envelope_hash, 1),),
    )
    try:
        missing = await _check(backend, linked)
        assert missing.items[0].reason == "history_lineage_unverifiable"
        present = await _check(backend, linked, _binding(parent, parent_receipt))
        assert all(x.visible for x in present.items)
        wrong = _rebind(
            child, child_receipt, evidence_refs=(h.EvidenceRef(env.evidence_id, "0" * 64, 1),)
        )
        assert (await _check(backend, wrong)).items[0].reason == "history_binding_mismatch"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_canonical_binding_subject_and_disclosure_negatives(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "negatives.db")
    try:
        with pytest.raises((ValueError, m.MemoryValidationError)):
            await _check(backend, _binding(env, replace(receipt, envelope_hash="0" * 64)))
        changed = _rebind(env, receipt, source_hash="b" * 64)
        # Receipt still binds old source hash: rejected at canonical admission.
        with pytest.raises((ValueError, m.MemoryValidationError)):
            await _check(backend, changed)
        foreign, fr = _admitted(subject="other")
        assert (await _check(backend, _binding(foreign, fr))).items[
            0
        ].reason == "history_subject_mismatch"
        mismatch = replace(_disclosure(), recipient_id="other")
        assert (
            not (await _check(backend, _binding(env, receipt), context=mismatch)).items[0].visible
        )
        generation = replace(_disclosure(), generation=h.DisclosureGeneration.STALE)
        assert (
            not (await _check(backend, _binding(env, receipt), context=generation)).items[0].visible
        )
        await _memory(backend, env, span)
        with pytest.raises(m.MemoryOwnershipConflict):
            await _check(
                backend,
                _binding(env, receipt),
                principal=replace(_principal(), household_id="wrong"),
            )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_batch_is_one_snapshot_and_recheck_observes_concurrent_forget(tmp_path, monkeypatch):
    import asyncio

    backend, env, receipt, span, _ = await _prepared(tmp_path / "race.db")
    mid = await _memory(backend, env, span)
    entered = asyncio.Event()
    release = asyncio.Event()
    original = backend._resolve_suppression_unlocked
    calls = 0

    async def pause(*args, **kwargs):
        nonlocal calls
        result = await original(*args, **kwargs)
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(backend, "_resolve_suppression_unlocked", pause)
    try:
        checking = asyncio.create_task(
            _check(backend, _binding(env, receipt), _binding(env, receipt))
        )
        await asyncio.wait_for(entered.wait(), 2)
        forgetting = asyncio.create_task(_forget(backend, m.SuppressionScopeKind.MEMORY, mid))
        await asyncio.sleep(0)
        assert not forgetting.done()
        release.set()
        before = await checking
        await forgetting
        after = await _check(backend, _binding(env, receipt), _binding(env, receipt))
        assert [i.visible for i in before.items] == [True, True]
        assert [i.visible for i in after.items] == [False, False]
        assert before.request_hash == after.request_hash
        assert before.snapshot_hash != after.snapshot_hash
        assert before.authority_epoch < after.authority_epoch
    finally:
        release.set()
        await backend.close()


async def _recall_binding(backend):
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="history-recall"),
    )
    assert len(execution.result.items) == 1
    item = execution.result.items[0]
    return m.HistoryRecallBinding(
        execution.result.result_id,
        execution.result.result_hash,
        item.selected_item.item_id,
        item.result_item_hash,
    ), execution


@pytest.mark.asyncio
async def test_old_recall_new_ui_request_current_source_not_old_authorization(tmp_path):
    clock = [20.0]
    backend, env, receipt, span, _ = await _prepared(tmp_path / "recall.db", now=lambda: clock[0])
    try:
        mid = await _memory(backend, env, span)
        binding, execution = await _recall_binding(backend)
        clock[0] = execution.result.authority_expires_at + 1
        context = replace(
            _disclosure(), run_id="actual-new-ui-request", purpose=h.DisclosurePurpose.USER_REVIEW
        )
        assert (await _check(backend, binding, context=context)).items[0].visible
        with pytest.raises(m.MemoryValidationError, match="expired"):
            await backend.page_typed_recall_result(
                principal=_principal(),
                request=h.RecallResultPageRequestV1(
                    result_id=binding.result_id,
                    result_hash=binding.result_hash,
                    requested_at=clock[0],
                    page_ordinal=1,
                    item_offset=0,
                    max_items=8,
                    max_bytes=8192,
                ),
            )
        assert (await _check(backend, replace(binding, item_hash="0" * 64))).items[
            0
        ].reason == "history_binding_mismatch"
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        assert not (await _check(backend, binding, context=context)).items[0].visible
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_correction_changes_head_old_source_denied_and_all_revision_forget(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _span,
        _with_action_authorities,
    )

    backend, env, receipt, span, authority = await _prepared(tmp_path / "correction.db")
    try:
        mid = await _memory(backend, env, span)
        binding, _ = await _recall_binding(backend)
        new, new_receipt = _admitted(evidence_id="correction")
        new_span = replace(
            _span(new, new_receipt), support_kind=h.EvidenceSupportKind.EXPLICIT_USER_CORRECTION
        )
        authority.register_admitted(new, new_receipt, new_span)
        await backend.ingest_committed_evidence(new, new_receipt)
        op = replace(
            _operation(
                new_span,
                operation_id="revise",
                kind=h.MemoryMutationKind.REVISE,
                target=h.ExistingMemoryTarget(mid, 1),
            ),
            payload=h.SemanticMemoryPayload("user:self", "response_style", "verbose", ("default",)),
        )
        plan = _with_action_authorities(
            _plan(new, op, base_revision=2, plan_id="revision", idempotency_key="revision"),
            authority,
        )
        await backend.apply_memory_mutation_plan(
            principal=_principal(), scope=m.MemoryScope.personal("actor-1"), plan=plan
        )
        assert (await _check(backend, binding)).items[0].reason == "history_source_stale"
        assert all(
            x.visible
            for x in (
                await _check(backend, _binding(env, receipt), _binding(new, new_receipt))
            ).items
        )
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        assert not any(
            x.visible
            for x in (
                await _check(backend, _binding(env, receipt), _binding(new, new_receipt))
            ).items
        )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_memory_forget_reopen_revoke_preserves_original_evidence_bytes(tmp_path):
    from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
    from tests.integration.test_suppression_v5 import _raw_evidence_snapshot

    path = tmp_path / "reopen.db"
    backend, env, receipt, span, _ = await _prepared(path)
    mid = await _memory(backend, env, span)
    original = await _raw_evidence_snapshot(backend)
    directive = await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
    assert await _raw_evidence_snapshot(backend) == original
    await backend.close()
    reopened = SQLiteHumanMemoryBackend(
        path, now=lambda: 30.0, classification_policy=_classification_policy()
    )
    await reopened.initialize()
    try:
        assert not (await _check(reopened, _binding(env, receipt))).items[0].visible
        await reopened.revoke_suppression(
            m.SuppressionRevokeRequest(
                "restore", "actor-1", directive.directive_id, "user_restored", 30
            ),
            principal=_principal(),
        )
        assert (await _check(reopened, _binding(env, receipt))).items[0].visible
        assert await _raw_evidence_snapshot(reopened) == original
        assert (await reopened.read_ingested_evidence(env.evidence_id)).envelope == env
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_read_only_suppression_is_not_bypassed_by_recall_binding(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "purpose.db")
    try:
        mid = await _memory(backend, env, span)
        binding, _ = await _recall_binding(backend)
        await backend.suppress(
            m.SuppressionRequest(
                "read-only",
                "actor-1",
                m.SuppressionScopeKind.MEMORY,
                mid,
                "user_forget",
                20,
                purpose=m.OrdinaryMemoryPurpose.READ,
            ),
            principal=_principal(),
        )
        assert (await _check(backend, binding)).items[0].visible
        ui = replace(_disclosure(), purpose=h.DisclosurePurpose.USER_REVIEW)
        assert (
            not (await _check(backend, binding, _binding(env, receipt), context=ui))
            .items[0]
            .visible
        )
        assert not (await _check(backend, _binding(env, receipt), context=ui)).items[0].visible
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_short_history_current_expiry_at_unchanged_epoch(tmp_path):
    from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
    from simple_harness_memory.embedders.mock import HashEmbedder
    from tests.integration.test_short_horizon_repository_v5 import (
        NOW,
        PRINCIPAL,
        _Authority,
        _registration,
    )
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    pairs = tuple(_registration(i) for i in range(1, 12))
    clock = [NOW]
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "short.db",
        now=lambda: clock[0],
        conversation_evidence_authority=_Authority(tuple(x[0] for x in pairs)),
        short_horizon_embedder=HashEmbedder(32),
        classification_policy=_classification_policy(),
    )
    await backend.initialize()
    try:
        for registration, ref in pairs:
            await backend.ingest_committed_evidence(
                registration.envelope, registration.admission_receipt
            )
            await backend.register_conversation_evidence(ref)
        await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
        context = _context(
            query="Project alpha",
            short_horizon=True,
            expires_at=NOW + 100,
            selectors=(h.RecallSelectorDomain.MEMORY_TYPE, h.RecallSelectorDomain.SHORT_HORIZON),
        )
        execution = await backend.execute_typed_recall(
            principal=PRINCIPAL,
            context=context,
            plan=_recall_plan(
                context,
                idempotency_key="short-history",
                requested_memory_types=(),
                selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,),
            ),
        )
        assert execution.result.items
        item = execution.result.items[0]
        binding = m.HistoryRecallBinding(
            execution.result.result_id,
            execution.result.result_hash,
            item.selected_item.item_id,
            item.result_item_hash,
        )
        before = await _check(backend, binding, principal=PRINCIPAL)
        assert before.items[0].visible and before.valid_until is not None
        clock[0] = before.valid_until
        after = await _check(backend, binding, principal=PRINCIPAL)
        assert not after.items[0].visible
        assert before.authority_epoch == after.authority_epoch  # time alone invalidates
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_current_classification_and_bounded_input(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "bounds.db")
    try:
        with pytest.raises(MemoryLimitError):
            await _check(backend)
        with pytest.raises(MemoryLimitError):
            await _check(backend, *([_binding(env, receipt)] * 257))
        # Current receiver facts bind the observation and never inherit old disclosure.
        household = replace(
            _disclosure(),
            recipient=h.DeliveryRecipient.HOUSEHOLD,
            intended_audience=h.IntendedAudience.HOUSEHOLD,
            recipient_id="household-1",
        )
        assert (
            not (await _check(backend, _binding(env, receipt), context=household)).items[0].visible
        )
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_memory_support_on_derived_evidence_hides_original_user_ancestor(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import _span

    backend, env, receipt, _, authority = await _prepared(tmp_path / "derived-support.db")
    derived, derived_receipt = _admitted(evidence_id="derived")
    binding = _rebind(
        derived,
        derived_receipt,
        evidence_refs=(h.EvidenceRef(env.evidence_id, env.envelope_hash, 1),),
    )
    span = _span(binding.envelope, binding.receipt)
    authority.register_admitted(binding.envelope, binding.receipt, span)
    try:
        await backend.ingest_committed_evidence(binding.envelope, binding.receipt)
        mid = await _memory(backend, binding.envelope, span)
        assert (await _check(backend, _binding(env, receipt))).items[0].visible
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        assert not (await _check(backend, _binding(env, receipt))).items[0].visible
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_existing_source_cannot_be_reidentified_to_evade_memory_forget(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "identity.db")
    alias, alias_receipt = _admitted(evidence_id="new-identity")
    alias = _rebind(alias, alias_receipt, source_ref=env.source_ref)
    try:
        mid = await _memory(backend, env, span)
        await _forget(backend, m.SuppressionScopeKind.MEMORY, mid)
        assert (await _check(backend, alias)).items[0].reason == "history_binding_mismatch"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_shared_parent_dag_is_checked_once_per_snapshot(tmp_path, monkeypatch):
    import simple_harness_memory.backends.history_visibility as visibility

    backend, env, receipt, _, _ = await _prepared(tmp_path / "dag.db")
    bindings = [_binding(env, receipt)]
    for index in range(1, 19):
        child, admission = _admitted(evidence_id=f"dag-{index}")
        parents = bindings[-2:]
        bindings.append(
            _rebind(
                child,
                admission,
                evidence_refs=tuple(
                    h.EvidenceRef(
                        parent.envelope.evidence_id, parent.envelope.envelope_hash, ordinal
                    )
                    for ordinal, parent in enumerate(parents, 1)
                ),
            )
        )
    calls = []
    original = visibility._evidence_uncached

    async def count(*args, **kwargs):
        calls.append(args[3].envelope.evidence_id)
        return await original(*args, **kwargs)

    monkeypatch.setattr(visibility, "_evidence_uncached", count)
    try:
        result = await _check(backend, *reversed(bindings))
        assert all(item.visible for item in result.items)
        assert len(calls) == len(bindings) == len(set(calls))
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_admission_identity_and_pending_batch_alias_conflicts(tmp_path):
    backend, env, receipt, _, _ = await _prepared(tmp_path / "admission-identity.db")
    other, admission = _admitted(evidence_id="other")
    try:
        reused = _binding(other, replace(admission, receipt_id=receipt.receipt_id))
        assert (await _check(backend, reused)).items[0].reason == "history_binding_mismatch"
        fresh, fresh_receipt = _admitted(evidence_id="fresh")
        alias = _rebind(other, admission, source_ref=fresh.source_ref)
        with pytest.raises(m.MemoryValidationError, match="duplicate_identity"):
            await _check(backend, _binding(fresh, fresh_receipt), alias)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_batch_samples_trusted_clock_once(tmp_path):
    calls = []

    def clock():
        calls.append(20.0)
        return 20.0

    backend, env, receipt, span, _ = await _prepared(tmp_path / "single-clock.db", now=clock)
    try:
        await _memory(backend, env, span)
        recall, _ = await _recall_binding(backend)
        calls.clear()
        result = await _check(backend, _binding(env, receipt), recall)
        assert all(x.visible for x in result.items)
        assert calls == [20.0]
        assert result.checked_at == 20.0
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_reopen_current_policy_can_deny_with_same_recall_epoch(tmp_path):
    from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend

    path = tmp_path / "policy.db"
    backend, env, receipt, span, _ = await _prepared(path)
    await _memory(backend, env, span)
    before = await _check(backend, _binding(env, receipt))
    await backend.close()
    policy = replace(_classification_policy(), required_privacy_class=h.PrivacyClass.RESTRICTED)
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0, classification_policy=policy)
    await backend.initialize()
    try:
        after = await _check(backend, _binding(env, receipt))
        assert before.items[0].visible and not after.items[0].visible
        assert before.authority_epoch == after.authority_epoch
        assert before.policy_hash != after.policy_hash
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_suppression_target_in_second_sql_chunk_is_not_lost(tmp_path):
    backend, env, receipt, span, _ = await _prepared(tmp_path / "target-chunks.db")
    entities = tuple(f"entity-{i:03d}" for i in range(251))
    try:
        await _memory(backend, env, span)
        directive = await _forget(backend, m.SuppressionScopeKind.ENTITY, entities[-1])
        result = await backend.resolve_suppression(
            SuppressionCandidate("actor-1", entity_ids=entities), m.OrdinaryMemoryPurpose.READ
        )
        assert result.denied and result.directive_ids == (directive.directive_id,)
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("row_count", [4096, 4097])
async def test_canonical_lineage_row_budget_does_not_truncate_to_allow(tmp_path, row_count):
    from simple_harness_memory.backends.history_visibility import _lineage_rows

    backend, _, _, _, _ = await _prepared(tmp_path / "row-bound.db")
    try:
        async with backend.connection.execute(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<?) "
            "SELECT x FROM n",
            (row_count,),
        ) as cursor:
            if row_count == 4097:
                with pytest.raises(MemoryLimitError, match="history_lineage_row_limit"):
                    _ = [row async for row in _lineage_rows(cursor, [0])]
            else:
                rows = [row async for row in _lineage_rows(cursor, [0])]
                assert len(rows) == 4096 and rows[-1][0] == 4096
    finally:
        await backend.close()
