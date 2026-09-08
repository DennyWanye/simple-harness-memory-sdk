# 401 矩阵四个公共见证增量（Memory 0.6.32）

> 2026-09-09。分支 `m0632`（基线 main `fc7fa88`，0.6.31）。未合 main、未构建 wheel、Host 未 pin。
> 上游需求：Host `simple_harness/plans/2026-09-07-corpus-c01-local/TYPED-RECALL-401-RUN-08.md`
> §2.I-1 / §2.I-2 与 §7 后继第 4 项（同一份需求在 `TYPED-RECALL-401-RUN-07.md` §3.1 的
> D / E 两组里给出了精确 file:line）。
> 用户授权：技术取舍由执行者作为独立裁决人裁定、记录并实施，不回问。

## 0. 一句话结论

**四个增量全部落地，公共错误类、冻结枚举、Harness v4 wire 形状、DDL（7.4 checksum）、根导出
一律未动。** 默认部署（不声明策略版本）的 `policy_hash` / decision / result / 用途收据
与 0.6.31 源**逐字节相同**（在独立 worktree `simple-harness-memory-sdk-0631-source` 上跑同一
脚本，`diff` 为空，字面值已钉进单测）。唯一有意的字节变化是 **contest 家族拒绝审计行的
`reason_code`**——那正是增量 (c) 要交付的东西。

| 增量 | 401 格 | 公共调用 / 字段 | 实现位置 |
|---|---|---|---|
| (a) 召回策略版本入口 | `current-use/authority:policy_hash_change`（1） | `MemoryManager.build_human_memory_v7(..., recall_policy=RecallEligibilityPolicyV1(n))`；`await manager.read_recall_policy(principal=…)` → `RecallPolicyStateV1.policy_version / policy_hash / authority_policy_hash / policy_changed` | `core/recall_policy.py`（新）、`backends/sqlite_v5.py:300`（常量改为按版本导出）、`:405`（构造参数）、`:6285`（`_reconcile_recall_policy_unlocked`）、`:6371`（`read_recall_policy`）、`:4790`（用途围栏判据）、`core/manager.py:490` |
| (b) 短时域清理公共入口 | `current-use/authority:short_source_cleanup`（1） | `await manager.cleanup_short_horizon(principal=…, now=None)` → `int`（被删除的 chunk 数） | `core/manager.py:508`（转发到既有 `core/port.py:465` 的 backend 方法） |
| (c) apply validation 精确 reason | conflict 精确 reason（3） | `await manager.read_memory_mutation_validation_notes(principal=…, plan_id=…)` → `MemoryMutationValidationNoteV1.reason_code`（六个稳定码之一） | `core/mutation_rejections.py`（新）、`backends/sqlite_v5.py:10331`（拒绝审计映射）、`:10480`（只读导出）、`core/manager.py:497` |
| (d) 执行 lane 见证 | executed-lane（3） | `TypedRecallExecution.executed_lanes`（本次真的产出被选中项的 lane）与 `.item_lane_witnesses[i].lanes / .lane_ranks / .source_kind / .item_id` | `core/recall.py:220`（`TypedRecallLaneWitnessV1` / `lane_witnesses` / `executed_lanes`）、`:503`（`build_host_execution` 填充） |

---

## 1. (a) 公共召回策略版本入口

### 1.1 问题

`_RECALL_POLICY_HASH` 是 `backends/sqlite_v5.py:300-315` 的模块常量，由
`{"policy":"typed-recall-eligibility/v1","schema":6,"rrf_k":60,"weights":{…}}` 的 canonical
sha256 得出。S3 slice §5.4 把「policy version 变化」列为召回权威的推进车道，`policy_hash`
又是 `authorize_recall_context_use` 的**硬**判据；但公共面没有任何版本入参，于是
「策略变更使此前签发的用途授权失效」这条安全属性在公共契约上**不可见证**。

### 1.2 裁决：把版本号写进 policy id，而不是另加一个键

三个候选方案：

| 方案 | 默认字节 | 语义 | 结论 |
|---|---|---|---|
| A. payload 加 `"policy_version": n` 键 | 默认要么加键（**hash 变**）要么条件加键（不对称、易漂移） | 版本与 policy id 分家 | 否 |
| B. 让整个 eligibility policy 可注入（权重/RRF_K 都可改） | 默认不变 | 但会让 `core/recall.py` 的 `RRF_WEIGHTS` 与注入值两处并存，S3 §5.6 的冻结排序失去单一真相 | 否 |
| **C. `policy` 键就是版本：`typed-recall-eligibility/v{n}`** | **v1 逐字不变** | 版本号本来就写在 policy id 里，零新键、零不对称 | **采纳** |

