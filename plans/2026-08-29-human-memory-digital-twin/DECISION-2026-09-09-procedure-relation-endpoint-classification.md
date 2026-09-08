# 裁决：关系端点的分类决定由血缘上最近的已分类祖先承担（F-S1，0.6.35）

> 义务：Host `HM-TO-A6` / 验收 A6-6（同一 plan 新建节点 + relation memory）
> 缺陷来源：Host 事件 S 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-S-RELATION-KEYERROR.md`
> §3「坑二」与 §8 后继 **F-S1（P0，SDK）**
> 分支：`m0635`（基线 `36dac46`，0.6.34）

---

## 1. 现场

Host 在事件 S 的正向用例里量到：一条走满三次独立成功观测、已经进入 `active` 的 Procedure，
head 是 **revision 4**，而 `cognitive_classification_decisions` 只有 **revision 1** 一行。
把它当作 `semantic_relation` 的 `ExistingMemoryTarget` 端点下发，SDK 在
`_resolve_semantic_relation_payload_unlocked` 抛

```
MemoryCorruptionError('relation endpoint classification is missing')
```

**整批分析死掉**——同批的 episode / semantic 一起丢。Host 因此在下发之前按名扣下所有
Procedure 端点（`sdk_procedure_endpoint_unresolvable`，备忘 §4.3），代价是
A6-6 的 Procedure 形态在 0.6.34 上不可达。

本轮在 SDK 侧逐字复现（`tests/integration/test_procedure_relation_endpoint.py`，基线 `36dac46` 红）：
三次真实 `record_procedure_observation` 之后 `committed_revision == 4`、
`lifecycle_state is ACTIVE`、该 memory 的分类行集合恰好是 `(1,)`。

## 2. 根因：分类行从来不是「每版一行」

`cognitive_memory_revisions` 在全仓只有两个写入点：

| 写入点 | 何时 | 是否配分类决定 |
|---|---|---|
| `apply_memory_mutation_plan`（`sqlite_v5.py:8528`） | 每个 mutation operation | **是**，每个 operation 恰好一行（`UNIQUE(principal_id, plan_id, operation_id)`；收据侧还有 `classification decision cardinality differs` 的基数校验） |
| `_copy_cognitive_revision_unlocked`（`sqlite_v5.py:11392`） | 生命周期推进：Procedure 观测提交、Prospective 信号提交 | **否** |

第二个写入点是逐字复制：`content_json` / `content_hash` /
`effective_privacy_class` / `information_attributes_json` / `valid_from` / `valid_to`
全部 `SELECT … FROM cognitive_memory_revisions WHERE revision=base`，
**只有 `lifecycle_state` / `plan_id` / `plan_hash` / `operation_id` / `created_at` 变**；
证据 span 与 task-scope origin 也一并复制。分类策略**根本没有被重新运行**，
因为没有任何东西需要它重新裁定——被分类的那三样东西（内容、隐私类、信息属性）一个字节都没变。

所以「每条 revision 都必须有自己的分类行」**从来不是本仓的不变量**。
0.6.34 的端点解析把它当成了不变量，于是把一条完全健康的血缘判成了损坏。
这条缺陷对 Prospective 端点同样成立（同一个复制函数），只是 Host 至今下发的
Prospective 端点都还停在 revision 1，没有撞上（本轮补了用例，见 §7）。

**S3 契约怎么说。** `slices/S3-cognitive-systems-recall.md:51-52`：
*effective classification 必须单调合并 …，且同事务持久化各 authority/hash 与最终 decision；
任何 classification authority 缺失整批拒绝。* 这句话的主语是 mutation **operation**——
它要求每个 operation 产生并持久化一条决定，**不**要求每条 revision 都有一条。
生命周期推进不是 operation，也从不重跑分类策略。本轮把这条区分与端点解析口径一起
写进契约（`§2-补（2026-09-09，0.6.35）`），不再让后来人从代码里重新推导。

**「至多一条分类决定指向同一 revision」的结构证明**（DDL 上没有这条唯一约束，值得写下来）：
`cognitive_classification_decisions` 只有 `UNIQUE(principal_id, plan_id, operation_id)` 与
`UNIQUE(decision_hash)`；但决定行的 `memory_revision` 恒取自同一事务内刚插入的那个 `revision`
（`sqlite_v5.py:8527` → `:8697`），而 `cognitive_memory_revisions` 的主键是 `(memory_id, revision)`，
两个 operation 不可能声明同一条 revision。所以健康库上「恰好一行」恒成立，
`len(classification_rows) != 1` 只可能取到 `0`。

**旁证：收据复核早就不要求端点这一版有分类行。**
`_decode_and_verify_mutation_receipt_row_unlocked`（`sqlite_v5.py:10166-10183`）重新读端点
revision，核对收据里记下的 `privacy_class / information_attributes / content_hash` 快照是否仍与
活行一致——**全程不查 `cognitive_classification_decisions`**。这是「每版一行」从来不是不变量的
独立证据，也意味着端点隐私类被篡改这一类攻击在收据复核处仍会被抓住。

## 3. 两个候选方案

### (a) 观测提交时补写一条分类行（「每版一行」真的成立）

**否决**，三条理由，任何一条单独成立：

1. **它会伪造审计**。`cognitive_classification_decisions` 的语义是
   「分类策略在某个 plan 的某个 operation 上作出的裁定」——行里钉着
   `policy_id/policy_version/policy_authority_ref/policy_hash`、
   证据权威逐条（`cognitive_classification_evidence_authorities`）、
   `decision_json` 有**闭合的键集合**与 `decision_hash UNIQUE` 且被
   `_decode_and_verify_mutation_receipt_row_unlocked`（`:9730` 起）逐字重算。
   观测提交时并没有跑过分类策略，补写的行只能是**编出来的**：
   `decision_id` / `plan_id` / `operation_id` / `decision_hash` 必须全新（唯一约束），
   于是它既不是任何真实裁定的复制，也无法通过既有的链式复核。
2. **它救不了已有库**。0.6.34 及以前所有观测提交出来的 revision 都缺行；
   补写只对**将来**的提交生效，A6-6 依然要等库里的 Procedure 重新走三次观测。
   要覆盖存量必须做世代重建 / 迁移——本轮明确要避免。
3. **它扩大审计面**。`twin` 血缘 refs 的 `classification` 一支
   （`:15522`，`SELECT decision_hash … ORDER BY memory_revision`）会随之多出行，
   同一条记忆的血缘 ref 集合被改写。

### (b) 端点解析回溯到血缘上最近的已分类祖先 —— **采纳**

契约上这才是正确的表述：**管辖某一版的分类决定，是血缘上最近的已分类祖先的那一条**；
因为从祖先到这一版全是逐字复制，那条裁定**仍然逐字描述着这一版**。

零 DDL、零迁移、零重建；存量库**立刻**可用；观测/信号提交路径一个字节不改，
审计形状零变化（本轮用例显式断言修复后分类行集合仍然是 `(1,)`）。

## 4. 实现

`backends/sqlite_v5.py::_resolve_semantic_relation_payload_unlocked` 的 `resolve()` 内，
把「按 exact revision 查分类行」换成：

```sql
SELECT d.decision_hash, d.memory_revision, r.content_hash,
       r.effective_privacy_class, r.information_attributes_json
