# TaskScope 创建权与不可变文件夹绑定

> 状态：创建权、managed/explicit、不可静默换根和 append-only 多根绑定均已确认
> 日期：2026-08-30

## 1. 谁判断、谁创建

职责必须拆开：

```text
主 Agent LLM
  判断语义上是否属于一次性问答、继续旧任务或创建新任务
  输出 TaskScopeProposal
                 ↓
Host 确定性代码
  校验 evidence、现有 TaskScope、路径、用户权限和文件夹 identity
  真正创建 TaskScope、文件夹、数据库记录与不可变绑定
                 ↓
Memory SDK
  接收已经验证的 task_scope_id，用于 evidence 标签和召回亲和度
```

LLM 没有数据库写权限，也不能把自己生成的路径直接变成 workspace/tool authority。

## 2. 什么时候必须使用 TaskScope

主模型在 Route 阶段按语义提出 create/continue/standalone。以下情况提示模型必须 create 或 continue：

- 用户明确说继续、恢复、以后再做某个任务；
- 用户给出或引用一个本地文件夹/workspace；
- 任务需要读写文件、运行命令、调用项目级 Skill/Tool；
- 任务有多个步骤、状态、阻塞或完成条件；
- 任务会产生代码、文档、表格、PPT、报告或其他 artifact；
- 用户要求保存任务进度，以后继续。

普通知识问答、翻译、简单改写和不会延续的一次性问题可以 `standalone`。

代码不能 100% 用规则判断自然语言是否具有长期任务价值，因此语义判断交给主模型；但 Host 可以实施硬门：

- 没有已绑定 TaskScope 的 Route Run 不暴露项目写工具；
- 任意 filesystem/shell/项目 artifact effect 在执行前必须存在可信 folder binding receipt；
- 模型漏建 TaskScope 时最多只能返回文本，不能在无档案状态下静默修改本地项目；
- 漏判通过冻结语料、真实主模型评估、用户纠正和审计指标优化。

## 3. 创建提案

模型输出：

```json
{
  "action": "create",
  "title": "Memory SDK 人类记忆架构升级",
  "goal": "完成记忆 SDK、协议和 Host 动态 Context 升级",
  "folder_binding": {
    "mode": "managed|explicit",
    "path_hint": null
  },
  "evidence_turn_ids": ["turn_..."],
  "confidence": 0.96,
  "reason_codes": ["MULTI_STEP_TASK", "FUTURE_CONTINUATION"]
}
```

这仍只是 proposal。Host 生成 canonical task_scope_id，禁止模型自行指定 ID。

## 4. 两种文件夹绑定方式

### 4.1 managed：用户未指定路径

Host 在配置的 simple_harness managed workspace root 下创建唯一文件夹：

```text
<managed_workspace_root>/
  <safe-title>--<task_scope_short_id>/
```

文件夹名称只用于可读性，真正 identity 是 task_scope_id + filesystem identity。不得仅凭 title 查找或授权。

### 4.2 explicit：用户明确指定路径

Host 必须：

1. 从可信用户输入/Project picker 获取路径，不能只接受模型转述；
2. expand、canonicalize 并验证是可访问目录；
3. 记录 filesystem identity，避免 symlink/path alias 偷换目标；
4. 判断当前用户有权绑定；
5. 生成不可变 `TaskFolderBindingReceipt`。

路径不存在时不得在 managed root 之外擅自创建；应要求用户确认创建位置或改用 managed 模式。

## 5. 已有绑定不可切换，但允许追加新 root

```text
TaskScopeFolderBinding
  binding_id PK
  task_scope_id
  root_ref
  workspace_root
  workspace_source: managed | explicit
  filesystem_identity
  binding_version = 1
  bound_event_id
  bound_by
  created_at
  binding_hash
```

原型阶段不提供已有 root 的 update/switch/handoff API。TaskScope 可以按
[09-multi-root-task-scope-options.md](09-multi-root-task-scope-options.md) 的确认规则追加 exact root，但已有
workspace binding 永远不变：

