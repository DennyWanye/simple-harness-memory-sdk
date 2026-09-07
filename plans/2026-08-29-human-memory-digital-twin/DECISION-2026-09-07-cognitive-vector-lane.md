# 裁决：长期认知记忆同义查询不命中（C01 召回率 73.7%）的修复方案

> **独立子代理裁决，主代理复核后执行。** 2026-09-07。只读调查，未改任何代码、未跑重型测试。
> 行号以 Memory SDK 源 `67b176d`（0.6.22 候选）与 Host main（pin M0.6.22 / H0.7.10）为准。

## 0. 一句话结论

**采纳方案 A：在 Memory SDK 内为长期认知记忆补一条真正的向量通道**（写入侧按"世代"批量嵌入 public payload 文本，召回侧在现有资格门之后、现有排序之前加一条 `vector` lane），出 **0.6.23 候选**；Host 需两处一行级改动并重 pin。B/C/D 均不采纳，理由见 §4。

## 1. 事实核查（问题 1：SDK 认知记忆是否已有 embedding）

**没有。** 认知记忆四张类型表只存结构化 payload，从未产生或存储向量：

| 事实 | 位置 |
|---|---|
| semantic 写入只 INSERT `semantic_claims(memory_id,revision,subject_entity,predicate,object_json,object_hash,qualifiers_json)`，无嵌入调用 | `src/simple_harness_memory/backends/sqlite_v5.py:9676-9688` |
| 整个 `sqlite_v5.py` 里 `embed`/`embed_batch` 只出现在短时域世代重建 | `sqlite_v5.py:2404-2405`（唯一的 `embedder.embed_batch`）、`:2968`（唯一的查询 `embed`） |
| schema 里的向量表：`embedding_lineages`(486)、`embedding_generations`(498)、`evidence_vectors`(510，`sqlite_v5.py` 零引用，遗留)、`short_horizon_generations`(1461)、`short_horizon_vectors`(1473)。**没有任何 cognitive_* 向量表** | `backends/schema_v5.py` |
| typed recall 对"请求 vector 且带 requested_memory_types"的计划**无条件**追加 `cognitive_vector_unavailable`，且该码被现有测试钉死为"持久化退化而非 unsupported" | `sqlite_v5.py:3240-3245`；`tests/integration/test_typed_recall_v6.py:804-842` |
| 认知候选收集只有四条 lane：`full_text`(词面计数)、`entity`、`task_scope`、`temporal`；lane 循环硬编码 `("full_text","entity","task_scope","temporal")`；**四条都不命中的记忆直接丢弃**（`if not lane_values: continue`） | `sqlite_v5.py:4700-4725`, `:4762` |
| 词面门 = `canonical_json(payload).casefold().count(term)`，term 来自 `typed_recall_query_terms`（`\w` 词项 + CJK 二字组合，0.6.20 修复） | `sqlite_v5.py:4682,4703-4704`；`features/lexical.py:49-68` |
| confirmation 门再次用同一词面规则算 `query_match = lexical_score > 0` | `sqlite_v5.py:4278-4281` |
| RRF 权重表**早已预留** `"vector": 0.40`（full_text 0.30 / entity 0.15 / task_scope 0.10 / temporal 0.05），`SUPPORTED_RETRIEVAL_MODES` 含 `vector`，即"vector 是受支持能力但认知侧从未实现" | `core/recall.py:26-37`, `:233-248` |
| 短时域向量通道是完整参照实现：世代重建（`embed_batch(public_text)` → `short_horizon_vectors` + lineage + 唯一 active 世代 + audit）；查询侧在 deadline 内嵌入查询、留 audit 预留、`_ExactVectorGenerationCache.exact_search` 精确余弦、与 fts/entity 做 RRF；退化码 `VECTOR_DEGRADED/NO_ACTIVE_GENERATION/STALE_ACTIVE_GENERATION/DEADLINE_EXCEEDED` | `sqlite_v5.py:2344-2470`（重建）、`:2930-2990`（查询）；`core/short_horizon.py:43-47`（退化码）、`:460-540`（numpy 精确扫描缓存） |
| 生产 embedder 只有一个：Host `WeMMEmbedder`（kind `wemm`、2048 维、本地快照、懒加载、有 warmup），经 `embedder_getter` → `build_kwargs()["short_horizon_embedder"]` 传给 SDK；hash/mock 被守卫为 None | Host `backend/main.py:3298-3307`, `:8391`；`deskpet/memory/human_memory_v7.py:174-179`；`deskpet/memory/wemm_embedder.py:30-215`；SDK `core/manager.py:559-585` |

## 2. Host 侧 RecallPlan 与 C01-10 无退化标记的原因（问题 2）

