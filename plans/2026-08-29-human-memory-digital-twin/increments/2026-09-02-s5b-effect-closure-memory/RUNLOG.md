# RUNLOG — S5b effect gate / semantic closure / Memory 异步面

- 2026-09-02 接手（HANDOFF-S5b）。Host `main`@`ec1cb944`（feat 分支已快进合并，tmp worktree 已移除）、Memory `main`@`fcf1682`。
- 基线：Host 6282 passed / 7 既有红（roster 与 S5a 一致）；Memory 1071 passed（`baseline.md`）。
- 现状调查：三路并行（Task 5/6/7），结论进 `notes-investigation-task{5,6,7}.md`。
- Spike（实践先行）：A1 真实 provider closure 调用 PASS；A2 Memory job runner 在 exact wheel 上部分成立（accepted ≠ 物化）；A3 SDK PROJECT_EFFECT 门成立含设计约束（standalone/hidden = 整 Run 故障）。
- phase-2 challenge loop `plan-iteration-001`（`verification/plan-challenge/`）：primary 18 findings（1 P0/11 P1/6 P2）→ 5 required specialist（含 4 个真实/exact-wheel probe）→ synthesis 28 canonical → 修订 plan（fe78… → db4f… → e5c6…）→ closure round 2：25 resolved / 3 open（均为 scope-change-proposal，待用户）/ 5 patch-induced P2（已修，档案 `closure-round-2-patch-induced.json`）。
- challenge 实证的关键新事实：Memory 0.6.0 三处阻断（filter policy 不可配、多 op finalize 永久 audit_pending、accepted 不物化）→ Memory 0.6.1 前移为里程碑直接依赖；冻结 SDK 下 standalone/hidden PROJECT_EFFECT 只能是整 Run 故障；终答由 SDK delivery pump 在 Host 终态前交付；Prospective ack 只能由新工具 `prospective_ack` 驱动；Harness 证据 outbox+worker 会丢行 → 改同事务直写+预留。
- Loop 状态：`USER_SCOPE_APPROVAL_REQUIRED`（A6/A7/A11 三项需用户裁决；acceptance 修订提案 A1–A13 见 `acceptance-amendments-proposed.md`）。
- closure round 3（e5c6…）：5 个 patch-induced P2 全部 resolved；残留一条非阻塞（映射表列 run_terminal）已落 plan。Ponytail minimality plan-pass：LEAN，7 条全部 scope_change=false 已自动应用（合并 harness_evidence 进 `ExecutionEvidenceIngress`、复用 `TaskEventRecorder`、内联 pre-admission audit、单一后台 lane、去掉 `AnalysisExecutorPermanentError`、去掉 `prospective_ack_invocations` 与 `post_turn_invocation_attempts_events` 两表）。当前 plan hash 见 git。
- **等待用户**：批准 acceptance 修订提案 A1–A13（含 A6/A7/A11 三项裁决）+ plan；批准后 `record-challenge-control --action scope-change-approved` 入账并合并 acceptance。
- 2026-09-02 用户回复（原话 sha256 `2a99dd6aabeee8485b1453b7371170bef6a04ff2990165079f31c691f4ad75f7`，原文存 `verification/plan-challenge/user-approval-2026-09-02.txt`）：①"接受"acceptance 与修订提案 A1–A13；②三项裁决（A6/A7/A11）委托独立子代理审核后采纳；③要求记录性文档一律中文。处理：英文 spike 报告加中文摘要置顶；后续所有记录文档中文；裁决交独立审核代理，结果入 `delegated-decisions-A6-A7-A11.md` 后合并进 acceptance 并以 `scope-change-approved` 入账。
- 委托裁决（`verification/plan-challenge/delegated-decisions-A6-A7-A11.md`）：A11 **拆分**——S5b 保留 AC-1/2/3/6（10 任务、3 高风险），AC-4+AC-5 移入 S5c（S6 之前）；A6 单根 scope 解释 + strict `workspace_binding_receipt_superseded`（Task 0 写 `behavior_changes` 进 sealed lineage）；A7 processed := durable `prospective_ack` 凭证 + 有界重现（随 A11 入 S5c）。已合并进 acceptance.md / assurance-contract.json（acceptance_ids=4，+OOS-S5C）/ plan.md（Task 0,1,2,3,4a,4,5,6,7,8）。
- 机器账本：`record-challenge-control --action scope-change-approved`（approval hash = 用户原话 `2a99dd6a…`）→ loop `plan-iteration-001` **CONVERGED**（3 轮：11 P0/P1 → 0）。plan 标 `finalized`。**进入 phase-3**。
- 执行模式自决（留痕）：集中兵力串行 Task 0→1→2→3（共享 foreground_queue/main/sdk_adapters）；Task 4a（Memory 仓，文件不相交）分兵给子代理在独立 worktree 并行；Task 4 汇合做里程碑。
- Task 0 完成（Host commit `aec5bacf`，Memory commit `3cdf167`）：oracle 冻结（TC-HM-08/09/11/14 frontmatter 追加 S5B-TO-* 义务并 bump revision）、`s5b-effect-closure-memory-verification-spec.json`/reuse-report、`design-freeze.md`、gate run `verification/r1-s5b` init+activate+phase-start(phase-3-execute)、黑盒与三 lane fault runner 骨架（47 strict xfail）。`check-release-unit` PASS（gate 解析 AC/高风险计数为 0，实际 4/3 以 manifest release_unit 为准）。
- 派发事故自报：首次分兵时隔离 worktree 落错仓（Task 4a 落在 Host、Task 1 落在 Memory），隔离守卫禁止跨仓 git，两代理均未改任何文件即停止；已按正确 cwd 重新派发（Task 1 → Host worktree，Task 4a → Memory worktree），错仓 worktree 已清理。教训：`isolation: worktree` 以派发时 shell cwd 所在仓为准，跨仓分兵前先 `cd`。
- **Task 1 完成并合并**（Host `s5b/task-1-effect-gate` → main ff `f8097429`，7 commits，oracle 先行 commit `0641211d` 实装前全红）：PROJECT_EFFECT 清单 + exhaustiveness、`BindingRootResolver`、`effect_gate.py`（§4 1→3→4→5→6）、executor 前置门（拒绝=`EffectExecution(effect=None, rejected)`）、main.py 注入与缺槽断言、standalone snapshot 不含写工具、三条整 Run 故障稳定码进 `run_terminal.public_payload.error_code`、ARCHITECTURE/PROJECT_STATUS 回写。主 checkout 复验：sdk_adapters/task_scope/execution 相关 150 passed / 11 xfailed；ruff 改动面与基线逐条相同（零新增）。design-freeze §4 第 3 步措辞按实装语义修订（§11）。
- 分兵事故二：Task 1 被派发两次（首次代理在被判"错仓"后自建 Host worktree 完成了工作；第二次代理做到 oracle+大半实现），采纳首次代理成果，第二次代理改动整体丢弃（未合并），worktree 已清理。教训：代理被纠正后要先确认其最终状态再重派。
- **Task 1 独立代码审查（A4，高档）**：`verification/code-review-task1.md`，VERDICT FAIL——P0=0、P1=1、P2=9。P1 F-1：EffectGate 在 SDK exact-replay/reconcile 之前返回终态 rejected（崩溃重放已 settle effect 时模型见 rejected 而 ledger=SUCCEEDED）→ 修法"已有 effect 记录跳过 gate 交 SDK 重放" + 两条决定性回归测试，**已追加给 Task 2 执行代理**（同文件避免冲突）。P2 F-2（head/scope 读不在同一快照，TOCTOU）、F-3（不 sticky）、F-5（MCP 写类工具未分类）、F-6（memo 释放）、F-7（缺 head 误报 superseded）、F-8（effect_id 条件校验）、F-9（error_code 无白名单）、F-10（覆盖缺口：inode/symlink/跨 Run/memo 隔离/composition 真构造）→ 记入 Task 6 hardening 清单；F-4（测试基座覆写 SDK execute）→ Task 2 的 F-1 回归测试改用真实 SDK executor。
- 2026-09-02 ~21:00 API 限额中断：Task 4a 代理已完成 §8.1–§8.5 六个 commit（worktree `agent-af580808ace4181ea`，第 6 项未提交），Task 2 代理尚未改文件；限额恢复后两代理以原上下文续做（SendMessage 续接，不重派）。
- **Task 4a 完成并合并**（Memory `worktree-agent-af580808ace4181ea` → main merge `f1609ea`，8 commits）：§8.1 filter policy 透传、§8.2 多 op finalize 规范序（根因 `_read_decisions` 只按 decision_id 序）、§8.3 accepted plan 在 prepare 事务内以 application capability 物化（spike A2 步骤 4a 转 PASS，kill before/after_commit 收敛）、§8.4 `register_principal_owner`、§8.5 analysis lineage + schema v7.1 前向加列、§8.6 `analysis_apply_head`（经 `core.jobs.current_analysis_apply_head()` contextvar 暴露，因 `analyze_memory` 签名冻结）；版本 0.6.1 + API 快照 + CHANGELOG。主 checkout 全量 **1106 passed / 8 skipped**（基线 1071）。wheel 双次 clean build + 合并后第三次重建同 hash `4b6c7bc665178d85340b80751d2216fd77821b0ae12f7a4c3281ae4fe9d2b5d6`。Host 侧须知：backend 未绑 evidence_authority 时保持审计-only；evidence authority 在写锁内被调用，Host 解析器不得回调 Memory 加锁读。
- **Host pin 0.6.1**（Host commit 见 git）：vendor wheel + candidate manifest + `sdk_candidate.py`/`pyproject.toml`；venv 以 `uv pip install --no-deps` 安装（wheel 声明 `simple-harness-sdk<0.8,>=0.7`，registry 不可解析属既有口径）；Memory 面 Host 测试（candidate/no_recall/s5a matrix/memory/route tool/s5b 骨架）全绿。`backend/uv.lock` 仍指 0.5.2（S5a 遗留，记入遗留清单）。
- **Task 2 完成并合并**（Host merge `959725f6`，7 commits，oracle 先行 `761e640d` 全红）：v46 迁移 `038_effect_closure_memory_v46.sql`（§5 七表 + marker/恢复注册/迁移链，前向迁移与旧 runtime 拒绝测试）；`OBJECTIVE_EVENT_MAP` + test-runner 白名单；executor 在 SDK settle 后同一 state.db 事务写 host.file|host.test + evidence 行 + harness.tool_invocation（SDK effect 分库经预留 seq 幂等关联，crash 排空重放收敛有测试）；`ExecutionEvidenceIngress` 预留/排空（observer 唯一排空 + tombstone，`authorize_terminal` 只在排空后放行）；`semantic_closure.dirty_state`；Task 1 审查 **F-1 已修**（`ee02d933`，步骤 0 exact replay 不重验，两条真实 SDK executor 回归先红后绿）。主 checkout 复验 190 passed / 39 xfailed；ruff 改动面零新增。
- Task 2 代理指出的 S5a 遗留：`migrator.py` 中 037 分支位于 `_S4_HUMAN_MIGRATIONS` 判断内但 037 不在该集合 → v45 无 marker/迁移链/恢复注册（fence 触发器缺失）；本轮 preserve-approved 未改，**记 Task 6 hardening**。无 foreground 绑定的 Run 不产 Harness 证据（边界已写 ARCHITECTURE）。
- **Task 2 独立代码审查**：`verification/code-review-task2.md`，VERDICT FAIL——P0=0、P1=2、P2=6；F-1 修复复核为真修。P1 F-1（`commit_fact` 对模型路径跑凭据正则在 settle 后抛错 → Run 失败循环、terminal 写不下）与 P1 F-2（终态时 UNKNOWN/HANDED_OFF 的 PROJECT_EFFECT 被 tombstone 成 trivial → dirty 静默干净）**已追加给 Task 3 执行代理**（同文件簇）。P2 六条记入 Task 6 backlog。
- **Task 3 完成并合并**（Host merge `e033a781`，7 commits，oracle 先红 `b36c6da3`）：`task_scope_update` direct kernel 工具（strict schema、§7 拒绝码与迁移表、apply+receipt 同事务、pre-admission audit；注册走 host-composed 同 `context_route`，未改 hash-bound manifest）；snapshot protected 收口指令注入；三水位终态门 `foreground_terminal_closure_pending`（四终态）+ `EffectBoundary.CLOSURE`；`RunBoundInvoker` 五态/unknown 三分类（reserved 与 lease 同事务，返回后复验）；`ClosureFallback`（仅 COMPLETED+终答，reconcile 全规则）；pending 归属 admission scope、下一 Run 合并、`force_close_pending`（complete/resume.update/checkpoint）、STATUS `semantic_closure_pending`；Task 2 审查 **F-1/F-2 已修**（`0ddf6f6e`）。主 checkout 复验 236 passed / 30 xfailed。自决记录：`resume` 强制收口取 `resume.update`（route resume_existing 不强制，否则下一 Run 无法合并 pending）；`sent_confirmed` 只能确认仍 `handed_off` 的行（v46 单调守卫）；v46 迁移加列 `tool_name`（Task 6 cutover 口径确认）。
- 派发 Task 4（价值里程碑：终态同事务 outbox、analysis_proposal、Host analysis executor/delivery authority、evidence_authority、v7 接线删 fail-open、后台 lane、真实 provider 里程碑车道）与 Task 3 独立审查（并行）。
- **Task 3 独立代码审查**：`verification/code-review-task3.md`，VERDICT FAIL——P0=0、P1=2、P2=7、P3=3；Task 2 F-1/F-2 修复复核为真修。P1 F-1（幂等重放用当前水位再写 receipt，可清零新脏事件）与 P1 F-2（生产 main.py 未注入 `closure_reader`，snapshot 收口注入只在测试基座）**已追加给 Task 4 执行代理**。P2 记入 Task 6 backlog。
- **Task 4 完成并合并（价值验证里程碑）**（Host merge `a5277c7e`，10 commits，oracle 先红 `dcb272a1`）：`memory/evidence_authority.py`（只读 state.db）、v7 接线（filter policies/evidence+delivery authority/`register_principal_owner`，**fail-open 分支已删**）、`record_sdk_terminal` 同事务 outbox+links、`memory_ingestion_outbox.py` worker、`analysis_proposal.py`（§9）、`analysis_executor.py`（executor=delivery authority，三键查重，blocked→`memory.analysis.blocked`）、单一后台 lane + main.py 装配 + `sdk_effect_gate` 白名单补漏；Task 3 审查 **F-1/F-2 已修**（`54b44952`/`2205a772`）。主 checkout 复验：sdk_adapters/execution/task_scope/memory/faults 548 passed / 1 failed（superseded wheel hash 断言，已随 pin 更新修正 `a42835d0`）/ 16 xfailed。
- **里程碑真实车道 PASS（主 checkout 复跑，2026-09-03 00:2x）**：`pytest tests/sdk_adapters/test_s5b_milestone_real_provider.py -m real_provider` 1 passed（51.5s）。事实：gpt-5.6-luna，主 Run 4 次 Provider 调用、3 次工具调用，README 版本 1.1.3→1.2.0，终答「已将 README.md 中的版本号改为 1.2.0，其余内容保持不变」；closure 由模型在 Run 内自行 `task_scope_update`（兜底 0 调用）；outbox delivered → job applied → cognitive head 物化（analysis/cognitive head 同步到 2）→ 下一轮 typed_recall 读到含 1.2.0 的记忆；attempts 恰 1。transcript `.local-test-evidence/s5b-real-provider/run-1788366475.json`（ignored）。子代理 worktree 内首跑的 transcript 随 worktree 删除丢失（教训：删 worktree 前先拷出 ignored 证据；本次以主 checkout 复跑重生）。
- 代理自报的自决/发现：① Memory 0.6.1 缺陷——多 evidence batch 中只引用非首条 evidence 的 operation 被 `decision_evidence_refs_ordinal_invalid` 拒绝（生产一 turn 一 batch 不触发；已派 Task 5 修为 0.6.2）；② v46（未发布）`post_turn_invocation_attempts` 加列 `result_envelope_json`；③ 成员集只含用户 turn 文本；④ `AnalysisLeaseFence.revalidate` 以 deadline+30 复验；⑤ 首跑模型 analysis 返回 no_mutation 后调整 `host-analysis-prompt/v1` 措辞（prompt 是实现不是 oracle，断言未放宽——交 Task 4 审查核实）；⑥ 一次跑中模型把 persona 文本追加进 README（版本号仍正确）——写工具口径问题记 Task 6。

