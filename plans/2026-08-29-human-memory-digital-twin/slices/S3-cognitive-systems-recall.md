# S3 — 四类长期记忆、类型化召回与展示投影

> Release unit：S3（Memory SDK）  
> 高风险子系统：认知状态机、检索资格/排序、派生投影（3）  
> 覆盖：HM-AC-2/4/5/6/7/8
> 执行状态：Task 1—4 COMPLETE（Memory Task 3 `31ffb15` + `3e45194`；Harness exact authority `aa45a51`）。Task 4 remediation 已完成五轮独立复审 P0/P1/P2=0；machine `a2-004` resolved；真实 quality gate 仍 `NOT_RUN/BLOCKED`；继续 Task 5—7

## 交付边界

在 S2 证据/审计底座上实现 Episode、Semantic、Procedure、Prospective 和五天 Short-Horizon Index。Working
Memory 只以 RecallDecision/ContextFragment 表达，不建长期表。数字孪生体只输出可视图数据，不提供 Agent 查询口。

## 文件影响清单

| 文件 | 改动 |
|---|---|
| `core/cognitive.py`（新） | 四类 record/state/epistemic/conflict/verification DTO、EvidenceSpan 与合法转换 |
| `core/mutations.py`（新） | MemoryMutationPlan validator、CAS、evidence entailment/ownership、apply receipt |
| `core/recall.py`（新） | RecallPlan validator、eligibility gate、typed candidates、minimal selection/decision |
| `core/prospective.py`（新） | trigger normalization/evaluation 与候选状态转换，不执行外部动作 |
| `core/manager.py`, `core/port.py` | 公开 apply/recall/trigger/feedback/twin graph/read-view API |
| `backends/sqlite.py` | episode/claim/procedure/prospective/evidence link/relation/short-horizon/projection tables |
| `features/{retriever,lexical,rrf,reranker}.py` | 从 Message/Fact Top-K 改为 typed candidate pipeline |
| `cognitive/twin_builder.py` | Fact 聚合改为 canonical relation graph projection |
| `features/facts.py` | 移除 free-form Chat Completions parser；提取器只消费 S1 strict payload |
| `tests/{unit,integration,artifact}/` | 状态机、资格门、质量集、性能、consumer wheel |

## Tasks

### Task 1 — 四类 canonical state 与独立认知维度 [HM-AC-2/5]

- Episode：span/thread、参与者/目标/行动/结果/影响、active/amended/disputed 与 raw evidence refs。
- Semantic Claim：`lifecycle_state`、`epistemic_status`、`conflict_status`、`verification_state`、valid interval 分列；
  同值加 evidence、多值并存、明确纠正 supersede、含糊 contested、inference 不得覆盖 explicit_user。
- Procedure：draft/eligible/active/reinforced/revised/inapplicable/superseded；适用环境、步骤、风险等级、成功/失败 evidence。
- Prospective：candidate/pending/triggered/in_progress/completed/rescheduled/cancelled/expired；行动与 typed trigger 分开。
- `EvidenceSpan` 固定 evidence/item ID、canonical UTF-8 byte offsets、exact quote、source/quote hash、normalization version、
  actor/source provenance 和 support kind；typed observation 另带注册 schema、JSON Pointer/value hash。
- 验证：表驱动合法/非法转换、历史有效期、冲突、重复证据、状态原子性。

### Task 2 — Strict MemoryMutationPlan 校验与混合提取 [HM-AC-2/7/8]

- 主模型 tool payload 只提出 operation；validator 验证 schema/长度、principal、EvidenceSpan offset/hash/ownership、base revision、
  epistemic 限制、suppression、状态转换和 idempotency。
- epistemic/status/kind 均是不可信提案：只有 exact verified evidence authority 可赋予 explicit user、external verification、
  observed behavior、correction/forget 权限；UNKNOWN/LLM inference 永远不能借自报状态进入 active/supersede/suppress。
- `EvidenceSpanRef.support_kind` 本身仍是模型提案，不能授予 correction/forget/supersede/suppress。相关动作必须额外取得
  Host-owned、绑定 exact subject/action/target revision/evidence/run-turn/plan-operation/expiry/nonce/issuer/hash 的
  `MemoryActionAuthority`；普通 assertion 重标 correction 必须拒绝。用户已批准：自然语言路径缺少 authority 时返回稳定
  `NEEDS_USER_CONFIRMATION`，用户确认后由 Host 签发；专用记忆 UI 的可信动作可直接签发。CREATE 不需要该 authority。
