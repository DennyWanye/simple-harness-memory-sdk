# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

"""0.6.30 短时域 chunk 长度上限（HM-TO-A6 turn 22：单条 29 778 字符 chunk 嵌入 23.9 s）。

事故原型：一个因果组一条 chunk、无上限。本文件钉死：
- 未分段因果组的 ``chunk_id``/``content_hash`` 与 0.6.29 **逐字相同**（字面值在 0.6.29 源上算出）；
- 超长因果组按 2 048 码点确定性切段、每组最多 8 段、尾段可召回可见、血缘为整组；
- 0.6.29 遗留的单条超长 chunk 打开不判损坏，下次重建替换并推进一次召回权威 epoch；
- 世代重建沿用 active 世代里同 chunk_id 的向量，只嵌入新出现的 chunk；
- Host 注册的 ``causal_group_id`` 不得含 U+001F。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import cast

import pytest
from simple_harness.contracts import FrozenJsonValue, JsonValue, fingerprint_json
from simple_harness.runtime import (
    EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
    EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
    AdmittedEvidenceAuthority,
    ConversationEvidenceMetadata,
    ConversationEvidenceMetadataReceipt,
    ConversationEvidenceRegistration,
    ConversationEvidenceRegistrationRef,
    ConversationEvidenceRole,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceActorRole,
    EvidenceItemAuthority,
    EvidenceProvenance,
    EvidenceReasonCode,
    EvidenceSourceKind,
    InformationAttribute,
    IntendedAudience,
    PrivacyClass,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
    authorize_conversation_public_text,
)

import simple_harness_memory as m
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core import short_horizon as core_short_horizon
from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryPrincipal
from simple_harness_memory.core.short_horizon import (
    SHORT_HORIZON_CHUNK_MAX_CHARS,
    SHORT_HORIZON_CHUNK_MAX_SEGMENTS,
    SHORT_HORIZON_RETENTION_SECONDS,
)
from simple_harness_memory.embedders.mock import HashEmbedder

NOW = 1_000_000.0
PRINCIPAL = MemoryPrincipal("actor-1", "actor-1", "actor-1", "session-1")
INCIDENT_CHARS = 29_778  # DIAG-RECALL-TIMEOUT.md §2.3 现场最长 chunk

# 在 0.6.29 源（main c025c98）上用同一夹具算出的字面值：未分段组的 id 必须逐字不变。
GOLDEN_SMALL_CHUNK_ID = "short:a70e0fc0a22374e8f120072abd5f20e6f451d153c147acfb6f172d2cb61a983a"
GOLDEN_SMALL_CONTENT_HASH = "7e4e5c726445ce966533c7868ba9f95f682b7a152139c3ab98e6ba7df54f92bc"
GOLDEN_RECENT_3_CHUNK_ID = "short:2157a1a39ddde197a3dfa7788b515e6eeb1d594d50e11f4ebe56799e5e647d2f"
# 0.6.29 对同一超长组产出的那**一条** chunk（29 805 字符）：0.6.30 遗留接受、重建后消失。
GOLDEN_LEGACY_LONG_CHUNK_ID = (
    "short:16cf47794275f292732e13b808f8c65c2fd7e9e12c6b97a3bb5fd912e4463710"
)
GOLDEN_LEGACY_LONG_CONTENT_HASH = "fd805ae245c692539a3ee9c4961f32f328acf4ee78827719c4ebe8a4f9ecc432"

_OPEN: list[SQLiteHumanMemoryBackend] = []


@pytest.fixture(autouse=True)
async def _close_open_backends() -> None:
    try:
        yield
    finally:
        while _OPEN:
            backend = _OPEN.pop()
            if backend._db is not None:
                with suppress(Exception):
                    await backend.close()


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        run_id="run-1",
        subject="actor-1",
        recipient=DeliveryRecipient.USER_SELF,
        recipient_id="actor-1",
        intended_audience=IntendedAudience.USER_SELF,
        purpose=DisclosurePurpose.PERSONALIZATION,
        source=DisclosureSource.AUTHENTICATED_HOST,
        trust=DisclosureTrust.TRUSTED_AUTHORITY,
        generation=DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


_KINDS = {
    ConversationEvidenceRole.USER: (
        EvidenceSourceKind.USER_MESSAGE,
        EvidenceActorRole.USER,
        EvidenceProvenance.AUTHENTICATED_USER,
    ),
    ConversationEvidenceRole.ASSISTANT: (
        EvidenceSourceKind.ASSISTANT_MESSAGE,
        EvidenceActorRole.ASSISTANT,
        EvidenceProvenance.MODEL_OUTPUT,
    ),
}


def _registration(
    seq: int,
    group: str,
    group_seq: int,
    ordinal: int,
    count: int,
    role: ConversationEvidenceRole,
    text: str,
) -> tuple[ConversationEvidenceRegistration, ConversationEvidenceRegistrationRef]:
    kind, actor_role, provenance = _KINDS[role]
    payload: dict[str, JsonValue] = {"item_id": f"message-{seq}", "public_text": text}
    envelope = SanitizedEvidenceEnvelope(
        evidence_id=f"evidence-{seq}",
        run_id="run-1",
        subject="actor-1",
        source_kind=kind,
        source_ref=f"turn-{seq}/{role.value}",
        source_hash=f"{seq % 10}" * 64,
        sanitized_payload=cast(Mapping[str, FrozenJsonValue], payload),
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(),
        evidence_refs=(),
    )
    receipt = SanitizedEvidenceReceipt(
        receipt_id=f"admission-{seq}",
        run_id="run-1",
        subject="actor-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=_disclosure(),
        evidence_refs=(),
        admitted_at=NOW - seq,
    )
    metadata = ConversationEvidenceMetadata(
        metadata_id=f"metadata-{seq}",
        authority_issuer_id="host-conversation-registry",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        run_id="run-1",
        subject="actor-1",
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        conversation_id="primary-conversation",
        primary_conversation_id="primary-conversation",
        causal_group_id=group,
        causal_group_sequence=group_seq,
        item_ordinal=ordinal,
        group_item_count=count,
        ordered_group_manifest_hash=f"{(group_seq + 1) % 10}" * 64,
        role=role,
        occurred_at=NOW - group_seq,
        task_scope_id="task-1",
        tool_causal_link=None,
        entities=("project-alpha",),
    )
    authority = EvidenceItemAuthority(
        schema_version=EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
        authority_id=f"item-authority-{seq}",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        source_hash=envelope.source_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id=f"message-{seq}",
        item_json_pointer="/public_text",
        normalization_version=EVIDENCE_NORMALIZATION_IDENTITY_UTF8_V1,
        actor_role=actor_role,
        provenance=provenance,
        required_privacy_class=PrivacyClass.SENSITIVE,
        required_information_attributes=(InformationAttribute.WORK,),
        classification_authority_ref="classification-authority-1",
        issuer_ref="host-evidence-registry",
    )
    metadata = authorize_conversation_public_text(
        metadata, AdmittedEvidenceAuthority(envelope, receipt, authority)
    )
    metadata_receipt = ConversationEvidenceMetadataReceipt(
        receipt_id=f"metadata-receipt-{seq}",
        metadata_id=metadata.metadata_id,
        authority_issuer_id=metadata.authority_issuer_id,
        evidence_id=metadata.evidence_id,
        envelope_hash=metadata.envelope_hash,
        admission_receipt_id=metadata.admission_receipt_id,
        admission_receipt_hash=metadata.admission_receipt_hash,
        run_id="run-1",
        subject="actor-1",
        source_hash=metadata.source_hash,
        sanitized_hash=metadata.sanitized_hash,
        metadata_hash=metadata.metadata_hash,
        issuer_ref=metadata.authority_issuer_id,
        accepted=True,
    )
    registration = ConversationEvidenceRegistration(
        f"registration-{seq}", envelope, receipt, metadata, metadata_receipt, authority
    )
    return registration, ConversationEvidenceRegistrationRef(
        registration.registration_id,
        registration.registration_hash,
        envelope.evidence_id,
        envelope.envelope_hash,
    )


def _incident_body() -> str:
    paragraph = "第%03d段：校对流程输出行，包含错误码 E%04d 与文件路径 /tmp/out/%03d.log。\n"
    body = "".join(paragraph % (i, i * 7, i) for i in range(1, 700))
    marker = "末尾独有词 ZEBRA-TAIL-MARKER"
    body = body[: INCIDENT_CHARS - len(marker)] + marker
    assert len(body) == INCIDENT_CHARS
    return body


Pair = tuple[ConversationEvidenceRegistration, ConversationEvidenceRegistrationRef]


def _fixture(*, extra_recent: int = 0) -> list[Pair]:
    """group-small(1) + group-long(2, incident-shaped) + 11 recent single-item groups(3..13)."""

    pairs: list[Pair] = []
    seq = 0

    def add(group: str, group_seq: int, ordinal: int, count: int, role, text: str) -> None:
        nonlocal seq
        seq += 1
        pairs.append(_registration(seq, group, group_seq, ordinal, count, role, text))

    user, assistant = ConversationEvidenceRole.USER, ConversationEvidenceRole.ASSISTANT
    add("group-small", 1, 1, 2, user, "校对脚本用 Python 3.12 跑，周五验样。")
    add("group-small", 1, 2, 2, assistant, "收到，Project alpha note small。")
    add("group-long", 2, 1, 2, ConversationEvidenceRole.USER, "把校对脚本跑一遍。")
    add("group-long", 2, 2, 2, ConversationEvidenceRole.ASSISTANT, _incident_body())
    for g in range(3, 14 + extra_recent):
        add(f"group-recent-{g}", g, 1, 1, ConversationEvidenceRole.USER, f"recent note {g}")
    return pairs


class _Authority:
    def __init__(self, registrations) -> None:
        self.registrations = {item.registration_id: item for item in registrations}

    async def resolve_conversation_registration(self, reference):
        return self.registrations[reference.registration_id]


class _CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__(32)
        self.batches: list[list[str]] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return await super().embed_batch(texts)


async def _backend(
    path: Path,
    pairs: list[Pair],
    *,
    embedder=None,
    register: bool = True,
    known: list[Pair] | None = None,
) -> SQLiteHumanMemoryBackend:
    backend = SQLiteHumanMemoryBackend(
        path,
        now=lambda: NOW,
        conversation_evidence_authority=_Authority([reg for reg, _ in (known or pairs)]),
        short_horizon_embedder=embedder or HashEmbedder(32),
    )
    await backend.initialize()
    _OPEN.append(backend)
    if register:
        for reg, ref in pairs:
            await backend.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
            await backend.register_conversation_evidence(ref)
    return backend


async def _chunk_rows(backend: SQLiteHumanMemoryBackend) -> list[dict[str, object]]:
    async with backend.connection.execute(
        "SELECT chunk_id,causal_group_id,content_hash,public_text FROM short_horizon_chunks "
        "ORDER BY causal_group_id,chunk_id"
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _epoch_events(backend: SQLiteHumanMemoryBackend) -> tuple[int, list[str]]:
    async with backend.connection.execute(
        "SELECT authority_epoch FROM recall_authority_heads WHERE principal_id=?",
        (PRINCIPAL.actor_id,),
    ) as cursor:
        row = await cursor.fetchone()
    async with backend.connection.execute(
        "SELECT event_kind FROM recall_authority_events WHERE principal_id=? "
        "ORDER BY authority_epoch",
        (PRINCIPAL.actor_id,),
    ) as cursor:
        kinds = [str(item[0]) for item in await cursor.fetchall()]
    return (0 if row is None else int(row[0])), kinds


@pytest.mark.asyncio
async def test_unsplit_ids_are_byte_identical_to_0_6_29_and_incident_group_is_capped(
    tmp_path: Path,
) -> None:
    backend = await _backend(tmp_path / "cap.db", _fixture())
    built = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert built.projected_chunk_count == 1 + SHORT_HORIZON_CHUNK_MAX_SEGMENTS + 1
    assert built.removed_chunk_count == 0
    assert built.split_group_count == 1 and built.truncated_group_count == 1
    rows = await _chunk_rows(backend)
    by_key = {str(row["causal_group_id"]): row for row in rows}
    # 未分段的组：id、content_hash、投影键（裸 Host id）与 0.6.29 逐字相同。
    assert by_key["group-small"]["chunk_id"] == GOLDEN_SMALL_CHUNK_ID
    assert by_key["group-small"]["content_hash"] == GOLDEN_SMALL_CONTENT_HASH
    assert by_key["group-recent-3"]["chunk_id"] == GOLDEN_RECENT_3_CHUNK_ID
    assert GOLDEN_LEGACY_LONG_CHUNK_ID not in {row["chunk_id"] for row in rows}
    # 超长组：8 段、投影键 id\x1fk/8、每段 ≤ 2 048 码点、内容寻址、整组血缘。
    segments = [by_key[f"group-long\x1f{k}/8"] for k in range(1, 9)]
    assert len({str(row["chunk_id"]) for row in segments}) == 8
    for row in segments:
        text = str(row["public_text"])
        assert 0 < len(text) <= SHORT_HORIZON_CHUNK_MAX_CHARS
        assert hashlib.sha256(text.encode()).hexdigest() == row["content_hash"]
        async with backend.connection.execute(
            "SELECT item_ordinal,registration_id FROM short_horizon_chunk_evidence "
            "WHERE chunk_id=? ORDER BY item_ordinal",
            (row["chunk_id"],),
        ) as cursor:
            evidence = [tuple(item) for item in await cursor.fetchall()]
        assert evidence == [(1, "registration-3"), (2, "registration-4")]
    head = "user: 把校对脚本跑一遍。\nassistant: 第001段"
    assert str(segments[0]["public_text"]).startswith(head)
    assert all(str(row["public_text"]).startswith("assistant: 第") for row in segments[1:])
    joined = "".join(str(row["public_text"]).partition("assistant: ")[2] for row in segments)
    assert _incident_body().startswith(joined) and "ZEBRA-TAIL-MARKER" not in joined  # 尾段被截
    # FTS 镜像逐行对应；审计记录切段/截断计数；重建幂等（replay）。
    async with backend.connection.execute(
        "SELECT chunk_id,public_text FROM short_horizon_fts ORDER BY chunk_id"
    ) as cursor:
        fts = sorted((str(a), str(b)) for a, b in await cursor.fetchall())
    assert fts == sorted((str(r["chunk_id"]), str(r["public_text"])) for r in rows)
    async with backend.connection.execute(
        "SELECT audit_json FROM short_horizon_audit WHERE audit_id=?", (built.audit_id,)
    ) as cursor:
        audit = json.loads(str((await cursor.fetchone())[0]))
    assert audit["details"]["split_group_count"] == 1
    assert audit["details"]["truncated_group_count"] == 1
    assert "ZEBRA" not in json.dumps(audit) and "第001段" not in json.dumps(audit)
    replay = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert (replay.projected_chunk_count, replay.removed_chunk_count) == (10, 0)
    assert (replay.split_group_count, replay.truncated_group_count) == (1, 1)
    # 关闭重开：一致性校验按投影键重推每一段。
    await backend.close()
    reopened = await _backend(tmp_path / "cap.db", _fixture(), register=False)
    assert await _chunk_rows(reopened) == rows
    await reopened.close()


@pytest.mark.asyncio
async def test_tail_segment_is_recallable_and_history_visible(tmp_path: Path) -> None:
    from simple_harness_memory import build_human_memory_v7

    pairs = _fixture()
    manager = await build_human_memory_v7(
        tmp_path / "recall.db",
        clock=lambda: NOW,
        conversation_evidence_authority=_Authority([reg for reg, _ in pairs]),
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
    )
    try:
        for reg, ref in pairs:
            await manager.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
            await manager.register_conversation_evidence(ref)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 10
        rows = await _chunk_rows(manager._backend)
        last = next(row for row in rows if row["causal_group_id"] == "group-long\x1f8/8")
        others = [row for row in rows if row is not last]
        code = next(
            token
            for token in re.findall(r"E\d{4}", str(last["public_text"]))
            if all(token not in str(row["public_text"]) for row in others)
        )
        result = await manager.recall_short_horizon(
            principal=PRINCIPAL, query=code, disclosure_context=_disclosure()
        )
        # 词面 lane 只命中尾段（entity-time lane 按共享实体把其余段一并列为候选，排在后面）。
        assert result.eligible_count == 10 and result.fts_count == 1
        hit = result.hits[0]
        assert hit.chunk_ref == last["chunk_id"] and hit.content_hash == last["content_hash"]
        assert len(hit.content) <= SHORT_HORIZON_CHUNK_MAX_CHARS
        assert all(len(item.content) <= SHORT_HORIZON_CHUNK_MAX_CHARS for item in result.hits)
        binding = m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
        snapshot = await manager.check_history_visibility(
            principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert snapshot.items[0].visible and snapshot.items[0].reason == "history_visible"
        # 被截掉的尾部不在任何 chunk 里：词面 lane 零命中。
        truncated = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="ZEBRA-TAIL-MARKER", disclosure_context=_disclosure()
        )
        assert truncated.fts_count == 0
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_legacy_unsplit_row_opens_and_next_rebuild_replaces_it_with_one_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from simple_harness_memory import build_human_memory_v7

    pairs = _fixture()
    path = tmp_path / "legacy.db"
    # 用极大的上限复现 0.6.29 的"一组一条"投影；产出的 id 必须是 0.6.29 源算出的字面值。
    monkeypatch.setattr(core_short_horizon, "SHORT_HORIZON_CHUNK_MAX_CHARS", 10**9)
    backend = await _backend(path, pairs)
    legacy = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert legacy.projected_chunk_count == 3 and legacy.split_group_count == 0
    legacy_rows = await _chunk_rows(backend)
    legacy_long = next(row for row in legacy_rows if row["causal_group_id"] == "group-long")
    assert legacy_long["chunk_id"] == GOLDEN_LEGACY_LONG_CHUNK_ID
    assert legacy_long["content_hash"] == GOLDEN_LEGACY_LONG_CONTENT_HASH
    prefix = "user: 把校对脚本跑一遍。\nassistant: "
    assert len(str(legacy_long["public_text"])) == INCIDENT_CHARS + len(prefix)
    await backend.close()
    monkeypatch.undo()

    # 0.6.30 打开同一个库：遗留超长行不是损坏，可召回、可见。
    manager = await build_human_memory_v7(
        path,
        clock=lambda: NOW,
        conversation_evidence_authority=_Authority([reg for reg, _ in pairs]),
        short_horizon_embedder=HashEmbedder(32),
        allow_development_embedder=True,
    )
    try:
        assert await _chunk_rows(manager._backend) == legacy_rows
        result = await manager.recall_short_horizon(
            principal=PRINCIPAL, query="ZEBRA-TAIL-MARKER", disclosure_context=_disclosure()
        )
        hit = result.hits[0]
        assert result.fts_count == 1 and hit.chunk_ref == GOLDEN_LEGACY_LONG_CHUNK_ID
        binding = m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
        before = await manager.check_history_visibility(
            principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert before.items[0].visible
        assert await _epoch_events(manager._backend) == (0, [])

        # 下一次重建：旧 chunk_id 消失 = 真正的 source 失效 → 推进一次 epoch（0.6.28 车道）。
        rebuilt = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert rebuilt.projected_chunk_count == 10 and rebuilt.removed_chunk_count == 1
        assert rebuilt.split_group_count == 1 and rebuilt.truncated_group_count == 1
        rows = await _chunk_rows(manager._backend)
        ids = {row["chunk_id"] for row in rows}
        assert GOLDEN_LEGACY_LONG_CHUNK_ID not in ids and GOLDEN_SMALL_CHUNK_ID in ids
        # 惰性建头 initialized（0→1）之后恰好一次资格事件（→2），没有别的车道推进。
        assert await _epoch_events(manager._backend) == (
            2, ["initialized", "short_horizon_projection_changed"],
        )
        after = await manager.check_history_visibility(
            principal=PRINCIPAL, disclosure_context=_disclosure(), bindings=(binding,)
        )
        assert not after.items[0].visible
        # 再次重建：纯 replay，epoch 不再动。
        again = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert again.removed_chunk_count == 0
        assert await _epoch_events(manager._backend) == (
            2, ["initialized", "short_horizon_projection_changed"],
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_generation_rebuild_reuses_vectors_and_embeds_only_new_chunks(
    tmp_path: Path,
) -> None:
    pairs = _fixture(extra_recent=1)  # 最后一个注册（group-recent-14）稍后才登记
    embedder = _CountingEmbedder()
    backend = await _backend(tmp_path / "reuse.db", pairs[:-1], embedder=embedder, known=pairs)
    first = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert first.projected_chunk_count == 10
    generation_1 = await backend.rebuild_short_horizon_generation()
    assert generation_1.activated and generation_1.vector_count == 10
    assert [len(batch) for batch in embedder.batches] == [10]
    async with backend.connection.execute(
        "SELECT chunk_id,embedding,embedding_hash FROM short_horizon_vectors "
        "WHERE generation_id=? ORDER BY chunk_id",
        (generation_1.generation_id,),
    ) as cursor:
        vectors_1 = {str(r[0]): (bytes(r[1]), str(r[2])) for r in await cursor.fetchall()}

    reg, ref = pairs[-1]
    await backend.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
    await backend.register_conversation_evidence(ref)
    second = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert second.projected_chunk_count == 11 and second.removed_chunk_count == 0
    generation_2 = await backend.rebuild_short_horizon_generation()
    assert generation_2.activated and generation_2.vector_count == 11
    assert generation_2.generation_id != generation_1.generation_id
    # 只嵌入新出现的那一条 chunk；其余 10 条沿用 active 世代的向量字节。
    assert [len(batch) for batch in embedder.batches] == [10, 1]
    assert embedder.batches[1] == ["user: recent note 4"]
    async with backend.connection.execute(
        "SELECT chunk_id,embedding,embedding_hash FROM short_horizon_vectors "
        "WHERE generation_id=? ORDER BY chunk_id",
        (generation_2.generation_id,),
    ) as cursor:
        vectors_2 = {str(r[0]): (bytes(r[1]), str(r[2])) for r in await cursor.fetchall()}
    assert set(vectors_1) < set(vectors_2)
    assert all(vectors_2[chunk_id] == value for chunk_id, value in vectors_1.items())
    async with backend.connection.execute(
        "SELECT audit_json FROM short_horizon_audit WHERE audit_id=?", (generation_2.audit_id,)
    ) as cursor:
        audit = json.loads(str((await cursor.fetchone())[0]))
    assert audit["details"]["embedded_count"] == 1
    assert audit["details"]["reused_vector_count"] == 10
    recall = await backend.recall_short_horizon(
        principal=PRINCIPAL, query="unmatched-vector-query", disclosure_context=_disclosure()
    )
    assert recall.used_generation_id == generation_2.generation_id
    assert recall.vector_count == 11 and recall.degradation_code is None
    # 关闭重开后向量一致性校验照常通过。
    await backend.close()
    reopened = await _backend(tmp_path / "reuse.db", pairs, embedder=embedder, register=False)
    replay = await reopened.rebuild_short_horizon_generation()
    assert replay.replayed and replay.generation_id == generation_2.generation_id
    assert [len(batch) for batch in embedder.batches] == [10, 1]
    await reopened.close()


@pytest.mark.asyncio
async def test_registration_rejects_reserved_separator_in_causal_group_id(tmp_path: Path) -> None:
    pairs = [
        _registration(1, "group\x1f1/2", 1, 1, 1, ConversationEvidenceRole.USER, "reserved"),
    ]
    backend = await _backend(tmp_path / "reserved.db", pairs, register=False)
    reg, ref = pairs[0]
    await backend.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
    with pytest.raises(MemoryValidationError, match="causal_group_id_reserved"):
        await backend.register_conversation_evidence(ref)
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM conversation_evidence_registrations"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 0
    await backend.close()


@pytest.mark.asyncio
async def test_suppression_and_expiry_apply_to_every_segment_of_a_group(
    tmp_path: Path,
) -> None:
    from simple_harness_memory.core.suppression import (
        SuppressionRequest,
        SuppressionScopeKind,
    )

    pairs = _fixture()
    clock = [NOW]
    backend = SQLiteHumanMemoryBackend(
        tmp_path / "segments.db",
        now=lambda: clock[0],
        conversation_evidence_authority=_Authority([reg for reg, _ in pairs]),
        short_horizon_embedder=HashEmbedder(32),
    )
    await backend.initialize()
    _OPEN.append(backend)
    for reg, ref in pairs:
        await backend.ingest_committed_evidence(reg.envelope, reg.admission_receipt)
        await backend.register_conversation_evidence(ref)
    built = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert built.projected_chunk_count == 10
    # 压制超长组的第一条证据：整组 8 段一起消失（部分上下文绝不可见）。
    await backend.suppress(
        principal=PRINCIPAL,
        request=SuppressionRequest(
            "forget-1", PRINCIPAL.actor_id, SuppressionScopeKind.EVIDENCE, "evidence-3",
            "user_forget", NOW,
        ),
    )
    rebuilt = await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
    assert rebuilt.projected_chunk_count == 2 and rebuilt.removed_chunk_count == 8
    assert {row["causal_group_id"] for row in await _chunk_rows(backend)} == {
        "group-small", "group-recent-3",
    }
    # 过期按 chunk 行判定，与 0.6.29 相同：跨过 5 天后 cleanup 一并移除。
    clock[0] = NOW + SHORT_HORIZON_RETENTION_SECONDS + 10
    cleaned = await backend.cleanup_short_horizon(principal=PRINCIPAL)
    assert cleaned == 2 and await _chunk_rows(backend) == []
    await backend.close()


@pytest.mark.asyncio
async def test_split_is_deterministic_across_fresh_databases(tmp_path: Path) -> None:
    ids = []
    for name in ("a.db", "b.db"):
        backend = await _backend(tmp_path / name, _fixture())
        await backend.rebuild_short_horizon_projection(principal=PRINCIPAL)
        rows = await _chunk_rows(backend)
        ids.append([(r["chunk_id"], r["causal_group_id"], r["content_hash"]) for r in rows])
        await backend.close()
    assert ids[0] == ids[1] and len(ids[0]) == 10
