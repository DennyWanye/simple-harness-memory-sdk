# 中文摘要（Spike A3：冻结 SDK 0.7.1 下 PROJECT_EFFECT 门与 envelope）

- 结论：**成立，含一条设计约束**。7 个用例通过（真 ReActLoop + Host 三 authority + v45 ledger + S4 binding store）。
- (a′) UNROUTED、(a″) 同批 route+write → `ROUTE_BARRIER_NOT_OBSERVED` 拒绝，handler 0 次；(b) ROUTED_TASK 下 `issue_envelope` 逐 call 调用，六元组 envelope 等于 S4 binding head 并到达 handler，真 `verify_task_execution_envelope` 接受；(c) 模型伪造 authority 字段 → `MODEL_AUTHORITY_FIELD_FORBIDDEN`；(d) 无 root_resolver → `sdk_task_execution_root_authority_unavailable`。
- 约束：`routed_standalone` 下 SDK preflight 不触发 barrier，Host 抛 `sdk_task_execution_route_authority_missing` **异常逃出 ReActLoop**（整 Run 故障）——冻结 SDK 没有让模型看到"闲聊状态不许项目 effect"的拒绝路径；policy 三字段进 capability/catalog fingerprint。

（以下为子代理原始英文报告，保留作证据）

# Spike A3 — PROJECT_EFFECT gating through the frozen SDK 0.7.1 react loop

Disposable spike. No repository file was modified.

## Command

```
cd /Users/taiwan/PROJECTS/SimplaHarness/simple_harness/backend && \
.venv/bin/python -m pytest \
  /private/tmp/claude-501/-Users-taiwan-PROJECTS-SimplaHarness/84cdd128-88f2-4c7d-9db9-64a64b8ed54e/scratchpad/spike-a3/spike_a3_test.py \
  -q -p no:cacheprovider -s
```

Result: `7 passed in 1.72s` (full output in `run_output.txt` next to this file).

Base: a copy of `backend/tests/sdk_adapters/test_s5a_milestone_route_loop.py`
(real `ReActLoop`, real `ProductRunContextAuthority` / `ProductRuntimeDecisionSink` /
`ContextRouteToolService` over a real v45 SQLite ledger + S4 binding store), extended with
a `write_file` tool whose `ToolExecutionPolicy` is
`PROJECT_EFFECT / route REQUIRED / task_scope REQUIRED`, a spike-local handler that
records `ToolContext`, and the real `ProductTaskExecutionAuthority` wrapped in a counter.
The `root_resolver` is Host-realistic: it reads the S4 binding head
(`WorkspaceBindingAuthorityStore.current_receipt`) and returns
`(head.appended_root.root_id, head.root_identity_hashes[0])`.

## Trimmed actual output

```
[A] exception: TaskExecutionAuthorityError('sdk_task_execution_route_authority_missing')
[A] handler calls: ['context_route']
[A] write_file handler invocations: 0
[A] issue_envelope requests: 2 errors: ['sdk_task_execution_route_authority_missing']
[A] write_file tool messages: []
[A] checkpoint route_state: routed_standalone phase: tool_batch_reserved

[A2] write_file tool messages: ['{"error_code":"ROUTE_BARRIER_NOT_OBSERVED","outcome":"rejected",
      "public_message":"Observe a Context route before executing this Tool.","value":null}']
[A2] handler calls: [] issue_envelope requests: 0

[A3-same-batch] write_file tool messages: ['{"error_code":"ROUTE_BARRIER_NOT_OBSERVED", ...}']

[B] issue_envelope tool_names: ['context_route', 'write_file', 'write_file']
[B] envelope: {'schema_version': 1, 'run_id': 'run-spike-a3', 'call_id': 'call-47d7…', 'effect_id': 'effect-47d7…',
    'raw_call_id': 'raw-write', 'turn_ordinal': 2, 'call_ordinal': 0, 'tool_name': 'write_file',
    'capability_id': 'builtin:write_file', 'capability_fingerprint': 'dddd…',
    'route_receipt_id': '1c3a93f1-…', 'route_receipt_hash': 'b9984fb6…',
    'task_scope_id': '322eb89c-b858-5671-a57a-4750a633b2a8',
    'root_id': 'root-322eb89c-b858-5671-a57a-4750a633b2a8', 'root_identity_hash': '8f7bf073…',
    'binding_set_revision': 1, 'binding_set_receipt_id': 'e79847b4-…', 'binding_set_receipt_hash': '953c01ce…',
    'idempotency_key': 'effect-47d7…'}
[B] verify_task_execution_envelope -> root-322eb89c-b858-5671-a57a-4750a633b2a8 1

[C:task_execution_envelope] write_file tool messages: ['{"error_code":"MODEL_AUTHORITY_FIELD_FORBIDDEN", ...}']
[C:binding_set_revision]    write_file tool messages: ['{"error_code":"MODEL_AUTHORITY_FIELD_FORBIDDEN", ...}']

[D] exception: TaskExecutionAuthorityError('sdk_task_execution_root_authority_unavailable')
[D] handler calls: ['context_route']
7 passed in 1.72s
```

