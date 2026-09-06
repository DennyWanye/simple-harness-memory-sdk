# SDK 7.3 invalidation终局实现：源码交接

2026-09-06。按[已接受的执行边界](未注册invalidation-patch边界.md)实施SDK部分，原边界文件保留。本叶不使用plan-test流程。基线2553bd6；版本字符串预留0.6.17，仅源码候选，未构建、未安装、未独审。原M616制品/native候选不改，Host52由主实施。

## 公开调用和类型

```python
source = await memory.read_prospective_outbox_source_v2(
    principal=principal, outbox_id=entry.outbox_id, payload_hash=entry.payload_hash)
result = await memory.settle_prospective_invalidation(
    principal=principal, outbox_id=entry.outbox_id, payload_hash=entry.payload_hash,
    expected_source_hash=source.source_hash)
```

返回严格联合 `RegistrationRequiredView | ProspectiveInvalidationNotRequiredReceipt`，均根导出。两者共同字段：deployment_id、household_id、subject、outbox_id、outbox_payload_hash、outbox_created_at、memory_id、target_revision、registration_revision、trigger_hash、target_source_hash、schema_version=1。取消身份使用历史目标，不读当前head/时钟猜来源。

- `RegistrationRequiredView.kind="registration_required"`：另含真实 `registration_entry: OutboxEntryV1`，包括原payload及当前持久投递状态；payload递归不可变。所有状态的登记请求都算存在，未ACK、dead_letter也不能not_required。不保证Host已经登记、不带grant。
- `ProspectiveInvalidationNotRequiredReceipt.kind="not_required"`：另含receipt_id、signal_result_id/hash、checked_at、reason固定signal_revision_never_registration_requested。receipt_id在SDK首次提交生成，重试返回同ID/hash/checked_at；session改变不更换所有权。真实signal result引用不冒称原mutation receipt或outbox生成cause。
- `operation_observation`从两者to_json、事实hash和相等比较排除。not_required的receipt_hash域为 `memory.prospective.invalidation.not-required.receipt.v1`；required的source_hash域为 `memory.prospective.invalidation.required.v1`。均对to_json按既有规范hash，不含自身派生hash。

## 主接audit的确切字段

根DTO：`ProspectiveInvalidationSettlementObservationV1`，to_json恰为invocation_ref_hash、request_hash、claimed_owner_ref_hash、source_hash、outcome、reason、observed_at、operation、persistence_status、schema_version。operation固定settle_prospective_invalidation，schema_version=1，persistence_status=host_persistence_unverified。

| 字段 | 域和payload |
| --- | --- |
| observation_hash | memory.prospective.invalidation.settlement.observation.v1；observation.to_json() |
| request_hash | memory.prospective.invalidation.settlement.request.v1；[outbox_id,payload_hash,expected_source_hash] |
| invocation_ref_hash | memory.prospective.invalidation.settlement.invocation.v1；SDK本次UUID |
| claimed_owner_ref_hash | 沿memory.prospective.source.claimed-owner.v1；[deployment_id,household_id,actor_id,session_id] |

成功outcome=observed，reason为registration_required或not_required_persisted；observation.source_hash分别等于返回required.source_hash或receipt.receipt_hash。拒绝为rejected/{input_or_binding_rejected,ownership_rejected,source_corrupt,resource_limit}，异常为failed/settlement_failed，取消为cancelled/settlement_cancelled；非成功source_hash=None。过大/不可编码请求字段对应hash允许None，Host不能补造。观察时间为物理时间。

成功经result.operation_observation，失败/取消经原exception.operation_observation返回。既有安全观测属性只fingerprint/stage/to_state/state_version。Host须显式白名单新operation并精确消费类型，不把该receipt交给apply_prospective_signal。取消可能发生在SDK已提交但响应未返回之后；观察取消不等于事务没提交，同参重试查证原receipt。

## 事务、emit与完整性

