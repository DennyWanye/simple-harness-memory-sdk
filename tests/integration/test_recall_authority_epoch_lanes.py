"""0.6.28 召回权威 epoch 车道分类：纯索引/投影重建不再推进 epoch。

S3 slice §5.4 把 ``recall_authority_events`` 的 epoch 定义为「任何**可能改变资格**的
suppression/revoke、认知 head/conflict/classification 变化、Short-Horizon source 失效和
policy version 变化」。0.6.27 之前实现里有三条**纯索引/投影**车道也推进 epoch
（``short_horizon_generation_changed`` / ``cognitive_vector_generation_changed`` /
纯新增的 ``short_horizon_projection_changed``），把一道罕见的语义围栏变成高频误报：
一次原生会话里 epoch 跑到 26，`authorize_recall_context_use` 的相等性判断因此在工具
已经结算之后抛 ``RECALL_AUTHORITY_STALE``，直接杀掉整个 Run（Host 备忘
``plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md`` §7(1)）。

本模块钉死修复后的契约：
1. 纯索引重建（认知向量世代激活）夹在类型化召回与用途授权之间，用途围栏放行；
2. 真正的资格变化（压制已绑定来源）仍以同一稳定码 ``RECALL_AUTHORITY_STALE`` 拒绝；
3. 纯新增的短时程投影重建不推进 epoch，而移除既有 chunk（=「source 失效」）仍推进，
   且即便不推进，用途围栏对被绑定来源的逐条重校验也仍然兜得住；
4. epoch 单调、``recall_authority_events`` 行形状不变。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from simple_harness.contracts import fingerprint_json
from simple_harness.runtime import (
    ContextFragmentBindingV2,
    RecallContextUseAuthorizationRequestV1,
    RecallItemBindingV1,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _span,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _plan as mutation_plan,
)
from tests.integration.test_cognitive_vector_generation import ControlledEmbedder
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

# 纯索引/投影车道：0.6.28 起一律不得出现在 recall_authority_events 里。
INDEX_ONLY_EVENT_KINDS = frozenset(
    {"short_horizon_generation_changed", "cognitive_vector_generation_changed"}
)


async def _events(backend: SQLiteHumanMemoryBackend) -> list[tuple[str, int, int]]:
    async with backend.connection.execute(
        "SELECT event_kind,previous_epoch,authority_epoch FROM recall_authority_events "
        "WHERE principal_id='actor-1' ORDER BY authority_epoch"
    ) as cursor:
        return [(str(row[0]), int(row[1]), int(row[2])) for row in await cursor.fetchall()]


async def _epoch(backend: SQLiteHumanMemoryBackend) -> int:
    async with backend.connection.execute(
        "SELECT authority_epoch FROM recall_authority_heads WHERE principal_id='actor-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


def _assert_monotonic(events: list[tuple[str, int, int]]) -> None:
    """行形状不变：previous_epoch 严格衔接、epoch 单调 +1、从 0 起。"""

    expected = 0
    for _kind, previous, epoch in events:
        assert previous == expected
        assert epoch == previous + 1
        expected = epoch


async def _prepared_with_embedder(
    path: Path, embedder: ControlledEmbedder
) -> tuple[SQLiteHumanMemoryBackend, object, object]:
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
        short_horizon_embedder=embedder,
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    return backend, envelope, span


def _use_request(execution, context, item, provider_attempt_id: str):
    fragment = ContextFragmentBindingV2("fragment-1", "f" * 64)
    return RecallContextUseAuthorizationRequestV1(
        "actor-1",
        context.run_id,
        context.turn_id,
        provider_attempt_id,
        execution.decision.decision_id,
        execution.decision.decision_hash,
        execution.result.result_id,
        execution.result.result_hash,
        (RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
        (fragment,),
        fingerprint_json([fragment.to_json()]),
        20.0,
    )


@pytest.mark.asyncio
async def test_index_only_rebuild_between_recall_and_use_no_longer_fences(
    tmp_path: Path,
) -> None:
    """(a) 认知向量世代重建夹在召回与用途之间 → 用途围栏放行；
    (b) 之后真的压制被绑定来源 → 仍以同一稳定码拒绝。"""

    embedder = ControlledEmbedder()
    backend, envelope, _span_ref = await _prepared_with_embedder(
        tmp_path / "index-only.db", embedder
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-index-only"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    assert bound_epoch == await _epoch(backend)

    # 纯索引重建：真的建了世代、真的写了向量，但不碰任何一条来源的资格。
    built = await backend.rebuild_cognitive_vector_generation()
    assert built.activated and not built.replayed and built.vector_count >= 1
    assert embedder.embedded  # 确实做了嵌入，不是空跑
    assert await _epoch(backend) == bound_epoch  # ← 0.6.28：索引重建不推进 epoch
    kinds = {kind for kind, _p, _e in await _events(backend)}
    assert not (kinds & INDEX_ONLY_EVENT_KINDS)

    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-1"),
        now=20.0,
    )
    assert receipt.authority_epoch == bound_epoch

    # 对照：真正的资格变化（压制被绑定来源）仍然以同一稳定码拒绝。
    await backend.suppress(
        SuppressionRequest(
            "suppress-bound-source",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            item.selected_item.source_ref,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    assert await _epoch(backend) > bound_epoch
    with pytest.raises(MemoryValidationError, match="RECALL_AUTHORITY_STALE"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-2"),
            now=20.0,
        )
    _assert_monotonic(await _events(backend))
    await backend.close()


@pytest.mark.asyncio
async def test_repeated_index_rebuilds_never_move_the_epoch(tmp_path: Path) -> None:
    """事故里 epoch 一次会话跑到 26 的直接来源：重复的世代重建。"""

    embedder = ControlledEmbedder()
    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "repeat-index.db", embedder
    )
    before = await _epoch(backend)
    for _ in range(3):
        await backend.rebuild_cognitive_vector_generation()
    assert await _epoch(backend) == before
    events = await _events(backend)
    assert [kind for kind, _p, _e in events] == [
        "initialized",
        "cognitive_memory_changed",
    ]
    _assert_monotonic(events)
    await backend.close()


@pytest.mark.asyncio
async def test_short_horizon_projection_addition_and_removal_are_classified(
    tmp_path: Path,
) -> None:
    """纯新增的投影重建不推进 epoch；移除既有 chunk（source 失效）仍推进。"""

    from simple_harness_memory import build_human_memory_v7
    from tests.integration.test_short_horizon_repository_v5 import (
        NOW,
        PRINCIPAL,
        _registration,
    )
    from tests.integration.test_short_horizon_repository_v5 import (
        _Authority as _ConversationAuthority,
    )

    # RECENT_CAUSAL_GROUP_LIMIT=10：最新的 10 个因果组仍在活动窗口内不入投影，
    # 因此要看到真实 chunk 至少需要 11 个注册。
    pairs = tuple(_registration(index) for index in range(1, 17))
    clock = [NOW]
    manager = await build_human_memory_v7(
        tmp_path / "projection.db",
        clock=lambda: clock[0],
        conversation_evidence_authority=_ConversationAuthority(
            tuple(reg for reg, _ in pairs)
        ),
    )
    backend = manager._backend
    try:

        async def epoch() -> int:
            async with backend.connection.execute(
                "SELECT authority_epoch FROM recall_authority_heads WHERE principal_id=?",
                (PRINCIPAL.actor_id,),
            ) as cursor:
                row = await cursor.fetchone()
            return 0 if row is None else int(row[0])

        async def kinds() -> list[str]:
            async with backend.connection.execute(
                "SELECT event_kind FROM recall_authority_events WHERE principal_id=? "
                "ORDER BY authority_epoch",
                (PRINCIPAL.actor_id,),
            ) as cursor:
                return [str(row[0]) for row in await cursor.fetchall()]

        async def register(index: int) -> None:
            reg, ref = pairs[index]
            await manager.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
            await manager.register_conversation_evidence(ref)

        for index in range(15):
            await register(index)
        first = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert first.projected_chunk_count == 5 and first.removed_chunk_count == 0
        # 还没有任何资格事件：连 recall_authority_heads 都不必存在。
        assert await epoch() == 0 and await kinds() == []

        # 纯新增：多出一个 chunk、没有任何既有 chunk 消失 → 不推进 epoch。
        await register(15)
        second = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert second.projected_chunk_count == 6 and second.removed_chunk_count == 0
        assert await epoch() == 0 and await kinds() == []

        # 既有 chunk 因过期被移除 = S3 §5.4「Short-Horizon source 失效」→ 必须推进 epoch。
        clock[0] = NOW + 5 * 86400 + 1
        third = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert third.projected_chunk_count == 0 and third.removed_chunk_count == 6
        # 惰性建头（initialized=1）+ 本次失效（=2）。
        assert await epoch() == 2
        assert await kinds() == ["initialized", "short_horizon_projection_changed"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_bound_short_horizon_source_removal_is_caught_without_the_epoch(
    tmp_path: Path,
) -> None:
    """即便 epoch 不动，用途围栏对被绑定来源的逐条重校验也仍然拦得住已消失的 chunk。

    直接删掉被绑定的 chunk（模拟一次投影重建把它换掉），epoch 保持不变，
    ``_validate_recall_context_use_sources_unlocked`` 仍以 ``RECALL_AUTHORITY_STALE`` 拒绝。
    """

    embedder = ControlledEmbedder()
    backend, _envelope, _span_ref = await _prepared_with_embedder(
        tmp_path / "source-fence.db", embedder
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-source-fence"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch

    # 被绑定的认知来源被 supersede 成新 revision：head 不再等于绑定 revision。
    await backend._db.execute(
        "UPDATE cognitive_memory_heads SET current_revision=current_revision+1 "
        "WHERE memory_id=?",
        (item.selected_item.source_ref,),
    )
    await backend._db.commit()
    assert await _epoch(backend) == bound_epoch  # epoch 没有被推进
    with pytest.raises(MemoryValidationError, match="RECALL_AUTHORITY_STALE"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-source"),
            now=20.0,
        )
    await backend.close()