- 用户想用另一个目录**替换**已有 root：拒绝替换；如果是任务确实新增工作目录，则走 append proposal 生成
  新 binding-set revision；如果是完全换任务，则创建新的 TaskScope 并关联旧任务；
- 文件夹被移动、删除或 filesystem identity 改变：TaskScope 进入 `blocked: workspace_unavailable`，不自动追踪
  新位置，不降级到其他目录；
- 重新开始时 Host 再次校验 canonical path 和 filesystem identity；不一致则先报告，禁止工具执行。

“不可切换”不表示文件夹内容不能变化；Agent 正常工作产生的文件修改会进入 TaskScope event/evidence。冻结的是
workspace 根边界，不是目录内容快照。

## 6. 幂等创建流程

文件系统和 SQLite 无法共享一个真正的 ACID 事务，因此用可恢复 provisioning state machine：

```text
1. Host 保存 TaskScopeCreateDecision + canonical task_scope_id
2. DB 写 task_scope_provisions(state=reserved, target_path, idempotency_key)
3. managed: 在 managed root 创建 exact 目标目录
   explicit: 验证 exact 现有目录
4. 计算 canonical path + filesystem identity
5. DB 事务写 task_scopes + task_folder_bindings + task.created/bound events
6. provision -> committed
7. 生成 README/STATUS/checkpoint 初始 revision
8. 启动 Execute Run
```

任一步骤失败：

- 原始用户 Turn 和 proposal/decision 永久保留；
- provision 保持 failed/retryable 并记录稳定 reason code；
- 不暴露项目写工具；
- 相同 idempotency key 重试收敛到同一 TaskScope 和文件夹；
- 不能通过新建第二个随机文件夹掩盖第一次失败。

## 7. 当前代码的复用与修改

当前 Host `TaskWorkContextResolver.resolve()` 已经支持：

- `explicit_workspace` -> `workspace_source=user_path`；
- `default_workspace_root/task_scope_id` -> `workspace_source=task_default` 并创建目录；
- `TaskWorkContext` 包含 session/run/task/workspace/binding_version。

可以复用路径规范化和 TaskWorkContext shape，但要修改两个关键语义：

1. 当前 task_scope_id 按 session/request/turn 每轮生成，要改成持久 TaskScopeStore 分配并跨 Turn 复用；
2. 当前 ProjectBinding authority 绑定 Session，要改成 `TaskScopeFolderBinding`，唯一主对话本身不携带项目路径。

## 8. 建议的目录内文件

对于 Host 自动创建的 managed task_home，可以安全地物化：

```text
README.md
PLAN.md
STATUS.md
DECISIONS.md
RESUME.md
EVIDENCE.md
.simple-harness/task-scope.json
```

对于用户指定的现有项目目录，不应覆盖项目自己的 README。建议将任务投影放在：

```text
.simple-harness/task-scopes/<task_scope_id>/README.md
.simple-harness/task-scopes/<task_scope_id>/PLAN.md
.simple-harness/task-scopes/<task_scope_id>/STATUS.md
.simple-harness/task-scopes/<task_scope_id>/DECISIONS.md
.simple-harness/task-scopes/<task_scope_id>/RESUME.md
.simple-harness/task-scopes/<task_scope_id>/EVIDENCE.md
.simple-harness/task-scopes/<task_scope_id>/MANIFEST.json
```

Canonical Archive 仍在 Host DB；这些 Markdown/manifest 是可重建投影。若用户项目明确禁止写管理元数据，则只在
private app-data 物化，并让 `task_scope_open` 返回内容。

## 9. 已确认的绑定基数

已确认一个 TaskScope 拥有一个 managed task_home，并可绑定一个或多个 exact workspace roots；同一 existing
workspace 可被多个 TaskScope 绑定。已有 root 不可替换，只能 append。Manual 逐次确认新增 root；Auto 仅在
可信 workspace root 的真实后代中由主模型提案、Host 校验后直接追加。完整规则见
[09-multi-root-task-scope-options.md](09-multi-root-task-scope-options.md)。
