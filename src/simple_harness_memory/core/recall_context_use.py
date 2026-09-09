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

0.6.38（DECISION-2026-09-09-lease-degradation-and-incumbent-vectors.md）新增第二个同形状的
稳定码 ``authority_lease_expired``：召回结果的 ``authority_expires_at`` 到期本身不再硬失败，
逐来源重校验全通过时照常签发收据。它同样**零 DDL**，且与 epoch 那一对严格同形：

* 「本次授权发生的时刻」落在不可变的 ``recall_context_use_receipts.authorized_at``；
* 「被绑定结果的租约」落在不可变的 ``typed_recall_results.result_json`` 的
  ``authority_expires_at``；两行仍由 ``result_id`` 唯一连接。

故「本次授权发生在租约到期之后」也是由不可变行严格导出的事实。
**注意**：收据行自己的 ``expires_at`` 在这一支是**续发**的新租约（冻结的
``RecallContextUseReceiptV1`` 要求 ``expires_at > authorized_at``，一张"已过期的收据"
在契约上不可构造），因此它不参与该事实的导出。
一张收据可能同时导出两条说明（epoch 前进 **且** 租约到期），此时按上述固定次序各出一条。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from simple_harness.contracts import JsonValue

from simple_harness_memory.core.errors import MemoryValidationError

RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED = "authority_epoch_advanced"
RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED = "authority_lease_expired"
RECALL_CONTEXT_USE_REASON_CODES = (
    RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
    RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED,
)

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
    # 0.6.38：仅 ``authority_lease_expired`` 使用，逐字取自不可变的
    # ``typed_recall_results.result_json`` 的 ``authority_expires_at``（= 被绑定时的租约，
    # 不是收据续发的那个）。``authority_epoch_advanced`` 的说明恒为 ``None``（与租约无关）。
    bound_authority_expires_at: float | None = None

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
        # ``authority_epoch_advanced`` 要求 epoch 真的前进；``authority_lease_expired``
        # 的 epoch 可以相等（它恰恰是"epoch 没动、只是租约到期"的那一格），但永不倒退。
        lease_expired = self.reason_code == RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED
        if self.authority_epoch < self.bound_authority_epoch or (
            not lease_expired and self.authority_epoch == self.bound_authority_epoch
        ):
            raise MemoryValidationError("recall_context_use_authority_epoch_invalid")
        if (
            isinstance(self.authorized_at, bool)
            or not isinstance(self.authorized_at, (int, float))
            or self.authorized_at < 0
        ):
            raise MemoryValidationError("recall_context_use_authorized_at_invalid")
        object.__setattr__(self, "authorized_at", float(self.authorized_at))
        if lease_expired:
            if (
                isinstance(self.bound_authority_expires_at, bool)
                or not isinstance(self.bound_authority_expires_at, (int, float))
                or self.bound_authority_expires_at < 0
                or self.authorized_at < float(self.bound_authority_expires_at)
            ):
                raise MemoryValidationError("recall_context_use_bound_authority_expires_at_invalid")
            object.__setattr__(
                self,
                "bound_authority_expires_at",
                float(self.bound_authority_expires_at),
            )
        elif self.bound_authority_expires_at is not None:
            raise MemoryValidationError("recall_context_use_bound_authority_expires_at_invalid")

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
            "bound_authority_expires_at": self.bound_authority_expires_at,
        }


__all__ = (
    "RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED",
    "RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED",
    "RECALL_CONTEXT_USE_REASON_CODES",
    "RecallContextUseAuthorityNoteV1",
)
