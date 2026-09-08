# 决策备忘：短时域 chunk 长度上限与确定性切段（0.6.30）

> 日期：2026-09-08 ｜ 版本：`simple_harness_memory_sdk 0.6.30`（本地候选，分支 `m0630`）
> 上游证据：Host 备忘 `simple_harness/plans/2026-09-08-hm-to-a6/DECISION-RECALL-TIMEOUT-HOST-SIDE.md` §2、
> `DIAG-RECALL-TIMEOUT.md` §2.3/§2.4
> 契约文本：`slices/S3-cognitive-systems-recall.md` Task 4（本次追加 §4-补 2026-09-08）；
> `slices/S5-host-context-integration.md`（本次追加 Host 侧不得假设"一组一条"的交叉引用）
> 相关决策：`DECISION-2026-09-08-recall-authority-epoch.md`（0.6.28 车道分类）、
> `DECISION-2026-09-07-cognitive-vector-lane.md` §4（不在写锁内嵌入、冷态只退化不失败）

---

## 1. 问题

HM-TO-A6 turn 22：现场 6 条短时域 chunk 的长度为 54 / 108 / 1 682 / 7 798 / 19 655 / **29 778** 字符，
真实 WeMM 逐条嵌入耗时 912 / 2 430 / 3 038 / 5 121 / 10 304 / **23 885** ms，一次世代重建 45.7 s。
0.6.27 已把嵌入移出写锁、0.6.28/0.6.29 已修正 epoch 围栏，但**单条 chunk 的成本本身没有上限**：

- `rebuild_short_horizon_projection`（`backends/sqlite_v5.py`）对每个完整因果组
  `content = "\n".join(f"{role}: {public_text}")`，**一组一条、无任何长度上限**；
- `chunk_id`/`content_hash` 都是该 content 的内容寻址哈希，Host 侧的 `public_text_hash` 绑定校验
  fail-closed，Host 无法截断（备忘 §2 已论证"Host 实现了就是破坏契约"）；
- S3 Task 4 / S5 的契约文本里**没有**任何 chunk 长度条款——这是一条需要**新增**的契约。

除了嵌入成本，超长 chunk 对召回消费方也是无用的：`RecallBudget.max_bytes` 协议上限 65 536、Host 取
16 384，一条 29 778 字符（约 89 KB UTF-8）的 chunk 永远放不进预算（S3 §5.6"单项永不截断；放不下则跳过"），
即使被命中也只会被跳过——**它既拖垮维护，又不能被使用**。

## 2. 裁定：切段而不是截断；不改 DDL；只嵌入新 chunk

| 方案 | 裁定 | 理由 |
|---|---|---|
| A. 只截断每组 `public_text` 的头部（一组仍一条） | **否** | 尾部内容从短时域彻底不可召回；Host 备忘与任务书都要求"再分块"；截断不是限长 |
| B. 只在向量层对超长 chunk 做分段池化（行不变） | **否** | 召回 hit 返回的仍是整条 29 778 字符 content，放不进预算；FTS 也只能整条命中 |
| C. **按长度上限把一个因果组切成多条内容寻址 chunk**（本次） | **是** | 每条都能进预算、每次嵌入调用有界、尾段可词面/向量命中；未变化的组 id 逐字不变 |
| C-1. 放宽 `short_horizon_chunks` 的 `UNIQUE (principal_id, primary_conversation_id, causal_group_id)`，加 `segment_ordinal/segment_count` 列（schema 7.5） | **推迟** | 需要一次**非附加式**的表重建前向迁移（7.x 线首例）、新的 catalog 变体与 marker 协议、`upgrade_validation` 的"前向不得改行"要放宽；投影表是可丢弃派生物，为一条可由注册 + 纯函数严格重推的事实做 DDL 切换，正是 0.6.27/0.6.29 拒绝过的代价 |
| C-2. **投影键编码**：分段 chunk 在 `causal_group_id` 列存 `<causal_group_id>\x1f<k>/<K>`，未分段的组仍存裸 Host id（本次） | **是** | 零 DDL、7.4 checksum 不变；行形状对未分段组逐字不变；所有读路径都经 `parse_short_horizon_projection_key`/`resolve_short_horizon_projection_row` 重推，一致性校验按投影键逐段重算 `chunk_id`，键写错即判损坏 |
| D. 世代重建沿用 active 世代里同 chunk_id 的向量，只嵌入新 chunk（本次一并做） | **是** | 切段只让**单条**成本有界；每次世代重建仍把 5 天窗口**全部**重嵌入才是维护 tick 的真正乘数。chunk_id 内容寻址 + 同 lineage ⇒ 向量是同一个纯函数值，沿用是精确的，不是近似 |

