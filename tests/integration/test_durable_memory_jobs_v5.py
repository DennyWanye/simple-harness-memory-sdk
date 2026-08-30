from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest
from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime import (
    AnalysisBudget,
    DeliveryRecipient,
    DisclosureContext,
    DisclosureGeneration,
    DisclosurePurpose,
    DisclosureReasonCode,
    DisclosureSource,
    DisclosureTrust,
    EvidenceReasonCode,
    EvidenceRef,
    EvidenceSourceKind,
    IntendedAudience,
    LongTermMemoryType,
    MemoryAnalysisRequest,
    MemoryAnalysisResult,
    MemoryMutationKind,
    MemoryMutationOperation,
    MemoryMutationPlan,
    SanitizedEvidenceEnvelope,
    SanitizedEvidenceReceipt,
)

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.jobs import (
    AnalysisResultCommitOutcome,
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)

# Test-only fixture policy. These values are intentionally not production defaults.
TEST_WORKER_CONFIG = MemoryJobWorkerConfig(
    batch_size=2,
    idle_wait_seconds=0.01,
    max_batch_wait_seconds=5.0,
    lease_seconds=10.0,
    max_attempts=2,
    retry_delays_seconds=(3.0,),
    max_result_bytes=64 * 1024,
    analysis_budget=AnalysisBudget(4096, 1024, 30_000, 1_000_000),
    prompt_version="test-prompt-v1",
    result_schema_version="test-result-v1",
    policy_version="test-policy-v1",
    validator_version="test-validator-v1",
    provider_id="test-provider",
    model_id="test-model",
    model_config_hash="a" * 64,
)


