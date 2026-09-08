# 决策备忘：一个未决 conflict group 不再短路整条 typed-recall 车道（0.6.31）

> 日期：2026-09-08 ｜ 版本：`simple_harness_memory_sdk 0.6.31`（本地候选，分支 `m0631`；
> 0.6.30 由另一分支并行准备，版本序在合并时统一）
> 上游证据：Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-CONTESTED-DISCLOSURE.md`
> §1.4（重放）、§7 **F-O-3**（短路粒度）与 **F-O-1**（历史可见性不认 confirmation 成员）
> 契约文本：`plans/2026-08-29-human-memory-digital-twin/slices/S3-cognitive-systems-recall.md`
> §5.1 / §5.2 / §5.3 / §5.6；冻结的 Harness SDK `simple_harness/runtime/recall_protocol_v4.py`
> `RecallDecisionV4.__post_init__`（`:438-445`）与 `TypedRecallResultV1.validate_decision`（`:913-920`）

---

## 1. 现场：一个 group 黑洞掉整个库

run4 的 `human_memory_v7.db`（13 个 head，其中 1 个 head `proofreading_python_version`
contested：incumbent rev2 "Python 3.13" ↔ challenger rev3 "3.12"）用本分支修改前的源码
（等价 0.6.29）重放，词面 lane、`memory_types=[semantic, episode, procedure]`：

| 查询 | 修改前 | group 命中的词 | 修改后 |
|---|---|---|---|
| 校对结果存到哪里 | `needs_user_confirmation`，items=0 | qualifiers「做资料**校对**时」 | `recall`，items=3（含 `proofreading_results_storage_directory`） |
| 秋分资料整理的目标是什么 | `needs_user_confirmation`，items=0 | qualifiers「做**资料**校对时」 | `recall`，items=5 |
| 校对流程用哪个 Python 版本 | `needs_user_confirmation` | predicate/object「python」 | `needs_user_confirmation`（不变） |
| 这套校对流程按哪个 Python 版本执行 | `needs_user_confirmation` | 同上 | `needs_user_confirmation`（不变） |
| 画画 | `recall`，items=1 | —（group 无命中） | `recall`，items=1（不变） |

根因有两层：

1. **准入太宽**：`_collect_typed_recall_confirmation` 用 group 成员的**整个**公开 payload
   做词面/向量命中。`subject_entity`「秋分资料整理校对流程」与 qualifiers「做资料校对时」
   和同主题的兄弟记忆共享——任何提到该主题的查询都会让 group 入选。
2. **入选即短路**：`execute_typed_recall` 只要 `confirmation_selection.selected` 非空就走
   `build_host_confirmation_execution`，`items=()`，普通候选根本不收集。

---

## 2. 契约怎么说（裁决依据）

### 2.1 契约文本没有要求整库扣住

- S3 §5.3：「普通选择仅允许 `uncontested|resolved`；contested 只能走完整 group confirmation」——
  约束的是**contested 候选自己**的载体，不是其它候选的去留。
- S3 §5.1：`RecallConfirmationGroupV4` 是原子 carrier，「member 不能同时进入普通 selected，
  也不能单独 page-in」——仍是对**成员**的约束。
- S3 §5.2 末句：「任何一侧不可见……整组、双方、candidate count 与"存在冲突"均不泄露」——
  这是 group **不可见**时的口径，恰恰说明"不披露 group"本身是契约允许的状态。
- S3 §5.6：普通候选的全局稳定序与 greedy 预算；契约**从未**把 group 排在普通候选之前，
  只给它换了一个载体。

**结论：契约不要求整次召回扣住。** 用户任务书的两分支（"按槽位粒度短路" / "契约真要求整体扣住则记录并停"）
取前者。

### 2.2 但冻结的 wire 一次只能带一种载体

Harness SDK（冻结）`RecallDecisionV4.__post_init__`：

```
RECALL                  → selected_items 非空 且 confirmation_groups 为空
NEEDS_USER_CONFIRMATION → confirmation_groups 非空 且 selected_items 为空
```

`TypedRecallResultV1.validate_decision` 同样钉死。**"同一结果里 items 与 group 并存"在 wire 层不可表达**，
任务书里"uncontested candidates for other slots are still returned as `items` in the same result"
的字面形状做不到；Memory SDK 也无法为一次 attempt 落两份 decision/result（`typed_recall_terminals`
单 decision_id/result_id，收据/分页/绑定链全部按 result_id）。

于是问题变成：**group 在什么条件下才有资格占据这唯一的载体。**

---

## 3. 裁决：group 的准入从"任一 lane 命中"收窄到"槽位级相关"

### 3.1 语义

一个 active conflict group 只在查询与**被争议的那一格**相关时才成为 confirmation 候选：

| lane | 普通候选（不变） | group（0.6.31） |
|---|---|---|
| `full_text` | 整个公开 payload 词面计数 | 只看**槽位文本** `contested_slot_text`：两名成员**取值不同**的公开字段（§5.2 说的"被争议的内容"）+ semantic 的 `predicate`（槽位名）；共享的 `subject_entity` / `qualifiers` 不算 |
| `vector` | 余弦 ≥ 0.45 即入 lane | 成员余弦 ≥ 0.45，**且不低于同类型任一普通候选的余弦**——争议记忆是该类型里离查询最近的语义匹配；否则查询更像在问别的槽位 |
| `entity` | 可单独准入 | 仍是过滤（不匹配整组出局）与排序 lane，**不单独准入** |
| `task_scope` / `temporal` | 可单独准入 | 同上，只过滤/排序 |

准入后的一切不变：group 仍是原子载体、仍走 `apply_confirmation_budget`、仍
`NEEDS_USER_CONFIRMATION` + `items=()`、仍在同一把写锁里 `_validate_recall_context_use_sources_unlocked`
后落终态。**未准入的 group 不是候选**——和词面/向量都不命中的普通记忆一样，既不计入
`filtered_candidate_count`，也不标 `truncated`（`truncated` 仍只表示"是候选但预算装不下"）。

### 3.2 为什么是"槽位"而不是"相对排序"

用 run4 的真实词面分数试过纯排序方案（group 与普通候选进同一全局序，谁在前谁占载体）：
「校对流程用哪个 Python 版本」里 episode 得 8 分、`execution_environment` 得 4 分、group 成员 3/2 分——
**正是依赖争议值的那条查询会把 group 排到后面**，模型拿到「前面说的 Python 环境」就去执行了。
CJK 二字组合计数天然偏爱长文本，排序不是可靠的相关性判据。

槽位文本的判据直接来自 §5.2 对 group 的定义：两个 revision、不同 content hash——**差异字段就是争议本身**；
semantic 的 predicate 是槽位名。查询碰到争议本身或槽位名，才需要"先确认"；只碰到共享主题，
说明它在问同主题的**别的**槽位，那些槽位有自己的普通候选。

向量 lane 没有"槽位向量"（世代只对整个公开 payload 嵌入），所以改用同类型内的相对判据：
余弦是可比的，"争议记忆是最近匹配"就是"查询在问它"。平局（≥）仍准入，偏保守。

### 3.3 取舍与已知边界（记录，不上问）

- 「关于 X 的全部信息」这类只提主题的查询：group 不准入，普通兄弟记忆返回，争议本身不出现。
  代价是模型这一轮不知道 X 下有一格在争议；收益是不再整库黑洞。在 wire 单载体约束下二者只能取一。
- 词面槽位命中对英文 predicate + 中文查询仍弱（0.6.20 起的已知限制），生产由 vector lane（FULL_TEXT+VECTOR）补。
- 普通候选现在**先于** confirmation 收集（向量判据要比同类型普通候选）。这只是同一 deadline 预算内的顺序调整；
  拒绝路径（unsupported / disclosure denied / idempotency）仍是零候选访问（`test_public_recall_rejection` 正控的观测顺序随之更新，两收集器的先后不是契约）。
- 无冲突库路径**逐字节不变**：decision/result/page/receipt/terminal hash 在 0.6.29 worktree 与本分支各跑一次 `diff` 为空，已钉死为字面值回归。

---

## 4. F-O-1：confirmation 成员可以被历史绑定

`backends/history_visibility.py::_recall` 原先只在 `result.items` 里找 `HistoryRecallBinding.item_id`；
Host 若把 group 成员投成 `RECALL_CONFIRMATION` fragment（S3 §5.1 明确要求它带完整 binding），
下一轮的历史可见性检查必然 `history_binding_mismatch`。

0.6.31：找不到 selected item 时再到 `result.confirmation_groups[*].members` 里找，按
`result_member_hash` 逐字核对；重校验走同一 `_validate_recall_context_use_sources_unlocked` 的
confirmation 分支（要求 group 仍 active、head 仍为 challenger、无 resolution、成员自身资格与披露门），
且 **`supplied_item_ids` 是整个 group 的成员集**——§5.2 整组原子：任何一侧不可见即整组 stale，
incumbent 自己没被抑制也一样。typed-short source 展开（`resolve_typed_short_horizon_sources`）对成员仍拒
（它只接受 short-horizon selected item）。

---

## 5. 落地

| 项 | 内容 |
|---|---|
| 新模块 | `features/conflict_slot.py`：`contested_slot_text(memory_type, incumbent_payload, challenger_payload)`，纯函数、只读公开 payload、不进任何 hash 域；`CONFLICT_SLOT_TEXT_VERSION = 1`；不进根导出 |
| `backends/sqlite_v5.py` | `execute_typed_recall`：普通候选先收集，再以 `ordinary_candidates=` 调 `_collect_typed_recall_confirmation`；`_collect_typed_recall_confirmation`：两名成员先过全部资格门（一字未改），再做槽位级准入（§3.1）；`build_host_confirmation_execution` / 预算 / 终态 / 幂等重放 / 0.6.27–0.6.29 的锁与 epoch 判据全部不动 |
| `backends/history_visibility.py` | `_recall` 接受 confirmation 成员绑定（§4） |
| 契约面 | 无 DDL 变化（7.4 checksum 不变）；根导出零增减；Harness v4 wire 形状零变化；快照 `public-api-0.6.31.json` 除 `version` 外与 0.6.19 起逐字相同 |
| 测试 | 新增 `tests/integration/test_typed_recall_conflict_short_circuit.py` 6 项：① 争议槽位 + 无关查询（只命中共享 qualifiers/subject）→ items 照常、无 group、不标 truncated、完全无关仍 NO_RECALL；② predicate / incumbent 值 / challenger 值 / 混合查询 → confirmation-only；③ 向量 lane：争议记忆不是最近匹配 → items，是最近匹配 → confirmation（词面零命中）；④ 成员绑定通过历史可见性、hash 篡改 mismatch、一侧证据遗忘 → 整组 stale、source 展开仍拒；⑤ 无冲突库 decision/result/page/receipt/terminal hash 与 0.6.29 逐字节相同（字面值）；⑥ `contested_slot_text` 纯函数边界。同步更新 `test_public_recall_rejection.py` 的收集器观测顺序 |
| 复现 | 修改前本分支源码对 run4 库重放即 §1 表左列；修改后为右列（脚本在会话 scratchpad，不入库） |

## 6. Host 侧后续

- `human_memory_v7.py::project_contested_confirmation` **不需要改形状**：`confirmation_groups` 的类型、成员字段、
  `result_member_hash` 逐字不变；变的只是"哪些查询会拿到 group"。Host 备忘 §3 的方案 C（`conflict_notice`）继续有效。
- F-O-1 修好后，Host 备忘 §3 的**方案 B**（把成员投成正经 `fragments[]` + `RecallPageConfirmationGroupBindingV1` 绑定链）
  在 SDK 侧已无阻碍：`history_visibility` 与 `authorize_recall_context_use`（本就要求整组供齐）现在口径一致。
- 需要 Host 注意的一条语义变化：**空 `fragments` + 无 `conflict_notice` 不再意味着"库里没有争议"**——只说明本轮查询与争议槽位无关。
  PERSONA 里"空 fragments + conflict_notice ≠ 没存过"的措辞不受影响。
- F-O-2（分析车道结算晚于回答）仍是 Host 侧独立缺陷，本次不涉及。

状态：仅本地候选（分支 `m0631`），未合 main、未构建 wheel、Host 未 pin。
