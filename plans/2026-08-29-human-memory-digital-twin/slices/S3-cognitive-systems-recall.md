# S3 — 四类长期记忆、类型化召回与展示投影

> Release unit：S3（Memory SDK）  
> 高风险子系统：认知状态机、检索资格/排序、派生投影（3）  
> 覆盖：HM-AC-2/4/5/6/7/8

## 交付边界

在 S2 证据/审计底座上实现 Episode、Semantic、Procedure、Prospective 和五天 Short-Horizon Index。Working
Memory 只以 RecallDecision/ContextFragment 表达，不建长期表。数字孪生体只输出可视图数据，不提供 Agent 查询口。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `core/cognitive.py`（新） | 四类 record/state/epistemic/conflict/verification DTO、EvidenceSpan 与合法转换 |
| `core/mutations.py`（新） | MemoryMutationPlan validator、CAS、evidence entailment/ownership、apply receipt |
| `core/recall.py`（新） | RecallPlan validator、eligibility gate、typed candidates、minimal selection/decision |
| `core/prospective.py`（新） | trigger normalization/evaluation 与候选状态转换，不执行外部动作 |
| `core/manager.py`, `core/port.py` | 公开 apply/recall/trigger/feedback/twin graph/read-view API |
| `backends/sqlite.py` | episode/claim/procedure/prospective/evidence link/relation/short-horizon/projection tables |
| `features/{retriever,lexical,rrf,reranker}.py` | 从 Message/Fact Top-K 改为 typed candidate pipeline |
| `cognitive/twin_builder.py` | Fact 聚合改为 canonical relation graph projection |
| `features/facts.py` | 移除 free-form Chat Completions parser；提取器只消费 S1 strict payload |
| `tests/{unit,integration,artifact}/` | 状态机、资格门、质量集、性能、consumer wheel |

## Tasks

### Task 1 — 四类 canonical state 与独立认知维度 [HM-AC-2/5]

- Episode：span/thread、参与者/目标/行动/结果/影响、active/amended/disputed 与 raw evidence refs。
- Semantic Claim：`lifecycle_state`、`epistemic_status`、`conflict_status`、`verification_state`、valid interval 分列；
  同值加 evidence、多值并存、明确纠正 supersede、含糊 contested、inference 不得覆盖 explicit_user。
- Procedure：draft/eligible/active/reinforced/revised/inapplicable/superseded；适用环境、步骤、风险等级、成功/失败 evidence。
- Prospective：candidate/pending/triggered/in_progress/completed/rescheduled/cancelled/expired；行动与 typed trigger 分开。
- `EvidenceSpan` 固定 evidence/item ID、canonical UTF-8 byte offsets、exact quote、source/quote hash、normalization version、
  actor/source provenance 和 support kind；typed observation 另带注册 schema、JSON Pointer/value hash。
- 验证：表驱动合法/非法转换、历史有效期、冲突、重复证据、状态原子性。

### Task 2 — Strict MemoryMutationPlan 校验与混合提取 [HM-AC-2/7/8]

- 主模型 tool payload 只提出 operation；validator 验证 schema/长度、principal、EvidenceSpan offset/hash/ownership、base revision、
  epistemic 限制、suppression、状态转换和 idempotency。
- 确定性代码不宣称证明开放自然语言 entailment：普通模型规范化 claim 保持 candidate/unverified；exact explicit-user
  assertion 可带原句/来源 active；注册 typed tool observation 才可 verified；inferred 永不覆盖 explicit/observed。
- correction/supersede 校验 target revision/relation；ambiguous target 或 contradictory evidence 转 contested 并要求确认。
- 用户明确 remember/correct/forget 从 Host immediate outbox 高优先执行；普通 committed groups 按 S2 durable batch 异步。
- Episode 只在任务/目标/决定/行动结果/纠正等长期事件形成；普通寒暄只留 evidence。事件 span 必须连续可校验。
- 每项 accepted/rejected 与 before/after state 在同事务记 decision；任何非法项不留下半 supersede/孤立 edge。
- 验证：五类 LLM 载荷变异、无 evidence/inference-as-fact、混合 batch 部分非法时全计划或逐操作既定原子策略。

### Task 3 — Procedure 与 Prospective 一等规则 [HM-AC-5]

