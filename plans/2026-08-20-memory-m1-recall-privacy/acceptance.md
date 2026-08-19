# 验收标准：simple-harness-memory-sdk 0.2.0 第一部分 — 召回/隐私/embedder（M1）

> 状态：DRAFT（待用户确认）
> 仓库：`simple-harness-memory-sdk`（代码改动 + 发布仅在此仓库）
> 来源：SDK 生产化 program Slice M1；评审文档"Memory shadow-write 前门禁"中的召回语义 + 隐私 + embedder 项
> 版本：本 slice 无 schema 迁移，版本暂留 0.1.0（0.2.0 bump 在 M2 引入 migration 时执行）

## 范围

**包含**（无 schema 迁移，改动集中在 recall 语义、日志、twin 反序列化、embedder 接口）：

- 只读召回拆分：`recall()` 无副作用，reinforcement 拆到独立方法
- 隐私日志：recall 不再记录 raw query / 抽取 fact 的 key/value/evidence 原文
- fail-open twin 修正：损坏 data_json 不再静默返回空 DigitalTwin
- async Embedder 协议：`embed()` 改 async，retriever/recall 全链路 await
- Hash 默认：`auto` 不再急切加载 BGE-M3

**明确不包含**：
- schema version / migration / 事务 / 幂等（M2）
- 级联删除 / embedding lineage / 资源上限（M3）
- 云端 embedding provider 实现（M4，本 slice 只定 async 协议）
- 宿主 `simple_harness` / AIPhone re-vendor（C1）

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 优先级 |
|----|--------|-------------------|--------|
| M1-AC-1 | 只读召回 | `MemoryManager.recall()` 调用后，DB 中 `messages.salience` / `last_recalled` 无任何变化（物理无写入）；新增 `recall_and_reinforce()`（对命中项 bump salience + 写 last_recalled，行为等同旧 `recall()` 的写路径） | 必须 |
| M1-AC-2 | 隐私日志 | `memory.recall` / `memory.recall_failed` 日志不包含 raw query 原文（改为 query 长度或省略）；fact 抽取路径不记录 key/value/evidence 原文 | 必须 |
| M1-AC-3 | fail-open twin 修正 | `_deserialize_twin` 解析失败时不再静默返回空 `DigitalTwin`；改为抛出稳定错误（如 `MemoryCorruptionError`）或返回明确 corrupt 标记，调用方据此上报而非当作"用户无画像" | 必须 |
| M1-AC-4 | async Embedder 协议 | `Embedder.embed()` / `embed_batch()` 改为 `async`；`Retriever.recall()` / `vector_search()` 及 `base.py` 的 recall/vector_search 全链路 `await`；`HashEmbedder` 实现 async 协议 | 必须 |
| M1-AC-5 | Hash 默认（不 auto BGE） | `get_embedder("auto")` 不再尝试导入/构造 `SentenceTransformer`（不触发 BGE 路径）；`auto` 等价于 Hash（或直接移除 `auto`、默认 Hash）。`get_embedder("bge")` 仍显式可用但须显式指定 | 必须 |

## 非功能 / 边界

- **向后兼容**：`recall()` 的返回结构（`list[Hit]`）不变，仅副作用语义变化；`Embedder` 接口从 sync→async 是公开接口变更，本 slice 是 0.2.0 前的破坏性变更（memory 无正式 release，可接受）
- **隐私**：query / fact key/value / evidence 不进入日志；存储层原文保留（删除是 M3 的级联删除职责）
- **性能**：async embedder 的 Hash 实现仍为确定性伪向量，无网络/重依赖；召回语义不变
- **错误态**：twin 损坏 → 稳定错误/标记，不静默清空

## 适用性声明（APPLICABILITY_DECLARATION）

- `input_sensitive=false`：库 API 语义修正，验证走确定性单测 + 内存/临时 SQLite，非 LLM 语义功能。
- `llm_payload_driven=false`：无 LLM 输出驱动端侧状态机。
- `stateful_init=false`：无异步注册服务/登录态依赖。

## 测试义务矩阵（Test Obligation Matrix）

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---------------|------|-------|------|-------------------|-----------------|
| TO-M1-1 | delivery | M1-AC-1 | — | recall 前后比对 salience/last_recalled 不变；recall_and_reinforce 后 salience 提升 | 证明只读召回物理无写入 |
| TO-M1-2 | delivery | M1-AC-2 | — | caplog 断言 recall 日志不含 query 原文 | 证明隐私日志生效 |
| TO-M1-3 | delivery | M1-AC-3 | — | 损坏 data_json → 抛稳定错误/返回 corrupt 标记 | 证明损坏不再被静默 |
| TO-M1-4 | delivery | M1-AC-4 | — | async embedder 全链路 recall 返回命中 | 证明 async 协议可用 |
| TO-M1-5 | delivery | M1-AC-5 | — | get_embedder("auto") 不触发 SentenceTransformer 导入、返回 HashEmbedder | 证明不 auto BGE |
| TO-M1-R1 | change-risk | M1-AC-1 | FAIL-5 既有行为回归 | 既有 recall 测试（命中/排序/affinity）仍通过 | 防止拆分召回破坏召回质量 |
| TO-M1-R2 | change-risk | M1-AC-4 | FAIL-6 接口破坏 | 既有 recall/vector_search 测试在 async 化后仍通过 | 防止 async 化破坏调用链 |

## 完成的定义（DoD 摘要）

1. 5 条 M1-AC 全部通过测试
2. 所有 delivery / change-risk obligation 有对应 PASS testcase
3. `simple-harness-memory-sdk` git status 干净、CHANGELOG 更新
4. 全量 pytest PASS
5. gate finalize exit 0，receipt 入账
