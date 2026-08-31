"""Bounded public views over committed cognitive mutation receipts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from simple_harness.contracts import JsonValue

from simple_harness_memory.core.errors import MemoryValidationError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _revision(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class MemoryMutationCommittedOperationView:
    """Exact committed slot and bounded classification for one operation."""

    operation_id: str
    memory_id: str
    revision: int
    memory_type: str
    semantic_kind: str | None
    content_hash: str
    effective_privacy_class: str
    epistemic_status: str
    evidence_ids: tuple[str, ...]
    decision_hash: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "mutation_operation_id"),
            (self.memory_id, "mutation_memory_id"),
            (self.memory_type, "mutation_memory_type"),
            (self.effective_privacy_class, "mutation_privacy_class"),
            (self.epistemic_status, "mutation_epistemic_status"),
        ):
            _identifier(value, name)
        _revision(self.revision, "mutation_revision")
        if self.semantic_kind is not None:
            _identifier(self.semantic_kind, "mutation_semantic_kind")
        _digest(self.content_hash, "mutation_content_hash")
        _digest(self.decision_hash, "mutation_decision_hash")
        evidence_ids = tuple(self.evidence_ids)
        if (
            not evidence_ids
            or evidence_ids != tuple(sorted(set(evidence_ids)))
        ):
            raise MemoryValidationError("mutation_evidence_ids_invalid")
        for evidence_id in evidence_ids:
            _identifier(evidence_id, "mutation_evidence_id")
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "operation_id": self.operation_id,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "memory_type": self.memory_type,
            "semantic_kind": self.semantic_kind,
            "content_hash": self.content_hash,
            "effective_privacy_class": self.effective_privacy_class,
            "epistemic_status": self.epistemic_status,
            "evidence_ids": list(self.evidence_ids),
            "decision_hash": self.decision_hash,
        }


@dataclass(frozen=True, slots=True)
class MemoryMutationReceiptView:
    """Principal-scoped public receipt with exact committed operation bindings."""

    receipt_id: str
    receipt_hash: str
    plan_id: str
    plan_hash: str
    apply_mode: str
    operations: tuple[MemoryMutationCommittedOperationView, ...]

    def __post_init__(self) -> None:
        _identifier(self.receipt_id, "mutation_receipt_id")
        _digest(self.receipt_hash, "mutation_receipt_hash")
        _identifier(self.plan_id, "mutation_plan_id")
        _digest(self.plan_hash, "mutation_plan_hash")
        if self.apply_mode != "strict_atomic":
            raise MemoryValidationError("mutation_apply_mode_invalid")
        operations = tuple(self.operations)
        if (
            not operations
            or not all(
                isinstance(item, MemoryMutationCommittedOperationView)
                for item in operations
            )
            or len({item.operation_id for item in operations}) != len(operations)
        ):
            raise MemoryValidationError("mutation_receipt_operations_invalid")
        object.__setattr__(self, "operations", operations)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "receipt_id": self.receipt_id,
            "receipt_hash": self.receipt_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "apply_mode": self.apply_mode,
            "operations": [item.to_json() for item in self.operations],
        }


__all__ = (
    "MemoryMutationCommittedOperationView",
    "MemoryMutationReceiptView",
)
