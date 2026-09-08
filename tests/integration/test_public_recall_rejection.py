"""Check public admission witnesses against traps and real SQLite reads.

The 13 field attacks retain S3 A2's field/companion mapping. Fixtures are local;
no Host runner import or inference of expected rejection from observed errors.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import FrozenInstanceError, replace

import pytest
from simple_harness.runtime import (
    DeliveryRecipient,
    DisclosurePurpose,
    RecallBudget,
    RecallReasonCode,
)

from simple_harness_memory import MemoryScope, build_human_memory_v7
from simple_harness_memory.core.errors import MemoryIdempotencyConflict, MemoryOwnershipConflict
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

# 0.6.31：普通候选先于 confirmation 收集（group 的向量准入要与同类型普通候选比较）；
# 本文件证明的是"拒绝路径零候选访问"，两者的先后不是契约，只是正控的观测顺序。
COLLECTORS = ("_collect_typed_recall_candidates", "_collect_typed_recall_confirmation")
ALL_COLLECTORS = (*COLLECTORS, "_collect_typed_recall_short_candidates")
ADMISSION_TABLES = {
    "principals",
    "recall_authority_heads",
    "typed_recall_requests",
    "typed_recall_terminals",
    "typed_recall_decisions",
    "typed_recall_results",
}
FIELD_ATTACKS = (
    "principal_id",
    "run_id",
    "context_hash",
    "context_revision",
    "plan_id",
    "plan_hash",
    "disclosure_hash",
    "recipient",
    "purpose",
    "budget.max_items",
    "budget.max_bytes",
    "budget.max_tokens",
    "budget.deadline_ms",
)


def _baseline():
    principal = replace(_principal(), actor_id="principal-1")
    original = _context()
    context = replace(
        original,
        run_id="run-1",
        subject=principal.actor_id,
        context_revision=7,
        budget=RecallBudget(4, 4096, 1024, 2000),
        disclosure_context=replace(
            original.disclosure_context,
            run_id="run-1",
            subject=principal.actor_id,
            recipient_id=principal.actor_id,
            purpose=DisclosurePurpose.TASK_EXECUTION,
        ),
    )
    plan = replace(_recall_plan(context, idempotency_key="witness-base"), plan_id="plan-1")
    return principal, context, plan


def _attack(field, principal, context, plan):
    if field == "principal_id":
        return replace(principal, actor_id="principal-2"), context, plan
    if field == "context_hash":
        return (
            principal,
            context,
            replace(
                plan,
                context_hash="e1b5609251224d45c0b3a0d5b5cb2b02506881bfebb37aaf40101767a63652ca",
            ),
        )
    if field == "plan_id":
        return principal, context, replace(plan, plan_id="plan-2")
    if field == "plan_hash":
        return (
            principal,
            context,
            replace(plan, reason_codes=(RecallReasonCode.USER_PREFERENCE_DEPENDENCY,)),
        )
    if field == "run_id":
        context = replace(
            context,
            run_id="run-2",
            disclosure_context=replace(context.disclosure_context, run_id="run-2"),
        )
    elif field == "context_revision":
        context = replace(context, context_revision=8)
    elif field.startswith("budget."):
        name = field.split(".")[1]
        values = {"max_items": 5, "max_bytes": 4095, "max_tokens": 1023, "deadline_ms": 1999}
        context = replace(context, budget=replace(context.budget, **{name: values[name]}))
    else:
        changes = {
            "disclosure_hash": {"authority_ref": "disclosure-2"},
            "recipient": {"recipient": DeliveryRecipient.TASK_COLLABORATOR},
            "purpose": {"purpose": DisclosurePurpose.TASK_RESUME},
        }
        context = replace(
            context, disclosure_context=replace(context.disclosure_context, **changes[field])
        )
    # Binding companions are synchronized so the attack reaches idempotency.
    return (
        principal,
        context,
        replace(
            plan,
            run_id=context.run_id,
            context_revision=context.context_revision,
            context_hash=context.context_hash,
            disclosure_context=context.disclosure_context,
            budget=context.budget,
        ),
    )


def _request_digest(principal, context, plan):
    # Frozen v4 preimage, independent of Memory's request_hash helper.
    encoded = json.dumps(
        {
            "domain": "simple-harness-memory/typed-recall-request/v1",
            "payload": {
                "harness_protocol": "recall-v4",
                "memory_protocol": "typed-recall-v1",
                "principal_id": principal.actor_id,
                "context": context.to_json(),
                "plan": plan.to_json(),
            },
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_tables(statements):
    # Includes FROM/JOIN inside subqueries/triggers, not just leading SELECTs.
    return {
        table.lower()
        for sql in statements
        for table in re.findall(r'\b(?:FROM|JOIN)\s+["`\[]?([\w]+)', sql, re.IGNORECASE)
    }


def _trap_collectors(backend, monkeypatch, calls):
    for name in ALL_COLLECTORS:

        async def trap(*args, _name=name, **kwargs):
            calls.append(_name)
            raise AssertionError(f"candidate access crossed rejection boundary: {_name}")

        monkeypatch.setattr(backend, name, trap)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", FIELD_ATTACKS)
async def test_public_field_attack_has_zero_candidate_access(tmp_path, monkeypatch, field):
    path = tmp_path / "admission.db"
    manager = await build_human_memory_v7(path, clock=lambda: 20.0)
    principal, context, plan = _baseline()
    try:
        await manager.register_principal_owner(principal, MemoryScope.personal(principal.actor_id))
        first = await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        assert not first.replayed and first.candidate_query_started
    finally:
        await manager.close()

    # Baseline terminal must survive a real close/reopen, not an in-process cache.
    manager = await build_human_memory_v7(path, clock=lambda: 20.0)
    statements, calls = [], []
    await manager.backend.connection.set_trace_callback(statements.append)
    _trap_collectors(manager.backend, monkeypatch, calls)
    try:
        actor, ctx, proposal = _attack(field, principal, context, plan)
        expected_type, stage, reason = {
            "principal_id": (
                MemoryOwnershipConflict,
                "ownership",
                "typed_recall_subject_not_owned",
            ),
            "context_hash": (ValueError, "narrowing", "RecallPlan context_hash differs"),
        }.get(field, (MemoryIdempotencyConflict, "idempotency", "IDEMPOTENCY_CONFLICT"))
        assert proposal.idempotency_key == plan.idempotency_key
        assert _request_digest(actor, ctx, proposal) != _request_digest(principal, context, plan)
        if stage == "idempotency":
            proposal.validate_narrowing(ctx, current_time=20.0)
        witnesses = []
        for _ in range(2):
            statements.clear()
            with pytest.raises(expected_type) as caught:
                await manager.execute_typed_recall(principal=actor, context=ctx, plan=proposal)
            assert type(caught.value) is expected_type
            assert str(caught.value) == reason
            assert not calls
            tables = _read_tables(statements)
            assert tables <= ADMISSION_TABLES, statements
            if stage == "idempotency":
                assert "typed_recall_requests" in tables  # trace observed the real lookup
            else:
                assert statements == []
            witness = caught.value.rejection_receipt
            assert witness.schema_version == 1
            assert isinstance(witness.invocation_id, str) and witness.invocation_id
            assert witness.stage == stage and witness.reason == reason
            assert (
                witness.context_hash == ctx.context_hash and witness.plan_hash == proposal.plan_hash
            )
            assert witness.request_hash == _request_digest(actor, ctx, proposal)
            assert witness.candidate_query_started is False
            assert type(witness.candidate_query_count) is int and witness.candidate_query_count == 0
            with pytest.raises(FrozenInstanceError):
                witness.reason = "replacement"
            witnesses.append(witness)
        assert witnesses[0].invocation_id != witnesses[1].invocation_id
        statements.clear()
        replay = await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        assert (
            replay.replayed and replay.result == first.result and replay.decision == first.decision
        )
        assert replay.candidate_query_started is False and replay.candidate_query_count == 0
        assert not calls
        assert "typed_recall_results" in _read_tables(statements)
        assert _read_tables(statements) <= ADMISSION_TABLES, statements
    finally:
        await manager.backend.connection.set_trace_callback(None)
        await manager.close()


@pytest.mark.asyncio
async def test_normal_recall_positive_control_observes_collectors_and_real_sql(
    tmp_path, monkeypatch
):
    manager = await build_human_memory_v7(tmp_path / "positive.db", clock=lambda: 20.0)
    statements, calls = [], []
    await manager.backend.connection.set_trace_callback(statements.append)
    try:
        for name in COLLECTORS:
            original = getattr(manager.backend, name)

            async def observed(*args, _original=original, _name=name, **kwargs):
                calls.append(_name)
                return await _original(*args, **kwargs)

            monkeypatch.setattr(manager.backend, name, observed)
        principal, context, plan = _baseline()
        result = await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        assert calls == list(COLLECTORS)
        assert result.candidate_query_started and not result.replayed
        # Empty results still read candidates: returned-row count is not query count.
        assert {
            "cognitive_conflict_groups",
            "cognitive_memory_heads",
            "cognitive_memory_revisions",
        } <= (_read_tables(statements))
        assert _read_tables(statements) - ADMISSION_TABLES
    finally:
        await manager.backend.connection.set_trace_callback(None)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("collector", COLLECTORS)
@pytest.mark.parametrize("error_kind", ["idempotency", "narrowing", "storage"])
async def test_error_inside_collector_has_no_admission_receipt(
    tmp_path, monkeypatch, collector, error_kind
):
    manager = await build_human_memory_v7(tmp_path / "collector-error.db", clock=lambda: 20.0)
    statements, calls = [], []
    await manager.backend.connection.set_trace_callback(statements.append)
    error = {
        "idempotency": MemoryIdempotencyConflict("IDEMPOTENCY_CONFLICT"),
        "narrowing": ValueError("RecallPlan context_hash differs"),
        "storage": RuntimeError("candidate storage unavailable"),
    }[error_kind]
    original = getattr(manager.backend, collector)

    async def fail_after_real_read(*args, **kwargs):
        await original(*args, **kwargs)
        calls.append(collector)
        raise error

    monkeypatch.setattr(manager.backend, collector, fail_after_real_read)
    try:
        principal, context, plan = _baseline()
        with pytest.raises(type(error)) as caught:
            await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        assert caught.value is error  # same class/message must not trigger a global wrapper
        assert calls == [collector]
        assert "cognitive_memory_heads" in _read_tables(statements)
        assert getattr(caught.value, "rejection_receipt", None) is None
    finally:
        await manager.backend.connection.set_trace_callback(None)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["manager", "backend"])
@pytest.mark.parametrize("version", [5, True, "4", None, 4.0])
async def test_public_protocol_admission_rejects_before_any_sql(tmp_path, entry, version):
    manager = await build_human_memory_v7(tmp_path / "protocol.db", clock=lambda: 20.0)
    statements = []
    await manager.backend.connection.set_trace_callback(statements.append)
    try:
        principal, context, plan = _baseline()
        target = manager if entry == "manager" else manager.backend
        reason = (
            "typed_recall_protocol_unsupported"
            if type(version) is int
            else "typed_recall_protocol_invalid"
        )
        with pytest.raises(ValueError) as caught:
            await target.execute_typed_recall(
                principal=principal, context=context, plan=plan, harness_protocol=version
            )
        assert str(caught.value) == reason
        assert statements == []  # no reads either, not merely unchanged durable state
        witness = caught.value.rejection_receipt
        assert witness.schema_version == 1 and witness.invocation_id
        assert witness.stage == "protocol" and witness.reason == reason
        assert witness.request_hash is None
        assert witness.context_hash == context.context_hash and witness.plan_hash == plan.plan_hash
        assert witness.candidate_query_started is False and witness.candidate_query_count == 0
        admitted = await manager.execute_typed_recall(
            principal=principal, context=context, plan=plan, harness_protocol=4
        )
        replay = await manager.execute_typed_recall(principal=principal, context=context, plan=plan)
        assert not admitted.replayed and replay.replayed
        assert admitted.result == replay.result and admitted.decision == replay.decision
        async with manager.backend.connection.execute(
            "SELECT request_hash FROM typed_recall_requests"
        ) as cursor:
            assert [row[0] for row in await cursor.fetchall()] == [
                _request_digest(principal, context, plan)
            ]
    finally:
        await manager.backend.connection.set_trace_callback(None)
        await manager.close()
