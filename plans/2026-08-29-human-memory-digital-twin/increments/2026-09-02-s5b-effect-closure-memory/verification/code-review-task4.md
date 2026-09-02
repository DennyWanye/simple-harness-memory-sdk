# S5b Task 4 独立代码审查（正确性优先，只读）

- 审查对象：Host 仓 `git diff e033a781..a5277c7e`（merge 前 10 commits），含 Task 3 审查 F-1 `54b44952` / F-2 `2205a772` 修复。
- 口径：`acceptance.md` S5B-AC-2 ①–⑥（A2/A10）与最小验证动作（A1）、`design-freeze.md` §6/§8/§9、`assurance-contract.json`（ASSET-PROVIDER-IDEMPOTENCY / ASSET-RAW-EVIDENCE / ASSET-CREDENTIALS / FAIL-DUPLICATE-PROVIDER-CALL / FAIL-DATA-LOSS / FAIL-PRIVACY-STALE）、`code-review-task3.md` F-1/F-2 原文；Memory 0.6.1 源码（`core/jobs.py` runner、`backends/sqlite_v5.py` claim/admit/prepare/fail、`core/audit.py`、`core/evidence.py`）；Harness `runtime/evidence_protocol.py`（`MemoryAnalysisRequest.to_json`、`EvidenceSpanRef.__post_init__`、`_verify_evidence_span_authority`）。
- 实测：只读检查真实车道 transcript 目录 `simple_harness/.local-test-evidence/s5b-real-provider/`（现存 **1** 个文件 `run-1788366475.json`，43 KB；已确认其中不含 `Bearer` / `sk-` / `api_key` 字样，本报告不抄录任何凭据）；`git log -p` 核对 prompt 常量与真实车道断言的历史；其余为代码推演。行号以 HEAD `a5277c7e` 为准。
- 严重度：P0 = 0，**P1 = 1**，P2 = 4，P3 = 9。

## 已确认成立的部分（不计 finding）

