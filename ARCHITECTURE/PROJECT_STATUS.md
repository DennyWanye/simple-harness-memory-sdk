最后更新：2026-09-07。0.6.19 clean源e27003c一次离线制品和Host H079/M619/S0313安装组合1PASS0.86s通过，版本元数据3控通过，旧106导出全保留+12；生产安装origin经实际vendor安装纠正后验证通过。全部资源组清空，原生/240质量仍未验。[候选与制品](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-07。共同Procedure/current-input组合已在Host80764c13/Memorya15c7be通过1个新增真实公共控制并独审接受，source overlay非installed；0.6.19版本与118项公共导出快照准备，旧M618 106项全保留，版本检查/制品待验。[候选边界](../plans/2026-09-07-procedure-current-input/CANDIDATE.md)。

最后更新：2026-09-07。Procedure discovery源f03dab0的新6项有效控制已获独审限定接受（首批有效4+实际遗忘负控2；旧误绿撤回）。文档后继d142d3a并入共同候选，current-input源码a28a857与Draft混合批量检查新控制仍待验；无新wheel/安装/原生完成声明。

最后更新：2026-09-06。主候选源码组合：Procedure f03dab0（含已审恢复）与current-input e500556合入独立后继分支，保留两组公共入口和HistoryProcedureDraftBinding检查。当前只是组合源码，未构建新wheel、未切Host pin；Procedure discovery新控/组合审查仍待完成，旧M618身份不改。[本轮输入接口](CURRENT_INPUT.md)。

最后更新：2026-09-06。Procedure恢复源码Host ea63ddc6/c76da29c、Memory978ae99：新增12唯一控制分批通过（SDK3，Host9），原四夹具失败保留且只重试四红；明确54增量attempt journal、过期重开/lostACK、同epoch旧revision、同Scope拒绝、真实drift物理0、高risk及timer兼容。全部资源组清空，临时vendor恢复；待新叶独审和统一制品，未合主/非native。首次草稿发现、失败归因、TC-HM04仍未完成。[结果与边界](../plans/2026-09-06-procedure-observation-prepare/RECOVERY.md)。

# PROJECT STATUS — simple-harness-memory-sdk

> 2026-09-07 转主干开发：main 已并入 `feat/human-memory-procedure-current-input-successor`（0.6.19 源）。下方 09-06 两路状态段为合并时的并集，各自描述当时状态，不互相覆盖。

最后更新：2026-09-06。Procedure后继公开prepare/read target/record的实际operation observation六项新控通过；f82c2b8仅Procedure复用source-only S1完整持久校验，Host三真实Scope路由/文件effects/完整group→公共观察由原红转绿，累计成功1/2/3与重放已验证。新四项跨源边界控未跑，完整TC-HM04、独审、installed/native未闭合。主整合Hegel e500556后统一版本，不独立build，不改M618制品；F01延期。[源码与证据边界](../plans/2026-09-06-procedure-observation-prepare/CONTRACT.md)。

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

> 最后更新：2026-09-05



## 2026-09-05 duplicate-source forget 共享源码候选（源码独立 scoped ACCEPT）

在独立069后继树实现真实 Host origin/cut 两阶段准备、当前 canonical MEMORY 全 revision
来源拒绝与共享 suppression resolver。实际 builder支持 history_source_authority，公开能力
MemoryManager.history_source_enforcement_version=1；不以此替代 exact后继artifact身份。
本机206项限定源码测试通过（15.14s），含22项新数据库控制、配置新authority后的23项原
攻击/zeroSQL控制、capability及相邻回归；ruff/mypy4源通过。原56c6bf7 no-/text误拒P1已
由2b2fa47修复；Dirac已对固定53099e7完整enforcement源码 scoped ACCEPT，未见剩余当前P0/P1。
Dirac要求的short补充控制已扩展原有用例并单跑1PASS/0.45s：不同实际来源、旧typed
新attempt拒绝/原receipt重放，以及cut后同文atomic来源越过recent10后重新可用；不累加为207项。
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

## 2026-09-05 当前 Host 运行时的全量回归

Host Python 3.12 + exact Harness 0.7.2 + Memory 0.6.3 源码：1123 passed / 9 skipped，
唯一红为旧 schema-cutover 测试仍要求版本字面量 0.6.2；已将该断言固定为当前 0.6.3，
未改变 v7.1 DDL checksum、schema 或旧库迁移断言。该文件重测 3 passed（`memory-schema-version-retest.log`）；
其余未变测试不重复消耗。Memory 本仓旧 .venv 仍装历史 Harness，首次 collection 错误不作产品失败。

## 2026-09-05 本机合入与 0.6.3 candidate

SDK 源码修复已提交 `2b8428465cbd41032ba024a0b7199183161f5ecd`（candidate 0.7.2）；主执行者报告真实 runtime route→WAITING→授权重启新增 2 用例先红后绿、独立 review 4 passed。Host 正在 revendor/安装，尚未完成新候选身份核验及 A14/S8；本地 S1 FAIL/S8 FLAKY 保留。

- IR-02/IR-03 独立 correctness/minimality review 接受，无新增 P0/P1/P2；复审 24 条通过，
  原 Host 复现分别得到两条 accepted/两条 head/两次调用与合法 no-mutation accepted。
- 修复已由独立分支合入 main（`d70d98c`）；source candidate 升为 0.6.3，以新版本保留
  0.6.2 wheel 身份，公共 API 与 schema v7.1 不变。0.6.3 快照逐字段对照 0.6.2，旧快照保留。
- Host `26b50ee8` 已接入 source `2f3d73814fe6a884e0458d87567b918c5863033e` 的双次一致 wheel：
  `6b20ae5bff6c3ecfe1108ccaff9bb41c4dc6a3b98bb754dac2c418673ab77c78`；版本/来源/hash 通过，Host 51、安装版 SDK 16 条通过。
- 新 wheel 原生 UI/gpt-5.5 root `c2af5326a8d05023868f7994f1a4e0be` 非空回复成功；r5 S8 保留 fail/pass，状态 FLAKY。
- A14 root `142bdb3b-9026-5264-b244-69e94bf0e388` 已真实写 README，却在 task_scope_update 获批后触发
  Harness initial/current route P1；terminal FAILED、closure pending、accepted/head=0，第二 root 未跑。
- 用户已批准 [A17 限定 SDK 修复](../plans/2026-08-29-human-memory-digital-twin/increments/2026-09-02-s5b-effect-closure-memory/SDK-ROUTE-UNFREEZE-PROPOSAL.md)
  与另线 S3 契约修订。P1/S1 尚未闭合；其余冻结项不变，未宣布 S5b/program complete。
- Host 本地证据根 `.local-test-evidence/2026-09-05/human-memory-resume/`：UI 在 `verification/r5-local/artifacts/s8-native-ui/`；
  S1 在 `verification/r5-local/artifacts/s1-route-failure/`（stderr SHA `5c479175a5c4…`，完整 hash 见 metadata）；
  7 项 metadata attach 保留原 FAIL/FLAKY。详见 [RESUME](../plans/2026-08-29-human-memory-digital-twin/RESUME-2026-09-05.md)。
- 本节更新下方“待 review/合并/exact-wheel”的历史交接状态；其余 required 验收与机器门仍未闭合。

## 2026-09-05 S5b IR-02 / IR-03：phase-3 源码修复交接

- 执行方式：集中串行完成两个同文件正确性修复。独立 worktree
  `/Users/denny/projects/simple-harness-memory-sdk-analysis-recovery`，分支
  `feature/human-memory-analysis-recovery`，基于 `main@78d61926e15a8b0b8f49971472e2f5ef2b25f60a`。
- IR-02：领取时等待同 principal 未物化的 batch；原 plan/base_revision/evidence/result hash 不改，
  CAS/target 冲突校验保留。故障恢复 + 新一轮事实最终 2 accepted / 2 heads，Provider 调用恰好 2 次。
- IR-03：合法可选 `closure_reason` 被接受、原值/hash 持久化，零认知写入；不可用响应保留
  `analysis_response_unusable` 且 rejected。首次应用与 audit_pending 恢复共用同一 shape 校验。
- 验证范围：Memory 源码自动化 + Host 生产组件的确定性 adapter 复现；尚无本修复的独立 review、
  真实 Provider/UI/生产或 exact-wheel 验收。Host IR-01 的 `f0133ac8` 另线完成，不包含在本 diff。
- 未改 Host、冻结 oracle/acceptance、原始 plan、版本/schema 或候选 pin；未 build wheel/push/tag/合并 main。
  此处只交接两个修复，不宣布 S5b/program complete，也不代替主执行者的 full-audit/机器门。

验证命令从本 worktree 执行，统一
`PYTHONPATH="$PWD/src" /Users/denny/projects/simple_harness/backend/.venv/bin/python -m pytest`：

- 基线：`-q tests/integration/test_durable_memory_jobs_v5.py tests/integration/test_memory_061_core.py tests/integration/test_memory_062_analysis_evidence_refs.py`
  → 91 passed。
- 新回归：`-q tests/integration/test_analysis_recovery_correctness.py` → 12 passed；修复前首批回归
  4 failed / 7 passed，明确得到 `rejected,accepted` 与合法 no-mutation rejected。
- 全量/静态检查与证据索引在下方记录。Ruff/mypy 使用 Memory 原 checkout 的 `.venv/bin`；mypy 指定
  `--python-executable /Users/denny/projects/simple_harness/backend/.venv/bin/python`。
- 原始 `revision.py` / `probe.py` 的可执行副本仅存 ignored 证据目录，调整源码 import 与成功断言，
  增加恢复后的下一 tick；两者 PASS。另以无 proposal 的非空响应验证 Host 告警 + Memory rejected，PASS。
- 剩余工作仅就本修复而言：主执行者独立 correctness/minimality review 后决定合入及候选重新验证。

本地证据目录（Git ignored）：`.local-test-evidence/2026-09-05/s5b-analysis-recovery/`。
日志、生产复现脚本与数据库只留本机；下方只保存结论和 SHA-256。

全量源码命令：`-q --basetemp=.local-test-evidence/2026-09-05/s5b-analysis-recovery/final-test-data`
→ **1124 passed / 9 skipped**。`ruff check src tests` 与 `mypy src tests` 均非全绿：
前者 2 项、后者 26 项，已用 `git archive 78d6192` 的只读副本按相同环境复核，无新增 diagnostic。
本次新测试 Ruff 通过、修改代码/测试无新增类型错误，`git diff --check` 通过。

| 证据相对文件 | 结果 | SHA-256 |
|---|---|---|
| `baseline.log` | 91 passed | `86fe655e010ac5264f6a8a24bf83a7d7583820090e08f62fecef21b2eb81a653` |
| `regression-red.log` | 4 failed / 7 passed，修复前 | `b390b73ee8c6892244d2f773e9e7bb5b89542616c243fcdb22719184b829b739` |
| `final-regressions.log` | 12 passed | `616390f827a1a32cdcbaf81c768b2e29aafd024fa5266260a1b2ff858afad9a0` |
| `final-full.log` | 1124 passed / 9 skipped | `86791de26c706053c2584fbbfe6739c570ee8028ac7325c889f9373029fc1ec1` |
| `host-revision.log` | 2 accepted / 2 heads / calls=2 | `0886d9c3144bf3bb22ff3957b1ba611cf18e395e47fe7a6d7af89f1a9350f4a1` |
| `host-probe.log` | accepted / heads=0 / calls=1 | `560caab634ed4995224b47efac240ed61aac2aa8c971acca7b52c43f6f675196` |
| `host-unusable.log` | rejected / heads=0 / calls=1；原因保留 | `e8dced11616209e96775f00afda0c396b8b54505982d4d5b235375a2b51666db` |
| `ruff.log` | 2 项基线问题，输出与 baseline 相同 | `925659d9ff539e52e3283cba1d3217e7708daf709c23bb9796332ac1cc07ad0b` |
| `mypy.log` | 26 项基线问题 / 3 文件，diagnostics 与 baseline 相同 | `4f852c67c88ffadcb8184219c485dcad898467bbf3f3426c30818d11e303e46d` |

## 2026-09-04 S5b：effect gate / 语义收口 / 记忆分析（验收中）

- **本仓在 S5b Task 7 无代码改动**：`src/` 最后一次变更是 0.6.2 cutover（`06ba9d4`，已入
  CHANGELOG，schema 保持 v7.1）。Task 7 的 9 处缺陷修复全部落在 Host 侧前台执行链，
  因此本仓**不新增 CHANGELOG 版本条目**——没有可发布的代码变化就不编造版本。
- **Host 侧里程碑**：human-memory 前台任务执行链首次在**生产入口**跑通
  （控制通道 `queue.enqueue` → `_drive_claimed` → SDK ReActLoop → 终态提交同事务写
  Memory ingestion outbox → analysis → 认知记忆物化）。该链此前从未在生产上跑通，
  因为 `_drive_claimed` 在 pytest 里零覆盖，测试基座手工推进状态机把生产装配缺口全补上了。
- **对本仓消费面的实证**：`memory_ingestion_outbox` + `memory_ingestion_evidence_links`
  在终态同事务各落 1 行，`cognitive_memory_heads` 物化 1 条 episode——0.6.2 的 analysis
  lineage 与 apply head 契约在真实 provider 下按预期工作。
- **S5a 遗留的两条上游义务仍未闭环**：属主注册 API（本仓）、SDK assistant `tool_calls`
  作为一等 transcript 字段（`simple-harness-sdk` 仓，冻结中）。均顺延。
- **移交下一切（S6）**：该链没有任何桌面 UI 入口，前端零调用 `queue.enqueue`。

## 2026-09-02 S5a：0.6 消费面定稿 + Host 生产接入

- **终态（2026-09-02）：S5a 增量 SHIPPABLE**，机器门 receipt
  `b5d416e372e3d2b8c3bd6ac86428941ce896b4123e291e12003697cee9118dac`（run `r3-s5a`）。
  7/7 required 场景 root PASS，独立 full-audit verdict=PASS。本仓全量 1071 passed 无回归；
  本轮本仓无代码改动（0.6.0 消费面已定稿），两个缺陷修复均落在 Host 侧。
- **真实桌面 UI 验收对本仓的一条上游义务**：Host 在全新安装场景发现，v7 store 的读路径
  （`read_occurrence_inbox`）对尚未注册的本地属主 fail-closed 抛
  `short_horizon_principal_rejected`，而属主只在首次 typed recall / mutation 时才自注册——
  全新安装的第一次 reconcile 因此必然失败。Host 侧已按"未注册属主的收件箱受 principals 外键
  强制不可能有条目"做了收窄的 fail-open 兜底，但**正解在本仓**：应提供正式的属主注册 API
  （或让读路径对未注册属主返回空页而非冲突），届时 Host 侧兜底分支移除。列 S5b 前置义务。
- **另一条 S5b 上游义务（SDK 仓，非本仓）**：`simple-harness-sdk` 的冻结契约禁止 provider
  assistant 消息把私有 metadata 写进 durable Context，导致 Host 无法跨轮携带 `tool_calls`，
  OpenAI 兼容端点因此拒绝 continuation 请求。建议上游把 assistant 的 `tool_calls` 视为
  一等公共 transcript 字段在 Context 重建请求时回挂。

- Host `feat/human-memory-s5a-context-route` 完成 S5a：v7 认知库首次生产组合（HumanMemoryV7Runtime），
  typed recall + short-horizon 双 lane 消费，occurrence inbox reconcile 成为 no_recall 硬门。
- 本仓交付：inbox/outbox 只读投影（含 suppressed 标志）、jobs 包根导出、v7 embedder 生产守卫、
  uv.sources 修复；1071 测试全绿；wheel 62a3f63c…（Host vendor exact pin + candidate manifest）。
- S5b 待办：registration outbox 消费/settled 状态机（presented cursor 由 Host v45 持有）、
  PROJECT_EFFECT root 签发接线（Host 侧）、WeMM 快照上传 COS。

## Human Memory Program

| Slice | 状态 | 当前生产事实 |
|---|---|---|
| S5b AC2 / IR-02、IR-03 | phase-3 源码修复已验证，待独立复审 | 按 principal 等待未物化 analysis；固定 plan/evidence/result 不变；合法 no-mutation 理由保留且零认知写入；不代表 S5b/program 完成 |
| V0 / S1 / S2 | 完成 | fresh v7 evidence、suppression、durable analysis 与 cognitive mutation authority |
| S3 Task 1–3 | 完成 | 四类 cognitive records、Procedure/Prospective lifecycle 与 Host authority consumption |
| S3 Task 4 | 完成 | 五天 Short-Horizon disposable projection；真实 semantic quality corpus 仍为外部 gate |
| S3 Task 5 | 完成 | strict typed recall、durable replay ledger、page-in 与 final current-use fence |
| S3 Task 6 | SDK 完成 | Harness v5 `applies_to` relation plan、Memory v7 canonical owner/derivative 原子写、公开 receipt view 与 display-only graph gate 已通过 exact-wheel 2-node/1-edge、suppression/reopen 0-edge 及 40-case integrity matrix |
| S3 Task 7 | 完成 | ref-authorized sealed audit、MEMORY trace、fixed metrics、canonical manifest、public v6 facade |
| Host / UI 接线 | 未开始 | Memory library API ready；不外推为产品或真人交互验收 |
| 0.6 candidate packaging | 待最终门禁 | relation SDK slice 已闭合；Host durable pre-admission audit 与真实 LLM quality 仍为明确外部门，未 tag、push、publish |

## Task 7 安全边界

- authenticated requester 与 target subject identity 分离并 exact 绑定；caller 自行构造 sealed decision 无效。
- 普通 metrics/trace 先执行 suppression policy；sealed read 共用 durable `max_reads` 预算并记录 hash-only access event。
- manifest coverage registry 覆盖全部 required v6 table；当前 access event 在 snapshot 后写入，历史 ledger 在后续 snapshot 可验证。
- manifest 是可比较的完整性快照，不替代外部保存的可信历史 hash，也不声称抵抗 DB owner 同步改写。

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
