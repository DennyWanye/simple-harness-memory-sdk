# S5b Task 7（S5B-S8）真实桌面 UI 通道 1-turn 预演（复跑于 Task 6 修复后）— 结果：**PASS**

- 时间：2026-09-03 02:25–02:29（本地；后端日志 UTC 2026-09-02T18:25Z 起）
- Host checkout：`/Users/taiwan/PROJECTS/SimplaHarness/simple_harness` main = `0de95582efe81117a0372f662c8dce70c4e0e1e5`（未改源码、未 commit；venv memory-sdk 0.6.2）
- 通道脚本：`.local-test-evidence/real-ui-channel/tools/`（本轮变更：`identity_harness.py` bootstrap 改为 `host-bootstrap-v2`，带 `documents_root=<run>/documents` 与 `documents_identity`，README 同步）
- 证据目录：本目录 `.local-test-evidence/real-ui-channel/20260903T022508/`
- 驱动方式：Browser pane 真实点击/输入（Claude-in-Chrome 无已连接浏览器）

## 关键事实

| 项 | 值 |
|---|---|
| 用户输入（UI） | 今天想去公园散步 |
| 会话 | `24ab4744-c528-51a6-89e9-ee2ce97552c7`（空态直发由后端新建） |
| request_id | `request-8a591f20-9e20-4a57-bc15-5edef3a2a836` |
| root_run_id | `afcd90e116235e3695338f9f7789af12` |
| sdk_run_id | `product-sdk-15af02ae1c5a3baf0c4556adb1a8caa04258162d091d92ebb23cc07f1e4c769b` |
| provider | 真实 `gpt-5.6-luna @ https://ai.svtun.cn/v1`（backend.log:141 `POST /v1/chat/completions 200`） |
| route | `context_route_decisions` 恰 1 行：`direct_standalone` / origin `no_recall` / provider_turn_ordinal 1（context_route_decisions.txt） |
| 终答（UI 可见，44 字） | 好呀，今天去公园走走很不错～晒晒太阳、吹吹风，心情会松快不少。记得穿舒服的鞋，带瓶水哦。 |
| 后端事件 | `product_sdk_runtime_ready`(:72)，无 `product_sdk_runtime_skipped`；`sdk_run_started`(:137) → `chat_v2_final_send_started sid=24ab4744-c528-51a6-89e9-ee2ce97552c7 request_id=request-8a591f20-9e20-4a57-bc15-5edef3a2a836 run_id=afcd90e116235e3695338f9f7789af12 task_scope_id=task-15af02ae1c5a3baf0c4556adb1a8caa0 chars=44` → `sdk_run_completed`(:151) |

## 步骤 → 预期 → 实际

| # | 步骤 | 预期 | 实际 |
|---|---|---|---|
| 1 | `start_channel.sh 20260903T022508`（vite [::1]:5173 → 后端 8100 → 代理 5199） | 三件套就绪 | ✅ harness.log：HEAD=0de95582、backend_python realpath、isolated fresh userdata、documents_root、`IDENTITY BOUND`；`shim injection OK` |
| 2 | 后端启动装配 | `product_sdk_runtime_ready`，provider 注册 | ✅ :38 `provider_registry_seeded_from_process_env`（key 只经环境变量，不落盘）、:72 `product_sdk_runtime_ready`、:75 `companion_runtime_adapter_ready` |
| 3 | Browser pane 打开代理地址 | 已连接 | ✅ ui-page-before.txt |
| 4 | 左栏"新建普通会话"→"创建普通 Session" | 新会话 | ❌ 对话框无响应（见 ui-observation.txt #2）；诊断探针证明后端 session_create ok（副作用：多一条空会话 9b40ee92…，无 run/route 行） |
| 5 | 空态直接输入"今天想去公园散步"→点击"发送" | 后端新建会话并启动 run | ✅ 会话 24ab4744… 出现，用户气泡显示，"工具执行中" |
| 6 | 等待终答 | 非空终答显示在 UI | ✅ 约 26s 后终答出现（ui-page-after.txt、截图内联） |
| 7 | `collect_evidence.sh` | 日志片段、route 行、sha256 | ✅ backend-log-excerpt.txt / context_route_decisions.txt / sha256sums.txt |
| 8 | `stop_channel.sh` | 进程退出、端口释放、.backend_secret 删除 | ✅ |

