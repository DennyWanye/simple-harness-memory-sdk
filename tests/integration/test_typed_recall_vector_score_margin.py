"""0.6.34 认知向量准入：同型相对判据 + 绝对护栏（DECISION-2026-09-09-vector-score-margin.md）。

缺陷来源：Host `simple_harness/plans/2026-09-07-corpus-c01-local/RUN-RERUN-FLASH-01-REVIEW.md`
§五缺陷 3——同一条中文短 semantic 记忆的两次合理改写余弦 **0.4354 / 0.5839** 跨在
`COGNITIVE_VECTOR_MIN_SCORE = 0.45` 两侧，召回成败取决于模型措辞抖动。

本文件用**合成向量**精确复现那一对分数，并钉死四条义务：
① 0.4354 一侧不再落空（同型相对救援）；② ≥ 0.45 的判定逐字不变（pin）；
③ 整库都不相关时不救援（零召回护栏）；④ 相对参照按记忆类型分组，
一个类型的强匹配不得压掉另一个类型的最佳匹配；⑤ 本次生效下限落 typed recall 审计。
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.runtime import (
    EpisodeLifecycleState,
    EpisodeMemoryPayload,
    LongTermMemoryType,
    RecallRetrievalMode,
    SemanticMemoryPayload,
)

from simple_harness_memory import MemoryScope, build_human_memory_v7
from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_VECTOR_MIN_SCORE,
    COGNITIVE_VECTOR_RELATIVE_FLOOR,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_cognitive_vector_generation import DIM, ControlledEmbedder, rows
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)

# Host 复核给出的那一对余弦（评审表 §五缺陷 3）。
FLASH_PARAPHRASE = 0.4354
LUNA_PARAPHRASE = 0.5839
# Host C06-06 的形状：procedure 0.6017 压掉 semantic 0.3690（此处用 episode 代 procedure，
# 该例要证明的是"跨类型压制"，与具体是哪一个非目标类型无关）。
STRONG_OTHER_TYPE = 0.6017
WEAK_TARGET = 0.3690

QUERY = "阈值余量查询"
QUERY_FLASH = "改写一 说明事情时先报结果还是先铺背景 用户的表达习惯"
QUERY_LUNA = "改写二 用户之前关于说明事情时应先报结果还是先铺背景的约定或偏好"


def _axis_vector(cosine: float) -> list[float]:
    """与 ``_query_vector`` 的余弦恰为 ``cosine`` 的单位向量。"""

    return [cosine, math.sqrt(max(0.0, 1.0 - cosine * cosine))] + [0.0] * (DIM - 2)


def _query_vector() -> list[float]:
    return [1.0] + [0.0] * (DIM - 1)


def _semantic_op(span, operation_id: str, predicate: str, value: str):
    return replace(
        _operation(span, operation_id=operation_id),
        payload=SemanticMemoryPayload("user:self", predicate, value, ()),
    )


def _episode_op(span, operation_id: str, title: str):
    return replace(
        _operation(span, operation_id=operation_id),
        memory_type=LongTermMemoryType.EPISODE,
        payload=EpisodeMemoryPayload(title, ("user:self",), (), (), (), (), 10.0, 11.0, "thread-1"),
        lifecycle_state=EpisodeLifecycleState.ACTIVE,
    )


async def _manager(path: Path, embedder: ControlledEmbedder, factories):
    """``manager_with`` 的本地变体：允许把非 semantic 的 operation 放进同一个计划。"""

    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    manager = await build_human_memory_v7(
        path,
        clock=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
        short_horizon_embedder=embedder,
        allow_development_embedder=True,
    )
    await manager.ingest_committed_evidence(envelope, receipt)
    result = await manager.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, *(factory(span) for factory in factories)),
    )
    assert result.outcome.value == "committed"
    return manager


async def _recall(manager, *, key: str, memory_types, query: str = QUERY):
    context = _context(query=query, modes=BOTH, memory_types=memory_types)
    return await manager.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


def _values(execution) -> list[str]:
    return sorted(
        str(item.public_payload.get("object_value") or item.public_payload.get("title"))
        for item in execution.result.items
    )


async def _admission(manager, key: str) -> dict:
    found = await rows(
        manager,
        "SELECT t.terminal_json FROM typed_recall_terminals t "
        "JOIN typed_recall_requests r ON r.request_id=t.request_id "
        "WHERE json_extract(r.request_json,'$.plan.idempotency_key')=?",
        key,
    )
    assert len(found) == 1, found
    body = json.loads(str(found[0][0]))
    return body["cognitive_vector"]["admission"]


def _effective(admission: dict) -> dict[str, float]:
    return {row["memory_type"]: row["value"] for row in admission["effective_min_score"]}


@pytest.mark.asyncio
async def test_both_reasonable_paraphrases_now_recall_the_same_memory(tmp_path: Path) -> None:
    """C01-19：0.4354 与 0.5839 不再跨在阈值两侧——召回不再取决于措辞抖动。

    同一条记忆、同一个向量世代，只换查询：两次改写的余弦精确复现 Host 复核的那一对。
    """

    embedder = ControlledEmbedder(
        extra={
            "explanation order": _axis_vector(1.0),
            QUERY_FLASH: _axis_vector(FLASH_PARAPHRASE),
            QUERY_LUNA: _axis_vector(LUNA_PARAPHRASE),
        }
    )
    manager = await _manager(
        tmp_path / "paraphrase.db",
        embedder,
        (lambda span: _semantic_op(span, "c19", "explanation_order", "先说结论再说理由"),),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        # ① flash 改写（0.4354）：0.6.33 下低于 0.45 被整条丢弃，0.6.34 下作为该类型最高分被救援。
        assert FLASH_PARAPHRASE < COGNITIVE_VECTOR_MIN_SCORE <= LUNA_PARAPHRASE
        flash = await _recall(
            manager, key="flash", memory_types=(LongTermMemoryType.SEMANTIC,), query=QUERY_FLASH
        )
        assert _values(flash) == ["先说结论再说理由"]
        assert flash.degradation_codes == ()
        effective = _effective(await _admission(manager, "flash"))
        assert effective["semantic"] == pytest.approx(0.9 * FLASH_PARAPHRASE, abs=1e-6)
        # ② luna 改写（0.5839）：本来就 ≥ 0.45，生效下限被钳回冻结绝对阈值（pin）。
        luna = await _recall(
            manager, key="luna", memory_types=(LongTermMemoryType.SEMANTIC,), query=QUERY_LUNA
        )
        assert _values(luna) == ["先说结论再说理由"]
        luna_effective = _effective(await _admission(manager, "luna"))
        assert luna_effective["semantic"] == COGNITIVE_VECTOR_MIN_SCORE
        # ③ 词面通道确实救不了：两次改写与 payload 零重叠（评审表"词法通道没有兜底"）。
        assert flash.result.items[0].public_payload["object_value"] == "先说结论再说理由"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_relative_rescue_never_reaches_below_the_absolute_floor(tmp_path: Path) -> None:
    """整库最高分也只有 0.30：没有任何候选被救援（C07 零召回护栏）。"""

    embedder = ControlledEmbedder(
        extra={
            "explanation order": _axis_vector(0.30),
            "preferred name": _axis_vector(0.12),
            QUERY: _query_vector(),
        }
    )
    manager = await _manager(
        tmp_path / "floor.db",
        embedder,
        (
            lambda span: _semantic_op(span, "far", "explanation_order", "远端负控"),
            lambda span: _semantic_op(span, "farther", "preferred_name", "更远负控"),
        ),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        execution = await _recall(manager, key="floor", memory_types=(LongTermMemoryType.SEMANTIC,))
        assert execution.result.items == () and execution.result.confirmation_groups == ()
        assert execution.degradation_codes == ()
        floor_effective = _effective(await _admission(manager, "floor"))
        assert floor_effective["semantic"] == COGNITIVE_VECTOR_RELATIVE_FLOOR
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_only_near_ties_within_the_same_type_are_rescued(tmp_path: Path) -> None:
    """同类型内落后最高分超过 10% 的候选不进 lane——救援不是"放开一个更低的绝对阈值"。"""

    embedder = ControlledEmbedder(
        extra={
            "explanation order": _axis_vector(0.4354),  # 该类型最高分
            "preferred name": _axis_vector(0.4200),  # 0.4354×0.90 = 0.39186 之上 → 救援
            "reply closing": _axis_vector(0.3600),  # 之下但仍高于绝对护栏 → 不救援
            QUERY: _query_vector(),
        }
    )
    manager = await _manager(
        tmp_path / "near.db",
        embedder,
        (
            lambda span: _semantic_op(span, "top", "explanation_order", "最高分"),
            lambda span: _semantic_op(span, "near", "preferred_name", "并列"),
            lambda span: _semantic_op(span, "far", "reply_closing", "落后"),
        ),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        execution = await _recall(manager, key="near", memory_types=(LongTermMemoryType.SEMANTIC,))
        assert _values(execution) == ["并列", "最高分"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_relative_reference_is_scoped_to_one_memory_type(tmp_path: Path) -> None:
    """C06-06 的形状：0.6017 的 episode 不得压掉 0.3690 的 semantic。"""

    embedder = ControlledEmbedder(
        extra={
            "无障碍培训检查": _axis_vector(STRONG_OTHER_TYPE),
            "图表说明": _axis_vector(WEAK_TARGET),
            QUERY: _query_vector(),
        }
    )
    manager = await _manager(
        tmp_path / "pertype.db",
        embedder,
        (
            lambda span: _episode_op(span, "strong", "无障碍培训检查"),
            lambda span: _semantic_op(span, "weak", "图表说明", "要配文字说明"),
        ),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        execution = await _recall(
            manager,
            key="pertype",
            memory_types=(LongTermMemoryType.SEMANTIC, LongTermMemoryType.EPISODE),
        )
        assert _values(execution) == ["无障碍培训检查", "要配文字说明"]
        admission = await _admission(manager, "pertype")
        assert admission["min_score"] == COGNITIVE_VECTOR_MIN_SCORE
        assert admission["relative_floor"] == COGNITIVE_VECTOR_RELATIVE_FLOOR
        assert admission["relative_ratio"] == 0.90
        effective = _effective(admission)
        # episode 的最高分 0.6017 → 0.90× 越过 0.45 被钳回绝对阈值；semantic 落到绝对护栏。
        assert effective["episode"] == COGNITIVE_VECTOR_MIN_SCORE
        assert effective["semantic"] == COGNITIVE_VECTOR_RELATIVE_FLOOR
        # 若相对参照是全局最高分（0.6017），semantic 的下限会是 0.5415，目标必然落空。
        assert WEAK_TARGET < 0.90 * STRONG_OTHER_TYPE
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_admission_block_is_absent_without_a_vector_lane(tmp_path: Path) -> None:
    """未请求 vector 的召回终态逐字不变（不引入新键 → 终态 hash 不变）。"""

    embedder = ControlledEmbedder(
        extra={"explanation order": _axis_vector(0.80), QUERY: _query_vector()}
    )
    manager = await _manager(
        tmp_path / "lexical.db",
        embedder,
        (lambda span: _semantic_op(span, "c19", "explanation_order", "先说结论再说理由"),),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        context = _context(
            query=QUERY,
            modes=(RecallRetrievalMode.FULL_TEXT,),
            memory_types=(LongTermMemoryType.SEMANTIC,),
        )
        await manager.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="lexical"),
        )
        found = await rows(
            manager,
            "SELECT t.terminal_json FROM typed_recall_terminals t "
            "JOIN typed_recall_requests r ON r.request_id=t.request_id "
            "WHERE json_extract(r.request_json,'$.plan.idempotency_key')='lexical'",
        )
        assert "cognitive_vector" not in json.loads(str(found[0][0]))
    finally:
        await manager.close()
