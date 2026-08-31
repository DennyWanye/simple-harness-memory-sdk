# Program Plan：Human Memory Digital Twin / 单一主对话与 Memory Program

<!-- plan-status: finalized -->

> 状态：APPROVED / EXECUTION IN PROGRESS — V0/S1/S2 与 S3 Task 1/2/3 complete；RecallDecision v3、EvidenceItemAuthority v3 classification、MemoryActionAuthority v2 与 Procedure/Prospective Host authority consumer 已闭合；machine `a2-003` resolved
> 行为策略：`preserve-approved`  
> 唯一真相：`acceptance.md` + `assurance-contract.json`  
> 实施仓库：`simple-harness-sdk` → `simple-harness-memory-sdk` → `simple_harness`

## 主要矛盾

在永久单一主对话中，主模型必须能按当前任务语义提出“需要什么记忆、属于哪个 TaskScope、该怎样更新任务/记忆”，
但它不能成为事实、权限或数据库状态的 authority。成功标准是把这类不可信提案统一收敛为：永久证据先提交、
严格协议提案、确定性资格/状态机裁决、原子 decision+state+outbox、同 Run 续推理、有界 Context 和可重放审计。

## 为什么拆成七个 release unit

Program 覆盖 8 条 MUST AC，但同时触及公共协议、Memory schema/状态机、Host Session/TaskScope/Context、运行调度、
项目权限和 UI，超过单一 release unit 的 3 个高风险子系统上限。因此本文件只定义依赖图与全局不变量；实际实施
按 `slices/V0`、`S1`—`S6` 独立验收。每个 slice 不超过 10 个 Task、3 个高风险子系统，失败可停在已完成边界。

```text
V0 验收权威、冲突测试迁移与五项真代码 spike（实施前）
  ↓
S1 公共协议、首次持久化安全边界与同 Run 控制屏障
  ↓
S2 Memory 永久证据、审计、suppression 与 durable outbox
  ↓
S3 四类长期记忆、类型化召回、Procedure/Prospective、图投影
  ↓
S4 Host 唯一主对话、TaskScope Archive、多根绑定、单 foreground FIFO
  ↓
S5 Host 动态 Context、路由/召回/语义收口与真实 provider 集成
  ↓
S6 单对话 UI、TaskScope 审查、记忆知识图谱与 program 级验收
```

S2 的 schema/kernel 可在 S1 协议冻结后与 S4 的 Host-only archive 基础并行开发；S3 依赖 S2；S5 依赖 S1—S4；
S6 依赖所有服务端读取 API 稳定。

## 关联验收标准

| AC | Release unit | 最终证明 |
|---|---|---|
| HM-AC-1—8 | V0 | 实施前 sealed testcase/metric/evidence authority、旧 Session oracle replacement lineage、五项 spike receipts |
| HM-AC-1 | S2, S4, S6 | 永久 raw evidence、唯一主对话、全侧路 suppression 与受控审计 |
| HM-AC-2 | S2, S3 | Working Memory 非表、四类长期记忆、即时+异步混合提取 |
| HM-AC-3 | S1, S4, S5 | 同 Run route barrier、TaskScope archive/bindings/closure/effect envelope |
| HM-AC-4 | S1, S3, S5 | 五路分流、TaskScope 发现、类型化 RecallPlan 与 no-recall |
| HM-AC-5 | S3 | Procedure/Prospective 状态机、适用性、触发候选与高风险边界 |
| HM-AC-6 | S3, S5, S6 | 动态 Context、10 causal groups、5-day index、bounded views、display-only graph |
| HM-AC-7 | V0, S1—S6 | invocation/decision/event/checkpoint/trace 全链路与分权读取 |
| HM-AC-8 | V0, S1—S6 | fresh init、consumer contracts、故障矩阵、质量/延迟/Token、真 UI/provider |

## 全局数据权威

| 数据 | 唯一 authority | 派生/消费者 |
|---|---|---|
| Host 用户/Agent/Tool/Run/Provider 原始执行证据 | Host state DB | TaskScope links、Memory ingestion outbox、审计导出 |
| TaskScope lifecycle/canonical state/events/checkpoints/bindings | Host | 六阅读视图、TaskScope search documents、Context projection |
| Memory evidence ingestion receipts/suppression/四类认知状态 | Memory SDK | 短时域索引、recall result、digital twin graph projection |
| Host↔Memory DTO、canonical JSON/hash、reason/error code | Harness SDK | Host 与 Memory SDK exact-version consumer |
| 最终 Provider ContextSnapshot/工具暴露/effect authority | Host + Harness runtime | 只读 trace/UI |
| 数字孪生体 | Memory canonical state 的可重建展示投影 | Host UI；禁止进入 Agent execution |

## 跨仓一致性与发布顺序

1. Harness SDK 先发布 breaking protocol candidate（计划版本 `0.7.0`）；public API snapshot、typing、consumer fixture
   和 canonical hash 冻结。