- effective classification 必须单调合并 Memory policy、全部 Host-signed evidence item floors、target revision 和 proposal，
  且同事务持久化各 authority/hash 与最终 decision；任何 classification authority 缺失整批拒绝。
- 确定性代码不宣称证明开放自然语言 entailment：普通模型规范化 claim 保持 candidate/unverified；exact explicit-user
  assertion 可带原句/来源 active；注册 typed tool observation 才可 verified；inferred 永不覆盖 explicit/observed。
- correction/supersede 校验 target revision/relation；ambiguous target 或 contradictory evidence 转 contested 并要求确认。
- 用户明确 remember/correct/forget 从 Host immediate outbox 高优先执行；普通 committed groups 按 S2 durable batch 异步。
- Episode 只在任务/目标/决定/行动结果/纠正等长期事件形成；普通寒暄只留 evidence。事件 span 必须连续可校验。
- 每项 accepted/rejected 与 before/after state 在同事务记 decision；任何非法项不留下半 supersede/孤立 edge。
- 验证：五类 LLM 载荷变异、无 evidence/inference-as-fact、混合 batch 部分非法时全计划或逐操作既定原子策略。

#### §2-补（2026-09-09，0.6.35）关系端点解析，与生命周期推进版本的分类归属

> 追加条款；上文 Task 2 历史文本不改。裁定与验证见
> `../DECISION-2026-09-09-procedure-relation-endpoint-classification.md`；缺陷来源
> Host 事件 S 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-S-RELATION-KEYERROR.md`
> §3「坑二」/ §8 F-S1（P0）。本节同时补上 Task 2 从未写过的**关系端点解析**口径。

1. **「任何 classification authority 缺失整批拒绝」（上文 Task 2）的适用范围**是 mutation *operation*：
   每一个 operation 必须在同事务内产生并持久化恰好一条 `cognitive_classification_decisions`。
   它**不**要求「每一条 `cognitive_memory_revisions` 行都有自己的分类决定」。
   `cognitive_memory_revisions` 只有两个写入点：mutation apply（受本条约束）与
   `_copy_cognitive_revision_unlocked`——后者服务于**生命周期推进**（Procedure 观测提交、
   Prospective 信号提交），逐字复制 `content_json` / `content_hash` /
   `effective_privacy_class` / `information_attributes_json` / 有效时间 / 证据 span /
   task-scope origin，只改 `lifecycle_state` 与 plan/operation 标识，**从不重跑分类策略**；
   被分类的三样东西一个字节都没变，本来也不需要重跑。该表 append-only（不可变触发器 + 无 `UPDATE` 写入点），
   且每条 revision 由唯一一个 operation 或唯一一次复制产生，因此至多一条分类决定指向同一 revision。
2. **管辖某一版的分类决定 = 血缘上最近的已分类祖先**：对 `(memory_id, revision)`，
   取 `memory_revision <= revision` 中最大的那条分类决定。链是连续的（每次推进都是
   `base_revision + 1` 且以 head CAS 收口），因此「最大的已分类 revision」与「复制链上最近的已分类祖先」
   恒等。**一条已分类祖先都没有 = 损坏**，`MemoryCorruptionError`，整批拒绝（上文 Task 2 的口径不变）。
3. **继承必须自证仍然成立**，两条：① 管辖决定的 `effective_privacy_class` /
   `effective_attributes_json`（被 `decision_hash` 锚定、收据复核逐字重算）必须与该 revision 行的
   `effective_privacy_class` / `information_attributes_json` 相等——对 exact revision 与继承祖先
   两条路径同样成立；② 当管辖决定不在这一版上时，该 revision 与祖先 revision 的 `content_hash` 必须相等，
   即它确实是那条已分类 revision 的复制后代。任一不成立即 `MemoryCorruptionError`，不得继承。
4. **关系端点解析（`semantic_relation` 的 `ExistingMemoryTarget` / `CreatedByOperationTarget`）**
   在 apply 时逐个端点重解析，顺序固定：所有权 → head CAS（端点必须是当前 head 的 exact revision）→
   `conflict_status` 必须 `uncontested` → 召回状态门（Procedure 必须 `active`/`reinforced`）→
   有效时间 → canonical `content_json` 与 `content_hash` 复算 → typed payload 行存在 →
   证据 span 非空 → 上述 §2-补.2/3 的分类归属 → `restricted` 不可披露 →
   记忆与逐条证据的 suppression。source 端必须是 semantic claim（非 relation），
   target 端必须是 procedure 或 prospective；自环拒绝。
5. **端点的隐私类与信息属性是关系记忆自身分类的下界**（与 `target` 同一条单调合并规则），
   并逐端点记入该关系 operation 的 `decision_json.relation_endpoints`
   （role / memory_id / revision / memory_type / privacy_class / information_attributes / content_hash）。
6. **离线车道口径（F-S2）**：分析车道构造 `RecallContext` 时用的是分析 run 的 `run_id`，
   而 Procedure 适用性指纹来自另一组事实（持久化的、已被 SDK 消费的 use）。SDK 只把该字段当集合用，
   因此今天自洽；但「这个 run 的**当前**适用性」这一字段名对离线车道不准确，
   离线调用方提供的是「曾经被真实用过的指纹」，不承诺此刻仍然适用。
7. **尚未闭合（F-S1b）**：`check_history_visibility` 目前对 Procedure 恒定判 `RECALL_AUTHORITY_STALE`
   （硬编码空指纹集合），因此本节的端点解析虽已可用，Host 的复核路径仍会打掉整批。
   放开它需要给 `check_history_visibility` 增加调用方提供适用性指纹的入口（公共 API 扩面），
   并同时裁定第 6 条那笔取舍能否作为复核依据。

### Task 3 — Procedure 与 Prospective 一等规则 [HM-AC-5]

状态：COMPLETE。Memory 仅消费 ref-only Host authority；Procedure 使用 logical qualification epoch、v2
applicability/hazard 与 rolling-90-day distinct evidence；Prospective 仅持久化 registration/invalidation outbox，
不启动 clock、不执行 action。两条链均保存 immutable consumption/event/decision/result/rejection audit，并在
replay/open/close 做 rooted exact-chain 校验。验证命令与结果同步记录在本仓 `ARCHITECTURE/ARCHITECTURE.md`
的“验证状态”。

- explicit “以后都这样”可直接 active（只代表记忆状态，不授予执行权限）。观察的低风险可逆程序：1 个成功 terminal
  Run 为 draft，2 个不同 TaskScope/terminal receipt 为 eligible，3 个不同 TaskScope 在 rolling 90 days 且相同 procedure
  revision/applicability fingerprint 才 auto-active；同 TaskScope/retry/replay 最多计一次。
- 任一可归因失败、user correct/revoke、tool/schema/version 或 applicability drift 立即阻止使用并转 revised/inapplicable/
  superseded；旧 revision 不自动复活，新 revision 重新累计。发布/删除/付款/权限等高风险 observation 永不 auto-active。
- Procedure 使用前检查 tool/environment/version applicability；失败或漂移转 revised/inapplicable/contested。
- Prospective 只有明确 action+trigger 可 pending；无 trigger 为 candidate；模糊愿望改为 Semantic Goal；LLM inference
  不得 pending。canonical state 以 durable registration/invalidation outbox 投影给 Host 唯一 scheduler；Memory 不启动第二时钟。
- 验证：发布/删除/付款/权限负例，跨任务独立证据，时间/事件 trigger replay/reschedule/cancel/expire。

### Task 4 — 五天 Short-Horizon Conversation Index [HM-AC-4/6/8]

状态：COMPLETE。公开入口只接收 principal/query/disclosure/bounds；active generation 与 numpy cache 由 SQLite
repository 私有持有并从 durable rows 重建。Host v3 registration 的唯一 public-text pointer/hash 与 classification
authority 是索引资格根；无授权 registration 永久保存但不索引。完整 eligibility universe 先经过 identity、
disclosure、time、privacy/classification 与 suppression，随后 FTS、entity-time、vector 独立排序并融合；stale/cold/
deadline 只降级当前 universe，且 audit 保存 gate counts、hashed refs/content hashes、lane/selection scores 与 generation
manifest。五天清理只删除派生 chunk/vector/FTS。调用 deadline 从公开入口开始计时，覆盖并发 write/audit 排队；
timeout 产生关联的 `recall_started` 与 `recall_terminal`，close 先拒绝新 recall、等待已接纳调用并 drain 审计。Host
metadata routing fields 回绑至签名 registration；FTS mirror/vector hash、dimension、causal metadata 与 audit lineage
均在 close/reopen 时 fail-closed。Focused `17 passed`、全仓 `864 passed, 8 skipped`；真实 200-query semantic quality
gate 仍归 S3 最终验收，未在本 Task 宣称 PASS。

- `a2-005` 用户批准的修正架构：active generation/cache 只能由 Memory repository 从 durable DB snapshot
  加载并核验，公开入口不得接受调用方指定 generation 或 cache；permission/status/time/suppression 先形成完整
  eligible universe，FTS 与 vector 在该 universe 上独立召回后融合，禁止以 FTS 命中集截断 vector candidates。
- Harness 的 Host-owned conversation registration 必须额外绑定唯一 `public_text` JSON pointer/hash、effective
  privacy class、information attributes 与 classification authority ref；Memory 只索引该授权文本并对 chunk 做
  单调从严聚合，禁止遍历 sanitized payload 的任意 string leaves。
- 对超过最近 10 causal groups 且 age≤5 days 的 immutable evidence 建 chunk；保留 roles/order/task/entity/time/source refs。
- FTS5 + embedding candidate + recency/task/entity affinity；最近窗口 evidence 去重；到期只移除派生 index。
- 按 V0 `SPIKE-VECTOR` 已冻结的 backend/容量/降级策略实现；统一 `VectorIndexPort` 仅在 spike 证明需要第二实现时保留，
  否则内联 SQLite repository。不得在实现时改变 corpus、oracle 或阈值。
- V0 选择：SQLite metadata/FTS5 + rebuildable numpy float32 generation cache exact scan（numpy 已是依赖）；100k×64
  cache≈25.6 MB。cache cold open/first query 和 warm p95 过门；打不开或超 deadline 时只用 permission-filtered
  FTS/entity/time candidates 并记录 `VECTOR_DEGRADED`，绝不读取 stale generation。
- 验证：五天边界、cross-task similar entity、index delete/rebuild、suppressed row、p95≤500ms/hard deadline 2s；V0
  synthetic backend 结果不替代 S3 真实 embedding/200-query semantic quality gate。
- 真实质量门先生成不少于 200 条带 expected type/privacy outcome 的候选 corpus 与固定 hash；在用户或独立人工
  完成标签 review/freeze 前，状态必须保持 `NOT_RUN/BLOCKED`，不得以 AI 草案或 synthetic benchmark 宣称 PASS。
- AI 候选集已生成 240 条，见 `quality/recall-corpus-candidate/`；JSONL SHA-256 为
  `e3d39fdf68ded5c4af94b7c7ca04587b724b46643d1ea6fd2ccecb0003e039d5`。其
  `label_source=AI_DRAFT_UNREVIEWED`、`quality_gate=NOT_RUN/BLOCKED`，只完成结构与分层准备，尚未构成质量证据。

#### §4-补（2026-09-08，0.6.30）短时域 chunk 长度上限与确定性切段

> 追加条款；上文 Task 4 历史文本不改。裁定与验证见
> `../DECISION-2026-09-08-short-horizon-chunk-cap.md`；缺陷来源 HM-TO-A6 turn 22
> （Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-TIMEOUT-HOST-SIDE.md` §2：
> 单条 29 778 字符 chunk 嵌入 23.9 s，Host 因 `public_text_hash` 绑定无法限长，chunk 边界归 SDK）。

