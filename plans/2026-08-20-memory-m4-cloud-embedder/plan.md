# Plan：simple-harness-memory-sdk 0.2.0 第四部分 — 云端 embedding adapter（M4）

## 主要矛盾

决定成败的核心问题：**实现 provider 无关的 CloudEmbedder（async + 批量 + 缓存 + 超时/重试 + fail-closed），并确保凭证值级不泄露、维度不漂移、不静默混入伪向量空间**。风险最高的是 Task 1（无静默降级——网络失败 fail-closed，否则 hash 伪向量混入 cloud cosine 空间）与 Task 3（凭证值级安全，非字面量 grep）。

## 关联验收标准

覆盖 M4-AC-1（Task 1）、M4-AC-2（Task 1）、M4-AC-3（Task 3）、M4-AC-4（Task 2）、M4-AC-5（Task 4）。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|------|------|----------|
| 新增 `src/simple_harness_memory/embedders/cloud.py` | CloudEmbedder + EmbeddingClient protocol | Task 1：async embed/batch + 缓存 + 重试 + fail-closed |
| 新增 `src/simple_harness_memory/embedders/openai_compatible.py` | OpenAI 兼容 HTTP client | Task 2/3：httpx /embeddings + 凭证安全 |
| `src/simple_harness_memory/core/errors.py` | 错误 | Task 1/2：新增 `EmbeddingError` |
| `src/simple_harness_memory/embedders/factory.py` | embedder 工厂 | Task 4：get_embedder("cloud") |
| `src/simple_harness_memory/embedders/__init__.py` | 导出 | Task 4：导出 CloudEmbedder/OpenAICompatibleClient/EmbeddingError |
| 新增 `tests/unit/test_cloud_embedder.py` | 测试 | mock client / httpx.MockTransport / 凭证 sentinel |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / 绑定 |
|-----------|:---:|------------|
| 新依赖 | 否 | httpx 已是 optional extra；CloudEmbedder 核心不依赖 httpx |
| 新公共 API | 是 | `CloudEmbedder` / `OpenAICompatibleClient` / `EmbeddingError` |
| 新持久化状态 | 否 | 缓存是内存态，不落盘 |
| 新抽象层 | 是 | `EmbeddingClient` protocol |
| 公开接口破坏 | 否 | 新增 embedder + 新错误类型，不改既有签名；**保留 `kind="auto"` 默认** |

## Assurance / 信任与失败边界

- Profile：standard；input_sensitive=true（记忆内容外发云端，测试不真发）。
- 范围内失败：FAIL-1 凭证泄露 / FAIL-2 网络失败崩溃 / FAIL-3 维度漂移 / FAIL-4 缓存错。
- 停止追踪点：不做本地 BGE（OOS-1）。

---

## 任务清单（按依赖排序）

### Task 1 — CloudEmbedder（async + 批量 + 缓存 + 重试 + fail-closed）  [M4-AC-1, M4-AC-2]
- 改动文件：新增 `embedders/cloud.py`、`core/errors.py`、新增测试
- 修改方式：
  1. `core/errors.py` 加 `EmbeddingError(RuntimeError)`（**challenger 校正：该类型此前不存在**）。
  2. `embedders/cloud.py`：
     - `EmbeddingClient` protocol：`async def embed(self, texts: list[str]) -> list[list[float]]`。
     - `CloudEmbedder(Embedder)`：`__init__(client, *, model, dim, cache_size=1024, retries=2, timeout=30.0)`；`kind="cloud"`、`dim` 属性。
     - `embed(text)` = `(await embed_batch([text]))[0]`；`embed_batch(texts)`：LRU 缓存（OrderedDict）命中直接返回；未命中 → `asyncio.wait_for(client.embed(missing), timeout)`，超时/异常 → **指数退避重试 `retries` 次**（backoff = 0.5 * 2^n）；耗尽 → **抛 `EmbeddingError`（fail-closed，无静默降级）**；成功后写缓存。
     - **`__repr__` 只显示 model/dim，不含 client 的任何字段**（避免透传 api_key）。
  3. **无 fallback 参数**（challenger P0：静默把 hash 向量标 cloud 会混入 cosine 空间；离线降级由调用方显式用 HashEmbedder，kind="hash" 正确记录）。
