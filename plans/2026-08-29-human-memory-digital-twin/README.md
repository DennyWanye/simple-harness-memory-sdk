# Human Memory Digital Twin Plan Workspace

> 创建日期：2026-08-29
> 状态：用户已批准直接实施；V0、S1、S2 与 S3 Task 1/2 已闭合；Host-owned `MemoryActionAuthority` + Memory 原子 consumer 通过两轮独立 closure audit，machine `a2-003` resolved；S3 Task 3—7 pending
> 主计划仓库：`simple-harness-memory-sdk`
> Worktree：`/Users/denny/projects/simple-harness-memory-sdk-memory-plan`
> 分支：`feat/human-memory-plan`

## 目标

以当前 `simple-harness-memory-sdk` 为唯一认知记忆底座，依据项目已有的人类记忆模型，
共同制定一份横跨 Memory SDK、Harness SDK 公共协议和 simple_harness Host 集成的可执行 program。
本目录是该 program 的主计划目录，保存计划、调研、验收标准、挑战、spike 和可审阅验证结论；业务实现与
原始测试证据分别落在三个实施仓库及其 ignored 本地证据目录中。

SDK 当前生产事实以本仓库的 `ARCHITECTURE/`、`src/simple_harness_memory/` 与测试为准；
`baseline/original-2026-08-17/` 是从 Host 项目历史调研中冻结的设计依据，不代表当前实现事实。

## 原始认知模型事实源

本次计划使用冻结快照，完整来源、SHA-256 和权威性约定见
[baseline/BASELINE-MANIFEST.md](baseline/BASELINE-MANIFEST.md)。首要基准是：

1. [Memory SDK 认知架构设计](baseline/original-2026-08-17/01-memory-sdk-cognitive-architecture.md)
   - L1 工作记忆
   - L2 情景记忆
   - L3 语义记忆
   - Facts、巩固、矛盾演化、遗忘和混合召回
2. [Memory SDK 深度解析：RRF 与数字孪生体](baseline/original-2026-08-17/02-memory-sdk-deep-dive.md)
   - 身份、认知、情感、社交、行为和动机六维数字孪生体
   - Facts 到数字孪生体的投影与个性化召回

## 当前认知科学调研

- [2026 人类记忆认知架构调研](research/01-human-memory-cognitive-architecture-2026.md)
  - 区分学界稳定共识、活跃争议与工程推论
  - 校正原三层模型遗漏的感觉记忆、非陈述性记忆、前瞻记忆和跨系统过程
  - 截止日期：2026-08-29
- [2026 记忆召回路由调研](research/02-memory-retrieval-routing-2026.md)
  - 明确什么情况下获取情景、语义、程序性、前瞻记忆或原始证据
  - 提出“确定性强线索与资格门 + LLM 语义路由 + 类型化召回 + 工作记忆投影”
  - 截止日期：2026-08-29
- [Recall Router 毛选式方法审查](research/03-recall-router-method-audit.md)
  - 区分已调查事实、未闭环假设和达到可靠 plan 的必要条件
  - 以典型复合场景解剖生产链路，并定义必须真跑的协议、路由质量、端到端和故障 spike
- [记忆写入、演化与审计执行架构](research/04-memory-write-evolution-audit-architecture.md)
  - 从 CommittedTurn、原始证据、LLM 提案、确定性裁决到四类状态机与认知投影的完整链路
  - 定义 LLM invocation evidence、structured decision record、只读审计导出和优化指标
- [单一主对话流与动态 Context 架构](research/05-single-stream-dynamic-context-architecture.md)
  - 用户只看到一条永久主对话，系统内部自动维护 TaskScope、Run 和 Episode
  - 最近 10 个因果 turn group、五天短时域检索、长期认知记忆与 tool/skill 的预算化动态组装
  - 明确 Memory SDK、Harness SDK 协议和 simple_harness Host 的跨仓职责
