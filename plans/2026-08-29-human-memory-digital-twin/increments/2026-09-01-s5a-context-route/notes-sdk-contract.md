# SDK 0.7.1 authority 契约事实（调查代理 2026-09-01，file:line 已核）

## prepare_snapshot（react_loop.py:298，唯一调用点）
- 前置：services.run_context_authority 非 None（286）；发生在 before_provider 预留 turn ordinal 后、任何 durable 写与 provider 调用前。
- Request 字段来源：run_id=value.run_id；provider_turn_ordinal=state.provider_turns_reserved_total（termination.py:301-305 自增）；prior_context_revision=services.context.load(run_id).revision（278）；route_state=state.route_state；route_receipt=_checkpoint_route_receipt（697-708 反解+血缘校验）；tool_catalog_fingerprint=_tool_catalog_fingerprint（720-739，优先 tool_exposure.checkpoint 的 catalog_fingerprint）。
- 返回校验：血缘回声 310-315（"lineage differs"）；revision 严格递增 316-317（"revision is stale"）；同 snapshot_id 不换 payload 318-325；② request fingerprint（用 snapshot 材料重建 ProviderRequest 328-335 → provider_request_fingerprint，provider_invocations.py:95-113，request_id 不进 fingerprint）vs ③ expected：336-339（"request fingerprint differs"）。
- receipt 入 checkpoint：340-355 replace state + 356-358 checkpoint.cas（durable 写点）→ 375 _verify_context_authority_receipt（742-765：①vs冻结绑定758、①vs②762、③vs②763）→ 376 provider.invoke。checkpoint 二次自校验 termination.py:264-293。
- 全部失败 = 裸 RuntimeError；Host 异常透传（timeout 在 provider 前逃逸）。

## record_no_recall（react_loop.py:477，唯一）
- 条件：终局轮（无 tool_calls，466）∧ route_state=="unrouted"（474）∧ sink 非 None；有 authority 无 sink → 终局轮 RuntimeError("…requires a no-recall decision sink")（467-473）。构造期无组合校验（kernel.py:661-714 缺口，上游反馈项）。
- 入参：run_id、provider_turn_ordinal=provider_turns_reserved_total、request_fingerprint=state.provider_request_fingerprint（keyword-only）。
- 返回校验 482-487：同 run ∧ route=DIRECT_STANDALONE ∧ recall_refs 空。receipt origin 默认 CONTEXT_TOOL ⇒ raw_call_id/effect_id 必填（占位串合法，fake 用 "terminal-direct"）。
- 之后 488-507：route_state=routed_standalone、receipt 入 state、CAS 落盘、返回 ReActResult。

## issue_envelope（react_loop.py:134）
- 触发：工具有 ToolExecutionPolicy（不限 PROJECT_EFFECT）∧ authority 非 None；PROJECT_EFFECT 无 authority → RuntimeError（177-178）。
- 校验：9 项身份回声 147-158；route receipt 绑定 159-163；PROJECT_EFFECT 需 ROUTED_TASK + 四项绑定与当前 receipt 一致 164-176；idempotency_key==effect_id（effects.py:120-121）；capability_fingerprint 必填 SHA-256；TaskScope 授权六元组全有或全无（effects.py:151-162，含 root_id/root_identity_hash）；SDK 不校验 root_id 内容——多 root fail-closed 属 Host（workspace_binding_protocol.py:38-49/1118-1132/1196-1200）。

## 注入面
- RuntimePorts（kernel.py:657-659）三字段可选默认 None → RuntimeServices（1444-1446）。
- ProductionRuntimeConfig（production.py:91-93）三字段必填（125-131 缺失 TypeError）→ build_production_runtime 218-220。

## Host 实现参考（fake：tests/integration/runtime/test_human_memory_react_barrier.py）
- prepare_snapshot：messages 非空必需；tools 必须=loop 真用的 ProviderToolSpec（进 fingerprint）；expected_request_fingerprint=用同 materials 造 ProviderRequest(RequestId("hash-only"))再 provider_request_fingerprint（215/745）；metadata 任意 Mapping 但须与算 fingerprint 的同份；回声 run_id/turn/prior_revision；snapshot_revision 逐轮严格递增；source_revisions=str→非负int；RunContextSnapshot 12 positional 参数（context_authority.py:298-312）。
- NoRecallSink：test:219-229。TaskExecutionAuthority：test:779-801（身份回声+route 透传+root 自造）。
- CONTEXT_CONTROL 工具返回：ToolResult.succeeded(call.call_id, receipt.to_json())，raw_call_id=values["raw_call_id"]、effect_id=context.effect_id.value（758-772）。
- policy 表样板 test:84-121：context_route=CONTEXT_CONTROL/FORBIDDEN/FORBIDDEN；checkpoint() 返回 catalog_fingerprint。

## route receipt 解码与 barrier
- 解码 react_loop.py:711-717（value.get("context_route_receipt", value)）；血缘 556-561；同批 route+project-effect 拒绝 684-694（ROUTE_BARRIER_NOT_OBSERVED，preflight 在 assistant 消息入 Context 前 451-457）；Host-only 字段黑名单 648-657。
- SDK 侧缺口（上游反馈，不在本增量修）：①构造期 authority⇒sink 组合校验缺失；②工具返回值无 size/depth/cycle 边界（schema.py:74-141 只管入参）→ Host route handler 须自防超长/深载荷。

## signal_conversation+prepared_context
- kernel.py:1132-1210；无 memory 时三件套必齐（1195-1196）；hash 恒等式 start_snapshot.py:223-231/319-323（context_stage_hash=sha256(canonical_json(prepared_context))）；回注 react.py:148-169（provider_messages ≥2 条，最后一条必须 == conversation envelope message canonical）；组合门禁 kernel.py:2450-2459。
