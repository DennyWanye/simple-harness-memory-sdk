"""0.6.34 认知向量准入阈值的纯函数（DECISION-2026-09-09-vector-score-margin.md）。

钉死三条不变量：
① ``effective`` 恒 ≤ ``COGNITIVE_VECTOR_MIN_SCORE``——只放宽不收紧，0.6.33 已准入者判定不变；
② ``s ≥ effective`` 与「``s ≥ 0.45`` 或（``s ≥ FLOOR`` 且 ``s ≥ RATIO × 同类型最高分``）」逐点等价；
③ 无同类型参照（该类型没有算出余弦的候选）时退回冻结绝对阈值。
"""

from __future__ import annotations

import pytest

from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_VECTOR_MIN_SCORE,
    COGNITIVE_VECTOR_RELATIVE_FLOOR,
    COGNITIVE_VECTOR_RELATIVE_RATIO,
    cognitive_vector_admits,
    cognitive_vector_effective_min_score,
)


def test_frozen_parameters_are_the_adjudicated_values() -> None:
    assert COGNITIVE_VECTOR_MIN_SCORE == 0.45
    assert COGNITIVE_VECTOR_RELATIVE_FLOOR == 0.35
    assert COGNITIVE_VECTOR_RELATIVE_RATIO == 0.90


def test_effective_min_score_never_exceeds_the_frozen_absolute_threshold() -> None:
    assert cognitive_vector_effective_min_score(None) == COGNITIVE_VECTOR_MIN_SCORE
    for step in range(-100, 101):
        best = step / 100.0
        assert cognitive_vector_effective_min_score(best) <= COGNITIVE_VECTOR_MIN_SCORE


def test_scores_at_or_above_the_absolute_threshold_are_always_admitted() -> None:
    """0.6.33 的准入集合是 0.6.34 的子集（pin）：受影响的只有原本被拒的候选。"""

    for step in range(-100, 101):
        best = step / 100.0
        for offset in (0.0, 0.001, 0.05, 0.3, 0.55):
            score = COGNITIVE_VECTOR_MIN_SCORE + offset
            assert cognitive_vector_admits(score, best) is True


def test_admission_is_pointwise_equivalent_to_the_or_form() -> None:
    for best_step in range(-20, 101):
        best = best_step / 100.0
        for score_step in range(-20, 101):
            score = score_step / 100.0
            if score > best:
                # 同类型最高分按定义 ≥ 任何同类型候选分。
                continue
            expected = score >= COGNITIVE_VECTOR_MIN_SCORE or (
                score >= COGNITIVE_VECTOR_RELATIVE_FLOOR
                and score >= COGNITIVE_VECTOR_RELATIVE_RATIO * best
            )
            assert cognitive_vector_admits(score, best) is expected, (score, best)


def test_absolute_floor_blocks_rescue_when_nothing_in_the_store_is_close() -> None:
    """整库都不相关时不救援——C07 零召回子集的护栏。"""

    for best_step in range(0, 35):
        best = best_step / 100.0
        assert cognitive_vector_admits(best, best) is False


def test_type_best_itself_is_admitted_once_it_clears_the_floor() -> None:
    for best_step in range(35, 101):
        best = best_step / 100.0
        assert cognitive_vector_admits(best, best) is True


def test_missing_score_never_enters_the_lane() -> None:
    assert cognitive_vector_admits(None, None) is False
    assert cognitive_vector_admits(None, 0.9) is False


def test_reported_corpus_pair_lands_on_the_same_side_after_the_change() -> None:
    """Host 语料 C01-19：同一记忆的两次合理改写 0.4354 / 0.5839 跨在 0.45 两侧。"""

    flash, luna = 0.4354, 0.5839
    assert flash < COGNITIVE_VECTOR_MIN_SCORE <= luna
    # 各自都是本类型内的最高分（该类型只有这一条目标记忆过了资格门）。
    assert cognitive_vector_admits(flash, flash) is True
    assert cognitive_vector_admits(luna, luna) is True
    assert cognitive_vector_effective_min_score(flash) == pytest.approx(0.39186)
    assert cognitive_vector_effective_min_score(luna) == COGNITIVE_VECTOR_MIN_SCORE
