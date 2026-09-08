最后更新：2026-09-07。0.6.19 clean源e27003c一次离线制品和Host H079/M619/S0313安装组合1PASS0.86s通过，版本元数据3控通过，旧106导出全保留+12；生产安装origin经实际vendor安装纠正后验证通过。全部资源组清空，原生/240质量仍未验。[候选与制品](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-07。共同Procedure/current-input组合已在Host80764c13/Memorya15c7be通过1个新增真实公共控制并独审接受，source overlay非installed；0.6.19版本与118项公共导出快照准备，旧M618 106项全保留，版本检查/制品待验。[候选边界](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-06。主候选源码组合：Procedure f03dab0（含已审恢复）与current-input e500556合入独立后继分支，保留两组公共入口和HistoryProcedureDraftBinding检查。当前只是组合源码，未构建新wheel、未切Host pin；Procedure discovery新控/组合审查仍待完成，旧M618身份不改。[本轮输入接口](CURRENT_INPUT.md)。

# ARCHITECTURE 索引

> 2026-09-07 转主干开发：main 已并入 `feat/human-memory-procedure-current-input-successor`（0.6.19 源）。下方 09-06 两路状态段为合并时的并集，各自描述当时状态，不互相覆盖。

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
- **阈值**：SDK 冻结常量 `COGNITIVE_VECTOR_MIN_SCORE = 0.45`（`features/cognitive_vector.py`），低于阈值不进候选；取值理由：双语句向量模型同义改写通常 ≥0.6、无关句通常 ≤0.3，取中点偏严以护住 C07 零召回子集，由 Host C07 回归校准。
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


## 2026-09-06 空assistant短期完整组源码候选

最后更新：2026-09-06。自有feat/short-empty-assistant/base6361edca，版本保持WIP0.6.14；仅允许合法ASSISTANT空字符串并保留完整ordinal/工具parent来源，两条投影路径排除全空角色标签伪命中。USER空/空白、NUL、UTF-8字节、identifier/hash及完整组门保持。9项公开API契约已写，待Dirac源码复核后145同锁原红/绿及必要邻居，未测试、未build/install/分配615/合主。Host真实SDK11turn工具组由主后继接线验证，不冒称Memory fixture为Host E2E。
[最小接口、源位置、测试边界与指纹](../plans/2026-09-06-short-empty-assistant/CONTRACT.md)。


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

本目录是 simple-harness-memory-sdk 的当前架构事实源。main 当前为 **0.6.3 source candidate**
新增 fresh `human-memory-v1` schema v7 的 immutable evidence、append-only suppression/audit、durable analysis
四阶段 authority、四类认知记录的 strict mutation/classification/action-authority 事务底座，以及 strict v4 typed
RecallPlan 执行与最终使用 authority，以及严格 display-only 的 Digital Twin graph projection，并精确依赖
Harness `>=0.7,<0.8`。0.6 不再默认实例化 regex fact
extractor，不导出物理会话删除 API；旧 v4 Message/Fact 类型和私有 storage seam 仅作兼容读及
回归 fixture，不是新 Human Memory 的 authority。候选版本尚未 tag/push/publish。

2026-09-05：隔离0.6.3基线 history visibility 源码候选新增 public batch 来源可见性检查，
修复 memory_id 遗忘后原 USER 历史复活；94项限定 source 测试通过，独立 review 接受。
未改版本/build/pin/合 main，Host接线及 native遗忘验证仍待主线完成；
[交付边界与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/RESULTS.md)。

2026-09-05：0.6.6组合候选在独立分支保留history+clock+rejection，130项限定源码测试通过；
source9ec5943/wheel381d8543已通过新venv publicconsumer与全包字节核验，Host接线另验，冻结旧candidate不变。
[当前候选](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-history-visibility/CANDIDATE-0.6.6.md)。

2026-09-05：后继独立short exact history源码修复28专项+93相邻测试通过，独立review接受。
新增三元carrier复用当前batch suppression/expiry/disclosure；版本尚未分配，未build/合main/接Host，
封存0.6.6 wheel不含此增量。[当前独立源码交付](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/RESULTS.md)。

2026-09-05：主分配0.6.7给已审short增量，独立候选根快照和消费者源码检查通过，wheel验证待完成。
[本轮候选](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-short-history-visibility/CANDIDATE-0.6.7.md)，不覆盖封存0.6.6或修改Host环境。

| 文档 | 范围 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 包结构、分层、本地后端与召回/认知/世界对象的生产边界 |

Human Memory Program 的 SDK 范围当前闭合到 S3 Task 7：长期认知与五天 Short-Horizon 统一进入 typed recall eligibility、
disclosure、lane-cap/weighted-RRF、去重和 provider-visible budget；durable request/attempt/decision/result/terminal
ledger 支持 exact replay、reopen hash rebuild、atomic confirmation、result-bound page-in 与 final current-use fence；
Digital Twin graph 从 canonical current cognitive records/relation rows 按普通展示 policy 即时重建，且 API/依赖
方向禁止它进入 recall、ranking、Context 或动作 authority。Harness v5 + Memory v7 已从 exact-wheel package root
原子创建一等 `applies_to` relation memory，并通过 owner/endpoint 状态门投影知识边。resolver-backed sealed audit、MEMORY lineage trace、
ordinary-visible metrics 与 canonical state manifest 均通过 public v6 Manager facade 提供。Host/UI 接线仍未实现。

<!-- last-updated: 2026-09-05 -->

2026-09-05：S3 隔离 0.6.5 candidate 已通过源码全量与独立 installed-wheel 核验，尚未合入 main 或 Host pin；401-cell、S5b 及 program 状态见 PROJECT_STATUS 最新节。

2026-09-05：独立0.6.8 source-only admission源码完成36专项、721含专项相邻、4 schema检查；
公开独立receipt/零analysis job、双模式冲突、registration/history union与fresh7.2边界已实现。
Dirac已审oracle，源码复审/wheel/Host11组组合待验，不合main，不标S3/program或selected-only完成。
[本轮事实与命令](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-source-only-admission/RESULTS.md)。

2026-09-05：独立0.6.9 A+B源码候选实现官方非空7.0/7.1保留式升级和actual-selected短来源批量读口；
WAL-only/升级COMMIT前后真进程退出、备份重试、旧任务续跑和history过滤已有限定源码证据。
固定2542736源码已独立scoped ACCEPT；BUSY窄修16项通过，installed wheel待验，不改冻结068、不合main，不标S3/program或Host native完成。
[069验证与剩余边界](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-069-existing-data-selected-sources/RESULTS.md)。

2026-09-05：独立duplicate-source forget共享源码候选206项限定测试通过，原short用例补强单跑通过；
Dirac对53099e7完整源码 scoped ACCEPT。后继artifact、Hostlegacy settle及native仍待验，不标旧v1cut或program完成。
[当前事实](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-05-duplicate-source-forget/ENFORCEMENT.md)。

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
