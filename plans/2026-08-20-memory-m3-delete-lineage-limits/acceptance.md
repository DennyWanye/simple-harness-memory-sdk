# 验收标准：simple-harness-memory-sdk 0.2.0 第三部分 — 删除/lineage/资源上限（M3）

> 状态：DRAFT（待用户确认）
> 仓库：`simple-harness-memory-sdk`
> 来源：SDK 生产化 program Slice M3；评审文档"Memory shadow-write 前门禁"的删除/lineage/上限三项
> 版本：0.2.0（M2 已 bump）

## 范围

**包含**（schema 迁移，高风险）：

- 级联删除（session / user / full-store / retention）
- embedding lineage 记录 + reindex
- 资源上限（单条 content/fact/payload 长度 + DB 增长上限）

**明确不包含**：
- 云端 embedding provider（M4，本 slice 只记录 lineage 字段 + 定 reindex 方法）
- 宿主 re-vendor（C1）

## 功能验收条款

| ID | 功能点 | 验收条件（可验证） | 优先级 |
|----|--------|-------------------|--------|
| M3-AC-1 | 级联删除 | `delete_session(session_id)` 删除该 session 的 messages + 其 `source_msg_id` 关联的 facts + workspace_actions，且 `digital_twins` 中仅由这些 facts 推导的信息被清理；`delete_all()` 清空 messages/facts/digital_twins/workspace_actions；`delete_old_sessions(older_than_days)` 删除最后活跃早于阈值的 session 及级联数据。测试：删除后该 session 的 messages/facts/actions 均无残留 | 必须 |
| M3-AC-2 | embedding lineage | messages 表加 lineage 列（`embedder_kind` / `embedding_dim` / `embedding_format_version`）；`append_message` 记录当前 embedder 的 lineage；`reindex(embedder)` 用新 embedder 重新 embedding 全部 messages 并更新 lineage。测试：append 后 lineage 与当前 embedder 一致；reindex 后 embedding 与 lineage 均更新 | 必须 |
| M3-AC-3 | 资源上限 | `append_message` 对超长 content（默认上限）抛稳定错误或截断（明确其一）；fact value / payload 同样受限；DB 增长上限（`max_db_bytes` 或等价，超限拒绝写入） | 必须 |

## 非功能 / 边界

- **retention**：默认无限期保留，靠 `daily_decay` 遗忘事实 + `delete_old_sessions` 显式清理；`delete_session`/`delete_all`/`delete_old_sessions` 都是幂等的（重复调用无副作用）
- **向后兼容**：lineage 列为可空，旧数据（无 lineage）可读；`reindex` 是可选的显式操作
- **错误态**：超限 → 稳定错误（如 `MemoryLimitError`）或明确截断，不静默丢弃
- **隐私**：删除必须级联清掉 facts 及其 evidence，不得残留派生数据

## 适用性声明（APPLICABILITY_DECLARATION）

- `input_sensitive=false`：库持久化语义修正，验证走确定性单测 + 临时 SQLite。
- `llm_payload_driven=false`：无 LLM 输出驱动端侧状态机。
- `stateful_init=false`：无异步注册服务/登录态依赖。

## 测试义务矩阵（Test Obligation Matrix）

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---------------|------|-------|------|-------------------|-----------------|
| TO-M3-1 | delivery | M3-AC-1 | — | 删除 session 后 messages/facts/actions 无残留 | 证明级联删除 |
| TO-M3-2 | delivery | M3-AC-2 | — | append 后 lineage 正确 + reindex 后更新 | 证明 lineage 记录 |
| TO-M3-3 | delivery | M3-AC-3 | — | 超长 content → 稳定错误/截断 | 证明资源上限 |
| TO-M3-R1 | change-risk | M3-AC-1/2 | FAIL-4 删除误删/丢数据 | 既有 append/recall/facts 回归仍通过 | 防止删除/lineage 破坏既有路径 |

## 完成的定义（DoD 摘要）

1. 3 条 M3-AC 全部通过测试
2. 所有 delivery / change-risk obligation 有对应 PASS testcase
3. `simple-harness-memory-sdk` git status 干净、CHANGELOG 更新
4. 全量 pytest PASS
5. gate finalize exit 0，receipt 入账
