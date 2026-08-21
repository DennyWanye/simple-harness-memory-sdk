import time

import pytest

from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend


@pytest.mark.asyncio
async def test_cleanup_expires_released_and_unreleased_results_but_keeps_active_horizon(
    tmp_path,
):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    await backend.initialize()
    query_ids = (
        "expired-retained",
        "active-retained",
        "expired-released",
        "other-user-retained",
    )
    results = {}
    for query_id in query_ids:
        user_id = "user-b" if query_id == "other-user-retained" else "user-a"
        results[query_id] = await backend.recall_bounded(
            "query",
            user_id=user_id,
            session_id=f"session-{user_id}",
            context_query_id=query_id,
        )
    await backend.release_recall_result(
        user_id="user-a",
        context_query_id="expired-released",
        result_hash=results["expired-released"].result_hash,
    )

    future = time.time() + 365 * 86400
    expired = future - 8 * 86400
    active = future - 1 * 86400
    await backend._conn.execute(
        "UPDATE recall_result_snapshots SET created_at = ? "
        "WHERE context_query_id IN ('expired-retained', 'other-user-retained')",
        (expired,),
    )
    await backend._conn.execute(
        "UPDATE recall_result_snapshots SET created_at = ? "
        "WHERE context_query_id = 'active-retained'",
        (active,),
    )
    await backend._conn.execute(
        "UPDATE recall_result_snapshots SET released_at = ? "
        "WHERE context_query_id = 'expired-released'",
        (expired,),
    )

    assert await backend.cleanup_recall_results(
        user_id="user-a", now=future, limit=1
    ) == 1
    assert await backend.cleanup_recall_results(
        user_id="user-a", now=future, limit=1
    ) == 1
    assert await backend.cleanup_recall_results(
        user_id="user-a", now=future, limit=1
    ) == 0
    async with backend._conn.execute(
        "SELECT context_query_id, user_id FROM recall_result_snapshots "
        "ORDER BY context_query_id"
    ) as cursor:
        assert [tuple(row) for row in await cursor.fetchall()] == [
            ("active-retained", "user-a"),
            ("other-user-retained", "user-b"),
        ]
    await backend.close()


@pytest.mark.asyncio
async def test_mock_cleanup_also_expires_unreleased_result() -> None:
    backend = MockMemoryBackend()
    await backend.recall_bounded(
        "query",
        user_id="user-1",
        session_id="session-1",
        context_query_id="expired-retained",
    )
    future = time.time() + 365 * 86400
    backend._recall_snapshots["expired-retained"]["created_at"] = future - 8 * 86400
    assert await backend.cleanup_recall_results(
        user_id="user-1", now=future, limit=1
    ) == 1
