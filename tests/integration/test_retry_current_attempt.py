"""Real failed-then-retried batches: ownership, current attempt and crash atomicity."""
import asyncio
from dataclasses import replace

import pytest

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryWriterConflict
from tests.integration.test_memory_061_core import (
    WORKER_CONFIG, _build_pipeline, _evidence, _HostEvidenceAuthority, _HostExecutor, _ingest,
)


async def setup(path, *, clock, fault=None, members=1):
    authority = _HostEvidenceAuthority()
    executor = _HostExecutor((), no_mutation=True)
    manager, _ = await _build_pipeline(
        path, executor, evidence_authority=authority, now=lambda: clock[0], fault_injector=fault,
    )
    for index in range(1, members + 1):
        await _ingest(manager, _evidence(index), authority)
    config = replace(WORKER_CONFIG, batch_size=members)
    first = await manager.backend.claim_analysis_batch(config, "first")
    assert first is not None and len(first.job_ids) == members
    assert await manager.backend.fail_analysis_batch(first, "provider_failure", config) is m.WorkerRunOutcome.RETRY_SCHEDULED
    clock[0] += 20
    second = await manager.backend.claim_analysis_batch(config, "second")
    assert second is not None and second.batch_id != first.batch_id
    return manager, config, first, second


async def rows(manager, sql, params=()):
    async with manager.backend.connection.execute(sql, params) as cursor:
        return [tuple(r) for r in await cursor.fetchall()]


@pytest.mark.parametrize("reopen", [False, True])
async def test_real_retry_expiry_reclaims_current_not_failed_history(tmp_path, reopen):
    path, clock = tmp_path / "memory.db", [40.0]
    manager, config, first, second = await setup(path, clock=clock)
    try:
        history = await rows(manager, "SELECT * FROM job_attempts WHERE batch_id=?", (first.batch_id,))
        clock[0] = second.lease_expires_at + 1
        if reopen:
            await manager.close()
            manager = await m.build_human_memory_v7(path, clock=lambda: clock[0])
        current = await manager.backend.claim_analysis_batch(config, "reclaimer")
        assert current is not None
        assert current.batch_id == second.batch_id
        assert current.request == second.request and current.job_ids == second.job_ids
        assert current.lease_token != second.lease_token
        assert await rows(manager, "SELECT * FROM job_attempts WHERE batch_id=?", (first.batch_id,)) == history
        assert await manager.backend.fail_analysis_batch(second, "stale_owner", config) is m.WorkerRunOutcome.STALE_LEASE
        assert await manager.backend.fail_analysis_batch(current, "actual_owner", config) is m.WorkerRunOutcome.DEAD_LETTER
    finally:
        await manager.close()


async def test_concurrent_workers_and_second_manager_cannot_steal_current_lease(tmp_path):
    path, clock = tmp_path / "memory.db", [40.0]
    manager, config, _, second = await setup(path, clock=clock)
    try:
        with pytest.raises(MemoryWriterConflict):
            await m.build_human_memory_v7(path, clock=lambda: clock[0])
        clock[0] = second.lease_expires_at + 1
        results = await asyncio.gather(*(
            manager.backend.claim_analysis_batch(config, owner) for owner in ("race1", "race2")
        ))
        winners = [c for c in results if c is not None]
        assert len(winners) == 1 and winners[0].batch_id == second.batch_id
        assert await rows(manager, "SELECT COUNT(*) FROM job_attempt_events WHERE event_kind='reclaimed'") == [(1,)]
    finally:
        await manager.close()


@pytest.mark.parametrize("damage", ["live_member", "attempt", "request"])
async def test_all_members_must_match_current_expired_attempt_before_rotation(tmp_path, damage):
    path, clock = tmp_path / "memory.db", [40.0]
    manager, config, _, second = await setup(path, clock=clock, members=2)
    try:
        clock[0] = second.lease_expires_at + 1
        db = manager.backend.connection
        if damage == "live_member":
            await db.execute("UPDATE jobs SET lease_expires_at=? WHERE job_id=?", (clock[0] + 100, second.job_ids[0]))
        elif damage == "attempt":
            await db.execute("UPDATE jobs SET attempt_count=attempt_count+1 WHERE job_id=?", (second.job_ids[0],))
        else:
            await db.execute("UPDATE job_attempts SET request_hash=? WHERE batch_id=? AND job_id=?", ("b" * 64, second.batch_id, second.job_ids[0]))
        await db.commit()
        before = await rows(manager, "SELECT lease_token FROM jobs ORDER BY job_id")
        assert await manager.backend.claim_analysis_batch(config, "cannot_partially_claim") is None
        assert await rows(manager, "SELECT lease_token FROM jobs ORDER BY job_id") == before
        assert await rows(manager, "SELECT COUNT(*) FROM job_attempt_events WHERE event_kind='reclaimed'") == [(0,)]
    finally:
        await manager.close()
