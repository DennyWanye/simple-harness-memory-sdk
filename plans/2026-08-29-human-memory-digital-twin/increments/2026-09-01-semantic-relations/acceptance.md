# 增量验收：Semantic Relation Memory

> 状态：APPROVED / FROZEN（2026-09-01）
> 父事实源：`../../acceptance.md`
> 用户批准：`采用，记得使用更新过的plan-test skill来继续做`
> 批准消息 SHA-256：`ff036f01b5dc3b6860f61cd2771846e8416480c840119d86f26202842490c416`

## 主要矛盾

关系不能只是 UI 画出来的一条线。它必须是一条有证据、可修订、可冲突、可逻辑遗忘、可审计的长期
Semantic Memory，同时普通数字孪生体只能投影当前允许展示的关系。

## 本增量范围

- Harness 公共 mutation schema v5：显式区分 Semantic claim/relation，只开放 `applies_to`，使用 exact existing 或
  same-plan created endpoint refs，并对版本、依赖、类型和自环 fail-closed。
- Memory fresh schema v7：保存 canonical relation memory 与同事务 derivative knowledge relation row；关系和端点
  共用主体、evidence、classification、epistemic、revision/conflict/suppression 和 immutable audit 状态机。
- ordinary twin graph：relation memory 不重复成 node；只有 owner 与两个 exact endpoints 都 eligible 时显示 edge。
- exact Harness/Memory wheels 的 package-root 公共 API 黑盒验收、40-case integrity/fault/replay/lifecycle/corruption
  矩阵、两仓全量回归、可复现 wheel 与架构事实源回写。

## 明确不在本增量

- Host 对 Harness parser failure 的 durable pre-admission audit 实装；接口已冻结，留待 S5，状态必须明确为
  `NOT_RUN/BLOCKED_UNTIL_S5`。
- 真实主模型的语义提取质量、UI/Agent 集成、图谱美化、旧数据迁移、新 relation kind、图参与 recall/rank/Context。
- 发布、push、tag、merge 或修改主 worktree。

## MUST AC

| ID | 验收条件 |
|---|---|
| HM-AC-2 | strict v5 公共协议能表达并验证一等 Semantic relation；Memory 只接受有证据、合法主体、合法 exact endpoints 与合法状态的 plan，任何失败不得产生半状态或孤边。 |
| HM-AC-6 | exact wheels 经 package-root 公共 API 在一个原子 plan 创建两个 canonical nodes 与一条 `applies_to` edge；relation node 数为 0；relation 或任一 endpoint 被 suppress 后 edge 为 0，close/reopen 不复活。 |
| HM-AC-7 | canonical relation revision、derivative row、receipt/manifest/trace 与 stable reason code 可关联；旧 evidence/row 永不物理删除；图谱只作展示，不进入 recall/Context。 |
| HM-AC-8 | fresh schema v7、重放、事务故障、生命周期、腐败重开与跨 exact-wheel consumer contract 全部 fail-closed/可恢复；两仓 full pytest、ruff、mypy 通过，wheel 两次构建字节一致。 |

## 测试义务

| obligation_id | 决定性证据 |
|---|---|
| HM-TO-A2 | TC-HM-08 rev4 与 TC-HM-12 rev3：公共 v5 plan、canonical relation、严格拒绝。 |
| HM-TO-A6 | TC-HM-12 rev3：exact-wheel 2 nodes + 1 edge、relation-node exclusion、suppression/reopen 0 edge。 |
| HM-TO-A7 | TC-HM-08 rev4 与 TC-HM-12 rev3：receipt/owner/root/trace lineage、raw evidence byte-identical。 |
| HM-TO-A8 | TC-HM-08 rev4 与 TC-HM-12 rev3：两 wheel 公开契约、40-case 故障/重放/重启、全量回归。 |
| HM-TO-R9 | TC-HM-08 rev4 与 TC-HM-12 rev3：非法 kind/type/dependency/主体/端点/状态/分类、事务故障、corruption、suppression 矩阵。 |

## 最小价值动作

在 fresh clean venv 中仅安装 exact Harness/Memory wheels，runner 只能 import 两个 package roots，通过公共 Manager
提交三 operation plan；结果必须精确为 2 nodes、1 `applies_to` edge、0 relation node，随后 relation/endpoint
suppression 与 close/reopen 均精确为 0 edge。任何私有 import、直接 SQL、source checkout import 或测试专用后门都使
该 lane 失败。

## 完成定义

1. 上述 4 条 MUST AC 与 5 条 obligation 都有当前 run 的新鲜根证据，不继承历史 PASS。
2. public value、40-case integrity、两仓全量 regression 三个 required scenario 全部 PASS。
3. 独立完成审计无 P0/P1，机器 `finalize` 返回成功收据。
4. 两 SDK 的 ARCHITECTURE/PROJECT_STATUS/CHANGELOG 已同步；阻塞的 Host/LLM 后续门不得被写成 PASS。
5. 所有原始测试证据保留在 ignored `.local-test-evidence`，不得删除；Git 只保存结论、索引和 hash。