- 验证：mock client 断言 ① batch 一次调用 ② 缓存命中同向量不重调 ③ 抛错 retries 次（带退避）后抛 `EmbeddingError`。
- 依赖：无

### Task 2 — OpenAICompatibleClient  [M4-AC-4]
- 改动文件：新增 `embedders/openai_compatible.py`、新增测试
- 修改方式：
  1. `OpenAICompatibleClient(base_url, api_key, model, dim)` 实现 `EmbeddingClient`。
  2. `embed(texts)`：`async with httpx.AsyncClient() as client`（**每次 embed 用 async with，避免连接泄漏，无需 aclose**）POST `{base_url}/embeddings`，body `{"model": model, "input": texts}`，header `Authorization: Bearer <api_key>`；解析 `data[].embedding`。
  3. `dim` **必填**（非 None）：校验返回向量长度 == dim，不符抛 `EmbeddingError`（维度漂移 FAIL-3）。
  4. httpx optional import，缺失抛 ImportError。
- 验证：httpx.MockTransport 断言请求 URL/body/header + 返回向量解析 + dim 不符抛错。
- 依赖：Task 1（EmbeddingError 已在）

### Task 3 — 凭证安全  [M4-AC-3]
- 改动文件：`embedders/openai_compatible.py`、`embedders/cloud.py`、`embedders/factory.py`
- 修改方式（challenger 校正：值级安全，非字面量 grep）：
  1. `OpenAICompatibleClient.__repr__`/`__str__` 只显示 base_url/model/dim，**不含 api_key**。
  2. 捕获 httpx 异常时，异常消息**不含 request/header 的 repr**（`f"embedding request failed: {type(exc).__name__}"`，不 `f"{request!r}"`）。
  3. `CloudEmbedder.__repr__` 只显示 model/dim，不显示 client。
  4. `factory.py` 的 cloud 分支 `logger.info` 只记 kind/model/dim，**不记 base_url/api_key**。
- 验证：注入哨兵 api_key 值（如 `"sk-SENTINEL-123"`），断言该值不出现在 `repr(client)`/`str(client)`/`repr(cloud)`/异常消息/工厂日志（值级断言，非 grep "api_key"）。
- 依赖：Task 2

### Task 4 — factory 集成  [M4-AC-5]
- 改动文件：`embedders/factory.py`、`embedders/__init__.py`
- 修改方式（challenger 校正：保留 kind="auto" 默认，cloud 参数仅 cloud 分支）：
  1. `get_embedder(kind="auto", *, dim=None, base_url=None, api_key=None, model=None, cache_size=1024, retries=2, timeout=30.0)`：`kind=="cloud"` 分支校验 base_url/api_key/model/dim 均非 None（**cloud 必填，dim 用 None 哨兵，不设 256 默认**），缺任一抛 ValueError（fail-closed 仅限 cloud 分支）；hash/mock/auto 分支 `dim=None` 时回落到默认 256。构建 `OpenAICompatibleClient(base_url, api_key, model, dim)` + `CloudEmbedder(client, model=model, dim=dim, ...)`（**同一 dim 传两者**）。
  2. `embedders/__init__.py` 导出 `CloudEmbedder`、`OpenAICompatibleClient`、`EmbeddingError`。
- 验证：`get_embedder("cloud", ...)` 返回 CloudEmbedder 且 dim 正确传递；缺参抛 ValueError；`get_embedder()`（无参）仍返回 HashEmbedder（auto 默认不破坏）。
- 依赖：Task 1/2

## 出口

- 5 条 M4-AC 全部有任务覆盖、7 个 challenger findings 已闭环 → 进入 round 2 diff 复审。
