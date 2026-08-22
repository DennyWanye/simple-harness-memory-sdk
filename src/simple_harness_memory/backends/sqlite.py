"""Fresh-v4 SQLite backend with immutable principal/scope ownership."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.backends.storage import (
    path_digest,
    secure_sqlite_path,
    verify_sqlite_path,
)
from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.conversation import (
    canonical_explicit_fact_payload,
    canonical_explicit_forget_payload_hash,
    canonicalize_memory_text,
    validate_digest,
    validate_identity,
)
from simple_harness_memory.core.errors import (
    MemoryBackupError,
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLimitError,
    MemoryOwnershipConflict,
    MemorySchemaIncompatible,
    MemoryWriterConflict,
)
from simple_harness_memory.core.identity import (
    MemoryPrincipal,
    MemoryScope,
    scope_predicate,
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
from simple_harness_memory.embedders.base import (
    EMBEDDING_FORMAT_VERSION,
    cosine_similarity,
    decode_vector,
    encode_vector,
)

logger = structlog.get_logger("simple_harness_memory.backends.sqlite")

_DDL = """
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE sessions (
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    PRIMARY KEY (deployment_id, session_id),
    UNIQUE (user_id, session_id)
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('personal', 'family')),
    scope_owner TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    salience REAL NOT NULL DEFAULT 0.0,
    decay_rate REAL NOT NULL DEFAULT 0.02,
    last_recalled REAL,
    last_decay_at REAL,
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
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('personal', 'family')),
    scope_owner TEXT NOT NULL,
    deterministic_id TEXT UNIQUE,
    extractor_lineage TEXT,
    projection_of TEXT,
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
    context_query_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    scope_set_hash TEXT NOT NULL,
    write_fence TEXT NOT NULL,
    session_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('retained', 'released')),
    created_at REAL NOT NULL,
    released_at REAL,
    PRIMARY KEY (deployment_id, context_query_id),
    FOREIGN KEY (user_id, session_id)
        REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE TABLE erasure_epochs (
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('personal', 'family')),
    scope_owner TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 0,
    erased_at REAL,
    PRIMARY KEY (deployment_id, household_id, scope_kind, scope_owner)
);
CREATE TABLE turn_receipts (
    turn_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_owner TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('applied', 'rejected_erased')),
    receipt_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (deployment_id, turn_id),
    UNIQUE (deployment_id, receipt_id)
);
CREATE TABLE fact_jobs (
    job_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_owner TEXT NOT NULL,
    source_msg_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    payload TEXT,
    payload_hash TEXT NOT NULL,
    erasure_epoch INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'applied', 'dead_letter', 'erased')),
    lease_until REAL,
    lease_token TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    extractor_lineage TEXT,
    extraction_hash TEXT,
    last_error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (deployment_id, turn_id),
    FOREIGN KEY (deployment_id, turn_id)
        REFERENCES turn_receipts(deployment_id, turn_id)
);
CREATE TABLE fact_tombstones (
    deterministic_id TEXT PRIMARY KEY,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_owner TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    erased_at REAL NOT NULL
);
CREATE TABLE suppression_receipts (
    source_event_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN (
        'SUPPRESS_TENTATIVE', 'SUPPRESS_TERMINAL', 'DEFERRED_TURN'
    )),
    created_at REAL NOT NULL
);
CREATE TABLE explicit_fact_receipts (
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    fact_id INTEGER NOT NULL,
    salience REAL NOT NULL,
    pinned INTEGER NOT NULL CHECK (pinned IN (0, 1)),
    tier TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('applied', 'forgotten')),
    created_at REAL NOT NULL,
    PRIMARY KEY (deployment_id, source_event_id),
    UNIQUE (deployment_id, fact_id)
);
CREATE TABLE explicit_forget_receipts (
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    fact_id INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    result INTEGER NOT NULL CHECK (result IN (0, 1)),
    created_at REAL NOT NULL,
    PRIMARY KEY (deployment_id, source_event_id)
);
CREATE INDEX idx_messages_user_created
    ON messages(user_id, created_at DESC, id DESC);
CREATE INDEX idx_messages_user_session_created
    ON messages(user_id, session_id, created_at DESC, id DESC);
CREATE INDEX idx_facts_user_subject
    ON facts(user_id, subject, category, id);
CREATE TRIGGER facts_superseded_owner_insert
BEFORE INSERT ON facts
WHEN NEW.superseded_by IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM facts
    WHERE user_id = NEW.user_id AND id = NEW.superseded_by
 )
BEGIN
    SELECT RAISE(ABORT, 'memory_ownership_conflict');
END;
CREATE TRIGGER facts_superseded_owner_update
BEFORE UPDATE OF user_id, superseded_by ON facts
WHEN NEW.superseded_by IS NOT NULL
 AND NOT EXISTS (
    SELECT 1 FROM facts
    WHERE user_id = NEW.user_id AND id = NEW.superseded_by
 )
BEGIN
    SELECT RAISE(ABORT, 'memory_ownership_conflict');
END;
CREATE INDEX idx_sessions_user_activity
    ON sessions(user_id, last_activity_at, session_id);
CREATE INDEX idx_actions_user_session
    ON workspace_actions(user_id, session_id, created_at DESC);
CREATE INDEX idx_recall_release
    ON recall_result_snapshots(user_id, state, released_at);
CREATE INDEX idx_recall_created
    ON recall_result_snapshots(user_id, state, created_at);
CREATE INDEX idx_messages_scope_created
    ON messages(deployment_id, household_id, scope_kind, scope_owner, created_at DESC, id DESC);
CREATE INDEX idx_facts_scope_active
    ON facts(deployment_id, household_id, scope_kind, scope_owner, forgotten_at, id DESC);
CREATE INDEX idx_fact_jobs_claim
    ON fact_jobs(state, next_attempt_at, lease_until, created_at);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    content, content='messages', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER messages_fts_update AFTER UPDATE OF content ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE VIRTUAL TABLE facts_fts USING fts5(
    value, content='facts', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER facts_fts_insert AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, value) VALUES (new.id, new.value);
END;
CREATE TRIGGER facts_fts_delete AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, value)
    VALUES ('delete', old.id, old.value);
END;
CREATE TRIGGER facts_fts_update AFTER UPDATE OF value ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, value)
    VALUES ('delete', old.id, old.value);
    INSERT INTO facts_fts(rowid, value) VALUES (new.id, new.value);
END;
CREATE TABLE embedding_lineages (
    lineage_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    normalization TEXT NOT NULL,
    format_version INTEGER NOT NULL,
    format_fingerprint TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE
);
CREATE TABLE embedding_generations (
    generation_id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL REFERENCES embedding_lineages(lineage_id),
    state TEXT NOT NULL CHECK (state IN ('building', 'active', 'retired', 'failed')),
    cursor INTEGER NOT NULL DEFAULT 0,
    vector_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    last_error_code TEXT,
    created_at REAL NOT NULL,
    activated_at REAL
);
CREATE UNIQUE INDEX idx_embedding_one_active
    ON embedding_generations(state) WHERE state = 'active';
CREATE TABLE message_vectors (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    generation_id TEXT NOT NULL REFERENCES embedding_generations(generation_id) ON DELETE CASCADE,
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension > 0),
    PRIMARY KEY (message_id, generation_id)
);
CREATE INDEX idx_message_vectors_generation
    ON message_vectors(generation_id, message_id);
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SCHEMA_VERSION = 4
SCHEMA_CHECKSUM = hashlib.sha256(_DDL.encode("utf-8")).hexdigest()
_LEGACY_V4_CHECKSUMS = frozenset(
    {
        "4e66bbfe712e479ef1e6ac5cbc0e720235b9ae6512a0668ddb18bb9cbf29e461",
        "59cb21710dcf4272231225fe93e9ab5015103aa810e842b356fc1b45faf7a8f6",
    }
)


def _ddl_statements(script: str) -> tuple[str, ...]:
    """Split DDL without breaking trigger bodies at their inner semicolons."""

    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        buffer.append(line)
        candidate = "\n".join(buffer).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buffer.clear()
    if "".join(buffer).strip():
        raise MemorySchemaIncompatible()
    return tuple(statements)


