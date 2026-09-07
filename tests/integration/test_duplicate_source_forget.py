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
    _admitted,
    _Authority,
    _classification_policy,
    _disclosure,
    _operation,
    _plan,
    _principal,
    _span,
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


async def forget_evidence(manager, evidence_id, key="forget-evidence"):
    """EVIDENCE 范围压制：2026-09-07 决定后仍是唯一会隐藏来源对话证据的路径。"""
    return await manager.suppress(principal=_principal(), request=m.SuppressionRequest(
        key, "actor-1", m.SuppressionScopeKind.EVIDENCE, evidence_id, "user_forget", 20.0,
    ))


async def learn(manager, binding, span, plan_id):
    """Re-learn a memory from an already ingested source through the public mutation path."""
    manager.backend._evidence_authority.register_admitted(binding.envelope, binding.receipt, span)
    async with manager.backend.connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id=?", ("actor-1",),
    ) as cursor:
        row = await cursor.fetchone()
    result = await manager.apply_memory_mutation_plan(
        principal=_principal(), scope=m.MemoryScope.personal("actor-1"),
        plan=_plan(binding.envelope, _operation(span), base_revision=1 if row is None else int(row[0]),
                   plan_id=plan_id, idempotency_key=plan_id),
    )
    assert result.outcome is h.MemoryMutationApplyOutcome.COMMITTED
    view = await manager.get_memory_mutation_receipt_view(
        principal=_principal(), receipt_ref=result.receipt_ref,
    )
    return view.operations[0].memory_id


async def resolve_memory(manager, memory_id):
    from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose, SuppressionCandidate

    return await manager.backend.resolve_suppression(
        SuppressionCandidate("actor-1", memory_id=memory_id), OrdinaryMemoryPurpose.RECALL,
        principal=_principal(),
    )


@pytest.mark.asyncio
async def test_no_authority_legacy_duplicate_memory_denied_while_evidence_stays_visible(tmp_path):
    """2026-09-07 决定：无 Host 授权的旧式遗忘不再隐藏重复来源证据，但重复重学的记忆仍被拒绝。"""
    manager, origins, seed, mid = await prepared(tmp_path / "baseline.db", use_new_builder=False)
    old, span = source("old")
    try:
        await manager.ingest_committed_evidence(old.envelope, old.receipt)
        assert (await check(manager, old)).items[0].visible
        assert old.envelope.source_hash != seed.envelope.source_hash
        await forget(manager, origins, mid, legacy=True)
        observed = (await check(manager, old, seed)).items
        assert [(item.visible, item.reason) for item in observed] == [
            (True, "history_visible"), (True, "history_visible"),
        ]
        assert (await resolve_memory(manager, mid)).denied
        relearned = await learn(manager, old, span, "relearn-old")
        assert relearned != mid
        # No proof is available at all, so the duplicate memory is not silently allowed.
        assert (await resolve_memory(manager, relearned)).denied
        assert (await check(manager, old)).items[0].visible
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_memory_forget_keeps_dependent_visible_and_evidence_scope_still_denies(tmp_path):
    """2026-09-07 决定：MEMORY 范围遗忘不隐藏被遗忘记忆来源的派生证据；EVIDENCE 范围压制仍会隐藏。"""
    manager, origins, seed, mid = await prepared(tmp_path / "other-profile.db")
    unrelated_env, unrelated_receipt = _admitted(evidence_id="unrelated-public-text")
    from tests.integration.test_history_visibility import _rebind

    unrelated = m.HistoryEvidenceBinding(unrelated_env, unrelated_receipt)
    child_env, child_receipt = _admitted(evidence_id="dependent-public-text")
    dependent = _rebind(child_env, child_receipt, evidence_refs=(
        h.EvidenceRef(seed.envelope.evidence_id, seed.envelope.envelope_hash, 1),
    ))
    try:
        before = await check(manager, unrelated, dependent)
        assert all(item.visible for item in before.items)
        await forget(manager, origins, mid)
        after = await check(manager, unrelated, dependent, seed)
        assert [item.visible for item in after.items] == [True, True, True]
        assert (await resolve_memory(manager, mid)).denied
        await forget_evidence(manager, seed.envelope.evidence_id)
        controlled = await check(manager, unrelated, dependent, seed)
        assert [item.visible for item in controlled.items] == [True, False, False]
        assert controlled.items[1].reason == "history_suppressed"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ingestion", ["before", "after", "cold"])
