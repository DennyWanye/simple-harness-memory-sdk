# Semantic relations 增量绿色基线

> 锁定时间：2026-09-01 Asia/Shanghai
> 业务代码修改：尚未开始

## 候选身份

| 仓库 | worktree | HEAD | 状态说明 |
|---|---|---|---|
| Harness SDK | `/Users/denny/projects/simple-harness-sdk-memory-program` | `fb491574db8bb4d19d8a7f9df0c72ae460bb08f4` | clean |
| Memory SDK | `/Users/denny/projects/simple-harness-memory-sdk-memory-plan` | `dfd12ce50bd9f22f5f6ed1a7d81e55ca4b20d4a0` | 只有本增量 plan/gate/spike 与重编译 manifest，业务代码 clean |
| testcase | `/Users/denny/projects/simple_harness-memory-plan` | `2ab09cfa` | clean |

## Harness SDK

- `uv run pytest -q` -> `1724 passed, 2 skipped`，25.44s。
- `uv run ruff check src tests` -> PASS。
- `uv run mypy` -> `Success: no issues found in 35 source files`。
- 探索性 `uv run ruff check .` 另发现 `examples/minimal-consumer/` 3 个既有可修复 lint（2 个 import order、1 个
  无 placeholder f-string）。该目录不在当前 CI release-path lint，也不与本增量改动路径重叠；本任务不顺手修改，final
  必须继续区分 scoped release lint PASS 与 repository-wide exploratory lint existing red。

## Memory SDK

首次 `uv run pytest -q` collection 失败，因为 worktree `.venv` 中旧 Harness 0.7.0 wheel 缺
`ContextFragmentBindingV2`。执行环境修复：

```text
uv sync --group dev --reinstall-package simple-harness-sdk
```

输出确认从 `/Users/denny/projects/simple-harness-sdk-memory-program` 构建/安装 exact path dependency，且公开 symbol 存在。
这只改变 ignored `.venv`，不改变交付文件。

修复后：

- `uv run pytest -q` -> `1037 passed, 8 skipped`，37.44s。
- `uv run ruff check src tests` -> PASS。
- `uv run mypy src` -> `Success: no issues found in 58 source files`。

## 基线判定

生产/测试源路径的既有 suite、lint、typing 为绿色；后续任何新红均视为本增量回归。Harness examples 的 3 个
repository-wide exploratory lint 是明确的 pre-existing、out-of-path 状态，不能被误报为本次修复或本次全仓 lint PASS。
