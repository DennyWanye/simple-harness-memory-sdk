# S6 — 单主对话 UI、TaskScope 审查、记忆知识图谱与 Program 验收

> Release unit：S6（Host UI + read APIs + 三仓验证）  
> 高风险子系统：用户可见 Session cutover、审计/隐私 UI、graph visualization（3）  
> 覆盖：HM-AC-1/6/7/8（并汇总 HM-AC-1—8）

## 交付边界

完成用户可见产品形态和 program 最终证明。图谱审美追求清晰、克制、层级良好；不引入独立 graph DB 或视觉
特效依赖。测试必须使用当前 worktree exact build、isolated userdata、真实 UI 点击和真实 provider。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `tauri-app/src/components/SessionList.tsx`、`WorkbenchShell.tsx` | 移除新建/切换/删除 Session UX；唯一聊天入口 |
| `tauri-app/src/stores/sessionsStore.ts`, `views/ChatView.tsx` | hydrate stable primary conversation，不暴露 Session management |
| `tauri-app/src/components/TaskScopePanel.tsx`（新） | active/recent/search/open、README/STATUS/checkpoint/drift/lineage 阅读 |
| `tauri-app/src/components/MemoryPanel.tsx` | Fact list 升级为四类 memory + graph/read/audit/correct/forget |
| `tauri-app/src/components/MemoryGraph.tsx`（新） | SVG accessible graph、filters、node/edge details，无动画特效 |
| `tauri-app/src/types/memoryProgram.ts`（新） | server-filtered view DTO；不复制 mutation authority |
| `backend/main.py`, control protocol handlers | primary/task/memory graph/audit/suppression read endpoints |
| `backend/tests/`, `tauri-app/src/**/*.test.tsx` | API privacy、UI state/accessibility、graph isolation |
| `scripts/acceptance/human_memory_program_smoke.py`（新） | critical/affected/full surface deterministic smoke |

## Tasks

### Task 1 — 唯一主对话 UI cutover [HM-AC-1/8]

- Workbench 不再渲染 Session catalog/new/switch/rename/delete/project-group navigation；启动后 hydrate 后端返回的 stable
  primary conversation，刷新/重启 ID 不变。
- 项目/任务通过内部 route 和 TaskScope panel 展示，不让用户为继续任务创建 Session。
- 旧 SessionList 可删除或仅保留历史未引用文件；production bundle/route manifest 不可触达旧 CRUD。
- 验证：frontend unit、cold start、reload、one visible conversation、no session management controls。

### Task 2 — TaskScope inspect/resume UI [HM-AC-3/7]

- 展示 active/recent TaskScope、status、bound roots/revision、next step/blocker；搜索旧任务只展示候选，用户/模型 exact open
  后才显示 archive view。
- README/STATUS 概括视图支持按需 page-in PLAN/DECISIONS/RESUME/EVIDENCE；显示 source revision/evidence refs/drift。
- Manual binding append 使用明确 confirmation；Auto 状态只读显示来源，不提供模型可操控开关。
- 验证：相似 A/B、cold restart resume、drift、Manual/Auto、wrong candidate no authority。

### Task 3 — Memory knowledge graph [HM-AC-6/7]

- MemoryPanel 使用 server-filtered graph：Episode/Semantic/Procedure/Prospective/Task/Project/Person/Goal/Evidence 节点与
  typed edges；颜色/形状/层级有一致语义，支持 keyboard focus、text alternative、zoom/pan/filter。
- 点击节点显示 type/state/epistemic/conflict/verification/confidence/validity/source refs；candidate/inferred 视觉明确。
- correction/forget 走现有 explicit proposal/decision，不在前端乐观改 canonical state；suppression receipt 后立即移除普通节点。
- 使用纯 React+SVG 和简单 deterministic layout；无粒子、炫光、无意义动画，新依赖为零。
- 验证：snapshot/accessibility、dense graph readable、filter、correct/forget/rebuild、no private tooltip/edge leak。

### Task 4 — 受控审计与普通面隔离 [HM-AC-1/7]

