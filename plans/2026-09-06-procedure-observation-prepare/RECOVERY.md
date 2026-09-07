# Procedure 公开恢复选项（未发布源码）

2026-09-06。基线db7ca22，根导出PROCEDURE_OBSERVATION_RECOVERY_VERSION=1仅表示接口能力，不是权限。

`read_procedure_use_target(..., allow_observation_rebase=False)`；`prepare_procedure_observation(..., allow_observation_rebase=False, previous_reference=None)`。省略参数保持原请求hash与严格revision行为；显式新参数纳入现operation request/observation，不新造审计表。旧record receipt/wire/hash、schema及M618制品不变。

rebase在同SDK写事务证明最多128个连续revision全部来自真实observation consumption/result，owner/完整定义/qualification epoch一致。previous_reference经真实Host resolver回读，旧意图完整来源/Run/operation固定；SDK确认未消费且到期或真实目标/资格变化才允许新prepare。仍可用、已消费或更换来源均拒绝；prepare不签grant。Host先重放原record，在自己的增量54日志持久续期尝试。prepare及最终消费均核当前目标/来源suppression；已有receipt重放仍按原协议。

978ae99新三控通过0.53s：真实observation链与REVISE、旧ref过期续期/已消费、prepare后forget。Host恢复/并发/drift另验，不重跑SDK原绿，不独立版本/build。Host准确契约：/Users/denny/projects/simple_harness-corpus-clock/plans/2026-09-06-procedure-adoption/RECOVERY.md。

Host ea63ddc6/c76da29c后继9新控分批通过，含未消费过期重开、已消费lostACK原ref、旧revision独立Scope、同Scope拒绝、真实工具/目录漂移零文件、高risk及54完整校验/timer；原四夹具失败保留，修复只重跑四红。末PG21115 exit0/remaining=[]，锁释放。未获本恢复叶独审，不构建。

准确结果/源码/原日志SHA：[/Users/denny/projects/simple_harness-corpus-clock/plans/2026-09-06-procedure-adoption/RECOVERY-RESULTS.md](/Users/denny/projects/simple_harness-corpus-clock/plans/2026-09-06-procedure-adoption/RECOVERY-RESULTS.md)。
