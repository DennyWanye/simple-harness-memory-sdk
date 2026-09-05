# Exact duplicate USER sources after memory-only forget — P1 contract proposal

2026-09-05. Design challenge requested; read-only investigation, no SDK implementation.
Isolated `feat/human-memory-duplicate-source-forget`, base exact
`f92fac121d2d9ce195b5715d272023e5aec920e3`. OA1 checkpoint da80e0a stays paused in its separate tree.
No 069/OA1 source mixing, version allocation, wheel build, pin, main merge or native activity.

## Verified counterexample and original contract

Original HM-AC-1 requires forgotten content to leave ordinary surfaces and not resurrect on rebuild;
S2 Task3 supplies explicit evidence/memory/entity/subject scopes and explicit audited revoke. The
original plan does NOT already specify a permanent all-text ban or a post-forget reassertion algorithm.
This proposal narrows a necessary duplicate-source closure; it must not guess user semantics.

Copied the actual closed native `human_memory_v7.db` and `state.db`, including existing sidecars,
from main's primary-ui-j475lsei userdata. Input SHA/mtime recorded and checked unchanged. SQLite
opens only the copies; original native stores are never opened by this investigation. The screenshot
text primary-ui-avqul005/06-after-forget-old-value.txt indeed shows old USER/assistant content and
an answer with the forgotten old preference. This is read evidence, not a new native run.

- Old USER evidence81c72f3d-58e6-54de-b279-dec752a9fab5 and successful USER
  bd3ee9fd-f500-5245-bfac-6517f5dac2c0 have exactly the same entire `/text` string.
- Their S1 payload also contains different `delivery_key`; source_hash, sanitized_hash AND existing
  item.content_hash therefore differ:8d35e2aa... vs e3bd50a8.... Envelopes/source_refs also differ.
  These existing hashes cannot be used as content equivalence keys or changed to force equality.
- Forgotten memory cognitive-memory-1c74ee03ee7d01a7ce6f1df91cfee66fb23483d7622625cf9dfd649fccc4b4d0
  has revision1 span to successful bd3e USER; revision2 span to c37f6a3f-fbcb-5600-ae61-acce86b1647a
  (correction). Both revisions, not only current lemon-water evidence, are relevant support seeds.
- Existing MEMORY directive decision hash02094169... is real. The old unmaterialized USER is not
  joined to that memory by evidence_id; its associated terminal/assistant can remain ordinarily visible.
- Host evidence occurred_at and sanitization receipt admitted_at are0.0. Host committed_at values
  exist, and snapshot-local rowids19/24 distinguish these rows, but neither has yet been established
  as the public, immutable source-order authority at the original forget action. Rowid alone is not
  a portable signed source sequence, particularly across restore/VACUUM. Do not silently promote it.

## Minimal semantic rule

A memory-only forget closes current ordinary use of its actual canonical USER support across every
revision, and exact duplicates of those USER sources that are proved to precede the same forget
boundary. Assistant/tool/terminal dependents inherit refusal ONLY through real source/terminal/input/
short lineage; no similarity test of assistant text and no hiding all failed Runs.

Identity profile `user-message-text-exact/v1`:
- Require a trusted Host-origin USER_MESSAGE S1 envelope + accepted receipt, subject ownership,
  exact admission/envelope/source/sanitized bindings and a declared compatible payload schema.
- Select ONLY the entire schema-declared `/text` string; no recursive text scan, query parsing,
  substring, trimming, casefold, Unicode normalization, stemming, embeddings or LLM inference.
- SDK independently computes E=SHA256(C({domain:"memory.history.user-source-equivalence.v1",
  payload:{profile:"user-message-text-exact/v1",subject,source_kind:"user_message",text}})). C is
  existing sorted compact UTF8 JSON, without Unicode normalization. Original S1 hashes unchanged.
- Ignore delivery_key ONLY for this new equality key, never for actual source identity/authorization.
  Different subject/role/profile/text bytes are not equivalent. A key supplied by a client is never
  proof; SDK derives it from the verified typed source. Same visible sanitized text is the exact
  comparison domain; no claim of semantic identity or equality of removed confidential material.
- Eligibility/disclosure/purpose/expiry/current suppression gates continue independently. Equality
  is an additional refusal edge, never a grant or a reason to reveal an otherwise suppressed source.

## Public integration and trusted boundary

Extend the existing trusted Host S1 admission integration with a READ-ONLY source-origin/cut witness
port backed by the existing authoritative Host evidence/action stores. It supplies source facts and
ordering, NOT a second suppression/disclosure permission authority. If no existing trustworthy order
exists, Host must create a minimal durable source/action sequence in its own store; SDK must not
read Host SQL or accept a caller-made numeric cutoff. A new sequence cannot retroactively prove an
unknown historical order; explicit legacy limitations below still apply.

Proposed public fact carriers (names provisional until challenge):
- `HistorySourceOriginRef`: immutable reference to an already durable Host source admission.
- Resolved origin: exact envelope+receipt binding, subject, producer/store identity and epoch,
  append sequence, source_kind/profile, proof hash. SDK validates canonical bindings before deriving E.
- `HistorySourceCutRef`: exact durable forget action/request identity plus target subject and store
  epoch. Resolved cut is fixed before dispatch to SDK, covers a stable source sequence, and binds the
  actual authenticated forget action. Its resolver cannot mint action permission from source text.
