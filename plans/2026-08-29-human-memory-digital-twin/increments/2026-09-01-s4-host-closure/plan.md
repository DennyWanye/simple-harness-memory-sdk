<!-- plan-status: finalized -->

# Plan：S4 Host TaskScope + Runtime Execution Closure（Task 5–8 + 最小 S5 composition）

## 主要矛盾

- 决定成败的核心问题：很久以后继续一个任务时，Host 能否从永久 Archive 找回正确 TaskScope，并让最老持久化 turn 使用冻结且可审计的 authority 真正启动唯一 SDK Runtime Run。
- 最小验证动作：fresh DB 写入 A/B 相似任务、100k events、checkpoint 与两个 queued turns；冷重启后 candidate search→exact open A→production scheduler claim 最老 turn→唯一 SDK start/bind→RUNNING→terminal→next，核对无串线、无重复 start、无 request-selected authority。
- 价值验证里程碑：Task 6；Task 1–5 已证明 archive/search/FIFO/recovery 基础，本轮先补真实 execution composition，再做其余扩大加固。

## 关联验收标准

- 覆盖 HM-AC-1、HM-AC-3、HM-AC-4、HM-AC-6、HM-AC-7、HM-AC-8。
- 复用 program testcase：TC-HM-02、TC-HM-09、TC-HM-10、TC-HM-11、TC-HM-12；本 slice 只新增其自动化 Host 子 lane，不宣称 UI/真实主模型通过。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `backend/deskpet/memory/migrations/031_task_scope_projections_v39.sql` | view/checkpoint 派生状态 | source-change/outbox、immutable view/group/block/checkpoint verification schema |
| `backend/deskpet/task_scope/projection_sources.py`（新） | 投影源身份 | 同事务登记 source sequence/hash 与 outbox，协调 canonical producers |
| `backend/deskpet/task_scope/projections.py` | 六视图 | deterministic bounded render、logical group/physical block、rebuild、checkpoint drift |
| `backend/deskpet/memory/migrations/032_task_scope_search_v40.sql` | locator | immutable search docs + rebuildable FTS5 + cursor refs |
| `backend/deskpet/task_scope/search.py` | candidate search/open | permission-first filter、rank、bounded candidate、exact open ResumePackage |
| `backend/deskpet/memory/migrations/033_foreground_queue_v41.sql` | Run/FIFO | durable run、turn queue、control receipt、lease/terminal facts |
| `backend/deskpet/execution/foreground_queue.py` | scheduler authority | one active Run、FIFO claim/settle、immediate control、restart recovery |
| `backend/deskpet/memory/migrations/034_human_memory_recovery_v42.sql` | epoch/recovery | data-format compatibility、fence/drain/park/export receipts |
| `backend/deskpet/memory/migrations/035_human_memory_quiescence_v43.sql` | recovery work ledger | durable per-item drain/park、lease revoke、worker ack/watermark |
| `backend/deskpet/memory/migrations/036_foreground_execution_v44.sql`（新） | execution preparation/audit | immutable claimed payload、prepare/start/bind/reconcile attempts 与 lifecycle receipts |
| `simple-harness-sdk/src/simple_harness/runtime/start_snapshot.py`（SDK 新版） | initial TaskScope route | `RunStart`/`StartSnapshot` 冻结 Host 已验证的初始 `ContextRouteReceipt` |
| `simple-harness-sdk/src/simple_harness/runtime/termination.py`、`runtime/drivers/react_loop.py`（SDK 新版） | route checkpoint | 首个 Provider turn 前恢复 task route，不要求模型再次调用 context-control tool |
| `backend/deskpet/execution/recovery_fence.py` | recovery | ingress fence、WAL checkpoint、raw manifest、emergency read/export |
| `backend/deskpet/execution/foreground_runtime.py`（新） | production scheduler/execution authority | exact claimed-turn read、prepare→claim→SDK start/bind→RUNNING、signal/terminal/restart reconciliation |
| `backend/deskpet/memory/human_memory_service.py` | Host composition | primary/TaskScope/search/open/mutate/binding/queue/control/audit facade 与 constructor-bound production ports |
| `backend/deskpet/task_scope/workspace_bindings.py`、`backend/deskpet/task_scope/runtime_binding_authority.py`（新） | binding authority | Host-auth Manual/Auto proposal→grant→CAS append；Auto 只读 current Run snapshot |
| `backend/deskpet/sdk_adapters/foreground_execution.py`（新） | Runtime 0.7 adapter | 复用现有 provider/tool/context preparation seams，构造唯一 `SdkRuntimeIngress.start`；不复制 ReAct loop |
| `backend/main.py`、`backend/context.py` | production entry/lifespan | HUMAN 默认注册真实 binding/recovery/scheduler/runtime ports；legacy/future absent；旧 CRUD→primary fence |
| `backend/deskpet/memory/{migrator,schema}.py`, `backend/deskpet/memory/session_db.py` | schema init | pre-opener epoch dispatch、v39–v44 chain、checksum、future/legacy stable reject |
| `backend/deskpet/{task_scope/store.py,task_scope/provisioning.py,task_scope/workspace_bindings.py,execution/evidence_ingress.py,memory/human_memory_program.py}` | source producers | canonical 写入同事务检查 fence 并登记 projection source change；不得靠事后扫描补 outbox |
| `backend/tests/task_scope/*`, `backend/tests/execution/*`, `backend/tests/memory/*` | black-box/fault tests | 1k/10k/100k、A/B、wrong principal、queue/recovery/API smoke |
| `testcase/human-memory-program/*`, `testcase/index.*` | oracle | 复用并版本化 S4 Host 自动化子 lane |
| `ARCHITECTURE/*` 与父 program 文档 | 事实源 | 只在测试完成后标 S4 Task 5–8 完成并记录证据 |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / AC 或 risk 绑定 |
|---|:---:|---|
| 新依赖 | 否 | 复用 SQLite/FTS5、aiosqlite、现有 FastAPI |
| 新公共 API | 是 | Host-only primary/TaskScope/search/open/queue/control/audit；HM-AC-1/3/4/7 |
| 新持久化状态 | 是 | projection/search/foreground/recovery/execution audit v39–v44；HM-AC-3/6/8 |
| 新配置项 | 否 | fresh prototype 默认启用，legacy DB stable reject |
| 新抽象层 | 是 | 单一 `HumanMemoryHostService` composition facade；避免 main.py 直接拼私有 store |
| 新后台任务 | 是 | 每 subject 单 production foreground scheduler；只驱动 Host FIFO→唯一 SDK ingress，后台 worker namespace 无权 claim |
| 可复用已有实现 | `CanonicalTaskScopeStore`, `TaskWorkspaceBindingStore`, `ExecutionEvidenceIngress` | canonical facts、binding 与 ingest 不复制 |
| 标准库/平台能力 | SQLite FTS5 / WAL checkpoint / JSON / SHA-256 | rebuildable locator 与 recovery manifest |