1. **同事务终态 outbox（重点 2）**：`foreground_queue.record_sdk_terminal` 在同一 `BEGIN IMMEDIATE` 内完成三水位门 → run/turn 迁移 → `_append_memory_ingestion_outbox_tx`（outbox 行 + `memory_ingestion_evidence_links`）→ `terminal.before_commit` → commit；幂等重放走 `existing` 早退（同一 receipt、不重写）；`outbox_id = uuid5(sdk_run_id, turn_id)` + 表级 `UNIQUE(sdk_run_id, turn_id)`；成员只含本 turn 的 `foreground_turns.evidence_id`（客观 `host.*` 证据留在 TaskScope 账本）。`record_sdk_terminal(run_binding=None)` 才跳过 outbox；生产 `foreground_runtime._terminal_binding`（L424-437）在 binding 缺失时抛错而非静默跳过。Host 侧一 Run 一 turn（`foreground_run_heads.turn_id`），`UNIQUE(sdk_run_id, turn_id)` 语义成立。矩阵用例 `test_terminal_commit_writes_ingestion_outbox_same_tx` 与 `raw-evidence-commit` seam 用 `state_hash` 证明 kill 前零半状态、重放收敛。
2. **三键查重与零调用复用（重点 1）**：`post_turn_invoker.invoke`（L323-364）在一个读事务内取 `(request_hash) latest`、成员 open 行、`evidence_set_key` durable 行；`evidence_set_key = sha256(canonical(request.to_json() − {job_id, attempt, idempotency_key}))`，`MemoryAnalysisRequest.to_json` 不含 `request_hash` 字段，故 Memory `attempt+1` / 新 `batch_id`（`job_id = batch_id = stable_id(subject, batch_key, member_identity)`，随 attempt 变）时 key 不变——`test_analysis_attempt_five_states_and_unique` ② 断言 `rows[0][5] == rows[1][5]`。Memory reclaim（同 batch、同 request_hash，`_read_analysis_claim_unlocked` 从 `analysis_batches.request_json` 原样重建）→ `analysis_executor._durable_envelope` 命中 → 0 调用（矩阵 ③、`validation-decision-commit`、`state-mutation-commit`）；Memory `fail_analysis_batch` 后的新 batch（新 request_hash）→ `_durable_evidence_set_result` 复用 durable 响应重新派生（`lease-reclaim-in-flight`、`reconciliation-observer`：`reason_code = reused:<attempt>`，`provider_calls = 0`）。
3. **`sent_unknown` 绝不重发**：同 request_hash `handed_off`/`unknown(sent_unknown)` → `blocked`；不同 request_hash 经成员索引 `(subject, run_id, evidence_id)` 阻断；每次 blocked 都写 durable `host_pre_admission_audit(payload_kind='analysis_result', reason_code='memory.analysis.blocked:*')`（独立事务，`invocation-evidence-commit` seam 断言 `blocked_audit_rows`）→ Memory 有界重试后 `dead_letter`。`sent_confirmed` 仅经注入 observer 且只对仍 `handed_off` 的行生效（v46 单调守卫）。
4. **delivery authority 同一对象**：`HumanMemoryV7Runtime.job_runner` 先断言 `executor is self._analysis_authority`，再把同一对象同时作 `executor` 与 `delivery_authority` 传给 `DurableMemoryJobRunner`；Memory `register_analysis_delivery_authority` 用 `is` 比较 builder 绑定对象（`sqlite_v5.py:10765-10785`），生产 `main.py` 中 v7 runtime 与 lane 共用 `HostMemoryAnalysisExecutor` 实例，满足 `analysis_delivery_authority_identity_differs` 校验。`verify_analysis_delivery` 只认同一 state.db 的 durable envelope（issuer / canonical JSON / attempt / result_hash），矩阵 ④ 用 `other-state.db` 与篡改 issuer 证明拒绝。
5. **evidence_authority（重点 3）**：`HostEvidenceAuthority.read_admitted` 只以 `mode=ro` 读 state.db（`human_memory_evidence` ⋈ `human_memory_sanitization_receipts`，校验 `envelope_sha256`/`receipt_sha256` 与 receipt↔envelope 绑定），不触碰 Memory backend（不同 DB 文件，Memory 写锁内无死锁；state.db 为 WAL，`recovery_fence.py:107`）。返回的 `EvidenceItemAuthority` 与 Memory `_verify_mutation_span_unlocked` 六元组（source_kind / source_hash / sanitized_hash / envelope_hash / admission_receipt_id / admission_receipt_hash）以及物化时 `authority_span_binding == span_binding` 的 11 元组（`sqlite_v5.py:8286-8310`）逐项一致；`classification_authority_ref = "host:classification/v1"` 与 `host_classification_policy().authority_ref` 相同；`required_privacy_class = PERSONAL` 与 operation `proposed_privacy_class = PERSONAL` 一致。Harness `_verify_evidence_span_authority` 用 `/text` 指针 + identity normalization 重新切 UTF-8 字节并比较 `exact_quote`，与 Host `derive_span` 的 `len(text[:first].encode())` 计算一致（矩阵用例断言 `encoded[start:end] == quote`）。
6. **analysis_proposal 派生（重点 4）**：`text.find(q)` 首次命中 + `find(q, first+1)` 二次命中 → 空串 / 未命中 / 多命中（含重叠）/ paraphrase 全部 `analysis_quote_not_found`，不修补不模糊匹配；`quotable=False` 项拒绝；工具 schema 中不含任何 Host 专属字段（矩阵用例枚举 `start_byte/end_byte/quote_hash/envelope_hash/admission_receipt_id/base_revision`）；`no_mutation`（模型声明 / 非 tool call / 多 tool call / outcome 非法 / 全拒）统一为 `no_mutation` 结果且 Memory 不物化；被拒 operation 只写 `canonical_hash(rejected.to_json())` 审计。
7. **worker / lane（重点 5）**：`claim()` 在 `BEGIN IMMEDIATE` 内取行并 UPDATE，双 claim 被序列化；过期 lease 可 reclaim（每次 claim 计一次 attempt）；旧 owner 的 `_settle ... WHERE lease_owner=?` 影响 0 行 → 不覆盖新 owner；Memory 按 `source_ref` 幂等（`_read_ingestion_by_source`）同 receipt、`evidence_envelopes` 不增；dead_letter 只追加不删（`memory_ingestion_outbox_monotonic` 触发器，`RAW_HOST_TABLES` hash 守恒）；`MemoryAnalysisLane._run` 对 tick 异常只记 `last_error` + 退避，不会停摆。
8. **v7 接线（重点 6）**：`HOST_SUPPORTED_FILTER_POLICIES == {"credential-filter/v1","host-public-turn/v1","host-typed-ingress/v1"}`，与 `HOST_PUBLIC_TURN_FILTER_POLICY` / `HOST_TYPED_INGRESS_FILTER_POLICY` 精确一致（仓内无第三种 `filter_policy_version`）；`manager()` 在 build 之后、`self._manager` 赋值之前调用幂等 `register_principal_owner(principal, personal scope)`，fail-open 分支已删（`test_fresh_install_registers_owner_and_reconciles_empty`、`test_ownership_conflicts_always_fail_closed` 三种冲突一律抛）；生产 subject `deskpet-local-owner-v1`（`main.py:3051/3171`）与 `local_memory_principal().actor_id` 相同，evidence principal 与注册属主一致。
9. **F-1 修复真**：`task_scope_mutation.commit_hook`（L402-425）先按 `(task_scope_id, plan_id)` 查 `task_scope_closure_receipts`，命中即返回首条 receipt（不再写第二条）；首写 watermark 取 `task_scope_canonical_revisions.event_watermark`（`decision_id` join，= mutation.plan 事件序号，与 apply 同事务插入，`store.py:323`），`no_mutation` 也有 revision 行故不会命中 `assert watermark_row`；`semantic_closure._derive_from_decision`（L764-790）同样改为 decision 水位并对已有 receipt 早退。决定性用例 `test_replayed_task_scope_update_returns_original_receipt_and_does_not_clear_newer_dirty` 覆盖"重放前新增 material 事件仍脏 + coverage 不满足 + 仅 1 条 receipt"。
10. **F-2 修复真**：`main._build_run_context_authority` 注入 `closure_reader = closure_instruction_for_run(state.db, run_id)` 并注册槽 `sdk_closure_instruction_reader`（进缺槽断言）；`test_production_context_authority_injects_closure_instruction_when_admission_scope_dirty` 走 `main._build_run_context_authority` 真对象的 `prepare_snapshot`，断言 protected 分区含 `source=semantic_closure` 的 `task_scope_closure_required`。
11. **真实车道（重点 7）**：现存 transcript 显示 主 Run 4 次调用（route → write_file → task_scope_update → 终答）、closure `already_closed`/0 调用、analysis 恰 1 次 → episode 记忆（title/actions 与用户原话一致、`exact_quote` 为整句逐字子串，无臆造）→ `analysis_head == cognitive_head == 2`、`memory.cognitive.committed` → `typed_recall("README", run_id="next-turn")` 读到含 "1.2.0" 的 `long_term_typed` payload；README 恰好只改版本行。断言 `len(transcript) == main + closure + 1`、`len(analysis_adapter.calls) == 1`、`attempts == [(1,"succeeded")]` 严格。`git log` 证明：`test_s5b_milestone_real_provider.py` 自 oracle commit `dcb272a1` 后**未改过**（断言未放宽）；`ANALYSIS_SYSTEM_INSTRUCTION`/`PROPOSAL_TOOL_DESCRIPTION` 在 `b56d02d0..a5277c7e` 全部 7 个含该文件的 commit 中 md5 相同（调整发生在首个 commit 之前的工作树中）。prompt 是实现（`prompt_version` 冻结常量）而非 oracle，调整措辞合法；acceptance ⑤ 的"人工检查一致、无臆造"在现存 transcript 上成立。

