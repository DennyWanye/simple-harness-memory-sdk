# Memory SDK 架构状态总表

最后更新：**2026-09-09 22:05**。下表是本仓当前状态的唯一总表；其下按时间倒序的"最后更新 / ## 版本"段落是历史记录，各自描述当时状态，不互相覆盖、不回改。

| 项 | 当前值 |
|---|---|
| 当前版本 | **0.6.38**（`src/simple_harness_memory/__init__.py::__version__`） |
| Host 钉版 | **0.6.38**（`simple_harness/backend/pyproject.toml`、`sdk_adapters/sdk_candidate.py::SDK_MEMORY_VERSION`） |
| 公共面 | `public-api-0.6.38.json` 除 `version` 外与 0.6.37 逐字相同；0.6.19 以来唯一一次根导出扩张是 0.6.36（+3 个名字） |
| DDL | 7.4 checksum 自 0.6.34 起未变（0.6.35/0.6.36/0.6.37/0.6.38 均零 DDL） |
| 测试 | 1673 passed / 8 skipped；`ruff check src tests` 709；全量失败集合与 main 基线逐条相同（63 项既有环境失败） |
| 今日版本序列 | 0.6.34 向量分数同型相对 margin → 0.6.35 关系端点分类取血缘上最近的已分类祖先 → 0.6.36 离线车道可提交 Procedure 适用性指纹证明 → 0.6.37 冲突组词法准入基底扩到 head 的 `subject_entity`/`qualifiers` → **0.6.38** 租约到期降级为 `authority_lease_expired`（续发租约）、未裁决冲突组 incumbent 进向量世代、世代自证 manifest 与 `cognitive_vector_partial` |
| 降级记账 | 0.6.37 读**有未裁决冲突组且已重建过世代**的 0.6.38 库会开库失败（`active cognitive vector generation is incomplete`），回退需先重建一代；其余版本对间降级安全 |
| 人类记忆数字孪生计划 | 7 个发布单元 / 51 Task / 8 条 MUST AC；V0·S1·S2·S4 完成，S3·S5 代码与契约完成待整跑复验，S6 2 ✅ / 4 🟡 / 2 🔶；AC 1 ✅ / 7 🟡，无红。总表见 [`plans/2026-08-29-human-memory-digital-twin/PROGRESS-2026-09-07.md`](../plans/2026-08-29-human-memory-digital-twin/PROGRESS-2026-09-07.md) 一~三节 |
| 今日 Host 侧验收 | HM-TO-A6 第 12 次整跑 14/1/3（第 13 次已启动）；Manual 模式旅程 run6 12/0/4；两轮完整流程旅程 flow1 全通过、重启段事件 AK 阻塞；240 语料三阈值首次全部达标（多提 10.7% / required 100% / 隐私 0）；401 矩阵 run-16 PASS 382 / FAIL 0 / BLOCKED 19 |

---

