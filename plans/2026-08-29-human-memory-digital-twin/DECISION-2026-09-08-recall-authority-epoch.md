# 决策备忘：召回权威 epoch 的车道分类（0.6.28）

> 日期：2026-09-08 ｜ 版本：`simple_harness_memory_sdk 0.6.28`（本地候选）
> 上游证据：Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md` §7(1)
> 契约文本：`plans/2026-08-29-human-memory-digital-twin/slices/S3-cognitive-systems-recall.md` §5.4

---

## 1. 问题

HM-TO-A6 原生验收的 turn 15：`context_route(route=memory_standalone)` 的工具在
`05:40:46.066` **成功结算**，`05:40:46.222` Harness 组装下一次 provider 请求、调用
`authorize_recall_context_use` 时抛 `MemoryValidationError("RECALL_AUTHORITY_STALE")`，
`react_loop` 的 `services.provider.invoke` 没有任何 except → `run.fail` → `run.terminal`。

用户库 `human_memory_v7.db` 的 `recall_authority_events` 在一次会话里累计 **26 个 epoch**，
事件类型混杂 `cognitive_memory_changed` / `cognitive_vector_generation_changed` /
`short_horizon_projection_changed` / `short_horizon_generation_changed`。同库
`typed_recall_results` 18 行，而 `recall_context_use_receipts` 只有 1 行 ——
「召回做了很多、真正被用途围栏放行的很少」。

Host 侧已确认 F-B（用途围栏）在 Host 无解：召回结果的 `result_id/result_hash` 已随工具回执
写进对话并被 provider 请求指纹覆盖，epoch 单调递增，重试永远不会成功；SDK 也没有
「重新围栏一个已存结果」的公开 API。所以修复责任在 SDK。

## 2. 契约文本怎么说

S3 slice §5.4 第一段（逐字）：

> 新增 append-only `recall_authority_events` + CAS `recall_authority_heads(principal, epoch,
> policy_hash)`。**任何可能改变资格的** suppression/revoke、认知 head/conflict/classification
> 变化、**Short-Horizon source 失效**和 policy version 变化，均在同一事务追加 event 并增加 epoch。

关键限定语是「**可能改变资格**（eligibility）」与「source **失效**」。§5.4 第三段又把
「suppression 先 commit → 授权返回 `RECALL_AUTHORITY_STALE` 且零 payload」写成一个
**固定的并发线性化结果** —— 它被设计成罕见且可预期的返回，而不是一个日常高频事件。

纯索引/投影/世代重建把同一批内容重新算了一遍向量或分片，**不让任何一条记忆失去资格**，
不在这个定义里。它们让 epoch 在一次会话里跑到 26，把一道罕见的语义围栏变成高频误报。

## 3. 逐点分类（`sqlite_v5.py` 全部 8 个 `_advance_recall_authority_unlocked` 抛点）

| # | 位置（0.6.27） | `event_kind` | 车道 | 对照 §5.4 | 裁定 |
|---|---|---|---|---|---|
| 1 | `:1866` `suppress()` | `suppression_changed` | 抑制指令落库 | 「suppression/revoke」明列 | **保留** |
| 2 | `:2355` `rebuild_short_horizon_projection` | `short_horizon_projection_changed` | 短时程投影重建 | 混合：移除既有 chunk = 「Short-Horizon source 失效」；纯新增不属于任何一项 | **收窄**：仅当 `removed_chunk_count > 0` |
| 3 | `:2527` `rebuild_short_horizon_generation` | `short_horizon_generation_changed` | 短时程向量世代激活 | 纯索引重建，不改变资格 | **停止推进** |
| 4 | `:2825` `rebuild_cognitive_vector_generation` | `cognitive_vector_generation_changed` | 认知向量世代激活 | 同上 | **停止推进** |
| 5 | `:3848` 短时程清理 | `short_horizon_cleanup` | 过期 chunk 删除 | §5.4 第三段明列「Short-Horizon expiry/cleanup」；原实现本就只在 `count > 0` 时推进 | **保留** |
| 6 | `:6858` `record_procedure_observation` | `procedure_changed` | procedure 生命周期/revision 变化 | 「认知 head 变化」 | **保留** |
| 7 | `:7213` prospective 信号套用 | `prospective_changed` | prospective 生命周期/信号状态变化 | 「认知 head 变化」 | **保留** |
| 8 | `:8704` `apply_memory_mutation_plan` | `cognitive_memory_changed` | 记忆创建/取代/冲突（仅 `MUTATE`） | 「认知 head/conflict/classification 变化」 | **保留** |

第 2 项为什么不是"全停"：`rebuild_short_horizon_projection` 是短时程 chunk 的**物化**过程，
`chunk_id` 由 `{registration_hashes, content_hash, privacy, attributes, …}` 的哈希导出。
往一个已存在的因果组里追加一条注册，会让旧 `chunk_id` 消失、新 `chunk_id` 出现 ——
对一条绑定了旧 `chunk_id` 的召回结果来说，这就是真正的 source 失效，必须推进 epoch。
反过来，只多出全新因果组（`removed_chunk_count == 0`）时，没有任何已绑定来源受影响。
`removed_chunk_count` 正是「既有 `chunk_id` 集合 − 目标 `chunk_id` 集合」的大小，
与「失效」一一对应，所以它就是这条车道的正确判据。

第 3/4 项为什么可以全停：世代激活事务只 `INSERT` 向量行、把旧世代置 `retired`、把本世代置
`active`、写一行审计。它不碰 `short_horizon_chunks`、不碰 `cognitive_memory_heads/revisions`、
不碰抑制与分类。向量只影响**未来召回的排序与召回率**，不影响任何已绑定条目的资格。

## 4. 停掉 epoch 之后，语义失效由谁兜住

`authorize_recall_context_use`（`sqlite_v5.py`）在 epoch 相等性判断之后**紧接着**调用
`_validate_recall_context_use_sources_unlocked`，在同一把写锁、同一个事务里对**每一个被绑定
来源**逐条重校验：

- 认知来源：`current_revision` 必须仍等于绑定 revision、`content_hash` 逐字相等、
  `_cognitive_recall_state_allowed`、`_cognitive_recall_valid_at`（有效期）、
  `effective_privacy_class` 与 `information_attributes` 逐字相等、
  `_cognitive_recall_type_authority_allowed_unlocked`（含 procedure applicability 指纹）、
  记忆与全部血缘 evidence 的抑制解析、`_candidate_disclosure_allowed`；
- 短时程来源：`short_horizon_chunks` 行**存在**、`now < expires_at`、`content_hash` 逐字相等、
  privacy/attributes 逐字相等、disclosure 门、chunk 血缘 evidence 的抑制解析。

任一不成立即抛同一个稳定码 `RECALL_AUTHORITY_STALE`。因此：

- 被停掉的两条向量车道碰不到上述任何字段 → **没有需要新增的检查**；
- 投影重建能造成的语义失效只有两种形态 —— 绑定的 `chunk_id` 不再存在、或同 id 下
  `content_hash` 变了 —— 恰好落在短时程分支的前两项检查上（而且这一类我们仍然推进 epoch）。

结论：**不需要在围栏处新增任何检查**。这次改动把判据从"一个全局计数器"换成"这次真正用到的
那几条来源"，披露完整性一分不放宽，只是不再为无关车道误报。

另外 `backends/history_visibility.py` 读 `recall_authority_heads` 时只取 `policy_hash`
参与 `memory.history.policy.v1` 哈希，**不读 epoch**，因此历史可见性行为逐字不变。

## 5. 为什么不选另外两条路

| 方案 | 裁定 |
|---|---|
| 把 epoch 相等性从"抛错"降级为"先做来源重校验、全通过则签发收据 + `authority_epoch_advanced` 降级码"（Host 备忘 §7(2)） | **本轮不做**。它改变 `RecallContextUseReceiptV1` 的语义面（收据里出现降级码），而 §5.4 把 stale 写成固定的并发线性化结果；在没有先把噪声源掐掉之前做这一步，等于用契约让步去掩盖一个实现缺陷。掐掉噪声之后再评估是否还需要它。 |
| Harness SDK 为用途围栏拒绝留同 Run 有界修复（`MandatoryContextRejectionV1.reason` 增加 `recall_authority_stale`，走 `_reserve_context_repair`）（§7(3)） | **本轮不做**（也不在本仓库）。要动 checkpoint/repair 状态机，代价最大；且即使做了，也应当建立在 epoch 不再高频误报之上。 |

本次采纳 §7(1)：**最小、不动任何契约、直接消掉事故窗口的绝大部分**。

## 6. 变更与验证

改动只在 `src/simple_harness_memory/backends/sqlite_v5.py` 三处（见 §3 表）。

新增 `tests/integration/test_recall_authority_epoch_lanes.py` 4 项：

| 用例 | 证明 | 0.6.27 源 |
|---|---|---|
| `test_index_only_rebuild_between_recall_and_use_no_longer_fences` | 认知向量世代重建（真的嵌入、真的激活）夹在 typed recall 与用途授权之间 → 用途围栏放行且收据 `authority_epoch` 等于绑定 epoch；随后真的压制被绑定来源 → 仍以 `RECALL_AUTHORITY_STALE` 拒绝 | 失败 |
| `test_repeated_index_rebuilds_never_move_the_epoch` | 连续三次世代重建，head epoch 纹丝不动，事件只有 `initialized` + `cognitive_memory_changed`；epoch 单调 +1、`previous_epoch` 严格衔接 | 失败 |
| `test_short_horizon_projection_addition_and_removal_are_classified` | 15→16 个注册的纯新增重建不推进 epoch（连 head 都不必惰性建出）；时钟跨过 5 天保留期后的重建 `removed_chunk_count=6` 并推进，事件类型只有 `short_horizon_projection_changed` | 失败 |
| `test_bound_short_horizon_source_removal_is_caught_without_the_epoch` | epoch 不动的情况下把被绑定认知来源 supersede 掉，用途围栏仍靠来源重校验以同一码拒绝 | **通过**（正是 §4 的证据） |

同步更新 `tests/integration/test_cognitive_vector_generation.py` 里断言"世代激活会写一行
`cognitive_vector_generation_changed`"的那一处（改为断言不再写，并注明理由）。

全量 `tests/`：基线（main `0ccec4f`）63 failed / 1565 passed / 8 skipped；本改动后
63 failed / 1569 passed / 8 skipped，失败集合 `diff` 为空，passed +4 恰为新增用例。

## 7. 遗留

- Host 侧 F-B 的 Run 失败面在本次之后**窗口极小但未彻底消除**：真正的资格变化
  （压制、取代、过期）仍然会在工具结算后到用途授权之间的几十~几百毫秒里发生，
  那时抛 stale 是**正确**行为，但 Harness SDK 仍然没有为这个可预期结果留出路。
  彻底消除取决于 Host 备忘 §7(2)/(3)。
- 本轮未合 main、未构建 wheel、未 push。
