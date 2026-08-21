"""Summarizer — 旧会话记忆压缩。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from simple_harness_memory.core.models import Message


class Summarizer(ABC):
    @abstractmethod
    async def summarize(self, messages: list[Message]) -> str: ...


class RuleBasedSummarizer(Summarizer):
    def __init__(self, max_chars: int = 1200) -> None:
        self._max_chars = max_chars

    async def summarize(self, messages: list[Message]) -> str:
        if not messages:
            return ""
        ordered = sorted(messages, key=lambda m: m.created_at)
        texts = [m.content.strip() for m in ordered if m.role == "user"]
        if not texts:
            return ""
        body = "；".join(texts)
        if len(body) > self._max_chars:
            body = body[: self._max_chars] + "…"
        return f"[会话摘要] {body}"


class LLMSummarizer(Summarizer):
    def __init__(self, client: Any, model: str = "gpt-4.1-mini") -> None:
        self._client = client
        self._model = model

    async def summarize(self, messages: list[Message]) -> str:
        if not messages:
            return ""
        transcript = "\n".join(
            f"{m.role}: {m.content}" for m in sorted(messages, key=lambda x: x.created_at)
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "用中文压缩对话：" + transcript}],
                temperature=0,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""
