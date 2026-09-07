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

## Public integration and trusted boundary — minimal read-only Host fact seam

Implementation status, exact entry coverage and current gates: [ENFORCEMENT.md](ENFORCEMENT.md).

The trusted Host S1/action stores retain origin order and first-action cut. SDK derives exact keys
and enforces current suppression; Host does NOT provide an equality key, choose Memory support
seeds, or grant disclosure permission. No new Memory table/implicit schema migration is needed.
This replaces the initial875554e suggestion of an additional SDK binding ledger: the actual Host
first-action journal already owns the cutoff fact, while the existing SDK directive owns suppression.
The new provenance adapter is not a second permission authority.

Fixed public interface for Host implementation:
```python
class HistorySourceAuthorityPort(Protocol):
    async def resolve_history_source(
        self, *, principal: MemoryPrincipal,
        envelope: SanitizedEvidenceEnvelope, receipt: SanitizedEvidenceReceipt,
    ) -> HistorySourceOriginReceipt | None: ...

    async def resolve_history_forget_cut(
        self, *, principal: MemoryPrincipal, decision: SuppressionDecision,
    ) -> HistoryForgetCutReceipt | None: ...

# Implemented in successor source56c6bf7+, absent from protocol-only8bd93c9/frozen069:
# optional keyword, default None; no change to suppress request/decision hashes
manager = await build_human_memory_v7(..., history_source_authority=host_source_authority)
```

Immutable DTOs, canonical to_json/from_json and new domain hashes:
- `HistorySourceNamespace(store_epoch: str, subject: str, source_stream: str)`.
  All three fields define one comparable sequence namespace. store_epoch must come from persistent
  Host store identity/restore lineage, never a process-random UUID. subject is exact SDK actor.
  For this Host, store_epoch is the exact human_memory_init_receipts.receipt_sha256, after
  recomputing receipt/marker and verifying subject/actual primary/format_epoch/first created_at.
  source_stream is exactly `primary:<actual_primary_conversation_id>:foreground_turns`.
  A same-history copy/restore preserves identity; fresh initialization changes it. Never compare
  queue sequences across different namespace fields.
- `HistorySourceOriginReceipt(namespace: HistorySourceNamespace, source_sequence: int,
  evidence_id: str, envelope_hash: str, admission_receipt_id: str,
  admission_receipt_hash: str, proof_kind: Literal["atomic", "legacy_before_only"],
  profile: str="user-message-text-exact/v1", schema_version: int=1)`.
  Positive source sequence. Source kind/text/profile are independently checked against actual S1;
  no key/text supplied by this receipt can replace envelope/receipt validation. `origin_hash` computed.
  admission_receipt_id/hash identify the actual Host SanitizedEvidenceReceipt; Memory ingestion
  is not a prerequisite. proof_kind is REQUIRED, strict closed strings, never a boolean/default.
- `HistoryForgetCutReceipt(namespace: HistorySourceNamespace, through_sequence: int,
  request_id: str, scope_kind: SuppressionScopeKind, scope_ref: str,
  action_ref: str, action_hash: str, schema_version: int=1)`.
  Nonnegative cut, actual MEMORY request/target/subject for this slice. `cut_hash` computed. The
  source namespace and scope bind the authenticated original forget action. No decision_hash input:
  Host commits action+cut before SDK commits decision, so requiring the future decision hash would
  be circular. SDK itself combines actual directive_id/decision_hash and cut_hash when checking.
  action_ref is original action S1 evidence_id; action_hash is that envelope's envelope_hash.
  Persist the v2 action's raw namespace/cut/request/scope facts first, then construct this receipt
  from its actual S1 identity. Do not embed its own cut_hash/action_hash into the action payload.

Wire contract: namespace to_json has exactly its three fields; origin/cut to_json have exactly
the listed fields including schema_version/profile, excluding computed origin_hash/cut_hash.
from_json rejects missing/unknown keys and unsupported schema; no wire defaults. Integers are
strict (not bool/float), source_sequence in [1, 2^63-1], through_sequence in [0, 2^63-1].
Digests are exactly 64 lowercase hex; cut scope is only SuppressionScopeKind.MEMORY (wire `memory`).
All DTOs are frozen/slots and return fresh nested JSON. These are trusted-port facts, not grants.

Canonical algorithm: SHA256(UTF8(C({"domain": DOMAIN, "payload": dto.to_json()}))), where C is
existing Harness canonical_json: sorted keys, compact separators, ensure_ascii=False, no Unicode
normalization and no NUL separator. Origin DOMAIN=`memory.history.source-origin.v1`,
cut DOMAIN=`memory.history.forget-cut.v1`. Existing S1/action/suppression hashes never change.
Independent literal vectors committed before carriers in491b813:
`tests/unit/test_history_source_contract.py` gives all exact payload fields; origin atomic
45db040a872144e428be23e6af1d94f98931c5a6c3bc513796467dcee0c17be1,
same origin legacy28b70510a95555f3ff8fa1dd25232edb4f5f7603fbeb8f45c3e8aad008f198e1,
cut85ec7b7718cb9669476730b8de056afd957b18657dd6d8c8315eb59cb62d36ff.

### Corrected source order proof (Dirac actual Host inspection)

