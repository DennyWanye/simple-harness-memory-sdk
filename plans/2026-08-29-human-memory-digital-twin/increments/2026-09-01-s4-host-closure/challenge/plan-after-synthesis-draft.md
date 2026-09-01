# Plan：S4 Host TaskScope Closure（Task 5–8）

## 主要矛盾

- 决定成败的核心问题：很久以后重新打开一个任务时，Host 能否从永久 canonical Archive 找回正确任务并给 Agent 一份有界、完整、可验证漂移的恢复包。
- 最小验证动作：fresh DB 写入 A/B 相似任务、100k events、checkpoint 与 queued turns，冷重启后 candidate search→exact open A，核对 view/page/resume hashes、drift 与 FIFO。
- 价值验证里程碑：Task 4；此前只实现 deterministic views/checkpoint、candidate search/open、durable FIFO 与 typed Host facade 的直接依赖。

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
| `backend/deskpet/execution/recovery_fence.py` | recovery | ingress fence、WAL checkpoint、raw manifest、emergency read/export |
| `backend/deskpet/human_memory_service.py`（新） | Host composition | primary/TaskScope/search/open/mutate/binding/queue/control/audit facade |
| `backend/main.py` | production entry | default fresh service lifecycle、HTTP/WS API、legacy CRUD→primary fence |
| `backend/deskpet/memory/{migrator,schema}.py`, `backend/deskpet/memory/session_db.py` | schema init | pre-opener epoch dispatch、v39–v42 chain、checksum、future/legacy stable reject |
| `backend/deskpet/{task_scope/store.py,task_scope/provisioning.py,task_scope/workspace_bindings.py,execution/evidence_ingress.py,memory/human_memory_program.py}` | source producers | canonical 写入同事务检查 fence 并登记 projection source change；不得靠事后扫描补 outbox |
| `backend/tests/task_scope/*`, `backend/tests/execution/*`, `backend/tests/memory/*` | black-box/fault tests | 1k/10k/100k、A/B、wrong principal、queue/recovery/API smoke |
| `testcase/human-memory-program/*`, `testcase/index.*` | oracle | 复用并版本化 S4 Host 自动化子 lane |
| `ARCHITECTURE/*` 与父 program 文档 | 事实源 | 只在测试完成后标 S4 Task 5–8 完成并记录证据 |

## Complexity inventory

| 复杂度表面 | 本次是否新增 | 理由 / AC 或 risk 绑定 |
|---|:---:|---|
| 新依赖 | 否 | 复用 SQLite/FTS5、aiosqlite、现有 FastAPI |
| 新公共 API | 是 | Host-only primary/TaskScope/search/open/queue/control/audit；HM-AC-1/3/4/7 |
| 新持久化状态 | 是 | projection/search/foreground/recovery v39–v42；HM-AC-3/6/8 |
| 新配置项 | 否 | fresh prototype 默认启用，legacy DB stable reject |
| 新抽象层 | 是 | 单一 `HumanMemoryHostService` composition facade；避免 main.py 直接拼私有 store |
| 新后台任务 | 否 | 本 slice 暴露 `run_once`/recover 接口；持续 worker owner 留在 S5 production loop |
| 可复用已有实现 | `CanonicalTaskScopeStore`, `TaskWorkspaceBindingStore`, `ExecutionEvidenceIngress` | canonical facts、binding 与 ingest 不复制 |
| 标准库/平台能力 | SQLite FTS5 / WAL checkpoint / JSON / SHA-256 | rebuildable locator 与 recovery manifest |

## Assurance / 信任与失败边界

- Profile：standard；contract 为同目录 `assurance-contract.json`。
- 入口链：authenticated Host subject → `HumanMemoryHostService` → exact store/search/queue operation → immutable receipt；search query/snippet 与重复 delivery 不可信。
- 数据流：raw/canonical 表只 append；head/lease/cache/FTS 是可恢复协调状态。任何 rebuild/recovery 不删除 raw 表。
- 关键失败：FAIL-DATA-LOSS、FAIL-TASK-RESUME-LOSS、FAIL-TASK-SEARCH-AUTHORITY、FAIL-FOREGROUND-RUN-CONCURRENCY、FAIL-PRIMARY-STREAM-SPLIT、FAIL-READ-VIEW-GROWTH、FAIL-PROTOCOL-REPLAY。
- 停止追踪点：S5 main-model route/recall/context/tool composition、S6 UI/真人 E2E、旧数据迁移、发布/合并。

