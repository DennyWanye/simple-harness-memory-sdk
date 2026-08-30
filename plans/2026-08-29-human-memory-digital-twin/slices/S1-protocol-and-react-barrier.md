# S1 — 公共协议与同 Run Context Route 屏障

> Release unit：S1（Harness SDK）  
> 高风险子系统：公共 API、ReAct 状态机、effect authority（3）  
> 覆盖：HM-AC-3/4/7/8
> 状态：COMPLETE — `a2-001`/`a2-002` 最小协议增量已闭合；Host/Memory consumer 集成仍分别接受验收，未 tag/publish
> 最终 source：`8f1027d2d64ca3a7e7a4d161833507eadac9552b`
> 最终候选物：wheel `b9421ddf2b1d5a4a4a0920a2e878c1d3cf098ff6ef0af8975b9eb5c516037d7b`；sdist `f9582decd48a195bd92dfd0f49cb2d726a0eedbf7f12143445758398f7ee4756`；manifest `fdc24acaababda1586afa965302be873f902240e1b943487e0e680258cbed097`

## 交付边界

只建立三仓共用的版本化 DTO、首次持久化安全边界、canonical hash/replay 规则，以及同一 ReAct Run 内的
`context_route`/Context authority 屏障和 `TaskExecutionEnvelope`。不在本 slice 实现 Memory 检索或 Host TaskScope 数据库。

### `a2-001` 最小契约增量

S4 Task 4 证明泛型 Tool authorization receipt 与 `RunContextSnapshot.metadata` 不能作为 workspace binding authority。
S1 必须新增 strict public DTO/port：Manual receipt 精确绑定 TaskScope、canonical root、filesystem identity、base
revision、nonce、decision 及 SDK/Host hash；Auto snapshot 必须由 Host authority 签发并绑定 Run/context revision、
configured workspace root identity 与 mode。模型提供的 metadata、opaque receipt ref 或 Host 结构 fallback 一律不成立。

### `a2-002` 最小契约增量

`MemoryAnalysisExecutorPort` 原本只返回 result，而 `MemoryAnalysisReceipt` 的 validation status/committed revision 语义
属于 Memory validator/apply，不能冒充 Host permanent invocation/result receipt。S1 必须新增 Host authority-verifiable
delivery receipt/envelope，精确绑定 request/result/attempt/provider refs 与 issuer；Memory 验证 Host durable delivery 后，
再独立产生 validation/apply receipt。

## 文件影响清单

| 文件 | 当前职责 | 改动 |
|---|---|---|
| `src/simple_harness/runtime/agent_memory.py` | 旧 identity/scope/自动 recall DTO | 保留主体 DTO；以新协议替代 Session-centric recall shape |
| `src/simple_harness/runtime/memory_protocol.py`（新） | — | RecallContext/Plan/Decision、MemoryMutationPlan、四类 memory enum 与 reason codes |
| `src/simple_harness/runtime/task_scope_protocol.py`（新） | — | 五路 Route、TaskScope proposal/mutation/search/open/receipt DTO |
| `src/simple_harness/runtime/evidence_protocol.py`（新） | — | SanitizedEvidence、ExecutionEvidence、MemoryAnalysis request/result/receipt |
| `src/simple_harness/runtime/disclosure_protocol.py`（新） | — | DisclosureContext、来源/信任/unknown 与披露 reason codes |
| `src/simple_harness/execution/context_authority.py` | 冻结 Memory payload/tool catalog | 扩展 ContextRouteReceipt、ContextFragment、ContextAssemblyDecision/Snapshot refs |
| `src/simple_harness/providers/base.py`, `tools/contracts.py` | Provider/tool public contracts | 私有 durable capability class 与 provider continuation capability |
| `src/simple_harness/execution/effects.py` | effect identity/fence | 增加 Host-only `TaskExecutionEnvelope` 与 binding-set revision |
| `src/simple_harness/runtime/drivers/react_loop.py` | provider/tool continuation | 加 route barrier 状态与 tool-output continuation 约束 |
| `src/simple_harness/runtime/kernel.py` | pre-provider recall、Run/turn terminal | 删除默认自动 recall；加入 route/no-recall 决策与 closure terminal hook seam |
| `src/simple_harness/runtime/production.py` | 生产 runtime 组装 | 注入 route executor/decision sink；默认 policy 单 foreground seam |
| `src/simple_harness/{runtime,execution}/__init__.py`、根 `__init__.py` | 公共导出 | 导出新协议，移除新版本中的旧三层命名 |
| `tests/{conformance,runtime,execution,typing}/` | 协议/运行时测试 | canonical JSON/hash、strict schema、barrier、replay、effect envelope |

## Tasks

### Task 1 — 冻结协议词汇与 canonical encoding [HM-AC-3/4/7/8]

- 新建两个 protocol 模块，用 frozen dataclass/StrEnum 表达：五路 route；Working Memory（非 storage enum）；
  Episode/Semantic/Procedure/Prospective；RecallPlan/Decision；TaskScopeProposal/MutationPlan；ContextFragment；稳定
  error/reason codes。
- 所有持久 DTO 带 `schema_version`、`run_id`、`subject`、`DisclosureContext`、`evidence_refs`、预算、
  `idempotency_key`/`base_revision`（按操作适用）。optional 字段在 strict tool schema 中用 required+nullable 表达。
- 复用 `contracts/json.py` canonical JSON；添加 schema/version 到 hash，拒绝 NaN、额外字段和未知 enum。
- 冻结 `SanitizedEvidenceEnvelope/Receipt`：source hash、sanitized hash、filter-policy version、removed span type/count；
  Host/Harness/Memory 第一次持久写之前必须验证，transport credentials 只能进程内存在。
