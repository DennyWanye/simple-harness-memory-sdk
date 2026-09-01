# Plan：S4 Host TaskScope Closure（Task 5–8）

## 主要矛盾

- 决定成败的核心问题：很久以后重新打开一个任务时，Host 能否从永久 canonical Archive 找回正确任务并给 Agent 一份有界、完整、可验证漂移的恢复包。
- 最小验证动作：fresh DB 写入 A/B 相似任务、100k events、checkpoint 与 queued turns，冷重启后 candidate search→exact open A，核对 view/page/resume hashes、drift 与 FIFO。
- 价值验证里程碑：Task 3；此前只实现 deterministic views/checkpoint 与 candidate search/open 的直接依赖。

## 关联验收标准

- 覆盖 HM-AC-1、HM-AC-3、HM-AC-4、HM-AC-6、HM-AC-7、HM-AC-8。
- 复用 program testcase：TC-HM-02、TC-HM-09、TC-HM-10、TC-HM-11、TC-HM-12；本 slice 只新增其自动化 Host 子 lane，不宣称 UI/真实主模型通过。

## 文件影响清单

| 文件 | 职责 | 本次改动 |
|---|---|---|
| `backend/deskpet/memory/migrations/031_task_scope_projections_v39.sql` | view/checkpoint 派生状态 | immutable view/page/checkpoint verification/outbox receipt schema |
| `backend/deskpet/task_scope/projections.py` | 六视图 | deterministic bounded render、stable paging、rebuild、checkpoint drift |
| `backend/deskpet/memory/migrations/032_task_scope_search_v40.sql` | locator | immutable search docs + rebuildable FTS5 + cursor refs |
| `backend/deskpet/task_scope/search.py` | candidate search/open | permission-first filter、rank、bounded candidate、exact open ResumePackage |
| `backend/deskpet/memory/migrations/033_foreground_queue_v41.sql` | Run/FIFO | durable run、turn queue、control receipt、lease/terminal facts |
| `backend/deskpet/execution/foreground_queue.py` | scheduler authority | one active Run、FIFO claim/settle、immediate control、restart recovery |
| `backend/deskpet/memory/migrations/034_human_memory_recovery_v42.sql` | epoch/recovery | data-format compatibility、fence/drain/park/export receipts |
| `backend/deskpet/execution/recovery_fence.py` | recovery | ingress fence、WAL checkpoint、raw manifest、emergency read/export |
| `backend/deskpet/human_memory_service.py`（新） | Host composition | primary/TaskScope/search/open/mutate/binding/queue/control/audit facade |
| `backend/main.py` | production entry | default fresh service lifecycle、HTTP/WS API、legacy CRUD→primary fence |
| `backend/deskpet/memory/{migrator,schema}.py` | schema init | v39–v42 chain、checksum、future/legacy stable reject |
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
- Task 8 提供可运行 Host API，但不在 S4 偷做 S5 的 LLM routing/context；入口接通与 Agent 消费是两个独立 release unit。

## 任务清单（最短价值路径优先）

### Task 1 — v39 六阅读视图与 checkpoint verifier [HM-AC-6/7/8]

- 改动：新增 v39 migration 与 `task_scope/projections.py`；从 canonical revision、events、steps、evidence refs、bindings、checkpoints 生成 README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE。
- 上限：README 16 KiB、STATUS 12 KiB、Resume 24 KiB、page 32 KiB、EVIDENCE 500 events/page；稳定 page ID 绑定 scope/revision/kind/page index/content hash。
- 语义：先提交 canonical，再由 outbox 生成 immutable projection revision；失败不回滚 canonical。cache 删除后同输入 byte-identical 重建。
- checkpoint：保存 repo/branch/head/dirty manifest/files/tests/artifacts/next action；open 时按 caller 提供的 live probe 生成 drift report，不静默改 canonical checkpoint。
- 验证：1k/10k/100k、Unicode/超长字段、worker crash/lost ACK、cache delete/rebuild、old revision immutability、drift matrix。

### Task 2 — v40 permission-first search 与 exact open [HM-AC-4/6/7]

