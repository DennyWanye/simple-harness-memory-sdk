# Plan：simple-harness-memory-sdk 0.2.0 第一部分 — 召回/隐私/embedder（M1）

## 主要矛盾

决定成败的核心问题：**把 recall 从"读+写混合"改成"物理只读"，并让 Embedder 协议 async 化——同时不破坏既有召回质量，且把所有锁死旧行为的既有测试（observability/mock_backend/embedders）显式改写为新语义**。风险最高的是 Task 4（async 化，调用链含 append_message + 测试里的 sync 调用）与 Task 2（隐私日志，query 在 retriever.py 与 base.py 两处）。

## 关联验收标准

覆盖 M1-AC-1（Task 1）、M1-AC-2（Task 2）、M1-AC-3（Task 3）、M1-AC-4（Task 4）、M1-AC-5（Task 5）。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|------|------|----------|
| `src/simple_harness_memory/backends/base.py` | 后端抽象 | Task 1/2/4：recall 只读化、日志脱敏、append_message 的 embed await、recall await retriever |
| `src/simple_harness_memory/core/manager.py` | 统一入口 | Task 1：加 `recall_and_reinforce()` |
| `src/simple_harness_memory/core/port.py` | MemoryBackend 协议 | Task 1：加 `recall_and_reinforce` |
| `src/simple_harness_memory/backends/sqlite.py` | SQLite 后端 | Task 3：`_deserialize_twin` fail-closed |
| `src/simple_harness_memory/embedders/base.py` | Embedder ABC | Task 4：embed/embed_batch 改 async |
| `src/simple_harness_memory/embedders/mock.py` | HashEmbedder | Task 4：embed 改 async |
| `src/simple_harness_memory/embedders/bge.py` | BGEM3Embedder | Task 4：embed 改 async |
| `src/simple_harness_memory/features/retriever.py` | RRF 六路召回 | Task 2/4：query 日志脱敏、recall/_vec/vector_search 改 async |
| `src/simple_harness_memory/embedders/factory.py` | embedder 工厂 | Task 5：auto 不再 BGE |
| 新增 `src/simple_harness_memory/core/errors.py` | 稳定错误类型 | Task 3：`MemoryCorruptionError` |
| `tests/unit/test_mock_backend.py` | 召回测试 | Task 1：`test_recall_bumps_salience` 改写为 recall_and_reinforce |
| `tests/unit/test_embedders.py` | embedder 测试 | Task 4/5：sync embed 改 await；auto→BGE 测试删除/改写 |
| `tests/unit/test_logging_observability.py` | observability 测试 | Task 2/4：query[:80] 断言改 query_len；sync retriever.recall 改 await |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / 绑定 |
|-----------|:---:|------------|
| 新依赖 | 否 | — |
| 新公共 API | 是 | `recall_and_reinforce()`（M1-AC-1）；`MemoryCorruptionError`（M1-AC-3） |
| 新持久化状态 | 否 | — |
| 新配置项 | 否 | — |
| 公开接口破坏 | 是 | `Embedder.embed` sync→async（M1-AC-4，0.2.0 前无 release） |
| 既有测试改写 | 是 | 3 个测试文件锁死旧语义（见下方清单），M1 行为变更须同步改写 |

## 既有测试改写清单（challenger 发现）

| 测试 | 旧断言 | 改写成 |
|------|--------|--------|
| `test_mock_backend.py::test_recall_bumps_salience`（141-148） | recall 后 salience==0.05 | 改为 recall 后 salience 不变 + recall_and_reinforce 后提升 |
| `test_embedders.py::test_get_embedder_auto_returns_bge_when_available`（54-57） | auto→BGEM3Embedder | 删除（auto 不再 BGE）或改为断言 auto→HashEmbedder |
| `test_embedders.py::test_get_embedder_auto_falls_back_to_hash`（43-45，带 skipif） | auto 缺依赖回退 hash | 去掉 skipif，改为 auto 恒 Hash |
| `test_embedders.py`（19-29,69-71） | sync `e.embed(...)` | `await e.embed(...)`（test 改 async） |
| `test_logging_observability.py::test_recall_emits_memory_recall`（63） | sync `retriever.recall(...)` | `await retriever.recall(...)` |
| `test_logging_observability.py`（53） | `query=query[:80]` 源码断言 | `query_len` 源码断言 |

这些是 memory-sdk 自身单测（非 black-box oracle），锁定的是本 slice 明确要改的旧行为；改写由已批准的 acceptance（recall 只读 / async / auto→Hash）授权，非静默行为变更。

## Assurance / 信任与失败边界

- Profile：standard（见 assurance-contract.json）。
- 范围内失败：FAIL-1 recall 仍写入 / FAIL-2 日志含 query / FAIL-3 twin 静默 / FAIL-4 auto BGE / FAIL-5 召回质量退化 / FAIL-6 async 化破坏调用链。
- 停止追踪点：不做 schema 迁移（OOS-1）、不做删除/lineage（OOS-2）、不做云端 embedder（OOS-3）。

---

## 任务清单（按依赖排序）

