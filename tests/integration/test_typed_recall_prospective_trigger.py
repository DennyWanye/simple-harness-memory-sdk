"""0.6.26 prospective 触发条件的自然语言渲染：词面/向量两条 lane 都能看到「周X + 提醒」。

语料 run-01f C04 实证：跑道修好 ``prospective_scheduler_registrations.state='accepted'``
之后，「我还留了什么周一要做的提醒？」仍然零召回。公开 payload 的 trigger 只有 epoch 数字
（``1788742800.0``）、时区名与 ``time`` 枚举，与中文查询既无词面重叠也无向量邻近，四条 lane
全空，候选在 ``_collect_typed_recall_candidates`` 的 ``if not lane_values: continue`` 处被丢弃。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    LongTermMemoryType,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveSignalKind,
    ProspectiveTimeTrigger,
    RecallDecisionOutcome,
    RecallRetrievalMode,
)

from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_TEXT_FORMAT_VERSION,
    COGNITIVE_VECTOR_MIN_SCORE,
    cognitive_text_supplement,
    cognitive_vector_text,
    prospective_trigger_text,
)
from simple_harness_memory.features.lexical import typed_recall_query_terms
from tests.integration.test_cognitive_vector_generation import ControlledEmbedder
from tests.integration.test_prospective_signal_repository_v5 import (
    _grant as prospective_grant,
)
from tests.integration.test_prospective_signal_repository_v5 import (
    _setup as prospective_setup,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

# 2026-09-07 09:00 Asia/Shanghai（周一）。C04-01 的种子提醒。
TRIGGER_AT = 1788742800.0
ACTION = "索取修正版"
QUERY = "周五验样结果如何？我还留了什么周一要做的提醒？现在只列，不执行。"


def _payload(trigger_at: float = TRIGGER_AT, timezone: str = "Asia/Shanghai") -> dict:
    return {
        "action": ACTION,
        "trigger": {
            "trigger_kind": "time",
            "trigger_at": trigger_at,
            "timezone": timezone,
        },
    }


async def _accepted_prospective(path: Path, clock: list[float], *, embedder=None):
    """一条同形的 pending prospective + accepted 注册（trigger_hash 一致）。"""

    trigger = ProspectiveTimeTrigger(TRIGGER_AT, "Asia/Shanghai")
    backend, authority, memory_id, revision, outbox_id, outbox_hash = (
        await prospective_setup(
            path,
            clock,
            payload=ProspectiveMemoryPayload(ACTION, trigger),
            embedder=embedder,
        )
    )
    accepted = prospective_grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=clock[0],
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
        trigger=trigger,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    return backend, memory_id, revision


async def _recall(backend, *, key: str, modes, query: str = QUERY):
    context = _context(
        query=query,
        memory_types=(LongTermMemoryType.PROSPECTIVE,),
        modes=modes,
    )
    return await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


def test_trigger_text_is_deterministic_and_localized() -> None:
    rendered = prospective_trigger_text(_payload()["trigger"])
    assert rendered == "2026-09-07 周一 09:00 定时提醒 待办"
    assert rendered == prospective_trigger_text(dict(_payload()["trigger"]))
    # 同一 epoch 换时区：本地日期/星期/时刻随之变化，格式与固定词不变。
    assert (
        prospective_trigger_text(_payload(timezone="UTC")["trigger"])
        == "2026-09-07 周一 01:00 定时提醒 待办"
    )
    assert (
        prospective_trigger_text(_payload(timezone="America/New_York")["trigger"])
        == "2026-09-06 周日 21:00 定时提醒 待办"
    )
    # 一周七天各自的中文星期（同一时区、逐日 +86400）。
    weekdays = [
        prospective_trigger_text(_payload(trigger_at=TRIGGER_AT + 86400.0 * day)["trigger"])
        .split(" ")[1]
        for day in range(7)
    ]
    assert weekdays == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def test_trigger_text_covers_event_kind_and_refuses_unknown_shapes() -> None:
    assert (
        prospective_trigger_text(
            {
                "trigger_kind": "event",
                "event_authority_ref": "host:calendar",
                "condition": "样品到货",
                "condition_hash": "0" * 64,
            }
        )
        == "事件提醒 待办"
    )
    # 未知/缺失 kind、非 Mapping：不臆造语义，返回空串（旧形状不变）。
    for trigger in (None, "time", 3, [], {}, {"trigger_kind": "cron"}, {"kind": "time"}):
        assert prospective_trigger_text(trigger) == ""
    # kind 可渲染但时刻不可渲染时，仍给出 kind 的中文词。
    for broken in (None, True, "1788742800", float("nan"), math.inf, 10.0**30):
        assert (
            prospective_trigger_text(
                {"trigger_kind": "time", "trigger_at": broken, "timezone": "Asia/Shanghai"}
            )
            == "定时提醒 待办"
        )
    # 未知时区名退回 UTC，仍然确定性。
    assert (
        prospective_trigger_text(
            {"trigger_kind": "time", "trigger_at": TRIGGER_AT, "timezone": "Mars/Olympus"}
        )
        == "2026-09-07 周一 01:00 定时提醒 待办"
    )


def test_vector_text_keeps_action_first_and_supplement_before_raw_trigger() -> None:
    text = cognitive_vector_text("prospective", _payload())
    assert text.split("\n") == [
        ACTION,
        "2026-09-07 周一 09:00 定时提醒 待办",
        "Asia/Shanghai",
        "1788742800.0",
        "time",
    ]
    # 其余类型没有补充文本，向量文本逐字不变。
    for memory_type, payload in (
        ("semantic", {"subject_entity": "user:self", "predicate": "a_b", "object_value": "v"}),
        ("episode", {"title": "T", "goals": ["g"], "actions": [], "results": ["r"]}),
        ("procedure", {"name": "n", "applicability": ["a"], "steps": ["s"]}),
    ):
        assert cognitive_text_supplement(memory_type, payload) == ""
    unchanged = cognitive_vector_text("semantic", {"subject_entity": "u", "predicate": "a_b"})
    assert unchanged == "u\na b"


@pytest.mark.asyncio
async def test_zero_lexical_prospective_is_recalled_after_trigger_text(tmp_path: Path) -> None:
    clock = [20.0]
    backend, memory_id, _revision = await _accepted_prospective(
        tmp_path / "c04-lexical.db", clock
    )
    try:
        # 修前的词面基线：只有公开 payload 的 canonical JSON 时，命中数为 0。
        terms = typed_recall_query_terms(QUERY)
        payload = _payload()
        assert sum(canonical_json(payload).casefold().count(term) for term in terms) == 0
        # 加上渲染后同一查询有命中（周一 / 提醒）。
        with_supplement = "\n".join(
            (canonical_json(payload), cognitive_text_supplement("prospective", payload))
        ).casefold()
        assert sum(with_supplement.count(term) for term in terms) > 0

        execution = await _recall(
            backend, key="c04-lexical", modes=(RecallRetrievalMode.FULL_TEXT,)
        )
        assert execution.decision.outcome is RecallDecisionOutcome.RECALL
        assert [item.selected_item.source_ref for item in execution.result.items] == [memory_id]
        item = execution.result.items[0]
        assert item.selected_item.memory_type == "prospective"
        # 公开 payload 形状不变：渲染只进入检索文本，不进入返回给 Host 的 payload。
        assert set(item.public_payload) == {"action", "trigger"}
        assert item.public_payload["action"] == ACTION
        assert item.public_payload["trigger"] == payload["trigger"]
        # 与提醒无关的中文查询仍然零召回（渲染不是万能通行证）。
        other = await _recall(
            backend,
            key="c04-lexical-negative",
            modes=(RecallRetrievalMode.FULL_TEXT,),
            query="上周的机票报销进度怎么样了？",
        )
        assert other.decision.outcome is RecallDecisionOutcome.NO_RECALL
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_prospective_enters_vector_lane_through_rendered_trigger(tmp_path: Path) -> None:
    embedder = ControlledEmbedder(extra={"待办": [0.0] * 5 + [1.0, 0.0, 0.0]})
    clock = [20.0]
    backend, memory_id, _revision = await _accepted_prospective(
        tmp_path / "c04-vector.db", clock, embedder=embedder
    )
    try:
        built = await backend.rebuild_cognitive_vector_generation()
        assert built.vector_count == 1 and built.activated
        # 世代文本正是带渲染的向量文本。
        assert any("定时提醒 待办" in text for text in embedder.embedded)
        # 查询里没有任何 payload 词面，只有"待办"这一概念轴与渲染重合。
        # 只开 vector 模式：词面 lane 不参与，命中只可能来自渲染后的向量。
        execution = await _recall(
            backend,
            key="c04-vector",
            modes=(RecallRetrievalMode.VECTOR,),
            query="待办",
        )
        assert execution.decision.outcome is RecallDecisionOutcome.RECALL
        item = execution.result.items[0]
        assert item.selected_item.source_ref == memory_id
        assert set(item.public_payload) == {"action", "trigger"}
        # 修前的向量文本（action + 时区 + epoch + time）与同一查询余弦为 0，低于阈值。
        before = embedder.vector_for("\n".join((ACTION, "Asia/Shanghai", "1788742800.0", "time")))
        query_vector = embedder.vector_for("待办")
        assert sum(a * b for a, b in zip(before, query_vector)) < COGNITIVE_VECTOR_MIN_SCORE
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_text_format_version_makes_old_generation_stale(tmp_path: Path) -> None:
    embedder = ControlledEmbedder(extra={"待办": [0.0] * 5 + [1.0, 0.0, 0.0]})
    clock = [20.0]
    backend, _memory_id, _revision = await _accepted_prospective(
        tmp_path / "c04-manifest.db", clock, embedder=embedder
    )
    try:
        built = await backend.rebuild_cognitive_vector_generation()
        async with backend.connection.execute(
            "SELECT content_hash FROM cognitive_vector_generations WHERE state='active'"
        ) as cursor:
            active = str((await cursor.fetchone())[0])
        assert active == await backend._current_cognitive_vector_manifest_hash_unlocked()

        head_rows = await backend._cognitive_vector_head_rows_unlocked()
        pinned = backend._cognitive_vector_manifest_hash(head_rows)
        # 渲染格式版本进入 manifest：版本一变，旧世代的 content_hash 不再等于当前 manifest，
        # vector lane 退化为 stale，下一次构建整代重建（不会继续用旧向量）。
        import simple_harness_memory.backends.sqlite_v5 as backend_module

        original = backend_module.COGNITIVE_TEXT_FORMAT_VERSION
        try:
            backend_module.COGNITIVE_TEXT_FORMAT_VERSION = original + 1
            assert backend._cognitive_vector_manifest_hash(head_rows) != pinned
            stale = await backend._current_cognitive_vector_manifest_hash_unlocked()
            assert stale != active
            rebuilt = await backend.rebuild_cognitive_vector_generation()
            assert rebuilt.generation_id != built.generation_id and not rebuilt.replayed
        finally:
            backend_module.COGNITIVE_TEXT_FORMAT_VERSION = original
        assert COGNITIVE_TEXT_FORMAT_VERSION == 2
        async with backend.connection.execute(
            "SELECT state,COUNT(*) FROM cognitive_vector_generations GROUP BY state "
            "ORDER BY state"
        ) as cursor:
            states = {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
        assert states == {"active": 1, "retired": 1}
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_rendered_trigger_never_reaches_the_public_payload(tmp_path: Path) -> None:
    clock = [20.0]
    backend, memory_id, revision = await _accepted_prospective(
        tmp_path / "c04-payload.db", clock
    )
    try:
        async with backend.connection.execute(
            "SELECT action_text,trigger_json FROM prospective_records "
            "WHERE memory_id=? AND revision=?",
            (memory_id, revision),
        ) as cursor:
            row = await cursor.fetchone()
        assert str(row[0]) == ACTION
        assert json.loads(str(row[1])) == _payload()["trigger"]
    finally:
        await backend.close()
