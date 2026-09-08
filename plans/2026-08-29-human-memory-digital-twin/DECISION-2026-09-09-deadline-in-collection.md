# 裁决：候选收集段耗尽预算时的终态契约（0.6.33）

> 2026-09-09。分支 `m0633`（基线 main `eec9760`，0.6.32）。
> 缺陷来源：Host 401 矩阵第四轮 `simple_harness/plans/2026-09-07-corpus-c01-local/TYPED-RECALL-401-RUN-10.md`
> §4.4 附带发现 / §10 后继第 1 条（"偶发候选侧缺陷"，12 次采样命中 5 次）。
> 用户授权：技术取舍由执行者作为独立裁决人从契约文本裁定、记录并实施，不回问。

## 0. 一句话结论

不是竞态**判据**的问题，是一条**取消安全**的问题：`await db.execute("BEGIN")` 被
`asyncio.wait_for` 取消之后，语句**仍然会在连接上执行**，而它写在 `try:` 之外，于是
`finally` 的 ROLLBACK 根本轮不到——连接上留下一个孤儿事务。修复放在开事务这一个原语上
（`backends/sqlite_tx.py`），召回路径上所有 `BEGIN` 站点一律改走它，语句文本逐字不变。

## 1. 现象与复现

Host 报的是：1 毫秒预算耗尽在候选收集阶段时，抛
`sqlite3.OperationalError: cannot start a transaction within a transaction`
而不是契约要求的 `TimeoutError("DEADLINE_EXCEEDED")`，且那一次不落 deadline 终态行。

在 0.6.32 源上用 60 次 `deadline_ms=1` 的召回复现，命中 7 次，堆栈逐字如下（节选）：

```
  sqlite_v5.py:4151 in execute_typed_recall
    candidates = await asyncio.wait_for(self._collect_typed_recall_candidates(...))
  sqlite_v5.py:5702 in _collect_typed_recall_candidates
    await self._resolve_suppression_unlocked(...)
  sqlite_v5.py:1710 in _resolve_suppression_unlocked
    await self._db.execute("BEGIN")            <-- 在这里被取消
  asyncio.exceptions.CancelledError

  ... 直接导致 ...
  sqlite_v5.py:4163 in execute_typed_recall
    await self._persist_typed_recall_timeout(...)
  sqlite_v5.py:6632 in _persist_typed_recall_timeout
    await self._db.execute("BEGIN IMMEDIATE")
  sqlite3.OperationalError: cannot start a transaction within a transaction
```

**比 Host 观察到的更严重的一件事**：同一次复现里，紧接着的**下一次**召回在
`_admit_typed_recall_request` 上抛同一个 `OperationalError`——孤儿事务留在连接上，
一次超时污染的是整条连接，而不只是那一次召回。

## 2. 根因（file:line）

`aiosqlite` 把每条语句放进一条串行队列，由后台线程执行；
`.venv/.../aiosqlite/core.py:57-74` 的 `_connection_worker_thread` 拿到
`(future, function)` 之后**无条件**执行 `function()`，只在 future 已完成时把结果丢掉
（`set_result` 里 `if not fut.done()`）。也就是说：

> **取消 `await` 并不会取消已经排队的语句。**

而 0.6.32 及以前，仓里每一处事务都是这个形状（`backends/sqlite_v5.py` 41 处，
`history_source_guard.py:203`、`history_visibility.py:423`、`procedure_discovery.py:111`、
`prospective_sources.py:176`、`source_admission.py:106`、`operation_audit.py:755` 各 1 处）：

```python
await self._db.execute("BEGIN IMMEDIATE")   # ← 在 try 之外
committed = False
try:
    ...
finally:
    if not committed:
        with suppress(Exception):
            await self._db.execute("ROLLBACK")
```

`BEGIN` 写在 `try:` **之外**，所以取消落在这一行时：语句照样在连接上执行，`finally`
一次都不会跑。typed recall 的候选收集段（`sqlite_v5.py:4151`、`:4185`、`:4270` 三处
`asyncio.wait_for`）正是靠取消来兑现 deadline 的，所以这条路径必然踩中；命中与否只取决于
取消恰好落在 `BEGIN` 这一次 `await` 上（受机器负载影响，Host 采到 5/12，本地 7/60）。

对称的第二个缺口：`COMMIT` 被取消之后 COMMIT 仍然执行，此时
`sqlite_v5.py:1718` / `history_source_guard.py:242` / `history_visibility.py:534` /
`procedure_discovery.py:156` 那四处**裸写**的 `except BaseException: await execute("ROLLBACK")`
会抛 `cannot rollback - no transaction is active`，把正在展开的 `CancelledError`
整个替换掉。本地复现里这一支同样出现（60 次里 7 次）。

## 3. 备选方案与裁定

| 方案 | 裁定 | 理由 |
|---|---|---|
| A. 在 `_persist_typed_recall_timeout` 里先 `if in_transaction: ROLLBACK` | **不作为主修** | `in_transaction` 是直接读 `sqlite3.Connection` 属性、不走串行队列，可能在孤儿 `BEGIN` **执行之前**就读到 `False`；而且它只救终态这一处，连接仍然会被别的路径污染 |
| B. 把 `BEGIN` 挪进 `try:` | 不够 | `try` 只在 `BEGIN` **返回之后**才生效；取消恰好落在那一次 `await` 上时仍然进不去 |
| C. 关掉取消（把整段收集做成不可取消） | 否 | 与 deadline 契约直接冲突：预算到点必须停 |
| **D. 把「开事务」做成不可丢失的原语** | **采纳** | BEGIN 单独排队；取消时**先等它落地**，若确实开了事务就在同一条串行队列上补一条 ROLLBACK，然后才把取消继续往上抛。语句文本、锁纪律、调用形状全都不变 |

