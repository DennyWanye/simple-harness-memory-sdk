# S5b Task 3 独立代码审查（正确性优先，只读）

- 审查对象：Host 仓 `git diff 959725f6..e033a781`（merge 前 7 commits），含 Task 2 审查 F-1/F-2 修复 `0ddf6f6e`。
- 口径：`acceptance.md` S5B-AC-1②③④（A3）、`design-freeze.md` §6/§7、`assurance-contract.json`（ASSET-TASKSCOPE-CANONICAL-STATE / ASSET-PROVIDER-IDEMPOTENCY / FAIL-SEMANTIC-CLOSURE / FAIL-DUPLICATE-PROVIDER-CALL）、`specialist-cluster-closure-terminal-window.json`、`code-review-task2.md` F-1/F-2。
- 实测：两条探针（scratchpad，未入仓）在 HEAD 上跑出 F-1、F-5 的失败场景；其余为代码推演。文件行号以 HEAD `e033a781` 为准。
- 严重度：P0 = 0，P1 = 2，P2 = 7，P3 = 3。

## 已确认成立的部分（不计 finding）

1. **reserved 行与 lease 同事务**（重点 1）：`foreground_queue.reserve_post_turn_attempt`（L2029-2097）在一个 `BEGIN IMMEDIATE` 内 `_validate_lease_tx`（owner/generation/过期/终态）+ CLOSURE 边界状态集 + `_validate_sdk_binding_tx` + INSERT attempt/members；非 owner → `foreground_generation_stale`、零行零调用（`test_reserved_row_requires_current_lease_owner_same_tx`）。`invoke` 的查重读取在另一事务先做（TOCTOU），但 attempt_id = uuid5(request_hash, ordinal) 且表 UNIQUE，第二插入必失败，且只有 lease owner 能插，故单 owner 不变量成立。
2. **返回后复验 lease**（重点 1）：`post_turn_invoker.py:402-411` `authorize_effect(CLOSURE)` 失败 → `lease_lost`，只把 attempt 行 settle 为 `succeeded`（账本事实，无 Provider/canonical 副作用）；`foreground_runtime.py:944-945` 对 `lease_lost` 抛错终止本 owner，不写 receipt、不 `record_sdk_terminal`。新 owner 见 `succeeded` 无 decision → `pending(closure_attempt_unapplied)`，零重发（`_lease_second_owner` seam 已证）。
3. **`sent_unknown` 绝不重发**：`handed_off` / `unknown(sent_unknown)` → `blocked`；无 observer 时同 request 与同成员均 0 调用（`test_unknown_taxonomy_*`、`_attempt_handed_off` seam）。`asyncio.wait_for` 超时与 `ProviderTimeoutError` 都归 `sent_unknown`（保守正确：发送后超时不会被判 not_sent）。
4. **receipt 与 `apply_mutation_plan` 同一事务**（重点 2）：`store.apply_mutation_plan(commit_hook)`（L234-355）在自身 `BEGIN IMMEDIATE` 事务内调用 hook，hook 用同一 `db` 写 `task_scope_closure_receipts` + projection source + `settle_succeeded_tx`（同一连接，非跨 store 对象/连接）；CAS 冲突路径不进 hook（无 receipt，attempt 由 `pending(extension=settle_success)` 在 receipt 事务内 settle）。`_semantic_closure_commit` seam 用 state_hash 证明零半状态。
5. **三水位终态门**（重点 3）：`record_sdk_terminal` 在 Harness 证据 gate 之后同事务调 `closure_coverage_tx`（scope 级 dirty ∨ 本 Run pending receipt），COMPLETED/FAILED 均有用例；非 COMPLETED 终态由 `ClosureFallback.settle` 直接 `pending(closure_run_not_completed)`，门仍生效且不发 Provider 调用。兜底发生在 `_observe_with_heartbeats` 返回之后（无心跳），lease 默认 300s、closure deadline 60s，窗口足够。
6. **handler 拒绝码矩阵**（重点 4）：standalone → `scope_unbound`；无脏无 pending → `nothing_to_close`（不递增 revision，`require_dirty` 在 apply 之外判断但 CAS 兜底）；refs 以 `task_scope_evidence_links` 为准；迁移表 `_check_transitions` 覆盖 §7 全部边（complete 之后 `plan.*`/状态迁移 → `after_complete`，`no_mutation` 任何状态合法）；plan_id = sha256(key+scope)，同 key 不同 scope 不冲突；同 key 同 scope 不同载荷 → store `mutation_plan_id_hash_conflict`（稳定码，非重试）。
7. **pending 归属**（重点 5）：`resolve_run_scope_tx` 以 `foreground_runs.task_scope_id`（admission）为准；跨 Run 合并 + `force_close_pending` 零 Provider 调用（`assert len(adapter3.calls)==1` 前后不变）；STATUS 投影新增 `semantic_closure_pending/pending_closure_count/pending_closures`，receipt 写入 bump projection source。
8. **F-2 修复真**：`ProductEffectExecutor` 预留时记 `tool_name`（`tools.py:400`）、v46 列入 identity guard、tombstone 带 `effect_class`、`is_material_event` 把 `abandoned+project_effect` 判 material（`test_abandoned_project_effect_reservation_is_material_dirty` 走真实 drain）。**F-1 修复真（凭据路径）**：`redact_credential_shapes` 为纯正则替换（确定性、无 DB 交互、不吞异常），`classify_objective_event` 对 targets/error_code 脱敏并标 `redacted=true`（`test_commit_fact_redacts_credential_like_path_and_never_raises_after_settle`）。残余见 F-8。
9. 测试改动 `d9046257`：`test_missed_call_fallback_*` 的重放断言由 `pending` 改为 `already_closed`（同为零调用、receipt 仍 pending），`sent_confirmed` 用例改为只作用于 `handed_off` 行（与 v46 单调守卫一致）——属基座修正，不是照实现改口径。

