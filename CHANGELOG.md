# Changelog

## [0.6.27] - 2026-09-08（世代重建把嵌入移出写锁；召回取锁受 deadline 约束）

- 基于 0.6.26。HM-TO-A6 turn 22 现场实证（诊断见 Host `simple_harness/plans/2026-09-08-hm-to-a6/DIAG-RECALL-TIMEOUT.md`）：`context_route(memory_standalone)` 连续 5 次 `context_route_recall_timeout`，Run 以 `react_repeated_tool_exceeded` 死亡。`typed_recall_terminals` 五条终态全是 `terminal_kind='deadline_exceeded'`、`candidate_query_started=0` —— **一条候选都没扫过**。离线重放证明 DB 侧只花 24–31 ms（占 1000 ms 预算的 2–3%）。
- **根因（本次修复）**：`rebuild_short_horizon_generation` 与 `rebuild_cognitive_vector_generation` 在 `_write_lock` 内 `await embedder.embed_batch(...)`。真实 WeMM 每条 200 ms、无批处理覆写（基类是串行 N 次调用），6 条 chunk 合计 45.7 s，而 Host 维护 tick 的超时只有 5 s：世代永远激活不了、chunk manifest 永远对不上，下一 tick 从头再来，形成活锁——每 ~7.7 s 就有一段 ≥5 s 的写锁占用（占空比约 65%）。前台 typed recall 两处取同一把写锁又都没有 deadline，拿到锁的第一件事就是 `raise TimeoutError`。这与本 SDK 自己的决策文档 `DECISION-2026-09-07-cognitive-vector-lane.md` §4.1「不在 mutation 写锁内嵌入」、§4.2「查询向量在取 `_write_lock` 之前算」、§4.4「冷态只退化不失败」三条不变量全部相反。
- **三段式世代重建**（短时域与认知世代同型）：① 持写锁读行 + 算 manifest hash + 判 replay/空集（认知侧连公开 payload 文本的渲染也在锁内完成）→ ② **释放写锁**做 `embed_batch` → ③ 重新取写锁，对 manifest hash 做乐观 CAS：未变才写向量表、原子激活、旧世代 retire、落审计；变了就本次不激活。嵌入期间新出现的同 manifest active 世代按 replay 返回，不会重复激活。
- **CAS 落空的语义**：`ShortHorizonGenerationBuildResult` / `CognitiveVectorGenerationBuildResult` 追加 `cas_miss: bool = False`，`audit_id` 放宽为 `str | None`。落空时返回 `(generation_id=None, activated=False, replayed=False, audit_id=None, cas_miss=True)` 并记一条 `*.generation.cas_miss` 结构化日志；**不写审计行**——两张审计表的 `event_kind` 只有 `generation_activated`（`cognitive_vector_audit.generation_state` 更是 `CHECK IN ('active','empty')`），把"没有激活"记成一次激活会污染防篡改的激活记录，也会逼出一次无谓的 DDL 变更。下一 tick 以新清单重建即可。
- **幂等/失败语义不变**：generation id 形状、replay 判据、空集分支、`COGNITIVE_TEXT_FORMAT_VERSION` 并入 manifest、0.6.24 的 `state='failed'` + `last_error_code` 行（嵌入在锁外失败时改为重新取锁后落库）与 `CognitiveVectorGenerationFailed(code=...)` 全部逐字保留。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.27.json`。
- **召回取锁受 deadline 约束**：新增 `_write_lock_before(deadline, *, stage=None)`（`asyncio.wait_for(lock.acquire(), remaining)`）。向量 lane 的取锁额外预留 `COGNITIVE_VECTOR_LOCK_RESERVE_S = 0.200`（实测 DB 侧全流程 24–31 ms，即 6–8 倍余量），等锁超时 **退化** 为 `cognitive_vector_deadline` 并把余下预算留给词面 lane 与终态写入，符合「冷态只退化不失败」；查询嵌入沿用 `COGNITIVE_VECTOR_AUDIT_RESERVE_S = 0.050`。`_admit_typed_recall_request` 保持硬失败语义（等锁时幂等记录尚未落库），但抛新的 `TypedRecallDeadlineExceeded(stage='admit_write_lock')`——`TimeoutError` 子类、`str()` 仍是 `DEADLINE_EXCEEDED`，Host 到 `context_route_recall_timeout` 的映射逐字不变，只是多了阶段名与 pre-candidate rejection receipt。`collected_epoch` 读取与短时域候选段的取锁一并纳入同一预算。
- 测试：新增 `tests/integration/test_generation_rebuild_lock_isolation.py` 7 项（慢嵌入器 300 ms/条 × 7 条、维护 tick 超时 1 s、前台预算 1000 ms 的活锁复现——0.6.26 上该用例以 `TimeoutError: DEADLINE_EXCEEDED` 失败，0.6.27 上召回在 1 s 内正常返回；认知与短时域两侧的 CAS 落空不激活、不写审计、旧 active 世代原样保留；写锁被短暂占用时向量 lane 退化而词面照常；写锁被整段预算占住时 admit 以命名阶段快速失败且不留幂等记录；嵌入失败仍落 failed 行；两段预留是冻结常量）。全量 `tests/` 失败集合与 main 基线逐条相同（63 项既有环境失败），1558 → 1565 passed。仅本地候选，未发布、未构建制品、Host 未 pin。
- **Host 侧仍需配套**（本次不改 SDK 无法覆盖的部分）：`WeMMEmbedder` 缺 `embed_batch` 覆写（单条 30k 字符耗时 23.9 s）、短时域 chunk `public_text` 无长度上限、`PrimaryShortIndexWorker` 超时后无退避/断路、`deadline_ms=1000` 偏紧、一次 recall 超时不应杀死整个 Run。

## [0.6.26] - 2026-09-08（Prospective 触发条件的自然语言渲染；词面与向量同源）

- 基于 0.6.25。语料 run-01f C04 实证：跑道修好 `prospective_scheduler_registrations.state='accepted'`（trigger_hash 一致）之后，「周五验样结果如何？我还留了什么周一要做的提醒？」对种子提醒（`action_text='索取修正版'`、`trigger_json={"timezone":"Asia/Shanghai","trigger_at":1788742800.0,"trigger_kind":"time"}`、lifecycle `pending`、已有向量）仍然零召回。根因：prospective 的公开 payload 只有 `action` 与 `trigger`，trigger 里是 epoch 数字、时区名与 `time` 枚举，中文查询与之既无词面重叠也无向量邻近，`full_text`/`vector`/`entity`/`task_scope`/`temporal` 五条 lane 全空，候选在 `_collect_typed_recall_candidates` 的 `if not lane_values: continue` 处被丢弃（不是资格门拒绝，terminal 记 `no_eligible_memory`）。
- **触发渲染**：`features/cognitive_vector.py` 新增 `prospective_trigger_text()`——只用公开字段，按 trigger 的 timezone 把 `trigger_at` 渲染为「YYYY-MM-DD 周X HH:MM」（中文星期）+ trigger_kind 中文（time→定时、event→事件）+ 固定词「提醒 待办」。未知 kind、非 Mapping、缺字段返回空串；`trigger_at` 非有限数或超范围时只保留 kind 词；未知时区名退回 UTC。纯函数、不读库、无本地时区依赖，跨进程逐字确定。
- **两条 lane 同源**：`cognitive_text_supplement()` 同时供给 `cognitive_vector_text('prospective', …)`（`action` 仍在最前，渲染紧随其后，原始 `trigger` 字段照旧在末尾）与 typed recall / confirmation 的词面门文本（`canonical_json(payload)` + 渲染）。公开 payload 形状不变——渲染只进入检索文本，返回给 Host 的仍是原样 `{action, trigger}`，`memory.typed-recall` 的 hash 域零变化。
- **世代与 manifest**：`_cognitive_vector_manifest_hash` 由 head 清单改为 `{text_format_version, heads}`，并入 `COGNITIVE_TEXT_FORMAT_VERSION = 2`。渲染格式一变，旧 active 世代的 `content_hash` 立刻不等于当前 manifest：`_prepare_cognitive_vector_lane` 判 `cognitive_vector_stale` 并退化（词面照常），下一次 `rebuild_cognitive_vector_generation()` 整代重建、旧世代 retire，绝不会继续使用按旧文本嵌入的向量。升级到 0.6.26 的库第一次重建即整代刷新。
- **不改**：资格门（lifecycle/epistemic、prospective 注册与信号权威、抑制、disclosure、时间窗、procedure 指纹门）、`COGNITIVE_VECTOR_MIN_SCORE=0.45`、lane 排序/预算/RRF、其余四类记忆的向量文本逐字不变。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.26.json`。
- 测试：新增 `tests/integration/test_typed_recall_prospective_trigger.py` 7 项（渲染确定性与三时区/七天中文星期；event 类与畸形 trigger 的负控；向量文本字段顺序与其余类型零变化；C04-01 复现——修前词面 0、修后 `full_text` 命中且无关查询仍 NO_RECALL；只开 vector 模式经渲染进入 `vector` lane 且修前余弦低于阈值；格式版本令旧世代 stale 并整代重建；渲染不落公开 payload/typed 行）。仅本地候选，未发布。

