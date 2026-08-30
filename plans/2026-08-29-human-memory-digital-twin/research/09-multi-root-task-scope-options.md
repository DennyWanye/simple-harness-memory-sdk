# 多文件夹 TaskScope 绑定方案比较

> 状态：方案 C + mode-aware C2 已获用户确认
> 日期：2026-08-30
> 主要矛盾：任务由一个目标定义，但执行可能跨多个互不包含的本地文件夹

## 1. 典型场景

“升级 Memory SDK 并接入产品”是一个目标、一个完成条件和一条决策链，但会同时修改：

```text
/Users/denny/projects/simple-harness-memory-sdk
/Users/denny/projects/simple-harness-sdk
/Users/denny/projects/simple_harness
```

按文件夹强拆为三个 TaskScope 会丢失统一步骤、跨仓协议版本、发布顺序和端到端验收；绑定它们的公共父目录
`/Users/denny/projects` 又会把大量无关项目授权给 Agent。

## 2. 方案 A：一个 TaskScope 只能绑定一个文件夹

优点：状态和权限模型最简单。

缺点：跨仓、前后端、App+SDK、文档+代码等正常任务被人为拆分；三个 TaskScope 之间还要实现父子协调、统一
checkpoint 和统一 DoD，复杂度只是被转移。该方案不满足当前需求。

## 3. 方案 B：绑定所有文件夹的公共父目录

例如直接绑定 `/Users/denny/projects`。

优点：现有单 root 工具几乎不用改。

缺点：权限范围远大于任务范围；Agent 可以看见和修改无关项目；无法审计某个目录为什么被授权；父目录可能是
home、磁盘或共享目录。该方案违反最小权限，不建议。

## 4. 方案 C：一个 Task Home + 多个精确 Workspace Bindings（推荐）

```text
TaskScope
├─ task_home（唯一、managed）
│  ├─ README.md
│  ├─ STATUS.md
│  └─ MANIFEST.json
│
└─ workspace_bindings（一个或多个）
   ├─ root_memory_sdk -> exact folder A, write
   ├─ root_harness_sdk -> exact folder B, write
   └─ root_host -> exact folder C, write
```

`task_home` 保存任务可读投影和 manifest，不等于执行权限。每个 workspace binding 单独保存 canonical path、
filesystem identity、role 和 access mode；不把公共父目录授权给模型。

目标关系变成多对多：

```text
一个 TaskScope -> 1..N 个 WorkspaceFolder
一个 WorkspaceFolder -> 0..N 个 TaskScope
```

同一个项目可以同时有“修复登录”和“重构支付”两个不同 TaskScope；同一个跨仓 TaskScope 也可以绑定多个项目。

## 5. 数据模型

```text
task_scopes
  task_scope_id PK
  task_home_root
  task_home_identity
  binding_set_revision
  ...

task_workspace_bindings
  binding_id PK
  task_scope_id
  root_ref UNIQUE per task
  canonical_root
  filesystem_identity
  source: managed | explicit | trusted_project
  role: primary | dependency | documentation | artifact | other
  access_mode: read | read_write
  state: active | unavailable | revoked
  added_event_id
  added_at
  binding_hash

task_workspace_binding_events
  event_id PK
  task_scope_id
  binding_set_revision
  action: add | mark_unavailable | revoke
  binding_id
  reason / evidence refs
  occurred_at
```

原绑定行不更新目标路径。`binding_set_revision` 每次合法扩展递增，并进入 RunStart、ContextSnapshot 和 tool
authority fingerprint。

## 6. 工具调用不能再使用裸绝对路径

模型看到的是有限 root catalog：

```json
{
  "roots": [
    {"root_ref": "memory_sdk", "label": "Memory SDK", "access": "read_write"},
    {"root_ref": "harness_sdk", "label": "Harness SDK", "access": "read_write"},
    {"root_ref": "host", "label": "simple_harness Host", "access": "read_write"}
  ]
}
```

工具参数使用 `root_ref + relative_path`：

```json
{
  "root_ref": "memory_sdk",
  "relative_path": "src/simple_harness_memory/core/manager.py"
}
```