## Findings

### F-1 [P1] Provider 响应到手之后、`settle_succeeded_tx` 之前的任何 Host 异常都把 attempt 永久留在 `handed_off`：已知结果被当作 `sent_unknown`，该证据被自己阻断到 dead_letter，响应丢失且无任何重试路径

- 文件:行：`backend/deskpet/memory/analysis_executor.py:366-374`（`invoke` 返回 `succeeded` 后直接 `await self._deliver(...)`，无异常处理）；`:376-447`（`_deliver` 在 `settle_succeeded_tx` 之前依次做 `current_analysis_apply_head`、`self._evidence.read_admitted` ×N、`compile_proposal`、对每个被拒 operation 的 `_audit`（各自 `BEGIN IMMEDIATE` 写 state.db，`busy_timeout=5000`）、`MemoryAnalysisResult/Receipt/Envelope` 构造、`durable_result_json`）；`backend/deskpet/memory/analysis_proposal.py:481-485`（`compile_proposal` 只捕获 `AnalysisProposalRejected`；`derive_span` 内 `EvidenceSpanRef(...)` 的 `ValueError` 直接逃逸——Harness `evidence_protocol.py` `_bounded_text(exact_quote, max_bytes=16_384)` 对 >16 KB 引用抛 `ValueError`）；`backend/deskpet/memory/evidence_authority.py:57-67`（`read_admitted` 的 `mode=ro` 连接无 `busy_timeout`，`aiosqlite.Error` 不捕获）。
- 问题：设计冻结 §6 把 `handed_off` 定义为"请求已发出、结果未知"，Host 对它的唯一处理是"拒绝一切再投递"。但这里响应已经在 Host 内存里，只因派生/审计/读库异常没能落库；`analyze_memory` 抛出 → Memory `fail_analysis_batch` → 重试 attempt+1（新 request_hash）→ `_open_member_attempt` 命中自己那条 `handed_off` 行 → `blocked` → 直到 `dead_letter`。既没有 `not_sent` 可走，也没有 durable 响应可复用（`_durable_evidence_set_result` 要求 `result_envelope_json IS NOT NULL`），一次真实 Provider 调用被浪费，该 turn 永远不会被分析。
- 失败场景：① 用户一轮贴入 >16 KB 文本，模型按 prompt "逐字引用"给出超长 `exact_quote` → `EvidenceSpanRef` `ValueError` → attempt 卡 `handed_off` → 3 次 Memory 重试全部 blocked → `dead_letter` + 3 条 `memory.analysis.blocked` 审计；② 模型给出 2 个 operation 其中 1 个被拒 → `_deliver` 为其写 `_audit` 时 state.db 正被前台终态事务长时间持锁（>5 s）→ `OperationalError: database is locked` → 同上；③ `read_admitted` 在 WAL checkpoint 竞争下的瞬时 `aiosqlite.Error` → 同上。三者都不是 transport 未知，却被永久归入"不可重发"。违反 AC-2②"永久记录 request/result receipt"（result 未记录）、AC-2③"新 attempt 只能按显式分类法构造"（没有分类能描述这条行）、§6 taxonomy；结果上等价于该证据的 FAIL-DATA-LOSS（Memory 侧永不物化）。
- 修法：把"响应落库"与"派生"拆开——`invoke` 返回 `succeeded` 后**立刻**在一个事务里 `settle_succeeded_tx(response, result_envelope_json=durable_result_json(response, envelope_json=None))`（只存公开响应 + hash），然后再派生/编译/审计；envelope 用既有的 `NULL→值` 一次性 UPDATE 附着（v46 触发器已允许）。派生阶段任何异常 → 抛 `HostAnalysisExecutorError("analysis_derivation_failed:*")` 让 Memory 有界重试，下一 attempt 经 `evidence_set_key` 复用 durable 响应（0 调用）重新派生；确定性失败（如超长引用）在 `derive_span` 内转为 `AnalysisProposalRejected(QUOTE_NOT_FOUND, reason="quote_too_long")`。顺带关闭 F-3 的两事务窗口。
- 决定性回归测试：`test_derivation_failure_after_provider_response_settles_attempt_and_replays_with_zero_calls`（fault 注入 `analysis-before-derive` 抛错 / 16 KB+ 引用两参数化；断言 attempt `succeeded` 且 `result_envelope_json` 含响应、Memory 重试 `applied` 或确定性 `no_mutation`，`adapter.calls == 1`，无 `memory.analysis.blocked` 行）。

