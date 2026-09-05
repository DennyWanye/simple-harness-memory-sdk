"""Negative source-only database faults. Never a public consumer or expected result generator."""

import hashlib
import json
from dataclasses import replace

import pytest
from simple_harness.contracts import canonical_json

from simple_harness_memory.core.errors import MemoryCorruptionError
from tests.integration.test_short_history_visibility import PRINCIPAL, _binding, _check, _fixture


async def _rewrite_audit(backend, audit_id, mutate):
    # Explicit post-initialize corruption: the sealed inputs and production triggers stay unchanged.
    async with backend.connection.execute(
        "SELECT audit_json FROM short_horizon_audit WHERE audit_id=?", (audit_id,)
    ) as cur:
        payload = json.loads((await cur.fetchone())[0])
    mutate(payload)
    raw = canonical_json(payload)
    await backend.connection.execute("DROP TRIGGER short_horizon_audit_immutable_update")
    await backend.connection.execute(
        "UPDATE short_horizon_audit SET audit_json=?,audit_hash=?,degradation_code=? "
        "WHERE audit_id=?",
        (raw, hashlib.sha256(raw.encode()).hexdigest(), payload["degradation_code"], audit_id),
    )
    await backend.connection.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["duplicate", "failed", "cancelled", "incomplete", "deadline", "wrong_attempt"]
)
async def test_residual_complete_selection_is_not_success(tmp_path, fault):
    close_corruption = "audit lineage differs" if fault == "wrong_attempt" else None
    async with _fixture(tmp_path / "history.db", close_corruption=close_corruption) as (
        manager,
        result,
        *_,
    ):
        binding = _binding(result)

        def mutate(audit):
            if fault == "duplicate":
                audit["details"]["selected"] *= 2
            elif fault == "deadline":
                audit["degradation_code"] = "DEADLINE_EXCEEDED"
            elif fault == "wrong_attempt":
                audit["details"]["attempt_audit_id"] = result.audit_id
            else:
                audit["details"]["gate_outcome"] = fault

        await _rewrite_audit(manager.backend, result.audit_id, mutate)
        if fault == "duplicate":
            with pytest.raises(MemoryCorruptionError, match="selection duplicate"):
                await _check(manager, binding)
        else:
            item = (await _check(manager, binding)).items[0]
            assert not item.visible and item.reason == "history_binding_mismatch"


@pytest.mark.asyncio
async def test_started_projection_and_linked_terminal_ids_are_not_results(tmp_path):
    async with _fixture(tmp_path / "history.db") as (manager, result, *_):
        backend = manager.backend
        async with backend.connection.execute(
            "SELECT audit_json FROM short_horizon_audit WHERE audit_id=?", (result.audit_id,)
        ) as cur:
            payload = json.loads((await cur.fetchone())[0])
        attempt_id = payload["details"]["attempt_audit_id"]
        async with backend.connection.execute(
            "SELECT audit_id FROM short_horizon_audit WHERE event_kind='projection_rebuilt' LIMIT 1"
        ) as cur:
            projection_id = (await cur.fetchone())[0]
        binding = _binding(result)
        for audit_id in (attempt_id, projection_id):
            assert not (await _check(manager, replace(binding, audit_id=audit_id))).items[0].visible
        terminal_id = await backend._record_short_horizon_recall_terminal(
            principal=PRINCIPAL,
            attempt_audit_id=attempt_id,
            disclosure_context_hash=payload["disclosure_context_hash"],
            query_hash=payload["query_hash"],
            deadline_ms=2000,
            created_at=payload["created_at"],
        )
        for audit_id in (result.audit_id, terminal_id):
            assert not (await _check(manager, replace(binding, audit_id=audit_id))).items[0].visible


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["missing_link", "wrong_link", "empty_refs", "changed_text", "classification"]
)
async def test_current_canonical_source_faults_fail_closed_without_global_policy(tmp_path, fault):
    async with _fixture(tmp_path / "history.db", close_corruption="short horizon chunk") as (
        manager,
        result,
        *_,
    ):
        backend = manager.backend
        binding = _binding(result)
        if fault == "missing_link":
            sql = "DELETE FROM short_horizon_chunk_evidence WHERE chunk_id=?"
        elif fault == "wrong_link":
            sql = "UPDATE short_horizon_chunk_evidence SET envelope_hash='wrong' WHERE chunk_id=?"
        elif fault == "empty_refs":
            sql = (
                "UPDATE short_horizon_chunks SET classification_authority_refs_json='[]' "
                "WHERE chunk_id=?"
            )
        elif fault == "changed_text":
            sql = "UPDATE short_horizon_chunks SET public_text='changed' WHERE chunk_id=?"
        else:
            sql = (
                "UPDATE short_horizon_chunks SET effective_privacy_class='public' WHERE chunk_id=?"
            )
        await backend.connection.execute(sql, (binding.chunk_ref,))
        await backend.connection.commit()
        item = (await _check(manager, binding)).items[0]
        assert not item.visible and item.reason == "history_source_stale"