## 矛盾转化再分析（里程碑 PASS 后，phase-3 A.3）

- 原主要矛盾"真实发生的事能否确定性沉淀为任务档案语义与长期记忆"已在真实 provider 上成立（改文件 → 客观事件 → 收口 → 同事务 outbox → analysis 物化 → 可召回）。
- 现在决定成败的问题转为：**这条链在故障、并发、恢复与权限边界下能否稳定、可审计地交付**——三轮独立审查已累计抓出 5 个 P1（全部已修）与 ~25 个 P2（Task 6 backlog），说明主链跑通但硬化不足；其次是 **真实桌面 UI 上整机是否通**（S5a 教训：零件绿整机不通）。
- 排序据此调整：Task 6（hardening：审查 P2 全清 + Auto explicit_only + cutover 前置 + 037 迁移链）与 Task 7（真实 UI 通道）并行先行，Task 5（0.6.2）汇合后再进 Task 8 验收矩阵与机器门。
- **Task 5 完成并合并**（Memory merge `abcaa9b`，3 commits）：缺陷根因 `_application_from_batch_unlocked` 把按 ordinal 过滤的 evidence_refs 子集直接交给 `DecisionLedgerEntry`（要求 ordinal 1..n）→ prepare COMMIT 后抛 `decision_evidence_refs_ordinal_invalid`；修为按 batch 顺序重编 ordinal，batch 外引用仍拒绝（反例覆盖）。0.6.2 cutover 测试（schema 钉 v7.1 checksum、0.6.1 库不迁移、0.6.0 库前向加列）、CHANGELOG、candidate manifest；全量 1113 passed / 8 skipped；wheel 双次 clean build + 主 checkout 重建同 hash `598678c6a90d6dcc0a0b75e4b7ebb8c2fc9ca52c362c6037334f93692bc2bd05`。Host pin → 0.6.2（vendor/candidate/sdk_candidate/pyproject/superseded 断言），Memory 面 Host 测试全绿。
- 分兵事故三：Task 6 首派再次落错仓（派发前 shell cwd 在 Memory 仓），代理零改动即停；已从 Host cwd 重派。规则固化：**每次 `isolation: worktree` 派发前，同一回合先单独 `cd` 到目标仓并 `pwd` 确认**。
- **Task 4 独立代码审查**：`verification/code-review-task4.md`，VERDICT FAIL——P0=0、P1=1、P2=4、P3=9；Task 3 F-1/F-2 修复复核为真修；真实车道断言自 oracle commit 未改、prompt 调整合法未放宽。P1 F-1（Provider 响应后派生异常让 attempt 永久 handed_off）+ AC-6① 违约（缺件 startup fail 实为 warning+skip）+ 两条 P2（outbox 不一致行无限 reclaim、缺 binding 阻断终态卡 FIFO）**已追加给 Task 6 执行代理**；其余 P2/P3 记遗留清单（phase-4 journal）。
- **Task 7 真实桌面 UI 通道：通道走通，预演 BLOCKED（抓到 P0）**：脚本在 `.local-test-evidence/real-ui-channel/tools/`（`scripts/dev/` 不被 ignore，故改放此处）；vite→后端（isolated fresh userdata、Dev python、WeMM 本地）→ Ed25519 身份绑定→shim 代理全部走通，Browser pane 真实点击输入"今天想去公园散步"并发送。**失败根因（S5a 同型：零件全绿整机不通）**：Host 真实启动 `product_sdk_runtime_skipped reason=build_failed: sdk_context_authority_composition_missing:sdk_provider_binding_resolver`——Task 4 装配 `_activate_memory_analysis_lane` 读模块全局 `_sdk_provider_binding_resolver`，该全局在 stack 构建之后才赋值，构建期恒 None；且 composition 失败只 skipped 不 fail startup。已作为 P0 最高优先追加给 Task 6（修装配顺序 + 真 startup fail + 按真实启动顺序的构造测试）；修复合并后由 Task 7 代理复跑预演。证据：`verification/real-ui-channel-20260903T003610/`（summary/sha256/decisions 0 行/UI 观察），原始日志与 state.db 在 ignored 目录。截图 PNG 未能落盘（screencapture 无权限、Browser pane 截图不落盘）——phase-4 UI 证据形态需另定（S5a 用 real-ui-session-evidence.txt 形态）。
- **Task 6 完成并合并**（Host merge `0de95582`，11 commits）：**真实启动 P0 已修**（`_activate_memory_analysis_lane` 改读 service_context 槽；composition 构建异常 raise 不再 skipped；`test_product_sdk_runtime_stack_builds_on_real_startup_order`）；Task 4 审查 F-1（响应先单事务 settle 再派生，`quote_too_long`）与两条 P2（outbox 不一致行有界 dead_letter；缺 binding 终态照常 + `dead_letter(run_binding_unavailable)`）；backlog 全清（F-2/F-3/F-6/F-7/F-8/F-9/F-10、T2-R 六条、T3-R 七条）；Auto `explicit_only` a–d 断言；037 迁移链回补 + 旧库幂等 repair；单根 per-canary + ≥2 root 隐藏；cutover 用例集 `tests/memory/test_s5b_v46_cutover.py`；S5a S1 断言+transcript、lint 清零；write_file 原样断言。主 checkout 复验 **600 passed / 14 xfailed / 0 failed**。**未做**：F-5 MCP 写工具纳入 gate（仅经"unknown EffectClass → Auto confirm-only"间接收窄；project_bound Run 已排除 filesystem MCP）→ 记遗留；`_drive_claimed` 真实 runtime 端到端未补；§3 `terminal:{run_id}` 字面偏离已记 ARCHITECTURE。
- 派发 Task 6 独立审查；Task 7 代理复跑真实 UI 预演（main `0de95582`）。
- 2026-09-03 ~02:00 第二次 API 限额中断：Task 6b（无提交）、Task 7 复跑预演（run 目录 20260903T015153 进行中）、Task 6 审查（报告未写）三代理中断；限额恢复后以原上下文续接（不重派）。
- **Task 6 独立代码审查**：`verification/code-review-task6.md`，VERDICT FAIL——P0=0、P1=1、P2=4、P3=5；P0 启动装配修复复核为真修（槽先注册后读、异常直达 lifespan）；Auto explicit_only/单快照/sticky/PREPARED 再过门/Task 4 F-1 均成立。**P1 F-1：升级路径断裂**——`dispatch_startup_epoch` 在 037 回补 repair 之前校验 marker 链，S5a v45 旧库/修复前 v46 库启动被 `human_memory_marker_chain_invalid` 拒绝 → **已追加给 Task 6b**（repair 前置到校验之前 + 真实 v45 库启动测试）。P2：真实启动顺序用例未走真实 builder；cutover 前置对非 foreground SDK WAITING 不可判定；F-5 Manual 下 MCP 写入盲区；§4 sticky 与冻结 authority 顺序偏离 → 记遗留/journal。
- **Task 6b 完成并合并**（Host merge `6b637886`，3 commits）：`foreground-fifo-closure` 补齐 message-commit/run-admission/projection-commit，`taskscope-init-binding` 全部 11 seam（S4 六条 kill/replay + S5b 五条 effect gate）实装，`tests/faults` **零 xfail**；Task 6 审查 **P1 升级路径已修**（`eaf74308`：启动入口在 marker-chain 校验前幂等回补 037 链，真实 v45 库可启动、evidence 守恒）。主 checkout 复验 faults/memory/sdk_adapters/execution/task_scope **618 passed / 0 failed**；ruff 自动修复 5 项后改动面零残留。**代码冻结（Host main 见 git，Memory main `6fe6555`+）→ 进入 phase-4。**
- **phase-4 r1-s5b**：re-attest（behavioral，73 变更）后记账：S2/S3/S4/S7 deterministic root PASS、S1 真实 ×2 PASS、证据 attach；**REG-FULL root FAIL（真实回归）**：`tests/test_execute_sdk_run.py::test_execute_sdk_run_registers_delivery_before_start_first_turn`——durable tool authority inventory 期望缺 Task 6 引入的 `effect_class`/`manifest_dangerous`（测试期望过期，非产品缺陷；修复 commit `32d7849c` 只改测试）。按 gate 规则 root fail 粘性 → r1 无法 SHIPPABLE，开 **r2-s5b** 承接（manifest `related_run_dirs=[r1-s5b]`；r1 将 `retire --superseded-by r2`，账本完整保留）。
- **phase-4 r2-s5b**（Host `32d7849c`）：S3/S4/S2/S7 deterministic root PASS（S2/S4 带 fault root_run_id）、S1 真实 ×2 PASS（transcript `run-…json`，business-result 已 attach）、fault-runner 三 lane 各 11 行、S7 facts；REG-FULL 后台记账中；UI-A/B/C 正式 run 由 Task 7 代理在 `32d7849c` 上执行中；`DRIVER_APPROVAL_MISSING` 待用户一句话批准。
- **2026-09-03 03:10 起（会话续接）**：上一会话被中断，后台的 REG-FULL r2 record-run 与 UI 代理均被杀（无完成记录）。核对落地状态：r2 已有 S3/S4/S2/S7/S1×2 root PASS；**UI-A 冷启动 1-turn 正式 run PASS**（`.local-test-evidence/real-ui-channel/20260903T030437-uiA/`，Host `af9fdc7a`，session `d5eea36c…`，root_run_id `1b3225ad…`，state.db 0→46 全量迁移、`product_sdk_runtime_ready`、route `direct_standalone`，终答非空）；UI-B 在 `af9fdc7a` 上跑到第 1 轮时被杀，但后端已把该 Run 判定失败。
- **用户批准 all-AI 驾驶**：用户 2026-09-03 原话「批准 S5b 真实 UI 场景由 AI 驾驶」，sha256 `7a84b793e6de249975a544288ce35989f02cb9e0a52f47eef933bb10beb64183`（原文存 `verification/plan-challenge/user-approval-all-ai-driving-2026-09-03.txt`），已 `record-approval --kind all-ai-driving` 入 r2 账本。
- **REG-FULL r2 重录**：首次调用因 `--exec` 语法（须 `--exec -- bash <script>`）未启动、未记账；改为脚本 `reg_r2.sh`（Host 全量 + 断言恰好 7 条已知红且零意外 + Memory 全量）后台记账中。
- **UI-B 两次失败定性为真实产品缺陷（S5B-UI-F1，待修）**：真实 UI 下模型对「继续任务：把 README 里的版本号改成 1.2.0」不走 `context_route`，直接 `tool_search` → 命中 `mcp:filesystem:*`（deferred）→ `tool_describe` 成功 → `tool_activate`（参数与 describe 返回完全一致）连续失败，模型只见到不透明的 `tool_failed/"Tool execution failed."`，反复重试至 `react_repeated_tool_exceeded` 整 Run 失败（两次 HEAD 9b0744dd / af9fdc7a 同一轨迹）。真实异常被 `tool_search.py::activate_handler`（异常→`{"error":…}`）与 `sdk_adapters/tools.py::_result`（`error`→统一 `tool_failed`，无日志）两层吞没。pytest 真实车道 S1 PASS 是因为基座把 `write_file` 直接放进目录、没走产品的 deferred 披露/激活路径——正是 UI 场景要抓的差异。已停掉残留通道进程（证据目录保留），派出 Task 7b 修复代理：确定性复现拿到准确异常 → 最小修复（不可激活的能力不披露或带原因；拒绝给稳定 error_code + next_action；Host 结构化日志）→ 决定性测试 → ARCHITECTURE 同步 → `notes-investigation-task7b.md`。修复落地后 UI-B/UI-C 在新 HEAD 重跑，REG/S1/S4 按 re-attest 结果重录。
- **REG-FULL r2 root PASS**（Host `af9fdc7a`：`7 failed, 6438 passed, 50 skipped`，恰好 7 条已知环境红、零意外；Memory `be0ab91`：`1113 passed, 8 skipped`；exec log `r2-s5b/artifacts/exec-S5B-REG-FULL-0007.log`）。同时 UI-A 的 S8/S7 root run 已记入 r2（`--run-id-under-test product-sdk-08e72106…`，session `d5eea36c…`）。
- **r2 账本完整性链断裂（执行者操作错误，如实记录）**：REG record-run（约 9 分钟）被放到后台执行，期间又在同一 run-dir 上执行了 record-approval / 两条 record-run，gate 的读-改-写不支持并发，结果 `finalize --check-only` 报 `LEDGER_TAMPERED: integrity 链只有 19 条，账本里的事实至少需要 20 条`。按 gate 规则不手改账本、不用新记录覆盖；处置：待 Task 7b 修复落地（代码变更本就要求 re-attest 重录）后 `init r3-s5b`（`related_run_dirs=[r1-s5b, r2-s5b]`），在最终 HEAD 上全量重录 7 场景（含 UI-A/UI-B/UI-C 真实 UI），r1/r2 均 `retire --superseded-by r3-s5b`。r2 的 UI-A 证据文件（`r2-s5b/artifacts/ui-a/`）与 exec 日志原样保留，r3 重新 attach。教训已写入个人记忆（gate 写操作必须串行）。
- **2026-09-03 上午：真实桌面 UI 抓到并修掉两个真实产品缺陷（Task 7b）**。详见 `notes-investigation-task7b.md`。
  - **S5B-UI-F1**（修复 `951538bd`）：project-bound Run 里 `mcp:filesystem` 被判 `workspace_unscoped`，但
    `tool_search`/`tool_describe` 与普通 deferred 工具毫无区别，`tool_activate` 抛出的
    `tool_unavailable:workspace_unscoped` 被 `activate_handler` 与 `_result` 两层压成不透明 `tool_failed` 且无日志 →
    真实模型原样重试三次 → `react_repeated_tool_exceeded` **整 Run 死**。修复：披露侧标 `activatable=false` +
    `availability_reason` + `next_action` 且可激活项排前；拒绝侧给白名单稳定码 + `next_action` + 结构化日志。
    **真实 UI 复验通过**（`20260903T0600-uiB-fix`：`tool_describe` 返回 `activatable: true`、`tool_activate` 成功）。
  - **S5B-UI-F2**（首版 `e46b1629`，扩面 `38ff5e9a`）：模型漏填必填参数时，冻结 SDK 在
    `ToolRegistry.validate` 于**进入处理器之前**抛 `MalformedToolArgumentsError`，kernel 把**整个 Run** 判
    `driver_failed`，模型无从自纠。真实 `gpt-5.6-luna` 先后用 `tool_search {}` 与 `context_route {}` 各打掉一个 Run
    （后者当场证伪了只覆盖三件套的首版修复）。最终方案：必填校验统一下沉到 Host 的 `_sdk_tool` 包装层，
    `required` 从发布给 SDK 的 schema 取出、由 Host 执行，缺项返回 `missing_required_argument` + 指名缺失参数，
    记 `tool_arguments.missing`；语义未放宽，类型校验仍由 SDK 负责。**真实 UI 复验通过**
    （`20260903T0730-uiB`：同一 Run 内六次空参数调用全部变成模型可见拒绝，Run 每次都存活）。
    动态 MCP 工具 schema 由远端提供，Host 无法接管，仍登记为上游 SDK 义务 + known-debt。
  - 两条契约均已在同一交付内写入 `ARCHITECTURE/AGENT_HARNESS.md`；决定性测试
    `backend/tests/sdk_adapters/test_tool_activate_unavailable_disclosure.py`（11 条，回退产品代码后变红）。
  - **UI 里程碑仍未跑通（如实记录）**：README 至今未被真实 UI 改成 1.2.0。两个阻塞点——① 种子任务域原绑
    `<run>/workspace` 与 Run 准入冻结的会话项目目录不一致（**种子设置问题，非产品缺陷**，已给
    `seed_task_scope.py` 加 `--workspace`）；② 本机时间 09:2x 起上游 `ai.svtun.cn` 反复 60 秒
    `transport_timeout`，SDK 按 `sent_unknown` 不重发，Run 挂在 `provider_outcome_unknown` 不恢复（环境因素 +
    既有 SDK 0.8 义务）。S5B-S1 主闸是 pytest 真实车道（已 ×2 PASS），S8/S7 由 UI-A 冷启动 PASS 覆盖；
    真实 UI 的里程碑补充证据待 provider 恢复后按新 `--workspace` 设置重跑。
  - **代码已变更 → r2 账本（已因并发写断链）无论如何都要作废**：待 provider 恢复、UI-B/UI-C 补齐后，
    在最终 HEAD 上 `init r3-s5b`（`related_run_dirs=[r1-s5b, r2-s5b]`，spec 已更新）全量重录 7 场景，
    r1/r2 均 `retire --superseded-by r3-s5b`。
