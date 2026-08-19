# 验收标准：simple-harness-memory-sdk 0.2.0 第二部分 — 持久化加固（M2）

> 状态：DRAFT（待用户确认）
> 仓库：`simple-harness-memory-sdk`
> 来源：SDK 生产化 program Slice M2；评审文档"Memory shadow-write 前门禁"的 schema/事务/幂等三项
> 版本：本 slice 引入 schema version 机制 + `source_event_id` 列，版本 bump 至 `0.2.0`

## 范围

**包含**（schema 迁移，高风险）：

- schema version + migration 机制 + checksum（未知/未来 schema 拒绝）
- `append_message`（含 fact 提取/插入/supersede）原子事务
- `source_event_id` 幂等键 + 唯一约束

**明确不包含**：
- 级联删除 / embedding lineage / 资源上限 / retention（M3）
- 云端 embedding provider（M4）
- 宿主 re-vendor（C1）

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 优先级 |
|----|--------|-------------------|--------|
| M2-AC-1 | schema version + migration | `initialize()` 使用 schema 版本标记（`PRAGMA user_version` 或 `schema_migrations` 表）：全新 DB → 建当前 schema + 记录版本；当前版本 → 直接打开；**未来版本 → 抛稳定错误 fail-closed 拒绝**；存在有序 migrations 机制（M2 为初始版本，机制就位即可）。schema checksum（DDL hash）记录并验证，检测 schema 漂移/篡改 | 必须 |
| M2-AC-2 | 原子事务 | `append_message`（含 auto_extract_facts 的 fact 提取→插入→supersede）在**单事务**内完成；任一步失败 → 全部回滚（无"message 已写、facts 未写"或"部分 facts 已写"）。测试：注入中途失败 → 断言 message + facts 均未持久化 | 必须 |
| M2-AC-3 | 幂等键 | messages 表加 `source_event_id TEXT` 列 + 部分唯一约束（NULL 不冲突）；`append_message` 接受 `source_event_id`；同 id 重复 append → 返回已有 message id、不重复插入 | 必须 |

## 非功能 / 边界

- **向后兼容**：现有 0.1.0 数据库（无 schema version）应能识别并迁移到当前版本（或明确报"需迁移"），不得静默丢数据
- **原子性**：事务失败回滚后，DB 状态与 append 前完全一致
- **幂等**：`source_event_id` 为 NULL 时行为与旧版一致（不要求幂等）；提供非 NULL 时才幂等
- **错误态**：未来 schema / 漂移 schema → fail-closed 抛错，不静默打开

## 适用性声明（APPLICABILITY_DECLARATION）

- `input_sensitive=false`：库持久化语义修正，验证走确定性单测 + 临时 SQLite。
- `llm_payload_driven=false`：无 LLM 输出驱动端侧状态机。
- `stateful_init=false`：无异步注册服务/登录态依赖。

## 测试义务矩阵（Test Obligation Matrix）

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---------------|------|-------|------|-------------------|-----------------|
| TO-M2-1 | delivery | M2-AC-1 | — | 全新 DB → 版本=当前；伪造未来版本 → 抛错拒绝 | 证明 schema 版本机制 + fail-closed |
| TO-M2-2 | delivery | M2-AC-2 | — | 注入 fact 插入失败 → append 回滚，message 未持久化 | 证明原子事务 |
| TO-M2-3 | delivery | M2-AC-3 | — | 同 source_event_id 两次 append → 一次插入、返回同 id | 证明幂等键 |
| TO-M2-R1 | change-risk | M2-AC-2 | FAIL-5 既有召回回归 | 既有 append/recall/facts 测试仍通过 | 防止事务化破坏既有写路径 |

## 完成的定义（DoD 摘要）

1. 3 条 M2-AC 全部通过测试
2. 所有 delivery / change-risk obligation 有对应 PASS testcase
3. `simple-harness-memory-sdk` git status 干净、CHANGELOG 更新、version 0.2.0
4. 全量 pytest PASS
5. gate finalize exit 0，receipt 入账
