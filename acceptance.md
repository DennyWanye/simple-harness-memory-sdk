# 验收标准：simple-harness-memory-sdk（首个 release unit：本地记忆核心 + 世界对象）

## 范围
- 包含：`MemoryBackend` 契约与数据模型、Mock/SQLite 本地后端、哈希伪向量嵌入器、
  规则 Facts 提取、RRF 六路召回、遗忘/显著性/会话亲和性、数字孪生体构建与冲突检测、
  世界对象（时间/知识边界/事件/天气，全部含 noop 降级）、`MemoryManager` 统一装配。
- 明确不包含：BGE-M3/torch 语义嵌入（可选 extra）、云端后端（Pinecone）、跨设备同步、
  LLM Facts 提取的真实在线调用（仅保留接口与降级路径）。

## 功能验收条款
| ID | 功能点 | 验收条件（可验证） | 优先级 |
|----|--------|-------------------|--------|
| AC-1 | 契约与模型 | `import simple_harness_memory` 成功；`MemoryBackend` 抽象接口、`Message`/`Fact`/`Hit`/`DigitalTwin` 存在；Fact 按 category 得到差异化 decay_rate（profile=0.0、event=0.05 等） | 必须 |
| AC-2 | Mock 后端 | `MockMemoryBackend` 追加/按 id 读/按会话读最近消息正确，会话间互不串扰 | 必须 |
| AC-3 | SQLite 后端 | `SQLiteMemoryBackend` 写入消息/fact/twin 后 close→重新 open，数据仍可读 | 必须 |
| AC-4 | Facts 提取 | 规则提取器从"我养了一只叫Max的狗，很喜欢吃披萨"得到 `pet_name=Max` 与至少一条 `preference`；写入后端；单值 key 新值 supersede 旧值 | 必须 |
| AC-5 | RRF 召回 | 六路召回对相关查询返回命中、对无关查询返回空；召回后命中消息 salience 提升 0.05 | 必须 |
| AC-6 | 遗忘衰减 | `daily_decay()` 对非 pinned fact 按 decay_rate 衰减，超过阈值标记 forgotten；pinned 与 profile 永不被遗忘 | 必须 |
| AC-7 | 数字孪生体 | 孪生体从 facts 自动构建 profile/skills/preferences/relationships/goals；`detect_inconsistencies` 检出单值 key 冲突 | 必须 |
| AC-8 | 世界对象与装配 | `WorldModel` 提供时间/知识边界/事件/天气且无网络时降级不抛；`MemoryManager` 组合 backend+world，`append_message` 自动 embedding | 必须 |

## 非功能 / 边界
- 错误态：SQLite 后端未 `initialize` 时调用数据方法应抛 `RuntimeError`。
- 依赖：核心路径不 import torch；BGE/httpx 仅在可选 extra 中惰性导入。
- 兼容：Python >= 3.11；本地文件 SQLite，无网络依赖即可跑通全部 AC。

## Assurance contract 摘要
- Profile：standard
- 受保护资产：本地记忆数据库（消息/facts/twin）的完整性与隐私
- 可信假设：开发者账户可信、本地文件系统可信
- 范围内失败/对手：误删/误写本地 db、错误输入导致异常、可选依赖缺失
- 明确范围外条件：网络中间人、恶意模型输出注入、云端多租户
- 最大可接受影响：本地单机记忆数据损坏/丢失（无跨用户或生产外泄面）

## 完成的定义（DoD 摘要）
- 8 条"必须" AC 全部有自动化断言通过
- 无回归（pytest 全绿）
- 文档与 ARCHITECTURE 同步