## Assurance / 信任与失败边界

- Profile：standard；contract 为同目录 `assurance-contract.json`。
- 入口链：authenticated Host subject → `HumanMemoryHostService` → exact queue/TaskScope facts → constructor-bound scheduler/execution authority → sole `SdkRuntimeIngress` → immutable lifecycle receipt；search/query/queued payload、重复 delivery 与 stale worker 不可信。
- 数据流：raw/canonical 表只 append；head/lease/cache/FTS 是可恢复协调状态。任何 rebuild/recovery 不删除 raw 表。
- 关键失败：FAIL-DATA-LOSS、FAIL-TASK-RESUME-LOSS、FAIL-TASK-SEARCH-AUTHORITY、FAIL-FOREGROUND-RUN-CONCURRENCY、FAIL-PRIMARY-STREAM-SPLIT、FAIL-READ-VIEW-GROWTH、FAIL-PROTOCOL-REPLAY。
- 停止追踪点：S5 剩余主模型 route/RecallPlan、Memory recall、五天短时域、动态 Memory Context 与 semantic closure；S6 UI/真人 E2E、旧数据迁移、发布/合并。最小 Context/Provider/Tool execution composition 已由用户 A2 批准进入本 slice。

## 方案选择与取舍

- 采用 canonical archive + rebuildable projection/FTS；不把 Markdown、FTS row 或 embedding 当 authority。
- 初版检索只实现 permission-first FTS5 + deterministic metadata rank，不预留 embedding interface/hook/factory。为本 slice 引入新向量依赖或未来扩展点会扩大环境与质量门，且不影响“候选→exact open”的正确性；向量检索必须由后续独立 acceptance 引入。
- 采用 DB partial unique constraint + transactional claim；不依赖进程内 Queue，因为进程崩溃会丢顺序和 active owner。
- Host 只拥有前台 admission/FIFO/control/lease authority；实际 Agent root Run 仍由已发布 Harness SDK Runtime 执行。一个 `host_run_id` 只能幂等绑定一个 `sdk_run_id`，Host 不实现第二套 ReAct loop。
- 不直接复用 `_run_product_harness_chat` 作为 scheduler：它绑定 legacy SessionDB/project migration/WebSocket 并重复写 user message。抽取/复用其中已存在的 provider freeze、tool authority preparation、context snapshot 与 SDK ingress seams，由新的 constructor-bound adapter 消费 canonical queued turn；scheduler payload 无权选择 subject/provider/tool/context/mode。
- execution preparation 与 start intent 先永久入账；`SdkRuntimeIngress` 的确定性 run ID 在调用前计算并与 host Run CAS 绑定。崩溃恢复先查询现有 binding/SDK durable state，再决定补写 started/terminal receipt 或重试同一确定性 start，永不生成第二个 Run ID。
- SDK 0.7.0 的 ReAct checkpoint 初始固定为 `UNROUTED`，不能表达“Host 已经从 exact queued turn 验证了 TaskScope”的事实；本 slice 把 `ContextRouteReceipt` 升为 v3 并冻结 `origin=context_tool|host_initial`。`context_tool` 保持 raw-call/effect provenance；`host_initial` 禁止伪造 raw-call/effect，改为强制 Host authority ref/hash，并完整绑定 `run_id`、TaskScope、binding-set receipt。ordinary `StartSnapshot` 新增 schema v7，把完整 route JSON/hash纳入 start request hash；schema 1–6 均解码为无 initial route/`UNROUTED`，host-control schema v6 不变。ReAct checkpoint 新增 schema v6：仅无 checkpoint 时从 exact start snapshot 原子初始化 `ROUTED_TASK`；已有 checkpoint 与 start route/hash/TaskScope/binding 任一不一致即 fail closed。
- TaskScope 可持久绑定多个 root，但现有 SDK `TaskExecutionEnvelopeRequest` 不含 effect arguments/root selector，Host 的 `TaskWorkContext` 也只有单 root。为避免隐式选错目录，本 slice 不扩大项目 Tool effect 协议：零 root 可执行无项目 effect；单 root 可按 exact binding receipt 准备既有 tool authority；多 root 的 project effect 稳定 fail closed，并留给独立的“按 effect 解析 exact root”验收。TaskScope 多 root 的存储、恢复、展示与不可切换语义仍必须完整实现。
- 投影视图的版本身份不是单一 canonical revision，而是 `TaskScopeProjectionSourceV1` 的内容哈希：scope、单调 source sequence、canonical revision/state hash、event watermark/prefix root、checkpoint set root、binding revision/receipt hash、renderer contract version。任何源变更都必须在源写事务内追加 source-change + outbox。
- `EVIDENCE 500 events/page` 定义为 logical page group，不承诺 500 条完整事件塞进 32 KiB；group manifest、index/leaf/chunk 都是内容寻址的物理 block，任一 block ≤32 KiB，并可逐字节恢复全部 canonical 字段与 refs。
- Task 7 提供可运行 Host API，但不在 S4 偷做 S5 的 LLM routing/context；Host 入口与 SDK execution adapter 是同一 slice 内的两个独立责任边界，必须一起闭合。

