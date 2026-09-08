"""Typed-recall 资格策略的显式版本入口（0.6.32）。

S3 slice §5.4 把「policy version 变化」列为召回权威 epoch 的推进车道之一，并把
``policy_hash`` 定为用途授权（``authorize_recall_context_use``）的**硬**判据：策略换了，
此前基于旧策略签发的结果绑定必须失效。0.6.31 之前 ``policy_hash`` 是
``backends/sqlite_v5.py`` 里的模块常量 ``_RECALL_POLICY_HASH``，公共面没有任何版本入参，
于是这条安全属性在公共契约上**不可见证**（401 矩阵 `current-use/authority:policy_hash_change`
被判 ``SDK_INCREMENT_REQUIRED``，见 Host `TYPED-RECALL-401-RUN-08.md` §2.I-1）。

本模块把它做成**显式、可审计**的部署级字段：

* ``RecallEligibilityPolicyV1.policy_version``（默认 ``1``）唯一决定 ``policy_id`` 与
  ``policy_hash``；版本号就写在 policy id 里（``typed-recall-eligibility/v{n}``）。
* 版本 1 的 canonical payload 与 0.6.31 的常量**逐字相同**，因此默认部署的
  ``policy_hash``、召回结果、用途收据、权威事件全部字节不变（见
  ``RECALL_POLICY_HASH_V1`` 的钉死字面值）。
* 语义不由本字段改变：SDK 只实现 v1 的资格门。字段声明的是「本部署跑的是哪一版资格策略」，
  部署方改了资格判据就必须 bump 版本，好让之前签发的用途授权按契约失效。

本模块不进根导出（沿用 0.6.20 起「根导出零增减」的纪律），只经
``simple_harness_memory.core.recall_policy`` 可达。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.core.errors import MemoryValidationError

RECALL_POLICY_FAMILY = "typed-recall-eligibility"
RECALL_POLICY_SCHEMA = 6
RECALL_POLICY_RRF_K = 60
RECALL_POLICY_WEIGHTS: dict[str, float] = {
    "vector": 0.40,
    "full_text": 0.30,
    "entity": 0.15,
    "task_scope": 0.10,
    "temporal": 0.05,
}
DEFAULT_RECALL_POLICY_VERSION = 1
MAX_RECALL_POLICY_VERSION = 1_000_000
#: 0.6.31 及更早版本的常量值；默认部署必须逐字得到它。
RECALL_POLICY_HASH_V1 = "c27604aa354d34f9597a62873a2a53547df192b74c267c569fae445d23c7fc04"
#: 策略版本变化时追加的权威事件种类（与 0.6.28 的既有车道并列，不改 DDL 行形状）。
RECALL_POLICY_CHANGED_EVENT_KIND = "recall_policy_changed"


def validate_recall_policy_version(value: object) -> int:
    """接受 ``1 .. MAX_RECALL_POLICY_VERSION`` 的严格整数版本号。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise MemoryValidationError("recall_policy_version_invalid")
    if not 1 <= value <= MAX_RECALL_POLICY_VERSION:
        raise MemoryValidationError("recall_policy_version_invalid")
    return value


def recall_policy_id(policy_version: int = DEFAULT_RECALL_POLICY_VERSION) -> str:
    return f"{RECALL_POLICY_FAMILY}/v{validate_recall_policy_version(policy_version)}"


def recall_policy_payload(
    policy_version: int = DEFAULT_RECALL_POLICY_VERSION,
) -> dict[str, JsonValue]:
    """版本 1 的键集与值与 0.6.31 常量逐字相同；版本号只体现在 ``policy``。"""

    return {
        "policy": recall_policy_id(policy_version),
        "schema": RECALL_POLICY_SCHEMA,
        "rrf_k": RECALL_POLICY_RRF_K,
        "weights": dict(RECALL_POLICY_WEIGHTS),
    }


def recall_policy_hash(policy_version: int = DEFAULT_RECALL_POLICY_VERSION) -> str:
    return hashlib.sha256(
        canonical_json(recall_policy_payload(policy_version)).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class RecallEligibilityPolicyV1:
    """一个部署所声明的召回资格策略版本（构造期即校验）。"""

    policy_version: int = DEFAULT_RECALL_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_version", validate_recall_policy_version(self.policy_version)
        )

    @property
    def policy_id(self) -> str:
        return recall_policy_id(self.policy_version)

    @property
    def policy_hash(self) -> str:
        return recall_policy_hash(self.policy_version)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "policy_version": self.policy_version,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
        }


def coerce_recall_policy(value: object) -> RecallEligibilityPolicyV1:
    """``None`` → 默认 v1；整数 → 该版本；已是记录则原样返回。"""

    if value is None:
        return RecallEligibilityPolicyV1()
    if type(value) is RecallEligibilityPolicyV1:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return RecallEligibilityPolicyV1(value)
    raise TypeError("recall_policy must use RecallEligibilityPolicyV1 or an int version")


@dataclass(frozen=True, slots=True)
class RecallPolicyStateV1:
    """一个 principal 上「配置策略」与「durable 权威头策略」的只读对照。

    ``authority_policy_hash`` 来自不可变的 ``recall_authority_heads`` 行；
    ``policy_hash`` 来自本进程的配置。两者不等即表示该 principal 的权威头
    尚未与新策略对齐（下一次召回或用途授权会以一条
    ``recall_policy_changed`` 事件对齐，并让旧结果的用途授权失效）。
    """

    policy_version: int
    policy_id: str
    policy_hash: str
    authority_epoch: int
    authority_policy_hash: str

    def __post_init__(self) -> None:
        validate_recall_policy_version(self.policy_version)
        if self.policy_id != recall_policy_id(self.policy_version):
            raise MemoryValidationError("recall_policy_id_invalid")
        if self.policy_hash != recall_policy_hash(self.policy_version):
            raise MemoryValidationError("recall_policy_hash_invalid")
        if isinstance(self.authority_epoch, bool) or not isinstance(
            self.authority_epoch, int
        ) or self.authority_epoch < 1:
            raise MemoryValidationError("recall_policy_authority_epoch_invalid")
        if (
            not isinstance(self.authority_policy_hash, str)
            or len(self.authority_policy_hash) != 64
            or any(c not in "0123456789abcdef" for c in self.authority_policy_hash)
        ):
            raise MemoryValidationError("recall_policy_authority_policy_hash_invalid")

    @property
    def policy_changed(self) -> bool:
        """配置策略与 durable 权威头是否已经对齐。"""

        return self.authority_policy_hash != self.policy_hash

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "policy_version": self.policy_version,
            "policy_id": self.policy_id,
            "policy_hash": self.policy_hash,
            "authority_epoch": self.authority_epoch,
            "authority_policy_hash": self.authority_policy_hash,
            "policy_changed": self.policy_changed,
        }


__all__ = (
    "DEFAULT_RECALL_POLICY_VERSION",
    "MAX_RECALL_POLICY_VERSION",
    "RECALL_POLICY_CHANGED_EVENT_KIND",
    "RECALL_POLICY_FAMILY",
    "RECALL_POLICY_HASH_V1",
    "RECALL_POLICY_RRF_K",
    "RECALL_POLICY_SCHEMA",
    "RECALL_POLICY_WEIGHTS",
    "RecallEligibilityPolicyV1",
    "RecallPolicyStateV1",
    "coerce_recall_policy",
    "recall_policy_hash",
    "recall_policy_id",
    "recall_policy_payload",
    "validate_recall_policy_version",
)
