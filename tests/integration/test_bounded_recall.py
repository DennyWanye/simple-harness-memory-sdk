import asyncio

import pytest

from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.models import RecallStatus


@pytest.mark.asyncio
async def test_recall_enforces_count_and_utf8_byte_bounds() -> None:
    backend = MockMemoryBackend(
        bounds=MemoryResourceBounds(
            recall_candidate_messages=3,
            recall_candidate_facts=3,
            recall_max_results=2,
        )
    )
    for index in range(5):
        await backend.append_message(
            "s1",
            "user",
            f"共享词 消息-{index}",
            user_id="u1",
            source_event_id=f"event-{index}",
        )
    result = await backend.recall_bounded(
        "共享词",
        user_id="u1",
        session_id="s1",
        context_query_id="query-count",
        max_results=2,
        max_bytes=360,
    )
    assert len(result.hits) <= 2
    assert result.result_bytes <= 360
    assert result.status is RecallStatus.TRUNCATED


@pytest.mark.asyncio
async def test_timeout_is_durable_stable_result(monkeypatch) -> None:
    backend = MockMemoryBackend()

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
        return [], False

    monkeypatch.setattr(backend, "_compute_recall", slow)
    first = await backend.recall_bounded(
        "query",
        user_id="u1",
        session_id="s1",
        context_query_id="query-timeout",
        max_results=2,
        max_bytes=1024,
        timeout_seconds=0.001,
    )
    assert first.status is RecallStatus.TIMEOUT
    replay = await backend.recall_bounded(
        "query",
        user_id="u1",
        session_id="s1",
        context_query_id="query-timeout",
        max_results=2,
        max_bytes=1024,
        timeout_seconds=0.001,
    )
    assert replay.replayed
    assert replay.result_hash == first.result_hash


def test_production_source_has_no_full_table_repository_api() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "simple_harness_memory"
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    assert "_messages_all" not in source
    assert "_facts_all" not in source


@pytest.mark.asyncio
async def test_sqlite_recall_uses_user_predicates_limits_and_indexes(tmp_path) -> None:
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    for index in range(4):
        await backend.append_message(
            f"session-{index}",
            "user",
            f"shared word {index}",
            user_id="user-a",
            source_event_id=f"event-{index}",
        )
    statements: list[str] = []
    await backend._conn.set_trace_callback(statements.append)
    await backend.recall_bounded(
        "shared",
        user_id="user-a",
        session_id="session-0",
        context_query_id="query-plan",
        max_results=2,
        max_bytes=2048,
    )
    bulk_reads = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select * from messages")
        or statement.lstrip().lower().startswith("select * from facts")
    ]
    assert len(bulk_reads) == 2
    assert all("where user_id =" in statement for statement in bulk_reads)
    assert all(" limit " in statement for statement in bulk_reads)

    plans: list[str] = []
    for sql in (
        "SELECT * FROM messages WHERE user_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        "SELECT * FROM facts WHERE user_id = ? AND superseded_by IS NULL "
        "AND forgotten_at IS NULL ORDER BY id DESC LIMIT ?",
    ):
        async with backend._conn.execute("EXPLAIN QUERY PLAN " + sql, ("user-a", 10)) as cursor:
            plans.extend(str(row[3]) for row in await cursor.fetchall())
    assert all("SEARCH" in plan and "user_id=?" in plan for plan in plans)
    await backend.close()
