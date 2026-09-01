## AC 覆盖审查
- HM-AC-1：`TC-HM-14` 覆盖 fresh primary、旧 CRUD fence、epoch 拒绝和 raw manifest，基本完整。
- HM-AC-3：`TC-HM-11` rev4 覆盖单 foreground Run、durable FIFO、control overtaking 和 restart；`TC-HM-09` rev4 覆盖 durable Auto snapshot。
- HM-AC-4：`TC-HM-02` rev2 覆盖 permission-first candidate→exact open 和 candidate-only 不改 authority，但尚未明确说明 poisoned query/snippet/candidate metadata 不得进入 ResumePackage 或改变权威。
- HM-AC-6：`TC-HM-02` rev2 与 `TC-HM-12` rev4 覆盖 100k、顶层字节上限、稳定分页和 canonical coverage。
- HM-AC-7：`TC-HM-12` rev4 覆盖 immutable revision/ref/hash 与 byte-identical rebuild；`TC-HM-14` 覆盖 recovery/export lineage。
- HM-AC-8：`TC-HM-11`/`TC-HM-14` 覆盖 duplicate/restart、drain-or-park、WAL、legacy/future，但 FTS5 unavailable 时的稳定 unavailable 与禁止越权 fallback scan 未落到分步 testcase。
- 无未绑定 AC/change-risk 的 selected required testcase。`TC-HM-10` rev2 已明确为 S4 non-gating，不重复计门。

## 既有资产与复用决策
- HM-S4-TO-VALUE：已读 `TC-HM-02`/`TC-HM-11` 原文，`reuse-with-extension`，分别证明 100k exact resume 和队列连续性。
- HM-S4-TO-VIEWS：已读 `TC-HM-12` 原文，`reuse-with-extension`。
- HM-S4-TO-FIFO：已读 `TC-HM-11` 原文，`reuse-with-extension`。
- HM-S4-TO-INTEGRATION：已审查五个既有候选，`create-new` 为 `TC-HM-14`，增量价值是 fresh Host/primary fence/epoch/export 联动。
- HM-S4-TO-DATA：已审查现有 rebuild/restart 步骤，`create-new` 为 `TC-HM-14`，增量价值是跨 fence/drain/WAL/export 的 raw manifest 守恒。
- HM-S4-TO-AUTHORITY：已读 `TC-HM-02`/`TC-HM-09`/`TC-HM-10` 原文，`reuse-with-extension`，选 02+09；10 重复且其余路由属 S5/S6。
- HM-S4-TO-REGRESSION：`create-new` 为 `TC-HM-14`，增量价值是 critical+affected 公开入口矩阵。
- selected testcase 均 active、revision 已固定，replacement 无断链/环，不继承历史 PASS。

## 缺失的必要测试（仅列出直接证明 AC 或防范受影响范围内风险的测试）
- [HM-AC-4 / FAIL-TASK-SEARCH-AUTHORITY] 缺 poisoned query/snippet/candidate metadata 零进入 ResumePackage/binding/tool authority 的明确分步断言。
- [HM-AC-8] 缺 FTS5 unavailable 稳定拒绝且不降级为未经 permission filter 的模糊扫描断言。

## 应删除或降级的测试（无目标绑定或超出受影响范围）
- `TC-HM-10` 的五路自然语言路由保持 non-gating，已经正确降级，无需删除。

## 步骤/预期不清的用例
- `TC-HM-14` 步骤 8 声称每个入口各一个有效和一个失败请求，但冻结 fixture 只为 wrong-principal 和旧 CRUD 等真正受影响失败边界建负例。建议把步骤改为“每个入口一个有效请求 + 冻结的必要负例”，避免为了对称而测无关错误。

## 建议新增的 required testcase（必须说明绑定哪个 AC 或防范哪个受影响范围内的风险）
- 不建议再新建 testcase；上述两个缺口应分别扩展 `TC-HM-02` 和 `TC-HM-14`，保持最小集。

## 输入广度盘点（仅当 input_sensitive=true 时必填）
- 不适用；`input_sensitive=false`，S4 是 typed deterministic Host 行为。required 仍 PENDING 的当前执行结果：全部，因本轮只准备 oracle、禁止运行产品测试。

## 最小充分性评估
- 当前 required testcase 总数：5
- 其中直接证明 AC 的：5
- 其中防范受影响范围内风险的：5（与 delivery 绑定有重叠）
- 建议删除/降级的：0（`TC-HM-10` 已 non-gating）
- 最终 required testcase 数：5

## 结论
- 当前集合接近最小充分，但搜索污染和 FTS unavailable 两个明示验收边界尚未落到可执行步骤。
- 所有 MUST AC 都有候选 testcase，但 HM-AC-4/HM-AC-8 的上述子边界尚不足以 PASS。

VERDICT: FAIL