## Findings

### F-1 [P1] 已应用 plan 的幂等重放在"新脏事件之后"再写一条 receipt，脏标记被无收口清零（探针实证）

- 文件:行：`backend/deskpet/sdk_adapters/task_scope_mutation.py:402-423`（`commit_hook` 用 `task_scope_heads.event_watermark` 当前值写 receipt）；`backend/deskpet/task_scope/store.py:257-266`（replay 路径 `commit_hook(db, result, True)`）；`backend/deskpet/execution/semantic_closure.py:262-274`（receipt 幂等键 `(sdk_run_id, closure_watermark, outcome)`，watermark 不同即新行）；同时 `apply_closure` L344/L358 对 `applied_before` 跳过 `require_dirty` 与 `_check_transitions`。
- 问题：replay 时 hook 重新读取 `head.event_watermark`（`append_host_event` 会推进它），而不是该 decision 当时的 watermark。若两次调用之间 scope 又落了 material 事件，第二条 receipt 的 watermark 覆盖新事件 → `dirty_state` 立即为空。
- 失败场景（探针 HEAD 实跑）：同一 turn 内工具批次 `[write_file a, task_scope_update(K), write_file b, task_scope_update(K 同载荷)]`：第一条 receipt watermark=3；写 b 后 dirty=True；重放返回 `replayed=True` 且新增 receipt `(run, 5, mutate, 同 plan_id)`，`dirty_state.is_dirty == False`——b 的变更永远不会被收口，终态门放行。违反 ASSET-TASKSCOPE-CANONICAL-STATE（receipt 不可伪造）/ FAIL-SEMANTIC-CLOSURE；AC-1④"重复 plan 无半状态"当前用例只在无新脏时重放（`test_handler_rejection_codes_and_audit_rows` L159）所以没抓到。
- 修法：receipt 的 `closure_watermark` 必须取 decision 的 durable 值——`SELECT event_watermark FROM task_scope_canonical_revisions WHERE decision_id=?`（即 mutation.plan 事件序号），replay 与首次都用它；或 replay 时按 `plan_id` 查已有 receipt 直接返回、不再写。`_derive_from_decision`（`semantic_closure.py:772-776`）同样改用 decision 的 revision watermark 而非 `head.event_watermark`。
- 决定性回归测试：`test_replayed_plan_after_new_material_event_keeps_scope_dirty_and_writes_no_second_receipt`。

### F-2 [P1] 生产组合未接 `closure_reader`：下一 Run 的 snapshot 注入（pending 合并 / 收口指令）在生产不存在，ARCHITECTURE 回写失实

