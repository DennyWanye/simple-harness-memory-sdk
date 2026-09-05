"""Actual retry/application events and as-of crosslinks; corrupt only disposable fixtures."""

import hashlib
from contextlib import suppress

import pytest
from simple_harness.contracts import canonical_json

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryCorruptionError
from tests.integration.test_audit_access_v6 import _AuditAccessAuthority, _grant, _principal
from tests.integration.test_memory_061_core import (
    WORKER_CONFIG,
    _build_pipeline,
    _evidence,
    _HostEvidenceAuthority,
    _HostExecutor,
    _ingest,
)
from tests.integration.test_operation_audit import _read, _suppress


async def setup(tmp_path, *, run=True, clock=None):
    audit, authority = _AuditAccessAuthority(), _HostEvidenceAuthority()
    executor = _HostExecutor((), no_mutation=True)
    now = clock or [40.0]
    manager, runner = await _build_pipeline(
        tmp_path / "memory.db",
        executor,
        evidence_authority=authority,
        audit_access_authority=audit,
        now=lambda: now[0],
    )
    try:
        await _ingest(manager, _evidence(1), authority)
        _, ref = _grant(audit, max_reads=32, expires_at=400)
        receipt = await manager.authorize_audit_access(principal=_principal(), authority_ref=ref)
        if run:
            assert await runner.run_once() is m.WorkerRunOutcome.APPLIED
        return manager, receipt, audit, now
    except BaseException:
        await manager.close()
        raise


@pytest.mark.parametrize(
    "kind",
    ["provider_handoff", "result_committed", "application_staged", "mutation_audit_committed"],
)
async def test_actual_applied_missing_predecessor_cannot_claim_complete(tmp_path, kind):
    manager, receipt, _, _ = await setup(tmp_path)
    try:
        db = manager.backend.connection
        await db.execute("DROP TRIGGER job_attempt_events_immutable_delete")
        await db.execute("DELETE FROM job_attempt_events WHERE event_kind=?", (kind,))
        await db.commit()
        page = await _read(manager, _principal(), receipt)
        coverage = next(c for c in page.coverage if c.family == "job_transition")
        assert coverage.missing_event_ref_hashes
        assert not page.all_operations_recorded
    finally:
        await manager.close()


async def test_recomputed_event_hash_cannot_rebind_result_to_foreign_batch(tmp_path):
    manager, receipt, _, _ = await setup(tmp_path)
    try:
        db = manager.backend.connection
        async with db.execute("SELECT * FROM job_attempt_events WHERE event_kind='applied'") as c:
            row = dict(await c.fetchone())
        row["result_hash"] = "b" * 64
        payload = {"schema_version": 1, **{k: v for k, v in row.items() if k != "event_hash"}}
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        await db.execute("DROP TRIGGER job_attempt_events_immutable_update")
        await db.execute(
            "UPDATE job_attempt_events SET result_hash=?,event_hash=? WHERE event_id=?",
            (row["result_hash"], digest, row["event_id"]),
        )
        await db.commit()
        with pytest.raises(MemoryCorruptionError, match="result"):
            await _read(manager, _principal(), receipt)
    finally:
        with suppress(MemoryCorruptionError):
            await manager.close()


async def test_actual_retry_and_reclaim_keep_old_cursor_and_actual_attempts(tmp_path):
    manager, receipt, audit, clock = await setup(tmp_path, run=False)
    p = _principal()
    try:
        await _suppress(manager, p, "first")
        await _suppress(manager, p, "second")
        first = await manager.backend.claim_analysis_batch(WORKER_CONFIG, "worker1")
        assert first is not None
        old = await _read(manager, p, receipt, limit=1)
        old_job = next(c for c in old.coverage if c.family == "job_transition")
        assert old_job.row_count == 1 and old_job.unresolved_ref_hashes
        # A legitimate lease reclaim of THIS current handoff precedes retry.
        clock[0] = first.lease_expires_at + 1
        reclaimed = await manager.backend.claim_analysis_batch(WORKER_CONFIG, "reclaimer")
        assert reclaimed is not None and reclaimed.batch_id == first.batch_id
        assert reclaimed.lease_token != first.lease_token
        first = reclaimed
        # Real failed attempt followed by actual scheduled retry, not fabricated events.
        assert (
            await manager.backend.fail_analysis_batch(
                first, "actual_provider_failure", WORKER_CONFIG
            )
            is m.WorkerRunOutcome.RETRY_SCHEDULED
        )
        clock[0] += 20
        second = await manager.backend.claim_analysis_batch(WORKER_CONFIG, "worker2")
        assert second is not None and second.batch_id != first.batch_id
        pinned = await _read(manager, p, receipt, limit=1, cursor=old.next_cursor)
        assert pinned.snapshot_hash == old.snapshot_hash and pinned.coverage == old.coverage
        await manager.close()
        manager = await m.build_human_memory_v7(
            tmp_path / "memory.db", clock=lambda: clock[0], audit_access_authority=audit
        )
        reopened = await _read(manager, p, receipt, limit=1, cursor=old.next_cursor)
        assert reopened.to_json() == pinned.to_json()
        fresh = await _read(manager, p, receipt)
        events = [i for i in fresh.items if i.family == "job_transition"]
        assert [i.event_kind for i in events] == [
            "provider_handoff",
            "reclaimed",
            "retry_scheduled",
            "provider_handoff",
        ]
        assert len({i.attempt_ref_hash for i in events}) == 2
        coverage = next(c for c in fresh.coverage if c.family == "job_transition")
        assert len(coverage.unresolved_ref_hashes) == 1 and not coverage.missing_event_ref_hashes
    finally:
        await manager.close()
