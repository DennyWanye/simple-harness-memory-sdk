# M0.6.15 空 assistant 后继候选

最后更新：2026-09-06。主已接受17aebde业务逻辑及9bbf42b测试/14指纹，明确分配0.6.15给此增量。自有树 `/Users/denny/projects/simple-harness-memory-sdk-typed-short-sources`，分支 `feat/short-empty-assistant`；本次只改包版本，不混入prospective public source API、非SELF或其他业务。

## 当前阶段

0.6.15源码候选准备中；Dirac对固定业务17aebde及验收9bbf42b的限定接受尚未收到，双构建/安装均未执行，wheel尚未生成。按主明确顺序，独审接受后才执行。原614源码/制品/installed全部保留，不更新Host pin，不tag/push/publish。

已通过的源验收保持：[原红、9专项分批、9邻居与Host原空assistant真实组载体](RESULTS.md)。Host原[True]为Memory源码overlay开发证据，不能代替0.6.15 installed验证或后继H074组合。

## 接下来的有界制品步骤

复用现有service SDK的hatchling解释器、主M614的依赖解释器，固定Git源码与SOURCE_DATE_EPOCH；两次offline wheel输出到两个新的ignored目录，SHA必须一致。用uv --offline --no-cache --no-config --no-deps安装到本叶独有空target；不写共享site-packages，不新建完整venv。

公开consumer用-I/-B，显式加载独有安装target并断言Memory实际路径、0.6.15版本；比对wheel全部非RECORD成员与target、包源码与固定Git，以及既有H073 wheel/installed成员。运行本叶9项空消息/完整tool-parent/全空组/拒绝门契约，原始DB/日志留ignored；独有installed结果与主后继H074组合分开。

统一使用同一共享资源入口 `/Users/denny/projects/simple_harness-test-resource-cleanup/scripts/run_resource_bounded.py`，默认OS锁及磁盘门，2048MiB/180秒，不换锁。重跑换新批次、不覆盖旧raw；完成后核资源组清空，交主wheel绝对路径/SHA、源码SHA及小型中文MD。
