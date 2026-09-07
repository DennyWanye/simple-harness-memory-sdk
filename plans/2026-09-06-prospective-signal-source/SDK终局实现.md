# SDK 7.3 invalidation终局实现：源码交接

2026-09-06。按[已接受的执行边界](未注册invalidation-patch边界.md)实施SDK部分，原边界文件保留。本叶不使用plan-test流程。基线2553bd6；主已转Dirac对5ee3c6b/32b9b94源码限定ACCEPT；0.6.17已完成单次offline构建与独有target验证（见文末），未验证Host52组合。原M616制品/native候选不改，Host52由主实施。业务源码固定5ee3c6bf5a18e710ba328c876423f1173c36797c；新增12项已分批通过，测试只修正future emit断言对topic的范围。

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

## 新增必要控与实际结果

`tests/integration/test_prospective_invalidation_settlement.py`共12个参数展开用例：旧7.2真实public mutation/signal遗留命令→显式升级→终局/reopen；pending依赖并实际ACK/取消；未来emit保留r1/不产生r2空取消；owner/source/payload拒绝；写入后回滚/提交后丢响应两例；两连接写锁与终局后登记/ACK反控；篡改receipt的replay/close/reopen拒绝；升级afterDDL/beforeCommit/afterCommit三例；未知库/冲突备份拒绝。

旧7.2夹具使用原DDL/checksum/初始化路径，实际调用public builder/mutation/signal；不称installed616或Host验收。没有重跑旧V2八项。

r1/r2/r3均是145默认共享锁BUSY、exit75，未启动child，不算测试结果。主释放后：

- r4：**11 passed, 1 failed / 3.39秒**；PGID67244、exit1、resource elapsed3.641秒、峰125200KiB、remaining_group_members=[]。失败是新测试把分析outbox当作提醒命令读取，KeyError: command；业务源码没有因此改动。
- r5-emit-topic：测试仅过滤memory.prospective. topic后，**1 passed, 11 deselected**；PGID67413、exit0、resource elapsed0.657秒、峰115936KiB、remaining_group_members=[]。其余11项不重跑，最终12个唯一用例分批通过；后续ps核两个PGID均为空，槽释放。
- 使用原M614解释器作为source carrier，PYTHONPATH明确本树src/根，pytest_asyncio、禁用cache，145默认共享锁2GiB/180秒。没有修改installed，未运行模型/native/Provider，未构建制品。

证据根 `.local-test-evidence/2026-09-06/prospective-settlement/`，仅r4和r5-emit-topic的command.log/resource.json是执行证据；BUSY批次不是执行。下方只索引4个必要raw，不扫旧包/旧V2证据。

| 相对树根的raw路径 | SHA-256 |
| --- | --- |
| `.local-test-evidence/2026-09-06/prospective-settlement/r4/command.log` | `99d3c19bb4c7061cdbce4843250235b4d00eb1c00f6abd5556b2573f03093683` |
| `.local-test-evidence/2026-09-06/prospective-settlement/r4/resource.json` | `b163898c4b91b4305f13a578825c992a101c17cffdd017292ddfb21f2927aee2` |
| `.local-test-evidence/2026-09-06/prospective-settlement/r5-emit-topic/command.log` | `2b8d39a94bcf6d4dcf01bfc40f39cec3a4d1ba43b476c62b31031d557b3e768b` |
| `.local-test-evidence/2026-09-06/prospective-settlement/r5-emit-topic/resource.json` | `f932eb6244e76689ae72f87350c13fbdaca6c014dcfafcbfd825b25c8d1e15af` |


## 给主和Dirac的固定审查范围

当前工具没有可直接联系的Dirac子代理入口；主已转达对此源码及新证据的限定ACCEPT。重点审同事务absence+terminal后登记门、old7.2保真/新marker及回滚、receipt replay与canonical manifest、v2 helper抽取仍保留原wire、Host必须按类型分支而非伪ACK。独有installed已完成文末3项控制；后继Host52/source/audit实际组合未测，本叶不宣称scheduler全链完成。

下表是2553bd6之后的源码/测试文件SHA-256（测试为topic断言修正后的当前文件）。按路径排序，将 `hash + 两个空格 + 路径 + LF` 拼接后SHA-256，集合指纹：`823aa8eab7651ab5bdfaaf29c23dc9a2d3fd1732d36b89fa9472788ce97c4ab3`。该指纹不是运行时DTO.source_hash。