### F-2 [P2] 真实车道的失败运行未留证据：STATUS/ARCHITECTURE 描述的"首跑 no_mutation"与"第二次运行 persona 追加进 README"两次 transcript 都不在 `.local-test-evidence/s5b-real-provider/`

- 文件:行：`simple_harness/.local-test-evidence/s5b-real-provider/`（仅 `run-1788366475.json`，`duration_s = 51.54`）；`ARCHITECTURE/PROJECT_STATUS.md` Task 4 段（"1 passed（125s）…第二次运行模型把自身 persona 文本追加进 README"）；`backend/tests/sdk_adapters/s5b_milestone_harness.py:180-189`（`transcript_path` 按 `int(started)` 命名，每次运行各留一份，且 `finally` 内 dump——失败运行也应有文件）。
- 问题：acceptance ⑤ 要求真实 provider 产出"人工检查与对话事实一致、无臆造"的非空 plan；本次能核对的只有最终成功的那一次。"prompt 在 no_mutation 之后调整"与"persona 文本进 README"都只能凭 STATUS 转述，无法复核模型到底输出了什么（例如 no_mutation 时 `closure_reason`、persona 追加时 `write_file.content` 全文与 EffectGate 记录），也无法判断 125 s 与 51.54 s 的差异来源。评审员被要求判断的两个真实车道问题因此不可审计。
- 失败场景：后续增量若再次调整 prompt/断言，没有基线 transcript 就无法证明"是实现变了而不是口径变了"。
- 修法：把三次运行的 transcript 补回（或说明删除原因并在 STATUS 登记），并在 `dump_transcript` 里追加 `prompt_version` + `ANALYSIS_SYSTEM_INSTRUCTION` sha256，使 prompt 变更可从 transcript 直接对照；RUNLOG 记录每次真实运行的文件名。
- 决定性回归测试：不适用（证据/流程项）；可加 `test_transcript_dump_records_prompt_hash_and_survives_failure`（断言失败路径也落盘且含 prompt hash）。

