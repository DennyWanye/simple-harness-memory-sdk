from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import fingerprint_json
from simple_harness.runtime import (
    ConflictStatus,
    ContextFragmentBindingV2,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceRef,
    ExistingMemoryTarget,
    IntendedAudience,
    LongTermMemoryType,
    MemoryMutationKind,
    ProcedureLifecycleState,
    ProspectiveLifecycleState,
    ProspectiveSignalKind,
    RecallBudget,
    RecallContext,
    RecallContextUseAuthorizationRequestV1,
    RecallDecisionOutcome,
    RecallItemBindingV1,
    RecallPlan,
    RecallReasonCode,
    RecallResultPageRequestV1,
    RecallRetrievalMode,
    RecallSelectorDomain,
    SemanticMemoryPayload,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SuppressionRequest,
    SuppressionScopeKind,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _operation,
    _prepared,
    _span,
    _tamper_immutable_table,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _plan as mutation_plan,
)
from tests.integration.test_procedure_observation_repository_v5 import (
    _grant as procedure_grant,
)
from tests.integration.test_procedure_observation_repository_v5 import (
    _setup as procedure_setup,
)
from tests.integration.test_prospective_signal_repository_v5 import (
    _grant as prospective_grant,
)
from tests.integration.test_prospective_signal_repository_v5 import (
    _setup as prospective_setup,
)
from tests.integration.test_short_horizon_repository_v5 import (
    NOW as SHORT_NOW,
)
from tests.integration.test_short_horizon_repository_v5 import (
    PRINCIPAL as SHORT_PRINCIPAL,
)
from tests.integration.test_short_horizon_repository_v5 import (
    _backend as short_backend,
)
from tests.integration.test_short_horizon_repository_v5 import (
    _registration as short_registration,
)


def _principal() -> MemoryPrincipal:
    return MemoryPrincipal("deployment-1", "household-1", "actor-1", "session-1")


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        "run-recall",
        "actor-1",
        DeliveryRecipient.USER_SELF,
        "actor-1",
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "disclosure-recall",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _context(
    *,
    query: str = "concise",
    selectors: tuple[RecallSelectorDomain, ...] = (RecallSelectorDomain.MEMORY_TYPE,),
    modes: tuple[RecallRetrievalMode, ...] = (RecallRetrievalMode.FULL_TEXT,),
    event_refs: tuple[str, ...] = (),
    memory_types: tuple[LongTermMemoryType, ...] = (LongTermMemoryType.SEMANTIC,),
    short_horizon: bool = False,
    expires_at: float = 100.0,
    entity_constraints: tuple[str, ...] = (),
    earliest_occurred_at: float | None = None,
    latest_occurred_at: float | None = None,
    budget: RecallBudget | None = None,
    disclosure: DisclosureContext | None = None,
    procedure_applicability_fingerprints: tuple[str, ...] = (),
) -> RecallContext:
    return RecallContext(
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
        _disclosure() if disclosure is None else disclosure,
        (EvidenceRef("evidence-recall", "e" * 64, 1),),
        RecallBudget(8, 16_384, 2_048, 1_000) if budget is None else budget,
    )


def _recall_plan(
    context: RecallContext,
    *,
    idempotency_key: str,
    requested_memory_types: tuple[LongTermMemoryType, ...] | None = None,
    selector_domains: tuple[RecallSelectorDomain, ...] | None = None,
) -> RecallPlan:
    return RecallPlan(
        "plan-recall",
        context.run_id,
        context.subject,
        context.context_hash,
        context.context_revision,
        context.query,
        (
            context.available_memory_types
            if requested_memory_types is None
            else requested_memory_types
        ),
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
        (RecallReasonCode.USER_FACT_DEPENDENCY,),
    )


