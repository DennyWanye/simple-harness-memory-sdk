# Memory 0.6.19共同候选

最后更新：2026-09-07。源合并f03dab0（Procedure）+e500556（本轮输入）为1df01d1；a28a857仅补CurrentInput请求hash合法exact Draft类型，Host同域同步补齐。产品共享visibility分支保持逐项当前检查，input例外仅原wholeUSER，不传播到draft。

组合控制Host80764c13/Memorya15c7be已独审限定接受：真实signedSELF/currentclaim与独立publicdraft共Manager，前双可见，publicforget后当前true/draftfalse，Hostjournal精确captured_bound。1PASS0.82s；原不存在all_visible测试属性失败保留、只红1修复重验。Memory为源码overlay，installed/native另验。原始证据与hash见Host plans/2026-09-07-current-input-procedure/RESULTS.md。

从实际d8d80d5c M618根导出AST逐项比较：原106全部保留，新增12；无Memory DDL变化。0.6.19公共快照和版本文档已准备，版本测试/一次制品仍待执行。旧public_api测试将历史0.6.12快照比较与当前版本比较分开，历史文件不改；当前快照仍精确比运行时exports/migrations，避免把陈旧0.6.12断言作为当前结果。仅本地候选不发布。

## 一次制品及安装组合

clean source e27003c68b892fe061aac0ca2c9a140871f564cd，经3版本元数据控PASS0.25s后离线hatchling1.32.0只构建一次。wheel SHA c95cdf4852c3ca07a6d62f40aa3c8559f2715e7f4dfa966f9d412f8c063509d1，manifest SHA b09e9fed7d3299afd8330aaa631bca45f92f6f05ea971ec29e795a5c381d822d。H079/M619/S0313实际安装新组合1PASS0.86s，174/92/116成员精确、184SDK模块来自target，无Memory源码overlay。初次生产identity因安装origin为build目录而拒，后经实际uv从vendor同一wheel安装纠正，未改metadata或重build；生产pin/lock关系已验。

Host制品原始证据在primary-candidate .local-test-evidence/2026-09-07/{memory619-contract,memory619-artifact,memory619-installed}/，精确命令/hash/资源与失败见Host plans/2026-09-07-current-input-procedure/INSTALLED-079619.md。五个进程组均清空，无原生/模型质量完成声明。
