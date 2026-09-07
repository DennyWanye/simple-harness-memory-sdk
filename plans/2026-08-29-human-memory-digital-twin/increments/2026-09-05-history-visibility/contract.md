# Approved bounded history visibility repair — 2026-09-05

Execution base: main8675352 / Memory0.6.3. User authorized AC1/AC7 remember/forget closure,
new isolated source worktree; no version/build/wheel/pin/Host change. Original401/numerical
thresholds remain unchanged. Serial execution: real reproduction -> contract/tests red ->
source green -> independent review. SDK/library tests only; no provider/UI/full401 run.

Reproduction before implementation: real SQLite memory_id suppression denies Memory but
permits read_ingested_evidence and projection_evidence_ids for its original USER evidence.
Ignored baseline code/result/log: .local-test-evidence/2026-09-05/history-visibility/.

Contract/oracle fixed before implementation:

1. Reuse append-only suppression authority; extend ordinary evidence resolution through canonical
   upstream evidence links and reverse cognitive support spans across ALL revisions, including
   associated canonical entity IDs. No copied suppression directives, new authority or raw deletion.
   Memory forget therefore hides original USER sources and their evidenced descendants, not only
   previously recalled assistant text. Unrelated evidence stays readable. Revoke restores only
   what is otherwise allowed. Existing audit authority remains separate.
2. New public Manager.check_history_visibility(principal, disclosure_context, bindings) accepts a
   bounded batch of HistoryEvidenceBinding(envelope,receipt) and HistoryRecallBinding(result_id,
   result_hash,item_id,item_hash). Host proves actual dependencies, including transitive assistant/
   tool lineage; it may provide already verified S1 envelope+receipt before async SDK ingestion.
   Reuse validate_sanitized_evidence (strict root DTOs/canonical/subject/filter/receipt/credential
   checks), not a new admission authority. Missing SDK storage alone cannot deny first USER history.
   Known stored identity mismatch or unresolved referenced dependencies deny; fresh unlinked USER
   evidence can allow under current ordinary disclosure/classification. This is canonical lineage
   checking, not semantic entity extraction from arbitrary text.
3. UI supplies actual Host request DisclosureContext; no fabricated execution Run is created and
   current context is not forced to equal the historical source Run. Current subject/trust/audience/
   purpose and effective classifications still gate. Recall binding resolves owned durable result
   and exact item hashes; checks current cognitive head/state/time/type, short existence/expiry,
   evidence/entity suppression. Old result expiry is not current source permission, and old typed
   current-use Run/turn/receipt rules are unchanged. Unsupported carriers explicitly deny.
4. One read transaction + existing backend lock covers the entire batch, trusted now sampled once.
   Output immutable per-binding visible/reason, ordered request hashes, checked_at, earliest known
   validity deadline, authority_epoch (0 only before a principal authority head exists), policy hash
   including current classification configuration, and snapshot hash. No result payload, new grant,
   durable receipt or ALLOW replay cache. Recheck the same batch before output; epoch equality alone
   is insufficient for time/disclosure changes. Host controls dependency completeness and the
   check-to-outbound ordering; this API does not hold a lock across arbitrary future Provider use.
5. No schema migration. Existing public methods remain compatible. New DTOs export from Memory
   root; Harness exports/version remain unchanged. New source candidate will need independently
   allocated version/wheel and Host wiring later; this task does neither.

Decisive source tests (AC1/AC7): reverse-memory suppression -> original USER ordinary read/projection
and new history deny; cold un-ingested USER allow/no inserts; unrelated evidence allow; reverse
all-revisions/shared evidence; entity + direct evidence/subject suppression; canonical/receipt/owner
negative; actual UI request id; mixed-page one-snapshot suppression interleaving; changed epoch after
suppression and identical-input fresh recheck; cognitive correction/expiry and short source expiry;
referenced assistant -> suppressed USER propagation; reopen; immutable evidence rows/hashes preserved;
old typed recall/current-use regression remains unchanged. Assert product behavior, never synthesize
expected outcomes from implementation output. No claim of complete S6/Host/UI/program delivery.

Implementation clarifications fixed during bounded red/green review:

- `authority_epoch` is exactly the existing recall-authority observation, NOT a complete database
  or history version. In particular, S1 ingestion/conversation registration can add lineage or
  entity/classification facts without advancing it. `checked_at` is a clock sample, not a revision.
  `schema_version=1` versions the response contract; `snapshot_hash` binds this observation and
  is not a durable snapshot handle. Host MUST fresh-check the same complete ordered batch and
  actual request DisclosureContext at each output boundary; equality of any old epoch/time/hash
  never authorizes a skip. No SDK lock is held during subsequent arbitrary Host/Provider activity.
- Fresh S1 has no principal row; ingested-but-not-analyzed S1 may have the existing subject-only
  placeholder identity. Both use trusted Host admission with subject checking, without inserting
  or promoting a principal on reads. A materialized principal must match deployment/household/actor.
- Upstream evidence suppression and reverse support serve different directions: a memory supported
  by derived evidence also hides the original USER ancestors. Reverse traversal discovers owned
  memory/entity targets only; it does not treat unrelated descendant evidence IDs as requested
  evidence targets. All supported revisions remain relevant after correction and reopen.
- A stored subject/source_ref identity cannot be reintroduced under a new evidence_id. Known
  conversation registration classification is also an ordinary disclosure floor. Cold S1 does not
  prove a sanitized whole envelope safe for another recipient: evidence bindings currently permit
  only the authenticated subject's own audience, with current SDK classification policy.
- One batch accepts 1..256 bindings. Evidence dependency traversal memoizes by evidence ID +
  envelope hash + receipt hash for the same snapshot/context, limits depth to64 and total unique
  node+edge work to4096; reverse canonical traversals cap4096 nodes. Exceeding a bound fails closed,
  never truncates into ALLOW. These are new endpoint resource bounds, not modifications to any
  original401 cell, original numerical acceptance threshold, or typed recall budget.
- Without a current procedure applicability proof, a historical procedure item returns
  `history_source_stale`; old runtime fingerprints cannot prove a new execution environment.
  This endpoint observes historical source visibility, not typed recall selection or execution
  authorization. `authorize_recall_context_use` and old receipt exact-replay bindings remain intact.

Final resource clarification: each canonical traversal uses fetchmany128 and a cumulative4096-row
budget across both directions and revisions. Suppression matches are filtered in SQL by250 target
pairs and capped4096; no whole-subject directive materialization. These bounds do not promise an
entire batch SQL CPU/IO/byte ceiling. The shared-parent memo work bound remains per batch.
