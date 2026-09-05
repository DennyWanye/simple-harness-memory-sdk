"""Real producer coverage and fault controls; no reader-produced expected receipts."""

from contextlib import suppress
from dataclasses import replace

import pytest
import simple_harness as h
from simple_harness.contracts import canonical_json, fingerprint_json

import simple_harness_memory as m
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLimitError
from tests.integration.test_audit_access_v6 import _AuditAccessAuthority, _grant, _principal
from tests.integration.test_operation_audit import _read, _suppress


async def capture_expected(db):
    # Independent source oracle: canonical producer rows saved BEFORE reader call.
    specs = (
        ("mutation_commit", "memory_mutation_receipts", "receipt_id", "receipt_hash", ""),
        (
            "mutation_rejection",
            "memory_mutation_rejection_audits",
            "rejection_id",
            "rejection_hash",
            "",
        ),
        ("typed_request", "typed_recall_requests", "request_id", "request_hash", ""),
        ("typed_attempt", "typed_recall_attempts", "attempt_id", "attempt_hash", ""),
        ("typed_terminal", "typed_recall_terminals", "request_id", "terminal_hash", ""),
        ("recall_context_use", "recall_context_use_receipts", "receipt_id", "receipt_hash", ""),
        (
            "short_recall",
            "short_horizon_audit",
            "audit_id",
            "audit_hash",
            "WHERE event_kind IN ('recall_started','recall','recall_terminal')",
        ),
        ("suppression", "suppression_directives", "directive_id", "decision_hash", ""),
        ("job_transition", "job_attempt_events", "event_id", "event_hash", ""),
    )
    result = []
    for family, table, key, digest, where in specs:
        async with db.execute(
            f"SELECT {key},{digest} FROM {table} {where} ORDER BY rowid"
        ) as cursor:
            result.extend(
                (family, m.operation_audit_ref_hash(family, row[0]), row[1])
                for row in await cursor.fetchall()
            )
    return result


async def mixed(tmp_path):
    from tests.integration.test_cognitive_mutation_repository_v5 import (
        _admitted,
        _Authority,
        _classification_policy,
        _operation,
        _plan,
        _span,
    )
    from tests.integration.test_short_horizon_repository_v5 import (
        NOW,
        _registration,
    )
    from tests.integration.test_short_horizon_repository_v5 import (
        _Authority as ConversationAuthority,
    )
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    audit = _AuditAccessAuthority()
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    evidence = _Authority(envelope, receipt, span)
    pairs = [_registration(i) for i in range(10, 22)]
    manager = await m.build_human_memory_v7(
        tmp_path / "mixed.db",
        clock=lambda: NOW,
        evidence_authority=evidence,
        audit_access_authority=audit,
        conversation_evidence_authority=ConversationAuthority(tuple(x[0] for x in pairs)),
    )
    p = _principal()
    try:
        await manager.register_principal_owner(p, m.MemoryScope.personal(p.actor_id))
        await manager.ingest_committed_evidence(envelope, receipt)
        with pytest.raises(m.MemoryValidationError, match="classification_policy_required"):
            await manager.apply_memory_mutation_plan(
                principal=p,
                scope=m.MemoryScope.personal(p.actor_id),
                plan=_plan(envelope, _operation(span)),
            )
    finally:
        await manager.close()
    manager = await m.build_human_memory_v7(
        tmp_path / "mixed.db",
        clock=lambda: NOW,
        evidence_authority=evidence,
        audit_access_authority=audit,
        classification_policy=_classification_policy(),
        conversation_evidence_authority=ConversationAuthority(tuple(x[0] for x in pairs)),
    )
    try:
        result = await manager.apply_memory_mutation_plan(
            principal=p,
            scope=m.MemoryScope.personal(p.actor_id),
            plan=_plan(
                envelope, _operation(span), plan_id="actual-commit", idempotency_key="actual-commit"
            ),
        )
        assert result.outcome is h.MemoryMutationApplyOutcome.COMMITTED
        no_plan = replace(
            _plan(
                envelope,
                _operation(span),
                base_revision=2,
                plan_id="actual-no-mutation",
                idempotency_key="actual-no-mutation",
            ),
            outcome=h.MemoryMutationPlanOutcome.NO_MUTATION,
            operations=(),
        )
        await manager.apply_memory_mutation_plan(
            principal=p, scope=m.MemoryScope.personal(p.actor_id), plan=no_plan
        )
        context = _context(expires_at=NOW + 100)
        execution = await manager.execute_typed_recall(
            principal=p,
            context=context,
            plan=_recall_plan(context, idempotency_key="actual-recall"),
        )
        assert execution.result.items
        item = execution.result.items[0]
        fragment = h.ContextFragmentBindingV2("fragment", "f" * 64)
        await manager.authorize_recall_context_use(
            principal=p,
            request=h.RecallContextUseAuthorizationRequestV1(
                p.actor_id,
                context.run_id,
                context.turn_id,
                "actual-provider-attempt",
                execution.decision.decision_id,
                execution.decision.decision_hash,
                execution.result.result_id,
                execution.result.result_hash,
                (h.RecallItemBindingV1(item.selected_item.item_id, item.result_item_hash),),
                (fragment,),
                fingerprint_json([fragment.to_json()]),
                NOW,
            ),
        )
        for registration, reference in pairs:
            await manager.ingest_committed_evidence(
                registration.envelope, registration.admission_receipt
            )
            await manager.register_conversation_evidence(reference)
        await manager.rebuild_short_horizon_projection(principal=p)
        short = await manager.recall_short_horizon(
            principal=p, query="Project alpha", disclosure_context=context.disclosure_context
        )
        assert short.hits
        directive = await _suppress(manager, p)
        await manager.revoke_suppression(
            principal=p,
            request=m.SuppressionRevokeRequest(
                "revoke-actual",
                p.actor_id,
                directive.directive_id,
                "user_restore",
                NOW,
            ),
        )
        _, ref = _grant(audit, max_reads=32, issued_at=NOW - 1, expires_at=NOW + 100)
        grant = await manager.authorize_audit_access(principal=p, authority_ref=ref)
        return manager, p, grant
    except BaseException:
        await manager.close()
        raise


