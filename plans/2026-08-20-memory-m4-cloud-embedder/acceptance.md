# 验收标准：simple-harness-memory-sdk 0.2.0 第四部分 — 云端 embedding adapter（M4）

> 状态：DRAFT（待用户确认）
> 仓库：`simple-harness-memory-sdk`
> 来源：SDK 生产化 program Slice M4；用户决定"手机用云端向量，不跑本地大模型"
> 版本：0.2.0 内

## 范围

**包含**（无 schema 迁移；新增 embedder，不动既有 Embedder 协议）：

- `CloudEmbedder`：async embed + 批量 + 缓存 + 超时/重试 + fail-closed
- `OpenAICompatibleClient`：httpx 调 OpenAI-compatible `/embeddings` 端点
- 凭证安全：api_key 不进日志/repr/异常
- factory `get_embedder("cloud", ...)` 集成

**明确不包含**：
- 本地 BGE-M3（已由 M1 移除 auto 加载，M4 不恢复）
- 宿主 re-vendor（C1）

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 优先级 |
|----|--------|-------------------|--------|
| M4-AC-1 | CloudEmbedder async + 批量 + 缓存 | `CloudEmbedder` 实现 async `embed`/`embed_batch`；`embed_batch` 一次性批量调用 client（非逐条）；同文本返回同向量（LRU 缓存，`cache_size` 上限，超出逐出最旧） | 必须 |
| M4-AC-2 | 超时 + 重试 + fail-closed | client 失败时按 `retries` 重试（可配，带指数退避），耗尽后抛 `EmbeddingError`（fail-closed，**不内置静默降级**——静默把 hash 伪向量标成 cloud 会混入云端 cosine 空间） | 必须 |
| M4-AC-3 | 凭证安全 | `api_key` 不出现在 `repr`/`str`、任何日志、任何异常消息中（值级断言，非字面量 grep） | 必须 |
| M4-AC-4 | OpenAICompatibleClient | `OpenAICompatibleClient(base_url, api_key, model, dim)` 用 httpx 调 `/embeddings` 返回归一化向量；`dim` 与返回维度校验 | 必须 |
| M4-AC-5 | factory 集成 | `get_embedder("cloud", base_url=..., api_key=..., model=..., dim=...)` 返回 `CloudEmbedder`（内部用 OpenAICompatibleClient，dim 必填）；缺 httpx 依赖时抛 `ImportError` | 必须 |

## 非功能 / 边界

- **凭证**：api_key 由调用方注入，SDK 不持久化、不写日志、不进 repr/异常（M4-AC-3）
- **离线降级**：CloudEmbedder **不内置**离线回退（fail-closed 抛 EmbeddingError）；离线场景由调用方**显式**使用 HashEmbedder（kind="hash"，lineage 正确记录），不静默把 hash 向量标成 cloud
- **依赖**：CloudEmbedder 核心不依赖 httpx；OpenAICompatibleClient 依赖 httpx（optional import，缺失时 ImportError）
- **幂等**：缓存使同文本幂等；网络重试对纯 embed 无副作用

## 适用性声明（APPLICABILITY_DECLARATION）

- `input_sensitive=true`：**向量化会把用户记忆内容原文外发到云端 provider**（隐私敏感）。测试用 mock client / httpx.MockTransport，不真发真实用户数据。
- `llm_payload_driven=false`：无 LLM 输出驱动端侧状态机。
- `stateful_init=false`：无异步注册服务/登录态依赖。

## 测试义务矩阵（Test Obligation Matrix）

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---------------|------|-------|------|-------------------|-----------------|
| TO-M4-1 | delivery | M4-AC-1 | — | mock client 断言 batch 一次调用 + 缓存命中同向量 | 证明 async + batch + 缓存 |
| TO-M4-2 | delivery | M4-AC-2 | — | client 抛错 **或超时** retries 次（带退避）后均抛 EmbeddingError | 证明重试（异常 + 超时两分支）+ fail-closed |
| TO-M4-3 | delivery | M4-AC-3 | — | 注入哨兵 api_key 值，断言其不出现在 repr/str/异常/factory 日志 | 证明凭证安全（值级，非字面量 grep） |
| TO-M4-4 | delivery | M4-AC-4 | — | httpx.MockTransport 断言请求 URL/body + 返回向量 | 证明 OpenAI 兼容调用 |
| TO-M4-5 | delivery | M4-AC-5 | — | get_embedder("cloud", base_url/api_key/model/dim 全给) 返回 CloudEmbedder；缺任一抛 ValueError | 证明 factory 集成 + fail-closed |

## 完成的定义（DoD 摘要）

1. 5 条 M4-AC 全部通过测试
2. 所有 delivery obligation 有对应 PASS testcase
3. `simple-harness-memory-sdk` git status 干净、CHANGELOG 更新
4. 全量 pytest PASS
5. gate finalize exit 0，receipt 入账