- 改动：新增 immutable search documents、FTS5 index、cursor/rebuild receipts；实现 `TaskScopeSearchService.search()` 与 `open_exact()`。
- search：先限定 authenticated subject/allowed scope IDs，再执行 MATCH/rank；返回 ID/title/goal/project/status/time/snippet/source revision，byte/item 上限固定。
- open：只收 exact ID，重载 canonical revision + projection receipt + checkpoint + binding set，组装 ≤24 KiB ResumePackage 和 page refs。
- authority：search/open 本身不写 active cursor、不追加 binding、不产生 tool grant；wrong principal 与 stale revision fail closed。
- 验证：A/B 同名、poison canary、旧 revision、wrong principal、empty/oversize query、FTS unavailable、cold rebuild/exact open。

### Task 3 — 价值 smoke：100k TaskScope 冷恢复 [HM-AC-3/4/6/7]

- 在 fresh DB 通过公开 Host facade 创建 A/B、100k events、checkpoint、pages；删除派生 cache/FTS 后重建并冷重启。
- 执行自然任务等价的 typed query，先返回候选，再 exact open A；核对 A/B canary、全部 view/page hashes、ResumePackage 上限与环境 drift。
- 此 smoke PASS 前不运行 full regression、打包或 finalize；失败立即回到 Task 1/2。

### Task 4 — v41 单 foreground Run 与 durable FIFO [HM-AC-3/8]

- schema：foreground runs、queued turns、control receipts、leases/terminal receipts；对 active/running 状态建立 subject 唯一约束。
- `enqueue_turn` 先验证 primary evidence ref 再 append；`claim_next` 原子创建/恢复唯一 Run 并冻结 task_scope/binding/context lineage；duplicate key 返回原 receipt。
- pause/stop/cancel 直接写 control receipt 并 signal 当前 Run，不进普通 queue；background worker kind 永远不能 claim foreground lease。
- terminal 原子落账后才允许按 sequence claim 下一 turn；restart 恢复 lease/terminal，不能双启或丢 turn。
- 验证：并发 enqueue、duplicate/lost ACK、control overtaking、lease expiry/restart、terminal crash boundary、worker coexistence、Auto binding snapshot read。

### Task 5 — v42 recovery fence 与 emergency export [HM-AC-1/7/8]

- schema/service：data-format epoch、min/max read-write、ingress fence state、drain/park receipt、WAL checkpoint receipt、raw manifest/export receipt。
- recovery 顺序：close ingress → drain or park projection/search/queue outbox → `wal_checkpoint(FULL)` → row-count/content-hash manifest → reopen or emergency read/export。
- future/legacy format stable reject；busy checkpoint、outbox gap、hash mismatch 都 fail closed。不得 truncate/delete raw tables 或把派生 cache hash当 raw integrity。
- 验证：每个边界 fault/restart、busy reader、park/replay、manifest determinism、raw bytes/row/hash invariant。

### Task 6 — Host service 与生产入口接线 [HM-AC-1/3/4/7/8]

- 新增 `HumanMemoryHostService` 组合 Task 1–5 与已有 primary/archive/binding/ingress stores，外部只见 typed facade/receipt。
- `backend/main.py` 在 fresh data dir 默认初始化新 service；提供 primary open、TaskScope create/search/open/mutate、binding append、queue/control、audit refs/recovery API。
- 旧 Session create/switch/rename/delete 若 target 等于 primary authority，返回 stable `human_memory_primary_authority_immutable`；legacy epoch 只能走明确 legacy path。
- 不把 service 接入主 Agent route/recall/context/tool effect；该依赖明确留给 S5。
- 验证：ASGI/API critical + affected smoke、cold/restart、legacy/future reject、旧 CRUD fence、wiring/exhaustiveness。

### Task 7 — testcase/oracle、回归与文档闭合 [HM-AC-1/3/4/6/7/8]

- 版本化 TC-HM-02/09/10/11/12 的 Host 自动化子 lane，更新 inventory/reuse report/verification spec 并冻结逐文件 hash。
- 先跑 Task 3 value smoke，再跑 focused fault suites、Host backend full pytest、ruff、changed-surface mypy、critical/affected/full-surface API smoke。
- 对 raw tables 做 pre/post row count/content hash；保留 ignored 原始证据与 SHA-256 索引。
- 测试完成后更新 Host `ARCHITECTURE/ARCHITECTURE.md` 校准锚点、`PROJECT_STATUS.md`、`index.md`，再更新父 program/S4 状态。
- 独立 auditor 审核 AC/obligation/commit-state/证据，机器 gate `finalize` 是唯一完成权威。