Original service first committed S1, then separately enqueued. Old turn_hash did NOT include
enqueue_sequence; sequence authority comes from the immutable turn row and its unique constraint,
not a claim that the old turn hash signed it. The initial same-transaction assumption was false.
New Host first-time S1 insert + queue insert share BEGIN IMMEDIATE; only this case may set
turn_json schema_version2/source_admission=`atomic-evidence-and-turn/v1`, resolved as `atomic`.
Existing S1 later enqueued stays original v1/`legacy_before_only`; retries preserve format/hash.
Resolver validates exact pair, complete immutable turn JSON/hash, queue row sequence, namespace,
and original producer proof. DTO hashing cannot authenticate a fabricated marker.

For a proved exact-key match in the same namespace with an actual original cut:

| Proof | sequence <= cut | sequence > cut |
|---|---|---|
| atomic | current suppression denies | independently evaluate fresh source's ordinary gates |
| legacy_before_only | admission preceded enqueue, so current suppression denies | UNVERIFIABLE, cannot prove freshness |
| missing/invalid | UNVERIFIABLE | UNVERIFIABLE |

Old v1 action with no cut returns None and stays legacy UNVERIFIABLE for affected exact matches,
regardless of source proof. Do not create a cut from current MAX, timestamps, or source-before-only.
Later genuine v2 remember/revise/forget acceptance does not certify the old native v1 forget.

Host must persist origin sequence atomically with original S1 admission, before async ingest/analysis.
At authenticated forget, atomically persist its actual request_id/target/action facts and first cut
in the SAME Host source-store transaction. Then call existing public SDK suppress. SDK decision
receipt can be attached to the Host action on ACK; ACK loss does not create another action/cut.
`resolve_history_forget_cut` looks up that first durable action by the supplied REAL SDK decision;
verify request_id/subject/scope/target, then return the fixed cut. Same action after new USER admission
returns the same cut. A changed/forged/ref-less record must returnNone/error, never currentMAX.
The SDK never receives arbitrary SQL, Host rowids or client-requested timestamps as order proofs.

Three independent validations:
1. **Seed authority**: SDK reads its own canonical suppressed memory and USER support across ALL
   revisions and real upstream evidence. Host/candidate never chooses seed IDs or key values.
2. **Source origin**: Host resolver must find the exact durable source and complete original S1;
   verify principal/full primary conversation ownership, envelope hash and receipt ID/hash. SDK
   repeats canonical S1/type/subject/profile binding validation, then computes the full/text key.
3. **Action cut**: Host resolves actual durable authenticated action with namespace/cut/scope proof;
   SDK binds it to the real stored suppression decision, not to caller-selected time or content.

Prepare known seed/origin/cut references under a bounded Memory read, release transaction before
invoking Host resolvers, then validate against current Memory suppression in one final snapshot.
No Host callback while holding a Memory SQLite transaction. If new relevant active directives/support
appear after prefetch, their missing proof is a precise fail-closed finding, not permission to use
unverified aliases. A revoked directive is ignored only through existing current suppression rules.
Evidence/source cut proof hashes participate in the visibility observation's binding/policy identity;
Host final outbound recheck must revalidate actual bindings, not rely only on a cached SDK epoch.

At check time, same exact key + namespace + origin sequence <= cut extends current ordinary refusal.
Later Memory ingestion cannot change a Host source's original sequence. Only proved atomic postcut
fresh origin is handled by the ordinary independent source gates. Matching keys with missing/foreign/unverifiable
origin/cut produce history_source_cut_unverifiable; unrelated nonmatching history stays readable.
This includes first USER not yet ingested: validate its real Host S1 and origin without fake Run,
Memory record or complete short group. Existing256/4096 bounds stay; no silent truncation or scan
of arbitrary historical text. Only actual suppressed-memory USER seed payloads and actual candidate/
ancestor S1s are parsed under the declared profile.

All future public exports/source changes belong to a new independently reviewed candidate. Original
069 wheel, suppress decision hashes, accepted evidence/job IDs and source-only/short contracts remain.

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
   Separate delayed-ENQUEUE control: S1 commit before cut but legacy queue insertion after cut must
   be UNVERIFIABLE, never fresh allow. Existing S1 retried through the new atomic producer stays
   legacy; only first-time S1+queue same-TX insertion can prove atomic freshness. No timestamp proxy.
4. Fresh first USER not yet ingested by async analysis remains verifiable through trusted Host S1
   origin proof. Missing proof blocks only affected equivalence checks, not all unrelated history.
5. Real crash before/after Host action+cut commit and SDK suppression commit, ACK loss, reopen and
   same request replay keep original cut and actual decision hashes; future sources cannot enter replay's historical scope.
6. Forged key/source/cut, wrong subject/store epoch, altered origin seq, mismatched receipt/pointer,
   unproved legacy cutoff fail closed. Revoke restores only through existing explicit authorization;
   reassertion never silently revokes. No trusting caller timestamps or provider-selected seeds.
7. Actual old native COPY public history consumer shows the counterexample before fix and expected
   bound refusal after fix, if original-cut proof is available; otherwise report exact legacy blocker,
   not PASS. Verify original source files' bytes unchanged. Source/public consumer proof remains
   separate from final main native screenshot and nextProvider evidence.

## Evidence updates

Main supplied actual native ledger657060e28a75df9da37da843ac41040d6712813c3d986050dad34ad6dfa40693;
its bytes were independently rehashed here. Main's public Host integration counterexample has
controlFalse PASS / earlier-duplicateTrue FAIL (2.89s), using genuine earlier ingest but no
materialization. This is not asserted to replay the native no_mutation job. Three required controls
remain: old Host-precut delayed Memory ingest deny, fresh postcut same USER permitted while oldrefs
remain unavailable, and same-action replay after new USER keeps original cut/decision.
