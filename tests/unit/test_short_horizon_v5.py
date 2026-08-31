# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest
from simple_harness.contracts import FrozenJsonValue, JsonValue, fingerprint_json
from simple_harness.runtime import (
    EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    AdmittedEvidenceAuthority,
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
    EvidenceActorRole,
    EvidenceItemAuthority,
    EvidenceProvenance,
    EvidenceReasonCode,
    EvidenceSourceKind,
    InformationAttribute,
    IntendedAudience,
    PrivacyClass,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    authorize_conversation_public_text,
)

from simple_harness_memory.core.short_horizon import (
    SHORT_HORIZON_RETENTION_SECONDS,
    ShortHorizonIndexError,
    build_short_horizon_chunks,
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
        "private_note": f"never-index-this-{sequence}",
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
    item_authority = EvidenceItemAuthority(
        schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
        authority_id=f"item-authority-{sequence}",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        source_hash=envelope.source_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id=f"message-{sequence}",
        item_json_pointer="/public_text",
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=EvidenceActorRole.USER,
        provenance=EvidenceProvenance.AUTHENTICATED_USER,
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(InformationAttribute.WORK,),
        classification_authority_ref="classification-authority-1",
        issuer_ref="host-evidence-registry",
    )
    metadata = authorize_conversation_public_text(
        ConversationEvidenceMetadata(
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
        ),
        AdmittedEvidenceAuthority(envelope, admission, item_authority),
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
        item_authority,
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
    assert chunks[0].effective_privacy_class is PrivacyClass.PERSONAL
    assert chunks[0].information_attributes == (InformationAttribute.WORK,)
    assert chunks[0].classification_authority_refs == ("classification-authority-1",)
    assert "never-index-this" not in chunks[0].content
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
