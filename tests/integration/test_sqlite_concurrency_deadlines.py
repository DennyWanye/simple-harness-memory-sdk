import asyncio
import sqlite3
import time

import pytest

from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.conversation import (
    ConversationMemoryAdapter,
    ConversationMemoryError,
    ConversationMemoryErrorCode,
    ConversationMemoryRecallQuery,
)
from simple_harness_memory.core.errors import MemoryIdempotencyConflict


@pytest.mark.asyncio
async def test_concurrent_recall_waits_for_rollback_then_commits_its_own_snapshot(
    tmp_path,
):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    statements: list[str] = []
    await backend._conn.set_trace_callback(statements.append)
    outer_started = asyncio.Event()
    release_outer = asyncio.Event()

    async def rollback_outer() -> None:
        with pytest.raises(RuntimeError, match="rollback outer"):
            async with backend._transaction():
                await backend._ensure_session_impl("outer-user", "outer-session")
                outer_started.set()
                await release_outer.wait()
                raise RuntimeError("rollback outer")

    outer = asyncio.create_task(rollback_outer())
    await outer_started.wait()
    inner = asyncio.create_task(
        backend.recall_bounded(
            "query",
            user_id="inner-user",
            session_id="inner-session",
            context_query_id="inner-query",
            timeout_seconds=1.0,
        )
    )
    await asyncio.sleep(0.02)
    assert not inner.done()

    release_outer.set()
    await outer
    result = await inner
    assert not result.replayed
    async with backend._conn.execute(
        "SELECT context_query_id FROM recall_result_snapshots"
    ) as cursor:
        assert [row[0] for row in await cursor.fetchall()] == ["inner-query"]
    async with backend._conn.execute(
        "SELECT session_id FROM sessions ORDER BY session_id"
    ) as cursor:
        assert [row[0] for row in await cursor.fetchall()] == ["inner-session"]
    transactions = [
        statement
        for statement in statements
        if statement in {"BEGIN IMMEDIATE", "ROLLBACK", "COMMIT"}
    ]
    assert transactions == ["BEGIN IMMEDIATE", "ROLLBACK", "BEGIN IMMEDIATE", "COMMIT"]
    await backend.close()


@pytest.mark.asyncio
async def test_concurrent_same_and_conflicting_query_ids_are_serialized(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()

    async def recall(query: str, context_query_id: str):
        return await backend.recall_bounded(
            query,
            user_id="user-1",
            session_id="session-1",
            context_query_id=context_query_id,
            timeout_seconds=1.0,
        )

    same = await asyncio.gather(recall("same", "same-id"), recall("same", "same-id"))
    assert {result.replayed for result in same} == {False, True}
    assert same[0].result_hash == same[1].result_hash

    different = await asyncio.gather(
        recall("first", "conflict-id"),
        recall("second", "conflict-id"),
        return_exceptions=True,
    )
    assert sum(not isinstance(value, BaseException) for value in different) == 1
    assert sum(isinstance(value, MemoryIdempotencyConflict) for value in different) == 1
    await backend.close()


@pytest.mark.asyncio
async def test_mock_concurrent_same_query_id_replays_instead_of_conflicting(
    monkeypatch,
):
    backend = MockMemoryBackend()
    original_compute = backend._compute_recall
    active = 0
    max_active = 0

    async def observed_compute(*args, **kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.01)
            return await original_compute(*args, **kwargs)
        finally:
            active -= 1

    monkeypatch.setattr(backend, "_compute_recall", observed_compute)

    async def recall():
        return await backend.recall_bounded(
            "same",
            user_id="user-1",
            session_id="session-1",
            context_query_id="same-id",
            timeout_seconds=1.0,
        )

    results = await asyncio.gather(recall(), recall())
    assert max_active == 1
    assert {result.replayed for result in results} == {False, True}
    assert results[0].result_hash == results[1].result_hash


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_poison_transaction_or_close(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    outer_started = asyncio.Event()
    release_outer = asyncio.Event()

    async def hold_outer() -> None:
        async with backend._transaction():
            outer_started.set()
            await release_outer.wait()

    outer = asyncio.create_task(hold_outer())
    await outer_started.wait()
    waiter = asyncio.create_task(
        backend.recall_bounded(
            "cancel",
            user_id="user-1",
            session_id="session-1",
            context_query_id="cancelled-query",
            timeout_seconds=1.0,
        )
    )
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    close_task = asyncio.create_task(backend.close())
    await asyncio.sleep(0.02)
    assert not close_task.done()
    release_outer.set()
    await outer
    await close_task
    assert backend._db is None


@pytest.mark.asyncio
async def test_external_sqlite_lock_maps_to_bounded_stable_timeout(tmp_path):
    path = tmp_path / "memory.db"
    backend = SQLiteMemoryBackend(str(path))
    await backend.initialize()
    locker = sqlite3.connect(path, isolation_level=None)
    locker.execute("BEGIN IMMEDIATE")
    query = ConversationMemoryRecallQuery.create(
        context_query_id="locked-query",
        user_id="user-1",
        session_id="session-1",
        query_text="query",
        max_items=2,
        max_bytes=1024,
        timeout_seconds=0.01,
    )
    adapter = ConversationMemoryAdapter(backend, close_backend=False)
    started = time.monotonic()
    try:
        with pytest.raises(ConversationMemoryError) as error:
            await adapter.recall_bounded(query)
        assert error.value.code is ConversationMemoryErrorCode.TIMEOUT
        assert time.monotonic() - started < 0.25
    finally:
        locker.execute("ROLLBACK")
        locker.close()

    retry = await adapter.recall_bounded(query)
    assert retry.context_query_id == "locked-query"
    async with backend._conn.execute(
        "SELECT count(*) FROM recall_result_snapshots "
        "WHERE context_query_id = 'locked-query'"
    ) as cursor:
        assert (await cursor.fetchone())[0] == 1
    await backend.close()


@pytest.mark.asyncio
async def test_overall_deadline_includes_wait_for_backend_operation_lock(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    outer_started = asyncio.Event()
    release_outer = asyncio.Event()

    async def hold_outer() -> None:
        async with backend._transaction():
            outer_started.set()
            await release_outer.wait()

    outer = asyncio.create_task(hold_outer())
    await outer_started.wait()
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="memory recall deadline exceeded"):
        await backend.recall_bounded(
            "query",
            user_id="user-1",
            session_id="session-1",
            context_query_id="lock-wait-query",
            timeout_seconds=0.01,
        )
    assert time.monotonic() - started < 0.25
    release_outer.set()
    await outer
    result = await backend.recall_bounded(
        "query",
        user_id="user-1",
        session_id="session-1",
        context_query_id="lock-wait-query",
        timeout_seconds=1.0,
    )
    assert not result.replayed
    await backend.close()


@pytest.mark.asyncio
async def test_deadline_covers_durable_snapshot_insert_and_rollback(tmp_path, monkeypatch):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    original_insert = backend._insert_recall_snapshot_impl

    async def slow_insert(**kwargs) -> None:
        await asyncio.sleep(0.05)
        await original_insert(**kwargs)

    monkeypatch.setattr(backend, "_insert_recall_snapshot_impl", slow_insert)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="memory recall deadline exceeded"):
        await backend.recall_bounded(
            "query",
            user_id="user-1",
            session_id="session-1",
            context_query_id="slow-commit-query",
            timeout_seconds=0.01,
        )
    assert time.monotonic() - started < 0.25
    async with backend._conn.execute(
        "SELECT count(*) FROM recall_result_snapshots"
    ) as cursor:
        assert (await cursor.fetchone())[0] == 0
    await backend.close()
