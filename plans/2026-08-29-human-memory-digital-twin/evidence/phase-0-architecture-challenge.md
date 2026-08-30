# Phase 0 Architecture Challenge

> 日期：2026-08-30
> 范围：三个仓库新增的 Human Memory Program 实施前边界与跨仓架构基线
> 预期 challenger：skill 配置中的 Claude challenger
> 实际 challenger：独立同级 Codex subagent（当前工具环境未提供 Claude 模型）

## Round 1 — FAIL

挑战者发现文档把 model-visible Memory surface 写得过宽：Host 只过滤 `memory_recall` 与
`memory_search`，仍向模型暴露 `memory_write`、`memory_read`、`memory_forget` 的真实 handler。
该错误会让后续计划误判旧工具的升级/退役范围。

代码证据：

- `simple_harness/backend/main.py:7275-7291`
- `simple_harness/backend/deskpet/tool_catalog/providers.py:342-420`
- `simple_harness/backend/deskpet/sdk_adapters/tools.py:455-493`

修正：Host 架构文档与跨仓 baseline 均改为精确描述；补充 write 的 trusted principal、read 的 exact Fact ID
和 forget 进入物理删除路径的现状，并把真正缺口限定为版本化 `RecallPlan` / context-route / typed recall。

## Round 2 — PASS

挑战者复核原 finding 已闭环，未发现新的不准确或遗漏。结论是修正后的文档可以作为 Phase 1 写计划的
可靠架构基线。

`VERDICT: PASS`