FROM cognitive_classification_decisions d
JOIN cognitive_memory_revisions r
  ON r.memory_id = d.memory_id AND r.revision = d.memory_revision
WHERE d.memory_id = ?
  AND d.memory_revision = (SELECT MAX(memory_revision)
                           FROM cognitive_classification_decisions
                           WHERE memory_id = ? AND memory_revision <= ?)
```

判据：

1. 恰好一行且 `decision_hash` 非空——否则
   `MemoryCorruptionError('relation endpoint classification is missing')`（**语句与 0.6.34 逐字相同**）。
   「一条已分类祖先都没有」仍然是真损坏。
2. **管辖决定必须仍然逐字描述这一版**（两条路径都查）：决定行的
   `effective_privacy_class` / `effective_attributes_json` 必须等于端点 revision 行的
   `effective_privacy_class` / `information_attributes_json`。取决定行而不是祖先 revision 行
   是有意的——决定行这两列被 `decision_hash` 锚定（`decision_json` 在收据复核处逐字重算，
   `:9770-9778`），而 revision 行的对应两列没有任何哈希覆盖（`content_hash` 只覆盖
   `content_json`）。两侧在写入时取自同一个 `classification` 对象（`:8455`/`:8720`），
   健康库上恒等。不等则 `MemoryCorruptionError('relation endpoint classification differs')`（新增码）。
   **这一条 0.6.34 完全没有**：它连「这一行是不是仍然描述这一版」都不问。
3. 若命中的 `memory_revision` **不等于**端点 revision，再追加要求祖先 revision 与端点 revision 的
   `content_hash` 相等——复制函数逐字搬运 `content_json`/`content_hash`，内容一旦分叉就不再由那条
   决定管辖。不等则 `MemoryCorruptionError('relation endpoint classification lineage differs')`（新增码）。

**确定性**：`MAX(memory_revision) <= 端点 revision` 是全序上的唯一解；
同一 revision 至多一条分类行（每条 revision 由唯一一个 operation 产生），
所以「恰好一行」在健康库上恒成立，选择与行序、时钟、并发都无关。

**与 0.6.34 的强弱对比，两半都说清楚**：
* **更宽**的一半就是本次修复的目的——被接受的端点 revision 集合**确实变大了**：
  所有由生命周期推进产生的 revision 从「一律判损坏」变成「可继承」。
* **更严**的一半：判据 2 是**新加的**，对 exact revision 与继承祖先两条路径都生效；
  判据 3 又给继承路径加了内容同一性。0.6.34 只检查「有一行且 hash 非空」。
* 诚实的残余：判据 3 比较的是两条 revision 行的 `content_hash`，两行都在同一张未被独立锚定的表里，
  所以它是**必要条件**而不是「机器证明」——一个已经绕过不可变触发器、并把 `content_json` 与
  `content_hash` 改成自洽一对的对手仍可构造。他还必须同时伪造 typed payload 行、证据 span 与
  head CAS；而隐私类/属性那一路变体会在收据复核（§2 旁证）处被抓住。本轮为这个形状补了用例（§7）。

## 5. 边界（本轮一个字节都没动的东西）

* **DDL / schema**：7.4 checksum 不变，**已有库不需要迁移，也不需要重建任何世代**。
* **写路径**：`record_procedure_observation` / `apply_prospective_signal` /
  `_copy_cognitive_revision_unlocked` / `_copy_procedure_payload_unlocked` 全部未改；
  不补写任何分类行。
* **端点解析的其余各门与其顺序**：所有权、head CAS（`relation_endpoint_revision_stale`）、
  `conflict_status`、`_cognitive_recall_state_allowed`（Procedure 仍必须 `active`/`reinforced`）、
  有效时间、`content_json` canonical + `content_hash` 复算、typed payload 行、
  证据 span 非空、`restricted` 不可披露、记忆与逐条证据的 suppression。
* **公共面**：根导出零增减；`public-api-0.6.35.json` 除 `version` 外与 0.6.19 起逐字相同。
* **`cognitive_relations` 与 twin graph 投影**、mutation 收据视图、分类决定链复核：均未改。
* **降级安全**：本轮不写任何新行、不加任何列，所以 0.6.34 读一个 0.6.35 写过的库
  看到的字节与自己写出来的完全一样（只会重新拒绝那些它本来就拒绝的端点）。
* **代价（记账，不修）**：`cognitive_classification_decisions` 上没有
  `(memory_id, memory_revision)` 索引，相关子查询 + 外层查询是两次扫描，0.6.34 是一次，
  即每个端点 ×2、每条关系 ×2 端点。加索引要动 DDL 与 7.4 checksum，本轮明确不做。

## 6. 诚实记账：F-S1 只解除了一半

备忘 §8 的 F-S1 是**两条**：

1. 观测提交的 Procedure revision 没有分类行 → 端点解析判损坏。**本轮已修。**
2. `check_history_visibility` 对 Procedure 永远 stale：
   `backends/history_visibility.py` 在调用
   `_validate_recall_context_use_sources_unlocked` 时写死
   `procedure_applicability_fingerprints=frozenset()`（注释：*"never reuse old runtime fingerprints"*），
   于是 `_cognitive_recall_type_authority_allowed_unlocked` 对任何 Procedure 返回 False
   → `RECALL_AUTHORITY_STALE` → `history_source_stale`。**本轮未动。**

第二条**不是一个 bug 修复，而是一次契约扩面**：要让它放行，
`check_history_visibility` 必须接受调用方提供的当前适用性指纹，
这要同时改 `core/port.py` 的抽象方法、`core/manager.py` 的公共 facade 与后端实现，
是一次**公共 API 新增**；并且它会把备忘 §4.1 那笔取舍
（`applied_use_fingerprints` 保住「用过」、放弃「此刻仍适用」）从"今天没有暴露面"
变成"直接决定 `check()` 放不放行"。备忘 §4.1 自己写明这笔取舍在 F-S1 解除时
**必须重新裁定**。本轮不在无人裁定的情况下替 Host 作这个决定，另立版本处理。

**结论：Host 现在还不能解除 `sdk_procedure_endpoint_unresolvable` 的扣留**——
解除后端点解析会通过，但 `check()` 那一关（备忘 §4.4 让 Procedure 候选直接
`analysis_candidate_no_longer_visible`）仍会打掉整批。本轮的价值是把
F-S1 的两条里**结构上更难的那条**（伪造审计 vs 世代重建的两难）消掉，
剩下的一条是纯粹的接口 + 裁定问题。

## 7. 测试

新增 `tests/integration/test_procedure_relation_endpoint.py`（6 项）：

| 用例 | 断言 | 基线 `36dac46` |
|---|---|---|
| `..._resolves_and_projects_edge` | 三次真实观测提交 → head=4 / ACTIVE / 分类行仅 `(1,)`（事故现场）；关系 plan 提交成功；`cognitive_relations` **恰好 1 行**且 `applies_to` 指向 `procedure@4`；twin graph **1 条边**且**两端**都在节点集合里；reopen 后边逐字相同；**分类行集合仍是 `(1,)`**（修复只改读） | **红**：`classification is missing` |
| `..._is_typed_recallable_at_the_same_revision` | typed recall（`FULL_TEXT` + 真实 `applicability_fingerprint`）命中的 exact revision 与**落库的那条边**指向同一版（读 `cognitive_relations` 回来比，不与同一个 Python 变量比） | **红** |
| `..._without_any_classified_ancestor_stays_corrupt` | 整条分类链摘掉后仍 `classification is missing`、零副作用；并断言这样的库**连重开都不该成功**（收据链复核先一步 fail closed）——这也是本文件唯一在打开的连接上篡改的用例的理由 | 绿（守卫） |
| `..._whose_decision_no_longer_describes_it_is_corrupt` | 关掉 → 篡改端点 revision 的 `information_attributes_json` → 重开 → `endpoint classification differs`、零副作用 | **红**：报 `missing`（该判据在 0.6.34 上根本不存在） |
| `..._content_forked_from_its_classified_ancestor_is_corrupt` | 关掉 → 把 `content_json` 与 `content_hash` 改成**自洽的一对**（绕过更早的内容门）→ 重开 → `classification lineage differs`、零副作用 | **红**：报 `missing` |
| `..._signal_committed_prospective_endpoint_resolves_and_projects_edge` | Prospective 走 `REGISTRATION_ACCEPTED` + `TIME_DUE` 到 `TRIGGERED`（head=revision 2、分类行仍只有 `(1,)`）；同一条继承路径放行；落 1 行 `cognitive_relations` + twin graph 边 | **红**：`classification is missing` |

除守卫用例外 5 项在基线 `36dac46` 上红、本分支绿（把本文件原样拷到基线 detached worktree 实跑核对）。

## 8. 回归

| 项 | 本分支 `m0635` | 基线 `36dac46`（独立 detached worktree） |
|---|---|---|
| 全量 `tests/` | **63 failed / 1644 passed / 8 skipped** | 63 failed / 1638 passed / 8 skipped |
| 失败集合 diff | **空**（63 项既有环境失败逐条相同） | — |
| `ruff check src tests` | **709** | 709 |

新增 6 项全部计入 passed 增量（1638 → 1644）。

## 8.1 独立评审（opus，只读）与处置

| 评审意见 | 处置 |
|---|---|
| **MUST-FIX 1**：新不变量只活在裁决备忘里；S3 从未写过关系端点解析；`S3:51-52` 那句「任何 classification authority 缺失整批拒绝」是读者会指着说话的条款，却没被正面回应；仓内先例（`§4-补`，0.6.30）是直接改 slice | **已改**：新增 `slices/S3-cognitive-systems-recall.md` 的 `§2-补（2026-09-09，0.6.35）`，七条：Task 2 那句话的适用范围是 operation 而非 revision、祖先归属规则、两条继承自证条件、**端点解析的完整门序**、端点分类作为关系记忆的下界、F-S2 的离线车道口径、F-S1b 未闭合。§2 同步补上对 `S3:51-52` 的正面引用与「至多一条决定指向同一 revision」的结构证明 |
| **N1**：`d.effective_privacy_class` / `d.effective_attributes_json` 取回来却没用；比较两条 revision 行等于比较两条**都没有被哈希锚定**的记录，「机器证明」说过头；且 exact revision 路径今天完全没有内容校验 | **已改**：判据 2 改为比较**决定行**（被 `decision_hash` 锚定）与端点 revision 行，且**两条路径都查**；判据 3 只留 `content_hash` 的祖先同一性。§4 把「机器证明」降级为「必要条件」并写清残余对手模型 |
| **N2**：在打开的连接上篡改是全仓孤例（其余六处都是 close→tamper→reopen），且依赖 `close()` 的 `_validate_integrity` 恰好不看这两处，将来会在 teardown 里以无关异常掩盖真断言 | **已改**：漂移与分叉两个用例改为 close→tamper→reopen（更强：证明拒绝是持久的）。「无已分类祖先」那个**不可能**这么写——那样的库收据链复核在 initialize 处就 fail closed；用例改为显式断言这一点，并在 teardown 直接释放连接而不是走完整性校验 |
| **N3**：typed recall 用例的 `apply` 调用是未被断言的 setup，删掉照样绿 | **已改**：读回 `cognitive_relations.target_revision`，与召回结果比对 |
| **N4**：`§7` 声称「两端都在节点集合里」，用例只断言了 target 端 | **已改**：断言 `{source, target} <= node_ids` |
| **N5**：`§4` 小标题「为什么比 (a) 更严」，正文论证的是比 **0.6.34** 更严；且没说被接受的端点集合其实变大了 | **已改**：改写为「与 0.6.34 的强弱对比，两半都说清楚」，明写更宽的一半 |
| **N6**：`§8` 写「见提交信息」，而 CHANGELOG 已有真数字——未提交工作树的裁决备忘不该拿提交信息当证据 | **已改**：数字内联 |
| **N7**：Prospective 走同一条继承路径，0.6.35 起首次可解析，零用例 | **已改**：新增端到端用例（本节表格第 6 行） |
| **N8**：`cognitive_classification_decisions` 上没有 `(memory_id, …)` 索引，两次扫描 vs 0.6.34 一次 | **已记账**（§5 最后一条）；加索引要动 DDL 与 7.4 checksum，本轮不做 |
| 评审确认无需改动的部分 | 两个写入点与逐字复制、链连续性、确定性（`MAX` 唯一解、争议/supersede 自带决定行、contested 端点更早被拒）、hash 形状不变、迁移干净、§6 对 F-S1 剩余一半的描述逐条属实、把那一半排除在 0.6.35 之外是对的 |

## 9. 后继

* **F-S1b（P0，SDK）**：`check_history_visibility` 的 Procedure 适用性指纹入口（§6 第 2 条）。
  解除时必须**同时**重新裁定备忘 §4.1 的
  `applied_use_fingerprints`（放弃了「此刻仍适用」）能否作为 `check()` 的复核依据，
  并给 Host 的 `check()` 补上备忘 §4.4 要求的真正复核路径。
* **F-S2**（备忘 §8）：离线车道用 `request.run_id` 构造 `RecallContext` 而指纹来自持久化使用，
  S3 契约值得补一句离线口径。本轮未涉及。
* Prospective 端点在信号提交之后也会走到同一条继承路径；本轮的修复对它同样生效，
  但没有为它单写用例（同一个 `_copy_cognitive_revision_unlocked`）。
