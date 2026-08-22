from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

import pytest
from simple_harness import (
    AgentIdentity,
    AgentMemoryError,
    AgentMemoryErrorCode,
    AgentMemoryPort,
    CommittedTurn,
    CommittedTurnStatus,
    MemoryRecallBounds,
    MemoryRecallRequest,
    MemoryReleaseRequest,
    MemoryScopeRef,
)

from simple_harness_memory import (
    MemoryManager,
    MemoryOwnershipConflict,
    MemoryPrincipal,
    MemoryScope,
)
from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.embedders.mock import HashEmbedder

IDENTITY = AgentIdentity("deployment-a", "house-a", "actor-a", "session-a")
SCOPES = (MemoryScopeRef.personal("actor-a"), MemoryScopeRef.family("house-a"))


def recall_request(
    identity: AgentIdentity = IDENTITY,
    *,
    query_id: str = "query-1",
    deadline_seconds: float = 1.0,
):
    return MemoryRecallRequest(
        query_id,
        f"turn-{query_id}",
        identity,
        (
            MemoryScopeRef.personal(identity.actor_id),
            MemoryScopeRef.family(identity.household_id),
        ),
        "Max",
        MemoryRecallBounds(20, 16_384, deadline_seconds),
        time.time(),
    )


class _CoordinatedEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def embed(self, text: str) -> list[float]:
        self.started.set()
        await self.release.wait()
        return await super().embed(text)


def committed_turn(
    turn_id: str,
    *,
    identity: AgentIdentity = IDENTITY,
    fence: str | None,
    started_at: float | None = None,
    user_text: str = "我养了一只叫Max的狗，很喜欢吃披萨",
) -> CommittedTurn:
    return CommittedTurn(
        turn_id,
        identity,
        user_text,
        "好的，我记住了。",
        MemoryScopeRef.personal(identity.actor_id),
        fence,
        time.time() if started_at is None else started_at,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["mock", "sqlite"])
async def test_direct_port_committed_pair_recall_release_and_conflict(tmp_path, backend_kind):
    backend = (
        MockMemoryBackend()
        if backend_kind == "mock"
        else SQLiteMemoryBackend(str(tmp_path / "memory.db"))
    )
    manager = await MemoryManager.build(backend=backend)
    typed: AgentMemoryPort = manager

    empty = await typed.recall_for_turn(recall_request())
    assert empty.item_count == 0
    turn = committed_turn("turn-1", fence=empty.write_fence)
    first = await typed.record_committed_turn(turn)
    replay = await typed.record_committed_turn(turn)
    assert first.status is CommittedTurnStatus.APPLIED
    assert replay.status is CommittedTurnStatus.ALREADY_APPLIED
    assert first.receipt_id == replay.receipt_id

    with pytest.raises(AgentMemoryError) as conflict:
        await typed.record_committed_turn(
            committed_turn("turn-1", fence=empty.write_fence, user_text="different")
        )
    assert conflict.value.code is AgentMemoryErrorCode.CONFLICT

    recalled = await typed.recall_for_turn(recall_request(query_id="query-2"))
    assert recalled.item_count == 2
    items = recalled.payload["items"]
    assert isinstance(items, (list, tuple))
    for item in items:
        assert isinstance(item, Mapping)
        scope = item["scope"]
        assert isinstance(scope, Mapping)
        assert scope["owner_id"] == "actor-a"
    await typed.release_recall(
        MemoryReleaseRequest(
            recalled.query_id,
            recalled.query_hash,
            recalled.result_id,
            recalled.result_hash,
            recalled.write_fence,
        )
    )
    await manager.close()