### Task 1 — recall 只读化 + recall_and_reinforce  [M1-AC-1]
- 改动文件：`backends/base.py`、`core/manager.py`、`core/port.py`、`tests/unit/test_mock_backend.py`
- 现状：`base.py` `recall()` 调 `self._retriever.recall(...)` 后 `for hit in hits: bump_salience + _update_message_salience`。
- 修改方式：
  1. `base.py`：抽 `async def recall_and_reinforce(self, query, session_id=None, limit=10)`（含 bump_salience 循环）；`recall()` 保留只读（召回 + 返回，不写）。
  2. `core/port.py` 加 `recall_and_reinforce`；`manager.py` 透传。
  3. `test_mock_backend.py`：`test_recall_bumps_salience` 改写为两条断言（recall 不变 / recall_and_reinforce 提升）。
- 验证：新增测试 ① recall 前后 salience/last_recalled 不变；② recall_and_reinforce 后命中项 salience 提升 + last_recalled 更新。
- 依赖：Task 4（同文件 await 改动一起做）

### Task 2 — 隐私日志  [M1-AC-2]
- 改动文件：`backends/base.py`、`features/retriever.py`、`tests/unit/test_logging_observability.py`
- 现状：query 日志在 `base.py`（`memory.recall`/`recall_failed` 记 `query=query`）与 `retriever.py:50/59`（`memory.recall`/`memory.recall_empty` 记 `query=query[:80]`）；**fact 日志在 `base.py:128-143`（`memory.fact_superseded` 记 `key=fact.key`；`memory.extract_facts` 记 `facts=[{"key","value","category"}]`，value/key 原文进日志）**。
- 修改方式：
  1. `base.py` `memory.recall`/`recall_failed`：`query=query` → `query_len=len(query)`。
  2. `retriever.py:50/59`：`query=query[:80]` → `query_len=len(query)`。
  3. `base.py` `memory.extract_facts`：删除 `facts=[{"key","value","category"}]` 列表（保留 `fact_count`）；`memory.fact_superseded`：删除 `key=fact.key`（保留 subject/old_id/new_id）。
  4. `test_logging_observability.py:53` 源码断言 `query=query[:80]` → `query_len`。
- 验证：caplog 断言 recall 日志不含 query 原文、extract_facts 日志不含 value/key 原文。
- 依赖：Task 1

### Task 3 — fail-open twin 修正  [M1-AC-3]
- 改动文件：新增 `core/errors.py`、`backends/sqlite.py`
- 现状：`sqlite.py` `_deserialize_twin` `except Exception: return DigitalTwin(subject=subject)`；`_load_twin`（163）/`get_digital_twin` 调用它。
- 修改方式：
  1. 新增 `core/errors.py` `MemoryCorruptionError(RuntimeError)`。
  2. `_deserialize_twin` 解析失败 → `raise MemoryCorruptionError`（保留 subject）。
  3. **传播决策**：`get_digital_twin`（base.py）及其调用方 `recall`/`suggest_questions` 均**传播**该异常（不隔离）——损坏即 fail-closed 上报；"隔离损坏 twin 继续召回"是 P1/M3 的损坏隔离策略，不在本 slice。
- 验证：损坏 data_json → `get_digital_twin` 抛 `MemoryCorruptionError`，不返回空 DigitalTwin；recall 遇损坏 twin 抛错而非静默。
- 依赖：无

### Task 4 — async Embedder 协议  [M1-AC-4]
- 改动文件：`embedders/base.py`、`embedders/mock.py`、`embedders/bge.py`、`features/retriever.py`、`backends/base.py`、`tests/unit/test_embedders.py`、`tests/unit/test_logging_observability.py`
- 现状：`Embedder.embed` sync；`HashEmbedder.embed`/`BGEM3Embedder.embed` sync；`Retriever._vec` sync 调 embed；`base.py` 两处 sync 调 embed：`recall` 路径（`self._retriever.recall`）与 **`append_message`（`base.py:78` `encode_vector(self._embedder.embed(content))`）**。
- 修改方式：
  1. `embedders/base.py`：`async def embed`；`async def embed_batch`。
  2. `mock.py`/`bge.py`：`async def embed`（内部逻辑不变）。
  3. `retriever.py`：`_vec`/`recall`/`vector_search` 改 async（`await self._embedder.embed(...)`）。
  4. `base.py`：`recall`/`vector_search` 改 `await self._retriever.recall(...)`；**`append_message` 改 `embedding = encode_vector(await self._embedder.embed(content))`**。
  5. `test_embedders.py`：sync `e.embed(...)` 改 `await`（test 函数改 async）；`test_logging_observability.py:63` sync `retriever.recall(...)` 改 `await`。
- 验证：全量 pytest 0 新增失败；新增 async embedder 全链路 append + recall 测试。
- 依赖：Task 1/2（同文件）

### Task 5 — Hash 默认（auto 不 BGE）  [M1-AC-5]
- 改动文件：`embedders/factory.py`、`tests/unit/test_embedders.py`
- 现状：`get_embedder(kind="auto")` `try: import BGEM3Embedder; return BGEM3Embedder()`。
- 修改方式：`auto` 分支直接 `return HashEmbedder(dim=dim)`（移除 BGE 导入）；`kind="bge"` 保留显式。
- 验证：`test_get_embedder_auto_returns_bge_when_available` 删除或改为断言 auto→HashEmbedder；`test_get_embedder_auto_falls_back_to_hash` 去 skipif 改为恒 Hash。
- 依赖：Task 4

## 出口

- 5 条 M1-AC 全部有任务覆盖、8 个 challenger findings 已闭环 → 进入 round 2 diff 复审。
