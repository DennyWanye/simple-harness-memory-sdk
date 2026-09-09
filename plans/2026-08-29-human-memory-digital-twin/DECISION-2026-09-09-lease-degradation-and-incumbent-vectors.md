# 裁定（0.6.38）：租约到期降级为收据；冲突组 incumbent 进向量世代；世代覆盖率与可用性分开判

- 日期：2026-09-09
- 分支：`m0638`（基线 `5ad222a` = 0.6.37 合入后的 main）
- 缺陷来源：
  - **F-AA-2**：Host 事件 AA 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-AA-AUTHORITY-STALE-RECOLLECT.md`
    §2 / §9(2)（HM-TO-A6 T18）
  - **F-V-2a / F-V-2b**：本仓 0.6.37 备忘 `DECISION-2026-09-09-contested-group-admission-basis.md`
    §5.1 与 §8（当时记为 P2，本轮升级为交付项）
- 证据：`.local-test-evidence/2026-09-09/native-a6-run9/primary-ui-8whts2lo/userdata/data/human_memory_v7.db`
  （只读，连 `-wal`/`-shm` 复制出来后离线重放）
- 契约：`slices/S3-cognitive-systems-recall.md` 新增 **§5.4-补**（租约）与 **§5.3-补2**（向量）

---

## 1. 两个缺陷

### 1.1 F-AA-2：一分钟的召回上下文期限被当成整轮用途租约

HM-TO-A6 T18：一轮工具循环里 12 次 provider 请求，前 11 次都在租约内正常出收据
（`recall_context_use_receipts` 11 行，同一 `result_id`、同一 `authority_epoch=9`），
第 12 次比 `authority_expires_at` 晚了 **4.96 秒** → `RECALL_AUTHORITY_STALE`
→ Host `RecallContextUseAuthorityStale` → `run.fail`。那一刻 **7 条被绑定来源逐条未变**
（仍是 r1、`content_hash` 未变、`suppression_directives` 无命中）。

抛点是 `backends/sqlite_v5.py` 用途围栏的四选一判据里的第三条：

```python
or effective_now >= result.authority_expires_at
```

`result.authority_expires_at` 的上游是 Host 的 `RecallContext.expires_at = moment + 60.0`
（SDK 原样取用，再与逐 item 的期限取 min）。**一个召回上下文期限被当成了整轮用途授权
的租约**：只要一轮工具步骤跑过一分钟，这一轮必死，与记忆是否真的变过无关。

### 1.2 F-V-2a / F-V-2b：世代只覆盖当前 revision，且 head 一变整库退化

`_cognitive_vector_head_rows_unlocked` 只取 `r.revision = h.current_revision`：

- **F-V-2a**：未裁决冲突组的 incumbent 成员按定义是**上一版**，因此永远拿不到向量分。
  `_collect_typed_recall_confirmation` 会对两名成员各调一次 `vector_lane.score`，
  其中一次注定返回 `None`——group 的向量准入只可能由 challenger 单方面贡献，
  与 S3 §5.2「整组同进同出」的对称性矛盾。
- **F-V-2b**：`_prepare_cognitive_vector_lane` 把「active 世代的 `content_hash` 是否等于
  **当前** head 清单的 manifest」当成可用性判据，于是**任何一次 head 修订**都让
  **整库**的认知向量车道 `cognitive_vector_stale`，直到下一次世代激活为止
  （run9 实测 3.38 s 与 15.19 s）——而争议轮恰好紧随修订。

---

## 2. 裁定一（F-AA-2）：租约到期是降级码，不是硬 stale

### 2.1 为什么这不是"放宽一点"

`authority_expires_at = min(RecallContext.expires_at, 每条被绑定来源自己的期限)`。
后一半在**同一把写锁、同一事务**里的 `_validate_recall_context_use_sources_unlocked`
被逐条独立重新执行：

| 来源类型 | 重校验里那一条 |
| --- | --- |
| 认知记忆（含 confirmation 成员） | `_cognitive_recall_valid_at(row, now)` = `valid_from <= now < valid_to` |
| Short-Horizon chunk | `now >= float(row["expires_at"])` → 抛 |

也就是说：**租约唯一多挡住的，就是 Host 那个 60 秒的召回上下文期限**。它挡不住任何一条
真的失效了的来源（那些各有各的、被逐条重新执行的期限），只能杀掉「跑得比该期限久的
正常回合」。把它从硬失败判据里移出，披露完整性一分不减。

### 2.2 修法

`authorize_recall_context_use`：

```python
if (policy_hash != result.policy_hash
        or self._recall_policy_hash != result.policy_hash
        or epoch < result.authority_epoch):
    raise MemoryValidationError("RECALL_AUTHORITY_STALE")