投影键为什么能不撒谎：`causal_group_id` 列在**投影表**里本来就是路由键而非权威（权威在
`conversation_evidence_registrations`），Host 从不读投影表；分隔符 U+001F 在注册时 fail-closed
（`conversation_registration_causal_group_id_reserved`），因此裸 Host id 与编码键在同一会话里不可能碰撞。
C-1 仍是更"诚实"的长期形态：**下一次不可避免的 DDL 切换时**顺带放宽该 UNIQUE 并加 segment 列，
届时投影键编码退役、`parse_short_horizon_projection_key` 只剩兼容读路径。

## 3. 契约条款（逐字追加到 S3 Task 4 之后）

> **§4-补（2026-09-08，0.6.30）短时域 chunk 长度上限与确定性切段**
>
> 1. 一条短时域 chunk 的内容（`role: public_text` 行以 `\n` 连接后的渲染文本）最多
>    `SHORT_HORIZON_CHUNK_MAX_CHARS = 2 048` 个 Unicode 码点。渲染文本不超过上限的完整因果组仍然
>    是**一组一条**，其 `chunk_id`/`content_hash`/投影行与 0.6.29 逐字相同。
> 2. 超过上限的完整因果组由 SDK 按以下确定性规则切成 K 条内容寻址 chunk：先按注册（item）边界整行装箱；
>    单行超过上限时依次优先在段落（`\n`）、句子（`。！？!?`）、空白处切分，且切点必须落在窗口后半段
>    （不产生小于上限一半的碎片），否则在上限处硬切；切分只在码点边界发生，永不切开一个码点；一条注册
>    被切出的各段拼接回去逐字等于原 `public_text`。
> 3. 每个因果组最多投影 `SHORT_HORIZON_CHUNK_MAX_SEGMENTS = 8` 段；之后的尾部**不投影**（原始证据与注册
>    不受影响），审计 `projection_rebuilt.details.truncated_group_count` 与
>    `ShortHorizonProjectionBuildResult.truncated_group_count` 记录被截断的组数；
>    `split_group_count` 记录被切段的组数。
> 4. 分段 chunk 的 `chunk_id` payload 在 0.6.29 的域上追加 `segment_ordinal=k` 与 `segment_count=K`
>    （K=1 时不出现，保证旧 id 稳定）；投影表 `causal_group_id` 列存投影键 `<causal_group_id>\x1f<k>/<K>`；
>    Host 注册的 `causal_group_id` 不得包含 U+001F，含有者注册即拒绝
>    （`conversation_registration_causal_group_id_reserved`）。
> 5. 每一段的血缘（`short_horizon_chunk_evidence`）都是**整个因果组**的全部注册；任一证据被抑制则该组
>    全部段一起消失（S3 Task 4"部分上下文绝不可见"不变）；`occurred_at/expires_at`、privacy/attributes/
>    classification refs、roles/task/entity/source refs 都按组聚合、各段相同；过期、清理、分页、召回、
>    历史可见性一律按 chunk 行处理，对分段透明。
> 6. 升级：0.6.29 写出的"一组一条"超长 chunk 行在 0.6.30 打开时**不是损坏**（一致性校验与历史可见性
>    对裸键行接受 0.6.29 形状，且要求它是该组唯一一行），下一次投影重建以分段替换它。该替换是既有
>    `chunk_id` 的移除，按 0.6.28 车道恰好推进一次召回权威 epoch（`short_horizon_projection_changed`），
>    绑定旧 chunk 的召回结果由此正确失效；绑定其他来源的结果按 0.6.29 逐来源重校验照常放行。
> 7. 投影重建改为**增量**：只删除目标清单里不再存在的 `chunk_id`、只插入新出现的 `chunk_id`，未变化的
>    chunk 连同 FTS 镜像、血缘行与 active 世代向量原样保留；世代重建沿用 active 世代（同 lineage、
>    hash/维度校验通过）里同 `chunk_id` 的向量字节，只对新 chunk 调用 `embed_batch`，审计
>    `generation_activated.details.embedded_count/reused_vector_count`。世代身份、manifest、CAS、
>    replay、空集与失败语义（0.6.27）逐字不变。
> 8. Host 侧不得假设"一个因果组一条 chunk"：`projected_chunk_count` 可大于完整因果组数；
>    Host 只通过 `chunk_ref`/`content_hash` 绑定来源，不解析投影键。

