# Procedure 公开观察预备接口（源码候选）

2026-09-06。自有原Memory树 `feat/procedure-observation-prepare`；M618 wheel/旧证据不变。本叶尚未测试、独审、构建或分配后继制品。

公开 `MemoryManager.prepare_procedure_observation(*, principal, scope, observation_id, target_memory_id, target_revision, kind, applicability, hazard, task_scope_id, evidence_span, terminal_receipt_id, terminal_receipt_hash, outcome, attributable, observed_at, run_id, operation_id)`；返回既有 Harness `ProcedureObservationIntent`，不返回authority/ref，不写观察或递增资格。subject、risk、transition_from/to由实际持久owner、当前revision和SDK资格算法给出，不允许调用者覆盖这些参数。

预备与 `record_procedure_observation` 共享同一个内部决策函数。预备在事务内核exact owner/scope/revision及合法evidence、同Scope注册工具回执、非未来时间，计算当前qualification epoch/applicability与90天窗口；原3次/低风险可逆规则不改，原消费再次计算并校验expected transition。旧authority、receipt、DDL及hash不改。

Host仍负责真实Procedure使用和完整步骤终态归因；SDK预备结果不能作为使用证明或effect许可。Host必须先持久实际来源与原authority/ref再调用公开消费，lost ACK重用原ref。并发revision变化要求重新读取实际source，不猜transition、不轮流提交错误intent试探。调用成功/拒绝/取消通过既有observability sink记录operation及无原始payload的状态；Host完整operation审计接线属于同一后续生产叶，不能仅凭SDK sink声称全栈OA通过。

两项新增源控待独审后运行：真实公开预备→Host测试authority→公共消费三独立Scope，预备无消费/重复稳定/旧revision拒绝；错误工具终态hash与foreign Scope拒绝。真实Host的application binding、三Scope与执行前drift另有必要控制，不能由这两项SDK控替代。
