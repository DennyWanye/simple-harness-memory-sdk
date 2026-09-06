# Procedure 公开观察预备接口（源码候选）

2026-09-06。自有原Memory树 `feat/procedure-observation-prepare`；M618 wheel/旧证据不变。本叶尚未测试、独审、构建或分配后继制品。

公开 `MemoryManager.prepare_procedure_observation(*, principal, scope, observation_id, target_memory_id, target_revision, kind, applicability, hazard, task_scope_id, evidence_span, terminal_receipt_id, terminal_receipt_hash, outcome, attributable, observed_at, run_id, operation_id)`；返回既有 Harness `ProcedureObservationIntent`，不返回authority/ref，不写观察或递增资格。subject、risk、transition_from/to由实际持久owner、当前revision和SDK资格算法给出，不允许调用者覆盖这些参数。

预备与 `record_procedure_observation` 共享同一个内部决策函数。预备在事务内核exact owner/scope/revision及合法evidence、同Scope注册工具回执、非未来时间，计算当前qualification epoch/applicability与90天窗口；原3次/低风险可逆规则不改，原消费再次计算并校验expected transition。旧authority、receipt、DDL及hash不改。

Host仍负责真实Procedure使用和完整步骤终态归因；SDK预备结果不能作为使用证明或effect许可。Host必须先持久实际来源与原authority/ref再调用公开消费，lost ACK重用原ref。并发revision变化要求重新读取实际source，不猜transition、不轮流提交错误intent试探。调用成功/拒绝/取消通过既有observability sink记录operation及无原始payload的状态；Host完整operation审计接线属于同一后续生产叶，不能仅凭SDK sink声称全栈OA通过。

两项新增源控待独审后运行：真实公开预备→Host测试authority→公共消费三独立Scope，预备无消费/重复稳定/旧revision拒绝；错误工具终态hash与foreign Scope拒绝。真实Host的application binding、三Scope与执行前drift另有必要控制，不能由这两项SDK控替代。

后继同时新增 `MemoryManager.read_procedure_use_target(*, principal, scope, memory_id, revision)`，返回公开根导出的 `ProcedureUseTarget`。字段为 memory_id、revision、lifecycle_state、risk_level、qualification_epoch、applicability_fingerprint、bound_hazard、step_hashes（有序tuple）及派生source_hash；`to_json()`不含派生hash，hash domain为 `memory.procedure-use-target.v1`，body为 `{domain,value:to_json()}`。这是属主内部精确使用核验元数据，不含原始步骤、不发披露或effect许可，也不作为给模型的上下文。

读取核实际owner/scope/current revision、有效时间、未争议状态、restricted拒绝和来源suppression；步骤/风险/适用性正文须与canonical revision及content hash一致。Host不得从显示用Twin或模型自报值代替此读数。新增两控只测exact读/异主体与过期revision拒绝/无raw步骤、临时测试库typed正文篡改拒绝；尚未执行。已有预备控把resolver调用数断言改为本次调用前后差值，不依赖旧消费内部调用次数。

与Hegel的input_visibility叶各自独立源码，manager、core/port.py及根导出只合并各自方法/import小段；版本由主统一，源码整合与独审后才一次制品冻结。本候选没有改M618 wheel，没有新增schema或安装。