## 方案选择与取舍

- 采用 canonical archive + rebuildable projection/FTS；不把 Markdown、FTS row 或 embedding 当 authority。
- 初版检索用 permission-first FTS5 + deterministic metadata rank；embedding locator 仅保留可插拔接口。为本 slice 引入新向量依赖会扩大环境与质量门，且不影响“候选→exact open”的正确性。
- 采用 DB partial unique constraint + transactional claim；不依赖进程内 Queue，因为进程崩溃会丢顺序和 active owner。
- Host 只拥有前台 admission/FIFO/control/lease authority；实际 Agent root Run 仍由已发布 Harness SDK Runtime 执行。一个 `host_run_id` 只能幂等绑定一个 `sdk_run_id`，Host 不实现第二套 ReAct loop。
- 投影视图的版本身份不是单一 canonical revision，而是 `TaskScopeProjectionSourceV1` 的内容哈希：scope、单调 source sequence、canonical revision/state hash、event watermark/prefix root、checkpoint set root、binding revision/receipt hash、renderer contract version。任何源变更都必须在源写事务内追加 source-change + outbox。
- `EVIDENCE 500 events/page` 定义为 logical page group，不承诺 500 条完整事件塞进 32 KiB；group manifest、index/leaf/chunk 都是内容寻址的物理 block，任一 block ≤32 KiB，并可逐字节恢复全部 canonical 字段与 refs。
- Task 8 提供可运行 Host API，但不在 S4 偷做 S5 的 LLM routing/context；入口接通与 Agent 消费是两个独立 release unit。

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

### Task 3 — v41 单 foreground Run 与 durable FIFO reducer [HM-AC-3/8]

- authority：Host 是 durable admission/FIFO/control/lease/current-Run snapshot 唯一 owner；Harness SDK Runtime 是实际 Agent execution 唯一 owner。foreground scheduler 以一对一 admission receipt 将稳定 `host_run_id` 绑定到唯一 `sdk_run_id`，重放只能返回原绑定，超时/未知不得另起 Run。
- queue：`ABSENT→QUEUED→CLAIMED→SETTLED`。enqueue 在确认同 subject/primary 的 committed evidence ref/hash 后分配单调 FIFO sequence；claim 只取最老未结算项，在同一事务创建 CLAIMED Run、冻结 scope/binding/context lineage、占用 subject slot 与 generation=1 lease；terminal/settlement/lease close/slot release 原子提交后下一项才可 claim。
- Run reducer：`CLAIMED→RUNNING|FAILED`；`RUNNING→PAUSE_REQUESTED→PAUSED|RUNNING`；PAUSED 可 resume 到 RUNNING 且 generation+1；任一非终态可按强度进入 `STOP_REQUESTED`/`CANCEL_REQUESTED`，最终只接受 SDK 认证的 `COMPLETED|FAILED|STOPPED|CANCELLED`。终态 immutable，只允许 exact replay。
- controls：优先级 `CANCEL > STOP > PAUSE`，不进入普通 FIFO。control intent、reduced desired state 与 durable signal outbox 同事务；强控制可覆盖弱控制，弱控制不得降级；terminal-first 返回 `already_terminal`，control-first 必须用 SDK causal evidence 裁决竞态，Host 不伪造取消终态。pause 保留 foreground slot；resume 仅允许无 stop/cancel intent 的 PAUSED Run。
- lease/restart：lease 身份为 `(host_run_id, owner_id, generation, expires_at)`；heartbeat 只续期，reclaim/transfer/resume generation+1。所有 start/signal ack/state CAS/effect admission/terminal/Auto snapshot 都校验当前 generation；旧 owner 只能读。crash 前后均恢复同一 queued turn/host Run/sdk Run，lease expiry 不等于终态、不重新排队。
- background exclusion：投影、搜索、提取 worker 使用独立 lease namespace，不能调用 foreground claim/start/signal/cancel；`worker_kind`/metadata 不能铸造 authority。partial unique constraint 保证每 subject 至多一个 nonterminal foreground Run。
- 验证：并发 enqueue、duplicate/lost ACK、每个事务边界 crash-before/after、control race/优先级、terminal race、stale generation、lease expiry/restart、background claim 拒绝、SDK 一对一绑定、Auto snapshot 只读当前 foreground lineage。

