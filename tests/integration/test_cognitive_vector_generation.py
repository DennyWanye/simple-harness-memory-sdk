"""0.6.23 长期认知记忆向量世代：空库/构建/激活/replay/head 变化/lineage 变化/审计/重开。

用确定性可控 embedder（``kind='mock'``，``allow_development_embedder=True``）：按关键词把文本映射到
固定单位向量，同义查询对余弦高、无关对余弦低。嵌入文本只来自公开 payload。
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.runtime import SemanticMemoryPayload

from simple_harness_memory import MemoryScope, build_human_memory_v7
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryValidationError
from simple_harness_memory.embedders.base import (
    EMBEDDING_FORMAT_FINGERPRINT,
    Embedder,
    EmbeddingLineage,
    decode_vector,
)
from simple_harness_memory.features.cognitive_vector import (
    cognitive_vector_ref,
    cognitive_vector_text,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_typed_recall_v6 import _principal

DIM = 8


def _unit(index: int) -> list[float]:
    vector = [0.0] * DIM
    vector[index] = 1.0
    return vector


# 概念 → 轴。同一概念的中文改写与英文 predicate 落在同一轴上（模拟双语句向量模型）。
CONCEPTS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("称呼", "称谓", "preferred name", "小周"), 0),
    (("结尾", "收尾", "客套", "reply closing"), 1),
    (("工作联系", "时段", "work contact hours", "09:00"), 2),
    (("段落", "两段", "email draft length", "邮件草稿"), 3),
    (("先报", "先说", "结论", "explanation order"), 4),
    (("待办", "todo sort order", "截止"), 5),
    (("response style", "concise", "verbose", "简洁", "啰嗦"), 6),
)


class ControlledEmbedder(Embedder):
    """Deterministic keyword→axis embedder; ``query_hook`` lets tests fault the query path."""

    def __init__(self, *, model: str = "controlled", extra: dict[str, list[float]] | None = None) -> None:
        self.model = model
        self.extra = dict(extra or {})
        self.embedded: list[str] = []
        self.query_hook = None

    @property
    def kind(self) -> str:
        return "mock"

    @property
    def dim(self) -> int:
        return DIM

    @property
    def lineage(self) -> EmbeddingLineage:
        return EmbeddingLineage(
            kind="mock",
            provider="tests",
            model=self.model,
            revision="1",
            dimension=DIM,
            normalization="l2",
            # 与生产 WeMM 一致：fingerprint 按模型区分（embedding_lineages.fingerprint UNIQUE）。
            format_fingerprint=f"{EMBEDDING_FORMAT_FINGERPRINT}:{self.model}",
        )

    def vector_for(self, text: str) -> list[float]:
        for needle, vector in self.extra.items():
            if needle in text:
                return list(vector)
        total = [0.0] * DIM
        lowered = text.casefold()
        for keywords, axis in CONCEPTS:
            if any(keyword.casefold() in lowered for keyword in keywords):
                total[axis] += 1.0
        if not any(total):
            total[DIM - 1] = 1.0
        norm = math.sqrt(sum(value * value for value in total))
        return [value / norm for value in total]

    async def embed(self, text: str) -> list[float]:
        self.embedded.append(text)
        if self.query_hook is not None:
            hook = self.query_hook
            result = await hook(text)
            if result is not None:
                return result
        return self.vector_for(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [self.vector_for(text) for text in texts]


def semantic(operation_id: str, span, predicate: str, value: str, qualifiers: tuple[str, ...] = ()):
    return replace(
        _operation(span, operation_id=operation_id),
        payload=SemanticMemoryPayload("user:self", predicate, value, qualifiers),
    )


async def manager_with(path: Path, embedder: Embedder | None, *, clock=None, operations=()):
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    kwargs = dict(
        clock=clock or (lambda: 20.0),
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    if embedder is not None:
        kwargs["short_horizon_embedder"] = embedder
        kwargs["allow_development_embedder"] = True
    manager = await build_human_memory_v7(path, **kwargs)
    await manager.ingest_committed_evidence(envelope, receipt)
    if operations:
        ops = [
            semantic(item[0], span, *item[1:]) if isinstance(item, tuple) else item
            for item in operations
        ]
        result = await manager.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, *ops),
        )
        assert result.outcome.value == "committed"
    return manager, envelope, span, authority


async def add_memory(manager, authority, *, evidence_id: str, operation):
    """Second plan on distinct evidence: changes the recallable head manifest."""

    envelope, receipt = _admitted(evidence_id=evidence_id)
    span = _span(envelope, receipt)
    authority.register_admitted(envelope, receipt, span)
    await manager.ingest_committed_evidence(envelope, receipt)
    op = semantic(operation[0], span, *operation[1:])
    base_revision = (await rows(manager, "SELECT revision FROM cognitive_apply_heads WHERE principal_id='actor-1'"))[0][0]
    result = await manager.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(
            envelope, op, base_revision=int(base_revision),
            plan_id=f"plan-{evidence_id}", idempotency_key=f"idem-{evidence_id}",
        ),
    )
    assert result.outcome.value == "committed"
    return envelope


async def rows(manager, sql: str, *params):
    async with manager._backend.connection.execute(sql, params) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


def test_cognitive_vector_text_is_deterministic_and_public_only() -> None:
    payload = {
        "subject_entity": "user:self",
        "predicate": "email_draft_length",
        "object_value": "最多两段",
        "qualifiers": ["邮件草稿"],
    }
    assert cognitive_vector_text("semantic", payload) == "user:self\nemail draft length\n最多两段\n邮件草稿"
    assert cognitive_vector_text("semantic", payload) == cognitive_vector_text("semantic", dict(payload))
    episode = {"title": "T", "participants": ["p"], "goals": ["g"], "actions": [], "results": ["r"],
               "impacts": ["hidden"], "occurred_start": 1.0, "occurred_end": None}
    assert cognitive_vector_text("episode", episode) == "T\ng\nr"
    assert cognitive_vector_text("procedure", {"name": "n", "applicability": ["a"], "steps": ["s1", "s2"],
                                               "effective_risk": "low"}) == "n\na\ns1\ns2"
    assert cognitive_vector_text("prospective", {"action": "call", "trigger": {"kind": "time", "at": 3}}) == "call\n3\ntime"
    assert cognitive_vector_ref("m", 2) == "m:2"


@pytest.mark.asyncio
async def test_empty_repository_yields_empty_generation_with_audit(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(tmp_path / "empty.db", embedder)
    try:
        result = await manager.rebuild_cognitive_vector_generation()
        assert result.generation_id is None and result.vector_count == 0
        assert result.activated is False and result.replayed is False
        assert embedder.embedded == []
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_generations") == [(0,)]
        audits = await rows(
            manager, "SELECT generation_state,vector_count,generation_id,audit_json FROM cognitive_vector_audit"
        )
        assert len(audits) == 1 and audits[0][:3] == ("empty", 0, None)
        details = json.loads(audits[0][3])["details"]
        assert details["replayed"] is False and len(details["manifest_hash"]) == 64
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_build_activate_replay_is_idempotent_and_embeds_public_text_only(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "build.db",
        embedder,
        operations=(("c1", "preferred_name", "小周"), ("c2", "email_draft_length", "最多两段", ("邮件草稿",))),
    )
    try:
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.activated and not built.replayed and built.vector_count == 2
        assert built.generation_id is not None and built.generation_id.startswith("cognitive-gen:")
        assert sorted(embedder.embedded) == [
            "user:self\nemail draft length\n最多两段\n邮件草稿",
            "user:self\npreferred name\n小周",
        ]
        assert all("evidence" not in text and "session" not in text for text in embedder.embedded)
        vectors = await rows(
            manager,
            "SELECT memory_id,revision,embedding,embedding_hash,dimension FROM cognitive_vectors "
            "WHERE generation_id=? ORDER BY memory_id",
            built.generation_id,
        )
        assert len(vectors) == 2
        for _memory_id, revision, blob, digest, dimension in vectors:
            assert revision == 1 and dimension == DIM
            assert hashlib.sha256(bytes(blob)).hexdigest() == digest
            assert len(decode_vector(bytes(blob))) == DIM
        replay = await manager.rebuild_cognitive_vector_generation()
        assert replay.generation_id == built.generation_id and replay.replayed and replay.activated
        assert len(embedder.embedded) == 2  # replay never re-embeds
        assert await rows(manager, "SELECT state FROM cognitive_vector_generations") == [("active",)]
        audits = await rows(
            manager, "SELECT generation_state,generation_id,audit_json FROM cognitive_vector_audit ORDER BY created_at"
        )
        assert [item[0] for item in audits] == ["active", "active"]
        assert {item[1] for item in audits} == {built.generation_id}
        assert [json.loads(item[2])["details"]["replayed"] for item in audits] == [False, True]
        # 0.6.28：世代激活是纯索引重建，不再推进召回权威 epoch（S3 §5.4 只认"可能改变
        # 资格"的事件）；世代身份仍完整留在 cognitive_vector_audit 里。
        assert await rows(
            manager,
            "SELECT event_kind FROM recall_authority_events WHERE principal_id='actor-1' "
            "AND event_kind='cognitive_vector_generation_changed'",
        ) == []
        cache = manager._backend._cognitive_vector_cache
        assert cache is not None and cache.generation_id == built.generation_id
        assert len(cache.memory_refs) == 2 and all(ref.endswith(":1") for ref in cache.memory_refs)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_head_change_builds_new_generation_and_retires_old(tmp_path: Path) -> None:
    embedder = ControlledEmbedder()
    manager, _envelope, _span, authority = await manager_with(
        tmp_path / "heads.db", embedder, operations=(("c1", "preferred_name", "小周"),)
    )
    try:
        first = await manager.rebuild_cognitive_vector_generation()
        await add_memory(manager, authority, evidence_id="evidence-2", operation=("c2", "reply_closing", "不要以客套话收尾"))
        # A mutation never embeds inline: only the two rebuilds below touch the embedder.
        assert len(embedder.embedded) == 1
        assert manager._backend._cognitive_vector_cache is not None  # stale until rebuilt
        second = await manager.rebuild_cognitive_vector_generation()
        assert second.generation_id != first.generation_id
        assert second.vector_count == 2 and not second.replayed
        assert sorted(await rows(manager, "SELECT generation_id,state FROM cognitive_vector_generations")) == sorted(
            [(first.generation_id, "retired"), (second.generation_id, "active")]
        )
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vectors WHERE generation_id=?", first.generation_id) == [(1,)]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vectors WHERE generation_id=?", second.generation_id) == [(2,)]
        assert manager._backend._cognitive_vector_cache.generation_id == second.generation_id
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_lineage_change_builds_independent_generation(tmp_path: Path) -> None:
    path = tmp_path / "lineage.db"
    first_embedder = ControlledEmbedder(model="model-a")
    manager, *_ = await manager_with(path, first_embedder, operations=(("c1", "preferred_name", "小周"),))
    first = await manager.rebuild_cognitive_vector_generation()
    await manager.close()
    second_embedder = ControlledEmbedder(model="model-b")
    manager, *_ = await manager_with(path, second_embedder, clock=lambda: 30.0)
    try:
        second = await manager.rebuild_cognitive_vector_generation()
        assert second.generation_id != first.generation_id and not second.replayed
        assert len(second_embedder.embedded) == 1
        generations = await rows(
            manager, "SELECT generation_id,state,lineage_id FROM cognitive_vector_generations ORDER BY created_at"
        )
        assert [(item[0], item[1]) for item in generations] == [
            (first.generation_id, "retired"), (second.generation_id, "active"),
        ]
        assert generations[0][2] != generations[1][2]
        assert await rows(manager, "SELECT COUNT(*) FROM embedding_lineages") == [(2,)]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_rebuild_requires_embedder(tmp_path: Path) -> None:
    manager, *_ = await manager_with(tmp_path / "no-embedder.db", None, operations=(("c1", "preferred_name", "小周"),))
    try:
        with pytest.raises(MemoryValidationError, match="short_horizon_embedder_required"):
            await manager.rebuild_cognitive_vector_generation()
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_generations") == [(0,)]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_reopen_loads_active_generation_and_tampered_vector_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "reopen.db"
    manager, *_ = await manager_with(path, ControlledEmbedder(), operations=(("c1", "preferred_name", "小周"),))
    built = await manager.rebuild_cognitive_vector_generation()
    await manager.close()
    manager, *_ = await manager_with(path, ControlledEmbedder(), clock=lambda: 30.0)
    try:
        cache = manager._backend._cognitive_vector_cache
        assert cache is not None and cache.generation_id == built.generation_id
    finally:
        await manager.close()
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("UPDATE cognitive_vectors SET embedding=X'5b312e305d' WHERE generation_id=?", (built.generation_id,))
    finally:
        connection.close()
    with pytest.raises(MemoryCorruptionError):
        await manager_with(path, ControlledEmbedder(), clock=lambda: 40.0)


# ---------------------------------------------------------------------------
# 0.6.24：relation 类 SEMANTIC head 是边不是节点；构建失败落 failed 行。
# ---------------------------------------------------------------------------


async def _relation_ids(manager) -> tuple[str, str, str]:
    """(claim_id, procedure_id, relation_id) of the ``_applies_to_plan`` fixture."""

    by_operation = {
        op: memory_id
        for op, memory_id in await rows(
            manager, "SELECT operation_id,memory_id FROM cognitive_memory_revisions"
        )
    }
    return by_operation["create-source"], by_operation["create-target"], by_operation["create-relation"]


async def relation_manager(path: Path, embedder, **kwargs):
    from tests.integration.test_cognitive_mutation_repository_v5 import _applies_to_plan

    manager, envelope, span, authority = await manager_with(path, embedder, **kwargs)
    result = await manager.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_applies_to_plan(envelope, span),
    )
    assert result.outcome.value == "committed"
    assert await rows(manager, "SELECT COUNT(*) FROM cognitive_relations WHERE relation_kind='applies_to'") == [(1,)]
    assert await rows(manager, "SELECT COUNT(*) FROM cognitive_memory_heads WHERE memory_type='semantic'") == [(2,)]
    return manager, envelope, span, authority


@pytest.mark.asyncio
async def test_relation_head_is_skipped_and_worker_order_succeeds(tmp_path: Path) -> None:
    """原生 r8 缺陷复现：claim + procedure + applies_to relation 落库后，0.6.23 的世代构建对
    relation head（memory_type=semantic、无 semantic_claims 行）抛 ``typed recall payload
    missing``，且不落任何世代行。0.6.24：relation 被跳过，vector_count 只计非 relation head。"""

    embedder = ControlledEmbedder()
    manager, *_ = await relation_manager(tmp_path / "relation.db", embedder)
    try:
        claim_id, procedure_id, relation_id = await _relation_ids(manager)
        # Host 短索引 worker 的顺序：projection → short generation → cognitive generation。
        await manager.rebuild_short_horizon_projection(principal=_principal())
        await manager.rebuild_short_horizon_generation()
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.activated and not built.replayed and built.vector_count == 2
        assert len(embedder.embedded) == 2
        assert all("applies_to" not in text and "relation" not in text for text in embedder.embedded)
        stored = await rows(manager, "SELECT memory_id FROM cognitive_vectors WHERE generation_id=?", built.generation_id)
        assert sorted(item[0] for item in stored) == sorted([claim_id, procedure_id])
        assert relation_id not in {item[0] for item in stored}
        assert await rows(manager, "SELECT state,last_error_code FROM cognitive_vector_generations") == [("active", None)]
        cache = manager._backend._cognitive_vector_cache
        assert cache is not None and sorted(cache.memory_refs) == sorted([f"{claim_id}:1", f"{procedure_id}:1"])
        # manifest / stale 判定同样排除 relation：head 未变 → replay，不是 stale。
        head_rows = await manager._backend._cognitive_vector_head_rows_unlocked()
        assert sorted(str(row["memory_id"]) for row in head_rows) == sorted([claim_id, procedure_id])
        active = await rows(manager, "SELECT content_hash FROM cognitive_vector_generations WHERE state='active'")
        assert active == [(manager._backend._cognitive_vector_manifest_hash(head_rows),)]
        assert active[0][0] == await manager._backend._current_cognitive_vector_manifest_hash_unlocked()
        replay = await manager.rebuild_cognitive_vector_generation()
        assert replay.replayed and replay.generation_id == built.generation_id and replay.vector_count == 2
        lane, degradation = await manager._backend._prepare_cognitive_vector_lane(
            query="concise", started_monotonic=time.monotonic(), deadline_monotonic=time.monotonic() + 1.0
        )
        assert degradation is None and lane is not None
        assert lane.score(relation_id, 1) is None
        assert lane.score(claim_id, 1) is not None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_relation_head_survives_reopen_without_stale_or_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "relation-reopen.db"
    manager, *_ = await relation_manager(path, ControlledEmbedder())
    built = await manager.rebuild_cognitive_vector_generation()
    await manager.close()
    manager, *_ = await manager_with(path, ControlledEmbedder(), clock=lambda: 30.0)
    try:
        cache = manager._backend._cognitive_vector_cache
        assert cache is not None and cache.generation_id == built.generation_id and len(cache.memory_refs) == 2
        replay = await manager.rebuild_cognitive_vector_generation()
        assert replay.replayed and replay.generation_id == built.generation_id
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_build_failure_records_failed_generation_with_error_code(tmp_path: Path) -> None:
    from simple_harness_memory.core.errors import CognitiveVectorGenerationFailed
    from simple_harness_memory.features.cognitive_vector import (
        COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED,
        COGNITIVE_VECTOR_BUILD_HEAD_INVALID,
        COGNITIVE_VECTOR_BUILD_WRITE_FAILED,
    )

    embedder = ControlledEmbedder()
    manager, *_ = await manager_with(
        tmp_path / "failed.db", embedder, operations=(("c1", "preferred_name", "小周"),)
    )
    backend = manager._backend
    try:
        # 1. 写库阶段失败（fault 注入在激活前）：building 事务回滚，落 failed 行。
        def fault(point: str) -> None:
            if point == "cognitive_vector.generation.before_activate":
                raise sqlite3.OperationalError("injected")

        backend._fault_injector = fault
        with pytest.raises(CognitiveVectorGenerationFailed) as info:
            await manager.rebuild_cognitive_vector_generation()
        backend._fault_injector = None
        assert info.value.code == COGNITIVE_VECTOR_BUILD_WRITE_FAILED
        assert str(info.value) == COGNITIVE_VECTOR_BUILD_WRITE_FAILED
        assert isinstance(info.value.__cause__, sqlite3.OperationalError)
        generations = await rows(
            manager, "SELECT generation_id,state,last_error_code,activated_at FROM cognitive_vector_generations"
        )
        assert generations == [(info.value.generation_id, "failed", COGNITIVE_VECTOR_BUILD_WRITE_FAILED, None)]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vectors") == [(0,)]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_audit") == [(0,)]
        assert backend._cognitive_vector_cache is None

        # 2. 嵌入阶段失败：embedder 抛错。
        async def broken(texts):
            raise RuntimeError("embedder offline")

        embedder.embed_batch = broken  # type: ignore[method-assign]
        with pytest.raises(CognitiveVectorGenerationFailed) as info:
            await manager.rebuild_cognitive_vector_generation()
        assert info.value.code == COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED
        del embedder.embed_batch

        # 3. head/公开 payload 阶段失败（0.6.23 的 relation 缺陷就落在这一阶段）。
        original = backend._cognitive_public_payload_unlocked

        async def missing(row):
            raise MemoryCorruptionError("typed recall payload missing")

        backend._cognitive_public_payload_unlocked = missing  # type: ignore[method-assign]
        with pytest.raises(CognitiveVectorGenerationFailed) as info:
            await manager.rebuild_cognitive_vector_generation()
        backend._cognitive_public_payload_unlocked = original  # type: ignore[method-assign]
        assert info.value.code == COGNITIVE_VECTOR_BUILD_HEAD_INVALID
        assert isinstance(info.value.__cause__, MemoryCorruptionError)

        states = await rows(
            manager, "SELECT state,last_error_code FROM cognitive_vector_generations ORDER BY rowid"
        )
        assert states == [
            ("failed", COGNITIVE_VECTOR_BUILD_WRITE_FAILED),
            ("failed", COGNITIVE_VECTOR_BUILD_EMBEDDING_FAILED),
            ("failed", COGNITIVE_VECTOR_BUILD_HEAD_INVALID),
        ]
        # 4. 故障消失后下一 tick 正常构建；failed 行保留为历史。
        built = await manager.rebuild_cognitive_vector_generation()
        assert built.activated and built.vector_count == 1
        assert await rows(manager, "SELECT state,generation_id FROM cognitive_vector_generations WHERE state='active'") == [
            ("active", built.generation_id)
        ]
        assert await rows(manager, "SELECT COUNT(*) FROM cognitive_vector_generations WHERE state='failed'") == [(3,)]
    finally:
        backend._fault_injector = None
        await manager.close()
