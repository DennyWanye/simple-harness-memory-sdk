# Plan：simple-harness-memory-sdk 0.2.0 第三部分 — 删除/lineage/资源上限（M3）

## 主要矛盾

决定成败的核心问题：**加级联删除、embedding lineage、资源上限，同时不误删其他 session 数据、不丢 embedding、不静默丢弃超限内容**。风险最高的是 Task 1（级联删除——source_msg_id 关联 + twin 重建 base 必须 None，否则保留陈旧画像）与 Task 2（lineage——reindex 必须换掉 `self._embedder`/`self._retriever`，否则 recall 维度不匹配静默返回空）。

## 关联验收标准

覆盖 M3-AC-1（Task 1）、M3-AC-2（Task 2）、M3-AC-3（Task 3）。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|------|------|----------|
| `src/simple_harness_memory/backends/sqlite.py` | SQLite 后端 | Task 1/2/3：删除级联 SQL、lineage 列、`reindex`、大小上限、`_delete_*_impl`/`_update_embedding_impl` |
| `src/simple_harness_memory/backends/base.py` | 后端抽象 | Task 1/2/3：delete/reindex/limit 方法 + lineage 记录 + `_delete_*_impl`/`_update_embedding_impl` 抽象 |
| `src/simple_harness_memory/backends/mock.py` | Mock 后端 | Task 1/2/3：`_delete_*_impl`/`_update_embedding_impl`/`_append_message_impl` 的内存实现 |
| `src/simple_harness_memory/core/port.py` / `manager.py` | 协议 + 入口 | Task 1：delete 方法透传 |
| `src/simple_harness_memory/core/models.py` | 数据模型 | Task 2：Message 加 lineage 字段 |
| `src/simple_harness_memory/embedders/base.py` / `mock.py` / `bge.py` | Embedder | Task 2：加 lineage 元数据 |
| 新增 `src/simple_harness_memory/core/errors.py` | 错误 | Task 3：`MemoryLimitError` |
| `tests/integration/test_sqlite_backend.py` | SQLite 测试 | 三个 AC 的决定性测试 + **更新 schema 版本测试（`== 1` 改 `== SCHEMA_VERSION`）** |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / 绑定 |
|-----------|:---:|------------|
| 新依赖 | 否 | — |
| 新公共 API | 是 | `delete_session`/`delete_all`/`delete_old_sessions`/`reindex`（M3-AC-1/2） |
| 新持久化状态 | 是 | lineage 列（M3-AC-2） |
| 新抽象层 | 否 | 复用 Embedder/twin_builder |
| 公开接口破坏 | 否 | 新增方法 |
| 可复用已有实现 | `build_twin_from_facts` | Task 1 复用（base=None） |

## Assurance / 信任与失败边界

- Profile：standard（见 assurance-contract.json）。
- 范围内失败：FAIL-1 删除不级联 / FAIL-2 误删 / FAIL-3 lineage 不一致 / FAIL-4 破坏既有路径 / FAIL-5 超限静默。
- 停止追踪点：不做云端 embedder（OOS-1）。

---

## 任务清单（按依赖排序）

### Task 1 — 级联删除 + retention  [M3-AC-1]
- 改动文件：`backends/sqlite.py`、`backends/base.py`、`backends/mock.py`、`core/port.py`、`core/manager.py`、新增测试
- 现状：无任何 delete 方法。
- 修改方式（challenger 校正：twin 重建 base=None + 空 ids + supersede 链）：
  1. `sqlite.py`/`mock.py` 加 `_delete_messages_by_ids_impl(ids)`、`_delete_facts_by_ids_impl(ids)`、`_delete_workspace_by_session_impl(session_id)`、`_clear_all_impl()`、`_clear_dangling_supersede_impl(deleted_fact_ids)`。后者**传递性 re-point**：对每个 `superseded_by IN deleted` 的剩余 fact，把其 `superseded_by` 指向后继的后继（`UPDATE facts SET superseded_by=(SELECT f2.superseded_by FROM facts f2 WHERE f2.id=facts.superseded_by) WHERE superseded_by IN deleted`），循环直到无 dangling——多跳链 A→B→C 删中间 B 时，A.superseded_by 应 re-point 到 C 而非 NULL（NULL 会复活陈旧值 A，与仍 active 的 C 冲突）。
  2. `base.py` 加：
     - `delete_session(session_id)`：取该 session 的 message ids；**ids 为空则只删 workspace_actions 并返回（跳过 facts 删除，避免 `IN ()` 语法错误）**；否则**先 re-point dangling supersede（物理删除之前，后继 fact 仍在表里）**：循环 `UPDATE facts SET superseded_by=(SELECT f2.superseded_by FROM facts f2 WHERE f2.id=facts.superseded_by) WHERE superseded_by IN (deleted_fact_ids) AND superseded_by IS NOT NULL` 直到 rowcount==0（多跳链 A→B→C 删 B，A.superseded_by 先 re-point 到 C）；再删 messages + source facts + workspace_actions → `_commit()` → `_rebuild_twin()`。
     - `_rebuild_twin()`：`build_twin_from_facts(active_facts, base=None)`（**fresh DigitalTwin，非 `_load_twin` 合并**，否则 set-if-None/upsert-only 会保留已删 session 的陈旧画像）→ `_save_twin` → `_commit()`。**已知限制（P2）**：base=None 会同时丢弃 `update_digital_twin` 手动设置的非 fact 字段（twin 无 provenance，无法区分 fact 派生 vs 手动）；隐私优先，过清优于残留，记录在 CHANGELOG。
     - `delete_all()`：清 4 表 → `_commit()`。
     - `delete_old_sessions(older_than_days)`：找最后活跃早于阈值的 session → 逐个 `delete_session`。
  3. `port.py`/`manager.py` 透传。