- `retrieval_modes` 由 Host `HumanMemoryV7Runtime.execute_typed_recall` 固定生成：`(FULL_TEXT, *(VECTOR if typed_short))`，即**只有模型在 `context_route` 里设 `include_short_horizon=true` 时才请求 vector**（注释明说是为了让短时域 vector-only 组不被丢弃）——`deskpet/memory/human_memory_v7.py:400-416`。模型可控的只有 `query / memory_types / include_short_horizon`（`deskpet/sdk_adapters/context_route.py:66-79`）；`semantic_correction.py:162` 的内部计划固定 FULL_TEXT。
- 证据：`run-01/C01-10/scoring/C01-10/observation-route_audit.json` → `recall_selection.include_short_horizon=false`，plan 只有 FULL_TEXT，所以 `degradation_codes=[]`；C01-17/C01-06 的 route_audit 全部 `include_short_horizon=true`，6/11 次调用一律 `["cognitive_vector_unavailable","NO_ACTIVE_GENERATION"]`（后者是短时域无 chunk，无前序对话时正常）。
- C01-10 命中纯属词面巧合：查询"待办排序约定"切出二字组"待办"，命中 qualifier `["待办清单"]`。其它 FAIL 的 payload 与查询零重叠（seed 见 Host `deskpet/quality/corpus_c01.py:52-71`）：

| 用例 | 存储 payload（predicate / object / qualifiers） | 模型实际查询（trace） | 词面结果 |
|---|---|---|---|
| C01-06 | `preferred_name` / "小周" / `()` | "用户最后明确确认的称呼、称谓偏好" ×11 次改写 | 0 |
| C01-07 | A `reply_closing` / "不要以“还有什么可以帮你”收尾" / `()` | "我对结尾客套话的约定…表达偏好" | A 0；B `ordinary_politeness`"一般礼貌**表达**不受禁止"误中 |
| C01-12 | A `work_contact_hours` / "09:00–17:00" / `()` | "用户平时允许安排工作联系的时段…不使用同事排班" | A 0；B qualifier"**同事**"误中（召回了明确被排除的记忆） |
| C01-17 | `email_draft_length` / "最多两段" / `("邮件草稿",)` | "通知段落格式…" ×6 次改写 | 0（"两段"≠"段落"） |
| C01-19 | `explanation_order` / "先说结论再说理由" / `()` | "先报结果还是先铺背景" | 0 |

  结论：词面门既漏召（A 全漏）也误召（C01-07/12 的 B），且模型多次改写查询（C01-06 四种不同措辞、C01-17 六种）全部失败——**这是查询扩展（方案 C）已在真实运行中被证伪的直接证据**。

## 3. 候选方案比较（问题 3）

| 维度 | A. SDK 认知向量通道 | B. 词面门同义/字符级模糊 | C. Host 查询扩展/重试改写 | D. A+B 或 A+C 组合 |
|---|---|---|---|---|
| 召回≥90% | **可达**：5 个 FAIL 全是语义同义（称呼↔称谓、段落格式↔邮件草稿最多两段、工作联系时段↔work_contact_hours 09:00–17:00、先报结果↔先说结论）；WeMM 双语模型可桥接英文 predicate | 不可达：单字模糊可救"称呼/称谓"，救不了"两段↔段落格式""先报结果↔先说结论"、英文 predicate；同义词典无界且中文特有 | 已被证伪：C01-06/17 共 17 次不同改写全部 0 命中 | 与 A 等价，只多带 B/C 的风险 |
| 隐私 100% | **不变**：vector 只在 L4636-4700 全部资格门（状态/类型权限/血缘/抑制/scope/entity/时间/disclosure）之后作为一条 lane 加分；短时域已证明同一模式可审计 | 单字/模糊会放大误召（C01-12 已因"同事"误召被排除记忆） | 不变 | 同 A |
| 多提类型≤15% | 不变（该指标是模型选 `memory_types`，不是候选数）；需加余弦阈值防 C07 零召回类出现假阳性 | 恶化风险（误召增多） | 不变 | 同 A |
| 401 矩阵/资格门/可审计性 | 资格门零改动；新增退化码与世代 hash 落 `typed_recall_terminals`/audit，与短时域同构；DDL 为附加式 7.4，需 401 runner 重 pin（常规） | 改词面规则会漂移全部 401 cell 的 lexical 期望；不可解释 | 无 SDK 变化，但每轮多 N 次 Provider 调用 | A 的风险 + B/C 的风险 |
| 实现规模 | SDK：1 个附加 schema 模块 + `sqlite_v5.py` 约 4 处（重建方法、缓存加载、typed recall 集成、lane 循环）+ manager 1 个公共方法；新增约 10 项测试、改写 1 项、快照 1 份。Host：2 处一行级 + pin | SDK 小改但需词典维护 | 仅 Host 提示词/循环逻辑 | 最大 |
| 是否同时发版 | **是**：SDK 0.6.23 + Host 改 `retrieval_modes` 与 worker 一行 + pin（Host 不改则认知 vector 只在 include_short_horizon=true 时生效） | 仅 SDK | 仅 Host | 是 |
| 与 F03（空召回循环止损，用户已延期） | **正向**：首次调用即命中，循环自然消失；F03 只剩"真无记忆"场景 | 无关 | **与 F03 对冲**：本质是把循环制度化 | — |

