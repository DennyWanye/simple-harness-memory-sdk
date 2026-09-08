# 裁决：离线车道可以提交自己召回时所用的 Procedure 适用性指纹（F-S1b，0.6.36）

> 义务：Host `HM-TO-A6` / 验收 A6-6（同一 plan 新建节点 + relation memory，Procedure 形态）
> 缺陷来源：0.6.35 裁决备忘 `DECISION-2026-09-09-procedure-relation-endpoint-classification.md`
> §6 第 2 条 / §9 **F-S1b（P0，SDK）**；再往上是 Host 事件 S 备忘
> `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-S-RELATION-KEYERROR.md` §3「坑一」/ §4.4 / §7
> 分支：`m0636`（基线 `b82187e`，0.6.35）

---

## 1. 现场：F-S1 剩下的那一半

0.6.35 修好了端点**解析**（分类决定由血缘上最近的已分类祖先承担），
但 Host 的 `SemanticCorrectionAuthority.check()` 走的是另一条路——
它把候选交给 `check_history_visibility` 重新复核披露。而
`backends/history_visibility.py` 在调用 `_validate_recall_context_use_sources_unlocked` 时写死：

```python
# No current procedure applicability was supplied: never reuse old runtime fingerprints.
procedure_applicability_fingerprints=frozenset(),
```

`_cognitive_recall_type_authority_allowed_unlocked` 对 `memory_type == "procedure"` 的判据是
「该版 `procedure_records.applicability_fingerprint` 不是 unbound 哨兵**且在给定集合里**」，
空集合 ⇒ 恒 False ⇒ `RECALL_AUTHORITY_STALE` ⇒ `history_source_stale` ⇒
Host 整批 `analysis_candidate_no_longer_visible`。

所以 0.6.35 之后 Host 仍然只能在**下发之前**扣下所有 Procedure 端点
（事件 S 备忘 §4.3 的具名扣留），A6-6 的 Procedure 形态依旧不可达。

那句注释本身**是对的**，它防的是一个真实的洞：`check_history_visibility` 拿到的是
`DisclosureContext`（本轮之前 `core/port.py:337`、`core/manager.py:197`），不是 `RecallContext`；
如果它顺手去读那条已存召回请求里的 `procedure_applicability_fingerprints`，
就等于让一次**任意晚**的复核继承一次**任意早**的运行时状态——
「此刻是否适用」会被一份陈旧快照冒名顶替。

**本轮要解决的正是这个两难**：既不让前台复核replay 旧指纹，又让一条**本来就没有活着的 Run**
的离线车道能够用它召回时所用的同一份事实完成复核。

## 2. 三个候选方案

### (a) 让 `check_history_visibility` 自己去读那条召回请求的指纹

**否决**。这正是注释所禁止的行为，且它对**所有**调用方生效——
前台历史页复核、当前输入观察、短时域来源展开都会一起继承旧指纹。
一次复核之所以有意义，是因为它在**当下**重新问一遍；
从持久化请求里翻出当时的答案再抄一遍，等于把复核变成回放。

### (b) 加一个「跳过 Procedure 适用性」的布尔开关

**否决**。它把「这一条为什么可以放行」变成了「调用方要求不检查」，
收据里只剩一个 `True`，与事件 S 备忘 §4.4 批评过的「装好引信的洞」同型：
一旦有人在前台车道打开它，Procedure 就零适用性进入披露，而审计说不出任何理由。

### (c) 显式 provenance 的 attestation + Memory 自己的观测审计佐证 —— **采纳**

调用方**主动提交**一份 `ProcedureApplicabilityAttestation(provenance, fingerprints)`：
`provenance` 是一个闭合枚举，今天只有 `applied_use_fingerprints` 一个成员，含义被契约钉死为
**「这些指纹属于 Memory 已经消费过其观测的那些使用」——即"曾经真的用过"，不承诺"此刻仍适用"**。

两条判据分工要说准（评审 MUST-FIX 2 纠正了本备忘第一版的过头说法）：

* **判据 ②（既有）已经把调用方钉死在 Memory 自己的值上**。类型权威门比的是
  `procedure_records.applicability_fingerprint` 这一列，而该列**只**由观测提交路径写入
  （`sqlite_v5.py:7254` / `:11092`）。所以「Host 表被改、被伪造、被换实现」根本过不了 ②——
  编出来的指纹与库里存的那一个对不上。这一半**不是**本轮新增的。