- [TaskScope 代码执行架构](research/06-task-scope-code-execution-architecture.md)
  - 核查当前每 Turn scope、Session 级 Project binding、自动 pre-provider recall 与 ReAct loop 接缝
  - 其中 Route Run → Execute Run 是已被取代的旧草案，不是当前定案
- [可永久恢复的 TaskScope 档案与检索](research/07-durable-task-scope-archive-and-retrieval.md)
  - TaskScope 保存完整对话、模型、工具、文件、步骤、决定、修改/取消原因和验证 evidence
  - README/STATUS 是带版本的可读投影，TaskResumeCheckpoint 支持多年后安全恢复
  - 长期 TaskScope 向量+全文索引只负责发现 ID，命中后必须从 canonical Archive 精确打开
- [TaskScope 创建权与不可变文件夹绑定](research/08-task-scope-creation-and-folder-binding.md)
  - 主模型判断并提出 TaskScopeProposal，Host 才能创建档案、文件夹和权限 binding
  - 未指定路径时在 managed workspace root 新建文件夹；明确路径时校验并绑定 exact folder identity
  - 已有 exact root 不允许静默换绑；路径缺失/identity 漂移时阻塞
- [多文件夹 TaskScope 绑定方案比较](research/09-multi-root-task-scope-options.md)
  - 排除“按文件夹拆 TaskScope”和“绑定公共父目录”两种错误简化
  - 推荐一个 managed task_home + 多个 exact workspace bindings，工具使用 root_ref + relative path
  - 已确认 mode-aware append-only 扩展：Manual 逐次确认，Auto 由主模型提案、Host 校验后直接追加
- [TaskScope 信息载体与审计分层](research/10-task-scope-information-carriers.md)
  - 区分 raw evidence、append-only event ledger、canonical state、checkpoint 和人/Agent 阅读视图
  - 已确认稳定阅读层为 README、PLAN、STATUS、DECISIONS、RESUME、EVIDENCE
  - 原始记录留在私有 DB/object store，Task Home 保存可重建投影和带 hash 的 evidence refs
- [永久审计、隐私隔离与逻辑遗忘](research/11-permanent-audit-privacy-and-logical-forgetting.md)
  - 已确认原始业务证据永久保存不等于永久向模型开放
  - 普通执行、用户审计和密封取证使用三个严格隔离的访问平面
  - append-only suppression 立即撤销普通使用权；凭据在进入永久证据域前过滤
- [TaskScope 事件记录与语义更新流水线](research/12-task-scope-event-and-semantic-update-pipeline.md)
  - Host 不经 LLM 永久记录客观运行事件，主模型只提议有含义的任务状态变化
  - `task_scope_update(TaskScopeMutationPlan)` 是预定义工具，不使用正则判断任务语义
  - dirty flags 与 closure gate 防漏记；一个语义阶段批量提交一次，失败不伪造 canonical state
- [单一主对话的 TaskScope 路由终态](research/13-task-scope-routing-outcomes.md)
  - 已确认 direct standalone、memory standalone、continue active、resume existing、create new 五种终态
  - TaskScope 只服务于有执行过程、状态、证据或恢复需求的任务，不作为所有认知记忆的容器
  - standalone 不获项目写权限；历史任务必须 search candidates 后 exact open canonical Archive
- [初版本核心设定收敛](research/14-initial-version-core-settings.md)
  - README/STATUS 有界且只做概括；普通记忆初版全局可候选但仍过隐私/遗忘过滤
  - 显式记住/纠正/遗忘立即处理，普通 turn 由 durable outbox 批量异步提取
  - 数字孪生体初版只做知识图谱式展示，不影响 Agent；单 ReAct Run 已确认
- [单 ReAct Run 与未来并发边界](research/15-single-react-run-and-future-concurrency-boundary.md)
  - Session 是永久对话、TaskScope 是永久任务、Run 是一次 Agent 执行；三者不互相替代
  - 一个用户请求在同一 ReAct Run 内完成 route、recall、tools、semantic closure 和最终回答
  - 初版只实现一个 foreground Run；普通消息 durable FIFO，stop/pause/cancel 立即控制当前 Run
  - 保留 run-scoped/CAS/idempotency 接缝，但不实现并行、运行中语义 steering 或子代理

