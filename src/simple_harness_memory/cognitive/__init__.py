"""simple_harness_memory.cognitive — 认知机制（遗忘曲线、显著性、会话亲和性）。"""
from simple_harness_memory.cognitive.decay import (
    FORGET_THRESHOLD,
    SALIENCE_RECALL_DELTA,
    bump_salience,
    days_since,
    decay_salience,
    retention,
    should_forget,
)
from simple_harness_memory.cognitive.session_affinity import (
    cross_session_weight,
    temporal_affinity,
)
from simple_harness_memory.cognitive.twin_builder import (
    build_twin_from_facts,
    detect_fact_conflicts,
)

__all__ = [
    "retention", "should_forget", "decay_salience", "bump_salience", "days_since",
    "FORGET_THRESHOLD", "SALIENCE_RECALL_DELTA",
    "cross_session_weight", "temporal_affinity",
    "build_twin_from_facts", "detect_fact_conflicts",
]