- **修复的连带处理与自查（Host `0c907b04` → 空串收窄提交）**：
  - 全量回归在最终 HEAD 上先报 **9 红**（基线 7 红），两条增量均由本次改动引起且都已归零：
    ① `test_checked_manifest_is_canonical_and_current`——改了 `deskpet/tools/tool_search.py`，
    `core.tool_search.v1` / `core.tool_describe.v1` / `core.tool_activate.v1` 三个 handler 的
    `build_digest` 变化，按脚本 `--write` 重建 `execution_build_manifest.json`；语义 diff 已核对：
    72 个 handler 无增删、其余 69 个 digest 不变（commit `790dab64`）。
    ② `test_public_narration_prompt_matches_optional_tolerant_tool_schema`——原断言
    `deskpet_public_progress` 不在 `schema["required"]` 里，必填下沉后发布 schema 已无 `required`
    故 KeyError。改为断言发布 schema 无 `required`，并新增行为不变量测试（只给
    `deskpet_public_progress` 不给 `path` → 按缺 `path` 拒绝且处理器不被调用；给了 `path` 不给
    `deskpet_public_progress` → 正常放行）。不变量本身未变（commit `0c907b04`）。
  - **自查发现并修正一处自己引入的风险**：首版 `_missing_required_arguments` 把空串一并当缺参，
    会误拒 `write_file(content="")` 这类合法的「写空文件」请求。已收窄为**仅缺失或显式 `None`**
    才算缺参；各工具对空值的语义（如 `tool_search` 空 query 无意义）留在各自处理器。
    新增 `test_empty_string_is_a_valid_required_value` 锁住（`content=""` 放行并原样传到处理器，
    `content=None` 仍按缺参拒绝）。
  - Memory 仓库全量 **1113 passed / 8 skipped**（未受影响）。
