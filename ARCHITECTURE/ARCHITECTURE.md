<!-- last-calibrated: 8cabfe9 -->

# ARCHITECTURE — simple-harness-memory-sdk（v0.2.0 生产化）

> 最后更新：2026-08-20
> 来源：sdk-productionization program（M1-M4），4 个 slice 全部 finalize PASS（receipt `bf594aa2`/`eac81d14`/`dcef5d80`/`f7a3ee2b`）

## 分层

```text
src/simple_harness_memory/
├── core/         # Port（MemoryBackend） + 数据模型 + DigitalTwin + MemoryManager + errors
├── backends/     # BaseMemoryBackend + Mock + SQLite（schema 版本化 + 事务）
├── features/     # facts 提取 / RRF 六路召回 / reranker / summarizer
├── cognitive/    # 遗忘曲线 / 显著性 / 会话亲和 / 孪生体构建
├── embedders/    # Embedder（hash 默认 / bge 可选 / cloud 云端）
└── world/        # WorldModelPort + temporal/events/geography/knowledge
```

## 生产事实（0.2.0）

### 召回（M1）
- `recall()` 物理只读（不写 salience/last_recalled）；reinforcement 显式走 `recall_and_reinforce()`。
- `Embedder.embed()/embed_batch()` 是 async；retriever/recall 全链路 await。
- `get_embedder("auto")` 恒返回 `HashEmbedder`（不急切加载 BGE-M3）。
- 隐私日志：recall/fact 只记长度与计数，不记 query 原文 / fact key/value/evidence。

### 持久化（M2）
- `schema_meta` 表 + `SCHEMA_VERSION=2` + `SCHEMA_CHECKSUM`：全新建库、老 0.1.0 原地迁移、
  future/checksum 漂移 fail-closed（`MemoryCorruptionError`）。
- `append_message`（含 fact 提取/插入/supersede）单事务；失败回滚。
- `source_event_id` 幂等键（部分唯一索引 + `INSERT OR IGNORE`）。
- `_*_impl` 不独立 commit；base 层写方法经 `_commit()`/`_transaction()`（`_tx_depth` 深度计数）。

### 删除 / lineage / 上限（M3）
- `delete_session`/`delete_all`/`delete_old_sessions` 级联 messages+facts+workspace_actions，
  supersede 传递性 re-point（先 re-point 再物理删）、twin 重建（base=None）。
- embedding lineage 列（embedder_kind/dim/format_version）+ `reindex(embedder)`（换掉 self._embedder/retriever）。
- 资源上限：`max_content_chars`/`max_fact_value_chars`/`max_payload_bytes`/`max_db_bytes`（`MemoryLimitError`）。

### 云端 embedding（M4）
- `CloudEmbedder`：async + 批量 + LRU 缓存 + 指数退避重试 + fail-closed（无静默降级）。
- `OpenAICompatibleClient`：httpx `/embeddings` + dim 校验；api_key 不进 repr/str/异常/log。
- `get_embedder("cloud", base_url/api_key/model/dim)` 集成；dim 必填（None 哨兵）。

## 关键边界
- 核心依赖仅 `aiosqlite`/`pydantic`/`numpy`；torch/httpx/openai 均为可选 extra。
- 向量化默认 `HashEmbedder`（确定性伪向量）；语义嵌入走 `BGEM3Embedder`（可选）；云端走 `CloudEmbedder`。
- 版本单一来源：`[tool.hatch.version] path = "src/simple_harness_memory/__init__.py"`（动态，不漂移）。
