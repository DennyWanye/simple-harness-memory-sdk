# 增量验收：Receipt HMAC 不再访问系统钥匙串

> 状态：APPROVED / FROZEN（2026-09-01）  
> 用户要求：`不要再请求 deskpet receitp_hmac 的钥匙串了，删掉这块儿，后续也不要请求`  
> 原始消息 SHA-256：`ea2d00112bbaf91898efe24c5bd27fd3345b7d3ffa167866c96e30b83c508b95`

## 主要矛盾

- 核心价值：simple_harness 启动和工具执行不能再因 ToolReceipt HMAC 访问或弹出 `deskpet.receipt_hmac` 系统钥匙串请求。
- 最小验证动作：在安装一个“任何访问都会抛错”的 fake `keyring` 后构造生产 `ReceiptStore`、重启加载同一 key、写入并验签 receipt；全程 fake 调用计数必须为 0。

## 范围

- 删除 `receipt_store.py` 对 Python `keyring`、macOS Keychain、Windows Credential/DPAPI 和 Linux libsecret 的 get/set 路径。
- ToolReceipt 继续使用 HMAC；key 只保存在应用私有 userdata 的 `secrets/receipt_hmac.key`，先完整 fsync 临时 inode、再以 atomic no-replace link 发布，并在 POSIX 校验/设置 0600；并发 loser 只能读取完整 winner key。
- 不读取、不迁移、不删除现有 OS 钥匙串条目；从代码上彻底停止访问它。
- 只有旧 Keychain key、没有 local key 的历史 receipt 保留原始 JSONL bytes，但因无法验证而退出 VerifyGate ledger并记录 `sig_invalid_filtered`；不得猜测信任、删除或冒充可验证。
- 更新生产注释、配置说明、架构事实与相关自动化 oracle。

## MUST AC

| ID | 验收条件 |
|---|---|
| RH-AC-1 | 生产 `ReceiptStore` 初始化、重启、签名、验签和工具调用链均不 import/call `keyring`，不使用 service `deskpet.receipt_hmac`；本地 key 首次原子创建、后续稳定复用，HMAC 防篡改语义保持。 |

## 测试义务

| obligation_id | type | ac_id | risk | min_decisive_test | required_reason |
|---|---|---|---|---|---|
| RH-TO-1 | delivery | RH-AC-1 | — | 模块加载前注入 fail-on-access fake keyring + production constructor/restart/receipt roundtrip，并与既有 registry tool-chain receipt test 联合验收；调用计数 0 | 直接证明不再请求系统钥匙串 |
| RH-TO-2 | change-risk | RH-AC-1 | FAIL-RECEIPT-KEY | 并发首次创建、0600、32-byte、重启同 key、篡改拒绝 | 防止移除 Keychain 后破坏 receipt 验签 |
| RH-TO-3 | change-risk | RH-AC-1 | FAIL-WIRING | `rg` 生产路径零 `deskpet.receipt_hmac`/receipt keyring 命中 + receipt/registry focused tests | 防止只改 helper 但生产仍有旁路访问 |
| RH-TO-4 | change-risk | RH-AC-1 | FAIL-RECEIPT-KEY | 用旧 key 签名 JSONL、只创建新 local key 后读取；verified ledger 为空且 raw bytes 不变 | 冻结禁止读取旧钥匙串后的诚实过渡语义 |

## 适用性

- `input_sensitive=false`：纯确定性 key storage 行为。
- `llm_payload_driven=false`：不处理 LLM 载荷。
- `stateful_init=true`：首次 key file 创建与并发/重启需要验证。

## 完成定义

- 三条 obligation 当前执行 PASS；Host 架构/配置与测试不再宣称 receipt HMAC 走 Keychain。
- 不触碰、不查询、不删除用户现有钥匙串条目。
- 变更提交态干净，机器门或父 S4 gate 能引用该结果。