- 普通 trace 遵守 suppression；用户明确“为什么记住/忘记”时 Host 创建 purpose-bound AuditAccessDecision，UI 只展示最小
  source/decision chain，审计访问本身留 event。
- audit receipt 不缓存成普通 Agent capability，不随下一 query/TaskScope/context 复用；关闭详情即丢弃前端临时 payload。
- 凭据/hidden reasoning 不显示；长 payload 只通过 paged exact refs，复制/导出同样由服务端过滤。
- 验证：HM-S7、普通 Agent reuse attempt、stale frontend cache、credential canary。

### Task 5 — 执行 V0 sealed testcase 与 gate manifest [HM-AC-1—8]

- 只执行 V0 sealed inventory/verification-spec/manifest；hash 不一致立即阻断，不在 S6 新增、删减或重标 required case。
- legacy Session 用例只按 V0 `reuse|replace|deprecated` lineage 判定；不得为让新 UI 过门临时排除旧 active oracle。
- manifest 声明 `input_sensitive=true`、`llm_payload_driven=true`、`stateful_init=true`；每个 scenario 已绑定 AC/risk、
  evidence contract、impact paths、manual/root-run 要求。
- 原始截图/录屏/log/DB/receipt 在 `.local-test-evidence/<date>/<run>`；Git 只存小型结论、相对 index、SHA-256。

### Task 6 — 自动化与性能/故障/质量门 [HM-AC-1—8]

- 三仓 clean HEAD 全量 lint/type/unit/integration/artifact/conformance/wheel consumer；fresh init、kill/restart、fault injection、
  suppression side paths、context budgets、physical delete invariant。
- 执行冻结真实主模型 routing/mutation set 的两个独立 root runs；其中同一轮必须 >=20 committed turns、两个
  TaskScope、一次 exact resume，并按 V0 公式计算 timeout/refusal/invalid-plan 与重复 run 聚合；指标达到 AC-8。
- 本地 recall benchmark p95≤500ms/hard≤2s；no-recall 零 Memory query/零额外 continuation；Context item/byte/token hard caps。
- `human_memory_program_smoke.py` 跑 critical+affected；因改路由/公共基础设施/正式 release gate，升级 full-surface smoke。

### Task 7 — required 真人桌面 E2E [HM-AC-1—8]

- 用 isolated userdata 启动当前 worktree Tauri，让 Tauri 自己 spawn backend/Vite；设置
  `DESKPET_BACKEND_DIR=<worktree>/backend`，日志确认 Dev python/worktree 路径，不测旧 frozen backend。
- 使用真实点击/输入，覆盖 frozen HM-S1—S12；每 case screenshot→declare coordinate/action/expectation→real action→screenshot→
  correlated logs。至少 3 个语义类+负例，含 cold start、>=20-turn 长上下文、两个 TaskScope、exact resume、两次独立
  root run 和正向业务结果。
- 真实 provider 凭据只从主 checkout ignored `.env` 进进程；不输出/复制/落证据。任何 required case 未跑或 PARTIAL 均 BLOCKED。

### Task 8 — 三仓架构/发布文档与 machine final gate [HM-AC-1—8]

- 每仓同步 ARCHITECTURE 模块、index、PROJECT_STATUS、CHANGELOG、schema/protocol/init/recovery 文档与 exact evidence refs。
- 三仓提交所有业务与文档改动，排除 run-dir 后工作树干净；对 clean HEAD 重跑关键门和 exact wheels。
- 完成 completion audit、testcase full-audit；以 `plan_test_gate.py finalize` exit code 和 `gate-receipt.json` 为唯一 verdict。
- 若正式发布/推送不在用户现有授权内，停在 validated clean commits/candidates，报告 release gate，不擅自 push/tag。

## 验证出口

- UI、API、库/管道均有对应 primary evidence；display-only twin 的“未进入 Provider Context”必须用 payload snapshot 证明。
- 只有 machine finalize exit 0 才可称 program 完成；否则按诊断码报告 BLOCKED/NOT SHIPPABLE。
