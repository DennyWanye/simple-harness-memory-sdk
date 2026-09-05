"""Durable analysis materialization must use the same origin gate as caller mutation."""

from dataclasses import replace

import pytest
from simple_harness.contracts import fingerprint_json

import simple_harness_memory as m
from tests.integration.test_cognitive_mutation_repository_v5 import _operation
from tests.integration.test_duplicate_source_forget import NS, TEXT, Origins
from tests.integration.test_memory_061_core import (
    _build_pipeline,
    _evidence,
    _HostEvidenceAuthority,
    _HostExecutor,
    _ingest,
    _placeholder_principal,
    _rows,
    _span,
)


def evidence(index):
    env, receipt = _evidence(index, text=TEXT, run_id=f"run-{index}")
    payload = {**env.sanitized_payload, "text": TEXT, "delivery_key": f"delivery-{index}"}
    digest = fingerprint_json(payload)
    env = replace(env, sanitized_payload=payload, sanitized_hash=digest,
                  source_hash=digest, evidence_refs=())
    receipt = replace(receipt, envelope_hash=env.envelope_hash, sanitized_hash=digest,
                      source_hash=digest, evidence_refs=())
    return env, receipt


class Executor(_HostExecutor):
    """Reads the fixture Host's admitted source store, like production authority.

It does not use a subject-only Memory read as a grant for a newly asserted source.
"""
    def __init__(self, authority):
        super().__init__(({"evidence_id": "evidence-1"},))
        self.authority = authority

    async def _operation(self, spec, ordinal):
        env, receipt = self.authority.admitted[spec["evidence_id"]]
        span = _span(env, receipt, f"span-{ordinal}")
        return _operation(span)


@pytest.mark.asyncio
@pytest.mark.parametrize("proof,expected_heads", [("atomic", 2), ("legacy_before_only", 1)])
async def test_real_background_apply_distinguishes_cognitive_write_from_applied(
    tmp_path, proof, expected_heads,
):
    authority, origins = _HostEvidenceAuthority(), Origins()
    executor = Executor(authority)
    manager, runner = await _build_pipeline(
        tmp_path / "analysis.db", executor, evidence_authority=authority,
        history_source_authority=origins, now=lambda: 20.0,
    )
    origins.backend = manager.backend
    try:
        first = evidence(1)
        origins.register(m.HistoryEvidenceBinding(*first), 1)
        await _ingest(manager, first, authority)
        assert await runner.run_once() is m.WorkerRunOutcome.APPLIED
        heads = await _rows(manager, "SELECT memory_id FROM cognitive_memory_heads")
        assert len(heads) == 1
        mid = heads[0][0]
        origins.cuts["job-forget"] = m.HistoryForgetCutReceipt(
            NS, 1, "job-forget", m.SuppressionScopeKind.MEMORY, mid,
            "action-s1", "d" * 64,
        )
        await manager.suppress(
            principal=_placeholder_principal(), request=m.SuppressionRequest(
                "job-forget", "actor-1", m.SuppressionScopeKind.MEMORY,
                mid, "user_forget", 20.0,
            ),
        )
        second = evidence(2)
        origins.register(m.HistoryEvidenceBinding(*second), 2, proof)
        executor.ops = ({"evidence_id": "evidence-2"},)
        await _ingest(manager, second, authority)
        assert await runner.run_once() is m.WorkerRunOutcome.APPLIED
        # Applied is a workflow state; independently assert actual cognitive effect.
        heads = await _rows(manager, "SELECT memory_id FROM cognitive_memory_heads")
        assert len(heads) == expected_heads
        new_support = await _rows(manager, "SELECT memory_id FROM cognitive_evidence_spans "
                                 "WHERE evidence_id='evidence-2'")
        assert len(new_support) == expected_heads - 1
        if new_support:
            assert new_support[0][0] != mid
        assert await _rows(manager, "SELECT state FROM analysis_batches ORDER BY rowid") == [
            ("applied",), ("applied",),
        ]
    finally:
        await manager.close()
