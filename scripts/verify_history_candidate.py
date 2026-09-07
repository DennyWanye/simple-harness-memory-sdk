#!/usr/bin/env python3
"""Exact installed0.6.7 public consumer; synthetic Host admissions, real SQLite.

Input constructors retain the established SDK fixture contract. Expected outcomes
are explicit below, independent of product outputs. No source/test imports, SQL,
private backend, provider, UI, or filesystem source-path injection at runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import simple_harness as h

import simple_harness_memory as m


def fingerprint_json(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disclosure(subject="actor-1"):
    return h.DisclosureContext(
        run_id="run-1",
        subject=subject,
        recipient=h.DeliveryRecipient.USER_SELF,
        recipient_id=subject,
        intended_audience=h.IntendedAudience.USER_SELF,
        purpose=h.DisclosurePurpose.PERSONALIZATION,
        source=h.DisclosureSource.AUTHENTICATED_HOST,
        trust=h.DisclosureTrust.TRUSTED_AUTHORITY,
        generation=h.DisclosureGeneration.CURRENT,
        authority_ref="host-disclosure-1",
        reason_codes=(h.DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _admitted(
    *, source_kind=h.EvidenceSourceKind.USER_MESSAGE, subject="actor-1", evidence_id="evidence-1"
):
    payload = {"item_id": "message-1", "public_text": "user prefers concise answers"}
    envelope = h.SanitizedEvidenceEnvelope(
        evidence_id=evidence_id,
        run_id="run-1",
        subject=subject,
        source_kind=source_kind,
        source_ref=("turn-1/user" if evidence_id == "evidence-1" else f"turn-{evidence_id}/user")
        if source_kind is h.EvidenceSourceKind.USER_MESSAGE
        else "provider-1/record-1",
        source_hash=_sha(payload["public_text"]),
        sanitized_payload=payload,
        sanitized_hash=fingerprint_json(payload),
        filter_policy_version="credential-filter/v1",
        removed_spans=(),
        disclosure_context=_disclosure(subject),
        evidence_refs=(),
    )
    receipt = h.SanitizedEvidenceReceipt(
        receipt_id="admission-1" if evidence_id == "evidence-1" else f"admission-{evidence_id}",
        run_id=envelope.run_id,
        subject=envelope.subject,
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        filter_policy_version=envelope.filter_policy_version,
        accepted=True,
        reason_codes=(h.EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        disclosure_context=envelope.disclosure_context,
        evidence_refs=envelope.evidence_refs,
        admitted_at=10.0,
    )
    return (envelope, receipt)


def _span(
    envelope,
    receipt,
    *,
    actor_role=h.EvidenceActorRole.USER,
    provenance=h.EvidenceProvenance.AUTHENTICATED_USER,
    support_kind=h.EvidenceSupportKind.EXPLICIT_USER_ASSERTION,
    typed_observation=None,
):
    text = cast(str, envelope.sanitized_payload["public_text"])
    return h.EvidenceSpanRef(
        span_id="span-1",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        source_kind=envelope.source_kind,
        item_ordinal=1,
        item_id="message-1",
        item_json_pointer="/public_text",
        start_byte=0,
        end_byte=len(text.encode("utf-8")),
        exact_quote=text,
        quote_hash=_sha(text),
        source_hash=envelope.source_hash,
        normalization_version="sanitized-string-identity-utf8/v1",
        actor_role=actor_role,
        provenance=provenance,
        support_kind=support_kind,
        typed_observation=typed_observation,
    )


def _item_authority(span):
    return h.EvidenceItemAuthority(
        schema_version=h.EVIDENCE_ITEM_AUTHORITY_SCHEMA_VERSION,
        authority_id="item-authority-1",
        evidence_id=span.evidence_id,
        envelope_hash=span.envelope_hash,
        sanitized_hash=span.sanitized_hash,
        source_hash=span.source_hash,
        source_kind=span.source_kind,
        item_ordinal=span.item_ordinal,
        item_id=span.item_id,
        item_json_pointer=span.item_json_pointer,
        normalization_version=span.normalization_version,
        actor_role=span.actor_role,
        provenance=span.provenance,
        required_privacy_class=h.PrivacyClass.PERSONAL,
        required_information_attributes=(),
        classification_authority_ref="host-classification-1",
        issuer_ref="host-evidence-1",
    )


def _classification_policy():
    return m.InformationClassificationPolicy(
        policy_id="memory-classification-policy",
        policy_version="1",
        authority_ref="memory-policy-registry:classification/v1",
        required_privacy_class=h.PrivacyClass.PERSONAL,
        required_information_attributes=(),
    )


def _operation(
    span,
    *,
    operation_id="create-1",
    kind=h.MemoryMutationKind.CREATE,
    target=None,
    depends_on=(),
    privacy=h.PrivacyClass.PUBLIC,
    attributes=(h.InformationAttribute.PREFERENCE,),
    epistemic_status=h.EpistemicStatus.EXPLICIT_USER,
    conflict_status=h.ConflictStatus.UNCONTESTED,
    verification_state=h.VerificationState.SOURCE_BOUND,
):
    return h.MemoryMutationOperation(
        operation_id=operation_id,
        kind=kind,
        memory_type=h.LongTermMemoryType.SEMANTIC,
        payload=h.SemanticMemoryPayload("user:self", "response_style", "concise", ("default",)),
        target=target,
        depends_on_operation_ids=depends_on,
        lifecycle_state=h.SemanticLifecycleState.ACTIVE,
        epistemic_status=epistemic_status,
        conflict_status=conflict_status,
        verification_state=verification_state,
        valid_time_interval=h.ValidTimeInterval(None, None),
        proposed_privacy_class=privacy,
        proposed_information_attributes=attributes,
        evidence_spans=(span,),
        reason_code="explicit_user_assertion",
    )


def _plan(
    envelope, *operations, base_revision=1, plan_id="plan-1", idempotency_key="idempotency-1"
):
    return h.MemoryMutationPlan(
        plan_id=plan_id,
        run_id="run-1",
        turn_id="turn-1",
        subject=envelope.subject,
        base_revision=base_revision,
        outcome=h.MemoryMutationPlanOutcome.MUTATE,
        operations=tuple(operations),
        disclosure_context=_disclosure(envelope.subject),
        evidence_refs=(h.EvidenceRef(envelope.evidence_id, envelope.envelope_hash, 1),),
        idempotency_key=idempotency_key,
    )


def _principal(actor_id="actor-1"):
    return m.MemoryPrincipal("deployment-1", "household-1", actor_id, "session-1")


def _context(
    *,
    query="concise",
    selectors=(h.RecallSelectorDomain.MEMORY_TYPE,),
    modes=(h.RecallRetrievalMode.FULL_TEXT,),
    event_refs=(),
    memory_types=(h.LongTermMemoryType.SEMANTIC,),
    short_horizon=False,
    expires_at=100.0,
    entity_constraints=(),
    earliest_occurred_at=None,
    latest_occurred_at=None,
    budget=None,
    disclosure=None,
    procedure_applicability_fingerprints=(),
):
    return h.RecallContext(
        "run-recall",
        "actor-1",
        "turn-recall",
        1,
        expires_at,
        query,
        None,
        memory_types,
        short_horizon,
        selectors,
        modes,
        (),
        entity_constraints,
        earliest_occurred_at,
        latest_occurred_at,
        event_refs,
        (),
        (),
        procedure_applicability_fingerprints,
        replace(_disclosure(), run_id="run-recall") if disclosure is None else disclosure,
        (h.EvidenceRef("evidence-recall", "e" * 64, 1),),
        h.RecallBudget(8, 16384, 2048, 1000) if budget is None else budget,
    )


def _recall_plan(context, *, idempotency_key, requested_memory_types=None, selector_domains=None):
    return h.RecallPlan(
        "plan-recall",
        context.run_id,
        context.subject,
        context.context_hash,
        context.context_revision,
        context.query,
        context.available_memory_types
        if requested_memory_types is None
        else requested_memory_types,
        context.short_horizon_allowed,
        context.allowed_selector_domains if selector_domains is None else selector_domains,
        context.allowed_retrieval_modes,
        (),
        context.allowed_entity_constraints,
        context.earliest_occurred_at,
        context.latest_occurred_at,
        context.event_constraint_refs,
        (),
        (),
        context.disclosure_context,
        context.evidence_refs,
        context.budget,
        idempotency_key,
        (h.RecallReasonCode.USER_FACT_DEPENDENCY,),
    )


class HostEvidenceAuthority:
    def __init__(self, envelope, receipt, span):
        self.span = span
        self.admitted = h.AdmittedEvidenceAuthority(envelope, receipt, _item_authority(span))

    async def resolve_admitted_evidence(self, span):
        if span != self.span:
            raise ValueError("unknown Host evidence binding")
        return self.admitted

    async def resolve_typed_observation(self, reference):
        raise ValueError("no typed observation in this fixture")


async def run(output):
    assert m.__version__ == importlib.metadata.version("simple-harness-memory-sdk") == "0.6.7"
    assert h.__version__ == importlib.metadata.version("simple-harness-sdk") == "0.7.2"
    assert not (output / "state.db").exists(), "use a new evidence directory"
    prefix = Path(sys.prefix).resolve()
    # -I prevents cwd/PYTHONPATH injection. Installed imports must stay inside this venv.
    for module in (h, m):
        assert Path(cast(str, module.__file__)).resolve().is_relative_to(prefix)
    now = [20.0]
    envelope, receipt = _admitted()
    unrelated, unrelated_receipt = _admitted(evidence_id="unrelated-user")
    text = "The sky looks clear today"
    payload = {"item_id": "message-1", "public_text": text}
    unrelated = replace(
        unrelated,
        sanitized_payload=payload,
        sanitized_hash=fingerprint_json(payload),
        source_hash=_sha(text),
    )
    unrelated_receipt = replace(
        unrelated_receipt,
        envelope_hash=unrelated.envelope_hash,
        sanitized_hash=unrelated.sanitized_hash,
        source_hash=unrelated.source_hash,
    )
    span = _span(envelope, receipt)
    authority = HostEvidenceAuthority(envelope, receipt, span)
    principal = _principal()
    disclosure = replace(
        _disclosure(), run_id="actual-host-history-request", purpose=h.DisclosurePurpose.USER_REVIEW
    )
    bindings = (
        m.HistoryEvidenceBinding(envelope, receipt),
        m.HistoryEvidenceBinding(unrelated, unrelated_receipt),
    )
    kwargs = dict(
        clock=lambda: now[0],
        classification_policy=_classification_policy(),
        evidence_authority=authority,
    )
    manager = await m.build_human_memory_v7(output / "state.db", **kwargs)
    observations = []

    async def check(expected, stage):
        snapshot = await manager.check_history_visibility(
            principal=principal, disclosure_context=disclosure, bindings=bindings
        )
        values = [item.visible for item in snapshot.items]
        assert values == expected, (stage, values)
        assert snapshot.checked_at == now[0]
        observations.append(
            {
                "stage": stage,
                "visible": values,
                "epoch": snapshot.authority_epoch,
                "snapshot_hash": snapshot.snapshot_hash,
            }
        )
        return snapshot

    try:
        await check([True, True], "cold_user")
        await manager.ingest_committed_evidence(envelope, receipt)
        await check([True, True], "ingested_without_analysis")
        applied = await manager.apply_memory_mutation_plan(
            principal=principal,
            scope=m.MemoryScope.personal(principal.actor_id),
            plan=_plan(envelope, _operation(span)),
        )
        assert applied.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        view = await manager.get_memory_mutation_receipt_view(
            principal=principal, receipt_ref=applied.receipt_ref
        )
        memory_id = view.operations[0].memory_id
        assert memory_id
        context = _context()
        plan = _recall_plan(context, idempotency_key="combined-candidate-recall")
        execution = await manager.execute_typed_recall(
            principal=principal, context=context, plan=plan
        )
        assert execution.result.evaluated_at == 20.0
        assert len(execution.result.items) == 1
        item = execution.result.items[0]
        assert item.public_payload["object_value"] == "concise"
        assert (
            await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        ).replayed
        recall_binding = m.HistoryRecallBinding(
            execution.result.result_id,
            execution.result.result_hash,
            item.selected_item.item_id,
            item.result_item_hash,
        )
        assert (
            (
                await manager.check_history_visibility(
                    principal=principal, disclosure_context=disclosure, bindings=(recall_binding,)
                )
            )
            .items[0]
            .visible
        )
        witnesses = []
        for protocol, reason in (
            (5, "typed_recall_protocol_unsupported"),
            ("5", "typed_recall_protocol_invalid"),
        ):
            try:
                await manager.execute_typed_recall(
                    principal=principal,
                    context=context,
                    plan=plan,
                    harness_protocol=cast(int, protocol),
                )
            except m.MemoryValidationError as error:
                assert str(error) == reason
                witness = getattr(error, "rejection_receipt", None)
                assert type(witness) is m.TypedRecallRejectionV1
                value = witness.to_json()
                assert value["stage"] == "protocol" and value["reason"] == reason
                assert value["context_hash"] == context.context_hash
                assert value["plan_hash"] == plan.plan_hash
                assert value["candidate_query_started"] is False
                assert value["candidate_query_count"] == 0
                witnesses.append(value)
            else:
                raise AssertionError("unsupported protocol was accepted")
        assert witnesses[0]["invocation_id"] != witnesses[1]["invocation_id"]
        observations.append({"stage": "protocol_rejections", "receipts": witnesses})
        before = await check([True, True], "materialized")
        # Only this MEMORY directive is issued: no evidence/entity/subject patch.
        directive = await manager.suppress(
            principal=principal,
            request=m.SuppressionRequest(
                "forget-one",
                "actor-1",
                m.SuppressionScopeKind.MEMORY,
                memory_id,
                "user_forget",
                now[0],
            ),
        )
        assert directive.scope_kind is m.SuppressionScopeKind.MEMORY
        after = await check([False, True], "memory_only_forget")
        assert after.authority_epoch > before.authority_epoch
        assert (
            not (
                await manager.check_history_visibility(
                    principal=principal, disclosure_context=disclosure, bindings=(recall_binding,)
                )
            )
            .items[0]
            .visible
        )
    finally:
        await manager.close()
    now[0] = 101.0
    manager = await m.build_human_memory_v7(output / "state.db", **kwargs)
    try:
        await check([False, True], "reopened")
        page = h.RecallResultPageRequestV1(
            execution.result.result_id, execution.result.result_hash, 1, 0, 1, 16384, 20.0
        )
        try:
            await manager.page_typed_recall_result(principal=principal, request=page)
        except m.MemoryValidationError as error:
            assert str(error) == "typed_recall_result_expired"
            observations.append({"stage": "clock_expired_page", "reason": str(error)})
        else:
            raise AssertionError("expired page accepted by backdated request")
    finally:
        await manager.close()
    observations.extend(await run_short(output))
    identity = {
        name: str(Path(cast(str, module.__file__)).resolve())
        for name, module in sys.modules.items()
        if name.startswith(("simple_harness.", "simple_harness_memory."))
        and getattr(module, "__file__", None)
    }
    assert all(Path(path).is_relative_to(prefix) for path in identity.values())
    result = {
        "status": "PASS",
        "memory_version": m.__version__,
        "harness_version": h.__version__,
        "observations": observations,
        "module_paths": identity,
    }
    (output / "public-smoke.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": "PASS",
                "stages": [x["stage"] for x in observations],
                "installed_modules": len(identity),
            }
        )
    )


def _short_registration(sequence):
    envelope, receipt = _admitted(evidence_id=f"short-source-{sequence}")
    text = (
        "Project alpha: user prefers concise answers"
        if sequence == 1
        else f"Project beta note {sequence}"
    )
    payload = {"item_id": "message-1", "public_text": text}
    envelope = replace(
        envelope,
        sanitized_payload=payload,
        sanitized_hash=fingerprint_json(payload),
        source_hash=_sha(text),
    )
    receipt = replace(
        receipt,
        envelope_hash=envelope.envelope_hash,
        sanitized_hash=envelope.sanitized_hash,
        source_hash=envelope.source_hash,
    )
    authority = _item_authority(_span(envelope, receipt))
    metadata = h.ConversationEvidenceMetadata(
        metadata_id=f"short-metadata-{sequence}",
        authority_issuer_id="host-conversation-registry",
        evidence_id=envelope.evidence_id,
        envelope_hash=envelope.envelope_hash,
        admission_receipt_id=receipt.receipt_id,
        admission_receipt_hash=receipt.receipt_hash,
        run_id=envelope.run_id,
        subject=envelope.subject,
        source_hash=envelope.source_hash,
        sanitized_hash=envelope.sanitized_hash,
        conversation_id="primary",
        primary_conversation_id="primary",
        causal_group_id=f"group-{sequence}",
        causal_group_sequence=sequence,
        item_ordinal=1,
        group_item_count=1,
        ordered_group_manifest_hash=fingerprint_json({"group": sequence, "items": ["message-1"]}),
        role=h.ConversationEvidenceRole.USER,
        occurred_at=10.0 + sequence / 10,
        task_scope_id="task-1",
        tool_causal_link=None,
        entities=("project-alpha" if sequence == 1 else "project-beta",),
    )
    metadata = h.authorize_conversation_public_text(
        metadata, h.AdmittedEvidenceAuthority(envelope, receipt, authority)
    )
    metadata_receipt = h.ConversationEvidenceMetadataReceipt(
        receipt_id=f"short-metadata-receipt-{sequence}",
        metadata_id=metadata.metadata_id,
        authority_issuer_id=metadata.authority_issuer_id,
        evidence_id=metadata.evidence_id,
        envelope_hash=metadata.envelope_hash,
        admission_receipt_id=metadata.admission_receipt_id,
        admission_receipt_hash=metadata.admission_receipt_hash,
        run_id=metadata.run_id,
        subject=metadata.subject,
        source_hash=metadata.source_hash,
        sanitized_hash=metadata.sanitized_hash,
        metadata_hash=metadata.metadata_hash,
        issuer_ref=metadata.authority_issuer_id,
        accepted=True,
    )
    registration = h.ConversationEvidenceRegistration(
        f"short-registration-{sequence}", envelope, receipt, metadata, metadata_receipt, authority
    )
    return registration


class HostConversationAuthority:
    def __init__(self, registrations):
        self.records = {x.registration_id: x for x in registrations}

    async def resolve_conversation_registration(self, reference):
        registration = self.records[reference.registration_id]
        if reference != h.ConversationEvidenceRegistrationRef(
            registration.registration_id,
            registration.registration_hash,
            registration.envelope.evidence_id,
            registration.envelope.envelope_hash,
        ):
            raise ValueError("unknown Host conversation binding")
        return registration


async def run_short(output):
    assert not (output / "short.db").exists(), "use a new evidence directory"
    registrations = tuple(_short_registration(i) for i in range(1, 13))
    first, second = registrations[:2]
    span = _span(first.envelope, first.admission_receipt)
    now = [20.0]
    principal = _principal()
    context = replace(
        _disclosure(),
        run_id="actual-short-history-request",
        purpose=h.DisclosurePurpose.USER_REVIEW,
    )
    kwargs = dict(
        clock=lambda: now[0],
        classification_policy=_classification_policy(),
        conversation_evidence_authority=HostConversationAuthority(registrations),
        evidence_authority=HostEvidenceAuthority(first.envelope, first.admission_receipt, span),
    )
    manager = await m.build_human_memory_v7(output / "short.db", **kwargs)
    observations = []
    bindings: tuple[m.HistoryBinding, ...] = ()

    async def check(expected, stage, checked_bindings=None, disclosure=None, owner=None):
        snapshot = await manager.check_history_visibility(
            principal=owner or principal,
            disclosure_context=disclosure or context,
            bindings=bindings if checked_bindings is None else checked_bindings,
        )
        assert [x.visible for x in snapshot.items] == expected, (stage, snapshot.to_json())
        assert snapshot.checked_at == now[0]
        observations.append(dict(stage=stage, snapshot=snapshot.to_json()))
        return snapshot

    async def forget(kind, target, key):
        return await manager.suppress(
            principal=principal,
            request=m.SuppressionRequest(
                key,
                principal.actor_id,
                kind,
                target,
                "user_forget",
                now[0],
            ),
        )

    try:
        await manager.register_principal_owner(
            principal, m.MemoryScope.personal(principal.actor_id)
        )
        for registration in registrations:
            await manager.ingest_committed_evidence(
                registration.envelope, registration.admission_receipt
            )
            await manager.register_conversation_evidence(
                h.ConversationEvidenceRegistrationRef(
                    registration.registration_id,
                    registration.registration_hash,
                    registration.envelope.evidence_id,
                    registration.envelope.envelope_hash,
                )
            )
        built = await manager.rebuild_short_horizon_projection(principal=principal)
        assert built.projected_chunk_count == 2
        result = await manager.recall_short_horizon(
            principal=principal, query="Project", disclosure_context=context
        )
        assert len(result.hits) == result.eligible_count == result.fts_count == 2
        hits = {hit.content: hit for hit in result.hits}
        first_hit = hits["user: Project alpha: user prefers concise answers"]
        second_hit = hits["user: Project beta note 2"]
        for hit in (first_hit, second_hit):
            assert _sha(hit.content) == hit.content_hash
        short_bindings = tuple(
            m.HistoryShortHorizonBinding(result.audit_id, hit.chunk_ref, hit.content_hash)
            for hit in (first_hit, second_hit)
        )
        evidence_bindings = tuple(
            m.HistoryEvidenceBinding(reg.envelope, reg.admission_receipt) for reg in (first, second)
        )
        bindings = short_bindings + evidence_bindings
        initial = await check([True, True, True, True], "short_exact_selection")
        forged = (
            replace(short_bindings[0], audit_id="short-audit:unknown"),
            replace(short_bindings[0], chunk_ref=second_hit.chunk_ref),
            replace(short_bindings[0], content_hash="0" * 64),
        )
        await check([False, False, False], "short_forged_triples", forged)
        limited = await manager.recall_short_horizon(
            principal=principal, query="Project", disclosure_context=context, limit=1
        )
        assert limited.eligible_count == 2 and len(limited.hits) == 1
        unselected = next(x for x in result.hits if x.chunk_ref != limited.hits[0].chunk_ref)
        await check(
            [False],
            "short_unselected",
            (
                m.HistoryShortHorizonBinding(
                    limited.audit_id, unselected.chunk_ref, unselected.content_hash
                ),
            ),
        )
        await check(
            [False, False],
            "short_wrong_subject",
            short_bindings,
            disclosure=replace(context, subject="other", recipient_id="other"),
            owner=_principal("other"),
        )
        await check(
            [False, False],
            "short_current_disclosure",
            short_bindings,
            disclosure=replace(
                context,
                recipient=h.DeliveryRecipient.HOUSEHOLD,
                intended_audience=h.IntendedAudience.HOUSEHOLD,
                recipient_id="household-1",
                purpose=h.DisclosurePurpose.TASK_EXECUTION,
            ),
        )
        assert initial.valid_until == 10.1 + 5 * 86400
        now[0] = initial.valid_until
        await check([False, True], "short_expiry_boundary", short_bindings)
        now[0] = 20.0
        applied = await manager.apply_memory_mutation_plan(
            principal=principal,
            scope=m.MemoryScope.personal(principal.actor_id),
            plan=_plan(first.envelope, _operation(span)),
        )
        assert applied.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        view = await manager.get_memory_mutation_receipt_view(
            principal=principal, receipt_ref=applied.receipt_ref
        )
        recall_context = _context()
        typed = await manager.execute_typed_recall(
            principal=principal,
            context=recall_context,
            plan=_recall_plan(recall_context, idempotency_key="short-consumer-typed"),
        )
        assert len(typed.result.items) == 1
        item = typed.result.items[0]
        assert item.public_payload["object_value"] == "concise"
        bindings += (
            m.HistoryRecallBinding(
                typed.result.result_id,
                typed.result.result_hash,
                item.selected_item.item_id,
                item.result_item_hash,
            ),
        )
        await check([True, True, True, True, True], "short_typed_evidence_compatible")
        await forget(
            m.SuppressionScopeKind.MEMORY, view.operations[0].memory_id, "short-forget-memory"
        )
        await check([False, True, False, True, False], "short_memory_only_suppression")
    finally:
        await manager.close()
    manager = await m.build_human_memory_v7(output / "short.db", **kwargs)
    try:
        await check([False, True, False, True, False], "short_memory_only_reopen")
        await forget(
            m.SuppressionScopeKind.EVIDENCE, second.envelope.evidence_id, "short-forget-source"
        )
        await check([False, False, False, False, False], "short_source_suppression")
    finally:
        await manager.close()
    manager = await m.build_human_memory_v7(output / "short.db", **kwargs)
    try:
        await check([False, False, False, False, False], "short_source_reopen")
    finally:
        await manager.close()
    return observations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.output.resolve()))