async def test_duplicate_and_dependent_answer_stay_visible_without_materializing_old(
    tmp_path, ingestion,
):
    """2026-09-07 决定：重复来源及其回答在 MEMORY 遗忘后仍可见且不落库；重学记忆被拒；EVIDENCE 范围才隐藏。"""
    manager, origins, seed, mid = await prepared(tmp_path / "duplicate.db")
    old, span = source("old")
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
        assert [x.visible for x in result.items] == [True, True, True, True]
        assert {x.reason for x in result.items} == {"history_visible"}
        assert (await resolve_memory(manager, mid)).denied
        if ingestion == "cold":
            assert await manager.backend._read_ingested_record("old") is None
        else:
            relearned = await learn(manager, old, span, "relearn-old")
            assert (await resolve_memory(manager, relearned)).denied
        await forget_evidence(manager, "old")
        controlled = await check(manager, old, child, other, seed)
        assert [x.visible for x in controlled.items] == [False, False, True, True]
        assert controlled.items[0].reason == "history_suppressed"
        assert controlled.items[1].reason == "history_suppressed"
        if ingestion == "cold":
            assert await manager.backend._read_ingested_record("old") is None
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof,denied", [
    ("atomic", False),
    ("legacy_before_only", True),
    (None, True),
])
async def test_postcut_relearned_memory_requires_actual_atomic_admission_not_late_enqueue(
    tmp_path, proof, denied,
):
    """2026-09-07 决定：切点后的来源证据始终可见；原子入库证明只决定重学记忆是否被拒。"""
    manager, origins, seed, mid = await prepared(tmp_path / "after.db")
    new, span = source("new")
    if proof:
        origins.register(new, 3, proof)
    try:
        first = await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        after = (await check(manager, new, seed)).items
        assert [(item.visible, item.reason) for item in after] == [
            (True, "history_visible"), (True, "history_visible"),
        ]
        relearned = await learn(manager, new, span, "relearn-new")
        assert (await resolve_memory(manager, relearned)).denied is denied
        assert (await resolve_memory(manager, mid)).denied
        replay = await forget(manager, origins, mid)
        assert replay == first
        assert origins.cuts[first.request_id].through_sequence == 2
        assert (await resolve_memory(manager, relearned)).denied is denied
        assert (await check(manager, new)).items[0].visible
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["subject", "store_epoch", "stream", "pair", "cut_target"])
async def test_exact_host_proof_bindings_cannot_grant_from_foreign_facts(tmp_path, field):
    """2026-09-07 决定：切点/来源证明只裁决重学记忆，伪造的 Host 事实不能放行重复记忆。"""
    manager, origins, seed, mid = await prepared(tmp_path / "forged.db")
    new, span = source("new")
    origins.register(new, 3)
    try:
        decision = await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        relearned = await learn(manager, new, span, "relearn-new")
        assert not (await resolve_memory(manager, relearned)).denied
        origin = origins.sources["new"]
        if field == "subject":
            origin = replace(origin, namespace=replace(NS, subject="other"))
        elif field == "store_epoch":
            origin = replace(origin, namespace=replace(NS, store_epoch="b" * 64))
        elif field == "stream":
            origin = replace(origin, namespace=replace(
                NS, source_stream="primary:other:foreground_turns",
            ))
        elif field == "pair":
            origin = replace(origin, admission_receipt_hash="e" * 64)
        else:
            cut = origins.cuts[decision.request_id]
            origins.cuts[decision.request_id] = replace(cut, scope_ref="other-memory")
        origins.sources["new"] = origin
        assert (await resolve_memory(manager, relearned)).denied
        assert (await check(manager, new)).items[0].visible
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_second_manager_commit_during_host_await_invalidates_final_snapshot(tmp_path):
    """2026-09-07 决定：外部提交仍使重学记忆的最终快照失效；来源证据本身保持可见。"""
    from simple_harness_memory.core.errors import MemoryWriterConflict

    path = tmp_path / "external.db"
    manager, origins, seed, mid = await prepared(path)
    new, span = source("new")
    origins.register(new, 3)
    second = None
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        relearned = await learn(manager, new, span, "relearn-new")
        assert not (await resolve_memory(manager, relearned)).denied
        # Production enforces a writer lease. First prove it; then deliberately
        # release that lease as a source-test fault to retain a stale connection
        # while a REAL second manager writes through public suppress (no SQL edit).
        with pytest.raises(MemoryWriterConflict):
            await m.MemoryManager.build_human_memory_v7(path)
        manager.backend._release_writer_lease()
        second = await m.MemoryManager.build_human_memory_v7(path)
        before_changes = manager.backend.connection.total_changes

        async def external_commit():
            await second.suppress(
                request=m.SuppressionRequest("external-forget", "actor-1",
                    m.SuppressionScopeKind.MEMORY, mid, "user_forget", 20.0),
                principal=_principal(),
            )

        origins.hook = external_commit
        result = await resolve_memory(manager, relearned)
        assert result.denied
        assert manager.backend.connection.total_changes == before_changes
        assert origins.hook is None
        assert ("cut", "external-forget") not in origins.calls  # not in prefetch
        assert (await check(manager, new)).items[0].visible
    finally:
        if second is not None:
            await second.close()
        await manager.close()