## [0.6.25] - 2026-09-07（Procedure 发现面对已采用流程可见；中文词项匹配）

- 基于 0.6.24。按 `simple_harness/plans/2026-09-07-native-main-journey/DECISION-PROCEDURE-USE-CHAIN.md` §3.1 的最小方案。原生 r8/r9 实证：用户以"以后就按这两步做"采用的流程被编译为 ACTIVE + `unbound:procedure-applicability:v2`，`discover_procedure_drafts` 只看 draft/eligible，typed recall 又要求指纹已绑定且等于当前 Run 指纹，于是模型没有任何入口拿到 memory_id/revision 去 `procedure_use`。r24/r25 另一层原因（`procedure_discover` 只做整串子串，中文查询必须逐字出现在 name/steps）在此一并消除。
- **发现面白名单**：`core/procedure_discovery.py` 新增 `DISCOVERABLE_LIFECYCLE_STATES = ("draft", "eligible_for_activation", "active", "reinforced")`，`ProcedureDraftCandidate.__post_init__` 与 `backends/procedure_discovery.read_candidate` 同用（与 `read_procedure_use_target` 四态一致）；revised/inapplicable/superseded/forgotten 仍不可见。资格门（uncontested、非 restricted、有效期、disclosure、抑制、血缘 history_visible、规范 payload 校验）与自证披露门不变；被遗忘的已采用流程同样从发现面消失。
- **词项匹配**：`backends/procedure_discovery.match_score` 用 `features.lexical.typed_recall_query_terms(query)`（与 typed recall/0.6.20 CJK 修复同源：`\w` 词 + CJK 二字组合）对 name + applicability + steps 的公开文本计数命中，整串子串命中额外 +1；命中数 0 不返回。单页内按命中数降序、再按扫描序（memory_id 升序）稳定排序；`next_after` 仍是扫描序的 memory_id，分页不重不漏；页预算/`omitted_oversize`/`limit≤8`/空查询拒绝（`procedure_draft_bounds_invalid`）不变。
- **不改**：向量世代与 manifest（草稿仍不入向量）、typed recall 的 applicability 指纹门（UNBOUND 仍 NO_RECALL，写成回归断言）、`procedure_use`/观察/恢复语义、候选 DTO 字段与 `memory.procedure.draft-candidate.v1` hash 域（Host `HistoryProcedureDraftBinding` 零改动）。无 DDL 变化（7.4 checksum 不变）、根导出零增减；快照 `public-api-0.6.25.json`。
- 测试：`tests/integration/test_procedure_discovery.py` 新增 4 项（ACTIVE-unbound 可发现且 DRAFT 仍可发现、遗忘后不可见；中文词项对 name/applicability/steps 命中、零命中、双向按命中数排序；limit=1 游标分页不重不漏；同库 typed recall 对 UNBOUND 流程仍 NO_RECALL）。Host 需同步改 `procedure_discover` 工具描述（不再写 draft/eligible + substring）与 PERSONA 一句"先 discover 再 procedure_use"。仅本地候选，未发布。