- **最终 HEAD `674e00e3` 的验证结果**：Host 全量回归 **6451 passed / 恰好 7 条已知环境红 / 零意外**；
  Memory 全量 **1113 passed / 8 skipped**；真实 provider 里程碑 pytest 车道（S5B-S1 主闸）在该 HEAD 上
  **独立跑通 2 次**（transcript `run-1788400628.json` / `run-1788400690.json`）。
- **真实 UI 里程碑仍未闭环，但阻塞点已定性且设置已就绪**（证据 `20260903T1000-uiB`）：
  - 前几轮写不进 README 的根因**不是缺陷**，而是 S5b 的安全属性——`effect_gate_frozen_scope_mismatch`：
    Run 只能在准入时冻结的任务域/工作区内产生副作用，中途 `context_route` 不授予对另一任务域的权限；
    产品 UI 亦明示「项目只在新 Session 创建时绑定，之后不能改绑」。同一轮模型**终答如实告知失败**、
    未编造成功，属 negative-safety 正向证据。
  - 已改用产品自带的「添加项目 → 选择文件夹 → 注册为独立项目 → 创建项目 Session」完成绑定；
    纯浏览器通道缺原生文件夹选择器，故给 `tauri_shim.js` 增补 `open_directory_dialog`，
    返回值经 `shim_proxy.py --project-dir-file` 服务端注入（不进 URL/仓库）。
    绑定生效实证：项目会话里 `file_grep(README.md)` **succeeded**、`builtin:edit_file` 已激活。
  - 两次写入尝试均在落笔前被上游 **provider 60 秒 transport_timeout** 打断（Run 落
    `provider_outcome_unknown` 不恢复）。**环境阻塞**，通道与绑定设置已完全就绪，provider 稳定后可直接复跑。
