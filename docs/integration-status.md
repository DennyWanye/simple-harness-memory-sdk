# Integration status

Status as of 2026-08-23 for `simple-harness-memory-sdk` 0.4.0:

Local promotion is complete: tag `v0.4.0` points to source commit `3d4247b`, and
`candidate-dist/BUILD_INFO.txt` plus `SHA256SUMS` identify wheel `bfcd2506…`. The source branch,
`main`, and tag have been pushed. The frozen wheel/sdist are published at the
[`v0.4.0` Release](https://github.com/DennyWanye/simple-harness-memory-sdk/releases/tag/v0.4.0),
and the public stable wheel URL returns the exact bytes verified by download-back checksums.

| Consumer | Interface status | Product integration / testing |
|---|---|---|
| `simple_harness` | Exact-wheel 0.4.0 integrated | Product cutover, automated regression, and real macOS UI testing passed on `4e797ccd` with Memory `3d4247b`; includes cold restart and recall/record fault recovery. |
| AIPhone | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. |
| K6/AgentOS | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. Existing product data is untouched. |
| NovelTagSystem | Outside this integration | Not modified, migrated or tested. |

The SDK conformance boundary covers trusted deployment/household/actor/session identity, personal/family
scope, automatic recall and committed-turn delivery. It does not claim product-specific authentication,
deployment, database migration, UI behavior or cross-device synchronization for future consumers.

The simple_harness result does not change the future-consumer boundary: AIPhone, K6/AgentOS, and
NovelTagSystem received no code change and no product validation in this program.
