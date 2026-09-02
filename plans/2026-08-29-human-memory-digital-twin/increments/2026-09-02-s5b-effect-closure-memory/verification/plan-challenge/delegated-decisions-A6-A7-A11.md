# 委托裁决：A6 / A7 / A11（独立审核代理，2026-09-02）

> 性质：用户已批准 S5b acceptance 与修订提案 A1–A13，并把其中三项"需用户裁决"的范围解释委托给独立审核代理裁决（用户原话："我不知道要决策什么…你让一个子代理审核吧"）。本文只做裁决与措辞，不改仓库任何既有文件；由主 agent 合并进 `acceptance.md` 并以 `record-challenge-control --action scope-change-approved` 入账（approval hash 取用户委托原话 + 本文 sha256）。
> 依据（只读核对）：本增量 `acceptance.md` / `acceptance-amendments-proposed.md` / `plan.md` / `assurance-contract.json`、challenge finding `tc-hm-09-multi-root-canary-vs-oos-and-d2-wording`、`prospective-processed-definition-acceptance-wording`、`release-unit-third-subsystem-packing` 及 synthesis decisions；program `acceptance.md`（HM-AC-3/4/5、HM-S4/S9、HM-TO-A3/A5/R8、"不能一次修改超过三个高风险子系统后再统一测试"）、`slices/S5-*.md`、`slices/S6-*.md`；冻结 oracle `TC-HM-09` rev4、`TC-HM-04` rev3；plan-test `config.md` `RELEASE_UNIT_LIMITS`、`policies/acceptance-preserving-ponytail.md`；S5a acceptance S5A-AC-4（mandatory inbox reconcile 谓词）。

## 背景

S5b 把 S5 slice 的 Task 5/6/7 打包成一个增量：① workspace effect gate、② TaskScope 语义收口/终态门、③ Host↔Memory 异步面（终态 outbox + 主模型 analysis executor + Memory 0.6.1 上游发布 + Prospective 唯一 scheduler + 即时 remember/correct/forget）。challenge 收敛后有三处无法由 challenger 单方面决定：D5 release unit 是否拆分（A11）；冻结 oracle TC-HM-09 步骤 6 的多 root canary 与本增量 assurance contract `OOS-MULTI-ROOT-SELECTION`、SDK 0.7.1 冻结的正面冲突（A6）；AC-4③⑤ 用"模型终答是否提及"定义 processed，与 program 禁止 NL/关键词判断冲突（A7）。裁决原则沿用 `acceptance-preserving-ponytail.md`："已批准验收是地板，不得削减 MUST AC、assurance 必要控制、冻结 oracle"；冻结 oracle 只能以绑定 exact old/new + 用户消息 hash + scope/expiry 的 `behavior_changes` artifact 解释，且**不许在失败后把 expected result 改成实现结果**（本文三项裁决全部在实现开始前做出）。

## 裁决一：A11 —— D5 release unit：**拆分**，AC-4 + AC-5 移入 S5c

**结论**：采纳备选方案（Ponytail 选项 B）。S5b 保留 AC-1/2/3/6（Task 0,1,2,3,4a,4,5,8,8b,9 = 10 个任务，MUST AC = 4，高风险子系统 = 3），AC-4（Prospective scheduler/occurrence/`prospective_ack`）+ AC-5（即时 remember/correct/forget）连同 Task 6/7、`prospective-occurrence` fault lane、S5B-S5/S6 真实车道、prospective 三张 v46 表移入独立增量 **S5c**，排在 S6 之前。