## 4. 参数为什么是 2 048 / 8

- **2 048 码点**：中文约 6 KB UTF-8、英文约 2 KB。Host `RecallBudget(8, 16_384, 2_048, 2_000)`
  下能同时放下 2–3 条中文段、8 条英文段；`max_tokens=2_048` 与 S3 保守估算 `tokens=max(码点数, bytes/3)`
  对齐——一条 chunk 恰好不会单独吃光 token 预算。现场 1 682 字符的 chunk 保持一条（id 不变），
  7 798 / 19 655 / 29 778 三条被切。
- **8 段**：每组最多投影 16 384 码点。按 DIAG §2.3 的实测曲线（≈230 ms 固定开销 + ≈0.57 ms/字符，
  上端超线性），一个新出现的超长组最坏约 8 × 1.4 s ≈ 11 s 嵌入，两三个这样的组仍在 Host
  `maintenance_timeout=60 s` 内；不设段数上限则一次 300 k 字符的粘贴会产生 150 段、数分钟嵌入，
  超时后无部分进度地整批重试——正是 0.6.27 消掉的活锁形态。曾考虑 16 段（覆盖现场 29 778 全部），
  但在世代构建有部分进度语义之前，8 是"冷态只退化不失败"的保守取值；**被截掉的尾部仍在原始证据里，
  分析车道提取长期记忆不受影响**。
- 切点"落在窗口后半段"：避免第 5 个字符处的换行把一段切成 5 个字符 + 2 043 个字符的两条 chunk。
- 不做 grapheme cluster 级别切分：契约只承诺"不切码点"；组合字符/ZWJ 序列在硬切时可能被分开，
  只影响极少数硬切场景的检索文本，不影响内容寻址与重推。

## 5. epoch 裁定（对照 0.6.28 车道分类）

0.6.28 把 `short_horizon_projection_changed` 收窄为"仅当 `removed_chunk_count > 0`"，判据是
「既有 `chunk_id` 集合 − 目标集合」——它与"Short-Horizon source 失效"一一对应。切段带来的三种情形：

| 情形 | `removed_chunk_count` | epoch | 为什么 |
|---|---|---|---|
| 新出现的超长组第一次投影为 K 段 | 0 | 不推进 | 纯新增，无既有来源受影响 |
| 0.6.29 遗留的单条超长行被 K 段替换 | 1 | **推进一次** | 旧 `chunk_id` 真的消失；绑定它的召回结果在 `_validate_recall_context_use_sources_unlocked` 里本就会因"行不存在"而 stale，推进 epoch 与之一致 |
| 未变化的组 | 0（增量重建连行都不动） | 不推进 | id/内容逐字相同 |

因此**不需要新的车道、不需要新的事件类型**；升级后每个遗留超长组只会在第一次重建时贡献一次推进，
之后回到 0.6.28 的稳态。世代重建沿用向量仍是"纯索引重建"，继续不推进（0.6.28 第 3 项）。

## 6. 变更

| 文件 | 变更 |
|---|---|
| `core/short_horizon.py` | 常量 `SHORT_HORIZON_CHUNK_MAX_CHARS/…_MAX_SEGMENTS/…_PROJECTION_KEY_SEPARATOR`；纯函数 `split_short_horizon_content`（`ShortHorizonSplit`）、`render_short_horizon_line`、`short_horizon_projection_key`/`parse_…`、`short_horizon_segment_payload_fields`、`resolve_short_horizon_projection_row`（`ShortHorizonProjectionRow`，含遗留形状接受）；`ShortHorizonChunk` 追加 `segment_ordinal/segment_count`（默认 1）；`build_short_horizon_chunks` 同规则切段；`ShortHorizonProjectionBuildResult` 追加 `split_group_count/truncated_group_count`（默认 0，位置构造不变） |
| `backends/sqlite_v5.py` | `register_conversation_evidence` 拒绝含 U+001F 的 `causal_group_id`；`rebuild_short_horizon_projection` 切段 + 投影键 + 增量删插 + 审计计数；`_validate_short_horizon_integrity_unlocked` 按投影键重推每段、遗留行只接受为该组唯一一行；`rebuild_short_horizon_generation` 新增 `_reusable_short_horizon_vectors_unlocked` 与只嵌入新 chunk 的装配 |
| `backends/short_history_visibility.py` | `check_selected_chunk` 按投影键重推该段、比对解码后的 Host `causal_group_id` |
| 契约面 | 无 DDL 变化（7.4 checksum 不变）；根导出零增减（新常量与函数只经 `core.short_horizon` 可达）；快照 `public-api-0.6.30.json` 除 `version` 外与 0.6.19 起逐字相同 |