## [0.6.24] - 2026-09-07（认知向量世代跳过 relation 记忆；构建失败落 failed 行）

- 基于 0.6.23。原生真实运行（r8）复现：分析任务落库一个含 semantic relation（`applies_to`）的 v6 提案后，Host 短索引 worker 每 tick 记录 `memory_short_index_unavailable type=MemoryCorruptionError`，`cognitive_vector_generations` 始终为空。根因：relation 记忆本身是 `cognitive_memory_heads` 里 `memory_type=semantic` 的 head，但它是图谱的边（HM-AC-6），没有 `semantic_claims` 行；`_cognitive_vector_head_rows_unlocked` 未排除它，`_cognitive_public_payload_unlocked` 对它抛 `typed recall payload missing`，且抛出发生在任何世代行写入之前。短时域 projection/generation 不受影响。
- 修复：`_cognitive_vector_head_rows_unlocked` 新增 `_cognitive_semantic_head_is_relation` 判定（与 typed recall 类型权限门同一口径，content 不可解析 fail closed），relation head 不进世代、不进 manifest（stale 判定同样排除）、`vector_count` 只计非 relation head；typed recall 的 vector lane 与 confirmation 门本就在类型权限门后才比对，relation 记忆永不被打分或作为 item/成员返回（新增回归钉死）。
- 构建失败契约：`rebuild_cognitive_vector_generation()` 的任何失败先在独立事务落一行 `state='failed'` + `last_error_code`（`cognitive_vector_head_invalid` / `cognitive_vector_embedding_failed` / `cognitive_vector_generation_write_failed`，常量在 `features/cognitive_vector.py`），再抛 `core.errors.CognitiveVectorGenerationFailed`（`code` 为同一失败码、`generation_id` 为该 failed 行；RuntimeError 子类，Host 现有 `except RuntimeError` 不需改）。故障消失后下一 tick 正常构建，failed 行保留为历史。
- 无 DDL 变化（7.4 checksum 不变）、根导出零增减。新增 4 项测试（`test_cognitive_vector_generation.py` 3 项：relation 跳过 + worker 顺序、重开、三阶段失败落 failed 行；`test_typed_recall_cognitive_vector.py` 1 项：relation 不进 vector lane/confirmation）。公共 API 快照 `public-api-0.6.24.json`。仅本地候选，未发布。

## [0.6.23] - 2026-09-07（长期认知记忆向量通道）