**理由**（三句）：
1. 数字上已经超限：`config.md RELEASE_UNIT_LIMITS` 规定 Task ≤ 10，plan.md Task 0 自报 `check-release-unit`（Task = 12：0,1,2,3,4a,4,5,6,7,8,8b,9），只能靠 manifest `thresholds` 覆盖过门，而覆盖"须用户知情"——用户已把知情裁决委托给本审核，本审核不接受为了保单增量而放宽门限（config 原文："不许为卡数字压缩文字"，反向亦然）。
2. 高风险子系统 = 3 是靠打包得到的：Prospective scheduler 是独立跨库状态机（Host state.db ↔ Memory outbox/inbox，四个 kill 点、独占 fault lane、确定性 signal 身份回签），与 outbox+analysis executor 没有共享事务边界；诚实计数为 4，正好触发 program acceptance.md:57-58 "不能一次修改超过三个高风险子系统后再统一测试"。即时操作（AC-5）体量小但依赖 `prospective_ack`/`memory_action_authority` 同一批 composition 注入与同一 v46 表族，随 AC-4 一起走最省。
3. 拆分不伤价值里程碑也不伤 S6：最小验证动作（改 README → 客观事件 → closure → 同事务 outbox → analysis 物化 → 下一轮召回）完全在 AC-1/2 内，"矛盾主要方面"（终态门跑通可重放）不依赖 Prospective/即时操作（acceptance 自述"是价值成立之后的事"）；S6 program 验收依赖三链齐全，S5c 在 S6 之前完成即可，顺序 S5b → S5c → S6 不改 S6 任何前置。代价是多一次 gate 仪式，但 S5c 复用 S5b 已建的 0.6.1 wheel、四 lane runner 骨架、Task 8b 真实桌面通道，仪式规模远小于把 6 条 MUST AC 在 Task 9 一次统一验收后 finalize 失败重跑的代价。

**对 program 承诺的影响**：HM-AC-5（Prospective/Procedure 一等能力）与 HM-S4、HM-S7、HM-TO-A5 的兑现时点从 S5b 顺延到 S5c，program 收口（S6）时点不变；HM-AC-3/HM-AC-2/HM-TO-R8 由 S5b 兑现不变。program 级承诺零削减，只是分两次验收。

**拆分后的边界不变量（必须写进 S5b 验收，防止"拆了之后半悬空"）**：
- S5b 的 analysis 可能产出 Prospective 意图 → Memory 会写 `memory.prospective.registration.requested` outbox 行。S5b 断言：这些行 durable 保留、state 保持 pending、Host 无游标、零 dead-letter；意图因无 `REGISTRATION_ACCEPTED` 保持 `registration_not_live`，TIME_DUE/EVENT 不可能触发 → Memory inbox 恒空 → S5a `no_recall` 门谓词真空成立（与 S5A-AC-4 边界声明同构）。S5c 从游标原点消费这些行。
- `memory_write`/`memory_forget` 在 S5b 保持现状（返回稳定 `memory_sdk_unavailable`，S5a 既有行为，非 Noop/fake 静默降级）；S5b AC-6① 注入清单剔除 `prospective_signal_authority`、`memory_action_authority` 两项，S5c 的 AC-6′ 补回并沿用"缺件 startup fail"。
- v46 只含 S5b 用到的表（closure/reservation/outbox/attempt/effect_gate_rejections/pre_admission_audit）；`prospective_scheduler_registrations`/`prospective_outbox_cursor`/`prospective_occurrences` 进 S5c 的 v47（append-only 迁移链继续）。Ponytail：不为将来预留空表。
- Memory 0.6.1 cutover receipt 留在 S5b Task 5；S5c 默认零 Memory wheel 改动（A8 已把递归意图按一次性到期处理、留 backlog）。若 S5c 发现必须改 wheel，则另出 0.6.2 并在 S5c acceptance 显式记录。

## 裁决二：A6 —— TC-HM-09 步骤 6 多根 canary 口径：**采纳单根 scope 解释 + strict**

**结论**：(a) S5B-S4 以"每个 canary root 一个单 root scope"执行步骤 6，并**追加**断言多 root（≥2）scope 的项目 effect 稳定 fail-closed；(b) Run 内任何 binding 追加（Manual 或 Auto）之后 head ≠ receipt.revision → 该 Run 后续项目 effect 一律 `workspace_binding_receipt_superseded`（strict），sticky 到下一个 Run 的 `context_route` 刷新；(c) 以 verification-spec oracle 解释 + `behavior_changes` artifact 入账，TC-HM-09 文件不改。

