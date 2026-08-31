<!-- plan-status: finalized -->

# Semantic Relation Memory 增量实施计划

> 日期：2026-09-01
> 流程：更新后的 `plan-test` / FULL / incremental AC
> 用户批准：`采用，记得使用更新过的plan-test skill来继续做`
> 批准消息 SHA-256：`ff036f01b5dc3b6860f61cd2771846e8416480c840119d86f26202842490c416`
> Review：该消息批准采用语义关系增量并要求按更新后的 plan-test 继续；本计划未扩张 acceptance/assurance 范围，
> 仅按挑战与 Ponytail 删除未授权复杂度，故作为本增量 final review authority。
> 范围事实源：`../../acceptance.md`、`../../assurance-contract.json`

## 1. 主要矛盾与最短价值路径

用户价值不是“图上多一条线”，而是：**关系本身必须成为可举证、可修订、可冲突、可遗忘和可审计的
长期语义记忆，同时普通数字孪生体只展示当前可用关系。** 当前实现只有 mutation revision 之间的
`amends/supersedes/contests/relates_to` 演化行；它不能通过公共 `MemoryMutationPlan` 表达“偏好适用于某个
程序”这样的知识命题。

最小验证动作（VALUE milestone）：只安装 exact Harness/Memory wheels，从 package root 公共 API 提交一个
原子 plan，创建一条 Semantic preference、一条 Procedure 和一条 `preference --applies_to--> procedure`
relation memory；普通 `get_twin_graph_view` 必须返回 **2 nodes + 1 edge**，relation memory 不重复成为 node；
suppression relation 或任一端点并 close/reopen 后必须返回 **0 edge**。在这个动作通过前，不把文档、全量回归、
更多关系 kind 或 UI 工作当成价值已成立。

## 2. 外部最佳实践与本项目适配

- W3C RDF 1.2 的 reification 模型把“关系命题”提升为可携带来源、上下文等元数据的一等资源；同一命题可有
  不同来源/上下文，reified proposition 也不等于自动断言该命题。
  参考：<https://www.w3.org/TR/rdf12-concepts/>、<https://www.w3.org/TR/rdf12-schema/>。
- W3C PROV-O 的 qualified relation 同样使用中间实体承载关系的额外细节。
  参考：<https://www.w3.org/TR/prov-o/>。
- 项目适配：不引入 RDF/图数据库依赖。canonical authority 仍是 SQLite 中版本化的 Semantic relation memory；
  `cognitive_relations` 只是由 canonical revision 同事务生成、可重建的知识投影索引。这样复用现有 evidence、
  classification、epistemic、conflict、suppression、manifest/audit 状态机，并保留单一写入口。

## 3. 当前代码事实

### Harness 协议

- `simple-harness-sdk/src/simple_harness/runtime/memory_protocol.py:67` 固定 mutation schema v4。
- 同文件 `1863-1927` 已有 exact existing target 与 same-plan created-by-operation target，可复用为 relation endpoint ref。
- 同文件 `2161-2211` 的 `SemanticMemoryPayload` 只有 subject/predicate/object value，没有 semantic subtype 或 endpoint。
- 同文件 `2383-2438` 按 `LongTermMemoryType` 单层 dispatch payload；Semantic 要支持 claim/relation 两种 payload，必须
  增加第二层 discriminator，不能靠字段猜测。
- 同文件 `2513` 起的 `MemoryMutationOperation/Plan` 已提供 strict-atomic、operation dependency 与 target 校验；relation
  endpoint 的 same-plan ref 必须进入 dependency closure，但不能套用“operation target 必须和 producer 同 memory type”的
  revision 规则。

### Memory 持久化与投影

- `src/simple_harness_memory/backends/schema_v5.py:740-768` 的 `cognitive_relations` 没有关系域与 canonical relation owner；
  现有 nullable 形状无法区分 mutation lineage 和知识关系。
- `src/simple_harness_memory/backends/sqlite_v5.py:6462-6514` 只在 REVISE/SUPERSEDE/CONTEST/SUPPRESS 时写演化关系行。
- 同文件 `731-835` 的 public graph read 读取全部 relation rows，并只依赖端点可见性；它目前无法检查“关系记忆本身
  是否 current/contested/suppressed/restricted”。