- 基于 0.6.22。按 `plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-07-cognitive-vector-lane.md` 方案 A：typed recall 为长期认知记忆新增真正的 `vector` lane（RRF 权重沿用预留的 0.40）。写入侧为"世代重建"：新公共方法 `MemoryManager.rebuild_cognitive_vector_generation()` 复用 `short_horizon_embedder`（不加新 builder kwarg），对全部可召回 head 的**公开 payload** 文本（`features/cognitive_vector.py::cognitive_vector_text`）批量嵌入，manifest hash(memory_id, revision, content_hash) 相同则 replay，否则写新世代并原子激活、旧世代 retire、审计 `cognitive_vector_audit`、推进 recall authority；嵌入永不在 mutation 写锁内发生。
- 召回侧：查询向量在取 `_write_lock` 之前、带 audit 预留的 deadline 内计算；余弦只对**已通过全部资格门**（状态/类型权限/血缘/抑制/scope/entity/时间/disclosure）的 (memory_id, revision) 计算，被抑制/遗忘的记忆永不进入向量比对；阈值为 SDK 冻结常量 `COGNITIVE_VECTOR_MIN_SCORE = 0.45`。confirmation 门同步接受 vector 命中。资格门顺序、`typed_recall_query_terms` 与既有四条 lane 的计分不变。
- 退化码语义变更：`cognitive_vector_unavailable` 仅表示 backend 无 embedder；新增 `cognitive_vector_no_generation` / `cognitive_vector_stale` / `cognitive_vector_deadline`。全部持久化到 `typed_recall_terminals.degradation_codes_json`；命中时 generation id 的 opaque hash 写入 terminal_json `cognitive_vector.used_generation_id_hash`。
- DDL 附加式 7.4（`backends/schema_v7_4.py`）：`cognitive_vector_generations`、`cognitive_vectors`、`cognitive_vector_audit`；7.3 DDL/checksum 冻结。7.3 库（fresh 或带 7.2→7.3 marker）打开即前向追加三表并写 `schema_meta[cognitive_vector_forward_v1]`，原初始化 receipt/meta/业务列不改写；未知 catalog/checksum fail-closed。
- 测试：新增 `test_cognitive_vector_generation.py`、`test_typed_recall_cognitive_vector.py`、`test_memory_0623_schema_cutover.py`；改写 `test_typed_recall_v6.py::test_cognitive_vector_degradation_is_durable_not_unsupported`。公共 API 快照 `public-api-0.6.23.json` 根导出零增减。仅本地候选，未发布。Host 需同步改 `retrieval_modes` 恒含 VECTOR 与 worker 追加一次 `rebuild_cognitive_vector_generation()`。

## [0.6.22] - 2026-09-07（遗忘只针对记忆：补齐 duplicate-source 路径）

- 基于 0.6.21。`_resolve_suppression_snapshot_unlocked` 仅对记忆候选调用 `duplicate_source_matches`：MEMORY 范围指令的重复来源别名仍可拒绝重学的记忆，但不再拒绝来源对话证据（原生 r6 发现 0.6.21 仍经此路径隐藏会话）。cut/proof 机制不变。
- duplicate-source 三个测试文件按新口径改写（19+ 项），全量 63 failed / 1510 passed 与基线一致。仅本地候选，未发布。

## [0.6.21] - 2026-09-07（遗忘只针对记忆候选）

- 基于 0.6.20。用户 09-07 产品决定：忘记一条认知记忆只抑制该记忆（typed recall、图谱、工作记忆、记忆读取），**不再**隐藏其来源对话证据。`_resolve_suppression_snapshot_unlocked` 对 evidence 候选不再纳入反向 MEMORY 目标；EVIDENCE/SUBJECT/ENTITY 指令行为不变，撤销与原始字节保留不变（源码与测试改写随 `4bd11cc` 提交）。
- 11 项既有测试按新口径改写（含 3 项同因回归），新增 `test_manager_memory_forget_keeps_evidence_visible_and_evidence_forget_hides_it`。无 DDL、无公共 DTO/hash 域变化。仅本地候选，未发布。

## [0.6.20] - 2026-09-07（typed recall 中文词法门修复候选）

- 基于 0.6.19 源 e27003c6。typed recall 候选门与 confirmation 门的查询切词改用 `features.lexical.typed_recall_query_terms`：保留原 `\w` 词项，新增 CJK 二字组合。此前 `\w` 已匹配汉字，中文查询只按标点断成整句并要求在 payload 中逐字出现，导致中文长期记忆在无 entity/scope/时间约束时全部被 `recall_no_eligible_memory` 丢弃（Host 语料 C01-10 真实运行复现，spike 验证修复后召回命中）。
- 无 DDL、无公共 DTO/hash 域变化；向量通道 `cognitive_vector_unavailable` 与短期 `[\w]+` 切词未改。新增 3 项中文正/负控测试。仅本地候选，未发布。

## [0.6.19] - 2026-09-07（Procedure 与本轮输入共同候选）

- 基于实际0.6.18源码d8d80d5c，整合已审Procedure目标/观察prepare恢复、DRAFT发现及精确历史binding；新增操作观察供Host独立审计。
- 本轮完整USER输入公开检查保留完整principal、真实Host来源与用途；当前项例外不传播到其它历史或Procedure草稿。混合批次请求hash接受exact草稿binding，原域与旧项hash不变。
- 保留0.6.18全部106根导出，新增12个公共导出；Memory无新DDL。旧0.6.18制品不改写，安装及原生验收独立记录。仅本地候选，未发布。

## [0.6.13] - 2026-09-06（独立 typed-short 来源候选）

- 新增 public resolve_typed_short_horizon_sources，以 durable selected typed item 四元组
  在同一当前可见性事务中返回完整短期来源 refs；认知/非 selected 不给 refs。
- 保留旧 standalone source port、DTO wire、hash、DDL 和冻结0612；新 request/binding hash 域分离。
- 精确校验当前 owner，复用 suppression/disclosure/expiry/registration lineage；不代替 Host 最终出站校验。
- cd1ea1a source 已独立限定 ACCEPT；仅本地后继候选，不 push/tag/release。

## [0.6.12] - 2026-09-05（独立凭据误报窄修候选）

- 保留已审0.6.11 privacy/OA1/retry能力，仅修正五个已确证公开完整词元被凭据前缀扫描误报。
- 原有凭据格式、无分隔符拒绝、阈值、其它扫描及S1/subject/suppression门保持；不改公共API/DDL/旧receipt或archive。
- 160项限定source及真实旧native三库副本Host factory page红绿已通过，固定ce1a85b独立scoped ACCEPT；本候选installed/native另验，不push/tag/release。

