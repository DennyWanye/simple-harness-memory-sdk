"""Product-neutral public ports for the memory SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    FactConflict,
    Hit,
    MemoryApplyResult,
    Message,
)
from simple_harness_memory.core.twin import DigitalTwin


class MemoryBackend(ABC):
    """Memory backend contract with explicit, immutable user ownership."""

    @abstractmethod
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str,
        source_event_id: str,
        payload_hash: str | None = None,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> MemoryApplyResult: ...

    @abstractmethod
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Message]: ...

    @abstractmethod
    async def get_message(self, message_id: int, *, user_id: str) -> Message | None: ...

    @abstractmethod
    async def extract_facts(
        self,
        message_id: int,
        content: str,
        role: str,
        *,
        user_id: str,
    ) -> list[Fact]: ...

    @abstractmethod
    async def get_facts(
        self,
        subject: str = "user",
        category: str | None = None,
        active_only: bool = True,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> list[Fact]: ...

    @abstractmethod
    async def forget_fact(self, fact_id: int, reason: str = "", *, user_id: str) -> bool: ...

    @abstractmethod
    async def get_digital_twin(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> DigitalTwin: ...

    @abstractmethod
    async def update_digital_twin(self, twin: DigitalTwin, *, user_id: str) -> None: ...

    @abstractmethod
    async def suggest_questions(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[str]: ...

    @abstractmethod
    async def detect_inconsistencies(
        self,
        subject: str = "user",
        *,
        user_id: str,
    ) -> list[FactConflict]: ...

    @abstractmethod
    async def recall(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def recall_bounded(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context_query_id: str,
        query_hash: str | None = None,
        max_results: int | None = None,
        max_bytes: int | None = None,
        timeout_seconds: float | None = None,
    ) -> BoundedRecallResult: ...

    @abstractmethod
    async def release_recall_result(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
    ) -> None: ...

    @abstractmethod
    async def cleanup_recall_results(
        self,
        *,
        user_id: str,
        now: float | None = None,
        limit: int | None = None,
    ) -> int: ...

    @abstractmethod
    async def recall_and_reinforce(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 10,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def vector_search(
        self,
        query: str,
        limit: int = 20,
        *,
        user_id: str,
    ) -> list[Hit]: ...

    @abstractmethod
    async def daily_decay(
        self,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
        *,
        user_id: str,
    ) -> dict[str, int]: ...

    @abstractmethod
    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
        *,
        user_id: str,
    ) -> None: ...

    @abstractmethod
    async def delete_session(self, session_id: str, *, user_id: str) -> int: ...

    @abstractmethod
    async def delete_all(self) -> None:
        """Deprecated compatibility surface; always fails closed."""

    @abstractmethod
    async def delete_old_sessions(
        self,
        older_than_days: float = 30.0,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> int: ...

    @abstractmethod
    async def reindex(
        self,
        embedder=None,
        *,
        user_id: str,
        limit: int | None = None,
    ) -> int: ...

    async def initialize(self) -> None:
        """Initialize the backend."""

    async def close(self) -> None:
        """Close the backend."""

    async def diagnostics_snapshot(self) -> dict[str, object]:
        """Return bounded aggregate operational health."""

        return {"health": "healthy"}

    async def __aenter__(self) -> MemoryBackend:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class AgentMemoryBackend(Protocol):
    """Internal v4 backend surface consumed by the direct AgentMemory integration."""

    async def agent_recall(
        self,
        *,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        query_id: str,
        query_hash: str,
        query_text: str,
        max_items: int,
        max_bytes: int,
    ) -> tuple[dict[str, object], str, bool]: ...

    async def agent_record_turn(
        self,
        *,
        principal: MemoryPrincipal,
        scope: MemoryScope,
        turn_id: str,
        payload_hash: str,
        user_text: str,
        assistant_text: str,
        write_fence: str | None,
        turn_started_at: float,
    ) -> tuple[str, str]: ...

    async def agent_export(
        self,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, object]], int | None]: ...

    async def agent_delete_scopes(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> dict[str, int | str]: ...