- **下一步（待 provider 稳定）**：复跑 UI-B 拿到 README 1.1.3→1.2.0 的真实 UI 证据 + UI-C（≥20 turn）；
  然后在最终 HEAD 上 `init r3-s5b`（`related_run_dirs=[r1-s5b, r2-s5b]`，spec 已更新）全量重录 7 场景，
  r1/r2 `retire --superseded-by r3-s5b`；再走独立 full-audit → 文档回写 → re-attest → finalize。

## 2026-09-03 下午：/plan-test 续跑（phase-4）
- **独立代码审查（CODE_REVIEW 硬门，执行者不自审）**：对 `32d7849c..674e00e3` 派独立 challenger 审查，
  **VERDICT FAIL**（P0=0 / P1=4 / P2=4 / P3=6）。P1 全部闭环（commit `efbe201e` + `e2639f00`）：
  - **F-1**：我把 `required` 从发布 schema 摘掉，使 **66/77** 个工具对模型呈现为「全可选」，反而放大漏填
    概率，且属已批准的模型可见契约缩水 → **已还原**，`required` 重新对模型可见。
  - **F-2/F-3/F-4**：嵌套 required、类型/枚举/范围错、多余属性、动态 MCP 工具全都绕过了首版修复 →
    收口点下沉到 `ProductToolsAdapter.validate`（commit `64a8a30c`），本轮补齐覆盖测试。
  - **F-5/F-6（P2）**：新增日志用 `extra=` 传字段，本项目 structlog 的 `foreign_pre_chain` 没有
    `ExtraAdder`，字段在渲染阶段被**整体丢弃**；配套断言读的是渲染前的 LogRecord 属性，属**假绿** →
    字段改为拼进 message，断言改到渲染后的消息上。
  - 审查另给一条 WIP 预警（ContextVar 跨 context 删除不回写 → 长 Run 泄漏）→ 改为模块级有界表。
  - 受影响套件 **657 passed**；`test_every_manifest_required_argument_is_enforced_by_the_host_wrapper`
    把断言绑到真实工具清单，防止清单换源后必填静默消失。
