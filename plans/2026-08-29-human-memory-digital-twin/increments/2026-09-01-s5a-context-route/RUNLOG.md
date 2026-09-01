# RUNLOG — S5a context-route（phase-3 执行）

- 2026-09-01 用户批准 acceptance+plan（含 program 102-103 收窄解释声明、叠 fix 分支基线、provider 配置义务）。
- **执行模式自决（留痕）**：集中兵力串行。理由：Task 0→1→2 是里程碑最短链路且共享 main.py/sdk_adapters 文件簇（强顺序依赖）；Task 3 虽在 Memory 仓独立，但非里程碑依赖，按"里程碑之前只做直接依赖"排后。
- Host 工作分支：`feat/human-memory-s5a-context-route`（自 fix/human-memory-runtime-p1-closure @ c9f73349）。
- Release Unit 体检：MUST AC=7(≤8)、任务=7(≤10)、plan 行数<2000、高风险子系统=3（Host sdk_adapters/execution、Host memory ledger、memory-sdk 消费面）——通过。
- provider 配置：用户批准时未提供 → 按 Task 0 检查点记 BLOCKED 风险，deterministic 先行；里程碑 demo 时再次请求。

## Task 0 完成（2026-09-01）
- 基线复验：Host `tests/execution tests/sdk_adapters` 329 passed（29s）@ feat/human-memory-s5a-context-route（基于 c9f73349 = S4 receipt dbaeaae7 全量绿锚点，零代码差异）。
- oracle 冻结：`testcase/human-memory-program/s5a-context-route-verification-spec.json`（S5A-S1..S6 → TC-HM-01/02/10/11 映射 + 中间态声明）+ reuse-report；Host commit f844d631。
- DisclosureContext 参数面核对：human_memory_service.py:1649-1662 样板完整（USER_SELF/TASK_EXECUTION/AUTHENTICATED_HOST/TRUSTED_AUTHORITY/CURRENT + MINIMUM_NECESSARY），chat lane 复用同构造。
- provider 配置：未提供 → BLOCKED 风险在案，deterministic 先行。

## Task 1 设计（v45 逻辑表，写 SQL 前冻结）
1. `context_route_decisions`（append-only）：decision_id PK、host_run_id、sdk_run_id、provider_turn_ordinal、route、origin、task_scope_id?、binding_set_revision?、binding_set_receipt_id/hash?、recall_refs_json、receipt_id UNIQUE、receipt_hash、raw_call_id?、effect_id?、request_fingerprint?、created_at。
2. `run_context_snapshot_receipts`（append-only）：snapshot_id PK、host_run_id、sdk_run_id、provider_turn_ordinal、prior_context_revision、snapshot_revision、source_revisions_json、payload_hash、expected_request_fingerprint、created_at；UNIQUE(host_run_id, provider_turn_ordinal, snapshot_revision)；revision 单调由写入时 head 查询保证。
3. `context_route_tool_invocations`（血缘）：invocation_id PK、host_run_id、raw_call_id、effect_id、proposal_hash、verdict、decision_id?、created_at；UNIQUE(host_run_id, effect_id) 幂等。
4. `occurrence_presented`（S5a 零写入）：occurrence_key TEXT PK、memory_id、prospective_revision、presented_at?、presented_run_id?、settled_at?、settled_reason?；CHECK 单向（settled 必先 presented）。

