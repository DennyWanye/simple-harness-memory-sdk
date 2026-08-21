"""RRF（Reciprocal Rank Fusion）融合算法。

核心公式（Cormack 2009，k=60）：
    rrf_score(item) = Σ  weight[source] / (k + rank[source])

六路信号权重：
    vec      0.5   BGE-M3 向量语义相似度
    fts      0.3   FTS5 全文关键词匹配
    recency  0.15  时间新近度
    salience 0.05  显著性（被召回次数）
    facts    0.2   结构化 Facts 路
    entity   0.1   实体索引路
"""

from __future__ import annotations

from dataclasses import dataclass

# 各召回源的 RRF 权重
SIGNAL_WEIGHTS: dict[str, float] = {
    "vec": 0.5,
    "fts": 0.3,
    "recency": 0.15,
    "salience": 0.05,
    "facts": 0.2,
    "entity": 0.1,
}

RRF_K = 60  # Cormack 2009 推荐值


@dataclass
class RankedItem:
    """单路召回中的排名项。"""

    message_id: int
    text: str
    rank: int  # 1-based
    source: str
    raw_score: float = 0.0
    recency: float = 0.0
    salience: float = 0.0
    session_affinity: float = 1.0
    session_id: str | None = None
    role: str | None = None
    created_at: float | None = None


def fuse(
    ranked_lists: list[list[RankedItem]],
    k: int = RRF_K,
    weights: dict[str, float] | None = None,
    limit: int = 10,
) -> list[dict]:
    """将多路排名列表 RRF 融合为统一排名。

    Args:
        ranked_lists: 每路召回的 RankedItem 列表（已按 rank 升序）。
        k:            RRF 平滑系数（默认 60）。
        weights:      各 source 的权重覆盖（None 使用 SIGNAL_WEIGHTS）。
        limit:        返回 top-N 结果。

    Returns:
        按 rrf_score 降序排列的融合结果列表，每项为 dict。
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    bounded_limit = min(limit, 4096)
    candidate_cap = min(max(bounded_limit * 8, 256), 32768)
    w = weights or SIGNAL_WEIGHTS
    scores: dict[int, float] = {}
    meta: dict[int, RankedItem] = {}

    for ranked in ranked_lists:
        for item in ranked[:candidate_cap]:
            weight = w.get(item.source, 0.1)
            contrib = weight / (k + item.rank)
            scores[item.message_id] = scores.get(item.message_id, 0.0) + contrib
            # 保留最高信号的元数据
            if item.message_id not in meta or item.raw_score > meta[item.message_id].raw_score:
                meta[item.message_id] = item

    sorted_ids = sorted(scores, key=lambda mid: (-scores[mid], mid))[:bounded_limit]
    result = []
    for mid in sorted_ids:
        item = meta[mid]
        result.append(
            {
                "message_id": mid,
                "text": item.text,
                "score": round(scores[mid], 6),
                "source": item.source,
                "recency": item.recency,
                "salience": item.salience,
                "session_affinity": item.session_affinity,
                "session_id": item.session_id,
                "role": item.role,
                "created_at": item.created_at,
            }
        )
    return result
