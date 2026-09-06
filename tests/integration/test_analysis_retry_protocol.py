"""Failed retries preserve complete sent input; fresh jobs keep new config."""
import json
from contextlib import suppress
from dataclasses import replace

import pytest

from simple_harness_memory.core.errors import MemoryCorruptionError
from simple_harness_memory.core.jobs import DurableMemoryJobRunner, WorkerRunOutcome
from .test_durable_memory_jobs_v5 import TEST_WORKER_CONFIG, _Executor, _authority_backend, _ingest_indexes


def semantic_input(request):
    return {key: value for key, value in request.to_json().items()
            if key not in {"job_id", "attempt", "idempotency_key"}}


@pytest.mark.asyncio
async def test_retry_keeps_full_input_and_original_cohort_new_job_uses_new_config(tmp_path):
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(tmp_path / "retry.db", executor, now=lambda: clock[0])
    await backend.initialize()
    old = replace(TEST_WORKER_CONFIG, prompt_version="prompt/v3", result_schema_version="result/v3", policy_version="policy/v3")
    new = replace(old, batch_size=1, prompt_version="prompt/v4", result_schema_version="result/v4", policy_version="policy/v4",
                  analysis_budget=replace(old.analysis_budget, max_input_tokens=5000, max_output_tokens=1500),
                  provider_id="new-provider", model_id="new-model", model_config_hash="b" * 64)
    try:
        await _ingest_indexes(backend, (1, 2))
        first = await backend.claim_analysis_batch(old, "old-worker")
        assert first is not None and len(first.job_ids) == 2
        assert await backend.fail_analysis_batch(first, "analysis_executor_failed", old) is WorkerRunOutcome.RETRY_SCHEDULED
        async with backend.connection.execute("SELECT request_json,request_hash FROM analysis_batches") as cursor:
            original = tuple(await cursor.fetchone())
        clock[0] = 24.0
        await _ingest_indexes(backend, (3,))
        retry = await backend.claim_analysis_batch(new, "new-worker")
        assert retry is not None and retry.job_ids == first.job_ids
        assert retry.request.request_hash != first.request.request_hash
        assert retry.request.attempt == first.request.attempt + 1
        assert semantic_input(retry.request) == semantic_input(first.request)
        async with backend.connection.execute("SELECT request_json,request_hash FROM analysis_batches WHERE batch_id=?", (first.batch_id,)) as cursor:
            assert tuple(await cursor.fetchone()) == original
        # Reclaim the ordinary active retry and apply through unchanged delivery
        # verification. Then the later, independent job receives the new budget.
        clock[0] = 40.0
        runner = DurableMemoryJobRunner(backend, executor, executor, new, "worker", lambda: clock[0])
        assert await runner.run_once() is WorkerRunOutcome.APPLIED
        fresh = await backend.claim_analysis_batch(new, "worker")
        assert fresh is not None and len(fresh.job_ids) == 1
        assert [ref.evidence_id for ref in fresh.request.ordered_evidence_refs] == ["evidence-3"]
        assert fresh.request.prompt_version == "prompt/v4"
        assert fresh.request.budget == new.analysis_budget
        assert fresh.request.provider_id == new.provider_id
        assert semantic_input(fresh.request) != semantic_input(first.request)
    finally:
        await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["budget", "member"])
async def test_retry_rejects_changed_persisted_input_before_new_claim(tmp_path, tamper):
    clock = [20.0]
    executor = _Executor(None, no_mutation=True)
    backend = _authority_backend(tmp_path / "tamper.db", executor, now=lambda: clock[0])
    await backend.initialize()
    try:
        await _ingest_indexes(backend, (1, 2))
        first = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker")
        assert await backend.fail_analysis_batch(first, "analysis_executor_failed", TEST_WORKER_CONFIG) is WorkerRunOutcome.RETRY_SCHEDULED
        if tamper == "budget":
            altered = first.request.to_json()
            altered["budget"]["max_input_tokens"] += 1
            await backend.connection.execute("UPDATE analysis_batches SET request_json=? WHERE batch_id=?",
                (json.dumps(altered), first.batch_id))
        else:
            await backend.connection.execute("UPDATE analysis_batch_members SET content_hash=? WHERE batch_id=? AND ordinal=1",
                ("0" * 64, first.batch_id))
        await backend.connection.commit()
        clock[0] = 24.0
        with pytest.raises(MemoryCorruptionError, match="analysis retry"):
            await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "retry-worker")
        async with backend.connection.execute("SELECT COUNT(*) FROM analysis_batches") as cursor:
            assert tuple(await cursor.fetchone()) == (1,)
        assert executor.provider_calls == 0
    finally:
        # Deliberately corrupted disposable fixtures may also fail rooted close.
        with suppress(MemoryCorruptionError):
            await backend.close()
