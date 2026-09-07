"""0.6.23 typed recall 长期认知记忆 ``vector`` lane（DECISION-2026-09-07 §4.3.2）。

覆盖：五种 C01 FAIL 形状（同义中文查询 / 英文 predicate + 纯值 payload）在词面 0 下经 vector 命中；
抑制优先；disclosure 拒绝优先；阈值负控；stale / 无世代 / 无 embedder / 查询嵌入超时退化且词面照常；
confirmation 门接受 vector 命中；退化码与世代 hash 持久化；未请求 vector 零副作用。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from simple_harness.contracts import canonical_json
from simple_harness.runtime import (
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    IntendedAudience,
    RecallDecisionOutcome,
    RecallRetrievalMode,
)

from simple_harness_memory.backends import sqlite_v5
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from simple_harness_memory.features.cognitive_vector import (
    COGNITIVE_VECTOR_DEADLINE,
    COGNITIVE_VECTOR_MIN_SCORE,
    COGNITIVE_VECTOR_NO_GENERATION,
    COGNITIVE_VECTOR_STALE,
    COGNITIVE_VECTOR_UNAVAILABLE,
)
from simple_harness_memory.features.lexical import typed_recall_query_terms
from tests.integration.test_cognitive_vector_generation import (
    DIM,
    ControlledEmbedder,
    add_memory,
    manager_with,
    rows,
)
from tests.integration.test_typed_recall_v6 import (
    _contest_semantic,
    _context,
    _principal,
    _recall_plan,
)

BOTH = (RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)
LEXICAL_ONLY = (RecallRetrievalMode.FULL_TEXT,)

# 五种 C01 FAIL 形状：存储 payload（predicate / object / qualifiers）↔ 模型实际查询。
C01_SHAPES = (
    ("c06", ("preferred_name", "小周"), "用户最后明确确认的称呼、称谓偏好"),
    ("c07", ("reply_closing", "不要以“还有什么可以帮你”收尾"), "我对结尾客套话的约定，表达偏好"),
    ("c12", ("work_contact_hours", "09:00–17:00"), "用户平时允许安排工作联系的时段，不使用同事排班"),
    ("c17", ("email_draft_length", "最多两段", ("邮件草稿",)), "通知段落格式"),
    ("c19", ("explanation_order", "先说结论再说理由"), "先报结果还是先铺背景"),
)


async def recall(manager, query: str, *, key: str, modes=BOTH, disclosure=None):
    context = _context(query=query, modes=modes, disclosure=disclosure)
    return await manager.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key=key),
    )


def values(execution) -> list[str]:
    return [str(item.public_payload["object_value"]) for item in execution.result.items]


async def terminal(manager, key: str) -> tuple[list[str], dict]:
    found = await rows(
        manager,
        "SELECT t.degradation_codes_json,t.terminal_json FROM typed_recall_terminals t "
        "JOIN typed_recall_requests r ON r.request_id=t.request_id "
        "WHERE json_extract(r.request_json,'$.plan.idempotency_key')=?",
        key,
    )
    assert len(found) == 1, found
    return json.loads(str(found[0][0])), json.loads(str(found[0][1]))


def _scored(monkeypatch) -> list[str]:
    scored: list[str] = []
    original = sqlite_v5._CognitiveVectorLane.score

    def record(self, memory_id, revision):
        scored.append(f"{memory_id}:{revision}")
        return original(self, memory_id, revision)

    monkeypatch.setattr(sqlite_v5._CognitiveVectorLane, "score", record)
    return scored


@pytest.mark.asyncio
async def test_five_c01_fail_shapes_hit_via_vector_lane_with_zero_lexical(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "c01.db", embedder, operations=tuple((op, *payload) for op, payload, _q in C01_SHAPES)
    )
    try:
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == 5
        for op, payload, query in C01_SHAPES:
            expected = payload[1]
            payload_text = canonical_json(
                {
                    "subject_entity": "user:self",
                    "predicate": payload[0],
                    "object_value": payload[1],
                    "qualifiers": list(payload[2] if len(payload) > 2 else ()),
                }
            ).casefold()
            assert all(term not in payload_text for term in typed_recall_query_terms(query)), (op, query)
            lexical = await recall(manager, query, key=f"{op}-lexical", modes=LEXICAL_ONLY)
            assert lexical.result.items == () and lexical.degradation_codes == ()
            assert "recall_no_eligible_memory" in {code.value for code in lexical.result.reason_codes}
            vector = await recall(manager, query, key=f"{op}-vector")
            assert vector.decision.outcome is RecallDecisionOutcome.RECALL
            assert values(vector) == [expected], (op, query, values(vector))
            assert vector.degradation_codes == ()
            item = vector.result.items[0]
            assert item.selected_item.source_kind == "cognitive_memory"
            assert item.score == pytest.approx(0.40 / 61, rel=1e-6)  # vector lane only, rank 1
            codes, body = await terminal(manager, f"{op}-vector")
            assert codes == []
            assert body["cognitive_vector"] == {
                "used_generation_id_hash": sqlite_v5._opaque_hash(built.generation_id)
            }
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_suppressed_memory_never_enters_vector_comparison(tmp_path: Path, monkeypatch) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "suppressed.db", embedder,
        operations=(("c06", "preferred_name", "小周"), ("c17", "email_draft_length", "最多两段", ("邮件草稿",))),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        before = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="before-forget")
        assert values(before) == ["小周"]
        memory_id = (await rows(
            manager, "SELECT h.memory_id FROM cognitive_memory_heads h JOIN semantic_claims s "
            "ON s.memory_id=h.memory_id AND s.revision=h.current_revision WHERE s.predicate='preferred_name'",
        ))[0][0]
        await manager._backend.suppress(
            SuppressionRequest(
                "forget-preferred-name", "actor-1", SuppressionScopeKind.MEMORY, memory_id,
                "user_forget", 20.0, OrdinaryMemoryPurpose.RECALL,
            )
        )
        scored = _scored(monkeypatch)
        after = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="after-forget")
        assert after.result.items == () and after.degradation_codes == ()
        assert not any(ref.startswith(f"{memory_id}:") for ref in scored)
        assert scored  # the other, eligible memory was compared and simply did not match
        other = await recall(manager, "通知段落格式", key="after-forget-other")
        assert values(other) == ["最多两段"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_disclosure_denial_wins_over_vector_hit(tmp_path: Path, monkeypatch) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(tmp_path / "disclosure.db", embedder, operations=(("c06", "preferred_name", "小周"),))
    try:
        await manager.rebuild_cognitive_vector_generation()
        query_calls = len(embedder.embedded)
        scored = _scored(monkeypatch)
        # A household task recipient may never read a personal-class memory, and an
        # off-purpose context is rejected before any candidate work at all.
        household = DisclosureContext(
            "run-recall", "actor-1", DeliveryRecipient.HOUSEHOLD, "household-1",
            IntendedAudience.HOUSEHOLD, DisclosurePurpose.TASK_EXECUTION, DisclosureSource.AUTHENTICATED_HOST,
            DisclosureTrust.TRUSTED_AUTHORITY, DisclosureGeneration.CURRENT, "disclosure-household",
            (DisclosureReasonCode.MINIMUM_NECESSARY,),
        )
        denied = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="household", disclosure=household)
        assert denied.result.items == () and denied.result.confirmation_groups == ()
        assert scored == []
        allowed = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="self")
        assert values(allowed) == ["小周"] and scored
        assert len(embedder.embedded) - query_calls <= 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cosine_below_frozen_threshold_is_not_a_candidate(tmp_path: Path) -> None:
    assert COGNITIVE_VECTOR_MIN_SCORE == 0.45
    low = [0.3, math.sqrt(1 - 0.09)] + [0.0] * (DIM - 2)
    high = [0.5, math.sqrt(1 - 0.25)] + [0.0] * (DIM - 2)
    query_vector = [1.0] + [0.0] * (DIM - 1)
    embedder = ControlledEmbedder(extra={"threshold low": low, "threshold high": high, "阈值查询": query_vector})
    manager, *_ = await manager_with(
        tmp_path / "threshold.db", embedder,
        operations=(("low", "threshold_low", "negative-control"), ("high", "threshold_high", "positive-control")),
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        execution = await recall(manager, "阈值查询", key="threshold")
        assert values(execution) == ["positive-control"]
        assert execution.degradation_codes == ()
        codes, body = await terminal(manager, "threshold")
        assert codes == [] and "cognitive_vector" in body
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_stale_generation_degrades_and_lexical_lane_continues(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "stale.db", embedder, operations=(("c06", "preferred_name", "小周"),)
    )
    try:
        await manager.rebuild_cognitive_vector_generation()
        await add_memory(manager, authority, evidence_id="evidence-2", operation=("c17", "email_draft_length", "最多两段"))
        stale = await recall(manager, "小周 的称呼", key="stale")
        assert values(stale) == ["小周"]  # lexical hit survives
        assert stale.degradation_codes == (COGNITIVE_VECTOR_STALE,)
        codes, body = await terminal(manager, "stale")
        assert codes == [COGNITIVE_VECTOR_STALE] and "cognitive_vector" not in body
        semantic_only = await recall(manager, "通知段落格式", key="stale-semantic")
        assert semantic_only.result.items == ()
        assert semantic_only.degradation_codes == (COGNITIVE_VECTOR_STALE,)
        await manager.rebuild_cognitive_vector_generation()
        fresh = await recall(manager, "通知段落格式", key="fresh-semantic")
        assert values(fresh) == ["最多两段"] and fresh.degradation_codes == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_no_generation_and_no_embedder_degrade_distinctly(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(tmp_path / "no-generation.db", embedder, operations=(("c06", "preferred_name", "小周"),))
    try:
        execution = await recall(manager, "小周", key="no-generation")
        assert values(execution) == ["小周"]
        assert execution.degradation_codes == (COGNITIVE_VECTOR_NO_GENERATION,)
        assert embedder.embedded == []  # no generation: the query is never embedded
        assert (await terminal(manager, "no-generation"))[0] == [COGNITIVE_VECTOR_NO_GENERATION]
    finally:
        await manager.close()
    manager, *_ = await manager_with(tmp_path / "no-embedder.db", None, operations=(("c06", "preferred_name", "小周"),))
    try:
        execution = await recall(manager, "小周", key="no-embedder")
        assert values(execution) == ["小周"]
        assert execution.degradation_codes == (COGNITIVE_VECTOR_UNAVAILABLE,)
        assert (await terminal(manager, "no-embedder"))[0] == [COGNITIVE_VECTOR_UNAVAILABLE]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_query_embedding_timeout_or_invalid_vector_degrades_to_deadline(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(tmp_path / "deadline.db", embedder, operations=(("c06", "preferred_name", "小周"),))
    try:
        await manager.rebuild_cognitive_vector_generation()

        async def slow(_text):
            raise TimeoutError("embedder deadline")

        embedder.query_hook = slow
        execution = await recall(manager, "小周", key="deadline")
        assert values(execution) == ["小周"]
        assert execution.degradation_codes == (COGNITIVE_VECTOR_DEADLINE,)
        assert (await terminal(manager, "deadline"))[0] == [COGNITIVE_VECTOR_DEADLINE]

        async def wrong_dimension(_text):
            return [1.0, 0.0]

        embedder.query_hook = wrong_dimension
        execution = await recall(manager, "小周", key="deadline-dimension")
        assert values(execution) == ["小周"]
        assert execution.degradation_codes == (COGNITIVE_VECTOR_DEADLINE,)
        embedder.query_hook = None
        execution = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="recovered")
        assert values(execution) == ["小周"] and execution.degradation_codes == ()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_confirmation_gate_accepts_vector_hit(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "confirmation.db", embedder, operations=(("c-style", "response_style", "concise", ("default",)),)
    )
    try:
        await _contest_semantic(manager._backend, authority)
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == 1
        query = "回复偏好是简洁还是啰嗦"
        lexical = await recall(manager, query, key="confirm-lexical", modes=LEXICAL_ONLY)
        assert lexical.result.confirmation_groups == () and lexical.result.items == ()
        vector = await recall(manager, query, key="confirm-vector")
        assert vector.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert vector.result.items == ()
        assert len(vector.result.confirmation_groups) == 1
        assert len(vector.result.confirmation_groups[0].members) == 2
        assert vector.degradation_codes == ()
        codes, body = await terminal(manager, "confirm-vector")
        assert codes == [] and body["cognitive_vector"]["used_generation_id_hash"] == sqlite_v5._opaque_hash(built.generation_id)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_plan_without_vector_mode_has_zero_vector_side_effects(tmp_path: Path, monkeypatch) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(tmp_path / "no-vector.db", embedder, operations=(("c06", "preferred_name", "小周"),))
    try:
        await manager.rebuild_cognitive_vector_generation()
        embedded_before = list(embedder.embedded)
        scored = _scored(monkeypatch)
        execution = await recall(manager, "用户最后明确确认的称呼、称谓偏好", key="lexical-only", modes=LEXICAL_ONLY)
        assert execution.result.items == () and execution.degradation_codes == ()
        assert embedder.embedded == embedded_before and scored == []
        codes, body = await terminal(manager, "lexical-only")
        assert codes == [] and "cognitive_vector" not in body
        hit = await recall(manager, "小周", key="lexical-hit", modes=LEXICAL_ONLY)
        assert values(hit) == ["小周"] and hit.result.items[0].score == pytest.approx(0.30 / 61, rel=1e-6)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_relation_memory_never_enters_vector_lane_or_confirmation(tmp_path: Path, monkeypatch) -> None:
    """0.6.24：relation 类 SEMANTIC 记忆是边不是节点（HM-AC-6）。世代跳过它；typed recall 的
    vector lane 与 confirmation 门都不对它比对，也不把它作为 item/成员返回。"""

    from dataclasses import replace

    from simple_harness.runtime import (
        ConflictStatus,
        ExistingMemoryTarget,
        MemoryMutationKind,
        SemanticMemoryPayload,
    )

    from simple_harness_memory import MemoryScope
    from tests.integration.test_cognitive_mutation_repository_v5 import _admitted, _operation, _span
    from tests.integration.test_cognitive_vector_generation import _relation_ids, relation_manager
    from tests.integration.test_typed_recall_v6 import mutation_plan

    embedder = ControlledEmbedder()
    manager, _envelope, _span_, authority = await relation_manager(tmp_path / "relation-recall.db", embedder)
    try:
        claim_id, procedure_id, relation_id = await _relation_ids(manager)
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.vector_count == 2
        scored = _scored(monkeypatch)
        query = "回复偏好是简洁还是啰嗦"
        assert not (set(typed_recall_query_terms(query)) & {"concise", "default"})
        hit = await recall(manager, query, key="relation-vector")
        assert [item.selected_item.source_ref for item in hit.result.items] == [claim_id]
        assert values(hit) == ["concise"] and hit.degradation_codes == ()
        assert scored == [f"{claim_id}:1"]
        assert f"{relation_id}:1" not in scored
        codes, body = await terminal(manager, "relation-vector")
        assert codes == [] and body["cognitive_vector"]["used_generation_id_hash"] == sqlite_v5._opaque_hash(built.generation_id)

        # contest 只针对 claim（不是 relation）：confirmation 门同样只比对 claim。
        challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
        challenger_span = _span(challenger_envelope, challenger_receipt)
        authority.register_admitted(challenger_envelope, challenger_receipt, challenger_span)
        await manager.ingest_committed_evidence(challenger_envelope, challenger_receipt)
        contest = replace(
            _operation(
                challenger_span,
                operation_id="relation-contest",
                kind=MemoryMutationKind.CONTEST,
                target=ExistingMemoryTarget(claim_id, 1),
                conflict_status=ConflictStatus.CONTESTED,
            ),
            payload=SemanticMemoryPayload("user:self", "response_style", "verbose", ("default",)),
        )
        base_revision = (await rows(manager, "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"))[0][0]
        result = await manager.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=mutation_plan(
                challenger_envelope, contest, base_revision=int(base_revision),
                plan_id="relation-contest-plan", idempotency_key="relation-contest-key",
            ),
        )
        assert result.outcome.value == "committed"
        rebuilt = await manager.rebuild_cognitive_vector_generation()
        assert rebuilt.generation_id != built.generation_id and rebuilt.vector_count == 2
        assert relation_id not in {
            item[0] for item in await rows(manager, "SELECT memory_id FROM cognitive_vectors WHERE generation_id=?", rebuilt.generation_id)
        }
        scored.clear()
        vector = await recall(manager, query, key="relation-confirm")
        assert vector.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
        assert vector.result.items == () and len(vector.result.confirmation_groups) == 1
        members = vector.result.confirmation_groups[0].members
        assert len(members) == 2 and relation_id not in {member.member.source_ref for member in members}
        assert {member.member.source_ref for member in members} == {claim_id}
        assert f"{relation_id}:1" not in scored and scored and all(ref != f"{relation_id}:1" for ref in scored)
        assert vector.degradation_codes == ()
    finally:
        await manager.close()