1. 一条短时域 chunk 的内容（`role: public_text` 行以 `\n` 连接后的渲染文本）最多
   `SHORT_HORIZON_CHUNK_MAX_CHARS = 2 048` 个 Unicode 码点。渲染文本不超过上限的完整因果组仍然是
   **一组一条**，其 `chunk_id`/`content_hash`/投影行与 0.6.29 逐字相同。
2. 超过上限的完整因果组由 SDK 按以下确定性规则切成 K 条内容寻址 chunk：先按注册（item）边界整行装箱；
   单行超过上限时依次优先在段落（`\n`）、句子（`。！？!?`）、空白处切分，且切点必须落在窗口后半段
   （不产生小于上限一半的碎片），否则在上限处硬切；切分只在码点边界发生，永不切开一个码点；一条注册
   被切出的各段拼接回去逐字等于原 `public_text`。
3. 每个因果组最多投影 `SHORT_HORIZON_CHUNK_MAX_SEGMENTS = 8` 段；之后的尾部**不投影**（原始证据与注册
   不受影响），审计 `projection_rebuilt.details.truncated_group_count` 与
   `ShortHorizonProjectionBuildResult.truncated_group_count` 记录被截断的组数；`split_group_count`
   记录被切段的组数。
4. 分段 chunk 的 `chunk_id` payload 在 0.6.29 的域上追加 `segment_ordinal=k` 与 `segment_count=K`
   （K=1 时不出现，保证旧 id 稳定）；投影表 `causal_group_id` 列存投影键 `<causal_group_id>\x1f<k>/<K>`；
   Host 注册的 `causal_group_id` 不得包含 U+001F，含有者注册即拒绝
   （`conversation_registration_causal_group_id_reserved`）。
