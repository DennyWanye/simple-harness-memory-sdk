"""Protocol-only oracle: literal vectors fixed before carrier implementation.

These tests do not claim duplicate-source suppression or Host admission works.
"""

from dataclasses import FrozenInstanceError, replace
import hashlib
import inspect
import json

import pytest

from simple_harness_memory import (
    HistoryForgetCutReceipt,
    HistorySourceAuthorityPort,
    HistorySourceNamespace,
    HistorySourceOriginReceipt,
    MemoryValidationError,
    SuppressionScopeKind,
)

NAMESPACE = {
    "store_epoch": "a" * 64,
    "subject": "actor-1",
    "source_stream": "primary:primary-1:foreground_turns",
}
ORIGIN = {
    "namespace": NAMESPACE,
    "source_sequence": 7,
    "evidence_id": "evidence-1",
    "envelope_hash": "b" * 64,
    "admission_receipt_id": "s1-receipt-1",
    "admission_receipt_hash": "c" * 64,
    "proof_kind": "atomic",
    "profile": "user-message-text-exact/v1",
    "schema_version": 1,
}
CUT = {
    "namespace": NAMESPACE,
    "through_sequence": 7,
    "request_id": "forget-1",
    "scope_kind": "memory",
    "scope_ref": "memory-1",
    "action_ref": "action-evidence-1",
    "action_hash": "d" * 64,
    "schema_version": 1,
}
ORIGIN_HASH = "45db040a872144e428be23e6af1d94f98931c5a6c3bc513796467dcee0c17be1"
CUT_HASH = "85ec7b7718cb9669476730b8de056afd957b18657dd6d8c8315eb59cb62d36ff"
LEGACY_HASH = "28b70510a95555f3ff8fa1dd25232edb4f5f7603fbeb8f45c3e8aad008f198e1"


def independent_hash(domain, payload):
    raw = json.dumps(
        {"domain": domain, "payload": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_literal_vectors_roundtrip_and_proof_kind_binding():
    assert independent_hash("memory.history.source-origin.v1", ORIGIN) == ORIGIN_HASH
    assert independent_hash("memory.history.forget-cut.v1", CUT) == CUT_HASH
    origin = HistorySourceOriginReceipt.from_json(ORIGIN)
    cut = HistoryForgetCutReceipt.from_json(CUT)
    assert origin.to_json() == ORIGIN
    assert cut.to_json() == CUT
    assert origin.origin_hash == ORIGIN_HASH
    assert cut.cut_hash == CUT_HASH
    legacy = replace(origin, proof_kind="legacy_before_only")
    assert legacy.origin_hash == LEGACY_HASH
    assert legacy.origin_hash != origin.origin_hash
    assert cut.scope_kind is SuppressionScopeKind.MEMORY
    assert replace(cut, through_sequence=0).through_sequence == 0


@pytest.mark.parametrize("carrier,payload", [
    (HistorySourceOriginReceipt, ORIGIN), (HistoryForgetCutReceipt, CUT),
    (HistorySourceNamespace, NAMESPACE),
])
def test_strict_wire_shape_no_missing_or_unknown_fields(carrier, payload):
    for field in payload:
        with pytest.raises(MemoryValidationError):
            carrier.from_json({k: v for k, v in payload.items() if k != field})
    with pytest.raises(MemoryValidationError):
        carrier.from_json({**payload, "permission": "allow"})
    for malformed in (None, [], "not-json", 1):
        with pytest.raises(MemoryValidationError):
            carrier.from_json(malformed)


@pytest.mark.parametrize("field,value", [
    ("proof_kind", True), ("proof_kind", "unknown"), ("proof_kind", None),
    ("source_sequence", True), ("source_sequence", 0), ("source_sequence", -1),
    ("source_sequence", 1.0), ("source_sequence", 2**63),
    ("schema_version", True), ("schema_version", 1.0), ("schema_version", 2),
    ("profile", "arbitrary-text"), ("envelope_hash", "A" * 64),
    ("admission_receipt_hash", "wrong"), ("admission_receipt_id", ""),
    ("evidence_id", "bad\x00id"), ("namespace", NAMESPACE),
])
def test_origin_rejects_invalid_direct_constructor_values(field, value):
    origin = HistorySourceOriginReceipt.from_json(ORIGIN)
    with pytest.raises(MemoryValidationError):
        replace(origin, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("through_sequence", True), ("through_sequence", -1),
    ("through_sequence", 1.0), ("through_sequence", 2**63),
    ("schema_version", True), ("schema_version", 2),
    ("scope_kind", SuppressionScopeKind.EVIDENCE), ("scope_kind", "memory"),
    ("scope_ref", ""), ("action_hash", "wrong"), ("action_ref", ""),
])
def test_cut_rejects_invalid_direct_constructor_values(field, value):
    with pytest.raises(MemoryValidationError):
        replace(HistoryForgetCutReceipt.from_json(CUT), **{field: value})


def test_frozen_and_returned_json_cannot_mutate_binding():
    origin = HistorySourceOriginReceipt.from_json(ORIGIN)
    with pytest.raises(FrozenInstanceError):
        origin.proof_kind = "atomic"
    with pytest.raises(FrozenInstanceError):
        origin.namespace.subject = "other"
    wire = origin.to_json()
    wire["namespace"]["subject"] = "other"
    assert origin.origin_hash == ORIGIN_HASH
    assert replace(origin, namespace=replace(origin.namespace, subject="other")).origin_hash != (
        ORIGIN_HASH
    )


def test_public_async_ports_have_exact_keyword_only_arguments():
    for name, fields in [
        ("resolve_history_source", ["principal", "envelope", "receipt"]),
        ("resolve_history_forget_cut", ["principal", "decision"]),
    ]:
        method = getattr(HistorySourceAuthorityPort, name)
        assert inspect.iscoroutinefunction(method)
        parameters = inspect.signature(method).parameters
        assert list(parameters) == ["self", *fields]
        assert all(parameters[field].kind is inspect.Parameter.KEYWORD_ONLY for field in fields)
