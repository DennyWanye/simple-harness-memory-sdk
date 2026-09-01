# Host 接线事实（调查代理 2026-09-01）

- 三 slot（sdk_run_context_authority/sdk_runtime_decision_sink/sdk_task_execution_authority）：context.py:122-124/276-278 声明，全仓零 register；proxy main.py:7659-7683 恒抛 *_unavailable；负测试 test_composition.py:319-324。
- `_sdk_runtime_authority_bindings()`（main.py:7686-7694）唯一消费点 = **splat 进 ProductionRuntimeConfig**（main.py:8370，production_runtime_factory 内）；不进 ports_factory。
- ProductSdkRuntimeStack 构造 main.py:8388-8405（paths/candidate_identity/dependency_loader/ready_publisher）；ports_factory 内 8284 注册 sdk_context_staging。
- 关键推论：tool_exposure 恒非 None + authority proxy 恒非 None ⇒ 当前 SDK 0.7.1 生产链**每个工具调用都会打 issue_envelope→unavailable**，每个 provider turn 都会打 prepare_snapshot→unavailable——与 plan P0 调查结论一致（authority 路径从未走通）。Task 1 注册实装即修此 P0。
- `_prepare_sdk_context_snapshot` main.py:11434-11621；唯一生产调用 9860（memory_items=None）；消息装配序 context_preparation.py:210-395（persona→memory(user,untrusted)→skills→project rules→project snapshot→history→current user）；history=_bounded_sdk_history(main.py:11392-11430, newest-first 硬断)；催化剂 compact_at=window*0.8、reserved 计算 11536-11556。
- temperature/max_output_tokens 不在 snapshot 面（藏在 provider_binding.model_params opaque dict）。
- continuation 链 main.py:9005/9049-9075：32k 硬编码、_truncated 丢弃、无 PreparedSnapshot；payload={"schema_version":1,"provider_messages":[*history,current],...} 经 context_sources.put_pending。
- ingress.start（sdk_adapters/ingress.py:101-117）有 initial_route_receipt/_hash 参数（默认 None）；chat 链 main.py:11760-11783 不传 ⇒ UNROUTED。S4 HOST_INITIAL 样板 foreground_runtime.py:571-604（receipt_id=_uuid(...)、run_id=sdk_run_id、v3、host_authority_ref/hash=admission receipt；verify_initial_route :604；start_request_hash 折叠 653-658；ingress 传参 778-779）。
- 迁移登记三件套（migrator.py）：schema_migrations 表（:838-842）+ MIGRATION_STEPS dict（:137-160，037→45）+ PRAGMA user_version（:843-845）；另 HUMAN_MEMORY_PROGRAM_MIGRATIONS（:120-132）、human_memory_migration_chain 标记插入（:828-841 区）、_register_recovery_tables（:245）、常量 FOREGROUND_EXECUTION_*=116-117、HUMAN_MEMORY_TARGET_SCHEMA_VERSION=:119（44→45）。文件禁 BEGIN/COMMIT/PRAGMA（:307-323）；结构=marker 表+CHECK(length=64)+UNIQUE 幂等+append-only 触发器（036 样板）。
- head CAS 纪律：033 触发器（*_no_update/_no_delete + heads_guard 状态对+transition 换新）；写函数样板 record_terminal foreground_queue.py:1852-1993（BEGIN IMMEDIATE→validate lease→append transition(canonical_hash payload)→append receipt→head UPDATE 带 WHERE state 谓词→fault hook→commit）；幂等重放样板 record_start_intent :1030-1110。连接 helper :2729-2734（row_factory、FK ON、busy_timeout 5000）。
- verify_memory_candidate：sdk_candidate.py:125-145（wheel sha/version/direct_url 四检）。
- Host ExecutableToolRecord 不传 effect_class/route_requirement ⇒ 全部默认 NON_PROJECT_EFFECT/OPTIONAL/OPTIONAL（runtime_catalog.py:211-213）；tool_effect_policy_manifest.json 是无关税目。授权轨（SdkPreparedAuthorizationPolicy tool_authority.py:1370/1519…）与 envelope 轨互不相知；物理执行 ProductEffectExecutor tools.py:353-368。

# S4 TaskScope API 面（Task 2 消费，调查代理已核 file:line）
- 搜索 facade：HumanMemoryHostService.search_task_scopes(SearchTaskScopesRequest(query,max_candidates=8,cursor)) human_memory_service.py:873；subject/allow-set 结构注入（:874/_owned_scope_ids:1630），API 层拒绝 caller 传 subject（human_memory_api.py:31-57）；候选={scope_ref,source_ref,source_hash,title,goal,project,status,snippet,rank}。错误码 human_memory_search_*。
- open facade：open_task_scope(OpenTaskScopeRequest(scope_ref,live_probe,expected_source_hash)) :903 → {scope_ref,receipt_ref,source_ref,source_hash,resume_package(≤24KiB),resume_sha256,receipt_hash,drift_report}；resume_package 含 binding_set_revision+binding_receipt_hash **但无 binding_set_receipt_id**（search.py:440-441）→ 需 WorkspaceBindingAuthorityStore.current_receipt(task_scope_id)（workspace_bindings.py:1205）补 id。permission_denied/task_scope_source_stale/task_scope_not_found。
- create facade：create_task_scope(CreateTaskScopeRequest(fixture_key,title,goal,idempotency_key)) :442，id=uuid5 派生，revision=1；provisioner 未接生产。binding 写入 = append_binding/manual propose+decide（runtime_binding_authority.py），MANUAL 模式返回 authorization_required。
- verify_route_binding（workspace_bindings.py:1137）：四元组必齐 + 不可变 revision 行 byte-match（不读 head）→ workspace_binding_route_authority_missing/stale。
- **无 durable active cursor**（authority_snapshot 硬编码 None :1534）；foreground 的 run head 是事实 cursor（current_snapshot :1996）。
- chat 链 subject：main.py:14388 AuthenticatedHostSnapshot(subject="deskpet-local-owner-v1",principal_id="local-control-channel",authority_ref="host:validated-control-channel:v1") 硬编码样板；sdk_adapters 层无来源。
- slot：human_memory_host_service_factory（main.py:3160，非 HUMAN epoch = None）→ factory.bind(auth) 得 facade。

# Task 2 裁决决策（补充设计冻结）
- resume 内容进 Context 的通道：SDK 解码取 value.get("context_route_receipt", value) ⇒ 成功结果 = {"context_route_receipt": receipt.to_json(), "resume_package": {...}}——resume 内容以工具结果消息进 context port，被下一 provider turn 的 authority snapshot 自然纳入（同 Run continuation 的价值链闭合点）。
- 路由 receipt 的 binding 四元组一律取 current_receipt() head（并与 resume_package.binding_set_revision/hash 比对，漂移→稳定 rejected task_scope_binding_stale）；verify_route_binding 复核不可变行。
- continue_active（无 cursor 的 S5a 裁决）：active = v45 context_route_decisions 最近一条 ROUTED_TASK 决策（单用户产品边界内成立；闲聊 standalone 不写 ROUTED_TASK ⇒ cursor 不被污染的不变量自然保持）；foreground current_snapshot 存在时优先。proposal 带 task_scope_id 时必须与 active 相等，否则 rejected；无 active → rejected context_route_no_active_task_scope。
- create_new：create_task_scope（幂等）→ append_binding（经 human_memory_binding_append_authority slot；authorization_required → 稳定 rejected，scope 已建为可接受幂等中间态）→ current_receipt → receipt。
- 非 HUMAN epoch / factory=None → context_route 稳定 failed context_route_composition_unavailable。