5. 每一段的血缘（`short_horizon_chunk_evidence`）都是**整个因果组**的全部注册；任一证据被抑制则该组全部段
   一起消失（"部分上下文绝不可见"不变）；`occurred_at/expires_at`、privacy/attributes/classification refs、
   roles/task/entity/source refs 都按组聚合、各段相同；过期、清理、分页、召回、历史可见性一律按 chunk 行
   处理，对分段透明。
6. 升级：0.6.29 写出的"一组一条"超长 chunk 行在 0.6.30 打开时**不是损坏**（一致性校验与历史可见性对裸键行
   接受 0.6.29 形状，且要求它是该组唯一一行），下一次投影重建以分段替换它。该替换是既有 `chunk_id` 的移除，
   按 0.6.28 车道（§5.4「Short-Horizon source 失效」）恰好推进一次召回权威 epoch
   （`short_horizon_projection_changed`），绑定旧 chunk 的召回结果由此正确失效；绑定其他来源的结果按
   0.6.29 逐来源重校验照常放行。
7. 投影重建改为**增量**：只删除目标清单里不再存在的 `chunk_id`、只插入新出现的 `chunk_id`，未变化的 chunk
   连同 FTS 镜像、血缘行与 active 世代向量原样保留；世代重建沿用 active 世代（同 lineage、hash/维度校验
   通过）里同 `chunk_id` 的向量字节，只对新 chunk 调用 `embed_batch`，审计
   `generation_activated.details.embedded_count/reused_vector_count`。世代身份、manifest、CAS、replay、
   空集与失败语义（0.6.27）逐字不变；沿用向量仍属纯索引重建，不推进 epoch（0.6.28 第 3 项）。
