"""遗忘曲线（Ebbinghaus Forgetting Curve）。

衰减公式：
    retention = exp(-decay_rate * days_since_last_recall)
    new_salience = base_salience * retention

每日 decay 任务：
- 对所有非 pinned、非 forgotten 的 Message / Fact 执行衰减
- 当 retention < FORGET_THRESHOLD 时标记为 forgotten
"""

from __future__ import annotations

import math
import time

# 遗忘阈值：retention 低于此值时触发显式遗忘
FORGET_THRESHOLD = 0.05

# 显著性每次召回增量
SALIENCE_RECALL_DELTA = 0.05

# 显著性衰减下限（不会衰减到 0）
SALIENCE_FLOOR = 0.0


def retention(decay_rate: float, days_elapsed: float) -> float:
    """计算经过 days_elapsed 天后的保留率（0.0-1.0）。

    Args:
        decay_rate:   衰减率（见 FACT_DECAY_DEFAULTS）
        days_elapsed: 距上次召回的天数

    Returns:
        保留率，1.0 表示完全保留，0.0 表示完全遗忘
    """
    if decay_rate <= 0.0:
        return 1.0
    return math.exp(-decay_rate * max(0.0, days_elapsed))


def should_forget(decay_rate: float, days_elapsed: float) -> bool:
    """判断是否应该触发遗忘。"""
    return retention(decay_rate, days_elapsed) < FORGET_THRESHOLD


def decay_salience(current_salience: float, decay_rate: float, days_elapsed: float) -> float:
    """对显著性值应用衰减。"""
    decayed = current_salience * retention(decay_rate, days_elapsed)
    return max(SALIENCE_FLOOR, decayed)


def bump_salience(current_salience: float, delta: float = SALIENCE_RECALL_DELTA) -> float:
    """召回时提升显著性（上限 1.0）。"""
    return min(1.0, current_salience + delta)


def days_since(unix_ts: float) -> float:
    """计算距某个 Unix 时间戳经过的天数。"""
    return (time.time() - unix_ts) / 86400.0
