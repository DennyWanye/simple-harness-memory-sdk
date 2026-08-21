"""In-memory backend with the same ownership/idempotency contract as SQLite."""

from __future__ import annotations

import time

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
)
from simple_harness_memory.core.models import (
    Fact,
    MemoryApplyResult,
    MemoryApplyStatus,
    Message,
)
from simple_harness_memory.core.twin import DigitalTwin


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


class MockMemoryBackend(BaseMemoryBackend):
    def __init__(
        self,
        *,
        embedder=None,
        fact_extractor=None,
        reranker=None,
        summarizer=None,
        auto_extract_facts: bool = False,
        bounds: MemoryResourceBounds | None = None,
    ) -> None:
        super().__init__(
            embedder=embedder,
            fact_extractor=fact_extractor,
            reranker=reranker,
            summarizer=summarizer,
            auto_extract_facts=auto_extract_facts,
            bounds=bounds,
        )
        self._messages: list[Message] = []
        self._facts: list[Fact] = []
        self._twins: dict[str, DigitalTwin] = {}
        self._workspace_actions: list[tuple[str, str, str, dict, float]] = []
        self._sessions: dict[str, tuple[str, float]] = {}
        self._source_events: dict[str, tuple[str, str, int]] = {}
        self._recall_snapshots: dict[str, dict[str, object]] = {}
        self._next_msg_id = 1
        self._next_fact_id = 1

    async def _ensure_session_impl(self, user_id: str, session_id: str) -> None:
        owner = self._sessions.get(session_id)
        if owner is None:
            self._sessions[session_id] = (user_id, time.time())
        elif owner[0] != user_id:
            raise MemoryOwnershipConflict()

    async def _append_message_impl(
        self,
        *,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        embedding: bytes | None,
        salience: float,
        decay_rate: float,
        created_at: float,
        is_summary: bool,
        summary_of: str | None,
        source_event_id: str,
        payload_hash: str,
        embedder_kind: str | None,
        embedding_dim: int | None,
        embedding_format_version: int | None,
    ) -> MemoryApplyResult:
        previous = self._source_events.get(source_event_id)
        if previous is not None:
            previous_user, previous_hash, message_id = previous
            if previous_user != user_id or previous_hash != payload_hash:
                raise MemoryIdempotencyConflict()
            return MemoryApplyResult(
                message_id=message_id,
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                status=MemoryApplyStatus.ALREADY_APPLIED,
            )
        message_id = self._next_msg_id
        self._next_msg_id += 1
        self._messages.append(
            Message(
                id=message_id,
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                created_at=created_at,
                salience=salience,
                decay_rate=decay_rate,
                embedding=embedding,
                is_summary=is_summary,
                summary_of=summary_of,
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                embedder_kind=embedder_kind,
                embedding_dim=embedding_dim,
                embedding_format_version=embedding_format_version,
            )
        )
        self._sessions[session_id] = (user_id, created_at)
        self._source_events[source_event_id] = (user_id, payload_hash, message_id)
        return MemoryApplyResult(
            message_id=message_id,
            source_event_id=source_event_id,
            payload_hash=payload_hash,
            status=MemoryApplyStatus.APPLIED,
        )

    async def _get_source_event_impl(
        self, user_id: str, source_event_id: str
    ) -> tuple[int, str] | None:
        previous = self._source_events.get(source_event_id)
        if previous is None or previous[0] != user_id:
            return None
        return previous[2], previous[1]

    async def _get_message_impl(self, user_id: str, message_id: int) -> Message | None:
        return next(
            (
                message
                for message in self._messages
                if message.user_id == user_id and message.id == message_id
            ),
            None,
        )

    async def _query_messages_impl(
        self,
        user_id: str,
        *,
        limit: int,
        session_id: str | None = None,
        older_than: float | None = None,
        lineage_mismatch: tuple[str, int, int] | None = None,
    ) -> list[Message]:
        messages = [message for message in self._messages if message.user_id == user_id]
        if session_id is not None:
            messages = [message for message in messages if message.session_id == session_id]
        if older_than is not None:
            messages = [message for message in messages if message.created_at < older_than]
        if lineage_mismatch is not None:
            kind, dim, version = lineage_mismatch
            messages = [
                message
                for message in messages
                if (
                    message.embedder_kind,
                    message.embedding_dim,
                    message.embedding_format_version,
                )
                != (kind, dim, version)
            ]
        messages.sort(key=lambda message: (message.created_at, message.id or 0), reverse=True)
        return messages[:limit]

    async def _query_facts_impl(
        self,
        user_id: str,
        *,
        limit: int,
        subject: str | None = None,
        category: str | None = None,
        active_only: bool = False,
    ) -> list[Fact]:
        facts = [fact for fact in self._facts if fact.user_id == user_id]
        if subject is not None:
            facts = [fact for fact in facts if fact.subject == subject]
        if category is not None:
            facts = [fact for fact in facts if fact.category == category]
        if active_only:
            facts = [fact for fact in facts if fact.is_active]
        facts.sort(key=lambda fact: fact.id or 0, reverse=True)
        return facts[:limit]

    async def _insert_fact_impl(self, user_id: str, fact: Fact) -> int:
        fact.id = self._next_fact_id
        fact.user_id = user_id
        self._next_fact_id += 1
        self._facts.append(fact)
        return fact.id

    async def _supersede_fact_impl(self, user_id: str, fact_id: int, superseded_by: int) -> None:
        for fact in self._facts:
            if fact.user_id == user_id and fact.id == fact_id:
                fact.superseded_by = superseded_by

    async def _forget_fact_by_id_impl(
        self, user_id: str, fact_id: int, forgotten_at: float
    ) -> bool:
        for fact in self._facts:
            if fact.user_id == user_id and fact.id == fact_id:
                fact.forgotten_at = forgotten_at
                return True
        return False

    async def _update_message_salience_impl(
        self,
        user_id: str,
        message_id: int,
        salience: float,
        last_recalled: float | None,
        last_decay_at: float | None = None,
    ) -> None:
        for message in self._messages:
            if message.user_id == user_id and message.id == message_id:
                message.salience = salience
                if last_recalled is not None:
                    message.last_recalled = last_recalled
                if last_decay_at is not None:
                    message.last_decay_at = last_decay_at

    async def _set_fact_decay_impl(
        self,
        user_id: str,
        fact_id: int,
        *,
        forgotten_at: float | None = None,
        last_decay_at: float | None = None,
    ) -> None:
        for fact in self._facts:
            if fact.user_id == user_id and fact.id == fact_id:
                if forgotten_at is not None:
                    fact.forgotten_at = forgotten_at
                if last_decay_at is not None:
                    fact.last_decay_at = last_decay_at

    async def _load_twin_impl(self, user_id: str, subject: str) -> DigitalTwin:
        twin = self._twins.get(user_id)
        if twin is not None and twin.subject != subject:
            raise MemoryOwnershipConflict("digital twin subject conflict")
        return twin or DigitalTwin(subject=subject)

    async def _save_twin_impl(self, user_id: str, twin: DigitalTwin) -> None:
        self._twins[user_id] = twin

    async def _record_workspace_impl(
        self, user_id: str, session_id: str, action_type: str, payload: dict
    ) -> None:
        self._workspace_actions.append((user_id, session_id, action_type, payload, time.time()))

    async def _delete_session_impl(self, user_id: str, session_id: str) -> int:
        ids = {
            message.id
            for message in self._messages
            if message.user_id == user_id and message.session_id == session_id
        }
        before = len(ids)
        self._messages = [
            message
            for message in self._messages
            if not (message.user_id == user_id and message.session_id == session_id)
        ]
        self._facts = [
            fact
            for fact in self._facts
            if not (fact.user_id == user_id and fact.source_msg_id in ids)
        ]
        self._workspace_actions = [
            action
            for action in self._workspace_actions
            if not (action[0] == user_id and action[1] == session_id)
        ]
        self._recall_snapshots = {
            key: value
            for key, value in self._recall_snapshots.items()
            if not (value["user_id"] == user_id and value["session_id"] == session_id)
        }
        owner = self._sessions.get(session_id)
        if owner is not None and owner[0] == user_id:
            del self._sessions[session_id]
        self._source_events = {
            event_id: record
            for event_id, record in self._source_events.items()
            if record[2] not in ids
        }
        existing_ids = {fact.id for fact in self._facts}
        for fact in self._facts:
            if fact.superseded_by not in existing_ids:
                fact.superseded_by = None
        return before

    async def _old_session_ids_impl(self, user_id: str, cutoff: float, limit: int) -> list[str]:
        matches = [
            (session_id, value[1])
            for session_id, value in self._sessions.items()
            if value[0] == user_id and value[1] < cutoff
        ]
        matches.sort(key=lambda item: (item[1], item[0]))
        return [session_id for session_id, _ in matches[:limit]]

    async def _update_embedding_impl(
        self,
        user_id: str,
        message_id: int,
        embedding: bytes,
        embedder_kind: str,
        embedding_dim: int,
        embedding_format_version: int,
    ) -> None:
        for message in self._messages:
            if message.user_id == user_id and message.id == message_id:
                message.embedding = embedding
                message.embedder_kind = embedder_kind
                message.embedding_dim = embedding_dim
                message.embedding_format_version = embedding_format_version

    async def _get_recall_snapshot_impl(
        self, user_id: str, context_query_id: str
    ) -> tuple[str, str, str, str, str] | None:
        row = self._recall_snapshots.get(context_query_id)
        if row is None or row["user_id"] != user_id:
            return None
        return (
            str(row["user_id"]),
            str(row["session_id"]),
            str(row["query_hash"]),
            str(row["result_payload"]),
            str(row["result_hash"]),
        )

    async def _insert_recall_snapshot_impl(
        self,
        *,
        context_query_id: str,
        user_id: str,
        session_id: str,
        query_hash: str,
        result_payload: str,
        result_hash: str,
        created_at: float,
    ) -> None:
        if context_query_id in self._recall_snapshots:
            raise MemoryIdempotencyConflict()
        self._recall_snapshots[context_query_id] = {
            "user_id": user_id,
            "session_id": session_id,
            "query_hash": query_hash,
            "result_payload": result_payload,
            "result_hash": result_hash,
            "state": "retained",
            "created_at": created_at,
            "released_at": None,
        }

    async def _release_recall_snapshot_impl(
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
        released_at: float,
    ) -> bool:
        row = self._recall_snapshots.get(context_query_id)
        if row is None or row["user_id"] != user_id or row["result_hash"] != result_hash:
            return False
        row["state"] = "released"
        if row["released_at"] is None:
            row["released_at"] = released_at
        return True

    async def _cleanup_recall_snapshots_impl(
        self, *, user_id: str, expired_before: float, limit: int
    ) -> int:
        candidates = sorted(
            (
                (key, row)
                for key, row in self._recall_snapshots.items()
                if row["user_id"] == user_id
                and (
                    (
                        row["state"] == "released"
                        and _as_float(row["released_at"]) <= expired_before
                    )
                    or (
                        row["state"] == "retained"
                        and _as_float(row["created_at"]) <= expired_before
                    )
                )
            ),
            key=lambda item: (
                _as_float(
                    item[1]["released_at"]
                    if item[1]["state"] == "released"
                    else item[1]["created_at"]
                ),
                item[0],
            ),
        )[:limit]
        for key, _ in candidates:
            del self._recall_snapshots[key]
        return len(candidates)
