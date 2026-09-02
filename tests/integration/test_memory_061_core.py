"""Memory 0.6.1 核心（S5b Task 4a）：设计冻结 §8 六项的 oracle。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import pytest
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceReasonCode,
    EvidenceRef,
    EvidenceSourceKind,
    IntendedAudience,
    PrivacyClass,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory import MemoryManager
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.mutations import InformationClassificationPolicy
from simple_harness_memory.embedders.mock import HashEmbedder

SUBJECT = "actor-1"
HOST_POLICIES = frozenset(
    {"credential-filter/v1", "host-public-turn/v1", "host-typed-ingress/v1"}
)


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure(run_id: str = "run-1") -> DisclosureContext:
    return DisclosureContext(
        run_id,
        SUBJECT,
        DeliveryRecipient.USER_SELF,
        SUBJECT,
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "host-authority",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _evidence(
    index: int,
    *,
    filter_policy: str = "credential-filter/v1",
    text: str | None = None,
    run_id: str = "run-1",
) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {
        "item_id": f"message-{index}",
        "public_text": text if text is not None else f"preference-{index}",
    }
    envelope = SanitizedEvidenceEnvelope(
        f"evidence-{index}",
        run_id,
        SUBJECT,
        EvidenceSourceKind.USER_MESSAGE,
        f"turn-{index}/user",
        f"{index % 10}" * 64,
        payload,
        _hash(payload),
        filter_policy,
        (),
        _disclosure(run_id),
        (EvidenceRef(f"source-event-{index}", f"{(index + 2) % 10}" * 64, 1),),
    )
    receipt = SanitizedEvidenceReceipt(
        f"admission-{index}",
        envelope.run_id,
        envelope.subject,
        envelope.evidence_id,
        envelope.envelope_hash,
        envelope.source_hash,
        envelope.sanitized_hash,
        envelope.filter_policy_version,
        True,
        (EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        envelope.disclosure_context,
        envelope.evidence_refs,
        10.0,
    )
    return envelope, receipt


def _classification_policy() -> InformationClassificationPolicy:
    return InformationClassificationPolicy(
        policy_id="memory-classification-policy",
        policy_version="1",
        authority_ref="memory-policy-registry:classification/v1",
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(),
    )


async def _build(db_path: Path, **kwargs: Any) -> MemoryManager:
    return await MemoryManager.build_human_memory_v7(
        db_path,
        classification_policy=_classification_policy(),
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
        **kwargs,
    )


async def _count(manager: MemoryManager, sql: str, params: tuple[object, ...] = ()) -> int:
    backend = cast(Any, manager.backend)
    async with backend.connection.execute(sql, params) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


# --------------------------------------------------------------------------- §8.1


@pytest.mark.asyncio
async def test_builder_passes_supported_filter_policies_to_backend(tmp_path: Path) -> None:
    manager = await _build(tmp_path / "policies.db", supported_filter_policies=HOST_POLICIES)
    try:
        receipt = await manager.ingest_committed_evidence(
            *_evidence(1, filter_policy="host-public-turn/v1")
        )
        assert receipt.evidence_id == "evidence-1"
        typed = await manager.ingest_committed_evidence(
            *_evidence(2, filter_policy="host-typed-ingress/v1")
        )
        assert typed.evidence_id == "evidence-2"
        assert await _count(manager, "SELECT COUNT(*) FROM evidence_envelopes") == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_builder_default_still_rejects_host_filter_policies(tmp_path: Path) -> None:
    manager = await _build(tmp_path / "default-policies.db")
    try:
        with pytest.raises(MemoryValidationError, match="evidence_filter_policy_unsupported"):
            await manager.ingest_committed_evidence(
                *_evidence(1, filter_policy="host-public-turn/v1")
            )
        accepted = await manager.ingest_committed_evidence(*_evidence(2))
        assert accepted.evidence_id == "evidence-2"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_builder_rejects_blank_filter_policy_set(tmp_path: Path) -> None:
    with pytest.raises(MemoryValidationError):
        await _build(tmp_path / "blank-policies.db", supported_filter_policies=frozenset({" "}))
