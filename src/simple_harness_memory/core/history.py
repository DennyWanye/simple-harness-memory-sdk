"""Current history visibility observations, never execution authorization grants."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
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


class ProcedureApplicabilityProvenance(Enum):
    """Where a caller-supplied Procedure applicability fingerprint set came from.

    0.6.36 (F-S1b).  ``check_history_visibility`` deliberately supplies **no** current
    Procedure applicability of its own: an ordinary foreground re-check must never
    replay the runtime fingerprints a stored ``RecallContext`` happened to carry.  The
    single member below is the one narrowly-scoped exception, and it is a *named* one:
    an offline lane that has no live Run states, explicitly and per call, that what it
    presents are the fingerprints of Procedure uses whose observation Memory already
    consumed — "it was really used", **not** "it is still applicable now".  The label is
    not taken on trust: `backends/history_visibility` admits a Procedure only where
    Memory's own immutable ``procedure_observations`` audit carries the same fingerprint
    for that memory with a successful, attributable observation.  See
    `slices/S3-cognitive-systems-recall.md` §2-补2（2026-09-09，0.6.36）.
    """

    APPLIED_USE_FINGERPRINTS = "applied_use_fingerprints"


@dataclass(frozen=True, slots=True)
class ProcedureApplicabilityAttestation:
    """One offline lane's explicitly-provenanced Procedure applicability fingerprints.

    Absent, ``check_history_visibility`` behaves exactly as it did before 0.6.36 (no
    Procedure is ever visible).  Present, it widens nothing else: the fingerprints are
    used only to re-validate ``HistoryRecallBinding`` sources, never evidence, short
    horizon, procedure drafts or the current-input entry point.
    """

    provenance: ProcedureApplicabilityProvenance
    fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.provenance) is not ProcedureApplicabilityProvenance:
            raise ValueError("procedure applicability provenance invalid")
        if type(self.fingerprints) is not tuple or not 1 <= len(self.fingerprints) <= 256:
            raise ValueError("procedure applicability requires 1 to 256 fingerprints")
        for value in self.fingerprints:
            _identifier(value, "applicability_fingerprint")
        # Canonical, caller-visible ordering: the attestation hash is part of the
        # snapshot request hash, so two callers presenting the same set must not be
        # able to produce two different receipts.
        if tuple(sorted(set(self.fingerprints))) != self.fingerprints:
            raise ValueError("procedure applicability fingerprints must be sorted and unique")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "provenance": self.provenance.value,
            "fingerprints": list(self.fingerprints),
        }

    @property
    def attestation_hash(self) -> str:
        return history_hash("memory.history.procedure-applicability.v1", self.to_json())


@dataclass(frozen=True, slots=True)
class ProcedureApplicabilityReceipt:
    """What the snapshot records about an attestation that was actually presented.

    ``admitted_binding_hashes`` lists, in the caller's binding order, every binding that
    is visible *because* of the attestation: without one, a Procedure source is
    unconditionally ``history_source_stale``, so every visible Procedure binding in an
    attested call was admitted by it.  It is a list, not a set — a caller that passes the
    same binding twice is named twice — which keeps it deterministic for a given request.
    """

    provenance: str
    attestation_hash: str
    fingerprint_count: int
    admitted_binding_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        # Only Memory produces this, but it is a root export: refuse a junk instance
        # rather than let one be mistaken for a real observation.
        if self.provenance not in {x.value for x in ProcedureApplicabilityProvenance}:
            raise ValueError("procedure applicability provenance invalid")
        if len(self.attestation_hash) != 64 or any(
            c not in "0123456789abcdef" for c in self.attestation_hash
        ):
            raise ValueError("procedure applicability attestation hash invalid")
        if type(self.fingerprint_count) is not int or not 1 <= self.fingerprint_count <= 256:
            raise ValueError("procedure applicability fingerprint count invalid")
        if type(self.admitted_binding_hashes) is not tuple:
            raise ValueError("procedure applicability admitted bindings invalid")
        for value in self.admitted_binding_hashes:
            _identifier(value, "admitted_binding_hash")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "provenance": self.provenance,
            "attestation_hash": self.attestation_hash,
            "fingerprint_count": self.fingerprint_count,
            "admitted_binding_hashes": list(self.admitted_binding_hashes),
        }


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
    # 0.6.36 (F-S1b): appended after ``schema_version`` on purpose — the existing
    # 7-positional shape stays literally unchanged, and an absent attestation keeps
    # ``to_json`` (and therefore both hashes) byte-identical to 0.6.35.
    procedure_applicability: ProcedureApplicabilityReceipt | None = None

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
            **(
                {}
                if self.procedure_applicability is None
                else {"procedure_applicability": self.procedure_applicability.to_json()}
            ),
        }
