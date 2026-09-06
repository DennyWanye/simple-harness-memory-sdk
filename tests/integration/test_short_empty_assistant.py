"""Public registration/projection/source APIs; complete Host authority fixtures.

No SDK result/Memory selection receipt is fabricated. Tool terminal links are
explicit Host authority fixtures, not a claim that these tests execute a tool.
"""
import hashlib
from dataclasses import replace

import pytest
import simple_harness.runtime as h
from simple_harness.contracts import fingerprint_json
import simple_harness_memory as m
from simple_harness_memory.core.short_horizon import (
    ShortHorizonIndexError, build_short_horizon_chunks, resolve_authorized_public_text,
)
from tests.integration.test_short_horizon_repository_v5 import (
    NOW, PRINCIPAL, _Authority, _disclosure, _registration,
)


def group(texts, roles):
    """Rebind each exact public source and one shared ordered group manifest."""
    manifest = fingerprint_json({"items": [
        {"ordinal": i, "role": role, "text_hash": hashlib.sha256(text.encode()).hexdigest()}
        for i, (text, role) in enumerate(zip(texts, roles, strict=True), 1)
    ]})
    pairs = []
    kinds = {"user": h.EvidenceSourceKind.USER_MESSAGE,
             "assistant": h.EvidenceSourceKind.ASSISTANT_MESSAGE,
             "tool": h.EvidenceSourceKind.TOOL_RESULT}
    provenances = {"user": h.EvidenceProvenance.AUTHENTICATED_USER,
                   "assistant": h.EvidenceProvenance.MODEL_OUTPUT,
                   "tool": h.EvidenceProvenance.TRUSTED_TOOL}
    for ordinal, (text, role) in enumerate(zip(texts, roles, strict=True), 1):
        seed, _ = _registration(100 + ordinal)
        payload = {"item_id": f"message-{ordinal}", "public_text": text}
        envelope = replace(seed.envelope, source_kind=kinds[role],
            sanitized_payload=payload, sanitized_hash=fingerprint_json(payload),
            source_hash=fingerprint_json(payload), source_ref=f"complete-group/item-{ordinal}")
        receipt = replace(seed.admission_receipt, envelope_hash=envelope.envelope_hash,
            source_hash=envelope.source_hash, sanitized_hash=envelope.sanitized_hash)
        item = replace(seed.recall_item_authority, envelope_hash=envelope.envelope_hash,
            sanitized_hash=envelope.sanitized_hash, source_hash=envelope.source_hash,
            source_kind=envelope.source_kind, item_ordinal=ordinal, item_id=f"message-{ordinal}",
            actor_role=h.EvidenceActorRole(role), provenance=provenances[role])
        link = None if role != "tool" else h.ConversationToolCausalLink(
            f"call-{ordinal}", "tool_search", ordinal - 1, f"host-tool-terminal-{ordinal}",
            fingerprint_json({"call": ordinal, "outcome": "succeeded"}))
        metadata = replace(seed.metadata, envelope_hash=envelope.envelope_hash,
            admission_receipt_hash=receipt.receipt_hash, source_hash=envelope.source_hash,
            sanitized_hash=envelope.sanitized_hash, causal_group_id="complete-tool-group",
            causal_group_sequence=1, item_ordinal=ordinal, group_item_count=len(texts),
            ordered_group_manifest_hash=manifest, role=h.ConversationEvidenceRole(role),
            tool_causal_link=link)
        metadata = h.authorize_conversation_public_text(metadata,
            h.AdmittedEvidenceAuthority(envelope, receipt, item))
        metadata_receipt = replace(seed.metadata_receipt, envelope_hash=envelope.envelope_hash,
            admission_receipt_hash=receipt.receipt_hash, source_hash=envelope.source_hash,
            sanitized_hash=envelope.sanitized_hash, metadata_hash=metadata.metadata_hash)
        registration = h.ConversationEvidenceRegistration(seed.registration_id, envelope, receipt,
            metadata, metadata_receipt, item)
        reference = h.ConversationEvidenceRegistrationRef(registration.registration_id,
            registration.registration_hash, envelope.evidence_id, envelope.envelope_hash)
        pairs.append((registration, reference))
    return tuple(pairs)


class Authority(_Authority):
    async def is_evidence_suppressed(self, *, evidence_id, subject):
        return False


async def ingest(manager, pairs):
    for reg, ref in pairs:
        await manager.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
        assert await manager.register_conversation_evidence(ref) == ref


