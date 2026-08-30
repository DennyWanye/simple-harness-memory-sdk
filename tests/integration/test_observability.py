from __future__ import annotations

import json
import time

import pytest
from simple_harness import (
    AgentIdentity,
    CommittedTurn,
    MemoryRecallBounds,
    MemoryRecallRequest,
    MemoryReleaseRequest,
    MemoryScopeRef,
)
from simple_harness.observability import CorrelationContext, RecordingSink

from simple_harness_memory import MemoryManager, MemoryPrincipal, MemoryScope
from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.models import Fact
from simple_harness_memory.core.observability import MemoryObservability
from tests.fixtures.legacy_fact_jobs import LegacyFactJobWorker

IDENTITY = AgentIdentity("deployment-observe", "house-observe", "actor-observe", "session-observe")
CORRELATION = CorrelationContext(
    trace_id="a" * 64,
    root_id="b" * 64,
    operation_id="c" * 64,
)
CANARIES = (
    "PRIVATE_QUERY_CANARY",
    "PRIVATE_CONTENT_CANARY",
    "PRIVATE_RESPONSE_CANARY",
    "sk-secret-api-key-canary",
    "PRIVATE_EXCEPTION_CANARY",
)


def _recall(query_id: str = "query-observe") -> MemoryRecallRequest:
    return MemoryRecallRequest(
        query_id,
        f"turn-{query_id}",
        IDENTITY,
        (MemoryScopeRef.personal(IDENTITY.actor_id),),
        CANARIES[0],
        MemoryRecallBounds(10, 4096, 1.0),
        time.time(),
    )


def _turn(
    turn_id: str = "turn-observe",
    *,
    content: str = CANARIES[1],
    started_at: float | None = None,
) -> CommittedTurn:
    return CommittedTurn(
        turn_id,
        IDENTITY,
        content,
        CANARIES[2],
        MemoryScopeRef.personal(IDENTITY.actor_id),
        None,
        time.time() if started_at is None else started_at,
    )


class _FailingSink:
    def emit(self, event: object) -> None:
        del event
        raise RuntimeError(CANARIES[4])


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["mock", "sqlite"])
async def test_public_builders_and_direct_backends_accept_shared_observability(
    tmp_path, backend_kind
) -> None:
    sink = RecordingSink()
    backend = (
        MockMemoryBackend(observability_sink=sink, correlation=CORRELATION)
        if backend_kind == "mock"
        else SQLiteMemoryBackend(
            str(tmp_path / "direct.db"),
            observability_sink=sink,
            correlation=CORRELATION,
        )
    )
    manager = await MemoryManager.build(
        backend=backend,
        observability_sink=sink,
        correlation=CORRELATION,
    )
    result = await manager.recall_for_turn(_recall(f"query-{backend_kind}"))
    assert result.item_count == 0
    assert manager._observability.runtime.flush(1.0)
    assert sink.events()
    assert {event.correlation for event in sink.events()} == {CORRELATION}
    await manager.close()


@pytest.mark.asyncio
async def test_sink_failure_and_sensitive_canaries_never_change_business_result() -> None:
    manager = await MemoryManager.build(
        observability_sink=_FailingSink(), correlation=CORRELATION
    )
    recall = await manager.recall_for_turn(_recall())
    receipt = await manager.record_committed_turn(_turn())
    assert recall.item_count == 0
    assert receipt.status.value == "applied"
    assert manager._observability.runtime.flush(1.0)
    snapshot = await manager.diagnostics_snapshot()
    rendered = json.dumps(snapshot, sort_keys=True)
    assert snapshot["observability"]["counters"]["sink_errors"] > 0
    assert not any(canary in rendered for canary in CANARIES)
    await manager.close()


@pytest.mark.asyncio
async def test_status_matrix_snapshot_schema_bounds_and_privacy() -> None:
    sink = RecordingSink(capacity=128)
    manager = await MemoryManager.build(
        observability_sink=sink,
        correlation=CORRELATION,
    )
    request = _recall()
    first = await manager.recall_for_turn(request)
    replay = await manager.recall_for_turn(request)
    await manager.release_recall(
        MemoryReleaseRequest(
            first.query_id,
            first.query_hash,
            first.result_id,
            first.result_hash,
            first.write_fence,
        )
    )
    turn = _turn()
    applied = await manager.record_committed_turn(turn)
    repeated = await manager.record_committed_turn(turn)
    snapshot = await manager.diagnostics_snapshot()
    assert first.result_hash == replay.result_hash
    assert applied.status.value == "applied"
    assert repeated.status.value == "already_applied"
    assert snapshot["schema_version"] == 1
    assert snapshot["component"] == "memory"
    assert set(snapshot["storage"]["fact_jobs"]) == {
        "pending",
        "claimed",
        "applied",
        "dead_letter",
        "erased",
        "oldest_pending_age_ms",
        "recent_error_codes",
    }
    assert len(snapshot["storage"]["fact_jobs"]["recent_error_codes"]) <= 20
    assert manager._observability.runtime.flush(1.0)
    names = {event.event_name for event in sink.events()}
    assert {
        "memory.recall.accepted",
        "memory.recall.started",
        "memory.recall.replayed",
        "memory.recall.degraded",
        "memory.recall.succeeded",
        "memory.recall.released",
        "memory.committed_turn.applied",
        "memory.committed_turn.replayed",
    }.issubset(names)
    rendered = json.dumps([event.to_dict() for event in sink.events()], sort_keys=True)
    assert not any(canary in rendered for canary in CANARIES)
    await manager.close()


