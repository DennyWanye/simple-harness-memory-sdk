# V0 Closure — Human Memory Program 验收权威

> 状态：V0 infrastructure complete；program scenarios 尚未执行。
> Program run：`run-20260830-103900`
> Active run：`verification/program-delivery-20260830-v2`
> 本文件不是最终 PASS receipt；最终状态只由 S1—S6 完成后的 machine `finalize` 决定。

## 冻结结果

- Host testcase inventory：145 项，其中 13 个 Human Memory required testcase、10 个旧 Session/workspace oracle
  `superseded`、8 个不冲突或已改写到单主对话/TaskScope 的 `TC-GS-03`—`TC-GS-10` 保持 active、109 个 legacy `needs-review`。
- 21 个 required testcase 与 reuse selected set 精确相等：`TC-HM-01`—`TC-HM-12`、`TC-HM-X01`
  加当前 revisions 的 `TC-GS-03`—`TC-GS-10`；历史 PASS 未继承。
- 8 个 delivery obligation 与 8 个 change-risk obligation 各有且仅有一条 reuse decision；HM-AC-1—8
  均进入 compiled manifest，15 个 required scenarios 的 testcase union=21。
- 旧 `TC-PS-*` 与含多 Session oracle 的 `TC-GS-*` 原文件、步骤和历史结果均保留；只追加
  `status=superseded` 与合法 replacement lineage。旧“物理删除 conversation/Memory 才算成功”的
  `TC-PS-08` 被 `TC-HM-X01` 取代，不再是 active authority。
- 冻结模型评估口径：12 个语义不等价类别 × 20 query=240，四种表达形式轮换；两次独立真实主模型
  root 聚合且每一轮也必须过门。第一轮要求同一主对话 >=20 committed turns、两个 TaskScope、一次 exact resume，
  并含 tool/Provider/记忆/纠正/遗忘/Prospective。

## Authority hashes

| Artifact | SHA-256 |
|---|---|
| `acceptance.md` | `ab4dbe080e27ab4a29bf4be74b539363b489f9ad165eadf748fb3b8019cbc067` |
| `assurance-contract.json` | `d828f016110bd876c364c9b17fdf2c316557988a7be6f8195d25aa0eb1b3e6a8` |
| `verification-spec.json` | `a626a557ee15388582a43ae9f7fa0a6894997f49c4c160adc95c947a4eadbd27` |
| `testcase-reuse-report.json` | `2d65d1a702ae7166b5ed3cf18430da166b045a6acb2dfaa490cac8e50204fed9` |
| `manifest.json` | `51459be0e11f58ca7d558ba375b3c63912b37c745d82e0d95c78b1ab6d2bd562` |
| compiled manifest seal | `dd9ef30e1df054330250fd65f1afee756b0347c46e125f37e6e21b87b4f7e0ed` |

Repository authorities at V0 seal:

- Memory SDK authority：`5bbc75dd3d60a847e5a2c5242b172105af303481`
- Harness SDK baseline：`255f966d753b61034d0ad7d36f35e43819bacdf3`
- Host testcase authority：`1801655a08ef16a3ac38b20d32abb871a0385e60`

## Spike closure

| Spike evidence | SHA-256 | V0 decision |
|---|---|---|
| `spike-manifest.json` | `13a2f2b5a1f4d74993a573bac31ffdddd228dd782a78c31411eea04caaf3c326` | seed、规模、fault points 与 hard thresholds 冻结 |
| `protocol-results.json` | `cae43f696e195311d88619455ec77661365dade255d0aa1334065b1215815a01` | runtime bridge、pre-persistence sanitization、唯一 Host scheduler prototype 可行 |
| `capacity-results.json` | `8fe7cfd072393c341ecfe0c8fa7fdd5f8d94ed86fed55132695de5281919f296` | SQLite+NumPy exact cache、10 完整因果组、bounded read views prototype 可行 |

这些 spike 只关闭实现可行性，不继承为生产 PASS：synthetic vector 不证明真实语义质量，离线 token oracle
不证明真实 Provider usage，provider opaque continuation 仍须各 adapter 证明；未证明者固定
`reasoning_disabled|provider_rejected`。

## Gate 状态

- `compile-manifest`：15 scenarios / 21 selected testcases / full=15。
- testcase inventory + reuse + revision lock：PASS。
- `validate-release-unit`：`RELEASE_UNIT_VALID`（V0；8 MUST AC；7 tasks；3 high-risk subsystems）。
- program ledger 已初始化并 active；15 个场景当前均为 `NOT_RUN`，这是实施前的真实状态，不用 mock/spike
  冒充通过，也不在 V0 提前 `finalize`。
- 被复审淘汰的 13-case 本地 ledger 未删除，已移到
  `.local-test-evidence/2026-08-30/human-memory-v0/obsolete-ledgers/program-delivery-20260830-13case` 留作审计。

## S1 入场条件

V0 没有修改业务实现。S1 可开始，但必须以本 manifest、21 个 testcase 原文、fixture/spec hashes 与已有
Phase 2 challenge closure 为不可反向修改的验收权威。任何 P0 技术假设在生产 seam 失败，停止对应 slice 并回到 review。
