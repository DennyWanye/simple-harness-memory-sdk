# 本轮输入用途公共口（限定源码片）

最后更新：2026-09-06。分支feat/current-input-visibility，基冻结M618 d8d80d5c；业务a8c8c38。Host c2fd8fcd真实消费者与源码已获Dirac限定ACCEPT；主分配统一版本前不改version/public snapshot、旧wheel或pin。

`build_human_memory_v7(..., current_input_authority=port)` 注入真实Host事实。`MemoryManager.check_current_input_visibility(*, principal, disclosure_context, binding: CurrentInputBindingV1, bindings=None)` 检查一个完整当前USER项；完整有序tuple为1..256个原HistoryBinding，必须包含当前exact pair。SDK核canonical S1、真实公共admitted item/逐字节span、注册owner及Host配置完整principal、原子origin和exact用途；Host外部port不在MemoryTX内。随后复用原history reader，同一个实际snapshot仅对当前pair适用输入例外，parents/其它evidence/typed/short继续原门。无Host SQL、无新业务ledger、无旧普通API放宽。

输入 `CurrentInputBindingV1(turn_id, request_id, evidence)`；port `resolve_current_input(*, principal, disclosure_context, binding) -> CurrentInputAuthorityV1|None`。输出 `CurrentInputVisibilityV1` 的 invocation_input_allowed仅为模型本轮输入；final_audience_disclosure_authorized始终False。含实际history_visibility及epoch/policy/request/snapshot hashes；Host不得自拼SDKsnapshot。配置/聊天不能重分类健康家庭旧记忆。legacy ingest actor/actor placeholder不能在Host冒领完整配置principal。

哈希沿既有E(domain,payload)=SHA256(UTF8(canonical_json({domain,payload})))。新request域memory.current-input.request.v1绑定principal的asdict、disclosure.to_json、binding_hash与完整有序bindings逐个memory.history.binding.v1哈希。新binding/authority/visibility/observation各有memory.current-input.*.v1域；无NUL或旧hash变更。

返回或异常attachment `CurrentInputObservationV1`：schema_version=1、invocation_ref_hash、request_hash、snapshot_hash、outcome、observed_at、operation=check_current_input_visibility、persistence_status=host_persistence_unverified。结果outcome为input_usable/input_denied，拒绝/异常/取消为rejected/failed/cancelled；只实际结果有snapshot_hash。现observability sink捕获memory.current_input.observed；Host既有operation-audit.db直接捕获并独立校验wire，SDK字段不改称已持久授权。此方法不冒称原sealed OA1 reader或全操作coverage已覆盖，usage/price未提供。

## 验证与剩余

Host源树 `/Users/denny/projects/simple_harness-typed-recall-context-use-full`：原8消费者绿复用；本轮9新unique分批5+2+2通过（2.20s、3.45s含两oracle失败的批次、2.42s仅两红重试）。实际SDK placeholder ingest、ordered batch/current-only例外、Host调用审计缺能力/取消/写失败；实际ForegroundRuntime/main checker/public reservation/Adapter guard/MockTransport正常1send，字节/完整policy读后token或claim变更均0send。Dirac独立只读最终限定ACCEPT，无新增P0/P1。PG10680/10822/11015/11195均退出remaining[]cleanupnull；原fixture和oracle层级失败保留，未重跑旧绿。

原raw仅Hostignored `.local-test-evidence/2026-09-06/nonself-input/{new-r1,physical-r1,physical-r2,physical-r3}`。精确可复跑命令/控件/失败分类见Host `plans/2026-09-06-nonself-input/RESULTS.md`，完整契约同目录CONTRACT.md。H078/S0313既有installed依赖，Memory为本树source overlay；不是新wheel安装或native/模型质量。unknown recall/short只负控，不称已物化typed/short全隔离。240本轮USER+public材料两个独立item尚未接，本片只一个完整item，不做最终正文披露授权。

组合时与Singer f82c2b8 Procedure段独立合入：本片manager/port/root新input入口、sqlite_v5 constructor及history旁wrapper、history_visibility共享检查与三个新input模块；他的Procedure验证段不覆盖。本次无DDL/migration，后继版本与公共exports snapshot由主组合时固定。