## 任务清单（最短价值路径优先）

### Task 1 — v39 六阅读视图与 checkpoint verifier [HM-AC-6/7/8]

- 改动：新增 v39 migration、`projection_sources.py` 与 `task_scope/projections.py`；从 canonical state、events/steps/evidence refs、bindings、checkpoints 生成 README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE。
- 源身份：每个 scope 单调分配 `source_sequence`；source row 固化 canonical revision/state hash、event watermark/prefix root（包含 event/step/evidence-link hashes）、checkpoint sequence/set root、binding revision/receipt hash、renderer contract version 与总 `source_hash`。TaskScope create/mutation/host event、evidence link、checkpoint、binding append 的原 authority transaction 同时追加 source-change + projection outbox；不得在事务外推测“最新”。
- 上限：README 16 KiB、STATUS 12 KiB、Resume 24 KiB、每个物理 block 32 KiB。EVIDENCE 每连续 500 events 形成稳定 logical group；manifest/index/leaf/chunk block 各自内容寻址且 ≤32 KiB，payload 过大时继续 chunk，但 group 边界不变。稳定 ID 绑定 scope/source hash/kind/group/block/content hash。
- 语义：canonical 与 source-change/outbox 同事务提交；projection worker 可合并连续 source sequence，但必须记录 covered range，exact revision/open 请求必须物化精确 source。projection 失败不回滚 canonical；旧 source/revision 永久可查；renderer contract 改变只生成新 derivative。cache 删除后同 source byte-identical 重建。
- checkpoint：保存 repo/branch/head/dirty manifest/files/tests/artifacts/next action；open 时按 caller 提供的 live probe 生成 drift report，不静默改 canonical checkpoint。
- 验证：1k/10k/100k、Unicode/单事件超长 payload、500-event group 跨多 block、每类 producer transaction crash/lost ACK、coalescing、cache delete/rebuild、old source immutability、drift matrix。

