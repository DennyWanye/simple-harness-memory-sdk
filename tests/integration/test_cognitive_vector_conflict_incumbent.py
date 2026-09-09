"""0.6.38 认知向量世代：争议组的 incumbent 也进世代；head 一变不再让整库退化。

缺陷来源：0.6.37 备忘 `DECISION-2026-09-09-contested-group-admission-basis.md` §5.1 的
两条附带查清（Host 事件 V 的 (a)），本轮升级为交付项：

* **F-V-2a**：``_cognitive_vector_head_rows_unlocked`` 只取 ``r.revision =
  h.current_revision``，因此未裁决冲突组的 **incumbent 成员（上一版）永远拿不到向量分**，
  group 的向量准入只可能由 challenger 单方面贡献——与 S3 §5.2「整组同进同出」不对称。
* **F-V-2b**：head 一变 manifest 立刻对不上，从该次修订到下一次世代激活之间
  （HM-TO-A6 实测 3.4 s / 15.2 s）**整库**的认知向量车道都是 ``cognitive_vector_stale``，
  而争议轮恰好紧随修订。

本模块钉死：
① incumbent 的向量真的能把 group 准入（查询离 incumbent 取值最近、词面零命中）——
   0.6.37 上 incumbent 没有向量、challenger 余弦为 0，该查询只能得到零候选；
② 争议刚落库、世代还没重建的那一格：**无关记忆**照常经向量车道召回，
   退化码是 ``cognitive_vector_partial`` 而不是 ``cognitive_vector_stale``；
③ 组被裁决之后 incumbent 立刻退出世代（准入条件与 confirmation 取组查询逐字一致）；
④ 无冲突组的库：head 清单与 0.6.37 逐字同序同集合，manifest hash 一个字节不变
   （= 这类库升级到 0.6.38 不触发任何世代重建）。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    ConflictStatus,
    EvidenceSupportKind,
    ExistingMemoryTarget,
    MemoryMutationKind,
    RecallDecisionOutcome,
    RecallRetrievalMode,
    SemanticMemoryPayload,
)

from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_TEXT_FORMAT_VERSION,
    COGNITIVE_VECTOR_PARTIAL,
    COGNITIVE_VECTOR_STALE,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _operation,
    _span,
    _with_action_authorities,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _plan as mutation_plan,
)
from tests.integration.test_cognitive_vector_generation import (
    DIM,
    ControlledEmbedder,
    _unit,
    add_memory,
    manager_with,
    rows,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)
LEXICAL_ONLY = (RecallRetrievalMode.FULL_TEXT,)

# 争议槽位：incumbent "concise" ↔ challenger "verbose"（`_contest_semantic` 的形状）。
CONTESTED = ("c-style", "response_style", "concise", ("default",))
# 无关记忆，落在"称呼"那条轴上。
UNRELATED = ("c06", "preferred_name", "小周", ("default",))

# 把两名成员放到**不同**的轴上（默认的 CONCEPTS 把 concise/verbose 压在同一条轴，
# 那样分不出到底是谁贡献了分数），并给查询一个只命中 incumbent 那条轴的锚词。
MEMBER_AXES = {"concise": _unit(5), "verbose": _unit(6), "锚词甲": _unit(5)}
# 只落在 incumbent 轴上、且与槽位文本零词面重合的查询。
INCUMBENT_QUERY = "锚词甲"


async def _contest(manager, authority, memory_id: str, *, evidence_id: str = "evidence-2"):
    """``test_typed_recall_v6._contest_semantic`` 的显式目标版本。

    库里有不止一条 semantic head 时那个帮手会任取一条；本模块的 ② 必须先有无关记忆
    再起争议，所以目标必须点名。除 ``target``/证据 id 外与它逐字相同。
    """

    envelope, receipt = _admitted(evidence_id=evidence_id)
    span = _span(envelope, receipt)
    authority.register_admitted(envelope, receipt, span)
    await manager._backend.ingest_committed_evidence(envelope, receipt)
    async with manager._backend.connection.execute(
        "SELECT current_revision FROM cognitive_memory_heads WHERE memory_id=?",
        (memory_id,),
    ) as cursor:
        head_revision = int((await cursor.fetchone())[0])
    async with manager._backend.connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"
    ) as cursor:
        base_revision = int((await cursor.fetchone())[0])
    contest = replace(
        _operation(
            span,
            operation_id=f"contest-{evidence_id}",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, head_revision),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload("user:self", "response_style", "verbose", ("default",)),
    )
    result = await manager.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            envelope,
            contest,
            base_revision=base_revision,
            plan_id=f"contest-plan-{evidence_id}",
            idempotency_key=f"contest-key-{evidence_id}",
        ),
    )
    assert result.outcome.value == "committed"


async def _semantic_head(manager, predicate: str) -> str:
    found = await rows(
        manager,
        "SELECT h.memory_id FROM cognitive_memory_heads h JOIN semantic_claims s "
        "ON s.memory_id=h.memory_id AND s.revision=h.current_revision WHERE s.predicate=?",
        predicate,
    )
    assert len(found) == 1, found
    return str(found[0][0])


async def _recall(manager, query: str, *, key: str, modes=BOTH):
    context = _context(query=query, modes=modes)
    return await manager.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


async def _generation_refs(manager) -> list[tuple[str, int]]:
    active = await rows(
        manager, "SELECT generation_id FROM cognitive_vector_generations WHERE state='active'"
    )
    assert len(active) == 1
    return [
        (str(item[0]), int(item[1]))
        for item in await rows(
            manager,
            "SELECT memory_id,revision FROM cognitive_vectors WHERE generation_id=? "
            "ORDER BY memory_id,revision",
            str(active[0][0]),
        )
    ]


@pytest.mark.asyncio
async def test_incumbent_vector_admits_the_group(tmp_path: Path) -> None:
    """① incumbent 的向量把未裁决的 group 准入（0.6.37 上这一查询零候选）。"""

    embedder = ControlledEmbedder(extra=MEMBER_AXES)
    manager, _base_envelope, _base_span, authority = await manager_with(
        tmp_path / "incumbent.db", embedder, operations=(CONTESTED,)
    )
    try:
        memory_id = await _semantic_head(manager, "response_style")
        await _contest(manager, authority, memory_id)
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == 2
        assert await _generation_refs(manager) == [(str(memory_id), 1), (str(memory_id), 2)]

        # 词面控制：锚词不在槽位文本、也不在 head 的 subject/qualifiers 里 → 词面零准入。
        lexical = await _recall(manager, INCUMBENT_QUERY, key="anchor-lexical", modes=LEXICAL_ONLY)
        assert lexical.result.confirmation_groups == () and lexical.result.items == ()

        # 向量：incumbent 余弦 1.0、challenger 0.0 → 只可能是 incumbent 把 group 准入。
        vector = await _recall(manager, INCUMBENT_QUERY, key="anchor-vector")
        assert vector.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert vector.result.items == ()
        assert len(vector.result.confirmation_groups) == 1
        members = vector.result.confirmation_groups[0].members
        assert sorted(member.member.source_revision for member in members) == [1, 2]
        assert vector.degradation_codes == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_contest_window_keeps_unrelated_memories_on_the_vector_lane(
    tmp_path: Path,
) -> None:
    """② 争议刚落库、世代还没重建的那十几秒：无关记忆不该被连坐成 stale。"""

    embedder = ControlledEmbedder(extra=MEMBER_AXES)
    manager, _base_envelope, _base_span, authority = await manager_with(
        tmp_path / "contest-window.db", embedder, operations=(CONTESTED,)
    )
    try:
        await add_memory(manager, authority, evidence_id="evidence-3", operation=UNRELATED)
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == 2  # 两条 head，尚无冲突组

        # 争议落库：head 前进 → 世代清单立刻对不上（维护 tick 还没跑）。
        await _contest(
            manager,
            authority,
            await _semantic_head(manager, "response_style"),
            evidence_id="evidence-4",
        )

        # 无关记忆的中文同义查询：词面零命中，只能靠向量。
        unrelated_query = "用户最后明确确认的称呼、称谓偏好"
        lexical = await _recall(manager, unrelated_query, key="window-lexical", modes=LEXICAL_ONLY)
        assert lexical.result.items == ()
        window = await _recall(manager, unrelated_query, key="window-vector")
        assert [
            str(item.public_payload["object_value"]) for item in window.result.items
        ] == ["小周"]
        assert window.degradation_codes == (COGNITIVE_VECTOR_PARTIAL,)
        assert COGNITIVE_VECTOR_STALE not in window.degradation_codes

        # 维护 tick 跑完之后退化码归零，且世代补上了两名冲突成员。
        rebuilt = await manager.rebuild_cognitive_vector_generation()
        assert rebuilt.vector_count == 3
        fresh = await _recall(manager, unrelated_query, key="window-fresh")
        assert fresh.degradation_codes == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_resolved_group_drops_the_incumbent_from_the_generation(
    tmp_path: Path,
) -> None:
    """③ 组一旦被裁决，incumbent 立刻退出世代（与 confirmation 取组条件同一判据）。"""

    embedder = ControlledEmbedder(extra=MEMBER_AXES)
    manager, _base_envelope, _base_span, authority = await manager_with(
        tmp_path / "resolved.db", embedder, operations=(CONTESTED,)
    )
    try:
        await _contest(manager, authority, await _semantic_head(manager, "response_style"))
        assert (await manager.rebuild_cognitive_vector_generation()).vector_count == 2
        group = (await rows(
            manager,
            "SELECT group_id,principal_id,memory_id,challenger_revision "
            "FROM cognitive_conflict_groups",
        ))[0]
        # 走真实的裁决路径（REVISE + conflict_status=resolved），而不是往
        # cognitive_conflict_resolutions 里塞一行——后者过不了 close 时的完整性校验。
        envelope, receipt = _admitted(evidence_id="evidence-3")
        span = replace(
            _span(envelope, receipt),
            support_kind=EvidenceSupportKind.EXPLICIT_USER_CORRECTION,
        )
        authority.register_admitted(envelope, receipt, span)
        await manager._backend.ingest_committed_evidence(envelope, receipt)
        resolve = replace(
            _operation(
                span,
                operation_id="resolve-to-incumbent",
                kind=MemoryMutationKind.REVISE,
                target=ExistingMemoryTarget(str(group[2]), int(group[3])),
                conflict_status=ConflictStatus.RESOLVED,
            ),
            payload=SemanticMemoryPayload(
                "user:self", "response_style", "concise", ("default",)
            ),
            reason_code="explicit_user_correction",
        )
        base_revision = int((await rows(
            manager, "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"
        ))[0][0])
        result = await manager.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_with_action_authorities(
                mutation_plan(
                    envelope, resolve, base_revision=base_revision,
                    plan_id="resolve-plan", idempotency_key="resolve-key",
                ),
                authority,
                nonce_prefix="resolve",
            ),
        )
        assert result.outcome.value == "committed"
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_conflict_resolutions") == [(1,)]
        resolved = await manager.rebuild_cognitive_vector_generation()
        # 裁决后 head 是新的 r3，组不再 active → 世代只剩 head 一条，incumbent 退出。
        assert resolved.vector_count == 1
        assert await _generation_refs(manager) == [(str(group[2]), int(group[3]) + 1)]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_conflict_free_store_keeps_the_0_6_37_manifest_byte_for_byte(
    tmp_path: Path,
) -> None:
    """④ 没有未裁决冲突组时 manifest 一个字节没变 → 已有库升级不触发任何世代重建。"""

    embedder = ControlledEmbedder()
    manager, _base_envelope, _base_span, authority = await manager_with(
        tmp_path / "conflict-free.db", embedder, operations=(UNRELATED,)
    )
    try:
        await add_memory(
            manager, authority, evidence_id="evidence-3",
            operation=("c17", "email_draft_length", "最多两段", ("邮件草稿",)),
        )
        backend = manager._backend
        head_rows = await backend._cognitive_vector_head_rows_unlocked()
        # 0.6.37 的取法：只取 head 的当前 revision，``ORDER BY h.memory_id``。
        async with backend.connection.execute(
            "SELECT r.*,h.memory_type AS memory_type FROM cognitive_memory_heads h "
            "JOIN cognitive_memory_revisions r "
            "ON r.memory_id=h.memory_id AND r.revision=h.current_revision "
            "ORDER BY h.memory_id"
        ) as cursor:
            legacy_rows = tuple(await cursor.fetchall())
        assert [
            (str(row["memory_id"]), int(row["revision"])) for row in head_rows
        ] == [(str(row["memory_id"]), int(row["revision"])) for row in legacy_rows]
        legacy_manifest = hashlib.sha256(
            canonical_json(
                {
                    "text_format_version": COGNITIVE_TEXT_FORMAT_VERSION,
                    "heads": [
                        {
                            "memory_id": str(row["memory_id"]),
                            "revision": int(row["revision"]),
                            "content_hash": str(row["content_hash"]),
                        }
                        for row in legacy_rows
                    ],
                }
            ).encode()
        ).hexdigest()
        assert (
            await backend._current_cognitive_vector_manifest_hash_unlocked()
            == legacy_manifest
        )
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == len(legacy_rows) == 2
        # 世代的**自证** manifest 与入库的 content_hash 逐字相等（可用性的全部条件）。
        assert (
            await backend._cognitive_vector_generation_manifest_hash_unlocked(
                str(built.generation_id)
            )
            == legacy_manifest
        )
        assert DIM  # 保持与 ControlledEmbedder 同一维度约定
    finally:
        await manager.close()