async def _contest_semantic(
    backend: SQLiteHumanMemoryBackend,
    authority: object,
) -> str:
    async with backend.connection.execute(
        "SELECT memory_id FROM cognitive_memory_heads WHERE memory_type='semantic'"
    ) as cursor:
        memory_id = str((await cursor.fetchone())[0])  # type: ignore[index]
    challenger_envelope, challenger_receipt = _admitted(evidence_id="evidence-2")
    challenger_span = _span(challenger_envelope, challenger_receipt)
    authority.register_admitted(  # type: ignore[attr-defined]
        challenger_envelope, challenger_receipt, challenger_span
    )
    await backend.ingest_committed_evidence(challenger_envelope, challenger_receipt)
    contest = replace(
        _operation(
            challenger_span,
            operation_id="typed-recall-contest",
            kind=MemoryMutationKind.CONTEST,
            target=ExistingMemoryTarget(memory_id, 1),
            conflict_status=ConflictStatus.CONTESTED,
        ),
        payload=SemanticMemoryPayload(
            "user:self", "response_style", "verbose", ("default",)
        ),
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(
            challenger_envelope,
            contest,
            base_revision=2,
            plan_id="typed-recall-contest-plan",
            idempotency_key="typed-recall-contest-key",
        ),
    )
    return challenger_envelope.evidence_id


@pytest.mark.asyncio
async def test_unsupported_is_zero_query_and_exact_replay_is_content_free(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "unsupported.db", now=lambda: 20.0)
    await backend.initialize()
    context = _context(
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.EVENT),
        modes=(RecallRetrievalMode.EXACT, RecallRetrievalMode.GRAPH),
        event_refs=("event-1",),
    )
    plan = _recall_plan(context, idempotency_key="idem-unsupported")
    first = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert first.decision.outcome is RecallDecisionOutcome.REJECTED
    assert first.result.items == ()
    assert not first.candidate_query_started
    assert first.candidate_query_count == 0
    assert first.unsupported_capabilities == (
        "selector:event",
        "retrieval:exact",
        "retrieval:graph",
    )

    replay = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert replay.replayed
    assert replay.decision == first.decision
    assert replay.result == first.result
    assert not replay.candidate_query_started
    assert replay.candidate_query_count == 0

    changed_context = _context(
        query="different",
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.EVENT),
        modes=(RecallRetrievalMode.EXACT, RecallRetrievalMode.GRAPH),
        event_refs=("event-1",),
    )
    changed_plan = replace(
        _recall_plan(changed_context, idempotency_key=plan.idempotency_key),
        plan_id=plan.plan_id,
    )
    with pytest.raises(MemoryIdempotencyConflict, match="IDEMPOTENCY_CONFLICT"):
        await backend.execute_typed_recall(
            principal=_principal(), context=changed_context, plan=changed_plan
        )
    async with backend.connection.execute(
        "SELECT candidate_query_started,candidate_query_count FROM typed_recall_terminals"
    ) as cursor:
        assert tuple(tuple(row) for row in await cursor.fetchall()) == ((0, 0),)
    await backend.close()


@pytest.mark.asyncio
async def test_one_eligible_semantic_is_persisted_as_content_bearing_typed_result(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "one-item.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    plan = _recall_plan(context, idempotency_key="idem-one-item")
    execution = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert execution.decision.outcome is RecallDecisionOutcome.RECALL
    assert execution.candidate_query_started
    assert execution.candidate_query_count == 1
    assert len(execution.result.items) == 1
    item = execution.result.items[0]
    assert item.selected_item.memory_type is LongTermMemoryType.SEMANTIC
    assert item.selected_item.source_revision == 1
    assert item.public_payload["object_value"] == "concise"
    assert item.selected_item.public_payload_hash
    assert item.selected_item.source_content_hash != item.selected_item.public_payload_hash
    execution.result.validate_decision(execution.decision)
    page = await backend.page_typed_recall_result(
        principal=_principal(),
        request=RecallResultPageRequestV1(
            execution.result.result_id,
            execution.result.result_hash,
            1,
            0,
            1,
            16_384,
            20.0,
        ),
    )
    assert page.complete and len(page.bindings) == 1
    assert page.bindings[0].item_hash == item.result_item_hash
    backend._now = lambda: 101.0
    with pytest.raises(MemoryValidationError, match="typed_recall_result_expired"):
        await backend.page_typed_recall_result(
            principal=_principal(),
            request=RecallResultPageRequestV1(
                execution.result.result_id,
                execution.result.result_hash,
                1,
                0,
                1,
                16_384,
                20.0,
            ),
        )
    backend._now = lambda: 20.0
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM typed_recall_decisions"
    ) as cursor:
        decision_count = await cursor.fetchone()
        assert decision_count is not None
        assert decision_count[0] == 1
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM typed_recall_result_items"
    ) as cursor:
        result_item_count = await cursor.fetchone()
        assert result_item_count is not None
        assert result_item_count[0] == 1
    await backend.close()


