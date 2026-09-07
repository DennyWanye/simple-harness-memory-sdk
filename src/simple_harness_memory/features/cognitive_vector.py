"""长期认知记忆向量通道（0.6.23）的纯函数与冻结常量。

向量只从 ``_cognitive_public_payload_unlocked`` 的公开 payload 生成；本模块不读库、不含任何
非公开字段。余弦阈值是 SDK 冻结常量：低于阈值的记忆不进入 ``vector`` lane。
relation 类 SEMANTIC 记忆（``semantic_kind == "relation"``）是图谱的边而非节点（HM-AC-6），
没有公开 payload，不进入向量世代、manifest 与 ``vector`` lane（0.6.24）。
0.6.26 起 prospective 的触发条件额外渲染为确定性中文描述（``prospective_trigger_text``），
向量文本与 typed recall 词面门共用（``cognitive_text_supplement``）；公开 payload 形状不变。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 余弦阈值（冻结常量）。初值 0.45：短时域精确扫描不设阈值是因为 chunk 已经过 FTS/实体窗口；
# 认知记忆的 vector lane 是资格门之后唯一的新增召回入口，必须有负控。0.45 处于双语句向量
# 模型"同义改写"（通常 ≥0.6）与"无关句"（通常 ≤0.3）之间，由 Host C07 零召回子集回归校准。
COGNITIVE_VECTOR_MIN_SCORE = 0.45

COGNITIVE_VECTOR_UNAVAILABLE = "cognitive_vector_unavailable"
COGNITIVE_VECTOR_NO_GENERATION = "cognitive_vector_no_generation"
COGNITIVE_VECTOR_STALE = "cognitive_vector_stale"
COGNITIVE_VECTOR_DEADLINE = "cognitive_vector_deadline"
COGNITIVE_VECTOR_DEGRADATION_CODES = frozenset(
    {
        COGNITIVE_VECTOR_UNAVAILABLE,
        COGNITIVE_VECTOR_NO_GENERATION,
        COGNITIVE_VECTOR_STALE,
        COGNITIVE_VECTOR_DEADLINE,
    }
)

# 世代构建失败码（0.6.24）：落 ``cognitive_vector_generations.last_error_code``，并作为
# ``CognitiveVectorGenerationFailed.code`` 抛出。按失败阶段划分：读 head/公开 payload、嵌入、写库。
COGNITIVE_VECTOR_BUILD_HEAD_INVALID = "cognitive_vector_head_invalid"
COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED = "cognitive_vector_embedding_failed"
COGNITIVE_VECTOR_BUILD_WRITE_FAILED = "cognitive_vector_generation_write_failed"
COGNITIVE_VECTOR_BUILD_ERROR_CODES = frozenset(
    {
        COGNITIVE_VECTOR_BUILD_HEAD_INVALID,
        COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED,
        COGNITIVE_VECTOR_BUILD_WRITE_FAILED,
    }
)


# 渲染文本格式版本。``cognitive_vector_text`` / ``cognitive_text_supplement`` 的输出形状由它
# 标定：任何渲染变化都必须 +1，因为该版本号进入认知向量世代 manifest
# （``_cognitive_vector_manifest_hash``），旧世代随之 stale 并在下一次构建时整代重建。
# 1 = 0.6.23–0.6.25 的隐式渲染（无补充文本）；2 = 0.6.26 起 prospective 带触发条件渲染。
COGNITIVE_TEXT_FORMAT_VERSION = 2

# 中文星期（``datetime.weekday()`` 0=周一）。
_CHINESE_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# prospective trigger_kind 的中文词。未知 kind 不渲染（保持旧形状，不臆造语义）。
_TRIGGER_KIND_TEXT = {"time": "定时", "event": "事件"}


def _flatten(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key in sorted(str(item) for item in value):
            parts.extend(_flatten(value[key]))
        return parts
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            parts.extend(_flatten(item))
        return parts
    return [str(value)]


def _local_moment_text(trigger_at: Any, timezone: Any) -> str | None:
    """``trigger_at`` 在 ``timezone`` 下的「YYYY-MM-DD 周X HH:MM」；不可渲染时返回 None。"""

    if isinstance(trigger_at, bool) or not isinstance(trigger_at, (int, float)):
        return None
    epoch = float(trigger_at)
    if not math.isfinite(epoch):
        return None
    zone: Any = UTC
    if isinstance(timezone, str) and timezone.strip():
        try:
            zone = ZoneInfo(timezone)
        except (KeyError, ValueError, ZoneInfoNotFoundError):
            # 未知时区名不阻断渲染：退回 UTC，仍然确定性。
            zone = UTC
    try:
        moment = datetime.fromtimestamp(epoch, zone)
    except (OSError, OverflowError, ValueError):
        return None
    return f"{moment:%Y-%m-%d} {_CHINESE_WEEKDAYS[moment.weekday()]} {moment:%H:%M}"


def prospective_trigger_text(trigger: Any) -> str:
    """prospective 触发条件的确定性自然语言描述（只用公开字段）。

    时间触发渲染为「YYYY-MM-DD 周X HH:MM 定时提醒 待办」，事件触发渲染为「事件提醒 待办」。
    epoch 数字与 ``trigger_kind`` 英文枚举在中文查询下既无词面重叠也无向量邻近，这段渲染是
    prospective 进入 ``full_text`` / ``vector`` lane 的唯一自然语言载体（0.6.26）。
    """

    if not isinstance(trigger, Mapping):
        return ""
    kind = trigger.get("trigger_kind")
    if not isinstance(kind, str) or kind not in _TRIGGER_KIND_TEXT:
        return ""
    parts = [f"{_TRIGGER_KIND_TEXT[kind]}提醒", "待办"]
    if kind == "time":
        moment = _local_moment_text(trigger.get("trigger_at"), trigger.get("timezone"))
        if moment is not None:
            parts.insert(0, moment)
    return " ".join(parts)


def cognitive_text_supplement(memory_type: str, public_payload: Mapping[str, Any]) -> str:
    """公开 payload 的确定性自然语言补充文本；公开 payload 形状本身不变。

    向量文本与 typed recall 词面门共用它，因此两条 lane 看到同一段渲染。当前只有
    prospective 有补充文本（触发条件），其余类型返回空串。
    """

    if memory_type != "prospective":
        return ""
    return prospective_trigger_text(public_payload.get("trigger"))


def cognitive_vector_text(memory_type: str, public_payload: Mapping[str, Any]) -> str:
    """Deterministic embedding text for one public cognitive payload.

    semantic = subject_entity + predicate（下划线转空格）+ object_value + qualifiers；
    episode = title/goals/actions/results；procedure = name/applicability/steps；
    prospective = action + 触发渲染（``cognitive_text_supplement``）+ trigger。
    未知类型回退为全部字段的确定性拼接。
    """

    if memory_type == "semantic":
        fields = ("subject_entity", "predicate", "object_value", "qualifiers")
    elif memory_type == "episode":
        fields = ("title", "goals", "actions", "results")
    elif memory_type == "procedure":
        fields = ("name", "applicability", "steps")
    elif memory_type == "prospective":
        fields = ("action", "trigger")
    else:
        fields = tuple(sorted(str(key) for key in public_payload))
    parts: list[str] = []
    for field in fields:
        value = public_payload.get(field)
        if field == "predicate" and isinstance(value, str):
            value = value.replace("_", " ")
        parts.extend(_flatten(value))
        if memory_type == "prospective" and field == "action":
            # action 仍在最前；触发渲染紧随其后，原始 trigger 字段照旧在末尾。
            supplement = cognitive_text_supplement(memory_type, public_payload)
            if supplement:
                parts.append(supplement)
    return "\n".join(part.strip() for part in parts if part.strip())


def cognitive_vector_ref(memory_id: str, revision: int) -> str:
    """Cache/lane reference for one (memory_id, revision)."""

    return f"{memory_id}:{int(revision)}"


@dataclass(frozen=True, slots=True)
class CognitiveVectorGenerationBuildResult:
    generation_id: str | None
    vector_count: int
    activated: bool
    replayed: bool
    audit_id: str


__all__ = (
    "COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED",
    "COGNITIVE_VECTOR_BUILD_ERROR_CODES",
    "COGNITIVE_VECTOR_BUILD_HEAD_INVALID",
    "COGNITIVE_VECTOR_BUILD_WRITE_FAILED",
    "COGNITIVE_VECTOR_DEADLINE",
    "COGNITIVE_VECTOR_DEGRADATION_CODES",
    "COGNITIVE_VECTOR_MIN_SCORE",
    "COGNITIVE_VECTOR_NO_GENERATION",
    "COGNITIVE_VECTOR_STALE",
    "COGNITIVE_VECTOR_UNAVAILABLE",
    "COGNITIVE_TEXT_FORMAT_VERSION",
    "CognitiveVectorGenerationBuildResult",
    "cognitive_text_supplement",
    "cognitive_vector_ref",
    "cognitive_vector_text",
    "prospective_trigger_text",
)
