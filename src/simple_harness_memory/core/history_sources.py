"""Trusted Host source-order facts; these carriers grant no Memory permission.

An origin binds Host S1 admission, never asynchronous Memory ingestion. ``atomic``
proves admission and queue insertion shared a transaction. ``legacy_before_only``
proves admission preceded queue insertion, but cannot prove post-cut freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast

from simple_harness.contracts import JsonValue

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.history import history_hash
from simple_harness_memory.core.suppression import SuppressionScopeKind, _identifier

if TYPE_CHECKING:
    from simple_harness import SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt

    from simple_harness_memory.core.identity import MemoryPrincipal
    from simple_harness_memory.core.suppression import SuppressionDecision


def _digest(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise MemoryValidationError(f"{name}_invalid")


def _sequence(value: object, name: str, *, minimum: int) -> None:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise MemoryValidationError(f"{name}_invalid")


def _schema(value: object) -> None:
    if type(value) is not int or value != 1:
        raise MemoryValidationError("history_source_schema_unsupported")


def _wire(value: object, fields: set[str]) -> dict[str, JsonValue]:
    if not isinstance(value, dict) or set(value) != fields:
        raise MemoryValidationError("history_source_wire_invalid")
    return cast(dict[str, JsonValue], value)


@dataclass(frozen=True, slots=True)
class HistorySourceNamespace:
    """One persistent Host store, subject and actual primary queue stream."""

    store_epoch: str
    subject: str
    source_stream: str

    def __post_init__(self) -> None:
        _digest(self.store_epoch, "history_source_store_epoch")
        _identifier(self.subject, "history_source_subject")
        _identifier(self.source_stream, "history_source_stream")

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "store_epoch": self.store_epoch,
            "subject": self.subject,
            "source_stream": self.source_stream,
        }

    @classmethod
    def from_json(cls, value: object) -> HistorySourceNamespace:
        data = _wire(value, {"store_epoch", "subject", "source_stream"})
        return cls(
            store_epoch=cast(str, data["store_epoch"]),
            subject=cast(str, data["subject"]),
            source_stream=cast(str, data["source_stream"]),
        )


@dataclass(frozen=True, slots=True)
class HistorySourceOriginReceipt:
    """Exact Host S1 pair plus trusted queue order, even before Memory ingest.

``admission_receipt_*`` identify SanitizedEvidenceReceipt, NOT an SDK
EvidenceIngestionReceipt. Proof kind is mandatory; legacy can never default to atomic.
Computed hashes bind facts but cannot authenticate an untrusted caller's assertions.
"""

    namespace: HistorySourceNamespace
    source_sequence: int
    evidence_id: str
    envelope_hash: str
    admission_receipt_id: str
    admission_receipt_hash: str
    proof_kind: Literal["atomic", "legacy_before_only"]
    profile: str = "user-message-text-exact/v1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, HistorySourceNamespace):
            raise MemoryValidationError("history_source_namespace_invalid")
        _sequence(self.source_sequence, "history_source_sequence", minimum=1)
        for name in ("evidence_id", "admission_receipt_id"):
            _identifier(getattr(self, name), f"history_source_{name}")
        for name in ("envelope_hash", "admission_receipt_hash"):
            _digest(getattr(self, name), f"history_source_{name}")
        if type(self.proof_kind) is not str or self.proof_kind not in (
            "atomic", "legacy_before_only",
        ):
            raise MemoryValidationError("history_source_proof_kind_invalid")
        if self.profile != "user-message-text-exact/v1":
            raise MemoryValidationError("history_source_profile_unsupported")
        _schema(self.schema_version)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "namespace": self.namespace.to_json(),
            "source_sequence": self.source_sequence,
            "evidence_id": self.evidence_id,
            "envelope_hash": self.envelope_hash,
            "admission_receipt_id": self.admission_receipt_id,
            "admission_receipt_hash": self.admission_receipt_hash,
            "proof_kind": self.proof_kind,
            "profile": self.profile,
            "schema_version": self.schema_version,
        }

    @property
    def origin_hash(self) -> str:
        return history_hash("memory.history.source-origin.v1", self.to_json())

    @classmethod
    def from_json(cls, value: object) -> HistorySourceOriginReceipt:
        data = _wire(value, {
            "namespace", "source_sequence", "evidence_id", "envelope_hash",
            "admission_receipt_id", "admission_receipt_hash", "proof_kind", "profile",
            "schema_version",
        })
        return cls(
            namespace=HistorySourceNamespace.from_json(data["namespace"]),
            source_sequence=cast(int, data["source_sequence"]),
            evidence_id=cast(str, data["evidence_id"]),
            envelope_hash=cast(str, data["envelope_hash"]),
            admission_receipt_id=cast(str, data["admission_receipt_id"]),
            admission_receipt_hash=cast(str, data["admission_receipt_hash"]),
            proof_kind=cast(Literal["atomic", "legacy_before_only"], data["proof_kind"]),
            profile=cast(str, data["profile"]),
            schema_version=cast(int, data["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class HistoryForgetCutReceipt:
    """Original authenticated action's durable cutoff, not a new suppression grant.

