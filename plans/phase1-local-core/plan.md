# Plan：simple-harness-memory-sdk 本地记忆核心（首个 release unit）

> 详细架构设计见主仓库 `simple_harness/plans/2026-08-17-memory-sdk/00-ARCHITECTURE.md`。
> 本 plan 只落首个垂直 slice 的代码级任务。

## 主要矛盾
决定成败的核心问题是：**如何在不引入 torch/网络的前提下，让一个本地库同时具备
持久化、结构化事实提取、多路混合召回、认知衰减与数字孪生体，并全部可确定测试**。
解法是把"向量化"和"事实提取"都做成可插拔：默认用哈希伪向量 + 规则提取，真实 BGE/LLM 走可选 extra。

## 关联验收标准
覆盖 AC-1..AC-8。

## 任务清单（按依赖排序）

### Task 1 — 补全 embedders（哈希嵌入器 + BGE 可选） [AC-8]
- 文件：`src/simple_harness_memory/embedders/{base.py,mock.py,bge.py,__init__.py}`
- 修改：`Embedder` ABC、`encode/decode_vector`、`cosine_similarity`；`HashEmbedder`（字符 n-gram + hashing trick，确定性）；`BGEM3Embedder`（惰性 import sentence-transformers）。

### Task 2 — 补全 features（facts / retriever / reranker / summarizer） [AC-4, AC-5]
- 文件：`src/simple_harness_memory/features/{facts.py,retriever.py,reranker.py,summarizer.py,__init__.py}`
- 修改：`RuleBasedFactExtractor`/`LLMFactExtractor`、六路 `Retriever`（vec/fts/recency/salience/facts/entity，recency/salience 只在候选集内排序）、`IdentityReranker`/`CrossEncoderReranker`、`RuleBasedSummarizer`/`LLMSummarizer`。

### Task 3 — 补全 cognitive twin builder [AC-7]
- 文件：`src/simple_harness_memory/cognitive/twin_builder.py`
- 修改：`build_twin_from_facts`（profile/skills/preferences/relationships/goals 映射）与 `detect_fact_conflicts`。

### Task 4 — 重构 backends 为共享 Base + 完整 Mock/SQLite [AC-2, AC-3]
- 文件：`src/simple_harness_memory/backends/{base.py,mock.py,sqlite.py}`
- 修改：`BaseMemoryBackend` 承载 facts 提取/召回/衰减/孪生体/摘要等共享逻辑；Mock/SQLite 只实现存储原语。

### Task 5 — 补全 world 世界对象 [AC-8]
- 文件：`src/simple_harness_memory/world/{events.py,geography.py,model.py,temporal.py,__init__.py}`
- 修改：`EventProvider`/`WeatherProvider`（noop/static/可选网络实现）、`WorldModel` 组合、`temporal` 修正时区偏移。

### Task 6 — 接线 MemoryManager [AC-8]
- 文件：`src/simple_harness_memory/core/manager.py`
- 修改：`MemoryManager.build` 接受 embedder/fact_extractor/reranker/world 并默认装配；`append_message` 触发 embedding；代理全部后端方法。

### Task 7 — 契约与模型收口 [AC-1]
- 文件：`src/simple_harness_memory/core/{port.py,models.py,twin.py}`
- 修改：补 `detect_inconsistencies` 到 Port、`SINGLE_VALUED_KEYS`/`FactConflict` 到 models。

### Task 8 — 测试 [AC-1..AC-8]
- 文件：`tests/unit/{test_embedders,test_facts,test_retriever,test_twin_builder,test_world}.py`、`tests/integration/{test_sqlite_backend,test_manager}.py`
- 修改：新增确定性 pytest 覆盖全部 8 条 AC。

### Task 9 — 机器门禁记账 [DoD]
- 文件：`plans/phase1-local-core/verification/<run-id>/`
- 修改：gate init + manifest + record-run（root pass/fail）+ finalize。