def create_fresh_v4_sync(connection: sqlite3.Connection) -> None:
    """Create the authoritative v4 schema for the explicit offline migrator."""

    for statement in _ddl_statements(_DDL):
        connection.execute(statement)
    connection.executemany(
        "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
        (("schema_version", str(SCHEMA_VERSION)), ("schema_checksum", SCHEMA_CHECKSUM)),
    )


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
        self._db: aiosqlite.Connection | None = None
        self._transaction_owner: asyncio.Task[Any] | None = None
        self._transaction_depth = ContextVar[int](f"memory_transaction_depth_{id(self)}", default=0)
        self._default_busy_timeout_ms = 5000
        self._writer_lock_file: Any | None = None
        self._agent_fence_context = ContextVar[str | None](
            f"memory_agent_fence_{id(self)}", default=None
        )

    async def initialize(self) -> None:
        async with self._operation():
            await self._initialize_locked()

    async def _initialize_locked(self) -> None:
        if self._db is not None:
            return
        digest = path_digest(self._db_path)
        try:
            self._secure_path = secure_sqlite_path(self._db_path)
            self._acquire_writer_lease()
            self._db = await aiosqlite.connect(str(self._secure_path), isolation_level=None)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA foreign_keys = ON")
            async with self._db.execute("PRAGMA foreign_keys") as cursor:
                enabled = await cursor.fetchone()
            if enabled is None or int(enabled[0]) != 1:
                raise MemoryCorruptionError("foreign key enforcement unavailable")
            await self._db.execute("PRAGMA journal_mode = WAL")
            await self._db.execute(f"PRAGMA busy_timeout = {self._default_busy_timeout_ms}")
            await self._initialize_fresh_or_validate()
            await self._validate_integrity()
            verify_sqlite_path(self._secure_path)
            logger.info(
                "memory.backend_initialized",
                db_path_hash=digest,
                schema_version=SCHEMA_VERSION,
                sqlite_version=sqlite3.sqlite_version,
                fts5=True,
            )
        except Exception:
            if self._db is not None:
                await self._db.close()
                self._db = None
            self._release_writer_lease()
            logger.error(
                "memory.backend_initialize_failed",
                db_path_hash=digest,
                stable_code="memory_backend_initialize_failed",
            )
            raise

    def _acquire_writer_lease(self) -> None:
        if self._writer_lock_file is not None:
            return
        assert self._secure_path is not None
        lock_path = self._secure_path.with_name(self._secure_path.name + ".writer.lock")
        lock_path.touch(mode=0o600, exist_ok=True)
        handle = lock_path.open("r+b")
        try:
            self._platform_writer_lock(handle, acquire=True)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise MemoryWriterConflict() from exc
        self._writer_lock_file = handle

    def _release_writer_lease(self) -> None:
        handle = self._writer_lock_file
        if handle is None:
            return
        try:
            self._platform_writer_lock(handle, acquire=False)
        finally:
            handle.close()
            self._writer_lock_file = None

    @staticmethod
    def _platform_writer_lock(
        handle: Any,
        *,
        acquire: bool,
        platform_name: str | None = None,
        windows_api: Any | None = None,
    ) -> None:
        """Hold one portable byte-range lease without importing POSIX modules on Windows."""

        if (platform_name or os.name) == "nt":
            msvcrt: Any = windows_api or importlib.import_module("msvcrt")

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            mode = msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK
            msvcrt.locking(handle.fileno(), mode, 1)
            return
        import fcntl

        mode = fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN
        fcntl.flock(handle.fileno(), mode)

    async def _initialize_fresh_or_validate(self) -> None:
        tables = await self._table_names()
        if not tables:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in _ddl_statements(_DDL):
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
        if version == str(SCHEMA_VERSION) and checksum in _LEGACY_V4_CHECKSUMS:
            if checksum == "4e66bbfe712e479ef1e6ac5cbc0e720235b9ae6512a0668ddb18bb9cbf29e461":
                await self._upgrade_legacy_v4_snapshot_identity()
            else:
                await self._upgrade_legacy_v4_forget_receipts()
            checksum = SCHEMA_CHECKSUM
            tables = await self._table_names()
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
            "erasure_epochs",
            "turn_receipts",
            "fact_jobs",
            "fact_tombstones",
            "suppression_receipts",
            "explicit_fact_receipts",
            "explicit_forget_receipts",
            "messages_fts",
            "facts_fts",
            "embedding_lineages",
            "embedding_generations",
            "message_vectors",
            "schema_meta",
        }
        if not expected.issubset(tables):
            raise MemorySchemaIncompatible()

    async def _upgrade_legacy_v4_snapshot_identity(self) -> None:
        """Transactionally repair the audited v4 snapshot key and add explicit receipts."""

        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._conn.execute(
                "CREATE TABLE recall_result_snapshots_next ("
                "context_query_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                "deployment_id TEXT NOT NULL, household_id TEXT NOT NULL, actor_id TEXT NOT NULL, "
                "scope_set_hash TEXT NOT NULL, write_fence TEXT NOT NULL, "
                "session_id TEXT NOT NULL, query_hash TEXT NOT NULL, "
                "result_payload TEXT NOT NULL, result_hash TEXT NOT NULL, "
                "state TEXT NOT NULL CHECK (state IN ('retained', 'released')), "
                "created_at REAL NOT NULL, "
                "released_at REAL, PRIMARY KEY (deployment_id, context_query_id), "
                "FOREIGN KEY (user_id, session_id) REFERENCES sessions(user_id, session_id) "
                "ON DELETE CASCADE)"
            )
            await self._conn.execute(
                "INSERT INTO recall_result_snapshots_next SELECT context_query_id, user_id, "
                "CASE WHEN deployment_id = 'standalone' THEN user_id ELSE deployment_id END, "
                "household_id, actor_id, scope_set_hash, write_fence, session_id, query_hash, "
                "result_payload, result_hash, state, created_at, released_at "
                "FROM recall_result_snapshots"
            )
            await self._conn.execute("DROP TABLE recall_result_snapshots")
            await self._conn.execute(
                "ALTER TABLE recall_result_snapshots_next RENAME TO recall_result_snapshots"
            )
            await self._conn.execute(
                "CREATE INDEX idx_recall_release ON "
                "recall_result_snapshots(user_id, state, released_at)"
            )
            await self._conn.execute(
                "CREATE INDEX idx_recall_created ON "
                "recall_result_snapshots(user_id, state, created_at)"
            )
            await self._conn.execute(
                "CREATE TABLE explicit_fact_receipts ("
                "deployment_id TEXT NOT NULL, household_id TEXT NOT NULL, actor_id TEXT NOT NULL, "
                "source_event_id TEXT NOT NULL, payload_hash TEXT NOT NULL, "
                "fact_id INTEGER NOT NULL, salience REAL NOT NULL, "
                "pinned INTEGER NOT NULL CHECK (pinned IN (0, 1)), tier TEXT NOT NULL, "
                "state TEXT NOT NULL CHECK (state IN ('applied', 'forgotten')), "
                "created_at REAL NOT NULL, "
                "PRIMARY KEY (deployment_id, source_event_id), UNIQUE (deployment_id, fact_id))"
            )
            await self._create_explicit_forget_receipts()
            await self._conn.execute(
                "UPDATE schema_meta SET value = ? WHERE key = 'schema_checksum'", (SCHEMA_CHECKSUM,)
            )
            await self._conn.execute("COMMIT")
        except Exception:
            await self._conn.execute("ROLLBACK")
            raise

    async def _upgrade_legacy_v4_forget_receipts(self) -> None:
        await self._conn.execute("BEGIN IMMEDIATE")
        try:
            await self._create_explicit_forget_receipts()
            await self._conn.execute(
                "UPDATE schema_meta SET value = ? WHERE key = 'schema_checksum'", (SCHEMA_CHECKSUM,)
            )
            await self._conn.execute("COMMIT")
        except Exception:
            await self._conn.execute("ROLLBACK")
            raise

    async def _create_explicit_forget_receipts(self) -> None:
        await self._conn.execute(
            "CREATE TABLE explicit_forget_receipts ("
            "deployment_id TEXT NOT NULL, household_id TEXT NOT NULL, actor_id TEXT NOT NULL, "
            "source_event_id TEXT NOT NULL, fact_id INTEGER NOT NULL, payload_hash TEXT NOT NULL, "
            "result INTEGER NOT NULL CHECK (result IN (0, 1)), created_at REAL NOT NULL, "
            "PRIMARY KEY (deployment_id, source_event_id))"
        )

    async def _table_names(self) -> set[str]:
        async with self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
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

    @staticmethod
    def _principal_key(principal: MemoryPrincipal) -> str:
        material = "\x1f".join(
            (principal.deployment_id, principal.household_id, principal.actor_id)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def _bind_agent_session(self, principal: MemoryPrincipal) -> str:
        """Create the immutable trusted session binding, or reject a rebind."""

        user_id = self._principal_key(principal)
        now = time.time()
        async with self._conn.execute(
            "SELECT household_id, actor_id FROM sessions "
            "WHERE deployment_id = ? AND session_id = ?",
            (principal.deployment_id, principal.session_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None:
            actual = (str(row[0]), str(row[1]))
            expected = (principal.household_id, principal.actor_id)
            if actual != expected:
                raise MemoryOwnershipConflict()
            return user_id
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
            (user_id, now),
        )
        try:
            await self._conn.execute(
                "INSERT INTO sessions "
                "(session_id, user_id, deployment_id, household_id, actor_id, "
                "created_at, last_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    principal.session_id,
                    user_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    now,
                    now,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            raise MemoryOwnershipConflict() from exc
        return user_id

    async def _scope_epoch(
        self, principal: MemoryPrincipal, scope: MemoryScope
    ) -> tuple[int, float | None]:
        scope.authorize(principal)
        await self._conn.execute(
            "INSERT INTO erasure_epochs "
            "(deployment_id, household_id, scope_kind, scope_owner, epoch) "
            "VALUES (?, ?, ?, ?, 0) ON CONFLICT DO NOTHING",
            (
                principal.deployment_id,
                principal.household_id,
                scope.kind.value,
                scope.owner_id,
            ),
        )
        async with self._conn.execute(
            "SELECT epoch, erased_at FROM erasure_epochs WHERE deployment_id = ? "
            "AND household_id = ? AND scope_kind = ? AND scope_owner = ?",
            (
                principal.deployment_id,
                principal.household_id,
                scope.kind.value,
                scope.owner_id,
            ),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            raise MemoryCorruptionError("erasure epoch unavailable")
        return int(row[0]), None if row[1] is None else float(row[1])

    @staticmethod
    def _write_fence(principal: MemoryPrincipal, scope: MemoryScope, epoch: int) -> str:
        material = {
            "protocol": "simple-harness-memory/write-fence/v1",
            "deployment_id": principal.deployment_id,
            "household_id": principal.household_id,
            "scope_kind": scope.kind.value,
            "scope_owner": scope.owner_id,
            "epoch": epoch,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

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
        """Return a durable identity-filtered recall payload and personal fence."""

        self._agent_fence_context.set(None)
        async with self._transaction():
            await self._bind_agent_session(principal)
            personal = MemoryScope.personal(principal.actor_id)
            epoch, _ = await self._scope_epoch(principal, personal)
            write_fence = self._write_fence(principal, personal, epoch)
            self._agent_fence_context.set(write_fence)
            async with self._conn.execute(
                "SELECT query_hash, result_payload, write_fence, deployment_id, "
                "household_id, actor_id, session_id FROM recall_result_snapshots "
                "WHERE deployment_id = ? AND context_query_id = ?",
                (principal.deployment_id, query_id),
            ) as cursor:
                prior = await cursor.fetchone()
            if prior is not None:
                identity = (
                    str(prior[3]),
                    str(prior[4]),
                    str(prior[5]),
                    str(prior[6]),
                )
                if str(prior[0]) != query_hash or identity != (
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                ):
                    raise MemoryIdempotencyConflict()
                return json.loads(str(prior[1])), str(prior[2]), True

        query_vector: list[float] | None = None
        try:
            query_vector = await self._embedder.embed(query_text)
            self._embedder.validate_vectors([query_vector], expected_count=1)
        except Exception:
            logger.warning(
                "memory.recall_vector_degraded",
                stable_code="memory_embedding_unavailable_lexical_only",
            )
        async with self._transaction():
            user_id = await self._bind_agent_session(principal)
            message_predicate, message_params = scope_predicate(principal, scopes, table_alias="m")
            message_predicate += " AND m.source_event_id NOT LIKE 'explicit-memory-source/v1/%'"
            fact_predicate, fact_params = scope_predicate(principal, scopes, table_alias="f")
            candidate_limit = min(
                self._bounds.recall_candidate_messages, max(max_items * 8, max_items + 1)
            )
            fact_limit = min(self._bounds.recall_candidate_facts, max(max_items * 4, max_items + 1))
            terms = re.findall(r"[\w]+", query_text[:256], flags=re.UNICODE)[:16]
            fts_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
            if fts_query:
                async with self._conn.execute(
                    "SELECT m.id, m.content, m.role, m.session_id, m.created_at, "
                    "m.scope_kind, m.scope_owner FROM messages_fts "
                    "JOIN messages AS m ON m.id = messages_fts.rowid "
                    f"WHERE {message_predicate} AND messages_fts MATCH ? "
                    "ORDER BY bm25(messages_fts), m.created_at DESC, m.id DESC LIMIT ?",
                    (*message_params, fts_query, candidate_limit),
                ) as cursor:
                    rows = list(await cursor.fetchall())
                async with self._conn.execute(
                    "SELECT f.id, f.value, f.category, f.created_at, f.scope_kind, "
                    "f.scope_owner FROM facts_fts JOIN facts AS f "
                    "ON f.id = facts_fts.rowid "
                    f"WHERE {fact_predicate} AND f.forgotten_at IS NULL "
                    "AND facts_fts MATCH ? ORDER BY bm25(facts_fts), "
                    "f.created_at DESC, f.id DESC LIMIT ?",
                    (*fact_params, fts_query, fact_limit),
                ) as cursor:
                    fact_rows = list(await cursor.fetchall())
            else:
                rows = []
                fact_rows = []
            async with self._conn.execute(
                "SELECT m.id, m.content, m.role, m.session_id, m.created_at, "
                "m.scope_kind, m.scope_owner FROM messages AS m "
                f"WHERE {message_predicate} ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                (*message_params, candidate_limit),
            ) as cursor:
                recent_rows = list(await cursor.fetchall())
            rows = list({int(row["id"]): row for row in [*rows, *recent_rows]}.values())
            async with self._conn.execute(
                "SELECT f.id, f.value, f.category, f.created_at, f.scope_kind, "
                "f.scope_owner FROM facts AS f "
                f"WHERE {fact_predicate} AND f.forgotten_at IS NULL "
                "ORDER BY f.created_at DESC, f.id DESC LIMIT ?",
                (*fact_params, fact_limit),
            ) as cursor:
                recent_fact_rows = list(await cursor.fetchall())
            fact_rows = list(
                {int(row["id"]): row for row in [*fact_rows, *recent_fact_rows]}.values()
            )
            vector_scores: dict[int, float] = {}
            if query_vector is not None:
                async with self._conn.execute(
                    "SELECT generation_id, lineage_id FROM embedding_generations "
                    "WHERE state = 'active' LIMIT 1"
                ) as cursor:
                    active = await cursor.fetchone()
                if (
                    active is not None
                    and str(active["lineage_id"]) == self._embedder.lineage.lineage_id
                ):
                    lexical_ids = [int(row["id"]) for row in rows]
                    placeholders = ",".join("?" for _ in lexical_ids)
                    lexical_clause = f"m.id IN ({placeholders}) OR " if lexical_ids else ""
                    async with self._conn.execute(
                        "SELECT m.id, v.embedding FROM messages AS m "
                        "JOIN message_vectors AS v ON v.message_id = m.id "
                        f"WHERE {message_predicate} AND v.generation_id = ? AND "
                        f"({lexical_clause}m.id IN (SELECT id FROM messages AS recent "
                        f"WHERE {message_predicate.replace('m.', 'recent.')} "
                        "ORDER BY recent.created_at DESC, recent.id DESC LIMIT ?)) "
                        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?",
                        (
                            *message_params,
                            str(active["generation_id"]),
                            *lexical_ids,
                            *message_params,
                            candidate_limit,
                            candidate_limit,
                        ),
                    ) as cursor:
                        vector_rows = await cursor.fetchall()
                    for vector_row in vector_rows:
                        try:
                            vector_scores[int(vector_row["id"])] = cosine_similarity(
                                query_vector, decode_vector(bytes(vector_row["embedding"]))
                            )
                        except (TypeError, ValueError, UnicodeDecodeError):
                            continue
            truncated = len(rows) + len(fact_rows) > max_items
            items: list[dict[str, object]] = []
            candidates: list[dict[str, object]] = []
            for row in rows:
                item = {
                    "record_id": f"message:{int(row['id'])}",
                    "text": str(row["content"]),
                    "role": str(row["role"]),
                    "session_id": str(row["session_id"]),
                    "created_at": float(row["created_at"]),
                    "scope": {
                        "kind": str(row["scope_kind"]),
                        "owner_id": str(row["scope_owner"]),
                    },
                    "_rank_score": vector_scores.get(int(row["id"]), 0.0),
                }
                candidates.append(item)
            for row in fact_rows:
                candidates.append(
                    {
                        "record_id": f"fact:{int(row['id'])}",
                        "text": str(row["value"]),
                        "role": "memory_fact",
                        "session_id": None,
                        "created_at": float(row["created_at"]),
                        "category": str(row["category"]),
                        "scope": {
                            "kind": str(row["scope_kind"]),
                            "owner_id": str(row["scope_owner"]),
                        },
                    }
                )
            candidates.sort(
                key=lambda item: (
                    float(str(item.get("_rank_score", 0.0))),
                    float(str(item["created_at"])),
                    str(item["record_id"]),
                ),
                reverse=True,
            )
            for item in candidates[:max_items]:
                item.pop("_rank_score", None)
                proposed = {"items": [*items, item], "truncated": truncated}
                proposed_bytes = json.dumps(
                    proposed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                if len(proposed_bytes) > max_bytes:
                    truncated = True
                    break
                items.append(item)
            payload: dict[str, object] = {"items": items, "truncated": truncated}
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            status = "truncated" if truncated else ("ready" if items else "empty")
            envelope = {
                "protocol": "simple-harness-agent-memory/recall-result/v1",
                "query_id": query_id,
                "query_hash": query_hash,
                "result_id": f"memory-recall/v1/{query_id}",
                "payload": payload,
                "status": status,
                "item_count": len(items),
                "byte_count": len(encoded.encode("utf-8")),
                "write_fence": write_fence,
            }
            result_hash = hashlib.sha256(
                json.dumps(
                    envelope,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            await self._conn.execute(
                "INSERT INTO recall_result_snapshots "
                "(context_query_id, user_id, deployment_id, household_id, actor_id, "
                "scope_set_hash, write_fence, session_id, query_hash, result_payload, "
                "result_hash, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'retained', ?)",
                (
                    query_id,
                    user_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    hashlib.sha256(repr(scopes).encode()).hexdigest(),
                    write_fence,
                    principal.session_id,
                    query_hash,
                    encoded,
                    result_hash,
                    time.time(),
                ),
            )
            return payload, write_fence, False

    def agent_failure_fence(self) -> str | None:
        return self._agent_fence_context.get()

    async def agent_release(
        self,
        *,
        query_id: str,
        query_hash: str,
        result_hash: str,
    ) -> None:
        async with self._transaction():
            async with self._conn.execute(
                "SELECT deployment_id, query_hash, result_hash FROM recall_result_snapshots "
                "WHERE context_query_id = ? AND query_hash = ? AND result_hash = ?",
                (query_id, query_hash, result_hash),
            ) as cursor:
                rows = list(await cursor.fetchall())
            if len(rows) != 1:
                raise MemoryIdempotencyConflict()
            await self._conn.execute(
                "UPDATE recall_result_snapshots SET state = 'released', "
                "released_at = COALESCE(released_at, ?) WHERE deployment_id = ? "
                "AND context_query_id = ? AND query_hash = ? AND result_hash = ?",
                (time.time(), str(rows[0][0]), query_id, query_hash, result_hash),
            )
            expired_before = time.time() - self._bounds.context_result_dedupe_seconds
            await self._conn.execute(
                "DELETE FROM recall_result_snapshots WHERE (deployment_id, context_query_id) IN ("
                "SELECT deployment_id, context_query_id FROM recall_result_snapshots "
                "WHERE state = 'released' AND released_at <= ? "
                "ORDER BY released_at, context_query_id LIMIT 100)",
                (expired_before,),
            )

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
        """Atomically store receipt, committed pair, and optional durable fact job."""

        now = time.time()
        receipt_id = f"memory-turn/v1/{turn_id}"
        async with self._transaction():
            async with self._conn.execute(
                "SELECT payload_hash, status, receipt_id, household_id, actor_id, session_id, "
                "scope_kind, scope_owner FROM turn_receipts "
                "WHERE deployment_id = ? AND turn_id = ?",
                (principal.deployment_id, turn_id),
            ) as cursor:
                prior = await cursor.fetchone()
            if prior is not None:
                expected_owner = (
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                    scope.kind.value,
                    scope.owner_id,
                )
                if str(prior[0]) != payload_hash or tuple(map(str, prior[3:])) != expected_owner:
                    raise MemoryIdempotencyConflict()
                prior_status = str(prior[1])
                return (
                    "already_applied" if prior_status == "applied" else prior_status,
                    str(prior[2]),
                )
            user_id = await self._bind_agent_session(principal)
            epoch, erased_at = await self._scope_epoch(principal, scope)
            expected_fence = self._write_fence(principal, scope, epoch)
            rejected = write_fence is not None and write_fence != expected_fence
            if write_fence is None and erased_at is not None:
                rejected = not (turn_started_at > erased_at and turn_started_at <= now)
            status = "rejected_erased" if rejected else "applied"
            await self._conn.execute(
                "INSERT INTO turn_receipts "
                "(turn_id, deployment_id, household_id, actor_id, session_id, "
                "scope_kind, scope_owner, payload_hash, status, receipt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    turn_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                    scope.kind.value,
                    scope.owner_id,
                    payload_hash,
                    status,
                    receipt_id,
                    now,
                ),
            )
            if rejected:
                return status, receipt_id
            message_ids: list[int] = []
            deployment_key = hashlib.sha256(principal.deployment_id.encode()).hexdigest()[:16]
            for role, content in (("user", user_text), ("assistant", assistant_text)):
                source_event_id = f"agent-turn/v1/{deployment_key}/{turn_id}/{role}"
                row_hash = hashlib.sha256(f"{payload_hash}\x1f{role}".encode()).hexdigest()
                cursor = await self._conn.execute(
                    "INSERT INTO messages "
                    "(user_id, deployment_id, household_id, actor_id, scope_kind, "
                    "scope_owner, session_id, role, content, created_at, salience, decay_rate, "
                    "embedding, is_summary, summary_of, source_event_id, payload_hash, "
                    "embedder_kind, embedding_dim, embedding_format_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0.02, NULL, 0, NULL, "
                    "?, ?, NULL, NULL, NULL)",
                    (
                        user_id,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        scope.kind.value,
                        scope.owner_id,
                        principal.session_id,
                        role,
                        content,
                        now,
                        source_event_id,
                        row_hash,
                    ),
                )
                message_ids.append(int(cursor.lastrowid or 0))
            if self._auto_extract_facts:
                job_id = hashlib.sha256(
                    f"fact-job\x1f{principal.deployment_id}\x1f{turn_id}".encode()
                ).hexdigest()
                await self._conn.execute(
                    "INSERT INTO fact_jobs "
                    "(job_id, turn_id, deployment_id, household_id, actor_id, session_id, "
                    "scope_kind, scope_owner, source_msg_id, payload, payload_hash, "
                    "erasure_epoch, state, next_attempt_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                    (
                        job_id,
                        turn_id,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        principal.session_id,
                        scope.kind.value,
                        scope.owner_id,
                        message_ids[0],
                        user_text,
                        hashlib.sha256(user_text.encode()).hexdigest(),
                        epoch,
                        now,
                        now,
                        now,
                    ),
                )
            return status, receipt_id

    async def recover_fact_jobs(self) -> None:
        async with self._transaction():
            await self._conn.execute(
                "UPDATE fact_jobs SET state = 'pending', lease_until = NULL, "
                "lease_token = NULL, updated_at = ? WHERE state = 'claimed' "
                "AND lease_until <= ?",
                (time.time(), time.time()),
            )

    async def claim_fact_job(self, *, lease_seconds: float = 30.0) -> dict[str, object] | None:
        now = time.time()
        token = uuid.uuid4().hex
        async with self._transaction():
            async with self._conn.execute(
                "SELECT job_id FROM fact_jobs WHERE "
                "(state = 'pending' OR (state = 'claimed' AND lease_until <= ?)) "
                "AND next_attempt_at <= ? ORDER BY created_at, job_id LIMIT 1",
                (now, now),
            ) as cursor:
                candidate = await cursor.fetchone()
            if candidate is None:
                return None
            job_id = str(candidate[0])
            await self._conn.execute(
                "UPDATE fact_jobs SET state = 'claimed', lease_until = ?, lease_token = ?, "
                "attempts = attempts + 1, updated_at = ? WHERE job_id = ?",
                (now + lease_seconds, token, now, job_id),
            )
            async with self._conn.execute(
                "SELECT * FROM fact_jobs WHERE job_id = ?", (job_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise MemoryCorruptionError("claimed fact job disappeared")
            return {key: row[key] for key in row.keys()}

    async def apply_fact_job(
        self,
        job: dict[str, object],
        facts: list[Fact],
        *,
        extractor_lineage: str,
    ) -> str:
        """Atomically apply a canonical extraction snapshot and acknowledge its job."""

        snapshot = [
            {
                "subject": fact.subject,
                "key": fact.key,
                "value": fact.value,
                "category": fact.category,
                "confidence": fact.confidence,
                "evidence": fact.evidence,
            }
            for fact in facts[: self._bounds.maintenance_batch_size]
        ]
        snapshot_json = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        extraction_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()
        now = time.time()
        async with self._transaction():
            async with self._conn.execute(
                "SELECT state, lease_token, erasure_epoch, deployment_id, household_id, "
                "scope_kind, scope_owner, source_msg_id FROM fact_jobs WHERE job_id = ?",
                (job["job_id"],),
            ) as cursor:
                current = await cursor.fetchone()
            if current is None:
                return "erased"
            if str(current[0]) == "applied":
                return "applied"
            if str(current[0]) != "claimed" or str(current[1]) != str(job["lease_token"]):
                return "lost_lease"
            async with self._conn.execute(
                "SELECT epoch FROM erasure_epochs WHERE deployment_id = ? AND household_id = ? "
                "AND scope_kind = ? AND scope_owner = ?",
                (current[3], current[4], current[5], current[6]),
            ) as cursor:
                epoch_row = await cursor.fetchone()
            if epoch_row is None or int(epoch_row[0]) != int(current[2]):
                await self._conn.execute(
                    "UPDATE fact_jobs SET state = 'erased', payload = NULL, lease_token = NULL, "
                    "lease_until = NULL, updated_at = ? WHERE job_id = ?",
                    (now, job["job_id"]),
                )
                return "erased"
            for index, fact in enumerate(facts[: self._bounds.maintenance_batch_size]):
                deterministic_id = hashlib.sha256(
                    f"{job['job_id']}\x1f{index}\x1f{extraction_hash}".encode()
                ).hexdigest()
                async with self._conn.execute(
                    "SELECT 1 FROM fact_tombstones WHERE deterministic_id = ?",
                    (deterministic_id,),
                ) as cursor:
                    if await cursor.fetchone() is not None:
                        continue
                await self._conn.execute(
                    "INSERT INTO facts "
                    "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
                    "deterministic_id, extractor_lineage, subject, key, value, category, "
                    "confidence, evidence, source_msg_id, created_at, decay_rate, pinned) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0) "
                    "ON CONFLICT(deterministic_id) DO NOTHING",
                    (
                        self._principal_key(
                            MemoryPrincipal(
                                str(job["deployment_id"]),
                                str(job["household_id"]),
                                str(job["actor_id"]),
                                str(job["session_id"]),
                            )
                        ),
                        job["deployment_id"],
                        job["household_id"],
                        job["actor_id"],
                        job["scope_kind"],
                        job["scope_owner"],
                        deterministic_id,
                        extractor_lineage,
                        fact.subject,
                        fact.key,
                        fact.value,
                        fact.category,
                        fact.confidence,
                        fact.evidence,
                        current[7],
                        now,
                        fact.decay_rate,
                    ),
                )
            await self._conn.execute(
                "UPDATE fact_jobs SET state = 'applied', payload = NULL, lease_until = NULL, "
                "lease_token = NULL, extractor_lineage = ?, extraction_hash = ?, "
                "updated_at = ? WHERE job_id = ?",
                (extractor_lineage, extraction_hash, now, job["job_id"]),
            )
        return "applied"

    async def fail_fact_job(self, job: dict[str, object], *, stable_code: str) -> None:
        now = time.time()
        attempts = int(str(job.get("attempts") or 1))
        state = "dead_letter" if attempts >= 5 else "pending"
        backoff = min(300.0, 2.0**attempts)
        async with self._transaction():
            await self._conn.execute(
                "UPDATE fact_jobs SET state = ?, lease_until = NULL, lease_token = NULL, "
                "next_attempt_at = ?, last_error_code = ?, updated_at = ? "
                "WHERE job_id = ? AND lease_token = ?",
                (
                    state,
                    now + backoff,
                    stable_code,
                    now,
                    job["job_id"],
                    job["lease_token"],
                ),
            )

    async def agent_export(
        self,
        principal: MemoryPrincipal,
        scopes: tuple[MemoryScope, ...],
        *,
        cursor: int = 0,
        limit: int = 100,
    ) -> tuple[list[dict[str, object]], int | None]:
        predicate, params = scope_predicate(principal, scopes)
        async with self._operation():
            await self._bind_agent_session(principal)
            async with self._conn.execute(
                "SELECT record_kind, id, role, content, created_at, scope_kind, scope_owner "
                "FROM (SELECT 'message' AS record_kind, id, role, content, created_at, "
                f"scope_kind, scope_owner FROM messages WHERE {predicate} "
                "UNION ALL SELECT 'fact' AS record_kind, id, 'memory_fact' AS role, "
                "value AS content, created_at, scope_kind, scope_owner FROM facts "
                f"WHERE {predicate} "
                "AND forgotten_at IS NULL) ORDER BY created_at, record_kind, id LIMIT ? OFFSET ?",
                (*params, *params, limit + 1, cursor),
            ) as query:
                rows = list(await query.fetchall())
        records = [
            {
                "record_id": f"{row['record_kind']}:{int(row['id'])}",
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": float(row["created_at"]),
                "scope": {"kind": str(row["scope_kind"]), "owner_id": str(row["scope_owner"])},
            }
            for row in rows[:limit]
        ]
        next_cursor = cursor + limit if len(rows) > limit and limit else None
        return records, next_cursor

    async def agent_delete_scopes(
        self, principal: MemoryPrincipal, scopes: tuple[MemoryScope, ...]
    ) -> dict[str, int | str]:
        predicate, params = scope_predicate(principal, scopes)
        now = time.time()
        counts: dict[str, int | str] = {
            "messages": 0,
            "facts": 0,
            "snapshots": 0,
            "jobs": 0,
        }
        async with self._transaction():
            await self._bind_agent_session(principal)
            for scope in scopes:
                await self._scope_epoch(principal, scope)
                await self._conn.execute(
                    "UPDATE erasure_epochs SET epoch = epoch + 1, erased_at = ? "
                    "WHERE deployment_id = ? AND household_id = ? AND scope_kind = ? "
                    "AND scope_owner = ?",
                    (
                        now,
                        principal.deployment_id,
                        principal.household_id,
                        scope.kind.value,
                        scope.owner_id,
                    ),
                )
            async with self._conn.execute(
                "SELECT job_id, payload_hash FROM fact_jobs WHERE source_msg_id IN "
                f"(SELECT id FROM messages WHERE {predicate})",
                params,
            ) as query:
                jobs = list(await query.fetchall())
            for row in jobs:
                await self._conn.execute(
                    "INSERT OR IGNORE INTO fact_tombstones "
                    "(deterministic_id, deployment_id, household_id, scope_kind, scope_owner, "
                    "payload_hash, erased_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"job:{row['job_id']}",
                        principal.deployment_id,
                        principal.household_id,
                        scopes[0].kind.value,
                        scopes[0].owner_id,
                        row["payload_hash"],
                        now,
                    ),
                )
            counts["jobs"] = len(jobs)
            async with self._conn.execute(
                f"SELECT COUNT(*) FROM facts WHERE {predicate}", params
            ) as query:
                fact_count_row = await query.fetchone()
            counts["facts"] = int(fact_count_row[0]) if fact_count_row else 0
            async with self._conn.execute(
                f"SELECT COUNT(*) FROM messages WHERE {predicate}", params
            ) as query:
                message_count_row = await query.fetchone()
            counts["messages"] = int(message_count_row[0]) if message_count_row else 0
            # Recall stages can contain data from either authorized scope, so an
            # erasure invalidates all stages belonging to this trusted principal.
            cursor_result = await self._conn.execute(
                "DELETE FROM recall_result_snapshots WHERE deployment_id = ? "
                "AND household_id = ? AND actor_id = ?",
                (principal.deployment_id, principal.household_id, principal.actor_id),
            )
            counts["snapshots"] = max(0, cursor_result.rowcount)
            if MemoryScope.personal(principal.actor_id) in scopes:
                await self._conn.execute(
                    "UPDATE explicit_fact_receipts SET state = 'forgotten' "
                    "WHERE deployment_id = ? AND household_id = ? AND actor_id = ?",
                    (principal.deployment_id, principal.household_id, principal.actor_id),
                )
            await self._conn.execute(
                f"DELETE FROM messages WHERE id IN (SELECT id FROM messages WHERE {predicate})",
                params,
            )
            await self._conn.execute(f"DELETE FROM facts WHERE {predicate}", params)
        counts["receipt_id"] = hashlib.sha256(
            f"delete\x1f{principal.opaque_id}\x1f{now}".encode()
        ).hexdigest()
        return counts

    async def agent_forget_fact(
        self,
        principal: MemoryPrincipal,
        fact_id: int,
        *,
        source_event_id: str,
        payload_hash: str | None,
    ) -> bool:
        source_event_id = validate_identity(source_event_id, "source_event_id")
        expected_hash = canonical_explicit_forget_payload_hash(
            principal=principal, source_event_id=source_event_id, fact_id=fact_id
        )
        if (
            payload_hash is not None
            and validate_digest(payload_hash, "payload_hash") != expected_hash
        ):
            raise MemoryIdempotencyConflict()
        personal = MemoryScope.personal(principal.actor_id)
        predicate, params = scope_predicate(principal, (personal,))
        now = time.time()
        async with self._transaction():
            await self._bind_agent_session(principal)
            async with self._conn.execute(
                "SELECT household_id, actor_id, fact_id, payload_hash, result "
                "FROM explicit_forget_receipts WHERE deployment_id = ? AND source_event_id = ?",
                (principal.deployment_id, source_event_id),
            ) as cursor:
                replay = await cursor.fetchone()
            if replay is not None:
                if (str(replay[0]), str(replay[1])) != (
                    principal.household_id,
                    principal.actor_id,
                ):
                    raise MemoryOwnershipConflict()
                if int(replay[2]) != fact_id or str(replay[3]) != expected_hash:
                    raise MemoryIdempotencyConflict()
                return bool(replay[4])
            async with self._conn.execute(
                "SELECT deterministic_id, payload_hash FROM ("
                "SELECT deterministic_id, '' AS payload_hash, id, deployment_id, household_id, "
                "scope_kind, scope_owner FROM facts) "
                f"WHERE {predicate} AND id = ?",
                (*params, fact_id),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                async with self._conn.execute(
                    "SELECT household_id, actor_id FROM explicit_fact_receipts "
                    "WHERE deployment_id = ? AND fact_id = ? UNION ALL "
                    "SELECT household_id, actor_id FROM explicit_forget_receipts "
                    "WHERE deployment_id = ? AND fact_id = ? LIMIT 1",
                    (principal.deployment_id, fact_id, principal.deployment_id, fact_id),
                ) as cursor:
                    provenance = await cursor.fetchone()
                if provenance is not None and (str(provenance[0]), str(provenance[1])) != (
                    principal.household_id,
                    principal.actor_id,
                ):
                    raise MemoryOwnershipConflict()
                result = False
            else:
                deterministic_id = str(row[0] or f"legacy-fact:{fact_id}")
                await self._conn.execute(
                    "INSERT OR IGNORE INTO fact_tombstones "
                    "(deterministic_id, deployment_id, household_id, scope_kind, scope_owner, "
                    "payload_hash, erased_at) VALUES (?, ?, ?, 'personal', ?, ?, ?)",
                    (
                        deterministic_id,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        hashlib.sha256(deterministic_id.encode()).hexdigest(),
                        now,
                    ),
                )
                await self._conn.execute(
                    "UPDATE explicit_fact_receipts SET state = 'forgotten' "
                    "WHERE deployment_id = ? AND household_id = ? AND actor_id = ? "
                    "AND fact_id = ?",
                    (
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        fact_id,
                    ),
                )
                await self._conn.execute(
                    "DELETE FROM facts WHERE deterministic_id = ? OR projection_of = ?",
                    (deterministic_id, deterministic_id),
                )
                result = True
            await self._conn.execute(
                "INSERT INTO explicit_forget_receipts (deployment_id, household_id, actor_id, "
                "source_event_id, fact_id, payload_hash, result, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    source_event_id,
                    fact_id,
                    expected_hash,
                    int(result),
                    now,
                ),
            )
            return result

    async def agent_remember_fact(
        self,
        principal: MemoryPrincipal,
        content: str,
        *,
        source_event_id: str,
        payload_hash: str | None,
        salience: float,
        pinned: bool,
        tier: str,
    ) -> int:
        content = self._check_content(canonicalize_memory_text(content))
        source_event_id = validate_identity(source_event_id, "source_event_id")
        expected_hash, salience, pinned, tier = canonical_explicit_fact_payload(
            principal=principal,
            source_event_id=source_event_id,
            content=content,
            salience=salience,
            pinned=pinned,
            tier=tier,
        )
        if (
            payload_hash is not None
            and validate_digest(payload_hash, "payload_hash") != expected_hash
        ):
            raise MemoryIdempotencyConflict()
        category = {
            "auto": "explicit",
            "working": "event",
            "long_term": "learning",
            "identity": "profile",
        }[tier]
        async with self._transaction():
            user_id = await self._bind_agent_session(principal)
            async with self._conn.execute(
                "SELECT household_id, actor_id, payload_hash, fact_id FROM explicit_fact_receipts "
                "WHERE deployment_id = ? AND source_event_id = ?",
                (principal.deployment_id, source_event_id),
            ) as cursor:
                prior = await cursor.fetchone()
            if prior is not None:
                if (str(prior[0]), str(prior[1])) != (
                    principal.household_id,
                    principal.actor_id,
                ):
                    raise MemoryOwnershipConflict()
                if str(prior[2]) != expected_hash:
                    raise MemoryIdempotencyConflict()
                return int(prior[3])
            now = time.time()
            internal_source_event = (
                "explicit-memory-source/v1/"
                + hashlib.sha256(
                    f"{principal.deployment_id}\x1f{source_event_id}".encode()
                ).hexdigest()
            )
            cursor = await self._conn.execute(
                "INSERT INTO messages (user_id, deployment_id, household_id, actor_id, "
                "scope_kind, scope_owner, session_id, role, content, created_at, salience, "
                "decay_rate, source_event_id, payload_hash) "
                "VALUES (?, ?, ?, ?, 'personal', ?, ?, 'user', ?, ?, ?, 0.0, ?, ?)",
                (
                    user_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.actor_id,
                    principal.session_id,
                    content,
                    now,
                    salience,
                    internal_source_event,
                    expected_hash,
                ),
            )
            source_msg_id = int(cursor.lastrowid or 0)
            deterministic_id = hashlib.sha256(
                f"explicit-fact/v1\x1f{principal.deployment_id}\x1f{source_event_id}".encode()
            ).hexdigest()
            cursor = await self._conn.execute(
                "INSERT INTO facts (user_id, deployment_id, household_id, actor_id, scope_kind, "
                "scope_owner, deterministic_id, extractor_lineage, subject, key, value, category, "
                "confidence, evidence, source_msg_id, created_at, decay_rate, pinned) "
                "VALUES (?, ?, ?, ?, 'personal', ?, ?, 'explicit-memory/v1', ?, 'memory', ?, ?, "
                "1.0, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.actor_id,
                    deterministic_id,
                    principal.actor_id,
                    content,
                    category,
                    content,
                    source_msg_id,
                    now,
                    0.0 if pinned else 0.01,
                    int(pinned),
                ),
            )
            fact_id = int(cursor.lastrowid or 0)
            await self._conn.execute(
                "INSERT INTO explicit_fact_receipts (deployment_id, household_id, actor_id, "
                "source_event_id, payload_hash, fact_id, salience, pinned, tier, state, "
                "created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?)",
                (
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    source_event_id,
                    expected_hash,
                    fact_id,
                    salience,
                    int(pinned),
                    tier,
                    now,
                ),
            )
            return fact_id

    async def agent_read_fact(self, principal: MemoryPrincipal, fact_id: int) -> Fact | None:
        personal = MemoryScope.personal(principal.actor_id)
        predicate, params = scope_predicate(principal, (personal,))
        async with self._operation():
            await self._bind_agent_session(principal)
            async with self._conn.execute(
                "SELECT * FROM facts WHERE " + predicate + " AND actor_id = ? AND id = ? "
                "AND forgotten_at IS NULL",
                (*params, principal.actor_id, fact_id),
            ) as cursor:
                row = await cursor.fetchone()
        return None if row is None else self._row_to_fact(row)

    async def agent_share_fact(self, principal: MemoryPrincipal, fact_id: int) -> str:
        personal = MemoryScope.personal(principal.actor_id)
        predicate, params = scope_predicate(principal, (personal,))
        async with self._transaction():
            async with self._conn.execute(
                "SELECT * FROM facts WHERE " + predicate + " AND id = ? AND forgotten_at IS NULL",
                (*params, fact_id),
            ) as cursor:
                source = await cursor.fetchone()
            if source is None:
                raise MemoryOwnershipConflict()
            origin = str(source["deterministic_id"] or f"legacy-fact:{fact_id}")
            projection_id = hashlib.sha256(
                f"family-projection\x1f{origin}\x1f{principal.household_id}".encode()
            ).hexdigest()
            await self._conn.execute(
                "INSERT INTO facts "
                "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
                "deterministic_id, extractor_lineage, projection_of, subject, key, value, "
                "category, confidence, evidence, source_msg_id, created_at, decay_rate, pinned) "
                "VALUES (?, ?, ?, ?, 'family', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(deterministic_id) DO NOTHING",
                (
                    source["user_id"],
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.household_id,
                    projection_id,
                    source["extractor_lineage"],
                    origin,
                    source["subject"],
                    source["key"],
                    source["value"],
                    source["category"],
                    source["confidence"],
                    source["evidence"],
                    source["source_msg_id"],
                    time.time(),
                    source["decay_rate"],
                    source["pinned"],
                ),
            )
            return projection_id

    async def close(self) -> None:
        async with self._operation():
            await self._close_locked()

    async def reindex_generation(
        self, embedder=None, *, page_size: int | None = None
    ) -> dict[str, object]:
        """Build and atomically activate a complete, restartable vector generation."""

        selected = embedder or self._embedder
        size = self._bounded_limit(page_size or self._bounds.maintenance_batch_size)
        lineage = selected.lineage
        started = time.monotonic()
        async with self._transaction():
            await self._conn.execute(
                "INSERT INTO embedding_lineages "
                "(lineage_id, kind, provider, model, revision, dimension, normalization, "
                "format_version, format_fingerprint, fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(lineage_id) DO NOTHING",
                (
                    lineage.lineage_id,
                    lineage.kind,
                    lineage.provider,
                    lineage.model,
                    lineage.revision,
                    lineage.dimension,
                    lineage.normalization,
                    EMBEDDING_FORMAT_VERSION,
                    lineage.format_fingerprint,
                    lineage.lineage_id,
                ),
            )
            async with self._conn.execute(
                "SELECT generation_id, cursor, vector_count FROM embedding_generations "
                "WHERE lineage_id = ? AND state = 'building' "
                "ORDER BY created_at DESC LIMIT 1",
                (lineage.lineage_id,),
            ) as existing_cursor:
                existing = await existing_cursor.fetchone()
            if existing is None:
                generation_id = f"gen:{uuid.uuid4().hex}"
                cursor_id = 0
                count = 0
                await self._conn.execute(
                    "INSERT INTO embedding_generations "
                    "(generation_id, lineage_id, state, created_at) "
                    "VALUES (?, ?, 'building', ?)",
                    (generation_id, lineage.lineage_id, time.time()),
                )
            else:
                generation_id = str(existing["generation_id"])
                cursor_id = int(existing["cursor"])
                count = int(existing["vector_count"])
        digest = hashlib.sha256()
        if count:
            vector_cursor = 0
            while True:
                async with self._operation():
                    async with self._conn.execute(
                        "SELECT message_id, embedding FROM message_vectors "
                        "WHERE generation_id = ? AND message_id > ? "
                        "ORDER BY message_id LIMIT ?",
                        (generation_id, vector_cursor, size),
                    ) as persisted_cursor:
                        persisted = list(await persisted_cursor.fetchall())
                if not persisted:
                    break
                for row in persisted:
                    digest.update(str(int(row["message_id"])).encode())
                    digest.update(bytes(row["embedding"]))
                vector_cursor = int(persisted[-1]["message_id"])
        try:
            while True:
                async with self._operation():
                    async with self._conn.execute(
                        "SELECT id, content FROM messages WHERE id > ? ORDER BY id LIMIT ?",
                        (cursor_id, size),
                    ) as cursor:
                        page = list(await cursor.fetchall())
                if not page:
                    break
                vectors = await selected.embed_batch([str(row["content"]) for row in page])
                selected.validate_vectors(vectors, expected_count=len(page))
                encoded = [encode_vector(vector) for vector in vectors]
                async with self._transaction():
                    await self._conn.executemany(
                        "INSERT OR REPLACE INTO message_vectors "
                        "(message_id, generation_id, embedding, dimension) VALUES (?, ?, ?, ?)",
                        [
                            (int(row["id"]), generation_id, blob, lineage.dimension)
                            for row, blob in zip(page, encoded)
                        ],
                    )
                    cursor_id = int(page[-1]["id"])
                    count += len(page)
                    for row, blob in zip(page, encoded):
                        digest.update(str(int(row["id"])).encode())
                        digest.update(blob)
                    await self._conn.execute(
                        "UPDATE embedding_generations SET cursor = ?, vector_count = ?, "
                        "content_hash = ? WHERE generation_id = ? AND state = 'building'",
                        (cursor_id, count, digest.hexdigest(), generation_id),
                    )
            async with self._transaction():
                async with self._conn.execute("SELECT COUNT(*) FROM messages") as cursor:
                    expected_row = await cursor.fetchone()
                    if expected_row is None:
                        raise MemoryCorruptionError("message count unavailable")
                    expected = int(expected_row[0])
                async with self._conn.execute(
                    "SELECT COUNT(*) FROM message_vectors WHERE generation_id = ? "
                    "AND dimension = ?",
                    (generation_id, lineage.dimension),
                ) as cursor:
                    actual_row = await cursor.fetchone()
                    if actual_row is None:
                        raise MemoryCorruptionError("vector count unavailable")
                    actual = int(actual_row[0])
                if actual != expected or actual != count:
                    raise MemoryCorruptionError("embedding generation verification failed")
                async with self._conn.execute(
                    "SELECT embedding FROM message_vectors WHERE generation_id = ? "
                    "ORDER BY message_id LIMIT 1",
                    (generation_id,),
                ) as sample_cursor:
                    sample = await sample_cursor.fetchone()
                if sample is not None and len(decode_vector(bytes(sample[0]))) != lineage.dimension:
                    raise MemoryCorruptionError("embedding generation sample verification failed")
                await self._conn.execute(
                    "UPDATE embedding_generations SET state = 'retired' WHERE state = 'active'"
                )
                await self._conn.execute(
                    "UPDATE embedding_generations SET state = 'active', activated_at = ? "
                    "WHERE generation_id = ? AND state = 'building'",
                    (time.time(), generation_id),
                )
            self._embedder = selected
            logger.info(
                "memory.reindex_completed",
                generation_id_hash=hashlib.sha256(generation_id.encode()).hexdigest()[:16],
                vector_count=count,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return {
                "generation_id": generation_id,
                "lineage_id": lineage.lineage_id,
                "vector_count": count,
                "state": "active",
            }
        except Exception:
            async with self._transaction():
                await self._conn.execute(
                    "UPDATE embedding_generations SET state = 'failed', "
                    "last_error_code = 'memory_reindex_failed' "
                    "WHERE generation_id = ? AND state = 'building'",
                    (generation_id,),
                )
            logger.error("memory.reindex_failed", stable_code="memory_reindex_failed")
            raise

    async def checkpoint(self, *, deadline_seconds: float = 5.0) -> tuple[int, int]:
        """Serialize a bounded WAL checkpoint with all writers and backups."""

        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        async with asyncio.timeout(deadline_seconds):
            async with self._operation():
                async with self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)") as cursor:
                    row = await cursor.fetchone()
        if row is None or int(row[0]) != 0:
            raise TimeoutError("memory checkpoint deadline exceeded")
        return int(row[1]), int(row[2])

    async def backup(self, destination: str | os.PathLike[str]) -> dict[str, object]:
        """Create a validated online backup and adjacent content-addressed manifest."""

        destination_path = Path(destination).resolve()
        manifest_path = destination_path.with_name(destination_path.name + ".manifest.json")
        if destination_path.exists() or manifest_path.exists():
            raise MemoryBackupError("memory_backup_destination_exists")
        if not destination_path.parent.is_dir():
            raise MemoryBackupError("memory_backup_parent_missing")
        temp_path = destination_path.with_name(f".{destination_path.name}.{uuid.uuid4().hex}.tmp")
        started = time.monotonic()
        try:
            secure_sqlite_path(temp_path)
            target = await aiosqlite.connect(str(temp_path), isolation_level=None)
            try:
                async with self._operation():
                    await self._conn.backup(target)
            finally:
                await target.close()
            verify_sqlite_path(temp_path)
            sha = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            async with self._operation():
                async with self._conn.execute(
                    "SELECT generation_id, lineage_id FROM embedding_generations "
                    "WHERE state = 'active' LIMIT 1"
                ) as cursor:
                    active = await cursor.fetchone()
            manifest: dict[str, object] = {
                "protocol": "simple-harness-memory/sqlite-backup/v1",
                "schema_version": SCHEMA_VERSION,
                "schema_checksum": SCHEMA_CHECKSUM,
                "sqlite_version": sqlite3.sqlite_version,
                "sha256": sha,
                "created_at": time.time(),
                "active_generation_id": None if active is None else str(active[0]),
                "active_lineage_id": None if active is None else str(active[1]),
            }
            os.replace(temp_path, destination_path)
            os.chmod(destination_path, 0o600)
            manifest_tmp = manifest_path.with_name(f".{manifest_path.name}.{uuid.uuid4().hex}.tmp")
            manifest_tmp.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            os.chmod(manifest_tmp, 0o600)
            os.replace(manifest_tmp, manifest_path)
            logger.info(
                "memory.backup_completed",
                backup_sha256=sha,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return manifest
        except Exception:
            temp_path.unlink(missing_ok=True)
            logger.error("memory.backup_failed", stable_code="memory_backup_failed")
            raise

    @staticmethod
    def restore_backup_sync(
        backup: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> dict[str, object]:
        """Validate a closed backup in isolation, then atomically replace the target."""

        backup_path = Path(backup).resolve()
        target_path = Path(target).resolve()
        manifest_path = backup_path.with_name(backup_path.name + ".manifest.json")
        try:
            verify_sqlite_path(backup_path)
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise MemoryBackupError()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("protocol") != "simple-harness-memory/sqlite-backup/v1":
                raise MemoryBackupError()
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise MemoryBackupError()
            if manifest.get("schema_checksum") != SCHEMA_CHECKSUM:
                raise MemoryBackupError()
            if hashlib.sha256(backup_path.read_bytes()).hexdigest() != manifest.get("sha256"):
                raise MemoryBackupError()
            if (
                backup_path.with_name(backup_path.name + "-wal").exists()
                or backup_path.with_name(backup_path.name + "-shm").exists()
            ):
                raise MemoryBackupError("memory_backup_has_wal_residue")
            source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
            try:
                if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise MemoryBackupError()
                if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise MemoryBackupError()
                meta = dict(source.execute("SELECT key, value FROM schema_meta"))
                if meta.get("schema_version") != str(SCHEMA_VERSION):
                    raise MemoryBackupError()
                if meta.get("schema_checksum") != SCHEMA_CHECKSUM:
                    raise MemoryBackupError()
                active = source.execute(
                    "SELECT generation_id, lineage_id FROM embedding_generations "
                    "WHERE state = 'active' LIMIT 1"
                ).fetchone()
                actual_generation = None if active is None else str(active[0])
                actual_lineage = None if active is None else str(active[1])
                if manifest.get("active_generation_id") != actual_generation:
                    raise MemoryBackupError()
                if manifest.get("active_lineage_id") != actual_lineage:
                    raise MemoryBackupError()
            finally:
                source.close()
            target_path.parent.mkdir(parents=False, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(prefix=f".{target_path.name}.", dir=target_path.parent)
            os.close(fd)
            temp = Path(raw_temp)
            try:
                os.chmod(temp, 0o600)
                source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
                destination = sqlite3.connect(temp)
                try:
                    source.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise MemoryBackupError()
                finally:
                    source.close()
                    destination.close()
                os.replace(temp, target_path)
                os.chmod(target_path, 0o600)
            finally:
                temp.unlink(missing_ok=True)
            return manifest
        except MemoryBackupError:
            raise
        except Exception as exc:
            raise MemoryBackupError() from exc

    async def _close_locked(self) -> None:
        if self._db is None:
            self._release_writer_lease()
            return
        await self._db.close()
        self._db = None
        self._release_writer_lease()
        logger.info("memory.backend_closed", db_path_hash=path_digest(self._db_path))

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteMemoryBackend is not initialized")
        return self._db

    async def _commit(self) -> None:
        if self._transaction_depth.get() == 0:
            await self._conn.commit()

    @asynccontextmanager
    async def _transaction(self, *, deadline: float | None = None):
        async with self._operation():
            task = asyncio.current_task()
            if task is None:
                raise RuntimeError("memory transaction requires an asyncio task")
            depth = self._transaction_depth.get()
            if self._transaction_owner is task:
                token = self._transaction_depth.set(depth + 1)
                try:
                    yield
                finally:
                    self._transaction_depth.reset(token)
                return

            token = self._transaction_depth.set(1)
            self._transaction_owner = task
            busy_timeout_changed = False
            try:
                if deadline is not None:
                    remaining = deadline - asyncio.get_running_loop().time()
                    busy_timeout_ms = int(remaining * 1000) - 1
                    if busy_timeout_ms < 1:
                        raise TimeoutError("memory transaction deadline exceeded")
                    busy_timeout_ms = min(busy_timeout_ms, self._default_busy_timeout_ms)
                    await self._conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
                    busy_timeout_changed = True
                await self._conn.execute("BEGIN IMMEDIATE")
                try:
                    yield
                    await self._conn.commit()
                except BaseException:
                    await self._conn.rollback()
                    raise
            except aiosqlite.OperationalError as exc:
                if deadline is not None and "locked" in str(exc).lower():
                    raise TimeoutError("memory transaction deadline exceeded") from None
                raise
            finally:
                self._transaction_owner = None
                self._transaction_depth.reset(token)
                if busy_timeout_changed and self._db is not None:
                    await self._conn.execute(
                        f"PRAGMA busy_timeout = {self._default_busy_timeout_ms}"
                    )

    async def _ensure_session_impl(self, user_id: str, session_id: str) -> None:
        now = time.time()
        await self._conn.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
            (user_id, now),
        )
        async with self._conn.execute(
            "SELECT user_id FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            try:
                await self._conn.execute(
                    "INSERT INTO sessions "
                    "(session_id, user_id, deployment_id, household_id, actor_id, "
                    "created_at, last_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, user_id, user_id, user_id, user_id, now, now),
                )
            except aiosqlite.IntegrityError as exc:
                raise MemoryOwnershipConflict() from exc

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
        try:
            cursor = await self._conn.execute(
                "INSERT INTO messages "
                "(user_id, deployment_id, household_id, actor_id, scope_kind, "
                "scope_owner, session_id, role, content, created_at, salience, "
                "decay_rate, embedding, is_summary, summary_of, source_event_id, "
                "payload_hash, embedder_kind, embedding_dim, "
                "embedding_format_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    user_id,
                    user_id,
                    user_id,
                    "personal",
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
                "SELECT id, payload_hash FROM messages WHERE user_id = ? AND source_event_id = ?",
                (user_id, source_event_id),
            ) as query:
                row = await query.fetchone()
            if row is None or row["payload_hash"] != payload_hash:
                raise MemoryIdempotencyConflict() from exc
            return MemoryApplyResult(
                message_id=int(row["id"]),
                source_event_id=source_event_id,
                payload_hash=payload_hash,
                status=MemoryApplyStatus.ALREADY_APPLIED,
            )
        await self._conn.execute(
            "UPDATE sessions SET last_activity_at = ? WHERE user_id = ? AND session_id = ?",
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
            "SELECT id, payload_hash FROM messages WHERE user_id = ? AND source_event_id = ?",
            (user_id, source_event_id),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return int(row["id"]), str(row["payload_hash"])

    async def _get_message_impl(self, user_id: str, message_id: int) -> Message | None:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE user_id = ? AND id = ?",
            (user_id, message_id),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_message(row) if row is not None else None

    async def _query_messages_impl(
        self,
        user_id: str,
        *,
        limit: int,
        session_id: str | None = None,
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
        self,
        user_id: str,
        *,
        limit: int,
        subject: str | None = None,
        category: str | None = None,
        active_only: bool = False,
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
        sql = "SELECT * FROM facts WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?"
        async with self._conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_fact(row) for row in rows]

    async def _insert_fact_impl(self, user_id: str, fact: Fact) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO facts "
            "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
            "subject, key, value, category, confidence, evidence, "
            "source_msg_id, created_at, decay_rate, pinned) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                user_id,
                user_id,
                user_id,
                "personal",
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

    async def _supersede_fact_impl(self, user_id: str, fact_id: int, superseded_by: int) -> None:
        await self._conn.execute(
            "UPDATE facts SET superseded_by = ? "
            "WHERE user_id = ? AND id = ? "
            "AND EXISTS (SELECT 1 FROM facts AS replacement "
            "WHERE replacement.user_id = ? AND replacement.id = ?)",
            (superseded_by, user_id, fact_id, user_id, superseded_by),
        )

    async def _forget_fact_by_id_impl(
        self, user_id: str, fact_id: int, forgotten_at: float
    ) -> bool:
        cursor = await self._conn.execute(
            "UPDATE facts SET forgotten_at = ? WHERE user_id = ? AND id = ?",
            (forgotten_at, user_id, fact_id),
        )
        return cursor.rowcount > 0

    async def _update_message_salience_impl(
        self,
        user_id: str,
        message_id: int,
        salience: float,
        last_recalled: float | None,
        last_decay_at: float | None = None,
    ) -> None:
        await self._conn.execute(
            "UPDATE messages SET salience = ?, "
            "last_recalled = COALESCE(?, last_recalled), "
            "last_decay_at = COALESCE(?, last_decay_at) "
            "WHERE user_id = ? AND id = ?",
            (salience, last_recalled, last_decay_at, user_id, message_id),
        )

    async def _set_fact_decay_impl(
        self,
        user_id: str,
        fact_id: int,
        *,
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
                f"UPDATE facts SET {', '.join(updates)} WHERE user_id = ? AND id = ?",
                tuple(params),
            )

    async def _load_twin_impl(self, user_id: str, subject: str) -> DigitalTwin:
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
            "INSERT INTO users (user_id, created_at) VALUES (?, ?) ON CONFLICT(user_id) DO NOTHING",
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
            "SELECT COUNT(*) FROM messages WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ) as cursor:
            row = await cursor.fetchone()
        deleted = int(row[0]) if row is not None else 0
        await self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )
        return deleted

    async def _old_session_ids_impl(self, user_id: str, cutoff: float, limit: int) -> list[str]:
        async with self._conn.execute(
            "SELECT session_id FROM sessions "
            "WHERE user_id = ? AND last_activity_at < ? "
            "ORDER BY last_activity_at, session_id LIMIT ?",
            (user_id, cutoff, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [str(row["session_id"]) for row in rows]

    async def _update_embedding_impl(
        self,
        user_id: str,
        message_id: int,
        embedding: bytes,
        embedder_kind: str,
        embedding_dim: int,
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
            "WHERE deployment_id = ? AND user_id = ? AND context_query_id = ?",
            (user_id, user_id, context_query_id),
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
        try:
            await self._conn.execute(
                "INSERT INTO recall_result_snapshots "
                "(context_query_id, user_id, deployment_id, household_id, actor_id, "
                "scope_set_hash, write_fence, session_id, query_hash, result_payload, "
                "result_hash, state, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'retained', ?)",
                (
                    context_query_id,
                    user_id,
                    user_id,
                    user_id,
                    user_id,
                    hashlib.sha256(f"personal:{user_id}".encode()).hexdigest(),
                    hashlib.sha256(f"standalone:{user_id}:0".encode()).hexdigest(),
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
        self,
        *,
        user_id: str,
        context_query_id: str,
        result_hash: str,
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
        self, *, user_id: str, expired_before: float, limit: int
    ) -> int:
        cursor = await self._conn.execute(
            "DELETE FROM recall_result_snapshots WHERE (deployment_id, context_query_id) IN ("
            "SELECT deployment_id, context_query_id FROM ("
            "SELECT deployment_id, context_query_id, released_at AS expired_at "
            "FROM recall_result_snapshots "
            "WHERE user_id = ? AND state = 'released' AND released_at <= ? "
            "UNION ALL "
            "SELECT deployment_id, context_query_id, created_at AS expired_at "
            "FROM recall_result_snapshots "
            "WHERE user_id = ? AND state = 'retained' AND created_at <= ?"
            ") ORDER BY expired_at, context_query_id LIMIT ?"
            ") AND user_id = ?",
            (
                user_id,
                expired_before,
                user_id,
                expired_before,
                limit,
                user_id,
            ),
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
            last_decay_at=row["last_decay_at"],
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
