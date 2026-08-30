"""Session 亲和性：跨会话召回降权。

规则：
  同 session          → 1.0
  code session → companion  code-type 降权到 0.5，person/preference 召回权重为 0.8
  Legacy same-session recency heuristic with an explicit seven-day constant.
"""

from __future__ import annotations

# 跨 session 降权系数
CROSS_SESSION_CODE_TYPE = 0.5  # code 类 fact 跨 session 降权
CROSS_SESSION_PERSON_TYPE = 0.8  # person/preference 跨 session 召回权重

# 同 session 时间衰减
SESSION_HALF_LIFE_DAYS = 7.0
SESSION_DECAY_FLOOR = 0.15

# 属于"人物/偏好"类的 fact category（跨 session 召回权重更高；不是保留周期）
PERSON_CATEGORIES = frozenset(
    {"profile", "preference", "goal", "decision", "constraint", "reflection"}
)


def cross_session_weight(source_session: str, target_session: str, category: str = "") -> float:
    """计算跨会话召回的降权系数。

    Args:
        source_session: 消息所在的 session_id
        target_session: 当前召回的 session_id
        category:       消息关联的 Fact category（可为空）

    Returns:
        权重系数 0.0-1.0
    """
    if source_session == target_session:
        return 1.0
    if category in PERSON_CATEGORIES:
        return CROSS_SESSION_PERSON_TYPE
    return CROSS_SESSION_CODE_TYPE


def temporal_affinity(age_days: float) -> float:
    """同 session 内基于时间的亲和度衰减。

    使用半衰期为 7 天的指数衰减，floor 为 0.15。
    """
    decayed = 0.5 ** (age_days / SESSION_HALF_LIFE_DAYS)
    return max(SESSION_DECAY_FLOOR, decayed)
