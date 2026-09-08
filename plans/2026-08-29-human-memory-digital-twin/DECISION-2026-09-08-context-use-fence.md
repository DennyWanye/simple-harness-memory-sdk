# 决策备忘：用途围栏对"权威 epoch 前进"的处理（0.6.29）

> 日期：2026-09-08 ｜ 版本：`simple_harness_memory_sdk 0.6.29`（本地候选，分支 `m0629`）
> 上游证据：Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md` §7(2)
> 前序：本仓库 `DECISION-2026-09-08-recall-authority-epoch.md`（0.6.28，§7(1)）
> 契约文本：`plans/2026-08-29-human-memory-digital-twin/slices/S3-cognitive-systems-recall.md` §5.4

---

## 1. 问题：0.6.28 之后仍然死人

0.6.28 把纯索引/世代车道从 epoch 里摘掉，把噪声源掐掉了。但 HM-TO-A6 第 4 次尝试
turn 15 仍然死于同一处围栏：

- 前台定型召回**已经结算**（`tool.effect_settled` / `tool_attempt.succeeded`）；
- 紧接着**异步分析车道**把**上一轮**的新记忆落库 —— `apply_memory_mutation_plan`
  的 `MUTATE` 分支写 `cognitive_memory_changed`，epoch +1；
- Harness 组装下一次 provider 请求时调用 `authorize_recall_context_use`，
  epoch 相等性判断抛 `MemoryValidationError("RECALL_AUTHORITY_STALE")`；
- Host 把它收敛成稳定码 `recall_context_use_authority_stale`，但**冻结的 Harness SDK 在这一 hop
  没有任何修复路径**（`dispatch._authorize_context_use` ← `react_loop` 的
  `services.provider.invoke` 无 except）→ `run.fail` → `run.terminal`。

证据：`simple_harness/.local-test-evidence/2026-09-08/native-a6-run4/primary-ui-*/native.log`
（`sdk_run_driver_failed error_type=RecallContextUseAuthorityStale`）。

**这不是罕见竞态。** 每一轮对话的分析车道都在该轮结束后 ~10–60 s 落库，正好落在**下一轮**
召回与用途授权之间。0.6.28 之后剩下的推进车道全是**真实的资格事件**，所以这个窗口
不可能再靠"分类"消掉 —— 只能改判据。

## 2. 裁定：采纳 Host 备忘 §7(2)，把判据从"全局计数器"换成"这次真正绑定的来源"

`authorize_recall_context_use`（`backends/sqlite_v5.py:4678-4690`）改为：

| 判据 | 0.6.28 | 0.6.29 |
|---|---|---|
| `policy_hash != result.policy_hash` | 抛 `RECALL_AUTHORITY_STALE` | **不变**，仍抛 |
| `effective_now >= result.authority_expires_at` | 抛 | **不变**，仍抛 |
| `epoch < result.authority_epoch`（权威倒退） | 被 `!=` 覆盖 | **显式**抛（只可能是损坏/回滚） |
| `epoch > result.authority_epoch`（权威前进） | 抛 | **不再直接抛**：记下 `authority_epoch_advanced`，交给下面的逐来源重校验裁定 |
| `_validate_recall_context_use_sources_unlocked` 任一来源不成立 | 抛 | **不变**，仍以同一稳定码抛 |

也就是说：**epoch 前进本身不再是拒绝理由；被绑定来源真的变了才是。**
两者在同一把写锁、同一个 `BEGIN IMMEDIATE` 事务里判定，没有引入任何新的窗口。

### 为什么这仍然是正确的线性化结果（S3 §5.4）

§5.4 第三段把并发线性化写死为：

> suppression 先 commit，则授权返回 `RECALL_AUTHORITY_STALE` 且零 payload；
> Context-use receipt 先 commit，则仅该 exact immutable snapshot/attempt 可完成一次，
> 随后 suppression 使所有新 attempt 失效。此边界同时覆盖 suppress、revoke、supersede、
> contest、classification/policy change、Short-Horizon expiry/cleanup。

逐条对照：

1. **该条款的每一个具名事件都是"作用在某条来源上"的**（suppress / revoke / supersede /
   contest / classification 变化 / Short-Horizon 过期清理），policy change 除外。
   只要它作用在**本次绑定的**来源上，`_validate_recall_context_use_sources_unlocked`
   就会在同一事务里发现并抛出同一个码 —— 认知来源查 head 仍等于绑定 revision、
   `content_hash` 逐字相等、`_cognitive_recall_state_allowed`、`_cognitive_recall_valid_at`、
   `effective_privacy_class` 与 `information_attributes` 逐字相等、
   `_cognitive_recall_type_authority_allowed_unlocked`（含 procedure applicability 指纹）、
   记忆与全部血缘 evidence 的抑制解析、`_candidate_disclosure_allowed`；
   短时程来源另查 chunk 行存在、`now < expires_at`、`content_hash`、privacy/attributes、
   disclosure 门、chunk 血缘 evidence 的抑制。**线性化结果一分未变。**
2. **policy change 不走这条放宽**：`policy_hash` 相等性原样保留，先于来源重校验硬失败。
3. **"零 payload"仍然成立**：拒绝路径完全不变（抛出发生在构造收据之前，事务 ROLLBACK，
   `recall_context_use_receipts` 不写行）。
4. **放行的那一次到底授权了什么？** 收据只绑定 `item_bindings` 里逐条列出的条目，
   而 `_validate...` 正是对这批 `supplied_item_ids` 逐条重校验的。
   **被授权的集合 = 模型已经看到的集合 = 被重校验的集合**；epoch 前进所对应的那条变化，
   按定义作用在这个集合**之外**（否则来源重校验会拒）。因此这次放行没有授权任何
   "模型没看到、且当前不合格"的字节 —— 这正是这道围栏要守的披露完整性。
5. §5.4 第二段要求"在 suppression 所用同一锁/事务边界重新验证 **epoch/policy/time**、
   current head 或 active group、source/content/classification、
   recipient/purpose/privacy/attributes 与 suppression"。
   0.6.29 仍然读 epoch、仍然验 policy 与 time，只是把 epoch 从"相等即通过、不等即拒"
   降级为"倒退即拒、前进则由后面那一整串**更强**的逐条检查裁定"。
   epoch 从来只是一个**保守的快捷判据**（"有什么东西可能变了"），
   而逐来源重校验是**精确判据**（"我这次要用的东西变没变"）。
   保留精确判据、放宽保守判据，披露完整性只增不减。
6. 同仓库已有先例：`backends/history_visibility.py:321` 就是先跑
   `_validate_recall_context_use_sources_unlocked`、把 `RECALL_AUTHORITY_STALE` 收敛成软结果
   `history_source_stale` 的写法 —— 用途围栏与历史可见性至此判据一致。

### 0.6.28 为什么当时不做这一步、现在为什么该做

0.6.28 备忘 §5 的原话是"在没有先把噪声源掐掉之前做这一步，等于用契约让步去掩盖一个实现缺陷"。
噪声源已经在 0.6.28 掐掉了：现在还能推进 epoch 的都是真实资格事件。
在此之上放宽，放宽掉的**只有**"资格事件发生在别的记忆上"这一种情况 ——
它既不是契约要防的东西，也是正常使用中最常见的一种并发。

## 3. 降级码怎么记：不新增任何 DDL

Host 备忘 §7(2) 建议"收据里带一个 `authority_epoch_advanced` 降级码"。**收据里加不了字段**：
`RecallContextUseReceiptV1` 定义在**冻结的 Harness SDK**
（`simple_harness/runtime/recall_protocol_v4.py:1458`），`from_json` 走 `_exact_keys`，
多一个键就直接抛 —— Memory SDK 无权改它，改了也会在 replay 时炸。

而这条事实**本来就已经逐字落在两条不可变行里**：

| 事实 | 落库位置 | 不可变性 |
|---|---|---|
| 授权时的当前 epoch | `recall_context_use_receipts.authority_epoch` | 表有 immutable update/delete 触发器；同时进入 `receipt_hash` 与 canonical manifest |
| 召回被绑定时的 epoch | `typed_recall_results.result_json` 的 `authority_epoch` | 同上（`typed_recall_results` 也有 immutable 触发器） |
| 两行的连接 | 收据 `receipt_json.result_id` → `typed_recall_results.result_id` | 收据 `request_hash`/`receipt_hash` 覆盖 |

所以「本次用途授权是在权威 epoch 前进之后签发的」= `收据.authority_epoch > 绑定结果.authority_epoch`，
是一个**由两条不可变行严格导出**的事实。再存一份冗余标记，只会引入"标记与 epoch 互相矛盾"
这一种新的损坏形态，而不会增加任何信息。为一条可导出的事实逼出一次 7.5 DDL 切换
（新 schema 模块 + 前向迁移 + canonical manifest roots + cutover 断言），
正是 0.6.27 备忘拒绝过的那种代价。

**因此 0.6.29 不动 schema（7.4 checksum 不变）**，改为：

- 新增 `core/recall_context_use.py`：稳定码常量
  `RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED = "authority_epoch_advanced"`
  与有界只读视图 `RecallContextUseAuthorityNoteV1`（构造期校验：只认已知码、
  当前 epoch 必须严格大于绑定 epoch）；
- 新增只读导出 `SQLiteHumanMemoryBackend.read_recall_context_use_authority_notes`
  与 `MemoryManager` 同名委派：按 principal（可选 `run_id`）从上述两条不可变行导出降级说明，
  **不写任何行**；
- 授权成功且 epoch 前进时打一行**无载荷**结构化日志
  `typed_recall.context_use.authority_epoch_advanced`
  （只带 `reason_code` / `subject_hash` / `bound_authority_epoch` / `authority_epoch` /
  `bound_source_count`，绝不带 query、召回内容或 source ref）。

沿用 0.6.20–0.6.28 的"根导出零增减"纪律：新常量与新视图**不进** `simple_harness_memory.__all__`，
只经 `core.recall_context_use` 可达；`public-api-0.6.29.json` 除 `version` 外与 0.6.19 起逐字相同。

## 4. 变更清单

| 文件 | 改动 |
|---|---|
| `src/simple_harness_memory/backends/sqlite_v5.py:4678-4690` | 围栏判据（见 §2 表）+ `authority_epoch_advanced` 标记 |
| `src/simple_harness_memory/backends/sqlite_v5.py:4772-4780` | COMMIT 之后打无载荷降级日志 |
| `src/simple_harness_memory/backends/sqlite_v5.py:4788-4854` | 新增 `read_recall_context_use_authority_notes`（只读） |
| `src/simple_harness_memory/core/recall_context_use.py` | 新文件：稳定码 + `RecallContextUseAuthorityNoteV1` |
| `src/simple_harness_memory/core/manager.py:466-477` | `MemoryManager` 委派 |

**没有改**：`execute_typed_recall` 内的工具内围栏（采集前后的 epoch 复核）
语义逐字不变 —— 它保护的是"一次召回执行内部的一致性"，与用途围栏是两回事；
`_validate_recall_context_use_sources_unlocked` 一行未动；
`recall_authority_events` / `recall_authority_heads` 的 DDL、行形状与推进车道分类（0.6.28 的裁定）；
收据构造、`receipt_hash` 域、幂等重放、`recall_context_use_receipts` 的 DDL 与写入列。

## 5. 测试

新增 `tests/integration/test_recall_context_use_fence.py`（7 项）：

| 用例 | 证明 | 0.6.28 源 |
|---|---|---|
| `test_concurrent_memory_apply_between_recall_and_use_now_authorizes` | A6 turn 15 原型：召回结算后落**另一条**新记忆（真实 `apply_memory_mutation_plan`，epoch +1）→ 签发收据、`receipt.authority_epoch` 等于**当前**头、降级说明 `authority_epoch_advanced` 且两个 epoch 正确；同 provider attempt 重放逐字返回同一张收据且说明不重复 | 失败（`RECALL_AUTHORITY_STALE`） |
| `test_unrelated_suppression_advances_the_epoch_and_still_authorizes` | 压制**别的**记忆（真实 `suppress`，epoch +2）→ 仍放行 | 失败 |
| `test_same_race_but_suppressed_bound_source_still_fences` | 同一竞态下压制**被绑定**来源 → 仍抛同一码、`recall_context_use_receipts` 零行、零降级说明 | 通过 |
| `test_same_race_but_superseded_bound_source_still_fences` | 被绑定来源 head 前进到新 revision → 仍抛同一码、零收据 | 通过 |
| `test_policy_change_expiry_and_epoch_regression_still_fence` | 替身接管权威读取（不篡改 head，避免破坏事件链完整性）：过期 / policy 变化 / epoch 倒退三种一律拒；只有「前进 + policy 不变 + 未过期 + 来源全通过」才放行 | 失败（④ 子项） |
| `test_no_race_receipt_bytes_are_unchanged_from_0_6_28` | 无竞态路径的 `receipt_id`、`receipt_hash`、canonical `receipt_json` 与 0.6.28 **逐字节相同**（钉死字面值，见下）；零降级说明；`_validate_integrity` 通过 | 失败（缺新方法） |
| `test_authority_note_view_rejects_impossible_shapes` | 降级视图有界：未知码、当前 epoch 未真的前进 → `MemoryValidationError` | 通过 |

逐字节证据：同一场景分别在 0.6.28 源（worktree `-0629-base`，detached `e554c20`）与 0.6.29 源上
跑同一段脚本，`receipt_hash` / `receipt_id` / canonical `receipt_json` 三者 `diff` 为空，
钉死值 `receipt_hash = af05933f0e177255f5e1263e2c7bb1b38f3210469d5d00bd92268083185c07ce`。

全量回归：基线（main `e554c20`，独立 worktree + 克隆 venv）63 failed / 1569 passed / 8 skipped；
本改动后 63 failed / 1576 passed / 8 skipped，**失败集合 `diff` 为空**，passed +7 恰为新增用例。

同步更新一处既有期望：`tests/integration/test_duplicate_source_short.py` 里
「任何新指令都会让旧结果的新 attempt 变 stale（**即便其来源仍然可见**）」这条断言，
压制的是一条**认知记忆**，而该用例绑定的是 short-horizon 来源 —— 正是 0.6.29 要放行的形态。
改为断言新 attempt 得到带**当前** epoch 的收据，并核对降级说明的 provider attempt、码与两个 epoch。

## 6. 遗留 / Host 侧配套

- **Host 不需要读任何新字段。** `authorize_recall_context_use` 的返回类型与字段逐字不变；
  Host 若想统计降级，直接比对 `receipt.authority_epoch` 与它手上召回结果的
  `authority_epoch` 即可（两者本来就都在 Host 内存里）。
  `read_recall_context_use_authority_notes` 是**可选**的事后审计入口，不接也不影响任何行为。
- Host 备忘 §9 的 `context_route.py` 白名单映射（把用尽后的 stale 暴露为
  `context_route_recall_authority_stale`）仍未做，与本轮无关。
- Host 备忘 §7(3)（Harness SDK 为用途围栏拒绝留同 Run 有界修复）**仍然值得做**：
  0.6.29 之后剩下的 stale 全是**正确**的拒绝（被绑定来源真的失效），
  但 Harness 依然只会把它变成 `run.fail`。窗口已经从"每一轮都可能"缩到
  "恰好在这几十~几百毫秒里压制/取代/过期了这次用到的那条记忆"，
  但要彻底消除 Run 失败面，仍需 Harness 侧留出路。
- 本轮未合 main、未构建 wheel、未 push。