`recall_policy_payload(1)` 的 canonical JSON 与 0.6.31 常量逐字相同，`recall_policy_hash(1)`
恒等于 `c27604aa…fc04`（该字面值同时钉在 `core/recall_policy.py` 与两处单测里，且
`backends/sqlite_v5.py` 用 `assert` 把常量与函数绑死，杜绝两处字面值漂移）。

**本字段不改变资格语义。** SDK 只实现 v1 的资格门；字段声明的是「本部署跑的是哪一版资格
策略」。部署方改了资格判据就必须 bump 版本，好让之前签发的用途授权按 S3 §5.4 失效。
版本号是 `1 .. 1_000_000` 的严格整数（`bool` 不算 `int`），构造期校验。

### 1.3 「立即失效」与「审计对齐」拆成两件事（关键裁决）

权威头 `recall_authority_heads.policy_hash` 是 durable 的；换版本后它仍停在旧值。两个诉求：

1. **安全属性必须立即成立**：旧策略签发的结果不得再被授权，**不能等**任何一次写入；
2. **对齐必须留审计**：真的换了策略要在 `recall_authority_events` 里留一条事件。

裁决：**判据用配置值（纯读），对齐用事件（写在能提交的路径上）。**

* `authorize_recall_context_use`（`:4790`）的硬判据加一条
  `self._recall_policy_hash != result.policy_hash`。它是**纯读**，因此在拒绝路径上
  （该事务紧接着 ROLLBACK）依然成立——这一点是把对齐写进 authorize 事务的方案**做不到**的：
  拒绝会把刚写的 `policy_changed` 事件一起回滚，留下一个「每次都重写又每次都回滚」的假审计。
* 对齐放在 `_ensure_recall_authority_unlocked`（`:6220`）里：它由
  `_admit_typed_recall_request`（`:5498`）在**会提交**的事务里调用。头行与配置不一致时追加
  一条 `recall_policy_changed` 事件（`previous_policy_hash` → `policy_hash`）并 CAS 头行，
  epoch 恰好 +1；一致时**一行不写**（默认部署恒定如此，事件表、头行、epoch 全部字节不变）。

事件行形状沿用 0.6.28 的既有列，无 DDL；`event_kind` 是 `TEXT`，无 CHECK 约束。

### 1.4 见证配方（矩阵接线用）

同一个库、同一条结果，只改策略版本一根轴：

1. v1 下召回 → `authorize_recall_context_use` **成功**（正对照：这条结果本来可授权）；
2. 关库，以 `recall_policy=RecallEligibilityPolicyV1(2)` 重开；
   `read_recall_policy` 报 `policy_changed=True`、`authority_policy_hash` 仍是 v1 的；
3. 对**同一条**旧结果授权 → `MemoryValidationError("RECALL_AUTHORITY_STALE")`，零收据行；
4. 下一次召回 → 恰好一条 `recall_policy_changed` 事件、epoch +1、头行对齐；再召回不再推进；
5. **反向对照**：把部署换回 v1、让头行重新对齐 → 同一条旧结果**又能**被授权。
   于是「拒绝」可归因到策略轴，而不是这条结果自己失效了。

## 2. (b) `MemoryManager.cleanup_short_horizon`

纯转发，无新语义：`core/manager.py:508` → `core/port.py:465` 的既有 backend 方法。
epoch 语义与内部车道**同一实现**，因此自动满足 0.6.28 的规则——**只有真的移除了 chunk
才推进一次 `short_horizon_cleanup`**；零删除不推进。测试同时对 manager 与 backend 各调一次，
断言事件计数而不是绝对 epoch（权威头是惰性建立的，绝对值不是契约）。

明确**不接受**用 `short_source_expiry` 冒充同一事件（RUN-08 §2.I-2 已写明）：过期与清理是
两件事，前者已单独有格且已 PASS。

## 3. (c) apply validation 的精确 reason 码

### 3.1 泛化在哪一层

两层都泛化了：

