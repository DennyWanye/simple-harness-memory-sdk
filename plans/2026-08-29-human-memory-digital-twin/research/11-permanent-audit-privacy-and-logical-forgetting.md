# 永久审计、隐私隔离与逻辑遗忘

> 日期：2026-08-30  
> 状态：已获用户确认

## 1. 已确认的语义

本系统中的“永久保存”和“遗忘”不是互相否定的两个物理操作：

- **永久保存**：经过入库前凭据过滤的业务原始证据、事件、决策和状态变迁不得物理删除或覆盖；
- **逻辑遗忘**：撤销相关内容在普通执行路径中的可见性、可检索性、可投影性和可使用性；
- **密封审计**：被逻辑遗忘的原始事实仍保留，但只有用户明确发起、声明目的的审计/复查路径可以读取；
- **凭据例外**：密码、API key、Token、Cookie、二维码认证材料等不得先落盘再“遗忘”，而是在进入永久证据域之前过滤。

因此：

> 永久保存不等于永久提供给模型；逻辑遗忘撤销的是使用权和可见性，不是改写历史。

## 2. 三个访问平面

### 2.1 Normal Execution Plane

普通对话、任务恢复、TaskScope 搜索、记忆召回、动态 Context、数字孪生投影和六个阅读视图均属于普通执行面。
任何 active suppression 都必须在本平面 fail-closed：即使旧向量、缓存或旧文档还未完成重建，也不得返回
被抑制内容。

### 2.2 User Audit Plane

只有用户明确提出审计、复查来源或解释系统决策时才可进入。请求必须形成结构化 `AuditAccessDecision`，至少包含：

- requester/subject；
- TaskScope 与证据范围；
- 审计目的；
- 请求时间和访问结果；
- 是否允许显示原文，或只显示脱敏来源、时间和 reason code。

普通 Agent 不能通过换一种 query、搜索 exact ID 或打开旧 Checkpoint 绕进审计面。

### 2.3 Sealed Forensic Plane

保存完整原始证据、历史投影 revision、被替代或被抑制内容及全部 lineage。该平面不注册为普通 Agent tool，
只能由受控审计服务按已批准的 `AuditAccessDecision` 读取。所有读取本身也追加审计事件。

## 3. 逻辑遗忘的数据模型

用户提出遗忘后，LLM 只能提出目标范围；Host/Memory SDK 确定性解析证据引用并写入不可变
`SuppressionDirective`：

```text
suppression_id
subject_id
target_kind              memory | evidence_span | entity | claim | task_projection
target_refs[]
scope                    global | task_scope | recipient | purpose
reason_code
requested_by
effective_at
status                   active | revoked
supersedes_directive_id?
source_turn_id
decision_record_id
```

不修改旧证据的内容或状态；撤销遗忘也不删除 directive，而是追加新的 revoke decision，保留完整 lineage。

## 4. 强制执行顺序

```text
输入/工具结果
  -> 凭据与认证材料过滤
  -> 永久 raw evidence commit
  -> Suppression/Privacy policy ledger
  -> memory / TaskScope candidate generation
  -> suppression-first eligibility filter
  -> ranking / token budget
  -> final Context disclosure filter
  -> frozen ContextSnapshot + decision log
```

关键点是 suppression 必须同时位于排序之前和最终 Context 发送之前。向量库、FTS、缓存、README 或
Checkpoint 都不是安全边界；即使它们含有延迟清理的旧内容，资格门仍必须阻止披露。

## 5. 逻辑遗忘后的派生更新

写入 directive 的同一事务产生 outbox 事件，异步触发：

1. 从 Short-Horizon Conversation Index 和长期 Memory Index 中撤下可检索文本；
2. 从 TaskScope Search Index 中删除或重写泄露内容的向量/全文字段；
3. 重新物化 README、PLAN、STATUS、DECISIONS、RESUME、EVIDENCE 当前视图；
4. 重建 TaskScope 当前状态投影、WorkingMemoryProjection 和数字孪生/世界模型展示投影；
5. 使相关 Context cache、ResumePackage 和旧 retrieval receipt 失效；
6. 保留“发生过 suppression 决策”的非泄露占位信息和 evidence hash lineage。

旧原始证据与旧 revision 迁入或保留在密封审计面，不再由普通 `task_scope_open`、历史 Checkpoint、搜索、
导出或恢复流程返回。任何派生更新失败都可重试，但 active directive 的同步资格门立即生效。

## 6. 入库前凭据过滤

“完整记录”不能解释为保存认证材料。Host 在 raw evidence commit 前执行确定性 secret filter：

- 已知结构化认证字段直接剔除；
- Authorization/Cookie/header、环境变量和值形态使用规则化检测；
- tool/provider payload 只保留允许字段、hash、长度和必要诊断元数据；
- 疑似凭据使用不可逆占位符，例如 `[REDACTED_CREDENTIAL]`，并记录过滤 reason code；
- 原始未过滤 payload 不进入日志、临时文件、embedding 请求或 LLM invocation evidence。

这不是物理删除，因为敏感认证材料从未成为系统承诺永久保存的业务证据。

## 7. 必须证明的性质

- active suppression 后，即使索引重建失败、缓存陈旧或 exact ID 已知，普通路径仍无法取回内容；
- 删除并重建全部派生索引与六个阅读视图，不会复活被抑制内容；
- 普通 Agent 不能把审计目的伪装成任务目的获得访问；
- 显式用户审计可以得到被授权范围内的来源和决策链，且本次读取会再留审计记录；
- revoke 通过追加新决策恢复被允许的派生使用，不覆盖原 suppression 历史；
- credential canary 在 DB、对象存储、日志、文档、向量输入和 ContextSnapshot 中均不存在。

## 8. 已确认结论

采用“永久密封事实 + 可撤销使用权”的模型。原始业务证据永久保留；普通运行、审计访问与密封取证严格
分面；逻辑遗忘通过 append-only suppression directive 立即阻断所有普通使用，再异步重建派生数据；凭据
在进入证据域前过滤，永不落库。
