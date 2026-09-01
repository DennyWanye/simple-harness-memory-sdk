## AC 覆盖审查
- HM-AC-1：`TC-HM-14` rev2 通过 fresh init、唯一 writable primary、旧 CRUD 四操作稳定 fence、epoch 拒绝与 pre/post raw manifest 直接证明。
- HM-AC-3：`TC-HM-11` rev4 直接证明单 foreground Run、durable FIFO、control overtaking、duplicate/lost-ACK/restart；`TC-HM-09` rev4 证明 Auto binding 只读 durable Run snapshot。
- HM-AC-4：`TC-HM-02` rev3 直接证明 permission-first bounded candidate、wrong principal/stale revision fail closed、exact-ID open，并明确断言 query/snippet/candidate poison 不进 ResumePackage/binding/tool grant。
- HM-AC-6：`TC-HM-02` rev3 与 `TC-HM-12` rev4 直接证明 1k/10k/100k 上限、EVIDENCE 500 events/page、单 page 32 KiB 和 stable page recovery。
- HM-AC-7：`TC-HM-12` rev4 覆盖 view/projection/page/checkpoint immutable refs/hashes 与 byte-identical rebuild；`TC-HM-14` rev2 覆盖 fence/export lineage。
- HM-AC-8：`TC-HM-11` rev4 与 `TC-HM-14` rev2 覆盖 fresh schema、legacy/future、projection/search/queue fault、duplicate/restart、drain-or-park、WAL、emergency export、critical+affected API；FTS5 unavailable 现已明确稳定 unavailable 且禁止越权 fallback scan。
- selected required testcase 都绑定至少一条 MUST AC 和 required obligation；无无目标 required case。

## 既有资产与复用决策
- HM-S4-TO-VALUE：`reuse-with-extension`，选 `TC-HM-02@3` + `TC-HM-11@4`；前者证 exact bounded resume，后者证 queued-turn 冷恢复，无重复 oracle。
- HM-S4-TO-VIEWS：`reuse-with-extension`，选 `TC-HM-12@4`。
- HM-S4-TO-FIFO：`reuse-with-extension`，选 `TC-HM-11@4`。
- HM-S4-TO-INTEGRATION：`create-new`，选 `TC-HM-14@2`；已记录相对既有用例的 fresh Host/primary/epoch/export 增量价值。
- HM-S4-TO-DATA：`create-new`，选 `TC-HM-14@2`；已记录跨 fence/drain/WAL/export raw-manifest 增量价值。
- HM-S4-TO-AUTHORITY：`reuse-with-extension`，选 `TC-HM-02@3` + `TC-HM-09@4`；`TC-HM-10@2` 的重复搜索步骤不计门，五路路由保持 S5/S6 non-gating。
- HM-S4-TO-REGRESSION：`create-new`，选 `TC-HM-14@2`；已记录 one-per-entrypoint 公开 API smoke 的增量价值。
- inventory/index、reuse report 和五个既有候选原文均已读；selected case 均 active，revision 与 index 一致，replacement 无断链/环，不继承历史 PASS。

## 缺失的必要测试（仅列出直接证明 AC 或防范受影响范围内风险的测试）
- 无。六条 MUST AC 和七条 required obligation 均有直接、分步、可判定的 testcase/scenario。

## 应删除或降级的测试（无目标绑定或超出受影响范围）
- 无。`TC-HM-10` 的 S4 部分已明确 non-gating，没有进入 `case_sets.full`。

## 步骤/预期不清的用例
- 无。第一轮中 `TC-HM-14` 步骤 8 的“每入口正负各一枪”与 fixture 不一致已改为“每入口一个有效请求 + 冻结的必要负例”。

## 建议新增的 required testcase（必须说明绑定哪个 AC 或防范哪个受影响范围内的风险）
- 无。再新增 case 会重复已选 02/09/11/12/14 的 oracle，不增加 AC 或 change-risk 覆盖。

## 输入广度盘点（仅当 input_sensitive=true 时必填）
- 不适用；`input_sensitive=false`，代表性 typed fixture 足以判定 S4 状态机、上限和恢复不变量。
- required 当前执行结果均为 PENDING/NOT_RUN：这是 phase-3 D 验证准备的预期状态，没有把 fixture self-check 当作产品 PASS。

## 最小充分性评估
- 当前 required testcase 总数：5
- 其中直接证明 AC 的：5
- 其中防范受影响范围内风险的：5（与 delivery 绑定有重叠）
- 建议删除/降级的：0
- 最终 required testcase 数：5

## 结论
- 当前 required 测试集是最小充分集：四个既有 case 分别承载 resume/binding/FIFO/views，一个新 Host scripted case 只填补 integration/data/regression 的公共缺口。
- 所有 MUST AC 都有 required testcase 覆盖，且七条 obligation 与 scenario 双向映射完整。

VERDICT: PASS
