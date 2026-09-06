# ARCHITECTURE 索引

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
