# 可永久恢复的 TaskScope 档案与检索

> 状态：用户目标已确认；存储和召回架构草案
> 日期：2026-08-30
> 核心目标：即使多年后再次继续任务，Agent 仍能知道做过什么、为什么改变、现在从哪里接着做

## 1. TaskScope 的新定义

TaskScope 不是一个任务标签，而是一套模型执行某个任务时形成的**完整任务档案**。它逻辑上包含：

- 与任务有关的全部用户/Agent 对话及准确 turn refs；
- 每次模型 invocation、结构化提案和最终裁决；
- 所有 tool call、tool result、错误、重试和权限确认；
- 任务目标、边界、计划、步骤、当前状态和完成条件；
- 每一步怎么执行、结果是什么、验证证据在哪里；
- 文件、代码、配置和 artifact 的创建/修改，以及修改前后 hash/commit/ref；
- 决定的建立、修改、撤销和被替代关系，以及明确原因；
- 暂停、恢复、失败、阻塞、取消和重新打开的时间线；
- 可供快速理解的 README、当前 STATUS 和可恢复 checkpoint。

TaskScope 的完整性不依赖模型是否写出了一份好摘要。摘要可以错、可以重建；原始 evidence 和 append-only
event timeline 才是事实源。

## 2. 不是“TaskScope 就等于向量数据库”

用户体验上可以说“去 TaskScope 向量库找任务”，但代码必须分开：

```text
TaskScope Archive（事实源）
  ├─ 结构化任务状态
  ├─ append-only 事件时间线
  ├─ 原始 conversation/run/tool/file evidence refs
  ├─ README / STATUS revisions
  └─ checkpoint / artifact / verification refs
             │
             └──生成──> TaskScope Search Index（派生定位器）
                           ├─ vectors
                           ├─ FTS
                           ├─ aliases/entities/project/status
                           └─ canonical task_scope_id + source revision hash
```

向量索引只能回答“哪个任务可能相关”，不能回答“这个任务真实做过什么”。索引损坏或删除后应能从 Archive
重建；Archive 损坏则任务无法可信恢复，因此 Archive 必须 append-only、事务化并永久保存。

## 3. Canonical TaskScope Archive

Host 是唯一 authority。建议在 Host-owned `state.db` 中增加以下逻辑表；可以物理拆表，但不能让向量库成为
主存储：

### 3.1 核心状态

```text
task_scopes
  task_scope_id PK
  primary_conversation_id
  title
  goal
  status: active | suspended | blocked | completed | cancelled
  project_binding_id nullable
  active_step_id nullable
  created_turn_id
  last_active_turn_id
  revision
  created_at / updated_at

task_steps
  step_id PK
  task_scope_id
  parent_step_id nullable
  ordinal
  title
  status: pending | in_progress | completed | failed | cancelled | superseded
  started_event_id / terminal_event_id
  outcome_summary
  revision
```

### 3.2 永久事件流

```text
task_events
  event_id PK
  task_scope_id
  sequence UNIQUE per task
  event_type
  actor_kind: user | agent | code | tool | system
  actor_ref
  source_ref
  source_hash
  payload_json / payload_hash
  reason_code / reason_text
  supersedes_event_id nullable
  idempotency_key UNIQUE
  occurred_at / recorded_at
```

`event_type` 至少覆盖：

```text
task.created / task.paused / task.resumed / task.completed / task.cancelled
turn.linked
provider.invoked / model.proposal / decision.applied / decision.rejected
step.created / step.started / step.completed / step.failed / step.cancelled / step.reopened
tool.called / tool.succeeded / tool.failed / tool.retried
file.created / file.modified / file.deleted_logically / file.restored
artifact.created / artifact.revised
test.started / test.passed / test.failed / test.blocked
scope.project_bound
checkpoint.created
readme.revised / status.revised
```

这里的“file.deleted_logically”只记录任务动作；是否真实删除文件仍服从工具权限和用户授权。TaskScope 原始
event/evidence 自身永远不物理删除。

### 3.3 原始记录关联

不必复制所有大型内容到一个 JSON 字段，但必须建立完整、可校验的关联：

```text
task_evidence_links
  task_scope_id
  evidence_kind: turn | message | run | provider_invocation | tool_effect | file_change | artifact | test
  evidence_id
  evidence_hash
  relation: primary | supporting | produced | modified | cancelled
  linked_event_id
```

Host SessionDB/Run ledger 保存完整原始对话和执行记录；TaskScope Archive 保存精确 ID、hash、关系和必要的稳定
snapshot。导出 TaskScope 时由聚合器把关联证据打包，不能只导出摘要。

## 4. README 与 STATUS

### 4.1 `README.md`

README 回答“这是什么任务”：

```text
# 标题与 TaskScope ID
## 目标与动机
## 明确范围 / 不做什么
## 项目与执行环境
## 完成条件
## 当前整体情况
## 关键决定
## 主要产物与代码入口
## 风险和约束
## 如何恢复本任务
```

### 4.2 `STATUS.md`

STATUS 回答“现在做到哪里”：

```text
# 当前状态、阶段和 active step
## 最近成功 checkpoint
## 已完成步骤（每步 outcome + evidence refs）
## 当前正在执行的步骤
## 待执行步骤
## 阻塞与失败
## 修改、取消、恢复记录及原因
## 当前文件/分支/commit/worktree 状态
## 测试与验收状态
## 下一位 Agent 应执行的第一步
```

README 和 STATUS 都是**带 revision/hash 的物化投影**，由确定性代码从 TaskScope state + events + evidence refs
生成骨架，LLM 只可提出叙述字段更新。每次更新保留旧 revision；当前 `.md` 可以覆盖为最新视图，但历史内容
必须能从 revision/event 恢复。

