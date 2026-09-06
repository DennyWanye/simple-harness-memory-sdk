# 空 assistant 短期消息组：最小源码契约

最后更新：2026-09-06。自有Memory树 `/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources`，分支 `feat/short-empty-assistant`，clean起点 `6361edca06c3c962986a7600410a0d6a0b427a13`。当前仅源码候选；按主指定 source→Dirac→145同锁红绿的顺序，待源码独审，尚未测试。版本仍0.6.14（WIP614），不分配615、不build/install/发布，不改Host WIP或任何installed文件。测试槽未占用。

## 确定的接口不一致

H073公开 `authorize_conversation_public_text`（主M614既有环境 `simple_harness/runtime/evidence_protocol.py:1695`）从已接纳源的唯一授权pointer派生UTF-8 hash。其 `_derive_authorized_public_text_binding:1544` 要求字符串但允许空字符串；identity normalization保留原字节。`ConversationEvidenceRegistration`继续核对角色与source_kind、metadata/receipt/envelope/item authority绑定；tool metadata只接受前序parent ordinal（同文件614），本叶不替换Host的真实工具终态来源验证。

M614 `MemoryManager.register_conversation_evidence`（core/manager.py:188）委托 `SQLiteHumanMemoryBackend.register_conversation_evidence:1817`。后者在真实写事务、verify registration和ingested evidence等式后调用 `resolve_authorized_public_text`。core/short_horizon.py原67行 `_bounded_non_blank` 被无角色区分地用于授权正文，导致合法空assistant在持久注册前失败。不是召回预算、recent10或Host工具parent丢失。

主原红：Host `.local-test-evidence/2026-09-06/tool-message-v2/r4/resource.json`，PGID40972/exit1/4.718秒/峰215792KiB/无残留。该目录本次只发现resource.json，没有command.log；具体异常由主反馈及实际源路径一致支持，不虚称本叶重跑过。只读Host WIP `backend/tests/memory/test_primary_tool_message_ingestion.py:44`：11个真实SDK turn，首组user/assistant/tool/assistant/tool/assistant完整6项、tool parent2/4、outbox/public registration/short/forget/reopen。该Host实际工具执行证据仍由主负责，本叶公共API测试不会冒称真实工具执行。

## 最小修复与不变条件

- `resolve_authorized_public_text`仅对 `role is ASSISTANT` 且正文恰为 `""` 保留空字节；随后仍核原授权text hash。其他输入仍走原 `_bounded_non_blank`，包括空/空白USER、空白assistant、NUL、超过1,048,576 UTF-8字节的正文。通用identifier函数不改。不是把空消息改为placeholder，也不删除registration或改变ordinal。
- 独立纯投影 `build_short_horizon_chunks` 和SQLite重建投影均在完整group检查后跳过全部正文为空的组，避免 `assistant: ` 角色标签形成伪query hit。registration仍可持久回读；真实recent10和group计数规则不改。
- 完整组继续核共同主体/primary/group/sequence/count/manifest、全部ordinal和唯一evidence/registration。既有backend `_short_horizon_group_is_complete:15105`、元数据绑定和source visibility完整回读逻辑不改。既有非空chunk bytes/hash/wire、DDL、阈值均不改；含空assistant的新组按全部原项形成精确内容/hash/来源。

## 待运行的必要验收

新增 `tests/integration/test_short_empty_assistant.py` 9项：完整6项tool-parent组空/非空正控2；全空assistant组不产生角色查询命中1；空/空白USER、空白assistant、NUL、UTF-8超限5；空文本仍核hash及identifier1。

前两项用H073公开authority/registration DTO和Memory公开ingest/register/rebuild/recall/source/suppress API在真实SQLite上运行。使用明确Host authority fixture（tool terminal link也是fixture），不伪造Memory查询或selection receipt；与主Host真实SDK工具执行层分开。全部6项ordinal/role/registration hash、parent2/4和原空字符串保留；纯投影与数据库投影字节一致、public重开幂等、tool-source遗忘后整组及source refs消失。全空组仍完成注册但projection0/query0。

先用原installed M614运行同一新测试得到确切原红，随后用本树 `PYTHONPATH=src` 做明确的Memory开发源码测试；两者均借用主M614解释器，不改installed。必要邻居仅short_horizon unit/repository和short_sources链路；Host WIP11turn实际producer回归由主固定该源后接续，不能把Memory fixture绿当Host E2E绿。

所有执行必须经 `/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py`（145默认共享OS锁），2048MiB/180秒，独立新 `.local-test-evidence/2026-09-06/short-empty-assistant/<batch>/`。BUSY不换锁，不起模型/native/新环境。原始数据不进Git。以下均未执行，未作PASS或质量完成结论。

## 固定源码指纹

| 本树相对路径 | SHA-256 |
|---|---|
| src/simple_harness_memory/core/short_horizon.py | b8acb62bab6138f92ce1586b588c22b1abd2338c94cfa24207144c93e23df8f5 |
| src/simple_harness_memory/backends/sqlite_v5.py | 89a8f4385770d114803022de8c72d8cc265b0da232287a7a3d1282fa970fd211 |
| tests/integration/test_short_empty_assistant.py | 0b9a114b9783272a5201153521b0dd3f6f9ebef21cafa6337d1716480eb3d40b |