**是否忠于冻结 oracle 与 OOS-MULTI-ROOT-SELECTION**：忠于。步骤 6 的 expected result 是"每个 effect envelope 绑定 exact task_scope_id、root ref 和当时 revision；无可信 binding 的路径零写入"——单根 scope 逐个跑 canary 时这两句字面成立，且每个 canary 都在自己的 scope/root/revision 下留 hash；多 root scope 下"零写入"恰是 OOS 要求的 fail-closed，作为追加断言只会更严不会更松。真正被改变的只是 fixture 拓扑（把"一个三根 scope"换成"三个单根 scope + 一个多根 scope 负例"），而不是 expected result；改变的原因是本增量 assurance contract 显式 OOS（多 root selection 协议）与冻结 SDK（`foreground_runtime_ports.py:332-341` 让 ≥2 root scope 整 Run projectless），不是实现跑失败后改口径。program 层面：HM-AC-3 承诺的是"多根**绑定**与 per-effect envelope"，HM-S9/HM-TO-A3 断言的是绑定权限（Manual/Auto/拒绝类），均不要求"在同一 scope 的多个 root 上执行 effect"；步骤 3/4（追加 revision、旧 root 不被替换）仍在同一个多根 scope 上原样执行。

**strict 而非 exact 的理由**：① `ASSET-WORKSPACE-AUTHORITY` 原文"binding revision 等于 receipt"，exact 会让"receipt 不可解析"成为空集（revision 是不可变行，永远可解析），"stale" 就失去定义；② 追加第二 root 之后该 scope 在所有后续 Run 已经是 projectless（OOS），exact 会制造唯一一个"多根 scope 仍在执行写入"的窗口——正是 OOS 想封死的东西；③ 不分 Manual/Auto 用同一条规则（head ≠ receipt），reason code 单一、无模式分支；Auto append 在 exact 下同样写不到新 root（envelope 只解析 receipt 内的恰一 root），所以 strict 的实际代价只是"追加当轮对旧 root 的剩余写入"，可接受。

**必须同时向用户说清的既有后果（写进 D2）**：追加第二个 root 之后，该 scope 的项目 effect 在多 root 选择协议落地前持续 fail-closed（S4 既有行为 + 本增量 OOS）；用户若要继续在某个目录干活，需要在只绑定该目录的 scope 里干（或在 S6/后续增量落地选择协议后）。这不是 S5b 新引入的限制，但 S5b 第一次让写工具真的能执行，用户会第一次感知到它。

**对 program 承诺的影响**：program 级残留一个显式 gap——"多根 scope 内的 root 选择与逐根 effect"（已在 plan 停止追踪点与 assurance OOS），S6 program 验收时 TC-HM-09 步骤 6 只能按本解释 PASS。硬约束：`behavior_changes` artifact 必须在 S5b Task 0（实现前）写入 verification-spec 并进入 V0 sealed lineage，scope = S5b/S5c/S6，expiry = "多 root 选择协议被独立验收之日"；否则 S6 Task 5"只执行 V0 sealed inventory，不新增/重标 required case"会把步骤 6 判 BLOCKED。

## 裁决三：A7 —— Prospective "已处理"定义：**采纳 ack 凭证定义 + 有界重现规则**

**结论**：processed := 该 `occurrence_key` 存在 durable `prospective_ack` receipt（Host 工具，strict schema，key ∈ 本 principal 的 presented 集合，五路可见；receipt 以 `(sdk_run_id, occurrence_key)` 幂等，lost-ACK 重放返回同一 receipt）。模型未调用/拒绝/timeout/Run 失败 → 不 processed，occurrence 保持 presented，下一 Run 继续注入，`no_recall` 继续被拒。"终答提及"只作 S5B-S5 真实车道的 quality_bar 人工检查，不进机器门。

**一致性核对**：
- program"所有模型/工具/文件/测试事实由 Host 不经 LLM 追加…不用正则或后台总结模型"：ack 是模型显式工具调用形成的 Host 事实，与 `task_scope_update` 同构；不解析终答文本。
- HM-AC-5"SDK 可靠地产生触发候选及状态审计，但不越权执行"：`prospective_ack` 零外部动作，只改 occurrence 状态并留审计；模型只能回显 Host 放进 inbox 的 64-hex key，无法凭空 ack 未呈现的 occurrence。
- TC-HM-04 步骤 4"只产生一个 occurrence；pending→triggered/settled；pending 不丢"：Host 侧 settled(acknowledged) 由 ack 轮终态提交驱动（或下一个观察到 acknowledged 行的终态），Memory 侧 triggered→completed 只由 ack 轮的 analysis `MemoryMutationPlan` 产生（`llm_payload_driven`，经 Memory transition 表校验）；"pending 不丢"要求 Host **不得静默过期**（见下）。
- HM-S4 期望"意图 pending；SDK 只产触发候选"：不变。

