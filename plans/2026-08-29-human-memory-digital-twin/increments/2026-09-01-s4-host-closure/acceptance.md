# 增量验收：S4 Host TaskScope + Runtime Execution Closure（Task 5–8 + 最小 S5 composition）

> 状态：APPROVED / FROZEN（2026-09-01）
> 父事实源：`../../acceptance.md`
> 用户批准：`好的，请你继续按照最新的plan-test skill流程继续处理`
> 批准消息 SHA-256：`00400f071b2f6129777b6e457f48fef5204475265e447cde691fe099c4c728bf`
> A2 范围修订：用户选择 `A`，批准把 claimed-turn、Context/Provider/Tool authority、SDK start/bind、terminal/restart、真实 workspace binding 与 HUMAN lifespan production composition 纳入本 slice。
> A2 批准消息 SHA-256：`559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd`

## 主要矛盾

- 核心价值：很久以后继续一个任务时，Host 不仅要找回正确 TaskScope，还必须让最老的持久化 turn 使用冻结且可审计的 TaskScope/Context/Provider/Tool authority，真正启动唯一的 Harness SDK Runtime Run。
- 最小验证动作：在 fresh Host DB 创建两个同名相似 TaskScope，向目标任务写入 100k events、checkpoint 与两个 queued turns；冷重启后 search candidate→exact open A，再由 production scheduler 只 claim 最老 turn，准备冻结 execution request，经唯一 SDK ingress 启动并绑定同一 host/sdk Run，记录 RUNNING→terminal 后才启动下一 turn；断言无串线、无重复 start、无 request-selected authority。

## 本增量范围

- TaskScope 六个确定性阅读视图：README、PLAN、STATUS、DECISIONS、RESUME、EVIDENCE；固定 byte/page 上限、immutable revision、重建和 checkpoint drift 验证。
- permission-first 的 TaskScope FTS locator；搜索只返回候选，exact open 才从 canonical Archive 组装 bounded ResumePackage。
- 每个 subject 一个 foreground Run、普通 turn durable FIFO、pause/stop/cancel 即时控制、crash/restart recovery，以及可供 Auto binding 读取的 durable Run facts。
- production foreground execution composition：claimed-turn exact read model、冻结 Context/Provider/Tool/execution authority、唯一 SDK ingress start、一对一 host/sdk binding、signal/terminal reconciliation 与 restart resume；Host 不实现第二套 Agent loop。
- Host-auth-bound workspace binding append：Manual 使用真实 interaction authority；Auto 只接受当前 foreground Run/generation/context/configuration snapshot；TaskScope 可绑定多个不可切换 root。
- Host-only composition/API、fresh `human-memory-v1` data-format compatibility、旧 Session CRUD 对新 primary 的 stable reject、durable ingress fence、drain/park、WAL checkpoint 和 emergency read/export manifest。
- 本 slice 的自动化 value smoke、fault/restart/integrity tests、Host full regression 与架构事实源回写。

## 明确不在本增量

- S5 其余语义能力：主模型 TaskScope route/RecallPlan、五天短时域、动态 Memory Context assembler、真实 Memory recall 与 semantic closure。为启动 Runtime 所需的最小冻结 Context/Provider/Tool authority 已纳入，但不得暗中实现 recall 决策或新语义路由。
- 多 root TaskScope 的 project Tool effect root-selection 协议。多 root 的 binding-set 存储与恢复必须保真，但在 exact root selector 尚未进入 SDK effect request 前，项目 effect 必须稳定 fail closed；不得默选第一个/最近一个目录。
- S6 的单主对话 UI、TaskScope Inspector、图谱 UI、真人桌面 E2E 与真实主模型质量门。
- 旧数据迁移、导入或展示；发布、push、tag、merge；多个 foreground Run 或 subagent 执行。

## MUST AC

| ID | 验收条件 |
|---|---|
| HM-AC-1 | fresh program 只暴露唯一 writable primary authority；所有新 evidence/TaskScope/Run 原始记录 append-only。旧 Session create/switch/rename/delete 直连该 primary 必须返回稳定拒绝，rollback/recovery 前后 raw row/count/content hash 不变。 |
| HM-AC-3 | Host 是 TaskScope/Run/FIFO admission 唯一 authority，Harness SDK Runtime 是 Agent execution 唯一 authority；同一 subject 同时最多一个 foreground Run，普通 turn 先永久入账后 FIFO，control 立即越过普通队列。最老 turn 必须经 claimed-turn exact read 与冻结 Context/Provider/Tool authority，通过唯一 SDK ingress 以 Host 已验证的 initial `ROUTED_TASK` receipt 实际启动；`host_run_id` 幂等绑定唯一 `sdk_run_id`，RUNNING/terminal/control/restart 均校验 generation，重启不得重复 start。durable Run snapshot 是 Auto binding 唯一 fact source。 |
| HM-AC-4 | TaskScope search 在 ranking 前按 subject/permission 过滤，只返回有界候选；candidate 不改变 active cursor、binding 或 tool authority。open 必须使用 exact ID 并从 canonical Archive 返回 bounded ResumePackage。 |
| HM-AC-6 | README ≤16 KiB、STATUS ≤12 KiB、ResumePackage ≤24 KiB、每个物理 block ≤32 KiB；EVIDENCE 每连续 500 events 形成一个稳定 logical page group，其 manifest 通过内容寻址 index/leaf/chunk blocks 恢复全部 canonical 字段与 refs。1k/10k/100k events 下顶层仍有界，500-event 分组不因物理 block 拆分而改变。 |
| HM-AC-7 | 六视图、projection revisions、checkpoint、search/open、queue/control、fence/export 均有 immutable receipt/ref/hash；删除派生 cache 后可从 canonical facts byte-identical 重建，Markdown/FTS 不是 authority。 |
| HM-AC-8 | fresh schema 初始化、future/legacy epoch 拒绝、projection/search crash、queue duplicate/restart、execution prepare/start/bind/terminal 各边界故障、signal replay、drain-or-park、WAL checkpoint 与 emergency export均 fail-closed/可恢复。HUMAN lifespan 必须注册真实 binding/recovery/scheduler/runtime authority，legacy/future 不得注册；Host full pytest 与变更 surface 静态检查通过。 |