authority_epoch_advanced = epoch != result.authority_epoch
authority_lease_expired = effective_now >= result.authority_expires_at
```

逐来源重校验一字未动，随后照常签发收据，并记一行无载荷结构化日志
`typed_recall.context_use.authority_lease_expired`。

### 2.3 续租：冻结契约不允许"已过期的收据"

冻结的 Harness `RecallContextUseReceiptV1.__post_init__` 要求 `expires_at > authorized_at`
（`receipt requires a future expiry`），因此这一支必须**续发**一段租约。取法：

```
receipt.expires_at = effective_now + (result.authority_expires_at - result.evaluated_at)
                     再与"本次重校验重新读到的来源最早期限"取 min
```

即：长度等于 Host 当初给这次结果的租约长度，起点改为本次授权时刻，上界是来源自己的期限
——**续租永远不会让模型用到一条已经过期的来源**。为拿到那个上界，
`_validate_recall_context_use_sources_unlocked` 额外返回它当下重新读到的最早来源期限
（认知记忆的 `valid_to` / chunk 的 `expires_at`，全无上界时 `None`）；
判据一条未改，既有调用方（召回路径）忽略返回值。
租约**未**到期的那一支 `receipt.expires_at` 仍逐字是 `result.authority_expires_at`
（`NO_RACE_RECEIPT_JSON`/`NO_RACE_RECEIPT_HASH` 两个字面值用例照旧绿）。

### 2.4 降级说明：仍然零 DDL，但导出对不是收据行自己那两列

`core/recall_context_use.py` 新增 `RECALL_CONTEXT_USE_AUTHORITY_LEASE_EXPIRED =
"authority_lease_expired"`，与 0.6.29 的 `authority_epoch_advanced` 同形：

| 事实 | 由哪两条不可变行导出 |
| --- | --- |
| epoch 前进（0.6.29） | `recall_context_use_receipts.authority_epoch` ↔ `typed_recall_results.result_json.authority_epoch` |
| 租约到期（0.6.38） | `recall_context_use_receipts.authorized_at` ↔ `typed_recall_results.result_json.authority_expires_at` |

**注意**：租约那一条**不能**用收据行自己的 `expires_at`——它已经是续发的新租约
（§2.3），比 `authorized_at` 晚。两行仍由收据 `request_json` 的 `result_id` 唯一连接。
`RecallContextUseAuthorityNoteV1` 追加一个**带默认值**的可选字段
`bound_authority_expires_at`（既有 13 参位置式构造逐字不变），只在租约码上非空，
并要求 `authorized_at >= bound_authority_expires_at`；epoch 码上必须为 `None`。
epoch 不变性也按码分岔：epoch 码要求严格前进，租约码允许相等但永不倒退。
一张收据可同时导出两条说明，次序固定为 epoch 前进在前。

### 2.5 有意留下的边界

`page_typed_recall_result` 的 `typed_recall_result_expired` **不动**：分页是把旧结果的
字节**重新取出**，不是对已下发字节的用途授权，两者的时限语义不同（写进 §5.4-补.6）。

---

## 3. 裁定二（F-V-2a）：未裁决冲突组的 incumbent 进世代

`_cognitive_vector_head_rows_unlocked` 改为「全部当前 head revision ∪ 未裁决冲突组的
incumbent revision」，取组条件与 `_collect_typed_recall_confirmation` 的取组查询逐字一致
（`h.current_revision = g.challenger_revision` 且 `cognitive_conflict_resolutions` 无行），
两批行按 `(memory_id, revision)` 合并去重排序。

- **候选面不变**：`_CognitiveVectorLane.score` 只对**已通过全部资格门**的那一个
  (memory_id, revision) 精确查表（`eligible_refs=frozenset({ref})`），incumbent 进世代
  不让它成为普通候选；普通候选永远只用自己的当前 revision 去查分。
- **重建成本**：没有未裁决冲突组的库里每条记忆恰好一行，且 `ORDER BY memory_id` 与
  `ORDER BY memory_id, revision` 同序 → **manifest hash 一个字节不变**，
  升级到 0.6.38 不触发任何世代重建（用例 ④ 逐字比对 0.6.37 的取法与 hash 公式）。
  有未裁决冲突组时，下一次维护 tick 的那一代多嵌入的条数 = 未裁决组数
  （run9 证据库：8 → 9，多 1 条）。组一被裁决，incumbent 立刻退出（用例 ③ 走真实的
  REVISE + `conflict_status=resolved` 路径）。
- **不加 DDL**：`cognitive_vectors` 的主键本来就是 `(memory_id, revision, generation_id)`，
  同一世代放同一条记忆的两个 revision 一行不用改。

## 4. 裁定三（F-V-2b）：世代的**可用性**与**覆盖率**分开判，零 DDL

问：能不能"让一次 head 修订只让被改的那条记忆失效，而不是整代"？
答：能，而且不需要 DDL——只要把混在一条判据里的两件事拆开。

| 问题 | 0.6.37 的判据 | 0.6.38 的判据 |
| --- | --- | --- |
| 这些向量还能不能信？ | （与下一行混成一条） | 该世代按**它自己**的 `(memory_id, revision)` 重算的 manifest == 入库的 `content_hash` |
| 它覆盖了当前的全部 revision 吗？ | active 世代的 `content_hash` == **当前** head 清单的 manifest，否则整代不用 | 不覆盖也照常用，只对覆盖到的 revision 打分，本次召回记 `cognitive_vector_partial` |

**自证 manifest 为什么等价于"还能信"**：`cognitive_memory_revisions` 行内**不可变**
（触发器 `immutable cognitive revision`；本轮写用例时被它挡下来一次，见
`test_recall_context_use_lease.py::_prepared_with_source_valid_to` 的注释），
所以对固定的 `generation_id`，重算结果只随 `COGNITIVE_TEXT_FORMAT_VERSION` 变化。
自证成立 ⟺ ① 该世代是用**当前**渲染格式版本嵌入的；② 它覆盖的每条 revision 的
`content_hash` 一字未变。这两条正是「这些向量还能不能用」的全部条件。
渲染格式版本一变，自证立刻不成立 → 缓存置空 → 整代 `cognitive_vector_stale`
（负控 `test_text_format_bump_still_degrades_the_whole_lane`）。

覆盖不到的 ref 只是 `score()` 返回 `None`，与「本来就没有向量」同形——世代里
**不会**留下一条已经不是当前 revision 的向量被误用：普通候选只用当前 revision 查分，
confirmation 成员只用组里那两个 revision 查分，两者都在当前 head 行集合里。

自证 manifest 在**装载缓存时**算一次（`_load_cognitive_vector_cache_unlocked`，
只在世代变化/启动时跑），召回路径零额外成本；召回路径新增的只有一次
`_current_cognitive_vector_manifest_hash_unlocked`（本来就在跑）与一次字符串比较。
缓存装载里原来那条「世代 ref 集合 != 当前 head 集合 → `MemoryCorruptionError`」
换成「行为空 → 损坏」，**行级完整性没有变弱**：紧接着的
`vector_manifest_hash`（(ref, embedding_hash) 全集的 hash）逐字复核仍在，
多一行少一行都过不去。

`cognitive_vector_partial` 是**车道仍在服务本次召回**的降级码，与其余四个「车道不可用」
的码不同，因此 `cognitive_vector_generation_id_hash` 照常落 typed recall 审计
（调用处的 `elif` 改成 `if`；其余四码下 lane 恒为 `None`，行为逐字不变）。

## 5. 证据库离线重放（只读副本，`native-a6-run9`）

脚本直接挂只读连接调用三个纯读方法（`initialize()` 走不通：该库的 evidence filter
policy 本 SDK 不识别，与 0.6.37 备忘同一处限制），时钟钉 T22 `1788905502.0`。

**(1) 冲突组与 head 清单**

```
open groups: [('cognitive-conflict-group-cd9b2beb…51fe7b5',
               'cognitive-memory-84b96e0b…7ee5bf12', incumbent=2, challenger=3)]
