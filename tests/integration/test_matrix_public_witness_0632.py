# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1
"""0.6.32：401 矩阵四个未闭合格所需的公共见证增量（端到端）。

来源：Host `simple_harness/plans/2026-09-07-corpus-c01-local/TYPED-RECALL-401-RUN-08.md`
§2.I-1 / §2.I-2 与 §7 后继第 4 项（同一份 RUN-07 §3.1 的 D / E 两组）。

* **(a) 召回策略版本入口**（`current-use/authority:policy_hash_change`，1 格）——
  ``policy_hash`` 从 Memory 常量变为部署字段 ``recall_policy``；换版本后此前签发的
  结果绑定必须失去用途授权，且默认版本的一切字节不变。
* **(b) ``MemoryManager.cleanup_short_horizon``**（`current-use/authority:short_source_cleanup`，
  1 格）——公共入口与内部清理车道同一实现、同一 0.6.28 epoch 规则。
* **(c) apply validation 精确 reason 码**（conflict 精确 reason，3 格）——三种 contest
  拒绝在 durable 审计与只读视图上一一对应，公共错误类不变。
* **(d) 执行 lane 见证**（executed-lane，3 格）——每条被选中项由哪些 lane 产生。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.runtime import (
    ConflictStatus,
    ExistingMemoryTarget,
    MemoryMutationApplyOutcome,
    MemoryMutationApplyReasonCode,
    MemoryMutationKind,
    SemanticMemoryPayload,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.mutation_rejections import (
    MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE,
    MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE,
    MemoryMutationValidationNoteV1,
)
from simple_harness_memory.core.recall_policy import (
    RECALL_POLICY_CHANGED_EVENT_KIND,
    RECALL_POLICY_HASH_V1,
    RecallEligibilityPolicyV1,
    RecallPolicyStateV1,
    recall_policy_hash,
    recall_policy_id,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _span,
)
from tests.integration.test_cognitive_mutation_repository_v5 import _plan as mutation_plan
from tests.integration.test_cognitive_vector_generation import ControlledEmbedder
from tests.integration.test_recall_authority_epoch_lanes import (
    _epoch,
    _events,
    _use_request,
)
from tests.integration.test_short_horizon_repository_v5 import (
    NOW as SHORT_NOW,
)
from tests.integration.test_short_horizon_repository_v5 import (
    PRINCIPAL as SHORT_PRINCIPAL,
)
from tests.integration.test_short_horizon_repository_v5 import _backend as _short_backend
from tests.integration.test_short_horizon_repository_v5 import _registration
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

_OPEN: list[SQLiteHumanMemoryBackend] = []


@pytest.fixture(autouse=True)
async def _close_backends():
    """任何断言失败都不得留下未关闭的 aiosqlite 线程（否则解释器退出时挂住）。"""

    _OPEN.clear()
    yield
    from contextlib import suppress

    for backend in tuple(_OPEN):
        with suppress(Exception):
            await backend.close()
    _OPEN.clear()


def _track(backend: SQLiteHumanMemoryBackend) -> SQLiteHumanMemoryBackend:
    _OPEN.append(backend)
    return backend


async def _prepared(
    path: Path,
    *,
    recall_policy: RecallEligibilityPolicyV1 | int | None = None,
    embedder: ControlledEmbedder | None = None,
) -> tuple[SQLiteHumanMemoryBackend, object, object, object]:
    """与 ``test_recall_authority_epoch_lanes._prepared_with_embedder`` 同型，另带策略版本。"""

    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    kwargs = {} if recall_policy is None else {"recall_policy": recall_policy}
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
        short_horizon_embedder=embedder,
        **kwargs,  # type: ignore[arg-type]
    )
    _track(backend)
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    return backend, envelope, span, authority


async def _head_policy(backend: SQLiteHumanMemoryBackend) -> str:
    async with backend.connection.execute(
        "SELECT policy_hash FROM recall_authority_heads WHERE principal_id='actor-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return str(row[0])


# --------------------------------------------------------------------------------------
# (a) 召回策略版本入口
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_policy_version_keeps_every_recall_byte_identical(
    tmp_path: Path,
) -> None:
    """默认部署（不传 ``recall_policy``）与显式 v1 的结果逐字节相同，且等于 0.6.31 常量。"""

    hashes: list[tuple[str, str, str]] = []
    for name, policy in (("default", None), ("explicit-v1", RecallEligibilityPolicyV1(1))):
        backend, _envelope, _span, _authority = await _prepared(
            tmp_path / f"policy-{name}.db", recall_policy=policy
        )
        context = _context()
        execution = await backend.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="idem-policy-default"),
        )
        assert execution.result.policy_hash == RECALL_POLICY_HASH_V1
        assert await _head_policy(backend) == RECALL_POLICY_HASH_V1
        item = execution.result.items[0]
        receipt = await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-policy"),
            now=20.0,
        )
        assert receipt.policy_hash == RECALL_POLICY_HASH_V1
        # 策略未变 ⇒ 权威事件里没有任何 policy 车道，epoch 与 0.6.31 一致。
        events = await _events(backend)
        assert all(kind != RECALL_POLICY_CHANGED_EVENT_KIND for kind, _p, _e in events)
        hashes.append(
            (execution.decision.decision_hash, execution.result.result_hash, receipt.receipt_hash)
        )
        state = await backend.read_recall_policy(principal=_principal())
        assert isinstance(state, RecallPolicyStateV1)
        assert state.policy_version == 1
        assert state.policy_id == "typed-recall-eligibility/v1"
        assert state.policy_hash == state.authority_policy_hash == RECALL_POLICY_HASH_V1
        assert state.policy_changed is False
        await backend.close()
    assert hashes[0] == hashes[1]
    # 0.6.31 源（独立 worktree ``simple-harness-memory-sdk-0631-source``，main ``ff8be5f``）
    # 上跑同一脚本的实测字面值；``diff`` 为空。默认策略版本不得改变任何一个字节。
    assert hashes[0] == (
        "adfddf5a8e6e665f9094a65a19bc482f5fc870bbb9d2cdca3ea48e85b3931f78",
        "2e003caab33fd2aa101f80afb1019cdaf9ac0c0316389fb6d5071369c2881823",
        "deb78444ad5d11f795cea0576df09ab38481081f06adfe04df77d3d83ed10f61",
    )


@pytest.mark.asyncio
async def test_policy_version_change_invalidates_earlier_context_use_authorizations(
    tmp_path: Path,
) -> None:
    """401 §2.I-1：策略换版本后，基于旧策略签发的结果不得再被用途授权。"""

    path = tmp_path / "policy-change.db"
    backend, _envelope, _span, _authority = await _prepared(path)
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-policy-change"),
    )
    item = execution.result.items[0]
    bound_policy = execution.result.policy_hash
    bound_epoch = execution.result.authority_epoch
    assert bound_policy == RECALL_POLICY_HASH_V1
    # 旧策略下先证明这条结果**本来是可以被授权的**（否则 0 无法归因到策略轴）。
    control = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-before"),
        now=20.0,
    )
    assert control.policy_hash == bound_policy
    await backend.close()

    # 只改一根轴：同一个库、同一条结果，重开时声明策略 v2。
    reopened = _track(
        SQLiteHumanMemoryBackend(
            path, now=lambda: 20.0, recall_policy=RecallEligibilityPolicyV1(2)
        )
    )
    await reopened.initialize()
    state = await reopened.read_recall_policy(principal=_principal())
    assert state.policy_version == 2
    assert state.policy_id == recall_policy_id(2)
    assert state.policy_hash == recall_policy_hash(2)
    # 权威头还停在旧策略上——对齐是一次带审计的写，见下。
    assert state.authority_policy_hash == RECALL_POLICY_HASH_V1
    assert state.policy_changed is True

    with pytest.raises(MemoryValidationError, match="RECALL_AUTHORITY_STALE"):
        await reopened.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-after"),
            now=20.0,
        )
    # 拒绝不写任何收据行。
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM recall_context_use_receipts"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1  # 只有旧策略下的那张

    # 下一次召回把权威头对齐：恰好一条 recall_policy_changed 事件、epoch +1。
    later = _context()
    await reopened.execute_typed_recall(
        principal=_principal(),
        context=later,
        plan=_recall_plan(later, idempotency_key="idem-policy-change-2"),
    )
    events = await _events(reopened)
    policy_events = [item for item in events if item[0] == RECALL_POLICY_CHANGED_EVENT_KIND]
    assert len(policy_events) == 1
    assert policy_events[0][1] == bound_epoch and policy_events[0][2] == bound_epoch + 1
    assert await _head_policy(reopened) == recall_policy_hash(2)
    assert await _epoch(reopened) == bound_epoch + 1
    aligned = await reopened.read_recall_policy(principal=_principal())
    assert aligned.policy_changed is False
    # 对齐之后再来一次仍然只有一条事件（幂等，不会每次召回都推进 epoch）。
    third = _context()
    await reopened.execute_typed_recall(
        principal=_principal(),
        context=third,
        plan=_recall_plan(third, idempotency_key="idem-policy-change-3"),
    )
    again = await _events(reopened)
    assert len([e for e in again if e[0] == RECALL_POLICY_CHANGED_EVENT_KIND]) == 1
    await reopened.close()

    # 反向对照：把部署换回 v1、让权威头重新对齐到 v1，同一条旧结果重新可以被授权
    # ——拒绝确实由策略轴造成，而不是这条结果本身失效了。
    restored = _track(SQLiteHumanMemoryBackend(path, now=lambda: 20.0))
    await restored.initialize()
    assert (await restored.read_recall_policy(principal=_principal())).policy_changed is True
    back = _context()
    await restored.execute_typed_recall(
        principal=_principal(),
        context=back,
        plan=_recall_plan(back, idempotency_key="idem-policy-restore"),
    )
    assert await _head_policy(restored) == RECALL_POLICY_HASH_V1
    receipt = await restored.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-restored"),
        now=20.0,
    )
    assert receipt.policy_hash == RECALL_POLICY_HASH_V1
    await restored.close()


@pytest.mark.asyncio
async def test_manager_exposes_the_policy_version_input_and_view(tmp_path: Path) -> None:
    """公共入口：``build_human_memory_v7(recall_policy=…)`` + ``read_recall_policy``。"""

    manager = await MemoryManager.build_human_memory_v7(
        tmp_path / "manager-policy.db", recall_policy=RecallEligibilityPolicyV1(3)
    )
    assert manager.backend._recall_policy == RecallEligibilityPolicyV1(3)
    assert manager.backend._recall_policy_hash == recall_policy_hash(3)
    await manager.close()

    default = await MemoryManager.build_human_memory_v7(tmp_path / "manager-default.db")
    assert default.backend._recall_policy_hash == RECALL_POLICY_HASH_V1
    await default.close()

    with pytest.raises(MemoryValidationError, match="recall_policy_version_invalid"):
        await MemoryManager.build_human_memory_v7(
            tmp_path / "manager-bad.db", recall_policy=0
        )


# --------------------------------------------------------------------------------------
# (b) MemoryManager.cleanup_short_horizon
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_cleanup_short_horizon_matches_the_internal_lane(
    tmp_path: Path,
) -> None:
    """401 §2.I-2：公共入口与 backend 同一实现、同一 0.6.28 epoch 规则。"""

    pairs = tuple(_registration(index) for index in range(1, 12))
    backend = _track(await _short_backend(tmp_path / "manager-cleanup.db", pairs))
    manager = MemoryManager(backend, None)
    built = await backend.rebuild_short_horizon_projection(principal=SHORT_PRINCIPAL)
    assert built.projected_chunk_count == 1

    async def epoch() -> int:
        async with backend.connection.execute(
            "SELECT authority_epoch FROM recall_authority_heads WHERE principal_id=?",
            (SHORT_PRINCIPAL.actor_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return 0 if row is None else int(row[0])

    async def cleanup_events() -> int:
        async with backend.connection.execute(
            "SELECT COUNT(*) FROM recall_authority_events WHERE principal_id=? "
            "AND event_kind='short_horizon_cleanup'",
            (SHORT_PRINCIPAL.actor_id,),
        ) as cursor:
            return int((await cursor.fetchone())[0])

    before = await epoch()
    # 未到期：零删除 ⇒ 按 0.6.28 规则不推进 cleanup 车道。
    assert await manager.cleanup_short_horizon(principal=SHORT_PRINCIPAL) == 0
    assert await cleanup_events() == 0
    assert await epoch() == before
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM short_horizon_chunks"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 1

    # 过了五天保留期：真的删掉 chunk ⇒ cleanup 车道恰好推进一次。
    removed = await manager.cleanup_short_horizon(
        principal=SHORT_PRINCIPAL, now=SHORT_NOW + 5 * 24 * 60 * 60
    )
    assert removed == 1
    assert await cleanup_events() == 1
    after = await epoch()
    async with backend.connection.execute(
        "SELECT event_kind FROM recall_authority_events WHERE principal_id=? "
        "AND authority_epoch=?",
        (SHORT_PRINCIPAL.actor_id, after),
    ) as cursor:
        assert str((await cursor.fetchone())[0]) == "short_horizon_cleanup"
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(*) FROM short_horizon_chunks),"
        "(SELECT COUNT(*) FROM short_horizon_fts),"
        "(SELECT COUNT(*) FROM conversation_evidence_registrations)"
    ) as cursor:
        assert tuple(await cursor.fetchone()) == (0, 0, 11)

    # 再清一次：零删除、epoch 不动（幂等），公共入口与内部车道同一语义。
    assert (
        await manager.cleanup_short_horizon(
            principal=SHORT_PRINCIPAL, now=SHORT_NOW + 6 * 24 * 60 * 60
        )
        == 0
    )
    assert await cleanup_events() == 1
    assert await epoch() == after
    # 直接调 backend 也一样（公共入口是纯转发，不是第二套语义）。
    assert (
        await backend.cleanup_short_horizon(
            principal=SHORT_PRINCIPAL, now=SHORT_NOW + 7 * 24 * 60 * 60
        )
        == 0
    )
    assert await epoch() == after
    await backend.close()


# --------------------------------------------------------------------------------------
# (c) apply validation 精确 reason 码
# --------------------------------------------------------------------------------------


async def _seed_memory(backend: SQLiteHumanMemoryBackend, envelope: object, span: object) -> str:
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return str(row[0])


async def _reason_codes(backend: SQLiteHumanMemoryBackend) -> list[str]:
    async with backend.connection.execute(
        "SELECT reason_code FROM memory_mutation_rejection_audits "
        "WHERE principal_id='actor-1' ORDER BY rejected_at,rejection_id"
    ) as cursor:
        return [str(row[0]) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_contest_rejections_map_one_to_one_to_stable_reason_codes(
    tmp_path: Path,
) -> None:
    """401 RUN-07 §3.1 D：三种 contest 拒绝不再共用一个泛化码。"""

    backend, envelope, span, authority = await _prepared(tmp_path / "contest-reasons.db")
    memory_id = await _seed_memory(backend, envelope, span)

    # 1) exact slot：payload 与在位版本逐字相同 → mutation_contest_exact_slot_required
    same = _operation(
        span,
        operation_id="contest-same",
        kind=MemoryMutationKind.CONTEST,
        target=ExistingMemoryTarget(memory_id, 1),
        conflict_status=ConflictStatus.CONTESTED,
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            envelope,
            same,
            base_revision=2,
            plan_id="contest-same-plan",
            idempotency_key="contest-same-key",
        ),
    )
    # 公共错误类与冻结枚举一字未动。
    assert result.outcome is MemoryMutationApplyOutcome.REJECTED
    assert result.reason_code is MemoryMutationApplyReasonCode.VALIDATION_REJECTED

    # 2) distinct evidence：payload 变了但复用在位证据 → mutation_contest_distinct_evidence_required
    reused = replace(
        _operation(
            span,
            operation_id="contest-reused-evidence",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload("user:self", "response_style", "verbose", ("default",)),
    )
    reused_result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            envelope,
            reused,
            base_revision=2,
            plan_id="contest-reused-plan",
            idempotency_key="contest-reused-key",
        ),
    )
    assert reused_result.reason_code is MemoryMutationApplyReasonCode.VALIDATION_REJECTED

    # 3) nested group：先建成一个 active group，再对同一条 head 二次 contest
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(challenger_envelope, challenger_receipt, challenger_span)
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="contest-ok",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload("user:self", "response_style", "verbose", ("default",)),
    )
    committed = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="contest-ok-plan",
            idempotency_key="contest-ok-key",
        ),
    )
    assert committed.outcome is MemoryMutationApplyOutcome.COMMITTED

    third_envelope, third_receipt = _admitted(evidence_id="evidence-3")
    third_span = _span(third_envelope, third_receipt)
    authority.register_admitted(third_envelope, third_receipt, third_span)
    await backend.ingest_committed_evidence(third_envelope, third_receipt)
    nested = replace(
        _operation(
            third_span,
            operation_id="contest-nested",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 2),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload("user:self", "response_style", "terse", ("default",)),
    )
    nested_result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            third_envelope,
            nested,
            base_revision=3,
            plan_id="contest-nested-plan",
            idempotency_key="contest-nested-key",
        ),
    )
    assert nested_result.reason_code is MemoryMutationApplyReasonCode.VALIDATION_REJECTED

    # durable 审计：三条精确码，一一对应，不再有 0.6.31 的两个泛化码。
    codes = await _reason_codes(backend)
    assert sorted(codes) == [
        "mutation_contest_distinct_evidence_required",
        "mutation_contest_exact_slot_required",
        "mutation_contest_nested_group_rejected",
    ]
    assert MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE not in codes
    assert MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE not in codes

    # 公共只读视图给出同一批码，并绑定 plan 与 apply 结果身份。
    notes = await backend.read_memory_mutation_validation_notes(principal=_principal())
    assert len(notes) == 3
    assert all(isinstance(note, MemoryMutationValidationNoteV1) for note in notes)
    by_plan = {note.plan_id: note for note in notes}
    assert by_plan["contest-same-plan"].reason_code == "mutation_contest_exact_slot_required"
    assert (
        by_plan["contest-reused-plan"].reason_code
        == "mutation_contest_distinct_evidence_required"
    )
    assert by_plan["contest-nested-plan"].reason_code == "mutation_contest_nested_group_rejected"
    assert by_plan["contest-same-plan"].apply_result_id == result.result_id
    assert by_plan["contest-same-plan"].apply_result_hash == result.result_hash
    assert by_plan["contest-nested-plan"].apply_result_hash == nested_result.result_hash
    # 过滤与上限。
    assert len(
        await backend.read_memory_mutation_validation_notes(
            principal=_principal(), plan_id="contest-nested-plan"
        )
    ) == 1
    assert len(
        await backend.read_memory_mutation_validation_notes(principal=_principal(), limit=1)
    ) == 1
    for bad in (0, 1001, "10", True):
        with pytest.raises((MemoryValidationError, TypeError)):
            await backend.read_memory_mutation_validation_notes(
                principal=_principal(), limit=bad  # type: ignore[arg-type]
            )
    await backend.close()


@pytest.mark.asyncio
async def test_non_contest_rejection_reason_code_is_unchanged(tmp_path: Path) -> None:
    """反例：不属于 contest 家族的拒绝仍走 0.6.31 的既有映射，一个字节都不变。"""

    from simple_harness.runtime import EpistemicStatus

    backend, envelope, span, _authority = await _prepared(tmp_path / "other-reason.db")
    bad = _operation(
        span,
        operation_id="unknown-source-bound",
        epistemic_status=EpistemicStatus.UNKNOWN,
    )
    with pytest.raises(MemoryValidationError, match="mutation_unknown_cannot_be_authoritative"):
        await backend.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=mutation_plan(
                envelope,
                bad,
                base_revision=2,
                plan_id="unknown-bad-plan",
                idempotency_key="unknown-bad-key",
            ),
        )
    codes = await _reason_codes(backend)
    assert codes == [MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE]
    # 泛化码的行不会出现在精确视图里。
    assert await backend.read_memory_mutation_validation_notes(principal=_principal()) == ()
    await backend.close()


# --------------------------------------------------------------------------------------
# (d) 执行 lane 见证
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executed_lane_witness_names_the_lane_that_produced_each_item(
    tmp_path: Path,
) -> None:
    """401 RUN-07 §3.1 E：公共面第一次能回答「这一项是哪条 lane 产生的」。"""

    from simple_harness.runtime import RecallRetrievalMode

    # 只请求词面：向量 lane 不参与。
    lexical_backend, _e, _s, _a = await _prepared(tmp_path / "lane-lexical.db")
    context = _context()
    execution = await lexical_backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-lane-lexical"),
    )
    assert len(execution.result.items) == 1
    assert execution.executed_lanes == ("full_text",)
    witness = execution.item_lane_witnesses[0]
    assert witness.item_id == execution.result.items[0].selected_item.item_id
    assert witness.ordinal == 1
    assert witness.source_kind == "cognitive_memory"
    assert witness.memory_type == "semantic"
    assert witness.lanes == ("full_text",)
    assert dict(witness.lane_ranks) == {"full_text": 1}
    assert witness.matched_lane_count == 1
    assert "vector" not in execution.executed_lanes
    # 见证不进任何 hash 域：result/decision 与不带见证时逐字相同。
    lexical_result_hash = execution.result.result_hash
    await lexical_backend.close()

    # 请求向量且有 embedder：vector lane 真的执行并产生该项。
    vector_backend, _e2, _s2, _a2 = await _prepared(
        tmp_path / "lane-vector.db", embedder=ControlledEmbedder()
    )
    await vector_backend.rebuild_cognitive_vector_generation()
    vector_context = _context(
        modes=(RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)
    )
    vector_execution = await vector_backend.execute_typed_recall(
        principal=_principal(),
        context=vector_context,
        plan=_recall_plan(vector_context, idempotency_key="idem-lane-vector"),
    )
    assert len(vector_execution.result.items) == 1
    vector_witness = vector_execution.item_lane_witnesses[0]
    assert "vector" in vector_witness.lanes
    assert vector_execution.executed_lanes[0] == "vector"
    # 冻结序：vector 永远排在 full_text 之前。
    if "full_text" in vector_witness.lanes:
        assert vector_witness.lanes.index("vector") < vector_witness.lanes.index("full_text")
    # 同一条记忆、同一 query：多命中一条 lane ⇒ RRF 分数更高、结果 hash 不同，
    # 说明见证反映的是**真的执行过**的 lane，而不是对请求 modes 的复述。
    assert vector_execution.result.items[0].score > execution.result.items[0].score
    assert vector_execution.result.result_hash != lexical_result_hash
    await vector_backend.close()

    # 幂等重放不带见证：重放只复述 durable 字节，本轮没有跑过任何 lane。
    replay_backend, _e3, _s3, _a3 = await _prepared(tmp_path / "lane-replay.db")
    replay_context = _context()
    first = await replay_backend.execute_typed_recall(
        principal=_principal(),
        context=replay_context,
        plan=_recall_plan(replay_context, idempotency_key="idem-lane-replay"),
    )
    assert first.item_lane_witnesses and first.replayed is False
    replay = await replay_backend.execute_typed_recall(
        principal=_principal(),
        context=replay_context,
        plan=_recall_plan(replay_context, idempotency_key="idem-lane-replay"),
    )
    assert replay.replayed is True
    assert replay.item_lane_witnesses == () and replay.executed_lanes == ()
    assert replay.result.result_hash == first.result.result_hash
    await replay_backend.close()


@pytest.mark.asyncio
async def test_rejected_execution_has_no_lane_witness(tmp_path: Path) -> None:
    """拒绝路径零候选访问 ⇒ 没有任何 lane 执行过，见证必须为空。"""

    from simple_harness.runtime import RecallRetrievalMode, RecallSelectorDomain

    backend, _e, _s, _a = await _prepared(tmp_path / "lane-rejected.db")
    context = _context(
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.EVENT),
        modes=(RecallRetrievalMode.EXACT, RecallRetrievalMode.GRAPH),
        event_refs=("event-1",),
    )
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-lane-rejected"),
    )
    assert execution.decision.outcome.value == "rejected"
    assert execution.candidate_query_started is False
    assert execution.item_lane_witnesses == () and execution.executed_lanes == ()
    await backend.close()