最后更新：2026-09-07。0.6.19 clean源e27003c一次离线制品和Host H079/M619/S0313安装组合1PASS0.86s通过，版本元数据3控通过，旧106导出全保留+12；生产安装origin经实际vendor安装纠正后验证通过。全部资源组清空，原生/240质量仍未验。[候选与制品](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-07。共同Procedure/current-input组合已在Host80764c13/Memorya15c7be通过1个新增真实公共控制并独审接受，source overlay非installed；0.6.19版本与118项公共导出快照准备，旧M618 106项全保留，版本检查/制品待验。[候选边界](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-07。Procedure discovery源f03dab0的新6项有效控制已获独审限定接受（首批有效4+实际遗忘负控2；旧误绿撤回）。文档后继d142d3a并入共同候选，current-input源码a28a857与Draft混合批量检查新控制仍待验；无新wheel/安装/原生完成声明。

最后更新：2026-09-06。主候选源码组合：Procedure f03dab0（含已审恢复）与current-input e500556合入独立后继分支，保留两组公共入口和HistoryProcedureDraftBinding检查。当前只是组合源码，未构建新wheel、未切Host pin；Procedure discovery新控/组合审查仍待完成，旧M618身份不改。[本轮输入接口](CURRENT_INPUT.md)。

最后更新：2026-09-06。Procedure恢复源码Host ea63ddc6/c76da29c、Memory978ae99：新增12唯一控制分批通过（SDK3，Host9），原四夹具失败保留且只重试四红；明确54增量attempt journal、过期重开/lostACK、同epoch旧revision、同Scope拒绝、真实drift物理0、高risk及timer兼容。全部资源组清空，临时vendor恢复；待新叶独审和统一制品，未合主/非native。首次草稿发现、失败归因、TC-HM04仍未完成。[结果与边界](../plans/2026-09-06-procedure-observation-prepare/RECOVERY.md)。

<!-- last-calibrated: 6ba269537e45d443629aee56e9cfabec9de2e833 -->

> 2026-09-07 转主干开发：main 已并入 `feat/human-memory-procedure-current-input-successor`（0.6.19 源）。下方 09-06 两路状态段为合并时的并集，各自描述当时状态，不互相覆盖。

最后更新：2026-09-06。Procedure后继公开prepare/read target/record的实际operation observation六项新控通过；f82c2b8仅Procedure复用source-only S1完整持久校验，Host三真实Scope路由/文件effects/完整group→公共观察由原红转绿，累计成功1/2/3与重放已验证。新四项跨源边界控未跑，完整TC-HM04、独审、installed/native未闭合。主整合Hegel e500556后统一版本，不独立build，不改M618制品；F01延期。[源码与证据边界](../plans/2026-09-06-procedure-observation-prepare/CONTRACT.md)。

## 2026-09-09 0.6.38 租约到期是降级；冲突组 incumbent 进向量世代；世代覆盖率与可用性分开判（F-AA-2 / F-V-2a / F-V-2b）

最后更新：2026-09-09。基于 0.6.37，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 Host 事件 AA 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-AA-AUTHORITY-STALE-RECOLLECT.md` §2 / §9(2)（**F-AA-2**，HM-TO-A6 T18）与本仓 0.6.37 备忘 §5.1 / §8（**F-V-2a / F-V-2b**）。裁定 [`DECISION-2026-09-09-lease-degradation-and-incumbent-vectors.md`](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-09-lease-degradation-and-incumbent-vectors.md)。

- **F-AA-2**：T18 一轮 12 次 provider 请求，第 12 次比 `authority_expires_at` 晚 4.96 s → `RECALL_AUTHORITY_STALE` → `run.fail`，而 7 条被绑定来源逐条未变。租约上游是 Host 的 `RecallContext.expires_at = moment + 60`——召回上下文期限被当成整轮用途租约。**修法**：该判据降级为稳定码 `authority_lease_expired`，照常签发收据。依据是结构性的：`authority_expires_at = min(上下文期限, 每条来源自己的期限)`，后者在同一事务的逐来源重校验里被逐条独立重新执行，租约挡不住任何一条真的失效了的来源。policy version / 策略版本 / epoch 倒退仍硬失败，重校验一字未动。
- **续租**：冻结的 `RecallContextUseReceiptV1` 要求 `expires_at > authorized_at`，故这一支续发一段租约（长度 = 结果原本的租约长度，起点 = 授权时刻，上界 = 重校验重新读到的来源最早期限）。租约未到期那一支收据逐字节不变。降级说明仍零 DDL，但导出对是 `recall_context_use_receipts.authorized_at` ↔ 结果 `result_json.authority_expires_at`（**不是**收据自己那个续发的 `expires_at`）。
- **F-V-2a**：认知向量世代覆盖集 = 全部当前 head revision **∪ 未裁决冲突组的 incumbent revision**（取组条件与 confirmation 取组查询逐字一致）。此前世代只覆盖当前 revision，冲突组的 incumbent 永远拿不到向量分。候选面不变（`vector` lane 只对已过全部资格门的那一个 ref 精确查表）；无未裁决冲突组的库 manifest 一个字节不变，升级不触发世代重建。
- **F-V-2b**：世代的**可用性**（自证 manifest = 按它自己的 `(memory_id, revision)` 重算 == 入库 `content_hash`，等价于「渲染格式版本与每条 revision 内容未变」，靠 `cognitive_memory_revisions` 行内不可变成立）与**覆盖率**（是否覆盖当前全部可召回 revision）分开判。覆盖不全时车道照常可用、只对覆盖到的 revision 打分，记新降级码 `cognitive_vector_partial`；`cognitive_vector_stale` 收窄为「整代不可信」。此前任何一次 head 修订都让**整库**的认知向量车道 stale 到下一次世代激活为止（run9 实测 3.38 s / 15.19 s），而争议轮恰好紧随修订。
- **契约**：`slices/S3-cognitive-systems-recall.md` 新增 `§5.4-补`（租约六条）与 `§5.3-补2`（向量五条）。**不改** DDL 与 7.4 checksum、写路径、世代构建三段式与 CAS、0.6.34 相对阈值、排序权重与预算、hash 域；`page_typed_recall_result` 的时限有意保留。**降级记账**：0.6.37 读一个有未裁决冲突组且已重建过世代的 0.6.38 库会开库失败（`active cognitive vector generation is incomplete`），回退需先重建一代。
- **公共面零增减**（`public-api-0.6.38.json` 除 version 外与 0.6.37 逐字相同）；新增 12 项用例（租约 7 / 向量 4 / 整代 stale 负控 1，基线上各 3 项红），有意反转既有断言 5 处；全量失败集合与 main 基线逐条相同（63 项既有环境失败，diff 为空），1661 → 1673 passed / 8 skipped。
- **Host 侧不需要配合改动**：事件 AA 的重采机制从「常态」退化成「兜底」，建议保留但不必再触发；`RecallContext.expires_at` 的语义可重新定义；看板应把 `cognitive_vector_partial`（非故障）与 `cognitive_vector_stale`（整代不可信）分开计数。

## 2026-09-09 0.6.37 冲突组的词面准入基底扩展到 head 的 subject_entity/qualifiers（F-V-2）

最后更新：2026-09-09。基于 0.6.36，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 Host 事件 V 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-V-CONTEST-NOTICE.md` §4.4 / §6 **F-V-2**（评审升级为 HM-TO-A6 **A6-8 / NC-4 的阻断项**）。裁定 [`DECISION-2026-09-09-contested-group-admission-basis.md`](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-09-contested-group-admission-basis.md)。

- **缺陷**：run9 里 `proofreading_script_python_version` 的争议组，其槽位文本逐字是 `{"object_value":["Python 3.13","3.12"]}` 与 `{"predicate":"proofreading_script_python_version"}`——**一个 CJK 字符都没有**。0.6.31 起冲突组的词面准入只看这段文本，于是 T22 的纯中文用户原句「那你现在按哪个版本执行这套校对流程？」零命中、`confirmation_groups=0`，未裁决的冲突值以「刚才对话里的事实」形态直达模型（A6-8 / NC-4 FAIL）。Host 侧只能保证「每条会执行的路由都去问 Memory」，「问了能不能得到答案」在 SDK。
- **契约**：`slices/S3-cognitive-systems-recall.md` 新增 `§5.3-补（2026-09-09，0.6.37）`——§5.3 从未规定 group 凭什么算相关，本轮把基底补写成条款：基底 = `contested_slot_text` ∪ head 当前 revision 的 `subject_entity`/`qualifiers`；只对冲突组生效；无向量世代时同样生效；不放宽任何披露判据；并写下已知代价。
- **修法**：`features/conflict_slot.py` 新增 `contested_admission_text` / `contested_head_context_text` / `CONTESTED_HEAD_CONTEXT_FIELDS` / `CONFLICT_ADMISSION_TEXT_VERSION`（均不进根导出，纯函数、只读公开 payload、不进任何 hash 域）；`sqlite_v5.py::_collect_typed_recall_confirmation` 在**两名成员都过完资格门之后**取 `revision == challenger_revision` 的公开 payload 作 `head_payload`。普通 item 车道、向量准入、排序权重、预算、DDL 一字未动。
- **0.6.31 的要害保留、代价诚实记账**：污染方向是「**兄弟记忆的**词面把 group 拉进来」，而本轮扩展的是「**group 自己 head 的**词面」，兄弟记忆的谓词/取值仍永远不准入 group。代价：查询命中 head 自己的 `subject_entity`/`qualifiers` 时该轮变成 confirmation-only，同轮普通 items 被扣住（F-O-3 抱怨的形状在这一格回归）。裁定「不让模型拿未裁决的争议值去执行」优先于「同轮多返回几条无关记忆」，已写进 §5.3-补.6。
- **证据库离线重放**（时钟钉 `1788905502.0`，剔除晚于 T22 的遗忘指令 `suppression-directive-1dba5ee…`）：T22 用户原句 `recall`/items=3/**0 组** → `needs_user_confirmation`/items=0/**1 组**；负控「今天天气不错，随便聊聊」两侧均 0 组；两条正控（模型转述、谓词查询）两侧均 1 组。Host 的验收信号 `contested_probe_admitted` 因此从 `model_query` 翻成 `user_turn`。
- **顺带查清（Host 备忘 (a)/(b)）**：(a) 「head 无向量世代」不准确——r2 的向量在更正后 3.38 s 就激活，争议后 15.19 s 又建了含 r3 的新世代，T22 时它已就位 51.4 s；真正成立的是**世代永远只覆盖 head 的当前 revision**，故冲突组的 incumbent 成员永远拿不到向量分。世代重建**不受召回 deadline 约束**（召回只退化不构建，构建在 Host 维护 tick 上）；记账：head 一变，**整库**向量车道 stale 到下一次激活为止（实测 3.4–15.2 s）。(b) 短路发生在**准入之后**：group 没被准入时这一轮「没有组」，泄露方向从未被破坏（contested head 永不作为普通 item 下发），被破坏的是条款背后的目的「依赖该值的任务必须要求确认」——本轮让**这个组**可达，且不放宽任何披露判据（逐组判定；§5.2 整组原子性与隐私门仍优先）。
- **不改**：DDL 与 7.4 checksum；公共面零增减（`public-api-0.6.37.json` 除 `version` 外与 0.6.36 逐字相同）；**降级安全**——准入基底不落库、不进 manifest 与 hash 域，0.6.36 读 0.6.37 用过的库看到的字节完全一样。
- **测试**：新增 `tests/integration/test_typed_recall_contested_group_admission.py` **8 项**（证据形状：槽位文本无 CJK、无向量世代、未裁决的冲突组、中文查询；含负控、两条正控、兄弟词面不准入、无冲突库普通车道不变、成员被遗忘则整组扣下、纯函数 fail closed）——基线 `b1f9492` 上 ① 与 ④ 逐条失败。`test_typed_recall_conflict_short_circuit.py` ① 按新政策改写（唯一一处被有意反转的既有断言）。全量失败集合与基线**逐条相同**（63 项既有环境失败，`diff` 为空），1653 → **1661** passed / 8 skipped。
- **Host 侧**：不需要配合改动；但应知道代价——命中争议 head 主题的那一轮，`memory_standalone` 会从「若干 fragments」变成「confirmation-only、零 fragments」。仅本地候选（分支 `m0637`），未发布、未构建制品、未合 main、Host 未 pin。

## 2026-09-09 0.6.36 离线车道可以提交自己召回时所用的 Procedure 适用性指纹（F-S1b）

最后更新：2026-09-09。基于 0.6.35，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 0.6.35 裁决备忘 §6 第 2 条 / §9 **F-S1b（P0）**，再往上是 Host 事件 S 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-S-RELATION-KEYERROR.md` §3「坑一」/ §4.4 / §7。裁定 [`DECISION-2026-09-09-analysis-lane-applicability-fingerprints.md`](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-09-analysis-lane-applicability-fingerprints.md)。

- **缺陷**：0.6.35 修好了关系端点解析，但 Host 的 `check()` 走 `check_history_visibility`，而 `backends/history_visibility.py` 对 `_validate_recall_context_use_sources_unlocked` 写死 `procedure_applicability_fingerprints=frozenset()`（注释：*never reuse old runtime fingerprints*），于是任何 Procedure 来源恒 `RECALL_AUTHORITY_STALE` → `history_source_stale` → Host 整批 `analysis_candidate_no_longer_visible`。Host 只能继续扣下所有 Procedure 端点，A6-6 的 Procedure 形态仍不可达。那句注释本身是对的：`check_history_visibility` 拿到的是 `DisclosureContext` 而不是 `RecallContext`，让它去读已存召回请求里的指纹，等于让一次任意晚的复核继承一次任意早的运行时状态。
- **契约**：`plans/2026-08-29-human-memory-digital-twin/slices/S3-cognitive-systems-recall.md` 新增 `§2-补2（2026-09-09，0.6.36）`——缺省即 0.6.35；唯一入口与 provenance 语义；作用面只到 `HistoryRecallBinding`；三条放行判据与「其余各门一条不少」；收据形状；**重新裁定 §2-补.6 的取舍**；F-S1 两条全部闭合（§2-补.7 作废）。
- **修法**（零 DDL、只加可选入口）：新增根导出 `ProcedureApplicabilityProvenance` / `ProcedureApplicabilityAttestation` / `ProcedureApplicabilityReceipt`，`check_history_visibility`（协议 + facade + 后端）增加**可选** `procedure_applicability`。provenance 今天只有 `applied_use_fingerprints` 一个成员，含义被契约钉死为「Memory 已消费其观测的那些使用的指纹」——**「曾经真的用过」，不承诺「此刻仍适用」**。**这个标签不被信任**：放行还要求该 memory 上至少一条 `outcome='success' AND attributable=1` 的 `procedure_observations` 携带逐字相同的指纹（匹配口径是 memory + 指纹，不含 revision/epoch）。分工要说准：既有的类型权威门已经把调用方钉死在 Memory 自己存的那个值上（`procedure_records.applicability_fingerprint` 只由观测提交写入），新增这一条加的是把「被绑定过」收紧为「被一次成功且可归因的使用背书过」。`procedure_observations` 是 Memory 自己的 append-only、不可变触发器保护、open 时逐字复核的表（实测：改一列则库不可开）。其余各门（head CAS / `content_hash` / 状态 / 有效时间 / 隐私类与属性 / suppression / 披露）一条不少。
- **缺省与 fail closed**：不提交 ⇒ 逐字等于 0.6.35，快照 `to_json()` 连 `procedure_applicability` 这个键都不出现；提交给当前输入观察入口 ⇒ `history_current_input_rejects_procedure_applicability`；非 canonical 类型 ⇒ `TypeError`；facade 只在真的提交时才转发该 kwarg，早于 0.6.36 的后端照常工作。
- **收据**：快照在 `schema_version` 之后追加 `procedure_applicability`（provenance / `attestation_hash` / `fingerprint_count` / 逐条命中的 binding hash），attestation 同时计入 `request_hash`；既有 7 参位置式构造逐字不变。
- **重新裁定 `applied_use_fingerprints`**（事件 S 备忘 §4.1 的要求）：**可以作为复核依据**——保住的那一半被收紧到「成功且可归因地用过」（「等于 Memory 自己存的值」本来就由既有的类型权威门保证），佐证来源被链锚定，且这只是复核不是授权（apply 时端点仍被逐门重解析）。诚实记账的残余：工具改名/换签/被撤的 Procedure 前台召回会消失，离线车道仍可把它作为关系端点提交；该边仍带 exact revision，各门照常生效。彻底消除需把「适用性快照」持久化成可离线重算的事实，记为 F-S1c。
- **不改**：DDL（7.4 checksum 不变，不加表/列/索引，已有库不需迁移或重建；**降级安全**——新键只在返回值里、不落库）、写路径、前台 `execute_typed_recall`、`cognitive_relations` 与 twin graph 投影、收据视图、分类决定链复核。代价记账：判据 ③ 每条 Procedure 绑定多两次点查，其中 `procedure_observations` 那一次走 `procedure_observation_success_scope_unique` 的 `memory_id` 前缀（部分索引谓词被查询蕴含，非覆盖但不是扫描）。
- **公共面**：`public-api-0.6.36.json` 是 0.6.19 以来第一次真正的根导出扩张，只多三个名字，`removed_public_methods` 与 `migrations` 逐字未变。
- **测试**：新增 `tests/integration/test_history_procedure_applicability.py` **9 项**（Procedure 走满三次真实观测进 `active` → 真实指纹公开 typed recall → `HistoryRecallBinding`，与 Host 分析车道逐字同形；缺省仍 stale 且快照无新键；带 attestation 即可见且收据四项齐全、两次调用逐字相同；判据 ③ 单独量出且证明篡改后库不可开；同批 semantic 绑定不受影响；当前输入入口拒绝；`generation=STALE` 仍不可见；canonical 形状 fail closed；facade 只在提交时转发）。基线 `b82187e` 上整文件收集即失败（公共面新增）。全量失败集合与基线**逐条相同**（63 项既有环境失败，`diff` 为空），1644 → **1653** passed / 8 skipped；`ruff` 709。
- **Host 侧**：Host 同步解除 `sdk_procedure_endpoint_unresolvable`（分支 `worktree-f-s1b`），按**能力探测**而不是版本号，因此同一份 Host 代码在 0.6.34/0.6.35 上继续扣留。**F-S1 两条至此全部闭合**，A6-6 的 Procedure 形态端到端可达。

## 2026-09-09 0.6.35 关系端点的分类决定由血缘上最近的已分类祖先承担

最后更新：2026-09-09。基于 0.6.34，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 Host 事件 S 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-S-RELATION-KEYERROR.md` §3 坑二 / §8 F-S1（P0）。裁定 [`DECISION-2026-09-09-procedure-relation-endpoint-classification.md`](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-09-procedure-relation-endpoint-classification.md)。

- **缺陷**：分析协议 v8 允许 `semantic_relation` 用 `ExistingMemoryTarget` 指向已有记忆。Procedure 端点必须先走满三次独立成功观测进 `active`，而观测提交走 `_copy_cognitive_revision_unlocked`——它逐字复制 content/`content_hash`/`effective_privacy_class`/`information_attributes_json`，只改 `lifecycle_state`，**从不重跑分类策略**，因此这些 revision 上没有自己的 `cognitive_classification_decisions` 行。`_resolve_semantic_relation_payload_unlocked` 在 head revision 上直接查这张表，于是对每一条**真的可用**的 Procedure 端点抛 `MemoryCorruptionError('relation endpoint classification is missing')`，**整批分析死掉**（连同批的 episode 一起丢）。Host 因此在下发前按名扣下所有 Procedure 端点（`sdk_procedure_endpoint_unresolvable`），验收 A6-6 的 Procedure 形态在 0.6.34 上不可达。
- **契约**：`plans/2026-08-29-human-memory-digital-twin/slices/S3-cognitive-systems-recall.md` 新增 `§2-补（2026-09-09，0.6.35）`——Task 2「任何 classification authority 缺失整批拒绝」的适用范围是 mutation **operation** 而非每条 revision；祖先归属规则与两条继承自证条件；**关系端点解析的完整门序**（此前从未入契约）；端点隐私类/属性作为关系记忆分类的下界；F-S2 离线车道口径；F-S1b 未闭合。
- **不变量**：`cognitive_memory_revisions` 只有两个写入点——mutation apply（必配一条分类决定）与 `_copy_cognitive_revision_unlocked`（生命周期推进，Procedure 观测提交 / Prospective 信号提交，逐字复制内容与分类结果）。因此「每条 revision 都必须有自己的分类行」从来不是本仓的不变量；真正的不变量是**管辖某一版的分类决定 = 血缘上最近的已分类祖先，且该决定必须仍然逐字描述这一版**。
- **修法**（只改读、不改写、零 DDL）：端点解析改查 `memory_revision <= 端点 revision` 的最大已分类 revision，三条判据——① 恰好一行且 `decision_hash` 非空，否则语句逐字不变的 `'…classification is missing'`（一条已分类祖先都没有仍是真损坏）；② **管辖决定必须仍然逐字描述这一版**：决定行的 `effective_privacy_class` / `effective_attributes_json`（被 `decision_hash` 锚定、收据复核逐字重算）必须等于端点 revision 行的对应两列，exact 与继承两条路径都查，否则新增码 `'relation endpoint classification differs'`；③ 继承路径再要求祖先与端点两版 `content_hash` 相等，否则新增码 `'relation endpoint classification lineage differs'`。②③ 是 0.6.34 完全没有的两道校验；同时诚实记账：被接受的端点 revision 集合确实变大了（这正是修复目的）。
- **不改**：DDL（7.4 checksum 不变，**已有库不需要迁移或重建世代**，且降级安全：不写新行不加新列）、观测/信号提交路径（不补写任何分类行，审计形状零变化）、端点解析的其余各门（所有权/CAS/conflict/状态/时间/内容哈希/typed payload/证据/restricted/suppression）与其顺序、`cognitive_relations` 与 twin graph 投影、根导出零增减。快照 `public-api-0.6.35.json` 除 `version` 外与 0.6.19 起逐字相同。
- **测试**：新增 `tests/integration/test_procedure_relation_endpoint.py` **6 项**（事故现场 + 落 1 行 `cognitive_relations` + twin graph 边两端都在节点集合 + reopen 逐字相同；typed recall 命中的 exact revision 与**落库的那条边**一致；整条分类链摘掉仍 `missing` 且那样的库重开即 fail closed；属性漂移 → `classification differs`；内容自洽分叉 → `lineage differs`；**Prospective 同形**走同一条继承路径并落边）。除守卫用例外 5 项在基线 `36dac46` 上红。全量失败集合与基线**逐条相同**（63 项既有环境失败，`diff` 为空），1638 → **1644** passed / 8 skipped；`ruff` 709。独立评审（opus，只读）1 条 MUST-FIX（契约未落地）+ 8 条 NIT 全部处置，逐条见裁决备忘 §8.1。
- **Host 侧**：F-S1 只解除了一半。端点解析这一半已修；`check_history_visibility` 对 Procedure 永远 `RECALL_AUTHORITY_STALE`（`backends/history_visibility.py` 写死 `procedure_applicability_fingerprints=frozenset()`）那一半**未动**，因此 Host 的 `sdk_procedure_endpoint_unresolvable` 扣留**暂不能解除**，详见备忘 §6。

## 2026-09-08 0.6.30 短时域 chunk 长度上限：超长因果组确定性切段；世代重建只嵌入新 chunk

最后更新：2026-09-08。基于 0.6.29，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 HM-TO-A6 turn 22（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-TIMEOUT-HOST-SIDE.md` §2：单条 29 778 字符 chunk 嵌入 23.9 s；Host 因 `public_text_hash` 绑定无法限长，chunk 边界归 SDK；S3/S5 无长度条款）。裁定 `plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-08-short-horizon-chunk-cap.md`，契约 S3 Task 4 §4-补。

- **契约**：一条 chunk 渲染内容 ≤ `SHORT_HORIZON_CHUNK_MAX_CHARS = 2 048` 码点；超长完整因果组按注册边界整行装箱 → 段落 → 句子 → 空白 → 硬切（切点落在窗口后半段、永不切码点、拼接逐字还原）确定性切成 K 条内容寻址 chunk；每组最多 `SHORT_HORIZON_CHUNK_MAX_SEGMENTS = 8` 段，尾部不投影并审计 `truncated_group_count`；每段血缘 = 整组，抑制/过期/分页/召回/可见性对分段透明；Host 不得假设"一组一条"。
- **id 稳定 + 零 DDL**：未分段组的 `chunk_id` payload 与 0.6.29 逐字相同（segment 字段只在 K>1 进入 payload；测试钉死 0.6.29 源算出的字面值）。`UNIQUE (principal_id, primary_conversation_id, causal_group_id)` 不改：分段 chunk 在该列存投影键 `<id>\x1f<k>/<K>`，读路径经 `core.short_horizon.parse_short_horizon_projection_key`/`resolve_short_horizon_projection_row` 重推，注册拒绝含 U+001F 的 `causal_group_id`。schema 7.5（放宽 UNIQUE + segment 列）推迟到下一次不可避免的 DDL 切换。
- **升级与 epoch**：0.6.29 遗留的单条超长行打开不判损坏（裸键行接受 0.6.29 形状且须为该组唯一一行），下次投影重建以分段替换——既有 `chunk_id` 移除，按 0.6.28 车道恰好推进一次 `short_horizon_projection_changed`；新超长组首次投影为 K 段是纯新增，不推进。
- **增量投影 + 向量沿用**：投影重建只删清单里消失的 id、只插新出现的 id；世代重建沿用 active 世代（同 lineage、hash/维度校验通过）里同 `chunk_id` 的向量字节，只对新 chunk 调 `embed_batch`，审计 `embedded_count/reused_vector_count`。世代身份、manifest、CAS、replay、失败语义（0.6.27）与"世代激活不推进 epoch"（0.6.28）不变。
- **契约面**：无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.30.json`；新增 15 项测试（8 单元 + 7 集成，含 0.6.29 字面值对照与遗留形状升级路径）；全量失败集合与 main 基线逐条相同。文档化测试命令 `uv run --frozen --group dev pytest -q` 修复（`uv.lock` 的 `simple-harness-sdk` 目录改回 `../simple-harness-sdk`，依赖版本零变化）。
- **Host 侧**：现有 `projected_chunk_count == 1` 断言因夹具文本很短仍成立，但生产逻辑不得假设一组一条；`WeMMEmbedder.embed_batch` 分组阈值可按段长重标定；维护实测常量在 0.6.30 后只对新 chunk 计成本。SDK 后续：世代构建部分进度（8 段抬到 16 的前提）、认知向量世代同样沿用向量。

## 2026-09-08 0.6.31 一个未决 conflict group 不再短路整条 typed-recall 车道

最后更新：2026-09-08。基于 0.6.29（0.6.30 由另一分支并行，版本序合并时统一），仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 HM-TO-A6 run4 事件 O（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-CONTESTED-DISCLOSURE.md` §7 F-O-3 / F-O-1）。

- **缺陷**：一个 contested head 的 group 成员靠共享的 `subject_entity`/`qualifiers` 被任何同主题查询词面命中，而 `execute_typed_recall` 只要 confirmation 非空就整次短路成 `needs_user_confirmation` + `items=()`，与争议槽位无关的记忆全部召不回（run4 重放：「校对结果存到哪里」0 item）。
- **裁决**（`plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-08-conflict-short-circuit.md`）：S3 §5.3 只约束 contested 候选的载体，契约不要求整次扣住；但冻结的 Harness `RecallDecisionV4` 一次只能带 items 或 groups 之一。因此 group 的准入收窄为**槽位级相关**：词面只看 `contested_slot_text`（两名成员取值不同的字段 + semantic `predicate`）；向量要求争议记忆是同类型里离查询最近的匹配；entity/task_scope/temporal 只过滤与排序。准入后的原子 carrier、预算、写锁内重校验、终态、幂等与 0.6.27–0.6.29 的锁/epoch 判据一字不动。
- **F-O-1**：`history_visibility._recall` 接受 confirmation 成员的 `HistoryRecallBinding`（按 `result_member_hash` 核对，整组重校验，一侧不可见即整组 stale）。
- **不改**：无 DDL 变化（7.4 checksum 不变）、根导出零增减、Harness v4 wire 形状不变；无冲突库五类 hash 与 0.6.29 逐字节相同（钉死字面值）。快照 `public-api-0.6.31.json`；新增 6 项回归测试。
- **Host 侧**：`project_contested_confirmation` 不需要改形状；空 fragments + 无 conflict_notice 不再意味着"库里没有争议"，只说明本轮查询与争议槽位无关。

## 2026-09-08 0.6.29 用途围栏：epoch 前进但被绑定来源未变时签发收据

最后更新：2026-09-08。基于 0.6.28，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 HM-TO-A6 第 4 次尝试 turn 15（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md` §7(2)）。

- **缺陷**：0.6.28 掐掉索引噪声后，剩下的 epoch 车道全是真实资格事件；而每轮的异步分析车道都在该轮结束后 ~10–60 s 落库（`cognitive_memory_changed`），恰好落在**下一轮**召回结算与用途授权之间。epoch 相等性判断因此抛 `RECALL_AUTHORITY_STALE` → Host `recall_context_use_authority_stale` → 冻结的 Harness SDK 无修复路径 → `run.fail`。这是正常使用中的高频竞态，靠车道分类已消不掉。
- **修复**：`authorize_recall_context_use` 把 epoch **相等性**改为**倒退性**判据。`policy_hash`、结果期限、epoch 倒退仍硬失败；epoch 前进交给同一把写锁、同一事务里紧接着的 `_validate_recall_context_use_sources_unlocked` 逐来源裁定，全部通过才签发收据，任一不成立仍以同一稳定码、零 payload、零收据行拒绝。`execute_typed_recall` 的工具内围栏语义不动。
- **契约论证（S3 §5.4）**：该条款具名的 suppress/revoke/supersede/contest/classification 变化/Short-Horizon expiry 全是**作用在某条来源上**的事件，作用在本次绑定的来源上时逐来源重校验必然发现；policy change 走单独判据未放宽。收据只绑定 `item_bindings` 逐条列出的条目，而重校验正是对这批条目做的——**被授权的集合 = 模型已经看到的集合 = 被重校验的集合**。epoch 是保守快捷判据、逐来源重校验是精确判据，保留精确的、放宽保守的，披露完整性只增不减。
- **降级码零 DDL**：`RecallContextUseReceiptV1` 属冻结的 Harness SDK（`_exact_keys`）加不了字段；两个 epoch 本来就分别落在不可变的 `recall_context_use_receipts.authority_epoch` 与 `typed_recall_results.result_json`，由 `result_id` 唯一连接。新增 `core/recall_context_use.py`（稳定码 `authority_epoch_advanced` + 有界只读视图）、只读导出 `read_recall_context_use_authority_notes`（不写行）与一行无载荷结构化日志。
- **不改**：`_validate_recall_context_use_sources_unlocked` 一行未动、`recall_authority_events`/`recall_authority_heads` 的 DDL 与 0.6.28 的车道分类、收据构造与 `receipt_hash` 域、幂等重放、收据表 DDL 与写入列。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.29.json`；新增 7 项回归测试（含"无竞态路径逐字节不变"与在 0.6.28 worktree 上的对照）。
- **Host 侧不需要读新字段**：返回类型与字段逐字不变；要统计降级，直接比对 `receipt.authority_epoch` 与手上召回结果的 `authority_epoch`。Host 备忘 §7(3)（Harness 为用途围栏拒绝留同 Run 有界修复）仍值得做——0.6.29 之后剩下的 stale 全是**正确**的拒绝，但 Harness 依然只会把它变成 `run.fail`。

## 2026-09-08 0.6.28 召回权威 epoch 只跟踪"可能改变资格"的事件

最后更新：2026-09-08。基于 0.6.27，仅本地候选、未发布、未构建制品、Host 未 pin。缺陷来源 HM-TO-A6 事故 F（Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-AUTHORITY-STALE.md`）。

- **缺陷**：工具已成功结算（`tool.effect_settled`）之后 ~160 ms，`authorize_recall_context_use` 比对已落库召回结果的 `(epoch, policy_hash)` 与当前 head，不等即抛 `RECALL_AUTHORITY_STALE`；Harness 的 `_authorize_context_use` 无 except，直接 `run.fail`。用户库一次会话累计 26 个 epoch，其中大量来自**纯索引/投影重建**车道。
- **修复**：按 S3 slice §5.4 逐点分类 8 个 epoch 抛点。停止推进 `short_horizon_generation_changed` 与 `cognitive_vector_generation_changed`（世代激活只是把同一批内容重新嵌入，不改变资格）；`short_horizon_projection_changed` 收窄为仅当 `removed_chunk_count > 0`（移除既有 chunk 才是 §5.4 的「Short-Horizon source 失效」，纯新增不使任何已绑定结果失去资格）。保留 suppression / cleanup / procedure / prospective / cognitive mutation 五条资格车道。
- **披露完整性不放宽**：epoch 相等性之后紧接的 `_validate_recall_context_use_sources_unlocked` 逐条重校验每个被绑定来源的 head/revision/`content_hash`/状态/有效期/privacy/attributes/type 权威/血缘抑制/disclosure（短时域另加 chunk 存在性与 `expires_at`），任一不成立以同一码拒绝。被停掉的两条向量车道只写 `*_vectors` 与世代状态表，碰不到这些字段；投影重建能造成的语义失效恰落在短时域来源的两项检查上。
- **不改**：`recall_authority_events`/`recall_authority_heads` 的 DDL 与行形状（epoch 单调 +1、`previous_epoch` 严格衔接、`initialized` 惰性建头 0→1）、事件+CAS 事务、两处围栏判据与抛出码、世代激活审计。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.28.json`；新增 4 项回归测试（3 项在 0.6.27 源上失败）。
- **仍可叠加**：Host 备忘 §7(2) 把 epoch 相等性降级为"来源重校验通过即签发 + 降级码"、§7(3) Harness SDK 为用途围栏拒绝留同 Run 有界修复路径。本次只做 §7(1)。

## 2026-09-08 0.6.27 世代重建把嵌入移出写锁；召回取锁受 deadline 约束

最后更新：2026-09-08。基于 0.6.26，仅本地候选、未发布、未构建制品、Host 未 pin。诊断见 Host `simple_harness/plans/2026-09-08-hm-to-a6/DIAG-RECALL-TIMEOUT.md`（HM-TO-A6 turn 22 现场）。

- **缺陷**：`rebuild_short_horizon_generation` 与 `rebuild_cognitive_vector_generation` 在 `_write_lock` 内 `await embedder.embed_batch(...)`。真实 WeMM 每条 200 ms 且无批处理覆写，6 条 chunk 合计 45.7 s，而 Host 维护 tick 超时 5 s：世代永远激活不了、manifest 永远对不上、下一 tick 全额重试，形成活锁（写锁占空比约 65%）。前台 typed recall 的 `_admit_typed_recall_request` 与 `_prepare_cognitive_vector_lane` 取同一把锁又没有 deadline，拿到锁的第一件事就是 `raise TimeoutError` —— 五次失败的 `typed_recall_terminals` 全是 `candidate_query_started=0`，一条候选都没扫过。该实现与本 SDK 决策文档 `DECISION-2026-09-07-cognitive-vector-lane.md` §4.1/§4.2/§4.4 的三条不变量全部相反。
- **修复（三段式重建）**：① 持写锁读行 + 算 manifest hash + 判 replay/空集（认知侧含公开 payload 文本渲染）→ ② 释放写锁做 `embed_batch` → ③ 重新取写锁做 manifest 乐观 CAS，未变才写向量表、原子激活、旧世代 retire、落审计。CAS 落空返回 `cas_miss=True` / `activated=False` / `audit_id=None` 并记结构化日志，**不写审计行**（两张审计表的 `event_kind` 只有 `generation_activated`，认知侧 `generation_state` 还有 `CHECK IN ('active','empty')`；把未激活记成激活会污染防篡改记录并逼出无谓 DDL 变更），下一 tick 以新清单重建。
- **修复（召回取锁）**：新增 `_write_lock_before(deadline, *, stage=None)`。向量 lane 的等锁额外预留 `COGNITIVE_VECTOR_LOCK_RESERVE_S = 0.200`（DB 侧实测全流程 24–31 ms，6–8 倍余量），超时**退化**为 `cognitive_vector_deadline` 并把余下预算留给词面 lane 与终态写入；`_admit` 保持硬失败但抛 `TypedRecallDeadlineExceeded(stage='admit_write_lock')`（`TimeoutError` 子类、`str()` 仍是 `DEADLINE_EXCEEDED`，Host 映射逐字不变）。
- **不改**：幂等/replay 判据、generation id 形状、空集分支、`COGNITIVE_TEXT_FORMAT_VERSION` 并入 manifest、0.6.24 的 `failed` 行与 `CognitiveVectorGenerationFailed`、资格门与 lane 计分。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.27.json`；新增 7 项回归测试（含 0.6.26 上以 `DEADLINE_EXCEEDED` 失败的活锁复现）。
- **Host 侧仍需配套**：`WeMMEmbedder` 缺 `embed_batch` 覆写、短时域 chunk 文本无长度上限、`PrimaryShortIndexWorker` 无退避/断路、`deadline_ms=1000` 偏紧、一次 recall 超时不应杀死整个 Run。

## 2026-09-08 0.6.26 Prospective 触发条件的自然语言渲染（词面 + 向量同源）

最后更新：2026-09-08。基于 0.6.25，仅本地候选、未发布、未构建制品、Host 未 pin。语料 run-01f C04 实证。

- **缺陷**（C04-01）：跑道修好 `prospective_scheduler_registrations.state='accepted'`（trigger_hash 一致）之后，「我还留了什么周一要做的提醒？」仍然零召回。prospective 公开 payload 只有 `action` 与 `trigger`，而 trigger 是 epoch 数字（`1788742800.0`）、时区名与 `time` 枚举：词面门（`canonical_json(payload)` 计数 `typed_recall_query_terms`）命中 0，向量文本（`cognitive_vector_text`）与「周一要做的提醒」余弦 ≈0 远低于 `COGNITIVE_VECTOR_MIN_SCORE=0.45`，entity/task_scope/temporal 三条 lane 未被请求，候选在 `_collect_typed_recall_candidates` 的 `if not lane_values: continue` 处被整条丢弃。
- **修复**：`features/cognitive_vector.py` 新增确定性渲染 `prospective_trigger_text()`——按公开 trigger 的 timezone 把 `trigger_at` 渲染为「YYYY-MM-DD 周X HH:MM」（中文星期）+ trigger_kind 中文（time→定时、event→事件）+ 固定词「提醒 待办」；未知 kind / 不可渲染时刻 / 非 Mapping 一律退回空串或只保留 kind 词，未知时区退回 UTC。`cognitive_text_supplement()` 把它同时喂给两处：`cognitive_vector_text('prospective', …)`（action 仍在最前，渲染紧随其后，原始 trigger 字段照旧在末尾）与 typed recall 的词面门文本（`canonical_json(payload)` + 渲染）。
- **世代重建**：`_cognitive_vector_manifest_hash` 除 head 清单外并入 `COGNITIVE_TEXT_FORMAT_VERSION`（=2）。渲染函数一变，旧 active 世代的 `content_hash` 不再等于当前 manifest，`_prepare_cognitive_vector_lane` 判 `cognitive_vector_stale` 并退化，下一次 `rebuild_cognitive_vector_generation()` 整代重建，不会继续使用按旧文本嵌入的向量。
- **不改**：公开 payload 形状（渲染只进入检索文本，`action`/`trigger` 原样返回 Host）、资格门（lifecycle/epistemic、注册与信号权威、抑制、disclosure、时间窗、指纹门）、余弦阈值、lane 排序与预算、其余四类记忆的向量文本逐字不变。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.26.json`；新增 7 项回归测试。

## 2026-09-07 0.6.25 Procedure 发现面对已采用流程可见、中文词项匹配

最后更新：2026-09-07。基于 0.6.24，仅本地候选、未发布、未构建制品、Host 未 pin。裁决见 `simple_harness/plans/2026-09-07-native-main-journey/DECISION-PROCEDURE-USE-CHAIN.md`。

- **缺陷**（原生 r8/r9、r24/r25）：用户明确采用的流程落库为 ACTIVE + UNBOUND 指纹，`discover_procedure_drafts` 只看 draft/eligible，typed recall 又要求指纹已绑定且等于当前 Run 指纹，模型没有任何入口拿到 memory_id/revision 去 `procedure_use`；另外发现面只做整串子串匹配，中文查询必须逐字出现在 name/steps。
- **修复**：两个查询面分工——**发现面 = 任何仍可使用状态的候选 + 词项匹配；召回面 = 已绑定且当前适用**。`core/procedure_discovery.DISCOVERABLE_LIFECYCLE_STATES` 扩到 draft/eligible/active/reinforced（与 `read_procedure_use_target` 一致），其余资格门与自证披露门不变；`backends/procedure_discovery.match_score` 用 `typed_recall_query_terms` 对 name + applicability + steps 计数命中（整串子串 +1），单页内按命中数降序、扫描序稳定排序，`next_after` 仍是扫描序 memory_id。
- **不改**：向量世代/manifest、typed recall 指纹门（UNBOUND 仍 NO_RECALL）、`procedure_use`/观察/恢复语义、候选 DTO 与 hash 域。无 DDL 变化、根导出零增减；快照 `public-api-0.6.25.json`；新增 4 项回归测试。

## 2026-09-07 0.6.24 认知向量世代跳过 relation 记忆、构建失败落库

最后更新：2026-09-07。基于 0.6.23，仅本地候选、未发布、未构建制品、Host 未 pin。

- **缺陷**（原生 r8）：含 semantic relation（`applies_to`）的提案落库后，Host 短索引 worker 每 tick 抛 `MemoryCorruptionError`（`typed recall payload missing`），`cognitive_vector_generations` 始终为空。relation 记忆是 `cognitive_memory_heads` 里 `memory_type=semantic` 的 head，但它是图谱的边（HM-AC-6）而非节点：没有 `semantic_claims` 行，从不参与召回排序。0.6.23 的 `_cognitive_vector_head_rows_unlocked` 把它当节点取公开 payload。短时域 projection/generation 不受影响。
- **修复**：`_cognitive_semantic_head_is_relation`（与 typed recall 类型权限门同一判定，content 不可解析 fail closed）在 head 收集处排除 relation；manifest/stale 判定、缓存完整性校验与 `vector_count` 同步只计节点 head。typed recall 的 vector lane 与 confirmation 门本就在类型权限门之后比对，relation 永不被打分或返回（回归钉死）。
- **构建失败契约**：`rebuild_cognitive_vector_generation()` 任何失败 → 先在独立事务落 `cognitive_vector_generations(state='failed', last_error_code)`（`cognitive_vector_head_invalid` / `cognitive_vector_embedding_failed` / `cognitive_vector_generation_write_failed`），再抛 `core.errors.CognitiveVectorGenerationFailed`（`code`、`generation_id`；RuntimeError 子类）。worker 不再每 tick 收到未落库的 `MemoryCorruptionError`；故障消失后下一 tick 正常构建。无 DDL 变化、根导出零增减；快照 `public-api-0.6.24.json`。

## 2026-09-07 0.6.23 长期认知记忆向量通道源码候选

最后更新：2026-09-07。按 [裁决](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-07-cognitive-vector-lane.md) 方案 A 实现，仅本地候选、未发布、未构建制品、Host 未 pin。

- **向量通道**：typed recall 在既有资格门（状态/类型权限/血缘/抑制/scope/entity/时间/disclosure）之后、排序之前新增认知记忆 `vector` lane，RRF 权重沿用预留的 0.40；confirmation 门同样接受 vector 命中。资格门顺序、`typed_recall_query_terms` 与 full_text/entity/task_scope/temporal 计分不变。余弦只对已通过全部门的 (memory_id, revision) 计算，被抑制/遗忘的记忆永不进入向量比对；查询向量在取 `_write_lock` 之前、带 audit 预留的 deadline 内嵌入。
- **世代**：`MemoryManager.rebuild_cognitive_vector_generation()`（复用 `short_horizon_embedder`，无新 builder kwarg）镜像短时域世代重建：可召回 head（含 contested）→ manifest hash(memory_id, revision, content_hash) → 同 lineage 同 manifest 则 replay，否则 `embed_batch` 公开 payload 文本（`features/cognitive_vector.py::cognitive_vector_text`）→ `cognitive_vectors` → 原子激活、旧世代 retire → `cognitive_vector_audit` → recall authority `cognitive_vector_generation_changed`。嵌入永不在 mutation 写锁内发生；召回只读。缓存复用 `_ExactVectorGenerationCache`，ref 为 `memory_id:revision`。
- **退化码**：`cognitive_vector_unavailable` 仅表示无 embedder；`cognitive_vector_no_generation`（无 active 世代）、`cognitive_vector_stale`（active 世代 manifest ≠ 当前 head manifest）、`cognitive_vector_deadline`（查询嵌入超时/向量无效）。全部落 `typed_recall_terminals.degradation_codes_json`；命中时 terminal_json 记 `cognitive_vector.used_generation_id_hash`（opaque hash）。
- **阈值**（0.6.34 起，见 [裁决](../plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-09-vector-score-margin.md)）：**不再是单一绝对常数**。Host 语料实测证伪了 0.6.23 的取值理由——目标记忆的余弦分布（min 0.0601 / p05 0.3048 / 中位 0.5738）与无关记忆的分布（中位 0.2818 / p95 0.4363 / max 0.6251）**完全重叠**，不存在「下有同义改写余量、上在无关之上」的常数。现行规则：`effective(type) = min(0.45, max(0.35, 0.90 × 该记忆类型内已过全部资格门的最高余弦))`，`cosine ≥ effective` 才进候选（`COGNITIVE_VECTOR_MIN_SCORE = 0.45` / `COGNITIVE_VECTOR_RELATIVE_FLOOR = 0.35` / `COGNITIVE_VECTOR_RELATIVE_RATIO = 0.90`，均在 `features/cognitive_vector.py`）。`effective ≤ 0.45` 恒成立，故只放宽不收紧；护栏 0.35 仍待 Host C07 零召回子集端到端回归。
- **schema 7.4**（`backends/schema_v7_4.py`，`DDL = schema_v7_3.DDL + COGNITIVE_VECTOR_DDL`）：`cognitive_vector_generations` / `cognitive_vectors` / `cognitive_vector_audit`；7.3 checksum 冻结。7.3 库（fresh 或带 7.2→7.3 marker）打开即前向追加三表并写 `schema_meta[cognitive_vector_forward_v1]`（`migrations/cognitive_vector_forward.py`），原初始化 receipt/meta checksum/7.3 marker/业务列不改写；未知 catalog/checksum fail-closed。`migrate_human_memory_v7_2_to_v7_3` 视已前向的库为已完成。
- **测试**：`test_cognitive_vector_generation.py`（7）、`test_typed_recall_cognitive_vector.py`（9，含五种 C01 FAIL 形状、抑制/disclosure 优先、阈值负控、stale/无世代/无 embedder/超时退化、confirmation、持久化、零副作用）、`test_memory_0623_schema_cutover.py`（5）；改写 `test_typed_recall_v6.py` 退化用例；公共 API 快照 `public-api-0.6.23.json` 根导出零增减。Host 需同步：`retrieval_modes` 恒含 VECTOR、short_index_worker 追加 `rebuild_cognitive_vector_generation()`、重 pin。

## 2026-09-06 M618 实际安装恢复控制

最后更新：2026-09-06。主转Dirac限定接受d46bf1f/cf7c8d5及Host6b53f27c/e37c42bb，版本d8d80d5固定0.6.18。一次offline wheel SHA010b4281…，两变动包成员fixedGit/source/wheel/独有target一致；H077依赖、无Memory源码覆盖的完整cohort及Host原普通异常升级两控通过（0.11s/0.73s）。PG1723/exit0/2.408s/峰189120KiB/remaining=[]，锁释放。M617/主环境不动；制品独审与主H078组合另验，Procedure观察/适用性仍待接线。[准确制品、hash及证据](../plans/2026-09-06-analysis-retry-protocol/CANDIDATE-0.6.18.md)。

## 2026-09-06 完整 analysis 重试输入恢复

最后更新：2026-09-06。后继源码d46bf1f保留普通失败批次完整request语义及原成员顺序，只替换attempt身份；新job独立使用新配置，篡改请求／成员拒绝。SDK三控及H077/M617依赖上的Host源码覆盖五控通过，含原v3普通异常→v4配置零新增Provider；旧24绿未跑。PG1149/exit0/3.834s/峰191648KiB/remaining=[]，共享槽释放。M617冻结不变，0.6.18.dev0未构建；待最终源码独审与实际installed，不称完整Procedure功能通过。[必要控制、原红边界与证据](../plans/2026-09-06-analysis-retry-protocol/RESULTS.md)。

## 2026-09-06 prospective终局与schema7.3源码候选

最后更新：2026-09-06。按2553已接受边界新增公开settle_prospective_invalidation严格联合、独立持久not_required receipt/observation、同事务无登记请求证明和后续登记门；新7.3显式升级保留原7.2 DDL/初始化receipt/业务列，fresh用7.3。主已转Dirac源码限定ACCEPT；0.6.17单次offline wheel e119cdcc…已构建，16个变动成员=source/wheel/own target，独有安装3PASS/0.68秒，无Memory源码覆盖；PGID70661/exit0/峰147104KiB/1.522秒、无残留，槽释放。Host52由主实施。业务源码5ee3c6b；新增12项风险控分批通过：r4为11PASS/1测试断言FAIL，topic范围修正后r5定向1PASS，不重复其余绿。PGID67413/exit0/峰115936KiB/0.657秒、无残留，槽释放；旧V2八项未重跑，尚无Host52实际组合结论。[实际接口与待验收边界](../plans/2026-09-06-prospective-signal-source/SDK终局实现.md)。

## 2026-09-06 prospective signal source V2 源码

最后更新：2026-09-06。新增公开read_prospective_outbox_source_v2及显式mutation/signal联合，按既存consumption/decision/result与历史revision核验signal来源，返回真实apply result，不伪造mutation receipt或Run。v2 operation/request/observation域明确，owner域沿v1；616旧方法/wire/hash不改。8个限定用例分批通过（首批5处篡改库teardown拒绝已显式断言），PGID54768已清空、槽释放；未构建/独审/Host组合。已证实同ref公开apply可恢复已提交的过期lostACK；无registration请求的派生revision之invalidation仍需主决定有记录终局，不能称scheduler闭合。[固定DTO/metadata接缝、精确方案及结果](../plans/2026-09-06-prospective-signal-source/最小契约.md)。

## 2026-09-06 M616 prospective source 候选

最后更新：2026-09-06。新增 public exact outbox reader，校验 owner、payload/hash、idempotency、持久 emit 时间、历史 target scope/lifecycle 与真实 mutation run/operation/receipt；invalidation 不用当前 head 改写来源，也不将 target lineage 冒充 outbox cause。signal 派生目标缺 mutation receipt 明确拒绝。源26项分批通过、必要邻居2项；metadata 经真实 H073 sink 原红后修白名单投影，定向通过。成功/拒绝/取消均交付独立 invocation observation，稳定 source hash 不受影响；Host 落盘与 OA1 全覆盖仍未证明。源码931b8c7固定0.6.16候选；offline wheel SHA00937eb5…，独有installed source3项通过/0.55秒，PGID47559已清空。未独审或Host组合，不影响冻结615；未改SDK schema/模型/Provider/native。[唯一接口及证据说明](../plans/2026-09-06-prospective-outbox-source/CONTRACT.md)。


## 2026-09-06 M0.6.15空assistant制品交付

最后更新：2026-09-06。源17aebde/测试9bbf42b已获主转Dirac限定ACCEPT；分配M615后固定7f9983d，双offline wheel SHA69544677…一致，351751bytes。73包成员=fixedGit、76非RECORD成员=独有安装target，借用H073的169成员一致；-I installed9项通过/1.06秒，无源码overlay，旧614全部73包文件不变。PGID43803/峰139856KiB/elapsed2.38秒已清空、槽释放；制品15MiB，无新完整venv或下载。未改Host pin/SDK main/发布，主H074组合与制品独审另验；prospective源事实API及非SELF不含于615。
[准确wheel路径、SHA、安装身份与原始证据索引](../plans/2026-09-06-short-empty-assistant/CANDIDATE-0.6.15.md)。


## 2026-09-06 空assistant完整组局部验收

最后更新：2026-09-06。业务17aebde保持不变，WIP0.6.14。原installed614的空组注册两红/非空正控绿；源码9专项分批通过、9投影/来源邻居通过，唯一测试修正是超限先被S1公开入场门拒绝。主d8a985c2原空assistant真实11turn工具组载体在Memory源码overlay下通过4.49秒，全部ordinal/parent与空字节保留，short/reopen/forget闭合；不算installed后继验收。四组已清空、测试槽释放，raw35MiB，剩余约3.8GiB。未build/install/分配615/合主，Dirac独审仍待，非SELF/输入permit及完整原程序未完成。
[原红、全部批次、精确路径/hash和限制](../plans/2026-09-06-short-empty-assistant/RESULTS.md)。


## 2026-09-06 最终受众约束0.6.14候选

最后更新：2026-09-06。业务d7cb3ca已独审限定ACCEPT，ordinary/candidate联合检查当前接收者与最终受众，修正协作者枚举不同拼写的history误拒；未放开external/public、非self原始history或classification/来源/遗忘门。原4反例红→必要源码13绿；27dceff后继0.6.14两次wheel一致、独立Memory安装target4个公开API检查通过。76个Memory和借用H073的169个安装成员匹配；非新完整venv，未更新Host pin或SDK main，未发布。资源串行/有界/无残留；[行为、边界和精确身份](../plans/2026-09-06-disclosure-audience/RESULTS.md)。


2026-09-06 final：Memory0613固定source/双wheel/exact installed已获Dirac只读
限定ACCEPT，无新增P0/P1；未改已核wheel或业务源。Host正式installed组合另验，
测试槽已释放。[独审闭合](../plans/2026-09-06-typed-short-sources/REVIEW.md)。

2026-09-06：typed-short source cd1ea1a已Dirac scoped ACCEPT，后继0.6.13固定
f2a6a706；两独立offlinewheel SHA33fcc494…相同，72包文件等于fixedGit。
owninstalled H073/M0613 public consumer8PASS2.09s，installed成员75/169字节一致；
Host只消费此wheel不overlay，完整group/final出站仍主线验证。无模型/native/DDL/发布，
旧0612冻结未动，整体扫描成本仍未闭合。制品只读独审待结果，测试槽已释放。
[固定artifact/边界](../plans/2026-09-06-typed-short-sources/CANDIDATE-0.6.13.md)。


## 2026-09-06 typed-short selected sources isolated source leaf

最后更新：2026-09-06。新public MemoryManager.resolve_typed_short_horizon_sources仅
接受durable typed selected-short四元组；返回现有ShortHorizonSourceSnapshot/Item/Ref，
新request/binding hash域，同current visibility事务验证owner/selection/current来源
与完整registration lineage。认知或未选中item不给refs，不伪造旧audit_id；旧short
接口/wire/DDL/hash不变。source阶段最终唯一31项绿，真实principal占位绕过原红保留
且newport专用exact校验修复。尚未改版本/build/install；Host只后继installed消费。
[契约](../plans/2026-09-06-typed-short-sources/CONTRACT.md) /
[命令与结果](../plans/2026-09-06-typed-short-sources/RESULTS.md)。

## 2026-09-06 可信输入绑定已复核并纳入 main

最后更新：2026-09-06。固定 `6e23c22` 的21条可见源片段绑定已经子代理实现、主代理逐例复核，以 `5edf0c5` 纳入 main；8项源契约验收通过。C05-07及C12全20条的用户语句、可信配置需求、共同政策和缺失字段显式分开，未改变r4或第一层编译器。运行链路仍缺实际Host身份/受众/用途政策、时钟与公共setup接线，240正式执行仍0；SDK源码仍0.6.3。详见[主代理复核](../scripts/corpus_trusted_bindings/主代理复核.md)。下文未合入、待复核等描述保留为当时历史，不覆盖本节当前状态。


2026-09-06主复核：源规格编译固定b72dbff限定ACCEPT并FF main；SDK源码仍0.6.3，15项源契约分批闭合，240正式执行仍0。详见[主复核](../scripts/corpus_runtime_input/主代理复核.md)；Host隔离组合18ec7194的M0613安装/模型short/资源验证与此源编译独立，见[续接记录](../plans/2026-08-29-human-memory-digital-twin/RESUME-2026-09-05.md)。

## 2026-09-06 21例可信字段source adapter验收

最后更新：2026-09-06。独立后继分支 `feat/corpus-trusted-bindings` 基于main `2641c90`，新增固定caseID、源行/UTF-8片段/hash映射，将C12全20例及C05-07的fixture配置需求与当前用户句显式分开；运行时不按自然语言分号推断角色、不从gold/setup决定权限。原r4及第一层源码/测试/中文文档未改，本后继分支尚未合入main。

8项标准库契约验收全部通过，覆盖21输入完整保留、源变更拒绝、隐藏gold/setup变异不影响绑定及无凭据/伪造凭据不可dispatch。经145资源入口默认共享锁、512MiB/90秒执行，进程组29035无残留，已通知主释放测试槽。没有运行SDK、Provider、模型或native。

模块边界仍为**源绑定已验收，Host公共setup及authority验证未实现**。21例全部ready/dispatchable/executed=false；第一层21 BLOCKED及240 ready=0历史结论保持。C05-07受众/用途/真实task ID与scope缺口明示；源policy hash不是权限receipt，不把此验收换算为模型质量或401矩阵通过。

[21项逐例映射](../scripts/corpus_trusted_bindings/逐例绑定.md)；[接口及剩余接线](../scripts/corpus_trusted_bindings/接口与状态.md)；[验收命令、源码及ignored证据SHA-256](../scripts/corpus_trusted_bindings/验收结果.md)。

## 2026-09-06 r4源编译与隔离契约验收

最后更新：2026-09-06。独立分支 `feat/corpus-runtime-input` 基于main `1a53e58`，新增标准库MD编译器，生产链路为只读r4源指纹校验 → 显式字段解析 → input/setup/scheduler/oracle/audit分区输出。原240条MD、旧集及阈值不变；不导入SDK、不执行Provider。此分支尚未合入main。

第一层源编译/隔离契约的15项必要验收已覆盖：首轮14项通过、1项测试变异定位错误；修正测试后定向3项通过。双次CLI输出字节一致，240ID/12类/22脚本、时钟与角色历史、输入非干扰和拒绝路径有标准库证据。统一资源入口145baed3以512MiB/90秒、默认共享锁运行；两个进程组无残留并已释放测试槽。

模块状态仅为**源编译层已验收，运行适配未完成**：21例混合可信输入仍阻断投影，全部240例ready=0/executed=0，公共setup/可信政策/三端时钟/真实历史/后续轮事件适配仍缺。零查询不证明后台gate已测，未运行模型质量或native，不能把本层验收当作program通过。

[接口与可见性](../scripts/corpus_runtime_input/接口契约.md)；[批次、命令、失败修正、ignored证据索引及SHA-256](../scripts/corpus_runtime_input/本轮实现状态.md)。以下保留既有审查及历史运行事实。

## 2026-09-06 后继中文语料完成AI两层审查

最后更新：2026-09-06。本仓SDK源码仍是main 0.6.3，隔离Host组合134bc4b8消费H073/M0612/S0313；本次未合入SDK运行时代码或切换用户主checkout。中文后继12×20语料由一个AI子代理和主代理逐条复核，r4语义基准可用于实现评估适配器。不是人工冻结、实际模型质量或完整program通过。
[审查结论、全部MD与剩余接线](../plans/2026-08-29-human-memory-digital-twin/quality/recall-corpus-candidate/review-zh/后继240条主代理复核.md)。401矩阵、两轮模型质量、性能与Context预算仍未完成；以下旧记录按历史保留。

# ARCHITECTURE — simple-harness-memory-sdk（v0.6.3 candidate）

> 最后更新：2026-09-05
> 当前事实：Human Memory V0/S1/S2 与 S3 Task 1–7 的 SDK 范围已闭合；S3 Task 6 已补齐一等
> `applies_to` 语义关系 proposal、原子持久化、公开收据视图与 display-only graph 投影。Host/UI 接线、
> Host durable pre-admission audit 与 program 最终验收须按各自 AC 核对。Memory 0.6.3 candidate 已构建接入；旧 Agent Memory v1 能力仍保留，
> 但不是新认知 mutation 的 authority。



## 2026-09-05 duplicate-source forget 共享源码候选（源码独立 scoped ACCEPT）

在独立069后继树实现真实 Host origin/cut 两阶段准备、当前 canonical MEMORY 全 revision
来源拒绝与共享 suppression resolver。实际 builder支持 history_source_authority，公开能力
MemoryManager.history_source_enforcement_version=1；不以此替代 exact后继artifact身份。
本机206项限定源码测试通过（15.14s），含22项新数据库控制、配置新authority后的23项原
攻击/zeroSQL控制、capability及相邻回归；ruff/mypy4源通过。原56c6bf7 no-/text误拒P1已
由2b2fa47修复；Dirac已对固定53099e7完整enforcement源码 scoped ACCEPT，未见剩余当前P0/P1。
同一short用例补强实际不同来源、遗忘后旧typed新attempt拒绝与历史receipt重放、
cut后同文atomic来源移出recent10后的召回/最终使用正控，单跑1PASS/0.45s；生产代码未变。
旧v1action无cut仍持续拒绝同内容新重申，不称支持旧库fresh reassert；Hostlate-enqueue
隐私拒绝正确，但CLAIMED/无SDKrun的settle闭环由主修复，未标产品PASS。/text等值SQL
无匹配索引，4096工作上限不证明P99。未分配版本/安装wheel/改main/native/冻结069，
不标S3/program完成。[当前源码、命令与边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-duplicate-source-forget/ENFORCEMENT.md)。


## 2026-09-05 duplicate-source forget 公共协议叶（未接 enforcement）

独立分支从冻结069新增 HistorySourceNamespace / HistorySourceOriginReceipt /
HistoryForgetCutReceipt / HistorySourceAuthorityPort 四项公共契约，固定 atomic 与
legacy_before_only 队列顺序证明、原始 v2 action cut 与 canonical hash 向量。
仅协议/根 API 源码38项通过、ruff/mypy通过；builder、当前 suppression 执行及真实数据库
red→green 尚未实现，不标 P1/S3/program/native 完成。旧 v1 action 无 cut 仍明确
UNVERIFIABLE；不回填、改旧hash或声称原 native forget PASS。未分配版本/build候选/合main，
冻结069字节不变。[协议交付与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-duplicate-source-forget/PROTOCOL-DELIVERY.md)。


## 2026-09-05 Memory0.6.7 独立候选冻结准备

主统一分配0.6.7给已审short e19161ba；仅版本、根快照与公开消费者增量，产品行为无修改。
根快照4项与新增short真实public source consumer11阶段通过；新wheel/isolated installed
消费与完整字节核验正在执行。封存0.6.6 wheel不覆盖，未合main/Host/native或发布。
[本轮候选记录](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/CANDIDATE-0.6.7.md)。

## 2026-09-05 独立 standalone short 历史可见性源码修复

在封存0.6.6之后的独立分支新增 `HistoryShortHorizonBinding(audit_id,chunk_ref,content_hash)`，
复用当前批量history快照，验证真实owned recall成功audit的exact选中、canonical来源、expiry、
disclosure与evidence/entity/反向MEMORY suppression。28项专项+93项相邻源码测试通过，
独立review ACCEPT；无需Host私查SQL或伪typed binding。nextProvider每次出站仍须当前完整来源复查，
SDK检查不是网络发送锁或Host依赖完整性证明。尚未分配新版本/build/pin/合main/接Host；
已封存0.6.6 wheel完全未变，该新能力不属于旧wheel。不标S3/S6/program完成。
[契约、验证与接线边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/RESULTS.md)。

## 2026-09-05 Memory0.6.6 隔离组合源码候选

用户授权独立组合history a96a5008、clock16dc707与rejection30743bb；不修改冻结0.6.3/0.6.5
wheel及main/Host环境。新0.6.6根快照保留所有旧导出并包含五项history DTO，schema/hash/阈值不变。
130项限定源码测试已通过；clean source9ec5943对应wheel381d8543已在新venv通过public
consumer、Memory63/Harness151源/轮子/安装字节一致性及pipcheck。尚无Host/UI完成结论。独立short-horizon hit仍缺历史复查binding，明确保留后继接口缺口。
详见[组合候选契约和命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/CANDIDATE-0.6.6.md)。

## 2026-09-05 隔离 history visibility 源码候选

从 main8675352 / Memory0.6.3 独立分支 `feature/human-memory-history-visibility` 完成 AC1/AC7
历史来源检查的限定 SDK 修复：memory_id suppression 反向覆盖原 USER、派生 evidence 及全部支持修订；
新增公开批量 `check_history_visibility`，接受 Host 验证的 S1 envelope/receipt（允许尚未分析/摄入）
或已持久化 recall result/item 绑定，同一读快照检查当前来源状态、suppression 和 disclosure。
不造 UI execution Run、不新增 authority；epoch 不是完整历史版本，Host 每次出站须 fresh-check。
本机 source 验证共94项通过（24项新 history +47项既有聚焦 +23项 mutation），限定独立 review 接受。
版本/冻结快照JSON/schema/wheel/pin未变，未合 main、未接 Host；无 provider/UI/installed-candidate
验收或 p95 性能结论，不标 S3/S6/program 完成。详见[契约、命令及本机证据索引](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/RESULTS.md)。

## 2026-09-05 最新 Host 及 S3 隔离候选验证

当前 Host main `c183fe70` 使用 Harness 0.7.2 / Memory 0.6.3 / Service 0.3.12。
Harness route P1 已修，两个真实生产 root 在旧 Host `8d574415` 完成 effect/closure/analysis；
随后发现的 episode 时间 P2 已在 Host `4eb1eb7c` 改为首次持久化观察时间，受影响 150 条通过。
新真实复验在前台第七次 Provider handoff 后遭传输 unknown，未进入 analysis，保留 FAIL、无重发。
S5b machine gate 尚未闭合；完整试次、REG 两项测试修正与四项历史红见
[RESUME](../plans/2026-08-29-human-memory-digital-twin/RESUME-2026-09-05.md)。

S3 隔离分支 `feat/typed-recall-observability` 的 source `30743bb17ed8301d01028357de6e4c5adcdde26b`
为 Memory 0.6.5 candidate；wheel SHA-256
`0977159d043d409d39232d0f14f91d27f1b09ac1a4523cf8aba9028f0d0a71df` 双次构建一致。
新增可信构造 clock、候选读取前的不可变异常见证及严格协议版本入口；既有 schema/hash/预算不变。
源码全量 1157 passed / 9 skipped，独立 source review ACCEPT；独立安装环境 77 个 SDK 模块来源正确，
Memory 61 / Harness 151 个包文件与指定 source/wheel/installed 字节一致，public clock/rejection/protocol/
reopen exact replay 与 pip check 通过。identity manifest SHA-256
`02aac6deb9944f185d9632b15c97587238f8e8aed36d666f90621d4f7601a0b2`。
证据索引为 Host ignored `human-memory-resume/independent-review/memory-rejection-065/REPORT.md`。
该候选未合入本仓 main、未替换 Host S5b pin；401-cell clean-wheel consumer 验收仍在执行，
240 条 corpus 未独立人工冻结。S5c/S6 隔离实现中，program 未完成；以下更早段落保留历史边界。

## 2026-09-05 当前候选与真实入口边界

Memory 0.6.3 source `2f3d73814fe6a884e0458d87567b918c5863033e`，双次 wheel SHA-256
`6b20ae5bff6c3ecfe1108ccaff9bb41c4dc6a3b98bb754dac2c418673ab77c78`；Host `26b50ee8`
已按 exact wheel 接入，集成 51 passed、安装版 SDK 16 passed。新候选原生 UI/gpt-5.5 非空回复成功，
root `c2af5326a8d05023868f7994f1a4e0be`；r5 保留早期失败，S8 状态 FLAKY。
A14 真实 queue.enqueue 在 README 写回后触发 Harness 0.7.1 initial/current route 恢复 P1：
root `142bdb3b-9026-5264-b244-69e94bf0e388` terminal FAILED、closure pending、accepted/head=0。
这不推翻 IR-02/03 的固定 plan/evidence 回归结论，也不构成 S5b 完成。
用户已批准 [A17 限定修复](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-02-s5b-effect-closure-memory/SDK-ROUTE-UNFREEZE-PROPOSAL.md)，
其余 SDK 功能/原 AC/权限/预算/oracle 不变；S3 契约修订另线已获批。本次只回写文档/证据；SDK 0.7.2 源码修复已提交 `2b842846…` 并经 review，Host 安装与生产复验仍待完成。
证据索引与状态见 [PROJECT_STATUS](PROJECT_STATUS.md) 和 [RESUME](../plans/2026-08-29-human-memory-digital-twin/RESUME-2026-09-05.md)。

本机当前回归使用 Host 的 Python 3.12 / exact Harness 0.7.2：全量 1123 passed / 9 skipped，
旧 cutover 测试的 0.6.2 版本字面量更正为 0.6.3 后，该文件 3 passed。
v7.1 DDL checksum 与全部迁移断言不变；这是测试身份修正，未修改已验证 wheel 的运行时包。

## S5b AC2：analysis 恢复与 no-mutation 正确性（2026-09-05）

本修复已通过独立复审并合入 main；当前 source candidate 0.6.3，公共 API 与 schema v7.1
保持 0.6.2 契约。以下 phase-3 交接中的“待 review”已由此更新；Host exact-wheel 已核验，整体验收仍受 SDK route P1 阻塞。

- 对应原始 [S2 Task 5](../plans/2026-08-29-human-memory-digital-twin/slices/S2-memory-evidence-audit-suppression.md)
  与 [S5b AC2 / Task 4a](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-02-s5b-effect-closure-memory/acceptance.md)，
  修复独立审查 S5B-IR-02 / IR-03；基于 Memory `78d6192`，仅源码修复，版本/schema/候选 pin 不变。
- `claim_analysis_batch` 在现有 `BEGIN IMMEDIATE` 内排除仍有 `handed_off` 或 `result_committed`
  batch 的 principal。新 evidence 照常摄入、job 保持 pending；lease 到期先 reclaim 原 batch，使用已保存
  request/result/plan/evidence 与原 `base_revision`，不追加 Provider 调用。`audit_pending` 已提交物化与 head，
  可以与下一 batch 重叠；不同 principal 的 pending batch 仍可领取。
- 未改变 plan/evidence/lineage/hash/target revision 契约，也未自动 rebase。真正的 CAS 或目标冲突仍按原规则拒绝；
  本修复防止新 analysis 抢先推进同属主 head，不回填旧版本已终态拒绝的 batch。
- 无操作结果允许 `{outcome: no_mutation, operations: []}` 及可选字符串 `closure_reason`，首次应用和 durable
  replay 使用同一校验。accepted plan 连同原理由生成 canonical hash，保留审计信息；无认知 revision/head、
  mutation receipt、operation decision 或 cognitive/prospective outbox 写入，apply revision 不递增。
  `analysis_response_unusable` 仍 rejected，原 structured result/Host 告警与审计保留；非法字段/类型/非空操作继续拒绝。
- 仓内决定性回归见 [test_analysis_recovery_correctness.py](../tests/integration/test_analysis_recovery_correctness.py)：
  apply commit 前后故障、新一轮到达、close/reopen、原结果与 accepted plan 字节契约、两份 evidence 最终各有 head、
  恰好两次 Provider 调用、同 principal 并发领取/跨 principal 进展、no-mutation 合法/非法形状及 audit_pending 恢复。
  原始 Host 生产复现也以本 worktree 源码重跑；Provider adapter 为确定性替身，未声称真实模型/UI/生产验收。
- 本节仅为 phase-3 修复事实；独立 review 由主执行者另派，S5b/program 完成状态与其他验收门保持原边界。
  测试命令、结果与本地证据索引见 [PROJECT_STATUS](PROJECT_STATUS.md)。

## Human Memory Program 当前边界（2026-09-01）

以下是 0.6 candidate 的已验证生产边界：

- fresh `human-memory-v1` schema v7 保存不可覆盖的原始 evidence、conversation registration、suppression、
  durable analysis，以及 Episode、Semantic、Procedure、Prospective 四类 typed revision/head/relation。Working
  Memory 仍只存在于运行 Context，不建立长期存储表。
- `MemoryMutationPlan` 只接受 Harness mutation schema v5；Semantic payload 显式区分 claim/relation，四类 payload、生命周期、epistemic/conflict/
  verification/valid-time、classification 与 TaskScope origin 在同一 strict-atomic transaction 落库。
- CREATE 依靠 exact admitted evidence 与 Memory classification policy；修改既有记忆的 REVISE、SUPERSEDE、
  SUPPRESS 必须解析 Host `MemoryActionAuthority` schema v2，并精确绑定 subject、whole plan intent、canonical
  operation index、target ID/revision、evidence/span、run/turn、expiry、issuer 与 replay identity。
- 缺 action authority 返回 typed `NEEDS_USER_CONFIRMATION` 且不写认知状态；无效、过期、lookup miss、clock
  rollback 或 nonce replay 返回 typed `REJECTED` 并写 durable rejection audit。成功消费在 mutation transaction
  内以 `(issuer_ref, nonce)` 和 `replay_identity` 双唯一锁定；exact idempotent receipt replay不重复消费。
- CONTEST 不是 action-authority 旁路：target payload、lifecycle、epistemic、verification 与 valid-time 必须完全
  不变，只允许 conflict flag 进入 CONTESTED；否则原子拒绝。
- Procedure observation 只接受 Host `ProcedureObservationAuthorityRef`。Memory exact resolve 后按 logical
  qualification epoch、v2 applicability、hazard、90-day distinct TaskScope/terminal receipt 重算资格；低风险且无
  hazard 的 attributable success 才能按 1/2/3 阶段推进，失败、漂移、高风险与非 attributable observation 不得
  绕过状态机。首次 applicability/hazard 绑定产生新 immutable revision，不原地改写。
- Prospective signal 只接受 Host `ProspectiveSignalAuthorityRef`。Memory 验证 exact trigger、scheduler registration、
  occurrence/receipt、revision/lifecycle 与 outbox 后原子应用 trigger/reschedule/cancel/expire；Memory 只产生 durable
  registration/invalidation command，不拥有 clock，也不执行 action。
- 两类 lifecycle consumer 持久化 full authority consumption、observation/event、decision、typed result、rejection
  与 outbox chain；open/close 全库校验，exact replay 只校当前 consumption chain。cognitive head/revision 额外持久化
  deployment、household、actor 与 scope，跨部署同 actor 的 stolen ref fail closed。
- evidence classification 由 Memory policy、全部 Host `EvidenceItemAuthority` floor、target 与 proposal 做单调
  privacy max / attribute union。classification、action consumption、mutation decision、receipt 与 apply result
  都是不可变 hash-bound 审计链；close→tamper→reopen resolver fail closed。
- backend 与所有 production builders 都没有 fact extractor 参数或 worker 启动路径；旧 regex
  extractor 只存在于 `tests/fixtures`，不进入 source distribution 的生产包或 wheel。Harness 0.7 typed
  analysis 是新的 LLM 边界。
- 兼容 `Fact` 的 `category` 只作标签，`decay_rate` 为显式 neutral 值；category 不再决定保留周期，
  `daily_decay()` 也不再按 category 自动遗忘 Fact。
- public `MemoryManager`、`MemoryBackend` 与 `BaseMemoryBackend` 不存在会话物理删除方法。
- public `MemoryManager`/port 已提供 strict v4 `execute_typed_recall`、result-bound
  `page_typed_recall_result` 与 `authorize_recall_context_use`。Memory-owned v6 ledger 原子保存 request/attempt、
  decision/items、content-bearing result/items/confirmation groups 与 terminal；exact replay 不再查询 candidate，
  reopen 重算 canonical body/hash/cardinality/cross-row binding。
- typed recall 对 Episode/Semantic/Procedure/Prospective 与 Short-Horizon 统一执行 current-head/lifecycle、
  epistemic×verification、half-open validity、suppression、type-specific runtime authority、recipient/purpose/privacy/
  sensitive-attribute disclosure 和 typed selector gate。候选按每 source/type/lane cap 后进入 weighted RRF、严格去重
  与 whole-item budget；cognitive vector 不可用只记录 durable degradation，不伪装 unsupported。
- contested cognitive memory 只以完整、恰好二成员 confirmation group 出现。Harness strict v4 明确要求
  `NEEDS_USER_CONFIRMATION` decision/result 只携带 confirmation groups、不得混入 ordinary selected items；因此同一
  invocation 一旦选择 confirmation group，返回 confirmation-only 是 Host wire invariant。
- durable result 只是审计/分页能力，不自动授权模型 Context。每个 provider attempt 必须经 final current-use fence
  重验 epoch/policy、run/turn/context、current head/group、expiry/classification/disclosure/suppression 与 Procedure/
  Prospective authority，并取得 immutable exact-replay receipt。
- public `MemoryManager.get_twin_graph_view` 是唯一 cognitive graph 入口。它在 trusted clock 下从 canonical current
  cognitive heads/revisions、完整 unresolved conflict groups、evidence lineage 与 relation rows 即时重建 immutable
  display-only projection；不建立 graph/cache authority 表，close→reopen 对同一 canonical state 重建相同 payload hash。
- graph node 提供 memory type、effective status、display confidence 及 basis、hash-only source refs 和 current-head
  correction/forget capability；confidence 是明确的确定性展示 heuristic，不反写 canonical record，也不参与 eligibility、
  recall、ranking、Context 或 action authority。关系只有在同 deployment/household/principal 的两个可见 current endpoint
  都存在时才展示。
- `cognitive_relations` 以数据库 CHECK/FK 区分 `relation_domain=evolution|knowledge`。既有
  `amends/supersedes/contests/relates_to` evolution rows 保持 owner=NULL 与旧 immutable lineage；knowledge rows
  必须由 exact Semantic relation memory revision 拥有。V1 只允许 `applies_to`，source 为 Semantic claim，target 为
  Procedure/Prospective，禁止 self-loop、relation-as-endpoint、跨 principal 或 stale endpoint。
- LLM 只能在 strict v5 `MemoryMutationPlan` 中提出 relation operation；Memory 在一个事务内把 same-plan created refs
  解析为 exact revision，写 canonical relation memory、knowledge derivative、receipt/decision/evidence/audit/root。
  public `get_memory_mutation_receipt_view` 返回当前 principal 拥有的 bounded exact operation bindings，使 clean-wheel
  consumer 无需 private import/SQL 即可核对 relation owner、endpoints、classification、evidence 与 hash。
- relation memory 复用普通 Semantic 的 evidence、classification、epistemic、lifecycle、revision/conflict/suppression。
  ordinary graph 仅在 owner/source/target 全部 current、active、uncontested、未过期、未 suppression 且可展示时发 edge；
  relation memory 自身不成为 node。失效后 edge 立即退出，close/reopen 不复活；evolution edge 语义不变。
- ordinary projection policy 在构图前执行 current-head、active/inferred lifecycle、half-open validity、完整 conflict group
  与 suppression gate。RESTRICTED 记录及 incident edge 完全不可见；SENSITIVE/敏感 attribute 仅显示固定 generic label，
  tooltip/edge/source refs 不携带内容或原始 evidence/span ID。suppressed、superseded、expired 或不完整 conflict group 不得
  通过 label、tooltip、hash-only refs 或 relation 泄露。
- 架构测试固定单向依赖：`core.recall` 不得 import twin projection，`cognitive.twin_builder` 不得 import Host runtime、
  recall candidate、Context fragment、ranking 或 current-use authorization。DTO 没有到 recall/context/action 的转换方法。
- 本 program 不迁移旧内容数据；schema v7 必须 fresh 初始化，旧数据库由 loader 稳定拒绝。
- `build_human_memory_v7` 是 fresh v7 的公开构造入口；`build_human_memory_v6` 仅为同一路径的兼容别名。consumer 可经该
  facade 完成 evidence/conversation admission、mutation、suppression/revoke、typed recall、display graph、
  trace、metrics 与 manifest，不需要导入 `sqlite_v5` 或读取 backend connection。suppression request/decision/
  scope enums、classification policy/effective result 与 stable evidence receipt/record DTO 均从 package root
  导出；`PrivacyClass`/`InformationAttribute` 仍以 Harness root 为唯一来源，exact-wheel consumer 不需 core import。
- sealed audit 只接受 `AuditAccessAuthorityRefV1`。Memory 通过 injected `AuditAccessAuthorityPort` resolve 后
  exact 校验 requester deployment/household/actor/session、target identity、decision/scope/time/hash/replay；旧
  caller-minted decision issuance 永久 fail closed。每次 granted/denied 都是 hash-only immutable event，trace、
  evidence 与 manifest 共用同一 `max_reads` budget。ordinary trace 必须传 target principal；sealed trace/evidence
  必须传 authenticated requester，并对 durable authority ref 重验 requester、实际 target row 与 scope。
- ordinary audit trace 支持 TURN/INVOCATION/DECISION/EVIDENCE/MEMORY。MEMORY selector 附带 hash-only proposal、
  accepted plan、mutation receipt/decision、classification、canonical revision 与 evidence lineage；不暴露内部 ID
  或内容。fixed aggregate metrics 只统计 ordinary-visible invocation/decision/token/cost/latency，无 caller label、
  provider/model/ref/content group，suppressed row 不进入任何字段。
- canonical state manifest 在单一 `BEGIN IMMEDIATE` snapshot 中先执行全库/跨行 validator，再按冻结 coverage
  registry 对全部 required v6 table 生成 principal-scoped root 或显式 derived/global exclusion；随后写独立、绑定
  manifest payload hash 的 access event。历史 audit access ledger 进入当前 snapshot，当前 access event 只进入下次
  snapshot。cursor HMAC key 的 hash 绑定 initialization receipt 并在 reopen 重验。
  manifest 不输出 raw ID、内容或 wall time；它必须与外部保存的旧 hash 比较才能检测具备 DB owner 权限的同步改写，
  不宣称本地自证明真实性。

## 分层

```text
src/simple_harness_memory/
├── core/         # MemoryManager、standalone identity/scope、Agent backend port、durable analysis kernel
├── backends/     # BaseMemoryBackend + Mock + SQLite fresh-v4
├── features/     # Python 内有界候选融合 / reranker / summarizer（无 fact extractor）
├── cognitive/    # 遗忘曲线 / 显著性 / 会话亲和 / 孪生体构建
├── embedders/    # hash 默认 / bge 可选 / cloud
└── world/        # WorldModelPort + temporal/events/geography/knowledge
```

## Agent Memory v1 一等边界

- `MemoryManager` 直接结构满足 Harness `AgentMemoryPort`：`recall_for_turn`、`release_recall`、
  `record_committed_turn`。消费者不构造公开 Adapter，也不维护自动 recall/append/outbox。
- Memory→Harness 是单向 optional `[harness]` extra；包根和 standalone API 不 import Harness，integration
  方法才 lazy import canonical DTO/status/error。缺 extra 稳定报 `harness_integration_extra_required`。
- root `__all__` 已移除旧 `ConversationMemoryAdapter` 与重复 DTO/enums；`core.conversation` 仅作为现有
  standalone canonical/hash 与内部兼容 helper，不是官方组合入口。
- default write scope 是 actor personal；recall 可读取 actor personal + household family。Memory 内容只作为
  带 scope provenance 的数据返回，instruction trust 投影由 Harness S1 负责。

## 当前 Observability 边界

- 基础依赖为 `simple-harness-sdk>=0.7,<0.8`，本地开发仍由 `uv.sources` 指向 sibling checkout。
  Memory 只复用 import-pure `simple_harness.observability` envelope、correlation、runtime 与 sinks；没有
  复制 wire schema，也不让 observability 成为授权、重试、CAS、事务或恢复 authority。
- `MemoryManager` direct init、三个 builders，以及 Mock/SQLite direct backend constructors 接受可选
  `observability_sink` / `correlation`。Noop 默认路径保持旧行为，sink construction/emit/close failure
  只增加共享 runtime counters。
- recall 发射 accepted/started/replayed/degraded/succeeded/released/cleanup/failed；committed turn 在权威
  receipt 可见后发射 applied/replayed/rejected。0.6 production path 不启动 legacy fact worker。
- correlation 未新增 durable 列：recall `query_id`、receipt `turn_id` 与 `session_id` 足以生成 bounded
  opaque identity；Host 显式注入时原样贯穿。
- `diagnostics_snapshot()` 的 schema 固定且有界。Mock 从内存状态聚合；SQLite 仅 GROUP BY/COUNT/MIN
  `state/status/created_at/last_error_code`，100ms query timeout、250ms manager deadline，错误与 close
  返回 degraded/closed schema 而不影响业务。禁止查询 content、result_payload、fact value、embedding、
  文件 path 或 exception repr；recent error codes 最多 20 项，age clamp 为非负值。

## Fresh Human Memory schema v7 与 identity/scope

- Human Memory builder 只接受 fresh v7/checksum；旧版本、缺 meta 或未知 checksum 漂移均
  `MemorySchemaIncompatible`，不执行内容迁移或删除。历史文件名 `schema_v5.py`/`sqlite_v5.py` 仅为内部路径兼容，
  initialization receipt、probe 与 runtime 错误均声明 v7；standalone `MemoryManager.build()` 仍维持独立的 v4
  compatibility store，不能与 Human Memory schema 混读。
- sessions/messages/facts/recall snapshots/receipts/jobs/erasure state 全链路保存
  deployment/household/actor/session/scope_kind/scope_owner；sessions主键为deployment+session，turn receipt
  主键为deployment+turn，允许不同deployment复用外部ID；同一deployment内的household/actor/session
  rebind在recall/read前失败，receipt replay还复核完整owner与scope。
- recall snapshot主键为deployment+context_query_id，允许不同deployment复用外部query ID。
- recall/export/delete/forget 使用 `core.identity.scope_predicate()` 同一 ownership predicate；personal
  owner 必须是 actor，family owner 必须是 household，不同 household 不进入候选集。
- SQLite 使用 WAL、FK、busy timeout、task-owned operation lock 与 `BEGIN IMMEDIATE`；数据库文件继续要求
  regular/no-symlink/current-owner/`0600`。每个数据库另有跨平台 OS writer lease（POSIX `flock`、Windows
  `msvcrt`非阻塞byte-range lock），第二个 live manager fail-closed；
  writer、checkpoint 与 online backup 都经同一 operation lock 串行。

## 有界检索与 embedding generation

- messages/facts 使用 external-content FTS5 与同步 insert/update/delete trigger。查询先绑定
  deployment/household/scope predicate，再 MATCH、稳定排序和 SQL LIMIT；20k/100k scale fixture 均确认
  query plan 使用 FTS virtual-table index。
- vector 只从当前 active generation 读取，候选来自有界 FTS + recent ids；每次 decode 有硬上限。
  active lineage 与当前 embedder 不一致，或 query embedding 失败时，记录稳定降级 code并只走 lexical，
  不混算未知 revision/dimension 的向量。
- lineage 包含 kind/provider/model/revision/dimension/normalization/format fingerprint，并以 canonical SHA-256
  标识。BGE 强制 local-only；production builder 拒绝 hash/mock、隐式模型或缺失资源。
- reindex 建立 building generation，分页持久化 cursor，可从中断点继续；count/dimension/hash/sample 校验全部
  通过后，在一个事务中 retired 旧 active并激活新 generation。故障 generation标记 failed，旧 active不变。

## SQLite 运维

- online backup 由 live manager串行执行，manifest记录 protocol、schema/checksum、SQLite version、active
  generation/lineage、SHA-256 与时间。日志只包含 hash/count/duration/stable code，不含路径或内容。
- restore 仅在 manager关闭后开放；先校验 manifest/hash、WAL残留、integrity/FK/schema/lineage，再写临时库并
  原子替换。任一校验失败保留原库。

## v3 → v4 显式迁移

- runtime loader仍只接受fresh v4；升级入口独立位于`simple_harness_memory.migrations`，不进入
  `AgentMemoryPort`。Memory结构化读取Harness公开manifest，不反向import Harness package。
- backup-first migrator要求closed source及可信一对一identity map；execution manifest与独立non-Harness
  provenance manifest对每个v3 source event恰好覆盖一次。未知版本、重复/缺失归属、identity歧义、digest或
  payload hash漂移均fail closed。
- `KEEP_COMPLETED_PAIR`保留完整user/assistant pair，缺失半边只能由hash-verified canonical turn补齐；
  `SUPPRESS_TENTATIVE`、`SUPPRESS_TERMINAL`、`DEFERRED_TURN`均不复制message/inline embedding/source facts，
  并写`legacy-source:` namespaced hash-only receipt。recall stage丢弃，digital twin只从保留facts重建。
- 临时v4经count/FK/integrity验证后原子替换；swap后故障从已验证backup恢复。公开runtime import只接受KEEP、
  遵守erasure、整manifest事务幂等，Harness outbox重放命中同canonical turn receipt而不重复写pair。

## Durable recall 与 committed turn

- 每个 query id 保存 canonical payload/result hash、identity binding、scope-set hash 与 personal erasure
  write fence；同 id 异 query/identity 冲突，同 id 同输入重放冻结 payload。release 校验 query/result hash，
  并有界清理超过 retention horizon 的 released stage。
- recall 先在短事务读取 erasure epoch/fence，再做embedding与候选ranking；embedding timeout/corruption或
  后续查询故障都通过task-local fence传入稳定Harness error。删除可以安全跨越embedding边界，旧fence的
  committed turn仍会被拒绝。
- `record_committed_turn` 在一个事务中写 turn receipt、user row和assistant row；任一步失败全部回滚。
  production builder 不创建 legacy fact job。幂等键为deployment+turn；同deployment下同turn+hash且完整identity/scope相同返回
  `already_applied`，payload或owner/scope不同返回conflict。
- fence 过期返回 hash-only `rejected_erased`。无 fence时，仅可信 `turn_started_at` 严格晚于最新
  `erased_at` 且不超当前可信时钟才可绑定当前 epoch；早于、相等或时钟回退均 fail closed。

## Legacy Fact compatibility storage

- 旧 v4 Fact/job 表只保留为 dormant compatibility storage、只读 diagnostics 与 erasure cleanup；
  production Mock/SQLite 不暴露 recover/claim/apply/fail mutation seam。
- regex extractor 与 legacy worker 都已完全移到 `tests/fixtures`，不打入 wheel/sdist 的 production package。
- 显式 `remember_fact()` 仍可写兼容 Fact；category 仅作标签，写入 neutral `decay_rate=0.0`，普通
  `daily_decay()` 不再扫描、衰减或自动遗忘 Fact。

## Privacy lifecycle

- `export_principal` 是 versioned、有界、分页输出，默认不包含 raw embedding。
- `delete_scope/delete_principal` 先推进 erasure epoch，再级联 messages/facts/recall stages/job payload；
  turn receipt 与 hash-only tombstone保留以拦截旧 outbox/job。
- `forget_fact` 保存 deterministic provenance tombstone，并删除该 personal fact 及 family projections；
  `share_fact` 是Harness-free顶层公共能力，以source provenance+household生成deterministic projection id，
  重复调用幂等且只保留一行；跨actor/household抛`MemoryOwnershipConflict`，family row以`projection_of`
  保留来源。forget source级联删除projection并留source tombstone，applied/late job replay不会复活。
- `remember_fact/read_fact` 是Harness-free principal显式写读能力，返回exact fact ID；完整identity、content、
  salience/pinned/tier进入canonical replay hash，forget保留receipt且不复活。
- principal `forget_fact`将reason/source_event_id持久绑定到deployment/household/actor/fact/hash；同动作重放
  返回原bool，不同动作对已遗忘fact记录false no-op，receipt不含content。
- Agent Memory structured events只记录 opaque principal、ID/hash、count/bytes/stable code；不记录 content、
  token、embedding、数据库路径或 exception repr。legacy standalone日志中的 user/session/source id也已哈希。

## 当前明确限制 / 后续 Slice

- simple_harness 已完成 exact-wheel 产品接线与真实 macOS UI；该结论不外推到其他消费者。
- AIPhone、K6/AgentOS、NovelTagSystem 未修改、未集成、未测试；前两者仅为 Agent Memory v1 接口就绪。

## Release candidate identity

- 唯一版本事实源为`src/simple_harness_memory/__init__.py`，当前 source candidate 为0.6.0；wheel metadata、README、公开API
  snapshot、changelog与candidate `BUILD_INFO.txt`必须一致。
- base wheel metadata 直接要求 `simple-harness-sdk>=0.7,<0.8`，`[harness]` 保持同一范围；当前 clean
  resolver gate 只接受 exact Harness 0.7 artifact，`<0.7` 与 `>=0.8` 必须拒绝。
- CI只build一次candidate wheel/sdist并记录source commit与SHA-256；Python 3.11/3.12/3.13及Windows x64、
  macOS ARM64、Linux ARM64 downstream只下载/验证同一 Memory artifact 与同一 pinned Harness 0.7
  artifact，不允许重建。0.6 当前只生成候选制品，不调用旧 release workflow，也不 tag/push/publish。

### 历史发布事实（不代表 0.6 current contract）

- Memory tag `v0.4.0` 指向 `3d4247b` 的冻结 candidate；2026-08-23 source、`main` 与 tag 已推送；
  当时的 wheel/sdist 已正式发布到 GitHub Release，并通过公开稳定 URL 下载回验。
- 0.5.0 已发布：tag 指向 `9c92ede`，wheel SHA-256 为
  `c274fa6b2db538c29897f684b3f2f85775cb4b3a6870018e83792ff90b51ea46`；公开下载回验通过。
  base 与 `[harness]` metadata 均要求 `simple-harness-sdk>=0.4,<0.5`。
- Short-Horizon registration 消费 Harness conversation evidence v3：无授权 registration/raw evidence 仍永久保存，
  但只有 Host 唯一 RFC6901 `public_text` pointer/hash、item authority、effective privacy、information attributes 与
  classification authority 全部 exact 的 item 才能进入派生索引；Memory 不扫描 payload 的其他字符串。
- 最近 10 个完整 causal groups 保持直接上下文，较旧且不超过五天的完整 groups 才生成 disposable chunk；chunk
  privacy 取最严格值、attributes/ref 做单调并集。到期与 suppression 只删除/排除 chunk/vector/FTS，registration 与
  evidence 永不删除。
- `recall_short_horizon` 不接受 generation/cache/query vector。SQLite repository 从 durable active generation/vector
  rows 重建私有 exact cache；principal/disclosure/time/privacy/classification/suppression 先形成完整 universe，FTS、
  entity-time 与 vector 在同一 universe 独立排序后融合。cold/stale/deadline 只降级到该 universe 的 FTS/entity-time，
  不读取 stale vectors；gate/lane/selection/generation/manifest/degradation 均写 privacy-safe immutable audit。
- 0.5.1 已发布：仅扩大 Harness metadata 范围并增加真实 wheel 矩阵，不改变 Memory 业务模块行为。
  released Harness 0.4.0 与 Harness 0.5.0 candidate/release 是两个强制 clean-venv 格；H0.5 wheel 未就绪时
  必须保持 pending，两个格均通过前不得发布。H0.4.0 released wheel 本地 clean-venv 格已通过，CI 使用
  固定 SHA-256 重跑同一 oracle；当前 H0.5.0 candidate commit `ac2e2add` / wheel `d5ac2976…` 已通过同一
  clean-venv aggregate 并保存 privacy-safe superseding receipt。旧 `e44d619` / `7d70b9fa…` receipt 已
  superseded；Harness v0.5.0 正式 wheel 与 accepted candidate 字节一致，H0.4/H0.5 release/download-back
  aggregate 均已通过并保存 formal receipt。
- Memory annotated tag `v0.5.1` 解引用到 `da85fa2`；正式 wheel `314c1b89…`、sdist `63b01464…` 均与
  clean-source 第二次构建逐字节一致，并通过公开 URL 下载回验。GitHub Release 为 Latest、非 Draft、
  非 Prerelease。

## 验证状态

- Human Memory S3 Task 1/2/3 candidate：Task 1/2 保持 Harness `baaefac2` Mutation/Action authority 闭环；
  Task 3 使用 exact Harness authority HEAD `a553cf3`，Memory commits `31ffb15` + `3e45194`。Memory 全仓
  `844 passed, 9 skipped`，Ruff 全绿，mypy `57 source files` 全绿，`git diff --check` 通过。
  独立 mutation/classification/action-authority closure audit 为 P0/P1/P2=0；focused `105 passed`，覆盖 missing/
  invalid/expired/lookup-miss/clock-rollback/replay、CONTEST 旁路、late fault 原子回滚、principal attribution 与
  receipt/ledger/decision corruption close→tamper→reopen。Task 3 focused `30 passed`，覆盖 Procedure qualification
  epoch/rolling window/first bind/CAS/fault/tamper 与 Prospective ACK/trigger/invalidation/expire/stale/replay/outbox/
  audit-chain；该证据只关闭 S3 Task 1—3，不代表 S3 整体完成。

- Human Memory S3 Task 4：短期对话索引已完成 remediation 并经五轮独立复审 P0/P1/P2=0。它以 Host v3
  pointer-only registration 构建五天、最近十组之外的可重建 projection；repository 私有 generation/cache；FTS、
  entity-time、vector 在同一完整资格 universe 上融合。入口起算的 absolute deadline 覆盖 audit/write 排队；每次
  timeout 都具有关联的 `recall_started` / `recall_terminal` 审计，close 会拒绝新调用、等待已接纳调用并 drain 审计。
  相关 tamper、immediate close/reopen、close-vs-recall、concurrent queue deadline 均 fail-closed。focused `17 passed`，
  全仓 `864 passed, 8 skipped`。真实 200-query semantic quality corpus 仍为 `NOT_RUN/BLOCKED`；Typed RecallPlan、
  graph 与 Host/UI 仍未完成。

- Human Memory S3 Task 6：display-only twin graph 的 builder、SQLite on-demand projection、public
  `MemoryManager`/port 与 import-isolation guard 已闭合。focused DTO/policy/correction/forget/conflict/reopen/public-API
  `11 passed`；全仓 `1006 passed, 8 skipped`，Ruff `src tests`、mypy `58 source files` 与 `git diff --check` 全绿。
  该证据证明 Memory library projection，不代表尚未实现的 Host/UI 接线或交互验收。

- Human Memory S3 Task 7：fresh-v6 public builder/Manager facade、external authority-ref sealed access、
  MEMORY hash-only lineage trace、ordinary-visible fixed metrics 与 sealed canonical state manifest 已闭合。
  access resolver miss、requester/target identity drift、ref/body/replay/time/max_reads、suppression、cursor/reopen、
  manifest coverage/independent root rebuild/tamper、no-mutation invocation 与 public consumer 均由仓内测试覆盖。
  Task 7 focused `12 passed`；public-surface focused `15 passed`；全仓 `1037 passed, 8 skipped`，Ruff `src tests`、
  mypy `58 source files` 与 `git diff --check` 全绿。

- 0.6.0 Task 6 source audit：冻结 Harness 0.7 下全仓 `493 passed, 8 skipped`；Ruff、项目 mypy
  `97 source files`、3 个发布脚本 strict mypy 与 REUSE 全绿。非最终 dirty-tree wheel/sdist 通过 Twine，
  public/artifact/clean-consumer gate `17 passed`；wheel 明确不含 `core/fact_jobs.py`、legacy worker 或 backend
  recover/claim/apply/fail seam，并消费 Harness wheel
  `b9421ddf…6037d7b`；这组 Memory bytes 只证明 source contract，不具 promotion authority。只有从审阅后的
  clean commit 重建并复验的 bytes 才能成为最终 candidate。候选制品未 tag/push/publish。

- 以下为 0.5 历史 observability/release 证据，不代表 0.6 fact-worker production path：privacy canary、sink failure isolation、public/direct composition、recall/
  receipt/fact-job 状态矩阵、snapshot schema/bounds/SQL denylist、close/reopen recovery correlation 均通过；
  `tests/integration/test_observability.py` 13 passed。Harness candidate `bc6ae8d` 声明 0.4.0，Memory installed
  metadata 确认 base/extra 均解析 `simple-harness-sdk>=0.4,<0.5`。
- 0.5.0 release-identity gate：源码 full `213 passed, 7 skipped`，Ruff 全绿，mypy 对 src/tests
  `83 source files` 全绿；本地临时 0.5.0 wheel/sdist 通过 Twine，联合 Harness 0.4 exact-wheel
  artifact suite `10 passed`；发布制品与下载回验字节一致。

- S3 targeted：Agent direct port、Mock/SQLite、atomic fault、fact recovery、identity rebind、scope matrix、
  export/delete/forget、erasure replay、日志 canary均通过。
- S4 targeted：20k/100k FTS query plan与有界 recall、generation restart/switch/failure、production embedder、
  second-writer reject、checkpoint、backup/restore/corruption preserve均通过。
- S3 migration targeted：四类完整覆盖、canonical pair补齐、derived cascade、non-Harness provenance、
  identity/digest tamper、三阶段fault rollback及Harness公开manifest/runtime replay均通过。
- S5 Memory candidate：0.4.0 public snapshot、base import blocker、真实`[harness]` resolver、错误版本拒绝、
  installed-wheel strict typing、candidate metadata/SHA与跨Python/平台消费门禁已定义。
- 最终本仓默认 full：`200 passed, 7 skipped`；正式 candidate gate：`205 passed, 2 skipped`；Ruff 与 mypy 全绿。
- Memory `3d4247b` / 0.4.0 wheel `bfcd2506…` 由 simple_harness `4e797ccd` exact installed-origin
  消费；产品 Gate r4 的 21/21 required 场景达到 `READY_FOR_AUDIT`。SH-M5 跨进程新 Session 召回，
  SH-M6 recall timeout 与 record transient/startup recovery 均由真实 UI + DeepSeek 验证。

2026-09-05：独立0.6.8 source-only admission源码完成36专项、721含专项相邻、4 schema检查；
公开独立receipt/零analysis job、双模式冲突、registration/history union与fresh7.2边界已实现。
Dirac已审oracle，源码复审/wheel/Host11组组合待验，不合main，不标S3/program或selected-only完成。
[本轮事实与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-source-only-admission/RESULTS.md)。

2026-09-05：独立0.6.9 A+B源码候选实现官方非空7.0/7.1保留式升级和actual-selected短来源批量读口；
WAL-only/升级COMMIT前后真进程退出、备份重试、旧任务续跑和history过滤已有限定源码证据。
固定2542736源码已独立scoped ACCEPT；BUSY窄修16项通过，installed wheel待验，不改冻结068、不合main，不标S3/program或Host native完成。
[069验证与剩余边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-069-existing-data-selected-sources/RESULTS.md)。

2026-09-05：授权分配独立0.6.10 privacy successor，root snapshot4项通过；双offline build与
installed public/native-copy gates正在执行，冻结069不变，不标Hostlate-enqueue/native完成。

2026-09-05：独立retry-current-attempt后继修复真实firstfail→secondclaim→expiry错误回收旧batch
P1；限定107PASS/1项冻结0610已有schema-probe拒绝测试失败单列保留，含8项新current/multi-member/
concurrent-owner/真实COMMIT前后进程退出控制。原069反例DB保留，publicgraph相邻源码绿。
待独立源码review，不改版本/DDL/冻结0610制品、不合main；随后才组合已审OA1统一候选。
[当前源码事实与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-retry-current-attempt/RESULTS.md)。

2026-09-05：retry-current-attempt0947c011限定源码已Dirac scoped ACCEPT；原红/DB与继承
测试错误均保留。OA1 af49另树也已源码ACCEPT，后续统一组合候选与installed验证，当前无新wheel。
2026-09-05：独立operation-audit后继树开始OA1；同步typed rejection carrier真实公共调用/
独立Hoststore reopen/进程退出/外部cancel共12项限定源码检查通过，既有拒绝回归保留。
ledger分页读口尚未实现、源审待验，不标OA1或全operation审计完成；未分配新版本，
此源码树不能冒充冻结069 wheel，不改Host/native。
[当前范围与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-operation-audit/RESULTS.md)。

2026-09-05：privacy0.6.10独立产物冻结后恢复OA1树；read_operation_audit WIP真实job effect
误报已由canonical plan重建/同cut receipt校验修复，11项限定source控制PASS（1.03s），
含no_mutation与written独立业务断言、旧cursor/预算/过期/删除检测。整体reader仍未审结，
混合typed/short与missing-event/完整boundedwork验证待完成，不标OA1/full审计完成，未分配候选。
[当前进展](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-operation-audit/RESULTS.md)。

2026-09-05：OA1 bounded reader完整源码已实现并提交独立审查：真实mixed九family、缺event/
crosslink、retry/reclaim、stable cursor/reopen和四种scan exhaustion；限定117PASS/2项明确
排除的冻结069既有schema-probe测试失败，mypy3source/ruff通过。两项原失败和独立retry
producer旧batch误回收P1反例均保留，不标全套绿。preDB Host持久化/未覆盖调用仍缺，
all_operations_recorded=false；未分配版本/build/合main，privacy0.6.10冻结不变。
[源码事实与原红证据](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-operation-audit/RESULTS.md)。

2026-09-05：Dirac完整OA1审查发现唯一新增P1（sole handoff缺失但独立attempt仍在）已按
独立attempt prefix/cut修复，31项受影响reader控制PASS/3.30s；其余完整审查无第二新增P0/P1，
最终复核待验。原红保留，未出候选/合main，all_operations_recorded仍false。

2026-09-05：OA1 af49f2a1完整bounded源码已独立scoped ACCEPT，包含sole-handoff原probe修后
真实复验。源码gate完成；候选组合/installed/Host持久化与全operation覆盖另验，未合main。

2026-09-05：独立0.6.11组合固定privacy02f4020+已审OA1af49f2a+retry0947c01；
source d520765 / wheeld290cbfc，双offline构建一致，owner新隔离installed公共7阶段PASS，
Memory72+Harness151 source/wheel/install字节及213origins/16deps/pipcheck/15旧json通过。
限定组合116源码测试PASS，原继承失败保留；Dirac installed复核待验，不合main/不改Host。
Hostcarrier持久化仍缺，all_operations_recorded=false，不标全program/native完成。
[候选身份、命令与边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-operation-audit/CANDIDATE-0.6.11.md)。

2026-09-05：Memory0.6.11 d520765/wheeld290cbfc的组合交集及artifact/exactinstalled/
publicconsumer证据已Dirac独立限定ACCEPT，无新增P0/P1。SDK候选gate完成；Hostcarrier、
全operation/native及独立Harness successor门仍待主线，不作替代，不push/tag/release。

2026-09-05：独立credential-public-identifiers后继修复仅将五个已证明公开完整词元
从凭据prefix-pattern误报中排除；保留所有其它legacy delimiter/无delimiter、秘密字段、
Bearer/AKIA/privatekey与S1验证。160项限定源测试通过，真实旧native三库副本的
Host factory history page由0610红变源码绿且reopen通过，原archive及10文件hash保持。
源码review/0.6.12 installed尚待，不改0610/0611或主树，不标native UI/program完成。
[事实及命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-credential-public-identifiers/RESULTS.md)。
