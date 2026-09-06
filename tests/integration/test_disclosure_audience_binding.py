"""Recipient labels cannot hide a different final audience from SDK gates."""
from dataclasses import replace

import pytest
import simple_harness as h
import simple_harness_memory as m

from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted, _span, _Authority, _classification_policy, _principal, _operation, _plan,
)
from tests.integration.test_typed_recall_v6 import _context, _recall_plan, _disclosure


@pytest.mark.asyncio
@pytest.mark.parametrize("audience", [h.IntendedAudience.EXTERNAL, h.IntendedAudience.PUBLIC,
                                     h.IntendedAudience.TASK_COLLABORATORS])
async def test_self_recipient_cannot_recall_for_a_different_final_audience(tmp_path, audience):
    envelope, admission = _admitted()
    span = _span(envelope, admission)
    authority = _Authority(envelope, admission, span)
    manager = await m.build_human_memory_v7(tmp_path / "audience.db",
        clock=lambda: 20.0, evidence_authority=authority, memory_action_authority=authority,
        classification_policy=_classification_policy())
    try:
        await manager.ingest_committed_evidence(envelope, admission)
        await manager.apply_memory_mutation_plan(principal=_principal(),
            scope=m.MemoryScope.personal("actor-1"), plan=_plan(envelope, _operation(span)))
        personal = _context()
        good = await manager.execute_typed_recall(principal=_principal(), context=personal,
            plan=_recall_plan(personal, idempotency_key="personal-control"))
        assert len(good.result.items) == 1
        context = _context(disclosure=replace(_disclosure(), intended_audience=audience,
                                             purpose=h.DisclosurePurpose.TASK_EXECUTION))
        denied = await manager.execute_typed_recall(principal=_principal(), context=context,
            plan=_recall_plan(context, idempotency_key="final-audience-denied"))
        assert not denied.result.items and not denied.result.confirmation_groups
        assert not denied.candidate_query_started and denied.candidate_query_count == 0
        item = good.result.items[0]
        visible = await manager.check_history_visibility(principal=_principal(),
            disclosure_context=context.disclosure_context,
            bindings=(m.HistoryRecallBinding(good.result.result_id, good.result.result_hash,
                item.selected_item.item_id, item.result_item_hash),))
        assert not visible.items[0].visible
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_collaborator_audience_reaches_source_validation_instead_of_string_mismatch(tmp_path):
    manager = await m.build_human_memory_v7(tmp_path / "collaborator.db")
    try:
        context = replace(_disclosure(), recipient=h.DeliveryRecipient.TASK_COLLABORATOR,
            recipient_id="colleague-1", intended_audience=h.IntendedAudience.TASK_COLLABORATORS,
            purpose=h.DisclosurePurpose.TASK_EXECUTION)
        result = await manager.check_history_visibility(principal=_principal(),
            disclosure_context=context,
            bindings=(m.HistoryRecallBinding("unselected-result", "a" * 64, "unselected-item", "b" * 64),))
        assert not result.items[0].visible
        assert result.items[0].reason == "history_binding_mismatch"
    finally:
        await manager.close()
