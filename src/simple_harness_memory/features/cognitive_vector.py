"""长期认知记忆向量通道（0.6.23）的纯函数与冻结常量。

向量只从 ``_cognitive_public_payload_unlocked`` 的公开 payload 生成；本模块不读库、不含任何
非公开字段。余弦阈值是 SDK 冻结常量：低于阈值的记忆不进入 ``vector`` lane。
relation 类 SEMANTIC 记忆（``semantic_kind == "relation"``）是图谱的边而非节点（HM-AC-6），
没有公开 payload，不进入向量世代、manifest 与 ``vector`` lane（0.6.24）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


def cognitive_vector_text(memory_type: str, public_payload: Mapping[str, Any]) -> str:
    """Deterministic embedding text for one public cognitive payload.

    semantic = subject_entity + predicate（下划线转空格）+ object_value + qualifiers；
    episode = title/goals/actions/results；procedure = name/applicability/steps；
    prospective = action/trigger。未知类型回退为全部字段的确定性拼接。
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
    "CognitiveVectorGenerationBuildResult",
    "cognitive_vector_ref",
    "cognitive_vector_text",
)