## Task 1 完成（2026-09-01，Host commits 0f563306 + 0c900c35）
- v45 migration 037：4 张 ledger 表 + occurrence_presented（全列、S5a 零写入、monotonic guard 触发器）；migrator 三件套登记 + recovery taxonomy A；fresh init→45、reopen 幂等、append-only/monotonic/settled-pair 触发器实测全绿。目标版本 44→45 带来的 8 处测试硬编码改为 HUMAN_MEMORY_TARGET_SCHEMA_VERSION 常量（oracle 语义不变：future 样例改 target+1）。
- 三 authority：ProductRunContextAuthority（镜像 react_loop 裸路径材料——context port messages/exposure provider_specs/start input 采样参数/空 metadata，行为不缩水；ledger 分配 snapshot_revision 单调 + replay 幂等；payload_hash==expected fingerprint 自检 fail-closed）；ProductRuntimeDecisionSink（DIRECT_STANDALONE + 空 recall_refs + durable origin=no_recall decision，幂等 + immutable 冲突拒绝）；ProductTaskExecutionAuthority（9 项身份回声；PROJECT_EFFECT 无 route/root → 稳定 fail-closed，生产 catalog 零 PROJECT_EFFECT 工具为已核事实，root resolver 端口留 Task 2 接线）。
- main.py 注册三 slot + 前提缺失 startup stable fail（_build_product_sdk_runtime_stack 内 raise → product_sdk_runtime_skipped，SDK 链不静默降级）+ exhaustiveness 断言 + ledger verify_schema（db 存在而 <45 → fail）。
- 测试：新增 8 black-box（三 hash/单调/replay/漂移拒绝/采样镜像/no-recall durable/envelope 回声/双 fail-closed/旧库 verify）；回归 337 passed（sdk_adapters+execution）；ruff 清；mypy 新增 0（context_authority.py 基线既有 32 保持不变）。
- 关键发现（已记 notes-host-wiring.md）：当前生产 SDK 0.7.1 链 authority proxy 恒非 None ⇒ 修复前每个 provider turn/工具调用必抛 unavailable——Task 1 即 P0 修复本体。SDK 侧两缺口留上游反馈：构造期 authority⇒sink 组合校验缺失；工具返回值无 size/topo 边界（Task 2 route handler 须自防）。

## Task 2 设计冻结（实现前）
- 工具面 = 两个：`context_route`（CONTEXT_CONTROL/FORBIDDEN/FORBIDDEN，direct kernel；只在"可提交路由"时成功——SDK 对 CONTEXT_CONTROL 成功结果无条件解码 receipt，故任何非提交结果（候选/歧义/澄清）必须走稳定 rejected/failed ToolResult，不得以成功空载荷返回）+ `task_scope_search`（只读候选搜索，非 CONTEXT_CONTROL，命中不授权）。TC-HM-10 entrypoint 的 task_scope_open 折叠进 context_route(resume_existing, task_scope_id=exact)——commit 需 exact ID，满足"search 命中不直接授权"。
- 五路裁决：direct_standalone→receipt v2 standalone；memory_standalone→Task 2 期稳定 failed(context_route_memory_standalone_unavailable)（BLOCKED-until-Task-5，不 Noop）；continue_active→exact active cursor/binding revision 校验后 ROUTED_TASK receipt；resume_existing→必须带 exact task_scope_id（无 ID→rejected 引导先 search），open 成功后 ROUTED_TASK receipt；create_new→provision+binding 后 ROUTED_TASK receipt。
- 载荷自防（SDK 返回值无 size/topo 边界的缺口由 Host 补）：入参 strict schema + 手工上限（query ≤2048 字符、字段白名单）；handler 内所有异常→稳定错误码，无半状态（先裁决后写 ledger，ledger 写失败→failed 不返回 receipt）。
- 血缘：receipt.raw_call_id=values["raw_call_id"]、effect_id=context.effect_id.value（SDK fake 样板）；每次调用写 context_route_tool_invocations（幂等 UNIQUE(sdk_run_id,effect_id)）+ 提交时写 context_route_decisions(origin=context_tool)。