## 已确认的产品方向

- 目标是完整、真实地记录与用户有关的记忆，形成数字孪生体，帮助用户按自己的想法完成任务。
- 记忆覆盖对话、决策、项目、文件、任务结果、纠正、偏好、目标、关系、行为习惯和工具经验。
- LLM 负责判断是否值得提取，并输出标准结构；确定性代码负责验证和存储。
- LLM 推断必须与用户明确事实区分，推断不得冒充事实。
- Session、Turn、Tool Result、LLM invocation evidence 和 decision record 等原始数据必须完整、永久保存，
  不允许系统、retention job 或用户请求触发物理删除。用户提出“删除/忘记”时仅执行逻辑遗忘：退出普通
  召回、认知投影和后续使用，但原始数据与状态变化仍保留在受控审计域中，防止无证据复活或改写历史。
- 逻辑遗忘采用 append-only `SuppressionDirective`，立即阻止普通 TaskScope 搜索/open、六阅读视图、
  ResumePackage、短期/长期召回、动态 Context 和数字孪生投影使用相关内容；派生重建失败不能绕过同步
  资格门。原始内容仅在用户明确发起并声明目的的审计中受控读取，审计读取本身也必须留痕。
- 密码、API key、Token、Cookie、认证二维码等不属于永久业务证据：三仓共享的 sanitization receipt 必须在
  Host/Harness/Memory 第一次持久化前产生并验证，未过滤 payload 不得进入数据库、WAL、checkpoint、对象存储、
  日志、embedding、LLM evidence 或临时文件。
- Episode 是从完整原始证据中选择性建立的长期事件，而不是每轮对话摘要；普通往返只保留原始证据，
  有目标、决定、行动与结果、纠正或长期影响的经历才形成 Episode。同一件事的多个阶段通过
  `EpisodeThread` 关联，各 Episode 始终引用准确的原始 turn span；所有分段和关联决定均可审计。
- 记忆分类拆成独立维度：认知类型、语义类别、可信状态、生命周期、作用域与隐私策略，
  不再把它们挤进单一 `category` 字段。
- 取消 L1/L2/L3 编号，统一使用认知类型名称。
- 工作记忆是一等认知系统，但不是第五种长期存储表；它是当前任务中被激活、保持、操作和控制的
  信息集合，并通过有限的 LLM Context 承载其中一部分内容。
- 召回采用“每轮判断、按需召回”：每轮评估任务、语义、时间和事件触发，但未命中触发时不查询
  长期记忆；核心身份和硬约束只作为通过隐私过滤的最小常驻投影。
- 本次不引入独立小模型；由主 Agent LLM 在正常工具循环中直接提出结构化 `RecallPlan`。Memory SDK
  负责验证路由、执行类型化召回及权限、状态、隐私和预算裁决。实验阶段完成后默认启用。
- 主模型判断不需要记忆时，不调用 Memory SDK，在同一次生成流中直接回答，并记录
  `outcome=no_recall`；需要记忆时，先执行 Memory tool call，再基于召回结果进行一次续推理。时间、
  事件、审计等确定性强触发不允许因主模型未调用工具而丢失。
- 本计划中所有 LLM 操作都必须进入可审计链：保存受控的原始调用证据，并生成结构化决策记录，覆盖
  召回判断、记忆提取、分类、巩固、冲突/更新、程序学习、前瞻意图和认知投影。记录必须关联
  Session/turn、模型与 prompt/schema 版本、输入输出 hash、验证结果和最终状态变化；不得记录 API key、
  token、cookie 等认证材料。审计链不做系统自动删除。
