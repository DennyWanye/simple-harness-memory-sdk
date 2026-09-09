"""0.6.29 用途围栏：epoch 前进但被绑定来源全部未变时签发收据而不是拒绝。

0.6.28 把纯索引/世代车道从 ``recall_authority_events`` 里摘掉之后，HM-TO-A6 第 4 次尝试
turn 15 仍然死于同一处围栏：前台定型召回已经结算，**异步分析车道**把上一轮的新记忆落库
（``cognitive_memory_changed`` → epoch +1）恰好落在 ``authorize_recall_context_use`` 之前，
epoch 相等性判断抛 ``RECALL_AUTHORITY_STALE``，Host 映射为
``recall_context_use_authority_stale``，冻结的 Harness SDK 在该 hop 没有修复路径 → ``run.fail``
（Host 备忘 ``plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md`` §7(2)）。

本模块钉死 0.6.29 的判据：

1. epoch 因**与本次绑定无关**的资格事件前进（新建记忆、压制别的记忆），而
   ``_validate_recall_context_use_sources_unlocked`` 对每一条被绑定来源全部通过
   → 照常签发收据，并留下稳定降级码 ``authority_epoch_advanced`` 与两个 epoch；
2. 同样的竞态下只要**被绑定来源**真的失效（取代 / 压制）→ 仍以 ``RECALL_AUTHORITY_STALE``
   拒绝、零 payload、不写任何收据行；
3. policy version 变化与权威 epoch 倒退仍然硬失败；
4. 无竞态路径的收据 ``receipt_hash`` 与 ``receipt_json`` 与 0.6.28 逐字节相同。

0.6.38（DECISION-2026-09-09-lease-degradation-and-incumbent-vectors.md）：第 3 条里的
「结果期限过期」被移出硬失败，降级为 ``authority_lease_expired``（本模块 ① 因此按新政策
改写，是本轮唯一一处被有意反转的既有断言；租约那一支的完整正/负控见
``test_recall_context_use_lease.py``）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from simple_harness.runtime import SemanticMemoryPayload

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.recall_context_use import (
    RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
    RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED,
    RecallContextUseAuthorityNoteV1,
)
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from tests.integration.test_cognitive_mutation_repository_v5 import _operation
from tests.integration.test_cognitive_mutation_repository_v5 import _plan as mutation_plan
from tests.integration.test_cognitive_vector_generation import ControlledEmbedder
from tests.integration.test_recall_authority_epoch_lanes import (
    _epoch,
    _prepared_with_embedder,
    _use_request,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

# 0.6.28 源上同一场景的实测值（见决策备忘 §6）：无竞态路径必须逐字节不变。
NO_RACE_RECEIPT_ID = (
    "recall-context-use-receipt-"
    "f429dfa8e14dc1d6def38f431f31dea6d51981b367a613a86d01f8b9904325cc"
)
NO_RACE_RECEIPT_HASH = "af05933f0e177255f5e1263e2c7bb1b38f3210469d5d00bd92268083185c07ce"
NO_RACE_RECEIPT_JSON = (
    '{"authority_epoch":2,"authorized_at":20.0,'
    '"decision_hash":"2484134c87001d3a6c0ea506f60758e463e9888f486f8b52af9a536d317fa431",'
    '"decision_id":"recall-decision:bbd25a458a1ff97f6560e7f333a46049","expires_at":100.0,'
    '"item_bindings":[{"item_hash":'
    '"8a3e9e90c57e740c4ccb72ceefc1571ebef9cbb559b2d09acbec211faee83fa9",'
    '"item_id":"recall-item:bbd25a458a1ff97f6560e7f3:1"}],'
    '"policy_hash":"c27604aa354d34f9597a62873a2a53547df192b74c267c569fae445d23c7fc04",'
    '"provider_attempt_id":"provider-attempt-norace","receipt_id":'
    f'"{NO_RACE_RECEIPT_ID}",'
    '"request_hash":"949e48b43dffbd884ef4205d975c0a48f02bc70764dd0b8c102f85057897b4c4",'
    '"result_hash":"23e0882d698297ff5c635627ac24faeed206303c5b7cf8287045bc0e52d1dc87",'
    '"result_id":"recall-result:bbd25a458a1ff97f6560e7f333a46049","run_id":"run-recall",'
    '"schema_version":1,"snapshot_manifest_hash":'
    '"a3300fd6d0aea972b1818e806a87a1fe7563db495ae4cd9f04a6858888839a50",'
    '"subject":"actor-1","turn_id":"turn-recall"}'
)


async def _memory_ids(backend: SQLiteHumanMemoryBackend) -> set[str]:
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads WHERE principal_id='actor-1'"
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


async def _apply_unrelated_memory(backend: SQLiteHumanMemoryBackend, envelope, span) -> str:
    """异步分析车道的等价物：落库**另一条**新记忆 → ``cognitive_memory_changed`` → epoch +1。"""

    before = await _memory_ids(backend)
    operation = dataclasses.replace(
        _operation(span, operation_id="create-2"),
        payload=SemanticMemoryPayload("user:self", "tone", "warm", ("default",)),
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            envelope,
            operation,
            plan_id="plan-2",
            idempotency_key="idempotency-2",
            base_revision=2,
        ),
    )
    assert result.outcome.value == "committed"
    created = await _memory_ids(backend) - before
    assert len(created) == 1
    return created.pop()


async def _receipt_rows(backend: SQLiteHumanMemoryBackend) -> list[tuple[str, int]]:
    async with backend.connection.execute(
        "SELECT receipt_id,authority_epoch FROM recall_context_use_receipts "
        "ORDER BY receipt_id"
    ) as cursor:
        return [(str(row[0]), int(row[1])) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_concurrent_memory_apply_between_recall_and_use_now_authorizes(
    tmp_path: Path,
) -> None:
    """HM-TO-A6 turn 15 的原型：召回已结算，分析车道落了**别的**记忆 → 放行 + 降级码。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "race-authorized.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-race-ok"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    assert bound_epoch == await _epoch(backend)

    other_memory_id = await _apply_unrelated_memory(backend, envelope, span)
    assert other_memory_id != item.selected_item.source_ref
    advanced = await _epoch(backend)
    assert advanced == bound_epoch + 1  # 真的是一次资格车道事件，不是索引噪声

    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-race"),
        now=20.0,
    )
    # 收据记录**授权时**的权威，而不是绑定时的旧 epoch。
    assert receipt.authority_epoch == advanced
    assert receipt.policy_hash == execution.result.policy_hash
    assert receipt.expires_at == execution.result.authority_expires_at

    notes = await backend.read_recall_context_use_authority_notes(principal=_principal())
    assert len(notes) == 1
    note = notes[0]
    assert isinstance(note, RecallContextUseAuthorityNoteV1)
    assert note.reason_code == RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED
    assert note.bound_authority_epoch == bound_epoch
    assert note.authority_epoch == advanced
    assert note.receipt_id == receipt.receipt_id
    assert note.receipt_hash == receipt.receipt_hash
    assert note.result_id == execution.result.result_id
    assert note.run_id == context.run_id and note.turn_id == context.turn_id
    # 降级说明完全由两条不可变行导出，没有引入新表。
    assert await _receipt_rows(backend) == [(receipt.receipt_id, advanced)]

    # 幂等重放：同一 provider attempt 仍然逐字返回同一张收据。
    replay = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-race"),
        now=20.0,
    )
    assert replay.receipt_hash == receipt.receipt_hash
    assert len(await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    )) == 1
    await backend.close()


