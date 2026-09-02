# S5b Task 2 独立代码审查（正确性优先，只读）

- 审查对象：Host 仓 `git diff afe1d0cd..959725f6`（7 commits，merge `959725f6`），含 Task 1 审查 F-1 修复 `ee02d933`。
- 口径：`acceptance.md` S5B-AC-1①（A13）、`design-freeze.md` §2/§3/§4/§5/§11、`assurance-contract.json`（ASSET-RAW-EVIDENCE / FAIL-HALF-STATE / FAIL-PROTOCOL-REPLAY）、`verification/code-review-task1.md` F-1。
- 实测：主 checkout 6 个相关测试文件 `27 passed / 17 xfailed`；F-1 回归在临时 worktree 中把 `tools.py` 回退到 `afe1d0cd` 后 **2 failed**（先红），HEAD 全绿（后绿）。
- 严重度：P0 = 0，P1 = 2，P2 = 6。

## 已确认成立的部分（不计 finding）

1. **同事务性**（重点 1）：`evidence_ingress.py` `commit_fact`（约 L560-650）在一个 `BEGIN IMMEDIATE` 内依次写 `human_memory_sanitization_receipts`+`human_memory_evidence`（`append_evidence_tx` 复用调用方 db）、`host.file|host.test` 事件 + refs、`harness.tool_invocation` 导入回执、watermark、projection source；`_fault("objective-event-commit")` 在 commit 前，异常统一 `rollback`。fault seam `objective-event-commit` 用 `state_hash` 证明 kill 后零半状态、replay 恰一份、再重放 hash 不变。SDK `execution_effects`（另一库）与 state.db 之间通过 `effect:{effect_id}` 预留行 + `source_event_id`/`evidence_hash` 幂等关联；crash 于 SDK settle 与 Host commit 之间 → 两条路都收敛：react loop 重放（步骤 0 跳 gate → SDK 直返原 receipt → `_commit_evidence` 看到 `reserved` → commit）或 terminal 排空（`read_reserved_fact` 读 SDK 账本）。
2. **预留并发**（重点 2）：`reserve`/`commit_fact`/`_tombstone`/`authorize_terminal` 全部 `BEGIN IMMEDIATE`；`ContextRouteLedgerStore` 三个写事务也是 `BEGIN IMMEDIATE`（`context_authority.py:429/529/698`），`ingest_ledger_fact_tx` 在其内 reserve+ingest，`_next_sequence_tx` 的 `MAX(receipts ∪ reservations)` 在同一写事务内计算 → 单进程多连接下无双分配；`UNIQUE(run_id, source_sequence)` 兜底。空洞由 terminal 排空 tombstone 补齐（`test_gap_in_reservations_keeps_terminal_pending_until_drained`）。`execution_after_terminal_rejected` 拒绝 terminal 后的迟到预留。`_ingest_tx` 对 run_terminal 检查 `later`（reservations ∪ receipts 中更大 seq）→ observer 在 `next_sequence()`（事务外读）与 `ingest()` 之间被插入新预留时以 conflict 失败而非丢行，下一 owner 重放收敛。
3. **v46 迁移**（重点 3）：8 张表 + marker 全部注册恢复表（taxonomy A，fence 触发器 INSERT/UPDATE/DELETE）、迁移链、`effect_closure_marker`；v45 → v46 只建表不动旧行（测试保留 `context_route_decisions` 行）；旧 runtime（target 45）打开 v46 → `FUTURE`/`human_memory_program_future_database_unsupported`，库字节不变。
4. **dirty_state**（重点 4）：以 scope 为键、`outcome IN ('mutate','no_mutation')` 取最大 `closure_watermark`，无 receipt 自 0，pending 不清脏；material 判定只用 `MATERIAL_HOST_EVENT_KINDS` + `PROJECT_EFFECT_TOOL_NAMES` 映射（无关键词/正则）；跨 Run 由 `event_sequence`（scope 级）天然覆盖。
5. **映射表**（重点 5）：`OBJECTIVE_EVENT_MAP` 与 `PROJECT_EFFECT_TOOL_NAMES` 有 exhaustiveness 断言；`run_shell`/`process_start` 两个分支（host.test / host.file）都是 material，**注入无法把 PROJECT_EFFECT 调用降级为 trivial**；失败 effect（FAILED 终态）同样 `classify_objective_event` → material（`test_objective_event_map_is_exhaustive...` 覆盖 `outcome=failed`）。
6. **F-1 修复**（重点 6）：`_is_first_occurrence` 用 `self._uow.read_effect(effect_id)`——与 SDK `executor.py:268` 同一读口、同一 uow；测试用真实 `EffectExecutor.execute` + `SqliteExecutionUnitOfWork`（不覆写 execute），覆盖 terminal 直返与 UNKNOWN→reconcile 两分支；先红后绿已实证。

