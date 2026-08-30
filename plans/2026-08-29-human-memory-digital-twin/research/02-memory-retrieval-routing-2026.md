# 记忆召回路由调研：什么情况下获取什么记忆（2026）

> 调研截止：2026-08-29
> 状态：`plan-bs` 研究结论；总召回策略已于 2026-08-29 经用户确认
> 范围：工作记忆、情景、语义、程序性、前瞻记忆和原始证据如何进入本轮 LLM Context

## 1. 核心结论

人类记忆检索不是先选择一个固定“仓库”，再只从该仓库读取。当前目标、注意、环境/时间线索、
上下文重现、候选之间的竞争和抑制共同决定什么内容进入当前工作记忆。

对本项目最稳妥的工程映射是：

```text
当前请求、任务阶段、参与者和环境
    ↓
召回意图与线索识别
    ↓
按类型并行生成候选
    ↓
作用域 / active 状态 / 证据 / 隐私 / 冲突 / 预算门
    ↓
跨类型排序、去重和最小充分选择
    ↓
组装成本轮工作记忆，投影到 LLM Context
```

因此：

- 工作记忆是一等认知系统，但不是第五种长期存储表。
- LLM Context 是承载工作记忆的技术容器之一，不是工作记忆本身。
- 不能用一次无类型区分的向量 Top-K 代表全部召回。
- 也不能把所有长期记忆都塞进每一轮 Context；这会增加干扰、隐私风险、延迟和成本。

## 2. 工作记忆与 LLM Context 的准确关系

可以把工作记忆近似理解为“本轮真正参与思考和行动的上下文”，但两者不是严格同义词：

```text
LLM Context Window
├── 系统规则、工具定义和安全策略        ← 不是用户记忆
├── 当前输入和近期对话原文              ← 工作记忆输入
├── 当前目标、计划、工具状态和中间结果  ← 工作记忆核心
├── 本轮召回的长期记忆                  ← 被激活后进入工作记忆
└── 可能存在但本轮未被注意的文本        ← 在窗口中，不一定实际发挥作用
```

所以产品定义建议固定为：

> 工作记忆是当前任务中被激活、保持、操作和控制的信息集合；LLM Context 是用于向模型承载其中一部分
> 信息的有限技术载体。Session 全量记录既不等于工作记忆，也不应整段自动进入 Context。

工作记忆可以保存审计快照，例如本轮采用了哪些记忆、为何采用、哪些被过滤，但这些快照是运行记录，
不是一种新的长期认知记忆。

## 3. 研究依据

### 3.1 目标和注意控制检索

2024 年 *Annual Review of Psychology* 的注意—记忆综述表明，工作记忆、长期记忆和注意持续交互；
记忆能够引导注意，当前目标也能反过来控制哪些信息获得优先访问。

2025 年关于记忆表征的综述进一步总结了 retrieval gating：人在情景检索时能够优先恢复与当前检索
目标相关的特征，而不是完整恢复所有已编码特征。

依据：