- **真实 UI 复验（Host `e2639f00`）**：Run 以 `react_max_turns_exceeded` **干净收尾**而非 `driver_failed`；
  模型多次空参数调用全部得到指名道姓的 `missing_required_argument`，Run 每次存活。修复成立。
- **新发现 S5B-UI-F3（未修，移交 S5c/S6）**：委派类工具 `agent` / `agent_parallel` / `spawn_team` /
  `spawn_subagents` 在产品目录里注册的是占位处理器 `boundary_only`
  （`tools/code_tools/spawn_subagents_tool.py:69-70`，恒抛
  `RuntimeError("delegation tool escaped the ReAct ChildRun boundary")`），设计上应由 Harness 在
  ReAct ChildRun 边界拦截执行，但 SDK 前台 Run 路径上**没有被拦截** → 每次调用都是不透明
  `tool_handler_failed`，模型无从判断其不可用，持续重试直到轮次耗尽。与 S5B-UI-F1 同一缺陷类，
  但属委派子系统、超出本增量范围。
  **对验收的直接影响：S5B-S1 的真实 UI 里程碑因此拿不到**——模型首选委派路径，而委派在本通道恒失败。
- **当前判定：BLOCKED**（S5B-S1 的 UI 面缺正向价值样本）。已验证面：Host 全量 6451 passed / 恰好 7 条
  已知环境红、零意外；Memory 1113 passed；真实 provider 里程碑 pytest 车道在最终 HEAD 上独立跑通 2 次；
  UI-A 冷启动（S8 + S7 cold_start）在 `1c511a66` 上 PASS。
- **S5B-UI-F3 修复复验通过**（Host `620a6f18`，证据 `20260903T1300-uiB`）：模型只调用一次 `agent`，
  拿到稳定码 `delegation_unavailable` + 替代路径后**立刻改走** `tool_search → tool_describe(builtin:edit_file)
  → tool_activate`（成功），不再反复重试委派直到 `react_max_turns_exceeded`。
