"""0.6.23 长期认知记忆向量世代：空库/构建/激活/replay/head 变化/lineage 变化/审计/重开。

用确定性可控 embedder（``kind='mock'``，``allow_development_embedder=True``）：按关键词把文本映射到
固定单位向量，同义查询对余弦高、无关对余弦低。嵌入文本只来自公开 payload。
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
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
        assert await rows(
            manager,
            "SELECT event_kind FROM recall_authority_events WHERE principal_id='actor-1' "
            "AND event_kind='cognitive_vector_generation_changed'",
        ) == [("cognitive_vector_generation_changed",)]
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
