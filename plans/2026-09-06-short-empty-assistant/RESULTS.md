# 空 assistant 短期完整组：原红、源码与真实运行载体验收

最后更新：2026-09-06。自有 `feat/short-empty-assistant`，clean基线6361edca，业务源码固定17aebdec14356393349ce4cb43fd5309c21fde1d后没有再次改动。版本保持WIP0.6.14；未分配615、未build/install/改Host pin/发布。Dirac尚无反馈；本轮依据主恢复必要测试的明确指示完成红绿，独审仍单独待办，不冒称已独审。

## 实际结果

- 原installed M614（两个受影响文件精确等于6361edca）上，新用例中的空assistant完整工具组及全空assistant组均在公开注册时报原 `authorized public text must be non-blank, bounded, and contain no NUL`；非空工具组正控通过。
- 17aebde业务源码下，首批9专项有8通过。剩余UTF-8超限项实际在更早的S1公开ingest门触发 `MemoryLimitError: evidence_payload_requires_controlled_blob_ref`，测试错误地只期待short注册阶段拒绝。仅修测试：先确认公开文本解析仍按1MiB限制拒绝，再确认public ingest更早拒绝；不绕入库门、不修改业务限制。该项定向重跑通过，另9项必要邻居通过；其余已绿专项没有重跑。
- 只读主已固定Host d8a985c2的原空assistant用例 `[True]`，用本树Memory源码作为SDK开发回归载体，真实运行11个Harness turn及两次工具调用的6项完整首组。原空父assistant保留、tool parent2/4、outbox、公有注册、非空short命中、重开引用一致、tool-source遗忘后整组无命中均通过，4.49秒。没有重复主已绿的非空组/21项交叉。

共9项专项分批通过、9项必要邻居通过、1项真实Host执行载体通过；不合并宣称某次19项全套重跑。H073/Memory公共API的fixture验证和实际Host执行载体分开计证；后一项仍是显式Memory源码overlay的开发证据，不是installed后继组合验收。没有真实网络Provider、模型或native；没有填placeholder、删消息或改变recent10/保留期/预算/阈值。

## 身份与资源

所有批次借用主M614既有解释器。r1只给Memory仓库根进入PYTHONPATH并断言导入installed路径及两文件原hash；r2/r3给本树src，r4给本树src及主Host/backend，均断言Memory实际导入路径及记录源码hash。

r4执行前后核对Host HEAD及7个相关源文件、资源入口hash完全一致；Host树没有本叶改动。执行后再核installed两个受影响成员仍等于6361edca，未写site-packages。本文不重复冒称对全部安装成员重新验真。

默认共享OS锁及2048MiB/180秒，未换lockfile。r1/r2使用原145入口；r3输出已包含主新增磁盘阈值，其执行后查到入口HEAD d739dcf781ae1ba759de38ccab97aa67bf01c549；r4执行前后固定同入口SHA `26e3c7bff077cbd36c8eae28cd1da02f8b1a27b85e48b445ed9e5ee75ea2f798`。不把r3未在执行前采集的入口hash冒称为精确预检记录。默认磁盘准入1024MiB、停止256MiB未覆盖。

四组remaining_group_members为空、cleanup_error为null；ps另核四个PGID均无行，测试槽已释放。开始可用3853MiB，完成3807MiB，本叶目录35MiB；未删除raw或缓存。原红/测试预期失败原件全部保留ignored，不提交Git。

| 批次 | 结果 | PGID / elapsed / 峰KiB |
|---|---|---|
| r1-installed-red | 2失败、1通过、6未选；原installed反例 | 42156 / 1.102s / 124480 |
| r2-source | 8通过、1测试预期错误；1.23秒 | 42225 / 1.527s / 115024 |
| r3-targeted-neighbors | 10通过；1专项修正+9邻居，1.01秒 | 42471 / 1.296s / 120480 |
| r4-real-group-source | 1通过；原Host空assistant真实执行载体，4.49秒 | 42531 / 5.147s / 182560 |

## 必要命令

下列共同变量只缩短复现描述，未创建新环境。所有新重跑必须换批次目录。runner为同一个默认锁入口，禁止绕开；原命令/stdout/资源JSON在对应本地批次。

```sh
MEMORY_TREE=/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources
HOST_TREE=/Users/denny/projects/simple_harness-primary-candidate
SDKPY=$HOST_TREE/.local-test-evidence/2026-09-06/primary-m0614/venv/bin/python
RUNNER=/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py
EVIDENCE=$MEMORY_TREE/.local-test-evidence/2026-09-06/short-empty-assistant
```

