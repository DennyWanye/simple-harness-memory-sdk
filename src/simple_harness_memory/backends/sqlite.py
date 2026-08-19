"""SQLite 后端 — 本地持久化实现。"""
from __future__ import annotations

import dataclasses
import json
import time
from typing import Optional

import aiosqlite
import structlog

from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.core.errors import MemoryCorruptionError
from simple_harness_memory.core.models import Fact, Message
from simple_harness_memory.core.twin import (
    DigitalTwin, Entity, Goal, Preference, PreferenceMap, RelationshipGraph,
    Skill, SkillMap, UserProfile,
)

logger = structlog.get_logger("simple_harness_memory.backends.sqlite")

_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    salience REAL NOT NULL DEFAULT 0.0,
    decay_rate REAL NOT NULL DEFAULT 0.02,
    last_recalled REAL,
    embedding BLOB,
    is_summary INTEGER NOT NULL DEFAULT 0,
    summary_of TEXT
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence TEXT NOT NULL DEFAULT '',
    source_msg_id INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    decay_rate REAL NOT NULL DEFAULT 0.01,
    pinned INTEGER NOT NULL DEFAULT 0,
    last_decay_at REAL,
    superseded_by INTEGER,
    forgotten_at REAL
);
CREATE TABLE IF NOT EXISTS digital_twins (
    subject TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject, category);
