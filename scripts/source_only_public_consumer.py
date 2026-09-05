"""Installed public consumer. Synthetic Host authority inputs; real SDK database/queue/selection.
Actual Host two-message lineage and11 completed groups are verified separately in Host tests.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import simple_harness as h
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

import simple_harness_memory as m

NOW = 1_000_000.0


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
        source_kind=EvidenceSourceKind.ASSISTANT_MESSAGE,
        source_ref=f"turn-{sequence}/assistant",
        source_hash=fingerprint_json({"role": "assistant", "content": payload["public_text"]}),
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
        ordered_group_manifest_hash=fingerprint_json({"items": [envelope.envelope_hash]}),
        role=ConversationEvidenceRole.ASSISTANT,
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
            actor_role=EvidenceActorRole.ASSISTANT,
            provenance=EvidenceProvenance.MODEL_OUTPUT,
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


class Trap:
    calls = 0

    async def analyze_memory(self, request):
        self.calls += 1
        raise AssertionError("source-only scheduled analysis")

    async def verify_analysis_delivery(self, request, result):
        self.calls += 1
        raise AssertionError("source-only requested delivery")


async def run(output, *, installed=True):
    output.mkdir(parents=True, exist_ok=False)
    assert m.__version__ == "0.6.8"
    if installed:
        assert Path(m.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        assert Path(h.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    pairs = tuple(_registration(i) for i in range(1, 12))
    authority = _Authority(tuple(x[0] for x in pairs))
    trap = Trap()
    now = [NOW]
    principal = m.MemoryPrincipal("actor-1", "actor-1", "actor-1", "session-1")
    config = m.MemoryJobWorkerConfig(
        2,
        0.01,
        0.0,
        10.0,
        1,
        (),
        65536,
        h.AnalysisBudget(4096, 1024, 30000, 1000000),
        "prompt-1",
        "result-1",
        "policy-1",
        "validator-1",
        "provider-1",
        "model-1",
        "a" * 64,
    )
    kwargs = dict(
        clock=lambda: now[0],
        conversation_evidence_authority=authority,
        analysis_delivery_authority=trap,
    )
    manager = await m.build_human_memory_v7(output / "source.db", **kwargs)
    first_receipts = []

    async def idle():
        runner = m.DurableMemoryJobRunner(
            manager.backend, trap, trap, config, "public-source-consumer", lambda: now[0]
        )
        assert str(await runner.run_once()) == "idle"
        assert trap.calls == 0

    try:
        await manager.register_principal_owner(
            principal, m.MemoryScope.personal(principal.actor_id)
        )
        for reg, ref in pairs:
            receipt = await manager.admit_evidence_source(
                principal=principal, envelope=reg.envelope, receipt=reg.admission_receipt
            )
            assert type(receipt) is m.EvidenceSourceAdmissionReceipt
            assert receipt.accepted_at == NOW
            assert not {"mutation_job_id", "outbox_id"} & receipt.to_json().keys()
            first_receipts.append(receipt)
            await manager.register_conversation_evidence(ref)
        await idle()
        built = await manager.rebuild_short_horizon_projection(principal=principal)
        assert built.projected_chunk_count == 1
        result = await manager.recall_short_horizon(
            principal=principal, query="Project alpha", disclosure_context=_disclosure()
        )
        assert len(result.hits) == 1
        hit = result.hits[0]
        assert hit.content == "assistant: Project alpha note 1"
        assert hashlib.sha256(hit.content.encode()).hexdigest() == hit.content_hash
        binding = m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
        snapshot = await manager.check_history_visibility(
            principal=principal, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert snapshot.items[0].visible
        # Full ingestion is explicitly forbidden after source-only, not an implicit enqueue.
        try:
            await manager.ingest_committed_evidence(
                pairs[0][0].envelope, pairs[0][0].admission_receipt
            )
        except m.MemoryIdempotencyConflict as exc:
            assert str(exc) == "evidence_admission_mode_conflict"
        else:
            raise AssertionError("cross-mode promotion")
        await idle()
    finally:
        await manager.close()
    now[0] += 5
    manager = await m.build_human_memory_v7(output / "source.db", **kwargs)
    try:
        for (reg, _), first in zip(pairs, first_receipts, strict=True):
            assert (
                await manager.admit_evidence_source(
                    principal=principal, envelope=reg.envelope, receipt=reg.admission_receipt
                )
                == first
            )
        await idle()
        await manager.suppress(
            principal=principal,
            request=m.SuppressionRequest(
                "forget-source",
                principal.actor_id,
                m.SuppressionScopeKind.EVIDENCE,
                pairs[0][0].envelope.evidence_id,
                "user_forget",
                now[0],
            ),
        )
        snapshot = await manager.check_history_visibility(
            principal=principal, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert not snapshot.items[0].visible
    finally:
        await manager.close()
    manager = await m.build_human_memory_v7(output / "source.db", **kwargs)
    try:
        snapshot = await manager.check_history_visibility(
            principal=principal, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert not snapshot.items[0].visible
        await idle()
    finally:
        await manager.close()
    result = dict(
        status="PASS",
        installed=installed,
        version=m.__version__,
        source_receipts=11,
        analysis_calls=trap.calls,
        selected_old_groups=1,
        newest_excluded=10,
        stages=[
            "source_admission",
            "idle",
            "real_selection",
            "current_visibility",
            "cross_mode_reject",
            "reopen_exact_receipt",
            "source_forget",
            "reopen_deny",
        ],
    )
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1])))
