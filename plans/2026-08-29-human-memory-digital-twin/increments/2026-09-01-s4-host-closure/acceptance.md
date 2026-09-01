# 增量验收：S4 Host TaskScope Closure（Task 5–8）

> 状态：APPROVED / FROZEN（2026-09-01）
> 父事实源：`../../acceptance.md`
> 用户批准：`好的，请你继续按照最新的plan-test skill流程继续处理`
> 批准消息 SHA-256：`00400f071b2f6129777b6e457f48fef5204475265e447cde691fe099c4c728bf`

## 主要矛盾

- 核心价值：很久以后重新打开一个任务时，Host 必须能从永久 canonical Archive 找回正确任务并给 Agent 一份有界、完整、可验证漂移的恢复包。
- 最小验证动作：在 fresh Host DB 创建两个同名相似 TaskScope，向目标任务写入 100k events、checkpoint 与排队 Run，重启后先搜索候选再 exact open；断言六视图顶层有界、目标任务无串线、FIFO 顺序不变。旧 Session CRUD fence 属于随后加固门，不阻塞这一价值动作本身。

## 本增量范围

- TaskScope 六个确定性阅读视图：README、PLAN、STATUS、DECISIONS、RESUME、EVIDENCE；固定 byte/page 上限、immutable revision、重建和 checkpoint drift 验证。
- permission-first 的 TaskScope FTS locator；搜索只返回候选，exact open 才从 canonical Archive 组装 bounded ResumePackage。
- 每个 subject 一个 foreground Run、普通 turn durable FIFO、pause/stop/cancel 即时控制、crash/restart recovery，以及可供 Auto binding 读取的 durable Run facts。
- Host-only composition/API、fresh `human-memory-v1` data-format compatibility、旧 Session CRUD 对新 primary 的 stable reject、durable ingress fence、drain/park、WAL checkpoint 和 emergency read/export manifest。
- 本 slice 的自动化 value smoke、fault/restart/integrity tests、Host full regression 与架构事实源回写。

## 明确不在本增量

- S5 的主模型 TaskScope route/RecallPlan、五天短时域、动态 Context assembler、真实 Memory recall、tool effect envelope 与 semantic closure production composition。
- S6 的单主对话 UI、TaskScope Inspector、图谱 UI、真人桌面 E2E 与真实主模型质量门。
- 旧数据迁移、导入或展示；发布、push、tag、merge；多个 foreground Run 或 subagent 执行。

## MUST AC

| ID | 验收条件 |
|---|---|
| HM-AC-1 | fresh program 只暴露唯一 writable primary authority；所有新 evidence/TaskScope/Run 原始记录 append-only。旧 Session create/switch/rename/delete 直连该 primary 必须返回稳定拒绝，rollback/recovery 前后 raw row/count/content hash 不变。 |
| HM-AC-3 | Host 是 TaskScope/Run/FIFO 唯一 authority；同一 subject 同时最多一个 foreground Run，普通 turn 先永久入账后 FIFO，control 立即越过普通队列；重启不丢失、不重复启动，durable Run snapshot 是 Auto binding 唯一 fact source。 |
| HM-AC-4 | TaskScope search 在 ranking 前按 subject/permission 过滤，只返回有界候选；candidate 不改变 active cursor、binding 或 tool authority。open 必须使用 exact ID 并从 canonical Archive 返回 bounded ResumePackage。 |
| HM-AC-6 | README ≤16 KiB、STATUS ≤12 KiB、ResumePackage ≤24 KiB、每个物理 block ≤32 KiB；EVIDENCE 每连续 500 events 形成一个稳定 logical page group，其 manifest 通过内容寻址 index/leaf/chunk blocks 恢复全部 canonical 字段与 refs。1k/10k/100k events 下顶层仍有界，500-event 分组不因物理 block 拆分而改变。 |
| HM-AC-7 | 六视图、projection revisions、checkpoint、search/open、queue/control、fence/export 均有 immutable receipt/ref/hash；删除派生 cache 后可从 canonical facts byte-identical 重建，Markdown/FTS 不是 authority。 |
| HM-AC-8 | fresh schema 初始化、future/legacy epoch 拒绝、projection/search crash、queue duplicate/restart、drain-or-park、WAL checkpoint 与 emergency export 均 fail-closed/可恢复；Host full pytest 与变更 surface 静态检查通过。 |

