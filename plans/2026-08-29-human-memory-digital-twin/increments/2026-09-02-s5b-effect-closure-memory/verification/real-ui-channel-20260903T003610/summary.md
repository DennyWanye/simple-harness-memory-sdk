# S5b Task 7（S5B-S8）真实桌面 UI 通道重建与 1-turn 预演 — 结果：**BLOCKED**

- 时间：2026-09-03 00:36–00:42（本机时区；后端日志为 UTC，即 2026-09-02T16:36Z 起）
- Host checkout：`/Users/taiwan/PROJECTS/SimplaHarness/simple_harness` main = `a42835d09017a979a7cc4fce30c7ad7df83220f4`（未改任何源码、未 commit）
- 通道脚本：`.local-test-evidence/real-ui-channel/tools/`（`scripts/dev/real_ui_channel/` **不被** .gitignore 忽略，故按要求改放此处）
- 证据目录：`.local-test-evidence/real-ui-channel/20260903T003610/`
- 驱动方式：Browser pane（Claude-in-Chrome MCP 无已连接浏览器，`list_connected_browsers` 返回空）真实点击/输入

## 步骤 → 预期 → 实际

| # | 步骤 | 预期 | 实际 |
|---|---|---|---|
| 1 | `start_channel.sh 20260903T003610`：vite（[::1]:5173） | 就绪 | ✅ `VITE v8.0.8 ready`（vite.log） |
| 2 | harness 以 stdin-v1 bootstrap 拉起 `backend/main.py`（isolated fresh userdata、`DESKPET_BACKEND_DIR`=本 checkout backend、`DESKPET_MODEL_ROOT`=本机 WeMM 快照） | 后端 8100 健康；日志确认 Dev python/路径 | ✅ harness.log：`backend_python=…/backend/.venv/bin/python -> realpath=…/uv/python/cpython-3.12.14…`、`cwd=…/simple_harness/backend`、`userdata(isolated,fresh)=…/20260903T003610/userdata entries_before=[]`；backend.log 首行 `crash_reporter_installed directory=/Users/taiwan/PROJECTS/SimplaHarness/simple_harness/crash_reports`、`config_loaded user_data_dir=…/20260903T003610/userdata env_pinned=true`；16s 后 `/health` 200 |
| 3 | provider：isolated userdata 的 `llm_runtime.json` 只含 base_url/model，key 经 `DESKPET_CLOUD_API_KEY` 进程内传递 | 后端注册 provider，不落盘 | ✅ backend.log:37-39 `provider_registry: added process-only provider primary` / `provider_registry_seeded_from_process_env base_url=https://ai.svtun.cn/v1 model=gpt-5.6-luna` / `provider_routing_ready providers=1`；:94 `provider catalog cache refreshed provider=primary models=21`（真实 provider 可达） |
| 4 | 身份门：`companion_control_challenge` → 自签 Ed25519 `companion_profile_bind` | `companion_profile_bound` | ✅ harness.log：`IDENTITY BOUND: {"profile_id": "legacy_local_profile", "profile_generation": 1, "owner_key": "companion:legacy_local_profile:1", "binding_epoch": "1", "next_request_seq": "2", "session_id": "d282b00e-5d1b-47e5-9da9-c5cb6b8a303a"}` |
| 5 | shim 反向代理 127.0.0.1:5199，服务端注入 `/__shim.js`（secret 不进 URL） | index.html `<head>` 含 shim | ✅ `curl` 校验通过；proxy.log `shim injected for 127.0.0.1`。首跑发现 vite 只监听 IPv6 `[::1]`，代理上游改为 `[::1]` 后通过 |
| 6 | Browser pane 打开 http://127.0.0.1:5199/ | 前端拿到 secret，显示已连接 | ✅ 截图（会话内联）：左下"● 已连接"，右上 `gpt-5.6-luna`，"新对话（直接输入即可开始）"；后端 :84 接受 `session_id=message-panel-main … requested_scope=companion_action` |
| 7 | 点击输入框、输入"今天想去公园散步"、点击"发送" | 消息进入消息流，真实 provider 返回非空终答 | ❌ 输入框被清空但消息流仍"（消息流为空）"，状态"✓ 空闲"；后端 105 行日志无任何 `sdk_run_started`/`chat_v2_*`/route 事件；`context_route_decisions` 0 行（context_route_decisions.txt） |

## 卡点根因（源码级，未自行修改）

后端启动时 SDK Runtime 装配失败，聊天主路径不可用（backend.log:70-74）：

```
:70 product_sdk_runtime_skipped reason="build_failed: sdk_context_authority_composition_missing:sdk_provider_binding_resolver"
:71 human_memory_foreground_runtime_unavailable reason=sdk_runtime_authority_unavailable
:74 companion_runtime_adapter_skipped reason="SDK Runtime unavailable - configure LLM provider in Settings"
```

