"""Typed recall lexical gate must match Chinese queries against Chinese memories.

Regression for the 2026-09-07 corpus finding (C01-10): ``\\w`` already matches CJK
ideographs, so a Chinese query collapsed into whole punctuation-delimited clauses
that never occurred verbatim in the payload; every candidate was dropped as
``recall_no_eligible_memory`` although the memory existed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from simple_harness.runtime import SemanticMemoryPayload

from simple_harness_memory import MemoryScope, build_human_memory_v7
from simple_harness_memory.features.lexical import typed_recall_query_terms
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _admitted,
    _Authority,
    _classification_policy,
    _operation,
    _plan,
    _span,
)
from tests.integration.test_typed_recall_v6 import _context, _principal, _recall_plan

_QUERY = "照我已存的待办排序约定，排一下：提交周五到期、复查无日期、取件周三到期。"
_UNRELATED = "今晚吃什么比较好"


def test_query_terms_keep_word_terms_and_add_cjk_bigrams() -> None:
    terms = typed_recall_query_terms("todo_sort_order 待办排序")
    assert "todo_sort_order" in terms
    assert {"待办", "办排", "排序"} <= set(terms)
    assert typed_recall_query_terms("我") == ("我",)
    assert typed_recall_query_terms("") == ()


async def _manager_with_chinese_preference(path):
    envelope, receipt = _admitted()
    span = _span(envelope, receipt)
    authority = _Authority(envelope, receipt, span)
    manager = await build_human_memory_v7(
        path,
        clock=lambda: 20.0,
        evidence_authority=authority,
        memory_action_authority=authority,
        classification_policy=_classification_policy(),
    )
    await manager.ingest_committed_evidence(envelope, receipt)
    operation = replace(
        _operation(span),
        payload=SemanticMemoryPayload(
            "user:self", "todo_sort_order", "按截止时间升序，没日期的放最后", ("待办清单",)
        ),
    )
    await manager.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=_plan(envelope, operation),
    )
    return manager


@pytest.mark.asyncio
async def test_chinese_query_recalls_chinese_semantic_memory(tmp_path):
    manager = await _manager_with_chinese_preference(tmp_path / "cjk.db")
    try:
        context = _context(query=_QUERY)
        execution = await manager.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="cjk-positive"),
        )
        assert [item.public_payload["object_value"] for item in execution.result.items] == [
            "按截止时间升序，没日期的放最后"
        ]
        assert "recall_no_eligible_memory" not in execution.result.reason_codes
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_unrelated_chinese_query_still_returns_nothing(tmp_path):
    manager = await _manager_with_chinese_preference(tmp_path / "cjk-negative.db")
    try:
        context = _context(query=_UNRELATED)
        execution = await manager.execute_typed_recall(
            principal=_principal(),
            context=context,
            plan=_recall_plan(context, idempotency_key="cjk-negative"),
        )
        assert execution.result.items == ()
        assert "recall_no_eligible_memory" in execution.result.reason_codes
    finally:
        await manager.close()
