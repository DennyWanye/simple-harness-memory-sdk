# 普通召回最终受众约束

最后更新：2026-09-06。自有feat/disclosure-audience-binding基于43be680，业务修复d7cb3ca经Dirac限定ACCEPT；候选源码27dceffe05247415ba9b48a55e865a0faba37629，版本0.6.14。后继只加版本及公共builder/零候选查询断言，没有重写0.6.13源f2a6a706或任何旧wheel。schema/数据格式/哈希域未变，无迁移/发布/Host pin变更。

## 实际修复

ordinary与candidate两层都要求当前接收者和最终受众处于同一已支持范围：self/self、household/household、task_collaborator/task_collaborators。原始字符串拼写不同不再误拒合法协作者语义。当前SELF不能凭这一标签为外部、公开或协作者最终受众查询本人私密记忆；全局不匹配在候选查询前拒绝。

这是一项保守修复，不提供更广受众授权。外部/公开用途仍不支持；非self原始历史、classification、purpose、recipient_id、来源/遗忘/到期门保留。collaborator检查只证明通过错误枚举门后仍需真实binding，不称第三方公开材料已经可用，也不称C12/240或实际Host物理出站通过。

## 源码与安装验证

- 旧源43be680上4个真实公开Manager操作反例全部失败（0.83s）：3个SELF但不同最终受众的query仍返回个人semantic；合法collaborator字符串在history误拒。此红保留。最初本批pytest DB由pytest默认目录生成，之后只移动本批pytest-1300六项到ignored r1-db，未删除证据或碰别批。
- d7后必要13项通过（1.10s）：上述4项、原分类/状态矩阵、short精确binding/owner/disclosure与原forget/history。pytest DB已显式置于ignored r2-db。
- 版本dff3fbe明确分配0.6.14；测试后继27dceff将3项构造改为公开package-root builder与真实admission，而不是直接backend fixture，并加零candidate query断言。业务修复未改变。
- 两次hatchling1.32.0 wheel构建字节一致。通过uv离线无依赖安装到全新Memory target，逐字节核对全部76个成员（仅排除RECORD），包源码也与wheel一致。借用既有exact H073/dependency解释器，H073的169个wheel/installed成员全匹配。不是新建完整venv、也不是Host环境已替换。
- 安装consumer以-I/-B启动，无SDK源码路径；使用源码中的测试/fixture作者代码作为调用方，实际Memory包从独立安装target导入。4项公开builder/admission/query/history测试全部通过（0.47s），SELF不同最终受众明确0候选查询/0结果，本人正控仍实际命中；无模型/Provider/native。

| 批次 | PGID | 峰KiB | 耗时 | 退出/残留 |
|---|---:|---:|---:|---|
| r1原红 | 33247 | 137184 | 1.093s | 1/无 |
| r2源码 | 33324 | 113008 | 1.331s | 0/无 |
| 两构建/安装/consumer | 34634 | 135888 | 1.308s | 0/无 |

全部经145默认共享OS锁、2GiB/180秒，无stop_reason或cleanup_error；未新建大型venv，未加载模型。源码13和安装4不能累计为一次全量。

## 身份及可复现证据

候选wheel SHA-256：`f60e7696af830704399f1e964fbd312ea1fea6e41ee7b9123a8a3dfe303368eb`；351502 bytes。小型身份索引见[CANDIDATE-0.6.14.json](CANDIDATE-0.6.14.json)。完整构建/安装编排脚本与member清单均留ignored，不提交原始机器报告。

相对路径基于本树；构建脚本中记录离线uv命令、两次hatchling命令、固定SOURCE_DATE_EPOCH、安装target及-I测试入口。重放必须换新ignored目录。

| ignored相对路径 | SHA-256 |
|---|---|
| `.local-test-evidence/2026-09-06/audience-binding/r1/command.log` | `342dfb2937a6ec6d77f48db333d555e621f56a7f10541f14e9bfd54060922a82` |
| `.local-test-evidence/2026-09-06/audience-binding/r1/resource.json` | `0c50ade46be4e9cf7f0a8a7d2e1336becc178dceb9487872059a2324e7b2bb6b` |
| `.local-test-evidence/2026-09-06/audience-binding/r2/command.log` | `5ceea94d0bc274b4cae475ad6f32427e3a1c0c4422a677b63c0719b16aaf3047` |
| `.local-test-evidence/2026-09-06/audience-binding/r2/resource.json` | `2a64c937626447f0168e431a6015cb8b99d3b5d021f82becb4a5e75fca4d9c22` |
| `.local-test-evidence/2026-09-06/audience-binding/artifact-resource/command.log` | `0f9f000ed5df3e88efb6ea8ddde31d6186fb6a79e8c4fa880b3c0d90b337a73d` |
| `.local-test-evidence/2026-09-06/audience-binding/artifact-resource/resource.json` | `852587c1e563e7e497ec25740fc28af9eac92f85e74ccc1a928c2948fae273d7` |
| `.local-test-evidence/2026-09-06/audience-binding/artifact/manifest.json` | `9d02732a606d5230989f87d14f330058c22c10a55363920e9aba95f9b2a75caa` |
| `.local-test-evidence/2026-09-06/audience-binding/artifact/runtime-identity.json` | `e250ad85330f1e1ed83e5701d3bda89ebd835e392cba519922c88dad90d2a999` |
| `.local-test-evidence/2026-09-06/audience-binding/build_install_check.py` | `6675f578a7126efe193d08e8a1dfe2a491a92490dc3c0edae4780eb98b73fb13` |
| `.local-test-evidence/2026-09-06/audience-binding/artifact/installed_consumer.py` | `bf17addb5c0efbe89116a9cb53a9446b5ea269048e46b64da86088b3bfb4e21e` |