### F-3 [P2] `lease_lost` 分支把"标记 succeeded"与"附着 durable 响应"拆成两个事务；`AnalysisLeaseFence.revalidate` 在生产永不触发，ARCHITECTURE 把它写成 fence 与事实不符

- 文件:行：`backend/deskpet/sdk_adapters/post_turn_invoker.py:479-488`（`revalidate` 失败 → `settle_succeeded(attempt_id, response, plan_id)` 独立事务，只存 `result_hash`）→ `backend/deskpet/memory/analysis_executor.py:358-365`（再开事务 `_deliver(attach_only=True)`）；`analysis_executor.py:132-135`（`revalidate` 仅当 `clock() − reserved_at > deadline + 30`）与 `post_turn_invoker.py:438-439`（`asyncio.wait_for(coroutine, timeout=deadline_seconds)` 把调用耗时封顶在 deadline）；`ARCHITECTURE.md` "已知边界④"。
- 问题：① 两事务之间 kill → 行 `succeeded` 但 `result_envelope_json IS NULL` → 同 request_hash 的 reclaim 走 `reused` → `_durable_envelope` 为空 → `analysis_attempt_result_unavailable`，Memory 换 attempt 后 `evidence_set_key` 复用也要求 envelope 非空 → **对同一证据集发起第二次 Provider 调用**，而账本里已有一条 `succeeded`（FAIL-DUPLICATE-PROVIDER-CALL 的"authority 重试新建 attempt"形态）。② 由于 `wait_for` 上限 = deadline，`reserved_at → 响应` 的间隔不可能超过 deadline + 30，`revalidate` 只能靠测试拨钟触发；生产里 Memory lease 真过期时 Host 会照常走 `succeeded → _deliver`，安全性实际由 Memory `commit_analysis_result` 的 lease 校验 + Host 一次事务内落盘的 envelope 保证（结论正确，但 fence 本身是装饰）。
- 失败场景：见 ①（概率低——需要 ② 的分支先被触发；但 F-1 的修法会把 `settle` 提前到派生之前，同一处顺手把 ① 合并成单事务）。
- 修法：`lease_lost` 也用 `settle_succeeded_tx(..., result_envelope_json=durable_result_json(response, None))` 单事务落盘；要么把 `revalidate` 改为真实语义（回读 Memory `jobs.lease_expires_at`/token 的只读查询，或把 fence 交给 Memory 并删除 Host 侧假 fence），要么在 ARCHITECTURE 明写"Host 无 lease fence，以 Memory commit-time 校验 + durable envelope 兜底"。
- 决定性回归测试：`test_lease_lost_settles_response_and_envelope_in_one_transaction`（fault 注入在 `settle_succeeded` 与 attach 之间，断言重放零调用）。

### F-4 [P2] `MemoryIngestionOutboxWorker.claim()` 在提交 claim 之后才校验 `evidence_ids_json` 与 links 一致：不一致的行每个 lease 周期被 reclaim 一次、`attempts` 无限递增，却永远不会 dead_letter，也不留 `last_error`

