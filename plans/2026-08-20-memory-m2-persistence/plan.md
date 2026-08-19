# Plan：simple-harness-memory-sdk 0.2.0 第二部分 — 持久化加固（M2）

## 主要矛盾

决定成败的核心问题：**给"每个操作独立 commit"的 SQLite 后端加上 schema 版本化 + append 原子事务 + 幂等键，同时不破坏既有 8 条写路径、不丢 0.1.0 数据**。风险最高的是 Task 2（事务化——8 个 `_*_impl` 的 commit 全部移除后，非事务调用点必须显式提交，漏一个就静默丢数据）与 Task 1（老 0.1.0 库的迁移分支——`user_version==0` 分不清"全新"和"老库"）。

## 关联验收标准

覆盖 M2-AC-1（Task 1）、M2-AC-2（Task 2）、M2-AC-3（Task 3）。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|------|------|----------|
| `src/simple_harness_memory/backends/sqlite.py` | SQLite 后端 | Task 1/2/3：schema_meta 版本权威 + 迁移、事务上下文 + `_commit`、`_*_impl` 去 commit、source_event_id + ON CONFLICT |
| `src/simple_harness_memory/backends/base.py` | 后端抽象 | Task 2/3：`_commit`/`_transaction` 协议（默认 no-op）+ append 事务化 + source_event_id + 各写方法补 `_commit()` |
| `src/simple_harness_memory/core/port.py` | MemoryBackend 协议 | Task 2/3：`_transaction`/`_commit` + append 签名 |
| `src/simple_harness_memory/core/manager.py` | 统一入口 | Task 3：append 透传 source_event_id |
| `tests/integration/test_sqlite_backend.py` | SQLite 测试 | 三个 AC + 0.1.0 迁移的决定性测试 |
| `src/simple_harness_memory/__init__.py` | 版本 | 0.2.0 bump |

## 写方法全清单（challenger 校正：8 个，非 6）

| base 层写方法 | `_*_impl` 调用 | 提交方式 |
|---|---|---|
| `append_message` | `_append_message_impl` + `extract_facts` | `_transaction` 包裹（原子） |
| `extract_facts`（独立） | `_insert_fact` + `_supersede_fact` | `_commit()`（append 内调用时经 `_tx_depth>0` 变 no-op） |
| `forget_fact` | `_forget_fact_by_id` | `_commit()` |
| `update_digital_twin` | `_save_twin` | `_commit()` |
| `recall_and_reinforce` | `_update_message_salience` ×N | `_commit()` |
| `daily_decay` | `_update_message_salience` + `_set_fact_decay` | `_commit()` |
| `summarize_old_sessions` | `_append_message_impl` | `_commit()` |
| `record_workspace_action` | `_record_workspace_impl` | `_commit()` |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / 绑定 |
|-----------|:---:|------------|
| 新依赖 | 否 | — |
| 新公共 API | 是 | `append_message(source_event_id=...)`（M2-AC-3） |
| 新持久化状态 | 是 | `source_event_id` 列 + `schema_meta` 表（M2-AC-1/3） |
| 新抽象层 | 是 | `_transaction` / `_commit`（M2-AC-2） |
| 公开接口破坏 | 否 | append 签名向后兼容 |
| 可复用已有实现 | harness execution DB 的 migration/checksum 模式 | Task 1 参照 |

## Assurance / 信任与失败边界

- Profile：standard（见 assurance-contract.json）。
- 范围内失败：FAIL-1 未来 schema 静默打开 / FAIL-2 部分写入 / FAIL-3 重复插入 / FAIL-4 0.1.0 迁移丢数据 / FAIL-5 事务化破坏写路径。
- 停止追踪点：不做删除/lineage（OOS-1）、不做云端 embedder（OOS-2）。

---

## 任务清单（按依赖排序）

### Task 1 — schema version + migration + checksum  [M2-AC-1]
- 改动文件：`backends/sqlite.py`、`tests/integration/test_sqlite_backend.py`
- 现状：`initialize()` 只 `executescript(_DDL)` + commit，无版本标记；`_DDL` 全 `CREATE TABLE IF NOT EXISTS`。
- 修改方式（challenger 校正：`user_version==0` 分不清全新/老库，改用 schema_meta + 表存在性区分）：
  1. 新增 `SCHEMA_VERSION = 1`、`SCHEMA_CHECKSUM = sha256(_DDL)`；`_DDL` 加 `source_event_id` 列 + 唯一索引（Task 3）+ `CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)`。
  2. `initialize()` 分支：
     - 读 `schema_meta` 的 `schema_version`（`SELECT value FROM schema_meta WHERE key='schema_version'`）。
     - **无 schema_meta 行**：再查 `sqlite_master` 是否有 `messages` 表。有 → **老 0.1.0 库**，跑 `MIGRATIONS[0]`（`ALTER TABLE messages ADD COLUMN source_event_id TEXT` + 建唯一索引 + `INSERT schema_meta(version, checksum)`）；无 → 全新，executescript(_DDL) + 写 schema_meta。
     - **有 schema_meta 行**：读 version。`> SCHEMA_VERSION` → 抛稳定错误（future schema fail-closed）；`== SCHEMA_VERSION` → 校验 checksum 匹配，不匹配抛 `MemoryCorruptionError`；`< SCHEMA_VERSION` → 顺序跑 `MIGRATIONS[from..]`。
  3. `MIGRATIONS` 结构：`[(from_version, to_version, migration_sql)]`，M2 含 `[(0, 1, "ALTER TABLE messages ADD COLUMN source_event_id TEXT; ...")]`；**每个 migration 用逐条 `execute("BEGIN IMMEDIATE")` → `execute(各条迁移语句)` → `execute("COMMIT")` 包裹**（勿用 `executescript`：它对已开事务隐式 COMMIT，静默击穿原子性；或把 BEGIN/COMMIT 内联进 migration SQL 再交给 executescript）。原子迁移，防半迁移库。