- `src/simple_harness_memory/cognitive/twin_builder.py:457-613` 的 DTO builder 已支持稳定 edge，但没有 knowledge owner gate。
- `src/simple_harness_memory/core/mutations.py:382-555` 已集中编译 mutation 权限、evidence 和生命周期；relation payload 的
  kind/type/self-loop 校验应放在这里和 backend exact-state validator，而不是 UI 或正则层。
- `simple_harness/testcase/human-memory-program/TC-HM-12-digital-twin-views.md` 与 runner 已冻结 public-wheel/no-private-SQL
  原则，但现有 runner revision 只能 self-check DTO，正式产品 lane 仍 fail-closed；本增量必须把它升级成可执行 public seed。

## 4. 冻结设计

### 4.1 公共协议 v5

1. Harness `MEMORY_MUTATION_SCHEMA_VERSION` 从 4 升为 5；本原型不兼容 v4 consumer，旧 wire fail-closed。
2. 增加 `SemanticMemoryKind = claim | relation`。普通 `SemanticMemoryPayload` wire 显式带
   `semantic_kind=claim`；新增 `SemanticRelationMemoryPayload` 带：
   - `memory_type=semantic`
   - `semantic_kind=relation`
   - `relation_kind`
   - `source_endpoint` / `target_endpoint`
3. endpoint 使用新的语义别名 `SemanticRelationEndpoint`，wire 复用 existing memory 或
   created-by-operation 两种 exact ref。created-by ref 必须指向同 plan 中较早的 CREATE operation，并显式出现在 relation
   operation 的 dependencies；允许不同长期记忆类型。
4. V1 knowledge relation 只开放 `applies_to`: Semantic claim -> Procedure 或 Prospective，不允许 self relation。任何
   新 knowledge kind 都必须有用户批准的协议升级、type/self-loop matrix 与新 oracle，不能在 v5 中静默追加。
5. 不允许 relation memory 作为 endpoint，避免初版形成未定义的高阶/循环关系；未来新增 kind 必须升级协议和 oracle。
6. LLM 仍只提出完整 `MemoryMutationPlan`；没有单独的 public `create_edge`/SQL/UI 写入口。

### 4.2 canonical relation 与派生行

1. Memory fresh schema 从 6 升为 7，不做旧数据迁移。`cognitive_relations` 增加不可含糊的 discriminator：
   - `relation_domain=evolution|knowledge`
   - knowledge 行必须有 `relation_memory_id/relation_memory_revision` exact owner；evolution 行两者必须为 NULL；
   - knowledge kind 只允许 `applies_to`；evolution 保持既有 `amends/supersedes/contests/relates_to`。
     `relation_domain` 与 owner nullability 提供明确语义域，禁止为了
     本增量改写 SUPPRESS 的 immutable `relates_to` lineage、stable ID 或 hash。
2. DB CHECK/FK 固化上述组合；owner、source、target 都 FK 到 exact cognitive revision。关系行 immutable，不能更新/删除。
3. apply 时先通过现有 evidence/classification/epistemic/lifecycle 校验，再在同一事务解析 created-by endpoints 为最终 exact
   `(memory_id, revision)`，校验同 authenticated principal、端点 current/eligible、类型矩阵、自环规则与 suppression/conflict。
4. 存入 canonical relation revision 的 payload 必须已经把 created-by ref 解析成 exact existing refs；其 content hash、receipt、
   manifest 与重启重放不依赖 operation-local ID。canonical revision 与 knowledge row 同事务写入；任意 fault 全回滚，无孤边。
5. relation revise/supersede/contest/suppress 沿用普通 Semantic 状态机。旧 relation rows 永不删除；ordinary graph 只投影 owner
   current、active、uncontested/resolved、未 suppression 且 classification 可展示的 revision。

### 4.3 graph 资格与隔离

- evolution edge：保持现有行为，只要求两个端点对 ordinary view 可见。
- knowledge edge：额外要求 relation owner 与两个 exact endpoint revision 全部 ordinary-visible；owner 或任一端点
  contested/superseded/expired/suppressed/restricted 都不显示。
