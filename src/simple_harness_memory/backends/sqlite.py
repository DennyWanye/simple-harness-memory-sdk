"""SQLite 后端 — Phase 1 本地持久化实现。

依赖：aiosqlite>=0.19
"""

from __future__ import annotations

import json
import time
from typing import Optional

import aiosqlite

from simple_harness_memory.core.models import Fact, Hit, Message
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.features.rrf import RankedItem, fuse

_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  REAL    NOT NULL,
    salience    REAL    NOT NULL DEFAULT 0.0,
    decay_rate  REAL    NOT NULL DEFAULT 0.02,
    last_recalled REAL,
    embedding   BLOB,
    is_summary  INTEGER NOT NULL DEFAULT 0,
    summary_of  TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject         TEXT    NOT NULL,
    key             TEXT    NOT NULL,
    value           TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    confidence      REAL    NOT NULL DEFAULT 1.0,
    evidence        TEXT    NOT NULL DEFAULT '',
    source_msg_id   INTEGER NOT NULL DEFAULT 0,
    created_at      REAL    NOT NULL,
    decay_rate      REAL    NOT NULL DEFAULT 0.01,
    pinned          INTEGER NOT NULL DEFAULT 0,
    last_decay_at   REAL,
    superseded_by   INTEGER,
    forgotten_at    REAL
);

CREATE TABLE IF NOT EXISTS digital_twins (
    subject     TEXT PRIMARY KEY,
    data_json   TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject, category);
"""


class SQLiteMemoryBackend(MemoryBackend):
    """SQLite 本地持久化后端（Phase 1）。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_DDL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SQLiteMemoryBackend not initialized — call initialize() first")
        return self._db

    # ── L2 ──────────────────────────────────────────

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at, salience, decay_rate) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, time.time(), salience, decay_rate),
        )
        await self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_recent_messages(self, session_id: str, limit: int = 20) -> list[Message]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_message(r) for r in reversed(rows)]

    async def get_message(self, message_id: int) -> Optional[Message]:
        async with self._conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_message(row) if row else None

    # ── L3 ──────────────────────────────────────────

    async def extract_facts(self, message_id: int, content: str, role: str) -> list[Fact]:
        # Phase 2 实现 LLM 提取，Phase 1 返回空列表
        return []

    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> list[Fact]:
        sql = "SELECT * FROM facts WHERE subject = ?"
        params: list = [subject]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if active_only:
            sql += " AND superseded_by IS NULL AND forgotten_at IS NULL"
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [self._row_to_fact(r) for r in rows]

    async def forget_fact(self, fact_id: int, reason: str = "") -> bool:
        cursor = await self._conn.execute(
            "UPDATE facts SET forgotten_at = ? WHERE id = ?",
            (time.time(), fact_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # ── Digital Twin ─────────────────────────────────

    async def get_digital_twin(self, subject: str = "user") -> DigitalTwin:
        async with self._conn.execute(
            "SELECT data_json FROM digital_twins WHERE subject = ?", (subject,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return DigitalTwin(subject=subject)
        return self._deserialize_twin(subject, row["data_json"])

    async def update_digital_twin(self, twin: DigitalTwin) -> None:
        twin.last_updated = time.time()
        twin.recalculate_completeness()
        await self._conn.execute(
            "INSERT INTO digital_twins (subject, data_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(subject) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at",
            (twin.subject, self._serialize_twin(twin), time.time()),
        )
        await self._conn.commit()

    async def suggest_questions(self, subject: str = "user") -> list[str]:
        twin = await self.get_digital_twin(subject)
        q_map = {
            "name": "你叫什么名字？",
            "occupation": "你是做什么工作的？",
            "location": "你在哪个城市？",
            "language": "你常用的语言是什么？",
        }
        return [q_map[f] for f in twin.missing_profile_fields() if f in q_map]

    # ── 混合召回 ─────────────────────────────────────

    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[Hit]:
        # Phase 1: FTS 关键词召回；Phase 2 接入向量 + RRF
        return await self._fts_search(query, session_id, limit)

    async def vector_search(self, query: str, limit: int = 20) -> list[Hit]:
        # Phase 2 实现 BGE-M3；Phase 1 降级为 FTS
        return await self._fts_search(query, None, limit)

    async def _fts_search(
        self,
        query: str,
        session_id: Optional[str],
        limit: int,
    ) -> list[Hit]:
        q = f"%{query.lower()}%"
        sql = "SELECT * FROM messages WHERE lower(content) LIKE ? "
        params: list = [q]
        if session_id:
            sql += "AND session_id = ? "
            params.append(session_id)
        sql += "ORDER BY created_at DESC LIMIT ?"
        params.append(limit * 2)
        async with self._conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        ranked = [
            RankedItem(
                message_id=r["id"],
                text=r["content"],
                rank=i + 1,
                source="fts",
                recency=1.0 / (i + 1),
                salience=r["salience"],
                session_id=r["session_id"],
                role=r["role"],
                created_at=r["created_at"],
            )
            for i, r in enumerate(rows)
        ]
        fused = fuse([ranked], limit=limit)
        return [
            Hit(
                message_id=f["message_id"],
                text=f["text"],
                score=f["score"],
                source=f["source"],
                recency=f["recency"],
                salience=f["salience"],
                session_id=f["session_id"],
                role=f["role"],
                created_at=f["created_at"],
            )
            for f in fused
        ]

    # ── 认知维护 ─────────────────────────────────────

    async def daily_decay(self) -> dict[str, int]:
        # Phase 3 实现完整衰减；Phase 1 返回 0
        return {"decayed": 0, "forgotten": 0}

    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
    ) -> dict[str, int]:
        return {"summarized_sessions": 0}

    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
    ) -> None:
        await self._conn.execute(
            "INSERT INTO workspace_actions (session_id, action_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, action_type, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        await self._conn.commit()

    # ── 序列化辅助 ────────────────────────────────────

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> Message:
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            salience=row["salience"],
            decay_rate=row["decay_rate"],
            last_recalled=row["last_recalled"],
            embedding=row["embedding"],
            is_summary=bool(row["is_summary"]),
            summary_of=row["summary_of"],
        )

    @staticmethod
    def _row_to_fact(row: aiosqlite.Row) -> Fact:
        f = Fact(
            id=row["id"],
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
        return f

    @staticmethod
    def _serialize_twin(twin: DigitalTwin) -> str:
        import dataclasses
        return json.dumps(dataclasses.asdict(twin), ensure_ascii=False)

    @staticmethod
    def _deserialize_twin(subject: str, data_json: str) -> DigitalTwin:
        # Phase 1 简化：反序列化失败时返回空孪生体
        try:
            data = json.loads(data_json)
            twin = DigitalTwin(subject=subject)
            p = data.get("profile", {})
            from simple_harness_memory.core.twin import (
                Goal, PreferenceMap, RelationshipGraph, SkillMap, UserProfile
            )
            twin.profile = UserProfile(**{k: v for k, v in p.items() if k != "extra"})
            twin.profile.extra = p.get("extra", {})
            twin.completeness = data.get("completeness", 0.0)
            twin.confidence = data.get("confidence", 0.0)
            twin.last_updated = data.get("last_updated")
            return twin
        except Exception:
            return DigitalTwin(subject=subject)
