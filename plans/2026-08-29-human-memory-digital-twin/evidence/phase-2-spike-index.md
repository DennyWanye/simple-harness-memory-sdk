# Phase 2 Spike Evidence Index

## 运行结果

| Artifact | SHA-256 | 结论 |
|---|---|---|
| `spikes/manifests/spike-manifest.json` | `13a2f2b5a1f4d74993a573bac31ffdddd228dd782a78c31411eea04caaf3c326` | 固定 seed、规模、故障点与硬阈值 |
| `spikes/results/protocol-results.json` | `cae43f696e195311d88619455ec77661365dade255d0aa1334065b1215815a01` | runtime bridge、sanitization/continuation、trigger replay prototype PASS |
| `spikes/results/capacity-results.json` | `8fe7cfd072393c341ecfe0c8fa7fdd5f8d94ed86fed55132695de5281919f296` | vector/context/document disposable benchmark PASS |

执行命令及代码见 `spikes/README.md`。两个 Python spike 均通过 `ruff check` 和重复执行。

## 已证明的有限结论

- SQLite 事务 prototype 能以 source event+hash、Host receipt/cursor 和 terminal watermark 在指定 crash/replay 路径保持
  5/5 事件无缺口、无重复；route 后 Host/Harness/adapter payload 三方 hash 相等且 snapshot 可重放。
- pre-persistence sanitization receipt + durable Provider allowlist 可让三个固定 credential/hidden-CoT canary 在持久记录中
  零命中；V1 因此采用 opaque continuation ref，否则 reasoning disabled/provider rejected。
- Memory registration outbox→唯一 Host scheduler→occurrence inbox 的 prototype 在重复投递后只有一个 occurrence，pending
  不丢，snapshot hash 稳定，suppression 不披露正文。
- 在本机 synthetic 64-d float32 ground truth 上，100k exact cache 约 25.6 MB，warm p95 低于 1 ms、cold first query
  低于 20 ms，stale resurrection 为 0；因此不引入新 native ANN 依赖。
- 24 causal groups/1 MiB tool result prototype 证明“10 完整组 + typed summary/ref”可有界；1k/10k/100k event
  projection 证明 README/STATUS/Resume 顶层可维持固定 cap 和 stable page refs。

## 明确保留到实施门的事项（不得误报为已证明）

- Vector spike 证明 backend 数据结构/延迟，不证明真实 embedding 或主模型 RecallPlan 的语义质量；S3 仍必须跑冻结的
  200+ 人工标注 query set 并达到 AC-8。
- Context spike 使用保守离线 token oracle，不是实际 provider usage；S5 必须用真实 provider 校准，任何低估都阻断。
- Provider capability matrix 采用安全默认拒绝，尚未证明各 provider 有 opaque crash-resume handle；只有 adapter 集成测试
  证明后才能为相应 provider 开启 reasoning continuation。
- Protocol spike 是真实 SQLite crash/reopen prototype，但不是生产 Host/Harness/Memory 代码；S1/S4/S5 必须复现相同
  fault matrix、三方 hash 和 canary scan。