## 4. 唯一推荐与不采纳理由（问题 4）

**推荐 A。** 不采纳 B：中文同义与英文 predicate 无法靠字面桥接，且会加重误召。不采纳 C：真实 trace 里 17 次改写已全部失败，且与用户延期的 F03 循环止损方向相反。不采纳 D：A 单独已足够，组合只增加 401 矩阵漂移面。

### 4.1 设计要点（对齐短时域现有模式，不发明新机制）

1. **嵌入文本**：新增确定性纯函数 `cognitive_vector_text(memory_type, public_payload)`（放 `core/recall.py` 或新 `features/cognitive_vector.py`）：semantic = `subject_entity + predicate.replace("_"," ") + object_value + qualifiers`；episode = title/goals/actions/results；procedure = name/applicability/steps；prospective = action/trigger。输入即 `_cognitive_public_payload_unlocked`（`sqlite_v5.py:5003-5063`）的公开 payload，不引入任何非公开字段。
2. **写入侧 = 世代重建，不在 mutation 写锁内嵌入**：`apply_memory_mutation_plan` 全程持 `_write_lock`（`sqlite_v5.py:6480,6503`），WeMM 冷加载约 8s（Host GENERATION.md），不能内联。新增 `rebuild_cognitive_vector_generation()`（镜像 `rebuild_short_horizon_generation` `:2344-2470`）：取所有可召回 head（`cognitive_memory_heads` JOIN 当前 revision，复用 `_cognitive_recall_state_allowed`）→ manifest hash(memory_id, revision, content_hash) → 同 lineage 同 manifest 已 active 则 replay → 否则 `embed_batch` → 写新表 → 原子激活、旧世代 retire → audit。
3. **DDL 附加式 7.4**：新 `backends/schema_v7_4.py`，`DDL = schema_v7_3.DDL + …`，加 `cognitive_vector_generations`（同 `short_horizon_generations` 形状 + 唯一 active 部分索引）与 `cognitive_vectors(memory_id, revision, generation_id, embedding, embedding_hash, dimension)`，lineage 复用 `embedding_lineages`；`SCHEMA_VERSION_LABEL='7.4'`，`REQUIRED_TABLES` 并集。遵循 7.3 的"7.2 checksum 冻结、旧库前向"规则（`schema_v7_3.py:1-70`）。
4. **召回侧**：
   - 查询向量在**取 `_write_lock` 之前**算：`execute_typed_recall` 里 `prepare_history_source_context` 同段（`:3350-3365`），复用短时域的 deadline 减 audit 预留写法（`:2955-2975`）；失败/超时 → 退化码，词面继续。
   - `_collect_typed_recall_candidates(..., query_vector, generation_cache)`：在 L4700 的 `lane_values` 处追加 `("vector", cosine)`，条件 `cosine ≥ COGNITIVE_VECTOR_MIN_SCORE`（SDK 冻结常量，建议初值 0.45，由 C07 零召回子集回归校准）；lane 循环 `:4762` 加 `"vector"`；`lane_cap` 复用。`eligible_refs` = 已过全部资格门的 (memory_id, revision)，抑制/遗忘的记忆永远不进向量比对（与短时域 `eligible_refs=frozenset(universe_by_ref)` 同构）。
   - 缓存：复用 `core/short_horizon._ExactVectorGenerationCache`（`:460-540`），ref 用 `f"{memory_id}:{revision}"`；active 世代 manifest ≠ 当前 head manifest → `cognitive_vector_stale` 退化并跳过 vector lane（镜像 `STALE_ACTIVE_GENERATION`）。
   - **退化码语义变更**：`cognitive_vector_unavailable` 仅在"请求 vector 但 backend 无 embedder"时出现；新增 `cognitive_vector_no_generation`、`cognitive_vector_stale`、`cognitive_vector_deadline`。全部落 `typed_recall_terminals.degradation_codes_json`，并把 generation id 的 opaque hash 写进 typed recall audit（同 `:3040-3070` 的 `vector_lane/used_generation_id_hash`）。
   - **confirmation 门**（`:4278-4281`）必须同步：`query_match` 对 vector 选中的项要接受（否则向量命中在确认阶段被词面门二次否决）。实现时把 lane 命中来源随候选传入，而非重算词面。