- **里程碑做不出来的根因查清：不是缺陷，是 UI 入口不存在**。模型激活 `edit_file`/`read_file` 后，
  `context_route` 以 `workspace_binding_current_run_authority_missing` 失败
  （`task_scope/runtime_binding_authority.py:288`，因 `foreground.current_snapshot` 返回 None）。链路核实：
  ① S5b 生产链由 `enqueue_turn` 驱动（`memory/human_memory_service.py:794`）；
  ② 其生产入口只有 WebSocket `human_memory_request` + `operation:"queue.enqueue"`
  （`memory/human_memory_api.py:207`，`main.py:14883`）；
  ③ 桌面 UI 普通聊天走 `chat_v2` **从不入队**，全仓 `after_enqueue` 只在 `main.py:11011` 启动恢复处调一次；
  ④ 前端**没有任何** `human_memory_request` / `queue.enqueue` 代码；
  ⑤ 4 个真实 UI run 的 `foreground_runs` 表全为 0 行。
  → 该 UI 入口属 **S6（全部 UI）**，而 S6 在本增量 plan/acceptance 里本就是范围外与停止追踪点；
  S5B-S1 当初标 `manual_required=是（真实桌面 chat UI）` 属起草时的范围错误。
- **A14 范围缩减（用户 2026-09-03 显式批准）**：原话「判定 UI 面移交下一切」，sha256
  `6086418dcc44ba2e7f4be13c9ced929cc7241f614cc16662bfa25e3fc3c2c41b`，原文存
  `verification/plan-challenge/user-approval-scope-reduction-2026-09-03.txt`。
  这是 plan-test DoD 允许的第二类合法出口（用户 chat 显式批准缩减 + 回写 acceptance + 结论按缩减后范围表述）。
  已回写：`acceptance.md` 新增「A14 范围缩减」节 + 场景矩阵行 + 适用性声明 + DoD 摘要第 1 条；
  Host `testcase/.../s5b-effect-closure-memory-verification-spec.json` 里 S5B-S1 的
  `ui`/`manual_required` 改 false、`required_artifact_kinds` 去掉 `ui-capture`、附 `scope_note`。
  **只缩两项**：S5B-S1 的真实桌面 UI 驱动面、≥20 turn 长上下文会话（均移交 S6，登记为 S6-OB-1/OB-2）。
  **业务判据一字未改**；S5B-S7 冷启动与 S5B-S8 真实 UI 通道两条 UI 面照旧 required 且已 PASS。
  **结论措辞纪律**：交付结论必须写明「真实桌面 UI 面移交 S6」，不得用 S7/S8 的 UI PASS 或 pytest 车道
  PASS 暗示 S5B-S1 的 UI 面已验证。
- **独立裁决回执（2026-09-03，裁决 D）**：同意「真实桌面 UI」这个**载体**要求属起草期范围错误、移交 S6
  （并复核出更硬的依据：S5B-S1 所需入口逐字就是 `slices/S6-ui-and-program-verification.md:16-17,29-40`
  的 Task 1/2 交付物，而 S6 UI 在本增量 plan/acceptance 里同时被列为范围外——**起草日即成立的自相矛盾**）。
  但**推翻了我 A14 初稿的两处过头**，已按裁决修正 acceptance 与验证规格：
  1. **不接受 pytest 里程碑车道作该 AC 主证据**——它替换了 `ProductForegroundToolPort.freeze`、
     `context_route → append_binding`、`ForegroundRuntimeExecutionAuthority` 等多处生产接缝
     （`s5b_milestone_harness.py:83-89`、`s5b_effect_gate_harness.py:473-490`），
     S5B-UI-F1 正是由此漏检（本增量 `notes-investigation-task7b.md` 已自述该盲区）。
  2. **实质要求不降级**：缩的只是「真人点击」载体，改由**唯一现存生产入口**兑现——对真实运行后端经
     控制 WebSocket 发 `human_memory_request` / `queue.enqueue`（未来 S6 按钮必然调用的同一段代码），
     自然用户语言 + 真实 provider + 真实文件 diff + 人工核对。**补不上则本增量退化为 BLOCKED。**
- **OBL-2 已实测证实（P0，归属本增量而非 S6）**：新增决定性测试
  `backend/tests/sdk_adapters/test_chat_session_project_effect_reachability.py`（Host `e391da93`），
  在**生产装配**（真实 `WorkspaceBindingRuntimeAuthority` + 真实 `ForegroundQueueStore` + 真实 state.db，
  零替身授权）下证实：无前台 Run 时 `append_binding` 抛 `workspace_binding_current_run_authority_missing`；
  对照组走生产 `enqueue_turn` 拿到前台 Run 后前置条件满足。即失败成因精确落在
  **「桌面聊天会话没有前台 Run」**，与 8 次真实 UI 实测一致。
  **定性**：acceptance AC-3④ 预设的产品行为（普通聊天 Run 先建 TaskScope、下一轮写入）在本增量实现下
  不可达，且与 `BEHAVIOR_POLICY = preserve-approved` 冲突（写文件是已交付能力）→ **不得推给 S6**。
  两条出路（① 让 `_append_auto` 接受非前台 Run 的准入权威；② 明确「桌面聊天在 S6 前不提供项目写入」
  并作为已批准行为的显式缩减入账，需用户批准）属技术选型，**需另开独立裁决**。
- **OBL-1 → S6**、**OBL-3 → 本增量 retro**（起草检查表缺「入口可达性」一问）已一并写入 acceptance A14 节。
- **当前判定：BLOCKED**，卡点两条：① OBL-2 这个 P0 未定出路；② S5B-S1 缺「生产 WS 入口」的正向价值样本。
- **用户 2026-09-03 决定并已实施：AUTO 模式下 Agent 自建任务目录并绑定，非 AUTO 弹窗确认**
  （原话「这个改成让Agent自己按照任务在制定的workspace里面建立目录，在auto模式下agent不需要用户授权，
  非auto模式下则需要弹出弹窗，让用户同意」）。Host commit `1206929d`：
  ① `_append_auto` 在没有前台 Run 时走 pre-admission bootstrap——合成确定性
  `CurrentRunBindingAuthority` 登记在 `_pre_admission` 表，store 的
  `_verify_current_run_authority` 仍逐字段核对身份与血缘（校验不放宽，只承认「还没有前台 Run」
  这一合法状态），用完即清；② `append_binding` 入口先 `_ensure_task_directory`，只在既定
  workspace root 的真实后代位置建目录（`canonical_workspace_root` 用 `resolve(strict=True)`，
  目录不存在就绑不了）；③ 非 AUTO 路径完全不变，仍走 `propose_manual_binding` 弹窗。
  决定性测试：无前台 Run 时绑定成功且目录被建出、revision≥1；workspace 之外的根照旧拒绝且不建目录。
  受影响套件 **557 passed**。
- **生产入口车道进展（`.local-test-evidence/real-ui-channel/20260903T16{20,40}-wsentry`）**：
  新增 `tools/production_entry_run.py`，对**真实运行后端**经控制 WebSocket 依次发
  `primary.open → task_scope.create → binding.append → queue.enqueue`（与将来 S6 按钮同一段代码）。
  死锁解开后 **前四步全部成功**（binding `status=bound`、`binding_set_revision=1`）。
