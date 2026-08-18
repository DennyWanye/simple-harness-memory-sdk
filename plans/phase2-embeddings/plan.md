# Plan：slice 2 — [embeddings] BGE 接入

## 主要矛盾
BGE-M3 语义向量是可选重依赖（torch + sentence-transformers，约 2GB）。本 slice 只做
**接入接线**：工厂按 kind 选择 hash/BGE，缺依赖优雅回退，真实模型权重下载另议。

## 关联验收标准
覆盖 AC-9、AC-10、AC-11。

## 任务清单
### Task 1 — Embedder 工厂 [AC-9, AC-10]
- 文件：`src/simple_harness_memory/embedders/factory.py`
- 修改：`get_embedder(kind)`：hash/mock → HashEmbedder；bge → BGEM3Embedder（缺依赖抛 ImportError）；auto → 优先 BGE、缺依赖回退 hash；未知抛 ValueError。

### Task 2 — MemoryManager 接线 [AC-11]
- 文件：`src/simple_harness_memory/core/manager.py`
- 修改：`build(embedder=...)` 支持字符串 kind，内部经 `get_embedder` 解析。

### Task 3 — 测试 [AC-9..AC-11]
- 文件：`tests/unit/test_embedders.py`、`tests/integration/test_manager.py`
- 修改：工厂返回类型 / auto 回退 / bge ImportError / 未知 ValueError / manager embedder 注入。