* **返回值层**：`backends/sqlite_v5.py:7736` 把所有 `mutation_contest_*` 统一映射为
  `MemoryMutationApplyReasonCode.VALIDATION_REJECTED`。该枚举定义在**冻结的** Harness SDK
  （`runtime/memory_protocol.py:3370`，只有 5 个成员），`MemoryMutationApplyResult` 走
  `_exact_keys`，**加不了成员也加不了字段**。
* **durable 审计层**：`_append_mutation_rejection_audit_unlocked` 把六个 `mutation_contest_*`
  里的四个压成 `mutation_contest_rejected`，另外两个
  （`mutation_contest_nested_group_rejected` / `mutation_contest_distinct_evidence_required`）
  **根本不在映射表里**，落到与 contest 无关的 `mutation_epistemic_or_validation_rejected`。

### 3.2 裁决：改 durable 审计的 `reason_code`，加只读导出；返回值层一字不动

为什么不能只加只读导出而不动审计：拒绝理由**不可从既存行重算**。行里有 `plan_id` /
`plan_hash` / `exception_fingerprint = sha256(exception_type \x00 reason_code)`，而
`exception_fingerprint` 恰恰是**由 reason_code 导出**的，不含更细的信息。要么存精确码，
要么这三格永远不可见证。（对比 0.6.29：那里「哪两个 epoch」是由两条既存不可变行**严格导出**
的，所以选了「不存冗余标记」；此处不存在这样的导出，两个场景的裁决方向相反是有依据的。）

为什么不加列：`memory_mutation_rejection_audits.reason_code` 已是**无 CHECK 的 `TEXT`**，
换值不需要任何 DDL（7.4 checksum 不变），加列则会。

**有意的字节变化，范围严格限定**：contest 家族拒绝的 `reason_code` 与随之而来的
`rejection_json` / `rejection_hash` 变了。这正是本增量交付的内容。**非 contest 的拒绝**
（映射表里的六条 + 默认泛化码）**一个字节都没变**，并以反例单测钉死：
`unknown × source_bound` 仍然落 `mutation_epistemic_or_validation_rejected`，且**不出现**
在精确视图里。这些行是不可变审计行，历史库里的旧值原样保留、不回填、不改写。

映射方式是**恒等**：`reason_code == str(exc)`。抛出侧与审计侧同名，没有第二套翻译表可以漂移。

### 3.3 见证配方（矩阵接线用）

`await manager.read_memory_mutation_validation_notes(principal=…, plan_id=…)` →
`MemoryMutationValidationNoteV1`，字段 `reason_code`（六个稳定码之一）、`plan_id` /
`plan_hash` / `idempotency_key` / `base_revision`、`apply_result_id` / `apply_result_hash`
（与调用方拿到的 `MemoryMutationApplyResult` 逐字相同，用来把「返回的那个泛化结果」与
「精确理由」绑在一起）。读出时逐行重算 `rejection_hash` 并核对 body 里的 `reason_code`，
不一致即 `MemoryCorruptionError`。

三格的构造：

| 格 | 构造 | 稳定码 |
|---|---|---|
| exact slot | contest 的 payload 与在位版本逐字相同 | `mutation_contest_exact_slot_required` |
| distinct evidence | payload 变了但复用在位证据 span | `mutation_contest_distinct_evidence_required` |
| nested group | 已有 active conflict group 时再 contest 同一条 head | `mutation_contest_nested_group_rejected` |

## 4. (d) 执行 lane 的公共见证

### 4.1 裁决：加在 `TypedRecallExecution` 上，不进任何 hash 域

S3 Task 4 明写「audit 保存 gate counts、hashed refs/content hashes、**lane/selection scores**
与 generation manifest」，§5.6 又把 source/evidence/classification/conflict/cross-scope 定为
**强制 control/audit metadata，不混入 Provider payload**。lane 归属属于同一类。

* 冻结的 `TypedRecallResultItemV1` 只有融合后的 `score`，`from_json` 走 `_exact_keys`
  → **收据/结果里加不了字段**；
* durable 侧没有逐项 lane 行，做「只读审计入口」等于**新增 DDL**；
* `TypedRecallExecution` 是 SDK 自有的返回包装（且**是**根导出），给它追加带默认值的字段
  是纯增量——与 0.6.30 给根导出 `ShortHorizonProjectionBuildResult` 追加
  `split_group_count` / `truncated_group_count` 同一条纪律。

