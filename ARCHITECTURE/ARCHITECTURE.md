# ARCHITECTURE — simple-harness-memory-sdk（v0.3.0）

> 最后更新：2026-08-21
> 来源：agent-runtime-sdk-integration Task 4–5；本地 M1/M2/M3、M-ALL 与 latest M-WHEEL 全绿

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

## 生产事实（0.3.0）

### Product-neutral conversation boundary

- `ConversationMemoryAdapter` 对齐冻结的 Harness structural ports，但 Memory 包不 import Harness。
- sink intent 使用 `source_event_id/user_id/session_id/role/canonical memory_text` 计算 SHA-256；同 ID 同
  hash 返回 `already_applied`，同 ID 异 hash 返回稳定 conflict。
- `recall_bounded()` 使用 deterministic `context_query_id/query_hash`，在 memory transaction 内持久化
  canonical payload/result hash；commit 后重放直接返回原 bytes，不重新 recall。
- overall deadline 覆盖 backend operation lock、SQLite busy/`BEGIN IMMEDIATE`、compute、snapshot insert
  与 durable commit；锁等待超时映射为稳定 `memory_timeout`，不泄漏 SQLite error。
- recall result 支持 `complete/truncated/timeout`、显式 count/UTF-8 byte bounds 与幂等 release。
  user-scoped bounded maintenance 会清理超过 dedupe horizon 的 released 与 retained/unreleased 结果，
  horizon 内记录均保留。

### Fresh schema v3 与 ownership

- v3 只有 fresh initialization：`users`、immutable owner `sessions`、messages source identity、facts 真实
  source FK、session-owned actions、user-keyed twins、durable recall snapshots；旧版、缺 meta 或 checksum
  漂移均 `MemorySchemaIncompatible`，不隐式迁移。
- 每个公开 Memory read/write/maintenance path 显式接收 `user_id`；SQLite 先用 user predicate/index/limit
  缩小集合，再进入 Python ranking。生产代码不再存在 `_messages_all/_facts_all`。
- 每次连接在事务外启用并 read-back `PRAGMA foreign_keys=ON`；初始化/打开后执行 integrity 与
  `foreign_key_check`。DB 路径必须 regular/no-symlink/current-owner，mode 创建及回读均为 `0600`。
- message insert 与自动 fact extraction/supersede 位于同一个 `BEGIN IMMEDIATE`；任一失败整体 rollback。
- SQLite 公开 API 使用 task-owned operation lock 串行化；transaction owner + task-local depth 仅允许
  同 task nested，异 task（包括继承 ContextVar 的 child task）必须等待并独立 commit/rollback。
- `delete_all` 是 deprecated fail-closed compatibility surface，只抛 `runtime_delete_disabled` 且不 mutation；
  不提供 runtime `delete_user`/public clear API。

### Resource bounds 与维护

- `MemoryResourceBounds` 集中限制 content/fact/payload/DB、recall candidates/results/bytes/timeout、maintenance
  batch、summary batch 与 recall-result dedupe horizon。
- recall/vector/facts/twin/reinforce/decay/summarize/retention/reindex/workspace action 均为 user-scoped；
  decay/reindex/retention/snapshot cleanup 有界。
- `MemoryManager` 的 bounded recall/release/cleanup facade 显式列出 user/session/query/hash/bounds/deadline
  参数，不使用 `**kwargs` 逃逸身份合同。
- message/fact decay 持久化本次衰减水位；同一逻辑时间的重试不重复衰减。summary 以确定性
  source event 去重，reindex 仅选取 lineage mismatch，重试均不重复写入。

### 召回（M1）
- `recall()` 物理只读（不写 salience/last_recalled）；reinforcement 显式走 `recall_and_reinforce()`。
- `Embedder.embed()/embed_batch()` 是 async；retriever/recall 全链路 await。
- `get_embedder("auto")` 恒返回 `HashEmbedder`（不急切加载 BGE-M3）。
- 隐私日志：recall/fact 只记长度与计数，不记 query 原文 / fact key/value/evidence。

### Lineage 与 session maintenance

- `delete_session`/user-scoped bounded `delete_old_sessions` 级联 messages+facts+workspace actions并重建 twin。
- embedding lineage 列（embedder_kind/dim/format_version）+ `reindex(embedder)`（换掉 self._embedder/retriever）。

### 云端 embedding（M4）
- `CloudEmbedder`：async + 批量 + LRU 缓存 + 指数退避重试 + fail-closed（无静默降级）。
- `OpenAICompatibleClient`：httpx `/embeddings` + dim 校验；api_key 不进 repr/str/异常/log。
- `get_embedder("cloud", base_url/api_key/model/dim)` 集成；dim 必填（None 哨兵）。

## 关键边界
- 核心依赖仅 `aiosqlite`/`pydantic`/`numpy`；torch/httpx/openai 均为可选 extra。
- 向量化默认 `HashEmbedder`（确定性伪向量）；语义嵌入走 `BGEM3Embedder`（可选）；云端走 `CloudEmbedder`。
- 版本单一来源：`[tool.hatch.version] path = "src/simple_harness_memory/__init__.py"`（动态，不漂移）。
- `pyproject.toml`/`uv.lock` 固定 Ruff `0.16.3`、mypy `1.20.2`；CI matrix 覆盖 Python
  3.11/3.12/3.13、clean exact wheel 与 Linux ARM64 core gate。
- CI authoritative artifact 才生成 canonical `BUILD_INFO.txt`/`SHA256SUMS`；本地 M-WHEEL dist 保持
  wheel/sdist 原 bytes。release workflow 仅手动验证指定 run/artifact ID、source commit 与 wheel SHA，
  再上传 verified Actions artifact 供 Task 10 single publisher 消费；它不由 tag 触发、不 rebuild、
  不创建 tag/release。
- artifact tests 仅在显式传入 `MEMORY_SDK_ARTIFACT_DIST` 时执行候选字节门；普通 full suite
  稳定 skip 这三项候选制品测试，candidate job/M-WHEEL 始终显式传入且不可降级。

## 验证状态

- M1：27 passed。
- M2：30 passed（含 SQLite query-plan/user predicate+limit、跨 user maintenance）。
- M3：Ruff 与 mypy 全绿。
- M-ALL（无候选制品 env）：126 passed、6 skipped；Python 3.11/3.12/3.13 与 Ruff/mypy 全绿。
- latest M-WHEEL：5 passed（exact wheel clean consumer + candidate/release contract）。
- Linux ARM64 candidate gate 已在 Actions run `32439769610` 验证通过；每次 promotion 仍须绑定 exact
  replacement run。Xperia/consumer exact candidate 验收属于后续 Task 6–10，不能由本地 macOS 结果代替。
