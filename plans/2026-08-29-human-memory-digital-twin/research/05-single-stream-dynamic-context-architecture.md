# 单一主对话流与动态 Context 架构

> 状态：产品方向与单 ReAct Run 执行链已确认
> 日期：2026-08-30
> 适用范围：`simple-harness-memory-sdk`、`simple-harness-sdk`、`simple_harness` Host

## 1. 产品语义

用户只和一个永久存在的主对话交互，不再创建、选择、切换或整理 Session。这里的“一个 Session”是
用户体验，不等于把所有内部边界压成一张无限增长的消息表：

- 每个用户只有一个稳定的 `primary_conversation_id`，作为新对话证据的主时间线；
- 每次模型调用仍是独立 `Run`，保留模型、工具、输入输出、成本和结果审计；
- 系统自动维护不可见的 `TaskScope`，表达当前目标、项目、阶段和相关资源；
- Episode 仍是有长期价值的事件表示，并引用主时间线中的准确 turn span；
- 当前原型不承接任何旧数据；在全新数据库中从第一条 evidence 开始执行永久保留。

因此，`Session` 不再承担“任务容器 + 用户导航 + Context 全量历史”三种职责。新的职责拆分为：

| 需求 | 承载结构 |
|------|----------|
| 用户连续交谈 | `primary_conversation_id` |
| 当前模型调用 | `Run` |
| 任务隔离、恢复与切换 | `TaskScope` |
| 最近因果上下文 | 最近 10 个完整 turn group |
| 五天内的旧对话检索 | Short-Horizon Conversation Index |
| 长期认知记忆 | Episode / Semantic / Procedure / Prospective |
| 完整审计与复查 | append-only 原始 evidence + decision lineage |

## 2. 动态 Context 的真实边界

“最近 10 次对话 + 五天向量召回”可以显著约束 Context 增长，但不能保证 Context 字节数恒定。单个工具
结果、附件或一轮超长回答仍可能很大。因此最终边界必须是**分区 Token 预算**，10 轮和 5 天只是选择规则。

每次调用主模型时，Host 按如下顺序组装不可变 `ContextSnapshot`：

1. 受保护且不可挤出的 system / policy / persona / 当前用户 query；
2. 最近 10 个完整因果 turn group，而不是数据库中任意 10 条 message；
3. 从当前 `TaskScope` canonical state 临时选择的本轮必要状态；
4. 五天短时域索引按当前 query 和 TaskScope 找到的相关旧对话片段；
5. `RecallPlan` 请求并通过资格门的长期 Episode / Semantic / Procedure / Prospective；
6. 当前任务需要的 tool、skill、attachment 和运行状态；
7. 在总 Token 预算内完成去重、排序、裁剪和引用外置，冻结最终 snapshot 后调用模型。

大型 Tool Result 不应原样长期占据最近窗口。原始结果永久保存；Context 中保留简洁的 typed summary、
artifact reference、状态和必要摘录，主模型可在确有需要时 page-in 原文。

## 3. 五天短时域不是第六类认知记忆

Short-Horizon Conversation Index 是对不可变原始对话证据建立的**工程检索层**，不是新的认知类型：

- 输入：超过最近 10 个 turn group、且距当前不超过五天的对话与必要工具结果；
- 切块：保持 turn 因果关系，记录 user/assistant/tool 角色、时间、TaskScope、项目、实体和原始 evidence refs；
- 检索：向量语义 + 全文关键词 + 时间衰减 + TaskScope/项目/实体亲和度的混合排序；
- 去重：最近 10 轮已经在 Context 中的证据不能再次作为短时结果注入；
- 输出：最小充分片段和来源引用，不把检索摘要冒充原文；
- 到期：五天后只退出该派生索引，原始证据永久保留，符合条件的长期记忆也继续存在；
- 恢复：派生索引允许删除和重建，但任何原始 Session/Turn/Tool/LLM evidence 不允许物理删除。

现有 Memory SDK 的 SQLite message embedding 能力可以作为复用候选，但正式实现不能只对 FTS/最近候选
做 Python cosine 后就宣称是完整向量检索。计划阶段需用生产规模 spike 决定 SQLite 向量扩展、独立本地
向量索引或其他实现，并验证过滤、重建、延迟和包体兼容性。

## 4. TaskScope 是内部认知边界，不是新 Session UI

单一主对话中可能连续出现多个任务。若只用当前 query 做全库向量相似度，项目术语相近时会互相污染；
因此系统需要内部 TaskScope，但用户不必管理它。

建议由主 Agent LLM 在已经建立的正常流式调用中提出：