因此：`item_lane_witnesses: tuple[TypedRecallLaneWitnessV1, ...] = ()` 与
`executed_lanes: tuple[str, ...] = ()`，排在字段末尾，位置式构造与既有 7 参形状逐字不变，
**不进** decision / result / receipt / terminal 的任何 hash 域。

### 4.2 语义边界（写清楚，免得被读成更强的东西）

* lane 名与序**冻结**为 `("vector", "full_text", "entity", "task_scope", "temporal")`，
  即 §5.6 的 RRF 权重降序；单测断言它由 `RRF_WEIGHTS` 导出，两处不会漂移。
* **幂等重放不带见证**（`item_lane_witnesses == ()`）。重放只复述 durable 字节，本轮没有跑过
  任何 lane；把重放伪装成「跑过 lane」会是假见证。
* **拒绝路径不带见证**（零候选访问 ⇒ 没有 lane 执行过）。
* **confirmation-only 的执行不带见证**：按 0.6.31，group 的准入是**槽位级判据**，不是选择
  lane，两者不是一回事。
* 见证反映的是**真的执行过**的 lane，不是对请求 `retrieval_modes` 的复述——测试用同一条
  记忆、同一 query，只加一个 embedder 就让 `score` 变高、`result_hash` 变化来钉死这一点。

## 5. 落地与验收

| 项 | 内容 |
|---|---|
| 新模块 | `core/recall_policy.py`、`core/mutation_rejections.py`（均**不进根导出**） |
| 改动 | `core/recall.py`（lane 见证）、`core/manager.py`（3 个新方法 + `recall_policy` 形参）、`backends/sqlite_v5.py`（策略常量→字段、对齐事件、用途围栏判据、拒绝审计映射、两个只读导出） |
| 契约面 | 无 DDL 变化（7.4 checksum 不变）；根导出零增减；Harness v4 wire 形状零变化；`removed_public_methods` / `migrations` 逐字未变；快照 `public-api-0.6.32.json` 除 `version` 外与 0.6.19 起逐字相同 |
| 字节回归 | 默认部署的 `policy_hash` / `decision_hash` / `result_hash` / `receipt_hash` 在 0.6.31 源 worktree（`ff8be5f`）与本分支各跑一次同一脚本，`diff` 为空；字面值 `adfddf5a…1f78` / `2e003caa…1823` / `deb78444…0f61` 钉进 `tests/integration/test_matrix_public_witness_0632.py` |
| 测试 | 新增 `tests/unit/test_matrix_public_witness_0632.py` 17 项、`tests/integration/test_matrix_public_witness_0632.py` 8 项；`tests/artifact/test_public_api_snapshot.py` 增加 0.6.32 段（新符号不在根导出、`TypedRecallExecution` 两个新字段在末尾、三个新 manager 方法可达、`recall_policy` 形参存在） |
| 全量 | 失败集合与 main 基线（`fc7fa88`）逐条相同（63 项既有环境失败，`diff` 为空），1597 → 1622 passed / 8 skipped |

## 6. Host 侧

* **Host 不需要读任何新字段。** 三个新 manager 方法都是可选的事后审计入口；
  `recall_policy` 不传即保持 0.6.31 行为。
* 401 矩阵可以按 §1.4 / §2 / §3.3 / §4 的配方接线 **I-1、I-2、conflict 精确 reason 3 格、
  executed-lane 3 格**，合计 **8 格**从 `SDK_INCREMENT_REQUIRED` / `ORACLE_GAP` 转为可见证。
* RUN-08 §7 的其余后继（H 组 4 格、I-3 接线、分页零候选读见证 4 格）**本轮不做**：
  前两项是纯 oracle 接线不需要 SDK 增量；分页见证需要给 `page_typed_recall_result` 的四条
  裸抛路径接上 `_attach_pre_candidate_rejection`，是独立一轮的改动面，未在本次范围内。
* `DECISION-2026-09-08-context-use-fence.md` §6 与 `DECISION-2026-09-08-conflict-short-circuit.md`
  §6 的后继逐条复核：Harness 侧同 Run 有界修复（§7(3)）、Host `context_route.py` 白名单映射、
  Host 方案 B 的 fragments 绑定链、F-O-2 分析车道结算时序——**全部在 Host / 冻结 Harness 一侧**，
  Memory 无可叠加的廉价增量，本轮不动。

状态：仅本地候选（分支 `m0632`），未合 main、未构建 wheel、未 push、Host 未 pin。