- 文件:行：`backend/main.py:8731-8739`（`ProductRunContextAuthority(ports_resolver=…, exposure_resolver=…, ledger=…, reconcile=…)` 无 `closure_reader`）；`backend/deskpet/sdk_adapters/context_authority.py:1004-1013, 1052-1057`（`closure_reader` 默认 None → 不注入）；`ARCHITECTURE/ARCHITECTURE.md` "snapshot 注入（`ProductRunContextAuthority(closure_reader=…)` → `closure_instruction_for_run`）"。
- 问题：`closure_instruction_for_run` 只在测试里被直接调用（`test_pending_closure_belongs_to_admission_scope_and_next_run_merges`），生产 `prepare_snapshot` 永远拿不到 `task_scope_closure_required` 消息。AC-1③ 明文要求 pending "在同一 admission scope 的下一 Run snapshot 注入"，且 `task_scope_update` 的 `allowed_evidence_refs`/`current_revision` 只经此消息暴露给模型——模型在 Run 内既不知道 evidence id 也不知道 base_revision，实际只能靠终态兜底（每个脏 Run 多一次 Provider 调用，而设计把兜底定义为"漏调用"的补救）。
- 失败场景：Run 1 pending → Run 2 同 scope 正常对话 → 模型从未收到收口指令 → Run 2 终态再发一次兜底调用；若模型在 Run 内自发调用 `task_scope_update`，refs/base_revision 只能猜 → `refs_outside_scope`/CAS 反复。
- 修法：main.py 组合处传 `closure_reader=lambda run_id: closure_instruction_for_run(_state_db_path, run_id)`，并按 `_sdk_provider_binding_resolver` 的做法在 `_activate_human_memory_host_ports` 缺件时 startup fail；ARCHITECTURE 在修好前不得声称已接线。
- 决定性回归测试：`test_production_context_authority_injects_closure_instruction_when_admission_scope_dirty`（走 `_build_product_sdk_runtime_stack`/service_context 注册的真实对象调用 `prepare_snapshot`，断言 protected 分区含 `source=semantic_closure`）。

### F-3 [P2] `not_sent` 分类在生产是死路径：SDK 用 `from None` 包装 httpx 异常，`_root_cause` 永远看不到 `ConnectError`

- 文件:行：`backend/deskpet/sdk_adapters/post_turn_invoker.py:376-386, 491-497`（`_root_cause` 只沿 `__cause__`）；SDK `simple_harness/providers/openai_compatible.py:151-154`（`raise ProviderTransportError(private_cause=…) from None`）；测试 `test_post_turn_invoker.py:99` 用裸 `httpx.ConnectError` 喂 FakeAdapter。
- 问题：生产路径 `ProductProviderAdapter → OpenAICompatibleProvider` 的连接拒绝/DNS 失败到达 invoker 时 `__cause__ is None` → 落入 `sent_unknown` → `pending(closure_attempt_unknown)` 且该 Run 的 members 被 open unknown 行锁死；design-freeze §6 规定的 `not_sent → attempt+1` 在生产永不触发。方向保守（不会重发），但测试用裸 httpx 异常证明的行为与生产不符（覆盖失真）。
- 修法：`_root_cause` 同时下钻 `getattr(exc, "private_cause", None)`（`ProviderError` 保存了它，errors.py:25-32）；用例改为真实 `OpenAICompatibleProvider` 指向已关闭端口。
- 决定性回归测试：`test_connection_refused_through_real_sdk_provider_is_classified_not_sent`。

### F-4 [P2] `reserved → handed_off` 不校验 rowcount：被新 owner reconcile 过的 reserved 行，旧 owner 仍会发出账本外的 Provider 调用

- 文件:行：`backend/deskpet/sdk_adapters/post_turn_invoker.py:347-362`（`_update(... WHERE status='reserved')` 后无条件 `adapter.invoke`）；`:290-292`（新 owner 把 `reserved` 标 `failed(not_sent)` 并新建 ordinal+1）。
- 失败场景：owner-1 插入 reserved 后被挂起（GC/SIGSTOP/慢 DB）直到 lease 过期；owner-2 reclaim → reserved→failed(not_sent) → 新 attempt 调 Provider；owner-1 恢复：UPDATE 影响 0 行但继续 `adapter.invoke` → 第二次 Provider 调用（账本里没有任何行代表它），返回后 `revalidate` 失败判 `lease_lost`，`settle_succeeded` 也 0 行。结果无半状态，但违反"一个 attempt ≤ 一次调用、每次调用有 durable 行"的 §6 不变量（FAIL-DUPLICATE-PROVIDER-CALL 的精神）。
- 修法：`handed_off` 转换用 `cursor.rowcount == 1` 守卫，0 行 → 直接返回 `lease_lost`（不调用）；`_settle_*` 同理记录 rowcount 供审计。
- 决定性回归测试：`test_stale_owner_does_not_call_provider_after_new_owner_reconciled_reserved_row`。

