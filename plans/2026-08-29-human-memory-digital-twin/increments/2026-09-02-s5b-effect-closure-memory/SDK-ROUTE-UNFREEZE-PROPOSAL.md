# S5b Harness route 恢复限定解冻提案

最后更新：2026-09-05。状态：**用户已批准限定解冻；SDK 源码修复/review 已通过，新候选生产复验未闭合**。

批准原话（由主执行者在本任务转述）：「我批准你进行，另外，我不喜欢你把token和资源浪费在反复的确认上」。
UTF-8、无末尾换行 SHA-256：`e77e066868134fa60789c3835c2ca376418bf61f6058fdb720ac93d68d19e343`。
批准对象为本提案下述唯一 SDK 例外；批准前提案 SHA-256：
`cc1ad96a7c6865e14ad8a9860d0ffcb7f1a0fc98e5e6be64237ad37888e04141`。
同次批准另含 S3 契约修订，另线执行；本次文档/账本工作不改原始 oracle。
授权持续有效，已批准范围内实施与复验不再重复确认；批准不等于 P1 修复或验收通过。

## 问题与已验证事实

原 acceptance §范围排除及架构决策冻结 Harness SDK 0.7.1。当前真实生产控制 WS
`queue.enqueue` 使用 Host `26b50ee81e7ccd290e8da6c88d0053d7d8f8ecb1`、Harness 0.7.1、
Memory 0.6.3、gpt-5.5，在合法 `context_route(continue_active)` 后，后续
`task_scope_update` 授权已接受，但 SDK 恢复失败：
`ReAct checkpoint initial Context route differs from start snapshot`。

Host Run `142bdb3b-9026-5264-b244-69e94bf0e388`；SDK Run
`product-sdk-84bb5dcf5cd8e1888192c9a743aee45294849ec9783d049c2cc4c4f4005d4e13`。
README 实际由 1.1.3 改成 1.2.0，但 Host terminal=FAILED、closure pending、
accepted analysis plans=0、memory heads=0；第二 root 未运行，S1 不通过。

独立审查 Popper 用安装版 SDK 与真实数据库副本验证：checkpoint v0 恢复成功，v4/v49
均抛同一异常。三者 hash 有效，Run/TaskScope/binding revision 相同，Context effect 已成功。
`react_checkpoint.py::_require_route_match` 把可变 current route 与 initial 全等比较，
而 `react_loop.py` 合法地更新 current；Kernel 从 durable StartSnapshot 恢复 initial 是正确行为。
这属于 SDK P1，不应由 Host 隐藏路由工具、删除 initial receipt、重写 checkpoint 或约束模型规避。

## 已批准的唯一 SDK 例外

允许修复 **initial/current route 的恢复校验，以及该修复必需的 SDK port、回归、候选版本和 Host pin**。
其余 Harness 功能继续冻结；原业务 AC、权限、预算、两 root 真 Provider 验收和 S5c/S6 义务不变。
S3 契约修订由同次批准另行承接，本提案不改写其原始 oracle 或历史证据；不包含发布、push、tag 或失败 Run 的自动复活。

## 实施方案与兼容要求

1. 保持 immutable initial receipt/hash 与 durable StartSnapshot 的绑定，拒绝恢复输入改变启动身份。
2. 独立恢复当前 route，验证 receipt/hash、Run、route-state 和合法 Context-control 来源。
   优先通过明确 SDK port 复用现有 StartSnapshot/effect/checkpoint authority；不新增重复账本。
   不能仅删除旧比较，也不能凭 `origin=context_tool` 放行。
3. 保留读取 StartSnapshot v7 和 checkpoint v6。若实现必须新增持久字段，则显式版本化、
   给出迁移/旧记录读取测试并独立审查；不隐式回填旧数据，也不降低旧版身份校验。
4. 保留 0.7.1 wheel 原字节，以新候选版本构建；exact-wheel 安装、来源/hash 校验后接入 Host。
5. 已失败业务 Run 原样保留；使用新 root 重测，不把已发生文件变更解释成任务成功。

## 必须通过的决定性用例

- 真实 SQLite：initial A → 成功的合法 current B → close/reopen → 用原 A 恢复，保留 B。
- 负例：换 initial/binding、坏 hash、跨 Run、无路由 checkpoint 冒充初始化、无合法来源的 B，均拒绝。
- 完整 runtime：Host initial → 真 context_route → 后续工具 REQUIRE_USER → exact approval →
  恢复完成，覆盖进程重启；已完成 route/provider 不重复执行，待授权工具仅执行一次。
- Host 生产 ports 装配回归：保留 initial receipt 和工具曝光，source/installed-wheel 均可用。
- 受影响便宜层与独立 review 全绿后，以新候选跑 A14 两个独立 root 的真实
  queue.enqueue → 文件效果 → closure → terminal outbox → analysis/materialization。
  A15 的 next_turn_typed_recall_hit 仍为 NOT_MEASURED，明确交 S5c/S6。
- 原生 UI S8 在新候选上重测；随后恢复原 S5b 所有 required 场景与机器门，不能跳过。

## 本地证据与停止点

Host 证据根 `.local-test-evidence/2026-09-05/human-memory-resume/`：
`tools/HANDOFF-SDK-ROUTE-FAILURE.md`、
`tools/a14-20260905T084624-dt4fjclb/root-1/route-failure-handoff/`，
其 `original-evidence-sha256.json` 绑定原 DB/WAL、执行脚本、日志和文件 diff。
原始材料只在本机 ignored 目录。r5-local 已登记 S1 FAIL 与 A2 `a2-001`。
生产 backend 已停止，18110 空闲。本次仅回写文档并追加证据 metadata，未启动 Provider/full-audit/finalize，未改代码或 pin。

实施次序：先回写本限定例外与独立审查后的接口设计，再由主执行者实施上述回归驱动修复；
若发现必须更改业务契约或扩大 SDK 范围，再停止该部分并报告具体差异。

最新进度：SDK 源码修复已提交 `2b8428465cbd41032ba024a0b7199183161f5ecd`（candidate 0.7.2）；主执行者报告真实 runtime route→WAITING→授权重启新增 2 用例先红后绿、独立 review 4 passed。Host 正在 revendor/安装，尚未完成新候选身份核验及 A14/S8；本地 S1 FAIL/S8 FLAKY 保留。
