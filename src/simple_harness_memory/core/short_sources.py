"""Exact selected-source observations. No content or execution authorization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from simple_harness_memory.core.history import history_hash


@dataclass(frozen=True, slots=True)
class ShortHorizonSourceRef:
    evidence_id: str
    envelope_hash: str
    source_ref: str
    source_hash: str
    sanitized_hash: str
    admission_receipt_id: str
    admission_receipt_hash: str
    registration_id: str
    registration_hash: str
    item_ordinal: int
    role: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ShortHorizonSourceItem:
    binding_hash: str
    visible: bool
    reason: str
    complete: bool
    source_refs: tuple[ShortHorizonSourceRef, ...]

    def __post_init__(self) -> None:
        if (
            type(self.source_refs) is not tuple
            or any(type(ref) is not ShortHorizonSourceRef for ref in self.source_refs)
            or self.visible != self.complete
            or self.visible != bool(self.source_refs)
            or self.visible != (self.reason == "history_visible")
        ):
            raise ValueError("short source observation inconsistent")

    def to_json(self) -> dict[str, Any]:
        return dict(
            binding_hash=self.binding_hash,
            visible=self.visible,
            reason=self.reason,
            complete=self.complete,
            source_refs=[ref.to_json() for ref in self.source_refs],
        )


@dataclass(frozen=True, slots=True)
class ShortHorizonSourceSnapshot:
    subject: str
    request_hash: str
    evaluated_at: float
    authority_epoch: int
    policy_hash: str
    valid_until: float | None
    items: tuple[ShortHorizonSourceItem, ...]
    schema_version: int = 1

    @property
    def snapshot_hash(self) -> str:
        return history_hash("memory.short.sources.snapshot.v1", self.to_json())

    def to_json(self) -> dict[str, Any]:
        return dict(
            schema_version=self.schema_version,
            subject=self.subject,
            request_hash=self.request_hash,
            evaluated_at=self.evaluated_at,
            authority_epoch=self.authority_epoch,
            policy_hash=self.policy_hash,
            valid_until=self.valid_until,
            items=[item.to_json() for item in self.items],
        )
