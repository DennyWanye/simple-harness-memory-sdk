# Prospective outbox 公开源事实接口

最后更新：2026-09-06。接口供 Host S5c RegistrationAuthoritySource 并行接线；source reader 已完成限定测试，审计 metadata 增量已完成定向验证；已构建候选并完成独有 installed 小集合；尚未独审或 Host 组合，不属于冻结 M0.6.15。工作树 `simple-harness-memory-sdk-typed-short-sources`，分支 `feat/prospective-outbox-source`，base `139dd889720764eae2e9ec580c6cb45b10326c3d`。

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

成功时新增 `operation_observation: ProspectiveSourceReadObservationV1` 属性；它不进入 to_json/source_hash，也不参与事实 DTO 的相等比较。拒绝/取消时同型值在异常的 `operation_observation`。其 schema_version=1、operation 固定方法名，包含真实单次调用 invocation_ref_hash、request_hash、claimed_owner_ref_hash、成功时 source_hash（失败为 None）、有限 outcome/reason、物理观察 observed_at 与 observation_hash。owner 只是请求身份的 hash，不代表身份已通过；缺少可安全编码的输入时相应 hash 为 None。重试会有新 invocation，目标事实 hash 不变。

审计接线沿 OA1 的 Host 持久化 observation 边界：`persistence_status=host_persistence_unverified`，Host 必须将完整 observation JSON/hash 与自身真实 attempt 关联落盘；它不是 Run、grant 或 Memory mutation receipt。SDK 同时向既有 MemoryObservability 投影 fingerprint/stage/to_state/state_version，严格遵守 H073 白名单。日志/sink 可观测不等于持久审计成功。OA1 现有九类持久表没有通用 reader 调用 producer，本叶不伪造旧 family，也不宣称 sealed OA1 已收录这些调用；Host durable 接收仍是组合义务。

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

## 必需验证与当前结果

真实 public mutation→receipt/outbox→reader；重开一致；历史 invalidation 与不同 head/run；跨 actor/deployment/household 拒绝；确切 hash 与持久绑定破坏拒绝；signal 派生目标明确缺口；限额/取消后正常重开；无授权 reader 不产生 ack/grant。结果按下表区分，不将 source 测试当 installed/Host scheduler 验收。


| 批次 | 实际结果与范围 |
| --- | --- |
| r1 | 19 fixture ERROR：误将 public OutboxPageV1 当 iterable；尚未触达 reader |
| r2 | 14 PASS、5 FAIL；失败位于 fixture 的 run/disclosure、不可变触发器、未注册 signal 协议构造 |
| r3 | 修正这些 fixture 后定向 8 PASS（11 deselected）；未放松 SDK 业务门 |
| r4-fixed | 固定 6b8d87f：23 专项 + 2 原 prospective 邻居 = 25 PASS，2.32 秒；PGID45976/峰119440KiB/无残留 |
| r5-observation | 新 observation 元数据、取消、corruption/limit 三项 PASS，0.55秒；PGID46817/无残留；首次 sink 载体是替身，不能证明真实白名单接线 |
| r6-sink-red | 改为真实 H073 RecordingSink 后 1 FAIL，实际0/4条；完整 observation 字段不在 safe attributes 白名单；PGID46873/无残留 |
| r7-sink-fix | 首次 BUSY75 未启动；后续实际收到4/4事件，但测试误用事件 to_json（真实为 to_dict），1 FAIL；PGID47303/无残留 |
| r8-sink-green | 仅修测试序列化调用后真实sink 1 PASS/0.44秒；PGID47377/峰114768KiB/无残留 |

资源入口 `/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py`，默认同一 OS 锁，2048MiB/180秒；未运行模型/Provider/native/build/install，无新环境。冻结615分支/制品与SDK schema/旧 reader 保持原样。按主分配，当前后继源码版本0.6.16；冻结615分支/制品不改。独审需主转Dirac（本会话无可调用子代理入口，现有任务列表也无Dirac）；当前尚无独审ACCEPT，制品准备不等于独审闭合。

源码测试使用主 M614 解释器借用依赖，并显式 PYTHONPATH 指向本树 src 与根目录；这是开发源码载体，不是 installed 组合。原始日志、resource.json、测试 DB 都在本树 ignored `.local-test-evidence/2026-09-06/prospective-outbox-source/`，r1 原临时 DB 已移入同批 cases，未删除原红。固定绿色源码与旧制品未重复全量 hash 扫描；后续只运行本次变动或真实失败所需的定向项。


## M0.6.16 本地候选制品

源码固定 `931b8c77076bb5b42ad41a3297ed4eb58bcaaab9`（包含44eefe3、6836ff3、6b8d87f）；单次 offline hatchling build，继承615已核构建方式，不重复双build/旧包全成员扫描。此制品尚待主转 Dirac 独审；已准备可审查候选，不宣称独审或 Host source/scheduler 完成。

- wheel：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/prospective-outbox-source/artifact-616/build/simple_harness_memory_sdk-0.6.16-py3-none-any.whl`
- SHA-256：`00937eb5d79c1ea989112c658eaf543e434fb211106f4edfbecbc10002bca9bf`；358630 bytes。
- 独有安装路径：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/prospective-outbox-source/artifact-616/installed`。
- 借用原 M614 Python/H073 依赖，用 `-I -B` 消费实际616 target，无 Memory src overlay；只跑 public source/reopen、历史 invalidation+真实 registration 门、真实 metadata sink 三项：3 PASS/0.55秒。只核本叶7个变动包成员=wheel=owninstalled；未写旧installed、未重扫旧包。
- r9-artifact：PGID47559/exit0/elapsed1.322秒/峰141744KiB/无残留；最低磁盘3112MiB，测试槽释放。
- 实际命令保存在 ignored `build_install_616.py`；固定源检查→offline build→uv offline no-deps target→隔离 Python installed consumer 均在同一默认资源锁内。没有新完整venv/网络安装/模型/native。

本次制品证据索引（只核新产物，不重复旧证据）：

| ignored 相对路径 | SHA-256 |
| --- | --- |
| `build_install_616.py` | `e49b72c33a93a1d6300194972337e2ec558e9374dc1f2d8472aca4b9267ef6f4` |
| `r9-artifact/command.log` | `0dcc37603a267e5fff55114b3573a83ea4d9b5f91c0926a80d53d80c8d1ec5f1` |
| `r9-artifact/resource.json` | `bec0a4c5a240b08dfe06962e9be31516b106ccd7332fbb3fd2ee7ca05e1fa311` |
| `artifact-616/manifest.json` | `38627e706a83c0607fde8965db0d67e42350e740f295850faa6e3f0922e74461` |
| `artifact-616/runtime-identity.json` | `874ccc0053a48724bbd6f4348dcde34d44cc28140343442c4891007cf44719b9` |
