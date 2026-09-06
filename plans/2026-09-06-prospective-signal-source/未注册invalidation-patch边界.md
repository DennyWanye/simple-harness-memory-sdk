# 未注册 revision 的 invalidation：可执行修改边界

2026-09-06，交主评估的推荐合同，尚未实施或验证。以Memory `e7a926a` 和实读Host `simple_harness-s5c-schema48/backend/deskpet/memory/`为锚点；不改变V2已固定接口/hash、616制品、旧outbox payload或现有ACK语义。主可按原授权安排实现，无需用户再次确认。新类型和方法名以下为建议，不能声称当前已导出。

## 推荐决策

SDK持久签发独立的 `not_required` 终局receipt，Host按类型消费并持久推进cursor；它不属于signal ACK，也不签发registration authority。未来emit避免生成已证明没有登记对象的命令；已有命令保留原字节，通过新receipt收尾。不能把accepted登记缺失等同于从未请求。

确切待取消身份是owner（deployment/household/actor）、memory_id、target_revision、registration_revision、trigger_hash；已登记则再绑定该revision实际scheduler_registration_ref。session是调用审计身份，不是跨重启receipt所有权或幂等边界。

## SDK：独立公共终局操作和存储

建议新增：

```python
await memory.settle_prospective_invalidation(
    principal=principal,
    outbox_id=entry.outbox_id,
    payload_hash=entry.payload_hash,
    expected_source_hash=source_v2.source_hash,
) -> RegistrationRequiredView | ProspectiveInvalidationNotRequiredReceipt
```

- `RegistrationRequiredView(kind="registration_required")`：返回**真实确切registration请求**的 `registration_entry: OutboxEntryV1`（SDK从该持久行构造，含ID/hash/created_at/原payload）、取消身份、target_source_hash。这样Host可处理精确依赖，不需另加泛用reader或猜SDK ID。已ACK与否不影响“请求存在”的判定；不由该view声称Host已登记。Host仍从自身实际持久状态恢复原authority/ACK。错误字段、损坏、限额等抛原规范异常，不能降级not_required。
- `ProspectiveInvalidationNotRequiredReceipt(kind="not_required")`：SDK事务提交后的事实凭据。字段为schema_version、receipt_id/hash、owner三元组、outbox_id/payload_hash/created_at、memory_id/target_revision/registration_revision/trigger_hash、target_source_hash、真实signal apply result_id/hash、reason固定`signal_revision_never_registration_requested`、checked_at。不含Run、authority、scheduler_registration_ref或伪mutation receipt。
- receipt_hash用独立域 `memory.prospective.invalidation.not-required.receipt.v1` 对不含自身hash/操作observation的规范事实JSON计算；receipt ID由SDK在首个成功事务生成并持久保存。相同owner/exact outbox/hash重试返回原receipt ID/hash/checked_at。每次调用另有独立observation，不能让重试时钟改变receipt。
- 沿既有operation observation审计结构，明确新operation为`settle_prospective_invalidation`，新request/observation域；owner域和metadata安全规范沿用。成功区分required事实和已持久not_required receipt，拒绝/取消也留metadata；主的operation白名单须显式接入，不由Host补造request hash。具体observation DTO/domain随后继源码固定，不偷换V2 reader observation。

事务内步骤（同一写连接和`BEGIN IMMEDIATE`，不在持锁时递归调用会重新取锁的公开reader）：

1. 核owner/scope、exact invalidation topic/ID/idempotency/payload/hash/created_at；按V2同等规则核历史目标来源，并比较expected_source_hash。用接收连接的内部事实helper复用校验，不读当前head猜历史状态。
2. 查找原receipt并核其完整绑定；合法重放返回原值。即使已有receipt，也不得忽略出现了registration请求/登记等矛盾事实。
3. 在**所有outbox状态**中核确切registration请求。SDK内部可复用实际稳定ID算法定位，Host不复制算法；对同目标的非规范ID、错hash、重复/不一致行拒绝。读取必须有字节/步数上限，不把查不到或超限自动判成未请求。
4. 请求存在：核其规范payload/owner/trigger，与目标精确匹配后返回RegistrationRequiredView；即使pending/claimed/dead_letter且未ACK，也不写not_required。若旧请求已ACK，原invalidation仍走同revision实际ref。
5. 请求不存在：只允许目标来源为真实APPLIED signal，且其历史目标生命周期不是PENDING/RESCHEDULED（当前生成协议不会为其发registration）；核signal持久完整链，并核该目标没有任何accepted/invalidated登记事件。其他来源、矛盾行或无法证明的缺口均拒绝，不泛化成空行可跳过。
6. 在同一事务写不可变receipt表，提交后返回。查询取消/故障回滚，不产生半receipt；提交后响应丢失可用完全相同参数重取原receipt，不需续签grant。

新增专用 `prospective_invalidation_terminal_receipts` 表：receipt_id主键、outbox_id外键与唯一约束、owner、payload_hash、target_source_hash、receipt_json/hash和checked_at；CHECK限定kind/reason，UPDATE/DELETE禁止。重复列与JSON/hash在open/replay/close完整性核验中交叉校验。保留原outbox state及所有payload/ID/hash；Host已有read_outbox读全状态，终局不依赖篡改outbox state为ACK。

**这一持久要求确实需要新DDL和受控schema升级**：当前Memory schema为7.2/checksum固定，不能运行时偷偷CREATE TABLE、回填旧初始化receipt或把新DDL冒称616。新增后继schema标识、fresh目录/校验及显式升级路径，旧7.2合法库只经公开升级；版本号由主协调。不要修改此次native已闭合的旧migration空fresh行为。