@pytest.mark.asyncio
async def test_contested_memory_is_only_disclosed_as_one_complete_confirmation_group(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, authority = await _prepared(
        tmp_path / "confirmation.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    challenger_evidence_id = await _contest_semantic(backend, authority)
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-confirmation"),
    )
    assert execution.decision.outcome is RecallDecisionOutcome.NEEDS_USER_CONFIRMATION
    assert execution.decision.selected_items == ()
    assert execution.result.items == ()
    assert len(execution.decision.confirmation_groups) == 1
    assert len(execution.decision.confirmation_groups[0].members) == 2
    assert len(execution.result.confirmation_groups[0].members) == 2
    page = await backend.page_typed_recall_result(
        principal=_principal(),
        request=RecallResultPageRequestV1(
            execution.result.result_id,
            execution.result.result_hash,
            1,
            0,
            1,
            16_384,
            20.0,
        ),
    )
    assert page.complete and len(page.bindings) == 1
    assert len(page.bindings[0].member_bindings) == 2
    fragment = ContextFragmentBindingV2("confirmation-fragment", "c" * 64)
    partial_member = execution.result.confirmation_groups[0].members[0]
    partial_request = RecallContextUseAuthorizationRequestV1(
        "actor-1",
        context.run_id,
        context.turn_id,
        "provider-partial-confirmation",
        execution.decision.decision_id,
        execution.decision.decision_hash,
        execution.result.result_id,
        execution.result.result_hash,
        (
            RecallItemBindingV1(
                partial_member.member.item_id,
                partial_member.result_member_hash,
            ),
        ),
        (fragment,),
        fingerprint_json([fragment.to_json()]),
        20.0,
    )
    with pytest.raises(
        MemoryValidationError, match="typed_recall_confirmation_group_must_be_complete"
    ):
        await backend.authorize_recall_context_use(
            principal=_principal(), request=partial_request, now=20.0
        )

    await backend.suppress(
        SuppressionRequest(
            "suppress-confirmation-member",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            challenger_evidence_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    excluded = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-partial-confirmation"),
    )
    assert excluded.decision.confirmation_groups == ()
    assert excluded.result.confirmation_groups == ()
    assert excluded.result.items == ()
    await backend.close()


@pytest.mark.asyncio
async def test_terminal_fault_rolls_back_body_and_same_request_retries_cleanly(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "fault-retry.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    plan = _recall_plan(context, idempotency_key="idem-fault-retry")

    def fail_after_header(point: str) -> None:
        if point == "typed_recall.after_decision_header":
            raise RuntimeError("injected terminal fault")

    backend._fault_injector = fail_after_header
    with pytest.raises(RuntimeError, match="injected terminal fault"):
        await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=plan
        )
    async with backend.connection.execute(
        "SELECT (SELECT COUNT(*) FROM typed_recall_decisions),"
        "(SELECT COUNT(*) FROM typed_recall_results),"
        "(SELECT COUNT(*) FROM typed_recall_terminals)"
    ) as cursor:
        assert tuple(await cursor.fetchone()) == (0, 0, 0)  # type: ignore[arg-type]

    backend._fault_injector = None
    recovered = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert recovered.decision.outcome is RecallDecisionOutcome.RECALL
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM typed_recall_attempts"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 2  # type: ignore[index]
    replay = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert replay.replayed and replay.result == recovered.result
    await backend.close()


@pytest.mark.asyncio
async def test_context_use_exact_replay_and_suppression_epoch_fence(tmp_path: Path) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "context-use.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-context-use"),
    )
    item = execution.result.items[0]
    fragment = ContextFragmentBindingV2("fragment-1", "f" * 64)
    manifest_hash = fingerprint_json([fragment.to_json()])

    def use_request(provider_attempt_id: str) -> RecallContextUseAuthorizationRequestV1:
        return RecallContextUseAuthorizationRequestV1(
            "actor-1",
            context.run_id,
            context.turn_id,
            provider_attempt_id,
            execution.decision.decision_id,
            execution.decision.decision_hash,
            execution.result.result_id,
            execution.result.result_hash,
            (RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
            (fragment,),
            manifest_hash,
            20.0,
        )

    request = use_request("provider-attempt-1")
    receipt = await backend.authorize_recall_context_use(
        principal=_principal(), request=request, now=20.0
    )
    replay = await backend.authorize_recall_context_use(
        principal=_principal(), request=request, now=20.0
    )
    assert replay == receipt
    with pytest.raises(
        MemoryValidationError,
        match="typed_recall_context_use_invocation_binding_invalid",
    ):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=replace(
                request,
                provider_attempt_id="provider-attempt-wrong-run",
                run_id="wrong-run",
            ),
            now=20.0,
        )
    with pytest.raises(
        MemoryValidationError,
        match="typed_recall_context_use_invocation_binding_invalid",
    ):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=replace(
                request,
                provider_attempt_id="provider-attempt-wrong-turn",
                turn_id="wrong-turn",
            ),
            now=20.0,
        )
    await backend.suppress(
        SuppressionRequest(
            "suppress-after-context-use",
            "actor-1",
            SuppressionScopeKind.MEMORY,
            item.selected_item.source_ref,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    assert (
        await backend.authorize_recall_context_use(
            principal=_principal(), request=request, now=20.0
        )
        == receipt
    )
    with pytest.raises(MemoryValidationError, match="RECALL_AUTHORITY_STALE"):
        await backend.authorize_recall_context_use(
            principal=_principal(),
            request=use_request("provider-attempt-2"),
            now=20.0,
        )
    await backend.close()


@pytest.mark.asyncio
async def test_collection_epoch_change_never_binds_stale_candidate_to_new_authority(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "collection-race.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    plan = _recall_plan(context, idempotency_key="idem-collection-race")
    collected = asyncio.Event()
    resume = asyncio.Event()
    original_collect = backend._collect_typed_recall_candidates

    async def pause_after_collect(**kwargs: object) -> object:
        result = await original_collect(**kwargs)  # type: ignore[arg-type]
        collected.set()
        await resume.wait()
        return result

    backend._collect_typed_recall_candidates = pause_after_collect  # type: ignore[assignment]
    task = asyncio.create_task(
        backend.execute_typed_recall(principal=_principal(), context=context, plan=plan)
    )
    await asyncio.wait_for(collected.wait(), timeout=2.0)
    await backend.suppress(
        SuppressionRequest(
            "suppress-during-collection",
            "actor-1",
            SuppressionScopeKind.EVIDENCE,
            envelope.evidence_id,
            "user_forget",
            20.0,
            OrdinaryMemoryPurpose.RECALL,
        )
    )
    resume.set()
    with pytest.raises(MemoryValidationError, match="RECALL_AUTHORITY_STALE"):
        await asyncio.wait_for(task, timeout=2.0)
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM typed_recall_terminals"
    ) as cursor:
        assert int((await cursor.fetchone())[0]) == 0  # type: ignore[index]

    backend._collect_typed_recall_candidates = original_collect  # type: ignore[method-assign]
    retry = await backend.execute_typed_recall(
        principal=_principal(), context=context, plan=plan
    )
    assert retry.decision.outcome is RecallDecisionOutcome.NO_RECALL
    assert retry.result.items == ()
    async with backend.connection.execute(
        "SELECT t.authority_epoch,h.authority_epoch FROM typed_recall_results t "
        "JOIN recall_authority_heads h ON h.principal_id=?",
        (_principal().actor_id,),
    ) as cursor:
        assert tuple(await cursor.fetchone()) == (3, 3)  # type: ignore[arg-type]
    await backend.close()


@pytest.mark.asyncio
async def test_absolute_deadline_cancels_slow_candidate_work_and_persists_terminal(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "typed-deadline.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context(budget=RecallBudget(8, 16_384, 2_048, 30))
    plan = _recall_plan(context, idempotency_key="idem-absolute-deadline")
    original_collect = backend._collect_typed_recall_candidates

    async def slow_collect(**kwargs: object) -> object:
        await asyncio.sleep(1.0)
        return await original_collect(**kwargs)  # type: ignore[arg-type]

    backend._collect_typed_recall_candidates = slow_collect  # type: ignore[assignment]
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="DEADLINE_EXCEEDED"):
        await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=plan
        )
    assert time.monotonic() - started < 0.25
    async with backend.connection.execute(
        "SELECT terminal_kind,decision_id,result_id FROM typed_recall_terminals"
    ) as cursor:
        assert tuple(await cursor.fetchone()) == ("deadline_exceeded", None, None)  # type: ignore[arg-type]
    await backend.close()


@pytest.mark.asyncio
async def test_reopen_rejects_context_use_receipt_cross_row_principal_tamper(
    tmp_path: Path,
) -> None:
    path = tmp_path / "context-use-tamper.db"
    backend, envelope, _receipt, span, _authority = await _prepared(
        path, now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    execution = await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-context-use-tamper"),
    )
    item = execution.result.items[0]
    fragment = ContextFragmentBindingV2("tamper-fragment", "f" * 64)
    request = RecallContextUseAuthorizationRequestV1(
        "actor-1",
        context.run_id,
        context.turn_id,
        "provider-tamper-attempt",
        execution.decision.decision_id,
        execution.decision.decision_hash,
        execution.result.result_id,
        execution.result.result_hash,
        (RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
        (fragment,),
        fingerprint_json([fragment.to_json()]),
        20.0,
    )
    await backend.authorize_recall_context_use(
        principal=_principal(), request=request, now=20.0
    )
    await backend.close()
    _tamper_immutable_table(
        path,
        "recall_context_use_receipts",
        "UPDATE recall_context_use_receipts SET principal_id='other-principal'",
    )
    reopened = SQLiteHumanMemoryBackend(path)
    with pytest.raises(MemoryCorruptionError):
        await reopened.initialize()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "update_sql"),
    (
        (
            "typed_recall_requests",
            "UPDATE typed_recall_requests SET request_hash='" + "a" * 64 + "'",
        ),
        (
            "typed_recall_attempts",
            "UPDATE typed_recall_attempts SET attempt_hash='" + "a" * 64 + "'",
        ),
        (
            "typed_recall_decision_items",
            "UPDATE typed_recall_decision_items SET item_hash='" + "a" * 64 + "'",
        ),
        (
            "typed_recall_decisions",
            "UPDATE typed_recall_decisions SET created_at=created_at+1",
        ),
        (
            "typed_recall_result_items",
            "UPDATE typed_recall_result_items SET result_item_hash='" + "a" * 64 + "'",
        ),
        (
            "typed_recall_results",
            "UPDATE typed_recall_results SET decision_id='typed-recall-decision:missing'",
        ),
        (
            "typed_recall_results",
            "UPDATE typed_recall_results SET created_at=created_at+1",
        ),
        (
            "typed_recall_terminals",
            "UPDATE typed_recall_terminals SET terminal_hash='" + "a" * 64 + "'",
        ),
        (
            "typed_recall_terminals",
            "UPDATE typed_recall_terminals SET attempt_id='typed-recall-attempt:missing'",
        ),
        ("typed_recall_decision_items", "DELETE FROM typed_recall_decision_items"),
    ),
)
async def test_reopen_recomputes_every_typed_recall_hash_and_cardinality(
    tmp_path: Path,
    table: str,
    update_sql: str,
) -> None:
    path = tmp_path / f"tamper-{table}.db"
    backend, envelope, _receipt, span, _authority = await _prepared(
        path, now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    context = _context()
    await backend.execute_typed_recall(
        principal=_principal(),
        context=context,
        plan=_recall_plan(context, idempotency_key="idem-tamper"),
    )
    await backend.close()
    _tamper_immutable_table(path, table, update_sql)
    reopened = SQLiteHumanMemoryBackend(path)
    with pytest.raises(MemoryCorruptionError):
        await reopened.initialize()


@pytest.mark.asyncio
async def test_cognitive_vector_degradation_is_durable_not_unsupported(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "vector-degrade.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    vector_context = _context(modes=(RecallRetrievalMode.VECTOR,))
    vector_only = await backend.execute_typed_recall(
        principal=_principal(),
        context=vector_context,
        plan=_recall_plan(vector_context, idempotency_key="idem-vector-only"),
    )
    assert vector_only.decision.outcome is RecallDecisionOutcome.NO_RECALL
    assert vector_only.unsupported_capabilities == ()
    assert vector_only.degradation_codes == ("cognitive_vector_unavailable",)

    mixed_context = _context(
        modes=(RecallRetrievalMode.FULL_TEXT, RecallRetrievalMode.VECTOR)
    )
    mixed = await backend.execute_typed_recall(
        principal=_principal(),
        context=mixed_context,
        plan=_recall_plan(mixed_context, idempotency_key="idem-vector-mixed"),
    )
    assert mixed.decision.outcome is RecallDecisionOutcome.RECALL
    assert len(mixed.result.items) == 1
    assert mixed.degradation_codes == ("cognitive_vector_unavailable",)
    async with backend.connection.execute(
        "SELECT degradation_codes_json FROM typed_recall_terminals ORDER BY created_at"
    ) as cursor:
        assert all(
            "cognitive_vector_unavailable" in str(row[0])
            for row in await cursor.fetchall()
        )
    await backend.close()


@pytest.mark.asyncio
async def test_entity_and_time_selectors_use_typed_semantic_fields_and_open_interval(
    tmp_path: Path,
) -> None:
    backend, envelope, _receipt, span, _authority = await _prepared(
        tmp_path / "typed-selectors.db", now=lambda: 20.0
    )
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    matching = _context(
        selectors=(
            RecallSelectorDomain.MEMORY_TYPE,
            RecallSelectorDomain.ENTITY,
            RecallSelectorDomain.TIME,
        ),
        entity_constraints=("user:self",),
        earliest_occurred_at=50.0,
        latest_occurred_at=60.0,
    )
    match_result = await backend.execute_typed_recall(
        principal=_principal(),
        context=matching,
        plan=_recall_plan(matching, idempotency_key="idem-typed-selector-match"),
    )
    assert match_result.decision.outcome is RecallDecisionOutcome.RECALL

    object_entity = _context(
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.ENTITY),
        entity_constraints=("concise",),
    )
    object_entity_result = await backend.execute_typed_recall(
        principal=_principal(),
        context=object_entity,
        plan=_recall_plan(object_entity, idempotency_key="idem-typed-object-entity"),
    )
    assert object_entity_result.decision.outcome is RecallDecisionOutcome.RECALL

    non_entity_text = _context(
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.ENTITY),
        entity_constraints=("response_style",),
    )
    non_entity_result = await backend.execute_typed_recall(
        principal=_principal(),
        context=non_entity_text,
        plan=_recall_plan(non_entity_text, idempotency_key="idem-typed-entity-negative"),
    )
    assert non_entity_result.decision.outcome is RecallDecisionOutcome.NO_RECALL

    before_revision = _context(
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.TIME),
        earliest_occurred_at=1.0,
        latest_occurred_at=19.0,
    )
    before_result = await backend.execute_typed_recall(
        principal=_principal(),
        context=before_revision,
        plan=_recall_plan(before_revision, idempotency_key="idem-typed-time-negative"),
    )
    assert before_result.decision.outcome is RecallDecisionOutcome.NO_RECALL
    await backend.close()