2. Memory SDK 发布新 fresh-schema candidate（计划版本 `0.6.0`），依赖 `simple-harness-sdk>=0.7,<0.8`；旧 v4 DB
   明确返回 unsupported，不迁移、不改写。
3. Host 锁定两个本地 wheel 的 exact version/hash，在 isolated userdata 完成空目录初始化和生产链 E2E。
4. 三仓都在提交态复验；测试通过的能力默认 ON。正式 tag/push 只在各自 machine gate 和用户已有发布策略允许时执行。

### Data epoch 与回退语义

| 阶段 | 允许动作 | 禁止动作 | 恢复点 |
|---|---|---|---|
| 新格式第一次写入前 | 停止新进程并恢复预切换 userdata 副本/旧 exact wheels | 旧/新进程并发写同一 userdata | `pre-human-memory-v1` backup manifest |
| 第一次 `human-memory-v1` 写入后 | durable ingress fence；drain 或 park job/outbox；WAL checkpoint；记录 schema/protocol/wheel hash、watermark、row count/content hash；由新格式 emergency read/export 取证或停服 forward-fix | 旧 Host/SDK 以读写方式打开新 userdata；删除或降级新 evidence | `human-memory-v1` frozen evidence manifest |
| 任一 slice 默认开启前 | 完成该 slice compatibility/rollback drill 与旧入口拒绝测试 | 等到 S6 UI 才封旧 CRUD | slice-specific cutover receipt |

旧 runtime 遇到未来 schema 必须 stable reject；不承诺旧 runtime 兼容读取新数据。“回滚”永远不等于删除新 evidence。

## Challenge 后新增的硬架构契约

- `SanitizedEvidenceEnvelope/Receipt` 是三仓首次持久化前的 admission gate：凭据原文只可存在于进程内瞬态，Host、
  Harness、Memory 的 DB/WAL/checkpoint/log/index 均只接受已验证 receipt；Memory 仍做防御性复核。
- `DisclosureContext` 分开记录 delivery recipient、intended audience、purpose class、source/trust/generation。只有认证 Host/UI、
  trusted tool destination metadata 或 purpose-bound AuditAccessDecision 能授予披露；LLM/用户自然语言推断只能收窄，
  unknown/ambiguous/external/stale/conflict 一律对敏感召回 fail-closed。
- Harness 每个 Provider turn 通过 `RunContextAuthorityPort` 请求 Host 的 immutable snapshot；receipt 在 provider reservation 前
  入 checkpoint，Host expected hash、Harness request fingerprint、adapter captured payload hash 必须三者相等。
- Harness 源账本在同事务写 `ExecutionEvidenceOutbox`，覆盖 Provider、Tool、Context、Route、Run terminal；Host 按
  `source_event_id+payload_hash` 幂等接收，foreground terminal 对外完成前必须越过 Host durable watermark。
- `MemoryAnalysisExecutorPort` 由 Host 用发起 Run 的主模型配置执行独立 post-turn analysis invocation；不是复用已结束的
  streaming connection，也不是 Memory SDK 自持小模型。request/result/receipt 与 job lease/CAS 永久可审计。
- 持久记录只保存 public content、public provider IDs/types、hash、usage/cost 和 opaque continuation ref；raw hidden reasoning
  永不持久化。不能用 opaque handle 恢复且必须保存 raw reasoning 的 provider 在 V1 禁用 reasoning 或拒绝接入。
- open-domain entailment 不冒充确定性判断：代码证明 EvidenceSpan 完整性/来源/合法转换；模型规范化的普通 claim 保持
  candidate/unverified，exact explicit-user assertion 和注册 typed observation 才可按冻结规则 active；歧义为 contested。
- Prospective 只在 Memory 保存 canonical intent；Host 是唯一 timer/event scheduler authority。durable registration/occurrence/
  cursor/receipt 进入不可跳过的 pre-provider 与 pre-terminal gate，`no_recall` 只在 mandatory inbox 已清空后成立。
- Memory analysis 的真实 delivery receipt 仍不是 mutation authority：repository 必须以
  `handed_off → result_committed → audit_pending → applied` 单向状态机签发逐 phase、单次、exact application-bound
  capability；caller-created validation receipt/decisions、乱序与跨 application replay 全部 fail-closed。
- Workspace Manual 与 Auto 是两条 authority 生命周期：Manual 来自 Host durable authenticated interaction，决定后的 exact
  receipt 可用于该次 append；Auto 每次使用前都要和 durable current Run/context/config/root facts 比较 freshness。已提交 exact
  replay 只返回原 receipt，不得刷新 binding/effect authority。
- Host `_build_product_sdk_runtime_stack()` 是 exact Harness runtime 唯一生产 composition owner；必须注入 concrete
  `ProductRunContextAuthority`、`ProductRuntimeDecisionSink`、`ProductTaskExecutionAuthority` 及其 durable dependencies，缺失即
  startup fail，禁止 Noop/fake/metadata fallback。

## Complexity inventory

