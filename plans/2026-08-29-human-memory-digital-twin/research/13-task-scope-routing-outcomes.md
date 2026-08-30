# 单一主对话的 TaskScope 路由终态

> 日期：2026-08-30  
> 状态：已获用户确认

## 1. 已确认边界

TaskScope 只服务于具有执行过程、状态、证据或未来恢复需求的任务。普通对话和用户级长期记忆永久保存在
primary conversation 与 Memory SDK 中，但不为了保存记忆而滥建 TaskScope。

TaskScope 不是 Episode/Semantic/Procedure/Prospective 的上位容器。认知记忆可以引用 TaskScope evidence，
也可以完全是跨任务或无任务的用户级记忆。

## 2. 五种路由终态

### `direct_standalone`

当前 Context 足够，不需要记忆、TaskScope 或项目工具。主模型直接回答；Host 保存原始 turn 和
`outcome=no_recall`，不改变 active scope cursor。

### `memory_standalone`

回答需要用户记忆，但没有持续任务。主模型提出 `scope=standalone + RecallPlan`，Memory SDK 类型化召回；
不创建 TaskScope，不授予项目工具权限。该 turn 仍可产生用户级认知记忆。

### `continue_active`

当前 query 明确延续 active TaskScope。使用 exact active scope 和冻结 binding-set，不执行向量 TaskScope
发现；按需加载当前 TaskScope 状态和相关记忆。

### `resume_existing`

用户指向较早任务且没有可信 exact ID。主模型先调用 `task_scope_search` 获取少量候选，再选择 exact ID 调用
`task_scope_open`；候选仍有歧义且会影响项目、文件、权限或答案事实时询问用户。搜索结果不能授予权限。

### `create_new`

请求包含项目 effect、多步骤执行、artifact、完成/阻塞状态、未来恢复要求或用户明确要求保存进度。主模型
只提出 `TaskScopeProposal(action=create)`；Host 幂等创建 scope、task_home 和必要 binding receipt。

## 3. Host 硬门

- standalone 不暴露 filesystem/shell/project artifact state-changing tools；
- 任意项目 effect 必须已有可信 TaskScope 与冻结 binding-set revision；
- continue 只能使用当前 Run 冻结的 exact ID；
- resume 必须由候选发现进入 exact canonical open，不能直接相信向量内容；
- create 必须经过 Host provision/identity/permission/idempotency 校验；
- 路由歧义若只影响个性化程度可以保守回答，若影响项目、文件、权限、外部动作或关键事实则必须确认；
- 所有五种终态都保留原始对话、模型 invocation 和结构化 route/recall decision。

## 4. 典型反例

以下信息可能形成长期认知记忆，但默认不建 TaskScope：

- 用户饮食、表达和交互偏好；
- 身份、关系、长期目标；
- 跨任务工作习惯；
- 模糊愿望形成的 Semantic Goal；
- 单次自包含的知识问答、翻译或改写。

“以后回答尽量简洁”可以形成用户级 Procedure；“有机会想学画画”可以形成 Semantic Goal；两者都不因为
需要记忆而自动生成任务档案。

## 5. 需要评估的错误

- TaskScope over-creation：standalone 被错误建成任务；
- TaskScope under-creation：发生项目 effect 或需要恢复却没有任务档案；
- active-scope inertia：因为当前有 active scope，把无关 query 强行塞入当前任务；
- false resume：相似名称导致恢复错误历史任务；
- memory/scope conflation：为了召回用户偏好而创建 TaskScope；
- permission by retrieval：把搜索候选误当作已授权 workspace。

冻结评估集必须分别统计这些错误，而不是只统计一个总 accuracy。
