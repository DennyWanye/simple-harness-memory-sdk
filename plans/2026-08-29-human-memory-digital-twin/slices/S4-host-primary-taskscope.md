# S4 — Host 唯一主对话、TaskScope Archive、多根绑定与 FIFO

> Release unit：S4（Host）  
> 高风险子系统：Host persistent state、filesystem authority、foreground scheduler（3）  
> 覆盖：HM-AC-1/3/7/8
> 实施进度：Task 1—3 complete；S1 `a2-001` typed authority 已闭合。Task 4 候选 `47895a25` 经审计后由 `13dbef17` 补齐 store-level Manual/Auto freshness、identity、replay 与 fail-closed seam；当前按 `a2-004` 冻结 durable authority 生命周期和 S5 production composition 后再终审。Task 3 最终提交 `f509a475ea330dff13bfbeab143506de3408df4e`，独立审计 P0/P1/P2=0。

## 交付边界

建立 Host-owned 的唯一主对话和 TaskScope 事实层、路径绑定与单 foreground Run 调度。暂不接真实 Memory recall
和动态 Context；使用 S1 fake route receipt 验证 authority。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `backend/deskpet/memory/migrations/027_human_memory_program_v35.sql`（新） | primary conversation、evidence/events、TaskScope、bindings、FIFO/provision/checkpoint/outbox schema |
| `backend/deskpet/memory/schema.py`, `migrator.py` | fresh program init/checksum/feature marker；不导入旧 Session |
| `backend/deskpet/memory/session_db.py` | 新 evidence append/read APIs；新主流不调用 `delete_turn` |
| `backend/deskpet/task_scope/store.py`（新） | canonical state/events/links/checkpoints/CAS/idempotency |
| `backend/deskpet/task_scope/provisioning.py`（新） | managed/explicit task_home 与 recoverable create state machine |
| `backend/deskpet/task_scope/bindings.py`（新） | append-only binding set、canonical path/filesystem identity、Manual/Auto policy |
| `backend/deskpet/task_scope/projections.py`（新） | 六 bounded views 与 immutable revisions/outbox |
| `backend/deskpet/task_scope/search.py`（新） | rebuildable FTS/vector locator，candidate-only |
| `backend/deskpet/execution/foreground_queue.py`（新） | one active Run + durable FIFO + immediate controls |
| `backend/deskpet/execution/evidence_ingress.py`（新） | Harness execution outbox ingest、receipt/cursor、terminal watermark |
| `backend/deskpet/execution/recovery_fence.py`（新） | data epoch、ingress fence、drain/checkpoint/emergency read-export |
| `backend/deskpet/session/{task_scope,project_binding}.py` | 退役 regex/Session authority；复用 path identity helper |
| `backend/main.py` | composition/API wiring，旧 Session create/list/delete 不作为新 UI 产品入口 |
| `backend/tests/{memory,session,task_scope,execution}/` | init/archive/binding/queue/recovery tests |

## Tasks

### Task 1 — Fresh primary conversation 与永久 Host evidence [HM-AC-1/7/8]

- 在空 userdata 中幂等创建每个 subject 唯一 writable `primary_conversation_id`；DB unique partial constraint + init receipt。
- user/assistant/tool/provider/run evidence 必须先取得 S1 sanitization receipt 后 append-only；业务 payload 和
  hash 不允许 UPDATE/DELETE。修订用新 event/relationship。
- 新 schema 不创建/写 `reasoning_content`；Provider durable record 只用 allowlist public content/ID/type/hash/usage/opaque ref。
- 旧 sessions 不迁移、不展示、不成为 Context；新 product endpoint 只返回 primary conversation。
- 验证：并发 cold init、commit fault、restart、old DB marker refusal、new evidence physical delete SQL/maintenance path 禁止。

### Task 2 — Canonical TaskScope Archive [HM-AC-3/7]

- 建 task_scopes/steps/events/evidence_links/canonical revisions/checkpoints/projection revisions/search outbox。
- Host-native turn/file/test 由 `TaskEventRecorder` 不经 LLM 追加；Harness Provider/Tool/Context/Route/Run 事实从 S1
  `ExecutionEvidenceOutbox` 接收，`source_event_id+hash` 幂等，持久 ingest receipt/cursor。
- terminal 对外完成前 `durable watermark >= run terminal source sequence`；缺口时等待/恢复，不伪造完整 TaskScope。
- mutation apply 使用 base revision CAS，在一事务追加 decision/event、更新 canonical state、写 projection/search outbox。
- 验证：事件顺序、cancel/supersede reason、CAS conflict、checkpoint immutability、删除 views 后重建。

### Task 3 — Managed/explicit provision state machine [HM-AC-3/8]

- 用户未给路径：在配置 root 下建 `<safe-title>--<scope-short-id>`；macOS/Linux 默认
  `~/SimpleHarnessWorkSpace`。用户明确路径只接受 trusted user/Project picker provenance。
- `reserved→filesystem_ready→committed|failed_retryable`；同 idempotency key 收敛同 scope/path，不能补建第二目录。
- task_home 与 workspace roots 分开；existing project 的管理视图默认放 `.simple-harness/task-scopes/<id>`，若禁止写
  metadata 则只在 app-data 物化。
- 验证：每个边界 kill/retry、path nonexist、permission denied、duplicate title、no partial authority。

### Task 4 — Append-only multi-root binding authority [HM-AC-3]

- 一个 TaskScope 有 task_home + 1..N exact roots；binding set 只 append revision，不 update/switch/delete。相同 root 可被
  多 TaskScope 引用。