@pytest.mark.asyncio
async def test_unrelated_suppression_advances_the_epoch_and_still_authorizes(
    tmp_path: Path,
) -> None:
    """压制**别的**记忆同样推进 epoch，但被绑定来源没变 → 仍应放行。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "race-unrelated-suppression.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-race-suppress-other"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    other_memory_id = await _apply_unrelated_memory(backend, envelope, span)
    await backend.suppress(
        SuppressionRequest(
            "suppress-unrelated",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            other_memory_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    advanced = await _epoch(backend)
    assert advanced == bound_epoch + 2

    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-unrelated"),
        now=20.0,
    )
    assert receipt.authority_epoch == advanced
    notes = await backend.read_recall_context_use_authority_notes(principal=_principal())
    assert [(n.bound_authority_epoch, n.authority_epoch) for n in notes] == [
        (bound_epoch, advanced)
    ]
    await backend.close()


@pytest.mark.asyncio
async def test_same_race_but_suppressed_bound_source_still_fences(tmp_path: Path) -> None:
    """同一竞态下压制**被绑定**来源 → 仍以 ``RECALL_AUTHORITY_STALE`` 拒绝、零收据。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "race-suppressed.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-race-suppressed"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    await _apply_unrelated_memory(backend, envelope, span)
    await backend.suppress(
        SuppressionRequest(
            "suppress-bound",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            item.selected_item.source_ref,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    assert await _epoch(backend) > bound_epoch
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-suppressed"),
            now=20.0,
        )
    assert await _receipt_rows(backend) == []
    assert await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    ) == ()
    await backend.close()