### Task 2 — v40 permission-first search 与 exact open [HM-AC-4/6/7]

- 改动：新增 immutable search documents、FTS5 index、cursor/rebuild receipts；实现 `TaskScopeSearchService.search()` 与 `open_exact()`。
- search：先限定 authenticated subject/allowed scope IDs，再执行 MATCH/rank；返回 ID/title/goal/project/status/time/snippet/source revision，byte/item 上限固定。
- open：只收 exact ID，重载 canonical revision + projection receipt + checkpoint + binding set，组装 ≤24 KiB ResumePackage 和 page refs。
- authority：search/open 本身不写 active cursor、不追加 binding、不产生 tool grant；wrong principal 与 stale revision fail closed。
- 验证：A/B 同名、poison canary、旧 revision、wrong principal、empty/oversize query、FTS unavailable、cold rebuild/exact open。

### Task 3 — v41/v44 单 foreground Run、durable FIFO 与 exact execution read model [HM-AC-3/8]

- authority：Host 是 durable admission/FIFO/control/lease/current-Run snapshot 唯一 owner；Harness SDK Runtime 是实际 Agent execution 唯一 owner。foreground scheduler 以一对一 admission receipt 将稳定 `host_run_id` 绑定到唯一 `sdk_run_id`，重放只能返回原绑定，超时/未知不得另起 Run。
- queue：`ABSENT→QUEUED→CLAIMED→SETTLED`。enqueue 在确认同 subject/primary 的 committed evidence ref/hash 后分配单调 FIFO sequence；claim 只取最老未结算项，在同一事务创建 CLAIMED Run、冻结 scope/binding/context lineage、占用 subject slot 与 generation=1 lease；terminal/settlement/lease close/slot release 原子提交后下一项才可 claim。
- Run reducer：`CLAIMED→RUNNING|FAILED`；`RUNNING→PAUSE_REQUESTED→PAUSED|RUNNING`；PAUSED 可 resume 到 RUNNING 且 generation+1；任一非终态可按强度进入 `STOP_REQUESTED`/`CANCEL_REQUESTED`，最终只接受 SDK 认证的 `COMPLETED|FAILED|STOPPED|CANCELLED`。终态 immutable，只允许 exact replay。
- controls：优先级 `CANCEL > STOP > PAUSE`，不进入普通 FIFO。control intent、reduced desired state 与 durable signal outbox 同事务；强控制可覆盖弱控制，弱控制不得降级；terminal-first 返回 `already_terminal`，control-first 必须用 SDK causal evidence 裁决竞态，Host 不伪造取消终态。pause 保留 foreground slot；resume 仅允许无 stop/cancel intent 的 PAUSED Run。
- lease/restart：lease 身份为 `(host_run_id, owner_id, generation, expires_at)`；heartbeat 只续期，reclaim/transfer/resume generation+1。所有 start/signal ack/state CAS/effect admission/terminal/Auto snapshot 都校验当前 generation；旧 owner 只能读。crash 前后均恢复同一 queued turn/host Run/sdk Run，lease expiry 不等于终态、不重新排队。
- background exclusion：投影、搜索、提取 worker 使用独立 lease namespace，不能调用 foreground claim/start/signal/cancel；`worker_kind`/metadata 不能铸造 authority。partial unique constraint 保证每 subject 至多一个 nonterminal foreground Run。
- exact read 分两阶段：constructor-bound `read_next_preparation_candidate(subject)` 先验证固定 subject/permission/最老 sequence，只生成不可执行的 preparation draft/source snapshot + canonical hash，不注册 Tool authority、不打开 Provider client、也不持有 SDK start/signal/effect 能力；`claim_next` 在同一事务 CAS exact candidate/draft hash并创建 host_run_id、owner、generation、lease。随后 `read_claimed_execution(host_run_id, owner_id, generation)` 再读取完整 immutable turn/evidence/scope/binding lineage并核对 draft hash，只有它能构造 generation-bound execution authority。
- v44：追加 immutable execution preparation、start intent、start observation、reconciliation receipt；协调 head 只允许 generation CAS。记录 request hash、SDK deterministic run ID、context/provider/tool/binding refs 和失败阶段，不保存 API key/token/provider 私密 payload。
- 验证：并发 enqueue、duplicate/lost ACK、exact payload hash、两个 scheduler 同时 prepare、prepare 后 claim 失败、旧 generation 持有已准备对象、claim 后 authority 构造崩溃，以及每个 claim/start/bind/started/terminal 边界 crash-before/after；另覆盖 control race/优先级、terminal race、stale generation、lease expiry/restart、background claim 拒绝、SDK 一对一绑定、Auto snapshot 只读当前 foreground lineage。