建议同时在私有 app-data 下物化为：

```text
task-scopes/<task_scope_id>/README.md
task-scopes/<task_scope_id>/STATUS.md
task-scopes/<task_scope_id>/MANIFEST.json
```

这些文件是人类/Agent 可读缓存，不是唯一事实源；删除缓存后可从 DB 重建。原始 evidence 不复制到 Git，也不
写入用户项目目录。

## 5. Resume Checkpoint

只知道“第 4 步进行中”仍不足以安全恢复。每个重要步骤结束、暂停、阻塞或 Run terminal 时生成 checkpoint：

```text
TaskResumeCheckpoint
  task_scope_id / checkpoint_id / revision
  goal / phase / active_step
  completed_steps / pending_steps / blockers
  decisions_active / decisions_contested / cancelled_actions
  project_binding_snapshot
  repo_ref / branch / head_sha / dirty_state_manifest
  files_touched + before/after hashes
  artifacts + tests + receipts
  last_success / last_failure
  next_recommended_action
  evidence_refs
  generated_at / payload_hash
```

恢复时必须重新验证当前项目是否仍和 checkpoint 一致。若 branch、HEAD、文件 hash、工具版本或权限发生漂移，
Agent 先报告 drift，再决定继续、重算或询问用户，不能假装环境没有变化。

## 6. TaskScope Search Index

这是一个独立的、可重建的长期索引，不受“五天短时域”限制。建议每个 TaskScope 建立多类 search document：

```text
task_header      = title + goal + aliases + project + status
task_readme      = README 当前 revision
task_status      = STATUS 当前 revision
task_decisions   = active/superseded/cancelled decisions + reasons
task_artifacts   = file/artifact/test names and descriptions
task_timeline    = 有界事件窗口的语义 chunk
```

检索采用：

```text
vector similarity
+ FTS exact term
+ project/entity/alias match
+ active/suspended/completed status filter
+ last-active recency（仅排序，不淘汰旧任务）
+ user/permission filter（排序前执行）
```

每条索引必须携带：

```text
task_scope_id
document_kind
source_revision
source_hash
embedding_lineage
indexed_at
```

索引可以删除、换模型和重建；TaskScope Archive 永不因此改变。

## 7. 用户说“继续做 xxx”时怎么执行

### 7.1 最近任务已有精确 ID

Routing Context 已有最近 TaskScope 目录。主模型直接提出：

```text
context_route(action=continue, target_scope_id=task_123)
```

Host 校验 ID 后打开 Archive，构建 Resume Package，通常需要 Route + Execute 两次模型调用。

### 7.2 很久以前、当前目录没有该任务

```text
1. 主模型调用 task_scope_search(query="之前的 xxx 任务")
2. Host 查询 TaskScope Search Index
3. 返回 3–5 个候选：ID、标题、目标、项目、状态、最后活动时间、匹配片段
4. 主模型选择 exact task_scope_id，或候选含糊时询问用户
5. 主模型调用 task_scope_open(task_scope_id)
6. Host 从 canonical Archive 生成 TaskResumePackage
7. 冻结项目/工具 authority，进入 Execute Run
```

`task_scope_search` 只返回候选摘要，不能触发项目权限或修改任务；`task_scope_open` 必须使用 exact ID。非常久远
且模糊的任务可能需要三次 Provider invocation：搜索、打开/选择、正式执行。这是避免打开错误项目的安全成本。

## 8. TaskResumePackage

打开档案时不是把所有历史塞进 Context，而是在预算内组装：

```text
protected:
  TaskScope identity + trusted ProjectBinding + active constraints

high priority:
  README + STATUS + latest valid checkpoint

selected:
  当前/下一步骤所需的 decisions, events, conversation spans,
  tool results, file diffs, artifacts and test evidence

page-in refs:
  完整 timeline、原始对话、长日志、历史 checkpoint、旧文件 diff
```

模型需要细节时通过 `task_scope_page_in` 按 exact evidence ref 读取。这样可以永久保留完整档案，同时保持最终
Context 有界。

## 9. 与三类记忆系统的关系

| 系统 | 保存什么 | 保存多久 | 主要用途 |
|------|----------|----------|----------|
| 五天短时域索引 | 最近对话片段 | 索引资格约五天；原文永久 | 找回近期但不在最近 10 轮的对话 |
| TaskScope Archive + Search Index | 一个任务的完整执行档案与定位索引 | 永久 | 发现旧任务并安全恢复执行 |
| 长期认知记忆 | Episode、Semantic、Procedure、Prospective | 按状态/逻辑遗忘策略 | 理解用户、经历、做事方式和未来意图 |

同一 Turn 可以同时属于 TaskScope evidence，并产生 Episode 或 Procedure；但三套系统的 authority 和用途不能
合并成一张“万能向量表”。

## 10. 审计和质量要求

- 任意 `STATUS.md` 结论都能回溯到 task event 和原始 evidence；
- 任意取消/修改必须有 actor、时间、old/new、reason 和 supersedes lineage；
- 任意搜索结果能解释命中的 document、分数、filter 和 source revision；
- 索引返回错误候选不得改变 active TaskScope 或项目权限；
- Resume Package 必须记录选入/排除/裁剪/page-in 的 ContextAssemblyDecision；
- 冷重启、换 Agent、换模型后仅凭 TaskScope ID 和受控 Archive 就能重建 README/STATUS/checkpoint 并继续；
- README/STATUS 叙述错误可以纠正，但不得覆盖或改写原始事件历史。

