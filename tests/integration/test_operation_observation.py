"""Actual public rejection -> typed carrier -> independent Host store, no logger oracle."""

import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest

import simple_harness_memory as m
from tests.integration.test_public_recall_rejection import _baseline


@pytest.mark.parametrize(
    "protocol,reason",
    [(5, "typed_recall_protocol_unsupported"), ("5", "typed_recall_protocol_invalid")],
)
async def test_protocol_handoff_preserves_zero_sql_and_host_reopen(
    tmp_path, protocol, reason, monkeypatch
):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db", clock=lambda: 20.0)
    sql = []
    await manager.backend.connection.set_trace_callback(sql.append)
    principal, context, plan = _baseline()

    async def forbidden(**kw):
        raise AssertionError("protocol rejection reached backend")

    monkeypatch.setattr(manager.backend, "execute_typed_recall", forbidden)
    host_path = tmp_path / "host-observations.db"
    host = sqlite3.connect(host_path)
    host.execute("CREATE TABLE attempts (id TEXT PRIMARY KEY, state TEXT, observation TEXT)")
    host.execute("INSERT INTO attempts VALUES (?, ?, NULL)", ("real-host-attempt-1", "started"))
    host.commit()  # Host start is durable before actual SDK call.
    try:
        before = set(asyncio.all_tasks())
        with pytest.raises(m.MemoryValidationError, match=reason) as caught:
            await manager.execute_typed_recall(
                principal=principal,
                context=context,
                plan=plan,
                harness_protocol=protocol,
                observation_context=m.MemoryOperationObservationContext(
                    "host-request-secret", "real-host-attempt-1"
                ),
            )
        error = caught.value
        witness = error.rejection_receipt
        observation = error.operation_observation
        assert type(error) is m.MemoryValidationError and str(error) == reason
        assert witness.reason == reason and observation.reason == reason
        assert observation.persistence_status == "host_persistence_unverified"
        assert observation.invocation_ref_hash == m.operation_audit_ref_hash(
            "invocation", witness.invocation_id
        )
        assert (
            observation.context_hash == context.context_hash
            and observation.plan_hash == plan.plan_hash
        )
        assert sql == [] and set(asyncio.all_tasks()) == before
        encoded = json.dumps(observation.to_json())
        assert "host-request-secret" not in encoded and "real-host-attempt-1" not in encoded
        assert context.query not in encoded
        # Host chooses durability; SDK does not execute a callback or change this row.
        assert host.execute("SELECT state FROM attempts").fetchone() == ("started",)
        host.execute(
            "UPDATE attempts SET state=?, observation=? WHERE id=?",
            ("observed_rejection", encoded, "real-host-attempt-1"),
        )
        host.commit()
        host.close()
        host = sqlite3.connect(host_path)
        state, stored = host.execute("SELECT state, observation FROM attempts").fetchone()
        assert state == "observed_rejection"
        assert m.MemoryOperationObservationV1(**json.loads(stored)) == observation
    finally:
        host.close()
        await manager.close()


@pytest.mark.parametrize("case", ["ownership", "narrowing", "bad_type"])
async def test_actual_other_pre_candidate_witnesses(tmp_path, case):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db", clock=lambda: 20.0)
    p, c, plan = _baseline()
    if case == "ownership":
        p = replace(p, actor_id="unowned")
    elif case == "narrowing":
        plan = replace(plan, context_hash="f" * 64)
    else:
        plan = object()
    statements = []
    await manager.backend.connection.set_trace_callback(statements.append)
    try:
        with pytest.raises((ValueError, TypeError, m.MemoryOwnershipConflict)) as caught:
            await manager.execute_typed_recall(
                principal=p,
                context=c,
                plan=plan,
                observation_context=m.MemoryOperationObservationContext("req", "attempt"),
            )
        observation = caught.value.operation_observation
        assert observation.stage == ("protocol" if case == "bad_type" else case)
        assert statements == []
        assert not observation.candidate_query_started
        assert observation.candidate_query_count == 0
        assert caught.value.rejection_receipt is not observation
    finally:
        await manager.close()


