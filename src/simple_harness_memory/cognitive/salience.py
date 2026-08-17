"""显著性机制（Spreading Activation 理论）。

每次被召回：salience += SALIENCE_RECALL_DELTA
每日衰减：见 cognitive/decay.py
"""
from __future__ import annotations

from simple_harness_memory.cognitive.decay import SALIENCE_RECALL_DELTA, bump_salience

__all__ = ["SALIENCE_RECALL_DELTA", "bump_salience", "compute_salience_score"]


def compute_salience_score(salience: float, recall_count: int) -> float:
    """基于显著性和召回次数计算综合得分（0.0-1.0）。"""
    base = min(1.0, salience)
    boost = min(0.5, recall_count * 0.05)  # 最多 +0.5
    return min(1.0, base + boost)
