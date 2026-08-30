# Recall Router 毛选式方法审查

> 日期：2026-08-29
> 状态：架构候选审查；不是定稿 plan，也不是可靠性证明

## 1. 当前判定

用户已选择“主 Agent LLM 每轮判断 + Memory SDK 代码资格门”，不引入独立小模型。主模型提出
`RecallPlan`，Memory SDK 验证并执行；确定性时间/事件/审计强触发不允许被模型跳过。该方案方向已经
确认，但路由质量、延迟、成本和协议可行性仍须通过 spike 证明。

毛选式方法支持的是调查、抓主要矛盾和实践检验的过程，不会因为一个方案符合抽象原则，就自动证明
该方案正确。

## 2. 主要矛盾候选

> 在有限的延迟、Token 和隐私边界内，让 SDK 可靠地把当前真正需要、仍然有效、允许披露的记忆送入
> 工作记忆，同时排除不相关、过期、冲突未决或不宜出现的记忆。

这个表述统一了用户已经指出的六类失败：漏召回、错误推断、过期信息、隐私不当、延迟和成本，以及
按认知类型正确召回的产品目标。仍需用户确认它是否是本次升级的主要矛盾。

## 3. 没有调查就没有发言权：已知与未知

### 已调查事实

- Harness 当前 `MemoryRecallRequest` 只有 identity、scopes、query text、bounds 和 turn time，尚不能表达
  task purpose、phase、environment、recipient 或 event：
  `/Users/denny/projects/simple-harness-sdk/src/simple_harness/runtime/agent_memory.py:155`。
- Harness 在 context preparation 中创建该请求：
  `/Users/denny/projects/simple-harness-sdk/src/simple_harness/runtime/kernel.py:905`、`:1032`。
- Memory SDK manager 当前把 `query_text` 直接传入 backend：
  `src/simple_harness_memory/core/manager.py:248`、`:279`。
- SQLite 的生产 recall 入口为 `src/simple_harness_memory/backends/sqlite.py:916`。
- 当前长期模型主要是 Message 和 Fact，Fact 的 category 同时承载多种含义：
  `src/simple_harness_memory/core/models.py:21`、`:59`、`:74`。
- 当前 standalone Retriever 在 message/fact 上执行统一混合召回：
  `src/simple_harness_memory/features/retriever.py:25`、`:33`。

### 尚未调查闭环

- Host 在真实对话、工具执行和多步任务中能稳定提供哪些结构化字段；
- RecallContext 加入公共协议后对 canonical hash、replay、exact-wheel 和旧消费者的影响；
- 主 Agent LLM 每轮判断的 required route 漏失、额外 route、延迟和成本；
- 主模型无 Memory tool call 时，Host 如何无额外推理地保存可审计 `no_recall` decision；
- 多 Route 并发是否能在现有两秒 recall deadline 内完成；
- 类型化结果如何进入现有 Context Provider 而不破坏上下文预算；
- Procedure 和 ProspectiveIntent 的真实 schema、状态机与更新语义。

这些未知项没有 spike 或代码证据前，不能在 plan 中写成已确定能力。

## 4. 具体问题具体分析

认知科学支持目标、注意、线索和情境影响检索，但不能直接推出软件必须使用 LLM Router。LLM Agent
论文支持类型化记忆和动态 retrieval policy，也不能证明其接口适合当前 SDK。

本项目的具体条件是：

- 已有 Harness→Memory 的公共 v1 协议和严格 query/result hash；
- 已有两秒 deadline、有界 item/byte、durable replay 和隐私 scope；
- SQLite 已有 message/fact FTS、vector 和 recent candidates；
- 尚无 Episode、Procedure、ProspectiveIntent 的一等模型；
- SDK 需要保持 Host 无关，不能把某个 Provider SDK 变成路由权威。

因此采用“改造后的主模型工具路由”：主 Agent LLM 在正常工具循环中提议，确定性代码验证并执行；
不能直接照搬外部 Agent 框架，也不能让 LLM 绕过 SDK 的状态和隐私边界。

## 5. 解剖麻雀

选择一条覆盖面最大的典型链路：

> “按照上次认可的发布方式上线，发布完成后提醒我。”

它同时要求：

- Semantic：项目、生产和用户硬约束；
- Episodic：上次发布事件及结果；
- Procedural：适用于当前环境的发布流程；
- Prospective：发布完成事件触发的通知意图；
- Evidence：当流程或约束发生冲突时可追溯原始证据；
- Working memory：在当前阶段只投影实际需要的部分。

架构基线阶段应从 Host 输入、Harness 请求、SDK routing、SQLite 候选、资格门、result payload 一直追到
最终 Context，不能只测试一个独立 Router 函数。

## 6. 实践—认识—再实践：必须通过的 spike

### Spike A：公共协议与幂等性

- 构造最小 RecallContext v2；
- 验证 context 进入 canonical query hash；
- 同 query text、不同 recipient/environment 不得重放旧结果；
- v1 请求仍有明确兼容或拒绝行为；
- 用真实 sibling wheel/consumer 跑协议测试。

### Spike B：主模型路由质量

建立覆盖以下类别的冻结语料：

- 不需要长期记忆；
- 明确过去经历；
- 稳定事实与偏好；
- 隐含程序需求；
- 时间型和事件型前瞻需求；
- 冲突、过期、审计、隐私和对抗表达。

使用本次选定的主 Agent LLM 工具路由，至少记录 required route 漏失、额外 route、禁用 route、
Memory tool 调用率、端到端延迟和 Token 成本；同时验证不需要记忆的轮次能在同一生成流直接回答并留下
`no_recall` decision。指标阈值应在 acceptance 中由用户确认，不能事后按结果改。

### Spike C：典型链路端到端

让“发布并提醒”场景走真实 Host→Harness→Memory SDK 调用链，证明四类长期记忆能正确组合，原始证据
只在冲突/审计时读取，最终结果满足 byte/item/deadline 上限。

### Spike D：LLM 和数据故障

- LLM timeout、拒答、非法 JSON、重复 Route、超长 query；
- embedding 降级、无候选、候选冲突；
- LLM 不可用时只执行确定性强触发，不扩大范围；
- 任何失败不得绕过主体、active 状态和隐私门。

## 7. 集中优势兵力

第一轮不平均研究所有 schema。优先歼灭这个不确定项：

> 主 Agent LLM 工具路由能否在可接受的 deadline/预算内减少漏召回，同时不增加错误和隐私不当召回？

如果不能，先重做路由边界；不应继续铺开五类表结构和 UI。

## 8. 打歼灭战而不是补丁

如果调查确认根因是现有 v1 协议只携带 query text，正确解法应升级公共 RecallContext、类型化模型和
结果投影；不能靠给 query 拼接环境字符串、继续增加 Fact category、或在 Retriever 中堆正则特例。

用户已经明确选择主模型判断，因此 spike 的失败出口不是悄悄退回独立小模型，而是回到用户重新讨论
Agent loop、工具协议、强触发和预算边界。

## 9. 达到“可靠 plan”的条件

只有以下条件全部完成后，才能称为可靠的可执行 plan：

1. 用户确认主要矛盾和外部行为；
2. `acceptance.md` 冻结可测标准；
3. Host→Harness→Memory→Context 生产链路完成架构基线；
4. 上述关键假设全部有真跑 spike 证据；
5. primary challenger 和必要专项 challenger 无未关闭 P0/P1；
6. 每个 AC 都追溯到代码任务和决定性测试；
7. 用户 review 后写入 `plan-status: finalized (plan-bs)`。