### Task 4 — fresh Host typed facade 与 100k 冷恢复价值 smoke [HM-AC-1/3/4/6/7/8]

- 在任何 `state.db` writable opener、`initialize_state_db()`、`SessionDB.initialize()`、MemoryManager/provider/worker/API/backup 之前，由单一 startup epoch dispatcher 持有决策锁并只读分类：`FRESH`、`HUMAN_RESUME`、`LEGACY`、`INVALID`、`FUTURE`。
- `FRESH` 仅允许批准的 prototype userdata lane 且 DB absent/zero-byte/无用户表的有效 v0；立即由 human initializer 写入 bootstrap/epoch marker 并顺序迁移至 v42。`HUMAN_RESUME` 验证 marker/checksum 后续跑 v0..v42 的精确未完成链。`LEGACY` 只走原 legacy composition 且 human endpoints 返回 `human_memory_program_legacy_database_unsupported`；`INVALID/FUTURE` 在任何业务写入、SessionDB、backup/reset/recovery 前 fail closed。所有消费者获得冻结 composition mode，不再各自 redispatch。
- 新增 `HumanMemoryHostService` typed facade 的价值路径：Host 从受信 auth snapshot 派生 subject；payload 只能提供 selector/内容/idempotency，不能自报 subject、allowed scope IDs、mode、binding/context revision 或 worker authority。scope/evidence/run/binding/checkpoint 的每次读取和写入都验证同 subject + primary + hash + lineage。
- 在 fresh DB 通过该 facade 创建 A/B、100k events、checkpoint 与 queued turns；删除派生 cache/FTS 后重建并冷重启。typed query 先返回候选，再 exact open A；核对 A/B canary、logical group/physical block coverage、全部 view/page hashes、ResumePackage 上限、环境 drift 与 FIFO 顺序。
- 此 smoke PASS 前不运行 recovery fault matrix、full regression、打包或 finalize；失败立即回到 Task 1–4 的对应设计，不先补外围加固。

### Task 5 — v42 recovery fence 与 emergency export [HM-AC-1/7/8]

- schema/service：data-format epoch、min/max read-write、durable fence singleton/generation、drain/park/worker-ack receipt、WAL checkpoint receipt、logical manifest/export receipt。冻结状态机为 `OPEN→CLOSING→QUIESCED→SEALED→OPEN`，任一步失败进入 `FAILED_CLOSED`；重启从 durable state/generation 继续，不猜测 ingress 已开启。
- 事务围栏：每个 human-memory canonical writer 用 `BEGIN IMMEDIATE`，在首次 mutation 前于同一事务读取 fence generation/state；仅 OPEN 可写。close coordinator 获取 SQLite writer lock，CAS OPEN→CLOSING 并固化 cutoff/generation，因此 fence commit 必然在线性化点之前所有 writer 提交之后；之后获锁的 writer 看见 CLOSING 并稳定拒绝。v42 对冻结的 canonical/Run/FIFO 表 allowlist 增加 SQLite trigger 作为漏登记 writer 的 defense-in-depth，统一抛 `human_memory_ingress_fenced`；recovery coordinator 只有 constructor-bound authority，可写 recovery receipts 与声明的 derived coordination 表。
- writer registry 明确覆盖 primary init/evidence、TaskScope create/event/mutation/checkpoint、provisioning、binding、foreground enqueue/claim/control/terminal 以及后续 canonical writer；关闭 API ingress 本身不构成 quiescence。CLOSING 后 drain/park cutoff 内全部 outbox，撤销或等待 worker lease，并以 ack/watermark/gap receipt CAS 到 QUIESCED。
- checkpoint：在 recovery mutex 与持续 closed fence 下以 autocommit 执行 `wal_checkpoint(FULL)`；返回必须非空且 `busy=0`、`log_frames=checkpointed_frames`。checkpoint 不能被一个长写事务包住，因此依赖 durable fence + 全 writer check + worker ack；busy/unknown/gap 进入 FAILED_CLOSED，不生成成功 manifest。
- manifest taxonomy 固定为 schema allowlist 而非名称前缀：A=protected immutable authority rows；B=只允许 CAS 的 authority coordination heads/watermarks/current binding/queue-run lease heads；C=恢复期间可追加的 immutable derived/audit receipts；D=可删除重建的 projection cache/FTS/index/worker cursor。cutoff 后不得新增 A；M0 对每个 A 表固化 schema/typed-column hash、按主键排序的 row count 与 typed canonical row leaf root，post-check 逐个证明所有 preexisting primary key 仍存在且 leaf 相同。B 验证引用/CAS invariant；C 单列合法 delta count/root；D 不参与 raw equality，只跑 rebuild oracle。未知 protected table/column 直接 fail closed。
- emergency export 仅从 SEALED manifest snapshot 生成，明确 allowlist A + 必要 B snapshot + C lineage，排除 D、legacy Session、auth/config secrets 与 private provider payload；typed deterministic serialization、主键排序、内容寻址 chunk，并包含 epoch/migration checksums/DB instance/fence generation+cutoff/per-table roots/overall root。export receipt 在 artifact 完成后追加，只绑定 artifact SHA-256/size，避免自引用；不得复用 legacy `backup_db` 或 `memory_export`。
- future/legacy/invalid format、busy checkpoint、outbox gap、hash mismatch 全部 fail closed；不得 truncate/delete/vacuum raw tables，也不得用数据库文件 byte hash冒充 logical row integrity。
- 验证：每个 canonical writer 与 fence 的 barrier race、unregistered SQL trigger、fault/restart、busy reader、worker ack/park/replay、old/new generation、manifest determinism、preexisting row equality、合法 C delta、B invariant、D rebuild、export privacy allowlist/root。