@pytest.mark.asyncio
async def test_procedure_recall_requires_exact_host_applicability_fingerprint(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, evidence, memory_id, revision = await procedure_setup(
        tmp_path / "typed-procedure.db", clock
    )
    first = procedure_grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=revision,
        index=1,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.DRAFT,
    )
    await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=first
    )
    second = procedure_grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=2,
        index=3,
        transition_from=ProcedureLifecycleState.DRAFT,
        transition_to=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
    )
    await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=second
    )
    third = procedure_grant(
        authority,
        evidence,
        memory_id=memory_id,
        revision=3,
        index=4,
        transition_from=ProcedureLifecycleState.ELIGIBLE_FOR_ACTIVATION,
        transition_to=ProcedureLifecycleState.ACTIVE,
    )
    await backend.record_procedure_observation(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=third
    )
    async with backend.connection.execute(
        "SELECT p.applicability_fingerprint FROM procedure_records p "
        "JOIN cognitive_memory_heads h ON h.memory_id=p.memory_id "
        "AND h.current_revision=p.revision WHERE h.memory_id=?",
        (memory_id,),
    ) as cursor:
        fingerprint = str((await cursor.fetchone())[0])

    for suffix, fingerprints, expected in (
        ("absent", (), RecallDecisionOutcome.NO_RECALL),
        ("mismatch", ("a" * 64,), RecallDecisionOutcome.NO_RECALL),
        ("match", (fingerprint,), RecallDecisionOutcome.RECALL),
    ):
        context = _context(
            query="publish report",
            memory_types=(LongTermMemoryType.PROCEDURE,),
            procedure_applicability_fingerprints=fingerprints,
        )
        result = await backend.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key=f"idem-procedure-{suffix}"),
        )
        assert result.decision.outcome is expected
    await backend.close()