- 文件:行：`backend/deskpet/memory/memory_ingestion_outbox.py:169-178`（`db.commit()` 后 `sorted(evidence_ids) != sorted(links)` → `raise RuntimeError`）；`:245-261`（`run_once` 只在 `deliver` 异常时走有界重试/dead_letter）；`:406-415`（lane 只记 `last_error` 继续）。
- 问题：行已 `claimed` 且持 lease；异常逃出 `run_once` → lane 吞掉；lease 到期再次被选中（`claimed AND lease_expires_at<=now`）→ 再抛。`attempts` 每 60 s +1 但从不比较 `max_attempts`，`last_error` 始终 NULL，STATUS 看不到任何异常；且它始终是"最老可投递行"，每个周期都先于其它 pending 行被挑中一次。
- 失败场景：任何写入 outbox 与 links 不一致的路径（未来多成员 turn 组、手工修库、迁移）都会制造一条永久幽灵行。
- 修法：一致性校验移到 `BEGIN IMMEDIATE` 内、UPDATE 之前，不一致 → 同事务 `state='dead_letter', last_error='memory_ingestion_outbox_links_mismatch'`（或不 claim 并审计）；`run_once` 对 `claim()` 异常也走 dead_letter 判定。
- 决定性回归测试：`test_outbox_links_mismatch_dead_letters_once_with_last_error_and_does_not_block_queue`。

### F-5 [P2] `foreground_runtime._terminal_binding` 在 binding 缺失时抛错：该 Run 永远无法进入 Host 终态，单 foreground FIFO 被整体卡死

- 文件:行：`backend/deskpet/execution/foreground_runtime.py:424-437, 969-981`（`foreground_runtime_run_binding_unavailable` 在 `record_sdk_terminal` 之前抛出，无降级）；`backend/main.py:3197-3200`（reader = `_sdk_runtime_stack.read_closure_run_facts`，读 SDK start snapshot 的 `context_metadata.run_binding`）。
- 问题：SDK 终态已观察、closure 已 settle、Harness 证据已排空，只因 start snapshot 里没有 `run_binding`（或 `_sdk_runtime_stack` 尚未 ready / 被重建）就拒绝写终态。lease 到期后下一 owner 重驱动会得到同样的错误，ASSET-FOREGROUND-RUN-ORDER（单 Run/FIFO）意味着同 subject 的后续 turn 全部排队。与 Task 3 的三水位门不同，这不是"债务未收口"，而是 Memory 摄入这一非关键路径把主链路 fail-closed 了。
- 失败场景：升级窗口内残留的旧 Run、start snapshot 因 `read_start_snapshot` 瞬时失败、或 `_sdk_runtime_stack` 在 stack rebuild 期间为 None（`main.py:10781` 的 `_build_product_sdk_runtime_stack` 在异常时只 warning+return）。
- 修法：binding 不可得时仍写 Host 终态，同事务写一条 `memory_ingestion_outbox(state='dead_letter', last_error='run_binding_unavailable')`（保留 turn→outbox 的 durable 记录并可审计），而不是阻断终态；或至少在 `_run_driver` 层把该错误映射为可重试 + STATUS 投影。
- 决定性回归测试：`test_terminal_without_run_binding_still_commits_and_dead_letters_outbox_row`。

### F-6 [P3] Host durable `result_envelope_json` 直接存完整 Provider 响应，不经 Host 侧凭据过滤；`host-public-turn/v1` 本身是空操作 sanitizer

- 文件:行：`backend/deskpet/memory/analysis_executor.py:430, 443-446`（`durable_result_json(response=…)` → `provider_response_json` 全文入库）；`backend/deskpet/memory/human_memory_service.py:1662-1725`（`build_foreground_turn_evidence` 把 `text` 原样放进 `sanitized_payload`，`removed_spans=()`）；仓内 `task_scope/protocol.py:121` 已有 `redact_credential_shapes` 但此路径未用。
- 问题：Memory 侧在 ingest（`core/evidence.py:277/288` `evidence_credential_boundary_rejected`）与 result（`freeze_public_audit_object` → `analysis_result_private_material`）两处都有拦截，所以含凭据形状的 turn 根本到不了 analysis（outbox 会 dead_letter）——ASSET-CREDENTIALS 在 Memory 侧成立。但 Host 的 durable 记录写在 Memory 校验**之前**，且 Host 侧没有任何等价检查；"analysis durable 记录只存 public 内容与 hash"目前依赖 Memory 的 ingest 边界而非 Host 自身。
- 修法：`settle_succeeded_tx` 前对响应文本/工具参数跑 `redact_credential_shapes`（命中 → 只存 hash + `redacted=true`）；把 `host-public-turn/v1` 至少接上同一 redactor（并把策略名与实际行为对齐）。
- 决定性回归测试：`test_analysis_durable_record_redacts_credential_shapes_before_settle`。

