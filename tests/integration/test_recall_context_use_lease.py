"""0.6.38 用途围栏：租约到期是降级，不是硬 stale（F-AA-2）。

事故（Host 备忘 ``simple_harness/plans/2026-09-08-hm-to-a6/
DECISION-AA-AUTHORITY-STALE-RECOLLECT.md`` §2/§9(2)，HM-TO-A6 T18）：一轮工具循环里
12 次 provider 请求，前 11 次都在租约内正常出收据，第 12 次比
``RecallContext.expires_at``（Host 定的 ``moment + 60 s``）晚了 **4.96 秒**，围栏抛
``RECALL_AUTHORITY_STALE`` → ``run.fail``。那一刻 7 条被绑定来源逐条未变
（revision / content_hash / 抑制 / 披露全对得上）。

裁定：``effective_now >= result.authority_expires_at`` 从硬失败判据里移出。理由是结构性的，
不是"放宽一点"——``authority_expires_at`` = min(``RecallContext.expires_at``, 每条被绑定
来源自己的期限)，而后者在 ``_validate_recall_context_use_sources_unlocked`` 里逐条被重新
执行（认知记忆 ``valid_from <= now < valid_to``，短时域 chunk ``now < expires_at``）。
租约唯一多挡住的就是 Host 那个 60 秒的召回上下文期限，它只能杀掉"跑超过一分钟的正常回合"。

本模块钉死：

1. 租约到期 + epoch 未动 + 来源全通过 → 签发收据 + ``authority_lease_expired`` 说明；
2. 续发的收据租约长度等于原租约长度、起点是本次授权时刻，且**不得越过来源自己的期限**；
3. 负控一：被绑定来源被取代（head 前进）→ 租约到期也照旧 ``RECALL_AUTHORITY_STALE``、零收据；
4. 负控二：被绑定来源被压制 → 同上；
5. 负控三：policy version 变化 → 同上（租约降级不给它开任何口子）；
6. 租约**未**到期的路径一个字节没动：不出说明，收据 ``expires_at`` 仍是结果的租约；
7. 同时"epoch 前进 + 租约到期"时导出两条说明，次序固定。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from simple_harness.runtime import ValidTimeInterval

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.recall_context_use import (
    RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
    RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED,
)
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
from tests.integration.test_recall_authority_epoch_lanes import (
    _prepared_with_embedder,
    _use_request,
)
from tests.integration.test_recall_context_use_fence import (
    _apply_unrelated_memory,
    _receipt_rows,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

# T18 的形状：租约到期之后一小段（事故里是 4.96 s）才组装下一次 provider 请求。
PAST_LEASE_SECONDS = 4.96


async def _prepared_with_source_valid_to(path: Path, valid_to: float):
    """与 ``_prepared_with_embedder`` 同一世界，只是那条记忆自己带一个有效期上界。

    ``cognitive_memory_revisions`` 行由触发器锁成不可变（``immutable cognitive revision``），
    所以有效期只能在写入时给定——这一点本身也是 0.6.38 向量世代"自证 manifest"成立的前提。
    """

    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
        short_horizon_embedder=ControlledEmbedder(),
    )
    await backend.initialize()
    await backend.ingest_committed_evidence(envelope, receipt)
    operation = dataclasses.replace(
        _operation(span), valid_time_interval=ValidTimeInterval(None, valid_to)
    )
    result = await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, operation),
    )
    assert result.outcome.value == "committed"
    return backend


async def _recalled(backend, key: str):
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )
    return context, execution, execution.result.items[0]


@pytest.mark.asyncio
async def test_expired_lease_with_unchanged_sources_now_authorizes(tmp_path: Path) -> None:
    """① 事故本身：只有时钟越过了租约，来源一条没变 → 出收据，并留下租约到期说明。"""

    backend, _envelope, _span = await _prepared_with_embedder(
        tmp_path / "lease-expired.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-expired")
    bound_lease = execution.result.authority_expires_at
    bound_epoch = execution.result.authority_epoch
    authorized_at = bound_lease + PAST_LEASE_SECONDS

    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-past-lease"),
        now=authorized_at,
    )
    assert receipt.authorized_at == authorized_at
    assert receipt.authority_epoch == bound_epoch  # epoch 一步没动，只是租约到了

    # ② 续发的租约：长度 = 原租约长度，起点 = 本次授权时刻。
    assert receipt.expires_at == authorized_at + (bound_lease - execution.result.evaluated_at)

    notes = await backend.read_recall_context_use_authority_notes(principal=_principal())
    assert [note.reason_code for note in notes] == [
        RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED
    ]
    note = notes[0]
    assert note.bound_authority_expires_at == bound_lease
    assert note.authorized_at == authorized_at
    assert note.bound_authority_epoch == note.authority_epoch == bound_epoch
    assert note.receipt_id == receipt.receipt_id
    assert note.receipt_hash == receipt.receipt_hash
    assert note.result_id == execution.result.result_id
    # 说明只由两条不可变行导出：收据的 authorized_at 与结果的 authority_expires_at。
    assert await _receipt_rows(backend) == [(receipt.receipt_id, bound_epoch)]

    # 幂等重放：同一 provider attempt 逐字返回同一张收据，说明不重复。
    replay = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-past-lease"),
        now=authorized_at + 1.0,
    )
    assert replay.receipt_hash == receipt.receipt_hash
    assert len(
        await backend.read_recall_context_use_authority_notes(principal=_principal())
    ) == 1
    await backend._validate_integrity()
    await backend.close()


@pytest.mark.asyncio
async def test_renewed_lease_never_outlives_the_source_itself(tmp_path: Path) -> None:
    """② 续租的硬上界是**来源自己**的期限，不是 Host 那个 60 秒。"""

    # 被绑定记忆自己的有效期在续租窗口内结束：续租不得越过它。
    source_valid_to = 100.0 + PAST_LEASE_SECONDS + 1.0
    backend = await _prepared_with_source_valid_to(
        tmp_path / "lease-source-bound.db", source_valid_to
    )
    context, execution, item = await _recalled(backend, "idem-lease-source-bound")
    bound_lease = execution.result.authority_expires_at
    authorized_at = bound_lease + PAST_LEASE_SECONDS
    assert authorized_at < source_valid_to < authorized_at + (
        bound_lease - execution.result.evaluated_at
    )

    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-source-bound"),
        now=authorized_at,
    )
    assert receipt.expires_at == source_valid_to
    assert receipt.expires_at < authorized_at + (
        bound_lease - execution.result.evaluated_at
    )

    # 越过来源自己的有效期之后，逐来源重校验照旧 fail closed。
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-source-gone"),
            now=source_valid_to,
        )
    await backend.close()


@pytest.mark.asyncio
async def test_expired_lease_with_superseded_source_still_fences(tmp_path: Path) -> None:
    """③ 负控：租约到期 **且** 被绑定来源被取代 → 仍然 ``RECALL_AUTHORITY_STALE``、零收据。"""

    backend, _envelope, _span = await _prepared_with_embedder(
        tmp_path / "lease-superseded.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-superseded")
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
            now=execution.result.authority_expires_at + PAST_LEASE_SECONDS,
        )
    assert await _receipt_rows(backend) == []
    assert await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    ) == ()
    await backend.close()


@pytest.mark.asyncio
async def test_expired_lease_with_suppressed_source_still_fences(tmp_path: Path) -> None:
    """④ 负控：租约到期 **且** 被绑定来源被遗忘 → 同一稳定码拒绝、零收据。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "lease-suppressed.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-suppressed")
    await _apply_unrelated_memory(backend, envelope, span)
    await backend.suppress(
        SuppressionRequest(
            "suppress-bound-lease",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            item.selected_item.source_ref,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-suppressed"),
            now=execution.result.authority_expires_at + PAST_LEASE_SECONDS,
        )
    assert await _receipt_rows(backend) == []
    await backend.close()


@pytest.mark.asyncio
async def test_expired_lease_does_not_excuse_a_policy_change(tmp_path: Path) -> None:
    """⑤ 负控：租约降级不给 policy version 变化开任何口子。"""

    backend, _envelope, _span = await _prepared_with_embedder(
        tmp_path / "lease-policy.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-policy")

    async def _authority(_principal_id: str) -> tuple[int, str]:
        return execution.result.authority_epoch, "b" * 64

    backend._recall_authority_unlocked = _authority  # type: ignore[method-assign]
    with pytest.raises(MemoryValidationError, match="^RECALL_AUTHORITY_STALE$"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=_use_request(execution, context, item, "provider-attempt-policy"),
            now=execution.result.authority_expires_at + PAST_LEASE_SECONDS,
        )
    assert await _receipt_rows(backend) == []
    await backend.close()


@pytest.mark.asyncio
async def test_lease_still_running_is_byte_for_byte_unchanged(tmp_path: Path) -> None:
    """⑥ 未受影响路径：租约还在跑时收据的 expires_at 仍是结果的租约，且零说明。"""

    backend, _envelope, _span = await _prepared_with_embedder(
        tmp_path / "lease-running.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-running")
    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-running"),
        now=20.0,
    )
    assert receipt.expires_at == execution.result.authority_expires_at
    assert await backend.read_recall_context_use_authority_notes(
        principal=_principal()
    ) == ()
    await backend._validate_integrity()
    await backend.close()


@pytest.mark.asyncio
async def test_epoch_advance_and_lease_expiry_export_two_notes(tmp_path: Path) -> None:
    """⑦ 两件事同时发生：一张收据导出两条说明，次序固定（epoch 前进 → 租约到期）。"""

    backend, envelope, span = await _prepared_with_embedder(
        tmp_path / "lease-and-epoch.db", ControlledEmbedder()
    )
    context, execution, item = await _recalled(backend, "idem-lease-and-epoch")
    bound_epoch = execution.result.authority_epoch
    await _apply_unrelated_memory(backend, envelope, span)
    receipt = await backend.authorize_recall_context_use(
        principal=_principal(),
        request=_use_request(execution, context, item, "provider-attempt-both"),
        now=execution.result.authority_expires_at + PAST_LEASE_SECONDS,
    )
    notes = await backend.read_recall_context_use_authority_notes(principal=_principal())
    assert [note.reason_code for note in notes] == [
        RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
        RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED,
    ]
    assert {note.receipt_id for note in notes} == {receipt.receipt_id}
    assert notes[0].bound_authority_expires_at is None
    assert notes[0].authority_epoch == bound_epoch + 1
    assert notes[1].bound_authority_expires_at == execution.result.authority_expires_at
    await backend.close()
