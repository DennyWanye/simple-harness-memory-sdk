"""0.6.33：候选收集段耗尽预算时的终态契约（Host 401 矩阵 run-16 §10.1 缺陷）。

缺陷：``asyncio.wait_for`` 掐断候选收集时，被取消的那一条 ``await db.execute("BEGIN")``
（``_resolve_suppression_unlocked`` 的读快照）仍然会被 aiosqlite 的 worker 线程执行，
于是连接上留下一个孤儿事务；紧接着的 deadline 终态写入第一条语句就是 ``BEGIN IMMEDIATE``，
抛 ``sqlite3.OperationalError: cannot start a transaction within a transaction``——
契约要求的 ``TimeoutError("DEADLINE_EXCEEDED")`` 被顶掉、终态行没写下，而且孤儿事务留在连接上，
之后每一次写入（含下一次召回的 admit）都继续抛同一个错。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from simple_harness.runtime import RecallBudget

from simple_harness_memory.backends.sqlite_tx import (
    begin_transaction,
    rollback_transaction,
)
from simple_harness_memory.core.errors import TypedRecallDeadlineExceeded
from simple_harness_memory.core.identity import MemoryScope
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _operation,
    _prepared,
)
from tests.integration.test_cognitive_mutation_repository_v5 import (
    _plan as mutation_plan,
)
from tests.integration.test_typed_recall_v6 import (
    _context,
    _principal,
    _recall_plan,
)


async def _backend_with_one_memory(path: Path) -> Any:
    backend, envelope, _receipt, span, _authority = await _prepared(path, now=lambda: 20.0)
    await backend.apply_memory_mutation_plan(
        principal=_principal(),
        scope=MemoryScope.personal("actor-1"),
        plan=mutation_plan(envelope, _operation(span)),
    )
    return backend


async def _terminals(backend: Any) -> list[tuple[Any, ...]]:
    async with backend.connection.execute(
        "SELECT terminal_kind,decision_id,result_id,candidate_query_started,"
        "candidate_query_count,unsupported_capabilities_json,degradation_codes_json "
        "FROM typed_recall_terminals ORDER BY rowid"
    ) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_begin_transaction_never_leaves_an_orphan_transaction_when_cancelled(
    tmp_path: Path,
) -> None:
    """原语层反例：裸 BEGIN 会留下孤儿事务，``begin_transaction`` 不会。"""

    backend = await _backend_with_one_memory(tmp_path / "primitive.db")
    db = backend.connection
    landed = asyncio.Event()

    real_execute = db.execute

    def _slow(statement: str) -> Any:
        async def _run() -> Any:
            cursor = await real_execute(statement)
            landed.set()
            await asyncio.sleep(1.0)
            return cursor

        return _run()

    # 1) 裸写法：BEGIN 已经在连接上落地，await 端被取消，事务没人关。
    db.execute = _slow  # type: ignore[method-assign]
    task = asyncio.create_task(db.execute("BEGIN"))
    await asyncio.wait_for(landed.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    db.execute = real_execute  # type: ignore[method-assign]
    assert db.in_transaction is True
    with pytest.raises(sqlite3.OperationalError, match="within a transaction"):
        await db.execute("BEGIN IMMEDIATE")
    await rollback_transaction(db)
    assert db.in_transaction is False

    # 2) 修好的原语：同一个时序下取消，连接上一定没有事务。
    landed.clear()
    db.execute = _slow  # type: ignore[method-assign]
    guarded = asyncio.create_task(begin_transaction(db, "BEGIN"))
    await asyncio.wait_for(landed.wait(), timeout=2.0)
    guarded.cancel()
    with pytest.raises(asyncio.CancelledError):
        await guarded
    db.execute = real_execute  # type: ignore[method-assign]
    assert db.in_transaction is False
    await begin_transaction(db)
    await db.execute("COMMIT")
    await backend.close()


@pytest.mark.asyncio
async def test_deadline_inside_candidate_collection_writes_one_terminal_and_times_out(
    tmp_path: Path,
) -> None:
    """确定性构造：预算恰好耗尽在候选收集段那条读快照 ``BEGIN`` 上。"""

    backend = await _backend_with_one_memory(tmp_path / "collection-deadline.db")
    db = backend.connection
    real_execute = db.execute
    state = {"armed": False, "hit": False}

    def _execute(statement: str, *args: Any, **kwargs: Any) -> Any:
        if not (statement == "BEGIN" and state["armed"] and not state["hit"]):
            return real_execute(statement, *args, **kwargs)
        state["hit"] = True

        async def _run() -> Any:
            # BEGIN 已经在连接上落地；把 await 端拖过 deadline，
            # 让 wait_for 恰好在这里取消收集协程。
            cursor = await real_execute(statement, *args, **kwargs)
            await asyncio.sleep(3.0)
            return cursor

        return _run()

    original_collect = backend._collect_typed_recall_candidates

    async def armed_collect(**kwargs: Any) -> Any:
        state["armed"] = True
        try:
            return await original_collect(**kwargs)
        finally:
            state["armed"] = False

    db.execute = _execute  # type: ignore[method-assign]
    backend._collect_typed_recall_candidates = armed_collect  # type: ignore[assignment]

    context = _context(budget=RecallBudget(8, 16_384, 2_048, 40))
    plan = _recall_plan(context, idempotency_key="idem-collection-deadline")
    with pytest.raises(TimeoutError) as raised:
        await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=plan
        )
    assert state["hit"] is True
    assert str(raised.value) == "DEADLINE_EXCEEDED"
    assert isinstance(raised.value, TypedRecallDeadlineExceeded)
    assert raised.value.stage == "collect_candidates"
    assert not isinstance(raised.value, sqlite3.OperationalError)

    db.execute = real_execute  # type: ignore[method-assign]
    backend._collect_typed_recall_candidates = original_collect  # type: ignore[method-assign]

    # (2) 恰好一条终态行，形状与入账阶段到期时逐字相同。
    assert await _terminals(backend) == [("deadline_exceeded", None, None, 0, 0, "[]", "[]")]
    # (3) 连接上没有留下任何事务。
    assert db.in_transaction is False

    # (3) 同 key 同 body 重放拿回同一个终态；连接没有被污染，别的 key 照常能召回。
    with pytest.raises(TimeoutError, match="DEADLINE_EXCEEDED"):
        await backend.execute_typed_recall(
            principal=_principal(), context=context, plan=plan
        )
    assert await _terminals(backend) == [("deadline_exceeded", None, None, 0, 0, "[]", "[]")]
    healthy_context = _context()
    healthy = await backend.execute_typed_recall(
        principal=_principal(),
        context=healthy_context,
        plan=_recall_plan(healthy_context, idempotency_key="idem-after-collection-deadline"),
    )
    assert healthy.result is not None
    assert db.in_transaction is False
    await backend.close()


@pytest.mark.asyncio
async def test_one_millisecond_budget_soak_never_escapes_operational_error(
    tmp_path: Path,
) -> None:
    """50 次 1 毫秒预算：只允许 ``DEADLINE_EXCEEDED``，且每个已入账请求恰好一条终态行。"""

    backend = await _backend_with_one_memory(tmp_path / "soak.db")
    iterations = 50
    for index in range(iterations):
        context = _context(budget=RecallBudget(8, 16_384, 2_048, 1))
        plan = _recall_plan(context, idempotency_key=f"idem-soak-{index}")
        try:
            await backend.execute_typed_recall(
                principal=_principal(), context=context, plan=plan
            )
        except TimeoutError as timeout:
            assert str(timeout) == "DEADLINE_EXCEEDED"
        except BaseException as escaped:  # noqa: BLE001 - 任何别的异常都是回归
            raise AssertionError(
                f"1ms budget escaped as {type(escaped).__name__}: {escaped}"
            ) from escaped
        assert backend.connection.in_transaction is False, index

    async with backend.connection.execute(
        "SELECT COUNT(*) FROM typed_recall_requests"
    ) as cursor:
        requests = int((await cursor.fetchone())[0])  # type: ignore[index]
    async with backend.connection.execute(
        "SELECT terminal_kind,COUNT(*) FROM typed_recall_terminals GROUP BY terminal_kind"
    ) as cursor:
        terminals = {str(row[0]): int(row[1]) for row in await cursor.fetchall()}
    assert requests >= 1
    assert terminals == {"deadline_exceeded": requests}

    # 连接没有被任何一次超时污染：正常预算仍然可用。
    healthy_context = _context()
    healthy = await backend.execute_typed_recall(
        principal=_principal(),
        context=healthy_context,
        plan=_recall_plan(healthy_context, idempotency_key="idem-soak-healthy"),
    )
    assert healthy.result is not None
    await backend.close()