### F-7 [P3] episode 的 `occurred_at` 取分析时刻而非用户说话时刻

- 文件:行：`backend/deskpet/memory/analysis_proposal.py:215-223`（`occurred_at = receipt.admitted_at or 0.0`，而 `build_foreground_turn_evidence` 固定 `admitted_at=0.0`）与 `:346-358`（`occurred = item.occurred_at or now`，`now = self._clock()` 在 `_deliver` 时取）。真实 transcript 中 `occurred_start = 1788366526.96`，比 turn 晚约 50 s；后台 lane 积压时可晚数分钟到数小时，影响 episode 时序与短时域窗口。
- 修法：`_append_memory_ingestion_outbox_tx` 把 `foreground_turns.created_at`（或 outbox `created_at`）写进 lineage/outbox，`AdmittedItem.occurred_at` 从该值取。
- 决定性回归测试：`test_episode_occurred_at_equals_turn_time_not_analysis_time`。

### F-8 [P3] `HumanMemoryV7Runtime.manager()` 注册属主失败时泄漏已 build 的 backend，且下一次调用会在同一 DB 上再建第二个 backend

- 文件:行：`backend/deskpet/memory/human_memory_v7.py`（`manager()`：`build_human_memory_v7` 成功后 `register_principal_owner` 抛错 → 未 `close()`，`self._manager` 仍为 None）。
- 修法：`try/except` 中 `await manager.close()` 后再抛；或先赋值再注册并把注册失败标记为 runtime fail-closed。
- 决定性回归测试：`test_owner_registration_failure_closes_backend_and_fails_closed`。

### F-9 [P3] "缺件 → startup stable fail" 实际是 warning + skip

- 文件:行：`backend/main.py:10781-10788`（`_build_product_sdk_runtime_stack` 任何异常 → `logger.warning("product_sdk_runtime_skipped")` 并 `return`），`_activate_memory_analysis_lane` 的 `sdk_context_authority_composition_missing:*` 都被它吞掉。属既有模式（Task 1–3 同样），但 Task 4 回写与 AC-6① 都写成"startup fail"；建议在 Task 6 统一：缺槽 → 进程退出或 STATUS 显式 `degraded` 而非静默无 SDK runtime。
- 决定性回归测试：`test_missing_memory_analysis_slot_is_a_startup_failure_not_a_skip`。

### F-10 [P3] 测试基座小项

1. `s5b_memory_harness.recall_payloads`（L360）`now = clock() + time.time()`：`production_builder=True` 时 clock 就是 `time.time` → `now ≈ 2×epoch`（2082 年），typed_recall 的时间语义在两条里程碑车道上都是错的（`valid_time` 全 None 所以恰好不影响断言）。改为 `now=time.time()`/测试钟二选一。
2. `s5b_milestone_harness.dump_transcript`（L188）`"api_key" not in text.lower() or '"api_key"' not in text` 是恒真式（只在字面 `"api_key"` 出现时才失败），并不检查密钥**值**是否泄漏；应读取 runtime 的密钥值做 `assert key not in text`（不打印）。
3. 真实车道 README 断言 `"1.2.0" in readme and "1.1.3" not in readme`（`test_s5b_milestone_real_provider.py:152`）比确定性车道弱，正是它让"persona 文本追加进 README"通过。这不是 EffectGate/写工具口径问题（EffectGate 只裁决路径/根/envelope，不裁决内容；写入合法），而是 oracle 过弱 + 主模型未遵循"其余内容原样保留"。建议断言 `readme == README_BEFORE.replace("1.1.3","1.2.0")`（真实车道允许失败但必须把差异写入 transcript 供人工检查），并把"文件内容与用户要求一致"作为 A1 人工检查项显式登记。
4. `_analysis_adapter`（`main.py:8210-8216`）与 closure 用同一 `build_authority(binding).provider` 重建路径，符合"不新建 extractor client"；但 `build_worker_config` 回落三元组用 `model_params={}`，与真实 binding 的 `model_config_hash` 不同——只在成员无 lineage 时生效（生产不会），保持即可，ARCHITECTURE 已注明。