## Findings

### F-1 [P1] 可读事实被 Host 侧校验永久拒绝时，Run 与 terminal 排空都不收敛（模型给的文件名即可触发）

- 文件:行：`backend/deskpet/execution/evidence_ingress.py` `commit_fact`（`reject_private_payload(dict(objective.payload), "objective_event")`，约 L571）；`backend/deskpet/sdk_adapters/tools.py` `_commit_evidence`（在 `super().execute` **返回之后**调用，约 L480-486）；`backend/deskpet/execution/foreground_runtime.py` `SqliteSdkTerminalObserver.observe` → `drain_reservations`（约 L1240）。
- 问题：`objective.payload["targets"]` 直接来自模型参数（`path`/`source`/`destination`…），`_reject_private` 对字符串值跑 `_CREDENTIAL_PATTERNS`（`protocol.py:57-64`），命中即抛 `TaskScopeProtocolError`。该抛错发生在 SDK 已 `settle_effect`（文件已写、ledger=SUCCEEDED）之后，`execute` 向上抛 → Run 以 driver failure 失败；重放时步骤 0 跳 gate、SDK 直返原 receipt、`_commit_evidence` 再抛同一错；terminal 排空 `read_reserved_fact` 读到同一事实 → `commit_fact` 再抛 → observer 抛出，`run_terminal` 永远写不下，`authorize_terminal` 永远 pending。`drain_reservations` 对"可读但不可提交"的事实没有任何降级路径（只有"不可读 → tombstone"）。
- 失败场景：`write_file(path="docs/bearer authentication.md", ...)`（`(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}` 命中 "bearer authentication"），或 `path="keys/sk-abcdefghijklmnopqrst.txt"`。文件已落盘，模型看不到 tool result，Host foreground Run 永不终态（FAIL-PROTOCOL-REPLAY；若 FIFO 依赖该 Run 终态，会阻塞后续 Run）。同类型触发还有 `TaskScopeConflict("objective_evidence_hash_conflict")`（同 effect id 两次算出不同 objective payload，例如 `_exit_code` 读到的 result.value 在 replay 与 drain 间不一致）。
- 建议修法：① 客观事件载荷不直接持久化模型给的路径字符串：`targets` 改为相对 workspace_root 的规范路径 + 在 `classify_objective_event` 内先做 `reject_private` 自检，命中则记 `{"targets_redacted": true, "target_count": n}`（仍是 material），永不在 settle 之后抛错；② `drain_reservations` 对 `commit_fact` 抛出的 `TaskScopeProtocolError`/`TaskScopeConflict` 兜底：写同 kind tombstone `{"status":"rejected_fact","reason_code":...}` 并置 `abandoned`，保证 terminal 收敛；③ `_commit_evidence` 的异常不得升级为 Run 故障（记 durable warning，留给 terminal 排空）。
- 建议回归测试：`test_write_file_with_credential_like_path_still_commits_material_event_and_run_terminates`、`test_drain_converges_when_reserved_fact_is_rejected_by_private_scan`。

