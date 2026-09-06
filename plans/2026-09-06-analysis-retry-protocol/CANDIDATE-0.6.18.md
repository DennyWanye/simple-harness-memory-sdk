# M618 单次构建与独有安装

最后更新：2026-09-06。主转 Dirac 已限定接受 SDK d46bf1f/cf7c8d5 与 Host 6b53f27c/e37c42bb；正式版本提交 **d8d80d5c00f489e7d85a7d1df613f73e489b4cc2** 只将0.6.18.dev0改为0.6.18。无业务源码后改，无新venv，不改冻结M617及主安装环境。制品独审、主H078组合另验；没有native／真实Provider结论。

## 固定制品

wheel：[simple_harness_memory_sdk-0.6.18-py3-none-any.whl](/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/analysis-retry-protocol/artifact-618/build/simple_harness_memory_sdk-0.6.18-py3-none-any.whl)

SHA-256：`010b4281c7b1149e32858939119262d97cedb8528ddd8bb62b87940dcefbe1cb`

独有安装：`/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources/.local-test-evidence/2026-09-06/analysis-retry-protocol/artifact-618/installed`。

一次offline hatchling wheel → uv offline/no-deps独有target。只核相对M617变动的2包成员，fixed Git=本地源码=wheel=target；不重复旧包全成员扫描。-I消费过程中所有已载入Memory模块路径都属于新target；Harness仍来自既有H077 target，不混H078。M617旧制品未写入，未tag/push/发布。

| 变动包成员 | SHA-256 |
|---|---|
| simple_harness_memory/__init__.py | 77c34a6118221a720cf6411ca333b0673324da73a3d11b75384af6dda98dae71 |
| simple_harness_memory/backends/sqlite_v5.py | 89d0b02f312bcbd9f532bf359d8160bcfec1b818379616b984f313a58a358dba |

## 两项实际安装检查

SDK完整cohort **1 PASS/0.11s**；Host原普通异常升级 `[3-True]` **1 PASS/0.73s**。后者实际Host持久响应与公共SDK应用、全部语义输入／旧failed原值不变、零新增Provider，未使用SDK源码overlay。此前3+5源码控制复用，不跑旧24绿。

默认共享资源入口：PG1723/exit0，2.408秒，峰189120KiB，最低磁盘4872MiB，remaining=[]/cleanup=null，额外ps无成员；锁释放。命令使用原primary-m0614 Python执行资源入口，512MiB/90s/default锁，子命令 `-I -B build_install_618.py d8d80d5c00f489e7d85a7d1df613f73e489b4cc2 <根>/artifact-618`。

## ignored 证据

根：`.local-test-evidence/2026-09-06/analysis-retry-protocol/`。

| 文件 | SHA-256 |
|---|---|
| build_install_618.py | 1af9c308947784964b8ebc69c839d90fae37d098f0f33975b0779ccea5b902aa |
| artifact-resource-r1/command.log | 0eb1b8651f0603b6c8a2ae84141419a34d38b3e8427a2e86366b4c3fe905381e |
| artifact-resource-r1/resource.json | 57a057e6961cea738f169b82674ea456500cfd2071414ac7e6725d7d965b4c43 |
| artifact-618/manifest.json | 69254343d97042f247cdd4e493db2882b0e129f9ca75f0cde9981a657f33be10 |
| artifact-618/sdk-identity.json | e2b4db68ce773ba9b58b0988c0b4aa1f9ee5b4dbdef80dddead80f467189b7db |
| artifact-618/host-identity.json | e2b4db68ce773ba9b58b0988c0b4aa1f9ee5b4dbdef80dddead80f467189b7db |

本后继仅修分析重试跨配置恢复。Procedure实际Scope观察来源与当前工具／环境applicability仍需Host后继接线，不能以本制品表示完整功能闭合。
