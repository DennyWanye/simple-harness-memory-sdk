<!-- last-calibrated: 6ba269537e45d443629aee56e9cfabec9de2e833 -->

## 2026-09-06 prospective终局与schema7.3源码候选

最后更新：2026-09-06。按2553已接受边界新增公开settle_prospective_invalidation严格联合、独立持久not_required receipt/observation、同事务无登记请求证明和后续登记门；新7.3显式升级保留原7.2 DDL/初始化receipt/业务列，fresh用7.3。版本预留0.6.17，未构建/安装/独审，Host52由主实施。新增12项风险控尚未运行（145共享锁三次BUSY75，无child），不能称验收完成；旧V2八项不重跑。[实际接口与待验收边界](../plans/2026-09-06-prospective-signal-source/SDK终局实现.md)。

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
