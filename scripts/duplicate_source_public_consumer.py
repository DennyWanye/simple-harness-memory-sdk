"""Installed public privacy consumer; controlled Host facts, real SQLite and public receipts.

No test imports, SDK private fields/imports, SQL, provider or expected-output harvesting.
The direct NO_MUTATION control is not a replay of the native failed analysis job.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import simple_harness as h

import simple_harness_memory as m

spec = importlib.util.spec_from_file_location(
    "public_inputs", Path(__file__).with_name("verify_history_candidate.py")
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
fingerprint_json = f.fingerprint_json
NOW = 20.0
PRINCIPAL = f._principal()
TEXT = "请记住：我的默认饮品偏好是无糖乌龙茶。"
NS = m.HistorySourceNamespace("a" * 64, "actor-1", "primary:p1:foreground_turns")


@contextmanager
def rejects(kind, reason):
    try:
        yield
    except kind as exc:
        assert str(exc) == reason, str(exc)
    else:
        raise AssertionError(f"expected rejection: {reason}")


class Origins:
    def __init__(self):
        self.sources, self.cuts = {}, {}

    def register(self, binding, seq, proof="atomic"):
        env, receipt = binding.envelope, binding.receipt
        self.sources[env.evidence_id] = m.HistorySourceOriginReceipt(
            NS,
            seq,
            env.evidence_id,
            env.envelope_hash,
            receipt.receipt_id,
            receipt.receipt_hash,
            proof,
        )

    async def resolve_history_source(self, *, principal, envelope, receipt):
        assert principal == PRINCIPAL
        origin = self.sources.get(envelope.evidence_id)
        if origin:
            assert (origin.envelope_hash, origin.admission_receipt_hash) == (
                envelope.envelope_hash,
                receipt.receipt_hash,
            )
        return origin

    async def resolve_history_forget_cut(self, *, principal, decision):
        assert principal == PRINCIPAL
        cut = self.cuts.get(decision.request_id)
        if cut:
            assert cut.namespace.subject == decision.subject
            assert (cut.scope_ref, cut.scope_kind) == (decision.scope_ref, decision.scope_kind)
        return cut


class EvidenceAuthority:
    def __init__(self):
        self.items = {}

    def register(self, binding, span):
        self.items[span.span_hash] = (
            span,
            h.AdmittedEvidenceAuthority(binding.envelope, binding.receipt, f._item_authority(span)),
        )

    async def resolve_admitted_evidence(self, span):
        expected, admitted = self.items[span.span_hash]
        assert span == expected
        return admitted

    async def resolve_typed_observation(self, reference):
        raise ValueError("no typed observation fixture")


def source(eid, text=TEXT, parent=None):
    env, receipt = f._admitted(evidence_id=eid)
    span = f._span(env, receipt)
    payload = {"schema_version": 1, "delivery_key": eid, "text": text}
    digest = fingerprint_json(payload)
    env = replace(
        env,
        sanitized_payload=payload,
        sanitized_hash=digest,
        source_hash=digest,
        source_kind=h.EvidenceSourceKind.USER_MESSAGE
        if parent is None
        else h.EvidenceSourceKind.ASSISTANT_MESSAGE,
        evidence_refs=()
        if parent is None
        else (h.EvidenceRef(parent.envelope.evidence_id, parent.envelope.envelope_hash, 1),),
    )
    receipt = replace(
        receipt,
        envelope_hash=env.envelope_hash,
        source_hash=digest,
        sanitized_hash=digest,
        evidence_refs=env.evidence_refs,
    )
    span = replace(
        span,
        envelope_hash=env.envelope_hash,
        source_hash=digest,
        sanitized_hash=digest,
        admission_receipt_hash=receipt.receipt_hash,
        item_json_pointer="/text",
        end_byte=len(text.encode()),
        exact_quote=text,
        quote_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    return m.HistoryEvidenceBinding(env, receipt), span


async def check(manager, bindings, expected):
    snapshot = await manager.check_history_visibility(
        principal=PRINCIPAL,
        disclosure_context=f._disclosure(),
        bindings=tuple(bindings),
    )
    assert [i.visible for i in snapshot.items] == expected, snapshot.to_json()
    return snapshot


async def main_case(folder, mode):
    folder.mkdir()
    old, oldspan = source("old")
    seed, span = source("seed")
    answer, _ = source("answer", "已记住", old)
    fresh, freshspan = source("fresh")
    late, _ = source("late-enqueue")
    unrelated_env, unrelated_receipt = f._admitted(evidence_id="no-text-profile")
    unrelated = m.HistoryEvidenceBinding(unrelated_env, unrelated_receipt)
    origins, authority = Origins(), EvidenceAuthority()
    for binding, sequence, proof in (
        (old, 1, "legacy_before_only"),
        (seed, 2, "atomic"),
        (fresh, 3, "atomic"),
        (late, 4, "legacy_before_only"),
    ):
        origins.register(binding, sequence, proof)
    for binding, item in ((old, oldspan), (seed, span), (fresh, freshspan)):
        authority.register(binding, item)
    kwargs = dict(
        history_source_authority=origins,
        evidence_authority=authority,
        classification_policy=f._classification_policy(),
        clock=lambda: NOW,
    )
    path = folder / "memory.db"
    manager = await m.build_human_memory_v7(path, **kwargs)
    request = None
    try:
        assert type(manager.history_source_enforcement_version) is int
        assert manager.history_source_enforcement_version == 1
        await check(manager, (old, answer, unrelated), [True, True, True])
        if mode == "cold":
            context = f._context()
            plan = f._recall_plan(context, idempotency_key="protocol-check")
            for protocol, reason in (
                (5, "typed_recall_protocol_unsupported"),
                ("5", "typed_recall_protocol_invalid"),
            ):
                try:
                    await manager.execute_typed_recall(
                        principal=PRINCIPAL,
                        context=context,
                        plan=plan,
                        harness_protocol=protocol,
                    )
                except m.MemoryValidationError as exc:
                    assert str(exc) == reason
                    witness = exc.rejection_receipt.to_json()
                    assert witness["stage"] == "protocol"
                    assert witness["candidate_query_started"] is False
                else:
                    raise AssertionError("bad protocol accepted")

        if mode in ("no_mutation", "before"):
            await manager.ingest_committed_evidence(old.envelope, old.receipt)
        if mode == "no_mutation":
            plan = replace(
                f._plan(old.envelope, f._operation(oldspan)),
                outcome=h.MemoryMutationPlanOutcome.NO_MUTATION,
                operations=(),
            )
            no_mutation = await manager.apply_memory_mutation_plan(
                principal=PRINCIPAL,
                scope=m.MemoryScope.personal("actor-1"),
                plan=plan,
            )
            assert no_mutation.reason_code is h.MemoryMutationApplyReasonCode.NO_MUTATION
            receipt = await manager.backend.resolve_memory_mutation_apply_receipt(
                no_mutation.receipt_ref,
            )
            receipt.validate_plan(plan)
            assert receipt.committed_revision == 1
            context = f._context()
            empty = await manager.execute_typed_recall(
                principal=PRINCIPAL,
                context=context,
                plan=f._recall_plan(context, idempotency_key="no-mutation-check"),
            )
            assert empty.result.items == ()
        await manager.ingest_committed_evidence(seed.envelope, seed.receipt)
        applied = await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL,
            scope=m.MemoryScope.personal("actor-1"),
            plan=f._plan(
                seed.envelope, f._operation(span), plan_id="create-seed", idempotency_key="seed"
            ),
        )
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL,
            receipt_ref=applied.receipt_ref,
        )
        assert len(view.operations) == 1 and view.operations[0].evidence_ids == ("seed",)
        mid = view.operations[0].memory_id
        request = m.SuppressionRequest(
            "forget", "actor-1", m.SuppressionScopeKind.MEMORY, mid, "user_forget", NOW
        )
        # Controlled Host action S1 is an input, not a derived Memory expected result.
        action, _ = source("actual-fixture-action", "forget source through sequence2")
        if mode != "legacy":
            origins.cuts["forget"] = m.HistoryForgetCutReceipt(
                NS,
                2,
                "forget",
                m.SuppressionScopeKind.MEMORY,
                mid,
                action.envelope.evidence_id,
                action.envelope.envelope_hash,
            )
        decision = await manager.suppress(principal=PRINCIPAL, request=request)
        cut_hash = origins.cuts["forget"].cut_hash if mode != "legacy" else None
        if mode == "after":
            await manager.ingest_committed_evidence(old.envelope, old.receipt)
        snapshot = await check(
            manager,
            (old, answer, unrelated, fresh, late, seed),
            [False, False, True, mode != "legacy", False, False],
        )
        assert snapshot.items[4].reason == "history_source_cut_unverifiable"
        if mode == "legacy":
            assert snapshot.items[3].reason == "history_source_cut_unverifiable"
        await manager.ingest_committed_evidence(fresh.envelope, fresh.receipt)
        assert await manager.suppress(principal=PRINCIPAL, request=request) == decision
        if cut_hash:
            assert origins.cuts["forget"].cut_hash == cut_hash
        await check(manager, (old, fresh), [False, mode != "legacy"])
    finally:
        await manager.close()
    manager = await m.build_human_memory_v7(path, **kwargs)
    try:
        reopened = await check(
            manager,
            (old, answer, unrelated, fresh, late, seed),
            [False, False, True, mode != "legacy", False, False],
        )
        assert reopened.policy_hash == snapshot.policy_hash
        assert await manager.suppress(principal=PRINCIPAL, request=request) == decision
    finally:
        await manager.close()
    return dict(
        stage=mode,
        decision_hash=decision.decision_hash,
        cut_hash=cut_hash,
        snapshot_hash=reopened.snapshot_hash,
    )


def registered(sequence, *, shared=False):
    """Rebind the existing synthetic SDK group fixture through every public DTO."""
    old = f._short_registration(sequence)
    text = (
        "Project alpha shared original" if sequence <= 2 or shared else f"Project alpha {sequence}"
    )
    payload = {
        "item_id": "message-1",
        "public_text": text,
        "text": text,
        "delivery_key": f"delivery-{sequence}",
    }
    digest = fingerprint_json(payload)
    envelope = replace(
        old.envelope, sanitized_payload=payload, source_hash=digest, sanitized_hash=digest
    )
    receipt = replace(
        old.admission_receipt,
        envelope_hash=envelope.envelope_hash,
        source_hash=digest,
        sanitized_hash=digest,
    )
    item = replace(
        old.recall_item_authority,
        envelope_hash=envelope.envelope_hash,
        source_hash=digest,
        sanitized_hash=digest,
    )
    metadata = replace(
        old.metadata,
        envelope_hash=envelope.envelope_hash,
        source_hash=digest,
        sanitized_hash=digest,
        admission_receipt_hash=receipt.receipt_hash,
        public_text_json_pointer=None,
        public_text_hash=None,
        public_text_normalization_version=None,
        evidence_item_authority_id=None,
        evidence_item_authority_hash=None,
        effective_privacy_class=None,
        information_attributes=None,
        classification_authority_ref=None,
    )
    metadata = h.authorize_conversation_public_text(
        metadata,
        h.AdmittedEvidenceAuthority(envelope, receipt, item),
    )
    mr = replace(
        old.metadata_receipt,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_hash=receipt.receipt_hash,
        source_hash=digest,
        sanitized_hash=digest,
        metadata_hash=metadata.metadata_hash,
    )
    registration = replace(
        old,
        envelope=envelope,
        admission_receipt=receipt,
        recall_item_authority=item,
        metadata=metadata,
        metadata_receipt=mr,
    )
    return registration, h.ConversationEvidenceRegistrationRef(
        registration.registration_id,
        registration.registration_hash,
        envelope.evidence_id,
        envelope.envelope_hash,
    )


async def short_case(tmp_path):
    pairs = [registered(i) for i in range(1, 13)]
    seed = pairs[1][0]
    span = f._span(seed.envelope, seed.admission_receipt)
    mutation = f.HostEvidenceAuthority(seed.envelope, seed.admission_receipt, span)
    origins = Origins()
    for index, (registration, _) in enumerate(pairs, 1):
        origins.register(
            m.HistoryEvidenceBinding(
                registration.envelope,
                registration.admission_receipt,
            ),
            index,
        )
    conversation_authority = f.HostConversationAuthority(tuple(p[0] for p in pairs))
    manager = await m.build_human_memory_v7(
        tmp_path / "short.db",
        clock=lambda: NOW,
        classification_policy=f._classification_policy(),
        evidence_authority=mutation,
        conversation_evidence_authority=conversation_authority,
        history_source_authority=origins,
    )

    try:
        await manager.register_principal_owner(PRINCIPAL, m.MemoryScope.personal("actor-1"))
        for registration, ref in pairs:
            await manager.ingest_committed_evidence(
                registration.envelope,
                registration.admission_receipt,
            )
            await manager.register_conversation_evidence(ref)
        built = await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        assert built.projected_chunk_count == 2
        before = await manager.recall_short_horizon(
            principal=PRINCIPAL,
            query="Project alpha",
            disclosure_context=f._disclosure(),
        )
        assert len(before.hits) == 2
        bindings = tuple(
            m.HistoryShortHorizonBinding(before.audit_id, x.chunk_ref, x.content_hash)
            for x in before.hits
        )
        sources_before = await manager.resolve_short_horizon_sources(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=bindings,
        )
        assert all(item.visible and item.complete for item in sources_before.items)
        assert {
            tuple(ref.evidence_id for ref in item.source_refs) for item in sources_before.items
        } == {("short-source-1",), ("short-source-2",)}
        context = f._context(
            query="Project alpha",
            short_horizon=True,
            expires_at=NOW + 100,
            selectors=(h.RecallSelectorDomain.MEMORY_TYPE, h.RecallSelectorDomain.SHORT_HORIZON),
        )
        typed_before = await manager.execute_typed_recall(
            principal=PRINCIPAL,
            context=context,
            plan=f._recall_plan(
                context,
                idempotency_key="short-before",
                requested_memory_types=(),
                selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,),
            ),
            now=NOW,
        )
        assert typed_before.result.items
        assert all(
            x.selected_item.source_kind.value == "short_horizon" for x in typed_before.result.items
        )

        def use_request(execution, ctx, attempt):
            item = execution.result.items[0]
            fragment = h.ContextFragmentBindingV2("short-fragment", "f" * 64)
            return h.RecallContextUseAuthorizationRequestV1(
                "actor-1",
                ctx.run_id,
                ctx.turn_id,
                attempt,
                execution.decision.decision_id,
                execution.decision.decision_hash,
                execution.result.result_id,
                execution.result.result_hash,
                (h.RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
                (fragment,),
                fingerprint_json([fragment.to_json()]),
                NOW,
            )

        old_use_request = use_request(typed_before, context, "short-use-before")
        old_use_receipt = await manager.authorize_recall_context_use(
            principal=PRINCIPAL,
            request=old_use_request,
        )
        result = await manager.apply_memory_mutation_plan(
            principal=PRINCIPAL,
            scope=m.MemoryScope.personal("actor-1"),
            plan=f._plan(seed.envelope, f._operation(span)),
        )
        assert result.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        view = await manager.get_memory_mutation_receipt_view(
            principal=PRINCIPAL,
            receipt_ref=result.receipt_ref,
        )
        mid = view.operations[0].memory_id

        origins.cuts["short-forget"] = m.HistoryForgetCutReceipt(
            NS,
            2,
            "short-forget",
            m.SuppressionScopeKind.MEMORY,
            mid,
            "action-s1",
            "d" * 64,
        )
        await manager.suppress(
            principal=PRINCIPAL,
            request=m.SuppressionRequest(
                "short-forget",
                "actor-1",
                m.SuppressionScopeKind.MEMORY,
                mid,
                "user_forget",
                NOW,
            ),
        )
        current = await manager.check_history_visibility(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=bindings,
        )
        assert all(not item.visible for item in current.items)
        resolved = await manager.resolve_short_horizon_sources(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=bindings,
        )
        assert all(not item.visible for item in resolved.items)
        typed_bindings = tuple(
            m.HistoryRecallBinding(
                typed_before.result.result_id,
                typed_before.result.result_hash,
                item.selected_item.item_id,
                item.result_item_hash,
            )
            for item in typed_before.result.items
        )
        typed_current = await manager.check_history_visibility(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=typed_bindings,
        )
        assert all(not item.visible for item in typed_current.items)
        with rejects(m.MemoryValidationError, "RECALL_AUTHORITY_STALE"):
            await manager.authorize_recall_context_use(
                principal=PRINCIPAL,
                request=replace(old_use_request, provider_attempt_id="short-use-after"),
            )
        # Exact receipt replay is historical acknowledgement, not current-use authorization.
        assert old_use_receipt == await manager.authorize_recall_context_use(
            principal=PRINCIPAL,
            request=old_use_request,
        )
        after = await manager.recall_short_horizon(
            principal=PRINCIPAL,
            query="Project alpha",
            disclosure_context=f._disclosure(),
        )
        assert after.hits == ()
        typed = await manager.execute_typed_recall(
            principal=PRINCIPAL,
            context=context,
            plan=f._recall_plan(
                context,
                idempotency_key="short-duplicate",
                requested_memory_types=(),
                selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,),
            ),
            now=NOW,
        )
        assert not typed.result.items

        # New independent atomic source13 has the same complete /text. Ten later
        # complete groups move it outside the existing recent10 exclusion window.
        new_pairs = [registered(i, shared=(i == 13)) for i in range(13, 24)]
        for index, (registration, ref) in enumerate(new_pairs, 13):
            conversation_authority.records[registration.registration_id] = registration
            origins.register(
                m.HistoryEvidenceBinding(
                    registration.envelope,
                    registration.admission_receipt,
                ),
                index,
            )
            await manager.ingest_committed_evidence(
                registration.envelope,
                registration.admission_receipt,
            )
            await manager.register_conversation_evidence(ref)
        await manager.rebuild_short_horizon_projection(principal=PRINCIPAL)
        fresh = await manager.recall_short_horizon(
            principal=PRINCIPAL,
            query="shared original",
            disclosure_context=f._disclosure(),
        )
        assert fresh.hits
        fresh_bindings = tuple(
            m.HistoryShortHorizonBinding(
                fresh.audit_id,
                item.chunk_ref,
                item.content_hash,
            )
            for item in fresh.hits
        )
        fresh_sources = await manager.resolve_short_horizon_sources(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=fresh_bindings,
        )
        assert any(
            item.visible and {r.evidence_id for r in item.source_refs} == {"short-source-13"}
            for item in fresh_sources.items
        )
        assert all(
            r.evidence_id not in {"short-source-1", "short-source-2"}
            for item in fresh_sources.items
            for r in item.source_refs
        )
        fresh_context = replace(context, query="shared original")
        fresh_typed = await manager.execute_typed_recall(
            principal=PRINCIPAL,
            context=fresh_context,
            plan=f._recall_plan(
                fresh_context,
                idempotency_key="short-fresh",
                requested_memory_types=(),
                selector_domains=(h.RecallSelectorDomain.SHORT_HORIZON,),
            ),
            now=NOW,
        )
        assert any(
            item.selected_item.source_ref in {x.chunk_ref for x in fresh.hits}
            for item in fresh_typed.result.items
        )
        await manager.authorize_recall_context_use(
            principal=PRINCIPAL,
            request=use_request(fresh_typed, fresh_context, "short-fresh-use"),
        )
        old_current = await manager.check_history_visibility(
            principal=PRINCIPAL,
            disclosure_context=f._disclosure(),
            bindings=bindings,
        )
        assert all(not item.visible for item in old_current.items)
    finally:
        await manager.close()

    # Reopen preserves old source refusal; no exact replay becomes a fresh grant.
    manager = await m.build_human_memory_v7(
        tmp_path / "short.db",
        clock=lambda: NOW,
        classification_policy=f._classification_policy(),
        evidence_authority=mutation,
        conversation_evidence_authority=conversation_authority,
        history_source_authority=origins,
    )
    try:
        await check(manager, bindings, [False] * len(bindings))
        await check(manager, fresh_bindings, [True] * len(fresh_bindings))
    finally:
        await manager.close()
    return {"stage": "short-selected-distinct/forget/typed-final-use/fresh13/reopen"}


async def run(args):
    assert "PYTHONPATH" not in os.environ and "PYTHONHOME" not in os.environ
    assert m.__version__ == "0.6.10" and h.__version__ == "0.7.2"
    if not args.source_smoke:
        assert sys.flags.isolated
        for module in (m, h):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
        assert importlib.metadata.version("simple-harness-memory-sdk") == "0.6.10"
    args.output.mkdir(parents=True, exist_ok=False)
    observations = []
    for mode in ("cold", "before", "after", "no_mutation", "legacy"):
        observations.append(await main_case(args.output / mode, mode))
    observations.append(await short_case(args.output))
    result = dict(
        status="PASS",
        version=m.__version__,
        installed=not args.source_smoke,
        stages=observations,
        memory_origin=m.__file__,
        harness_origin=h.__file__,
    )
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-smoke", action="store_true")
    asyncio.run(run(parser.parse_args()))
