# Prospective outbox 公开源事实接口

最后更新：2026-09-06。接口供 Host S5c RegistrationAuthoritySource 并行接线；实现 WIP、尚未测试或安装，不属于冻结 M0.6.15。工作树 `simple-harness-memory-sdk-typed-short-sources`，分支 `feat/prospective-outbox-source`，base `139dd889720764eae2e9ec580c6cb45b10326c3d`。

## 固定调用契约

```python
await manager.read_prospective_outbox_source(
    principal=principal,       # MemoryPrincipal，Host 当前可信身份
    outbox_id=entry.outbox_id, # public read_outbox 的确切 ID
    payload_hash=entry.payload_hash,
) -> ProspectiveOutboxSourceView
```

方法位于 public `MemoryManager`，所有参数 keyword-only。返回类型拟从 `simple_harness_memory` 根导出。不接受 caller 提交的 scope/run/operation/lifecycle、时间猜测或 grant。无需另造输入 DTO。一次只读一个确切 outbox，不批扫或选最新匹配项。

## 返回字段（属性名固定）

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | `int`，固定 1 |
| `subject` | `str`，持久 principal 的 actor_id |
| `outbox_id`, `outbox_payload_hash` | `str`，确切持久命令与规范 payload SHA-256 |
| `outbox_created_at` | `float`，实际持久 outbox.created_at；有限且非负，纳入 to_json/source_hash；仅 emit 时间，不证明生成 Run/cause |
| `command` | `str`，`registration` 或 `invalidation` |
| `target_memory_id`, `target_revision` | `str`, `int`，命令指向的真实历史认知 revision |
| `registration_revision` | `int`，本 wire 与 target_revision 相等；SDK 核对而非 Host 推断 |
| `target_scope` | `MemoryScope`，历史 revision 的 kind/owner_id |
| `target_task_scope_id` | `str \| None`，历史 revision 持久 task scope；None 不补造 |
| `target_lifecycle_state` | Harness `ProspectiveLifecycleState`，目标历史 revision 的实际状态 |
| `target_run_id`, `target_plan_id`, `target_plan_hash` | `str`，创建目标 revision 的真实 mutation plan/receipt 绑定 |
| `target_operation_id`, `target_operation_kind` | `str`，该 plan 中实际 committed operation，kind 为原枚举的字符串值 |
| `target_mutation_receipt_ref` | Harness `MemoryMutationApplyReceiptRef`，真实 receipt_id/receipt_hash |
| `trigger`, `trigger_hash` | 现有 Harness prospective trigger DTO、其规范 hash，核对历史记录与 outbox payload |
| `outbox_cause_status` | `str`，本版固定 `not_persisted`，不能当成 outbox 生成原因已证实 |
| `source_hash` | 只读属性；域 `memory.prospective.outbox.target-source.v1` 对 `to_json()` 求 history_hash；是事实摘要，不是签名/授权 |

`to_json()` 不包括派生属性 source_hash；scope 编码 `{kind, owner_id}`，lifecycle/operation kind 编码枚举字符串，receipt ref 和 trigger 用各自 `to_json()`。返回不含用户原文、action 正文、authority、grant、ready 或可直接执行的 Run。

## 身份与历史绑定

SDK 在同一只读数据库快照内核对：principal 持久 deployment/household/actor 三元组、outbox owner、目标 revision owner，以及 MemoryScope.authorize。session_id 是当前调用身份字段，不要求重开后的会话等于创建时会话。Host 仍负责 principal 来自可信运行配置；DTO/hash 本身不建立调用者身份。

同时核验 outbox topic/稳定 ID/完整 payload/hash、idempotency_key==outbox_id 与有限非负 created_at，目标 revision 的 content/trigger/hash、真实 plan/receipt 及 committed decision 的 operation/after_ref。只使用命令明确的 target_revision，不以 head、当前 clock、outbox created_at 或猜测的前一 run 替代。

例如 G1 创建 revision 1=PENDING，G2 改写 head 并产生 invalidation(revision 1)：返回 G1 的 target_run_id/operation/scope 与 revision 1 的 PENDING。Host 构造后继协议时，`transition_from` 来源是 `target_lifecycle_state`，不是 G2/current head。此返回不声称 G1 生成了该 invalidation。

Host 可用 reader.outbox_created_at 与 entry.created_at 精确匹配并要求不晚于可信 now；SDK reader 不用当前时钟改写事实或猜测 lineage。

读取历史 source 不要求目标仍是当前 head；不能因 head 更新重写来源事实。当前 ack 资格仍由实际 SDK signal 门核查：target state、确切 outbox；invalidation 还必须有真实 accepted registration。reader 成功不等于这些门已通过，也不替代 Harness authority source 的协议验证。

## 明确缺口及失败边界

现有 outbox 没有持久生成 cause 的 run/operation/receipt 引用，本版不从 target lineage 冒充生成 cause。因此 Host 若需要真正的 outbox 生成操作来源，必须保留未闭合状态，不能用 target_run_id 顶替。

signal 创建的 revision 使用 synthetic plan_id，可能没有对应 mutation receipt。本版在确切目标不存在可核验 mutation receipt 时，抛 `MemoryValidationError("prospective_target_mutation_source_unavailable")`；不返回半真 DTO，不复用更旧 revision 的 Run。该路径需后继补真实 signal source 持久事实，不能宣称全部 prospective 场景均可调度。

缺失/错 payload hash 用 MemoryValidationError；身份/ownership 不符用 MemoryOwnershipConflict；持久绑定损坏用 MemoryCorruptionError；单文档字节或 SQL 工作预算超限用 MemoryLimitError。Host 必须拒绝发 authority，并保留可诊断失败；不得回退私有 SQL/时间猜测。取消应传播。各错误不写 ack/outbox state，不生成 Memory receipt。

实现预算拟定：每个读取 JSON 文档上限 1 MiB，独立只读快照和 SQLite VM 步数上限 200,000；超过显式失败，未承诺大库全量吞吐。本版不改变冻结 schema/旧 reader 行为。

## 必需验证（待执行）

真实 public mutation→receipt/outbox→reader；重开一致；历史 invalidation 与不同 head/run；跨 actor/deployment/household 拒绝；确切 hash 与持久绑定破坏拒绝；signal 派生目标明确缺口；限额/取消后正常重开；无授权 reader 不产生 ack/grant。测试结果及独审后另写结果文档，不在本契约中预填通过。