* **判据 ③（新增）加的是另一件事**：把「这个指纹**被绑定**过」升级为
  「它**被一次成功且可归因的使用**背书过」。第一次观测无论成败都会绑定指纹
  （`sqlite_v5.py:18666-18670`），因此在健康库上存在一条 ③ 真正起作用的路径：
  指纹由一次失败/非终态观测绑定，之后该 Procedure 由 `EXPLICIT_USER` 的
  correct/supersede 从 DRAFT 直接推到 ACTIVE（合法，`core/cognitive.py:426-435`），
  epoch 只在 CREATE/REVISE 重置因而指纹被继承——①②与状态门都放行，③ 拒绝。

`procedure_observations` 是 **Memory 自己的**表：append-only、有不可变触发器、
且在 open 时被逐字复核（本轮实测：改掉其中一列，库直接开不起来，
报 `procedure observation columns differ`）。

于是这次扩面不是「相信调用方」，而是「**要求调用方指出一条 Memory 自己成功用过的事实**」。
诚实记账：本轮为 ③ 写的用例走的是**篡改库**那条路；上面那条健康库路径已识别但未单写用例。

## 3. 契约

`slices/S3-cognitive-systems-recall.md` 新增 `§2-补2（2026-09-09，0.6.36）`，七条：
缺省即 0.6.35（连收据键都不多一个）；唯一入口与 provenance 语义；作用面只到
`HistoryRecallBinding`（当前输入入口显式拒绝）；三条放行判据与「其余各门一条不少」；
收据形状；**重新裁定 §2-补.6 的取舍**；F-S1 两条至此全部闭合。

## 4. 实现

| 位置 | 改动 |
|---|---|
| `core/history.py` | 新增 `ProcedureApplicabilityProvenance`（枚举，1 个成员）、`ProcedureApplicabilityAttestation`（构造期要求已排序、去重、1..256 条 → 同一集合恒得同一 `attestation_hash`）、`ProcedureApplicabilityReceipt`；`HistoryVisibilitySnapshot` **在 `schema_version` 之后**追加 `procedure_applicability`，`to_json` 只在非 `None` 时输出该键 |
| `backends/history_visibility.py` | `check_history_visibility` 增加可选 kwarg；`_Applicability` 持有 `frozenset` 与逐条命中标记；`_recall` 把它交给 `_validate_recall_context_use_sources_unlocked`（缺省仍是 `frozenset()`）；末尾那条 `valid_to` 查询顺带取回 `memory_type`，Procedure 走新的 `_applied_procedure_applicability` 佐证；attestation 计入 `request_hash` 与快照收据 |
| `core/port.py` / `core/manager.py` / `backends/sqlite_v5.py` | 抽象方法 + 公共 facade + 后端实现同步加可选参数；facade **只在调用方真的提交时才转发这个 kwarg**，早于 0.6.36 的后端因此照常工作 |
| `__init__.py` | 三个新根导出，`__version__ = "0.6.36"` |

**放行判据（离线路径）**，三条同时成立：
① 端点这一版 `procedure_records.applicability_fingerprint` 不是 `UNBOUND_PROCEDURE_APPLICABILITY`；
② 它在调用方提交的集合里（既有的类型权威门）；
③ 该 memory 上存在成功且可归因的 `procedure_observations` 携带同一指纹（**本轮新增**）。

**其余各门一条不少**：`_validate_recall_context_use_sources_unlocked` 的 head CAS、
`content_hash`、状态门、有效时间、隐私类与信息属性、记忆与逐条证据的 suppression，
以及整批的 `_ordinary_recall_disclosure_allowed` / 收件人绑定 / 主体一致，全部照原样先跑。
attestation 只能把「Procedure 恒 stale」这一条变成「Procedure 按既有判据裁定」。

**fail closed**：不提交 ⇒ 逐字等于 0.6.35（用例断言快照 JSON 里连 `procedure_applicability`
这个键都不出现）；提交给当前输入观察入口 ⇒
`MemoryValidationError('history_current_input_rejects_procedure_applicability')`；
非 canonical 类型 ⇒ `TypeError`。

**确定性**：集合成员判定与 `EXISTS` 与行序/时钟/并发无关；
`admitted_binding_hashes` 按调用方绑定顺序生成；
同一时钟下同一请求两次调用 `to_json()` 与 `snapshot_hash` 逐字相同（用例断言）。

## 5. 重新裁定：`applied_use_fingerprints` 能不能当复核依据