## [0.6.10] - 2026-09-05（独立 duplicate-source privacy 候选）

- 保留冻结069能力，新增已独立审的 Host source origin/cut 公共契约与跨 history/ordinary/typed/short/mutation/background 共享当前 suppression 检查。
- memory-only forget 覆盖同 subject 的完整 USER /text 精确重复及真实来源血缘；新 atomic source 依原 cut 判定，旧 v1 无 cut/legacy 晚入队明确不可验证。
- 不改 schema、旧快照、既有 hash 或冻结069轮子；仅隔离候选，不 push/tag/native。Host late-enqueue 收尾及原生闭环独立验证。

## [0.6.7] - 2026-09-05（独立 short 候选）

- 保留0.6.6 history/clock/rejection，新增已独立审查的 exact standalone short history carrier。
- 同一 public history batch 核验实际 audit 选中、当前来源/subject/disclosure/expiry 及反向 suppression。
- 原0.6.6及旧快照/wheel保持冻结；本版本仅候选，未push/tag/release，Host接线另验。

## [0.6.6] - 2026-09-05（独立组合候选）

- 合并0.6.3基线的 history visibility 完整修复、0.6.4公开可信clock及0.6.5限定拒绝见证；普通历史可见性以当前SDK反向suppression和source状态为准。
- 新增五项history根导出与0.6.6 API快照；保留所有旧快照、schema v7.1、typed v4 hash和原数值阈值。
- 不替换冻结0.6.3/0.6.5 artifact，不合main/tag/push；本候选的源码、wheel与最小installed验证另见history increment候选记录。

## [0.6.5] - 2026-09-05（S3 候选访问前拒绝见证）

- `execute_typed_recall` 的类型、ownership、narrowing 和精确幂等冲突保留原异常，附加不可变 `TypedRecallRejectionV1`，绑定本次 invocation 与可合法计算的 request/context/plan hash。逻辑零表示未进入候选访问，不是 SQL 条数，也不声称没有 admission 写入。
- 数据库故障、损坏、取消、timeout 和候选访问后的异常不获得此见证；没有新增账本、授权 token 或全局 last-error 槽。
- Manager/backend 增加严格 `harness_protocol=4` 入口，未知版本在 backend 操作前拒绝；默认调用保留旧 backend 参数集合、原 v4 hash 和 schema v7.1。
- 新增 30 条专项回归，全量 1157 passed / 9 skipped，独立 source review ACCEPT；本分支仍为 S3 隔离候选，不替换 Host S5b 的 0.6.3。401-cell 与 program verdict 按实际验收独立记录。

## [0.6.4] - 2026-09-05（S3 公开时间依赖）

- `build_human_memory_v7` 增加可选可信构造依赖 `clock`，复用既有 backend 时钟，让 recall、page-in 和 current-use 使用同一时间源；默认仍为系统时间。请求不能通过回填时间绕过分页过期。
- 真实 SQLite 回归覆盖固定时间、关闭重开、过期拒绝、默认时钟及非法构造输入；独立 review ACCEPT。schema v7.1、根导出及旧候选快照保持。
- 本分支为 S3 隔离候选；不替换 Host S5b 已安装的 0.6.3，不代表 401-cell 或 program gate 已通过。

## [0.6.3] - 2026-09-05（S5b 恢复正确性）

- 同 principal 的后续 analysis 等待已领取批次完成物化，保留固定 plan/base_revision/evidence/hash，避免故障恢复丢失旧批次事实。
- 合法 no_mutation 保留可选 closure_reason 并以同一规则恢复；不可用响应仍被拒绝，零认知写入。
- schema v7.1 与 0.6.2 公共 API 完全一致；新增 0.6.3 快照保留旧版本谱系。独立复审接受，候选构建与 Host 验收另行记录。

## [0.6.2] - 2026-09-03（S5b Task 5：Memory 0.6.1 余项）

- **缺陷修复**（Host Task 4 真实/确定性车道发现）：多 evidence 的 analysis batch 中，只引用
  **非首条** evidence 的 operation 被 `decision_evidence_refs_ordinal_invalid` 拒绝。根因：
  `prepare_analysis_application` COMMIT 后构造 decision 时，把按 batch ordinal 过滤出的
  `plan.evidence_refs` 子集（如 ordinal=2）直接交给 `DecisionLedgerEntry`，而其 `_refs` 契约要求
  ordinal 恰为 1..n；异常在事务提交之后抛出，batch 卡在 `audit_pending`。修法：decision 的
  evidence_refs 按 batch 顺序过滤后重编 ordinal 为 1..n；成员集合仍由 prepare 内
  `plan.evidence_refs == request.ordered_evidence_refs` 校验，引用成员集合外 evidence 的 plan
  继续 `analysis_validator_rejected`。oracle：
  `tests/integration/test_memory_062_analysis_evidence_refs.py`。
- cutover：无 DDL 变化，schema 保持 **v7.1**（`SCHEMA_VERSION_LABEL="7.1"`，checksum 与 0.6.1
  相同并在 `tests/integration/test_memory_062_schema_cutover.py` 钉死）；0.6.1 写出的库打开不
  迁移、receipt/meta 稳定；0.6.0 写出的库（真实 v7.0 DDL）打开仍按 0.6.1 规则一次前向加列到 v7.1。