## PASS/FAIL per sub-assumption

| # | Claim | Verdict | Observed |
|---|-------|---------|----------|
| (a) | In `routed_standalone`, SDK rejects `write_file` with `ROUTE_BARRIER_NOT_OBSERVED`-class rejection, handler not called, no ledger row | **PASS on the invariant, FAIL on the literal code path** | Handler NOT called (0 invocations), no TOOL message appended, no effect prepared. BUT the rejection is **not** a model-visible `ROUTE_BARRIER_NOT_OBSERVED` `ToolResult.rejected`. In `routed_standalone` the SDK preflight passes (barrier only fires on `UNROUTED` or same-batch CONTEXT_CONTROL), then `EffectBatchExecutor.execute` calls `issue_envelope` and the **Host** `ProductTaskExecutionAuthority` raises `TaskExecutionAuthorityError('sdk_task_execution_route_authority_missing')`, which **propagates out of `ReActLoop.run`** (no `except` anywhere in `react_loop.py`). The Run is left at checkpoint `phase=tool_batch_reserved, route_state=routed_standalone`. See "Facts" below for what this means. |
| (a′) | Variant: `write_file` while `UNROUTED` (first turn) | PASS | `ROUTE_BARRIER_NOT_OBSERVED` as a rejected ToolResult in the TOOL message; handler not called; `issue_envelope` NOT called; run ends `routed_standalone` via no-recall sink. |
| (a″) | Variant: `context_route` + `write_file` in the same batch | PASS | `ROUTE_BARRIER_NOT_OBSERVED`; only `context_route` executes. |
| (b) | `ROUTED_TASK` + `root_resolver` -> `issue_envelope` per call, envelope with six TaskScope fields reaches handler as `context.task_execution_envelope` | **PASS** | `issue_envelope` called for every call that has a policy (`['context_route','write_file','write_file']` — note it is called for CONTEXT_CONTROL too, with `route_receipt=None`). Both `write_file` handler invocations received a `TaskExecutionEnvelope` with `task_scope_id`, `root_id`, `root_identity_hash`, `binding_set_revision`, `binding_set_receipt_id`, `binding_set_receipt_hash` all populated and equal to the S4 binding head; `context.call_id == envelope.call_id`, `context.effect_id == envelope.effect_id`, `idempotency_key == effect_id`. Bonus: the real Host S4 `WorkspaceBindingAuthorityStore.verify_task_execution_envelope(envelope, frozen_route_receipt)` accepts it. |
| (c) | Model-supplied `task_execution_envelope` / `binding_set_revision` -> `MODEL_AUTHORITY_FIELD_FORBIDDEN` | **PASS** | Both keys produce a rejected ToolResult with `error_code=MODEL_AUTHORITY_FIELD_FORBIDDEN`; handler not called; `issue_envelope` not called for that call. (Public message is the generic "Observe a Context route…" string — the SDK reuses one message for all preflight rejections, `react_loop.py:537-541`.) |
| (d) | `root_resolver=None` -> `sdk_task_execution_root_authority_unavailable`, handler not invoked | **PASS** (same caveat as (a): it is an exception, not a rejection) | `TaskExecutionAuthorityError('sdk_task_execution_root_authority_unavailable')` raised from `issue_envelope`, escapes `ReActLoop.run`; handler not invoked; `issue_envelope` requests `['context_route','write_file']`. |

## Call chain observed (SDK 0.7.1 frozen source / Host)

1. `ReActLoop.run` → `_preflight_tool_batch(...)` — `simple_harness/runtime/drivers/react_loop.py:451-457` calling `:660-695`.
   - `:672` `policy = tool_exposure.execution_policy(run_id, call.name)` (Host exposure).
   - `:682-683` any key in `_HOST_ONLY_ARGUMENTS` (`:648-657`: `task_execution_envelope, route_receipt, binding_set_revision, binding_set_receipt_id, binding_set_receipt_hash, root_identity_hash`) → `MODEL_AUTHORITY_FIELD_FORBIDDEN`.
   - `:687-694` `route_requirement is REQUIRED and route_state is UNROUTED` → `ROUTE_BARRIER_NOT_OBSERVED`; also when the same batch contains a CONTEXT_CONTROL call. **No rule for `ROUTED_STANDALONE`.**
