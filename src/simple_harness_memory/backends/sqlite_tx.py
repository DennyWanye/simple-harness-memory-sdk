"""取消安全的 SQLite 事务原语（0.6.33）。

aiosqlite 把每条语句放进一条串行队列，由后台线程执行；**取消 await 并不会取消已经排队的
语句**——``aiosqlite.core._connection_worker_thread`` 拿到 ``(future, function)`` 之后
无条件执行 ``function()``，只是在 future 已经完成时把结果丢掉。

因此裸写 ``await db.execute("BEGIN IMMEDIATE")`` 有一个真实的健壮性缺口：只要这一行被
``asyncio.wait_for`` / ``asyncio.timeout`` 取消（typed recall 的候选收集段正是这么被
预算掐断的），连接上很可能真的开着一个**没有任何人负责关闭的孤儿事务**——因为 ``BEGIN``
本身在 ``try:`` 之外，``finally`` 的 ROLLBACK 根本不会执行。随后：

1. 同一次召回的 deadline 终态写入（``_persist_typed_recall_timeout``）第一条语句就是
   ``BEGIN IMMEDIATE``，于是抛 ``sqlite3.OperationalError: cannot start a transaction
   within a transaction``，契约要求的 ``TimeoutError("DEADLINE_EXCEEDED")`` 被顶掉，
   终态行也没落库；
2. 更糟的是这个孤儿事务**留在连接上**，之后每一次写入（包括下一次召回的 admit）都继续抛
   同一个 OperationalError——一次超时污染整条连接。

对称地，``COMMIT`` 被取消之后 COMMIT 仍然会执行，此时 ``except`` 分支里裸写的
``await db.execute("ROLLBACK")`` 会抛 ``cannot rollback - no transaction is active``，
把正在展开的异常整个替换掉。

本模块把这两件事各自做成不可丢失的操作：

* :func:`begin_transaction` —— BEGIN 单独排队；取消时先等它落地，再在同一条串行队列上补一条
  ROLLBACK，然后才允许把取消继续往上抛，所以任何取消路径都不会留下开着的事务。
* :func:`rollback_transaction` —— 回滚永远不替换它正在收尾的那个异常（连接上没有事务时是
  合法的 no-op）。

两个函数都必须在调用方持有后端写锁时使用，与被替换掉的裸语句语义完全一致；语句文本逐字未变。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

__all__ = ["BEGIN_STATEMENTS", "begin_transaction", "rollback_transaction"]

BEGIN_STATEMENTS = frozenset(
    {"BEGIN", "BEGIN DEFERRED", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"}
)


async def _begin(db: aiosqlite.Connection, statement: str) -> None:
    await db.execute(statement)


async def _settle_orphan_begin(
    db: aiosqlite.Connection, began: asyncio.Future[Any]
) -> None:
    """等排队中的 BEGIN 落地；真的开了事务就立刻回滚，绝不把它留给下一个调用者。"""

    opened = True
    try:
        await began
    except BaseException:  # noqa: BLE001 - 取消/失败都意味着没有事务留下
        opened = False
    if opened:
        await rollback_transaction(db)


async def begin_transaction(
    db: aiosqlite.Connection, statement: str = "BEGIN IMMEDIATE"
) -> None:
    """开启一个事务，且保证「被取消」不会留下孤儿事务。"""

    if statement not in BEGIN_STATEMENTS:
        raise ValueError("unsupported sqlite transaction statement")
    began: asyncio.Future[Any] = asyncio.ensure_future(_begin(db, statement))
    try:
        await asyncio.shield(began)
    except BaseException:
        # shield 只挡住了「我们这一侧」的取消：worker 线程照样会执行排队中的 BEGIN。
        # 必须先把它收干净，再让异常继续往上走。
        await asyncio.shield(_settle_orphan_begin(db, began))
        raise


async def rollback_transaction(db: aiosqlite.Connection) -> None:
    """回滚（若连接上确有事务）；永远不让回滚自身的错误替换正在展开的异常。"""

    with suppress(Exception):
        await db.execute("ROLLBACK")