事件 S 备忘 §4.1 把这笔取舍写得很清楚，并要求「F-S1 解除时**必须**重新裁定」。

* **保住**：「从未被真实用过的 Procedure 不露面」。
* **放弃**：「而且它**此刻**仍然适用」——离开 Run 没有当前工具集可以重算 `current_snapshot`。

**裁定：可以，三条理由。**

1. **保住的那一半现在被收紧到「成功且可归因地用过」**。「指纹必须等于 Memory 自己存的那个值」
   由既有判据 ② 保证（该列只由观测提交写入），Host 编不出来；本轮判据 ③ 在此之上要求
   同一指纹被一条 `outcome='success' AND attributable=1` 的 `procedure_observations` 背书，
   于是「用过」不再包含「只是被一次失败观测绑定过」。
2. **佐证来源被链锚定**。`procedure_observations` 的 append-only + 不可变触发器 +
   open 时逐字复核，使「见证」这件事本身站得住（用例实测：篡改后库开不起来）。
3. **它只是复核，不是授权**。端点在 apply 时仍被 `_resolve_semantic_relation_payload_unlocked`
   逐门重解析（S3 §2-补.4），Procedure 仍必须 `active`/`reinforced`。

**诚实记账（残余暴露面，不修）**：一个工具后来改名 / 换签 / 被撤的 Procedure，
其**前台**召回会消失（`current_fingerprints` 重算不上），但离线车道仍可把它作为关系端点提交。
代价是可能出现一条 `applies_to` 指向「当前不可用、但确曾被真实用过」的流程。
这条边本身仍带 exact revision，遗忘 / suppression / 冲突 / 状态各门照常对它生效，
且「曾经用过」本来就是一条**历史陈述**——一条记录「这个事实适用于那个流程」的关系记忆，
其真值并不随工具改名而失效。要彻底消掉这条残余，唯一正确的方向是让 Host 把
「适用性快照」本身持久化成可离线重算的事实，那是另一次立项（记为 F-S1c）。

## 6. 边界（本轮一个字节都没动的东西）

* **DDL / schema**：7.4 checksum 不变，不加表、不加列、不加索引，已有库不需要迁移或重建。
* **降级安全**：不写任何新行；0.6.34/0.6.35 读一个 0.6.36 用过的库看到的字节完全一样。
  快照的新键只在**返回值**里，不落库。
* **写路径**：观测提交 / 信号提交 / mutation apply 一个字节未动。
* **前台车道**：`execute_typed_recall` 及其三处 `context.procedure_applicability_fingerprints`
  未动；`check_history_visibility` 的缺省行为逐字不变。
* **`cognitive_relations` 与 twin graph 投影**、收据视图、分类决定链复核：均未改。
* **代价（记账，不修）**：判据 ③ 每条 Procedure 绑定多两次点查——`procedure_records` 主键命中，
  加上 `procedure_observations` 上一次**索引搜索**：查询里的 `outcome='success' AND
  attributable=1` 恰好蕴含部分索引 `procedure_observation_success_scope_unique` 的谓词，
  实测 `EXPLAIN QUERY PLAN` 为 `SEARCH … USING INDEX procedure_observation_success_scope_unique
  (memory_id=?)`（非覆盖，但不是扫描）。不加任何索引，DDL 与 7.4 checksum 不动；
  一批复核里 Procedure 绑定的数量以关系端点候选数为上界（≤ 8）。

## 7. 测试

新增 `tests/integration/test_history_procedure_applicability.py`（9 项）。
Procedure 走满三次真实 `record_procedure_observation` 进 `active`（复用 0.6.35 的 `_active_procedure`），
用**真实** `applicability_fingerprint` 做一次公开 typed recall，再把选中项绑成
`HistoryRecallBinding`——与 Host 分析车道逐字同形。