def _hash(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _disclosure() -> DisclosureContext:
    return DisclosureContext(
        "run-1",
        "actor-1",
        DeliveryRecipient.USER_SELF,
        "actor-1",
        IntendedAudience.USER_SELF,
        DisclosurePurpose.PERSONALIZATION,
        DisclosureSource.AUTHENTICATED_HOST,
        DisclosureTrust.TRUSTED_AUTHORITY,
        DisclosureGeneration.CURRENT,
        "host-authority",
        (DisclosureReasonCode.MINIMUM_NECESSARY,),
    )


def _authority(index: int) -> tuple[SanitizedEvidenceEnvelope, SanitizedEvidenceReceipt]:
    payload: dict[str, JsonValue] = {"public_text": f"preference-{index}"}
    envelope = SanitizedEvidenceEnvelope(
        f"evidence-{index}",
        "run-1",
        "actor-1",
        EvidenceSourceKind.USER_MESSAGE,
        f"turn-{index}/user",
        f"{index}" * 64,
        payload,
        _hash(payload),
        "credential-filter/v1",
        (),
        _disclosure(),
        (EvidenceRef(f"source-event-{index}", f"{index + 2}" * 64, 1),),
    )
    receipt = SanitizedEvidenceReceipt(
        f"admission-{index}",
        envelope.run_id,
        envelope.subject,
        envelope.evidence_id,
        envelope.envelope_hash,
        envelope.source_hash,
        envelope.sanitized_hash,
        envelope.filter_policy_version,
        True,
        (EvidenceReasonCode.SANITIZED_AND_ACCEPTED,),
        envelope.disclosure_context,
        envelope.evidence_refs,
        10.0,
    )
    return envelope, receipt


class _Executor:
    def __init__(
        self,
        backend: SQLiteHumanMemoryBackend,
        *,
        no_mutation: bool = False,
        error: Exception | None = None,
        private: bool = False,
        base_revision: int = 1,
        structured_override: dict[str, JsonValue] | None = None,
    ) -> None:
        self.backend = backend
        self.no_mutation = no_mutation
        self.error = error
        self.private = private
        self.base_revision = base_revision
        self.structured_override = structured_override
        self.calls = 0

    async def analyze_memory(self, request: MemoryAnalysisRequest) -> MemoryAnalysisResult:
        self.calls += 1
        assert not self.backend.connection.in_transaction
        if self.error is not None:
            raise self.error
        structured: dict[str, JsonValue]
        if self.structured_override is not None:
            structured = self.structured_override
        elif self.private:
            structured = {
                "reasoning": "hidden-chain-of-thought-canary"
            }
        elif self.no_mutation:
            structured = {"outcome": "no_mutation", "operations": []}
        else:
            operation = MemoryMutationOperation(
                "operation-1",
                MemoryMutationKind.CREATE,
                LongTermMemoryType.SEMANTIC,
                None,
                "User prefers concise answers.",
                request.ordered_evidence_refs,
                "explicit_user_preference",
            )
            structured = MemoryMutationPlan(
                "plan-1",
                request.run_id,
                request.subject,
                self.base_revision,
                (operation,),
                request.disclosure_context,
                request.ordered_evidence_refs,
                request.idempotency_key,
            ).to_json()
        return MemoryAnalysisResult(
            request.job_id,
            request.run_id,
            request.request_hash,
            f"provider-response-{self.calls}",
            structured,
            100,
            50,
            7,
            25,
        )


async def _ingest(backend: SQLiteHumanMemoryBackend, count: int = 2) -> None:
    for index in range(1, count + 1):
        await backend.ingest_committed_evidence(*_authority(index))


@pytest.mark.asyncio
async def test_batch_analysis_runs_outside_transaction_and_cas_applies_once(
    tmp_path: Path,
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "jobs.db", now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    before = await backend.export_ingested_evidence("evidence-1")
    executor = _Executor(backend)
    runner = DurableMemoryJobRunner(
        backend, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )

    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    assert executor.calls == 1
    assert await backend.export_ingested_evidence("evidence-1") == before
    for table, expected in (
        ("analysis_batches", 1),
        ("analysis_batch_members", 2),
        ("accepted_analysis_plans", 1),
        ("llm_invocations", 1),
    ):
        async with backend.connection.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
            row = await cursor.fetchone()
        assert row is not None and int(row[0]) == expected
    async with backend.connection.execute(
        "SELECT state FROM jobs ORDER BY job_id"
    ) as cursor:
        assert [str(row[0]) for row in await cursor.fetchall()] == ["applied", "applied"]
    async with backend.connection.execute("SELECT revision FROM analysis_apply_heads") as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 2
    await backend.close()


@pytest.mark.asyncio
async def test_no_mutation_is_accepted_and_audited_without_decisions(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "no-mutation.db", now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend,
        _Executor(backend, no_mutation=True),
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    async with backend.connection.execute("SELECT COUNT(*) FROM decision_records") as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 0
    await backend.close()


@pytest.mark.asyncio
async def test_result_replay_divergence_and_stale_lease_are_audited_not_applied(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend = SQLiteHumanMemoryBackend(tmp_path / "result-cas.db", now=lambda: clock[0])
    await backend.initialize()
    await _ingest(backend)
    claim = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-1")
    assert claim is not None
    executor = _Executor(backend, no_mutation=True)
    result = await executor.analyze_memory(claim.request)
    first = await backend.commit_analysis_result(claim, result)
    replay = await backend.commit_analysis_result(claim, result)
    assert first.outcome is AnalysisResultCommitOutcome.COMMITTED
    assert replay.outcome is AnalysisResultCommitOutcome.REPLAYED
    divergent = MemoryAnalysisResult(
        result.job_id,
        result.run_id,
        result.request_hash,
        "provider-response-divergent",
        {"outcome": "no_mutation", "operations": [], "extra": "different"},
        100,
        50,
        7,
        25,
    )
    divergence = await backend.commit_analysis_result(claim, divergent)
    assert divergence.outcome is AnalysisResultCommitOutcome.DIVERGENT
    assert divergence.canonical_result == result

    clock[0] = 31.0
    reclaimed = await backend.claim_analysis_batch(TEST_WORKER_CONFIG, "worker-2")
    assert reclaimed is not None and reclaimed.lease_token != claim.lease_token
    stale = await backend.commit_analysis_result(claim, result)
    assert stale.outcome is AnalysisResultCommitOutcome.STALE_LEASE
    await backend.close()


@pytest.mark.asyncio
async def test_executor_failure_retries_then_dead_letters_with_explicit_schedule(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend = SQLiteHumanMemoryBackend(tmp_path / "retry.db", now=lambda: clock[0])
    await backend.initialize()
    await _ingest(backend)
    executor = _Executor(backend, error=TimeoutError())
    runner = DurableMemoryJobRunner(
        backend, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    assert await runner.run_once() is WorkerRunOutcome.RETRY_SCHEDULED
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    clock[0] = 23.0
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    assert executor.calls == 2
    async with backend.connection.execute("SELECT DISTINCT state FROM jobs") as cursor:
        assert [str(row[0]) for row in await cursor.fetchall()] == ["dead_letter"]
    await backend.close()


@pytest.mark.asyncio
async def test_private_result_is_dead_lettered_without_body_in_db_wal_or_logs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private-result.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    runner = DurableMemoryJobRunner(
        backend,
        _Executor(backend, private=True),
        TEST_WORKER_CONFIG,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    await backend.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
    durable = b"".join(
        item.read_bytes()
        for item in (path, path.with_name(path.name + "-wal"))
        if item.exists()
    )
    assert b"hidden-chain-of-thought-canary" not in durable
    async with backend.connection.execute(
        "SELECT result_json FROM analysis_batches"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] is None
    await backend.close()


@pytest.mark.asyncio
async def test_crash_after_result_commit_reopens_without_second_provider_call(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reopen.db"
    clock = [20.0]
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == "job.result.after_commit" and not fired:
            fired = True
            raise RuntimeError("crash after durable result")

    first = SQLiteHumanMemoryBackend(path, now=lambda: clock[0], fault_injector=fault)
    await first.initialize()
    await _ingest(first)
    executor = _Executor(first, no_mutation=True)
    runner = DurableMemoryJobRunner(
        first, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    with pytest.raises(RuntimeError, match="crash after durable result"):
        await runner.run_once()
    await first.close()

    clock[0] = 31.0
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: clock[0])
    await reopened.initialize()
    replay_executor = _Executor(reopened, no_mutation=True)
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is WorkerRunOutcome.APPLIED
    assert executor.calls == 1
    assert replay_executor.calls == 0
    await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault_point", "advance_clock", "expected_replay_calls", "expected_outcome"),
    (
        ("job.claim.after_commit", True, 1, WorkerRunOutcome.APPLIED),
        ("job.apply.after_commit", True, 0, WorkerRunOutcome.APPLIED),
        ("job.finalize.after_commit", False, 0, WorkerRunOutcome.IDLE),
    ),
)
async def test_commit_boundary_fault_matrix_is_reclaim_safe(
    tmp_path: Path,
    fault_point: str,
    advance_clock: bool,
    expected_replay_calls: int,
    expected_outcome: WorkerRunOutcome,
) -> None:
    path = tmp_path / f"fault-{fault_point}.db"
    clock = [20.0]
    fired = False

    def fault(point: str) -> None:
        nonlocal fired
        if point == fault_point and not fired:
            fired = True
            raise RuntimeError(f"fault at {point}")

    first = SQLiteHumanMemoryBackend(path, now=lambda: clock[0], fault_injector=fault)
    await first.initialize()
    await _ingest(first)
    first_executor = _Executor(first, no_mutation=True)
    first_runner = DurableMemoryJobRunner(
        first, first_executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    with pytest.raises(RuntimeError, match="fault at"):
        await first_runner.run_once()
    await first.close()

    if advance_clock:
        clock[0] = 31.0
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: clock[0])
    await reopened.initialize()
    replay_executor = _Executor(reopened, no_mutation=True)
    replay_runner = DurableMemoryJobRunner(
        reopened,
        replay_executor,
        TEST_WORKER_CONFIG,
        "worker-2",
        lambda: clock[0],
    )
    assert await replay_runner.run_once() is expected_outcome
    assert replay_executor.calls == expected_replay_calls
    async with reopened.connection.execute(
        "SELECT COUNT(*) FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_partial_batch_waits_for_explicit_max_wait_and_shutdown_is_immediate(
    tmp_path: Path,
) -> None:
    clock = [20.0]
    backend = SQLiteHumanMemoryBackend(tmp_path / "max-wait.db", now=lambda: clock[0])
    await backend.initialize()
    await _ingest(backend, count=1)
    executor = _Executor(backend, no_mutation=True)
    runner = DurableMemoryJobRunner(
        backend, executor, TEST_WORKER_CONFIG, "worker-1", lambda: clock[0]
    )
    assert await runner.run_once() is WorkerRunOutcome.IDLE
    clock[0] = 25.0
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    stop = asyncio.Event()
    stop.set()
    await runner.run_until_stopped(stop)
    assert executor.calls == 1
    await backend.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executor_kwargs",
    (
        {"base_revision": 99},
        {"structured_override": {"outcome": "refusal", "operations": []}},
    ),
)
async def test_revision_drift_and_safe_refusal_are_rejected_and_audited(
    tmp_path: Path, executor_kwargs: dict[str, object]
) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "rejected.db", now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    executor = _Executor(backend, **executor_kwargs)  # type: ignore[arg-type]
    runner = DurableMemoryJobRunner(
        backend, executor, TEST_WORKER_CONFIG, "worker-1", lambda: 20.0
    )
    assert await runner.run_once() is WorkerRunOutcome.APPLIED
    async with backend.connection.execute(
        "SELECT host_receipt_json FROM llm_invocations"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    receipt = json.loads(str(row[0]))
    assert receipt["validation_status"] == "rejected"
    assert receipt["committed_revision"] is None
    async with backend.connection.execute(
        "SELECT COUNT(*) FROM accepted_analysis_plans"
    ) as cursor:
        count = await cursor.fetchone()
    assert count is not None and int(count[0]) == 0
    async with backend.connection.execute(
        "SELECT revision FROM analysis_apply_heads"
    ) as cursor:
        head = await cursor.fetchone()
    assert head is not None and int(head[0]) == 1
    async with backend.connection.execute(
        "SELECT outcome FROM decision_records"
    ) as cursor:
        decision = await cursor.fetchone()
    assert decision is not None and str(decision[0]) == "rejected"
    await backend.close()


@pytest.mark.asyncio
async def test_oversize_result_is_rejected_before_durable_body_write(tmp_path: Path) -> None:
    backend = SQLiteHumanMemoryBackend(tmp_path / "oversize.db", now=lambda: 20.0)
    await backend.initialize()
    await _ingest(backend)
    config = replace(TEST_WORKER_CONFIG, max_result_bytes=100)
    runner = DurableMemoryJobRunner(
        backend,
        _Executor(backend, no_mutation=True),
        config,
        "worker-1",
        lambda: 20.0,
    )
    assert await runner.run_once() is WorkerRunOutcome.DEAD_LETTER
    async with backend.connection.execute(
        "SELECT result_json,state FROM analysis_batches"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None and row[0] is None and str(row[1]) == "failed"
    await backend.close()


def test_worker_policy_requires_every_value_and_has_no_product_defaults() -> None:
    parameters = inspect.signature(MemoryJobWorkerConfig).parameters.values()
    assert parameters
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)
    with pytest.raises(TypeError):
        MemoryJobWorkerConfig()  # type: ignore[call-arg]