- 只有 `semantic_kind=relation` 的 canonical memory 不作为 node；普通 Semantic claim 仍显示。edge 的 label 只能是受限
  relation kind，source refs 使用 hash-safe canonical refs，不泄露 relation payload/evidence 原文。
- graph 仍是纯展示：Recall/Context/Agent runtime 不 import graph projection，不增加 graph recall/rank API。

## 5. 信任、数据流与停止点

```text
LLM/Host JSON (untrusted)
  -> Harness v5 strict parser + typed credential-safe validation diagnostic
       -> on parser failure: Host audit port (durable owner; S5 implementation gate)
       -> Memory call count = 0
  -> plan dependency validation
  -> public MemoryManager.apply_memory_mutation_plan
  -> authenticated principal/evidence/action authority/classification validation
  -> resolve exact endpoint revisions + type/kind/current-state validation
  -> one SQLite transaction:
       canonical relation memory revision
       + knowledge relation derivative row
       + receipt/audit/manifest/authority epoch
  -> ordinary twin graph eligibility gate
  -> display-only DTO
```

停止点：v4/unknown wire、unknown kind、forward/missing dependency、非 CREATE producer、跨 principal、stale/missing/hidden
endpoint、relation-as-endpoint、非法 type matrix/self-loop、无证据、classification 不足、并发 CAS/fault、hash/FK/domain-owner
不一致。Harness parser failure 只产稳定、bounded、credential-safe diagnostic，由 Host 负责 durable invocation/validation audit，
不得伪造 Memory receipt；本增量冻结该 Host port/trace contract，但实际 Host 证据保持 `NOT_RUN/BLOCKED` 到 S5。合法 plan
进入 Memory 后的拒绝才由 Memory 事务性 rejection audit/receipt 负责。两侧都必须证明零半状态、零孤边，ordinary graph
不泄露失败候选。

## 6. Complexity inventory / Ponytail 约束

| 新增复杂度 | 为什么不可省 | 最小化决定 |
|---|---|---|
| Semantic 第二层 discriminator | 同一 memory type 有 claim/relation 两种严格 wire | 只增加一个 enum 与一个无 qualifiers 的最小 payload，不建通用 AST |
| 关系 domain + owner | 避免 evolution/knowledge 语义混用并让关系状态可审计 | 仍用现有表，不新增图数据库/ORM |
| endpoint 解析器 | same-plan 原子创建需要 operation ref 转 exact revision | 复用现有 target wire 和 dependency DAG |
| kind/type matrix | 防 LLM 输出任意 predicate 变成事实图 | 初版只开放 `applies_to`，不做用户自定义 schema |
| graph owner gate | relation 本身被遗忘/争议时 edge 必须退出 | 扩展现有 builder/read path，不建第二投影服务 |
| exact-wheel public runner | DTO helper 不能证明生产写链 | 扩展 TC-HM-12，不增加私有 seed API |

明确不做：RDF/SPARQL/Neo4j、图参与 recall、旧 schema migration、relation qualifiers、`supports`/knowledge
`relates_to`/用户自定义 kind、relation-of-relation、UI 美化。

## 7. 任务顺序（最短价值优先）

### Task 0 — 实现前冻结 relation black-box oracle [HM-AC-6/8]

- 在不读取未来实现输出的前提下先升级 `TC-HM-12`/fixture/runner：冻结 allowed package roots、Harness v5 三 operation
  JSON、created-by dependencies、public Manager/evidence/apply/graph/suppress/close/reopen 调用顺序、exact 2 nodes +
  1 `applies_to` edge、relation node zero、endpoint suppression + reopen 0 edge、missing public symbol fail-closed。
- runner 必须先接受 candidate identity 占位并保持 `NOT_RUN/BLOCKED`；行为/DTO/transition 逐文件 hash 在业务实现前锁定。
  source commit、wheel/version/reproducible hashes 只能在构建后单独 repin，不能改变上述 oracle 语义。

### Task 1 — VALUE Harness v5 `applies_to` wire [HM-AC-2/7/8, FAIL-RELATION-INTEGRITY]

- 修改 `src/simple_harness/runtime/memory_protocol.py` 与 package-root exports；先实现 claim/relation discriminator、
  `applies_to` payload、strict JSON round-trip、created-by dependency/type/self-loop validation、v4 rejection；同时新增 typed、
  bounded、credential-safe stable validation diagnostic。Harness 不持久化 audit。