- 公共 API 快照 `tests/artifact/public-api-0.6.2.json`：根导出与 0.6.1 完全一致（不增不减）；
  `register_principal_owner`、`supported_filter_policies`、`analysis_lineage`、
  `current_analysis_apply_head()` 可达性由快照测试只读核对。
- 版本 `0.6.2`（`pyproject` 动态取 `src/simple_harness_memory/__init__.py::__version__`）；候选
  wheel `uv build --no-sources` 两次 clean build 字节一致：见 `docs/build-and-release.md`
  「0.6.2 candidate manifest」。

## [0.6.1] - 2026-09-02（S5b Task 4a：Memory 0.6.1 核心）

依据 `plans/2026-08-29-human-memory-digital-twin/increments/2026-09-02-s5b-effect-closure-memory/design-freeze.md` §8。

- `MemoryManager.build_human_memory_v7(..., supported_filter_policies=None)` 透传 backend；默认仍只认
  `credential-filter/v1`（§8.1）。
- 多 operation analysis finalize 收敛：`_read_decisions(operation_order=...)` 按 accepted plan 的
  operations 规范序比较，`decision_id`（hash）序不再作比较基准；≥2 op plan 不再卡死 audit_pending（§8.2）。
- accepted 且 `outcome=mutate` 的 analysis plan 在 `prepare_analysis_application` 同一事务内、以仓储
  单次签发的内核能力物化（复用 `apply_memory_mutation_plan` 的 compile/apply 内核）：写 cognitive
  revisions/heads、`memory_mutation_receipts`、`memory.cognitive.committed` 与 prospective registration
  outbox；`no_mutation` 不物化；replay 幂等；物化失败 SAVEPOINT 回退、plan 转 rejected
  （`analysis_materialization_rejected`）；`analysis_apply_heads` 与 `cognitive_apply_heads` 对齐到 max 后
  同步推进到 base+1。前置：backend 绑定 `evidence_authority` 与 `classification_policy`，否则保持 0.6.0
  审计-only；evidence authority 在写锁内被调用，不得回调 Memory backend 加锁读（§8.3）。
- `MemoryManager.register_principal_owner(principal, scope) -> PrincipalRegistrationReceipt`：幂等登记
  属主 deployment/household（修正 ingest 占位形状）；登记后 outbox/inbox/短时域读取不再
  `short_horizon_principal_rejected`（§8.4）。
- `AnalysisLineage(provider_id, model_id, model_config_hash)`（包根导出）；
  `ingest_committed_evidence(envelope, receipt, *, analysis_lineage=None)` 逐 evidence 持久到
  `evidence_envelopes.analysis_lineage_json`；回放给出不同血缘或事后补写 →
  `evidence_lineage_replay_conflict`。`claim_analysis_batch` 从成员派生 request 的
  provider/model/config_hash，成员不一致（含部分缺失）→ `analysis_batch_lineage_differs`，全部缺失
  回落 `MemoryJobWorkerConfig`（15 字段仍必填）（§8.5）。
- `AnalysisBatchClaim.analysis_apply_head: int`（仓储必填 kw_only）：claim 时只读
  max(analysis head, cognitive head)，缺省 1；`DurableMemoryJobRunner` 在调用 executor 期间经
  contextvar 暴露，Host 用 `core.jobs.current_analysis_apply_head()` 填 `plan.base_revision`（§8.6）。
- schema v7 → **v7.1**（`SCHEMA_MINOR_VERSION=1`、`SCHEMA_VERSION_LABEL="7.1"`；主版本 7 与
  receipt CHECK 不变，小版本由 DDL checksum 编码）。规则：0.6.0 写出的库（meta checksum ==
  `SCHEMA_CHECKSUM_V7_0` 且无新列）打开时在一个事务内 `ALTER TABLE` 加列并把
  `initialization_receipts`/`schema_meta` 的 checksum 与 receipt_hash 重算为 v7.1 值，之后按 v7.1
  checksum 校验；新库直接按 v7.1 建；未知 checksum 仍 fail-closed。
- 公共 API 快照 `tests/artifact/public-api-0.6.1.json`：0.6.0 根导出全部保留，仅新增
  `AnalysisLineage`、`PrincipalRegistrationReceipt`。
- 候选 wheel `uv build --no-sources` 两次 clean build 字节一致：见 `docs/build-and-release.md`
  「0.6.1 candidate manifest」。

## 0.6.0（S5a 消费面定稿，2026-09-02）

- 包根导出 jobs 消费符号（`DurableMemoryJobRunner`/`MemoryJobWorkerConfig`/`WorkerRunOutcome`）。
- 新增只读 occurrence inbox / outbox 投影（`OccurrenceInboxEntryV1/PageV1`、`OutboxEntryV1/PageV1`）：
  `(occurred_at, event_id)` 排序键在形内、当前 head lifecycle_state、suppressed 标志（memory-scope
  suppression 指令联查）、principal fail-closed；Host reconcile 门的冻结 consumer contract。
- `build_human_memory_v7` 拒绝 hash/mock embedder（`allow_development_embedder` 显式豁免）。
- 修复 `[tool.uv.sources]` 路径；候选 wheel 双 clean build 字节一致
  sha256=62a3f63cadd7796b1e86e57a9dce2bffc773b3da2ef3e78ba5002fea50f822ff。

