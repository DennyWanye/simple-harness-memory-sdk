"""Regex extractor retained exclusively as an old-schema test fixture."""

from __future__ import annotations

import re
import time

from simple_harness_memory.core.models import Fact


class LegacyRegexFactExtractor:
    _RULES: tuple[tuple[str, str, re.Pattern[str], float, int], ...] = (
        ("profile", "name", re.compile(r"我叫([^，。！？,、\s的]{1,20})"), 0.9, 1),
        (
            "profile",
            "pet_name",
            re.compile(
                r"(?:我)?(?:养了?|有一只)(?:一只|一条|一个|只|条|个)?"
                r"(?:叫|名字叫)?([^，。！？,、\s的]{1,20})(?:的)?(?:狗|猫|宠物|仓鼠|鱼)"
            ),
            0.7,
            1,
        ),
        (
            "preference",
            "prefers",
            re.compile(
                r"(?:很|非常|比较|特别)?(?:喜欢|爱|偏好|偏爱)"
                r"(?:吃|喝|看|听|用)?([^，。！？,、\s的]{1,30})"
            ),
            0.55,
            1,
        ),
    )

    async def extract(
        self,
        content: str,
        *,
        role: str = "user",
        message_id: int = 0,
        created_at: float | None = None,
        subject: str = "user",
        user_id: str = "",
        **_: object,
    ) -> list[Fact]:
        if role != "user":
            return []
        timestamp = created_at if created_at is not None else time.time()
        facts: list[Fact] = []
        seen: set[tuple[str, str, str]] = set()
        for category, key, pattern, confidence, group in self._RULES:
            for match in pattern.finditer(content):
                value = match.group(group).strip()
                identity = (subject, key, value)
                if not value or identity in seen:
                    continue
                seen.add(identity)
                facts.append(
                    Fact(
                        id=None,
                        user_id=user_id,
                        subject=subject,
                        key=key,
                        value=value,
                        category=category,
                        confidence=confidence,
                        evidence=content,
                        source_msg_id=message_id,
                        created_at=timestamp,
                    )
                )
        return facts