@pytest.mark.asyncio
async def test_sqlite_pair_receipt_and_job_are_atomic_and_worker_applies(tmp_path):
    manager = await MemoryManager.build(
        backend=SQLiteMemoryBackend(str(tmp_path / "memory.db"), auto_extract_facts=True),
        enable_facts=True,
    )
    recall = await manager.recall_for_turn(recall_request())
    receipt = await manager.record_committed_turn(
        committed_turn("turn-facts", fence=recall.write_fence)
    )
    assert receipt.status is CommittedTurnStatus.APPLIED
    await manager.drain_fact_jobs()
    async with manager.backend._conn.execute(
        "SELECT (SELECT COUNT(*) FROM messages), (SELECT COUNT(*) FROM turn_receipts), "
        "(SELECT COUNT(*) FROM fact_jobs WHERE state='applied'), "
        "(SELECT COUNT(*) FROM facts)"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert tuple(row) == (2, 1, 1, 2)
    await manager.close()


@pytest.mark.asyncio
async def test_session_rebind_fails_before_read(tmp_path):
    manager = await MemoryManager.build(db_path=str(tmp_path / "memory.db"))
    await manager.recall_for_turn(recall_request())
    forged = AgentIdentity("deployment-a", "house-a", "actor-b", "session-a")
    with pytest.raises(AgentMemoryError) as error:
        await manager.recall_for_turn(recall_request(forged, query_id="forged"))
    assert error.value.code is AgentMemoryErrorCode.PERMANENT
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["mock", "sqlite"])
async def test_same_session_and_turn_ids_are_isolated_by_deployment(tmp_path, backend_kind):
    backend = (
        MockMemoryBackend()
        if backend_kind == "mock"
        else SQLiteMemoryBackend(str(tmp_path / "deployment.db"))
    )
    manager = await MemoryManager.build(backend=backend)
    first_identity = AgentIdentity("deployment-a", "house-a", "actor-a", "shared-session")
    second_identity = AgentIdentity("deployment-b", "house-b", "actor-b", "shared-session")
    first_recall = await manager.recall_for_turn(
        recall_request(first_identity, query_id="deployment-a-query")
    )
    second_recall = await manager.recall_for_turn(
        recall_request(second_identity, query_id="deployment-b-query")
    )
    first = await manager.record_committed_turn(
        committed_turn("shared-turn", identity=first_identity, fence=first_recall.write_fence)
    )
    second = await manager.record_committed_turn(
        committed_turn("shared-turn", identity=second_identity, fence=second_recall.write_fence)
    )
    assert first.status is CommittedTurnStatus.APPLIED
    assert second.status is CommittedTurnStatus.APPLIED
    if isinstance(backend, SQLiteMemoryBackend):
        async with backend._conn.execute(
            "SELECT (SELECT COUNT(*) FROM sessions WHERE session_id='shared-session'), "
            "(SELECT COUNT(*) FROM turn_receipts WHERE turn_id='shared-turn'), "
            "(SELECT COUNT(*) FROM messages)"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None and tuple(row) == (2, 2, 4)
    else:
        assert len(backend._agent_bindings) == 2
        assert len(backend._turn_receipts) == 2

    conflicting_identity = AgentIdentity(
        "deployment-a", "house-a", "actor-a", "different-session"
    )
    conflicting_recall = await manager.recall_for_turn(
        recall_request(conflicting_identity, query_id="same-deployment-query")
    )
    with pytest.raises(AgentMemoryError) as conflict:
        await manager.record_committed_turn(
            committed_turn(
                "shared-turn",
                identity=conflicting_identity,
                fence=conflicting_recall.write_fence,
            )
        )
    assert conflict.value.code is AgentMemoryErrorCode.CONFLICT

    first_principal = MemoryPrincipal(
        first_identity.deployment_id,
        first_identity.household_id,
        first_identity.actor_id,
        first_identity.session_id,
    )
    second_principal = MemoryPrincipal(
        second_identity.deployment_id,
        second_identity.household_id,
        second_identity.actor_id,
        second_identity.session_id,
    )
    assert len((await manager.export_principal(first_principal)).records) == 2
    assert len((await manager.export_principal(second_principal)).records) == 2
    deleted = await manager.delete_scope(
        first_principal, (MemoryScope.personal(first_identity.actor_id),)
    )
    assert deleted.deleted_messages == 2
    assert len((await manager.export_principal(first_principal)).records) == 0
    assert len((await manager.export_principal(second_principal)).records) == 2
    second_after_delete = await manager.recall_for_turn(
        recall_request(second_identity, query_id="deployment-b-after-delete")
    )
    assert second_after_delete.item_count == 2
    await manager.close()


@pytest.mark.asyncio
async def test_erasure_fence_blocks_old_turn_and_allows_new_degraded_turn(tmp_path):
    manager = await MemoryManager.build(db_path=str(tmp_path / "memory.db"))
    old_started = time.time()
    recall = await manager.recall_for_turn(recall_request())
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    await asyncio.sleep(0.01)
    await manager.delete_scope(principal, (MemoryScope.personal("actor-a"),))

    stale = await manager.record_committed_turn(
        committed_turn("stale-fence", fence=recall.write_fence)
    )
    pre_delete = await manager.record_committed_turn(
        committed_turn("old-no-fence", fence=None, started_at=old_started)
    )
    new_degraded = await manager.record_committed_turn(
        committed_turn("new-no-fence", fence=None, started_at=time.time())
    )
    boundary = await manager.record_committed_turn(
        committed_turn("boundary", fence=None, started_at=old_started)
    )
    assert stale.status is CommittedTurnStatus.REJECTED_ERASED
    assert pre_delete.status is CommittedTurnStatus.REJECTED_ERASED
    assert boundary.status is CommittedTurnStatus.REJECTED_ERASED
    assert new_degraded.status is CommittedTurnStatus.APPLIED
    await manager.close()


@pytest.mark.asyncio
async def test_embedding_timeout_retains_fence_and_delete_rejects_degraded_turn(tmp_path):
    embedder = _CoordinatedEmbedder()
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"), embedder=embedder)
    manager = await MemoryManager.build(backend=backend)

    with pytest.raises(AgentMemoryError) as error:
        await manager.recall_for_turn(
            recall_request(query_id="timeout", deadline_seconds=0.01)
        )
    assert error.value.code is AgentMemoryErrorCode.TIMEOUT
    assert error.value.write_fence is not None

    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    await manager.delete_scope(principal, (MemoryScope.personal("actor-a"),))
    rejected = await manager.record_committed_turn(
        committed_turn("timeout-stale", fence=error.value.write_fence)
    )
    assert rejected.status is CommittedTurnStatus.REJECTED_ERASED
    await manager.close()


@pytest.mark.asyncio
async def test_delete_can_cross_embedding_boundary_and_stale_fence_is_rejected(tmp_path):
    backend = SQLiteMemoryBackend(str(tmp_path / "memory.db"), embedder=HashEmbedder())
    manager = await MemoryManager.build(backend=backend)
    initial = await manager.recall_for_turn(recall_request(query_id="seed"))
    await manager.record_committed_turn(
        committed_turn("seed-turn", fence=initial.write_fence)
    )

    embedder = _CoordinatedEmbedder()
    backend._embedder = embedder
    pending = asyncio.create_task(
        manager.recall_for_turn(recall_request(query_id="delete-boundary"))
    )
    await asyncio.wait_for(embedder.started.wait(), timeout=1.0)
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    await manager.delete_scope(principal, (MemoryScope.personal("actor-a"),))
    embedder.release.set()
    recalled = await asyncio.wait_for(pending, timeout=1.0)

    assert recalled.item_count == 0
    stale = await manager.record_committed_turn(
        committed_turn("boundary-stale", fence=recalled.write_fence)
    )
    assert stale.status is CommittedTurnStatus.REJECTED_ERASED
    await manager.close()


@pytest.mark.asyncio
async def test_personal_family_and_cross_household_isolation(tmp_path):
    manager = await MemoryManager.build(
        backend=SQLiteMemoryBackend(str(tmp_path / "memory.db"), auto_extract_facts=True),
        enable_facts=True,
    )
    a_recall = await manager.recall_for_turn(recall_request())
    await manager.record_committed_turn(committed_turn("scope-turn", fence=a_recall.write_fence))
    await manager.drain_fact_jobs()
    async with manager.backend._conn.execute("SELECT id FROM facts ORDER BY id LIMIT 1") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    await manager.share_fact(
        MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a"), int(row[0])
    )

    actor_b = AgentIdentity("deployment-a", "house-a", "actor-b", "session-b")
    house_b = AgentIdentity("deployment-b", "house-b", "actor-c", "session-c")
    b_result = await manager.recall_for_turn(recall_request(actor_b, query_id="actor-b"))
    other_result = await manager.recall_for_turn(recall_request(house_b, query_id="house-b"))
    assert any(item["scope"]["kind"] == "family" for item in b_result.payload["items"])
    assert not any(item["scope"]["kind"] == "personal" for item in b_result.payload["items"])
    assert other_result.item_count == 0
    await manager.close()


@pytest.mark.asyncio
async def test_export_delete_and_late_fact_job_do_not_resurrect(tmp_path):
    manager = await MemoryManager.build(
        backend=SQLiteMemoryBackend(str(tmp_path / "memory.db"), auto_extract_facts=True),
        enable_facts=True,
    )
    recall = await manager.recall_for_turn(recall_request())
    await manager.record_committed_turn(committed_turn("privacy-turn", fence=recall.write_fence))
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    exported = await manager.export_principal(principal)
    assert len(exported.records) >= 2
    assert all("embedding" not in record for record in exported.records)
    receipt = await manager.delete_scope(principal, (MemoryScope.personal("actor-a"),))
    assert receipt.deleted_messages == 2
    await manager.drain_fact_jobs()
    async with manager.backend._conn.execute(
        "SELECT (SELECT COUNT(*) FROM messages), (SELECT COUNT(*) FROM facts), "
        "(SELECT COUNT(*) FROM fact_tombstones)"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and tuple(row) == (0, 0, 1)
    await manager.close()


@pytest.mark.asyncio
async def test_committed_turn_fault_rolls_back_receipt_pair_and_job(tmp_path):
    manager = await MemoryManager.build(
        backend=SQLiteMemoryBackend(str(tmp_path / "memory.db"), auto_extract_facts=True)
    )
    recall = await manager.recall_for_turn(recall_request())
    await manager.backend._conn.execute(
        "CREATE TRIGGER fail_fact_job BEFORE INSERT ON fact_jobs "
        "BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )
    with pytest.raises(AgentMemoryError):
        await manager.record_committed_turn(
            committed_turn("atomic-fault", fence=recall.write_fence)
        )
    async with manager.backend._conn.execute(
        "SELECT (SELECT COUNT(*) FROM turn_receipts), "
        "(SELECT COUNT(*) FROM messages), (SELECT COUNT(*) FROM fact_jobs)"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and tuple(row) == (0, 0, 0)
    await manager.close()


@pytest.mark.asyncio
async def test_fact_claim_recovered_after_restart(tmp_path):
    path = str(tmp_path / "memory.db")
    backend = SQLiteMemoryBackend(path, auto_extract_facts=True)
    manager = await MemoryManager.build(backend=backend)
    recall = await manager.recall_for_turn(recall_request())
    await manager.record_committed_turn(committed_turn("restart-job", fence=recall.write_fence))
    claimed = await backend.claim_fact_job()
    assert claimed is not None
    await backend._conn.execute(
        "UPDATE fact_jobs SET lease_until = 0 WHERE job_id = ?", (claimed["job_id"],)
    )
    await manager.close()

    reopened = await MemoryManager.build(
        backend=SQLiteMemoryBackend(path, auto_extract_facts=True), enable_facts=True
    )
    await reopened.drain_fact_jobs()
    async with reopened.backend._conn.execute(
        "SELECT state, payload, attempts FROM fact_jobs"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] == "applied" and row[1] is None and row[2] == 2
    await reopened.close()


@pytest.mark.asyncio
async def test_forget_fact_removes_family_projection_and_leaves_tombstone(tmp_path):
    manager = await MemoryManager.build(
        backend=SQLiteMemoryBackend(str(tmp_path / "memory.db"), auto_extract_facts=True),
        enable_facts=True,
    )
    recall = await manager.recall_for_turn(recall_request())
    await manager.record_committed_turn(committed_turn("forget-turn", fence=recall.write_fence))
    await manager.drain_fact_jobs()
    async with manager.backend._conn.execute("SELECT id FROM facts ORDER BY id LIMIT 1") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    fact_id = int(row[0])
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    await manager.share_fact(principal, fact_id)
    assert await manager.forget_fact(fact_id, principal=principal)
    async with manager.backend._conn.execute(
        "SELECT (SELECT COUNT(*) FROM facts), (SELECT COUNT(*) FROM fact_tombstones)"
    ) as cursor:
        counts = await cursor.fetchone()
    assert counts is not None and tuple(counts) == (1, 1)
    # The second extracted fact remains; the personal fact and its family projection are gone.
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_kind", ["mock", "sqlite"])
async def test_public_share_is_idempotent_owned_and_forget_cascades(tmp_path, backend_kind):
    backend = (
        MockMemoryBackend(auto_extract_facts=True)
        if backend_kind == "mock"
        else SQLiteMemoryBackend(str(tmp_path / "share.db"), auto_extract_facts=True)
    )
    manager = await MemoryManager.build(backend=backend, enable_facts=True)
    recall = await manager.recall_for_turn(recall_request(query_id=f"share-{backend_kind}"))
    await manager.record_committed_turn(
        committed_turn(f"share-{backend_kind}", fence=recall.write_fence)
    )
    await manager.drain_fact_jobs()
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")

    if isinstance(backend, SQLiteMemoryBackend):
        async with backend._conn.execute(
            "SELECT id, deterministic_id FROM facts WHERE scope_kind='personal' "
            "ORDER BY id LIMIT 1"
        ) as cursor:
            source_row = await cursor.fetchone()
        assert source_row is not None
        fact_id, origin = int(source_row[0]), str(source_row[1])
        async with backend._conn.execute("SELECT job_id FROM fact_jobs LIMIT 1") as cursor:
            job_row = await cursor.fetchone()
        assert job_row is not None
        late_job: dict[str, object] = {"job_id": str(job_row[0])}
        late_facts = []
    else:
        fact_id, meta = next(
            (fact_id, meta)
            for fact_id, meta in backend._agent_fact_meta.items()
            if meta[3:5] == ("personal", "actor-a")
        )
        origin = meta[5]
        late_job = dict(next(iter(backend._fact_jobs.values())))
        source = next(fact for fact in backend._facts if fact.id == fact_id)
        late_facts = [source]

    first = await manager.share_fact(principal, fact_id)
    assert await manager.share_fact(principal, fact_id) == first
    for unauthorized in (
        MemoryPrincipal("deployment-a", "house-a", "actor-b", "session-b"),
        MemoryPrincipal("deployment-a", "house-b", "actor-a", "session-b"),
    ):
        with pytest.raises(MemoryOwnershipConflict) as error:
            await manager.share_fact(unauthorized, fact_id)
        assert error.value.code == "memory_ownership_conflict"

    if isinstance(backend, SQLiteMemoryBackend):
        async with backend._conn.execute(
            "SELECT COUNT(*), MIN(projection_of), MIN(scope_kind), MIN(scope_owner) "
            "FROM facts WHERE deterministic_id = ?",
            (first,),
        ) as cursor:
            projection_row = await cursor.fetchone()
        assert projection_row is not None
        assert tuple(projection_row) == (1, origin, "family", "house-a")
    else:
        projections = [meta for meta in backend._agent_fact_meta.values() if meta[5] == first]
        assert len(projections) == 1
        assert projections[0][3:7] == ("family", "house-a", first, origin)

    assert await manager.forget_fact(fact_id, principal=principal)
    assert (
        await backend.apply_fact_job(late_job, late_facts, extractor_lineage="late-replay")
        == "applied"
    )
    if isinstance(backend, SQLiteMemoryBackend):
        async with backend._conn.execute(
            "SELECT (SELECT COUNT(*) FROM facts WHERE deterministic_id = ? OR projection_of = ?), "
            "(SELECT COUNT(*) FROM fact_tombstones WHERE deterministic_id = ?)",
            (origin, origin, origin),
        ) as cursor:
            remaining = await cursor.fetchone()
        assert remaining is not None and tuple(remaining) == (0, 1)
    else:
        assert origin in backend._fact_tombstones
        assert not any(meta[5] in (origin, first) for meta in backend._agent_fact_meta.values())
    await manager.close()


@pytest.mark.asyncio
async def test_agent_events_redact_identity_and_content(tmp_path, capsys):
    canary = "PRIVATE-IDENTITY-CANARY-9f13"
    identity = AgentIdentity("deployment-a", "house-a", canary, "session-secret")
    manager = await MemoryManager.build(db_path=str(tmp_path / "memory.db"))
    recall = await manager.recall_for_turn(recall_request(identity, query_id="private-query"))
    await manager.record_committed_turn(
        committed_turn(
            "privacy-log-turn", identity=identity, fence=recall.write_fence, user_text=canary
        )
    )
    await manager.delete_scope(
        MemoryPrincipal("deployment-a", "house-a", canary, "session-secret"),
        (MemoryScope.personal(canary),),
    )
    await manager.close()
    output = capsys.readouterr().out
    assert canary not in output
    assert "session-secret" not in output