- Cowan et al., 2024, [The Relation Between Attention and Memory](https://doi.org/10.1146/annurev-psych-040723-012736)。
- Rugg, 2025, [The cognitive neuroscience of memory representations](https://doi.org/10.1016/j.neubiorev.2025.106417)。

工程推论：召回请求必须携带当前目标、任务阶段或等价的 `retrieval purpose`；仅有一段 query 文本不足以
稳定决定应该取什么。

### 3.2 情景记忆依赖线索、情境和竞争

2025 年 *Trends in Cognitive Sciences* 综述将人类式情景记忆的关键属性概括为动态更新、事件分段、
选择性编码与检索、时间邻近性以及检索竞争。2026 年的实验也表明，情境重现能够唤起先前重叠事件，
同时带来整合与竞争。

依据：

- Dong et al., 2025, [Towards large language models with human-like episodic memory](https://doi.org/10.1016/j.tics.2025.06.016)。
- Wahlheim et al., 2026, [A role for context-cued study-phase retrievals in episodic memory updating](https://pubmed.ncbi.nlm.nih.gov/41577941/)。

工程推论：询问“上次、为什么、当时怎么处理、类似事情发生过吗”时，应以人物、时间、项目、地点、
目标、行动和结果作为复合线索检索 Episode；不能只按消息文本相似度检索。

### 3.3 语义与情景是互补候选，不是单向升级

2025 年自适应压缩框架认为，语义记忆学习稳定规律，情景记忆保留意外或不能被现有规律解释的经历，
两者共同支持未来判断。

依据：Nagy, Orbán & Wu, 2025，
[Adaptive compression as a unifying framework for episodic and semantic memory](https://doi.org/10.1038/s44159-025-00458-6)。

工程推论：一般事实问题优先取当前有效的语义记忆；当语义事实存在冲突、置信度低、需要解释来源，
或当前事件偏离既有规律时，再同时取支持/反驳它的 Episode 和原始证据。

### 3.4 程序性记忆由任务和情境线索激活

2025 年 *Trends in Cognitive Sciences* 的习惯综述强调，习惯行为通常在熟悉情境和线索出现时可靠表达；
环境变化后继续执行旧习惯会造成 action slip。AI Agent 的程序性记忆研究也开始把过去轨迹蒸馏为
细粒度步骤和高层脚本，并分别研究构建、检索与更新。

依据：

- Linnebank et al., 2025, [Leveraging cognitive neuroscience for making and breaking real-world habits](https://doi.org/10.1016/j.tics.2024.10.006)。
- Liu et al., 2025, [MemP: Exploring Agent Procedural Memory](https://arxiv.org/abs/2508.06433)。

工程推论：只有在“准备行动”时才优先取程序性记忆，并必须匹配任务类型、工具、环境、约束和阶段；
旧环境下成功的流程不能因为文本相似就直接用于新环境。

### 3.5 前瞻记忆由时间、事件和主动监测触发

前瞻记忆包含未来意图的内容以及在合适时机恢复它的机制。事件型意图由外部事件触发；时间型意图
依赖时间监测。对预期情境进行战略监测能够提高前瞻任务表现，同时持续监测会占用认知资源。

依据：

- Peper & Ball, 2023, [Strategic monitoring improves prospective memory: A meta-analysis](https://doi.org/10.1177/17470218231161015)。
- Kliegel et al., 2026, [The functional neuroanatomy of event-based and time-based prospective memory](https://pmc.ncbi.nlm.nih.gov/articles/PMC13269919/)。

工程推论：前瞻记忆不能依赖普通语义向量检索碰运气。系统要对 `time_trigger`、`event_trigger`、
`deadline` 和状态建立确定性索引；只在进入相关时间窗口、事件出现或用户进行计划/状态检查时激活。

### 3.6 隐私是情境适当性，而不只是字段是否敏感

ICLR 2024 的 CONFAIDE 结果说明，LLM 即使知道敏感信息，也不能可靠判断在当前接收者和目的下是否适合
披露。Contextual Integrity 强调发送者、接收者、信息主体、信息属性、使用目的和传输条件共同决定
信息流是否合适。

依据：Mireshghallah et al., 2024，
[Can LLMs Keep a Secret?](https://proceedings.iclr.cc/paper_files/paper/2024/hash/08305d8b2ddab98932c163ea73df065f-Abstract-Conference.html)。

工程推论：长期记忆“相关”不代表“适合进入当前 Context 或输出”。作用域与隐私过滤必须是独立门，
而且应在把原文交给远程 LLM 之前执行。

## 4. 建议的类型召回矩阵

| 当前情况 | 优先获取 | 可选补充 | 默认不获取 |
|---|---|---|---|
| 用户继续当前话题、出现“这个/刚才/继续” | 当前工作状态、当前 Session 最近相关片段 | 本轮已召回内容 | 无关长期历史 |
| 询问“上次发生了什么、为什么这么决定” | 情景记忆 | 相关语义事实、原始证据 | 无关程序与未来意图 |
| 询问稳定身份、偏好、关系、项目约束 | 当前 active 语义记忆 | 支撑或反驳 Episode | 已 superseded 的旧值，除非解释变化 |
| 正在规划、执行工具或重复性任务 | 程序性记忆 | 语义约束、成功/失败 Episode | 无关个人旧事 |
| 到达时间窗口、事件发生或检查未来计划 | 前瞻记忆 | 相关程序、目标语义 | 已完成/取消意图，除非审计 |
| 新输入疑似改变既有信息 | 当前值 + 竞争值 + 更新证据 | 相关 Episode | 只取一个最高分值后直接覆盖 |
| 高风险决定、冲突调查、审计或要求原话 | 原始证据 | Episode、语义状态演化链 | 仅凭摘要或推断作答 |
| 提供建议或做个性化规划 | 相关语义 + 程序 + 未完成前瞻 | 少量代表性 Episode | 全量历史、无关敏感信息 |
| 面向第三方输出、共享设备或跨主体任务 | 先做情境隐私判断 | 通过最小披露门的记忆 | 仅因相关便直接披露的私人记忆 |
| 没有明确记忆需求且当前上下文足够 | 不取长期记忆 | 最小身份/硬约束投影 | 为了“显得懂用户”而主动翻旧事 |

这张表是召回路由的产品策略，不是宣称人脑存在同名 SQL 路由器。

## 5. 每类记忆的硬触发条件

### 5.1 情景记忆

至少命中一种情况才进入候选：

- 当前请求显式引用过去经历；
- 当前情境与过去 Episode 的人物、项目、目标、工具或结果高度重合；
- 需要解释某条语义记忆从何而来；
- 当前结果异常，需要查找过去相似成功或失败案例；
- 当前信息可能与过去经历冲突。

### 5.2 语义记忆

至少命中一种情况才进入候选：

- 回答或行动依赖用户身份、稳定偏好、关系、长期目标或项目事实；
- 需要个性化选择或遵守用户约束；
- 当前输入出现已知实体或概念；
- 需要判断新信息是否更新既有事实。

### 5.3 程序性记忆

至少命中一种情况才进入候选：

- Agent 即将规划或执行动作；
- 当前任务与已知流程、工具组合或决策模式匹配；
- 用户要求“按以前的方式”“照我的习惯”；
- 当前动作曾失败，需要召回纠错程序；
- 任务进入某个已定义流程阶段。

程序必须通过环境、版本、权限和适用条件检查，不能只按相似度采用。

### 5.4 前瞻记忆

至少命中一种情况才进入候选：

- 当前时间进入 `due_window`；
- 当前事件匹配 `event_trigger`；
- 用户询问计划、承诺、待办或未来目标；
- 当前动作将阻塞、推进或完成某个未完成意图；
- 系统准备结束 Session，需要检查是否产生或遗漏后续事项。

### 5.5 原始证据

默认不直接进入普通回答的 LLM Context。以下情况才取：

- 用户要求原话、完整历史、审计或复查；
- 记忆之间发生冲突，需要判定来源；
- 高风险行为要求证据支持；
- 需要重新提取、重新巩固或修复错误记忆；
- 用户质疑系统为何记住或为何得出某个判断。

## 6. 所有类型共享的召回门

候选内容进入工作记忆前，建议按以下次序执行：

1. **主体与作用域门**：当前用户、家庭、项目、Session 是否有权读取。
2. **状态门**：`active`、`superseded`、`disputed`、`completed`、`cancelled` 等是否符合本轮目的。
3. **触发门**：任务、时间、事件、实体、环境、流程阶段是否匹配。
4. **证据门**：明确事实、用户确认、观察、推断分别处理；推断不得冒充事实。
5. **时效与冲突门**：最新不一定自动正确；冲突时保留竞争候选与来源。
6. **隐私适当性门**：接收者、目的、信息主体、属性和传输条件是否允许。
7. **相关性与效用门**：这条记忆是否会改变本轮答案、计划或行动。
8. **最小充分与预算门**：去重、压缩、限制 token、延迟和 LLM 调用数。

前六道门属于资格判断，不能被一个高向量相似度覆盖；排序只在合格候选之间进行。

## 7. 推荐的软件召回流程

### 阶段 A：确定性快速路由

- 当前 Session continuation；
- 显式过去/未来/审计措辞；
- 时间和事件 trigger；
- 当前 identity、scope、recipient 和 task phase；
- 硬隐私、状态和权限过滤。

### 阶段 B：LLM 召回规划

LLM 根据语义输出标准结构，只提出召回意图，不直接读取或授权数据：

```json
{
  "purposes": ["execute_task", "personalize"],
  "memory_types": ["procedural", "semantic"],
  "entities": ["simple-harness-memory-sdk"],
  "time_range": null,
  "need_evidence": false,
  "privacy_context": {
    "recipient": "user",
    "purpose": "plan_co_creation"
  }
}
```

### 阶段 C：按类型候选生成

- Episode：事件、人物、时间、地点、目标、结果复合检索；
- Semantic：subject/predicate/value、实体图、FTS/vector；
- Procedural：task/tool/environment/stage/trigger 索引；
- Prospective：time/event/status 索引；
- Evidence：只按证据引用或受控范围读取。

### 阶段 D：确定性资格门与跨类型排序

先过滤无权、失效、不适当、证据不足的候选，再综合：

- 与当前目标的因果效用；
- 线索匹配；
- 证据强度；
- 当前有效性；
- 时间与事件邻近；
- 成功/失败适用性；
- 多样性和冗余；
- Context 预算。

### 阶段 E：认知投影

把最终候选转换为明确分区的工作记忆，而不是混成无来源文本：

```text
已确认事实
相关经历
适用操作程序
待完成意图
存在争议或需要确认的信息
证据引用
```

## 8. 当前 SDK 与目标模型的差距

基于 0.5.2 当前代码：

- `Fact.category` 混合了语义类别、认知类型和生命周期含义；
- `Message` 被注释为情景记忆单元，但实际仍是原始消息，不是 Episode；
- recall 主要在 message/fact 上做 FTS、向量、最近性和 lexical score；
- 没有独立 Episode、Procedure、ProspectiveIntent 数据模型和类型专用索引；
- 没有携带 `retrieval purpose`、task phase、recipient 或 environment 的召回计划；
- 没有跨类型的状态/证据/隐私资格门；
- `recall_for_turn` 返回冻结的有界结果，但尚未表达“为什么召回、为什么过滤、投影到哪个工作记忆分区”。

因此本次升级不是调 RRF 权重或新增 category 就能完成，而是召回协议、持久化模型和 Context 投影的
协同升级。

## 9. 已确认的召回判断策略

采用“主模型语义判断 + SDK 确定性裁决”的混合路由：

- 确定性代码负责强线索、时间/事件 trigger、权限、状态、隐私和预算；
- LLM 负责理解任务语义、提出所需记忆类型、生成类型化查询和对合格候选做语义效用判断；
- LLM 不能绕过代码门，也不能直接把候选标成 active、合法或可披露。

用户已确认采用：

> 每一轮都判断是否需要记忆，但不是每一轮都实际查询长期记忆；只有命中任务、语义、时间或事件
> 触发时才执行类型化召回。核心身份和硬约束可以作为经过隐私过滤的最小常驻投影。

用户进一步确认：本次实验开发阶段不引入独立小模型，由主 Agent LLM 直接完成每轮 Memory Need 判断。
推荐执行形态是主模型在正常 Agent 工具循环中提出结构化 `RecallPlan`：不需要记忆时直接继续回答；
需要记忆时调用内建 Memory recall 操作，Host 执行 SDK 路由并把结果返回主模型续推理。

两条生产路径固定为：

```text
无召回：主模型判断当前工作记忆充分
      → 不调用 Memory SDK
      → 在同一次生成流中直接输出最终回答
      → Host 持久化 outcome=no_recall 的 RecallDecision

有召回：主模型提出 RecallPlan / memory tool call
      → Memory SDK 验证并执行类型化召回
      → Host 把工具结果交回主模型
      → 主模型执行一次工具调用后的续推理并输出最终回答
      → Host 持久化完整 RecallDecision 与 invocation 关联
```

这项选择意味着：

- 召回质量优先于使用能力较弱的小模型节省成本；
- 不额外维护小模型、阈值、升级模型和双模型分歧状态；
- 发生召回的轮次仍需要工具调用后的主模型续推理。复用流式连接只减少建连开销，不消除推理延迟、
  输入/输出 token 成本或 provider 协议上的 continuation；
- 时间到期、事件触发、审计模式、权限、状态、隐私和预算仍由确定性代码强制执行，不能依赖主模型
  自觉调用或允许其绕过；
- 当前实现位于“主模型调用前自动 recall”，要实现此策略必须重新校准 Harness Agent loop 与
  `AgentMemoryPort` 的顺序和公共协议，不能只在 Memory SDK 内新增一个类。

## 10. LLM 操作的全链路审计要求

用户已确认：本计划涉及的所有 LLM 操作都必须留下可复查、可关联、可验证的审计记录。普通
observability log 不足以承担这项职责，因为它可能轮转、缺少状态语义，而且当前隐私安全事件有意不记录
content 和 result payload。

建议分为两层：

### 10.1 LLM Invocation Evidence

每次真实 LLM 调用保存一条不可变调用证据：

- `invocation_id`、Session/turn/run/correlation；
- 操作类型，例如 `recall_need`、`fact_extract`、`consolidate`、`resolve_conflict`；
- provider、model、模型参数、prompt/template/schema 版本；
- 输入证据引用、canonical input hash，以及受权限保护的原始输入；
- 原始模型输出、结构化 tool call、canonical output hash；
- 开始/结束时间、延迟、token usage、可得时的费用；
- finish reason、provider request id、错误、重试和降级链；
- 代码、SDK 和 Host 版本。

API key、access token、cookie、密码和其他认证材料永远不得进入证据；发送前与落盘前都要做独立凭据
扫描。敏感内容不等于认证材料：为了审计，用户对话和记忆内容可以保存，但必须受主体、作用域和访问
控制保护，不能进入普通 telemetry。

### 10.2 Structured Decision Record

每次 LLM 输出被系统解释后，再保存结构化决策记录。`RecallDecision` 是这类新记录之一，并非 0.5.2
现有对象：

```text
RecallDecision
├── decision_id / invocation_id / turn_id
├── outcome: no_recall | recall
├── proposed_routes / accepted_routes / rejected_routes
├── reason_codes / trigger evidence refs
├── candidate ids / selected ids / filtered reason codes
├── validator and policy version
└── final projection hash / state transition receipt
```

无召回轮次同样必须有记录。若主模型直接完成回答且没有发出 Memory tool call，Host 写入：

```json
{
  "outcome": "no_recall",
  "reason_code": "model_completed_without_memory_tool",
  "model_invocation_id": "...",
  "turn_id": "..."
}
```

这条记录不声称掌握模型隐藏推理，只证明本次真实调用没有提出召回操作；原始 invocation evidence
保留实际输入、公开输出和 finish/tool-call 结果，供后续复查。禁止为了审计保存或索取隐藏思维链。

同一模式也适用于：

- `ExtractionDecision`：提取了什么、哪些被验证/拒绝、最终写入什么；
- `ConsolidationDecision`：哪些 Episode 支持形成或更新语义/程序记忆；
- `ConflictResolutionDecision`：竞争信息如何保持 disputed、确认或 supersede；
- `ProspectiveDecision`：意图如何创建、触发、完成、延期或取消；
- `ProjectionDecision`：哪些记忆进入数字孪生体或本轮工作记忆。

原始调用证据回答“模型实际看到了什么、输出了什么”；结构化决策记录回答“代码如何解释它、最后改变
了什么”。两者通过 ID 和 hash 互相引用，不依靠一条自由文本 log 兼任全部职责。

审计记录采用 append-only 语义，不做系统自动删除；用户显式删除与法律合规要求的边界仍需单独确认。

## 11. 研究限制

- 认知科学描述的是人类行为与神经机制，不能直接证明某个软件 schema 或排序公式正确。
- 前瞻记忆究竟是独立系统还是跨系统能力仍有理论争议；本项目把它独立建模是产品决定。
- AI Agent 程序性记忆仍是快速发展的研究方向，2025 年相关论文不能视为成熟工业标准。
- 召回路由最终必须用真实用户语言、长期状态变化、隐私场景和延迟预算进行产品验证。
