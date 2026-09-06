# NEXT-SHORT — 最小生产接线缺口

2026-09-06，只读核对 Host `/Users/denny/projects/simple_harness-primary-candidate`，
HEAD `af9851273a88dfdbd179578ab0c6d71d9f82b958`，核对时工作树干净。
本轮未运行测试、模型、native、构建；历史测试只读，不作为本机新验证。M0612冻结。

## 实际源码

下列路径相对上述 Host 树：

| 位置 | 当前事实 |
|---|---|
| `backend/deskpet/memory/short_indexing.py:42` | 全量遍历 completed runs；整组验证后 USER 带原 analysis_lineage ingest，其他 source-only admit，再 register/rebuild。无生产调用点，无分页/增量扫描。 |
| `backend/deskpet/memory/conversation_registration.py:68` | 已由真实 terminal/USER/delivered outbox 派生 authority；139行强制两消息，角色仅 USER/ASSISTANT，group_item_count 固定2。 |
| `backend/deskpet/memory/runtime_composition.py:46`、`human_memory_v7.py:151` | 未构造 PrimaryConversationAuthority，也未给 builder 注入 conversation_evidence_authority。 |
| `backend/deskpet/memory/selected_short_sources.py:80` | 已能从公开 resolve_short_horizon_sources 取实际选中 refs、核 Host 完整注册组、复查当前 visibility；无生产调用点。 |
| `backend/deskpet/memory/human_memory_v7.py:382–391,514` | 独立 short recall 后直接返回 RecallLanes；short_history_dependencies 默认 None，fragment 因而不含来源依赖。 |
| `backend/deskpet/execution/primary_dependencies.py:183–198` | short 三元组还必须配非空 history_source_dependencies；缺失即拒绝，不能先开索引就声称生产可用。 |
| `backend/main.py:9031`、`memory_ingestion_outbox.py:430` | 生产后台只有 ingestion outbox＋analysis runner，没有 short indexing worker。 |

**多消息目前是明确不支持，并未被误登记。** `primary_message_evidence.py:105` 和
registration 都先检查 len==2；真实 USER→ASSISTANT→TOOL→ASSISTANT 整组返回
`terminal_multiple_items_not_representable`。对应测试源码在
`backend/tests/memory/test_primary_short_ingestion.py:300`，本轮未运行。
不能删除长度检查，却保留 `/messages/1`、ordinal2、ASSISTANT 角色及 count2。

## 只选一项：接通 actual selected-hit 来源依赖

这是启用生产 worker 之前可独立闭合的最小项。复用 M0612 公开能力及现有 reader，
不改 SDK 或 typed-recall 新叶子；**完成后仍不能宣称 fresh 库已有生产短索引**。

最小合同（注入参数为建议，不冒称已存在）：

1. Host 从已验证 subject/实际 primary init 事实构造现有
   `PrimaryConversationAuthority(state_db_path, subject=..., primary_ref=...)`；
   composition/runtime 共享该实例，以 `conversation_evidence_authority` 注入公开 builder。
   若有初始化先后问题，lazy 解析真实事实；不伪造 primary/Run，不建立第二 ledger。
2. runtime 得到独立 short result 后，用同 manager/principal/disclosure 调现有
   `SelectedShortSourceReader(authority, manager=..., principal=...).resolve(`
   `disclosure_context=..., bindings=(HistoryShortHorizonBinding(actual_audit_id,`
   `actual_chunk_ref, actual_content_hash), ...))`。不从文本反推 source。
3. 仅保留 accepted_bindings 对应的实际 hits，保持 audit_id/内容/hash 不变；把 reader 的
   visibility_dependencies 写入 RecallLanes.short_history_dependencies，沿现有 fragment、
   terminal 和 final-outbound fence 传递。不使用 indexer 的 all-groups 依赖替代选中来源。
4. 不完整或不可见的 hit 不输出 content；缺公共 port/Host authority 明确记 lane 不可用，
   不 catch 成 visible。无关 root 遗忘不应挡住合法 hit。原依赖上限和最终复查保持，
   不截断完整 group。验收必须走实际 factory，而非测试直接调用叶子。

## 应固化的小批反例（未执行）

- 真实 foreground＋S1＋outbox 生成11个合法两消息组；公开登记只作 setup。实际 runtime
  factory recall→fragment→primary dependencies→最终准备/出站门：早组命中，最近10组
  排除。缺 selected 来源接线应红，补接后携原 audit/refs 通过。手动 setup 不算 worker 证据。
- 混入真实四消息 tool 组、仅 USER 未终态组、旧 terminal 缺逐 message S1 组：零部分登记，
  原 blocked reason 保留，合法组仍可用；不取首尾两条冒充完整组。
- 选中后最终门前遗忘所选 memory/source：相应内容拒绝；遗忘未选组：合法 hit 仍可用；
  reopen 保持结论。伪造 audit/chunk/hash、错 subject、缺 ordinal/source 均拒绝。
- reader 成功但下游丢 history_source_dependencies 应红；完整依赖超现有上限仍拒，
  不减少 refs 或抬阈值。只跑单进程决定性小批，不与模型/native/构建/pytest并行。

## 留待后继的明确缺口

- **生产 worker/增量登记**：selected 路径闭合后再绑定唯一后台 owner；真实 terminal＋
  delivered USER outbox 作重放事实。分页处理 whole groups，保留原 USER lineage，
  assistant source-only 零 analysis job；crash/reopen 不跳过 SDK 登记/投影，也不能用
  单一水位永久跳过稍后才 delivered 的旧组。现 reconcile 全量扫描不能冒称 bounded/P95。
- **多 message/tool**：先扩展新终态同 TX 的逐 message S1/完整 proof，再扩 registration
  的实际 ordinal/count/role/manifest/tool causal link。旧不完整档案不回填、不重 stamp。
  两消息限制只能算 bounded leaf，不能标 S3/S6 全短期记忆可用。

原 plan 依据：SDK 原 program 的 `slices/S3-cognitive-systems-recall.md` Task4
（79–110行）要求完整 causal group、授权 public-text pointer、roles/order/source、最近10组/
五天和质量门；Task5 负责 typed 资格/final-use。上述为 Host 消费者缺口，不降低401cells或
原阈值，不把 Task3 程序性/前瞻性状态机当作本项。
