"""Actual public standalone selection across two exact USER source duplicates."""

from dataclasses import replace

import pytest
import simple_harness as h
from simple_harness.contracts import fingerprint_json

import simple_harness_memory as m
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _Authority as MutationAuthority,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_duplicate_source_forget import Origins
from tests.integration.test_short_horizon_repository_v5 import (
    NOW,
    PRINCIPAL,
    _Authority,
    _disclosure,
    _registration,
)


def registered(sequence):
    """Rebind the existing synthetic SDK group fixture through every public DTO."""
    old, _ = _registration(sequence)
    text = "Project alpha shared original" if sequence <= 2 else f"Project alpha {sequence}"
    payload = {"item_id": f"message-{sequence}", "public_text": text,
               "text": text, "delivery_key": f"delivery-{sequence}"}
    digest = fingerprint_json(payload)
    envelope = replace(old.envelope, sanitized_payload=payload,
                       source_hash=digest, sanitized_hash=digest)
    receipt = replace(old.admission_receipt, envelope_hash=envelope.envelope_hash,
                      source_hash=digest, sanitized_hash=digest)
    item = replace(old.recall_item_authority, envelope_hash=envelope.envelope_hash,
                   source_hash=digest, sanitized_hash=digest)
    metadata = replace(
        old.metadata, envelope_hash=envelope.envelope_hash, source_hash=digest,
        sanitized_hash=digest, admission_receipt_hash=receipt.receipt_hash,
        public_text_json_pointer=None, public_text_hash=None,
        public_text_normalization_version=None, evidence_item_authority_id=None,
        evidence_item_authority_hash=None, effective_privacy_class=None,
        information_attributes=None, classification_authority_ref=None,
    )
    metadata = h.authorize_conversation_public_text(
        metadata, h.AdmittedEvidenceAuthority(envelope, receipt, item),
    )
    mr = replace(old.metadata_receipt, envelope_hash=envelope.envelope_hash,
                 admission_receipt_hash=receipt.receipt_hash, source_hash=digest,
                 sanitized_hash=digest, metadata_hash=metadata.metadata_hash)
    registration = replace(old, envelope=envelope, admission_receipt=receipt,
                           recall_item_authority=item, metadata=metadata, metadata_receipt=mr)
    return registration, h.ConversationEvidenceRegistrationRef(
        registration.registration_id, registration.registration_hash,
        envelope.evidence_id, envelope.envelope_hash,
    )


@pytest.mark.asyncio
async def test_standalone_and_typed_short_actual_duplicates_denied_after_memory_only_forget(
    tmp_path,
):
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    pairs = [registered(i) for i in range(1, 13)]
    seed = pairs[1][0]
    span = replace(_span(seed.envelope, seed.admission_receipt), item_id="message-2")
    mutation = MutationAuthority(seed.envelope, seed.admission_receipt, span)
    mutation.admitted = h.AdmittedEvidenceAuthority(
        seed.envelope, seed.admission_receipt, seed.recall_item_authority,
    )
    origins = Origins()
    for index, (registration, _) in enumerate(pairs, 1):
        origins.register(m.HistoryEvidenceBinding(
            registration.envelope, registration.admission_receipt,
        ), index)
    manager = await m.build_human_memory_v7(
        tmp_path / "short.db", clock=lambda: NOW,
        classification_policy=_classification_policy(), evidence_authority=mutation,
        conversation_evidence_authority=_Authority(tuple(p[0] for p in pairs)),
        history_source_authority=origins,
    )
    origins.backend = manager.backend
    try:
        for registration, ref in pairs:
            await manager.ingest_committed_evidence(
                registration.envelope, registration.admission_receipt,
            )
            await manager.register_conversation_evidence(ref)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 2
        before = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="Project alpha", disclosure_context=_disclosure(),
        )
        assert len(before.hits) == 2
        context = _context(
            query="Project alpha", short_horizon=True, expires_at=NOW + 100,
            selectors=(h.RecallSelectorDomain.MEMORY_TYPE, h.RecallSelectorDomain.SHORT_HORIZON),
        )
        typed_before = await manager.execute_typed_recall(
            principal=PRINCIPAL, context=context,
            plan=_recall_plan(
                context, idempotency_key="short-before", requested_memory_types=(),
                selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,),
            ), now=NOW,
        )
        assert typed_before.result.items
        assert all(x.selected_item.source_kind.value == "short_horizon"
                   for x in typed_before.result.items)
        result = await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL, scope=m.MemoryScope.personal("actor-1"),
            plan=_plan(seed.envelope, _operation(span)),
        )
        assert result.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL, receipt_ref=result.receipt_ref,
        )
        mid = view.operations[0].memory_id
        from tests.integration.test_duplicate_source_forget import NS

        origins.cuts["short-forget"] = m.HistoryForgetCutReceipt(
            NS, 2, "short-forget", m.SuppressionScopeKind.MEMORY, mid, "action-s1", "d" * 64,
        )
        await manager.suppress(principal=PRINCIPAL, request=m.SuppressionRequest(
            "short-forget", "actor-1", m.SuppressionScopeKind.MEMORY, mid, "user_forget", NOW,
        ))
        bindings = tuple(m.HistoryShortHorizonBinding(before.audit_id, x.chunk_ref, x.content_hash)
                         for x in before.hits)
        current = await manager.check_history_visibility(
            principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings,
        )
        assert all(not item.visible for item in current.items)
        resolved = await manager.resolve_short_horizon_sources(
            principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=bindings,
        )
        assert all(not item.visible for item in resolved.items)
        after = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="Project alpha", disclosure_context=_disclosure(),
        )
        assert after.hits == ()
        typed = await manager.execute_typed_recall(
            principal=PRINCIPAL, context=context,
            plan=_recall_plan(context, idempotency_key="short-duplicate", requested_memory_types=(),
                              selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,)), now=NOW,
        )
        assert not typed.result.items
    finally:
        await manager.close()