@pytest.mark.parametrize("assistant", ["", "Search capabilities"])
async def test_complete_tool_group_public_registration_sources_reopen_forget(tmp_path, assistant):
    roles = ("user", "assistant", "tool", "assistant", "tool", "assistant")
    texts = ("quartznebula preference", assistant, "capability one", assistant, "capability two", "done")
    first = group(texts, roles)
    # Real default recent budget remains ten; older full group becomes eligible.
    recent = tuple(_registration(i) for i in range(2, 12))
    pairs = first + recent
    authority = Authority(tuple(reg for reg, _ in pairs))
    kwargs = dict(clock=lambda: NOW, conversation_evidence_authority=authority)
    path = tmp_path / "memory.db"
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        await ingest(manager, pairs)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 1
        result = await manager.recall_short_horizon(principal=PRINCIPAL,
            query="quartznebula", disclosure_context=_disclosure())
        assert len(result.hits) == 1
        hit = result.hits[0]
        assert hit.content == "\n".join(f"{role}: {text}" for role, text in zip(roles, texts, strict=True))
        binding = m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
        before = await manager.resolve_short_horizon_sources(principal=PRINCIPAL,
            disclosure_context=_disclosure(), bindings=(binding,))
        refs = before.items[0].source_refs
        assert before.items[0].complete and tuple(ref.role for ref in refs) == roles
        assert tuple(ref.item_ordinal for ref in refs) == tuple(range(1, 7))
        assert tuple(ref.registration_hash for ref in refs) == tuple(reg.registration_hash for reg, _ in first)
        links = [reg.metadata.tool_causal_link for reg, _ in first if reg.metadata.role is h.ConversationEvidenceRole.TOOL]
        assert [link.parent_item_ordinal for link in links] == [2, 4]
        assert first[3][0].envelope.sanitized_payload["public_text"] == assistant
        # Pure projection and persistent projection must retain identical bytes.
        chunks = await build_short_horizon_chunks(tuple(ref for _, ref in pairs), authority=authority, now=NOW)
        assert len(chunks) == 1 and chunks[0].content == hit.content
        await manager.close()
        manager = await m.build_human_memory_v7(path, **kwargs)
        await ingest(manager, pairs)  # idempotent public replay, no missing members
        assert await manager.resolve_short_horizon_sources(principal=PRINCIPAL,
            disclosure_context=_disclosure(), bindings=(binding,)) == before
        await manager.suppress(principal=PRINCIPAL, request=m.SuppressionRequest(
            "forget-tool", PRINCIPAL.actor_id, m.SuppressionScopeKind.EVIDENCE,
            first[2][0].envelope.evidence_id, "user_forget", NOW))
        assert not (await manager.recall_short_horizon(principal=PRINCIPAL,
            query="quartznebula", disclosure_context=_disclosure())).hits
        after = await manager.resolve_short_horizon_sources(principal=PRINCIPAL,
            disclosure_context=_disclosure(), bindings=(binding,))
        assert not after.items[0].visible and after.items[0].source_refs == ()
    finally:
        await manager.close()


async def test_empty_only_group_has_no_synthetic_role_hit(tmp_path):
    empty = group(("",), ("assistant",))
    pairs = empty + tuple(_registration(i) for i in range(2, 12))
    authority = Authority(tuple(reg for reg, _ in pairs))
    manager = await m.build_human_memory_v7(tmp_path / "empty.db", clock=lambda: NOW,
        conversation_evidence_authority=authority)
    try:
        await ingest(manager, pairs)
        assert (await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)).projected_chunk_count == 0
        assert not (await manager.recall_short_horizon(principal=PRINCIPAL,
            query="assistant", disclosure_context=_disclosure())).hits
        assert await build_short_horizon_chunks(tuple(ref for _, ref in pairs), authority=authority, now=NOW) == ()
    finally:
        await manager.close()


@pytest.mark.parametrize("role,text", [("user", ""), ("user", " \t\n"),
    ("assistant", " \t"), ("assistant", "bad\x00text"), ("assistant", "界" * 349526)],
    ids=["empty-user", "blank-user", "blank-assistant", "nul-assistant", "utf8-over-limit"])
async def test_original_blank_nul_and_utf8_byte_limits_remain(tmp_path, role, text):
    pairs = group((text,), (role,))
    authority = Authority(tuple(reg for reg, _ in pairs))
    manager = await m.build_human_memory_v7(tmp_path / "rejected.db", clock=lambda: NOW,
        conversation_evidence_authority=authority)
    try:
        reg, ref = pairs[0]
        await manager.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
        with pytest.raises(ShortHorizonIndexError, match="non-blank, bounded, and contain no NUL"):
            await manager.register_conversation_evidence(ref)
    finally:
        await manager.close()


def test_empty_text_still_requires_exact_hash_and_valid_identifier():
    reg, _ = group(("",), ("assistant",))[0]
    with pytest.raises(ShortHorizonIndexError, match="hash differs"):
        resolve_authorized_public_text(reg.envelope.sanitized_payload,
            replace(reg.metadata, public_text_hash="0" * 64))
    with pytest.raises(ValueError):
        replace(reg.metadata, primary_conversation_id="")