8. Host 侧不得假设"一个因果组一条 chunk"：`projected_chunk_count` 可大于完整因果组数；Host 只通过
   `chunk_ref`/`content_hash` 绑定来源，不解析投影键。
9. 无 DDL 变化（7.4 checksum 不变）。放宽 `short_horizon_chunks` 的
   `UNIQUE (principal_id, primary_conversation_id, causal_group_id)` 并加 segment 列（schema 7.5）
   推迟到下一次不可避免的 DDL 切换，届时投影键编码退役。

### Task 5 — Typed RecallPlan 与资格门 [HM-AC-4/7/8]

`a2-006` corrected architecture 已获用户批准（消息 SHA-256：
`36f33adaf0942634a8ece1eec4a6f30d44dec73e1ef8704b29d983a57f2e09ae`）。本 Task 不兼容旧 wire/DB；
原型从 fresh data 初始化，Harness Recall 协议一次性切到 strict v4，Memory schema 切到 fresh v6。

#### 5.1 公开 authority 链与内容载体

- Harness 用 discriminated `RecallSelectedItemV4` 替代 `selected_memory_types + selected_memory_refs`：公共字段固定
  `item_id/ordinal/item_kind/source_kind/source_ref/source_content_hash/public_payload_hash/item_hash`；认知记忆必须带
  `memory_type + exact revision`，Short-Horizon 必须带 `chunk_ref` 且禁止伪造 revision。这样 long-term-only、
  short-horizon-only 与 mixed result 均可表达。
- `RecallConfirmationGroupV4` 是一个原子 carrier，绑定 `conflict_group_id/hash` 与完整、有序、至少两项的 exact
  member bindings；member 不能同时进入普通 selected，也不能单独 page-in。`RecallDecisionV4` 严格拒绝 v3 wire。
- `TypedRecallResultV1` 绑定 `decision_id/hash、result_id/hash、authority_epoch、policy_hash、evaluated_at、
  authority_expires_at`，每项同时保存 canonical source hash 与最小公开投影 payload/hash、effective classification、
  score、evidence manifest hash 和 cross-TaskScope provenance。source hash 与公开 payload hash 不得混为一个值。
- 所有公开 page-in/重建只接受 `result_id + result_hash + item/page coordinates + bounds`，不得接受裸
  `memory_id/revision/chunk_ref`。Memory 重新校验 durable result 后返回 hash-identical page/receipt；ref-only 入口不存在。
- recalled `ContextFragmentV2`（含 `RECALLED_MEMORY`、`SHORT_HORIZON`、新增 `RECALL_CONFIRMATION`）必须携带公开 payload
  以及 decision/result/item/page-or-use-receipt 的完整 binding；非 recall fragment 禁止这些字段。官方 Context assembler
  只接受已验证 binding，并在 assembly decision 中绑定 fragment `(id, hash)`，不能只绑 ID。公开 dataclass 只是序列化值，
  不是读取 capability。

#### 5.2 两侧冲突的写入与解决