5. **公共面**：manager 暴露 `rebuild_cognitive_vector_generation()`；不加新 builder kwarg，认知向量与短时域共用 `short_horizon_embedder`（生产只有一个 WeMM；`test_public_api_snapshot.py:136-139` 按参数名断言，不受影响）。新增 `tests/artifact/public-api-0.6.23.json`（根导出零增减，新增方法可达性只读核对）。

### 4.2 Host 改动（两处一行级 + pin）

- `deskpet/memory/human_memory_v7.py:412`：`retrieval_modes` 改为 `(FULL_TEXT, VECTOR)` 恒定（认知 vector 不再依赖 `include_short_horizon`）；短时域是否执行仍由 `typed_short` 决定，不受影响。
- `deskpet/memory/short_index_worker.py:112` 后追加 `await manager.rebuild_cognitive_vector_generation()`（同一 `operation_timeout`、同一 `_generation_pending` 重试语义）。该 worker 由 `memory_ingestion_outbox.py:430,445` 每 tick 驱动，语料跑道 `corpus_runtime.drain()` 会经过它；实施时需实证 seed 后、评分轮前世代已 active，否则在 `corpus_scoring_session.py` seed 后显式调一次。
- pin：`backend/pyproject.toml:170,186`、`deskpet/sdk_adapters/sdk_candidate.py:32-35`、vendor wheel；401 runner 重 pin（RESUME-2026-09-07 已把它当常规动作）。

### 4.3 测试（SDK 新增约 10 项 + 改写 1 项）

1. `tests/integration/test_cognitive_vector_generation.py`（新）：空库 → empty 世代；构建/激活/replay 幂等；head 变化 → 新世代、旧世代 retire；lineage 变化 → 独立世代；audit 行。
2. `tests/integration/test_typed_recall_cognitive_vector.py`（新，用 `allow_development_embedder=True` + 可控确定性 embedder，如 `tests` 现有 fake 模式）：
   - 五种 C01 FAIL 形状（同义中文查询 / 英文 predicate + 纯值 payload）在 vector lane 下命中，词面 0；
   - 被抑制（遗忘）记忆有向量也**不**出现；disclosure 拒绝优先于 vector；
   - 阈值以下不进候选（C07 零召回负控）；
   - 世代 stale → `cognitive_vector_stale` 且词面照常；无 embedder → `cognitive_vector_unavailable`；查询嵌入超时 → `cognitive_vector_deadline`；
   - confirmation 门接受 vector 命中；
   - 退化码持久化到 `typed_recall_terminals`；plan 未请求 vector 时零向量副作用。
3. 改写 `test_typed_recall_v6.py::test_cognitive_vector_degradation_is_durable_not_unsupported`（`:804-842`）：无 embedder 分支保留 `cognitive_vector_unavailable`，有 embedder 分支断言新码。
4. schema：`test_memory_0623_schema_cutover.py` 钉 7.4 checksum、7.3 库打开前向、未知 checksum fail-closed（照 0.6.1/0.6.2 先例）。
5. 真实验收（不在单测里）：C01-06/07/12/17/19 + C01-10 回归 + C07 零召回 20 例重跑（校准阈值），记录到 Host `plans/2026-09-07-corpus-c01-local/`。

### 4.4 版本与发布

- **需要 0.6.23 候选**（有 DDL 7.4、新公共方法、退化码语义变更）；CHANGELOG 按 0.6.20-0.6.22 体例，标注"仅本地候选，未发布"。
- Host 与 SDK **同时发版**（Host 不改 `retrieval_modes` 则线上认知 vector 几乎永不触发）。
- 性能边界：typed recall 预算 `deadline_ms=1000`（Host `RecallBudget(8,16_384,2_048,1_000)`），查询嵌入受同一 deadline 与 audit 预留约束；Host 已有 WeMM warmup（`plans/2026-09-06-short-terminal-source/WARMUP.md`），冷态只退化不失败。

### 4.5 明确不做

- 不在 mutation 内联嵌入；不在召回时补写向量（召回必须只读）。
- 不改 `typed_recall_query_terms` 与四条既有 lane 的计分；不改资格门顺序。
- 不处理 F03 循环本身（用户已延期），但预期 A 落地后 C01-06/17 类循环自然消失，建议 F03 复评时以 A 后的 trace 为基线。
