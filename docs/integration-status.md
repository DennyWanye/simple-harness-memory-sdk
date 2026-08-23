# Integration status

Status as of 2026-08-24: `simple-harness-memory-sdk` 0.5.1 is an unpublished compatibility
candidate. It requires Harness `>=0.4,<0.6`; this metadata-only expansion does not change
personal/family scope, cloud embedding lineage, receipt, outbox, or message behavior.

The exact-wheel matrix has two mandatory clean-venv cells: released Harness 0.4.0 and exact Harness
0.5.0 candidate/release bytes. The H0.4 cell passed locally against released wheel SHA-256
`aaf8d79a71b75bde0d71157a635b841eb557ea8889e2824571cacd7d8a58ecb6` and is automated in CI.
The H0.5 candidate cell passed against Harness source commit `7fd6610` and exact wheel SHA-256
`7d70b9fa2f5953ce8b2ba23cc0b9bc40fb101631964b25dcb047effda8f71167`; the privacy-safe receipt is
[`harness-compatibility-candidate-0.5.1.json`](harness-compatibility-candidate-0.5.1.json). The final
Harness release/download-back cell remains pending. Memory 0.5.1 must not be published before it passes.

Release verification: source full suite `213 passed, 7 skipped`; Ruff and strict mypy passed;
the frozen 0.5.0 wheel/sdist passed Twine and the 10-test joint Harness 0.4 artifact suite.

The prior 0.5.0 promotion is complete: tag `v0.5.0` points to source commit `9c92ede`, and
`candidate-dist/BUILD_INFO.txt` plus `SHA256SUMS` identify wheel `c274fa6b…`. The source branch,
`main`, and tag have been pushed. The frozen wheel/sdist are published at the
[`v0.5.0` Release](https://github.com/DennyWanye/simple-harness-memory-sdk/releases/tag/v0.5.0),
and the public stable wheel URL returns the exact bytes verified by download-back checksums.

| Consumer | Interface status | Product integration / testing |
|---|---|---|
| `simple_harness` | Harness 0.4.0 / Memory 0.5.0 exact wheels integrated | Observability, privacy, candidate-origin, and diagnostic-bundle automated regression passed. |
| AIPhone | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. |
| K6/AgentOS | Agent Memory v1 interface ready | Not integrated, modified or tested in this Program. Existing product data is untouched. |
| NovelTagSystem | Outside this integration | Not modified, migrated or tested. |

The SDK conformance boundary covers trusted deployment/household/actor/session identity, personal/family
scope, automatic recall and committed-turn delivery. It does not claim product-specific authentication,
deployment, database migration, UI behavior or cross-device synchronization for future consumers.

The simple_harness result does not change the future-consumer boundary: AIPhone, K6/AgentOS, and
NovelTagSystem received no code change and no product validation in this program.