### F-11 [P3] 覆盖缺口

1. 无一条用例经真实 `ForegroundRuntimeExecutionAuthority._drive_claimed` + `SdkRuntimeStack.read_closure_run_facts` 走到 `record_sdk_terminal(run_binding=…)`；里程碑两条车道都用 `FakeRunFacts` 直接调 `mh.record_terminal`（Task 3 F-9.2 的同一缺口延伸到 Task 4）。
2. 终态 outbox 只在 COMPLETED 上验证；FAILED/CANCELLED/STOPPED 终态是否也应写 outbox（用户 turn 已存在，分析仍有价值）未定义也未测试。
3. F-1 场景（响应后派生异常）、F-4（links 不一致）、F-5（binding 缺失）均无用例。
4. `MemoryAnalysisLane._run` 未被任何用例驱动（只测 `worker.run_once`/`run_job`）；lane 的退避、`wake()`、`close()` 超时取消路径无覆盖。
5. Host outbox 双 owner **真正并发**（两个连接同时 `claim`）未覆盖，`commit-before-ack` 是串行 reclaim。
6. Task 3 未要求修复的 F-3（`_root_cause` 看不到 `private_cause`，生产 `not_sent` 是死路径）、F-4（`handed_off` 不校验 rowcount）、F-6（吞 `CancelledError`）、F-7（`force_close_pending` 覆盖在飞 Run）在本 diff 中仍未处理，analysis purpose 同样受 F-3/F-4/F-6 影响（`test_analysis_attempt_five_states_and_unique` 仍用裸 `httpx.ConnectError`）。
7. Memory 0.6.1 已登记缺陷 `decision_evidence_refs_ordinal_invalid`（多 evidence batch 只引用非首条 evidence）使 `_resolve_outbox` 的多 Run 分支（`analysis_executor.py:184-194`）在生产 `batch_size=1` 下是死代码；`membership-growth` seam 刻意只引用首条 evidence，属"绕开缺陷"而非证明——应在 Memory 修复后补引用第二条 evidence 的断言。

### F-12 [P3] 三键查重与 reserve 分属两个事务；成员 open 检查无 DB 级约束

- 文件:行：`post_turn_invoker.py:323-328`（读事务）与 `:399`（`reserve_attempt` 另一事务）。同 request_hash 由 `UNIQUE(request_hash, attempt_ordinal)` 兜底；不同 request_hash、同成员的并发（两个 executor 实例）无约束。生产单一 lane + 单进程串行，Task 3 已接受同样的设计；仅登记，建议在 `reserve_analysis_attempt` 事务内再查一次成员 open 行。
- 决定性回归测试：`test_concurrent_reserve_on_same_member_is_rejected_in_reserve_transaction`。

## 其他观察（不计 finding）

- `MemoryAnalysisRequest.run_id` = 每 subject 固定的 foreground evidence run（`uuid5(subject)`），所以 Memory `batch_key` 对同一 subject 恒定；`batch_size=1`/`max_batch_wait=0` 保证一 turn 一 batch。若将来调大 batch_size，`_resolve_outbox` 的"跨 Run 只要求 lineage 三元组一致、取最新 Run 的 binding 重建 adapter"会让 Provider 调用绑定到并非所有成员的 Run——需要在那时重新审。
- `HostMemoryAnalysisExecutor.calls/provider_calls/last_outcome` 是进程内计数器，仅供测试；ASSET-PROVIDER-IDEMPOTENCY 的证据在 attempt 账本，正确。
- `analysis_lineage_json.run_binding` 只含 `SdkRunBindingV1` 的 id/fingerprint/model_params 字段，无凭据。
- 通过 Memory `claim_analysis_batch` 派生的 `provider_id/model_id/model_config_hash` 与 outbox lineage 逐位比较（`analysis_lineage_mismatch` 用例 0 调用 + 审计行）——AC-2② "按 originating Run 的 durable binding 重建" 成立。

---

VERDICT: FAIL
