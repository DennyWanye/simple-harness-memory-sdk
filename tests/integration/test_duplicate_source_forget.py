"""Real SQLite/public S1 and mutation; Host-order authority is a controlled fixture.

Pending/no-materialization duplicate is not a replay of the native no_mutation job.
"""

import hashlib
from dataclasses import replace

import pytest
import simple_harness as h
from simple_harness.contracts import canonical_json

import simple_harness_memory as m
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _Authority, _admitted, _classification_policy, _disclosure, _operation,
    _plan, _principal, _span,
)


TEXT = "请记住：我的默认饮品偏好是无糖乌龙茶。"
NS = m.HistorySourceNamespace("a" * 64, "actor-1", "primary:p1:foreground_turns")


def source(eid, text=TEXT, parent=None):
    env, receipt = _admitted(evidence_id=eid)
    old_span = _span(env, receipt)
    payload = {"schema_version": 1, "delivery_key": eid, "text": text}
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    env = replace(
        env, sanitized_payload=payload, sanitized_hash=digest, source_hash=digest,
        source_kind=(h.EvidenceSourceKind.USER_MESSAGE if parent is None
                     else h.EvidenceSourceKind.ASSISTANT_MESSAGE),
        evidence_refs=(() if parent is None else (
            h.EvidenceRef(parent.envelope.evidence_id, parent.envelope.envelope_hash, 1),
        )),
    )
    receipt = replace(
        receipt, envelope_hash=env.envelope_hash, source_hash=digest, sanitized_hash=digest,
        evidence_refs=env.evidence_refs,
    )
    span = replace(
        old_span, envelope_hash=env.envelope_hash, sanitized_hash=digest, source_hash=digest,
        admission_receipt_hash=receipt.receipt_hash, item_json_pointer="/text",
        end_byte=len(text.encode()), exact_quote=text,
        quote_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    return m.HistoryEvidenceBinding(env, receipt), span


class Origins:
    def __init__(self):
        self.sources = {}
        self.cuts = {}
        self.backend = None
        self.hook = None
        self.calls = []

    def register(self, binding, seq, proof="atomic"):
        env, receipt = binding.envelope, binding.receipt
        self.sources[env.evidence_id] = m.HistorySourceOriginReceipt(
            NS, seq, env.evidence_id, env.envelope_hash,
            receipt.receipt_id, receipt.receipt_hash, proof,
        )

    async def resolve_history_source(self, *, principal, envelope, receipt):
        self.assert_unlocked()
        self.calls.append(("source", envelope.evidence_id))
        if self.hook:
            hook, self.hook = self.hook, None
            await hook()
        return self.sources.get(envelope.evidence_id)

    async def resolve_history_forget_cut(self, *, principal, decision):
        self.assert_unlocked()
        self.calls.append(("cut", decision.request_id))
        return self.cuts.get(decision.request_id)

    def assert_unlocked(self):
        if self.backend is not None:
            assert not self.backend._write_lock.locked()
            assert not self.backend._db.in_transaction


async def prepared(path, *, use_new_builder=True):
    seed, span = source("seed")
    evidence_authority = _Authority(seed.envelope, seed.receipt, span)
    origins = Origins()
    origins.register(seed, 2)
    kwargs = {"history_source_authority": origins} if use_new_builder else {}
    manager = await m.MemoryManager.build_human_memory_v7(
        path, evidence_authority=evidence_authority,
        memory_action_authority=evidence_authority,
        classification_policy=_classification_policy(), clock=lambda: 20.0, **kwargs,
    )
    origins.backend = manager.backend
    await manager.ingest_committed_evidence(seed.envelope, seed.receipt)
    applied = await manager.apply_memory_mutation_plan(
        principal=_principal(), scope=m.MemoryScope.personal("actor-1"),
        plan=_plan(seed.envelope, _operation(span)),
    )
    view = await manager.get_memory_mutation_receipt_view(
        principal=_principal(), receipt_ref=applied.receipt_ref,
    )
    return manager, origins, seed, view.operations[0].memory_id


async def forget(manager, origins, mid, key="forget-1", legacy=False):
    request = m.SuppressionRequest(key, "actor-1", m.SuppressionScopeKind.MEMORY,
                                   mid, "user_forget", 20.0)
    if not legacy:
        origins.cuts.setdefault(key, m.HistoryForgetCutReceipt(
            NS, 2, key, m.SuppressionScopeKind.MEMORY, mid, "action-s1", "d" * 64,
        ))
    return await manager.suppress(request=request, principal=_principal())


async def check(manager, *bindings):
    return await manager.check_history_visibility(
        principal=_principal(), disclosure_context=_disclosure(), bindings=tuple(bindings),
    )


@pytest.mark.asyncio
async def test_no_authority_legacy_duplicate_is_not_silently_allowed(tmp_path):
    manager, origins, seed, mid = await prepared(tmp_path / "baseline.db", use_new_builder=False)
    old, _ = source("old")
    try:
        await manager.ingest_committed_evidence(old.envelope, old.receipt)
        assert (await check(manager, old)).items[0].visible
        assert old.envelope.source_hash != seed.envelope.source_hash
        await forget(manager, origins, mid, legacy=True)
        observed = (await check(manager, old)).items[0]
        assert not observed.visible
        assert observed.reason == "history_source_cut_unverifiable"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ingestion", ["before", "after", "cold"])
async def test_duplicate_and_real_dependent_answer_deny_without_materializing_old(tmp_path, ingestion):
    manager, origins, seed, mid = await prepared(tmp_path / "duplicate.db")
    old, _ = source("old")
    child, _ = source("answer", "已记住", old)
    other, _ = source("other", "普通无关问题")
    origins.register(old, 1, "legacy_before_only")
    try:
        if ingestion == "before":
            await manager.ingest_committed_evidence(old.envelope, old.receipt)
        assert all(item.visible for item in (await check(manager, old, child, other)).items)
        await forget(manager, origins, mid)
        if ingestion == "after":
            await manager.ingest_committed_evidence(old.envelope, old.receipt)
        result = await check(manager, old, child, other, seed)
        assert [x.visible for x in result.items] == [False, False, True, False]
        assert result.items[0].reason == "history_suppressed"
        assert result.items[1].reason == "history_suppressed"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof,expected,reason", [
    ("atomic", True, "history_visible"),
    ("legacy_before_only", False, "history_source_cut_unverifiable"),
    (None, False, "history_source_cut_unverifiable"),
])
async def test_postcut_requires_actual_atomic_admission_not_late_enqueue(tmp_path, proof, expected, reason):
    manager, origins, seed, mid = await prepared(tmp_path / "after.db")
    new, _ = source("new")
    if proof:
        origins.register(new, 3, proof)
    try:
        first = await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        after = (await check(manager, new, seed)).items
        assert (after[0].visible, after[0].reason) == (expected, reason)
        assert not after[1].visible
        replay = await forget(manager, origins, mid)
        assert replay == first
        assert origins.cuts[first.request_id].through_sequence == 2
        assert (await check(manager, new)).items[0].visible is expected
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["subject", "store_epoch", "stream", "pair", "cut_target"])
async def test_exact_host_proof_bindings_cannot_grant_from_foreign_facts(tmp_path, field):
    manager, origins, seed, mid = await prepared(tmp_path / "forged.db")
    new, _ = source("new")
    origins.register(new, 3)
    try:
        decision = await forget(manager, origins, mid)
        origin = origins.sources["new"]
        if field == "subject":
            origin = replace(origin, namespace=replace(NS, subject="other"))
        elif field == "store_epoch":
            origin = replace(origin, namespace=replace(NS, store_epoch="b" * 64))
        elif field == "stream":
            origin = replace(origin, namespace=replace(NS, source_stream="primary:other:foreground_turns"))
        elif field == "pair":
            origin = replace(origin, admission_receipt_hash="e" * 64)
        else:
            cut = origins.cuts[decision.request_id]
            origins.cuts[decision.request_id] = replace(cut, scope_ref="other-memory")
        origins.sources["new"] = origin
        result = await check(manager, new)
        assert result.items[0].reason == "history_source_cut_unverifiable"
    finally:
        await manager.close()
