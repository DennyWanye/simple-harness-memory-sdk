# TaskScope 事件记录与语义更新流水线

> 日期：2026-08-30  
> 状态：已获用户确认

## 1. 已确认结论

TaskScope 不使用正则或关键词匹配判断目标、决定、计划、阶段和恢复信息。采用：

- Host 确定性记录全部客观运行事件；
- 当前主模型理解语义变化，并调用预先注册的 `task_scope_update` 工具；
- 工具参数是结构化 `TaskScopeMutationPlan`，LLM 只能提出操作；
- Host 维护结构化 dirty flags，并用 closure gate 防止模型漏掉应收口的任务变化；
- Host 校验证据、revision、权限和状态迁移后，才写 canonical state；
- 不运行独立后台总结模型，不为每个低层操作增加一次 LLM 调用。

## 2. 两条并行记录链

### 2.1 客观事实链：不经过 LLM

Host `TaskEventRecorder` 从真实运行时直接追加：

- user/assistant/provider turn；
- provider invocation、模型、prompt/schema、Token、延迟和终态；
- tool call/result/error；
- 文件 effect、before/after hash；
- command、exit code；
- test run、case、PASS/FAIL/BLOCKED；
- artifact/evidence ref；
- binding/checkpoint/context snapshot revision；
- Run/step 的机器状态事件。

这些记录不等待模型总结。LLM 不得把真实结果重新描述后充当原始事实。

### 2.2 语义状态链：主模型提案，Host 裁决

当前主模型负责识别：

- 目标、范围或完成条件变化；
- 用户确认、推翻或补充关键决定；
- 计划步骤新增、重排、修改或取消；
- 某组客观事件对任务阶段的语义影响；
- 暂停、阻塞、恢复或完成所需的信息；
- Context 压缩前未来 Agent 必须知道的恢复语义。

识别到变化后调用 `task_scope_update`；不能直接写 DB、Markdown、Checkpoint 或 Search Index。

## 3. 工具协议

预定义工具接收：

```text
TaskScopeMutationPlan
  task_scope_id
  base_revision
  outcome: mutate | no_mutation
  operations[]
  closure_reason?
  source_turn_id
  idempotency_key
```

首版 operation 白名单：

```text
goal.set | goal.revise
scope.include | scope.exclude
decision.record | decision.supersede
plan.step.add | plan.step.revise | plan.step.cancel | plan.reorder
task.pause | task.block | task.resume | task.complete
resume.update
checkpoint.request
relation.add
```

每个 operation 必须带稳定 reason code、简短说明和 `evidence_refs[]`。说明是可审计结论，不保存隐藏思维链。

`outcome=no_mutation` 只在 closure gate 要求收口、但模型判断客观事件没有改变任务语义时使用；平常没有任何
dirty flag 且无语义变化时不需要调用工具。

## 4. Dirty Flags 不是语义判断

Host 只根据结构化 runtime event 设置 dirty flags：

```text
task_scope_created
binding_revision_changed
filesystem_effect_committed
artifact_emitted
test_run_terminal
step_machine_state_changed
run_terminal_requested
context_compaction_pending
uncheckpointed_effects
```

它们只表示“存在需要收口检查的事实”，不表示目标一定变化。例如八次文件修改只产生客观 event 和
`filesystem_effect_committed=true`；主模型可以在最终收口时一次性判断这些修改是否导致 plan/status/decision
更新。

## 5. Closure Gate

主模型的系统契约要求在最终回答前主动完成语义收口。Host 拦截最终化请求并检查：

1. 无 dirty flag，且本轮未产生显式语义变化：允许直接结束；
2. 已有覆盖当前 event watermark 的有效 mutation receipt：允许结束；
3. 有 material dirty flag，但没有 receipt：暂存最终文本，要求同一主模型补交一次
   `mutate` 或 `no_mutation`；
4. 补交仍非法、超时或拒绝：原始事实保留，Run 标记 `semantic_closure_pending`，不得伪造语义状态；
5. pause/block/complete/context compaction 等硬边界未收口时，不生成声称可恢复的 Checkpoint。

补交是漏调用时的安全兜底，不是每轮固定增加一次模型请求。评估必须分别统计主动调用率、closure 补交率、
错误 mutation 率和漏记纠正率。

## 6. Host 校验与提交

`TaskScopeMutationValidator` 至少验证：

- `task_scope_id` 是本 Run 冻结的可信 Scope；
- `base_revision` 通过 CAS，过期计划不能覆盖新状态；
- evidence refs 存在、属于允许主体/Scope，且未被 active suppression 禁止普通使用；
- operation/type/字段/长度在版本化白名单内；
- cancel/supersede/complete 等操作满足合法状态迁移和必要 evidence；
- `task.complete` 不能仅凭模型宣称，必须满足完成条件或明确保留未完成项；
- payload 已做凭据过滤，不含权限扩大或直接数据库/文件写指令；
- idempotency key 重放得到同一 receipt，不同 payload 复用同一 key 返回 conflict。

通过后单事务追加 mutation decision/event、更新 canonical state revision，并写 projection/index outbox；失败只
追加拒绝 decision，不产生半状态。

## 7. 六阅读视图与 Checkpoint

六个视图从 canonical state 和 evidence refs 确定性物化：

- README：goal/scope/主要约束和稳定概览；
- PLAN：当前计划 revision 与步骤关系；
- STATUS：步骤机器事实加已验证的语义状态；
- DECISIONS：decision operations 及证据/替代关系；
- RESUME：最后有效 checkpoint 和 `resume.update`；
- EVIDENCE：工具、文件、测试和 artifact 事实索引。

LLM 已在 mutation 中提供必要语义，不再启动另一个模型重写文档。projection 失败不会回滚事实和 canonical
state；Worker 按 revision 幂等重建。

## 8. 调用频率

不按 tool call 粒度调用。一次语义阶段可将多次文件、命令和测试事实批量引用到一个 mutation：

```text
8 次文件 effect + 3 次测试 + 1 次方案调整
  -> 11+ 条 raw event
  -> 1 个 TaskScopeMutationPlan
  -> 1 个 canonical state revision
```

建议收口点是目标/范围/关键决定刚发生时、阶段终态、最终回答前、pause/block/complete、Context 压缩前。这样
保留完整性，同时控制工具续推理、延迟和 Token 成本。