## 非功能 / 边界

- `input_sensitive=false`：本增量验证的是冻结 DTO 与确定性 Host 行为；自然语言路由质量留到 S5/S6。
- `llm_payload_driven=false`：S4 不新增 LLM 输出解析；现有 mutation plan 只作为 deterministic fixture 输入。
- `stateful_init=true`：新增 v39–v42 持久化 schema、投影索引、Run/FIFO 与 recovery state。
- 原始数据永不物理删除；派生 cache/FTS 可重建，但重建不得改变 canonical rows 或让 suppressed/无权限数据成为候选。
- 不新增第三方运行时依赖；SQLite FTS5 缺失时返回稳定 unavailable，不降级成无权限过滤的模糊扫描。
- 完成且通过测试的 S4 服务在 fresh prototype data dir 默认启用；已有 legacy DB 稳定拒绝升级，不迁移。

## 测试义务矩阵

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---|---|---|---|---|---|
| HM-S4-TO-VALUE | delivery | HM-AC-3/HM-AC-4/HM-AC-6 | — | 100k events + A/B 相似任务 + checkpoint + queued turns，冷重启后 search candidate→exact open→resume | 直接证明长期任务可以正确、有限地恢复 |
| HM-S4-TO-VIEWS | delivery | HM-AC-6/HM-AC-7 | — | 六视图 1k/10k/100k 上限、稳定分页、cache 删除重建 hash equality、drift report | 证明摘要有界且不丢 canonical 事实 |
| HM-S4-TO-FIFO | delivery | HM-AC-3/HM-AC-8 | — | 并发普通 turn、control overtaking、duplicate delivery、terminal→next、crash/restart | 证明初版单 foreground Run 与 durable FIFO |
| HM-S4-TO-INTEGRATION | delivery | HM-AC-1/HM-AC-8 | — | fresh composition/API smoke、legacy/future epoch reject、旧 CRUD→primary reject、emergency export | 证明 Host 入口真实接线而非孤立库代码 |
| HM-S4-TO-DATA | change-risk | HM-AC-1/HM-AC-7/HM-AC-8 | FAIL-DATA-LOSS | fault/recovery/drain/rollback drill 前后 raw tables row count/content hash 相同 | 证明任何恢复与清理都不删原始数据 |
| HM-S4-TO-AUTHORITY | change-risk | HM-AC-3/HM-AC-4 | FAIL-TASK-SEARCH-AUTHORITY/FAIL-FOREGROUND-RUN-CONCURRENCY | wrong principal/search poisoning/candidate-only/no cursor mutation/second active Run rejected | 防止候选搜索或并发执行扩大 authority |
| HM-S4-TO-REGRESSION | change-risk | HM-AC-8 | FAIL-PROTOCOL-REPLAY | TaskScope/primary/Host full pytest + critical/affected API smoke + changed-surface mypy/ruff | 防止新增 schema/入口破坏既有生产路径 |

## 完成定义

1. 六条 MUST AC 与七条 required obligation 都有当前 run 的 fresh root evidence。
2. 价值 smoke 在昂贵全量回归前通过；无 UI/真实主模型成功声明。
3. 独立完成度审计无 open/deferred P0/P1，机器 `finalize` 返回有效 receipt。
4. Host `ARCHITECTURE/ARCHITECTURE.md`、`ARCHITECTURE/PROJECT_STATUS.md`、`ARCHITECTURE/index.md` 与父 program 状态同步。
5. 所有原始测试证据保留在 ignored `.local-test-evidence`；不删除历史证据，不提交 raw artifacts。