- Task 2 的旧“CONTEST 必须复制相同 payload”规则在本 Task 被明确替换。`CONTEST` 必须瞄准 exact current head `rN`，
  challenger payload 的 canonical content hash 必须与 incumbent 不同；challenger 必须有非空可信 evidence，且至少一条
  evidence span 未绑定 incumbent。缺证据、同内容、stale target、已存在 active group 或 nested contest 全部拒绝。
- 同一 strict transaction 在原 logical `memory_id` 创建 challenger head `rN+1`（保留该类型的合法 lifecycle，
  `conflict_status=contested`），并写 immutable `cognitive_conflict_groups`、恰好两个有序
  `cognitive_conflict_members`（incumbent=`rN`、challenger=`rN+1`）、成员 content/evidence-set hash、relation、decision、
  receipt 后 CAS head。两项是不同 revision 与不同 content hash；跨 principal/memory 的 member FK/unique 约束禁止。
- group 仅在 current head 仍为 `rN+1`、head contested、恰好两项 hash 完整且没有 resolution fact 时 active。
  authorized `REVISE` resolution 必须创建 `rN+2` 且 `conflict_status=resolved`；选择旧一侧时复制其 payload 并绑定新的
  resolution evidence，出现第三种 evidence-backed 内容时记 replacement。`SUPERSEDE/SUPPRESS` 可形成 terminal resolution。
  append-only `cognitive_conflict_resolutions` 记录选择/替换/终止；永不把 head 回滚到旧 revision，旧 group 永不复活。
- receipt/open/replay/recall 必须重算 group/member/evidence/resolution/relation hashes 和 cardinality。group/member/resolution
  插入点及 head CAS 前的 fault 全部回滚；commit 后 replay 不重复。任何一侧不可见、hash 漂移、被 suppression、过期、
  principal 不符或 group 不 active 时，整组、双方、candidate count 与“存在冲突”均不泄露。

#### 5.3 完整资格与 disclosure matrix

- 所有长期普通候选先要求 exact principal、exact current head、half-open 有效期 `valid_from <= now < valid_until`
  （无上界允许）、未 suppression，再按类型冻结 lifecycle：Episode=`active|amended`；Semantic=`active`；Procedure=
  `active|reinforced`；Prospective=`pending|triggered|in_progress|rescheduled`。普通选择仅允许 `uncontested|resolved`；
  contested 只能走完整 group confirmation。Short-Horizon 使用 `occurred_at <= now < expires_at`、签名 registration/
  classification chain 与全部 source evidence suppression gate。
- 普通 Episode/Semantic 的 epistemic×verification 白名单：`explicit_user` 仅 `source_bound|user_confirmed`；
  `verified_external` 仅 `source_verified`；`observed_behavior` 仅 `source_verified|repeated_observation`。
  `llm_inference|unknown` 与任何 `unverified` 一律禁止。Procedure：explicit-user active/reinforced 使用
  `source_bound|user_confirmed`；observation-qualified 只允许 `repeated_observation`，并要求 Host 当前 applicability
  fingerprint 与 revision 绑定值完全一致。Prospective 只允许 `explicit_user + source_bound|user_confirmed`，且 typed
  trigger 与当前 signal state 完整。任何未列组合 fail-closed。
- 普通 recall 只接受 trusted/current DisclosureContext。`USER_SELF` 对 `task_execution/personalization/task_resume/user_review`
  可收 PUBLIC/PERSONAL/SENSITIVE，RESTRICTED 永远不进入模型 Context；HOUSEHOLD/TASK_COLLABORATOR 仅在
  `task_execution|task_resume` 收 PUBLIC；EXTERNAL_PARTY/PUBLIC/UNKNOWN 全拒。非 self 即使 privacy 被错误标 public，
  只要 attributes 含 identity/relationship/family/health/location/financial 仍拒。AUDIT/EXPORT 不走 ordinary recall，
  使用独立 sealed audit/export authority。attribute 只能从严，不能放宽 privacy。
- TaskScope 不是普通认知隔离：未指定 scope 时同 principal 全局候选；指定时只收窄。每个 candidate/filter/selected item
  均记录 source TaskScope set、active TaskScope 与 `cross_scope`。entity/task/time selector 使用类型化字段；Episode 用
  occurred interval overlap，Semantic 用 valid interval/revision time，Procedure 用 latest qualifying evidence time，
  Prospective 用 next trigger/last transition，Short-Horizon 用 occurred_at。

#### 5.4 即时 suppression 与最终 Context 使用