### Task 4 — fresh Host typed facade 与 100k Archive 冷恢复 smoke [HM-AC-1/3/4/6/7/8]

- 在任何 `state.db` writable opener、`initialize_state_db()`、`SessionDB.initialize()`、MemoryManager/provider/worker/API/backup 之前，由单一 startup epoch dispatcher 持有决策锁并只读分类：`FRESH`、`HUMAN_RESUME`、`LEGACY`、`INVALID`、`FUTURE`。
- `FRESH` 仅允许批准的 prototype userdata lane 且 DB absent/zero-byte/无用户表的有效 v0；立即由 human initializer 写入 bootstrap/epoch marker 并顺序迁移至 v44。`HUMAN_RESUME` 验证 marker/checksum 后续跑 v0..v44 的精确未完成链。`LEGACY` 只走原 legacy composition 且 human endpoints 返回 `human_memory_program_legacy_database_unsupported`；`INVALID/FUTURE` 在任何业务写入、SessionDB、backup/reset/recovery 前 fail closed。所有消费者获得冻结 composition mode，不再各自 redispatch。
- 新增 `HumanMemoryHostService` typed facade 的价值路径：Host 从受信 auth snapshot 派生 subject；payload 只能提供 selector/内容/idempotency，不能自报 subject、allowed scope IDs、mode、binding/context revision 或 worker authority。scope/evidence/run/binding/checkpoint 的每次读取和写入都验证同 subject + primary + hash + lineage。
- facade authority matrix 固定如下，公共 DTO 不得增加绕过列：

  | 操作族 | payload 只可提供 | Host 必须派生/校验 |
  |---|---|---|
  | primary/evidence/TaskScope create+append+mutate+checkpoint | exact ID、内容、expected revision、idempotency、冻结 receipt/ref | subject、唯一 writable primary、scope owner、evidence ID+hash+subject+primary、run↔scope lineage |
  | search/open_exact | query、cursor/bounds 或 exact scope/source revision/page selector/live probe | allowed scope IDs 由 canonical ownership/permission 计算并在 MATCH 前过滤；open 不改 cursor/binding/grant |
  | manual/Auto binding | manual proposal/root/idempotency，或 Auto exact run/scope selector | manual interaction authority；Auto 当前 foreground Run/generation、mode、binding/context/config revisions 与 receipt hashes |
  | queue/control | turn content/evidence ref/idempotency/optional scope，或 exact run/control kind/reason | queue subject/primary/scope lineage；control 当前 run subject+generation，claim/settle 仅 internal scheduler |
  | audit/recovery/export | exact owned IDs/pagination，或 bounded lifecycle action/idempotency | 返回 refs 均追溯 owned primary/scope；recovery capability、subject、DB path、table allowlist/epoch 全由 trusted Host lifecycle 固定 |

- 在 fresh DB 通过该 facade 创建 A/B、100k events、checkpoint 与 queued turns；删除派生 cache/FTS 后重建并冷重启。typed query 先返回候选，再 exact open A；核对 A/B canary、logical group/physical block coverage、全部 view/page hashes、ResumePackage 上限、环境 drift 与 FIFO 顺序。
- 本 Task 的 Archive smoke 已在 Host `e212fb90` 通过；它是新 Task 6 execution value smoke 的前置事实，不能替代实际 SDK start。

### Task 5 — v42/v43 recovery fence、真实 quiescence 与 emergency export [HM-AC-1/7/8]

