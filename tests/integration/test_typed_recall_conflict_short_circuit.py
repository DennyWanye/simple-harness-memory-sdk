"""0.6.31：争议 group 的槽位级准入（F-O-3）与 confirmation 成员的历史绑定（F-O-1）。

缺陷来源：HM-TO-A6 run4（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/
DECISION-CONTESTED-DISCLOSURE.md` §1.4 / §7 F-O-1 / F-O-3）：13 条记忆的库里只有一个
未决 conflict group，任何提到同一主题的查询都被短路成 confirmation-only，
`items=()`，与争议槽位无关的记忆全部召不回。

裁决见 `plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-08-conflict-short-circuit.md`：
冻结的 Harness ``RecallDecisionV4`` 一次只能带 items 或 groups 之一，所以 group 的准入
从"任一 lane 命中"收窄到"槽位级相关"——词面只看两名成员取值不同的字段 + semantic
predicate；向量要求争议记忆是同类型里离查询最近的语义匹配；entity/task_scope/temporal
只过滤与排序，不单独准入。

本模块钉死：
① 争议槽位 + 兄弟记忆自己的词面 → 普通 items 照常返回、无 group、不标 truncated；
   （0.6.37 / F-V-2 把 head 自己的 subject/qualifiers 重新纳入 group 准入基底，
   故 "default"/"user:self" 这两条查询改为 confirmation-only，见本文件 ① 与
   `DECISION-2026-09-09-contested-group-admission-basis.md`）；
② 争议槽位 + 相关查询（predicate / incumbent 值 / challenger 值）→ confirmation-only（items 为空）；
③ 向量 lane：争议记忆不是最近匹配 → items；是最近匹配 → confirmation（词面零命中）；
④ confirmation 成员可作为 `HistoryRecallBinding` 通过历史可见性；hash 篡改 → mismatch；
   任一成员的证据被遗忘 → 整组 stale；typed-short source 展开对成员仍拒；
⑤ 无冲突库的 decision/result/page/receipt/terminal hash 与 0.6.29 源逐字节相同（钉死字面值）；
⑥ `contested_slot_text` 纯函数：只含差异字段 + 槽位名，不含共享的 subject/qualifiers。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from simple_harness.contracts import fingerprint_json
from simple_harness.runtime import (
    ContextFragmentBindingV2,
    RecallContextUseAuthorizationRequestV1,
    RecallDecisionOutcome,
    RecallItemBindingV1,
    RecallReasonCode,
    RecallResultPageRequestV1,
    RecallRetrievalMode,
)

import simple_harness_memory as m
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from simple_harness_memory.features.conflict_slot import contested_slot_text
from tests.integration.test_cognitive_vector_generation import (
    ControlledEmbedder,
    add_memory,
    manager_with,
    rows,
)
from tests.integration.test_typed_recall_v6 import (
    _contest_semantic,
    _context,
    _disclosure,
    _principal,
    _recall_plan,
)

LEXICAL_ONLY = (RecallRetrievalMode.FULL_TEXT,)
BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)

# 争议槽位：response_style（incumbent "concise" ↔ challenger "verbose"，
# qualifiers 都是 ("default",)）。
CONTESTED = ("c-style", "response_style", "concise", ("default",))
# 同主题（user:self）、同 qualifiers 的无关槽位。
UNRELATED = ("c-closing", "reply_closing", "不要以“还有什么可以帮你”收尾", ("default",))


async def _contested_store(path: Path, embedder=None, *, unrelated=UNRELATED):
    manager, _envelope, _span, authority = await manager_with(
        path, embedder, operations=(CONTESTED,)
    )
    challenger_evidence_id = await _contest_semantic(manager._backend, authority)
    await add_memory(manager, authority, evidence_id="evidence-3", operation=unrelated)
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
async def test_sibling_text_returns_items_and_head_text_admits_the_group(tmp_path: Path) -> None:
    """① F-O-3 的一半保留、另一半被 0.6.37 有意反转。

    保留（run4 原型的要害）：**兄弟记忆自己的**词面（`reply_closing` 与它的取值）
    永远不会把 group 拉进来，因此与争议槽位无关的记忆照常作为普通 item 返回。

    反转（0.6.37 / F-V-2，`DECISION-2026-09-09-contested-group-admission-basis.md`）：
    group 所属 **head 自己的** `subject_entity`/`qualifiers` 重新成为词面准入基底，
    所以 "default" / "user:self" 这两条查询回到 confirmation-only。这是本轮明知的代价：
    槽位文本可能一个 CJK 字符都没有（run9 的 `{"object_value":["Python 3.13","3.12"]}`），
    那时 head 的 qualifiers 才是用户真会说出口的那几个字。
    """

    manager, _ = await _contested_store(tmp_path / "unrelated.db")
    try:
        for key, query in (("q-closing", "reply_closing"),
                           ("q-closing-value", "还有什么可以帮你")):
            execution = await _recall(manager, query, key=key)
            assert execution.decision.outcome is RecallDecisionOutcome.RECALL, (key, query)
            assert _predicates(execution) == ["reply_closing"], (key, query)
            assert execution.decision.confirmation_groups == ()
            assert execution.result.confirmation_groups == ()
            # 未准入的 group 不是候选，不算被预算跳过。
            assert execution.result.truncated is False
            assert RecallReasonCode.NEEDS_USER_CONFIRMATION not in execution.result.reason_codes
            assert execution.candidate_query_count == 1
            # 争议 head 本身从不作为普通 item 出现。
            assert "response_style" not in _predicates(execution)
        # head 自己的 qualifiers / subject_entity：0.6.31 不准入，0.6.37 准入。
        for key, query in (("q-default", "default"), ("q-subject", "user:self")):
            head_text = await _recall(manager, query, key=key)
            assert head_text.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION, key
            assert head_text.result.items == () and head_text.decision.selected_items == ()
            assert len(head_text.result.confirmation_groups) == 1, key
        # 完全无关的查询仍是 NO_RECALL（group 也不会被"顺带"披露）。
        nothing = await _recall(manager, "nothing-matches-anything", key="q-none")
        assert nothing.decision.outcome is RecallDecisionOutcome.NO_RECALL
        assert nothing.result.items == () and nothing.result.confirmation_groups == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_slot_related_query_is_confirmation_only(tmp_path: Path) -> None:
    """② predicate / incumbent 值 / challenger 值 任一命中 → 只走完整 group confirmation。"""

    manager, _ = await _contested_store(tmp_path / "related.db")
    try:
        for key, query in (("q-pred", "response_style"), ("q-inc", "concise"),
                           ("q-chal", "verbose"),
                           ("q-mixed", "concise 与 default 与 reply_closing")):
            execution = await _recall(manager, query, key=key)
            assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION, key
            assert execution.decision.selected_items == () and execution.result.items == ()
            assert len(execution.result.confirmation_groups) == 1
            members = execution.result.confirmation_groups[0].members
            values = [str(x.public_payload["object_value"]) for x in members]
            assert values == ["concise", "verbose"]
            assert RecallReasonCode.NEEDS_USER_CONFIRMATION in execution.result.reason_codes
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_vector_lane_admits_group_only_as_nearest_match(tmp_path: Path) -> None:
    """③ 词面零命中时，group 只有作为同类型最近语义匹配才准入。"""

    embedder = ControlledEmbedder()
    # 无关记忆同时落在"结尾"(轴 1) 与"简洁"(轴 6) 两条轴上。
    manager, _ = await _contested_store(
        tmp_path / "vector.db", embedder, unrelated=("c-closing", "reply_closing", "结尾要简洁", ())
    )
    try:
        built = await manager.rebuild_cognitive_vector_generation()
        # 0.6.38（F-V-2a）：incumbent + challenger + 无关 head。0.6.37 只有后两条。
        assert built.vector_count == 3
        # 查询同时落在两条轴上：无关记忆 cos=1.0，challenger（只在轴 6）cos≈0.707 ≥ 阈值但不是最近。
        nearer_elsewhere = await _recall(manager, "收尾要简洁点", key="v-elsewhere", modes=BOTH)
        assert nearer_elsewhere.decision.outcome is RecallDecisionOutcome.RECALL
        assert _predicates(nearer_elsewhere) == ["reply_closing"]
        assert nearer_elsewhere.result.confirmation_groups == ()
        assert nearer_elsewhere.degradation_codes == ()
        # 查询只落在轴 6：challenger cos=1.0 > 无关记忆 0.707 → group 是最近匹配 → confirmation。
        # 词面控制：槽位文本（response_style/concise/verbose）零命中 → 无 group；
        # "简洁"词面命中的是无关记忆"结尾要简洁"，作为普通 item 返回。
        lexical_only = await _recall(manager, "简洁还是啰嗦", key="v-lexical", modes=LEXICAL_ONLY)
        assert lexical_only.result.confirmation_groups == ()
        assert _predicates(lexical_only) == ["reply_closing"]
        nearest = await _recall(manager, "简洁还是啰嗦", key="v-nearest", modes=BOTH)
        assert nearest.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert nearest.result.items == () and len(nearest.result.confirmation_groups) == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_confirmation_member_binding_survives_history_visibility(tmp_path: Path) -> None:
    """④ F-O-1：成员绑定可见；hash 篡改 mismatch；一侧证据被遗忘 → 整组 stale；source 展开仍拒。"""

    manager, challenger_evidence_id = await _contested_store(tmp_path / "binding.db")
    backend = manager._backend
    try:
        execution = await _recall(manager, "concise", key="h-confirm")
        assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        members = execution.result.confirmation_groups[0].members
        bindings = tuple(
            m.HistoryRecallBinding(
                execution.result.result_id, execution.result.result_hash,
                member.member.item_id, member.result_member_hash,
            )
            for member in members
        )
        visible = await backend.check_history_visibility(
            principal=_principal(), disclosure_context=_disclosure(), bindings=bindings
        )
        assert [item.visible for item in visible.items] == [True, True]
        assert [item.reason for item in visible.items] == ["history_visible", "history_visible"]

        # 成员 hash 篡改：与普通 item 一样 mismatch；成员 id 换成普通 item 的 hash 形状也 mismatch。
        tampered = m.HistoryRecallBinding(
            bindings[0].result_id, bindings[0].result_hash, bindings[0].item_id, "0" * 64
        )
        mismatch = await backend.check_history_visibility(
            principal=_principal(), disclosure_context=_disclosure(), bindings=(tampered,)
        )
        assert mismatch.items[0].reason == "history_binding_mismatch"

        # typed-short source 展开只接受 short-horizon selected item：成员仍拒。
        sources = await manager.resolve_typed_short_horizon_sources(
            principal=_principal(), disclosure_context=_disclosure(), bindings=bindings[:1]
        )
        assert sources.items[0].visible is False
        assert sources.items[0].reason == "history_binding_mismatch"

        # 遗忘 challenger 的证据：incumbent 自身未被抑制，但 §5.2 整组原子 → 两个绑定都 stale。
        await backend.suppress(
            SuppressionRequest(
                "forget-challenger", "actor-1", SuppressionScopeKind.EVIDENCE,
                challenger_evidence_id, "user_forget", 20.0, OrdinaryMemoryPurpose.RECALL,
            )
        )
        stale = await backend.check_history_visibility(
            principal=_principal(), disclosure_context=_disclosure(), bindings=bindings
        )
        assert [item.reason for item in stale.items] == ["history_source_stale"] * 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_no_conflict_store_hashes_are_byte_identical_to_0_6_29(tmp_path: Path) -> None:
    """⑤ 无冲突库：decision/result/page/receipt/terminal hash 与 0.6.29 源逐字相同。

    字面值由 `scratchpad/hashes.py` 在 0.6.29 worktree（`simple-harness-memory-sdk-0629-source`）
    与本分支各跑一次得到，`diff` 为空；这里钉死，保证"普通候选先收集"的重排与 group 准入
    收窄没有触碰任何 hash 域。
    """

    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "plain.db", None, operations=(CONTESTED,)
    )
    try:
        await add_memory(manager, authority, evidence_id="evidence-3", operation=UNRELATED)
        expected = {
            "plain-1": ("recall",
                        "f75d7c333b40c28dc3e6fa49f0ecd8c620937c61abf3d22e44124d7bdf1a6e35",
                        "b92dbbe76ba9b47593b3ebcf88ea618e03e56a4cf764308fe69305f12a1fd8db", 1),
            "plain-2": ("recall",
                        "5844c6e0cc96469a0297c7759798f71d499cda4c7fdcd15d3efd81da68e86e25",
                        "318ce563bd9054513c14f8d302dbd9cadeacb4c8b0338bcb93caae085f58daf1", 2),
            "plain-3": ("no_recall",
                        "d7f5c68a3b6236e20df210a75aaf93bef0449b2d10f3180b3f31a24c757589f2",
                        "10415fafdeae7be8aab8b215129d080adec7dd2d0378ec340b6444a01f63a610", 0),
        }
        expected_pages = {
            "plain-1": "9e0549a80619617cdec7058a42021848d3e1aa8fc56113ff3b19159bd9e2be1d",
            "plain-2": "4c711b2569e07a6b325711499015b16282a227a867e0ed1f51775e5790454cf2",
        }
        expected_receipts = {
            "plain-1": ("recall-context-use-receipt-"
                        "bba5e3e561d36070a058978aa8a1e849f115536bd480666a15329de8e7942034",
                        "e23e52feb9cf9c25632017e0bec58c36c646efc5d13199cf95fd75d202acc9df"),
            "plain-2": ("recall-context-use-receipt-"
                        "608249c4b1675dae094dcca209c653519e9a3c372f62d3508aa84ef2adcff82f",
                        "f973498863a61ade196e8fe10e80d82d87636fa952a5ed39c6d41c6eb042e492"),
        }
        for key, query in (("plain-1", "concise"), ("plain-2", "default"),
                           ("plain-3", "nothing-matches")):
            context = _context(query=query)
            execution = await manager.execute_typed_recall(
                principal=_principal(), context=context,
                plan=_recall_plan(context, idempotency_key=key),
            )
            assert (
                execution.decision.outcome.value, execution.decision.decision_hash,
                execution.result.result_hash, len(execution.result.items),
            ) == expected[key], key
            assert execution.result.truncated is False
            if not execution.result.items:
                continue
            page = await manager.page_typed_recall_result(
                principal=_principal(),
                request=RecallResultPageRequestV1(
                    execution.result.result_id, execution.result.result_hash, 1, 0, 8, 16_384, 20.0
                ),
            )
            assert page.page_hash == expected_pages[key], key
            fragment = ContextFragmentBindingV2("fragment-plain", "c" * 64)
            receipt = await manager.authorize_recall_context_use(
                principal=_principal(),
                request=RecallContextUseAuthorizationRequestV1(
                    "actor-1", context.run_id, context.turn_id, f"provider-{key}",
                    execution.decision.decision_id, execution.decision.decision_hash,
                    execution.result.result_id, execution.result.result_hash,
                    tuple(
                        RecallItemBindingV1(i.selected_item.item_id, i.result_item_hash)
                        for i in execution.result.items
                    ),
                    (fragment,), fingerprint_json([fragment.to_json()]), 20.0,
                ),
                now=20.0,
            )
            assert (receipt.receipt_id, receipt.receipt_hash) == expected_receipts[key], key
        terminals = await rows(
            manager,
            "SELECT terminal_hash FROM typed_recall_terminals ORDER BY created_at, request_id",
        )
        assert [row[0] for row in terminals] == [
            "aab2d2c97ab37e3c559c6bb44710b3c7850358b293d5dda1fc2a642a59660579",
            "b1fba1e14a8aa620ec2af9f314bdb21b895b1a280ead56447eccde2c2f767ca4",
            "f9cdd3361baa2adc02db88f6f2ed76d45b02d12c42b939616afd39a1130ec0d3",
        ]
    finally:
        await manager.close()


def test_contested_slot_text_only_carries_differing_fields_and_slot_name() -> None:
    """⑥ 纯函数：差异字段 + semantic predicate；共享的 subject/qualifiers 不进入；未知类型空串。"""

    incumbent = {"subject_entity": "秋分资料整理校对流程",
                 "predicate": "proofreading_python_version",
                 "object_value": "Python 3.13", "qualifiers": ["做资料校对时"]}
    challenger = {**incumbent, "object_value": "3.12"}
    text = contested_slot_text("semantic", incumbent, challenger)
    assert "Python 3.13" in text and "3.12" in text and "proofreading_python_version" in text
    assert "秋分资料整理校对流程" not in text and "做资料校对时" not in text
    assert text == contested_slot_text("semantic", incumbent, challenger)  # 确定性
    # 只有 qualifiers 不同：qualifiers 进入，object 不进入，predicate 仍进入。
    only_qualifiers = contested_slot_text(
        "semantic", incumbent, {**incumbent, "qualifiers": ["周末"]}
    )
    assert "周末" in only_qualifiers and "Python 3.13" not in only_qualifiers
    assert "proofreading_python_version" in only_qualifiers
    # episode：只有差异字段；无槽位名字段。
    episode = contested_slot_text(
        "episode",
        {"title": "同一件事", "results": ["成功"]},
        {"title": "同一件事", "results": ["失败"]},
    )
    assert "成功" in episode and "失败" in episode and "同一件事" not in episode
    # prospective：trigger 不同时追加两侧确定性渲染（周几/时分）。
    prospective = contested_slot_text(
        "prospective",
        {"action": "索取修正版", "trigger": {"trigger_kind": "time", "trigger_at": 1788742800.0,
                                          "timezone": "Asia/Shanghai"}},
        {"action": "索取修正版", "trigger": {"trigger_kind": "time", "trigger_at": 1788829200.0,
                                          "timezone": "Asia/Shanghai"}},
    )
    assert "索取修正版" not in prospective and "提醒" in prospective
    assert contested_slot_text("relation", incumbent, challenger) == ""
    assert contested_slot_text("semantic", "bad", challenger) == ""  # type: ignore[arg-type]
