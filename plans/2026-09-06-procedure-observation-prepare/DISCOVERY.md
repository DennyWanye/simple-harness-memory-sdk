# Procedure首次发现公共增量契约

2026-09-06结果更新：固定f03dab0的两个新SDK公共控制2PASS/0.42s；Host有效4项新控（含撤回一项误绿后只修两负控）累计6个唯一控制通过。待Dirac终审与主nonSELF共同出口。准确命令、原失败/撤回、raw hash及PG清理见[Host结果](/Users/denny/projects/simple_harness-corpus-clock/plans/2026-09-06-procedure-adoption/DISCOVERY-RESULTS.md)。本树不build、不更改版本。

2026-09-06，基于da7728b；保留M618及原恢复13项证据。本叶不建表、不改版本、不产独立wheel，后续与nonSELF e500556合并共同出口。

公开keyword方法：`MemoryManager.discover_procedure_drafts(principal, scope, disclosure_context, query, after="", limit=8, max_bytes=32768)`，所有参数keyword-only，返回`ProcedureDraftPage`。Manager将实际默认值一并纳入既有Procedure调用审计，不从oracle、聊天或名称推导权限。backend port同签名。

只接受确切个人owner和可信SELF披露，使用SDK业务时钟。当前head/revision、revision主体、生命周期draft/eligible、分类、冲突、有效期、suppression及全部实际证据来源需满足现有读取门。查询只匹配名称/步骤的literal casefold substring，不作为语义分类器，不替代applicability/使用权限。ACTIVE仍走原正常typed recall。

`ProcedureDraftCandidate.to_json`精确字段：memory_id、revision、name、steps数组、applicability数组、risk_level、lifecycle_state、qualification_epoch、applicability_fingerprint、content_hash。候选hash域`memory.procedure.draft-candidate.v1`。完整合法步骤不截断，Host独立保留16步实际使用限制。

`ProcedureDraftPage.to_json`精确字段：candidates数组、next_after（实际memory_id或null）、scanned、omitted_oversize。page hash域`memory.procedure.draft-page.v1`；operation_observation为独立属性，不纳source_hash。扫描至多128个目标（多读1行判断续页），返回至多8候选；query最多512字节，after最多1024字节，limit=1..8，max_bytes=256..32768，拒绝bool冒充整数。完整page canonical JSON UTF-8不得超max_bytes；过大候选不部分返回，明确计数，继续游标；仅游标也装不下则公开resource-limit拒绝，不冒充无更多。此为返回/扫描边界，不声称SQLite硬CPU时限，来源追溯复用现有4096工作量边界。

`HistoryProcedureDraftBinding(memory_id, revision, candidate_hash)`的to_json另带kind=`procedure_draft`。`check_history_visibility`同快照重建上述实际候选；变化、遗忘、不可见均不能借旧hash通过。现有history binding/snapshot域不改，新kind显式区分；旧v1/v2 Host依赖保持，新增v3只添加procedure_drafts数组。

新操作沿`ProcedureOperationObservationV1`，operation=`discover_procedure_drafts`；request/claimed-owner/invocation/observation hash域仍是既有`memory.procedure.operation.*.v1`。成功source_hash为page hash，拒绝/异常/取消有原规范元数据；没有新业务真相账本。Host sidecar明确登记新operation，本叶不声称旧sealed OA1全量coverage已自动扩展。

待运行2个新SDK控制：实际public创建UNBOUND draft→预览/完整预算/精确历史绑定/forget，以及非SELF/非法界限/无匹配；Host另有3个实际运行控制。新方法及联合消费待Dirac与资源槽，未计入既有绿色验收。真实工具失败的公共prepare/record已支持FAILURE+attributable=False，本次SDK不放宽该协议。

联合边界：主已发现current-input request hash白名单及对应Host审计缺新增HistoryProcedureDraftBinding，正在共同source树补同wire/hash域的类型覆盖。本f03源码及以上6项不包含该组合修订，不能视为新制品/跨权限联合已验。