Host 将 root_ref 解析成冻结的 exact binding，再校验最终路径仍在该 root 内。模型提交的任意新绝对路径不能越过
binding set。

## 7. 创建时如何绑定多个文件夹

### 用户没有给路径

Host 创建唯一 task_home，并把它同时作为第一个 managed execution root：

```text
bindings = [task_home(read_write, primary)]
```

### 用户给出一个或多个路径

Host 始终创建 private/managed task_home 存放任务投影；对用户明确给出的每个文件夹分别 canonicalize、验证
filesystem identity，再写一个 binding。用户给出三个项目就得到三个 exact roots，而不是绑定共同父目录。

## 8. 后来发现还需要另一个文件夹

这里有两个可选规则：

### C1：绑定集合完全冻结

创建后不能加、删、替换。需要新目录就创建新 TaskScope。

- 优点：最简单、最强不可变；
- 缺点：真实任务经常执行到一半才发现依赖另一个仓库，会被迫放弃统一档案。

### C2：mode-aware append-only 扩展（已确认）

已有 binding 永不替换；允许追加新 exact root，确认规则由 Host 冻结的运行模式决定。

#### Manual 模式

必须满足其一：

- 用户本轮明确给出路径并要求纳入当前任务；
- 用户通过 folder picker 明确选择；
- 主模型发现需要新目录后询问用户，用户确认。

#### Auto 模式

主模型可以根据当前任务、工具结果和可信 Project/Filesystem discovery 提出 `WorkspaceBindingAppendProposal`；
Host 验证通过后直接追加，不再逐次询问用户。Auto 模式必须来自 Host 可信设置/当前 Run snapshot，模型无权
自行开启或把 Manual 改成 Auto。

Auto 的候选路径必须是配置的 simple_harness workspace root 的**真后代目录**。macOS/Linux 未配置时，Host
默认使用 `~/SimpleHarnessWorkSpace`。canonicalize/symlink resolve 后落在该 root 之外的路径必须拒绝，并要求
切换 Manual 由用户明确绑定；Auto 不能绑定 workspace root 本身。Windows 默认根另行确定，不在本条推断。

两种模式下都必须：

- canonicalize exact directory 并验证真实存在、权限和 filesystem identity；
- 拒绝 `/`、用户 home、managed workspace root 本身、项目集合父目录等明显过宽目标；
- 拒绝用新路径替换已有 binding；重叠/重复 root 只能得到幂等 no-op 或更窄 exact binding；
- 保存 proposal、模型 invocation、mode snapshot、验证 reason、old/new binding-set hash 和最终 decision；
- 追加后生成新 `binding_set_revision`；正在运行的 Execute Run 仍使用旧 revision，新增目录只能从新的
  continuation Run 生效。

Auto 只豁免“是否把这个 exact root 加入当前 TaskScope”的逐次确认，不豁免高风险工具本身的权限/确认规则，
也不能据此自动发布、删除、付款、修改系统权限或执行其他不可逆外部动作。

因此“不可切换”被精确定义为：

- 不允许把已有 binding A 的目标改成 B；
- Manual 不允许无用户证据地扩大目录集合；
- Auto 允许主模型提案经代码校验后，在保留旧 binding 和历史的前提下追加 B；
- revoke 只停止未来访问并保留历史 binding/event，不删除原记录。

## 9. Resume 行为

`TaskResumeCheckpoint` 保存整个 binding set revision。恢复时逐个验证：

```text
all roots valid       -> 可继续
read-only root missing -> 报告 drift，按步骤需要决定是否阻塞
required write root missing -> TaskScope blocked
identity changed      -> fail-closed，不自动追踪新路径
```

README/STATUS 必须列出各 root 的用途、访问模式和健康状态，让未来 Agent 知道为什么任务涉及多个目录。

## 10. 推荐结论

采用方案 C + mode-aware C2：TaskScope 有唯一 task_home，但可以绑定多个 exact workspace roots；已有目标不可
替换。Manual 下新增 root 需要用户明确授权，Auto 下由主模型提案并由 Host 校验后直接 append-only 生效。两种
模式都保留完整 revision/audit，且目录扩张不改变高风险工具权限规则。
