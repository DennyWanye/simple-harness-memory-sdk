# Credential scan: proven public runtime identifiers

Date: 2026-09-05. Authorized successor of reviewed 0.6.11 source, isolated branch;
0.6.10/0.6.11 wheels and every original S1/receipt/archive stay unchanged.

## Counterexample and independent vectors (before implementation)

Actual stopped native Host21c55cf9, Memory0.6.10, Harness0.7.2, terminal
`ab9d6aca-6b5b-52ce-a6d6-63c5d0ec6a4b`. Public history validation throws
`evidence_credential_boundary_rejected`, wrapped as `primary_read_policy_unavailable`.
Same-run USER and factory/state controls pass. Analysis applied and new autumn
memory d438b6f... revision1 is durable; this is not an analysis retry failure.

The legacy pattern `\b(?:sk|key|tsk)-?[a-zA-Z0-9_-]{8,}` matches the `sk` in
ordinary skill identifiers. Actual maximal public lexemes and independent SHA256:

| Actual complete lexeme | SHA256 | Source |
|---|---|---|
| `skill_resource` | `db03bd1a4e9e79aa184f32f289ea67f6f9d570c12b0fdb9e7135639fa41410c7` | Harness0.7.2 `execution/context_authority.py`, kind literal |
| `product-skill-catalog` | `4c0a867deb52833ddddf0e02d9e526d22cfdec7e174f0c61f5b9e5935a29a107` | Host21c55cf9 `sdk_adapters/capability_catalog.py`, source literal |
| `product-skill-catalog-v1` | `e5d02bfbda6a76d25068071d409bd9fd99b0114a695ee04218bc21ff2d9b1c12` | Same Host module, source_revision literal |

The last two regex matches are suffixes `skill-catalog` and `skill-catalog-v1`,
with SHA256 `cf829f3d0f157859ac7d36aaf0d5b87789db2dbdb3eb835357858b72ebfea8fc`
and `6e0df673084d6122bb6344e3ef86f150317b70b2fefff3db29a47cdcf0b749db`.
Do not confuse the matched substring with the complete actual string.
No unidentified credential-like value was printed. Dirac verified the match hashes.

## Minimal semantics

Retain the existing credential regex, minimum lengths, case, delimiter-free
legacy rejection, forbidden-key rules, and other credential families. Do not
replace an optional delimiter with a mandatory one and silently accept formerly
rejected no-delimiter tokens.

Only the exact public vocabulary `skill_resource`, `skill-catalog`,
`skill-catalog-v1`, `product-skill-catalog`, `product-skill-catalog-v1` is exempt
from **this one prefix-pattern false positive**. The entire maximal lexeme
(Unicode word characters plus hyphen) must equal a listed value. This is no
`skill*` or `keyword*` prefix allowlist. Prepending/appending token characters,
including underscore/hyphen/Unicode letters, does not inherit the exemption.
No caller-defined allowlist, policy switch, DTO, persisted authority or second
ledger is introduced. All other scan patterns still inspect the full original
string: e.g. `Bearer skill_resource` is rejected. Forbidden structural keys
remain rejected even when their value is one of these public labels.

This intentionally bounded vocabulary repair does not claim to solve every
possible false positive for arbitrary ordinary words. Broad grammar migration
is outside this fix and may not be smuggled into the successor candidate.

## Decisive oracle

1. Public Manager cold S1 batch for these exact public labels is visible; ingest
   and reopen retain exact original S1/receipt hashes; actual saved native
   terminal and mixed dependencies pass using the actual Host runtime/history
   policy. A complete Host page with its actual settled reader must also pass
   before a product closure claim. Do not reissue CREATE or rewrite old receipts.
2. Synthetic sk-/sk_/key_/tsk_ and legacy delimiter-free sk/key/tsk tokens are
   rejected before DB access. Existing Bearer/AKIA/private-key and nested
   authorization/API-key/password/cookie/hidden-reasoning rejection persists.
3. Prefix/suffix/Unicode-boundary attacks and safe-label-plus-separated-token
   remain rejected. Nonlisted `skill_*`/`keyword_*` are not blanket permitted.
4. Tampered envelope/receipt and wrong subject remain rejected. Existing
   suppression keeps sources unavailable after forget, including reopen; a
   safe textual identifier never conveys identity/disclosure permission.
5. Capture red before code change, green after, then adjacent evidence/audit/
   history/typed pre-candidate zero-SQL controls. No full-suite or UI/Provider
   restart required for source closure. Installed/public/native-copy gates and
   independent review remain distinct from scanner-only tests.

Raw evidence is ignored under `.local-test-evidence/2026-09-05/credential-public-identifiers/`.
The original native red remains in the unchanged 0611 candidate tree's ignored
`native-policy-7ac1-readonly/` directory. Version/build happens once after review;
no push/tag/release/main change.

## Legacy evidence and oracle correction

Host21c55cf9 `task_scope/protocol.py` explicitly recognizes sk- and tsk_/key_
forms; Memory's original integration tests reject sk- plus nested secrets,
Bearer, and other credential families. No positive contract requiring arbitrary
no-delimiter strings to be accepted was found. Frozen0611 real public controls
reject all three synthetic sk/key/tsk no-delimiter forms. This leaf preserves
that observable rejection conservatively, without claiming those synthetic
strings are actual deployed credential formats. sk_ is also preserved explicitly.

Initial red: five intended public-label failures; 33 passing controls. Two
additional test-authoring errors were corrected before production edits: the
existing regex does not match `_skill_resource` (leading underscore defeats
its word boundary), so that is not an inherited-rejection oracle; malformed
envelope constructor rejects before API call, and belongs inside the rejection
assertion. Original red log retained. The legacy word-boundary limitation is
unchanged, not silently expanded into another scanner redesign.
