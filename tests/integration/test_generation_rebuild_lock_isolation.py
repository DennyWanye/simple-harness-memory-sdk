"""0.6.27 世代重建不再在写锁内嵌入 + 召回取锁受 deadline 约束。

复现 HM-TO-A6 turn 22 的活锁（Host `plans/2026-09-08-hm-to-a6/DIAG-RECALL-TIMEOUT.md`）：
慢嵌入器（每条 300 ms）× 6 条 chunk / head，维护 tick 超时 1 s，前台 typed recall 预算 1000 ms。
0.6.26 的实现把 ``embed_batch`` 放在 ``_write_lock`` 内，维护 tick 以 ~65% 占空比霸占写锁，
前台 recall 取同一把锁又没有 deadline，拿到锁的第一件事就是抛 ``DEADLINE_EXCEEDED``。

本文件锁死三件事：
1. 重建进行中（嵌入阶段）前台 typed recall 照常在预算内返回；
2. 嵌入期间清单变化 → 乐观 CAS 落空 → 本次不激活、不写审计、不污染世代表；
3. 写锁被短暂占用 → 向量 lane 退化到 ``cognitive_vector_deadline``，词面 lane 照常出结果；
   写锁被整段预算占用 → admit 以 ``TypedRecallDeadlineExceeded(stage='admit_write_lock')``
   快速失败，而不是无限期阻塞。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from simple_harness.runtime import RecallRetrievalMode

from simple_harness_memory.backends import sqlite_v5
from simple_harness_memory.core.errors import TypedRecallDeadlineExceeded
from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_VECTOR_DEADLINE,
    COGNITIVE_VECTOR_PARTIAL,
)
from tests.integration.test_cognitive_vector_generation import (
    ControlledEmbedder,
    add_memory,
    manager_with,
    rows,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)

# 现场是 WeMM ~200 ms/条、6 条合计 45.7 s；这里按同一形状缩小到 300 ms/条 × 6 条 = 1.8 s，
# 依然远大于维护 tick 的 1 s 超时与前台 1000 ms 预算。
SLOW_EMBED_SECONDS = 0.3
WORKER_TIMEOUT_SECONDS = 1.0

SIX = (
    ("c06", "preferred_name", "小周"),
    ("c07", "reply_closing", "不要以客套话收尾"),
    ("c12", "work_contact_hours", "09:00–17:00"),
    ("c17", "email_draft_length", "最多两段", ("邮件草稿",)),
    ("c19", "explanation_order", "先说结论再说理由"),
    ("c21", "todo_sort_order", "按截止时间排"),
)


class SlowEmbedder(ControlledEmbedder):
    """基类没有覆写 ``embed_batch``，生产 WeMM 也没有；这里显式模拟串行 N 次模型调用。"""

    def __init__(self, *, seconds: float = SLOW_EMBED_SECONDS, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.seconds = seconds
        self.batch_started = asyncio.Event()
        self.batch_hook = None

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_started.set()
        if self.batch_hook is not None:
            await self.batch_hook()
        vectors: list[list[float]] = []
        for text in texts:
            await asyncio.sleep(self.seconds)
            self.embedded.append(text)
            vectors.append(self.vector_for(text))
        return vectors


async def recall(manager, query: str, *, key: str, modes=BOTH):
    context = _context(query=query, modes=modes)
    return await manager.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


def values(execution) -> list[str]:
    return [str(item.public_payload["object_value"]) for item in execution.result.items]


@pytest.mark.asyncio
async def test_slow_rebuild_never_blocks_typed_recall(tmp_path: Path) -> None:
    """维护重建在嵌入阶段不持写锁，前台召回在 1000 ms 预算内照常返回。"""

    embedder = SlowEmbedder()
    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "livelock.db", embedder, operations=SIX
    )
    try:
        first = await manager.rebuild_cognitive_vector_generation()
        assert first.activated and first.vector_count == 6
        # 清单变化 → 下一次重建必须整代重新嵌入（现场就是这个状态）。
        await add_memory(
            manager, authority, evidence_id="evidence-2",
            operation=("c22", "response_style", "简洁"),
        )
        embedder.batch_started.clear()

        async def maintenance_tick() -> str:
            """Host `PrimaryShortIndexWorker.operation_timeout = 5.0` 的等价物（这里 1 s）。"""
            try:
                async with asyncio.timeout(WORKER_TIMEOUT_SECONDS):
                    await manager.rebuild_cognitive_vector_generation()
                return "completed"
            except TimeoutError:
                return "worker_timeout"

        tick = asyncio.create_task(maintenance_tick())
        await asyncio.wait_for(embedder.batch_started.wait(), timeout=2.0)
        # 此刻重建正卡在 embed_batch 上：0.6.26 会在这里持有 _write_lock。
        started = time.monotonic()
        execution = await recall(manager, "小周 的称呼", key="during-rebuild")
        elapsed = time.monotonic() - started
        assert values(execution) == ["小周"]  # 词面 lane 照常出结果
        assert elapsed < 1.0, elapsed  # 没有被写锁拖到预算之外
        # 世代因为 head 变化只覆盖了旧清单，退化码是 partial（0.6.38：不再是整代 stale），
        # 而不是任何超时——这一条才是本用例要与 ``cognitive_vector_deadline`` 区分开的。
        assert execution.degradation_codes == (COGNITIVE_VECTOR_PARTIAL,)
        assert await tick == "worker_timeout"  # 1 s 的 worker 超时确实兜不住 2.1 s 的嵌入
        # 被取消的一次重建没有留下任何半成品世代。
        assert await rows(
            manager, "SELECT COUNT(*) FROM cognitive_vector_generations WHERE state='building'"
        ) == [(0,)]

        # 给足时间（Host 侧退避/放宽超时之后）重建就会正常激活。
        second = await manager.rebuild_cognitive_vector_generation()
        assert second.activated and second.vector_count == 7
        assert second.generation_id != first.generation_id
        fresh = await recall(manager, "小周 的称呼", key="after-rebuild")
        assert values(fresh) == ["小周"] and fresh.degradation_codes == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cognitive_cas_miss_does_not_activate_and_writes_no_audit(tmp_path: Path) -> None:
    """嵌入期间 head 清单变了：本次不激活，世代表与审计表都不留痕，下一 tick 重来。"""

    embedder = SlowEmbedder(seconds=0.01)
    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "cas.db", embedder, operations=(("c06", "preferred_name", "小周"),)
    )
    try:
        generations_before = await rows(
            manager, "SELECT COUNT(*) FROM cognitive_vector_generations"
        )
        audits_before = await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_audit")
        assert generations_before == [(0,)] and audits_before == [(0,)]

        async def mutate_during_embedding() -> None:
            # 只有在嵌入不持写锁时这个写入才可能发生——它同时也是 P0 的行为证明。
            await add_memory(
                manager, authority, evidence_id="evidence-2",
                operation=("c17", "email_draft_length", "最多两段"),
            )

        embedder.batch_hook = mutate_during_embedding
        result = await manager.rebuild_cognitive_vector_generation()
        embedder.batch_hook = None
        assert result.cas_miss is True
        assert result.activated is False and result.replayed is False
        assert result.generation_id is None and result.audit_id is None
        assert result.vector_count == 1  # 本次嵌入的是旧清单的 1 条
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_generations") == [(0,)]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_audit") == [(0,)]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vectors") == [(0,)]

        # 下一 tick 以新清单重建并正常激活。
        retried = await manager.rebuild_cognitive_vector_generation()
        assert retried.cas_miss is False and retried.activated and retried.vector_count == 2
        assert await rows(
            manager, "SELECT state FROM cognitive_vector_generations"
        ) == [("active",)]
        replay = await manager.rebuild_cognitive_vector_generation()
        assert replay.replayed and replay.generation_id == retried.generation_id
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_short_horizon_cas_miss_does_not_activate(tmp_path: Path) -> None:
    """短时域世代同型：嵌入期间 chunk 清单变了就不激活，旧 active 世代保持不变。"""

    from simple_harness_memory.embedders.mock import HashEmbedder
    from tests.integration.test_short_horizon_repository_v5 import (
        PRINCIPAL,
        _backend,
        _registration,
    )

    class SlowHashEmbedder(HashEmbedder):
        """同 WeMM：没有真正的批处理，``embed_batch`` 就是 N 次串行调用。"""

        def __init__(self) -> None:
            super().__init__(32)
            self.batch_hook = None

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            if self.batch_hook is not None:
                await self.batch_hook()
            return [await self.embed(text) for text in texts]

    embedder = SlowHashEmbedder()
    pairs = tuple(_registration(index) for index in range(1, 13))
    backend = await _backend(tmp_path / "short-cas.db", pairs, embedder=embedder)
    try:
        await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
        built = await backend.rebuild_short_horizon_generation()
        assert built.activated and built.cas_miss is False

        authority = backend._conversation_evidence_authority

        async def register(indices: range) -> None:
            for registration, reference in (_registration(index) for index in indices):
                authority.registrations[registration.registration_id] = registration
                await backend.ingest_committed_evidence(
                    registration.envelope, registration.admission_receipt
                )
                await backend.register_conversation_evidence(reference)

        # 先让 chunk 清单相对 active 世代变化一次，本次重建必须真的重新嵌入。
        await register(range(13, 25))
        await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)

        async def mutate_during_embedding() -> None:
            # 只有在嵌入不持写锁时这个写入才可能发生——它同时也是 P0 的行为证明。
            await register(range(25, 37))
            await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)

        # 重建已经读到了嵌入前的 chunk 清单，嵌入过程中投影再次换掉 chunk。
        embedder.batch_hook = mutate_during_embedding
        result = await backend.rebuild_short_horizon_generation()
        embedder.batch_hook = None
        assert result.cas_miss is True
        assert result.activated is False and result.generation_id is None
        assert result.audit_id is None
        async with backend.connection.execute(
            "SELECT generation_id,state FROM short_horizon_generations ORDER BY created_at"
        ) as cursor:
            generations = [tuple(row) for row in await cursor.fetchall()]
        assert generations == [(built.generation_id, "active")]  # 旧世代原样保留

        retried = await backend.rebuild_short_horizon_generation()
        assert retried.activated and retried.cas_miss is False
        assert retried.generation_id != built.generation_id
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_contended_write_lock_degrades_vector_lane_instead_of_failing(
    tmp_path: Path,
) -> None:
    """写锁被别的写入短暂持有：向量 lane 退化，词面 lane 与终态写入照常。"""

    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "contended.db", embedder, operations=(("c06", "preferred_name", "小周"),)
    )
    backend = manager._backend
    try:
        await manager.rebuild_cognitive_vector_generation()
        warm = await recall(manager, "小周 的称呼", key="warm")
        assert values(warm) == ["小周"] and warm.degradation_codes == ()

        held = asyncio.Event()
        # 预算 1000 ms：取锁预留 200 ms，故等锁在 ~800 ms 超时；这里占 850 ms，
        # 让向量 lane 必然退化，同时给词面 lane 与终态留出真实余量。
        hold_seconds = 0.85

        async def hold_write_lock() -> None:
            async with backend._write_lock:
                held.set()
                await asyncio.sleep(hold_seconds)

        original_admit = backend._admit_typed_recall_request
        holder: list[asyncio.Task[None]] = []

        async def admit_then_contend(**kwargs: object):
            admitted = await original_admit(**kwargs)  # type: ignore[arg-type]
            task = asyncio.create_task(hold_write_lock())
            holder.append(task)
            await held.wait()
            return admitted

        backend._admit_typed_recall_request = admit_then_contend  # type: ignore[assignment]
        try:
            started = time.monotonic()
            execution = await recall(manager, "小周 的称呼", key="contended")
        finally:
            backend._admit_typed_recall_request = original_admit  # type: ignore[assignment]
        elapsed = time.monotonic() - started
        assert values(execution) == ["小周"]  # 词面 lane 照常
        assert execution.degradation_codes == (COGNITIVE_VECTOR_DEADLINE,)
        assert hold_seconds <= elapsed < 1.5, elapsed
        await asyncio.gather(*holder)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_admit_write_lock_timeout_fails_fast_with_named_stage(tmp_path: Path) -> None:
    """写锁被整段预算占住：admit 在 deadline 处快速失败并写明阶段，而不是无限期阻塞。"""

    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "admit.db", embedder, operations=(("c06", "preferred_name", "小周"),)
    )
    backend = manager._backend
    try:
        await manager.rebuild_cognitive_vector_generation()
        held = asyncio.Event()
        release = asyncio.Event()

        async def hold_write_lock() -> None:
            async with backend._write_lock:
                held.set()
                await release.wait()

        holder = asyncio.create_task(hold_write_lock())
        await held.wait()
        started = time.monotonic()
        with pytest.raises(TypedRecallDeadlineExceeded) as raised:
            await recall(manager, "小周 的称呼", key="admit-blocked")
        elapsed = time.monotonic() - started
        assert str(raised.value) == "DEADLINE_EXCEEDED"
        assert isinstance(raised.value, TimeoutError)  # Host 的映射契约不变
        assert raised.value.stage == "admit_write_lock"
        assert raised.value.rejection_receipt.stage == "admit_write_lock"  # type: ignore[attr-defined]
        # 1000 ms 预算：在 deadline 处返回，不会等到锁被释放。
        assert 0.9 <= elapsed < 1.6, elapsed
        release.set()
        await holder
        # 锁释放后同一 idempotency_key 仍可正常执行（admit 超时没有落任何幂等记录）。
        recovered = await recall(manager, "小周 的称呼", key="admit-blocked")
        assert values(recovered) == ["小周"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_embedding_failure_still_records_failed_generation_row(tmp_path: Path) -> None:
    """0.6.24 语义保持：嵌入在锁外失败，失败世代行仍然（重新取锁后）落库。"""

    from simple_harness_memory.core.errors import CognitiveVectorGenerationFailed
    from simple_harness_memory.features.cognitive_vector import (
        COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED,
    )

    embedder = SlowEmbedder(seconds=0.0)
    manager, *_ = await manager_with(
        tmp_path / "failed.db", embedder, operations=(("c06", "preferred_name", "小周"),)
    )
    try:
        async def explode() -> None:
            raise RuntimeError("embedder exploded")

        embedder.batch_hook = explode
        with pytest.raises(CognitiveVectorGenerationFailed) as raised:
            await manager.rebuild_cognitive_vector_generation()
        assert raised.value.code == COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED
        assert await rows(
            manager,
            "SELECT state,last_error_code FROM cognitive_vector_generations",
        ) == [("failed", COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED)]
        embedder.batch_hook = None
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.activated and built.vector_count == 1
    finally:
        await manager.close()


def test_frozen_recall_lock_reserves() -> None:
    """两段预留是冻结常量：等锁 ≤ deadline-200 ms，查询嵌入 ≤ deadline-50 ms。"""

    assert sqlite_v5.COGNITIVE_VECTOR_LOCK_RESERVE_S == 0.200
    assert sqlite_v5.COGNITIVE_VECTOR_AUDIT_RESERVE_S == 0.050