`backends/prospective_settlement.py`在同一连接、BEGIN IMMEDIATE及200000 SQL步数预算内核exact outbox和V2历史来源，核全状态登记请求；错误ID/hash/owner/重复目标/畸形或超限JSON不能作为absence。只有实际APPLIED signal派生、历史非PENDING/RESCHEDULED、无请求且无登记事件时写独立不可变receipt。每份JSON限1MiB。replay重新核持久receipt/原source/无请求事实，返回首个receipt。

`prospective_sources_v2.py`仅抽取同连接的signal_target事实校验，并补直接调用时目标content大小校验；原V2公开wire/hash不改。future emit只对完整核验的旧signal目标抑制无对象invalidation；r1登记→r2触发时原r1取消保留。原7.2无终局表的旧库校验/夹具保留其旧emit合同。

7.3独立表prospective_invalidation_terminal_receipts有exact outbox外键/唯一性、目标历史revision外键、不可变UPDATE/DELETE。registration outbox及registration event的INSERT触发器阻止终局后再登记；SDK正常append/ACK路径也显式检查。Python证明与SQL后续门共享SQLite事务，跨连接不能越过。reopen/close及规范state manifest包含终局记录，outbox原state/payload/ID/hash不改。

## 显式7.3升级

```python
upgrade = await migrate_human_memory_v7_2_to_v7_3(
    db_path, backup_path=exclusive_backup_path,
    expected_initialization_receipt_hash=original_receipt_hash)
```

根返回类型ProspectiveSettlementSchemaUpgradeReceipt；fresh7.3调用返回None，已升级返回原升级receipt。非空7.2默认builder拒绝，调用方必须明确升级；7.0/7.1先走原公开7.2升级，不偷做自动升级。主将来消费617需要接这条公开升级；旧native/M616调用不动。

- `schema_v7_3.py`只追加DDL；schema_v5的7.2 DDL/checksum/default receipt不变。原InitializationReceipt仅扩展可验证7.3 checksum；7.3 fresh初始化用新子类默认checksum。
- 旧schema_upgrade仅提取相同的identity校验helper；7.3对实际完整catalog先做精确验证，再核原7.2身份及既有升级marker。原7.2迁移合同/receipt域不变。
- 新marker键prospective_settlement_upgrade_v1，协议memory.schema.prospective-settlement-upgrade.v1；升级receipt绑定原init ID/hash、source/target checksum与catalog、追加DDL hash、所有旧列根、backup SHA和提交时间。原schema_meta已有键、原初始化receipt、旧升级marker与所有旧业务列保留，只有新增marker。
- 升级前只读完整验证，获取原writer lease与BEGIN IMMEDIATE，保持旧读快照；备份不得覆盖不同内容，备份校验/fsync后才执行DDL。提交前核旧列根和新marker，提交后lost response可重放。目录校验由冻结旧DDL和追加DDL导出，未知catalog拒绝；不是按表存在猜可升级。

## 新增必要控与当前状态

`tests/integration/test_prospective_invalidation_settlement.py`共12个参数展开用例：旧7.2真实public mutation/signal遗留命令→显式升级→终局/reopen；pending依赖并实际ACK/取消；未来emit保留r1/不产生r2空取消；owner/source/payload拒绝；写入后回滚/提交后丢响应两例；两连接写锁与终局后登记/ACK反控；篡改receipt的replay/close/reopen拒绝；升级afterDDL/beforeCommit/afterCommit三例；未知库/冲突备份拒绝。

旧7.2夹具使用原DDL/checksum/初始化路径，实际调用public builder/mutation/signal；不称installed616或Host验收。没有重跑旧V2八项。

r1/r2/r3均是145默认共享锁BUSY、exit75，未启动child、无测试结论；未改lockfile。本次只做源码/文档静态diff检查。以上12项待资源槽可用后执行，**实现尚未经测试，不可称功能验收完成或发布ready**。证据批次根 `.local-test-evidence/2026-09-06/prospective-settlement/`，raw保持ignored。