- 验证：① 全新 → version=1 + checksum；② **构造 0.1.0 老库（建 messages 表 + 插数据 + 无 schema_meta）→ initialize 后 source_event_id 列存在 + 数据未丢 + 可 append**（TO-M2-4）；③ 伪造 version=999 → 抛 future-schema；④ 篡改 checksum → 抛 MemoryCorruptionError。
- 依赖：无

### Task 2 — append 原子事务  [M2-AC-2]
- 改动文件：`backends/sqlite.py`、`backends/base.py`、`core/port.py`、`tests/integration/test_sqlite_backend.py`
- 现状：8 个 `_*_impl` 各 `await self._conn.commit()`（L103/131/136/140/145/159/171/178）。
- 修改方式：
  1. `core/port.py` 加 `async def _commit(self) -> None` 与 `_transaction()` 上下文（协议；base 默认 `_commit` 为 no-op、`_transaction` 为 no-op `yield`）。
  2. `sqlite.py` `_commit`：`if self._tx_depth == 0: await self._conn.commit()`；`_transaction`：`self._tx_depth += 1` → `BEGIN IMMEDIATE` → `yield` → `COMMIT`，异常 → `ROLLBACK` + re-raise，finally `self._tx_depth -= 1`（**深度计数，支持 append 内嵌 extract_facts 的嵌套**，而非非重入布尔）。**单写者假设**：append 经单 aiosqlite 连接串行化；若未来需并发写，加 `asyncio.Lock` 串行化事务（challenger P2，contract 无并发假设）。
  3. `connect(..., isolation_level=None)`（显式 autocommit，手动 BEGIN/COMMIT/ROLLBACK）。
  4. **8 个 `_*_impl` 删除各自的 `await self._conn.commit()`**。
  5. `base.py`：`append_message` 用 `async with self._transaction():` 包住 `_append_message_impl` + `extract_facts`；**其余 7 个写方法（见"写方法全清单"）在各 `_*_impl` 后 `await self._commit()`**（`extract_facts` 的 `_commit()` 在 append 事务内经 `_tx_depth>0` 自动变 no-op，避免嵌套提交）。
  6. Mock 后端：`_commit`/`_transaction` 用 base 默认 no-op（内存后端天然原子）。
- 验证：monkeypatch `_insert_fact` 抛错 → append 抛错且 message + facts 均未持久化（回滚）；forget_fact/daily_decay/summarize_old_sessions 写路径仍落盘（新增回归测试覆盖这些此前无覆盖的路径）。
- 依赖：Task 1（同文件 DDL 改动一起）

### Task 3 — source_event_id 幂等键  [M2-AC-3]
- 改动文件：`backends/sqlite.py`、`backends/base.py`、`core/manager.py`、`core/port.py`、`tests/integration/test_sqlite_backend.py`
- 现状：messages 无 source_event_id；append 无幂等参数。
- 修改方式（challenger 校正：SELECT-then-INSERT 有竞态，用 ON CONFLICT）：
  1. `_DDL` messages 加 `source_event_id TEXT` + `CREATE UNIQUE INDEX idx_messages_source_event ON messages(source_event_id) WHERE source_event_id IS NOT NULL`。
  2. `append_message`（base/manager/port）加 `source_event_id: Optional[str] = None`；`_append_message_impl` 加参数。
  3. 幂等逻辑（challenger 实证：部分唯一索引**不能**作 `ON CONFLICT(column)` 目标）：`source_event_id` 非空时 `INSERT OR IGNORE ...`（无目标，兼容部分唯一索引）；`cur.rowcount == 0`（冲突）→ `SELECT id FROM messages WHERE source_event_id=?` 返回已有 id；`rowcount == 1` → 返回 `lastrowid`。唯一索引兜底并发/重放，稳定映射到"返回已有 id"。
- 验证：同 source_event_id 两次 append → 返回同 id、messages 仅 1 行；不同 id → 2 行。
- 依赖：Task 2（append 签名改动一起）

## 出口

- 3 条 M2-AC 全部有任务覆盖、6 个 challenger findings 已闭环 → 进入 round 2 diff 复审。