### F-5 [P2] 多字节 `idempotency_key` 让 handler 抛 `TaskScopeProtocolError`，变成无稳定码、无 audit 的 `tool_handler_failed`（探针实证）

- 文件:行：`backend/deskpet/sdk_adapters/task_scope_mutation.py:507-509`（只查 `len(key) > 256` 字符）与 `:551-552`（`identifier(str(arguments[name]), name, 512)` 按 UTF-8 字节数抛 `TaskScopeProtocolError`，不在 `ClosureRejected` 之内）；SDK `tools/registry.py:160-178` 把 handler 异常转 `ToolResult.failed("tool_handler_failed")`。
- 失败场景：模型给 200 个 CJK 字符的 key（600 字节）→ `idempotency_key_too_large` 逃出 `handle_task_scope_update` → 模型看到 `tool_handler_failed`（非 §7 稳定码），`host_pre_admission_audit` 无行。同样逃逸：`TaskScopeProtocolError` 来自 `_verify_refs_tx`/subject 校验、`TaskScopeNotFound`。
- 修法：`_validate_shape` 用字节长度校验并抛 `payload_invalid`；`handle_task_scope_update` 对 `TaskScopeProtocolError`/`TaskScopeNotFound` 统一转 `ClosureRejected("task_scope_update_payload_invalid"|"task_scope_update_scope_unbound")` 并写 audit。
- 决定性回归测试：`test_multibyte_idempotency_key_rejected_with_stable_code_and_audit_row`。

### F-6 [P2] `invoke` 吞掉 `asyncio.CancelledError`：运行时关闭/驱动取消时兜底继续写 pending receipt 与 Host 终态

- 文件:行：`backend/deskpet/sdk_adapters/post_turn_invoker.py:364-369`（`except (asyncio.CancelledError, ProviderCancelledError)` 后正常 return）。
- 问题：Python 3.11+ 任务取消需要向上传播；这里把取消当成 `unknown(sent_unknown)` 正常返回，`ClosureFallback.settle` 接着写 pending、`_drive_claimed` 接着 `record_sdk_terminal`——在 `_run_driver` 明确 `except CancelledError: raise` 的设计下，关闭序列中会多出一整段不该发生的 durable 写入；`ProductProviderAdapter.invoke` 也刻意把 `ProviderCancelledError` 还原为 `CancelledError` 以保持协作取消。
- 修法：settle unknown 后 `raise`（保留 durable 账本，恢复取消语义）；`asyncio.wait_for` 超时产生的内部取消不受影响（外层收到 `TimeoutError`）。
- 决定性回归测试：`test_cancelled_invoke_settles_sent_unknown_and_re_raises_cancellation`。

### F-7 [P2] `force_close_pending` 以 `head.event_watermark` 清零整个 scope 的脏，会吞掉正在执行的 Run 的 material 事件

- 文件:行：`backend/deskpet/execution/semantic_closure.py:876-892`（receipt watermark = 当前 head）；`backend/deskpet/memory/human_memory_service.py:493-500, 535-542`（checkpoint / task.complete / resume.update 前无条件调用）。
- 失败场景：Run A 留下 pending(W=5)；Run B 在同 scope 执行中已写文件（事件 6、7，尚未终态）；用户此时在 UI 保存 checkpoint → `force_close_pending` 写 `no_mutation` receipt watermark=7 → B 的事件被"closure_abandoned"覆盖；B 终态时 `coverage.satisfied` 为真（无脏）→ 不发兜底、模型在 Run 内的 `task_scope_update` 得到 `nothing_to_close` 或 CAS 冲突——B 的真实变更永远没有语义收口。与 A3 "pending 仍在时才强制收口"以及"不得静默清除"相悖。
- 修法：强制收口的 watermark 取最后一条 pending receipt 的 `closure_watermark`（只清它承载的债务），并在 scope 有非终态 foreground Run 时拒绝/延后（`foreground_runs` 可查）；至少 checkpoint 路径应把 receipt watermark 与 checkpoint 的 `event_watermark` 绑定。
- 决定性回归测试：`test_force_close_pending_does_not_cover_material_events_of_in_flight_run`。

