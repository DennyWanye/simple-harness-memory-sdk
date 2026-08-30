"""Evidence-first admission contracts for the human-memory v1 data epoch.

The Memory SDK never receives the unsanitized source body.  ``source_hash`` is
therefore verified as an exact Host receipt binding, while ``sanitized_hash``
is independently recomputed from the public payload before persistence.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from simple_harness.contracts import (
    FrozenJsonValue,
    JsonValue,
    canonical_json,
    freeze_json,
    thaw_json,
)
from simple_harness.runtime import SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt

from simple_harness_memory.core.errors import MemoryLimitError, MemoryValidationError

MAX_INLINE_EVIDENCE_BYTES = 64 * 1024
MAX_EVIDENCE_NODES = 4096
MAX_EVIDENCE_DEPTH = 32
MAX_PUBLIC_STRING_BYTES = 64 * 1024
SUPPORTED_FILTER_POLICY_VERSIONS = frozenset({"credential-filter/v1"})

_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "apikey",
        "xapikey",
        "accesstoken",
        "refreshtoken",
        "sessiontoken",
        "password",
        "passwd",
        "privatekey",
        "clientsecret",
        "credential",
        "credentials",
        "chainofthought",
        "hiddenreasoning",
        "reasoningsignature",
        "thoughtsignature",
    }
)
_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\b(?:sk|key|tsk)-?[a-zA-Z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_FORBIDDEN_KEY_SUFFIXES = (
    "authorization",
    "cookie",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "sessiontoken",
    "password",
    "passwd",
    "privatekey",
    "clientsecret",
    "secretaccesskey",
    "credential",
    "credentials",
)
_BLOB_REF_PATTERN = re.compile(r"memory-blob:[a-zA-Z0-9._:-]{1,1000}\Z")


def _sha256_json(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _identifier(value: object, name: str, *, max_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    ordinal: int
    item_kind: str
    content_hash: str
    public_payload: Mapping[str, FrozenJsonValue] | None = None
    blob_ref: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 1:
            raise MemoryValidationError("evidence_span_ordinal_invalid")
        _identifier(self.item_kind, "evidence_span_kind", max_bytes=128)
        _digest(self.content_hash, "evidence_span_content_hash")
        if (self.public_payload is None) == (self.blob_ref is None):
            raise MemoryValidationError("evidence_span_storage_invalid")
        if self.public_payload is not None:
            frozen = freeze_json(thaw_json(cast(FrozenJsonValue, self.public_payload)))
            if not isinstance(frozen, Mapping):
                raise MemoryValidationError("evidence_span_payload_invalid")
            object.__setattr__(self, "public_payload", frozen)
        if self.blob_ref is not None and _BLOB_REF_PATTERN.fullmatch(self.blob_ref) is None:
            raise MemoryValidationError("evidence_blob_ref_invalid")


@dataclass(frozen=True, slots=True)
class EvidenceIngestionReceipt:
    receipt_id: str
    evidence_id: str
    source_ref: str
    source_hash: str
    sanitized_hash: str
    envelope_hash: str
    admission_receipt_id: str
    admission_receipt_hash: str
    mutation_job_id: str
    outbox_id: str
    accepted_at: float
    schema_version: int = 1
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("evidence ingestion schema_version must be an integer")
        if self.schema_version != 1:
            raise MemoryValidationError("evidence_ingestion_schema_unsupported")
        for value, name in (
            (self.receipt_id, "receipt_id"),
            (self.evidence_id, "evidence_id"),
            (self.source_ref, "source_ref"),
            (self.admission_receipt_id, "admission_receipt_id"),
            (self.mutation_job_id, "mutation_job_id"),
            (self.outbox_id, "outbox_id"),
        ):
            _identifier(value, name)
        for value, name in (
            (self.source_hash, "source_hash"),
            (self.sanitized_hash, "sanitized_hash"),
            (self.envelope_hash, "envelope_hash"),
            (self.admission_receipt_hash, "admission_receipt_hash"),
        ):
            _digest(value, name)
        if (
            isinstance(self.accepted_at, bool)
            or not isinstance(self.accepted_at, (int, float))
            or not math.isfinite(float(self.accepted_at))
            or float(self.accepted_at) < 0
        ):
            raise MemoryValidationError("evidence_accepted_at_invalid")
        object.__setattr__(self, "accepted_at", float(self.accepted_at))
        object.__setattr__(self, "receipt_hash", _sha256_json(self.to_json()))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "evidence_id": self.evidence_id,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "sanitized_hash": self.sanitized_hash,
            "envelope_hash": self.envelope_hash,
            "admission_receipt_id": self.admission_receipt_id,
            "admission_receipt_hash": self.admission_receipt_hash,
            "mutation_job_id": self.mutation_job_id,
            "outbox_id": self.outbox_id,
            "accepted_at": self.accepted_at,
        }


@dataclass(frozen=True, slots=True)
class IngestedEvidenceRecord:
    envelope: SanitizedEvidenceEnvelope
    admission_receipt: SanitizedEvidenceReceipt
    ingestion_receipt: EvidenceIngestionReceipt
    spans: tuple[EvidenceSpan, ...]


def validate_sanitized_evidence(
    envelope: SanitizedEvidenceEnvelope,
    receipt: SanitizedEvidenceReceipt,
    *,
    supported_filter_policies: Sequence[str] = tuple(SUPPORTED_FILTER_POLICY_VERSIONS),
) -> EvidenceSpan:
    """Validate S1 authority and defensively rescan the public structure."""

    if type(envelope) is not SanitizedEvidenceEnvelope:  # exact protocol authority
        raise TypeError("envelope must use the S1 SanitizedEvidenceEnvelope")
    if type(receipt) is not SanitizedEvidenceReceipt:
        raise TypeError("receipt must use the S1 SanitizedEvidenceReceipt")
    # Strict live DTO round trips catch protocol objects forged without their
    # constructor or carrying a future/extra wire field.
    decoded_envelope = SanitizedEvidenceEnvelope.from_json(envelope.to_json())
    decoded_receipt = SanitizedEvidenceReceipt.from_json(receipt.to_json())
    decoded_receipt.verify(decoded_envelope)
    if decoded_envelope.filter_policy_version not in frozenset(supported_filter_policies):
        raise MemoryValidationError("evidence_filter_policy_unsupported")
    if (
        decoded_envelope.disclosure_context.to_json()
        != decoded_receipt.disclosure_context.to_json()
    ):
        raise MemoryValidationError("evidence_disclosure_receipt_mismatch")
    if decoded_envelope.evidence_refs != decoded_receipt.evidence_refs:
        raise MemoryValidationError("evidence_refs_receipt_mismatch")
    if decoded_envelope.subject != decoded_envelope.disclosure_context.subject:
        raise MemoryValidationError("evidence_subject_disclosure_mismatch")
    payload = thaw_json(cast(FrozenJsonValue, decoded_envelope.sanitized_payload))
    if _sha256_json(payload) != decoded_envelope.sanitized_hash:
        raise MemoryValidationError("evidence_sanitized_hash_mismatch")
    encoded = canonical_json(payload).encode("utf-8")
    blob = _controlled_blob_ref(payload)
    if blob is not None:
        blob_ref, content_hash = blob
        return EvidenceSpan(1, "controlled_blob_ref", content_hash, blob_ref=blob_ref)
    if len(encoded) > MAX_INLINE_EVIDENCE_BYTES:
        raise MemoryLimitError("evidence_payload_requires_controlled_blob_ref")
    _scan_public_structure(cast(JsonValue, decoded_envelope.to_json()))
    return EvidenceSpan(
        1,
        "sanitized_payload",
        decoded_envelope.sanitized_hash,
        public_payload=decoded_envelope.sanitized_payload,
    )


def _controlled_blob_ref(value: JsonValue) -> tuple[str, str] | None:
    if not isinstance(value, dict) or set(value) != {"blob_ref", "content_hash", "byte_length"}:
        return None
    blob_ref = value["blob_ref"]
    content_hash = value["content_hash"]
    byte_length = value["byte_length"]
    if not isinstance(blob_ref, str) or _BLOB_REF_PATTERN.fullmatch(blob_ref) is None:
        raise MemoryValidationError("evidence_blob_ref_invalid")
    normalized_content_hash = _digest(content_hash, "evidence_blob_content_hash")
    if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 1:
        raise MemoryValidationError("evidence_blob_length_invalid")
    return blob_ref, normalized_content_hash


def _scan_public_structure(value: JsonValue) -> None:
    nodes = 0

    def visit(item: JsonValue, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_EVIDENCE_NODES or depth > MAX_EVIDENCE_DEPTH:
            raise MemoryLimitError("evidence_structure_limit_exceeded")
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
                if normalized in _FORBIDDEN_KEYS or normalized.endswith(
                    _FORBIDDEN_KEY_SUFFIXES
                ):
                    raise MemoryValidationError("evidence_credential_boundary_rejected")
                visit(nested, depth + 1)
            return
        if isinstance(item, list):
            for nested in item:
                visit(nested, depth + 1)
            return
        if isinstance(item, str):
            if len(item.encode("utf-8")) > MAX_PUBLIC_STRING_BYTES:
                raise MemoryLimitError("evidence_public_string_limit_exceeded")
            if any(pattern.search(item) for pattern in _FORBIDDEN_VALUE_PATTERNS):
                raise MemoryValidationError("evidence_credential_boundary_rejected")

    visit(value, 0)


__all__ = (
    "EvidenceIngestionReceipt",
    "EvidenceSpan",
    "IngestedEvidenceRecord",
    "MAX_INLINE_EVIDENCE_BYTES",
    "SUPPORTED_FILTER_POLICY_VERSIONS",
    "validate_sanitized_evidence",
)