- 更新 Harness public API snapshots/consumer tests；构建 candidate wheel，只证明协议，不宣称 Memory 价值成立。

### Task 2 — VALUE Memory schema v7 与 `applies_to` 原子 write [HM-AC-1/2/7/8, FAIL-RELATION-INTEGRITY]

- 修改 `backends/schema_v5.py` 的 fresh schema/checksum，给 relation row 增加 domain/owner/FK/CHECK；不做 migration。
- 修改 `core/mutations.py`、`backends/sqlite_v5.py` 与 public exports，严格解析 Harness v5，解析 same-plan endpoints，
  原子写 canonical relation revision + derivative knowledge row + audit/manifest。
- VALUE 前只覆盖使正链可信的最小负例：invalid `applies_to` type/self-loop、missing/forward dependency、cross-principal、
  missing/stale endpoint、一个 pre-relation-row fault rollback。完整状态/fault/replay 矩阵移到 Task 4。

### Task 3 — VALUE：ordinary twin graph 公共 wheel 冒烟 [HM-AC-6/7]

- 修改 graph read/builder：分别处理 evolution 与 knowledge；relation memory node exclusion；knowledge owner + endpoint gates。
- 先在 Memory source integration 跑 2 nodes + 1 edge / suppress->0 / reopen->0；随后构建 exact Harness/Memory candidate wheels。
- 原样执行 Task 0 已冻结的 `TC-HM-12` fixture/runner，通过 clean venv、package-root public imports 和 public Manager API
  运行最小验证动作；此处禁止修改 runner/fixture 语义，禁止 source checkout/private SQL/private import。只有这个
  frozen-oracle smoke PASS 才标记 VALUE milestone。

### Task 4 — `applies_to` 状态、隐私、审计完整矩阵 [HM-AC-1/2/6/7, HM-TO-R3/R5/R9]

- 覆盖 relation 与 endpoint 的 revise/supersede/contest/suppress、classification、expiry、current-head、CAS race；每项验证
  ordinary graph 退出但 sealed audit/immutable old rows 仍可复查。
- 扩展 manifest/root/trace/rebuild 检查：canonical relation revision 与 derivative row owner/domain/hash/FK 一致；corruption
  close/reopen fail-closed；raw evidence 永不物理删除。
- 明确证明 graph read 不改变 RecallDecision、rank、ContextSnapshot、回答或 tool control bytes/hash。
- 冻结 pre-admission malformed-v5 trace：Harness stable diagnostic，Host audit-port payload 绑定 invocation/request/output/parser
  hashes 与 reason code，Memory call/row delta=0；Host durable execution 在 S5 前保持 `NOT_RUN/BLOCKED`。post-admission 拒绝
  单独证明 Memory rejection audit。

### Task 5 — 分层 oracle 与跨仓 repin [HM-AC-6/8]

- 对 Task 0 已冻结的 TC-HM-12/fixture/runner 做 post-build exact identity repin；若语义 bytes 改变必须触发 frozen-oracle
  behavior-change gate，不能借“repin”放宽。更新 testcase index；新增测试不能反转或放宽已冻结 oracle。
- source lane 专测 fault/corruption/SQL invariant；exact-wheel lane 只用公开 API。更新 Task 5/6/7 exact identities 与 evidence
  mapping，旧 pin 保留 lineage 但不冒充当前 candidate。

### Task 6 — 全量门禁、可复现 wheels 与事实源回写 [HM-AC-7/8]

- 三仓各跑基线对照后的 full unit/integration、ruff/mypy/build/twine/REUSE（按仓库已有命令）；两次 clean build 比较 canonical
  wheel bytes/hash，clean venv 重跑 public smoke。
- 原始证据只写 `.local-test-evidence/2026-09-01/semantic-relations-*`，Git 只提交结论、run/scenario ID、relative index、SHA-256。
- 更新 Memory/Harness `ARCHITECTURE`、`PROJECT_STATUS`、API docs/changelog 与本 program S3 Task 6/7 状态；运行 updated
  `plan_test_gate.py finalize`。真实 LLM 质量仍保持 `NOT_RUN/BLOCKED`，不得用确定性关系测试冒充。

