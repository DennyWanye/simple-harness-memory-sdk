"""Current history visibility observations, never execution authorization grants."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.core.suppression import _identifier

if TYPE_CHECKING:
    from simple_harness import SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt


def history_hash(domain: str, payload: JsonValue) -> str:
    return hashlib.sha256(
        canonical_json({"domain": domain, "payload": payload}).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class HistoryEvidenceBinding:
    """Host-verified S1 admission, including evidence not yet ingested by Memory."""

    envelope: SanitizedEvidenceEnvelope
    receipt: SanitizedEvidenceReceipt

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "kind": "evidence",
            "envelope": self.envelope.to_json(),
            "receipt": self.receipt.to_json(),
        }


@dataclass(frozen=True, slots=True)
class HistoryRecallBinding:
    """An exact selected item of a durable owned result; no old grant is replayed."""

    result_id: str
    result_hash: str
    item_id: str
    item_hash: str

    def __post_init__(self) -> None:
        for name in ("result_id", "item_id", "result_hash", "item_hash"):
            _identifier(getattr(self, name), name)
        for value in (self.result_hash, self.item_hash):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("history binding digest invalid")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "kind": "recall",
            "result_id": self.result_id,
            "result_hash": self.result_hash,
            "item_id": self.item_id,
            "item_hash": self.item_hash,
        }


@dataclass(frozen=True, slots=True)
class HistoryShortHorizonBinding:
    """Exact standalone short hit selected by an owned durable recall audit."""

    audit_id: str
    chunk_ref: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("audit_id", "chunk_ref", "content_hash"):
            _identifier(getattr(self, name), name)
        if len(self.content_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.content_hash
        ):
            raise ValueError("history binding digest invalid")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "kind": "short_horizon",
            "audit_id": self.audit_id,
            "chunk_ref": self.chunk_ref,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class HistoryProcedureDraftBinding:
    """Exact preview payload; recheck current draft, owner and source before use."""
    memory_id: str
    revision: int
    candidate_hash: str

    def __post_init__(self):
        _identifier(self.memory_id, "memory_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("procedure_draft_revision_invalid")
        if type(self.candidate_hash) is not str or len(self.candidate_hash)!=64 or any(c not in "0123456789abcdef" for c in self.candidate_hash):
            raise ValueError("procedure_draft_hash_invalid")

    def to_json(self):
        return {"kind":"procedure_draft", "memory_id":self.memory_id,
                "revision":self.revision,"candidate_hash":self.candidate_hash}


HistoryBinding = HistoryEvidenceBinding | HistoryRecallBinding | HistoryShortHorizonBinding | HistoryProcedureDraftBinding


@dataclass(frozen=True, slots=True)
class HistoryVisibilityItem:
    binding_hash: str
    visible: bool
    reason: str

    def to_json(self) -> dict[str, JsonValue]:
        return {"binding_hash": self.binding_hash, "visible": self.visible, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class HistoryVisibilitySnapshot:
    subject: str
    request_hash: str
    checked_at: float
    valid_until: float | None
    authority_epoch: int
    policy_hash: str
    items: tuple[HistoryVisibilityItem, ...]
    schema_version: int = 1

    @property
    def snapshot_hash(self) -> str:
        return history_hash("memory.history.visibility.snapshot.v1", self.to_json())

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "subject": self.subject,
            "request_hash": self.request_hash,
            "checked_at": self.checked_at,
            "valid_until": self.valid_until,
            "authority_epoch": self.authority_epoch,
            "policy_hash": self.policy_hash,
            "items": [item.to_json() for item in self.items],
        }
