# 完整 analysis 输入恢复：必要控制

最后更新：2026-09-06。SDK 固定业务 `d46bf1f`（0.6.18.dev0），Host 固定 `6b53f27c`，沿 H077/M617 依赖并覆盖本 SDK 源码。没有使用 H078，没有修改旧 installed／M617 wheel，没有调用真实 Provider／模型／native。

## 结果

共享 runner 单次 r3：SDK **3 PASS / 0.47s**；Host **5 PASS、24 deselected / 2.59s**。完整进程组 PG1149，exit0、3.834s、峰191648KiB、最低磁盘4917MiB，remaining=[]、cleanup=null，额外只读 ps 无成员，锁释放。此前 r1/r2 均 BUSY75，未启动 child，不计测试。

- SDK：旧两成员普通失败后改变完整配置、预算和 batch_size，并加入新 job，仍保留原完整输入与成员顺序；新 job 独立用新配置。两项持久预算／成员篡改均拒绝，无新 claim／Provider。
- Host 原 `[3-True]`：实际 public worker／job／Host durable response 后抛普通 RuntimeError，旧 batch 确为 failed；新 v4 配置重开，复用原响应并应用旧 v3 ACTIVE 语义，新增 Provider=0。除 job_id/attempt/idempotency_key 外全部输入精确相等；旧 failed request JSON/hash 不变，新 attempt hash 不同。不是取消／expiry 替代，也不是 SDK 三控替代。
- Host `[4-True]` 同路保留 v4 DRAFT，另两项 cancellation 回收分别保留原 v3/v4；高风险字段边界通过。已持久 plan 禁止重新编译，未知／混合协议仍拒绝并保留审计。

本轮只解决跨版本恢复 P1；Procedure 的 TaskScope 成功观察／适用性产品接线尚未完成。历史混合批次成员若已终态或被拆分，明确拒绝，不伪装 exact replay。源码最终独审与 M618 制品／实际 installed 证据待续，默认 v4 尚不能仅凭本源码覆盖结果合主。

## 原始证据索引

根：`.local-test-evidence/2026-09-06/analysis-retry-protocol/`，全部 ignored。

| 文件 | SHA-256 |
|---|---|
| run_controls.py | 78aa4e97c1d584f841e705932ee6dd73344feec19e2894de8d0e6c9e0f1ab50e |
| r3/command.log | d77c9c4d01511620b91d72682651b7e6ee2f83f0c937a0ba46e342a7691d81b2 |
| r3/resource.json | 9134ae7d902d43645762581534868293f206685ed80c0705ec6a8f36f77ec730 |
| src/simple_harness_memory/backends/sqlite_v5.py（仓库路径） | 89d0b02f312bcbd9f532bf359d8160bcfec1b818379616b984f313a58a358dba |
| tests/integration/test_analysis_retry_protocol.py（仓库路径） | 1dad5c831c91df4ced246782610cc6769d3d1f23b6881370f2a558e9bb5cf50c |
| Host backend/tests/memory/test_procedure_adoption.py | 0e4826b29bb9a01f682ed3ed2877632ce3f96577ca5e748d33235a67b5181ab5 |

命令：借用 `primary-candidate/.local-test-evidence/2026-09-06/primary-m0614/venv/bin/python` 运行 `/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py --evidence-dir <本根>/r3 --rss-mib 512 --seconds 90 -- <同 python> -I -B <本根>/run_controls.py <本根>/r3`；不指定 lock-file。carrier 串行运行 SDK 三控与 Host 五控，各自关闭缓存和插件自动加载，精确命令保存在 carrier。

M618 构建脚本已准备于本根 `build_install_618.py`，未执行：收到固定源码独审后再固定 release 版本，一次 offline wheel，独有 target 安装；只核与 M617 相比改变的包成员，安装后跑原完整 cohort 和 Host `[3-True]` 两项消费控制。制品另交主转 Dirac，不重复旧包全量扫描。