- 验证：① delete_session 后该 session 的 messages/facts/workspace_actions 无残留、其他 session 保留；② **twin 重建后不含已删 session 派生的 profile/preference 信息**（TO-M3-1 补 twin 断言）；③ delete_all 后全空；④ 空 session 幂等删除不抛错。
- 依赖：无

### Task 2 — embedding lineage + reindex  [M3-AC-2]
- 改动文件：`embedders/base.py`、`mock.py`、`bge.py`、`core/models.py`、`backends/sqlite.py`、`backends/base.py`、`backends/mock.py`、`tests/integration/test_sqlite_backend.py`
- 现状：messages 仅 `embedding BLOB`；`Embedder` 仅 `dim`。
- 修改方式（challenger 校正：reindex 换 self._embedder + 分批 + schema 测试更新）：
  1. `embedders/base.py` 加 `kind` 抽象属性 + `EMBEDDING_FORMAT_VERSION = 1`；`mock.py` `kind="hash"`、`bge.py` `kind="bge"`。
  2. `core/models.py` `Message` 加 `embedder_kind`/`embedding_dim`/`embedding_format_version`（默认 None）；`_row_to_message` 兼容旧数据（`row["embedder_kind"] if "embedder_kind" in row.keys() else None`，或用 `row["embedder_kind"]` 经迁移列已存在）。
  3. `_DDL` messages 加 3 个 lineage 列（可空）+ MIGRATIONS 追加 `(1, 2, "ALTER TABLE messages ADD COLUMN embedder_kind TEXT; ...")`，`SCHEMA_VERSION = 2`。
  4. `append_message` 记录 `self._embedder` 的 lineage；`_append_message_impl` 加 lineage 参数（sqlite 存列，mock 忽略）。
  5. `reindex(embedder=None)`：`new_embedder = embedder or self._embedder`；**分批**（chunk=100）`embed_batch` 重 embed 全部 messages，更新 embedding BLOB + lineage → `_commit()`；**随后 `self._embedder = new_embedder` 并 `self._retriever = Retriever(new_embedder, self._reranker)`**（否则 recall 维度不匹配，`_vec` 静默 `continue` 返回空）。
  6. `tests/integration/test_sqlite_backend.py`：**`test_schema_version_recorded_and_future_rejected` 的 `int(row[0]) == 1` 改 `== SCHEMA_VERSION`**（导入常量）。
- 验证：① append 后 lineage 与当前 embedder 一致；② `reindex(HashEmbedder(dim=128))` 后所有 message 的 embedding 维度 + lineage 更新；③ **reindex 后 `recall("猫")` 仍返回命中（维度已对齐，非静默空）**。
- 依赖：Task 1（同文件 DDL/迁移改动一起）

### Task 3 — 资源上限  [M3-AC-3]
- 改动文件：`core/errors.py`、`backends/base.py`、`backends/sqlite.py`、`backends/mock.py`、新增测试
- 现状：无大小限制。
- 修改方式（challenger 校正：4 个上限全覆盖 + DB 检查集中）：
  1. `core/errors.py` 加 `MemoryLimitError(RuntimeError)`。
  2. `base.py` 加 `_check_content(content)`（`len > self._max_content_chars` → 抛 `MemoryLimitError`，默认 100_000，构造参数可配）；`extract_facts` 对每个 fact 的 `value`/`evidence` 校验；`record_workspace_action` 校验 payload 序列化大小。
  3. **DB 增长上限集中**：`base.py` 加 `async _check_db_size()`，在 `append_message`/`extract_facts`/`record_workspace_action`/`update_digital_twin` 等**所有写入口**前调用（sqlite 实现 `os.path.getsize(self._db_path) > self._max_db_bytes` 抛 `MemoryLimitError`，默认 100MB；mock 实现 no-op）。
- 验证：① 超长 content → 抛 `MemoryLimitError`；② 超长 fact value → 抛；③ 超大 payload → 抛；④ DB 超限（构造 `max_db_bytes` 极小）→ 抛且不写入。
- 依赖：Task 1（同文件）

## 出口

- 3 条 M3-AC 全部有任务覆盖、8 个 challenger findings 已闭环 → 进入 round 2 diff 复审。
