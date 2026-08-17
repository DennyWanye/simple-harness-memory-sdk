"""知识边界检测（Phase 4）。

检测查询中是否包含时间敏感词，判断 LLM 知识截止日期后的内容。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Optional

from simple_harness_memory.world.port import KnowledgeGap

# 时间敏感词模式
_TIME_SENSITIVE_PATTERNS = re.compile(
    r"最近|今天|现在|最新|当前|今年|本周|本月|刚刚|昨天|近期|最近几[天周月年]|"
    r"today|latest|current|recent|now|this (week|month|year)",
    re.IGNORECASE,
)

# 建议工具映射
_TOOL_SUGGESTIONS: dict[str, list[str]] = {
    "news":    ["web_search"],
    "weather": ["weather_api"],
    "stock":   ["financial_api"],
    "default": ["web_search"],
}


def detect_knowledge_gap(
    query: str,
    cutoff_date: str = "2026-05-31",
) -> Optional[KnowledgeGap]:
    """检测查询是否涉及知识截止日期后的内容。

    Args:
        query:        用户查询字符串
        cutoff_date:  LLM 训练截止日期（ISO格式）

    Returns:
        KnowledgeGap 实例（如有），或 None
    """
    terms = _TIME_SENSITIVE_PATTERNS.findall(query)
    if not terms:
        return None

    now = datetime.now(tz=timezone.utc)
    current_date = now.strftime("%Y-%m-%d")
    try:
        cutoff_dt = datetime.fromisoformat(cutoff_date)
        gap_days = (now.date() - cutoff_dt.date()).days
    except ValueError:
        gap_days = 0

    return KnowledgeGap(
        cutoff_date=cutoff_date,
        current_date=current_date,
        gap_days=max(0, gap_days),
        time_sensitive_terms=terms,
        suggested_tools=_TOOL_SUGGESTIONS["default"],
    )