- 审计能力必须可实际审查而非只落表：支持按 turn/invocation/memory/decision 导出端到端 trace，使用
  稳定 reason code 解释接受、拒绝和过滤，并能按模型、prompt/schema 版本聚合延迟、Token、费用、
  漏召回纠正、冲突和状态变化指标，用于后续优化且不得覆盖历史 lineage。
- Semantic Claim 将 lifecycle、epistemic、conflict、verification 拆成正交状态；明确纠正可以
  supersede，模糊冲突必须将双方标记 contested，任务依赖时询问用户，否则不投影，禁止静默选边。
- Procedure 的明确用户规则可直接 active；单次行为只能形成 draft。低风险可逆程序在多个独立任务
  重复成功后允许自动激活，高风险、发布、删除、付款和权限程序必须经用户明确确认；所有程序持续受
  工具、环境、版本和失败证据的 applicability 检查。
- Prospective Intent 只有在“明确行动 + 明确触发”时才进入 pending；行动明确但缺少触发条件时仅为
  candidate，模糊愿望只进入 Semantic Goal，LLM 推测不得直接提醒或执行。SDK 保存状态并产生触发候选，
  Host 负责调度、通知和执行，高风险外部动作仍须经过权限护栏与必要确认。
- 世界模型纳入本次直接实施范围，不只保留接口边界。
- 用户侧只保留一条永久主对话，不再要求用户创建、选择或切换 Session；内部仍保留稳定 ID、Run、
  TaskScope、Episode 和完整 lineage，避免任务污染并支持审计。
- Session 不再等于任务；主模型提出结构化 `TaskScopeProposal`，Host 确定性代码验证、存储和审计，系统自动
  完成任务边界识别与恢复。
- TaskScope 是永久任务档案而非轻量标签：逻辑包含该任务全部对话、Run、模型/工具操作、文件变化、步骤、
  决定、修改/取消原因、artifact 和测试 evidence；README、STATUS 与 checkpoint 使未来 Agent 可恢复执行。
- TaskScope 拥有独立的长期向量+全文 Search Index。主模型可先按自然语言搜索候选 ID，再用 exact ID 打开
  canonical Archive；向量命中不能直接授予项目权限，也不能替代任务事实源。
- TaskScope 必须拥有本地 task_home，并绑定一个或多个 exact workspace folder identity。主模型只判断并提交
  proposal；Host 创建/校验目录并生成版本化 binding-set receipt。已有 root 不允许替换；Manual 模式追加 root
  需要用户确认，Auto 模式不逐次询问，但仍执行 exact path/identity/过宽目录校验并记录完整 audit。
- Auto 模式只能自动绑定配置 workspace root 下的真实后代目录；macOS/Linux 未配置时默认根为
  `~/SimpleHarnessWorkSpace`。根本身、symlink resolve 后越界的目录和公共父目录均不能自动绑定。
- TaskScope 信息载体采用六层 authority：raw evidence、append-only task events、canonical state、immutable
  checkpoints、README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE 阅读视图和可重建 Search Index；Markdown
  不是事实源。
- TaskScope 更新采用双链：Host 直接记录全部模型/工具/文件/测试事实；当前主模型在目标、范围、决定、计划、
  阶段或恢复语义变化时调用预定义 `task_scope_update`，提交带 evidence refs 的结构化 MutationPlan。Host
  dirty flags 只检测未收口事实，closure gate 要求模型补交 mutate/no_mutation；不靠正则，不运行后台总结模型。
- 单一主对话每轮路由到 direct standalone、memory standalone、continue active、resume existing 或 create new。
  普通对话与用户级长期记忆不自动创建 TaskScope；只有具有执行过程、状态、证据或未来恢复需求的任务才建档。
- 动态 Context 采用最近 10 个完整因果 turn group、当前 TaskScope 状态的临时 Context 投影、五天短时域对话索引、按需
  长期记忆、tool/skill/attachment 和分区 Token 预算；最终 Context 是冻结且可审计的 snapshot。