**有界重现规则（裁决：按身份有界、按时间无界、不静默过期、有确定性升级信号）**：
1. 呈现幂等：同一 `(occurrence_key, sdk_run_id)` 至多一条 presented 记录（snapshot receipt 同事务）；同 Run 内 crash/replay 不产生第二次呈现；不同 Run 才计新一次呈现。`presented_count` durable 单调。
2. 无静默过期：Host 永不因"呈现了 N 次没人 ack"把 occurrence settle 掉。唯一出口：模型 `prospective_ack`（acknowledged）；用户显式 forget/suppress（`memory_forget` → suppression → settled(suppressed)，内容零进 Context）；Memory 生命周期退出（cancelled/expired/completed/superseded，由 tick 从 inbox/outbox 事实派生为 settled(superseded|expired)）。
3. 确定性升级信号：`presented_count ≥ 3`（N 在 v46/v47 设计冻结固定）时，inbox 消息带 `overdue=true` 布尔字段并追加恰一条 append-only `prospective_ack_overdue` 审计事件；occurrence 仍 mandatory（no_recall 仍被拒——program plan.md:102-103 口径）。不引入新表、不改门谓词。
4. 必测（deterministic 子 lane）：模型连续 3 个 Run 不 ack → 3 条 presented 记录、同一 occurrence_key、零重复 occurrence、overdue 事件恰一条、意图仍 pending；第 4 Run ack → acknowledged → 终态 settled(acknowledged)；ack 重放同 receipt；ack 一个未呈现/他人 key → 稳定拒绝零状态变化；用户 forget → settled(suppressed) 且六路普通读取不可见。

**对 program 承诺的影响**：HM-AC-5/HM-S4 的兑现方式从"终答提及"（不可确定性验证）改为"结构化 ack 凭证"（可验证、可重放），是对承诺的**加严**而非放宽；用户可感知差异：AI 要明确"确认收到提醒"（工具调用），没确认下次还提醒，用户可随时说"忘掉这个提醒"关掉。随 A11 一并移入 S5c 验收。

## 最终措辞表（合并进 acceptance.md 的替换文本）