2. `:519-541` per call: if a preflight rejection exists → `ToolResult.rejected(internal_call_id, code, "Observe a Context route before executing this Tool.")` (never touches `services.tools`); else `self._effects.execute(..., route_receipt=_checkpoint_route_receipt(state, run_id))`.
3. `EffectBatchExecutor.execute` → `one()` — `react_loop.py:122-195`:
   - `:130-146` `envelope = await services.task_execution_authority.issue_envelope(TaskExecutionEnvelopeRequest(run_id, internal_call_id, effect_id, raw_call_id, turn_ordinal, call_ordinal, tool_name, policy, route_receipt))` — called for **every** call with a non-None policy (CONTEXT_CONTROL included).
   - `:147-161` exact-identity checks (`RuntimeError("Host TaskExecutionEnvelope differs from exact effect")`).
   - `:166-179` PROJECT_EFFECT: requires `route_receipt.route_state is ROUTED_TASK` and the four binding fields to match, else `RuntimeError("project TaskExecutionEnvelope has stale TaskScope binding authority")`. (In (a) the Host authority raised first, so this SDK check was not the one that fired.)
   - `:177-178` PROJECT_EFFECT with no `task_execution_authority` → `RuntimeError("project effect requires Host TaskExecutionEnvelope authority")`.
   - `:179-195` `services.tools.execute(effect_id=..., call=ToolCall(...), context=ToolContext(run_id, request_id, cancellation, call_id=internal_call_id, effect_id=effect_id, task_execution_envelope=envelope), ...)`.
4. Host `ProductTaskExecutionAuthority.issue_envelope` — `backend/deskpet/sdk_adapters/task_execution.py:44-95`:
   - `:56-65` PROJECT_EFFECT with receipt lacking task_scope/binding fields → `TaskExecutionAuthorityError("sdk_task_execution_route_authority_missing")` (this is what fires in (a): a `direct_standalone` receipt has `task_scope_id=None`).
   - `:67-70` `root_resolver is None` → `sdk_task_execution_root_authority_unavailable` (d).
   - `:71` `root_id, root_identity_hash = await self._root_resolver(receipt)` (receipt is the SDK `ContextRouteReceipt`; fields used: `task_scope_id`, `binding_set_revision`, `binding_set_receipt_id`, `binding_set_receipt_hash`).
