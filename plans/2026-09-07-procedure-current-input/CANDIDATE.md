# Memory 0.6.19共同候选

最后更新：2026-09-07。源合并f03dab0（Procedure）+e500556（本轮输入）为1df01d1；a28a857仅补CurrentInput请求hash合法exact Draft类型，Host同域同步补齐。产品共享visibility分支保持逐项当前检查，input例外仅原wholeUSER，不传播到draft。

组合控制Host80764c13/Memorya15c7be已独审限定接受：真实signedSELF/currentclaim与独立publicdraft共Manager，前双可见，publicforget后当前true/draftfalse，Hostjournal精确captured_bound。1PASS0.82s；原不存在all_visible测试属性失败保留、只红1修复重验。Memory为源码overlay，installed/native另验。原始证据与hash见Host plans/2026-09-07-current-input-procedure/RESULTS.md。

从实际d8d80d5c M618根导出AST逐项比较：原106全部保留，新增12；无Memory DDL变化。0.6.19公共快照和版本文档已准备，版本测试/一次制品仍待执行。旧public_api测试将历史0.6.12快照比较与当前版本比较分开，历史文件不改；当前快照仍精确比运行时exports/migrations，避免把陈旧0.6.12断言作为当前结果。仅本地候选不发布。
