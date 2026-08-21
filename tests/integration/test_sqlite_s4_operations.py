from __future__ import annotations

import hashlib
import json
import time

import pytest

from simple_harness_memory import MemoryManager, MemoryPrincipal, MemoryScope
from simple_harness_memory.backends import sqlite as sqlite_module
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.errors import (
    MemoryBackupError,
    MemoryProductionConfigurationError,
    MemoryWriterConflict,
)
from simple_harness_memory.embedders.base import EMBEDDING_FORMAT_VERSION, encode_vector
from simple_harness_memory.embedders.mock import HashEmbedder


class _FailingEmbedder(HashEmbedder):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("deterministic reindex fault")


@pytest.mark.asyncio
async def test_production_builder_requires_explicit_non_development_resources(tmp_path):
    with pytest.raises(MemoryProductionConfigurationError) as missing:
        await MemoryManager.build_production(tmp_path / "missing.db")
    assert missing.value.code == "memory_production_embedder_required"
    with pytest.raises(MemoryProductionConfigurationError):
        await MemoryManager.build_production(
            tmp_path / "hash.db", embedder=HashEmbedder(), resource_path=tmp_path
        )


async def _seed_messages(backend: SQLiteMemoryBackend, count: int) -> None:
    now = time.time()
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "scale-session")
    user_id = backend._principal_key(principal)
    async with backend._transaction():
        await backend._conn.execute(
            "INSERT INTO users(user_id, created_at) VALUES (?, ?)", (user_id, now)
        )
        await backend._conn.execute(
            "INSERT INTO sessions(session_id, user_id, deployment_id, household_id, actor_id, "
            "created_at, last_activity_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "scale-session",
                user_id,
                "deployment-a",
                "house-a",
                "actor-a",
                now,
                now,
            ),
        )
        await backend._conn.executemany(
            "INSERT INTO messages(user_id, deployment_id, household_id, actor_id, "
            "scope_kind, scope_owner, session_id, role, content, created_at, source_event_id, "
            "payload_hash) VALUES (?, 'deployment-a', 'house-a', 'actor-a', "
            "'personal', 'actor-a', 'scale-session', 'user', ?, ?, ?, ?)",
            [
                (
                    user_id,
                    f"bounded retrieval row {index} Max" if index % 997 == 0 else f"row {index}",
                    now + index / 1_000_000,
                    f"scale-event-{index}",
                    hashlib.sha256(str(index).encode()).hexdigest(),
                )
                for index in range(count)
            ],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("row_count", [20_000, 100_000])
async def test_fts_query_plan_and_recall_remain_bounded(tmp_path, row_count):
    backend = SQLiteMemoryBackend(str(tmp_path / f"scale-{row_count}.db"))
    await backend.initialize()
    await _seed_messages(backend, row_count)
    predicate = (
        "m.deployment_id = ? AND m.household_id = ? AND "
        "m.scope_kind = ? AND m.scope_owner = ?"
    )
    async with backend._conn.execute(
        "EXPLAIN QUERY PLAN SELECT m.id FROM messages_fts JOIN messages AS m "
        f"ON m.id = messages_fts.rowid WHERE {predicate} AND messages_fts MATCH ? LIMIT ?",
        ("deployment-a", "house-a", "personal", "actor-a", "Max", 64),
    ) as cursor:
        plan = " ".join(str(row[3]) for row in await cursor.fetchall())
    assert "VIRTUAL TABLE INDEX" in plan

    payload, _fence, _replayed = await backend.agent_recall(
        principal=MemoryPrincipal("deployment-a", "house-a", "actor-a", "scale-session"),
        scopes=(MemoryScope.personal("actor-a"),),
        query_id=f"scale-query-{row_count}",
        query_hash=hashlib.sha256(f"query-{row_count}".encode()).hexdigest(),
        query_text="Max",
        max_items=20,
        max_bytes=16_384,
    )
    assert len(payload["items"]) <= 20
    await backend.close()


@pytest.mark.asyncio
async def test_lineage_drift_degrades_without_decoding_active_vectors(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(str(tmp_path / "drift.db"), embedder=HashEmbedder(dim=32))
    await backend.initialize()
    await _seed_messages(backend, 10)
    await backend.reindex_generation(HashEmbedder(dim=32), page_size=4)
    backend._embedder = HashEmbedder(dim=64)

    def forbidden_similarity(*_args, **_kwargs):
        raise AssertionError("drifted vectors must not be decoded or scored")

    monkeypatch.setattr(sqlite_module, "cosine_similarity", forbidden_similarity)
    payload, _fence, _replayed = await backend.agent_recall(
        principal=MemoryPrincipal("deployment-a", "house-a", "actor-a", "scale-session"),
        scopes=(MemoryScope.personal("actor-a"),),
        query_id="drift-query",
        query_hash=hashlib.sha256(b"drift-query").hexdigest(),
        query_text="Max",
        max_items=5,
        max_bytes=8_192,
    )
    assert payload["items"]
    await backend.close()


@pytest.mark.asyncio
async def test_two_generation_reindex_switch_and_failure_preserve_active(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    manager = await MemoryManager.build(backend=backend)
    await backend.append_message(
        "session-a",
        "user",
        "Max likes pizza",
        user_id="user-a",
        source_event_id="event-a",
    )
    selected = HashEmbedder(dim=32)
    lineage = selected.lineage
    first_vector = encode_vector(await selected.embed("Max likes pizza"))
    first_hash = hashlib.sha256(b"1" + first_vector).hexdigest()
    async with backend._transaction():
        await backend._conn.execute(
            "INSERT INTO embedding_lineages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        await backend._conn.execute(
            "INSERT INTO embedding_generations(generation_id, lineage_id, state, cursor, "
            "vector_count, content_hash, created_at) VALUES "
            "('resume-generation', ?, 'building', 1, 1, ?, ?)",
            (lineage.lineage_id, first_hash, time.time()),
        )
        await backend._conn.execute(
            "INSERT INTO message_vectors VALUES (1, 'resume-generation', ?, 32)",
            (first_vector,),
        )
    await backend.append_message(
        "session-a",
        "assistant",
        "Acknowledged",
        user_id="user-a",
        source_event_id="event-b",
    )
    activated = await manager.reindex_generation(selected, page_size=1)
    assert activated["state"] == "active"
    assert activated["generation_id"] == "resume-generation"
    assert activated["vector_count"] == 2
    async with backend._conn.execute(
        "SELECT generation_id FROM embedding_generations WHERE state = 'active'"
    ) as cursor:
        before = str((await cursor.fetchone())[0])

    with pytest.raises(RuntimeError, match="deterministic reindex fault"):
        await manager.reindex_generation(_FailingEmbedder(dim=64), page_size=1)
    async with backend._conn.execute(
        "SELECT generation_id FROM embedding_generations WHERE state = 'active'"
    ) as cursor:
        after = str((await cursor.fetchone())[0])
    assert after == before
    await manager.close()


@pytest.mark.asyncio
async def test_second_writer_checkpoint_backup_restore_and_corruption_preserve(tmp_path):
    database = tmp_path / "memory.db"
    manager = await MemoryManager.build(db_path=str(database))
    competing = SQLiteMemoryBackend(str(database))
    with pytest.raises(MemoryWriterConflict) as conflict:
        await competing.initialize()
    assert conflict.value.code == "memory_second_writer_rejected"

    await manager.backend.append_message(
        "session-a",
        "user",
        "durable backup value",
        user_id="user-a",
        source_event_id="event-a",
    )
    await manager.checkpoint(deadline_seconds=1.0)
    backup = tmp_path / "memory.backup.db"
    manifest = await manager.backup(backup)
    assert manifest["sha256"] == hashlib.sha256(backup.read_bytes()).hexdigest()
    await manager.close()

    original = database.read_bytes()
    manifest_path = backup.with_name(backup.name + ".manifest.json")
    valid_manifest = manifest_path.read_text(encoding="utf-8")
    tampered = json.loads(valid_manifest)
    tampered["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MemoryBackupError):
        await manager.restore_backup(backup)
    assert database.read_bytes() == original

    manifest_path.write_text(valid_manifest, encoding="utf-8")
    await manager.restore_backup(backup)
    restored = await MemoryManager.build(db_path=str(database))
    recent = await restored.backend.get_recent_messages("session-a", user_id="user-a")
    assert [message.content for message in recent] == ["durable backup value"]
    await restored.close()


@pytest.mark.asyncio
async def test_checkpoint_and_restore_require_live_and_closed_boundaries(tmp_path):
    manager = await MemoryManager.build(db_path=str(tmp_path / "memory.db"))
    with pytest.raises(ValueError, match="positive"):
        await manager.checkpoint(deadline_seconds=0)
    with pytest.raises(RuntimeError, match="closed"):
        await manager.restore_backup(tmp_path / "missing.db")
    await manager.close()
    with pytest.raises(RuntimeError, match="not initialized"):
        await manager.checkpoint(deadline_seconds=0.1)