5. `ToolContext.task_execution_envelope` — `simple_harness/tools/contracts.py:115`, validated `:131-142` (must match run/call/effect).
6. Durable ledger (not exercised here because the spike's executor returns `EffectExecution(effect=None, ...)` like the Host milestone test): the real `simple_harness/tools/executor.py:426-441` calls `uow.prepare_effect(..., task_execution_envelope=context.task_execution_envelope)` → `execution/sqlite/uow.py:5263-5313` persists `task_execution_envelope_json/_hash` on `execution_effects` (schema `execution/sqlite/schema.py:26-28`). Because both rejection and authority failure happen **before** step 3's `services.tools.execute`, no `prepare_effect` row can exist in any of (a),(a′),(a″),(c),(d).

## Facts the implementer must know

1. **(a) as literally stated is not how the SDK behaves.** In `routed_standalone`, the SDK does not emit a model-visible barrier rejection for a PROJECT_EFFECT tool; the Host authority's exception escapes `ReActLoop.run`, aborting the Run mid-batch (checkpoint left in `phase=tool_batch_reserved`). The fail-closed invariant (handler never runs, nothing durable) holds, but the plan must decide what it wants:
   - If the desired UX is "the model sees a rejection and can re-route", the **Host** must do it, because the frozen SDK cannot be changed. Options: (i) have `ProductTaskExecutionAuthority.issue_envelope` / a Host wrapper turn `route_authority_missing` into a rejected `ToolResult` — not possible at that layer (the SDK requires an envelope return or an exception), so (ii) do it earlier in the Host's `RunToolExposurePort.execution_policy` is also wrong (policy is static); realistically (iii) catch `TaskExecutionAuthorityError` at the Host's loop-driver boundary and map it to a terminal/fault state with a user-facing message, or (iv) accept exception-as-fail-closed and document `sdk_task_execution_route_authority_missing` as the observable code. The spike asserts (iv) as observed.
   - If instead the Host authority returned an envelope without TaskScope fields, the SDK itself would raise `RuntimeError("project TaskExecutionEnvelope has stale TaskScope binding authority")` (`react_loop.py:166-179`) — still an exception. There is no SDK path that yields a `ToolResult.rejected` for PROJECT_EFFECT in `ROUTED_STANDALONE`.
2. **Where to set the policy so fingerprints stay consistent.** `SDK_TOOL_EXECUTION_POLICY_OVERRIDES` (`tool_authority.py:62-64`) is consumed only at `tool_authority.py:735-746` when building `ExecutableToolRecord`s inside `prepare_run`. The SDK folds `effect_class/route_requirement/task_scope_requirement` into `ExecutableToolRecord.to_json()` (`runtime_catalog.py:284-294`), which feeds both the per-tool `capability_fingerprint` (`:297-304`) and the catalog `_snapshot_fingerprint` (`:566-575`). So adding `"write_file": ("project_effect", "required", "required")` changes the catalog fingerprint and `write_file`'s capability fingerprint. `ExecutableToolRecord.__post_init__` (`:263-266`) structurally **requires** PROJECT_EFFECT to have `route_requirement=REQUIRED` (and task-scope REQUIRED) — mismatched tuples will raise at prepare time. The override values are the enum `.value` strings (`"project_effect"`, `"required"`). Restored/resumed Runs compare `state.catalog_fingerprint` to the snapshot fingerprint (`runtime_catalog.py:866`) — check `restore_run` (`tool_authority.py:905`) / record version (`SDK_TOOL_AUTHORITY_RECORD_VERSION = 3`) for in-flight Runs across a deploy; the spike did not test that.
3. **`issue_envelope` is called for every tool call that has a policy, including `context_route` (CONTEXT_CONTROL) with `route_receipt=None`, and for NON_PROJECT_EFFECT tools.** A root_resolver is only invoked for PROJECT_EFFECT. Anything the Host resolver does (DB read of the binding head) is on the hot path of every project write.
4. **`ProductEffectExecutor` sees the envelope only indirectly.** It receives the SDK `ToolContext` (`tools.py:344-347` type-checks it) and passes it through to `EffectExecutor.execute` → `prepare_effect` (persisted) → `registry.invoke`. There is no envelope field on the Host `ToolExecutionContext` (`deskpet/tools/capabilities.py:416-446`; built at `tool_authority.py:239-270` with only `call_id`/`effect_id`). Host handlers reach it via `active_product_tool_context()` (`tools.py:197`, contextvar `_current_tool_context` at `:129`) → `.task_execution_envelope`; `context_route.py:123-131` already does exactly this (`context.task_execution_envelope`, `envelope.raw_call_id`, `envelope.turn_ordinal`). Handler signature is `ProductHandler = Callable[[Mapping[str, JsonValue], ToolContext], Any]` (`tools.py:43`), so the second positional arg also carries it.
5. **`ToolContext` field names (SDK `tools/contracts.py:107-115`):** `run_id: RunId`, `request_id: RequestId`, `cancellation`, `metadata`, `workflow_spawn_context`, `call_id: CallId | None`, `effect_id: EffectId | None`, `task_execution_envelope: TaskExecutionEnvelope | None`.
6. **`TaskExecutionEnvelope` field names (SDK `execution/effects.py:72-91`):** `run_id, call_id, effect_id, raw_call_id, turn_ordinal, call_ordinal, tool_name, capability_id, capability_fingerprint, route_receipt_id, route_receipt_hash, task_scope_id, root_id, root_identity_hash, binding_set_revision, idempotency_key, schema_version=1, binding_set_receipt_id, binding_set_receipt_hash`. `to_json()` and `envelope_hash` exist.
7. **Root resolver contract that satisfies both SDK and Host S4 verification:** return `(head.appended_root.root_id, head.root_identity_hashes[0])` from `WorkspaceBindingAuthorityStore.current_receipt(receipt.task_scope_id)` after checking `head.binding_set_revision/receipt_id/receipt_hash` equal the route receipt's. `verify_task_execution_envelope` (`workspace_bindings.py:1168-1203`) then accepts the envelope (`root_id` must equal `authority.root.root_id`). Multi-root binding sets are not single-root; the resolver must fail closed there (spike asserts `len(root_identity_hashes)==1`).
8. Rejection public message is the same string for `MODEL_AUTHORITY_FIELD_FORBIDDEN` and `ROUTE_BARRIER_NOT_OBSERVED` ("Observe a Context route before executing this Tool.", `react_loop.py:539`); only `error_code` differs. Preflight rejections are appended to Context as a TOOL message (`react_loop.py:586-599`), so the model does see them.

## Verdict on A3

**Mostly holds; one sub-assumption is mis-stated.** (b), (c), (d) are verified end-to-end through the real SDK loop with real Host authorities. (a) holds as a fail-closed invariant (handler never invoked, no effect row, nothing model-visible), but the mechanism in `routed_standalone` is a Host `TaskExecutionAuthorityError('sdk_task_execution_route_authority_missing')` escaping `ReActLoop.run`, **not** a `ROUTE_BARRIER_NOT_OBSERVED` rejection. `ROUTE_BARRIER_NOT_OBSERVED` only occurs for `UNROUTED` or same-batch-with-`context_route`. The plan should either accept the exception as the documented (a) behaviour or add Host-side handling at the loop-driver boundary; it cannot obtain a model-visible rejection for this case from the frozen SDK.
