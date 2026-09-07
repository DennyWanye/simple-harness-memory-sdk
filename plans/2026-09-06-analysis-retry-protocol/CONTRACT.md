# failed analysis retry 保留完整语义输入

2026-09-06。自有现存树 `simple-harness-memory-sdk-typed-short-sources`，分支 `feat/analysis-retry-protocol`，base `ed9996f9bc507b34f7e995a900fe956bee6d7d87`。后继源码 WIP `0.6.18.dev0`，未构建制品；冻结0.6.17 wheel、原始证据和任何 installed 环境均未修改。原 Procedure 只读目录保留独立 untracked。

## 实际边界

Host `evidence_set_key` 包含除 job_id/attempt/idempotency_key 外所有 request 字段。Memory 0.6.17 的 `core/jobs.py::DurableMemoryJobRunner.run_once` 对普通 executor Exception 调用 `fail_analysis_batch`，把旧 batch/attempt结算failed、job改pending；`backends/sqlite_v5.py::claim_analysis_batch` 下一次使用当前config建立新 request。v3 response已经在Host durable时，版本／预算变化会绕开旧复用键，重复Provider调用。取消／expiry reclaim是另一分支，不能代替本修复。

只改 `claim_analysis_batch` 及其私有读取辅助函数：pending队列首项若有历史attempt，核实际最新failed attempt、batch及完整成员绑定，按旧member ordinal读取原队列；新job不夹入旧cohort，重试不被新batch_size拆开。完整成员都须pending、仍归原attempt且已到期；不复活dead_letter/applied/被别的attempt占用成员，成员被拆分则显式拒绝，不能伪装成原exact replay。

读取原MemoryAnalysisRequest并验证request_hash、job/attempt/principal/水位及逐member evidence/hash/ordinal；再按原生产入场流程重新核对当前持久evidence payload、Run、subject、disclosure和model lineage。通过后使用原完整request，仅替换本次job_id/attempt/idempotency_key，保留三版本、budget、schema及所有其余字段。无lineage的旧回落provider/model/config同样保留原值，不套新worker配置。

旧failed request/attempt/event原值不重写；新batch拥有自己的新request_hash及正常lease/validator/delivery/application/audit链。`core/jobs.py` 无需改，schema/receipt/wire均不改。新fresh job单独按当前v4配置与预算生成新请求；Host哈希算法和各合法校验不删键、不放松。

## 必要控制（源码固定后执行）

- Host原 `[3-True]`：真实v3 response已持久→普通派生异常→v4 config，旧members完成应用且零新增Provider；保留旧原红。两处测试修正及两个取消恢复新控单独验，不重跑旧24绿。
- SDK三项新控制：两成员旧batch、改版本/预算/provider/batch_size并加入新job，旧完整语义输入和顺序不变，新job独立使用新配置；原持久budget/hash或member证据改变时拒绝，不新增claim、不调用Provider。

这份源码尚未验收、独审或build。测试用默认共享资源入口，SDK源码overlay与真实installed制品证据明确区分；新版本制品待主／Dirac确认固定源码后另行协调，不把M617改名替代。
