# 裁定（0.6.37）：冲突组的词面准入基底扩展到 head 的 subject_entity / qualifiers

- 日期：2026-09-09
- 分支：`m0637`（基线 `b1f9492` = 0.6.36 合入后的 main）
- 缺陷来源：Host 事件 V 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-V-CONTEST-NOTICE.md`
  §4.4 / §6 **F-V-2**（评审升级为 HM-TO-A6 **A6-8 / NC-4 的阻断项**）
- 证据：`.local-test-evidence/2026-09-09/native-a6-run9/primary-ui-8whts2lo/userdata/data/human_memory_v7.db`
  （只读，连 `-wal`/`-shm` 复制出来后离线重放）
- 契约：`slices/S3-cognitive-systems-recall.md` 新增 **§5.3-补**（本轮把「基底」写进契约）

---

## 1. 缺陷

T20 用户更正「校对脚本我现在统一用 Python 3.13，不是 3.12」→ head 前进到 revision 2；
T21 分析车道产出 `contest_semantic` → revision 3（值 `3.12`，`conflict_status=contested`）
＋ 1 条未裁决的 `cognitive_conflict_groups`；T22 用户问「那你现在按哪个版本执行这套校对
流程？」——模型按 `direct_standalone` 作答「按 Python 3.13 执行」，**没有要求确认**。

Host 侧已在事件 V 里修好「每一条会执行的路由都一定去问 Memory」。但**问了能不能得到
答案**是 SDK 的事，而 0.6.34/0.6.36 上答案是「不能」：

```
# 该 group 的槽位文本（contested_slot_text）插桩输出，逐字：
{"object_value":["Python 3.13","3.12"]}
{"predicate":"proofreading_script_python_version"}
```

**一个 CJK 字符都没有**。0.6.31 起冲突组的词面准入只看这段文本，于是纯中文的用户原句
永远零命中；Host 备忘 §2.4 的重放之所以能出通知，只是因为**模型的转述**里逐字复述了
「统一用 3.13，不是 3.12」——那是缺陷报告，不是可依赖的机制。

而用户真正会说出口的那几个字，恰好在这条 head 自己的 `qualifiers` 里：`["在做资料校对时"]`
（`subject_entity` 是 `user:self`）。0.6.31 把这两个字段从 group 的判据里拿掉了。

## 2. 为什么 0.6.31 当初要拿掉，以及为什么这里不成立

0.6.31（`DECISION-2026-09-08-conflict-short-circuit.md`，事件 O / F-O-3）：冻结的
`RecallDecisionV4` 一次只能带 `selected_items` 或 `confirmation_groups` 之一，所以
**group 一旦入选就把同一轮的普通候选整体扣住**。当时的现象是 13 条记忆的库里只有一个
未决 group，任何提到同一主题的查询都被短路成 confirmation-only。根因是 group 的词面
判据用了**整个** payload，其中 `subject_entity`/`qualifiers` 与同主题的**兄弟记忆**共享。

要害在于：这次污染的方向是「**兄弟记忆的词面把 group 拉进来**」。而本轮扩展的是
「**group 所属 head 自己的**词面」——一个 group 只有一个 head，兄弟记忆自己的谓词与
取值仍然永远不准入 group。0.6.31 的要害因此完整保留（用例 ⑤ 与
`test_typed_recall_conflict_short_circuit.py` ① 各钉一次）。

**但要诚实**：代价不是零。查询命中 head 自己的 `subject_entity`/`qualifiers` 时，这一轮
确实回到 confirmation-only，同轮的普通 items 被扣住（F-O-3 抱怨的形状在**这一格**回归）。
裁定：**「不让模型拿一个未裁决的争议值去执行」优先于「同轮多返回几条无关记忆」**——
前者是 S3 §5.2/§5.3 的安全属性，后者是召回质量。已写进契约 §5.3-补.6。

## 3. 修法

`features/conflict_slot.py` 新增（均不进根导出）：

- `CONTESTED_HEAD_CONTEXT_FIELDS = ("subject_entity", "qualifiers")`；
- `contested_head_context_text(memory_type, head_payload)`：按上述字段以
  `{field: value}` 的 canonical JSON 逐行拼接；未知类型 / 非 Mapping / `None` → 空串；
- `contested_admission_text(memory_type, incumbent, challenger, *, head_payload=None)`
  ＝ `contested_slot_text(...)` ∪ head 上下文；**不传 `head_payload` 时逐字等于 0.6.31**；
- `CONFLICT_ADMISSION_TEXT_VERSION = 1`（`CONFLICT_SLOT_TEXT_VERSION` 仍是 1：槽位文本
  本身一个字节没改，只是准入基底多了一段合成文本）。

`backends/sqlite_v5.py::_collect_typed_recall_confirmation` 在**两名成员都通过全部资格门
之后**取 `staged` 里 `revision == group["challenger_revision"]` 的那一项做 `head_payload`
（`h.current_revision = g.challenger_revision` 是取组查询的前提），改调
`contested_admission_text`。取的是 `_cognitive_public_payload_unlocked` 的**公开** payload，
已过隐私门与抑制门，因此扩展的是「这个组这次算不算相关」，不是「披露什么」。

**范围**：只有 confirmation 收集这一处。普通 item 车道、向量准入（0.6.34 的相对阈值）、
entity/task_scope/temporal lane、排序权重、预算、hash 域、DDL 全部一字未动。

## 4. 验收：证据库离线重放（时钟钉 `1788905502.0`）

夹具＝证据库副本剔除**晚于 T22** 的遗忘指令 `suppression-directive-1dba5ee…`
（`effective_at=1788905616.85`，是 T23 在 UI 上的遗忘，归档快照把它带进了重放）。
重放脚本按 `deskpet/memory/human_memory_v7.py::typed_recall` 逐字构造 plan/context，
本机无 embedder，故向量车道整条 `cognitive_vector_unavailable`——**词面是唯一车道**。

| 查询 | 0.6.36（main） | 0.6.37 |
| --- | --- | --- |
| T22 用户原句「那你现在按哪个版本执行这套校对流程？」 | `recall` / items=3 / **0 组** | `needs_user_confirmation` / items=0 / **1 组** |
| 负控「今天天气不错，随便聊聊」 | `no_recall` / 0 / **0 组** | `no_recall` / 0 / **0 组** |
| 正控·模型转述（含「统一用 3.13，不是 3.12」） | `needs_user_confirmation` / 0 / **1 组** | 同左 |
| 正控·谓词查询「秋分资料整理校对流程所用的 Python 环境」 | `needs_user_confirmation` / 0 / **1 组** | 同左 |

命中的 group 逐字是证据里的 `cognitive-conflict-group-cd9b2beb…51fe7b5`
（incumbent r2 `Python 3.13` / challenger r3 `3.12`）。Host 侧的验收信号
`contested_probe_admitted` 因此从 `model_query` 翻成 `user_turn`，与 F-V-2 的要求一致。

## 5. 顺带查清的两件事（Host 备忘 (a)/(b)）

### 5.1 (a) revision 2 的向量世代：备忘的说法要更正

证据库 `cognitive_vector_generations` 共 10 代（9 retired + 1 active），
`cognitive_vectors` 每代 8 行 = 当时的可召回 head 数。逐行时序：

| 时刻 | 事实 |
| --- | --- |
| 1788905260.850 | T20 更正落库（head → r2） |
| 1788905264.232 | 世代 `0a55e0c1…` 激活，**含 `(memory, r2)` 的向量**（更正后 **3.38 s**） |
| 1788905435.434 | T21 争议落库（head → r3，group 建立） |
| 1788905450.643 | 世代 `5adb7b43…` 激活，**含 `(memory, r3)`**（争议后 **15.19 s**）；r2 随旧世代 retire |
| 1788905502.028 | T22（此时 active 世代已就位 **51.4 s**，manifest 与当前 head 清单一致） |

所以「该 head 在 T22 没有向量世代」**不准确**：head 的**当前** revision（r3）在 T22 有
向量。真正成立的是更强的一条结构事实——`_cognitive_vector_head_rows_unlocked` 只取
`r.revision = h.current_revision`，**世代永远只覆盖 head 的当前 revision**，因此
**冲突组的 incumbent 成员（r2）永远拿不到向量分**，group 的向量准入只可能由 challenger
贡献。离线重放里更是整条车道不可用。词面因此是这类争议轮唯一可靠的车道，F-V-2 成立。

**世代重建不受召回 deadline 约束**：`_prepare_cognitive_vector_lane` 从不构建世代，
只做「有没有 active 世代 / manifest 对不对得上 / 查询嵌入来不来得及」三判，任一不成立
就退化（`cognitive_vector_no_generation` / `_stale` / `_deadline`）。构建发生在 Host 的
维护 tick（`deskpet/memory/short_index_worker.py`，`timeout=60 s`，失败退避 60–600 s）。
**记账**：head 一变，manifest 立刻对不上，于是从该次修订到下一次成功激活之间
（本轮实测 3.4 s 与 15.2 s），**整库**的认知向量车道都是 `cognitive_vector_stale`，
不只是被改的那条记忆。这不是本轮要修的（属 Host 维护节奏 + SDK 整代重建的设计），
但它解释了为什么「争议刚落库的那十几秒」恰好是最脆弱的窗口——而争议轮往往紧随其后。

### 5.2 (b) 短路发生在准入之后，§5.3 的意图并未被「泄露」方向破坏

`execute_typed_recall` 的顺序是：普通候选收集 → `_collect_typed_recall_confirmation`
（含 group 的槽位级准入）→ **只有在 `confirmations` 非空时**才走
`build_host_confirmation_execution` 并丢弃普通 items。即**短路在准入之后**：group 没被
准入时，这一轮根本不是「有组但没披露」，而是「没有组」。

因此 §5.3「contested 只能走完整 group confirmation」在**泄露方向**上从未被破坏——
普通车道的 `_cognitive_recall_state_allowed` 不带 `allow_contested`，contested head 永远
不会作为普通 item 下发（用例 ⑤/⑦ 各钉一次）。被破坏的是**该条款背后的目的**：
「依赖该值的任务必须要求确认」。head 连候选都不是时，冲突对这一轮不存在，模型于是拿
对话里的旧值继续执行——这正是 T22。本轮的修法让**这个组**可达，而不放宽任何披露判据：
准入仍是逐组判定（另一个组的 head 文本不会因为这个组被命中而一起披露），§5.2 的整组
原子性与隐私门仍然优先——任一成员不可见则整组连同「存在冲突」一起扣下（用例 ⑦）。

## 6. 测试

- 新增 `tests/integration/test_typed_recall_contested_group_admission.py` **8 项**，
  以证据形状离线复现（槽位文本无 CJK、无向量世代、未裁决的冲突组、中文查询）：
  ① 中文用户原句 → `needs_user_confirmation` / items=0 / 1 组、两名成员带 exact revision；
  ② 负控（无关中文闲聊）0 组；③ 两条正控仍 1 组；④ 无任何 `cognitive_vector_generations`
  行时仍准入（`degradation_codes == ('cognitive_vector_unavailable',)`）；⑤ 兄弟记忆自己的
  词面永不准入 group；⑥ 无冲突库上同一条中文查询照旧走普通车道；⑦ 成员证据被遗忘 →
  整组扣下且不退化成普通 item；⑧ 纯函数（不传 head 逐字回退、head 上下文只含两个字段、
  未知类型/非 Mapping/None fail closed）。
  **基线 `b1f9492` 上 ① 与 ④ 逐条失败**（`recall` ≠ `needs_user_confirmation`），
  ②③⑤⑥⑦ 在基线上即通过（它们是控制项）。
- `tests/integration/test_typed_recall_conflict_short_circuit.py` ① 按新政策改写并改名为
  `test_sibling_text_returns_items_and_head_text_admits_the_group`：保留「兄弟记忆自己的
  词面 → 普通 items」，把 `"default"` / `"user:self"` 两条改为 confirmation-only，
  **这是本轮唯一一处被有意反转的既有断言**，模块 docstring 同步注明。其余 5 项未动。
- 快照测试增加 0.6.37 段：`public-api-0.6.37.json` 除 `version` 外与 0.6.36 **逐字相同**
  （公共面零增减），并断言四个新符号**不在**根导出里。
- 全量 `tests/`：**63 failed / 1661 passed / 8 skipped**；与 main 基线
  （`b1f9492`，独立 detached worktree：63 failed / 1653 passed / 8 skipped）
  的 FAILED 集合逐条相同，`diff` 为空；`ruff check src tests` 与基线同为 **709**。

## 7. 不改 / 边界

- DDL 与 7.4 checksum 未动；已有库不需要迁移或重建世代；**降级安全**——准入基底不落库、
  不进任何 manifest 与 hash 域，0.6.36 读一个 0.6.37 用过的库看到的字节完全一样。
- 公共面零增减（`public-api-0.6.37.json` 除 version 外与 0.6.36 逐字相同）。
- 写路径、向量世代构建、排序权重、预算、`ContextRouteReceipt` 侧的任何 Host 契约未动。
- Host 侧**不需要配合改动**：`contested_probe_admitted` 自动从 `model_query` 翻成
  `user_turn`。**但 Host 应知道 §5.3-补.6 的代价**：命中争议 head 主题的那一轮，
  `memory_standalone` 会从「若干 fragments」变成「confirmation-only、零 fragments」。

## 8. Followup

- **F-V-2a（SDK，P2）**：冲突组的 incumbent 成员永远不在向量世代里（§5.1）。若要让向量
  车道对争议组真正对称，需要让世代覆盖「active group 的 incumbent revision」这一小撮
  非当前 revision；这会动 manifest 口径（`COGNITIVE_TEXT_FORMAT_VERSION` 之外再加一维）
  与整代重建成本，本轮不做。
- **F-V-2b（SDK/Host，P2）**：任何一次 head 修订都会让**整库**的认知向量车道 stale 到
  下一次世代激活为止（本轮实测 3.4–15.2 s），而争议轮恰好紧随修订。可选修法是增量世代
  或「旧世代对未变记忆继续可用」的分片 manifest；同样要动 manifest 口径，另立。
- **F-V-2c（验证，Host）**：本轮只证明「问得到」。模型拿到 `conflict_notice` 后是否仍
  采信对话里的旧值，仍需真实模型逐字重放复验（Host 备忘 F-V-3 同一件事）。