- schema/service：data-format epoch、min/max read-write、durable fence singleton/generation、drain/park/worker-ack receipt、WAL checkpoint receipt、logical manifest/export receipt。冻结状态机为 `OPEN→CLOSING→QUIESCED→SEALED→OPEN`，任一步失败进入 `FAILED_CLOSED`；重启从 durable state/generation 继续，不猜测 ingress 已开启。
- 事务围栏：每个 human-memory canonical writer 用 `BEGIN IMMEDIATE`，在首次 mutation 前于同一事务读取 fence generation/state；仅 OPEN 可写。close coordinator 获取 SQLite writer lock，CAS OPEN→CLOSING 并固化 cutoff/generation，因此 fence commit 必然在线性化点之前所有 writer 提交之后；之后获锁的 writer 看见 CLOSING 并稳定拒绝。v42 对冻结的 canonical/Run/FIFO 表 allowlist 增加 SQLite trigger 作为漏登记 writer 的 defense-in-depth，统一抛 `human_memory_ingress_fenced`；recovery coordinator 只有 constructor-bound authority，可写 recovery receipts 与声明的 derived coordination 表。
- writer registry 明确覆盖 primary init/evidence、TaskScope create/event/mutation/checkpoint、provisioning、binding、foreground enqueue/claim/control/terminal 及 v44 每个 execution writer；关闭 API ingress 本身不构成 quiescence。v44 逐表冻结 taxonomy：immutable claimed payload/preparation/start intent/start observation/reconciliation/terminal lineage 属 A（既存行不可变）或显式 C（fence 后允许的合法 immutable delta）；generation/lease/current heads 属 B；仅可重建索引属 D。各表同步加入 fence trigger allowlist、quiescence ack/watermark、M0/post typed-leaf manifest 与 emergency export allowlist。CLOSING 后 drain/park cutoff 内全部 outbox，撤销或等待 worker lease，并以 ack/watermark/gap receipt CAS 到 QUIESCED。
- checkpoint：在 recovery mutex 与持续 closed fence 下以 autocommit 执行 `wal_checkpoint(FULL)`；返回必须非空且 `busy=0`、`log_frames=checkpointed_frames`。checkpoint 不能被一个长写事务包住，因此依赖 durable fence + 全 writer check + worker ack；busy/unknown/gap 进入 FAILED_CLOSED，不生成成功 manifest。
- manifest taxonomy 固定为 schema allowlist 而非名称前缀：A=protected immutable authority rows；B=只允许 CAS 的 authority coordination heads/watermarks/current binding/queue-run lease heads；C=恢复期间可追加的 immutable derived/audit receipts；D=可删除重建的 projection cache/FTS/index/worker cursor。cutoff 后不得新增 A；M0 对每个 A 表固化 schema/typed-column hash、按主键排序的 row count 与 typed canonical row leaf root，post-check 逐个证明所有 preexisting primary key 仍存在且 leaf 相同。B 验证引用/CAS invariant；C 单列合法 delta count/root；D 不参与 raw equality，只跑 rebuild oracle。未知 protected table/column 直接 fail closed。
- emergency export 仅从 SEALED manifest snapshot 生成，明确 allowlist A + 必要 B snapshot + C lineage，排除 D、legacy Session、auth/config secrets 与 private provider payload；typed deterministic serialization、主键排序、内容寻址 chunk，并包含 epoch/migration checksums/DB instance/fence generation+cutoff/per-table roots/overall root。export receipt 在 artifact 完成后追加，只绑定 artifact SHA-256/size，避免自引用；不得复用 legacy `backup_db` 或 `memory_export`。
- future/legacy/invalid format、busy checkpoint、outbox gap、hash mismatch 全部 fail closed；不得 truncate/delete/vacuum raw tables，也不得用数据库文件 byte hash冒充 logical row integrity。
- 验证：每个 canonical writer 与 fence 的 barrier race、unregistered SQL trigger、fault/restart、busy reader、worker ack/park/replay、old/new generation、manifest determinism、preexisting row equality、合法 C delta、B invariant、D rebuild、export privacy allowlist/root。

### Task 6 — production foreground execution authority 与最小 Runtime composition [HM-AC-3/8]