| 用例 | 断言 |
|---|---|
| `..._stays_stale_without_an_attestation` | 缺省逐字保留：`history_source_stale`，且快照 `to_json()` 里**没有** `procedure_applicability` 这个键 |
| `..._admit_the_procedure_binding` | 同一条绑定带 attestation 即 `history_visible`；收据的 provenance / `attestation_hash` / count / **逐条命中**齐全；两次调用 `to_json()` 与 `snapshot_hash` 逐字相同；`request_hash` 与不带的那次**不同**（attestation 真的进了请求身份） |
| `..._without_the_endpoint_fingerprint_admits_nothing` | 指纹对不上 ⇒ 仍 stale，收据如实记「提交过、一条没放行」 |
| `..._observation_audit_does_not_corroborate_is_refused` | 判据 ③ 单独量出：篡改前可见 → 把三条观测的指纹改掉（`procedure_records` 不动，②仍成立）→ 同一 attestation 变 stale；随后断言这样的库**重开即 fail closed**（`procedure observation columns differ`）——这既是本文件唯一在打开连接上篡改的理由，也是判据 ③ 站得住的根据 |
| `..._never_touches_non_procedure_bindings` | 同一批里的 semantic 绑定带不带 attestation 逐字同结果，且**不进**命中清单；Procedure 那一条进 |
| `..._rejected_on_the_current_input_entry_point` | `history_current_input_rejects_procedure_applicability`；非 canonical 类型 `TypeError` |
| `..._disclosure_bound_like_every_other_history_check` | `generation=STALE` 时 Procedure 仍不可见，命中清单为空——attestation 不绕过任何既有门 |
| `..._canonical_form_is_fail_closed` | 未排序 / 重复 / 空集 / 257 条 / 错 provenance / 非 tuple / 空串全部构造期拒绝；同集合同哈希、异集合异哈希 |
| `..._facade_forwards_only_when_supplied` | 不提交时 facade **不向后端传这个 kwarg**（早于 0.6.36 的后端照常工作），提交时才传 |

基线 `b82187e` 上整文件收集即失败（`AttributeError: ProcedureApplicabilityProvenance`）——
这是一次公共面新增，预期如此。

## 8. 回归

| 项 | 本分支 `m0636` | 基线 `b82187e`（独立 detached worktree） |
|---|---|---|
| 全量 `tests/` | **63 failed / 1653 passed / 8 skipped** | 63 failed / 1644 passed / 8 skipped |
| 失败集合 diff | **空**（63 项既有环境失败逐条相同） | — |
| `ruff check src tests` | **709** | 709 |

新增 9 项全部计入 passed 增量（1644 → 1653）。
`public-api-0.6.36.json` 是 0.6.19 以来**第一次**真正的根导出扩张：只多三个名字，
`removed_public_methods` 与 `migrations` 逐字未变；快照测试改为显式断言这一点。
`test_memory_0623_schema_cutover.py:77` 的版本钉死顺延到 0.6.36（7.4 checksum 不变）。

## 9. 独立评审（opus，只读）与处置