## [0.6.0] - 2026-08-30

### Human Memory foundation

- Added the fresh `human-memory-v1` evidence, audit, suppression and durable analysis repositories.
- Removed the regex fact extractor implementation from the production package, every production builder
  argument that could enable it, the legacy worker implementation, and Mock/SQLite recover/claim/apply/fail
  job mutation seams. Regression-only extractor/worker fixtures live under `tests/`; Harness 0.7 owns
  structured LLM analysis.
- Removed category-derived Fact half-lives and automatic Fact decay. Compatibility Fact rows use a neutral
  explicit decay value; category is no longer retention authority.
- Removed `delete_session`, `delete_old_sessions` and `delete_all` from the 0.6 public backend and
  manager protocols. Suppression is the ordinary-use authority; immutable evidence is retained.
- Froze candidate metadata at `0.6.0` with exact Harness compatibility `>=0.7,<0.8`.

## [0.5.2] - 2026-08-25

### Changed
- Expanded the Harness dependency metadata to `simple-harness-sdk>=0.4,<0.7` after the retained
  Agent Memory v1 contract passed against the exact Harness 0.6.1 prepublish wheel. No Memory
  behavior or public API changed.

All notable changes to `simple-harness-memory-sdk` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Semantic relation memory

- Added fresh schema v7 knowledge relations with an exact canonical Semantic relation owner while preserving
  existing immutable evolution relations.
- Added strict atomic `applies_to` persistence for Semantic claim to Procedure/Prospective endpoints, including
  same-plan exact endpoint resolution, fault rollback, replay, lifecycle and restart integrity gates.
- Added the principal-scoped public committed mutation receipt view and display-only graph projection that
  excludes relation memories as nodes and removes edges when the owner or either endpoint becomes ineligible.

### Human Memory audit access

- Added the public fresh-v6 `build_human_memory_v6` manager facade, including evidence/conversation
  admission, mutation, suppression/revocation, typed recall, display graph and audit methods.
- Added resolver-backed `AuditAccessAuthorityRefV1`; direct caller-minted sealed decisions now fail
  closed. Grant/deny, replay, expiry and shared read-budget outcomes are durable hash-only events.
- Added MEMORY trace with hash-only cognitive lineage, ordinary-visible fixed aggregate metrics and
  sealed canonical state manifests with independently reproducible table roots and access-event
  binding.
- Bound the audit cursor authority hash into the initialization receipt, made public trace/evidence
  reads principal/requester-mandatory, and froze full required-table manifest coverage with explicit
  derived/global exclusions.
- Exported suppression request/decision/scope contracts and stable evidence receipt/record DTOs from
  the package root so exact-wheel consumers can use the complete Manager facade without core imports.
- Exported `InformationClassificationPolicy` and `EffectiveInformationClassification` from the
  package root; callers continue to source `PrivacyClass` and `InformationAttribute` from Harness.

## [0.5.1] - 2026-08-24

### Compatibility

- Expanded the Harness dependency metadata to `simple-harness-sdk>=0.4,<0.6` while preserving the
  Agent Memory v1 public contracts and all personal/family scope, cloud embedding, receipt, outbox,
  and message behavior.
- Added an isolated exact-wheel compatibility runner and a pinned Harness 0.4.0 CI cell. Harness
  0.5.0 remains a required pending cell until its candidate or release wheel is available; 0.5.1
  must not be published before both cells pass.

## [0.5.0] - 2026-08-23

### Observability

- Added optional shared Harness observability sinks and correlation to `MemoryManager` direct
  construction, all builders, and direct Mock/SQLite backends without changing business authority.
- Added privacy-safe structured lifecycle events for recall, committed turns, durable fact jobs and
  restart recovery, including replay, degradation, retry, dead-letter, erasure and lost-lease outcomes.
- Added bounded aggregate `diagnostics_snapshot()` health for recall stages, turn receipts, fact-job
  queues and sink counters. SQLite diagnostics select status/time/error-code aggregates only and never
  query content, payload or embedding columns.

### Packaging

- Promoted `simple-harness-sdk>=0.4,<0.5` to a base dependency so both SDKs consume the same
  import-pure observability envelope; the local sibling path source remains available for development.
- Froze the 0.5.0 public API and candidate metadata identity while retaining the 0.4.0 release record.

## [0.4.0] - 2026-08-22

### Breaking changes

- Fresh schema v4 replaces the earlier runtime schemas. Normal runtime startup never upgrades an old
  database; operators must use the explicit backup-first v3→v4 migration API.
- The public conversation adapter and duplicate Harness DTOs are retired. Consumers pass
  `MemoryManager` directly as the Harness `AgentMemoryPort`.
- Global `delete_all()` mutation is disabled; privacy operations require an explicit trusted principal
  and scope.

### Bounded retrieval and SQLite operations

- Added identity/scope-filtered external-content FTS5 indexes and bounded lexical/recent vector
  candidate decoding against the active embedding generation only.
- Added complete embedding lineage, local-only BGE loading, fail-closed production embedder
  construction, and restartable two-generation reindex with verified atomic activation.
- Added a per-database writer lease, serialized bounded checkpoints, online backups with
  schema/lineage/SHA-256 manifests, and closed-manager restore with corruption checks and atomic
  replacement.

