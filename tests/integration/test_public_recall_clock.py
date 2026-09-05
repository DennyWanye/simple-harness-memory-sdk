"""Trusted public construction clock governs recall, paging and reopened access."""

from __future__ import annotations

import pytest
from simple_harness import RecallResultPageRequestV1

from simple_harness_memory import MemoryScope, build_human_memory_v7
from simple_harness_memory.core.errors import MemoryValidationError
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan


@pytest.mark.asyncio
async def test_public_builder_clock_controls_paging_and_reopen_without_request_backdating(tmp_path):
    now = [20.0]
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    path = tmp_path / "public-clock.db"
    kwargs = dict(
        clock=lambda: now[0],
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    manager = await build_human_memory_v7(path, **kwargs)
    try:
        await manager.ingest_committed_evidence(envelope, receipt)
        await manager.apply_memory_mutation_plan(
            principal=_principal(),
            scope=MemoryScope.personal("actor-1"),
            plan=_plan(envelope, _operation(span)),
        )
        context = _context()
        execution = await manager.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="public-clock-recall"),
        )
        assert execution.result.evaluated_at == 20.0
        assert execution.result.items[0].public_payload["object_value"] == "concise"
        request = RecallResultPageRequestV1(
            execution.result.result_id,
            execution.result.result_hash,
            1,
            0,
            1,
            16384,
            20.0,
        )
        page = await manager.page_typed_recall_result(principal=_principal(), request=request)
        assert page.complete and len(page.bindings) == 1
    finally:
        await manager.close()
    reopened = await build_human_memory_v7(path, **kwargs)
    try:
        assert (
            await reopened.page_typed_recall_result(principal=_principal(), request=request) == page
        )
        now[0] = 101.0
        with pytest.raises(MemoryValidationError, match="typed_recall_result_expired"):
            await reopened.page_typed_recall_result(principal=_principal(), request=request)
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_public_builder_omitted_clock_uses_wall_time(tmp_path):
    import time

    before = time.time()
    manager = await build_human_memory_v7(tmp_path / "default-clock.db")
    try:
        await manager.register_principal_owner(_principal(), MemoryScope.personal("actor-1"))
        context = _context(expires_at=before + 100.0)
        execution = await manager.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="wall-clock-recall"),
        )
        assert before <= execution.result.evaluated_at <= time.time()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_public_builder_rejects_non_callable_clock_before_creating_storage(tmp_path):
    path = tmp_path / "invalid-clock.db"
    with pytest.raises(TypeError, match="clock must be callable"):
        await build_human_memory_v7(path, clock=20.0)
    assert not path.exists()
