"""Native terminal false-positive oracle; synthetic tokens never use real secrets."""

import hashlib
import json
from dataclasses import replace

import pytest
import simple_harness as h

import simple_harness_memory as m
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _classification_policy,
    _disclosure,
    _principal,
)

PUBLIC = (
    "skill_resource",
    "skill-catalog",
    "skill-catalog-v1",
    "product-skill-catalog",
    "product-skill-catalog-v1",
)
VECTORS = {
    "skill_resource": "db03bd1a4e9e79aa184f32f289ea67f6f9d570c12b0fdb9e7135639fa41410c7",
    "product-skill-catalog": "4c0a867deb52833ddddf0e02d9e526d22cfdec7e174f0c61f5b9e5935a29a107",
    "product-skill-catalog-v1": "e5d02bfbda6a76d25068071d409bd9fd99b0114a695ee04218bc21ff2d9b1c12",
}
TOKENS = tuple(
    prefix + "FAKE_ONLY_123456789"
    for prefix in (
        "sk-",
        "sk_",
        "key_",
        "tsk_",
        "key-",
        "tsk-",
        "sk",
        "key",
        "tsk",
    )
)
REJECTED = (
    *TOKENS,
    "foo-skill_resource",
    "skill_resourceX",
    "key-skill-catalog",
    "product-skill-catalog-v10",
    "skill_resource_FAKE_ONLY_123456789",
    "skill_resourceé",
    "skill_resource-",
    "keyword_private_123456789",
    "skill_unknown_private_123456789",
    "skill_resource\n" + TOKENS[0],
    TOKENS[0] + ", skill_resource",
    "Bearer skill_resource",
    "Bearer FAKE_ONLY_123456789",
    "AKIA" + "0" * 16,
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
)


def pair(payload):
    envelope, receipt = _admitted(source_kind=h.EvidenceSourceKind.RUNTIME_EVENT)
    digest = hashlib.sha256(h.canonical_json(payload).encode()).hexdigest()
    envelope = replace(
        envelope, sanitized_payload=payload, sanitized_hash=digest, source_hash=digest
    )
    receipt = replace(
        receipt, envelope_hash=envelope.envelope_hash, source_hash=digest, sanitized_hash=digest
    )
    return envelope, receipt


async def manager(path):
    result = await m.build_human_memory_v7(
        path, classification_policy=_classification_policy(), clock=lambda: 20.0
    )
    await result.register_principal_owner(_principal(), m.MemoryScope.personal("actor-1"))
    return result


async def check(manager, binding, *, principal=None):
    return await manager.check_history_visibility(
        principal=principal or _principal(),
        disclosure_context=replace(_disclosure(), purpose=h.DisclosurePurpose.USER_REVIEW),
        bindings=(binding,),
    )


def test_independent_public_source_vectors():
    for word, expected in VECTORS.items():
        assert hashlib.sha256(word.encode()).hexdigest() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("word", PUBLIC)
async def test_public_terminal_source_admission_history_reopen_and_suppression(tmp_path, word):
    path = tmp_path / "memory.db"
    payload = {"messages": [{"role": "tool", "content": json.dumps({"kind": word})}]}
    envelope, receipt = pair(payload)
    original = (envelope.to_json(), receipt.to_json())
    binding = m.HistoryEvidenceBinding(envelope, receipt)
    current = await manager(path)
    try:
        assert (await check(current, binding)).items[0].visible  # cold, no job or fake SDK Run
        first = await current.admit_evidence_source(
            principal=_principal(), envelope=envelope, receipt=receipt
        )
        assert (
            await current.admit_evidence_source(
                principal=_principal(), envelope=envelope, receipt=receipt
            )
            == first
        )
        await current.close()
        current = await manager(path)
        assert (await check(current, binding)).items[0].visible
        exported = await current.backend.export_ingested_evidence(envelope.evidence_id)
        assert exported.envelope.to_json() == original[0]
        assert exported.admission_receipt.to_json() == original[1]
        await current.backend.suppress(
            m.SuppressionRequest(
                "forget",
                "actor-1",
                m.SuppressionScopeKind.EVIDENCE,
                envelope.evidence_id,
                "user_forget",
                20.0,
            ),
            principal=_principal(),
        )
        await current.close()
        current = await manager(path)
        decision = (await check(current, binding)).items[0]
        assert not decision.visible and decision.reason == "history_suppressed"
        assert (envelope.to_json(), receipt.to_json()) == original
    finally:
        await current.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", REJECTED)
async def test_actual_format_and_boundary_attacks_rejected_before_sql(tmp_path, value):
    current = await manager(tmp_path / "reject.db")
    envelope, receipt = pair({"messages": [{"role": "tool", "content": value}]})
    trace = []
    await current.backend.connection.set_trace_callback(trace.append)
    try:
        with pytest.raises(m.MemoryValidationError, match="credential_boundary_rejected"):
            await check(current, m.HistoryEvidenceBinding(envelope, receipt))
        assert trace == []
        with pytest.raises(m.MemoryValidationError, match="credential_boundary_rejected"):
            await current.admit_evidence_source(
                principal=_principal(), envelope=envelope, receipt=receipt
            )
        assert trace == []
    finally:
        await current.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", ["Authorization", "OPENAI_API_KEY", "password", "cookie", "hidden_reasoning"]
)
async def test_safe_label_does_not_override_forbidden_nested_field(tmp_path, key):
    current = await manager(tmp_path / "key.db")
    envelope, receipt = pair({"nested": [{key: "skill_resource"}]})
    trace = []
    await current.backend.connection.set_trace_callback(trace.append)
    try:
        with pytest.raises(m.MemoryValidationError, match="credential_boundary_rejected"):
            await check(current, m.HistoryEvidenceBinding(envelope, receipt))
        assert trace == []
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_safe_label_does_not_authorize_tampered_receipt_or_wrong_subject(tmp_path):
    current = await manager(tmp_path / "binding.db")
    envelope, receipt = pair({"content": "skill_resource"})
    try:
        with pytest.raises((ValueError, m.MemoryValidationError)):
            await check(
                current,
                m.HistoryEvidenceBinding(envelope, replace(receipt, envelope_hash="f" * 64)),
            )
        with pytest.raises((ValueError, m.MemoryValidationError)):
            changed = replace(envelope, sanitized_payload={"content": "skill-catalog"})
            await check(current, m.HistoryEvidenceBinding(changed, receipt))
        denied = await check(
            current, m.HistoryEvidenceBinding(envelope, receipt), principal=_principal("other")
        )
        assert not denied.items[0].visible
        assert denied.items[0].reason == "history_subject_mismatch"
    finally:
        await current.close()