### Task 6 — Host service 与生产入口接线 [HM-AC-1/3/4/7/8]

- 完成 `HumanMemoryHostService` 全 facade：primary open、evidence append、TaskScope create/event/mutate/checkpoint/rebuild、search/exact open、manual/Auto binding、queue/control、audit refs、recovery/export。每个方法由 Host 派生 subject 与 allowed set；wrong subject、wrong primary、wrong scope/evidence/run/binding lineage 在 store 调用前稳定拒绝。
- `backend/main.py` 只消费 Task 4 冻结的 composition mode，在 fresh human lane 默认启用 service；提供 typed HTTP/WS API。queue claim/settle 仅对内部 scheduler 暴露，recovery/export 仅对 trusted Host lifecycle 暴露，公共 payload 不能选择 subject、数据库路径、raw table 或 authority mode。
- 旧 Session fence 使用共享 guard，并同时落在入口和最终 mutation boundary：project protocol/session creation service/`SessionDB.create_session|ensure_session`；chat new-session 与 peer remap/switch；session rename/`set_session_title`；session delete/mark_deleted/`SessionDB.clear`。只要 target/source/requested/generated ID 触及 primary，在 SQL、handoff read、peer remap、workflow cancellation 或 success event 前返回 stable `human_memory_primary_authority_immutable`；现有 `ok=false` response 必须保留稳定 code。
- 不把 service 接入主 Agent route/recall/context/tool effect；该依赖明确留给 S5。
- 验证：ASGI/API critical + affected + full-surface smoke、fresh/cold/restart、legacy/invalid/future reject、facade authority matrix、旧 CRUD fence 全入口与最终边界、wiring/exhaustiveness。

### Task 7 — testcase/oracle、回归与文档闭合 [HM-AC-1/3/4/6/7/8]

- 版本化 TC-HM-02/09/10/11/12，并新增 TC-HM-14 recovery/integration Host lane；更新 inventory/reuse report/verification spec 并冻结逐文件 hash。
- 先跑 Task 4 value smoke，再跑 focused fault suites、Host backend full pytest、ruff、changed-surface mypy、critical/affected/full-surface API smoke。
- 对 raw tables 做 pre/post row count/content hash；保留 ignored 原始证据与 SHA-256 索引。
- 测试完成后更新 Host `ARCHITECTURE/ARCHITECTURE.md` 校准锚点、`PROJECT_STATUS.md`、`index.md`，再更新父 program/S4 状态。
- 独立 auditor 审核 AC/obligation/commit-state/证据，机器 gate `finalize` 是唯一完成权威。
