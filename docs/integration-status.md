# Integration status

Status as of 2026-08-30: 0.6.0 is an unpublished source candidate requiring exact Harness
`>=0.7,<0.8`. Its Human Memory evidence/audit/suppression/analysis contracts require a clean exact-wheel
Harness 0.7 consumer gate before promotion. The pinned Harness source is
`8f1027d2d64ca3a7e7a4d161833507eadac9552b`; CI builds that 0.7.0 wheel once, passes its directory through
`HARNESS_SDK_ARTIFACT_DIST`, and reuses the same Harness and Memory bytes in clean consumers. Task 6 does
not publish, tag or push 0.6.
The published fallback remains 0.5.1.

## Historical 0.5 release evidence

Historical release fact as of 2026-08-24: `simple-harness-memory-sdk` 0.5.1 is published. It requires Harness
`>=0.4,<0.6`; this metadata-only expansion does not change
personal/family scope, cloud embedding lineage, receipt, outbox, or message behavior.

The exact-wheel matrix has two mandatory clean-venv cells: released Harness 0.4.0 and exact Harness
0.5.0 candidate/release bytes. The H0.4 cell passed locally against released wheel SHA-256
`aaf8d79a71b75bde0d71157a635b841eb557ea8889e2824571cacd7d8a58ecb6` and is automated in CI.
The current H0.5 candidate cell passed against Harness source commit `ac2e2add` and exact wheel SHA-256
`d5ac29760304b0eeebd40dd26bac7f8e65d0700a4066699a9f0d5fca6ec3f94c`; the privacy-safe receipt is
[`harness-compatibility-candidate-0.5.1-ac2e2add.json`](harness-compatibility-candidate-0.5.1-ac2e2add.json).
The earlier receipt committed at `e44d619` and its `7d70b9fa…` Harness candidate are explicitly
superseded and carry no promotion authority. Harness v0.5.0 is now Latest/non-draft/non-prerelease;
its public wheel is byte-identical to the accepted candidate and the H0.4/H0.5 formal matrix passed.
The formal receipt is [`harness-compatibility-release-0.5.1.json`](harness-compatibility-release-0.5.1.json).

Memory release verification is complete: annotated tag `v0.5.1` resolves to source commit
`da85fa2f61f5df213e292c752c79317dc23d79c1`; the wheel SHA-256 is
`314c1b89a1921abef3b9900a32b753cc0a0c89a3ce92b98822ec1cb45f7a9898` and the sdist SHA-256 is
`63b01464890098bb83c341de79aad7a4dd07ef11f4df3003ac744ad7ca0f69b3`. The
[`v0.5.1` Release](https://github.com/DennyWanye/simple-harness-memory-sdk/releases/tag/v0.5.1) is
Latest/non-draft/non-prerelease; public URL download-back, checksums, METADATA, BUILD_INFO source,
reproducible rebuild, and H0.4/H0.5 exact-wheel reruns passed.

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