## 未来emit与并发门

实际修改锚点：`src/simple_harness_memory/backends/sqlite_v5.py:9532` 的 `_append_prospective_mutation_outbox_unlocked`；现`:9604`附近对所有live旧revision无条件append invalidation。

- 仅在已证明旧revision为上述signal派生、无确切registration请求时不emit；有请求（包括未ACK）保持emit，其他正常mutation路径保持原语义。
- r1登记→TIME_DUE创建r2时，对r1的invalidation必须保留；随后REVISE r2生成r3时可不再emit无对象的invalidation(r2)。不把原r2命令改指r1。
- 新receipt与任何未来registration插入/ACK之间要有共同写事务门：已存在not_required终局的同目标不能后来生成请求或接受登记。门放SDK实际append入口及`:9957` `_verify_prospective_outbox_unlocked`相关ACK检查；保持`:10006`附近live registration gate原义。并发两连接不能先证明不存在、再越过终局插入请求。
- 当前outbox已有immutable identity/delete触发器（`schema_v5.py:473–485`）；无请求证明依赖受支持写路径的不可删除历史与signal生成协议，不能只信一次SELECT空结果或Host policy文字。新完整性校验核receipt与无请求/无登记约束。

## Host：类型分支和真实cursor收尾

主当前正在接V2/audit；以下修改由主合并，不能改Hegel/Carver独有WIP。

| 修改位置（Host memory目录） | 最小改变 |
| --- | --- |
| `prospective_registration_source.py:32` prepare_registration | 后继返回显式 `PreparedSignalAuthority | SettledNotRequired | RegistrationDependency`。registration及正常invalidation沿真实authority；无可用登记时调用上述公开SDK操作，不能仅据Host查无记录判not_required。V2 source内部mutation/signal分支由主适配，保持其与终局联合的层次区别。 |
| `s5c_consumer.py:44` source Protocol；`:81` run_once | 精确类型分支：authority正常public apply；not_required只commit终局+cursor，物理signal apply次数0；dependency走有记录恢复路径。禁止把receipt鸭子类型当authority或catch-all吞错误。 |
| `s5c_store.py` registration/cursor/commit入口 | 新commit_not_required(entry,receipt,expected_cursor)，核owner、entry和public receipt全绑定，在同一Host事务持久终局record与cursor；重开按类型恢复，不构造prepared registration/result。 |
| `s5c_schema.py`、当前schema后继initializer/validator | 显式支持终局table与typed cursor；原50/51数据、旧hash、正常pending恢复链保留。不能只改Python通过畸形旧schema。 |

**已确认的DDL硬约束**：`migrations/s5c/042_prospective_memory_actions_v50.sql:19–29` 的cursor外键仅指向registration表；registration phase也只允许prepared/applied。不要把not_required塞入该表伪装ACK。推荐新增独立terminal表，并在后继迁移中把cursor改为两个可空外键（原registration_record_id、新terminal_record_id），CHECK恰好一项非空；旧行原字段/record_hash/链值原样保留，旧行decoder/hash规则不改，新终局行用明确新hash域。重建表时恢复约束/不可变触发器、核旧链，公开initializer验证后再用；不要修改旧SQL文件假装已升级。

跨库顺序为SDK receipt提交→Host精确消费receipt并原子提交终局与cursor。SDK已提交而Host未提交时，下次同参数恢复同receipt；Host已提交后重开读typed终局，不再申请signal grant。若SDK出现取消或receipt无法复核，不能推进cursor。

请求存在但尚未ACK：先恢复Host同请求已持久prepared authority，调用原ref public apply取原结果，再对同revision取消；SDK已提交的过期lostACK可重放，未提交且过期仍拒绝，不能续期冒充原调用。若invalidation先于尚未处理的registration被读到，持久记录exact依赖ID/hash，并有界读取真实依赖entry、先prepare/apply依赖（此预处理不抢先推进全局cursor）；随后收尾当前invalidation。请求后来在正常扫描中出现时复用已持久结果。需把现有store“prepare必带cursor推进”拆出内部原子prepare-only路径及独立cursor确认，而非无限队首轮询或无记录跨过。这里只允许公开exact请求事实/entry，不扫描SDK SQL。

## 改变范围与最小后继验收

Memory新增终局DTO/backend模块、manager/port/root导出、schema/显式升级及针对终局的完整性门；V2事实校验可抽取同连接helper但不改其公开JSON/hash。Host只改上述source/consumer/store、必要schema successor/audit operation白名单，不改model/tool schema、timer语义、Run授权、SDK signal ACK类型。

独审后仅新集合：①真实signal派生→旧invalidation的not_required持久重开/同参重放；②pending请求未ACK不能not_required，原登记与取消均完成；③已ACK仍同revision原ref；④wrong owner/sourcehash/篡改receipt拒绝；⑤双连接终局与请求插入竞态；⑥SDK提交后Host断连/Host事务回滚恢复且后续命令继续；⑦未来emit保留r1取消、无r2空对象命令、旧payload逐字不变；⑧实际旧库升级与typed cursor旧链保真。只测改变及必要跨SDK链，不重跑V2八项或旧包全量。

本轮只提交审查索引和该边界MD；后继源码、DDL、终局receipt和Host分支均尚未实现，待主评估后按授权开工。