- 先在 `simple-harness-sdk` 增加 v3 `ContextRouteReceipt(origin=host_initial)` 和 ordinary StartSnapshot v7：`RunStart`、durable snapshot、start request hash/serialization、ReAct checkpoint v6 与 recovery 都携带 exact route JSON/hash；仅接受 `ROUTED_TASK`、exact `run_id`、完整 binding-set receipt/hash、Host authority ref/hash。旧 v1/v2 route 仅用于既有 context-tool/standalone；start schema 1–6 读取为 `UNROUTED`。补 fresh start、duplicate/restart、route/binding/Host-ref tamper、已有 UNROUTED checkpoint 与 routed start 冲突、legacy snapshot compatibility 测试；构建新的 exact candidate wheel，Host 只按 wheel SHA 使用，不在本任务 push/tag/release。
- 新增 `ForegroundRuntimeExecutionAuthority`，构造时固定 state DB、authenticated subject、scheduler owner identity、SDK ingress、context preparer、provider resolver、tool authority preparer、terminal observer 与审计 sink。唯一 public wake 是 `after_enqueue(subject)`；subject 必须等于构造绑定值，不能从 queued payload 派生 authority。最终 Context/Provider/Tool authority 全部绑定 `(host_run_id,sdk_run_id,owner_id,generation)`；旧 generation 对象不能 start/signal/effect。
- scheduler 状态机：`wake/recover → read oldest candidate → build inert draft → atomic claim exact candidate+draft hash → build generation-bound Context/Provider/Tool authority → persist start intent + deterministic sdk_run_id → bind host/sdk → sole ingress.start → observe receipt → record RUNNING → pump signals/acks → observe authenticated terminal → record terminal + settle → wake next`。同一 subject 同时只允许一个驱动协程；真正排他性由 DB lease/generation/CAS 保证，进程锁只用于减少重复工作。
- 冻结三个完全去 Session 化的 constructor-bound port：`ForegroundProviderAuthorityPort` 只从当前 product provider registry/config revision 冻结 provider/model/budget；`ForegroundContextPreparationPort` 只读取 claimed execution、exact ResumePackage、当前 turn、binding receipt 与明确空 recall marker；`ForegroundToolAuthorityPort` 只读取 Host 已验证的 run/binding/catalog facts。它们不得接收或调用 `SessionDB`。若 SDK 仍需 `execution_session_id`，它只由 `host_run_id` 确定性派生作协议身份，禁止用于 SessionDB 查询。initial route 由 Host exact TaskScope/binding receipt 冻结，不能写成 `DIRECT_STANDALONE`；prepared snapshot/source、provider binding、tool authority 和 execution request 均写 immutable audit ref/hash。
- SDK start 不复制 `_run_product_harness_chat` 的 SessionDB user append、projectless migration、WebSocket reservation 或 ReAct loop。适配器复用 `_freeze_sdk_provider_authority`、`_prepare_sdk_context_snapshot`、`SdkRunToolAuthorityRegistry.prepare_run` 与 `SdkRuntimeIngress.start` 的生产逻辑；需要先把这些从 `main.py` 提取为可构造 service，原 chat ingress 也改为消费同一 service，防止两套 composition 漂移。
- restart reconciliation：CLAIMED+无 binding 使用同一 preparation/start identity 继续；有 binding 时先 query SDK durable state，RUNNING/WAITING 补观察 receipt，不再 start；terminal 必须有 SDK 认证 event/ref/hash及 source sequence，缺证据 fail closed。lease reclaim generation+1 后旧 owner 不能 start/signal/terminal/effect。
- control：pending signal 只由当前 scheduler generation 发送到已绑定 SDK Run；SDK ack 后才落 Host ack。pause/stop/cancel 与 terminal race沿用 v41 reducer，Host 不根据超时伪造 terminal。
- 价值 smoke：production constructor + deterministic provider/runtime harness 创建 A/B、100k events、checkpoint、two queued turns；cold restart 后最老 turn 以 `ROUTED_TASK` exact start 一次、Host Context 首轮读取 exact ResumePackage、host/sdk 一对一、RUNNING→terminal→next，注入 prepare/start/bind/observe 各边界故障并证明同一 SDK ID 恢复。Provider 返回确定性纯文本终态，因此该 smoke 不把多 root project effect 伪装成已支持。

### Task 7 — workspace binding、HUMAN lifespan 与 production API 接线 [HM-AC-1/3/4/7/8]