### Agent Memory v1 / schema v4

- `MemoryManager` now directly implements the Simple Harness `AgentMemoryPort` through lazy
  imports supplied by the optional `[harness]` extra; the former public conversation adapter and
  duplicate DTO exports are retired.
- Fresh SQLite schema v4 persists deployment/household/actor/session identity, personal/family
  scope, immutable bindings, recall write fences, erasure epochs, turn receipts and tombstones.
- Session and committed-turn receipt keys are deployment-scoped, with full household/actor/session/scope
  validation on replay; different deployments may safely reuse external session and turn identifiers.
- Recall captures its erasure fence before embedding/ranking, so timeout/corruption degradation retains the
  delete boundary and stale turns remain `rejected_erased`.
- A committed turn atomically creates one receipt, the user/assistant pair, and a durable fact job.
  The leased worker performs extraction outside the write transaction and atomically applies its
  canonical snapshot with the job acknowledgement; expired claims recover at startup.
- Added principal export, scope deletion, fact forgetting and authorized family projection APIs.
  Deletion advances the erasure epoch before cascading content and prevents late replay/job
  resurrection.
- Froze the Harness-free public `share_fact(MemoryPrincipal, fact_id)` contract: deterministic replay,
  cross-principal ownership conflicts, `projection_of` provenance, and source-forget tombstone cascade;
  `MemoryOwnershipConflict` is exported at package top level for future consumers.
- Added Harness-free `remember_fact` / `read_fact` principal APIs returning exact fact IDs, with canonical
  source-event replay, persisted salience/pinned/tier metadata, ownership isolation, and no-resurrection forget.
- Scoped recall snapshot identity by deployment, including checksum-gated transactional repair of the known
  early-v4 global-key schema, and added portable POSIX/Windows fail-fast writer leases.
- Persisted principal explicit-forget action receipts keyed by deployment/source event, preserving first-result
  replay semantics, ownership/payload conflicts, restart safety, and distinct no-op provenance without content.
- Structured Agent Memory events emit opaque principal identifiers and counts/hashes only.
- Added an explicit backup-first v3→v4 migrator and public manifest import API. The approved
  four-way taxonomy suppresses tentative, terminal and deferred legacy sources with hash-only
  receipts, cascades their embeddings/facts, rebuilds aggregates from retained facts, and restores
  the verified backup on any publication fault. Runtime opening of v3 remains fail-closed.

### Changed
- `recall()` is now read-only: it no longer bumps salience or writes `last_recalled`.
  Reinforcement is available via the explicit `recall_and_reinforce()` method.
- `Embedder.embed()` / `embed_batch()` are now async (the whole retriever/recall chain
  awaits them), preparing for a cloud embedder.
- `get_embedder("auto")` no longer eagerly loads BGE-M3; it always returns the
  deterministic `HashEmbedder`. BGE-M3 remains available via the explicit `"bge"` kind.
- A corrupted `digital_twins` row now raises `MemoryCorruptionError` instead of silently
  returning an empty DigitalTwin.

### Persistence
- Fresh databases are stamped with the exact v4 schema descriptor and checksum; missing, older, newer,
  or checksum-mismatched runtime databases fail closed.
- `append_message` (including fact extraction/insert/supersede) is now atomic — a single
  transaction rolls back the message and any partially-written facts on failure.
- Added an optional `source_event_id` idempotency key on messages (partial unique index);
  re-appending the same event returns the existing message id without a duplicate row.

### Deletion & Limits
- Principal/scope privacy deletion cascades messages, source facts, vectors and pending jobs, repairs
  supersession lineage, and rebuilds the digital twin from retained facts.
- Added embedding lineage columns (`embedder_kind` / `embedding_dim` /
  `embedding_format_version`) plus a `reindex(embedder)` method that re-embeds every
  message and swaps the active embedder/retriever.
- Added size limits (`max_content_chars` / `max_db_bytes`) raising `MemoryLimitError`.

### Cloud embedding
- Added `CloudEmbedder` (async, batched, LRU-cached, retry-with-backoff, fail-closed)
  and `OpenAICompatibleClient` (httpx `/embeddings`, dimension-validated). Cloud
  embedding has no silent offline fallback — network failure raises `EmbeddingError`,
  so callers choose an explicit degradation (e.g. `HashEmbedder`).
- `get_embedder("cloud", base_url=..., api_key=..., model=..., dim=...)` wires the
  cloud embedder; `api_key` never appears in repr/log/exception.

### Privacy
- Recall and fact-extraction logs no longer emit raw query text or fact key/value
  content; they log lengths/counts only.

### Observability

- Added `memory.recall` / `memory.recall_empty` structured events (query length, hit
  count, per-source contribution) to the hybrid retriever.

### Documentation
- README quickstart restructured so the basic example runs under a plain `pip install -e .`
  (append + recall + facts); world model and BGE-M3 embedding moved to an "optional capabilities"
  section with their exact extras and weight-download prerequisites.
- Documented the default HashEmbedder as a deterministic hash pseudo-vector (not semantic);
  production semantic recall requires the `[embeddings]` extra.

### Tooling
- Added `scripts/verify_quickstart.sh`, a release gate that installs into a clean venv and executes
  the README quickstart block verbatim (no paraphrase), reporting a structured PASS/FAIL.