@pytest.mark.asyncio
async def test_same_race_but_superseded_bound_source_still_fences(tmp_path: Path) -> None:
    """被绑定来源被取代成新 revision（head 不再等于绑定 revision）→ 同一稳定码拒绝。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "race-superseded.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-race-superseded"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    await _apply_unrelated_memory(backend, envelope, span)
    assert await _epoch(backend) == bound_epoch + 1
    await backend.connection.execute(
        "UPDATE cognitive_memory_heads SET current_revision=current_revision+1 "
        "WHERE memory_id=?",
        (item.selected_item.source_ref,),
    )
    await backend.connection.commit()
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-superseded"),
            now=20.0,
        )
    assert await _receipt_rows(backend) == []
    await backend.close()


@pytest.mark.asyncio
async def test_policy_change_and_epoch_regression_still_fence(
    tmp_path: Path,
) -> None:
    """epoch 之外的两条硬判据一分未放宽：policy version、权威倒退。

    权威读取被替身接管（不篡改 ``recall_authority_heads``，那会破坏事件链的完整性校验），
    这样测的正是 0.6.29 新分支本身的判据顺序。

    0.6.38：原 ① 的「结果期限过期 → 拒」改为「结果期限过期 + 来源全通过 → 签发收据 +
    ``authority_lease_expired`` 说明」，其余三条逐字保留。
    """

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "hard-fences.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-hard-fences"),
    )
    item = execution.result.items[0]
    bound_epoch = execution.result.authority_epoch
    bound_policy = execution.result.policy_hash

    async def _authority(_principal_id: str) -> tuple[int, str]:
        return authority_value[0]

    authority_value = [(bound_epoch, bound_policy)]
    backend._recall_authority_unlocked = _authority  # type: ignore[method-assign]

    # ① 结果期限过期（0.6.38）：epoch 一致、来源全通过 → 签发收据并留下租约到期说明。
    lease_receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-expired"),
        now=execution.result.authority_expires_at,
    )
    assert lease_receipt.authority_epoch == bound_epoch
    lease_notes = await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    )
    assert [note.reason_code for note in lease_notes] == [
        RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED
    ]
    assert lease_notes[0].bound_authority_expires_at == execution.result.authority_expires_at
    assert lease_notes[0].bound_authority_epoch == lease_notes[0].authority_epoch

    # ② policy version 变化：即便来源全部完好，也绝不放行。
    authority_value[0] = (bound_epoch + 1, "b" * 64)
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-policy"),
            now=20.0,
        )

    # ③ 权威倒退：epoch 比绑定时更小，只可能是损坏或回滚，绝不放行。
    authority_value[0] = (bound_epoch - 1, bound_policy)
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-regress"),
            now=20.0,
        )
    # ②③ 一行收据都没有多写：库里只有 ① 那张。
    assert await _receipt_rows(backend) == [(lease_receipt.receipt_id, bound_epoch)]

    # ④ 「epoch 前进 + policy 不变 + 来源全通过」照常放行。
    authority_value[0] = (bound_epoch + 1, bound_policy)
    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-allowed"),
        now=20.0,
    )
    assert receipt.authority_epoch == bound_epoch + 1
    await backend.close()


@pytest.mark.asyncio
async def test_no_race_receipt_bytes_are_unchanged_from_0_6_28(tmp_path: Path) -> None:
    """(c) 无竞态路径逐字节不变：receipt_id / receipt_hash / canonical receipt_json。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "no-race.db", ControlledEmbedder()
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-norace"),
    )
    item = execution.result.items[0]
    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-norace"),
        now=20.0,
    )
    assert receipt.receipt_id == NO_RACE_RECEIPT_ID
    assert receipt.receipt_hash == NO_RACE_RECEIPT_HASH
    assert receipt.authority_epoch == execution.result.authority_epoch
    async with backend.connection.execute(
        "SELECT receipt_json,receipt_hash,authority_epoch,policy_hash,authorized_at,"
        "expires_at FROM recall_context_use_receipts"
    ) as cursor:
        rows = tuple(await cursor.fetchall())
    assert len(rows) == 1
    assert str(rows[0]["receipt_json"]) == NO_RACE_RECEIPT_JSON
    assert str(rows[0]["receipt_hash"]) == NO_RACE_RECEIPT_HASH
    assert int(rows[0]["authority_epoch"]) == execution.result.authority_epoch
    # 无竞态 → 没有任何降级说明。
    assert await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    ) == ()
    await backend._validate_integrity()
    await backend.close()


@pytest.mark.asyncio
async def test_authority_note_view_rejects_impossible_shapes() -> None:
    """降级视图是有界的：只认已知码，且当前 epoch 必须真的前进。"""

    with pytest.raises(MemoryValidationError, match="recall_context_use_reason_code_invalid"):
        RecallContextUseAuthorityNoteV1(
            "receipt-1", "a" * 64, "actor-1", "run-1", "turn-1", "pa-1",
            "result-1", "b" * 64, "some_other_code", 1, 2, "c" * 64, 20.0,
        )
    with pytest.raises(
        MemoryValidationError, match="recall_context_use_authority_epoch_invalid"
    ):
        RecallContextUseAuthorityNoteV1(
            "receipt-1", "a" * 64, "actor-1", "run-1", "turn-1", "pa-1",
            "result-1", "b" * 64, RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
            2, 2, "c" * 64, 20.0,
        )
