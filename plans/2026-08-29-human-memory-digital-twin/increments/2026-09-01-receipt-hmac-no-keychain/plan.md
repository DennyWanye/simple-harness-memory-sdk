<!-- plan-status: finalized -->

# Plan：Receipt HMAC 移除 Keychain 访问

## 主要矛盾

- 核心问题：启动和工具执行能否彻底停止访问 `deskpet.receipt_hmac` 系统钥匙串，同时保留 receipt 防篡改能力。
- 最小验证：fail-on-access fake keyring 下走 production constructor→restart→sign/verify，调用数必须为 0。
- 路径：`ReceiptStore.__init__ → load_or_create_hmac_key → userdata/secrets/receipt_hmac.key`。

## Complexity inventory

- 新依赖/API/后台任务：无。
- 新持久化状态：无；沿用已存在的 file fallback 路径并把它提升为唯一路径。
- 删除的复杂度：`_try_keystore_get/_set`、service/username 常量、base64/keyring 分支。

## Tasks

### Task 1 — 先冻结 no-access oracle [RH-AC-1]

- 修改 `backend/tests/test_receipt_store.py`：在模块 reload 前注入 fail-on-access keyring，走真实 `ReceiptStore` constructor→restart→receipt roundtrip；与现有 registry tool-chain receipt test 联合验收；增加并发首次创建、权限与重启稳定性断言。
- 增加旧 key transition oracle：历史 JSONL 原始 bytes 保持，无法由新 local key 验证时退出 ledger 并留稳定告警，不访问旧钥匙串、不删除、不猜测信任。
- 静态 oracle：生产 `receipt_store.py` 零 `keyring`/`deskpet.receipt_hmac`。

### Task 2 — 删除 receipt Keychain 实现 [RH-AC-1]

- 修改 `backend/deskpet/tools/receipt_store.py`：删除 keyring wrapper；只读取 32-byte local key。不存在时先对同目录 unique temp inode 写满 32 bytes 并 fsync，再以 atomic hard-link no-replace 发布 final path；并发 loser 只能在 link 成功后重读完整 winner，最后清理 temp。POSIX chmod 0600；任何发布/权限失败都 fail closed，不访问外部 credential store。
- 不调用系统 `security`、不读取或删除旧 Keychain item。

### Task 3 — 接线与文档回归 [RH-AC-1]

- 更新 `config.toml`、`ARCHITECTURE/AgentLoop.md`、`ARCHITECTURE/ARCHITECTURE.md`、`PROJECT_STATUS.md` 和当前边界文档，明确 ToolReceipt HMAC 只用 local file；历史 plan 保留原文，标为历史而不批量改写。
- 运行 focused receipt/registry/agent wiring tests、ruff/mypy changed surface 与静态零命中；提交独立可回滚 commit。