| 评审意见 | 处置 |
|---|---|
| **MUST-FIX 1**：`git diff main` 显示 PROGRESS 的 §十八（A6 第 9 次跑完那一节）被删 | **不成立，已核实**：本分支基线是 `b82187e`，那一节由 main 在**之后**的 `1b2d0ab` 追加，本分支从未持有过它。本轮只在文件末尾追加 §十九，一行未删；合并时两段各自追加、无内容冲突 |
| **MUST-FIX 2**：判据 ③ 的论证过头——「Host 表被改、被伪造都不足以通过」这一半**本来就**由既有判据 ② 保证（②比的是 `procedure_records.applicability_fingerprint`，该列只由观测提交写入），③ 真正加的是把「被绑定过」升级为「被一次成功且可归因的使用背书过」；并给出健康库上 ③ 唯一起作用的路径（失败观测绑定指纹 + `EXPLICIT_USER` correct/supersede 推到 ACTIVE） | **已改**：§2(c)、§5、CHANGELOG、三份 ARCHITECTURE、PROGRESS 与 S3 `§2-补2.4` 全部改写为两条判据的准确分工，并把那条健康库路径写进 §2；同时按评审给的第二选项**明写**「本轮为 ③ 写的用例走的是篡改库那条路，健康库路径已识别但未单写用例」，记入 §11 |
| **MUST-FIX 3**：代价记账写错——查询里的 `outcome='success' AND attributable=1` 恰好蕴含部分索引 `procedure_observation_success_scope_unique` 的谓词，实为索引搜索而非扫描 | **已改并自行复算**：`EXPLAIN QUERY PLAN` = `SEARCH procedure_observations USING INDEX procedure_observation_success_scope_unique (memory_id=?)`。§6、CHANGELOG、三份 ARCHITECTURE 同步改写，§11 里那条「缺索引」的后继删除 |
| **N2**：③ 不看 `qualification_epoch` / `procedure_revision`，退休 epoch 的见证也能背书当前端点 | **不改代码，改契约**：复制链上指纹逐字继承，这正是「一条旧 revision 的成功观测背书当前 head」被允许的原因；S3 `§2-补2.4` 与 CHANGELOG 显式写明匹配口径是 **memory + 指纹**，不含 revision/epoch |
| **N3**：`admitted_binding_hashes` 被描述成「集合」，实为按绑定顺序的列表，重复绑定会出现两次 | **已改** docstring |
| **N4**：S3 把 `conflict_status` 列进「一条不少」，但 confirmation 成员的状态门本就 `allow_contested=True` | **已改**：`§2-补2.4` 加上这条例外，并写明 apply 时 §2-补.4 仍要求 `uncontested`，不产生新暴露面 |
| **N5**：当前输入入口的拒绝写得比守卫强 | **已改** `§2-补2.3` 措辞（入口本身不接受该参数；后端在两者同时出现时显式拒绝） |
| **N6**：`ProcedureApplicabilityReceipt` 是根导出却没有 `__post_init__` | **已改**：补 provenance / 哈希形状 / 计数 / 逐条 hash 的构造期校验 |
| **N7**：`CognitiveMemoryBackend` 协议多了一个形参，快照只记名字看不到 | **已记账**：CHANGELOG 公共面一栏写明第三方后端运行时照常（协议非 `runtime_checkable`，全仓无 `isinstance`，facade 只在提交时转发），但静态类型检查需要跟进 |
| **N8**：CHANGELOG 引的 `core/port.py:337` / `core/manager.py:197` 是改动**前**的行号 | **已改**：加「本轮之前」限定 |
| **N9**：「semantic 绑定逐字同结果」的断言弱于说法 | **已改**：改为比对整个 item 的 `to_json()` 与 `valid_until` |
| **N10**：`pytest.raises((ValueError, MemoryValidationError))` 冗余（后者是前者子类），且掩盖了两类具体异常 | **已改**：分别断言 `ValueError` 与 `MemoryValidationError` |
| **N11**：篡改用例只断言 `MemoryCorruptionError`，而备忘引了确切语句 | **已改**：加 `match="procedure observation columns differ"` |
| **N1**：`_applied_procedure_applicability` 重读 `procedure_records`、重算 ①②，可以省一次点查 | **不改**：这两条本就记在「多两次点查」的账里；把判据写全在一处比省一次主键命中更值得，且它让离线路径不依赖上游门的求值顺序 |
| **N12**：`test_procedure_observation_repository_v5` 的一处失败与本轮无关 | 已复核，属既有 63 项环境失败之一 |
| 评审确认无需改动的部分 | 新 JOIN 不可能改变任何既有行集或 `valid_until`（`cognitive_memory_heads.memory_id` 是主键，且该 head 已被上游门证明存在）；不提交 attestation 时 `to_json` / `request_hash` / `snapshot_hash` 与 0.6.35 逐字相同、位置式构造不变；新 kwarg 从短时域两个 resolver 与当前输入入口都不可达；门序未变且 ③ 是严格追加的 AND；确定性成立 |

## 10. Host 侧

Host 本轮同步解除扣留（分支 `worktree-f-s1b`，备忘
`simple_harness/plans/2026-09-08-hm-to-a6/DECISION-F-S1B-PROCEDURE-ENDPOINT-LIFT.md`）：
按**能力探测**（根导出三个类型 + facade 有 `procedure_applicability` 参数）而不是版本号，
因此同一份 Host 代码在 0.6.34/0.6.35 上继续扣留、在 0.6.36 上放行；
召回时的指纹被持久进候选快照，`check()` 用**同一份**构造 attestation，
并**复核返回的收据**（`attestation_hash` 相等且每条 Procedure 绑定都在
`admitted_binding_hashes` 里）——一个接受 kwarg 却什么都不做的后端因此也进不去。

## 11. 后继

* **F-S1c（P2）**：把「适用性快照」持久化成可离线重算的事实，消掉 §5 的残余暴露面。
* **F-S2**（事件 S 备忘 §8）：离线车道用 `request.run_id` 构造 `RecallContext` 而指纹来自
  另一组事实——S3 §2-补.6 已把口径写进契约，字段名本身仍未改（改名是 wire 变更，另立）。
* 判据 ③ 在健康库上唯一起作用的那条路径（§2 第二个要点：失败观测绑定指纹 + 显式
  correct/supersede 推到 ACTIVE）尚无专门用例，本轮只由篡改库用例覆盖。