| 新delta文件 | SHA-256 |
| --- | --- |
| `src/simple_harness_memory/__init__.py` | `5b23a78ba54ebd973e338d25a14a4e8e200db0d8e8effdbc4ad9c99ab10b05f3` |
| `src/simple_harness_memory/backends/prospective_settlement.py` | `6e8b9bc21a934b1378d6656d3cf12597c2b4c01a89eb071a11e4f0e13addd7fb` |
| `src/simple_harness_memory/backends/prospective_sources_v2.py` | `2999a4afe4a0fa95ecefa01d86e0f46c1f2e1589e31bb4444293ee8d663107e2` |
| `src/simple_harness_memory/backends/schema_v5.py` | `7c914397e096b08932f993a6884340dd88830cc6a12e6637c042874471746cae` |
| `src/simple_harness_memory/backends/schema_v7_3.py` | `8b4076809a8db135edab0b0868f60eff5fff0f23988aeef61e2320a6333dc75a` |
| `src/simple_harness_memory/backends/sqlite_v5.py` | `34acfbeff330a3fc010f3cf9ed7567e6e4e3076f0906d021ed68c7d83233b9e5` |
| `src/simple_harness_memory/backends/upgrade_validation.py` | `47bfc7167576ba91556df92ff7b315e4713d214e73ed4f5c2407f39fffd5bc2c` |
| `src/simple_harness_memory/core/manager.py` | `d3d6ecbd54457becfdd4a51f181ace113b340bd611f3c6e5835a0171fee3b84c` |
| `src/simple_harness_memory/core/port.py` | `43e22055837e62f08144571d8a1c49dbeb730b8a69bf951b85a29a7489cd4f34` |
| `src/simple_harness_memory/core/prospective_settlement.py` | `5f4dd075213103054fdbbf3748c7cfbf4b53675a2f2b3589c0fe953c967398bb` |
| `src/simple_harness_memory/core/prospective_settlement_observation.py` | `6a542bd9e618c877a4a4b9804d29e2bab4f9f666e149269e944b4bd3cab48c6b` |
| `src/simple_harness_memory/migrations/__init__.py` | `bf6580ef9c4d77f282a20bf0029adb9ae50340c3d05f82b870b409b6281c9ea4` |
| `src/simple_harness_memory/migrations/schema_upgrade.py` | `3589b5b287f01f37a312f39439fb5713a12e2f56b136298a35f976fbdb206baf` |
| `src/simple_harness_memory/migrations/settlement_upgrade.py` | `bceac9733997d1bcac1965c0d1712970eadd5627e09074c7945643df84029169` |
| `tests/integration/test_prospective_invalidation_settlement.py` | `36503c3935247bd272c7c7739f69d52c83f98c40212e44469f522a6901734a00` |

## 0.6.17单次构建与独有安装交付

主转Dirac源码ACCEPT后，按已授权共享145默认锁执行一次offline hatchling wheel build，uv offline/no-deps安装到独有target；未新建venv。构建固定提交 `32b9b9410cdf0f05ad205a18b42a5fc3ade55211`，沿615/616已核构建工具，不重复双build或旧包全成员扫描。

- wheel：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/prospective-settlement/artifact-617/build/simple_harness_memory_sdk-0.6.17-py3-none-any.whl`
- SHA-256：`e119cdcc29cd8d3566848e80a1e1c3ebb897715d666b7311643af1b514de869c`；379311 bytes。
- own installed：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/prospective-settlement/artifact-617/installed`。
- 仅核相对冻结616源码931b8c7的16个变动包成员：固定源码=wheel=own installed；未重扫旧包/旧证据，M616旧wheel和旧native环境未改。
- `-I -B`实际导入own target，确认Memory版本0.6.17、借用Harness0.7.3；所有已加载Memory模块位于该target，无Memory src overlay。根路径只用于加载测试夹具。
- 仅选3项新能力：旧7.2真实遗留命令→公开升级/终局/reopen及metadata；pending请求真实依赖并ACK/取消；future emit保留r1取消且不产生r2空对象命令。**3 PASS、9 deselected，0.68秒**，未重复旧V2八项。
- resource：PGID70661、exit0、elapsed1.522秒、峰147104KiB、remaining_group_members=[]；另行ps核PGID为空，槽释放。
- 不把此target验证称作Host52/c48/timer组合或native验收；主取得wheel后负责实际新组合。

| 新raw相对树根路径 | SHA-256 |
| --- | --- |
| `.local-test-evidence/2026-09-06/prospective-settlement/build_install_617.py` | `3a150bc0e8922c9c43ac572b59821097fa46a635eb051b73c0f4dd6a939d65b6` |
| `.local-test-evidence/2026-09-06/prospective-settlement/build-617-r1/command.log` | `4f1fa0e8df4e8dc783b17fb65c62255e103559928335c08db99bd28fd185c57c` |
| `.local-test-evidence/2026-09-06/prospective-settlement/build-617-r1/resource.json` | `1db0edf3f780afdd53e070708d1be1904101e1e915ad0e73dd7235d357188623` |
| `.local-test-evidence/2026-09-06/prospective-settlement/artifact-617/manifest.json` | `c32ed4fe3b5bf1e1abcab77c07f513593ad2cbbf866583a04550c27a79f9fbda` |
| `.local-test-evidence/2026-09-06/prospective-settlement/artifact-617/runtime-identity.json` | `9c597b8ab31f5645bb7340472484da8addba9d08c52d421bc691e60ad044af70` |
| `.local-test-evidence/2026-09-06/prospective-settlement/artifact-617/installed_consumer.py` | `465e7c1b20c9957abe7c5a74931b8284ba2a04878d88952a55d68459d3a49bab` |
