# ARCHITECTURE — simple-harness-memory-sdk

> 最后更新：2026-08-18
> 详细设计：主仓库 `simple_harness/plans/2026-08-17-memory-sdk/00-ARCHITECTURE.md`

## 分层

```text
src/simple_harness_memory/
├── core/         # Port（MemoryBackend） + 数据模型 + DigitalTwin + MemoryManager
├── backends/     # BaseMemoryBackend + Mock + SQLite
├── features/     # facts 提取 / RRF 六路召回 / reranker / summarizer
├── cognitive/    # 遗忘曲线 / 显著性 / 会话亲和 / 孪生体构建
├── embedders/    # Embedder（hash mock 默认，BGE 可选）
└── world/        # WorldModelPort + temporal/events/geography/knowledge
```

## 关键边界
- 核心依赖仅 `aiosqlite`/`pydantic`/`numpy`；torch/httpx/openai 均为可选 extra。
- 向量化默认 `HashEmbedder`（确定性伪向量）；语义嵌入走 `BGEM3Embedder`（可选）。
- 世界对象所有网络数据源都有 noop 降级（未配置时返回空/None）。
- 云端后端（Pinecone）为后续 slice，不在本 release unit。