resolutions: 0
0.6.38 head rows: 9        （0.6.37 是 8）
  incumbent in set: True   challenger in set: True
```

**(2) T22 那一刻的 active 世代（`…13e96d22` = 备忘里的 `5adb7b43…`）**

```
active generation refs: 8
self manifest == stored content_hash: True     → 世代可用
current manifest == stored:            False   → cognitive_vector_partial
current refs missing from generation: [(cognitive-memory-84b96e0b…, 2)]   ← 只差 incumbent
generation refs no longer current:    []
```

即：**T22 这一轮在 0.6.38 下不再是 `cognitive_vector_stale`**，8 条已覆盖记忆
（含 challenger r3）照常打分，只有 incumbent r2 要等下一次维护 tick 才有向量。

**(3) 全部 10 代逐代复算**

```
…f52682af retired refs=1 self_manifest_ok=True still_current=0 orphaned=1
…8fc3e996 retired refs=2 self_manifest_ok=True still_current=1 orphaned=1
…343f4e86 retired refs=3 self_manifest_ok=True still_current=2 orphaned=1
…c644f311 retired refs=4 self_manifest_ok=True still_current=3 orphaned=1
…e7ab85a6 retired refs=5 self_manifest_ok=True still_current=4 orphaned=1
…f3998af5 retired refs=6 self_manifest_ok=True still_current=5 orphaned=1
…69249848 retired refs=7 self_manifest_ok=True still_current=6 orphaned=1
…f50a48ce retired refs=8 self_manifest_ok=True still_current=7 orphaned=1
…2d3a1082 retired refs=8 self_manifest_ok=True still_current=8 orphaned=0   ← T20 更正后 3.38 s 那一代
…13e96d22 active  refs=8 self_manifest_ok=True still_current=8 orphaned=0   ← T21 争议后 15.19 s 那一代
```

两条读数：

1. **10 代的自证 manifest 全部成立**——revision 行内不可变这条设计前提在真实库上逐代验证过；
2. `…2d3a1082`（T20 更正后激活、含 r2）的 8 条 ref 在 0.6.38 下**全部仍是当前可召回
   revision**（r2 现在是未裁决组的 incumbent），`orphaned=0`。所以争议落库后那 **15.19 秒**
   的窗口里，0.6.37 让整库 `cognitive_vector_stale`，0.6.38 下这一代**继续可用**，
   9 条当前 revision 里覆盖 8 条，只差刚落库的 r3。

## 6. 测试

### 6.1 新增 `tests/integration/test_recall_context_use_lease.py`（7 项）

| 用例 | 主张 | 基线 `5ad222a` |
| --- | --- | --- |
| `test_expired_lease_with_unchanged_sources_now_authorizes` | 事故本身：只有时钟越过租约 → 出收据 + 一条 `authority_lease_expired`；续租长度=原租约长度、起点=授权时刻；幂等重放逐字同一张收据、说明不重复；`_validate_integrity` 通过 | **红** |
| `test_renewed_lease_never_outlives_the_source_itself` | 记忆自己的 `valid_to` 落在续租窗口内 → `receipt.expires_at == valid_to`；越过之后重校验照旧 fail closed | **红** |
| `test_expired_lease_with_superseded_source_still_fences` | 负控：租约到期 **且** 来源被取代 → `RECALL_AUTHORITY_STALE`、零收据、零说明 | 绿（控制项） |
| `test_expired_lease_with_suppressed_source_still_fences` | 负控：租约到期 **且** 来源被遗忘 → 同上 | 绿（控制项） |
| `test_expired_lease_does_not_excuse_a_policy_change` | 负控：policy version 变化不因租约降级被放行 | 绿（控制项） |
| `test_lease_still_running_is_byte_for_byte_unchanged` | 未受影响路径：`receipt.expires_at` 仍是结果的租约、零说明 | 绿（控制项） |
| `test_epoch_advance_and_lease_expiry_export_two_notes` | 两件事同时发生 → 两条说明，次序固定，epoch 码的 `bound_authority_expires_at` 为 `None` | **红** |

### 6.2 新增 `tests/integration/test_cognitive_vector_conflict_incumbent.py`（4 项）

| 用例 | 主张 | 基线 |
| --- | --- | --- |
| `test_incumbent_vector_admits_the_group` | 查询只落在 incumbent 取值那条轴上（challenger 余弦 0、词面零命中）→ group 仍被准入、两名成员带 exact revision、零退化码。**只可能是 incumbent 的向量做到的** | **红** |
| `test_contest_window_keeps_unrelated_memories_on_the_vector_lane` | 争议刚落库、世代未重建：**无关记忆**照常经向量车道召回，退化码是 `cognitive_vector_partial` 而非 `cognitive_vector_stale`；重建后归零且世代补上两名成员 | **红** |
| `test_resolved_group_drops_the_incumbent_from_the_generation` | 走真实裁决路径（REVISE + `conflict_status=resolved`）后 incumbent 立刻退出世代 | **红** |
| `test_conflict_free_store_keeps_the_0_6_37_manifest_byte_for_byte` | 无冲突组的库：head 清单与 0.6.37 取法逐字同序同集合、manifest hash 相等、世代自证 manifest 相等 | 绿（控制项） |

### 6.3 被有意反转的既有断言（本轮共 5 处）

1. `test_recall_context_use_fence.py::test_policy_change_expiry_and_epoch_regression_still_fence`
   → 改名 `..._policy_change_and_epoch_regression_still_fence`，① 由「租约到期 → 拒」
   改为「租约到期 + 来源全通过 → 收据 + 说明」，②③④ 逐字保留；模块 docstring 同步。
2. `test_typed_recall_cognitive_vector.py::test_confirmation_gate_accepts_vector_hit`
   世代条数 1 → 2，并新增「两名成员的 revision 都在世代里」的断言。
3. 同文件 relation 用例的世代条数 2 → 3。
4. 同文件 `test_stale_generation_degrades_and_lexical_lane_continues`
   → 改写为 `test_partial_generation_keeps_covered_memories_scorable`（退化码
   `stale` → `partial`、断言世代 hash 仍落审计），并新增负控
   `test_text_format_bump_still_degrades_the_whole_lane` 守住「整代不可信」那一支。
5. `test_generation_rebuild_lock_isolation.py` 与
   `test_typed_recall_conflict_short_circuit.py::test_vector_lane_admits_group_only_as_nearest_match`
   各一条（`stale` → `partial`；世代条数 2 → 3）。
   另有 `test_memory_0623_schema_cutover.py` 与 `test_public_api_snapshot.py` 的版本号钉。

### 6.4 全量

`63 failed / 1673 passed / 8 skipped`（基线 `5ad222a`：`63 failed / 1661 passed / 8 skipped`，
独立 detached worktree `../simple-harness-memory-sdk-0638-baseline`）。
**FAILED 集合逐条相同，`diff` 为空**（63 项既有环境失败）。
`ruff check src tests` 与基线同为 **709**。

## 7. 不改 / 边界

- **DDL 与 7.4 checksum 未动**：不加表/列/索引；`cognitive_vectors` 主键本来就允许同一
  世代放同一记忆的两个 revision。已有库不需要迁移；**没有未裁决冲突组的库连世代都不用重建**。
- **降级安全**：0.6.37 读一个 0.6.38 用过的库——`cognitive_vectors` 里可能多出
  incumbent 那一行，0.6.37 的 `_load_cognitive_vector_cache_unlocked` 会因
  「世代 ref 集合 != 当前 head 集合」抛 `active cognitive vector generation is incomplete`
  （**记账：这一格不是静默退化，而是开库失败**，回退需先重建一代）；
  `recall_context_use_receipts` 里多出的续租值只是一个更晚的 `expires_at`，0.6.37 读它无碍。
- **写路径、向量世代构建的三段式与 CAS、`_collect_typed_recall_candidates`、0.6.34 的向量
  相对阈值、entity/task_scope/temporal lane、排序权重与预算、hash 域**全部一字未动。
- **公共面零增减**：`public-api-0.6.38.json` 除 `version` 外与 `public-api-0.6.37.json`
  逐字相同；两个新稳定码分别留在 `core.recall_context_use` 与 `features.cognitive_vector`，
  一个名字都不进根导出（快照测试新增 0.6.38 段并断言之）。

## 8. Host 侧

**不需要配合改动**（Host 只把 `degradation_codes` 原样透传进 `context_route` 回执与
`contested_probe_degradation_codes`，没有白名单），但应知道三件事：

1. **T18 那一类失败会自己消失**：租约到期而来源未变时 SDK 现在签发收据。Host 事件 AA
   的重采机制（`context_use_recollections` / `CONTEXT_USE_LEASE_MARGIN_SECONDS=10`）
   因此从「常态」退化成「兜底」——**建议保留但不必再触发**，它多做的一次召回在
   0.6.38 下是纯开销。真正需要它的只剩「来源真的变了」，而那一支两边都仍 fail closed。
2. **`RecallContext.expires_at = moment + 60` 的语义可以重新定义**（AA 备忘 §9(3)）：
   它现在只是「这次召回结果多久之后需要重新解释」，不再是「整轮用途租约」。
3. **新降级码 `cognitive_vector_partial`**：表示「向量车道可用，但当前世代没覆盖全部
   可召回 revision」。它**不是**故障，出现在每次修订到下一次维护 tick 之间；
   若 Host 有按退化码告警的看板，应把它与 `cognitive_vector_stale` 分开计数，
   `stale` 从此意味着「整代不可信」（渲染格式版本变化或世代损坏），是真正需要看的那个。

仅本地候选（分支 `m0638`），未发布、未构建制品、未合 main、Host 未 pin。

## 9. Followup

- **F-AA-2a（SDK/Host，P2）**：续租长度沿用「结果原本的租约长度」，等于把 Host 的 60 秒
  当成了每轮的续租粒度。真正合理的做法是让调用方按回合预算显式配置（AA 备忘 §9(2) 后半），
  但那要动 `RecallContext` 的形状（冻结的 Harness SDK），另立。
- **F-V-2d（SDK，P2）**：`cognitive_vector_partial` 只说"没覆盖全"，没说"缺哪几条"。
  真要让 Host 判断"这次召回是否可信"，需要把未覆盖的记忆条数落进 typed recall 审计的
  `cognitive_vector` 段。本轮不做（会改审计形状）。
- **F-V-2c（验证，Host）**：0.6.37 遗留——模型拿到 `conflict_notice` 后是否仍采信对话里的
  旧值，仍需真实模型逐字重放复验。未动。