- canonicalize/realpath + platform filesystem identity；拒绝 workspace root 本身、公共父目录、symlink escape、identity drift。
- Manual append 要 structured user authorization receipt；Auto mode 只从 trusted Run snapshot 取得，且只允许 configured
  workspace root 的真实后代；Auto 不扩大高风险 action 权限。
- Manual challenge 必须通过 constructor-bound authority 读取 Host durable authenticated user evidence，绑定 subject、scope、
  proposal/root、base binding revision、channel、nonce、interaction ID 与 validity interval；decision 再读取绑定 exact
  challenge/nonce/actor/decision/time 的 authenticated interaction。相同 payload replay 原子返回原 receipt，divergent replay
  拒绝。已经决定并持久化的 exact Manual receipt 是该次 append 的 durable authority，不按 Auto expiry 失效；但未提交 append
  每次都重载 proposal/challenge/decision/grant，重启后 verifier 或事实缺失必须 fail-closed。
- Auto snapshot 只能从 Host durable current facts 构造：active Run lifecycle、subject/scope/run revision、frozen binding-set
  revision、context snapshot ID/revision/hash、configuration revision、AUTO mode、configured-root canonical filesystem identity、
  issued/expiry。authorize 与 append 都重载 exact proposal/grant/request/snapshot 和 live facts，复核 configured/proposed root
  identity，并在 commit 前 CAS unchanged base revision。unused grant 在 expiry、terminal、lineage/context/config drift 或
  filesystem replacement 后失效；已提交的 exact grant 只可幂等返回原 immutable receipt，不得创建新 revision 或刷新 effect
  authority，原 Run 仍只能使用 route 冻结的旧 binding receipt。
- 验证：HM-S9 全矩阵、Manual/Auto durable authority restart reconstruction、缺 verifier/store、append-time drift/expiry、
  committed exact replay，每个 effect 读取 exact frozen revision。测试 fake 只证明 port policy，S5 Task 8 的真实 composition
  通过前不得宣称 production authority 闭合。

### Task 5 — 六 bounded 阅读视图与 checkpoint [HM-AC-3/7]

- README/PLAN/STATUS/DECISIONS/RESUME/EVIDENCE 从 canonical state+events+refs 确定性生成；LLM 叙述只来自已接受
  mutation 字段。README/STATUS 上限由 DOC-SPIKE 固定，超限写稳定子文档与索引。
- 冻结上限：README 16 KiB、STATUS 12 KiB、ResumePackage 24 KiB、单 page 32 KiB、EVIDENCE 每 500 events
  一个稳定 page；1k/10k/100k fixture 均保持顶层有界和全字段恢复 oracle。
- projection 失败不回滚 canonical commit；worker 按 revision/hash 重建；旧 revision immutable。
- checkpoint 包含 repo/branch/head/dirty manifest/file hashes/tests/artifacts/next action；resume 时重新验证 drift。
- 验证：长期 fixture、超限拆分、projection crash/rebuild、hash equality、drift report。

### Task 6 — TaskScope candidate search/open [HM-AC-3/7]

- task header/readme/status/decision/artifact/timeline documents 建 FTS+现有 embedding locator；permission filter 在 rank 前。
- search 只返回 ID/标题/goal/project/status/time/snippet/source revision；open 只接受 exact ID，从 archive 组装 bounded
  ResumePackage/page refs。候选不能改变 active cursor/binding/tool authority。
- 验证：相似任务 A/B、旧 revision、wrong principal、search poisoning、exact open、cold restart。

### Task 7 — 单 foreground Run 与 durable FIFO [HM-AC-3/8]

- scheduler policy `max_foreground_runs_per_session=1`；普通新 turn 先永久入账并 FIFO；active terminal 后按 sequence 启动。
- stop/pause/cancel 是 immediate control signal，不进入普通 queue；background workers 不获 Agent effect/semantic authority。
- run/queue/lease/terminal 均 durable，恢复不重复启动或丢 turn；事实模型保留 run_id/CAS seam 但不实现并行。
- 本 Task 同时提供 Auto binding authority 的唯一 durable Run fact source：active/terminal lifecycle、subject、TaskScope、run
  revision、frozen binding-set revision 与当前 route lineage；不能从 DTO metadata、模型参数或进程内 cache 推导。
- 验证：并发输入排序、crash/restart、duplicate delivery、control overtaking、worker coexistence。

### Task 8 — Host-only integration、旧入口 fence 与 recovery [HM-AC-1/3/8]

- `backend/main.py` 装配新 stores/services；在 S4 默认开启新 primary 写入的同一版本，服务端即拒绝旧 Session create/
  switch/rename/delete 对新 authority 的访问，不能等 S6 UI；旧代码只能读明确 legacy epoch。
- 写 data-format epoch/min-max read-write compatibility；future schema stable reject。实现 durable ingress fence、job/outbox
  drain-or-park、WAL checkpoint、schema/protocol/wheel/watermark/row-count/content-hash manifest 与新格式 emergency read/export。
- 关键 API smoke：primary open、TaskScope create/search/open/mutate、binding append、queue/control、audit refs；旧 CRUD 直连
  新 primary stable reject；逐 slice rollback drill 前后 raw evidence count/hash 不变。
- 更新 Host ARCHITECTURE 对应模块和 PROJECT_STATUS（只有本 slice 测试完成后标完成）。

## 验证出口

- Backend full pytest + fresh DB/restart/fault/permission tests；没有 UI 或 Memory 产品成功声明。
- 对新 raw tables 执行 row/hash invariant，证明 cleanup/session delete/forget 不物理删除。