- 完成 `HumanMemoryHostService` 全 facade：primary open、evidence append、TaskScope create/event/mutate/checkpoint/rebuild、search/exact open、manual/Auto binding、queue/control、audit refs、recovery/export。每个方法由 Host 派生 subject 与 allowed set；wrong subject、wrong primary、wrong scope/evidence/run/binding lineage 在 store 调用前稳定拒绝。
- 建立 `CurrentRunBindingAuthorityPort` 的 production 实现，从 `ForegroundRunSnapshot` 读取 exact run/scope/binding/context/generation 并冻结 configuration revision。Auto port 只在当前授权策略为 Auto 且 root 位于 configured workspace 下时执行 proposal→mode snapshot→grant→CAS append；Manual 必须消费现有 Host interaction event/actor/nonce/evidence，若这些 authority 未提供则稳定拒绝，绝不把普通 API 调用当批准。
- Manual binding 采用两阶段 typed Host action，而不是扩充一次性 `AppendBindingRequest` 让 payload 自证授权：`propose_manual_binding` 由已认证 subject + exact raw interaction evidence 生成 durable proposal/challenge/nonce/expiry；`decide_manual_binding` 只接受同一 actor 对该 nonce 的 allow/deny interaction event，验证后生成 decision/grant 并 CAS append。普通 `append_binding` 在 Manual 模式只返回 `workspace_binding_manual_authorization_required` + challenge ref；不得自动 allow。两阶段原始 interaction/evidence/challenge/decision/grant/receipt 永久保留并可审计，重放只返回原结果。
- `backend/main.py` 只消费冻结 composition mode，在 fresh HUMAN lane默认注册 `human_memory_binding_append_authority`、`human_memory_recovery_lifecycle`、`human_memory_foreground_scheduler_wake` 和 runtime execution authority；legacy/future/invalid lane 这些 slot 必须为 `None` 且 endpoint stable fail closed。ServiceContext whitelist/dataclass/exhaustiveness 同步。
- scheduler 在 SDK runtime open 后启动并执行 cold reconciliation；shutdown 先停止 wake/claim、等待或 park 当前工作，再进入 v43 recovery fence。公共 payload 不能选择 subject、数据库路径、worker/owner/generation、raw table、Provider/Tool/Context 或 authority mode。
- 旧 Session fence 使用共享 guard，并同时落在入口和最终 mutation boundary：project protocol/session creation service/`SessionDB.create_session|ensure_session`；chat new-session 与 peer remap/switch；session rename/`set_session_title`；session delete/mark_deleted/`SessionDB.clear`。只要 target/source/requested/generated ID 触及 primary，在 SQL、handoff read、peer remap、workflow cancellation 或 success event 前返回 stable `human_memory_primary_authority_immutable`；现有 `ok=false` response 必须保留稳定 code。
- 不接入主模型 RecallPlan/Memory recall/动态 Context，也不改变 Tool effect envelope；只把 queued primary turn 接到现有 SDK runtime authority。
- 验证：ASGI/API critical + affected + full-surface smoke、fresh/cold/restart、真实 port presence/absence、Auto current-Run authority、Manual challenge→allow/deny/expired/replay/wrong-actor authority、scheduler lifecycle、legacy/invalid/future reject、facade authority matrix、旧 CRUD fence 全入口与最终边界、wiring/exhaustiveness。

### Task 8 — testcase/oracle、回归与文档闭合 [HM-AC-1/3/4/6/7/8]

- 版本化 TC-HM-02/09/10/11/12，并新增 TC-HM-14 recovery/integration Host lane；更新 inventory/reuse report/verification spec 并冻结逐文件 hash。
- 跨仓 identity oracle 固定 SDK source commit、candidate wheel filename/version/SHA-256、installed distribution version、module origin 与 public contract manifest；Host vendored wheel/`pyproject.toml`/`uv.lock` exact pin 独立提交。新 Host 对旧 0.7.0 或错误 wheel hash启动时 fail closed；exact-wheel fresh routed start、duplicate 与 cold restart只用 package-root public API 验证。
- 先跑 Task 6 execution value smoke，再跑 focused fault suites、Host backend full pytest、ruff、changed-surface mypy、critical/affected/full-surface API smoke；Task 4 Archive smoke 作为内容寻址前置证据导入新 run，不替代 execution smoke。
- 对 raw tables 做 pre/post row count/content hash；保留 ignored 原始证据与 SHA-256 索引。
- 测试完成后更新 Host `ARCHITECTURE/ARCHITECTURE.md` 校准锚点、`PROJECT_STATUS.md`、`index.md`，再更新父 program/S4 状态。
- 独立 auditor 审核 AC/obligation/commit-state/证据，机器 gate `finalize` 是唯一完成权威。
