# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
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

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryOwnershipConflict
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.short_horizon import ShortHorizonDegradationCode
from simple_harness_memory.embedders.mock import HashEmbedder

NOW = 1_000_000.0
PRINCIPAL = MemoryPrincipal("actor-1", "actor-1", "actor-1", "session-1")
_OPEN_BACKENDS: list[SQLiteHumanMemoryBackend] = []


@pytest.fixture(autouse=True)
async def _close_failed_test_backends() -> None:
    try:
        yield
    finally:
        while _OPEN_BACKENDS:
            backend = _OPEN_BACKENDS.pop()
            if backend._db is not None:
                with suppress(Exception):
                    await backend.close()


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
    sequence: int, *, authorized: bool = True
) -> tuple[ConversationEvidenceRegistration, ConversationEvidenceRegistrationRef]:
    payload: dict[str, JsonValue] = {
        "item_id": f"message-{sequence}",
        "public_text": f"Project alpha note {sequence}",
        "private_text": f"secret-never-index-{sequence}",
    }
    envelope = SanitizedEvidenceEnvelope(
        evidence_id=f"evidence-{sequence}",
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
    receipt = SanitizedEvidenceReceipt(
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
        admitted_at=NOW - sequence,
    )
    metadata = ConversationEvidenceMetadata(
        metadata_id=f"metadata-{sequence}",
        authority_issuer_id="host-conversation-registry",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        run_id=envelope.run_id,
        subject=envelope.subject,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        conversation_id="primary-conversation",
        primary_conversation_id="primary-conversation",
        causal_group_id=f"group-{sequence}",
        causal_group_sequence=sequence,
        item_ordinal=1,
        group_item_count=1,
        ordered_group_manifest_hash=f"{(sequence + 1) % 10}" * 64,
        role=ConversationEvidenceRole.USER,
        occurred_at=NOW - sequence,
        task_scope_id=f"task-{sequence % 2}",
        tool_causal_link=None,
        entities=("project-alpha",),
    )
    item_authority = None
    if authorized:
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
            required_privacy_class=PrivacyClass.SENSITIVE,
            required_information_attributes=(InformationAttribute.WORK,),
            classification_authority_ref="classification-authority-1",
            issuer_ref="host-evidence-registry",
        )
        metadata = authorize_conversation_public_text(
            metadata, AdmittedEvidenceAuthority(envelope, receipt, item_authority)
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
        receipt,
        metadata,
        metadata_receipt,
        item_authority,
    )
    return registration, ConversationEvidenceRegistrationRef(
        registration.registration_id,
        registration.registration_hash,
        envelope.evidence_id,
        envelope.envelope_hash,
    )


class _Authority:
    def __init__(self, registrations: tuple[ConversationEvidenceRegistration, ...]) -> None:
        self.registrations = {item.registration_id: item for item in registrations}

    async def resolve_conversation_registration(
        self, reference: ConversationEvidenceRegistrationRef
    ) -> ConversationEvidenceRegistration:
        return self.registrations[reference.registration_id]


async def _backend(
    path: Path,
    pairs: tuple[tuple[ConversationEvidenceRegistration, ConversationEvidenceRegistrationRef], ...],
    *,
    embedder: HashEmbedder | None = None,
) -> SQLiteHumanMemoryBackend:
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: NOW,
        conversation_evidence_authority=_Authority(tuple(item[0] for item in pairs)),
        short_horizon_embedder=embedder or HashEmbedder(32),
    )
    await backend.initialize()
    _OPEN_BACKENDS.append(backend)
    for registration, reference in pairs:
        await backend.ingest_committed_evidence(
            registration.envelope, registration.admission_receipt
        )
        await backend.register_conversation_evidence(reference)
    return backend


@pytest.mark.asyncio
async def test_pointer_only_projection_and_repository_owned_generation_reopen(
    tmp_path: Path,
) -> None:
    pairs = tuple(_registration(index) for index in range(1, 13))
    path = tmp_path / "short-horizon.db"
    backend = await _backend(path, pairs)

    built = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert built.projected_chunk_count == 2
    rebuilt = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert rebuilt.projected_chunk_count == 2
    async with backend.connection.execute(
        "SELECT public_text,effective_privacy_class,information_attributes_json,"
        "classification_authority_refs_json FROM short_horizon_chunks ORDER BY chunk_id"
    ) as cursor:
        rows = tuple(await cursor.fetchall())
    assert all("secret-never-index" not in str(row[0]) for row in rows)
    assert {str(row[1]) for row in rows} == {"sensitive"}
    assert {str(row[2]) for row in rows} == {'["work"]'}
    assert {str(row[3]) for row in rows} == {'["classification-authority-1"]'}

    generation = await backend.rebuild_short_horizon_generation()
    assert generation.activated is True
    generation_replay = await backend.rebuild_short_horizon_generation()
    assert generation_replay.generation_id == generation.generation_id
    assert generation_replay.replayed is True
    result = await backend.recall_short_horizon(
        principal=PRINCIPAL,
        query="unmatched-vector-query",
        disclosure_context=_disclosure(),
    )
    assert result.eligible_count == 2
    assert result.fts_count == 0
    assert result.vector_count == 2
    assert result.used_generation_id == generation.generation_id
    assert result.hits
    async with backend.connection.execute(
        "SELECT audit_json FROM short_horizon_audit "
        "WHERE event_kind='recall' AND vector_count=2 LIMIT 1"
    ) as cursor:
        audit_row = await cursor.fetchone()
    assert audit_row is not None
    audit = json.loads(str(audit_row[0]))
    assert audit["details"]["candidate_count"] == 2
    assert len(audit["details"]["eligible"]) == 2
    assert len(audit["details"]["vector_lane"]) == 2
    assert "Project alpha note" not in str(audit)
    assert "secret-never-index" not in str(audit)
    with pytest.raises(MemoryOwnershipConflict):
        await backend.recall_short_horizon(
            principal=MemoryPrincipal("other", "actor-1", "actor-1", "session-1"),
            query="Project",
            disclosure_context=_disclosure(),
        )
    await backend.close()

    reopened = SQLiteHumanMemoryBackend(
        path, now=lambda: NOW, short_horizon_embedder=HashEmbedder(32)
    )
    await reopened.initialize()
    _OPEN_BACKENDS.append(reopened)
    replay = await reopened.recall_short_horizon(
        principal=PRINCIPAL,
        query="unmatched-vector-query",
        disclosure_context=_disclosure(),
    )
    assert replay.used_generation_id == generation.generation_id
    await reopened.close()