@pytest.mark.asyncio
async def test_direct_current_gate_and_reopen_keep_exact_cut(tmp_path):
    """2026-09-07 决定：切点只裁决重学记忆（切点前重复被拒、切点后原子入库放行），证据始终可见，重开后不变。"""
    path = tmp_path / "reopen.db"
    manager, origins, seed, mid = await prepared(path)
    old, old_span = source("old")
    new, new_span = source("new")
    origins.register(old, 1, "legacy_before_only")
    origins.register(new, 3)
    try:
        for binding in (old, new):
            await manager.ingest_committed_evidence(binding.envelope, binding.receipt)
        await forget(manager, origins, mid)
        snapshot = await check(manager, old, new)
        assert [i.visible for i in snapshot.items] == [True, True]
        memories = {
            "old": await learn(manager, old, old_span, "relearn-old"),
            "new": await learn(manager, new, new_span, "relearn-new"),
        }
        for name, denied in (("old", True), ("new", False)):
            assert (await resolve_memory(manager, memories[name])).denied is denied
    finally:
        await manager.close()

    manager = await m.MemoryManager.build_human_memory_v7(
        path, history_source_authority=origins, classification_policy=_classification_policy(),
        clock=lambda: 20.0,
    )
    origins.backend = manager.backend
    try:
        reopened = await check(manager, old, new)
        assert [i.visible for i in reopened.items] == [True, True]
        assert reopened.policy_hash == snapshot.policy_hash
        for name, denied in (("old", True), ("new", False)):
            assert (await resolve_memory(manager, memories[name])).denied is denied
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_same_operation_cross_transaction_cache_observes_external_data_version(tmp_path):
    from simple_harness_memory.backends.history_source_guard import (
        history_source_operation,
        prepare_history_source_context,
    )
    from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose, SuppressionCandidate

    path = tmp_path / "data-version.db"
    manager, origins, seed, mid = await prepared(path)
    new, span = source("new")
    origins.register(new, 3)
    second = None
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        # 2026-09-07 决定：目录缓存失效通过重学记忆候选（而非证据候选）观察。
        relearned = await learn(manager, new, span, "relearn-new")
        manager.backend._release_writer_lease()  # controlled lease-handoff fault, as above
        second = await m.MemoryManager.build_human_memory_v7(path)

        @history_source_operation
        async def same_operation(backend):
            await prepare_history_source_context(backend, _principal())
            candidate = SuppressionCandidate("actor-1", memory_id=relearned)
            async with backend._write_lock:
                await backend.connection.execute("BEGIN")
                before = await backend._resolve_suppression_unlocked(
                    candidate, OrdinaryMemoryPurpose.RECALL,
                )
                await backend.connection.execute("COMMIT")
            assert not before.denied  # populates THIS operation's catalog cache
            changes = backend.connection.total_changes
            await second.suppress(request=m.SuppressionRequest(
                "external-second", "actor-1", m.SuppressionScopeKind.MEMORY,
                mid, "user_forget", 20.0,
            ), principal=_principal())
            assert backend.connection.total_changes == changes
            async with backend._write_lock:
                await backend.connection.execute("BEGIN")
                after = await backend._resolve_suppression_unlocked(
                    candidate, OrdinaryMemoryPurpose.RECALL,
                )
                await backend.connection.execute("COMMIT")
            assert after.denied

        await same_operation(manager.backend)
    finally:
        if second:
            await second.close()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof,recallable", [("atomic", True), ("legacy_before_only", False)])