| 复杂度表面 | 新增 | 理由 / 绑定 |
|---|:---:|---|
| 新依赖 | 原则上否 | 优先 SQLite/FTS5、现有 numpy/embedding、React SVG；只有 VECTOR-SPIKE 证明必要且三平台可交付才提 scope-neutral 依赖 |
| 新公共 API | 是 | Recall/TaskScope/Mutation/Context/Effect DTO，HM-AC-3/4/7/8 |
| 新持久化状态 | 是 | 永久 evidence、suppression、四类记忆、TaskScope archive/FIFO/checkpoint，HM-AC-1/2/3/5/7/8 |
| 新配置项 | 最小 | managed workspace root、context budgets、worker batch/deadline；均绑定 HM-AC-3/6/8，默认值由 spike 固定 |
| 新抽象层 | 是 | Host TaskScope store、Memory deterministic policy/state machine；避免 Host 与 SDK 双写 authority |
| 新后台任务 | 是 | Memory extraction/index/projection outbox；不能产生 Agent effect 或 TaskScope semantic mutation，HM-AC-2/6/8 |
| 新 UI | 是 | 单主对话、TaskScope 审查、display-only memory graph，HM-AC-1/6/7 |
| 可复用已有实现 | 是 | Harness ReAct/checkpoint/outbox/ToolContext；Memory embedding lineage/SQLite writer lock；Host ContextSnapshot/assembler/project binding canonicalization |
| 删除/退役旧实现 | 是 | 默认 regex Fact extractor、L1/L2/L3 语义、pre-provider auto recall、可见 Session CRUD、new-prototype physical delete path；acceptance 明确无旧兼容 |

## Assurance / 信任与失败边界

- Profile：`standard`；绑定 contract 中所有 `ASSET-*`、`FAIL-*`、`ADV-*`。
- LLM output 与自然语言是非可信输入；strict schema 只解决形状，不解决证据蕴含、权限或状态合法性。
- credential filter 在 evidence commit 前执行；被过滤的认证材料从未进入“永久业务证据”承诺域。
- 普通认知记忆跨 TaskScope 可候选，但 recipient/purpose/sensitivity/suppression/status/expiry 是排序前硬门。
- TaskScope search/vector result 永不授予 workspace authority；只有 exact canonical open + binding receipt + per-effect
  envelope 可执行项目 effect。
- Host 与 Memory DB 之间只承诺 evidence/outbox/receipt 最终一致，不承诺跨库 ACID；每个故障点可重放。
- SQLite 单 writer 事实不被隐藏；后台 worker 使用 lease、短事务、CAS、bounded retry 和 checkpoint 监控。
- 停止追踪点：外部 calendar/notification provider、真实高风险 action executor、多 foreground run/subagent、旧数据迁移、
  云同步、独立图数据库均按 `OOS-*` 停止。

## Attack-surface inventory

| 入口 | 不可信内容 | 强制控制 | 失败出口 |
|---|---|---|---|
| user query / path mention | 含糊 task、路径诱导、凭据 | trusted input provenance、canonicalize、filesystem identity、mode snapshot | standalone/confirm/fail-closed |
| LLM tool arguments | 错 enum、超长、重复、伪 ID/revision/evidence | strict schema + size limit + exact run binding + CAS + evidence ownership | rejected decision + stable code |
| TaskScope search result | 错候选、旧 revision | permission-first filter、候选不授权、exact open | ask user / no switch |
| Memory recall candidate | 隐私、旧值、冲突、suppressed | eligibility before rank and again before disclosure | filtered reason / no recall |
| outbox replay/concurrency | duplicate/half state | unique key、payload hash、lease/attempt、single transaction receipt | replay receipt / conflict / dead-letter |
| exact ID / old checkpoint / stale cache | suppression bypass | synchronous deny authority at every read surface | ordinary not-found/suppressed |
| effect execution | root widening、binding drift | Host-injected envelope、exact root membership、binding revision、filesystem identity | `TASK_BINDING_STALE` |
| UI graph/audit | private labels/edges, audit authority reuse | server-side filtered view model、purpose-bound audit token、no graph-to-context path | empty/redacted + audit event |
| first durable write | credential/hidden-CoT canary | sanitization receipt + allowlisted durable provider record | reject before DB/checkpoint |
| provider continuation | stale/wrong-run snapshot, raw reasoning | Host snapshot receipt + ordinal/CAS/hash equality + opaque continuation | stable reject/replay same snapshot |

## Release unit documents

- `slices/V0-verification-and-spikes.md`
- `slices/S1-protocol-and-react-barrier.md`
- `slices/S2-memory-evidence-audit-suppression.md`
- `slices/S3-cognitive-systems-recall.md`
- `slices/S4-host-primary-taskscope.md`
- `slices/S5-host-context-integration.md`
- `slices/S6-ui-and-program-verification.md`

每个文档中的 Task 是 Phase 3 唯一实施清单；若 Phase 2 spike 改变具体技术选择，只更新受影响 slice 并重新挑战，
不得改变冻结 AC。