共同形式：`PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=<下表> "$SDKPY" -B "$RUNNER" --evidence-dir "$EVIDENCE/<batch>/resource" --rss-mib 2048 --seconds 180 -- "$SDKPY" -B "$EVIDENCE/run_checks.py" <installed或source> -p pytest_asyncio.plugin -q <选择> --basetemp="$EVIDENCE/<batch>/stores"`。

| 批次 | cwd / PYTHONPATH / mode | 选择 |
|---|---|---|
| r1 | Memory树 / Memory树 / installed | tests/integration/test_short_empty_assistant.py -k 'complete_tool_group or empty_only_group' |
| r2 | Memory树 / Memory树/src:Memory树 / source | tests/integration/test_short_empty_assistant.py |
| r3 | Memory树 / Memory树/src:Memory树 / source | 下列10项 |
| r4 | Host主树 / Memory树/src:Host主树/backend / source | backend/tests/memory/test_primary_tool_message_ingestion.py::test_complete_six_item_tool_group_is_indexed_and_forgotten[True] |

r3选择（有方括号的节点参数需shell引用）：

```text
tests/integration/test_short_empty_assistant.py::test_original_blank_nul_and_utf8_byte_limits_remain[utf8-over-limit]
tests/unit/test_short_horizon_v5.py
tests/integration/test_short_horizon_repository_v5.py::test_pointer_only_projection_and_repository_owned_generation_reopen
tests/integration/test_short_horizon_repository_v5.py::test_unapproved_registration_is_durable_but_never_projected_and_cleanup_is_derived
tests/integration/test_short_horizon_repository_v5.py::test_projection_fault_rolls_back_derived_rows_and_audit
tests/integration/test_short_horizon_repository_v5.py::test_forged_routing_metadata_is_rejected_and_audited
tests/integration/test_short_sources.py::test_exact_sources_one_clock_and_reopen
tests/integration/test_typed_short_sources.py::test_exact_duplicate_domain_clock_and_reopen
```

## 固定指纹

CONTRACT的初始17aebde测试hash保留为历史；本次仅超限测试预期修正，业务两文件hash保持相同。原始证据路径以下均相对本树，所有raw ignored。

| 路径 | SHA-256 |
|---|---|
| src/simple_harness_memory/core/short_horizon.py | b8acb62bab6138f92ce1586b588c22b1abd2338c94cfa24207144c93e23df8f5 |
| src/simple_harness_memory/backends/sqlite_v5.py | 89a8f4385770d114803022de8c72d8cc265b0da232287a7a3d1282fa970fd211 |
| tests/integration/test_short_empty_assistant.py | 849f934f746b03170275198e637da41ddb71aa7340a5e0d7e497d0db8e74a632 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r1-installed-red/resource/command.log | 1025e82343a6507c5aed7e08e8ac6c42768225fd570f777864a1300685aa6031 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r1-installed-red/resource/resource.json | 2cf3d43c497078bcffccec1894a0c2cf1d2efc8b9dcab93a793a9d13d8cc79da |
| .local-test-evidence/2026-09-06/short-empty-assistant/r2-source/resource/command.log | f0d96a4848f73ebc7014daf250b01ed9956e271f38b97f76936fe40f6e05f417 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r2-source/resource/resource.json | 175873663912b2babf63ad7ce29e7e72cf654f506ca881341b67b4a256afcbc7 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r3-targeted-neighbors/resource/command.log | a36035f3fee8bfc3c515cdd3fe30cd8dab68d8f26229423ff43440564549a9cb |
| .local-test-evidence/2026-09-06/short-empty-assistant/r3-targeted-neighbors/resource/resource.json | 4971a1b0f1cccc1d3a56b9bc8f47034f1bfb196b1ca59f186247d786c23439d7 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r4-real-group-source/resource/command.log | 250575adbd4fe7a9007215cabb679dd1a14e6ebe7f36731792ce21087b8ab8dc |
| .local-test-evidence/2026-09-06/short-empty-assistant/r4-real-group-source/resource/resource.json | 12916203cd7deb35d59327dd17bc30cc277c8e94ad48414b696db11bad45da61 |
| .local-test-evidence/2026-09-06/short-empty-assistant/run_checks.py | bdee884d3ceb7224af6838de6b2cf57f09e43c795688906bb7ce59a42c00464e |
| .local-test-evidence/2026-09-06/short-empty-assistant/r4-real-group-source/source-before.json | 542e31fa3695b36c2133d52f347e69bd108eeb87301283a2e673c45e4825f5c1 |
| .local-test-evidence/2026-09-06/short-empty-assistant/r4-real-group-source/source-after.json | c715a3c9eecf0473ade56b7166f7661c7da95e12d107044b583aaedd26b579b4 |
