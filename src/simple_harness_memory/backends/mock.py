"""In-memory backend with the same ownership/idempotency contract as SQLite."""

from __future__ import annotations

import hashlib
import json
import time
import uuid

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope, ScopeKind
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


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return int(value)
    return 0


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
        self._sessions: dict[tuple[str, str], float] = {}
        self._source_events: dict[str, tuple[str, str, int]] = {}
        self._recall_snapshots: dict[str, dict[str, object]] = {}
        self._next_msg_id = 1
        self._next_fact_id = 1
        self._agent_bindings: dict[tuple[str, str], tuple[str, str]] = {}
        self._agent_meta: dict[int, tuple[str, str, str, str, str]] = {}
        self._agent_recalls: dict[str, dict[str, object]] = {}
        self._agent_epochs: dict[tuple[str, str, str, str], tuple[int, float | None]] = {}
        self._turn_receipts: dict[
            tuple[str, str], tuple[str, str, str, str, str, str, str, str]
        ] = {}
        self._fact_jobs: dict[str, dict[str, object]] = {}
        self._fact_tombstones: set[str] = set()
        self._agent_fact_meta: dict[int, tuple[str, str, str, str, str, str, str | None]] = {}

    @staticmethod
    def _agent_user(principal: MemoryPrincipal) -> str:
        return hashlib.sha256(
            "\x1f".join(
                (principal.deployment_id, principal.household_id, principal.actor_id)
            ).encode()
        ).hexdigest()

    def _bind_agent(self, principal: MemoryPrincipal) -> str:
        key = (principal.deployment_id, principal.session_id)
        expected = (principal.household_id, principal.actor_id)
        prior = self._agent_bindings.get(key)
        if prior is not None and prior != expected:
            raise MemoryOwnershipConflict()
        self._agent_bindings[key] = expected
        return self._agent_user(principal)

    def _epoch(self, principal: MemoryPrincipal, scope: MemoryScope) -> tuple[int, float | None]:
        scope.authorize(principal)
        key = (
            principal.deployment_id,
            principal.household_id,
            scope.kind.value,
            scope.owner_id,
        )
        return self._agent_epochs.setdefault(key, (0, None))

    @staticmethod
    def _fence(principal: MemoryPrincipal, scope: MemoryScope, epoch: int) -> str:
        return hashlib.sha256(
            repr(
                (
                    "simple-harness-memory/write-fence/v1",
                    principal.deployment_id,
                    principal.household_id,
                    scope.kind.value,
                    scope.owner_id,
                    epoch,
                )
            ).encode()
        ).hexdigest()

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
    ) -> tuple[dict[str, object], str, bool]:
        self._bind_agent(principal)
        personal = MemoryScope.personal(principal.actor_id)
        fence = self._fence(principal, personal, self._epoch(principal, personal)[0])
        prior = self._agent_recalls.get(query_id)
        binding = (
            principal.deployment_id,
            principal.household_id,
            principal.actor_id,
            principal.session_id,
        )
        if prior is not None:
            if (
                prior["query_hash"] != query_hash
                or prior["binding"] != binding
            ):
                raise MemoryIdempotencyConflict()
            previous_payload = prior["payload"]
            if not isinstance(previous_payload, dict):
                raise MemoryIdempotencyConflict()
            return dict(previous_payload), str(prior["fence"]), True
        allowed = {(scope.kind.value, scope.owner_id) for scope in scopes}
        for scope in scopes:
            scope.authorize(principal)
        rows = [
            message
            for message in reversed(self._messages)
            if message.id is not None
            and message.id in self._agent_meta
            and self._agent_meta[message.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_meta[message.id][3:] in allowed
        ]
        fact_rows = [
            fact
            for fact in reversed(self._facts)
            if fact.id in self._agent_fact_meta
            and self._agent_fact_meta[fact.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_fact_meta[fact.id][3:5] in allowed
            and fact.is_active
        ]
        truncated = len(rows) + len(fact_rows) > max_items
        candidates: list[dict[str, object]] = []
        for message in rows:
            meta = self._agent_meta[message.id or 0]
            candidates.append(
                {
                    "record_id": f"message:{message.id}",
                    "text": message.content,
                    "role": message.role,
                    "session_id": message.session_id,
                    "created_at": message.created_at,
                    "scope": {"kind": meta[3], "owner_id": meta[4]},
                }
            )
        for fact in fact_rows:
            fact_meta = self._agent_fact_meta[fact.id or 0]
            candidates.append(
                {
                    "record_id": f"fact:{fact.id}",
                    "text": fact.value,
                    "role": "memory_fact",
                    "session_id": None,
                    "created_at": fact.created_at,
                    "category": fact.category,
                    "scope": {"kind": fact_meta[3], "owner_id": fact_meta[4]},
                }
            )
        candidates.sort(key=lambda item: _as_float(item["created_at"]), reverse=True)
        items: list[dict[str, object]] = []
        for item in candidates[:max_items]:
            proposed = {"items": [*items, item], "truncated": truncated}
            if len(json.dumps(proposed, ensure_ascii=False).encode()) > max_bytes:
                truncated = True
                break
            items.append(item)
        payload: dict[str, object] = {"items": items, "truncated": truncated}
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        status = "truncated" if truncated else ("ready" if items else "empty")
        envelope = {
            "protocol": "simple-harness-agent-memory/recall-result/v1",
            "query_id": query_id,
            "query_hash": query_hash,
            "result_id": f"memory-recall/v1/{query_id}",
            "payload": payload,
            "status": status,
            "item_count": len(items),
            "byte_count": len(encoded.encode()),
            "write_fence": fence,
        }
        self._agent_recalls[query_id] = {
            "query_hash": query_hash,
            "binding": binding,
            "payload": payload,
            "fence": fence,
            "result_hash": hashlib.sha256(
                json.dumps(
                    envelope,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "released": False,
        }
        return payload, fence, False

    async def agent_release(self, *, query_id: str, query_hash: str, result_hash: str) -> None:
        row = self._agent_recalls.get(query_id)
        if row is None or row["query_hash"] != query_hash or row["result_hash"] != result_hash:
            raise MemoryIdempotencyConflict()
        row["released"] = True

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
    ) -> tuple[str, str]:
        key = (principal.deployment_id, turn_id)
        prior = self._turn_receipts.get(key)
        if prior is not None:
            expected_owner = (
                principal.household_id,
                principal.actor_id,
                principal.session_id,
                scope.kind.value,
                scope.owner_id,
            )
            if prior[0] != payload_hash or prior[3:] != expected_owner:
                raise MemoryIdempotencyConflict()
            return ("already_applied" if prior[1] == "applied" else prior[1], prior[2])
        user_id = self._bind_agent(principal)
        epoch, erased_at = self._epoch(principal, scope)
        rejected = write_fence is not None and write_fence != self._fence(principal, scope, epoch)
        if write_fence is None and erased_at is not None:
            rejected = not (turn_started_at > erased_at and turn_started_at <= time.time())
        status = "rejected_erased" if rejected else "applied"
        receipt_id = f"memory-turn/v1/{turn_id}"
        self._turn_receipts[key] = (
            payload_hash,
            status,
            receipt_id,
            principal.household_id,
            principal.actor_id,
            principal.session_id,
            scope.kind.value,
            scope.owner_id,
        )
        if rejected:
            return status, receipt_id
        ids: list[int] = []
        deployment_key = hashlib.sha256(principal.deployment_id.encode()).hexdigest()[:16]
        for role, content in (("user", user_text), ("assistant", assistant_text)):
            message_id = self._next_msg_id
            self._next_msg_id += 1
            self._messages.append(
                Message(
                    id=message_id,
                    user_id=user_id,
                    session_id=principal.session_id,
                    role=role,
                    content=content,
                    created_at=time.time(),
                    source_event_id=f"agent-turn/v1/{deployment_key}/{turn_id}/{role}",
                    payload_hash=hashlib.sha256(f"{payload_hash}\x1f{role}".encode()).hexdigest(),
                )
            )
            self._agent_meta[message_id] = (
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
                scope.kind.value,
                scope.owner_id,
            )
            ids.append(message_id)
        if self._auto_extract_facts:
            job_id = hashlib.sha256(
                f"fact-job\x1f{principal.deployment_id}\x1f{turn_id}".encode()
            ).hexdigest()
            self._fact_jobs[job_id] = {
                "job_id": job_id,
                "turn_id": turn_id,
                "deployment_id": principal.deployment_id,
                "household_id": principal.household_id,
                "actor_id": principal.actor_id,
                "session_id": principal.session_id,
                "scope_kind": scope.kind.value,
                "scope_owner": scope.owner_id,
                "source_msg_id": ids[0],
                "payload": user_text,
                "payload_hash": hashlib.sha256(user_text.encode()).hexdigest(),
                "erasure_epoch": epoch,
                "state": "pending",
                "attempts": 0,
                "next_attempt_at": time.time(),
                "created_at": time.time(),
            }
        return status, receipt_id

    async def recover_fact_jobs(self) -> None:
        for job in self._fact_jobs.values():
            if job["state"] == "claimed":
                job["state"] = "pending"

    async def claim_fact_job(self, *, lease_seconds: float = 30.0) -> dict[str, object] | None:
        del lease_seconds
        for job in self._fact_jobs.values():
            if job["state"] == "pending" and _as_float(job["next_attempt_at"]) <= time.time():
                job["state"] = "claimed"
                job["attempts"] = _as_int(job["attempts"]) + 1
                job["lease_token"] = uuid.uuid4().hex
                return dict(job)
        return None

    async def apply_fact_job(
        self, job: dict[str, object], facts: list[Fact], *, extractor_lineage: str
    ) -> str:
        current = self._fact_jobs.get(str(job["job_id"]))
        if current is None:
            return "erased"
        principal = MemoryPrincipal(
            str(job["deployment_id"]),
            str(job["household_id"]),
            str(job["actor_id"]),
            str(job["session_id"]),
        )
        scope = MemoryScope(ScopeKind(str(job["scope_kind"])), str(job["scope_owner"]))
        if self._epoch(principal, scope)[0] != _as_int(job["erasure_epoch"]):
            current["state"] = "erased"
            current["payload"] = None
            return "erased"
        extraction_hash = hashlib.sha256(
            json.dumps([(fact.key, fact.value) for fact in facts], ensure_ascii=False).encode()
        ).hexdigest()
        for index, fact in enumerate(facts):
            deterministic = hashlib.sha256(
                f"{job['job_id']}\x1f{index}\x1f{extraction_hash}".encode()
            ).hexdigest()
            if deterministic in self._fact_tombstones:
                continue
            fact.id = self._next_fact_id
            self._next_fact_id += 1
            fact.user_id = self._agent_user(principal)
            fact.source_msg_id = _as_int(job["source_msg_id"])
            self._facts.append(fact)
            self._agent_fact_meta[fact.id] = (
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
                scope.kind.value,
                scope.owner_id,
                deterministic,
                None,
            )
        current.update(
            state="applied",
            payload=None,
            extractor_lineage=extractor_lineage,
            extraction_hash=extraction_hash,
        )
        return "applied"

    async def fail_fact_job(self, job: dict[str, object], *, stable_code: str) -> None:
        current = self._fact_jobs[str(job["job_id"])]
        attempts = _as_int(current["attempts"])
        current["state"] = "dead_letter" if attempts >= 5 else "pending"
        current["next_attempt_at"] = time.time() + 2**attempts
        current["last_error_code"] = stable_code

    async def agent_export(
        self,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, object]], int | None]:
        self._bind_agent(principal)
        allowed = {(scope.kind.value, scope.owner_id) for scope in scopes}
        for scope in scopes:
            scope.authorize(principal)
        rows: list[tuple[float, dict[str, object]]] = [
            (
                message.created_at,
                {
                    "record_id": f"message:{message.id}",
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                    "scope": {
                        "kind": self._agent_meta[message.id or 0][3],
                        "owner_id": self._agent_meta[message.id or 0][4],
                    },
                },
            )
            for message in self._messages
            if message.id in self._agent_meta
            and self._agent_meta[message.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_meta[message.id][3:] in allowed
        ]
        rows.extend(
            (
                fact.created_at,
                {
                    "record_id": f"fact:{fact.id}",
                    "role": "memory_fact",
                    "content": fact.value,
                    "created_at": fact.created_at,
                    "scope": {
                        "kind": self._agent_fact_meta[fact.id or 0][3],
                        "owner_id": self._agent_fact_meta[fact.id or 0][4],
                    },
                },
            )
            for fact in self._facts
            if fact.id in self._agent_fact_meta
            and self._agent_fact_meta[fact.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_fact_meta[fact.id][3:5] in allowed
            and fact.is_active
        )
        rows.sort(key=lambda item: (item[0], str(item[1]["record_id"])))
        records = [record for _, record in rows[cursor : cursor + limit]]
        next_cursor = cursor + limit if len(rows) > cursor + limit and limit else None
        return records, next_cursor

    async def agent_delete_scopes(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> dict[str, int | str]:
        self._bind_agent(principal)
        allowed = {(scope.kind.value, scope.owner_id) for scope in scopes}
        for scope in scopes:
            scope.authorize(principal)
            key = (
                principal.deployment_id,
                principal.household_id,
                scope.kind.value,
                scope.owner_id,
            )
            epoch, _ = self._agent_epochs.setdefault(key, (0, None))
            self._agent_epochs[key] = (epoch + 1, time.time())
        ids = {
            message.id
            for message in self._messages
            if message.id in self._agent_meta
            and self._agent_meta[message.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_meta[message.id][3:] in allowed
        }
        fact_ids = {
            fact.id
            for fact in self._facts
            if fact.id in self._agent_fact_meta
            and self._agent_fact_meta[fact.id][:2]
            == (principal.deployment_id, principal.household_id)
            and self._agent_fact_meta[fact.id][3:5] in allowed
        }
        job_ids = [
            job_id
            for job_id, job in self._fact_jobs.items()
            if _as_int(job["source_msg_id"]) in ids
        ]
        for job_id in job_ids:
            self._fact_tombstones.add(f"job:{job_id}")
            del self._fact_jobs[job_id]
        self._messages = [message for message in self._messages if message.id not in ids]
        self._facts = [fact for fact in self._facts if fact.id not in fact_ids]
        for message_id in ids:
            if message_id is not None:
                self._agent_meta.pop(message_id, None)
        for fact_id in fact_ids:
            if fact_id is not None:
                self._agent_fact_meta.pop(fact_id, None)
        snapshots = len(
            [
                key
                for key, row in self._agent_recalls.items()
                if row["binding"]
                == (
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                )
            ]
        )
        self._agent_recalls = {
            key: row
            for key, row in self._agent_recalls.items()
            if row["binding"]
            != (
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
                principal.session_id,
            )
        }
        return {
            "messages": len(ids),
            "facts": len(fact_ids),
            "snapshots": snapshots,
            "jobs": len(job_ids),
            "receipt_id": uuid.uuid4().hex,
        }

    async def agent_forget_fact(self, principal: MemoryPrincipal, fact_id: int) -> bool:
        meta = self._agent_fact_meta.get(fact_id)
        if (
            meta is None
            or meta[:3]
            != (
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
            )
            or meta[3:5] != ("personal", principal.actor_id)
        ):
            return False
        deterministic = meta[5]
        self._fact_tombstones.add(deterministic)
        remove_ids = {
            stored_id
            for stored_id, stored in self._agent_fact_meta.items()
            if stored_id == fact_id or stored[6] == deterministic
        }
        self._facts = [fact for fact in self._facts if fact.id not in remove_ids]
        for stored_id in remove_ids:
            del self._agent_fact_meta[stored_id]
        return True

    async def agent_share_fact(self, principal: MemoryPrincipal, fact_id: int) -> str:
        meta = self._agent_fact_meta.get(fact_id)
        source = next((fact for fact in self._facts if fact.id == fact_id), None)
        if (
            meta is None
            or source is None
            or meta[:3]
            != (
                principal.deployment_id,
                principal.household_id,
                principal.actor_id,
            )
        ):
            raise MemoryOwnershipConflict()
        projection = hashlib.sha256(
            f"family-projection\x1f{meta[5]}\x1f{principal.household_id}".encode()
        ).hexdigest()
        if any(stored[5] == projection for stored in self._agent_fact_meta.values()):
            return projection
        copy = Fact(
            id=self._next_fact_id,
            user_id=source.user_id,
            subject=source.subject,
            key=source.key,
            value=source.value,
            category=source.category,
            confidence=source.confidence,
            evidence=source.evidence,
            source_msg_id=source.source_msg_id,
            created_at=time.time(),
        )
        self._next_fact_id += 1
        self._facts.append(copy)
        self._agent_fact_meta[copy.id or 0] = (
            principal.deployment_id,
            principal.household_id,
            principal.actor_id,
            "family",
            principal.household_id,
            projection,
            meta[5],
        )
        return projection

    async def _ensure_session_impl(self, user_id: str, session_id: str) -> None:
        self._sessions.setdefault((user_id, session_id), time.time())

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
        self._sessions[(user_id, session_id)] = created_at
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
        self._sessions.pop((user_id, session_id), None)
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
            (session_id, created_at)
            for (owner_id, session_id), created_at in self._sessions.items()
            if owner_id == user_id and created_at < cutoff
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
                    (row["state"] == "released" and _as_float(row["released_at"]) <= expired_before)
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