@pytest.mark.asyncio
async def test_prospective_recall_requires_current_registration_and_trigger_signal(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend, authority, memory_id, revision, outbox_id, outbox_hash = (
        await prospective_setup(tmp_path / "typed-prospective.db", clock)
    )

    def prospective_context() -> RecallContext:
        return _context(
            query="send report",
            memory_types=(LongTermMemoryType.PROSPECTIVE,),
        )

    before_context = prospective_context()
    before = await backend.execute_typed_recall(
        principal=_principal(),
        context=before_context,
        plan=_recall_plan(before_context, idempotency_key="idem-prospective-unregistered"),
    )
    assert before.decision.outcome is RecallDecisionOutcome.NO_RECALL

    accepted = prospective_grant(
        authority,
        memory_id=memory_id,
        revision=revision,
        kind=ProspectiveSignalKind.REGISTRATION_ACCEPTED,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.PENDING,
        observed_at=20.0,
        outbox_id=outbox_id,
        outbox_hash=outbox_hash,
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=accepted
    )
    pending_context = prospective_context()
    pending = await backend.execute_typed_recall(
        principal=_principal(),
        context=pending_context,
        plan=_recall_plan(pending_context, idempotency_key="idem-prospective-pending"),
    )
    assert pending.decision.outcome is RecallDecisionOutcome.RECALL

    clock[0] = 30.0
    due = prospective_grant(
        authority,
        memory_id=memory_id,
        revision=1,
        kind=ProspectiveSignalKind.TIME_DUE,
        transition_from=ProspectiveLifecycleState.PENDING,
        transition_to=ProspectiveLifecycleState.TRIGGERED,
        observed_at=30.0,
        signal_id="typed-due-signal",
        receipt_id="typed-due-receipt",
    )
    await backend.apply_prospective_signal(
        principal=_principal(), scope=MemoryScope.personal("actor-1"), reference=due
    )
    triggered_context = prospective_context()
    triggered = await backend.execute_typed_recall(
        principal=_principal(),
        context=triggered_context,
        plan=_recall_plan(triggered_context, idempotency_key="idem-prospective-triggered"),
    )
    assert triggered.decision.outcome is RecallDecisionOutcome.RECALL
    assert triggered.result.items[0].selected_item.source_revision == 2
    await backend.close()


@pytest.mark.asyncio
async def test_short_only_and_long_only_sources_are_strictly_isolated(tmp_path: Path) -> None:
    backend = await short_backend(
        tmp_path / "typed-short.db", tuple(short_registration(i) for i in range(1, 12))
    )
    await backend.rebuild_short_horizon_projection(principal=SHORT_PRINCIPAL)
    short_context = _context(
        query="Project alpha",
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.SHORT_HORIZON),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
    )
    short_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=short_context,
        plan=_recall_plan(
            short_context,
            idempotency_key="idem-short-only",
            requested_memory_types=(),
            selector_domains=(RecallSelectorDomain.SHORT_HORIZON,),
        ),
    )
    assert short_result.decision.outcome is RecallDecisionOutcome.RECALL
    assert all(
        item.selected_item.source_kind.value == "short_horizon"
        for item in short_result.result.items
    )

    long_context = _context(query="Project alpha", expires_at=SHORT_NOW + 100.0)
    long_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=long_context,
        plan=_recall_plan(long_context, idempotency_key="idem-long-isolation"),
    )
    assert long_result.decision.outcome is RecallDecisionOutcome.NO_RECALL
    assert long_result.result.items == ()
    await backend.close()