```text
TaskScopeDecision
  action: continue | create | switch | link | complete | reopen | standalone
  target_scope_id?: ...
  goal: ...
  project_refs: [...]
  evidence_refs: [...]
  confidence: ...
  ambiguity: ...

RecallPlan
  memory_types: [...]
  short_horizon_query?: ...
  task_scope_ids: [...]
  time/entity/event constraints: ...
  reason_codes: [...]
```

确定性代码负责 schema、主体、Scope、隐私、状态、预算和 evidence refs 校验，并保存最终
`TaskScopeDecisionRecord`、`RecallDecision` 与 `ContextAssemblyDecision`。低置信且会影响动作正确性时询问
用户；不影响当前回答时可继续，但不得把未确认 Scope 当成长期事实。

主模型不是在看到完整无限历史后才做判断。初始调用只接收当前 query、最近 10 个 turn group、当前/最近
TaskScope 的紧凑目录和必要硬触发；如果判断需要更多记忆，再通过工具召回并续推理。这样无召回轮次保持
单次模型生成，需要召回的轮次承担一次工具调用后的续推理成本。

## 5. TaskScope 当前状态进入 Context

不建立独立 Task Capsule。每次组装 Context 时，Host 从同一个 TaskScope canonical state 确定性选择本轮必要的：

- 用户目标、当前阶段、完成条件；
- 已确认决定和硬约束；
- open items、阻塞、下一步；
- 相关文件、artifact、工具状态和环境；
- 最近一次成功/失败及 evidence refs；
- source revision、evidence refs 和详细信息 page refs。

该临时投影不是新存储实体、表、索引或 Worker；实际发送内容只随最终 `ContextSnapshot` 留档。完整
README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE 继续按需 page-in。

## 6. 跨仓职责

### `simple-harness-memory-sdk`

- 永久原始证据、五天短时域索引和四类长期记忆的持久化/查询；
- 保存可信 `task_scope_id` 作为证据标签、过滤条件和排序亲和度，但不拥有 TaskScope 生命周期或项目权限；
- EpisodeThread、认知状态演化、资格门、逻辑遗忘和认知投影；
- `MemoryMutationPlan` / `RecallPlan` 的确定性验证、执行和审计；
- 新 schema 初始化、索引重建、质量与性能评估。

### `simple-harness-sdk`

- 定义中立、版本化、可 canonical hash/replay 的 Host↔Memory 公共协议；
- 至少覆盖 `RecallContext`、`RecallPlan`、`RecallDecision`、`TaskScopeDecision`、
  `ContextFragment`、`ContextAssemblyDecision` 和错误/reason code；
- 不拥有 Host 的最终 Context 选择，也不实现产品 UI。

### `simple_harness` Host

- 提供唯一主对话 UX 和新消息的 `primary_conversation_id` 绑定；
- 唯一拥有 TaskScope 状态机、canonical state、active cursor 与 `TaskScope -> ProjectBinding` 关系；
- 在调用主模型前构建初始有界 Context，并处理主模型提出的 TaskScope/Recall tool call；
- 最终拥有 Context Token 预算、工具/skill/附件选择、去重、裁剪、冻结和 provider 调用；
- 保存每次真实发送给模型的 `ContextSnapshot` 与组装决策，使结果可以复查；
- 承担通知、日历、权限确认和外部动作执行，Memory SDK 只产生状态和触发候选。

## 7. 每轮执行链（已确认单 Run）

```text
用户 query
   ↓
Host 原子提交原始 Turn（唯一主对话流）
   ↓
初始 Context = 最近 10 turn groups + TaskScope 目录 + 当前 query + 硬约束
   ↓
主模型提出 TaskScopeProposal / RecallPlan，或直接回答 no_recall
   ↓                                  ↓
context_route control barrier         直接流式回答
   ↓
Host 确定性校验 TaskScope/bindings + 短时域/长期记忆召回
   ↓
结果作为 Tool observation 返回同一 ReAct Run
   ↓
主模型续推理 → 每个项目 Effect 绑定 TaskExecutionEnvelope → 最终回答
   ↓
原子提交 Run、Tool、LLM evidence 与 decision lineage
   ↓
后台异步 MemoryMutationPlan → 确定性状态机 → 投影/索引更新
```

## 8. 原型数据策略

本次不设计旧数据库、旧 Message/Fact 或旧 Session 的迁移、导入、兼容读取和 UI 展示。验收从空数据目录
初始化唯一主对话开始；开发期间已有测试数据可以整体弃用并重新初始化。进入真实用户数据阶段前，必须另立
数据迁移计划，不能从本原型计划推导出任何旧数据处置权限。

一旦新原型开始写入，所有 Session/Turn/Tool/LLM evidence 立即受永久保留约束：容量、索引维护、逻辑遗忘
和测试清理都不得物理删除这些原始记录。只有派生索引、投影和可重建 cache 可以失效后重建。
