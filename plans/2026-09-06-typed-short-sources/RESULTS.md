# Typed short sources — source evidence

2026-09-06. Real public typed execution and SQLite, HashEmbedder fixture only; no
model weights/native/build. Full source suite not run. One process at a time,
process-tree cap1GiB/deadline120s, no cap hit. Source overlay explicitly declared.

- First15 failures were fixture RecallContext selector/constraint mismatch, before
  new port execution. Corrected the fixture to real context/plan selector contracts;
  second15PASS2.30s. First log kept, not counted as a product red-to-green fix.
- Expanded necessary scope31 cases:29PASS/2FAIL4.70s. Real newport bug: wrong
  deployment/household with same actor bypassed inherited S1-placeholder convention.
  Newport-only exact principal check closes this; unchanged two negatives and seven
  positive/current neighbors9PASS1.58s. Old port compatibility preserved.
- Extracted collector static F821 check found missing local mismatch constant in
  receipt mismatch branch. Restored constant; ruff --select F passes. Shared new/old
  source positive/reopen2PASS0.75s. This correction adds no new validation scope.
- Final unique source scope31 (new20, old source10, frozen DTO hash vector1), green
  across the above bounded runs; repeated cases are not summed. Actual new tests
  cover duplicate/one-clock/reopen, four forged tuple fields, genuine nonselected and
  cognitive items, actor/subject/deployment/household/disclosure/expiry/evidence-only/
  MEMORY-only forget, three derived lineage corruptions, wrong binding port, same-TX
  forget ordering and cancel rollback. No raw evidence physically deleted/restamped;
  corruption tests only mutate derived projections and expect close integrity failure.
- Receipt source shape includes actual owned source_ref/source_hash/envelope/admission/
  registration hashes. Host full causal-group/final outgoing policy is a separate gate.
  No version/build/install claim yet; source independent review pending.

## Raw command records (ignored local only)

```sh
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/bin/python -m pytest tests/integration/test_typed_short_sources.py -q -p no:cacheprovider -p pytest_asyncio.plugin
```

Exit1; monitor2.414s; sampled RSS118048KiB.

`.local-test-evidence/2026-09-06/typed-short-sources/first.json` SHA256 `d8ae84a7eafdff2543c16c9317dadd5372e7acfcf696ecde33c257408f72fe45`.

`.local-test-evidence/2026-09-06/typed-short-sources/first.log` SHA256 `62640b3d7b9a73e06ecdcd2109d15445e26c8e9f88c1f346e49562564ddd400e`.

```sh
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/bin/python -m pytest tests/integration/test_typed_short_sources.py -q -p no:cacheprovider -p pytest_asyncio.plugin
```

Exit0; monitor2.497s; sampled RSS119184KiB.

`.local-test-evidence/2026-09-06/typed-short-sources/second.json` SHA256 `712c4f4d6d685710757ed7b43ef3b0b836492ac1d201823a9d4873ae1f2481cc`.

`.local-test-evidence/2026-09-06/typed-short-sources/second.log` SHA256 `d8314e05bda208617333aac1a69330b74184e267eaa2d7a8891e741261332f67`.

```sh
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/bin/python -m pytest tests/integration/test_typed_short_sources.py tests/integration/test_short_sources.py tests/unit/test_short_sources_contract.py -q -p no:cacheprovider -p pytest_asyncio.plugin
```

Exit1; monitor4.893s; sampled RSS121680KiB.

`.local-test-evidence/2026-09-06/typed-short-sources/adjacent.json` SHA256 `43ffb2430e3a2f9655a35d59d8915c491aaa8df229425dfcc9f401a3f35ff49b`.

`.local-test-evidence/2026-09-06/typed-short-sources/adjacent.log` SHA256 `72dcbb88454d072c5959712d2252fab9f83d7657220b6fc40abd800214e1eddd`.

```sh
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/bin/python -m pytest tests/integration/test_typed_short_sources.py::test_same_actor_wrong_principal_rejected tests/integration/test_typed_short_sources.py::test_exact_duplicate_domain_clock_and_reopen tests/integration/test_typed_short_sources.py::test_current_gates_deny_refs -q -p no:cacheprovider -p pytest_asyncio.plugin
```

Exit0; monitor1.71s; sampled RSS119392KiB.

`.local-test-evidence/2026-09-06/typed-short-sources/principal.json` SHA256 `b2fc3096c295bef4637058552b4ed2507e2ed26e1f79441b1c1c6993be4a0bfd`.

`.local-test-evidence/2026-09-06/typed-short-sources/principal.log` SHA256 `f4a62bceaa8fb3cff227351052b8c6e744b52305a2225194567bb44f0b4fe70a`.

```sh
/Users/denny/projects/simple_harness-primary-candidate/.local-test-evidence/2026-09-05/primary-candidate/venv/bin/python -m pytest tests/integration/test_typed_short_sources.py::test_exact_duplicate_domain_clock_and_reopen tests/integration/test_short_sources.py::test_exact_sources_one_clock_and_reopen -q -p no:cacheprovider -p pytest_asyncio.plugin
```

Exit0; monitor0.92s; sampled RSS119168KiB.

`.local-test-evidence/2026-09-06/typed-short-sources/shared.json` SHA256 `f5d862c7863c9a7753939292f07d9cc769da87a731d467e3fee772dd3b4e1585`.

`.local-test-evidence/2026-09-06/typed-short-sources/shared.log` SHA256 `2279ec65d7821a5fdf0d326061fe8c4bae70ad1962651b6925df69fa8b30a84e`.

## Fixed-source independent review / successor version

Dirac read-only scoped ACCEPT cd1ea1adfda5c2d4714a8a695eb8795f879e7f86; clean
and all10 evidence hashes independently checked. No new P0/P1. No rerun. He notes
256-binding/4096-collector limits do not establish whole-call cost bounds: existing
source checker still fetchall chunk evidence and prefetch remains existing mechanism.
Do not claim all scanning/latency resolved. Host outbound/full-group remains separate.

Local tags and all local version history checked: no0.6.13 usage. This metadata-only
successor commit sets dynamic package version0.6.13 and changelog. Fixed0612 unchanged.
Next two independent offline builds and owninstalled public consumers must identify
this exact successor source; no source-overlay Host claims.
