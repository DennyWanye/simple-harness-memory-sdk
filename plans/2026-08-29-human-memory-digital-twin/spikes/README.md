# Phase 2 disposable spikes

这些脚本只验证计划的高风险假设，不进入 SDK/Host 生产包。固定输入和阈值见
`manifests/spike-manifest.json`。小型 JSON 结论写入 `results/`；若产生大型 DB/日志，应写到项目
`.local-test-evidence/` 并只在计划中保存 hash/index。

- `run_protocol_spikes.py`：same-Run Context/执行证据桥、hidden-CoT/credential admission、Prospective trigger replay。
- `run_capacity_spikes.py`：100k 向量 exact-cache backend、24-group Context、100k TaskScope event bounded views。

运行：

```bash
python spikes/run_protocol_spikes.py --manifest spikes/manifests/spike-manifest.json --output spikes/results/protocol-results.json
python spikes/run_capacity_spikes.py --manifest spikes/manifests/spike-manifest.json --output spikes/results/capacity-results.json
```