- 普通认知记忆在初版对同一用户全局可成为候选，不以 TaskScope/workspace 作硬隔离；相关内容仍必须经过
  recipient/purpose、敏感级别、suppression、冲突/过期状态和最小披露过滤，并记录跨任务命中 log。
- 记忆提取采用混合模式：显式记住/纠正/遗忘立即裁决，普通 committed turn group 经 durable outbox 批量
  异步提取，失败或重启不丢 job，且不阻塞当前回答。
- 数字孪生体初版只做用户可见的知识图谱式展示，不进入 Agent Context、不影响召回/回答/工具/行动；等积累
  足够真实数据和审计 log 后再评估用途。向量用于语义检索，graph 是从 canonical facts/relations 构建的展示投影，
  初版不强制采用图数据库。
- 五天短时域是原始对话证据上的派生检索层，不是第六类认知记忆；到期只退出派生索引，原始数据永不删除。
- 当前为原型开发，不迁移、导入或兼容现有旧数据库/旧 Session 数据；从全新数据库初始化唯一主对话。
  “原始数据永不删除”从新原型写入的第一条 evidence 开始执行。
- 当前优先级依次是：按原认知分类正确召回、避免漏记、避免错误推断、处理信息更新、
  避免不当隐私召回、控制延迟与成本。

## 计划产物

- `acceptance.md`：已由用户批准并冻结
- `assurance-contract.json`：与冻结验收标准配套的机器可读保障边界
- `architecture-baseline.md`：当前 Host、Harness SDK、Memory SDK 与目标架构差距
- `best-practices.md`：认知、LLM tool、持久化、检索与权限实践的项目适配结论和典型调用链
- `plan.md`：program 依赖图、全局不变量和七个 release unit 入口
- `slices/`：每个不超过三类高风险子系统、可独立执行和验收的代码级实施计划
- `evidence/`：调研、挑战和 spike 的文字结论；原始测试证据不进入 Git

## 当前阶段

初版本产品级核心设定、验收契约、跨仓架构基线和代码级 program plan 已冻结，用户已批准直接实施。
V0 authority、旧 Session oracle lineage 和五项关键假设 spike 已闭合；S1 Harness SDK 0.7.0 source
`64d409d4` 已完成 `a2-001` typed workspace binding authority、`a2-002` Host-durable analysis delivery 和
`a2-003` strict cognitive/evidence/recall protocol closure。旧 exact candidate wheel `b9421ddf…` 永久失效；
新 reproducible candidate wheel 为 `49e42eaa…`，独立最终审计 P0/P1/P2=0，仍未 tag/publish。
S2 Memory SDK 已完成 fresh schema、永久 evidence ingestion、suppression authority、LLM audit ledger、durable worker、
旧默认移除与 0.6.0 slice candidate；source `e316919` 全仓 `493 passed, 8 skipped`、独立审计 P0/P1/P2=0，clean wheel
`5011da96…` 曾与旧 exact Harness 0.7.0 wheel `b9421ddf…` 完成隔离兼容验证，该回执仅保留为 S2 历史证据，不再是
program 候选。S1 门已重新关闭，现在恢复 S3 四类认知状态、短时域索引、类型化召回和 display-only 图投影。
S4 Host 已完成 primary evidence、Canonical TaskScope Archive、目录 provisioning，并在候选
`13dbef17` 关闭 store-level Manual/Auto freshness、identity 和 replay seam；`a2-004` 仍要求把 durable Manual interaction、
current Run/context/config facts 与 production adapters 明确装配。Phase 2 综合审查另确认 Host exact Harness 0.7 production
composition 缺少三个 mandatory authority port，定为 P0，必须在 S5 由唯一 composition owner 实装且 fail-closed。
S3 正在实施；S5、S6 未开始。program 的 15 个最终场景仍保持 `NOT_RUN`，只有全部实现、
自动化、真实模型、桌面 UI 和 machine `finalize` 完成后才能宣称 program 完成。