- 冻结 `DisclosureContext`：delivery recipient、intended audience、purpose class、source/trust/generation/unknown；授权来源
  仅认证 Host/UI、trusted tool destination metadata、AuditAccessDecision，LLM/自然语言只能收窄权限。
- 冻结 `MemoryAnalysisRequest/Result/Receipt` 与 `MemoryAnalysisExecutorPort`，绑定 job、originating Run、ordered evidence
  refs+hash、prompt/schema/policy、provider/model/config、attempt、usage/cost、validator 和 result hash。
- 验证：public API snapshot、typing consumer、同 payload hash 稳定、environment/recipient/version 改变 hash。

### Task 2 — 定义 route receipt 与同 Run barrier 状态 [HM-AC-3/4]

- 在受哈希保护的私有 tool catalog 增加 `effect_class=(context_control|project_effect|non_project_effect)`、
  `route_requirement=(forbidden|required|optional)`、`task_scope_requirement=(forbidden|required|optional)`；模型参数不能覆盖。
- 在 runtime context 中记录 `unrouted | routed_standalone | routed_task`；receipt 绑定 exact `run_id`、route outcome、
  TaskScope/binding revision/recall refs。
- 修改 `react_loop.py` 在任何 `prepare_effect` 前预检整个 provider tool batch：`context_route` 是 control tool；同批所有
  route-required effect 拒绝为 `ROUTE_BARRIER_NOT_OBSERVED` 且不得产生 effect ledger/handoff，下一 continuation 重提。
- `direct_standalone/no_recall` 允许同一次 provider response 直接 terminal，但必须产生 decision sink 事件。
- 验证：五路 route、同 batch 越 barrier、wrong run receipt、replay 后状态一致。

### Task 3 — 注入 per-effect TaskExecutionEnvelope [HM-AC-3/7]

- 扩展 `effects.py`/`ToolContext` 的 Host-injected authority metadata；模型参数中出现同名字段时忽略/拒绝。envelope
  绑定 call/effect identity、tool capability fingerprint、route receipt、exact root identity、binding revision 与 hash。
- project effect 必须包含 exact task_scope/root/binding-set revision/effect/idempotency identity；non-project tool 可无
  TaskScope，但仍绑定 run/effect。
- runtime 只定义和验证 envelope 完整性，folder membership 由 Host adapter 校验。
- 验证：模型伪造、missing/stale revision、跨 Run replay、non-project standalone。

### Task 4 — 每个 Provider turn 的 Host Context authority [HM-AC-4/6/7/8]

- 新增 `RunContextAuthorityPort`：初始及每次 `context_route` 后，Harness 用 run/turn ordinal、prior context revision、
  route receipt 请求 Host；Host 返回 exact messages/tools/options、snapshot revision/source revisions/expected fingerprint。
- Harness 在 provider reservation 前持久写 receipt+payload+hash 并校验 lineage；ProviderRequest 只能由此 payload 构建。
  wrong run/stale revision/same ID different payload fail-closed；崩溃重放相同 snapshot。
- 持久 Provider record 使用 allowlist，只含 public content/IDs/types/hash/usage/opaque continuation ref，不含 raw hidden
  reasoning。根据 V0 capability matrix 对不兼容 provider 禁用 reasoning 或拒绝。
- 验证：Host expected hash = Harness request fingerprint = adapter captured JSON hash；各 checkpoint/handoff 边界 kill/replay。

### Task 5 — 将自动 pre-provider recall 改为显式协议 seam [HM-AC-4/8]

- 在 `kernel.py` 移除每轮无条件 `AgentMemoryPort.recall_for_turn()` 的生产路径；保留 committed evidence outbox。
- provider 初次调用只收到 Host prepared snapshot；Memory query 仅由 `context_route`/recall tool executor 触发。
- no_recall 仅在 Host durable mandatory-signal inbox 已 reconcile 且为空时成立；此时断言 Memory ranking port 零调用、
  只有一次 provider invocation；需要 recall 时以同 Run tool continuation 继续。
- 验证：更新 `test_production_runtime.py`、`test_react_conversation_memory.py`、故障恢复与 checkpoint replay。

### Task 6 — Consumer contract 与候选构建 [HM-AC-8]

- 更新 root exports、版本为 breaking `0.7.0` candidate、artifact provenance/public API snapshots。
- 建立 fake Host + fake Memory consumer：sanitization→strict tool call→Host Context receipt→continuation→effect envelope；
  覆盖 unknown disclosure、raw-CoT/credential canary、乱序、重复、schema 违约、timeout 和超长字段。
- 构建 wheel，在 clean venv 安装并运行 artifact/conformance/typing/full runtime tests。

## 验证出口

- `ruff`, `mypy`, 全量 `pytest`；wheel build/install；public API/protocol snapshots。
- Required fault cases：wrong run, stale receipt, same-batch effect, duplicate call, illegal schema, no-recall zero Memory query。
- S1 完成时只证明协议与 Runtime 屏障；不声称真实 TaskScope/Memory 产品链可用。

最终闭合证据（source `8f1027d2`）：聚焦协议/runtime `84 passed`，public/artifact `27 passed`，全仓
`1596 passed, 2 skipped`；默认 CI mypy 覆盖 35 个文件，ruff 与 clean wheel install/import 均通过；第三方独立审计
P0/P1/P2 均为 0。候选 wheel 使用固定 ZIP timestamp 重复构建，hash 与 manifest 自洽。`a2-001` 的 Host
binding consumer 与 `a2-002` 的 Memory durable-delivery consumer 必须各自在所属 slice 通过后，才能关闭 program 集成缺口。