@pytest.mark.asyncio
async def test_committed_turn_rejected_erased_event() -> None:
    sink = RecordingSink()
    manager = await MemoryManager.build(
        observability_sink=sink, correlation=CORRELATION
    )
    principal = MemoryPrincipal(
        IDENTITY.deployment_id,
        IDENTITY.household_id,
        IDENTITY.actor_id,
        IDENTITY.session_id,
    )
    await manager.delete_scope(principal, (MemoryScope.personal(IDENTITY.actor_id),))
    receipt = await manager.record_committed_turn(
        _turn("turn-rejected", started_at=1.0)
    )
    assert receipt.status.value == "rejected_erased"
    assert manager._observability.runtime.flush(1.0)
    event = next(
        event
        for event in sink.events()
        if event.event_name == "memory.committed_turn.rejected"
    )
    assert event.attributes["error_code"] == "memory_rejected_erased"
    await manager.close()


class _Extractor:
    lineage = "test-extractor:1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def extract(self, content: str, **kwargs: object) -> list[Fact]:
        del content, kwargs
        if self.fail:
            raise RuntimeError(CANARIES[4])
        return []


class _WorkerBackend:
    def __init__(self, *, settle: str = "applied", fail_state: str = "pending") -> None:
        self.settle = settle
        self.fail_state = fail_state
        self.returned = False

    async def recover_fact_jobs(self) -> int:
        return 0

    async def claim_fact_job(self) -> dict[str, object] | None:
        if self.returned:
            return None
        self.returned = True
        return {
            "job_id": "job-status-matrix",
            "session_id": IDENTITY.session_id,
            "payload": CANARIES[1],
            "source_msg_id": 1,
            "created_at": time.time(),
            "actor_id": IDENTITY.actor_id,
            "attempts": 5 if self.fail_state == "dead_letter" else 1,
        }

    async def apply_fact_job(
        self, job: dict[str, object], facts: list[Fact], *, extractor_lineage: str
    ) -> str:
        del job, facts, extractor_lineage
        return self.settle

    async def fail_fact_job(self, job: dict[str, object], *, stable_code: str) -> str:
        del job, stable_code
        return self.fail_state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settle", "expected"),
    [("applied", "applied"), ("erased", "erased"), ("lost_lease", "lost_lease")],
)
async def test_fact_job_authoritative_settlement_matrix(settle: str, expected: str) -> None:
    sink = RecordingSink()
    observer = MemoryObservability(sink, CORRELATION)
    worker = LegacyFactJobWorker(_WorkerBackend(settle=settle), _Extractor(), observer)
    assert await worker.drain_once()
    assert observer.runtime.flush(1.0)
    names = {event.event_name for event in sink.events()}
    assert "memory.fact_job.claimed" in names
    assert f"memory.fact_job.{expected}" in names
    rendered = json.dumps([event.to_dict() for event in sink.events()], sort_keys=True)
    assert not any(canary in rendered for canary in CANARIES)
    observer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "dead_letter"])
async def test_fact_job_retry_and_dead_letter_matrix(state: str) -> None:
    sink = RecordingSink()
    observer = MemoryObservability(sink, CORRELATION)
    worker = LegacyFactJobWorker(
        _WorkerBackend(fail_state=state), _Extractor(fail=True), observer
    )
    assert await worker.drain_once()
    assert observer.runtime.flush(1.0)
    expected = "retrying" if state == "pending" else "dead_letter"
    assert any(event.event_name == f"memory.fact_job.{expected}" for event in sink.events())
    rendered = json.dumps([event.to_dict() for event in sink.events()], sort_keys=True)
    assert CANARIES[4] not in rendered
    observer.close()


@pytest.mark.asyncio
async def test_sqlite_snapshot_queries_never_select_sensitive_columns(tmp_path) -> None:
    backend = SQLiteMemoryBackend(str(tmp_path / "snapshot.db"))
    manager = await MemoryManager.build(backend=backend)
    statements: list[str] = []
    await backend._conn.set_trace_callback(statements.append)
    snapshot = await manager.diagnostics_snapshot()
    assert snapshot["health"] == "healthy"
    selects = [
        statement.lower()
        for statement in statements
        if statement.lstrip().lower().startswith("select")
    ]
    assert selects
    for statement in selects:
        assert not any(
            forbidden in statement
            for forbidden in ("content", "payload", "embedding", "result_payload", "user_text")
        )
    await manager.close()


@pytest.mark.asyncio
async def test_closed_snapshot_is_stable_and_bounded() -> None:
    manager = await MemoryManager.build()
    await manager.close()
    first = await manager.diagnostics_snapshot()
    second = await manager.diagnostics_snapshot()
    assert first == second
    assert first["health"] == "closed"
    assert len(json.dumps(first)) < 4096