action_ref/hash bind the original action S1 evidence ID/envelope hash. They are
not this cut_hash or a future SDK decision hash (which would make a cycle).
"""

    namespace: HistorySourceNamespace
    through_sequence: int
    request_id: str
    scope_kind: SuppressionScopeKind
    scope_ref: str
    action_ref: str
    action_hash: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, HistorySourceNamespace):
            raise MemoryValidationError("history_source_namespace_invalid")
        _sequence(self.through_sequence, "history_cut_sequence", minimum=0)
        if self.scope_kind is not SuppressionScopeKind.MEMORY:
            raise MemoryValidationError("history_cut_scope_unsupported")
        for name in ("request_id", "scope_ref", "action_ref"):
            _identifier(getattr(self, name), f"history_cut_{name}")
        _digest(self.action_hash, "history_cut_action_hash")
        _schema(self.schema_version)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "namespace": self.namespace.to_json(),
            "through_sequence": self.through_sequence,
            "request_id": self.request_id,
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "action_ref": self.action_ref,
            "action_hash": self.action_hash,
            "schema_version": self.schema_version,
        }

    @property
    def cut_hash(self) -> str:
        return history_hash("memory.history.forget-cut.v1", self.to_json())

    @classmethod
    def from_json(cls, value: object) -> HistoryForgetCutReceipt:
        data = _wire(value, {
            "namespace", "through_sequence", "request_id", "scope_kind", "scope_ref",
            "action_ref", "action_hash", "schema_version",
        })
        if type(data["scope_kind"]) is not str or data["scope_kind"] != "memory":
            raise MemoryValidationError("history_cut_scope_unsupported")
        return cls(
            namespace=HistorySourceNamespace.from_json(data["namespace"]),
            through_sequence=cast(int, data["through_sequence"]),
            request_id=cast(str, data["request_id"]),
            scope_kind=SuppressionScopeKind.MEMORY,
            scope_ref=cast(str, data["scope_ref"]),
            action_ref=cast(str, data["action_ref"]),
            action_hash=cast(str, data["action_hash"]),
            schema_version=cast(int, data["schema_version"]),
        )


class HistorySourceAuthorityPort(Protocol):
    """Read-only Host facts. SDK invokes outside its SQLite transaction.

Host verifies exact immutable S1/turn/init/action bindings and ownership. Missing
or legacy action cut returns None, never a guessed timestamp/current queue MAX.
An origin may return legacy_before_only; it must never be upgraded on replay.
"""

    async def resolve_history_source(
        self, *, principal: MemoryPrincipal,
        envelope: SanitizedEvidenceEnvelope, receipt: SanitizedEvidenceReceipt,
    ) -> HistorySourceOriginReceipt | None: ...

    async def resolve_history_forget_cut(
        self, *, principal: MemoryPrincipal, decision: SuppressionDecision,
    ) -> HistoryForgetCutReceipt | None: ...
