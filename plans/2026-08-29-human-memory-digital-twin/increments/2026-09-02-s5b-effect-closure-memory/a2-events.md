
## 2026-09-05 a2-001：冻结 SDK 的 route 恢复假设失效

影响 S5b Task 7 与真实验收。类型 assumption-failure；独立真实数据库探针确认
Harness 0.7.1 将合法演进后的 current route 与 initial route 比较并拒绝恢复。
详见 [限定解冻提案](SDK-ROUTE-UNFREEZE-PROPOSAL.md)。本机 r5-local 已入账，
状态 OPEN（SDK 修复/复验未闭合）；用户已批准 A17 限定例外，原话 hash `e77e066868134fa60789c3835c2ca376418bf61f6058fdb720ac93d68d19e343`。
本次回写 acceptance/plan 并通过 metadata attach 将 S1 原始失败证据及批准关联到 r5，未改代码/pin，
未将批准记成修复完成；S8 的 fail/pass 历史与 FLAKY 保留。

源码修复/review 已提交 `2b8428465cbd41032ba024a0b7199183161f5ecd` / 0.7.2；
A2 仍 OPEN，待新 Host exact-wheel 与真实 A14 重测，不用源码通过清除原失败事实。
