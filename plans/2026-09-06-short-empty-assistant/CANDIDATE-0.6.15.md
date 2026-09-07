# M0.6.15 空 assistant 后继制品

最后更新：2026-09-06。主转Dirac对17aebde/9bbf42b固定业务/测试限定ACCEPT、14hash及Host原[True]源码overlay已核；主明确分配0.6.15后，本轮完成双offline build和独有installed验证。自有树 `/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources`，分支 `feat/short-empty-assistant`。

## 交主消费的精确身份

- 固定构建源码：`7f9983dc3ced27a963fb207b17a4dc9470dbcae4`，仅在9bbf42b上改包版本；业务17aebde两hunk保持。
- Wheel：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/build1/simple_harness_memory_sdk-0.6.15-py3-none-any.whl`。
- 第二独立输出：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/build2/simple_harness_memory_sdk-0.6.15-py3-none-any.whl`。
- 两份SHA-256：`69544677c44a09fb53cbe18df2c2cfe6e33b892eb34cb32b1cb2cf3c6445294d`，均351751 bytes。
- 没有prospective source API/非SELF等后继改动，未改旧614、Host pin、SDK main，未tag/push/publish。

## 构建与安装事实

固定SOURCE_DATE_EPOCH=1788666965，复用既有service SDK hatchling解释器直接构建，两次独立输出字节一致；没有下载或安装构建依赖。uv --offline --no-cache --no-config --no-deps装入本叶独有空target，不建完整venv、不写共享site-packages。uv安装日志选择CPython3.13.13作目标解析，wheel为py3-none-any；实际-I/-B consumer由主M614既有Python3.12解释器运行。

独有target为 `/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/installed`。Memory73包成员逐项等于fixedGit源码，wheel76个非RECORD成员逐项等于target；既有H073 wheel169成员逐项等于借用解释器的installed包。consumer断言Memory0.6.15及独有target实际路径、isolated=True、无Memory源码overlay；原614全部73包文件执行前后hash相同。

独有installed的9项验收全部通过，1.06秒：空/非空完整工具父项组、公有ingest/register/projection/recall/source、重开/遗忘、全空组query0、USER空/空白及NUL/UTF-8/identifier/hash门。工具终态link在本批为显式Host authority fixture，不称真实工具执行；另有源阶段主Host真实11turn空assistant执行载体通过，但它仍是overlay证据。主后继H074+M615实际installed组合另验，不能合并冒称已通过。

## 资源与边界

同一默认OS锁资源入口d739dcf7（原145后继、含默认磁盘准入1024MiB/停止256MiB），2048MiB/180秒。PGID43803、elapsed2.38秒、峰139856KiB、exit0，remaining为空/cleanup_error为空；ps另核无组成员，测试槽释放。整个artifact目录15MiB，结束可用磁盘约3501MiB，未清理旧raw。制品独审/主H074组合仍待；240质量、非SELF/输入permit、prospective事实接口不在615内。

## 复现和本机证据

构建编排脚本包含两次hatchling命令、固定Git成员核对、uv独有target安装及完整consumer代码。历史重放须换新证据路径；脚本拒绝非固定HEAD、脏工作树和已存在artifact目录。所有raw ignored，不提交或上传。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-06/primary-m0614/venv/bin/python -B \
/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py \
--evidence-dir /Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/short-empty-assistant/artifact-615-resource \
--rss-mib 2048 --seconds 180 -- \
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-06/primary-m0614/venv/bin/python -B \
/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/short-empty-assistant/build_install_615.py
```

| 本树相对路径 | SHA-256 |
|---|---|
| .local-test-evidence/2026-09-06/short-empty-assistant/build_install_615.py | 6bee688ea6a6395adb3913a15af35a3ad8700131f13ab9b76af86b53e4616b3c |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615-resource/command.log | a1433a01baff2a5ac3faaa341e57c8808533eaf08eb7add18eeacd477bb45c6b |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615-resource/resource.json | 5ec75aa901f34c5d630c7e9e52c087acaf703e074d4058dabc501a71be1d9833 |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/manifest.json | 1665b246152debcffb80a12c9f8df0821abf8f1f2f0c5b2ae556d863f98d44ec |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/runtime-identity.json | 2da3c02e74a87c794edb709b7c7c9c9be85a6c9d00cdebea6315b8c8d6d213a2 |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/old614-unchanged.json | 24f45b876d5e605d125b6cddb72f7c2230a135da10b300b9a5dee64f1a696298 |
| .local-test-evidence/2026-09-06/short-empty-assistant/artifact-615/installed_consumer.py | 9ae20942c1d222e46a5db2da501cde127dd43d84c160c00ca12a2b27ae4de98f |
