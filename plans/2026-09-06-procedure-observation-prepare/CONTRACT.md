# Procedure 公开观察预备接口（源码候选）

2026-09-06。自有原Memory树 `feat/procedure-observation-prepare`；M618 wheel/旧证据不变。e84e334六项公共新控通过；f82c2b8再由Host三Scope真实source-only交叉原红→绿验证。未独审、构建或分配后继制品。

公开 `MemoryManager.prepare_procedure_observation(*, principal, scope, observation_id, target_memory_id, target_revision, kind, applicability, hazard, task_scope_id, evidence_span, terminal_receipt_id, terminal_receipt_hash, outcome, attributable, observed_at, run_id, operation_id)`；当前后继返回 `PreparedProcedureObservation(intent, operation_observation)`，其中intent为既有 Harness `ProcedureObservationIntent`；不返回authority/ref，不写观察或递增资格。subject、risk、transition_from/to由实际持久owner、当前revision和SDK资格算法给出，不允许调用者覆盖这些参数。

预备与 `record_procedure_observation` 共享同一个内部决策函数。预备在事务内核exact owner/scope/revision及合法evidence、同Scope注册工具回执、非未来时间，计算当前qualification epoch/applicability与90天窗口；原3次/低风险可逆规则不改，原消费再次计算并校验expected transition。旧authority、receipt、DDL及hash不改。

Host仍负责真实Procedure使用和完整步骤终态归因；SDK预备结果不能作为使用证明或effect许可。Host必须先持久实际来源与原authority/ref再调用公开消费，lost ACK重用原ref。并发revision变化要求重新读取实际source，不猜transition、不轮流提交错误intent试探。调用成功/拒绝/取消通过既有observability sink记录operation及无原始payload的状态；Host完整operation审计接线属于同一后续生产叶，不能仅凭SDK sink声称全栈OA通过。

已执行两项新增源控：真实公开预备→Host测试authority→公共消费三独立Scope，预备无消费/重复稳定/旧revision拒绝；错误工具终态hash与foreign Scope拒绝。真实Host的application binding、三Scope与执行前drift另有必要控制，不能由这两项SDK控替代。

后继同时新增 `MemoryManager.read_procedure_use_target(*, principal, scope, memory_id, revision)`，返回公开根导出的 `ProcedureUseTarget`。字段为 memory_id、revision、lifecycle_state、risk_level、qualification_epoch、applicability_fingerprint、bound_hazard、step_hashes（有序tuple）及派生source_hash；`to_json()`不含派生hash，hash domain为 `memory.procedure-use-target.v1`，body为 `{domain,value:to_json()}`。这是属主内部精确使用核验元数据，不含原始步骤、不发披露或effect许可，也不作为给模型的上下文。

读取核实际owner/scope/current revision、有效时间、未争议状态、restricted拒绝和来源suppression；步骤/风险/适用性正文须与canonical revision及content hash一致。Host不得从显示用Twin或模型自报值代替此读数。新增两控只测exact读/异主体与过期revision拒绝/无raw步骤、临时测试库typed正文篡改拒绝；已经通过。已有预备控把resolver调用数断言改为本次调用前后差值，不依赖旧消费内部调用次数。

与Hegel的input_visibility叶各自独立源码，manager、core/port.py及根导出只合并各自方法/import小段；版本由主统一，源码整合与独审后才一次制品冻结。本候选没有改M618 wheel，没有新增schema或安装。


审计后继：公开根 `ProcedureOperationObservationV1` 明确operation（仅prepare_procedure_observation/read_procedure_use_target/record_procedure_observation）、invocation_ref_hash、request_hash、claimed_owner_ref_hash、source_hash、outcome、reason、observed_at、persistence_status、schema_version及派生observation_hash。`to_json`排除observation_hash；domain分别为 `memory.procedure.operation.observation.v1`、`.request.v1`、`.claimed-owner.v1`、`.invocation.v1`，均SHA256(canonical({domain,payload}))。request包含operation、scope和本次完整公开参数的规范值；不记录原始正文，超界/无效自定义类型的绑定为null，不伪称可核验。时间是物理观察时间，不是业务观察的occurred_at。

prepare的新包装仅用于这份未发布后继，Host从`.intent`取原协议。read target与record result增加可选operation_observation（不参与相等、原to_json及source/result hash）；record旧持久wire/receipt/hash不变，重放业务result相同但调用invocation不同。成功返回、拒绝、普通错误与取消都通过既有sink记录；异常原类型保留，并附同一公开DTO。没有公共eligibility独立方法，资格计算是prepare的一部分。

Host直接调用包装将捕获这些公开DTO，并复用既有memory_call_attempts sidecar核operation/request/owner/实际返回intent或result commitment，不新增业务事实表。SDK旧OA1 sealed page的九个family尚不含Procedure生命周期，不能把本次per-call记录说成旧历史全面覆盖、不可丢事件或已有sealed持久授权。原生/生产组合与完整coverage未验。新增观察控制仅针对本次成功、exact replay、拒绝、错误、取消与Host operation替换，不重复旧audit套件。

## 当前 source-only 交叉修正与边界

f82c2b8仅Procedure允许实际source-only S1 receipt，经现有 `_read_ingested_record` 核完整envelope、items、单一admission模式与真实receipt hash，再保留exact span/Scope/terminal门；普通mutation full ingestion门不改。Host原红 `mutation_evidence_span_not_admitted` 已由三真实Scope调用公共prepare/record转绿，未制造tool分析任务。

SDK六项原绿：本树 `.local-test-evidence/2026-09-06/procedure-scope/sdk-r1`，PG8385 exit0／1.081s／峰119200KiB／remaining=[]。Host交叉：`/Users/denny/projects/simple_harness-corpus-clock/.local-test-evidence/2026-09-06/procedure-scope/host-r6`，1PASS9.53s，PG11070 exit0／remaining=[]。详细命令/原红/hash在Host `plans/2026-09-06-procedure-adoption/SCOPE-RESULTS.md`；不是installed或native证明。新 test_procedure_source_admission.py 两项及Host scope sources两项尚未运行；主native占共享槽，不重复旧绿。

Hegel固定SDK e500556，由主统一整合后版本/build；本树保留，不cherry其源码、不产独立包。Host过期未消费authority恢复、并发旧revision、drift反控、草稿发现及失败归因未闭合；F01延期。
