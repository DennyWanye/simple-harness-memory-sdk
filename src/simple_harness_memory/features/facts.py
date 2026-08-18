"""Facts 自动提取（规则提取 + 可选 LLM 提取）。"""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Any

from simple_harness_memory.core.models import Fact


class FactExtractor(ABC):
    @abstractmethod
    async def extract(
        self, content: str, *, role: str = "user", message_id: int = 0,
        created_at: float | None = None, subject: str = "user",
    ) -> list[Fact]: ...


class RuleBasedFactExtractor(FactExtractor):
    _RULES: tuple[tuple[str, str, re.Pattern[str], float, int], ...] = (
        ("profile", "name", re.compile(r"我叫([^，。！？,、\s的]{1,20})"), 0.9, 1),
        ("profile", "name", re.compile(r"我的名字是?([^，。！？,、\s的]{1,20})"), 0.9, 1),
        ("profile", "occupation", re.compile(r"我(?:是|做|干)(?:一名|一个|一位|名|个|位)?([^，。！？,、\s的]{1,20})"), 0.6, 1),
        ("profile", "location", re.compile(r"我(?:住在|在|来自)([^，。！？,、\s的]{1,20})"), 0.6, 1),
        ("profile", "language", re.compile(r"我(?:常用|使用|说)的语言?是?([^，。！？,、\s的]{1,20})"), 0.5, 1),
        ("profile", "pet_name", re.compile(r"(?:我)?(?:养了?|有一只)(?:一只|一条|一个|只|条|个)?(?:叫|名字叫)?([^，。！？,、\s的]{1,20})(?:的)?(?:狗|猫|宠物|仓鼠|鱼)"), 0.7, 1),
        ("preference", "prefers", re.compile(r"(?:很|非常|比较|特别)?(?:喜欢|爱|偏好|偏爱)(?:吃|喝|看|听|用)?([^，。！？,、\s的]{1,30})"), 0.55, 1),
        ("learning", "skill", re.compile(r"我(?:擅长|精通)([^，。！？,、\s的]{1,30})"), 0.6, 1),
        ("goal", "goal", re.compile(r"我(?:打算|计划|目标(?:是)?|希望)([^，。！？,、\s的]{1,50})"), 0.6, 1),
        ("event", "event", re.compile(r"(?:昨天|今天|前天|上周|上个月|最近)(?:我)?(?:去了|到了|在)([^，。！？,、\s的]{1,20})"), 0.55, -1),
    )

    async def extract(self, content, *, role="user", message_id=0, created_at=None, subject="user"):
        if role != "user":
            return []
        ts = created_at if created_at is not None else time.time()
        facts: list[Fact] = []
        seen: set[tuple[str, str, str]] = set()
        for category, key, pattern, confidence, group in self._RULES:
            for match in pattern.finditer(content):
                value = (match.group(0) if group == -1 else match.group(group)).strip()
                if not value:
                    continue
                dedup = (subject, key, value)
                if dedup in seen:
                    continue
                seen.add(dedup)
                facts.append(Fact(
                    id=None, subject=subject, key=key, value=value, category=category,
                    confidence=confidence, evidence=content, source_msg_id=message_id, created_at=ts,
                ))
        return facts


class LLMFactExtractor(FactExtractor):
    def __init__(self, client: Any, model: str = "gpt-4.1-mini") -> None:
        self._client = client
        self._model = model

    async def extract(self, content, *, role="user", message_id=0, created_at=None, subject="user"):
        if role != "user":
            return []
        import json as _json
        ts = created_at if created_at is not None else time.time()
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "提取事实为 JSON 数组(key/category/value/confidence)：\n" + content}],
                temperature=0,
            )
            raw = resp.choices[0].message.content
            parsed = _json.loads(raw or "[]")
        except Exception:
            return []
        facts: list[Fact] = []
        for item in parsed:
            key = str(item.get("key", "")).strip()
            value = str(item.get("value", "")).strip()
            if not key or not value:
                continue
            facts.append(Fact(
                id=None, subject=subject, key=key, value=value,
                category=str(item.get("category", "profile")).strip(),
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0.7)))),
                evidence=content, source_msg_id=message_id, created_at=ts,
            ))
        return facts
