# TaskScope 信息载体与审计分层

> 状态：已获用户确认
> 日期：2026-08-30
> 原则：Markdown 不是事实源；完整审计、机器恢复和 Agent 快速阅读使用不同载体

## 1. 为什么 README、STATUS、Checkpoint 不够

这三个载体分别能回答：

- README：任务是什么；
- STATUS：现在做到哪里；
- Checkpoint：某一时刻如何恢复机器状态。

但它们不能完整回答：

- 每次模型和工具真实输入输出是什么；
- 某个步骤为什么被修改、取消或恢复；
- 哪个文件在何时由哪个 Run 改变，before/after hash 是什么；
- STATUS 的一句结论依据哪些原始 evidence；
- LLM 摘要写错后如何重建事实；
- 多次 checkpoint、计划 revision、binding revision 如何演化。

因此 TaskScope 应采用五层信息结构，而不是三个文件。

## 2. 五层结构

```text
L0 Raw Evidence Store             完整原始记录，永久保存
        ↓ exact ID + hash
L1 Append-only Audit Ledger       发生了什么、谁做的、为什么、关联什么
        ↓ deterministic reducers
L2 Canonical Task State           当前任务/步骤/绑定/决定/验证状态
        ↓ versioned snapshots
L3 Checkpoints & Resume Package   机器可恢复状态
        ↓ materialized views
L4 Human/Agent Documents          README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE
        ↓ derived embeddings
L5 Search Index                   向量+FTS，只负责发现
```

上层都可以从下层重建。任何 Markdown 和向量索引损坏都不能改变 L0/L1 的事实。

## 3. L0：Raw Evidence Store

完整保存：

```text
Conversation
  user/assistant/tool messages, attachments, exact turn spans

LLM
  provider request/response evidence, model/prompt/schema version,
  tool calls, Token/cost/latency, validation result

Tool/Execution
  call arguments, outcome, stdout/stderr refs, retries, permission receipts

Files/Artifacts
  canonical root_ref + relative path, before/after hash, patch/commit/artifact refs

Verification
  test command, environment, result, logs/screenshots/receipts refs

Authority
  mode snapshot, workspace binding receipts, approvals, denials, revocations
```

大型内容保存在 Host-owned content-addressed object store，数据库记录 object ID、SHA-256、media type、size、
privacy classification 和 encryption metadata。不得把 raw secrets 复制到 Markdown 或向量索引。

## 4. L1：Append-only Audit Ledger

`task_events` 是 TaskScope 的总时间线。每个 event 包含：

```text
event_id / task_scope_id / sequence
event_type / actor / occurred_at / recorded_at
source evidence refs + hashes
reason_code + reason_text
old/new semantic state refs
supersedes_event_id
idempotency_key / event_hash / previous_event_hash
```

可选 hash chain 用于发现顺手改写；它不是 hostile-host 独立信任锚。事件永不 update/delete；纠正通过新 event
supersede，取消通过新 event cancel，恢复通过新 event reopen。

## 5. L2：Canonical Task State

机器查询不应解析 Markdown。使用版本化结构化表/JSON：

```text
TASK.json-equivalent
  identity, title, goal, scope, DoD, lifecycle status

PLAN.json-equivalent
  step tree, dependencies, status, revision

WORKSPACES.json-equivalent
  task_home, exact root bindings, access, health, binding-set revision

DECISIONS.json-equivalent
  active/contested/superseded/cancelled decisions and evidence

ARTIFACTS.json-equivalent
  files, commits, generated artifacts and lineage

VERIFICATION.json-equivalent
  acceptance/test/evidence states
```

“`.json-equivalent`”表示 canonical authority 可以物理存在 SQLite，不要求把所有状态真的双写成 JSON 文件。
Task Home 中的 JSON manifest 是带 hash 的可重建快照。

## 6. L3：Checkpoint 与 Resume Package

Checkpoint 不应该只是一个不断覆盖的文件，而是不可变 revision 集：

```text
checkpoints/<checkpoint_id>.json
  task/plan/workspace/decision/verification revision set
  current step and next action
  last success/failure
  repo/branch/HEAD/dirty manifest
  relevant evidence refs
  payload hash
```

