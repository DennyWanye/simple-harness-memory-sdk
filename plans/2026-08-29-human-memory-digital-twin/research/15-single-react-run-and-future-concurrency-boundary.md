# 单 ReAct Run 与未来并发边界

> 日期：2026-08-30  
> 状态：已获用户确认

## 1. 三个不同生命周期

```text
Primary Session   用户唯一、永久的聊天时间线
TaskScope         跨很多 Turn/Run 的永久任务档案
ReAct Run         处理一次用户请求的 Agent 执行过程
```

Run 不是新 Session、TaskScope 专属环境、文件夹、容器或进程。一个 Run 内可以发生多次 provider continuation
和多次 tool effect；同一个 TaskScope 可以在不同时间关联多个 Run。

## 2. 已确认的单 Run 执行链

每个用户请求通常只启动一个 ReAct Run：

```text
user turn
  -> one ReAct Run
       -> model decision
       -> context_route barrier
       -> verified TaskScope state / recall / root refs observation
       -> model continuation
       -> project and non-project tool effects
       -> task_scope_update semantic closure
       -> final response
```

不创建独立 Route Run 和 Execute Run。Agent 保持统一工具层；工具 schema 暴露可按 Context 预算优化，但不
代表 TaskScope 授予工具所有权。项目 effect 由 Host 自动生成 per-Effect `TaskExecutionEnvelope`，绑定 exact
run/task/root/binding revision/effect identity。

`context_route` 是控制屏障：依赖路由结果的项目 effect 必须在模型看到真实 RouteReceipt 后的新 provider
continuation 中提出。路由前的项目 effect 返回 `TASK_SCOPE_REQUIRED`，不通过隐藏工具实现。

## 3. 初版推荐并发策略

唯一主 Session 同一时刻最多一个 **foreground Agent ReAct Run**：

```text
idle -> running(run A) -> terminal -> running(run B) -> ...
```

普通新输入在 A 运行时先永久入账并进入 durable FIFO；A 结束后才启动 B。显式 stop/cancel/pause 是控制信号，
可立即作用于 A，不等待普通队列。初版不把普通自然语言新输入自动解释为 interrupt，也不使用第二个 LLM
Run并行判断；运行中语义 steering 留待后续。

以下不计为并行 ReAct Run：

- Memory extraction/outbox worker；
- embedding/index rebuild worker；
- 文档/知识图谱 projection worker；
- 已返回 lease 的外部进程或 provider job；
- 审计导出等确定性后台任务。

它们可以并发工作，但不能充当第二个 Agent、改变 TaskScope 语义或绕过 foreground effect authority。

## 4. 现在只保留的未来扩展边界

初版不实现多 Run 调度、子代理、父子任务图或并行 merge，但避免把“只能有一个”写死到事实模型：

- 所有 Run、provider invocation、effect、ContextSnapshot 都有稳定 `run_id`；
- active route context 按 `run_id` 保存，不使用进程级单例可变 TaskScope；
- TaskScope canonical state 使用 revision/CAS，effect 有 idempotency key；
- workspace binding 使用版本化 set，effect 记录 exact revision；
- 输入队列、Run lease 和终态是 durable record；
- 并发限制由 Host scheduler policy `max_foreground_runs_per_session=1` 实施，不用不可迁移的数据库形状表达；
- raw evidence 和 decision lineage 不假设事件总是来自唯一未来 Run。

这些是当前正确性本来就需要的边界，不要求实现并行 conflict resolution。

## 5. 明确留到后续

- 同一 Session 多 foreground Run；
- 同一 TaskScope 多 Run 并行写 canonical state；
- 多 TaskScope 并行工具 effect；
- subagent parent/child Run 协议；
- workspace/file lease 和跨 Run 冲突合并；
- 多 Run UI、优先级、公平性、资源配额和统一取消；
- 并行模型成本、上下文隔离和结果合并策略。

后续只有在真实单 Run log 证明存在吞吐或等待问题时，才为这些能力制定独立计划。