### F-2 [P1] Run 终态时仍非终态（UNKNOWN/HANDED_OFF）的 PROJECT_EFFECT 被 tombstone 成 trivial，脏标记静默丢失

- 文件:行：`backend/deskpet/sdk_adapters/composition.py` `read_reserved_fact`（`if record is None or not record.terminal or record.result is None: return None`，约 L633）；`evidence_ingress.py` `_tombstone`（payload 只有 `{"status":"abandoned","reservation_id":…}`）；`semantic_closure.py` `is_material_event`（tombstone 的 `harness.tool_invocation` 无 `tool_name` → trivial）；SDK `effects.py:44-52`（`UNKNOWN` 不在 `_TERMINAL_STATES`）。
- 问题：design-freeze §2 规定 PROJECT_EFFECT "成功或失败执行 → material"，但 UNKNOWN（物理结果不明，文件可能已写）这一档在实现里既无 `host.file` 事件、`harness.tool_invocation` tombstone 又是 trivial，`dirty_state` 认为 scope 干净。预留行不存 `tool_name`，tombstone 无法回溯是哪类工具。
- 失败场景（真实可达，`test_gate_does_not_preempt_unknown_effect_reconciliation` 已展示前半段）：handler 中途 CancelledError → ledger `unknown`；恢复后 reconcile 返回非终态（`ToolResult.unknown("awaiting reconciliation")`），react loop 继续并 COMPLETED；terminal 排空 → `read_reserved_fact` 返回 None → tombstone → `dirty_state(scope).is_dirty == False` → Task 3 终态门不会触发 closure；实际磁盘上文件已写。同时 SDK 授权拒绝（effect=None）的调用也被记成 "abandoned" tombstone，语义混淆（无害但审计失真）。
- 建议修法：`read_reserved_fact` 对 **任意状态** 的 effect 记录都返回 `ToolInvocationFact`（`effect_state=record.state.value`，`outcome="unknown"`，`objective=classify_objective_event(record.tool_name, args, record.result or ToolResult.unknown(...))`），只有"账本无记录"才 tombstone；或最少让 `tool_invocation` 类 tombstone 携带 `tool_name`（需在预留时记录 tool_name——v46 尚未发布，可加列）并在 `is_material_event` 中把 PROJECT_EFFECT 的 abandoned tombstone 判 material（fail-closed）。
- 建议回归测试：`test_drain_marks_unknown_project_effect_material_not_trivial_tombstone`、`test_dirty_state_counts_abandoned_project_effect_reservation_as_material`。

### F-3 [P2] 步骤 0 对 PREPARED 记录也跳过 gate：crash 于 `prepare_effect` 与 `mark_effect_handed_off` 之间时，物理效果在无重验下执行

- 文件:行：`backend/deskpet/sdk_adapters/tools.py` `_is_first_occurrence`（`return read_effect(effect_id) is None`，约 L500）；`effect_gate.py` 模块 docstring 步骤 0 "any state — … PREPARED"；对照 SDK `executor.py:312`（PREPARED → `refresh_prepared_authority`）、`:426`（`prepare_effect` 持久化）、`:459`（`mark_effect_handed_off`）。
- 问题：PREPARED 行代表"尚无任何物理动作"，重放时 SDK 会重新授权并**物理 dispatch**；此时跳过 gate 与 acceptance ④ "物理 executor 前每次重验" 相悖。Task 1 审查 F-1 已明示可 `existing is None or existing.state is PREPARED` 时才 gate，实现选择了更宽的 "任一状态"，且 design-freeze §4 未增补步骤 0（只改了 ARCHITECTURE 与 docstring）。REQUIRE_USER 路径在 `prepare_effect` 之前抛 `ToolAuthorizationPending`，不产生 PREPARED 行，故窗口仅限 `prepare_effect`→`bind_effect_handoff`（Host 侧 await）→`mark_effect_handed_off` 之间的 crash 与 fence epoch 更换。
- 失败场景：crash 于 `bind_effect_handoff` 期间；恢复前用户 close scope / 追加 binding；恢复后重放 → 无 gate → 写入已关闭 scope 或 superseded 根。
- 建议修法：`_is_first_occurrence` 改为 `existing is None or existing.state is EffectState.PREPARED`；design-freeze §4 增补步骤 0 措辞。
- 建议回归测试：`test_gate_reverifies_prepared_not_handed_off_effect_on_replay`（真实 SDK executor，`bind_effect_handoff` 抛 CancelledError 留下 PREPARED 行，gate 条件失效后重放 → rejected 且无物理写）。