- `HistorySuppressionBindingReceipt`: actual SDK directive_id/decision_hash, immutable source-cut
  receipt hash, sorted exact USER seed keys and all-revision support binding hashes, binding hash.

Host creates/persists source admission order when S1 is originally admitted, not when async Memory
analysis finally consumes it. At forget, Host atomically persists the authenticated action and its
source cut before invoking SDK. SDK resolves and validates that exact cut, derives seed keys from its
OWN canonical support lineage, and atomically commits the original suppression decision and the new
binding. Extend `MemoryManager.suppress(..., history_cut_ref=...)` without changing existing decision
hash/fields; expose a separate public binding receipt read for auditing and outbox exact replay.
Same request/ACK replay must return identical cut/key binding, never recompute a current maximum.
Conflicting replay must reject. New additive persistence and public API require a successor candidate;
no alteration of frozen069 bytes or old decision/receipt hashes.

History batch checks accept/resolvably reference origin proofs alongside actual HistoryEvidenceBinding.
Resolve external Host facts outside the Memory snapshot/transaction; validate the complete bindings
against the frozen cut and current Memory suppression within one SDK snapshot. Already admitted SDK
sources can use persisted verified origin metadata. Pending first USER evidence can use the same
trusted Host admission proof without a fabricated Run, fake ingestion, or a fake complete short group.

At check time, SDK computes the candidate's exact key and looks up applicable active suppression
bindings. If source store/epoch matches and source admission sequence <= the fixed cut, suppress it.
Late ingestion of an OLD source keeps its original Host sequence, so it cannot impersonate a new
statement. Do not enumerate arbitrary historical text or implement a Host copy of private SDK SQL.
Matching keys with missing/unverifiable origin/cut produce a precise history_source_cut_unverifiable
refusal, not an allow. Nonmatching unrelated ordinary history must remain readable. Existing256/4096
history bounds stay intact; unsupported profile/store or exceeded work stays explicit, not truncated.

## Reassertion after forget

A genuinely NEW authenticated USER source admitted strictly AFTER the frozen cut can be evaluated
normally and proposed as new memory if its own provenance/disclosure/action gates pass. Repeating
exact words is not an automatic revoke of the old directive. It does not restore old source IDs,
old memories/revisions, receipts, assistant history or old recall authorization. A copied/restamped old
source is not a new source; actual original admission identity/sequence must be retained on replay.
A question about the old preference is not inferred to be a reaffirmation. Only explicit audited
revoke can restore old suppressed targets. New USER content depending on a forgotten old source
still inherits its real dependency refusal; a fresh independent assertion needs no fake old lineage.

## Legacy069 directive boundary — concrete unresolved proof requirement

Current original directive has no history-cut receipt. Do NOT use requested_at/effective_at,
S1 admitted_at0, Memory ingestion time, current MAX(rowid), or the time of this fix as a fabricated
original source cutoff. Main is preparing the actual ledger summary to determine whether a durable
Host action fact can bind the original ordering. The two observed rowids are investigative facts,
not yet reusable public cut authority.

A public, audited backfill may bind an existing decision to an independently verifiable original
cut, with a NEW binding receipt recording its provenance; old receipts/jobs remain exact. If the
original boundary cannot be proven, legacy matching-source checks must report boundary_unverifiable
rather than silently allow or claim full repair. Any proposal to adopt a NEW broader cutoff must be
explicit about changed historical coverage/reassertion impact; it is not ordinary ACK replay and
must not be smuggled in as a factual repair. An exact provable before-forget relation may be used
only for those sources it actually covers, with remaining coverage gaps explicit. No global hiding
of all ordinary history or permanent content ban to conceal this missing proof.

## Decisive oracle before implementation (7 required groups)

1. Real old-style USER A → applied no_mutation/no cognitive write; same exact-text USER B with new
   delivery identity → actual CREATE; genuine correction C → REVISE; MEMORY-only forget: A/B/C and
   their actual dependent assistant/terminal sources deny ordinary history/nextProvider input.
   Independent unrelated USER/assistant control remains allowed. No fake metadata or deleted Run.
2. Existing source/sanitized/item hashes A != B, new exact key A == B independently computed BEFORE
   product implementation. Changed whitespace/case/Unicode byte sequence, other actor/role/profile
   do not match. Full message exactness only, not substring preference extraction.
3. Original Host source A before cut but Memory ingested after cut still denies; new independently
   authenticated post-cut USER with exact same text may be evaluated normally, oldrefs still deny.
4. Fresh first USER not yet ingested by async analysis remains verifiable through trusted Host S1
   origin proof. Missing proof blocks only affected equivalence checks, not all unrelated history.
5. Real crash before/after atomic SDK suppression binding commit, ACK loss, reopen and same request
   replay keep original cut/seed hashes; future sources cannot enter replay's historical scope.
6. Forged key/source/cut, wrong subject/store epoch, altered origin seq, mismatched receipt/pointer,
   unproved legacy cutoff fail closed. Revoke restores only through existing explicit authorization;
   reassertion never silently revokes. No trusting caller timestamps or provider-selected seeds.
7. Actual old native COPY public history consumer shows the counterexample before fix and expected
   bound refusal after fix, if original-cut proof is available; otherwise report exact legacy blocker,
   not PASS. Verify original source files' bytes unchanged. Source/public consumer proof remains
   separate from final main native screenshot and nextProvider evidence.
