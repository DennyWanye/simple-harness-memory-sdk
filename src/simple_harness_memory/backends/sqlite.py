"""Fresh-v3 SQLite backend with immutable user/session ownership."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiosqlite
import structlog

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.backends.storage import (
    path_digest,
    secure_sqlite_path,
    verify_sqlite_path,
)
from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemorySchemaIncompatible,
)
from simple_harness_memory.core.models import (
    Fact,
    MemoryApplyResult,
    MemoryApplyStatus,
    Message,
)
from simple_harness_memory.core.twin import (
    DigitalTwin,
    Entity,
    Goal,
    Preference,
    PreferenceMap,
    RelationshipGraph,
    Skill,
    SkillMap,
    UserProfile,
)


logger = structlog.get_logger("simple_harness_memory.backends.sqlite")

_DDL = """
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    UNIQUE (user_id, session_id)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    salience REAL NOT NULL DEFAULT 0.0,
    decay_rate REAL NOT NULL DEFAULT 0.02,
    last_recalled REAL,
    embedding BLOB,
    is_summary INTEGER NOT NULL DEFAULT 0 CHECK (is_summary IN (0, 1)),
    summary_of TEXT,
    source_event_id TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    embedder_kind TEXT,
    embedding_dim INTEGER,
    embedding_format_version INTEGER,
    UNIQUE (user_id, id),
    FOREIGN KEY (user_id, session_id)
        REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence TEXT NOT NULL DEFAULT '',
    source_msg_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    decay_rate REAL NOT NULL DEFAULT 0.01,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    last_decay_at REAL,
    superseded_by INTEGER,
    forgotten_at REAL,
    UNIQUE (user_id, id),
    FOREIGN KEY (user_id, source_msg_id)
        REFERENCES messages(user_id, id) ON DELETE CASCADE,
    FOREIGN KEY (superseded_by) REFERENCES facts(id) ON DELETE SET NULL
);
CREATE TABLE digital_twins (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE workspace_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (user_id, session_id)
        REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE TABLE recall_result_snapshots (
    context_query_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('retained', 'released')),
    created_at REAL NOT NULL,
    released_at REAL,
    FOREIGN KEY (user_id, session_id)
        REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE INDEX idx_messages_user_created
    ON messages(user_id, created_at DESC, id DESC);
CREATE INDEX idx_messages_user_session_created
    ON messages(user_id, session_id, created_at DESC, id DESC);
CREATE INDEX idx_facts_user_subject
    ON facts(user_id, subject, category, id);
CREATE INDEX idx_sessions_user_activity
    ON sessions(user_id, last_activity_at, session_id);
CREATE INDEX idx_actions_user_session
    ON workspace_actions(user_id, session_id, created_at DESC);
CREATE INDEX idx_recall_release
    ON recall_result_snapshots(user_id, state, released_at);
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SCHEMA_VERSION = 3
SCHEMA_CHECKSUM = hashlib.sha256(_DDL.encode("utf-8")).hexdigest()


class SQLiteMemoryBackend(BaseMemoryBackend):
    def __init__(
        self,
        db_path: str,
        *,
        embedder=None,
        fact_extractor=None,
        reranker=None,
        summarizer=None,
        auto_extract_facts: bool = False,
        bounds: MemoryResourceBounds | None = None,
        max_content_chars: int | None = None,
        max_fact_value_chars: int | None = None,
        max_payload_bytes: int | None = None,
        max_db_bytes: int | None = None,
    ) -> None:
        super().__init__(
            embedder=embedder,
            fact_extractor=fact_extractor,
            reranker=reranker,
            summarizer=summarizer,
            auto_extract_facts=auto_extract_facts,
            bounds=bounds,
            max_content_chars=max_content_chars,
            max_fact_value_chars=max_fact_value_chars,
            max_payload_bytes=max_payload_bytes,
            max_db_bytes=max_db_bytes,
        )
        self._db_path = str(db_path)
        self._secure_path: Path | None = None
        self._db: Optional[aiosqlite.Connection] = None
        self._tx_depth = 0

    async def initialize(self) -> None:
        if self._db is not None:
            return
        digest = path_digest(self._db_path)
        try:
            self._secure_path = secure_sqlite_path(self._db_path)
            self._db = await aiosqlite.connect(
                str(self._secure_path), isolation_level=None
            )
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA foreign_keys = ON")
            async with self._db.execute("PRAGMA foreign_keys") as cursor:
                enabled = await cursor.fetchone()
            if enabled is None or int(enabled[0]) != 1:
                raise MemoryCorruptionError("foreign key enforcement unavailable")
            await self._db.execute("PRAGMA journal_mode = WAL")
            await self._initialize_fresh_or_validate()
            await self._validate_integrity()
            verify_sqlite_path(self._secure_path)
            logger.info(
                "memory.backend_initialized",
                db_path_hash=digest,
                schema_version=SCHEMA_VERSION,
            )
        except Exception:
            if self._db is not None:
                await self._db.close()
                self._db = None
            logger.exception(
                "memory.backend_initialize_failed",
                db_path_hash=digest,
                stable_code="memory_backend_initialize_failed",
            )
            raise

    async def _initialize_fresh_or_validate(self) -> None:
        tables = await self._table_names()
        if not tables:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _DDL.split(";"):
                    statement = statement.strip()
                    if statement:
                        await self._conn.execute(statement)
                await self._write_schema_meta()
                await self._conn.execute("COMMIT")
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise
            return
        if "schema_meta" not in tables:
            raise MemorySchemaIncompatible()
        version = await self._read_meta("schema_version")
        checksum = await self._read_meta("schema_checksum")
        if version != str(SCHEMA_VERSION) or checksum != SCHEMA_CHECKSUM:
            raise MemorySchemaIncompatible()
        expected = {
            "users",
            "sessions",
            "messages",
            "facts",
            "digital_twins",
            "workspace_actions",
            "recall_result_snapshots",
            "schema_meta",
        }
        if not expected.issubset(tables):
            raise MemorySchemaIncompatible()

    async def _table_names(self) -> set[str]:
        async with self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            return {str(row[0]) for row in await cursor.fetchall()}

    async def _write_schema_meta(self) -> None:
        await self._conn.executemany(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("schema_checksum", SCHEMA_CHECKSUM),
            ),
        )

    async def _read_meta(self, key: str) -> str | None:
        async with self._conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        return str(row[0]) if row is not None else None

    async def _validate_integrity(self) -> None:
        async with self._conn.execute("PRAGMA integrity_check") as cursor:
            row = await cursor.fetchone()
        if row is None or row[0] != "ok":
            raise MemoryCorruptionError("database integrity check failed")
        async with self._conn.execute("PRAGMA foreign_key_check") as cursor:
            violation = await cursor.fetchone()
        if violation is not None:
            raise MemoryCorruptionError("database foreign key check failed")

    async def close(self) -> None:
        if self._db is None:
            return
        await self._db.close()
        self._db = None
        logger.info(
            "memory.backend_closed", db_path_hash=path_digest(self._db_path)
        )

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteMemoryBackend is not initialized")
        return self._db

    async def _commit(self) -> None:
        if self._tx_depth == 0:
            await self._conn.commit()

    @asynccontextmanager
    async def _transaction(self):
        if self._tx_depth:
            self._tx_depth += 1
            try:
                yield
            finally:
                self._tx_depth -= 1
            return
        self._tx_depth = 1
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            await self._conn.execute("COMMIT")
        except BaseException:
            await self._conn.execute("ROLLBACK")
            raise
        finally:
            self._tx_depth = 0

    async def _ensure_session_impl(self, user_id: str, session_id: str) -> None:
        now = time.time()
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
            (user_id, now),
        )
        async with self._conn.execute(
            "SELECT user_id FROM sessions "
            "WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            try:
                await self._conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, user_id, created_at, last_activity_at) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, user_id, now, now),
                )
            except aiosqlite.IntegrityError as exc:
                raise MemoryOwnershipConflict() from exc

    async def _append_message_impl(
        self, *, user_id: str, session_id: str, role: str, content: str,
        embedding: bytes | None, salience: float, decay_rate: float,
        created_at: float, is_summary: bool, summary_of: str | None,
        source_event_id: str, payload_hash: str, embedder_kind: str | None,
        embedding_dim: int | None, embedding_format_version: int | None,
    ) -> MemoryApplyResult:
        try:
            cursor = await self._conn.execute(
                "INSERT INTO messages "
                "(user_id, session_id, role, content, created_at, salience, "
                "decay_rate, embedding, is_summary, summary_of, source_event_id, "
                "payload_hash, embedder_kind, embedding_dim, "
                "embedding_format_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    session_id,
                    role,
                    content,
                    created_at,
                    salience,
                    decay_rate,
                    embedding,
                    int(is_summary),
                    summary_of,
                    source_event_id,
                    payload_hash,
                    embedder_kind,
                    embedding_dim,
                    embedding_format_version,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            async with self._conn.execute(
                "SELECT id, payload_hash FROM messages "
                "WHERE user_id = ? AND source_event_id = ?",
                (user_id, source_event_id),
            ) as query:
                row = await query.fetchone()
            if (
                row is None
                or row["payload_hash"] != payload_hash
            ):
                raise MemoryIdempotencyConflict() from exc
            return MemoryApplyResult(
                message_id=int(row["id"]),
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                status=MemoryApplyStatus.ALREADY_APPLIED,
            )
        await self._conn.execute(
            "UPDATE sessions SET last_activity_at = ? "
            "WHERE user_id = ? AND session_id = ?",
            (created_at, user_id, session_id),
        )
        return MemoryApplyResult(
            message_id=int(cursor.lastrowid or 0),
            source_event_id=source_event_id,
            payload_hash=payload_hash,
            status=MemoryApplyStatus.APPLIED,
        )

    async def _get_source_event_impl(
        self, user_id: str, source_event_id: str
    ) -> tuple[int, str] | None:
        async with self._conn.execute(
            "SELECT id, payload_hash FROM messages "
            "WHERE user_id = ? AND source_event_id = ?",
            (user_id, source_event_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["id"]), str(row["payload_hash"])

    async def _get_message_impl(
        self, user_id: str, message_id: int
    ) -> Optional[Message]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_message(row) if row is not None else None

    async def _query_messages_impl(
        self, user_id: str, *, limit: int, session_id: str | None = None,
        older_than: float | None = None,
        lineage_mismatch: tuple[str, int, int] | None = None,
    ) -> list[Message]:
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if older_than is not None:
            clauses.append("created_at < ?")
            params.append(older_than)
        if lineage_mismatch is not None:
            clauses.append(
                "(embedder_kind IS NOT ? OR embedding_dim IS NOT ? "
                "OR embedding_format_version IS NOT ?)"
            )
            params.extend(lineage_mismatch)
        params.append(limit)
        sql = (
            "SELECT * FROM messages WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        async with self._conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def _query_facts_impl(
        self, user_id: str, *, limit: int, subject: str | None = None,
        category: str | None = None, active_only: bool = False,
    ) -> list[Fact]:
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if active_only:
            clauses.append("superseded_by IS NULL")
            clauses.append("forgotten_at IS NULL")
        params.append(limit)
        sql = (
            "SELECT * FROM facts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id DESC LIMIT ?"
        )
        async with self._conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_fact(row) for row in rows]

    async def _insert_fact_impl(self, user_id: str, fact: Fact) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO facts "
            "(user_id, subject, key, value, category, confidence, evidence, "
            "source_msg_id, created_at, decay_rate, pinned) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                fact.subject,
                fact.key,
                fact.value,
                fact.category,
                fact.confidence,
                fact.evidence,
                fact.source_msg_id,
                fact.created_at,
                fact.decay_rate,
                int(fact.pinned),
            ),
        )
        return int(cursor.lastrowid or 0)

    async def _supersede_fact_impl(
        self, user_id: str, fact_id: int, superseded_by: int
    ) -> None:
        await self._conn.execute(
            "UPDATE facts SET superseded_by = ? "
            "WHERE user_id = ? AND id = ?",
            (superseded_by, user_id, fact_id),
        )

    async def _forget_fact_by_id_impl(
        self, user_id: str, fact_id: int, forgotten_at: float
    ) -> bool:
        cursor = await self._conn.execute(
            "UPDATE facts SET forgotten_at = ? "
            "WHERE user_id = ? AND id = ?",
            (forgotten_at, user_id, fact_id),
        )
        return cursor.rowcount > 0

    async def _update_message_salience_impl(
        self, user_id: str, message_id: int, salience: float,
        last_recalled: float | None,
    ) -> None:
        await self._conn.execute(
            "UPDATE messages SET salience = ?, "
            "last_recalled = COALESCE(?, last_recalled) "
            "WHERE user_id = ? AND id = ?",
            (salience, last_recalled, user_id, message_id),
        )

    async def _set_fact_decay_impl(
        self, user_id: str, fact_id: int, *,
        forgotten_at: float | None = None,
        last_decay_at: float | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if forgotten_at is not None:
            updates.append("forgotten_at = ?")
            params.append(forgotten_at)
        if last_decay_at is not None:
            updates.append("last_decay_at = ?")
            params.append(last_decay_at)
        if updates:
            params.extend((user_id, fact_id))
            await self._conn.execute(
                f"UPDATE facts SET {', '.join(updates)} "
                "WHERE user_id = ? AND id = ?",
                tuple(params),
            )

    async def _load_twin_impl(
        self, user_id: str, subject: str
    ) -> DigitalTwin:
        async with self._conn.execute(
            "SELECT subject, data_json FROM digital_twins WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return DigitalTwin(subject=subject)
        if row["subject"] != subject:
            raise MemoryOwnershipConflict("digital twin subject conflict")
        return self._deserialize_twin(subject, row["data_json"])

    async def _save_twin_impl(self, user_id: str, twin: DigitalTwin) -> None:
        await self._conn.execute(
            "INSERT INTO users (user_id, created_at) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, time.time()),
        )
        await self._conn.execute(
            "INSERT INTO digital_twins "
            "(user_id, subject, data_json, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "subject = excluded.subject, data_json = excluded.data_json, "
            "updated_at = excluded.updated_at",
            (
                user_id,
                twin.subject,
                json.dumps(
                    dataclasses.asdict(twin),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                time.time(),
            ),
        )

    async def _record_workspace_impl(
        self, user_id: str, session_id: str, action_type: str, payload: dict
    ) -> None:
        await self._conn.execute(
            "INSERT INTO workspace_actions "
            "(user_id, session_id, action_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                session_id,
                action_type,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                time.time(),
            ),
        )

    async def _delete_session_impl(self, user_id: str, session_id: str) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ) as cursor:
            row = await cursor.fetchone()
        deleted = int(row[0]) if row is not None else 0
        await self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )
        return deleted

    async def _old_session_ids_impl(
        self, user_id: str, cutoff: float, limit: int
    ) -> list[str]:
        async with self._conn.execute(
            "SELECT session_id FROM sessions "
            "WHERE user_id = ? AND last_activity_at < ? "
            "ORDER BY last_activity_at, session_id LIMIT ?",
            (user_id, cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [str(row["session_id"]) for row in rows]

    async def _update_embedding_impl(
        self, user_id: str, message_id: int, embedding: bytes,
        embedder_kind: str, embedding_dim: int,
        embedding_format_version: int,
    ) -> None:
        await self._conn.execute(
            "UPDATE messages SET embedding = ?, embedder_kind = ?, "
            "embedding_dim = ?, embedding_format_version = ? "
            "WHERE user_id = ? AND id = ?",
            (
                embedding,
                embedder_kind,
                embedding_dim,
                embedding_format_version,
                user_id,
                message_id,
            ),
        )

    async def _get_recall_snapshot_impl(
        self, user_id: str, context_query_id: str
    ) -> tuple[str, str, str, str, str] | None:
        async with self._conn.execute(
            "SELECT user_id, session_id, query_hash, result_payload, result_hash "
            "FROM recall_result_snapshots "
            "WHERE user_id = ? AND context_query_id = ?",
            (user_id, context_query_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return (
            str(row["user_id"]),
            str(row["session_id"]),
            str(row["query_hash"]),
            str(row["result_payload"]),
            str(row["result_hash"]),
        )

    async def _insert_recall_snapshot_impl(
        self, *, context_query_id: str, user_id: str, session_id: str,
        query_hash: str, result_payload: str, result_hash: str,
        created_at: float,
    ) -> None:
        try:
            await self._conn.execute(
                "INSERT INTO recall_result_snapshots "
                "(context_query_id, user_id, session_id, query_hash, "
                "result_payload, result_hash, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'retained', ?)",
                (
                    context_query_id,
                    user_id,
                    session_id,
                    query_hash,
                    result_payload,
                    result_hash,
                    created_at,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise MemoryIdempotencyConflict() from exc

    async def _release_recall_snapshot_impl(
        self, *, user_id: str, context_query_id: str, result_hash: str,
        released_at: float,
    ) -> bool:
        cursor = await self._conn.execute(
            "UPDATE recall_result_snapshots "
            "SET state = 'released', released_at = COALESCE(released_at, ?) "
            "WHERE user_id = ? AND context_query_id = ? AND result_hash = ?",
            (released_at, user_id, context_query_id, result_hash),
        )
        return cursor.rowcount > 0

    async def _cleanup_recall_snapshots_impl(
        self, *, user_id: str, released_before: float, limit: int
    ) -> int:
        cursor = await self._conn.execute(
            "DELETE FROM recall_result_snapshots WHERE context_query_id IN ("
            "SELECT context_query_id FROM recall_result_snapshots "
            "WHERE user_id = ? AND state = 'released' AND released_at <= ? "
            "ORDER BY released_at, context_query_id LIMIT ?"
            ") AND user_id = ?",
            (user_id, released_before, limit, user_id),
        )
        return max(0, cursor.rowcount)

    async def _check_db_size(self) -> None:
        if (
            self._bounds.max_db_bytes is not None
            and self._secure_path is not None
            and os.path.getsize(self._secure_path) > self._bounds.max_db_bytes
        ):
            raise MemoryLimitError("database exceeds max_db_bytes")

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> Message:
        return Message(
            id=row["id"],
            user_id=row["user_id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            salience=row["salience"],
            decay_rate=row["decay_rate"],
            last_recalled=row["last_recalled"],
            embedding=row["embedding"],
            embedder_kind=row["embedder_kind"],
            embedding_dim=row["embedding_dim"],
            embedding_format_version=row["embedding_format_version"],
            source_event_id=row["source_event_id"],
            payload_hash=row["payload_hash"],
            is_summary=bool(row["is_summary"]),
            summary_of=row["summary_of"],
        )

    @staticmethod
    def _row_to_fact(row: aiosqlite.Row) -> Fact:
        return Fact(
            id=row["id"],
            user_id=row["user_id"],
            subject=row["subject"],
            key=row["key"],
            value=row["value"],
            category=row["category"],
            confidence=row["confidence"],
            evidence=row["evidence"],
            source_msg_id=row["source_msg_id"],
            created_at=row["created_at"],
            pinned=bool(row["pinned"]),
            last_decay_at=row["last_decay_at"],
            superseded_by=row["superseded_by"],
            forgotten_at=row["forgotten_at"],
        )

    @staticmethod
    def _deserialize_twin(subject: str, data_json: str) -> DigitalTwin:
        try:
            data = json.loads(data_json)
        except Exception as exc:
            raise MemoryCorruptionError("digital twin payload is corrupt") from exc
        twin = DigitalTwin(subject=data.get("subject", subject))
        profile = data.get("profile") or {}
        twin.profile = UserProfile(
            name=profile.get("name"),
            occupation=profile.get("occupation"),
            location=profile.get("location"),
            language=profile.get("language"),
            timezone=profile.get("timezone"),
            extra=profile.get("extra") or {},
        )
        skills = (data.get("skills") or {}).get("skills") or {}
        twin.skills = SkillMap(skills={})
        for name, item in skills.items():
            twin.skills.skills[name] = Skill(
                name=item.get("name", name),
                level=item.get("level", 0.5),
                evidence_count=item.get("evidence_count", 0),
                last_updated=item.get("last_updated"),
            )
        preferences = (data.get("preferences") or {}).get("preferences") or {}
        twin.preferences = PreferenceMap(preferences={})
        for key, item in preferences.items():
            twin.preferences.preferences[key] = Preference(
                key=item.get("key", key),
                value=item.get("value", ""),
                strength=item.get("strength", 0.5),
                evidence_count=item.get("evidence_count", 0),
            )
        entities = (data.get("relationships") or {}).get("entities") or {}
        twin.relationships = RelationshipGraph(entities={})
        for name, item in entities.items():
            twin.relationships.entities[name] = Entity(
                name=item.get("name", name),
                entity_type=item.get("entity_type", "object"),
                relation=item.get("relation", ""),
                attributes=item.get("attributes") or {},
                confidence=item.get("confidence", 0.5),
                last_mentioned=item.get("last_mentioned"),
            )
        twin.goals = [
            Goal(
                goal_id=item.get("goal_id", ""),
                description=item.get("description", ""),
                deadline=item.get("deadline"),
                status=item.get("status", "active"),
                priority=item.get("priority", 0.5),
                created_at=item.get("created_at"),
            )
            for item in data.get("goals") or []
        ]
        twin.completeness = data.get("completeness", 0.0)
        twin.confidence = data.get("confidence", 0.0)
        twin.last_updated = data.get("last_updated")
        return twin


__all__ = (
    "SCHEMA_CHECKSUM",
    "SCHEMA_VERSION",
    "SQLiteMemoryBackend",
)