@pytest.mark.asyncio
async def test_short_typed_entity_time_attribute_floor_and_exact_expiry(
    tmp_path: Path,
) -> None:
    backend = await short_backend(
        tmp_path / "typed-short-selectors.db",
        tuple(short_registration(i) for i in range(1, 12)),
    )
    await backend.rebuild_short_horizon_projection(principal=SHORT_PRINCIPAL)
    positive = _context(
        query="Project alpha",
        selectors=(
            RecallSelectorDomain.MEMORY_TYPE,
            RecallSelectorDomain.SHORT_HORIZON,
            RecallSelectorDomain.ENTITY,
            RecallSelectorDomain.TIME,
        ),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
        entity_constraints=("project-alpha",),
        earliest_occurred_at=SHORT_NOW - 20.0,
        latest_occurred_at=SHORT_NOW,
    )
    positive_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=positive,
        plan=_recall_plan(
            positive,
            idempotency_key="idem-short-selectors-positive",
            requested_memory_types=(),
            selector_domains=(
                RecallSelectorDomain.SHORT_HORIZON,
                RecallSelectorDomain.ENTITY,
                RecallSelectorDomain.TIME,
            ),
        ),
    )
    assert positive_result.decision.outcome is RecallDecisionOutcome.RECALL

    wrong_entity = _context(
        query="Project alpha",
        selectors=(
            RecallSelectorDomain.MEMORY_TYPE,
            RecallSelectorDomain.SHORT_HORIZON,
            RecallSelectorDomain.ENTITY,
        ),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
        entity_constraints=("project-beta",),
    )
    wrong_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=wrong_entity,
        plan=_recall_plan(
            wrong_entity,
            idempotency_key="idem-short-selector-negative",
            requested_memory_types=(),
            selector_domains=(
                RecallSelectorDomain.SHORT_HORIZON,
                RecallSelectorDomain.ENTITY,
            ),
        ),
    )
    assert wrong_result.decision.outcome is RecallDecisionOutcome.NO_RECALL

    await backend.connection.execute(
        "UPDATE short_horizon_chunks SET effective_privacy_class='public',"
        "information_attributes_json='[\"health\"]'"
    )
    await backend.connection.commit()
    household_disclosure = replace(
        _disclosure(),
        recipient=DeliveryRecipient.HOUSEHOLD,
        recipient_id="household-1",
        intended_audience=IntendedAudience.HOUSEHOLD,
        purpose=DisclosurePurpose.TASK_EXECUTION,
    )
    household = _context(
        query="Project alpha",
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.SHORT_HORIZON),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
        disclosure=household_disclosure,
    )
    household_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=household,
        plan=_recall_plan(
            household,
            idempotency_key="idem-short-household-attribute-floor",
            requested_memory_types=(),
            selector_domains=(RecallSelectorDomain.SHORT_HORIZON,),
        ),
    )
    assert household_result.decision.outcome is RecallDecisionOutcome.NO_RECALL
    async with backend.connection.execute(
        "SELECT eligible_count,audit_json FROM short_horizon_audit "
        "WHERE event_kind='recall' AND disclosure_context_hash=? "
        "ORDER BY created_at DESC,audit_id DESC LIMIT 1",
        (household_disclosure.context_hash,),
    ) as cursor:
        household_audit = await cursor.fetchone()
    assert household_audit is not None and int(household_audit[0]) == 0
    assert json.loads(str(household_audit[1]))["details"]["eligible"] == []

    await backend.connection.execute(
        "UPDATE short_horizon_chunks SET expires_at=?", (SHORT_NOW,)
    )
    await backend.connection.commit()
    expired = _context(
        query="Project alpha",
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.SHORT_HORIZON),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
    )
    expired_result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=expired,
        plan=_recall_plan(
            expired,
            idempotency_key="idem-short-exact-expiry",
            requested_memory_types=(),
            selector_domains=(RecallSelectorDomain.SHORT_HORIZON,),
        ),
    )
    assert expired_result.decision.outcome is RecallDecisionOutcome.NO_RECALL
    await backend.connection.execute("DELETE FROM short_horizon_chunks")
    await backend.connection.commit()
    await backend.rebuild_short_horizon_projection(principal=SHORT_PRINCIPAL)
    await backend.close()


@pytest.mark.asyncio
async def test_short_typed_lane_and_type_fusion_cap_at_128(tmp_path: Path) -> None:
    backend = await short_backend(
        tmp_path / "typed-short-cap.db",
        tuple(short_registration(i) for i in range(1, 141)),
    )
    await backend.rebuild_short_horizon_projection(principal=SHORT_PRINCIPAL)
    context = _context(
        query="Project alpha",
        selectors=(RecallSelectorDomain.MEMORY_TYPE, RecallSelectorDomain.SHORT_HORIZON),
        memory_types=(LongTermMemoryType.SEMANTIC,),
        short_horizon=True,
        expires_at=SHORT_NOW + 100.0,
        budget=RecallBudget(32, 65_536, 8_192, 2_000),
    )
    result = await backend.execute_typed_recall(
        principal=SHORT_PRINCIPAL,
        context=context,
        plan=_recall_plan(
            context,
            idempotency_key="idem-short-cap-128",
            requested_memory_types=(),
            selector_domains=(RecallSelectorDomain.SHORT_HORIZON,),
        ),
    )
    assert result.decision.filtered_candidate_count == 128
    assert len(result.result.items) == 32
    assert result.result.truncated
    await backend.close()