## 上一轮（20260903T015153）失败根因与本轮修正

- 015153 在 0de95582 上 SDK runtime 已就绪，但空态直发与"创建普通 Session"都无终答：harness 的 bootstrap 用 `window-control-bootstrap-v1`，不带 `documents_root/documents_identity`，后端 `SessionCreationService._prepare_automatic_workspace` 抛 `host_documents_unavailable`（`backend/deskpet/session/project_binding.py:957`），chat_v2 走 `chat_v2_error(session_create_failed)` 且 UI 空态不呈现该错误、后端也不打日志（探针 `session_create_response ok:false code=host_documents_unavailable` 定位）。
- 修正：harness 改用 `host-bootstrap-v2`，`documents_identity = sha256("v1\0darwin\0st_dev\0st_ino")`，与 Rust 壳 `process_manager.rs::bootstrap_line` 同配方；documents_root 隔离在 run 目录内，不碰 `~/Documents`。

## 其他观察

- PNG 截图落盘不可用（screencapture 无屏幕录制权限；Browser pane 截图仅回传；页面注入脚本被权限分类器拒绝）→ 以 ui-page-before/after.txt 替代，截图 6 张内联于会话。
- Browser pane 里对输入框按 Return 不触发发送，点"发送"按钮可靠。
- 浏览器侧 `companion_profile_bind`/`companion_action_ready` 被 `window_credential_required` 拒绝并 rechallenge 为预期（无 Rust 签名），不影响会话。
- 未改 `backend/`、`tauri-app/`；未 commit/push；未访问 Keychain；API key 未打印/未落盘。

## 文件清单与 sha256

```
671fd60f48a5f1ed73c0f9662b0eb509050566fe14f2b1e273e989d41054d438  backend.log
d49848b7d09a85ad5ad7bf5e86c21015c5dda2caff9f69a1ede243e41d3c5dc1  harness.log
385ed60f49d66fcc5bb9bb69b6404e46c0e05d6b8711eeac955dadc99ef78c88  proxy.log
06e44d1eb2dde7b641ede1001307bf0c22f8b41457e4efcc4d87677c7029358c  vite.log
8b01734b74c691cac11c2042f05d70d102200617a21ec60f2b9e0cd269c79500  backend-log-excerpt.txt
efe3d500729e6bec8543f308e125cbdf411bffcb7e4abf7b2f88fe338cec3240  context_route_decisions.txt
564426c45a4492641cafe1803d7e68bef22386323b0d14441a770a8078742bd7  ui-page-before.txt
a12eac96c67a6d0c1897f6e04fa5546f33bb51f6079ef36306981cc4bfa55a36  ui-page-after.txt
29aba0469333444a025c41e5da20a542a5c8ac8bebc8427d7482e2d5cf18e55b  ui-observation.txt
4874c8d7b1654f38ce17dd57396a4a243e55460afc5abfd19cf87a2cfaa957f5  userdata/data/state.db
```

通道脚本（tools/）：

```
894d569093652302786caf7f5d8a7f7d21196a1a5d15afbfd9edf2ce2dcb3d3f  identity_harness.py
861088616b1be84560686d5808d3f002d42f47dcaa653fe5dc82aeac400d78a4  shim_proxy.py
7a1dfef0c7ddf65086760f79135eff1d045d62a1922747ce916bca3faa8e1383  tauri_shim.js
0912cd2f9ef96c8faa8e307960ff19ad3367a106c154ecad30b30f94518ec4c1  collect_evidence.sh
5232295ff2fcbf94cc212214819cbb00c0ded32cf39754f5e0fb9ef66a77aaa6  start_channel.sh
4e25db87ca02c15a9d0312990d359c7f64bac8b7caf249625086f98bef71188d  stop_channel.sh
19d8835db8651aba4b36f54417021e7ba3eb9fae32ef4c96fde7ffa8825b741d  README.md
```

完整清单（含本文件）见 `sha256sums.txt`。