async def test_no_context_keeps_existing_exception_and_no_carrier(tmp_path):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db")
    p, c, plan = _baseline()
    try:
        with pytest.raises(m.MemoryValidationError) as caught:
            await manager.execute_typed_recall(
                principal=p, context=c, plan=plan, harness_protocol=5
            )
        assert caught.value.rejection_receipt.reason == "typed_recall_protocol_unsupported"
        assert not hasattr(caught.value, "operation_observation")
    finally:
        await manager.close()


@pytest.mark.parametrize("error", [RuntimeError("private-payload-fault"), asyncio.CancelledError()])
async def test_unwitnessed_fault_cancel_unchanged_and_no_tasks(tmp_path, monkeypatch, error):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db")
    p, c, plan = _baseline()

    async def failed(**kwargs):
        assert set(kwargs) == {"principal", "context", "plan", "now"}
        raise error

    monkeypatch.setattr(manager.backend, "execute_typed_recall", failed)
    try:
        tasks = set(asyncio.all_tasks())
        with pytest.raises(type(error)) as caught:
            await manager.execute_typed_recall(
                principal=p,
                context=c,
                plan=plan,
                observation_context=m.MemoryOperationObservationContext("req", "attempt"),
            )
        assert caught.value is error
        assert not hasattr(error, "operation_observation")
        assert set(asyncio.all_tasks()) == tasks
    finally:
        await manager.close()


async def test_external_task_cancel_is_not_relabelled(tmp_path, monkeypatch):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db")
    p, c, plan = _baseline()
    entered = asyncio.Event()

    async def waits(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager.backend, "execute_typed_recall", waits)
    try:
        task = asyncio.create_task(
            manager.execute_typed_recall(
                principal=p,
                context=c,
                plan=plan,
                observation_context=m.MemoryOperationObservationContext("req", "attempt"),
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert not hasattr(caught.value, "operation_observation")
        assert task.done() and task.cancelled()
    finally:
        await manager.close()


def test_real_consumer_crash_before_persistence_leaves_started_attempt(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    code = """
import asyncio, os, sqlite3, sys
from pathlib import Path
import simple_harness_memory as m
from tests.integration.test_public_recall_rejection import _baseline
async def run():
    folder=Path(sys.argv[1])
    host=sqlite3.connect(folder/'host.db')
    host.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY, state TEXT)')
    host.execute("INSERT INTO attempts VALUES('attempt-1','started')")
    host.commit()
    manager=await m.build_human_memory_v7(folder/'memory.db')
    p,c,plan=_baseline()
    try:
        await manager.execute_typed_recall(principal=p,context=c,plan=plan,harness_protocol=5,
            observation_context=m.MemoryOperationObservationContext('req-1','attempt-1'))
    except m.MemoryValidationError as error:
        assert error.operation_observation.persistence_status=='host_persistence_unverified'
        os._exit(23)
asyncio.run(run())
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        timeout=20,
    )
    assert process.returncode == 23, process.stderr.decode()
    host = sqlite3.connect(tmp_path / "host.db")
    try:
        assert host.execute("SELECT * FROM attempts").fetchall() == [("attempt-1", "started")]
    finally:
        host.close()


async def test_malformed_optional_witness_does_not_replace_original_error(tmp_path, monkeypatch):
    manager = await m.build_human_memory_v7(tmp_path / "memory.db")
    p, c, plan = _baseline()
    error = ValueError("original-product-error")
    error.rejection_receipt = m.TypedRecallRejectionV1(
        1,
        "actual-invocation",
        "invalid-digest",
        None,
        None,
        "narrowing",
        "existing reason",
        False,
        0,
    )

    async def failed(**kwargs):
        raise error

    monkeypatch.setattr(manager.backend, "execute_typed_recall", failed)
    try:
        with pytest.raises(ValueError) as caught:
            await manager.execute_typed_recall(
                principal=p,
                context=c,
                plan=plan,
                observation_context=m.MemoryOperationObservationContext("req", "attempt"),
            )
        assert caught.value is error and str(error) == "original-product-error"
        assert not hasattr(error, "operation_observation")
        assert error.operation_observation_status == "witness_unverifiable"
    finally:
        await manager.close()