"""


class SQLiteMemoryBackend(BaseMemoryBackend):
    def __init__(self, db_path: str, *, embedder=None, fact_extractor=None, reranker=None, summarizer=None, auto_extract_facts=False):
        super().__init__(embedder=embedder, fact_extractor=fact_extractor, reranker=reranker, summarizer=summarizer, auto_extract_facts=auto_extract_facts)
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        try:
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_DDL)
            await self._db.commit()
            logger.info("memory.backend_initialized", db_path=self._db_path)
        except Exception:
            logger.exception("memory.backend_initialize_failed", db_path=self._db_path)
            raise

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("memory.backend_closed", db_path=self._db_path)

    @property
    def _conn(self):
        if self._db is None:
            raise RuntimeError("SQLiteMemoryBackend not initialized — call initialize() first")
        return self._db

    async def _append_message_impl(self, session_id, role, content, embedding, salience, decay_rate, created_at, is_summary, summary_of):
        cur = await self._conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at, salience, decay_rate, embedding, is_summary, summary_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, role, content, created_at, salience, decay_rate, embedding, int(is_summary), summary_of),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def _get_message_impl(self, message_id):
        async with self._conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)) as cur:
            row = await cur.fetchone()
        return self._row_to_message(row) if row else None

    async def _get_recent_messages_impl(self, session_id, limit):
        async with self._conn.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?", (session_id, limit)) as cur:
            rows = await cur.fetchall()
        return [self._row_to_message(r) for r in reversed(rows)]

    async def _messages_all(self):
        async with self._conn.execute("SELECT * FROM messages ORDER BY id") as cur:
            rows = await cur.fetchall()
        return [self._row_to_message(r) for r in rows]

    async def _facts_all(self):
        async with self._conn.execute("SELECT * FROM facts") as cur:
            rows = await cur.fetchall()
        return [self._row_to_fact(r) for r in rows]

    async def _insert_fact(self, fact):
        cur = await self._conn.execute(
            "INSERT INTO facts (subject, key, value, category, confidence, evidence, source_msg_id, created_at, decay_rate, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact.subject, fact.key, fact.value, fact.category, fact.confidence, fact.evidence, fact.source_msg_id, fact.created_at, fact.decay_rate, int(fact.pinned)),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def _supersede_fact(self, fact_id, superseded_by):
        await self._conn.execute("UPDATE facts SET superseded_by = ? WHERE id = ?", (superseded_by, fact_id))
        await self._conn.commit()

    async def _forget_fact_by_id(self, fact_id, forgotten_at):
        cur = await self._conn.execute("UPDATE facts SET forgotten_at = ? WHERE id = ?", (forgotten_at, fact_id))
        await self._conn.commit()
        return cur.rowcount > 0

    async def _update_message_salience(self, message_id, salience, last_recalled):
        await self._conn.execute("UPDATE messages SET salience = ?, last_recalled = COALESCE(?, last_recalled) WHERE id = ?", (salience, last_recalled, message_id))
        await self._conn.commit()

    async def _set_fact_decay(self, fact_id, *, forgotten_at=None, last_decay_at=None):
        updates = []
        params = []
        if forgotten_at is not None:
            updates.append("forgotten_at = ?")
            params.append(forgotten_at)
        if last_decay_at is not None:
            updates.append("last_decay_at = ?")
            params.append(last_decay_at)
        if updates:
            params.append(fact_id)
            await self._conn.execute(f"UPDATE facts SET {', '.join(updates)} WHERE id = ?", params)
            await self._conn.commit()

    async def _load_twin(self, subject):
        async with self._conn.execute("SELECT data_json FROM digital_twins WHERE subject = ?", (subject,)) as cur:
            row = await cur.fetchone()
        return self._deserialize_twin(subject, row["data_json"]) if row else DigitalTwin(subject=subject)

    async def _save_twin(self, twin):
        await self._conn.execute(
            "INSERT INTO digital_twins (subject, data_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(subject) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at",
            (twin.subject, json.dumps(dataclasses.asdict(twin), ensure_ascii=False), time.time()),
        )
        await self._conn.commit()

    async def _record_workspace_impl(self, session_id, action_type, payload):
        await self._conn.execute(
            "INSERT INTO workspace_actions (session_id, action_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (session_id, action_type, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        await self._conn.commit()

    @staticmethod
    def _row_to_message(row):
        return Message(
            id=row["id"], session_id=row["session_id"], role=row["role"], content=row["content"],
            created_at=row["created_at"], salience=row["salience"], decay_rate=row["decay_rate"],
            last_recalled=row["last_recalled"], embedding=row["embedding"],
            is_summary=bool(row["is_summary"]), summary_of=row["summary_of"],
        )

    @staticmethod
    def _row_to_fact(row):
        return Fact(
            id=row["id"], subject=row["subject"], key=row["key"], value=row["value"],
            category=row["category"], confidence=row["confidence"], evidence=row["evidence"],
            source_msg_id=row["source_msg_id"], created_at=row["created_at"],
            pinned=bool(row["pinned"]), last_decay_at=row["last_decay_at"],
            superseded_by=row["superseded_by"], forgotten_at=row["forgotten_at"],
        )

    @staticmethod
    def _deserialize_twin(subject, data_json):
        try:
            d = json.loads(data_json)
        except Exception as exc:
            raise MemoryCorruptionError(
                f"digital_twin for subject {subject!r} is corrupt"
            ) from exc
        twin = DigitalTwin(subject=d.get("subject", subject))
        p = d.get("profile") or {}
        twin.profile = UserProfile(name=p.get("name"), occupation=p.get("occupation"), location=p.get("location"), language=p.get("language"), timezone=p.get("timezone"), extra=p.get("extra") or {})
        sm = (d.get("skills") or {}).get("skills") or {}
        twin.skills = SkillMap(skills={})
        for name, sk in sm.items():
            twin.skills.skills[name] = Skill(name=sk.get("name", name), level=sk.get("level", 0.5), evidence_count=sk.get("evidence_count", 0), last_updated=sk.get("last_updated"))
        pm = (d.get("preferences") or {}).get("preferences") or {}
        twin.preferences = PreferenceMap(preferences={})
        for key, pr in pm.items():
            twin.preferences.preferences[key] = Preference(key=pr.get("key", key), value=pr.get("value", ""), strength=pr.get("strength", 0.5), evidence_count=pr.get("evidence_count", 0))
        rg = (d.get("relationships") or {}).get("entities") or {}
        twin.relationships = RelationshipGraph(entities={})
        for name, e in rg.items():
            twin.relationships.entities[name] = Entity(name=e.get("name", name), entity_type=e.get("entity_type", "object"), relation=e.get("relation", ""), attributes=e.get("attributes") or {}, confidence=e.get("confidence", 0.5), last_mentioned=e.get("last_mentioned"))
        twin.goals = []
        for g in d.get("goals") or []:
            twin.goals.append(Goal(goal_id=g.get("goal_id", ""), description=g.get("description", ""), deadline=g.get("deadline"), status=g.get("status", "active"), priority=g.get("priority", 0.5), created_at=g.get("created_at")))
        twin.completeness = d.get("completeness", 0.0)
        twin.confidence = d.get("confidence", 0.0)
        twin.last_updated = d.get("last_updated")
        return twin