async def test_fresh_reassert_commits_and_typed_recall_gate_denies_unproven_duplicate(
    tmp_path, proof, recallable,
):
    """2026-09-07 决定：重新断言的来源证据可写入记忆；typed recall 与直接候选共用重学记忆闸门。"""
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    manager, origins, seed, mid = await prepared(tmp_path / "mutation-recall.db")
    new, span = source("new")
    origins.register(new, 3, proof)
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        assert (await check(manager, new, seed)).items[0].visible
        relearned = await learn(manager, new, span, "new-plan")
        assert (await resolve_memory(manager, relearned)).denied is not recallable
        context = _context()
        execution = await manager.execute_typed_recall(
            principal=_principal(), context=context,
            plan=_recall_plan(context, idempotency_key="recall-new"),
        )
        assert len(execution.result.items) == int(recallable)
        if recallable:
            item = execution.result.items[0]
            assert item.selected_item.source_ref != mid
            binding = m.HistoryRecallBinding(
                execution.result.result_id, execution.result.result_hash,
                item.selected_item.item_id, item.result_item_hash,
            )
            assert (await check(manager, binding)).items[0].visible
            fragment = h.ContextFragmentBindingV2("fragment-1", "f" * 64)
            manifest = hashlib.sha256(canonical_json([fragment.to_json()]).encode()).hexdigest()
            request = h.RecallContextUseAuthorizationRequestV1(
                "actor-1", context.run_id, context.turn_id, "provider-new-assertion",
                execution.decision.decision_id, execution.decision.decision_hash,
                execution.result.result_id, execution.result.result_hash,
                (h.RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
                (fragment,), manifest, 20.0,
            )
            receipt = await manager.authorize_recall_context_use(
                principal=_principal(), request=request,
            )
            assert receipt == await manager.authorize_recall_context_use(
                principal=_principal(), request=request,
            )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_revise_preserves_old_revision_seed_and_unrelated_exact_text_control(tmp_path):
    """2026-09-07 决定：修订后旧版本种子仍裁决重学的重复记忆，精确文本对照记忆放行；证据全部可见。"""
    from tests.integration.test_cognitive_mutation_repository_v5 import _with_action_authorities

    manager, origins, seed, mid = await prepared(tmp_path / "revision.db")
    old, old_span = source("old")
    correction, span = source("correction", "请把饮品偏好改成柠檬水。")
    unrelated, unrelated_span = source("other", TEXT + " ")  # no trim/substrings/semantic matching
    origins.register(old, 1, "legacy_before_only")
    origins.register(correction, 3)
    authority = manager.backend._evidence_authority
    authority.register_admitted(correction.envelope, correction.receipt, span)
    try:
        for binding in (correction, old, unrelated):
            await manager.ingest_committed_evidence(binding.envelope, binding.receipt)
        operation = _operation(span, kind=h.MemoryMutationKind.REVISE,
                               target=h.ExistingMemoryTarget(mid, 1))
        operation = replace(operation, payload=replace(operation.payload, object_value="lemonade"))
        revised = await manager.apply_memory_mutation_plan(
            principal=_principal(), scope=m.MemoryScope.personal("actor-1"),
            plan=_with_action_authorities(_plan(
                correction.envelope, operation, base_revision=2,
                plan_id="revise", idempotency_key="revise",
            ), authority),
        )
        assert revised.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        view = await manager.get_memory_mutation_receipt_view(
            principal=_principal(), receipt_ref=revised.receipt_ref,
        )
        assert view.operations[0].revision == 2
        from_old = await learn(manager, old, old_span, "relearn-old")
        from_unrelated = await learn(manager, unrelated, unrelated_span, "learn-unrelated")
        origins.cuts["forget-1"] = m.HistoryForgetCutReceipt(
            NS, 3, "forget-1", m.SuppressionScopeKind.MEMORY, mid, "action-s1", "d" * 64,
        )
        await forget(manager, origins, mid)
        observed = await check(manager, old, seed, correction, unrelated)
        assert [item.visible for item in observed.items] == [True, True, True, True]
        assert (await resolve_memory(manager, mid)).denied
        # Revision-1 seed text still denies the duplicate memory learned from "old";
        # the exact-text control differs by one trailing space and stays allowed.
        assert (await resolve_memory(manager, from_old)).denied
        assert not (await resolve_memory(manager, from_unrelated)).denied
    finally:
        await manager.close()