## 7. 验证

- `tests/unit/test_short_horizon_chunk_cap.py` 8 项：常量冻结；恰好到上限仍一段且 payload 无 segment 字段；
  整行装箱先于切行；段落 → 句子 → 空白 → 硬切的优先级与"后半段"规则；astral 码点文本切段后逐段合法、
  拼接逐字还原、纯函数确定；段数上限与 `truncated`；投影键往返与 7 种畸形键 fail-closed；
  行重推对裸键接受 0.6.29 形状、对编码键 K 不符即拒。
- `tests/integration/test_short_horizon_chunk_cap.py` 7 项（夹具 = 事故原型：一个 29 778 字符的 assistant
  项 + 小组 + 11 个最近组）：
  ① 未分段组的 `chunk_id`/`content_hash` 与**在 0.6.29 源（main `c025c98`）上用同一夹具算出的字面值**逐字相同
  （`short:a70e0fc0…983a` / `short:2157a1a3…7d2f`），超长组恰为 8 段、投影键 `group-long\x1f{k}/8`、
  每段 ≤ 2 048 码点、内容寻址、每段血缘 = 整组两条注册、FTS 镜像逐行对应、审计计数、replay 幂等、
  关闭重开一致性通过；② 只出现在第 8 段的错误码经 `recall_short_horizon` 词面 lane 命中该段且
  `check_history_visibility` 可见，被截尾部零命中；③ 用极大上限复现 0.6.29 的"一组一条"投影，其 id 等于
  0.6.29 源算出的 `short:16cf4779…3710`，0.6.30 打开不判损坏、可召回可见，下一次重建
  `removed_chunk_count=1`、epoch 恰好推进一次（`initialized` + `short_horizon_projection_changed`）、
  旧绑定不可见、再重建不再推进；④ 世代重建 `[10, 1]`：第二代只嵌入新 chunk，其余 10 条向量字节与第一代
  逐字相同，审计 `embedded_count=1/reused_vector_count=10`，重开 replay 不再嵌入；⑤ 含 U+001F 的
  `causal_group_id` 注册被拒且零行；⑥ 压制超长组任一证据 → 8 段一起消失，跨过 5 天 cleanup 按行移除；
  ⑦ 两个全新库切段结果逐字相同。
- 全量 `tests/`：基线（main `c025c98`，独立 worktree）63 failed / 1576 passed / 8 skipped；本改动后
  63 failed / 1591 passed / 8 skipped，失败集合 `diff` 为空，passed +15 恰为新增用例。

## 8. Host 侧交接

- `backend/tests/memory/test_primary_short_ingestion.py:99`、`test_short_terminal_source.py:27` 断言
  `projected_chunk_count == 1`——夹具文本远小于 2 048 码点，**仍然成立**；但 Host 不得在生产逻辑里
  假设"一组一条"（条款 §4-补 8）。
- `WeMMEmbedder.embed_batch` 的分组批处理（备忘 §1，`最长 × 条数 ≤ 1024`）对 ≤ 2 048 码点的段仍是
  一段一次调用；若要让分段真正批起来，`_BATCH_MAX_PADDED_CHARS` 需要按实测重新标定（Host 决定）。
- 世代构建的"部分进度"（一次 tick 只嵌入前 N 条、下一 tick 续上）是把 8 段上限抬到 16 的前提，属 SDK
  后续；认知向量世代（`rebuild_cognitive_vector_generation`）仍是整代重嵌入，同样可沿用向量，本次未做。
- 仅本地候选（分支 `m0630`），未合 main、未构建 wheel、未 push、Host 未 pin。