### F-8 [P2] Task 2 F-1 的修复只覆盖凭据路径：`drain_reservations` 对 `commit_fact` 其它确定性拒绝仍无降级路径

- 文件:行：`backend/deskpet/execution/evidence_ingress.py` `drain_reservations`（fact 可读 → `commit_fact` 直抛，无 `except`）；`commit_fact` 内 `reject_private_payload` 与 `objective_evidence_hash_conflict` 仍可抛。
- 问题：Task 2 审查 F-1 明确列出的第二触发（同 effect id 在 replay 与 drain 间算出不同 objective payload → `TaskScopeConflict("objective_evidence_hash_conflict")`）未处理；`error_code` 之外的 `result.value` 派生字段（`_exit_code`）仍可能不一致；一旦发生，observer 抛出 → `run_terminal` 永远写不下 → 三水位门全部 pending、Run 永不终态。
- 修法：drain 对 `TaskScopeConflict`/`TaskScopeProtocolError` 写同 kind tombstone（`status=rejected_fact`, `reason_code`，PROJECT_EFFECT 仍带 `effect_class` 保 material）并置 `abandoned`，保证 terminal 收敛。
- 决定性回归测试：`test_drain_converges_when_reserved_fact_is_rejected_by_commit_fact`。

### F-9 [P2] 决定性覆盖缺口

1. 终态门只参数化 COMPLETED/FAILED（`test_s5b_acceptance_matrix.py:547`），CANCELLED/STOPPED 未证"一律生效"。
2. 无一条经真实 `ForegroundRuntimeExecutionAuthority._drive_claimed` 的端到端用例：兜底 `settle` → `record_sdk_terminal` 的生产顺序、`lease_lost` 抛错后 `_run_driver` 退出并在下一次 kick 收敛、`foreground_terminal_closure_pending` 后的重驱动，全部只在 harness 里手工顺序调用。
3. F-1 场景（重放前有新脏）与 F-5 场景无用例；`force_close_pending` 只直接调用函数，未经 `HumanMemoryHostService.save_checkpoint/mutate_task_scope` 生产入口。
4. `not_sent` 未用真实 SDK Provider（F-3）。
5. 两个 owner **同时**尝试 reserve（真正并发两连接）未覆盖，`_lease_second_owner` 是串行 reclaim。

### F-10 [P3] standalone 路由的 Run：Run 内 handler 拒绝 `scope_unbound`，终态兜底却照发 Provider 调用并可 apply

- 文件:行：`semantic_closure.py:599-616`（settle 不看 route）、`task_scope_mutation.py:258-262`（handler 看 route）。ARCHITECTURE 把它写成有意为之。两条通道对同一 Run 的口径相反；兜底会把与任务无关的 standalone 终答当 observation 让模型产出 mutate。建议兜底对 standalone 路由直接 `pending(closure_route_standalone)`，交给下一 Run 合并（与 §7"路由到 standalone 的轮次不承担该债务"一致）。回归：`test_standalone_routed_run_fallback_is_pending_without_provider_call`。

### F-11 [P3] 小项

- `post_turn_invoker.py:447-457` `_Transaction.__aenter__`：`assert_human_memory_ingress_open_tx` 抛错时连接未关闭（泄漏）。
- `task_scope_mutation.py:131` `derive_plan_id` 用 `key + scope` 无分隔符拼接（设计原文如此，但应 canonical_json 化以杜绝拼接歧义）。
- `semantic_closure.py:647-650` members 只取最近 32 个 material 事件的 refs，`evidence_set_key` 用全部事件 id——两者口径不一致，成员查重覆盖不完整。

## 其他观察（不计 finding）

- `lease_lost` 后旧 owner 的结果只存 hash，新 owner 只能 `pending(closure_attempt_unapplied)`——一次 Provider 调用被浪费但零重发，符合 §6；若要减少浪费需把 response 持久化到 attempt 行。
- `record_sdk_terminal` 的第三水位在 `closure_fallback is None` 的组合下会让脏 Run 永不终态；生产已接线，但其它组合（测试/工具）应在 startup 显式拒绝。
- `human_memory_service.mutate_task_scope` 在 `force_close_pending` 之后再读 `current_revision`，CAS 不受强制收口影响，正确。

---

VERDICT: FAIL
