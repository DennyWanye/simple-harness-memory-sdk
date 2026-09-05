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
async def test_other_user_profile_stays_visible_but_real_forgotten_parent_denies(tmp_path):
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
        after = await check(manager, unrelated, dependent)
        assert [item.visible for item in after.items] == [True, False]
        assert after.items[1].reason == "history_suppressed"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ingestion", ["before", "after", "cold"])
async def test_duplicate_and_real_dependent_answer_deny_without_materializing_old(
    tmp_path, ingestion,
):
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
async def test_postcut_requires_actual_atomic_admission_not_late_enqueue(
    tmp_path, proof, expected, reason,
):
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
            origin = replace(origin, namespace=replace(
                NS, source_stream="primary:other:foreground_turns",
            ))
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


@pytest.mark.asyncio
async def test_second_manager_commit_during_host_await_invalidates_final_snapshot(tmp_path):
    from simple_harness_memory.core.errors import MemoryWriterConflict

    path = tmp_path / "external.db"
    manager, origins, seed, mid = await prepared(path)
    new, _ = source("new")
    origins.register(new, 3)
    second = None
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
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
        result = await check(manager, new)
        assert result.items[0].reason == "history_source_cut_unverifiable"
        assert manager.backend.connection.total_changes == before_changes
        assert origins.hook is None
        assert ("cut", "external-forget") not in origins.calls  # not in prefetch
    finally:
        if second is not None:
            await second.close()
        await manager.close()


@pytest.mark.asyncio
async def test_direct_current_gate_and_reopen_keep_exact_cut(tmp_path):
    from simple_harness_memory.core.suppression import OrdinaryMemoryPurpose, SuppressionCandidate

    path = tmp_path / "reopen.db"
    manager, origins, seed, mid = await prepared(path)
    old, _ = source("old")
    new, _ = source("new")
    origins.register(old, 1, "legacy_before_only")
    origins.register(new, 3)
    try:
        for binding in (old, new):
            await manager.ingest_committed_evidence(binding.envelope, binding.receipt)
        await forget(manager, origins, mid)
        snapshot = await check(manager, old, new)
        assert [i.visible for i in snapshot.items] == [False, True]
        for binding, denied in ((old, True), (new, False)):
            observed = await manager.backend.resolve_suppression(
                SuppressionCandidate("actor-1", evidence_id=binding.envelope.evidence_id),
                OrdinaryMemoryPurpose.RECALL, principal=_principal(),
            )
            assert observed.denied is denied
    finally:
        await manager.close()

    manager = await m.MemoryManager.build_human_memory_v7(
        path, history_source_authority=origins, classification_policy=_classification_policy(),
        clock=lambda: 20.0,
    )
    origins.backend = manager.backend
    try:
        reopened = await check(manager, old, new)
        assert [i.visible for i in reopened.items] == [False, True]
        assert reopened.policy_hash == snapshot.policy_hash
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
    new, _ = source("new")
    origins.register(new, 3)
    second = None
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        manager.backend._release_writer_lease()  # controlled lease-handoff fault, as above
        second = await m.MemoryManager.build_human_memory_v7(path)

        @history_source_operation
        async def same_operation(backend):
            await prepare_history_source_context(backend, _principal())
            candidate = SuppressionCandidate("actor-1", evidence_id="new")
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
@pytest.mark.parametrize("proof,should_commit", [("atomic", True), ("legacy_before_only", False)])
async def test_fresh_reassert_actual_mutation_and_typed_recall_share_gate(
    tmp_path, proof, should_commit,
):
    from simple_harness_memory.core.suppression import SuppressionDenied
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    manager, origins, seed, mid = await prepared(tmp_path / "mutation-recall.db")
    new, span = source("new")
    origins.register(new, 3, proof)
    manager.backend._evidence_authority.register_admitted(new.envelope, new.receipt, span)
    try:
        await forget(manager, origins, mid)
        await manager.ingest_committed_evidence(new.envelope, new.receipt)
        plan = _plan(new.envelope, _operation(span), base_revision=2,
                     plan_id="new-plan", idempotency_key="new-plan")
        if not should_commit:
            with pytest.raises(SuppressionDenied):
                await manager.apply_memory_mutation_plan(
                    principal=_principal(), scope=m.MemoryScope.personal("actor-1"), plan=plan,
                )
        else:
            result = await manager.apply_memory_mutation_plan(
                principal=_principal(), scope=m.MemoryScope.personal("actor-1"), plan=plan,
            )
            assert result.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        context = _context()
        execution = await manager.execute_typed_recall(
            principal=_principal(), context=context,
            plan=_recall_plan(context, idempotency_key="recall-new"),
        )
        assert len(execution.result.items) == int(should_commit)
        if should_commit:
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
    from tests.integration.test_cognitive_mutation_repository_v5 import _with_action_authorities

    manager, origins, seed, mid = await prepared(tmp_path / "revision.db")
    old, _ = source("old")
    correction, span = source("correction", "请把饮品偏好改成柠檬水。")
    unrelated, _ = source("other", TEXT + " ")  # no trim/substrings/semantic matching
    origins.register(old, 1, "legacy_before_only")
    origins.register(correction, 3)
    authority = manager.backend._evidence_authority
    authority.register_admitted(correction.envelope, correction.receipt, span)
    try:
        await manager.ingest_committed_evidence(correction.envelope, correction.receipt)
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
        origins.cuts["forget-1"] = m.HistoryForgetCutReceipt(
            NS, 3, "forget-1", m.SuppressionScopeKind.MEMORY, mid, "action-s1", "d" * 64,
        )
        await forget(manager, origins, mid)
        observed = await check(manager, old, seed, correction, unrelated)
        assert [item.visible for item in observed.items] == [False, False, False, True]
        assert observed.items[0].reason == "history_suppressed"
    finally:
        await manager.close()