async def test_real_mixed_all_nonjob_families_receipts_and_pages(tmp_path):
    manager, p, receipt = await mixed(tmp_path)
    try:
        expected = await capture_expected(manager.backend.connection)
        assert {f for f, _, _ in expected} == {
            "mutation_commit",
            "mutation_rejection",
            "typed_request",
            "typed_attempt",
            "typed_terminal",
            "recall_context_use",
            "short_recall",
            "suppression",
        }
        observed, cursor = [], None
        first = None
        while True:
            page = await _read(manager, p, receipt, limit=2, cursor=cursor)
            if first is None:
                first = page
                await _suppress(manager, p, "after-pinned-cut")
            assert page.snapshot_hash == first.snapshot_hash
            observed.extend((i.family, i.event_ref_hash, i.receipt_hash) for i in page.items)
            assert "payload-secret" not in canonical_json(page.to_json())
            cursor = page.next_cursor
            if cursor is None:
                break
        assert observed == expected
        assert len(observed) == len(set(observed))
        commits = [i for i in first.items if i.family == "mutation_commit"]
        assert {i.cognitive_effect for i in commits} == {"written", "no_mutation"}
    finally:
        await manager.close()


@pytest.mark.parametrize("damage", ["typed_terminal", "mutation_rejection"])
async def test_fresh_snapshot_checks_canonical_row_bindings(tmp_path, damage):
    manager, p, receipt = await mixed(tmp_path)
    try:
        db = manager.backend.connection
        if damage == "typed_terminal":
            await db.execute("DROP TRIGGER typed_recall_terminals_immutable_update")
            await db.execute("UPDATE typed_recall_terminals SET result_hash=?", ("b" * 64,))
        else:
            await db.execute("DROP TRIGGER memory_mutation_rejection_audits_immutable_update")
            await db.execute("UPDATE memory_mutation_rejection_audits SET plan_id='foreign-plan'")
        await db.commit()
        with pytest.raises(MemoryCorruptionError):
            await _read(manager, p, receipt)
    finally:
        with suppress(MemoryCorruptionError):
            await manager.close()


@pytest.mark.parametrize(
    "limit_name,reason",
    [
        ("_MAX_ROWS", "operation_audit_snapshot_limit_exceeded"),
        ("_MAX_VALIDATION_ROWS", "operation_audit_validation_limit_exceeded"),
        ("_MAX_DATABASE_BYTES", "operation_audit_database_limit_exceeded"),
        ("_MAX_SQL_STEPS", "operation_audit_scan_limit_exceeded"),
    ],
)
async def test_real_budget_exhaustion_no_partial_page_and_cleanup(
    tmp_path, monkeypatch, limit_name, reason
):
    from simple_harness_memory.backends import operation_audit as reader
    from tests.integration.test_operation_audit import _open

    manager, p, receipt, _ = await _open(tmp_path, max_reads=1)
    try:
        await _suppress(manager, p)
        with monkeypatch.context() as patch:
            patch.setattr(reader, limit_name, 0)
            with pytest.raises(MemoryLimitError, match=reason):
                await _read(manager, p, receipt)
        assert not manager.backend.connection.in_transaction
        # Failure consumed no shared grant and left no SQL progress handler behind.
        assert (await _read(manager, p, receipt)).enumeration_complete
    finally:
        await manager.close()