方案 A 保留为**纵深防御**（见 §4 第 3 条），但不是正确性的依赖项。

## 4. 实现

1. 新增 `src/simple_harness_memory/backends/sqlite_tx.py`（内部原语，`backends.*`
   从来不在公共面上）：
   * `begin_transaction(db, statement="BEGIN IMMEDIATE")` —— `asyncio.ensure_future` 排队 +
     `asyncio.shield`；取消时 `await` 那个 future 拿到确定结论，真的开了事务就立刻
     `rollback_transaction`，之后 `raise` 原异常。`statement` 只接受
     `BEGIN / BEGIN DEFERRED / BEGIN IMMEDIATE / BEGIN EXCLUSIVE` 四个字面量，
     **文本与被替换掉的裸语句逐字相同**。
   * `rollback_transaction(db)` —— 回滚永远不让自己的错误替换正在收尾的异常。
2. 召回路径上（含它经过的 6 个 helper 模块）**全部** 47 处 `BEGIN*` 改走
   `begin_transaction`；四处裸写的 `except BaseException: ROLLBACK` 改走
   `rollback_transaction`。其余 44 处 ROLLBACK（41 处已包在 `with suppress(Exception):` 里，另 3 处是有意的控制流回滚）
   本就安全，逐字未动（把 diff 压到最小）。
   **不在范围内**：`backends/sqlite.py`（v4 旧后端，另一个连接对象、不在 typed-recall
   路径上）与 `migrations/*`、`backends/upgrade_validation.py`（同步 `sqlite3`，没有取消）。
3. `_persist_typed_recall_timeout`（`sqlite_v5.py:6631`）加一条纵深防御：拿到写锁后若
   `self._db.in_transaction` 为真先回滚，让「终态必然落库」不依赖任何上游路径的正确性。
4. 阶段命名：入账**之后**的每一处预算耗尽改抛 0.6.27 的
   `TypedRecallDeadlineExceeded(stage)`（`TimeoutError` 子类，`str(exc)` 仍是
   `DEADLINE_EXCEEDED`），`stage` 取
   `after_admission` / `history_source_context` / `cognitive_vector_lane` /
   `collect_write_lock` / `collect_candidates` / `after_collect_candidates` /
   `collect_confirmation` / `collect_short_candidates` / `authority_expired`。
   `stage` **只活在异常对象上**，不进任何持久行——终态行的形状与入账阶段到期时逐字相同
   （`("deadline_exceeded", NULL, NULL, 0, 0, "[]", "[]")`）。
   `admit_write_lock` 仍是唯一一个**没有**终态行的阶段（幂等记录尚未落库，语义不变）。

## 5. 修复后的三条义务（Host 401 §4.4 的判据可以照抄）

任何阶段耗尽预算：

1. 抛稳定的 `TimeoutError("DEADLINE_EXCEEDED")`（`TypedRecallDeadlineExceeded`，
   `stage` 指出是哪一段）；
2. 恰好落下**一条** deadline 终态行，形状与入账阶段到期时逐字相同；
3. 连接上不留任何事务；随后同 key 同 body 的重放拿回同一个终态，其他 key 的召回照常成功
   （连接没有被污染）。

## 6. 反例与回归

`tests/integration/test_typed_recall_deadline_in_collection.py`（3 项）：

* `test_begin_transaction_never_leaves_an_orphan_transaction_when_cancelled`：
  原语层**成对**见证——同一个时序下，裸写法之后 `in_transaction is True` 且下一条
  `BEGIN IMMEDIATE` 抛 `cannot start a transaction within a transaction`；
  `begin_transaction` 之后 `in_transaction is False` 且下一条 `BEGIN IMMEDIATE` 正常。
* `test_deadline_inside_candidate_collection_writes_one_terminal_and_times_out`：
  **确定性**构造——把候选收集段那条读快照 `BEGIN` 的 `await` 端拖到 deadline 之后
  （BEGIN 已在连接上落地），逐条断言 §5 的三条义务 + `stage == "collect_candidates"`。
* `test_one_millisecond_budget_soak_never_escapes_operational_error`：
  50 次 `deadline_ms=1`，只允许 `DEADLINE_EXCEEDED`（任何别的异常直接判回归）、
  每次之后连接上无事务、**每个已入账请求恰好一条** deadline 终态行、最后一次正常预算召回成功。

负控：把后两项拷到 0.6.32 基线 worktree（去掉新模块的 import）跑，两项都以
`sqlite3.OperationalError: cannot start a transaction within a transaction` 失败。

全量 `tests/` 失败集合与 main 基线（`eec9760`，独立 detached worktree）**逐条相同**
（63 项既有环境失败，`diff` 为空），1622 → 1625 passed / 8 skipped；
`ruff check src tests` 计数与基线同为 709。

## 7. 边界

无 DDL 变化（7.4 checksum 不变）；根导出零增减；公共错误类与 Harness v4 wire 形状逐字不变；
快照 `public-api-0.6.33.json` 除 `version` 外与 0.6.19 起逐字相同。
仅本地候选（分支 `m0633`），未合 main、未构建 wheel、未 push、Host 未 pin。
