"""0.6.37：冲突组的词面准入基底 = 槽位文本 ∪ head 的 subject_entity/qualifiers（F-V-2）。

缺陷来源：HM-TO-A6 run9（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/
DECISION-V-CONTEST-NOTICE.md` §4.4 / §6 F-V-2）。证据库 `native-a6-run9` 里，
`proofreading_script_python_version` 的争议组槽位文本插桩输出逐字是

    {"object_value":["Python 3.13","3.12"]}
    {"predicate":"proofreading_script_python_version"}

——**一个 CJK 字符都没有**。而 T22 的用户原句「那你现在按哪个版本执行这套校对流程？」
是纯中文，0.6.31 的准入基底（`contested_slot_text`）因此零命中；该 head 当时也只有
challenger 那一版进了向量世代（incumbent 版本随旧世代 retire），离线复核里向量车道
更是整条不可用，于是词面是唯一车道 → `confirmation_groups=0`，未裁决的冲突组全程
无人看见，模型拿对话里的旧值继续执行（A6-8 / NC-4 FAIL）。

0.6.37 把**冲突组的**词面准入基底扩展为 `contested_admission_text` =
`contested_slot_text` ∪ 该 group 所属 head 当前 revision 的 `subject_entity` /
`qualifiers`（head 的 `qualifiers`「在做资料校对时」才是用户真会说出口的那几个字）。
普通 item 车道不受影响；扩展只读**公开** payload，隐私门与 §5.2 整组原子性一字未改。

本模块以证据形状（槽位文本无 CJK、无向量世代、未裁决的冲突组、中文查询）钉死：
① 复现：中文用户原句 → `needs_user_confirmation` / items=0 / 1 组（main 上是 recall / 0 组）；
② 负控：无关中文闲聊 → 0 组，且不影响普通召回；
③ 两条正控：模型转述（逐字含「统一用 3.13，不是 3.12」）与谓词查询仍是 1 组；
④ 无向量世代时词面是唯一车道，扩展照样生效；
⑤ 兄弟记忆自己的词面永远不准入 group（0.6.31 的要害保留）；
⑥ 无冲突库：同一条中文查询照旧返回普通 items（普通车道逐字未变）；
⑦ §5.2 仍然优先：任一成员被抑制 → 整组连同「有冲突」这件事一起扣下，不退化成普通 item；
⑧ 纯函数：`contested_admission_text` 不传 head 即逐字等于 `contested_slot_text`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from simple_harness.runtime import RecallDecisionOutcome, RecallRetrievalMode

from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from simple_harness_memory.features.conflict_slot import (
    CONFLICT_ADMISSION_TEXT_VERSION,
    CONTESTED_HEAD_CONTEXT_FIELDS,
    contested_admission_text,
    contested_head_context_text,
    contested_slot_text,
)
from tests.integration.test_cognitive_vector_generation import (
    add_memory,
    manager_with,
    rows,
)
from tests.integration.test_typed_recall_v6 import (
    _context,
    _principal,
    _recall_plan,
)

LEXICAL_ONLY = (RecallRetrievalMode.FULL_TEXT,)
BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)

# 证据形状：槽位（predicate + 两侧取值）全是 ASCII，只有 qualifiers 是中文。
PREDICATE = "proofreading_script_python_version"
INCUMBENT_VALUE = "Python 3.13"
CHALLENGER_VALUE = "3.12"
QUALIFIER = "在做资料校对时"
CONTESTED = ("c-python", PREDICATE, INCUMBENT_VALUE, (QUALIFIER,))
# 兄弟记忆：自己的谓词与取值都与争议槽位无关（qualifiers 与 head 共享，与证据同形）。
SIBLING = ("c-closing", "reply_closing", "不要以“还有什么可以帮你”收尾", (QUALIFIER,))

# T22 的四条查询（逐字取自 Host 备忘 §2.2 / §2.4 与 run9 的对话正文）。
USER_TURN = "那你现在按哪个版本执行这套校对流程？"
UNRELATED_CHAT = "今天天气不错，随便聊聊"
MODEL_QUERY = (
    "用户问现在按哪个 Python 版本执行秋分资料整理的校对流程，"
    "依据本请求中刚给出的更正（统一用 3.13，不是 3.12）直接回答。"
)
PREDICATE_QUERY = "秋分资料整理校对流程所用的 Python 环境"


async def _contest(backend, authority, *, target_revision: int, base_revision: int) -> str:
    """把 head 争议成 `3.12`（与证据同形：challenger 是 head 的当前 revision）。"""

    from dataclasses import replace

    from simple_harness.runtime import (
        ConflictStatus,
        ExistingMemoryTarget,
        MemoryMutationKind,
        SemanticMemoryPayload,
    )

    from simple_harness_memory.core.identity import MemoryScope
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted,
        _operation,
        _span,
    )
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _plan as mutation_plan,
    )

    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads WHERE memory_type='semantic'"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])
    envelope, receipt = _admitted(evidence_id="evidence-contest")
    span = _span(envelope, receipt)
    authority.register_admitted(envelope, receipt, span)
    await backend.ingest_committed_evidence(envelope, receipt)
    contest = replace(
        _operation(
            span,
            operation_id="op-contest-python-version",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, target_revision),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload("user:self", PREDICATE, CHALLENGER_VALUE, (QUALIFIER,)),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            envelope,
            contest,
            base_revision=base_revision,
            plan_id="contest-python-version-plan",
            idempotency_key="contest-python-version-key",
        ),
    )
    return envelope.evidence_id


async def _evidence_store(path: Path):
    """证据形状的库：无 embedder（无向量世代）＋ 一条兄弟记忆 ＋ 未裁决的冲突组。"""

    manager, _envelope, _span, authority = await manager_with(
        path, None, operations=(CONTESTED,)
    )
    await add_memory(manager, authority, evidence_id="evidence-sibling", operation=SIBLING)
    challenger_evidence_id = await _contest(
        manager._backend, authority, target_revision=1, base_revision=3
    )
    return manager, challenger_evidence_id


async def _recall(manager, query: str, *, key: str, modes=LEXICAL_ONLY):
    context = _context(query=query, modes=modes)
    return await manager.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


def _predicates(execution) -> list[str]:
    return [str(item.public_payload["predicate"]) for item in execution.result.items]


@pytest.mark.asyncio
async def test_chinese_user_turn_admits_the_contested_group(tmp_path: Path) -> None:
    """① run9 复现：纯中文的用户原句必须要求确认（main 上是 recall / 0 组）。"""

    manager, _ = await _evidence_store(tmp_path / "user-turn.db")
    try:
        # 前提：槽位文本里一个 CJK 字符都没有（与证据插桩逐字同形）。
        slot = contested_slot_text(
            "semantic",
            {"subject_entity": "user:self", "predicate": PREDICATE,
             "object_value": INCUMBENT_VALUE, "qualifiers": [QUALIFIER]},
            {"subject_entity": "user:self", "predicate": PREDICATE,
             "object_value": CHALLENGER_VALUE, "qualifiers": [QUALIFIER]},
        )
        assert all(ord(ch) < 0x2E80 for ch in slot), slot
        execution = await _recall(manager, USER_TURN, key="v-user-turn")
        assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert execution.decision.selected_items == () and execution.result.items == ()
        assert len(execution.result.confirmation_groups) == 1
        members = execution.result.confirmation_groups[0].members
        assert [str(x.public_payload["object_value"]) for x in members] == [
            INCUMBENT_VALUE,
            CHALLENGER_VALUE,
        ]
        # 整组披露：两名成员都在，且都带 exact revision。
        assert [int(x.member.source_revision) for x in members] == [1, 2]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_unrelated_chinese_chat_stays_at_zero_groups(tmp_path: Path) -> None:
    """② 负控：无关闲聊既不准入 group，也不改变普通车道的结论。"""

    manager, _ = await _evidence_store(tmp_path / "negative.db")
    try:
        execution = await _recall(manager, UNRELATED_CHAT, key="v-negative")
        assert execution.result.confirmation_groups == ()
        assert execution.decision.confirmation_groups == ()
        assert execution.decision.outcome is RecallDecisionOutcome.NO_RECALL
        assert execution.result.items == ()
        assert execution.result.truncated is False
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_slot_text_queries_still_admit_the_group(tmp_path: Path) -> None:
    """③ 两条正控：模型转述与谓词查询在 0.6.31 上就能准入，0.6.37 后仍是 1 组。"""

    manager, _ = await _evidence_store(tmp_path / "positive.db")
    try:
        for key, query in (("v-model", MODEL_QUERY), ("v-predicate", PREDICATE_QUERY)):
            execution = await _recall(manager, query, key=key)
            assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION, key
            assert execution.result.items == ()
            assert len(execution.result.confirmation_groups) == 1, key
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_admission_holds_without_any_vector_generation(tmp_path: Path) -> None:
    """④ 无向量世代（CJK typed recall 缺陷）时词面是唯一车道，扩展照样生效。"""

    manager, _ = await _evidence_store(tmp_path / "no-vector.db")
    try:
        assert await rows(manager, "SELECT generation_id FROM cognitive_vector_generations") == []
        assert await rows(manager, "SELECT memory_id FROM cognitive_vectors") == []
        execution = await _recall(manager, USER_TURN, key="v-no-vector", modes=BOTH)
        assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert len(execution.result.confirmation_groups) == 1
        # 向量车道整条不可用（无 embedder），准入只可能来自词面。
        assert execution.degradation_codes == ("cognitive_vector_unavailable",)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_sibling_text_never_admits_the_group(tmp_path: Path) -> None:
    """⑤ 0.6.31 的要害保留：兄弟记忆**自己的**词面不把 group 拉进来。"""

    manager, _ = await _evidence_store(tmp_path / "sibling.db")
    try:
        for key, query in (("v-sib-pred", "reply_closing"), ("v-sib-value", "还有什么可以帮你")):
            execution = await _recall(manager, query, key=key)
            assert execution.decision.outcome is RecallDecisionOutcome.RECALL, key
            assert _predicates(execution) == ["reply_closing"], key
            assert execution.result.confirmation_groups == ()
            assert execution.result.truncated is False
            # 争议 head 从不作为普通 item 出现。
            assert PREDICATE not in _predicates(execution)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_ordinary_lane_is_unchanged_without_a_conflict_group(tmp_path: Path) -> None:
    """⑥ 无冲突库：同一条中文查询照旧走普通车道（本轮不碰普通 item 的词面准入）。"""

    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "plain.db", None, operations=(CONTESTED,)
    )
    try:
        await add_memory(manager, authority, evidence_id="evidence-sibling", operation=SIBLING)
        execution = await _recall(manager, USER_TURN, key="v-plain")
        assert execution.decision.outcome is RecallDecisionOutcome.RECALL
        assert execution.result.confirmation_groups == ()
        assert sorted(_predicates(execution)) == sorted([PREDICATE, "reply_closing"])
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_privacy_gate_still_withholds_the_whole_group(tmp_path: Path) -> None:
    """⑦ §5.2 优先于本轮扩展：一名成员被遗忘 → 整组连同「有冲突」一起扣下。"""

    manager, challenger_evidence_id = await _evidence_store(tmp_path / "privacy.db")
    backend = manager._backend
    try:
        await backend.suppress(
            SuppressionRequest(
                "forget-challenger",
                "actor-1",
                SuppressionScopeKind.EVIDENCE,
                challenger_evidence_id,
                "user_forget",
                20.0,
                OrdinaryMemoryPurpose.RECALL,
            )
        )
        execution = await _recall(manager, USER_TURN, key="v-privacy")
        assert execution.result.confirmation_groups == ()
        # 扣下的是整组：contested head 也不会退化成普通 item。
        assert PREDICATE not in _predicates(execution)
    finally:
        await manager.close()


def test_admission_text_is_slot_text_plus_head_context() -> None:
    """⑧ 纯函数：不传 head 逐字回退；传 head 只多 subject_entity/qualifiers 两行。"""

    incumbent = {"subject_entity": "user:self", "predicate": PREDICATE,
                 "object_value": INCUMBENT_VALUE, "qualifiers": [QUALIFIER]}
    challenger = {**incumbent, "object_value": CHALLENGER_VALUE}
    slot = contested_slot_text("semantic", incumbent, challenger)
    assert contested_admission_text("semantic", incumbent, challenger) == slot
    widened = contested_admission_text(
        "semantic", incumbent, challenger, head_payload=challenger
    )
    assert widened.startswith(slot) and QUALIFIER in widened and "user:self" in widened
    assert widened == contested_admission_text(
        "semantic", incumbent, challenger, head_payload=challenger
    )
    # head 上下文只有这两个字段：取值（争议内容）不因为 head 而多进来一遍。
    head_text = contested_head_context_text("semantic", challenger)
    assert CONTESTED_HEAD_CONTEXT_FIELDS == ("subject_entity", "qualifiers")
    assert CHALLENGER_VALUE not in head_text and PREDICATE not in head_text
    assert head_text.splitlines() == [
        '{"subject_entity":"user:self"}',
        '{"qualifiers":["在做资料校对时"]}',
    ]
    # fail closed：未知类型 / 非 Mapping / None。
    assert contested_head_context_text("relation", challenger) == ""
    assert contested_head_context_text("semantic", None) == ""
    assert contested_head_context_text("semantic", "bad") == ""  # type: ignore[arg-type]
    assert (
        contested_admission_text("relation", incumbent, challenger, head_payload=challenger) == ""
    )
    assert CONFLICT_ADMISSION_TEXT_VERSION == 1
