"""``apply_memory_mutation_plan`` 拒绝的**精确** validation reason 码与只读视图（0.6.32）。

冻结的 Harness ``MemoryMutationApplyReasonCode``（``runtime/memory_protocol.py:3370``）
只有 5 个成员，contest 家族的每一种拒绝都被压成同一个
``VALIDATION_REJECTED``；而 0.6.31 的 durable 拒绝审计又把 6 个
``mutation_contest_*`` 中的 4 个压成 ``mutation_contest_rejected``、另外 2 个
（``mutation_contest_nested_group_rejected`` / ``mutation_contest_distinct_evidence_required``）
干脆落到 ``mutation_epistemic_or_validation_rejected``——一个与 contest 无关的类名。
于是 401 矩阵的三格（`conflict-state` 精确 reason）在公共面无法区分是哪一种拒绝。

0.6.32 的增量：

* **不改公共错误类**（仍是 ``MemoryValidationError``，``str(exc)`` 逐字不变），
  **不改** 冻结枚举，**不加 DDL**（``memory_mutation_rejection_audits.reason_code``
  本就是无 CHECK 的 ``TEXT``）；
* 把 contest 家族在 durable 审计里的 ``reason_code`` 改成**一一对应**的稳定码；
* 新增只读导出 ``MemoryManager.read_memory_mutation_validation_notes``，把该码连同
  plan 身份与 apply 结果身份一起给出。

本模块不进根导出（沿用 0.6.20 起「根导出零增减」的纪律）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from simple_harness.contracts import JsonValue

from simple_harness_memory.core.errors import MemoryValidationError

MUTATION_CONTEST_DISTINCT_EVIDENCE_REQUIRED = "mutation_contest_distinct_evidence_required"
MUTATION_CONTEST_EXACT_SLOT_REQUIRED = "mutation_contest_exact_slot_required"
MUTATION_CONTEST_EXACT_TARGET_REQUIRED = "mutation_contest_exact_target_required"
MUTATION_CONTEST_LIFECYCLE_MUST_BE_UNCHANGED = "mutation_contest_lifecycle_must_be_unchanged"
MUTATION_CONTEST_NESTED_GROUP_REJECTED = "mutation_contest_nested_group_rejected"
MUTATION_CONTEST_REQUIRES_CONTESTED_STATE = "mutation_contest_requires_contested_state"

#: 冻结的稳定码集合（排序固定，供 Host 做穷尽映射）。每一个码与
#: ``MemoryValidationError`` 的 ``str(exc)`` 逐字相同——这是有意的：
#: 抛出侧与审计侧同名，没有第二套翻译表可以漂移。
MEMORY_MUTATION_VALIDATION_REASON_CODES = (
    MUTATION_CONTEST_DISTINCT_EVIDENCE_REQUIRED,
    MUTATION_CONTEST_EXACT_SLOT_REQUIRED,
    MUTATION_CONTEST_EXACT_TARGET_REQUIRED,
    MUTATION_CONTEST_LIFECYCLE_MUST_BE_UNCHANGED,
    MUTATION_CONTEST_NESTED_GROUP_REJECTED,
    MUTATION_CONTEST_REQUIRES_CONTESTED_STATE,
)
#: 0.6.31 及更早把上述六种全部压成的两个泛化码（保留为历史读出值）。
MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE = "mutation_contest_rejected"
MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE = "mutation_epistemic_or_validation_rejected"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def specific_validation_reason_code(message: str) -> str | None:
    """把一条 ``MemoryValidationError`` 文本映射到稳定码；未收录返回 ``None``。"""

    if message in MEMORY_MUTATION_VALIDATION_REASON_CODES:
        return message
    return None


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


@dataclass(frozen=True, slots=True)
class MemoryMutationValidationNoteV1:
    """一条被 validation 拒绝的 plan 的精确理由，全部字段来自不可变审计行。"""

    rejection_id: str
    rejection_hash: str
    plan_id: str
    plan_hash: str
    idempotency_key: str
    base_revision: int
    reason_code: str
    apply_result_id: str | None
    apply_result_hash: str | None
    rejected_at: float

    def __post_init__(self) -> None:
        for value, name in (
            (self.rejection_id, "memory_mutation_rejection_id"),
            (self.plan_id, "memory_mutation_plan_id"),
            (self.idempotency_key, "memory_mutation_idempotency_key"),
        ):
            _identifier(value, name)
        for value, name in (
            (self.rejection_hash, "memory_mutation_rejection_hash"),
            (self.plan_hash, "memory_mutation_plan_hash"),
        ):
            _digest(value, name)
        if (
            isinstance(self.base_revision, bool)
            or not isinstance(self.base_revision, int)
            or self.base_revision < 1
        ):
            raise MemoryValidationError("memory_mutation_base_revision_invalid")
        if self.reason_code not in MEMORY_MUTATION_VALIDATION_REASON_CODES:
            raise MemoryValidationError("memory_mutation_validation_reason_code_invalid")
        if self.apply_result_id is not None:
            _identifier(self.apply_result_id, "memory_mutation_apply_result_id")
        if self.apply_result_hash is not None:
            _digest(self.apply_result_hash, "memory_mutation_apply_result_hash")
        if (self.apply_result_id is None) != (self.apply_result_hash is None):
            raise MemoryValidationError("memory_mutation_apply_result_binding_invalid")
        if (
            isinstance(self.rejected_at, bool)
            or not isinstance(self.rejected_at, (int, float))
            or self.rejected_at < 0
        ):
            raise MemoryValidationError("memory_mutation_rejected_at_invalid")
        object.__setattr__(self, "rejected_at", float(self.rejected_at))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "rejection_id": self.rejection_id,
            "rejection_hash": self.rejection_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "idempotency_key": self.idempotency_key,
            "base_revision": self.base_revision,
            "reason_code": self.reason_code,
            "apply_result_id": self.apply_result_id,
            "apply_result_hash": self.apply_result_hash,
            "rejected_at": self.rejected_at,
        }


__all__ = (
    "MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE",
    "MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE",
    "MEMORY_MUTATION_VALIDATION_REASON_CODES",
    "MUTATION_CONTEST_DISTINCT_EVIDENCE_REQUIRED",
    "MUTATION_CONTEST_EXACT_SLOT_REQUIRED",
    "MUTATION_CONTEST_EXACT_TARGET_REQUIRED",
    "MUTATION_CONTEST_LIFECYCLE_MUST_BE_UNCHANGED",
    "MUTATION_CONTEST_NESTED_GROUP_REJECTED",
    "MUTATION_CONTEST_REQUIRES_CONTESTED_STATE",
    "MemoryMutationValidationNoteV1",
    "specific_validation_reason_code",
)
