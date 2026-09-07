# 0.6.9 A oracle fixed before implementation

2026-09-05. Contract269326f independently ACCEPT by Dirac. This document freezes
input identities and decisive expectations; it does not mark A/B or W1-W5 complete.

- Exact old Memory0.6.0 wheel62a3f63c / source3fa56572718b2e922aff8abcbb53eb5d5be907e3:
  all60 package Python files match. The initially inspected1cae806 was two files earlier;
  corrected by comparing the wheel bytes, without changing either artifact.
- .063 source2f3d738 / wheel6b20ae5b:60files match; .067 sourcefa6badd / wheel7dd224c2:
  63files match. Each has a separate installed environment with exact Harness0.7.2.
- `scripts/schema_upgrade_old_fixture.py` uses the corresponding archived test Host
  authority factories and installed OLD SDK public repository operations. It creates
  nonempty cognitive/evidence/span/typed recall receipts, three active suppression
  scopes, two pending analysis jobs and pending outbox. SQL only supplies SDK fixture
  WAL controls and diagnostic snapshots, never product data/IDs/expected receipts.
- The old public control actually selects the created memory, exact-replays the same
  decision/result, then denies its MEMORY target and still reads unrelated USER evidence.
  Process death leaves committed cognitive data in WAL with main-only cognitive count0.
  Expected preserved data is the complete WAL-visible OLD-column snapshot, captured
  before any successor implementation. Preserve these rows and hashes exactly.
- Official .063 initializer genuinely upgrades a COPY of the nonempty .060 fixture
  using its pre-existing7.0→7.1 implementation. Its actual appended catalog matches
  the independently constructed ALTER recipe. Its rewritten legacy initialization
  receipt is an already-existing input, not authority for .069 to rewrite anything.
- Finite catalog hashes are fixed in `tests/fixtures/schema-upgrade-v1/catalog-pins.json`.
  Catalog encoding includes exact sqlite_master(type/name/table/SQL), table_xinfo,
  index_list and foreign_key_list; sorted compact UTF8 JSON. Official .060/.063/.067
  and actual prior ALTER agree with these recipes on SQLite3.50.4 (actual isolated Python3.12 runtime). Other physical variants must fail closed, not normalize into one.
- Independent Unicode receipt vector: stdlib only, before new product code;
  `receipt.json` freezes H(C({domain,payload})), new ID/receipt domains. Old hashes untouched.
  `committed_at` is canonical float; first successful receipt persists across ACK loss.

Raw evidence: `.local-test-evidence/2026-09-05/069-existing-data/`:
`old-wheel-identities.json`, `nonempty-060-r1`, `nonempty-063-r4`, `nonempty-067-r1`,
`official-alter-071.db`, `official-alter-071.log`, `catalog-recipes-observed.json`.
Earlier r1–r3 .063 logs are fixture-script API/URI corrections, not product failures.

Remaining required A oracle cases retain CONTRACT.md W1-W5 in full: complete jobs
progress/analysis receipts and short state coverage, backup WAL preservation, migration
pre/post-COMMIT death, missing/stale SHM, rejects unchanged, exact backup retry/conflict,
post-migration legitimate writes/reopen and new corruption rejection. B also remains
required; no threshold, lineage or selected-only availability claim is removed.