## 8. AC / obligation / evidence 映射

| 条款 | 实现任务 | required evidence |
|---|---|---|
| HM-AC-2 | 1,2,4 | strict v5 round-trip/rejection；relation canonical state；invalid/fault zero partial |
| HM-AC-6 | 3,4,5 | exact-wheel 2+1 smoke；suppression/reopen 0 edge；agent influence zero |
| HM-AC-7 | 2,4,6 | invocation/decision/mutation/root/trace owner chain；sealed audit preservation |
| HM-AC-8 | 1,2,5,6 | fresh schema idempotence；cross-wheel contract；reproducible artifacts/full regression |
| FAIL-RELATION-INTEGRITY / HM-TO-R9 | 1-6 | malformed/cross-principal/stale/fault/corruption matrices and public value smoke |

## 9. 交付与回滚边界

- 发布顺序：Harness protocol candidate -> Memory implementation candidate -> testcase repin；本次不 push/tag/publish/merge。
- rollback 先分类：binary/config、可重建派生索引、manifest 明确证明从未写入真实 Session/Turn/Tool/LLM evidence 的
  synthetic-only DB、含任一受保护 raw evidence 的 DB。只有 synthetic-only DB 可由测试环境回收；任何 evidence-bearing
  schema-7 DB 永不删除、覆盖或降级，必须原样保留并记录 schema/checksum/wheel/commit refs，通过既有受控审计边界可读；
  旧 wheel 需要运行时新建另一个数据目录。rollback oracle 比较受保护表 row count 与 canonical content hash，覆盖 retention、
  maintenance、test cleanup 后必须逐项不变。
- 若挑战或 spike 证明同表 domain/owner 不能满足 FK/immutable root 约束，视为结构根因，回到计划修订而不是用 nullable owner、
  magic kind 或 UI 特判绕过。
- 若 exact public Manager API 无法在不暴露 private authority 的情况下完成最小 seed，先修公共 plan/write contract；不得给
  testcase 新增私有 SQL 或测试专用后门。

## 10. 关键技术假设与 spike

- `SPIKE-RELATION-ENDPOINT-DAG`：用最小 source spike 验证“异类型 created-by endpoint 可被独立解析而不破坏 operation
  target 的同类型 revision 约束”，并覆盖 missing/forward/non-CREATE producer。
- `SPIKE-RELATION-DOMAIN-CHECK`：用临时 SQLite schema 验证 evolution owner=NULL、knowledge owner=exact revision、
  非法混合拒绝，并证明 `(evolution, relates_to)` 与 `(knowledge, applies_to)` 受各自 domain/kind/owner 约束；
  命令、DDL 和实际输出回写本节。spike 只验证结构可行性，不滚成业务实现。
- W3C 资料只支持建模选择，不构成项目运行证据；最终以 exact-wheel public smoke 和 durable reopen 为准。

### Spike 实跑记录（2026-09-01）

- 脚本：`spikes/run_relation_spikes.py`，SHA-256
  `8201bf2692bb35d68ed914fd2418fe27187d5d4d9848ce3e38eb58a0d76d3468`。
- 命令：
  `python3 plans/2026-08-29-human-memory-digital-twin/increments/2026-09-01-semantic-relations/spikes/run_relation_spikes.py`
- 实际结果：`SPIKE-RELATION-ENDPOINT-DAG` 接受 Semantic CREATE + Procedure CREATE 作为跨类型 relation endpoints，
  同时拒绝 `missing_dependency`、`forward_reference`、`non_create_producer`、`revision_target_type_mismatch`，证明 endpoint
  DAG 规则不需要放宽原有 revision-target 同类型规则。
- 实际结果：`SPIKE-RELATION-DOMAIN-CHECK` 同时接受 `(evolution, relates_to, owner=NULL)` 与
  `(knowledge, applies_to, exact owner)`；拒绝 `knowledge-owner-null`、`evolution-owner-present` 与 owner FK 不存在，证明
  单表现有结构可用 domain + exact owner 清晰表达两类关系，无需改名或新图数据库。
- 限定：spike 使用最小 Python/SQLite 模型，只验证决定方案成败的结构假设；不替代生产 schema、public API、fault、reopen
  或 exact-wheel 验收。