- **暴露前台链第二个缺口（S5B-P0-2，未修）**：前台 Run 起不来，`foreground.runtime.failed`
  错误码 `conversation_entrypoint_required`。根因：冻结 SDK `runtime/kernel.py:729-733` 规定
  启用 Agent Memory 时 `start()` 必须带 `conversation`，而
  `execution/foreground_runtime.py:821-830` 调 `self._ingress.start(...)` 时**没有传 conversation**
  （`sdk_adapters/ingress.py:130` 的 `conversation is not None` 分支因此永不进入）。
  已先 `primary.open` 建出主对话（`primary_ref` 返回）仍无用——前台运行时根本没把它传下去。
  → S5b 的前台执行链在生产上**从未真正启动过一个 SDK Run**；pytest 车道用基座自建 runtime，绕过了这里。
- **前台链缺口二已修（Host `5cba5e9e`）**：`ForegroundRuntimeExecutionAuthority` 新增可选
  `conversation_entrypoint` 构造器并在 `ingress.start` 前传入；`main.py` 用与 chat 路径
  （`:10409`/`:10475`）同一套 `memory_identity_authority` + `sdk_context_source_repository` 实现。
  未接线时保持 None，既有测试基座行为不变。sdk_adapters+faults **460 passed**。
  实测（`20260903T1700-wsentry`）：`conversation_entrypoint_required` 消失，换成下一个错误。
- **暴露前台链缺口三（S5B-P0-3，未修）**：`foreground.runtime.failed` /
  `IntegrityError` / FOREIGN KEY constraint failed。根因：`memory/identity.py:76-79` 的
  `memory_session_identities.session_id` 有 `REFERENCES sessions(id)` 外键，而前台链传给
  身份绑定的是 `foreground_runtime.py:207-209` 从 host_run_id 派生的
  `foreground-execution-<sha256>`，**该 id 不在 `sessions` 表里**；主对话 id
  （`4d5a6efc…`）同样不在。即前台 Run 没有可用于 Memory 身份绑定的真实会话行。
  → 需要决定前台 Run 的会话身份口径（复用主对话并为其建 sessions 行 / 放宽该外键 /
  由前台链自建执行会话行），属架构取舍。
- **可观测性顺带修复**：`_run_driver` 的失败审计此前只记 `error_code`，SQLite 异常退化成
  一个类名。已追加 `error_type` / `error_detail`（截断，只进 Host 日志）。
  另记一个日志脱敏误报：`TraceRedactor` 把 "FOREIGN KEY constraint failed" 里的 KEY 当敏感词，
  实测输出为 `FOREIGN [REDACTED]`——排障时会误导，建议收窄该规则（S6 候选）。

## 2026-09-03 下午：前台链一次性排障，生产入口首次跑通业务动作
- 用户要求「先把整条链的断点一次查清再动手」。派独立调查员做**基座 vs 生产装配**逐处比对
  （16 条接缝清单），同时用临时探针把链路往下推。据此一次性修掉 **6 个既有缺陷**：
  | # | 缺陷 | commit |
  |---|---|---|
  | 1 | 首次 workspace binding 死锁（绑定要 Run、Run 要绑定） | `1206929d` |
  | 2 | `ingress.start` 不传 conversation → `conversation_entrypoint_required` | `5cba5e9e` |
  | 3 | 派生执行会话缺 `sessions` 行 → Memory 身份绑定外键失败 | `1d9e5596` |
  | 4 | context source 载荷缺 `provider_messages` → Run 起不来 | `1c5c8cc8` |
  | 5 | Host 首轮路由回执不落账 → 首轮永远无活跃任务域，模型连挂 10 次 | `b08924d6` |
  | 6 | `edit_file` 拒绝不透明 + 相对路径按**进程 cwd** 解析（真实原因是文件找不到） | `26e6c1fb` |
  这些全部是**既有缺陷**，最早可追到项目初始提交；能一直藏着是因为**整个前台执行流程在 pytest 里
  零覆盖**——基座手工按序调七八个方法推进任务，`_drive_claimed` 全流程一步没走。
- **生产入口首次跑通业务动作**（证据 `real-ui-channel/prod-lane-04`，另 probe-10 / prod-lane-02
  独立复现，共 3 次）：真实 provider 经 `queue.enqueue` 把 README `1.1.3 → 1.2.0` 真实写入；
  **语义收口回执 1 条 `outcome=mutate`**；客观事件 38 条；SDK Run 终态 `completed`；
  路由账本 1 行 `resume_existing / host_initial`。
- **仍缺最后一环（断点 9，未修）**：`memory_ingestion_outbox` 0 行、`cognitive_memory_heads` 0 行。
  定位：前台回合停在 `CLAIMED`，**终态提交未执行**（`foreground.runtime` 日志只到 `bound`，
  无 `closure_settled` / `record_sdk_terminal`），而 outbox 行正是在终态提交事务里写
  （`foreground_queue.py:2026-2027`）。即驱动循环在 SDK Run 已 `completed` 后卡在
  `foreground_runtime.py:1189` 的 `self._terminal.observe`。
- **全量回归**（Host `26e6c1fb`）：`6458 passed`，8 红 = 7 条已知环境红 + manifest 过期
  （已随 edit_file 改动重建并提交）。
- **断点 9 已修（`34ea5274`）**：前台驱动在观察到 `BOUND_WAITING`（等用户授权）后 return，
  而它只被 `after_enqueue` / `after_control` 唤醒——**`after_control` 在生产上零调用者**
  （全仓只有 `tests/execution/test_foreground_runtime.py` 调）。用户批准后没有任何东西叫醒驱动，
  SDK Run 跑完了前台回合却永远停在 CLAIMED，终态提交不执行，而 Memory ingestion outbox 行
  正写在终态事务里。修复：`_signal_product_harness_decision` 在决策落地后调
  `after_control`；唤醒失败只记 warning，不影响决策落地。
- **S5B-S1 全链闭环 PASS，≥2 独立 root run**（满足 acceptance `min_root_runs=2`）：
  | root | 证据 | 指令 | 结果 |
  |---|---|---|---|
  | 1 | `real-ui-channel/prod-lane-05` | 「把项目里 README.md 的版本号从 1.1.3 改成 1.2.0…」 | 全链 PASS |
  | 2 | `real-ui-channel/prod-lane-08` | 「请把项目 README.md 里的版本号更新到 1.2.0…」 | 全链 PASS |

  每次均：README `1.1.3→1.2.0` 真实写入 → 客观事件（39/41 行）→ 语义收口回执 1 行
  `outcome=mutate` → 前台回合 **SETTLED** → `memory_ingestion_outbox` 1 行 +
  `memory_ingestion_evidence_links` 1 行 → `cognitive_memory_heads` 1 行（episode）。
  驱动入口 = 生产 `queue.enqueue`（与将来 S6 界面按钮同一段代码），真实 provider gpt-5.6-luna，
  自然用户语言，AUTO 模式下 Agent 在既定 workspace 自建并绑定任务目录。
- **本轮共修 7 个既有缺陷**（`1206929d` / `5cba5e9e` / `1d9e5596` / `1c5c8cc8` / `b08924d6` /
  `26e6c1fb` / `34ea5274`），全部因「前台执行流程在 pytest 里零覆盖」而长期潜伏。