- 新增 append-only `recall_authority_events` + CAS `recall_authority_heads(principal, epoch, policy_hash)`。任何可能改变资格的
  suppression/revoke、认知 head/conflict/classification 变化、Short-Horizon source 失效和 policy version 变化，均在同一事务
  追加 event 并增加 epoch；revoke 也增加，旧 result 不会自动复活。结果 expiry 不晚于 RecallContext expiry 与所选 source
  最早 expiry。
- 历史 result 可审计/重建但不自动授权 Context。Host 完成候选 ContextSnapshot manifest 后调用 Memory-owned
  `authorize_recall_context_use`，只传 decision/result/item hashes、snapshot manifest/hash、run/turn/provider-attempt 与 now；
  不传裸 source ref。Memory 在 suppression 所用同一锁/事务边界重新验证 epoch/policy/time、current head 或 active group、
  source/content/classification、recipient/purpose/privacy/attributes 与 suppression，随后写 immutable、exact-replayable、
  单 provider-attempt 的 `RecallContextUseReceipt`。Harness provider reservation 必须绑定该 receipt；新的 continuation/attempt
  必须重新授权。
- 并发线性化固定：suppression 先 commit，则授权返回 `RECALL_AUTHORITY_STALE` 且零 payload；Context-use receipt 先 commit，
  则仅该 exact immutable snapshot/attempt 可完成一次，随后 suppression 使所有新 attempt 失效。此边界同时覆盖 suppress、
  revoke、supersede、contest、classification/policy change、Short-Horizon expiry/cleanup，不承诺撤回已经发给 provider 的字节。

#### 5.5 replay、失败恢复与 unsupported 能力

- 新增 immutable request-attempt-terminal ledger，唯一键 `(principal_id, idempotency_key)`；domain-separated `request_hash`
  绑定 Harness/Memory protocol version、principal/run、context hash/revision、plan id/hash、disclosure hash 与完整 budget。
  same key+same hash：terminal 后直接返回 exact stored decision/result bytes/hash，candidate query=0；same key+different hash：
  稳定 `IDEMPOTENCY_CONFLICT`，candidate query=0。unexpired dangling attempt 从零 durable candidate state 重跑；expired dangling
  attempt 终结为 `DEADLINE_EXCEEDED`。没有持久化半 candidates。
- 一个 final transaction 原子写 decision header、有序 selected/confirmation items、result header/items 与 terminal fence。
  header 后、items 间、result 前后、commit 前 fault 均只保留 start attempt，不留下任何 terminal 半状态；commit 后 ACK 丢失
  必须 exact replay。deadline 从 public API entry 开始覆盖验证、排队、lane、final commit 与 return；超时取消 candidate work、
  返回零 content，并按 Task 4 的 durable terminal/close-drain 纪律完成 timeout terminal。启动恢复过期未终结 attempt。
- V1 支持 selector=`MEMORY_TYPE|TASK_SCOPE|ENTITY|TIME|SHORT_HORIZON`；`EVENT|ENVIRONMENT|TASK_PHASE`
  在 resolver 未实现前整 plan `REJECTED/INVALID_PLAN`。候选 retrieval mode 只支持 `FULL_TEXT|VECTOR`；RecallPlan 的
  `EXACT|TEMPORAL` 拒绝，`GRAPH` 永久禁止（数字孪生图不参与 recall）。EXACT 仅为 result-bound 内部 page-in 语义。
- 固定优先级：Harness 严格 wire/version parser（失败只写 Host invocation audit，不调用 Memory）→ authenticated
  identity 与 Context/Plan/disclosure binding → idempotency replay/conflict → capability matrix → candidate access。
  任一 unsupported member 不得被静默丢弃；按 EVENT/ENVIRONMENT/TASK_PHASE 与 EXACT/TEMPORAL/GRAPH 排序记录。
  candidate-access trap + SQL trace 必须证明首次拒绝、exact rejected replay、conflicting replay 和组合拒绝均为
  `candidate_query_started=false/count=0`，允许的仅是 idempotency/audit 读写。

#### 5.6 确定性候选、排序、去重与预算

- Harness `RecallBudgetV1` 范围：`max_items=1..32`、`max_bytes=1..65536`、`max_tokens=1..8192`、
  `deadline_ms=1..2000`。每个 `(source,type,lane)` cap `C=min(128,max(32,8*max_items))`；Episode/Semantic/
  Procedure/Prospective/Short-Horizon 各自融合后最多 128，mixed union 去重前最多 640。资格 gate 在 lane/cap 之前；
  未通过 gate 的数量/refs 不进入任何公开或普通 audit 字段。
