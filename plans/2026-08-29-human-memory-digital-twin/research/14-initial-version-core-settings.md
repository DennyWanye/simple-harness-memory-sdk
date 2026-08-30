# 初版本核心设定收敛

> 日期：2026-08-30  
> 状态：第 1–6 项及初版单 Run 排队/控制语义均已获用户确认

## 1. Session、TaskScope 与 ReAct Run

已确认口径：用户只有一个永久主 Session；TaskScope 是跨多轮、可永久恢复的任务档案；Run 是处理某次
用户请求的一次 Agent 执行记录，不是独立 Session、独立文件夹或独立运行环境。建议每个用户 Turn 只创建一个
ReAct Run，在同一循环内通过 `context_route` 控制屏障建立 TaskScope 上下文，再执行后续工具；项目 Effect
使用 per-Effect `TaskExecutionEnvelope` 绑定 TaskScope/root/binding revision。

research/06 中旧的 Route Run + Execute Run 方案已被本决定取代；当前单 Run 和未来并发边界见 research/15。

## 2. README / STATUS 保持概括且有大小上限

已确认 README 和 STATUS 是概括性视图，不允许随任务年限无限增长：

- README 只保留任务目标、范围、关键约束、稳定架构概览和详细资料索引；
- STATUS 只保留当前阶段、当前步骤、阻塞、下一步和最新验证状态；
- 旧状态、完整决定、计划细节和 evidence 不向这两个文件追加堆积，分别进入 canonical history、
  Checkpoint revisions、PLAN、DECISIONS 和 EVIDENCE；
- 物化器执行 byte/token/section 上限；超限时根文件保留摘要和索引，详细内容拆入稳定子文档；
- 拆分不删除 canonical facts，也不能让历史信息只存在于 Markdown；
- 初版具体阈值由真实长期 TaskScope 文档 spike 确定，不在需求阶段拍脑袋固定。

## 3. 普通记忆初版全局可候选使用

已确认初版不按 TaskScope/workspace 对普通认知记忆做检索隔离：同一用户的记忆在任何任务或对话中都可以
成为召回候选，用实际 recall/audit log 积累数据，再分析是否需要更细的范围策略。

“全局可候选”不等于无条件披露：已经确认的 subject、recipient/purpose、敏感级别、active suppression、
冲突/过期状态和最小披露过滤继续生效。TaskScope 仍用于任务归属、根目录和审计亲和度，但不作为普通记忆
的硬过滤边界。每次跨 TaskScope/workspace 命中必须记录来源、目标任务、过滤结果和最终是否进入 Context，
为后续范围分析提供数据。

## 4. 记忆提取采用混合模式 C

已确认：

- 用户明确要求记住、纠正或遗忘时，立即走结构化提案与确定性裁决；
- 普通 committed turn group 先永久保存 raw evidence，再写 durable extraction outbox；
- Worker 以短时间窗口/数量批量调用 LLM 提取，不阻塞当轮回答；
- 未处理 job 在退出、崩溃或重启后继续，不能因批处理丢失；
- batch size、idle window、最大等待时间和成本阈值通过 spike/真实日志确定；
- 每个 batch 保留精确 turn/evidence refs，不能把批量摘要当原始事实。

## 5. 数字孪生体初版只展示

已确认数字孪生体初版不影响 Agent：

- 不进入 Agent Context；
- 不参与 Recall 排序、工具选择、回答风格或任务决策；
- 不产生自动动作或提醒；
- 只作为 Memory facts/relations 的可重建展示投影，让用户观察积累的数据最终形成怎样的画像；
- 每个展示节点必须有来源、类型、状态、置信度和纠正/遗忘入口；
- 未确认推断清楚标为 inferred/candidate，不能伪装成用户事实。

等积累足够真实数据与审计 log 后，再单独评估数字孪生体是否以及如何影响 Agent，不在初版本预设用途。

## 6. 记忆与数字孪生体使用知识图谱视觉

已确认审查/展示入口采用知识图谱式视觉：

- Memory 事实记录可具有 embedding vector，用于语义检索；
- 事实、人物、任务、项目、目标、程序、事件和证据关系投影为 graph nodes/edges；
- 向量检索和知识图谱是两个正交能力：前者负责相似召回，后者负责关系表达与可视化；
- 初版本不因为要画图就强制引入独立图数据库，可先从 canonical relational state + relation tables 构建图投影；
- 视觉目标是清晰、克制、层级良好、可读且有审美，不通过粒子、炫光、无意义动画或特效堆砌“好看”；
- 支持按记忆类型、状态、时间、TaskScope、证据来源和隐私级别过滤，点击节点可查看 lineage 与审计信息；
- 被 suppression 的内容不能在普通图谱中以节点、边、标签、tooltip 或布局暗示泄露。