- explicit “以后都这样”可直接 active（只代表记忆状态，不授予执行权限）。观察的低风险可逆程序：1 个成功 terminal
  Run 为 draft，2 个不同 TaskScope/terminal receipt 为 eligible，3 个不同 TaskScope 在 rolling 90 days 且相同 procedure
  revision/applicability fingerprint 才 auto-active；同 TaskScope/retry/replay 最多计一次。
- 任一可归因失败、user correct/revoke、tool/schema/version 或 applicability drift 立即阻止使用并转 revised/inapplicable/
  superseded；旧 revision 不自动复活，新 revision 重新累计。发布/删除/付款/权限等高风险 observation 永不 auto-active。
- Procedure 使用前检查 tool/environment/version applicability；失败或漂移转 revised/inapplicable/contested。
- Prospective 只有明确 action+trigger 可 pending；无 trigger 为 candidate；模糊愿望改为 Semantic Goal；LLM inference
  不得 pending。canonical state 以 durable registration/invalidation outbox 投影给 Host 唯一 scheduler；Memory 不启动第二时钟。
- 验证：发布/删除/付款/权限负例，跨任务独立证据，时间/事件 trigger replay/reschedule/cancel/expire。

### Task 4 — 五天 Short-Horizon Conversation Index [HM-AC-4/6/8]

- 对超过最近 10 causal groups 且 age≤5 days 的 immutable evidence 建 chunk；保留 roles/order/task/entity/time/source refs。
- FTS5 + embedding candidate + recency/task/entity affinity；最近窗口 evidence 去重；到期只移除派生 index。
- 按 V0 `SPIKE-VECTOR` 已冻结的 backend/容量/降级策略实现；统一 `VectorIndexPort` 仅在 spike 证明需要第二实现时保留，
  否则内联 SQLite repository。不得在实现时改变 corpus、oracle 或阈值。
- V0 选择：SQLite metadata/FTS5 + rebuildable numpy float32 generation cache exact scan（numpy 已是依赖）；100k×64
  cache≈25.6 MB。cache cold open/first query 和 warm p95 过门；打不开或超 deadline 时只用 permission-filtered
  FTS/entity/time candidates 并记录 `VECTOR_DEGRADED`，绝不读取 stale generation。
- 验证：五天边界、cross-task similar entity、index delete/rebuild、suppressed row、p95≤500ms/hard deadline 2s；V0
  synthetic backend 结果不替代 S3 真实 embedding/200-query semantic quality gate。

### Task 5 — Typed RecallPlan 与资格门 [HM-AC-4/7/8]

- RecallPlan 指定 memory types、task/time/entity/event constraints、item/byte/token budget；Host 注入并覆盖完整
  `DisclosureContext`/identity，模型字段只能进一步收窄。
- pipeline：validate→permission/status/suppression/expiry filter→per-type candidates→typed rank→dedupe/conflict/minimal
  selection→durable RecallDecision。普通 memory 跨 TaskScope 全局可候选但记录 cross-scope provenance。
- task depends on contested fact 时返回双方+确认需要；不依赖时不投影。no_recall 不进入本 API。
- 验证：冻结 route set；hard-trigger/隐私禁止 100%，required type≥90%，no extra type≤15%，预算/deadline。

### Task 6 — Display-only digital twin graph [HM-AC-6/7]

- `twin_builder.py` 从 canonical active/contested/inferred records 和 relation rows生成 node/edge DTO，节点包含 type/status/
  confidence/source refs/correction-forget capability；superseded/suppressed/expired 按普通 view policy 不展示。
- public port 只叫 `get_twin_graph_view`，不实现 recall/rank/context conversion；在代码与测试中建立禁止依赖：Agent
  runtime/Recall pipeline 不 import twin projection。
- 验证：纠正/forget/rebuild 后图更新；敏感 label/edge/tooltip 不泄露；graph payload hash 可重建。

### Task 7 — SDK 质量、审计与 wheel 门 [HM-AC-7/8]

- 提供按 turn/invocation/memory/decision 的 trace 和 privacy-safe aggregate metrics。
- 更新 public API/schema/ARCHITECTURE/PROJECT_STATUS/CHANGELOG；构建 exact wheel 与 S1 fake Host consumer。
- 全量 unit/integration/artifact；性能与真实主模型评估原始证据写 `.local-test-evidence` 对应目录，Git 只存 hash/index。

## 验证出口

- 四类状态机、mutation/recall fault matrices、suppression side-channel、short-horizon rebuild、graph isolation 全绿。
- 质量集必须达到 acceptance 阈值；若真实主模型达不到，S3 BLOCKED，不通过调整 oracle 规避。