| 条款 | 最终措辞 |
|---|---|
| D5（替换全文） | **Release unit（用户委托裁决，2026-09-02）**：S5b = S5B-AC-1/2/3/6，高风险子系统 ① workspace effect authority ② TaskScope closure/终态门 ③ Host↔Memory 终态 outbox + 主模型 analysis executor + Memory 0.6.1 cutover，计 3；Task 0,1,2,3,4a,4,5,8,8b,9 共 10。**S5B-AC-4 与 S5B-AC-5 移入独立增量 S5c**（Prospective 唯一 scheduler/occurrence/`prospective_ack`、即时 remember/correct/forget、`prospective_signal_authority` 与 `memory_action_authority` 注入、v47 prospective 三表、`prospective-occurrence` fault lane、S5B-S5/S6 真实车道、S5B-S7 的 memory tool 载荷变异），措辞按 A7/A8 修订后原样带入 S5c acceptance；S5c 在 S6 之前完成，S6 program 验收前三链齐全的前置不变。S5b 边界不变量：analysis 产出的 Memory prospective registration outbox 行 durable 保留（state=pending、Host 无游标、零 dead-letter、意图 `registration_not_live`、inbox 恒空、no_recall 门不受影响）；`memory_write/forget` 维持 S5a 稳定 `memory_sdk_unavailable`。 |
| S5B-AC-4 / S5B-AC-5 行 | 状态列改为"**移交 S5c**（本增量不验收、不计 MUST）"；场景矩阵 S5B-S5、S5B-S6 同步移交；S5B-S7 保留 `task_scope_update`/analysis result 变异，memory tool 载荷变异移交。 |
| S5B-AC-6① | 注入清单：root_resolver、closure authority、Memory analysis executor + delivery authority、Host `evidence_authority`、`register_principal_owner` 首次幂等调用、ingestion outbox/job worker；逐项移除任一 → startup stable fail（禁 Noop/fake）。`prospective_signal_authority`、`memory_action_authority` 移 S5c。 |
| S5B-AC-6② | v46 迁移只含 closure/reservation/outbox/attempt/effect_gate_rejections/pre_admission_audit 表；prospective 表族属 S5c v47。 |
| S5B-AC-3⑥（替换"逐 root canary envelope"） | 验证 HM-S9（TC-HM-09 步骤 3–6）：步骤 3/4 在同一 scope 上执行 Manual/Auto 追加（新 revision、旧 root 不替换）；**步骤 6 以每个 canary root 一个单 root scope 执行**，每个 canary envelope 绑定 exact task_scope_id、root ref、当时 revision 并留逐 root hash；**追加断言**：≥2 root scope 的写工具不出现在 snapshot tools，强制调用 → durable FAILED + 稳定码（`catalog_execution_policy_unavailable` / `sdk_task_execution_root_authority_ambiguous`），两根 canary hash 均不变（OOS-MULTI-ROOT-SELECTION）。Run 内任何 binding 追加后 head ≠ receipt.revision → 后续项目 effect `workspace_binding_receipt_superseded`（strict，Manual/Auto 同一规则），sticky 至下一 Run `context_route` 刷新。以 verification-spec oracle 解释 + `behavior_changes`（exact old/new、用户委托消息 hash、scope=S5b/S5c/S6、expiry=多 root 选择协议独立验收之日）入账，TC-HM-09 文件不改；artifact 在 Task 0 写入并进 V0 sealed lineage。 |
| D2（在 A4 修订文之后追加一句） | 追加第二个 root 之后，该 scope 的项目 effect 在多 root 选择协议落地前持续 fail-closed（S4 既有行为，本增量 OOS）；要继续在某目录写入，须使用只绑定该目录的 scope。 |
| S5B-AC-4③⑤（带入 S5c） | ③ occurrence 状态 `claimed→presented→acknowledged→settled(acknowledged|suppressed|superseded|expired)` 与游标分离；**processed := 该 occurrence_key 存在 durable `prospective_ack` receipt**（Host 工具、strict schema、key ∈ 本 principal presented 集合、五路可见、`(sdk_run_id, occurrence_key)` 幂等重放同 receipt）；模型未调用/拒绝/timeout/Run 失败 → 不 processed，occurrence 保持 presented，下一 Run 继续注入且 no_recall 继续被拒；`occurrence_presented` 投影只在 occurrence 离开 mandatory inbox 时写入；suppressed/FORGOTTEN settle 为 suppressed，内容零进入 Context。**有界重现**：同 `(occurrence_key, sdk_run_id)` 至多一次呈现，`presented_count` durable；Host 不静默过期，出口仅 ack / 用户 forget-suppress / Memory 生命周期退出；`presented_count ≥ 3` → inbox 消息 `overdue=true` + 恰一条 append-only `prospective_ack_overdue` 事件，occurrence 仍 mandatory。⑤ 真实 provider："发布成功以后提醒我更新变更日志" → 注册 → 触发 → 下一轮 no_recall 被拒且 summary 进 snapshot → 模型调用 `prospective_ack` → acknowledged → 终态 settled(acknowledged)；终答提及提醒只作 quality_bar 人工检查。deterministic 子 lane 必含：连续 3 Run 不 ack（3 条 presented、零重复 occurrence、overdue 恰一、仍 pending）→ 第 4 Run ack → ack 重放同 receipt → 未呈现/他人 key 稳定拒绝 → forget 后六路不可见。 |
| Task 0 `check-release-unit` | MUST AC = 4、Task = 10、高风险 = 3、plan 行数照实；不覆盖 `thresholds`。 |
| Task 9 验收 lane 顺序 | effect/closure → memory analysis 两链先后 record-run；Prospective/即时链归 S5c。 |

## 风险与回退

**风险**：拆分后 S5b 与 S5c 之间的接口（prospective outbox 行 pending 不消费、`memory_*` 维持 stub）在 S5b 真实车道里会被用户/模型第一次感知（"记住 X"暂时报 unavailable、提醒暂不生效），以及 A6 的 `behavior_changes` artifact 若未在 Task 0 进入 sealed lineage，S6 会把 TC-HM-09 步骤 6 判 BLOCKED。
**回退**：三项裁决均可在 S5c 立项前由用户一句话推翻——A11 回退为单增量只需把 Task 6/7 与 AC-4/5 合回并接受 manifest `thresholds` 覆盖（须用户知情入账）；A6 的 strict→exact 只是 effect gate 一条 reason-code 分支；A7 的 N=3 升级信号可删（其余定义不动），任何回退都不触碰已批准的 MUST AC 地板。
