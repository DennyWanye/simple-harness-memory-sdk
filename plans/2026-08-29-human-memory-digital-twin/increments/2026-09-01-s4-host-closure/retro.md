# retro（自我批评，2026-09-01 P1 闭环轮）

真拦住问题的门：独立 full-audit round-1 抓住了"archive smoke 冒充执行价值链证据"的账本绑定断点（plan 明文禁止而执行时仍犯）——qualitative auditor 与 deterministic validator 互补的价值实锤。空转/拖慢的环节：re-attest 把 ARCHITECTURE 文档回写判为 behavioral 触发全量复测（impact_paths 未覆盖文档路径，fail-closed 代价 ~30 分钟），且复测批次因复用 runner artifact 目录（残留 sdk-runtime durable 状态）产生三次瞬态假红、误诊为后台 QoS——教训：①编 manifest 时把纯叙述文档目录列入 impact 豁免或单列 doc 类；②runner artifact 目录一次一用应写进 runner 本身而非靠纪律。
