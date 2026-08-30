# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest
from simple_harness.contracts import FrozenJsonValue, JsonValue, fingerprint_json
from simple_harness.runtime import (
    ConversationEvidenceMetadata,
    ConversationEvidenceMetadataReceipt,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    ConversationEvidenceRole,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceReasonCode,
    EvidenceSourceKind,
    IntendedAudience,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory.core.short_horizon import (
    SHORT_HORIZON_RETENTION_SECONDS,
    ExactVectorGenerationCache,
    PermissionFilteredFtsCandidates,
    ShortHorizonDegradationCode,
    ShortHorizonIndexError,
    ShortHorizonSearchRow,
    build_short_horizon_chunks,
    search_short_horizon,
)


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        run_id="run-1",
        subject="actor-1",
        recipient=DeliveryRecipient.USER_SELF,
        recipient_id="actor-1",
        intended_audience=IntendedAudience.USER_SELF,
        purpose=DisclosurePurpose.PERSONALIZATION,
        source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY,
        generation=DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _registration(
    sequence: int,
    *,
    occurred_at: float,
    group_item_count: int = 1,
    conversation_id: str = "primary-conversation",
) -> tuple[ConversationEvidenceRegistration, ConversationEvidenceRegistrationRef]:
    evidence_id = f"evidence-{sequence}"
    payload: dict[str, JsonValue] = {
        "item_id": f"message-{sequence}",
        "public_text": f"Python project note {sequence}",
    }
    envelope = SanitizedEvidenceEnvelope(
        evidence_id=evidence_id,
        run_id="run-1",
        subject="actor-1",
        source_kind=EvidenceSourceKind.USER_MESSAGE,
        source_ref=f"turn-{sequence}/user",
        source_hash=f"{sequence % 10}" * 64,
        sanitized_payload=cast(Mapping[str, FrozenJsonValue], payload),
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(),
        evidence_refs=(),
    )
    admission = SanitizedEvidenceReceipt(
        receipt_id=f"admission-{sequence}",
        run_id=envelope.run_id,
        subject=envelope.subject,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=_disclosure(),
        evidence_refs=(),
        admitted_at=occurred_at,
    )
    metadata = ConversationEvidenceMetadata(
        metadata_id=f"metadata-{sequence}",
        authority_issuer_id="host-conversation-registry",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_id=admission.receipt_id,
        admission_receipt_hash=admission.receipt_hash,
        run_id=envelope.run_id,
        subject=envelope.subject,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        conversation_id=conversation_id,
        primary_conversation_id="primary-conversation",
        causal_group_id=f"group-{sequence}",
        causal_group_sequence=sequence,
        item_ordinal=1,
        group_item_count=group_item_count,
        ordered_group_manifest_hash=f"{(sequence + 1) % 10}" * 64,
        role=ConversationEvidenceRole.USER,
        occurred_at=occurred_at,
        task_scope_id=f"task-{sequence % 2}",
        tool_causal_link=None,
        entities=("python",),
    )
    metadata_receipt = ConversationEvidenceMetadataReceipt(
        receipt_id=f"metadata-receipt-{sequence}",
        metadata_id=metadata.metadata_id,
        authority_issuer_id=metadata.authority_issuer_id,
        evidence_id=metadata.evidence_id,
        envelope_hash=metadata.envelope_hash,
        admission_receipt_id=metadata.admission_receipt_id,
        admission_receipt_hash=metadata.admission_receipt_hash,
        run_id=metadata.run_id,
        subject=metadata.subject,
        source_hash=metadata.source_hash,
        sanitized_hash=metadata.sanitized_hash,
        metadata_hash=metadata.metadata_hash,
        issuer_ref=metadata.authority_issuer_id,
        accepted=True,
    )
    registration = ConversationEvidenceRegistration(
        f"registration-{sequence}",
        envelope,
        admission,
        metadata,
        metadata_receipt,
    )
    reference = ConversationEvidenceRegistrationRef(
        registration.registration_id,
        registration.registration_hash,
        envelope.evidence_id,
        envelope.envelope_hash,
    )
    return registration, reference


class _ProjectionAuthority:
    def __init__(
        self,
        registrations: tuple[ConversationEvidenceRegistration, ...],
        *,
        suppressed: frozenset[str] = frozenset(),
    ) -> None:
        self._registrations = {item.registration_id: item for item in registrations}
        self._suppressed = suppressed

    async def resolve_conversation_registration(
        self, reference: ConversationEvidenceRegistrationRef
    ) -> ConversationEvidenceRegistration:
        return self._registrations[reference.registration_id]

    async def is_evidence_suppressed(self, *, evidence_id: str, subject: str) -> bool:
        assert subject == "actor-1"
        return evidence_id in self._suppressed


@pytest.mark.asyncio
async def test_only_authority_registered_groups_outside_recent_ten_are_projected() -> None:
    now = 1_000_000.0
    pairs = tuple(_registration(i, occurred_at=now - i) for i in range(1, 13))
    registrations = tuple(item[0] for item in pairs)
    refs = tuple(item[1] for item in pairs)

    chunks = await build_short_horizon_chunks(
        refs,
        authority=_ProjectionAuthority(registrations),
        now=now,
    )

    assert [item.causal_group_sequence for item in chunks] == [1, 2]
    assert chunks[0].evidence_refs == ("evidence-1",)
    assert chunks[0].role_sequence == ("user",)
    assert chunks[0].task_scope_ids == ("task-1",)
    assert chunks[0].entity_refs == ("python",)
    assert chunks[0].expires_at == now - 1 + SHORT_HORIZON_RETENTION_SECONDS


@pytest.mark.asyncio
async def test_five_day_boundary_is_inclusive_and_suppression_only_removes_projection() -> None:
    now = 1_000_000.0
    boundary = _registration(1, occurred_at=now - SHORT_HORIZON_RETENTION_SECONDS)
    expired = _registration(2, occurred_at=now - SHORT_HORIZON_RETENTION_SECONDS - 0.001)
    suppressed = _registration(3, occurred_at=now - 10)
    registrations = (boundary[0], expired[0], suppressed[0])
    authority = _ProjectionAuthority(
        registrations,
        suppressed=frozenset({suppressed[0].envelope.evidence_id}),
    )

    chunks = await build_short_horizon_chunks(
        (boundary[1], expired[1], suppressed[1]),
        authority=authority,
        now=now,
        recent_group_limit=0,
    )

    assert [item.evidence_refs for item in chunks] == [("evidence-1",)]
    # The authority still resolves both excluded raw registrations; the builder deletes nothing.
    assert await authority.resolve_conversation_registration(expired[1]) is expired[0]
    assert await authority.resolve_conversation_registration(suppressed[1]) is suppressed[0]


@pytest.mark.asyncio
async def test_forged_secondary_or_incomplete_registration_is_fail_closed() -> None:
    now = 1_000_000.0
    complete = _registration(1, occurred_at=now - 1)
    forged_ref = replace(complete[1], registration_hash="f" * 64)
    authority = _ProjectionAuthority((complete[0],))
    with pytest.raises(ValueError, match="reference differs"):
        await build_short_horizon_chunks(
            (forged_ref,), authority=authority, now=now, recent_group_limit=0
        )

    secondary = _registration(
        2,
        occurred_at=now - 2,
        conversation_id="secondary-conversation",
    )
    with pytest.raises(ValueError, match="primary conversation"):
        await build_short_horizon_chunks(
            (secondary[1],),
            authority=_ProjectionAuthority((secondary[0],)),
            now=now,
            recent_group_limit=0,
        )

    incomplete = _registration(3, occurred_at=now - 3, group_item_count=2)
    with pytest.raises(ShortHorizonIndexError, match="incomplete"):
        await build_short_horizon_chunks(
            (incomplete[1],),
            authority=_ProjectionAuthority((incomplete[0],)),
            now=now,
            recent_group_limit=0,
        )


class _FtsAuthority:
    def __init__(self, result: PermissionFilteredFtsCandidates, *, delay: float = 0) -> None:
        self.result = result
        self.delay = delay

    async def permission_filtered_fts_candidates(
        self,
        *,
        query: str,
        disclosure_context_hash: str,
        active_generation_id: str,
        now: float,
    ) -> PermissionFilteredFtsCandidates:
        assert query and disclosure_context_hash and active_generation_id and now >= 0
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


def _search_row(
    memory_ref: str, content: str, *, expires_at: float = 200.0
) -> ShortHorizonSearchRow:
    return ShortHorizonSearchRow(
        memory_ref=memory_ref,
        subject="actor-1",
        content=content,
        occurred_at=1.0,
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_stale_vector_generation_degrades_only_to_permission_filtered_fts() -> None:
    context_hash = "a" * 64
    permitted = _search_row("allowed", "python project")
    candidates = PermissionFilteredFtsCandidates(context_hash, "b" * 64, (permitted,))
    cache = ExactVectorGenerationCache(
        generation_id="stale-generation",
        lineage_id="lineage-1",
        memory_refs=("allowed", "private"),
        vectors=((1.0, 0.0), (1.0, 0.0)),
    )

    result = await search_short_horizon(
        "python",
        query_vector=(1.0, 0.0),
        active_generation_id="active-generation",
        cache=cache,
        fts_authority=_FtsAuthority(candidates),
        disclosure_context_hash=context_hash,
        now=100.0,
        limit=5,
        deadline_ms=100,
    )

    assert [hit.memory_ref for hit in result.hits] == ["allowed"]
    assert result.used_generation_id is None
    assert result.degradation_code is ShortHorizonDegradationCode.VECTOR_DEGRADED
    assert result.fts_authority_receipt_hash == "b" * 64


@pytest.mark.asyncio
async def test_active_generation_scan_cannot_read_a_row_omitted_by_permission_authority() -> None:
    context_hash = "a" * 64
    candidates = PermissionFilteredFtsCandidates(
        context_hash,
        "b" * 64,
        (_search_row("allowed", "python"),),
    )
    cache = ExactVectorGenerationCache(
        generation_id="active-generation",
        lineage_id="lineage-1",
        memory_refs=("allowed", "private"),
        vectors=((0.9, 0.1), (1.0, 0.0)),
    )
    result = await search_short_horizon(
        "python",
        query_vector=(1.0, 0.0),
        active_generation_id="active-generation",
        cache=cache,
        fts_authority=_FtsAuthority(candidates),
        disclosure_context_hash=context_hash,
        now=100.0,
        limit=5,
        deadline_ms=100,
    )
    assert [hit.memory_ref for hit in result.hits] == ["allowed"]
    assert result.used_generation_id == "active-generation"
    assert result.degradation_code is None


@pytest.mark.asyncio
async def test_expired_authority_row_and_hard_deadline_fail_closed() -> None:
    context_hash = "a" * 64
    expired = PermissionFilteredFtsCandidates(
        context_hash,
        "b" * 64,
        (_search_row("expired", "python", expires_at=99.0),),
    )
    with pytest.raises(ShortHorizonIndexError, match="expired"):
        await search_short_horizon(
            "python",
            query_vector=(1.0,),
            active_generation_id="active",
            cache=None,
            fts_authority=_FtsAuthority(expired),
            disclosure_context_hash=context_hash,
            now=100.0,
            limit=1,
            deadline_ms=100,
        )

    permitted = PermissionFilteredFtsCandidates(
        context_hash,
        "b" * 64,
        (_search_row("allowed", "python"),),
    )
    timed_out = await search_short_horizon(
        "python",
        query_vector=(1.0,),
        active_generation_id="active",
        cache=None,
        fts_authority=_FtsAuthority(permitted, delay=0.02),
        disclosure_context_hash=context_hash,
        now=100.0,
        limit=1,
        deadline_ms=1,
    )
    assert timed_out.hits == ()
    assert timed_out.fts_authority_receipt_hash is None
    assert timed_out.degradation_code is ShortHorizonDegradationCode.VECTOR_DEGRADED

    with pytest.raises(ShortHorizonIndexError, match="two-second"):
        await search_short_horizon(
            "python",
            query_vector=(1.0,),
            active_generation_id="active",
            cache=None,
            fts_authority=_FtsAuthority(permitted),
            disclosure_context_hash=context_hash,
            now=100.0,
            limit=1,
            deadline_ms=2_001,
        )