### F-4 [P2] test-runner 白名单只看首 token，shell 复合命令可被标成 `host.test`

- 文件:行：`backend/deskpet/sdk_adapters/effect_gate.py` `_command_tokens`/`_test_runner_head`（约 L246-262）。
- 问题：`"pytest && rm -rf build"`、`"pytest; git push"` 的首 token 序列 == `("pytest",)` → `host.test`。materiality 不受影响（两支都 material），但 `host.test` 语义（"只是跑了测试"）会被 Task 3 closure 摘要与 Memory analysis 当作非变更信号。`"pytest;"`（无空格）恰好不匹配属偶然。
- 建议修法：白名单命中后若剩余 token 含 `;` `&&` `||` `|` `$(` `` ` `` `>` 任一（token 级等值/前缀判断，非正则），降级为 `host.file`；`shell=True` 参数存在时同样降级。
- 建议回归测试：`test_test_runner_head_followed_by_shell_operator_is_host_file`。

### F-5 [P2] v46 单调守卫漏网列

- 文件:行：`backend/deskpet/memory/migrations/038_effect_closure_memory_v46.sql` `memory_ingestion_outbox_guard`（约 L173-192）、`post_turn_invocation_attempts_guard`（约 L194-224）。
- 漏网 UPDATE 路径（DELETE 已全部封死）：
  1. `memory_ingestion_outbox`：`analysis_lineage_json`、`lease_owner`/`lease_expires_at`、`last_error` 在 `delivered`/`dead_letter` 后仍可改；`analysis_lineage_json` 未列入 identity。
  2. `post_turn_invocation_attempts`：`provider_request_id` 任何状态可改（含 settled 后），`reason_code` settled 后可改，`unknown_class` 可在 `handed_off` 未 settle 时随意设置，`handed_off_at` 可在 `status='reserved'` 时先行写入。
  3. `harness_evidence_reservations`：无 `_no_update` 触发器但 guard 完整，OK。
- 失败场景：Task 4/7 的 bug 或手工 SQL 可在 `succeeded` 后改 `provider_request_id`，破坏 "request/result/receipt 永久可审计"（program 契约 96-97）。
- 建议修法：identity 列加 `analysis_lineage_json`；attempts guard 增加 "OLD.provider_request_id IS NOT NULL AND NEW.provider_request_id IS NOT OLD.provider_request_id → ABORT"、settled 后 `reason_code`/`provider_request_id` 冻结、`handed_off_at` 只能与 status→handed_off 同步写。
- 建议回归测试：`test_v46_guards_freeze_provider_request_id_and_outbox_lineage_after_settle`。

### F-6 [P2] `run_terminal` 未走预留协议，与 §3 `terminal:{sdk_run_id}` 规范不符；observer 的 next_sequence 在事务外读取

- 文件:行：`backend/deskpet/execution/foreground_runtime.py` L1240-1300（`drain` → `next_sequence()` → `ingest(source_sequence=next_sequence)`，`event_id=str(sdk_evidence.event_id)`，idempotency `foreground-terminal:{event_id}`）；`RESERVATION_KINDS` 含 `run_terminal` 但无人写。
- 问题：非 bug（`_ingest_tx` 的 collision/`reserved_by_other`/`later` 三重检查保证冲突而非丢行），但 (a) §3 冻结的 `terminal:{sdk_run_id}` 未实现，(b) 竞争时 observer 抛 `execution_source_sequence_conflict`（TaskScopeConflict）而非 `TerminalWatermarkPending`，上层若按异常类型区分"可重试"会误判。
- 建议修法：terminal 也 `reserve_tx(kind="run_terminal", source_event_id=f"terminal:{sdk_run_id}")` 并在**同一事务**内 ingest；或在 design-freeze §3/§11 记录偏离。
- 建议回归测试：`test_run_terminal_uses_reserved_sequence_in_same_transaction`。

### F-7 [P2] `_evidence_scope` 的 envelope 回退让无 foreground 绑定的 Run 也产生预留，但没有排空者

- 文件:行：`backend/deskpet/sdk_adapters/tools.py` `_evidence_scope`（约 L368-385）；ARCHITECTURE 写的是 "无 foreground 绑定的 Run 不产 Harness 证据"，与代码不一致。
- 问题：只有 `SqliteSdkTerminalObserver`（foreground）排空；回退路径创建的 `reserved` 行永远 reserved，`task_scope_run_watermarks` 永无 terminal。测试基座（`s5b_effect_gate_harness`）正依赖此回退，`test_executor_reserves_before_dispatch_and_skips_when_effect_absent` 因而只能断言 write_file 一条预留——属"按基座能力补预期"。
- 建议修法：二选一并写进 ARCHITECTURE：删除回退（仅 foreground 绑定产证据，测试基座补 `foreground_run_sdk_bindings`），或为非 foreground Run 提供同一排空入口。
- 建议回归测试：`test_envelope_only_run_without_foreground_binding_produces_no_reservation`（或对应的 drainer 用例）。

### F-8 [P2] 覆盖缺口

1. `ProductSdkRuntimeStack.read_reserved_fact` 生产实现零测试（所有排空测试用 `_Stack` 替身）：effect 分支的 `run_id` 不匹配返回 None、provider 分支 `usage_json.get("usage")` 形状假设、`provider_response_from_json` 失败静默为 None，都未验证。建议 `test_runtime_stack_read_reserved_fact_from_real_sdk_ledger`。
2. 无一条经真实 react loop + foreground 绑定 + 真实 stack 的端到端用例证明四类事实（snapshot/provider/route/tool）都在生产接线下预留-导入-排空（现有 `test_four_harness_evidence_kinds_advance_watermark_to_terminal` 直接调 ledger/ingress）。
3. 两连接并发 `reserve`（模拟双 owner）无用例，仅靠 `BEGIN IMMEDIATE` 推理。建议 `test_concurrent_reserve_from_two_connections_never_double_allocates`。
4. `_commit_evidence` 在 settle 后抛错的行为（F-1）无用例。
5. `dirty_state`：receipt `closure_watermark` 大于当前最大 event_sequence、同 scope 两个 Run 交错 receipt 的边界无用例。
6. `test_reservation_and_tombstone_tables_are_append_only_and_monotonic` 中 `drain_reservations(RUN, fact_reader=None)` 与生产 `fact_reader=stack` 路径不同，tombstone 路径与真实读取路径的 `read_reserved_fact` 返回 None 的等价性未锁定。

## 其他观察（不计 finding）

- `ContextRouteLedgerStore` 的 `row_factory` 改为 `aiosqlite.Row` 以复用 `_tx` helpers，既有位置索引读取仍兼容。
- `commit_fact` 之前的 `program.initialize_subject(subject)` 是独立事务，幂等，不影响主事务原子性。
- F-1 修复 commit 的 test 改动只是把 `_Case` 时钟对齐 SDK lease（先红后绿的失败原因是断言而非基座），未见"照实现补预期"。
- `_S4_HUMAN_MIGRATIONS` 纳入 038 使其获得 chain SQL 与 fault-injection 钩子；037 不入链的遗留已在 `schema.py` 注释与 ARCHITECTURE 如实记录。

---

VERDICT: FAIL
