"""单元测试：RRF 融合算法。"""

from __future__ import annotations

from simple_harness_memory.features.rrf import RankedItem, fuse


def _make_ranked(items: list[tuple[int, str, str]]) -> list[RankedItem]:
    """辅助：[(message_id, text, source), ...] → RankedItem 列表。"""
    return [
        RankedItem(message_id=mid, text=text, rank=i + 1, source=source)
        for i, (mid, text, source) in enumerate(items)
    ]


def test_fuse_single_list_preserves_order() -> None:
    ranked = _make_ranked([(1, "msg1", "fts"), (2, "msg2", "fts"), (3, "msg3", "fts")])
    result = fuse([ranked])
    assert [r["message_id"] for r in result] == [1, 2, 3]


def test_fuse_deduplicates_across_sources() -> None:
    vec_ranked = _make_ranked([(1, "msg1", "vec"), (2, "msg2", "vec")])
    fts_ranked = _make_ranked([(2, "msg2", "fts"), (1, "msg1", "fts"), (3, "msg3", "fts")])
    result = fuse([vec_ranked, fts_ranked])
    ids = [r["message_id"] for r in result]
    # 不应出现重复 ID
    assert len(ids) == len(set(ids))
    # 总数不超过去重后的消息数
    assert len(ids) <= 3


def test_fuse_boosted_by_multiple_sources() -> None:
    """同时出现在多路召回中的消息，RRF 分数应更高。"""
    vec_ranked = _make_ranked([(5, "boosted", "vec"), (6, "only_vec", "vec")])
    fts_ranked = _make_ranked([(7, "only_fts", "fts"), (5, "boosted", "fts")])
    result = fuse([vec_ranked, fts_ranked])
    # message_id=5 在两路都出现，应排第一
    assert result[0]["message_id"] == 5


def test_fuse_respects_limit() -> None:
    ranked = _make_ranked([(i, f"msg{i}", "fts") for i in range(20)])
    result = fuse([ranked], limit=5)
    assert len(result) == 5


def test_fuse_empty_input() -> None:
    result = fuse([])
    assert result == []


def test_fuse_scores_sum_correctly() -> None:
    """验证 RRF 分数公式：weight / (k + rank)，精度到小数点后6位。"""
    from simple_harness_memory.features.rrf import RRF_K, SIGNAL_WEIGHTS

    ranked = [RankedItem(message_id=1, text="x", rank=1, source="vec")]
    result = fuse([ranked])
    expected = SIGNAL_WEIGHTS["vec"] / (RRF_K + 1)
    assert abs(result[0]["score"] - expected) < 1e-6


def test_fuse_custom_weights() -> None:
    vec = _make_ranked([(1, "a", "vec")])
    fts = _make_ranked([(2, "b", "fts")])
    # 给 fts 极高权重，让 id=2 排第一
    result = fuse([vec, fts], weights={"vec": 0.01, "fts": 99.0})
    assert result[0]["message_id"] == 2