async def test_real_typed_attempt_cut_then_completion_and_deleted_terminal(tmp_path, monkeypatch):
    from tests.integration.test_operation_audit import _open
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    manager, p, receipt, _ = await _open(tmp_path)
    try:
        await _suppress(manager, p, "1")
        await _suppress(manager, p, "2")
        original = manager.backend._collect_typed_recall_confirmation
        snapshots = []

        async def after_admission(**kwargs):
            snapshots.append(await _read(manager, p, receipt, limit=1))
            return await original(**kwargs)

        monkeypatch.setattr(manager.backend, "_collect_typed_recall_confirmation", after_admission)
        context = _context()
        await manager.execute_typed_recall(
            principal=p,
            context=context,
            plan=_recall_plan(context, idempotency_key="actual-after-cut"),
        )
        first = snapshots[0]
        assert next(c for c in first.coverage if c.family == "typed_attempt").unresolved_ref_hashes
        old = await _read(manager, p, receipt, limit=1, cursor=first.next_cursor)
        assert old.snapshot_hash == first.snapshot_hash and old.coverage == first.coverage
        fresh = await _read(manager, p, receipt)
        assert not next(
            c for c in fresh.coverage if c.family == "typed_attempt"
        ).unresolved_ref_hashes
        db = manager.backend.connection
        await db.execute("DROP TRIGGER typed_recall_terminals_immutable_delete")
        await db.execute("DELETE FROM typed_recall_terminals")
        await db.commit()
        missing = await _read(manager, p, receipt)
        assert next(
            c for c in missing.coverage if c.family == "typed_terminal"
        ).missing_event_ref_hashes
        # The late result never retroactively alters the earlier unresolved snapshot.
        assert (
            await _read(manager, p, receipt, limit=1, cursor=first.next_cursor)
        ).to_json() == old.to_json()
    finally:
        await manager.close()


async def test_actual_cancel_retry_ordinal_deletion_is_detected(tmp_path, monkeypatch):
    import asyncio

    from tests.integration.test_operation_audit import _open
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    manager, p, receipt, _ = await _open(tmp_path)
    try:

        async def cancelled(**kwargs):
            raise asyncio.CancelledError()

        original = manager.backend._collect_typed_recall_confirmation
        context = _context()
        plan = _recall_plan(context, idempotency_key="actual-cancel-retry")
        monkeypatch.setattr(manager.backend, "_collect_typed_recall_confirmation", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await manager.execute_typed_recall(principal=p, context=context, plan=plan)
        monkeypatch.setattr(manager.backend, "_collect_typed_recall_confirmation", original)
        await manager.execute_typed_recall(principal=p, context=context, plan=plan)
        page = await _read(manager, p, receipt)
        assert next(c for c in page.coverage if c.family == "typed_attempt").row_count == 2
        db = manager.backend.connection
        await db.execute("DROP TRIGGER typed_recall_attempts_immutable_delete")
        await db.execute("DELETE FROM typed_recall_attempts WHERE attempt_ordinal=1")
        await db.commit()
        with pytest.raises(MemoryCorruptionError, match="attempt_ordinal"):
            await _read(manager, p, receipt)
    finally:
        await manager.close()


async def test_short_timeout_emits_actual_terminal_and_shared_attempt(tmp_path, monkeypatch):
    from tests.integration.test_operation_audit import _open
    from tests.integration.test_typed_recall_v6 import _disclosure

    manager, p, receipt, _ = await _open(tmp_path)
    try:

        async def timeout(**kwargs):
            raise TimeoutError()

        monkeypatch.setattr(manager.backend, "_recall_short_horizon_after_start", timeout)
        result = await manager.recall_short_horizon(
            principal=p, query="payload-secret-timeout", disclosure_context=_disclosure()
        )
        assert not result.hits and result.degradation_code.value == "DEADLINE_EXCEEDED"
        # close drains the actual SDK-owned pending terminal task; reopen is public.
        await manager.close()
        manager = await m.build_human_memory_v7(tmp_path / "memory.db", clock=lambda: 40.0)
        page = await _read(manager, p, receipt)
        items = [i for i in page.items if i.family == "short_recall"]
        assert [i.event_kind for i in items] == ["recall_started", "recall_terminal"]
        assert len({i.attempt_ref_hash for i in items}) == 1
        assert not next(
            c for c in page.coverage if c.family == "short_recall"
        ).unresolved_ref_hashes
        assert "payload-secret-timeout" not in canonical_json(page.to_json())
    finally:
        await manager.close()


async def test_cancelled_request_cannot_lose_its_atomic_admission_attempt(tmp_path, monkeypatch):
    import asyncio

    from tests.integration.test_operation_audit import _open
    from tests.integration.test_typed_recall_v6 import _context, _recall_plan

    manager, p, receipt, _ = await _open(tmp_path)
    try:

        async def cancelled(**kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(manager.backend, "_collect_typed_recall_confirmation", cancelled)
        context = _context()
        with pytest.raises(asyncio.CancelledError):
            await manager.execute_typed_recall(
                principal=p,
                context=context,
                plan=_recall_plan(context, idempotency_key="atomic-attempt-loss"),
            )
        page = await _read(manager, p, receipt)
        assert next(c for c in page.coverage if c.family == "typed_attempt").row_count == 1
        db = manager.backend.connection
        await db.execute("DROP TRIGGER typed_recall_attempts_immutable_delete")
        await db.execute("DELETE FROM typed_recall_attempts")
        await db.commit()
        with pytest.raises(MemoryCorruptionError, match="request_attempt"):
            await _read(manager, p, receipt)
    finally:
        await manager.close()