@pytest.mark.asyncio
async def test_unapproved_registration_is_durable_but_never_projected_and_cleanup_is_derived(
    tmp_path: Path,
) -> None:
    pairs = tuple(_registration(index) for index in range(1, 12)) + (
        _registration(12, authorized=False),
    )
    backend = await _backend(tmp_path / "unauthorized.db", pairs)
    built = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert built.projected_chunk_count == 1
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM conversation_evidence_registrations"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 12
    removed = await backend.cleanup_short_horizon(principal=PRINCIPAL, now=NOW + 5 * 24 * 60 * 60)
    assert removed == 1
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(*) FROM conversation_evidence_registrations),"
        "(SELECT COUNT(*) FROM evidence_envelopes),"
        "(SELECT COUNT(*) FROM short_horizon_chunks),"
        "(SELECT COUNT(*) FROM short_horizon_fts)"
    ) as cursor:
        assert tuple(await cursor.fetchone()) == (12, 12, 0, 0)
    await backend.close()


class _SlowEmbedder(HashEmbedder):
    async def embed(self, text: str) -> list[float]:
        await asyncio.sleep(1)
        return await super().embed(text)


@pytest.mark.asyncio
async def test_stale_generation_and_slow_query_embedding_degrade_without_stale_read(
    tmp_path: Path,
) -> None:
    pairs = tuple(_registration(index) for index in range(1, 13))
    backend = await _backend(tmp_path / "deadline.db", pairs)
    await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    await backend.rebuild_short_horizon_generation()
    added, added_ref = _registration(13)
    authority = cast(_Authority, backend._conversation_evidence_authority)
    authority.registrations[added.registration_id] = added
    await backend.ingest_committed_evidence(added.envelope, added.admission_receipt)
    await backend.register_conversation_evidence(added_ref)
    await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    stale = await backend.recall_short_horizon(
        principal=PRINCIPAL,
        query="Project",
        disclosure_context=_disclosure(),
    )
    assert stale.vector_count == 0
    assert stale.degradation_code is ShortHorizonDegradationCode.STALE_ACTIVE_GENERATION

    await backend.rebuild_short_horizon_generation()
    backend._short_horizon_embedder = _SlowEmbedder(32)
    started = time.monotonic()
    result = await backend.recall_short_horizon(
        principal=PRINCIPAL,
        query="Project",
        disclosure_context=_disclosure(),
        deadline_ms=30,
    )
    assert time.monotonic() - started < 0.25
    assert result.vector_count == 0
    assert result.degradation_code is ShortHorizonDegradationCode.DEADLINE_EXCEEDED
    assert result.fts_count == 3
    await backend.close()


@pytest.mark.asyncio
async def test_projection_fault_rolls_back_derived_rows_and_audit(tmp_path: Path) -> None:
    pairs = tuple(_registration(index) for index in range(1, 13))
    backend = await _backend(tmp_path / "fault.db", pairs)
    await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(*) FROM short_horizon_chunks),"
        "(SELECT COUNT(*) FROM short_horizon_audit)"
    ) as cursor:
        before = tuple(await cursor.fetchone())
    added, added_ref = _registration(13)
    authority = cast(_Authority, backend._conversation_evidence_authority)
    authority.registrations[added.registration_id] = added
    await backend.ingest_committed_evidence(added.envelope, added.admission_receipt)
    await backend.register_conversation_evidence(added_ref)

    def inject(point: str) -> None:
        if point == "short_horizon.projection.before_commit":
            raise RuntimeError("injected")

    backend._fault_injector = inject
    with pytest.raises(RuntimeError, match="injected"):
        await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(*) FROM short_horizon_chunks),"
        "(SELECT COUNT(*) FROM short_horizon_audit)"
    ) as cursor:
        assert tuple(await cursor.fetchone()) == before
    backend._fault_injector = None
    await backend.close()


@pytest.mark.asyncio
async def test_close_fails_closed_on_projection_or_vector_tamper(tmp_path: Path) -> None:
    pairs = tuple(_registration(index) for index in range(1, 13))
    projection = await _backend(tmp_path / "projection-tamper.db", pairs)
    await projection.rebuild_short_horizon_projection(principal=PRINCIPAL)
    await projection.connection.execute(
        "UPDATE short_horizon_chunks SET public_text='tampered',content_hash=?",
        ("0" * 64,),
    )
    with pytest.raises(MemoryCorruptionError, match="chunk projection differs"):
        await projection.close()

    vector = await _backend(tmp_path / "vector-tamper.db", pairs)
    await vector.rebuild_short_horizon_projection(principal=PRINCIPAL)
    await vector.rebuild_short_horizon_generation()
    await vector.connection.execute(
        "UPDATE short_horizon_vectors SET embedding=?",
        (b"not-json",),
    )
    with pytest.raises(MemoryCorruptionError, match="vectors are invalid"):
        await vector.close()