打开任务时，Host 对最新有效 checkpoint 做 drift validation，再生成一次性的 `TaskResumePackage`。Resume Package
是本次模型 Context 输入，不是新的事实源。

## 7. L4：给人和 Agent 阅读的文件

建议将快速阅读层扩展为六个稳定文件：

### `README.md` — 这是什么

目标、动机、范围/非范围、项目、DoD、总体架构、关键入口和长期约束。低频更新。

### `PLAN.md` — 准备怎么做

当前有效步骤树、依赖关系、验收映射和 plan revision。步骤修改不覆盖历史，旧 revision 在 canonical state/event
中永久保留。

### `STATUS.md` — 现在在哪里

当前 lifecycle/phase/active step、完成/待处理/阻塞、workspace health、最近测试和下一步。步骤 terminal 或状态
变化时更新。

### `DECISIONS.md` — 为什么这样做

重要决定、替代方案、原因、evidence、supersedes/cancel/reopen 关系。避免未来 Agent 只看到结果却重新踩一遍
已经否决的路线。

### `RESUME.md` — 下一位 Agent 先做什么

最新 checkpoint 的人类可读投影：从哪里开始、先验证什么、不能假设什么、哪些 drift/阻塞必须处理。每次
checkpoint 更新。

### `EVIDENCE.md` — 凭什么说做完了

验收条款、测试/人工证据状态、命令、Run/scenario ID、artifact/ref/hash 和 remaining gates。只列索引和结论，
不内嵌大型原始日志或敏感内容。

可选按需生成：

- `TIMELINE.md`：从 task_events 生成的可读时间线；
- `CHANGES.md`：跨 workspace 的文件/commit/配置变化视图；
- `COST.md`：模型调用、Token、延迟、费用聚合；
- `PRIVACY.md`：受控权限下的记忆/披露/逻辑遗忘决策视图。

## 8. Task Home 建议布局

```text
<task_home>/
  README.md
  PLAN.md
  STATUS.md
  DECISIONS.md
  RESUME.md
  EVIDENCE.md
  .simple-harness/
    MANIFEST.json
    TASK-SNAPSHOT.json
    PLAN-SNAPSHOT.json
    WORKSPACES.json
    DECISION-INDEX.json
    VERIFICATION-INDEX.json
    checkpoints/
      <checkpoint_id>.json
```

L0/L1 原始 evidence 和 event authority 默认留在私有 app data/DB，不直接写入 Task Home：原始对话、工具输出和
Provider evidence 可能含隐私或凭据，且体积会快速增长。Task Home 通过 immutable IDs/hashes 指向它们。

需要完整复查或迁移时，`task_scope_export(task_scope_id)` 生成受控审计包：

```text
manifest + canonical states + event ledger + evidence index + selected raw objects
```

导出需记录 purpose、权限、过滤项和 export hash，不能把“全部导出”变成凭据泄露通道。

## 9. 更新频率

```text
每个动作/调用/状态变化
  -> L0 evidence + L1 event（不额外调用 LLM）

计划/步骤结构变化
  -> L2 PLAN revision + PLAN.md

步骤完成/失败/取消/阻塞
  -> L2 state + STATUS.md

关键决定建立/修改/撤销
  -> L2 decision + DECISIONS.md；必要时 README

Run terminal / pause / block / complete
  -> immutable checkpoint + RESUME.md

测试或验收状态变化
  -> verification state + EVIDENCE.md
```

确定性代码先写事实和结构化状态；需要自然语言总结时由主模型提出 projection patch，代码要求 evidence refs 后
写入新 revision。projection 失败不影响原始执行记录。

## 10. 已确认结论

不采用“README + STATUS + 一个 Checkpoint 文件”作为 TaskScope。已确认采用：

- DB/object store 的完整 raw evidence；
- append-only task event ledger；
- 版本化 canonical task state；
- immutable checkpoint revisions；
- README、PLAN、STATUS、DECISIONS、RESUME、EVIDENCE 六个稳定阅读视图；
- 可重建 TaskScope Search Index。

这样既满足完整审计，也能让 Agent 不必阅读多年原始日志就恢复任务。