- 共用 weighted RRF (`k=60`)：vector=.40、FTS=.30、entity=.15、TaskScope affinity=.10、temporal=.05；backend raw
  score 仅决定本 lane 名次。缺失/未请求 lane 贡献 0，不用未请求 lane fallback。全局稳定序：`-rrf_score`（序列化 12 位）、
  `-matched_lane_count`、`-typed_source_time`、`source_kind`、`memory_type-or-empty`、`source_ref`、
  `source_revision-or-zero`。vector 不可用时只降级该 lane并审计；不得把未授权 source 放入 fallback。
- exact dedupe：认知记忆=`(memory_id,revision)`；Short-Horizon=`(chunk_ref,content_hash)`。跨 source 仅在
  public-projection hash 与 sorted exact evidence-id manifest 同时相同才合并；语义相似绝不去重。
- Provider-visible 最小 payload 冻结：Episode=title/participants/goals/actions/results/impacts/occurred interval；
  Semantic=subject_entity/predicate/object_value/qualifiers；Procedure=name/applicability/steps/effective risk；
  Prospective=action/trigger；Short-Horizon=content/occurred_at。source/evidence/classification/conflict/cross-scope 作为强制
  control/audit metadata，不混入 Provider payload；所有估算由 SDK 派生，调用方不能自报。
- 预算单位是全局排序后的 `{source_kind,memory_type,payload}` 数组之 canonical JSON（sorted keys、compact、
  ensure_ascii=false）UTF-8。`bytes=len(encoded)`；保守 `tokens=max(1, Unicode codepoint count, ceil(bytes/3))`。
  按稳定序 greedy，单项字段/文本永不截断；放不下则跳过并继续尝试更小项。任何跳过都 durable 记
  `truncated=true/BUDGET_EXHAUSTED`；非空仍为 RECALL，零项为 Memory 执行后的 NO_RECALL/BUDGET_EXHAUSTED。
  主模型在调用前判断“不需要记忆”的 NO_RECALL 仍完全在 Host，不调用本 API。

#### 5.7 决定性验证出口

- 新增 `TC-HM-13` 与 `typed-recall-v1` fixture：mixed/short-only source bindings、裸 ref=零读取、完整/不完整冲突组、
  eligibility/disclosure 全矩阵、current-use 两种并发顺序、unsupported zero-query、exact/conflicting replay、重启恢复、
  decision/items/result/receipt fault seams、durable hash rebuild、candidate cap、稳定排序与 item/byte/token/deadline 边界。
- exact-limit/limit+1 覆盖 ASCII/CJK/emoji/escaping、oversize-first+smaller-fit；clean installed Harness wheel 覆盖 exports、
  strict v3 rejection、canonical round-trip、mixed sources、atomic confirmation 与 Context assembly authority。
- 质量 corpus 版本显式升级：原 `contested` 类改名 `contested-not-required`，原 20 条 no-recall gold 不变；新增
  `contested-dependent-complete/partial` 只进入 typed-recall fixture。人工 review/freeze 未完成前整体真实质量仍
  `NOT_RUN/BLOCKED`，不得因本 Task 单元/集成全绿宣称 required type≥90% 或 overall quality PASS。

### Task 6 — Display-only digital twin graph [HM-AC-6/7]

- `twin_builder.py` 从 canonical active/contested/inferred records 和 relation rows生成 node/edge DTO，节点包含 type/status/
  confidence/source refs/correction-forget capability；superseded/suppressed/expired 按普通 view policy 不展示。
- public port 只叫 `get_twin_graph_view`，不实现 recall/rank/context conversion；在代码与测试中建立禁止依赖：Agent
  runtime/Recall pipeline 不 import twin projection。
- 验证：纠正/forget/rebuild 后图更新；敏感 label/edge/tooltip 不泄露；graph payload hash 可重建。

### Task 7 — SDK 质量、审计与 wheel 门 [HM-AC-7/8]

- 提供按 turn/invocation/memory/decision 的 trace 和 privacy-safe aggregate metrics。
- 更新 public API/schema/ARCHITECTURE/PROJECT_STATUS/CHANGELOG；构建 exact wheel 与 S1 fake Host consumer。
- 全量 unit/integration/artifact；性能与真实主模型评估原始证据写 `.local-test-evidence` 对应目录，Git 只存 hash/index。

## 验证出口

- 四类状态机、mutation/recall fault matrices、suppression side-channel、short-horizon rebuild、graph isolation 全绿。
- 质量集必须达到 acceptance 阈值；若真实主模型达不到，S3 BLOCKED，不通过调整 oracle 规避。