## 非功能 / 边界

- `input_sensitive=false`：本增量验证确定性的 admission/composition/lifecycle；自然语言路由与回答质量留到 S5/S6，Provider 文本不作为本 slice 的成功 oracle。
- `llm_payload_driven=false`：本 slice 复用 SDK Runtime 已有 LLM/tool 状态机，不新增或放宽模型载荷解析；测试 Provider 只用于证明 production start/terminal wiring。
- `stateful_init=true`：新增 v39–v44 持久化 schema、投影索引、Run/FIFO、recovery 与 execution preparation/audit state。
- 原始数据永不物理删除；派生 cache/FTS 可重建，但重建不得改变 canonical rows 或让 suppressed/无权限数据成为候选。
- Manual workspace binding 必须经过 durable challenge + 同一已认证 actor 的 allow/deny decision；一次性 append 请求不能自证授权。Auto binding 只使用当前 foreground Run 的 exact generation/context/configuration snapshot，且仅限 configured workspace root 之内。
- initial TaskScope route 必须具有独立 Host provenance，并进入 SDK ordinary start wire、start hash 与 ReAct checkpoint；旧 start wire 保持 `UNROUTED`。已有 checkpoint 与 initial route 不一致时 fail closed，不能覆盖或重建成“看起来一致”。
- claim 前 preparation 只能生成不可执行 draft；Context/Provider/Tool/start/signal/effect authority 必须在 atomic claim 后绑定 exact host/sdk Run、owner 与 generation。foreground production ports 禁止读取 legacy `SessionDB`。
- v44 execution 原始 audit rows 永久保留并逐表纳入 recovery fence、manifest taxonomy 与 emergency export；不得把 preparation/start/observation/reconciliation lineage 当 cache 删除。
- 不新增第三方运行时依赖；SQLite FTS5 缺失时返回稳定 unavailable，不降级成无权限过滤的模糊扫描。
- 完成且通过测试的 S4 服务在 fresh prototype data dir 默认启用；已有 legacy DB 稳定拒绝升级，不迁移。

## 测试义务矩阵

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---|---|---|---|---|---|
| HM-S4-TO-VALUE | delivery | HM-AC-3/HM-AC-4/HM-AC-6 | — | 100k events + A/B 相似任务 + checkpoint + two queued turns；冷重启后 search→exact open→production scheduler 启动最老 SDK Run→terminal→next | 直接证明长期任务不仅可正确恢复，而且会按冻结 authority 真正继续执行 |
| HM-S4-TO-VIEWS | delivery | HM-AC-6/HM-AC-7 | — | 六视图 1k/10k/100k 上限、稳定分页、cache 删除重建 hash equality、drift report | 证明摘要有界且不丢 canonical 事实 |
| HM-S4-TO-FIFO | delivery | HM-AC-3/HM-AC-8 | — | 并发普通 turn、inert draft→atomic claim→generation-bound authority、initial routed SDK one-to-one start/bind、control overtaking+ack、terminal→next、prepare/start/bind 各边界 crash/restart | 证明初版单 foreground Run 与 SDK execution 的 durable FIFO |
| HM-S4-TO-INTEGRATION | delivery | HM-AC-1/HM-AC-8 | — | fresh HUMAN lifespan composition/API smoke、真实 binding/recovery/scheduler/runtime ports、legacy/future missing-port reject、旧 CRUD→primary reject、emergency export | 证明 Host 入口和 production authority 真实接线而非 fixture 或孤立库代码 |
| HM-S4-TO-DATA | change-risk | HM-AC-1/HM-AC-7/HM-AC-8 | FAIL-DATA-LOSS | fault/recovery/drain/rollback drill 前后 raw tables row count/content hash 相同 | 证明任何恢复与清理都不删原始数据 |
| HM-S4-TO-AUTHORITY | change-risk | HM-AC-3/HM-AC-4 | FAIL-TASK-SEARCH-AUTHORITY/FAIL-FOREGROUND-RUN-CONCURRENCY/FAIL-RUNTIME-AUTHORITY-DRIFT | wrong principal/search poisoning/candidate-only/no cursor mutation/second active Run rejected；request-selected subject/provider/tool/context/mode 与 stale generation 全拒绝 | 防止候选搜索、并发执行或 Runtime composition 扩大 authority |
| HM-S4-TO-REGRESSION | change-risk | HM-AC-8 | FAIL-PROTOCOL-REPLAY | SDK old/new start/checkpoint matrix + exact candidate wheel identity/origin + TaskScope/primary/Host full pytest + critical/affected API smoke + changed-surface mypy/ruff | 防止跨仓协议、新 schema 或入口破坏既有生产路径 |

## 完成定义

1. 六条 MUST AC 与七条 required obligation 都有当前 run 的 fresh root evidence。
2. 价值 smoke 在昂贵全量回归前通过；无 UI/真实主模型成功声明。
3. 独立完成度审计无 open/deferred P0/P1，机器 `finalize` 返回有效 receipt。
4. Host `ARCHITECTURE/ARCHITECTURE.md`、`ARCHITECTURE/PROJECT_STATUS.md`、`ARCHITECTURE/index.md` 与父 program 状态同步。
5. 所有原始测试证据保留在 ignored `.local-test-evidence`；不删除历史证据，不提交 raw artifacts。