## Task 2 完成 + 价值里程碑（deterministic）PASS（2026-09-01，Host commits 8b3f20f7 + 9c796064）
- 工具链：context_route（host-composed、CONTEXT_CONTROL/FORBIDDEN/FORBIDDEN、direct kernel）+ task_scope_search（只读候选）；策略表 SDK_TOOL_EXECUTION_POLICY_OVERRIDES 驱动 ExecutableToolRecord；五路裁决接真实 S4 facade（search/open/create/binding head）；durable decisions(origin=context_tool) + invocation 血缘入 v45。12 个 service 级黑盒测试。
- **里程碑（S5A-CR-F1 收窄口径）**：tests/sdk_adapters/test_s5a_milestone_route_loop.py —— 真 SDK ReActLoop + 真三 authority + 真 route tool + 真 S4 store + 真 v45 ledger，deterministic scripted provider：
  1. direct_standalone：route receipt 收敛 + 每 turn snapshot receipt（revision 1,2 单调、payload_hash==expected fingerprint、checkpoint receipt==ledger 行）；
  2. resume_existing（"继续以前的 A"）：真 facade create→rebuild→真 binding head（manual-grant 仪式种子）→search 工具候选→exact ID open→route receipt 四元组==binding head→**最终 provider payload 含 exact ResumePackage 内容（同 Run continuation 证明）**→3 turn snapshot 链；
  3. unrouted 终局→sink 产 durable DIRECT_STANDALONE(origin=no_recall)，零 Memory 查询、零工具调用（TC-HM-01 口径）；
  4. memory_standalone→稳定 rejected（BLOCKED-until-Task-5，不 Noop）→终局 no_recall。
  4/4 PASS；回归 353 passed。复现命令：`cd backend && .venv/bin/python -m pytest tests/sdk_adapters/test_s5a_milestone_route_loop.py -v`
- 真实 provider lane：BLOCKED（用户未提供配置）——按批准口径 deterministic 先行，已升级请求。

## 矛盾转化再分析（里程碑后，phase-3 A.3）
主要矛盾"主模型能否同 Run 内正确判断上下文需求并完成回答"的生产链已经跑通（deterministic 证明 route 裁决→receipt→snapshot→同 Run continuation 全链协议成立）。矛盾转化为两个方面：
1. **真实性**：deterministic ≠ DoD——真实 provider 的 resume lane 与 usage 校准是 DoD 第 1 条唯一凭据，仍 BLOCKED 于用户 provider 配置（决定增量终态）。
2. **稳定交付**：链路存在 ≠ 链路可信——Task 3（Memory 0.6 消费面）、Task 4（因果组/冻结预算，消除 32k 双真相）、Task 5（no_recall 门接 reconcile+负测试）、Task 6（载荷变异/kill-replay/cutover）是把"能跑"变成"可交付"。
剩余任务排序不变（T3→T4→T5→T6），T3 在 Memory 仓独立、优先执行以解除 T5 依赖。

## 真实 provider 配置 + 里程碑真实车道 PASS（2026-09-01，Host commit 追加）
- provider 配置检查点解除 BLOCKED：用户提供 .env（simple-harness-sdk/.env，原未被 gitignore——已补 ignore 防泄漏）；持久化到产品原生 llm_runtime.json（用户数据目录，明文有意为之的产品配置面；启动自动种 registry provider 'primary' 并经产品自身路径转存 keychain）；模型 gpt-5.6-luna（用户口述 "5.6luna"，/models 实测唯一匹配）；连通性 smoke 200 OK。APIKEY 未打印、未进仓库文件、未进证据。
- **真实车道 PASS**（tests/sdk_adapters/test_s5a_milestone_real_provider.py，marker real_provider 默认跳过）：gpt-5.6-luna 3 turn 完成 "继续以前的 A"——task_scope_search("A")→context_route(resume_existing, exact task_scope_id, 且模型主动 pin expected_source_hash)→用 exact ResumePackage 回答（进度/取消原因/下一步全部准确）；route receipt 四元组==binding head；3 turn snapshot receipt 三 hash 相等；durable resume_existing decision。usage 4.7k/5.2k/8.5k tokens。原始 transcript 只进 ignored .local-test-evidence/s5a-real-provider/。
- 失败教训（第一轮 max_turns）：CJK FTS 分词——标题 "任务A-季度报告" 中 "任务A" 为单 token，查询 "A" 零命中致模型循环搜索；种子改空格分隔 latin token（"季度报告 A"）后全查询命中。**这是 S5b 语料/检索质量门的真实前置发现**（自然中文标题需要分词器或 trigram 支持，记入 S5b backlog）。
- DoD 第 1 条车道解除 BLOCKED。里程碑（deterministic + 真实）双 PASS。