调用链（`backend/main.py` @ a42835d0）：
- `_activate_product_sdk_runtime()`（L10728，由 lifespan L5606 调用）→ L10781 `stack = await _build_product_sdk_runtime_stack(...)`
- `_build_product_sdk_runtime_stack()`（L7837）→ L8787 `_activate_memory_analysis_lane()`（S5b Task 4 组合）
- `_activate_memory_analysis_lane()`（L8848）L8871-8872：`if _sdk_provider_binding_resolver is None: raise RuntimeError("sdk_context_authority_composition_missing:sdk_provider_binding_resolver")`
- 但模块全局 `_sdk_provider_binding_resolver` 只在 L10888（`_activate_product_sdk_runtime` 内、stack 构建**之后**）才从 `service_context.get("sdk_provider_binding_resolver")` 赋值；构建期间它恒为 None（L7373 初值）。
- 因此每次真实启动必然 raise → runtime skipped。该分支由 commit `7b3c7ede`（2026-09-03 00:16 +0800，"main.py 装配 Host↔Memory 异步面…缺件 startup fail"）引入；仓库内现有所有 `product_sdk_runtime_ready` 的启动证据（s5a-cold-start/*.log）均早于该 commit。
- 与我的环境无关：provider 已注册（:37-39）、身份已绑定、isolated userdata 正常；`service_context` 里的 `"sdk_provider_binding_resolver"` 其实在 L8705（同一构建函数内、L8787 之前）已 register，只是 L8871 读的是模块全局而非 service_context。
- 需要什么：源码修复（例如 L8871 改读 `service_context.get("sdk_provider_binding_resolver")`，或把 L8787 的 lane 激活挪到 L10888 之后），由主代理决定并修；修复后重跑 `start_channel.sh` + 本预演即可。

## 其他观察

- Browser pane 里对输入框按 `Return` 不触发发送（可能是 IME/keydown 差异），点击"发送"按钮可清空输入框；README 已记为操作口径。
- 浏览器侧自身 `companion_profile_bind`/`companion_action_ready` 被 `window_credential_required` 拒绝并 rechallenge（预期，浏览器无法 Rust 签名；S5a 同样如此）。
- **并发改动提示**：00:40:50（本预演后端已于 00:36:10 启动并在 00:36:24 失败之后）工作区出现非本任务的修改：`backend/pyproject.toml`、`backend/deskpet/sdk_adapters/sdk_candidate.py`、`backend/tests/sdk_adapters/test_official_memory_product_integration.py` 改为 memory-sdk 0.6.2，venv 也在 00:40:50 换成 0.6.2。本预演后端进程 import 时 venv 仍为 HEAD 钉的 0.6.1；失败点与 memory-sdk 版本无关（是 main.py 装配顺序）。这些改动不是本任务所为，未触碰。
- PNG 截图落盘未能完成：`screencapture` 报 `could not create image from display`（终端无屏幕录制权限）；Browser pane 截图工具只回传会话不落盘；在页面注入 html2canvas 取 PNG 被权限分类器拒绝。截图 4 张内联于本会话；UI 文本证据见 `ui-observation.txt`。

## 已试方法（针对卡点）

1. 核对 provider 是否为因：backend.log :37-39/:94 显示 provider 已注册且目录可拉取 → 排除。
2. 核对身份门：harness IDENTITY BOUND → 排除。
3. 静态追踪 reason 字符串到 L8872，并核对 `_sdk_provider_binding_resolver` 全部赋值点（仅 L10888）与调用顺序（L10781 先于 L10888）→ 确认为装配顺序缺陷。
4. 未尝试改源码（任务硬约束）。

## 文件清单与 sha256（证据目录）

```
73979cc414029f9ab4fd1c8715c5c33e2a30a1136ac6c52fbd4f356735c17344  backend.log
d8a9e70c0ac5a49cc8d5a5e4cd73e0b0b067d4ecec6890a792179ebdd704bcbf  harness.log
d071d1f450e895a5823a87d4e4c4dbe69518a6db9f23640ae2c568d716a53871  proxy.log
5a53f707e44980bfe8a551ddf47692c318ebf9676c3acc6e236915a4b5ca1d57  vite.log
76b55826feb079a28b6a7384d27f9ae6ad1df3c4f1ef7d696aa615acebd77ca3  backend-log-excerpt.txt
657a8803c4e857f33e9c8c51de3cf0a89b69b51859e0386239754392da4c1a95  context_route_decisions.txt
718ad37e3f0ca512de4d710355233e3c8759d909e0a2669be7e5b1a2e024c839  ui-observation.txt
29ef1235ed1acab5021d1da9daed5384d926e5ee7e7fd0bfd874fef047017d24  userdata/data/state.db
```

通道脚本（tools/）：

```
264a403e9e8b44d41db02c193c9e1a94993360dd5be4d0ca8a37885a17ce1081  identity_harness.py
861088616b1be84560686d5808d3f002d42f47dcaa653fe5dc82aeac400d78a4  shim_proxy.py
7a1dfef0c7ddf65086760f79135eff1d045d62a1922747ce916bca3faa8e1383  tauri_shim.js
0912cd2f9ef96c8faa8e307960ff19ad3367a106c154ecad30b30f94518ec4c1  collect_evidence.sh
5232295ff2fcbf94cc212214819cbb00c0ded32cf39754f5e0fb9ef66a77aaa6  start_channel.sh
4e25db87ca02c15a9d0312990d359c7f64bac8b7caf249625086f98bef71188d  stop_channel.sh
ad020020f01b21e64a4bfb3907e1b733cab6b1d6144d4926bcf77e67f218d8ac  README.md
```

完整清单（含本文件）见同目录 `sha256sums.txt`（由 collect_evidence.sh 生成）。
