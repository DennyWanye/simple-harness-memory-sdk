"""用途围栏（``authorize_recall_context_use``）的降级码与可审计视图（0.6.29）。

0.6.29 起，被绑定来源全部通过重校验、只有权威 epoch 前进的并发场景不再抛
``RECALL_AUTHORITY_STALE``，而是照常签发收据。该事实**不新增任何 DDL**：

* 「授权时的当前 epoch」已经逐字落在不可变的 ``recall_context_use_receipts.authority_epoch``
  （同时进入 ``receipt_hash`` 与 canonical manifest）；
* 「召回被绑定时的 epoch」已经逐字落在不可变的 ``typed_recall_results.result_json``
  的 ``authority_epoch``；
* 两行由收据 ``request_json`` 里的 ``result_id`` 唯一连接。

因此「本次用途授权是在 epoch 前进之后签发的」是一个**由两条不可变行严格导出**的事实，
比再存一份可能与之矛盾的冗余标记更强。本模块只提供稳定码与只读视图，不进根导出
（沿用 0.6.20–0.6.28「根导出零增减」的纪律）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from simple_harness.contracts import JsonValue

from simple_harness_memory.core.errors import MemoryValidationError

RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED = "authority_epoch_advanced"
RECALL_CONTEXT_USE_REASON_CODES = (RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,)

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


def _epoch(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryValidationError(f"{name}_invalid")
    return value


@dataclass(frozen=True, slots=True)
class RecallContextUseAuthorityNoteV1:
    """一条已签发收据的权威降级说明，全部字段均从不可变行导出。"""

    receipt_id: str
    receipt_hash: str
    subject: str
    run_id: str
    turn_id: str
    provider_attempt_id: str
    result_id: str
    result_hash: str
    reason_code: str
    bound_authority_epoch: int
    authority_epoch: int
    policy_hash: str
    authorized_at: float

    def __post_init__(self) -> None:
        for value, name in (
            (self.receipt_id, "recall_context_use_receipt_id"),
            (self.subject, "recall_context_use_subject"),
            (self.run_id, "recall_context_use_run_id"),
            (self.turn_id, "recall_context_use_turn_id"),
            (self.provider_attempt_id, "recall_context_use_provider_attempt_id"),
            (self.result_id, "recall_context_use_result_id"),
        ):
            _identifier(value, name)
        for value, name in (
            (self.receipt_hash, "recall_context_use_receipt_hash"),
            (self.result_hash, "recall_context_use_result_hash"),
            (self.policy_hash, "recall_context_use_policy_hash"),
        ):
            _digest(value, name)
        if self.reason_code not in RECALL_CONTEXT_USE_REASON_CODES:
            raise MemoryValidationError("recall_context_use_reason_code_invalid")
        _epoch(self.bound_authority_epoch, "recall_context_use_bound_authority_epoch")
        _epoch(self.authority_epoch, "recall_context_use_authority_epoch")
        if self.authority_epoch <= self.bound_authority_epoch:
            raise MemoryValidationError("recall_context_use_authority_epoch_invalid")
        if (
            isinstance(self.authorized_at, bool)
            or not isinstance(self.authorized_at, (int, float))
            or self.authorized_at < 0
        ):
            raise MemoryValidationError("recall_context_use_authorized_at_invalid")
        object.__setattr__(self, "authorized_at", float(self.authorized_at))

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "receipt_id": self.receipt_id,
            "receipt_hash": self.receipt_hash,
            "subject": self.subject,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "provider_attempt_id": self.provider_attempt_id,
            "result_id": self.result_id,
            "result_hash": self.result_hash,
            "reason_code": self.reason_code,
            "bound_authority_epoch": self.bound_authority_epoch,
            "authority_epoch": self.authority_epoch,
            "policy_hash": self.policy_hash,
            "authorized_at": self.authorized_at,
        }


__all__ = (
    "RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED",
    "RECALL_CONTEXT_USE_REASON_CODES",
    "RecallContextUseAuthorityNoteV1",
)
