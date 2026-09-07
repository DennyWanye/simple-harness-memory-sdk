# Standalone short exact history visibility — bounded approved repair

2026-09-05. User explicitly authorized this necessary AC1/AC7 remember/forget repair and
independent design agreement before minimal implementation. Base2877474 preserves the sealed
0.6.6 source9ec5943 / wheel381d8543. No version allocation, wheel build, old snapshot edit,
Host/native change, main/push/tag, provider or full401 run in this increment.

## Real pre-implementation counterexample

Source baseline2877474, real public Manager + SQLite, existing source-fixture public authority
constructors, deterministic development embedder explicitly opted in. Twelve registered causal
groups leave the newest ten in working context and yield two real standalone short hits.
After ENTITY(project-alpha) suppression, fresh short recall has zero hits, while public backend
resolve_suppression(candidate carrying only the old hit's chunk_ref as memory_id) still allows.
No exact standalone short binding is exported. This is insufficient caller lineage, not proof
that the canonical resolver ignored a supplied target. Raw reproduction/result/database/log:
`.local-test-evidence/2026-09-05/short-history-baseline/` (ignored). Earlier setup corrections
were wrong facade method/keyword and fewer than eleven groups; they are not product failures.

## Contract / oracle fixed before implementation

1. Add root frozen `HistoryShortHorizonBinding(audit_id: str, chunk_ref: str,
   content_hash: str)` to HistoryBinding. JSON kind `short_horizon`; IDs nonblank, bounded,
   no NUL; content hash lowercase64hex. Existing binding/request/snapshot domains and schema1
   unchanged: SHA256(canonical_json({domain,payload})). Existing carriers unchanged. Batch
   `MemoryManager.check_history_visibility(principal=..., disclosure_context=..., bindings=...)`
   still accepts1..256 mixed ordered bindings under one read transaction and one trusted now.
2. SDK reads owned immutable `short_horizon_audit`, verifies canonical JSON/raw SHA and row
   bindings, event_kind=recall, successful selected membership and owned linked recall_started
   attempt. Use existing opaque chunk hash SHA256(UTF8("memory-log/v1|" + chunk_ref)); do not
   change or recreate audit identity. Exactly one selected entry and exactly one eligible entry
   must bind that hash; eligible content_hash must equal caller's. Eligible alone, another audit,
   another principal, attempt/terminal/projection ID, wrong hash or unknown ID denies. Existing
   degraded vector recall with a valid selected lexical hit remains valid. Stored corruption
   raises existing MemoryCorruptionError, never emits ALLOW or a fabricated rejection receipt.
3. Resolve current owned chunk; verify actual text content SHA equals requested/stored hash,
   occurred_at <= trusted now < expires_at. Missing/cleaned/changed/expired source denies.
   Resolve canonical chunk-evidence-registration bindings to owned admitted evidence; empty,
   missing or mismatched lineage denies. No caller-supplied entity/evidence substitutes. Use
   existing suppression authority for chunk MEMORY plus each evidence and canonical entities,
   including existing reverse cognitive MEMORY support/all revisions from history repair.
   Purpose READ for USER_REVIEW, otherwise RECALL; purpose-scoped suppression/revoke preserved.
4. Actual current Host disclosure facts gate subject/trust/generation/audience/recipient/purpose.
   Current canonical short classification and nonempty authority refs are mandatory; apply
   configured global classification policy as an additional floor when present. A legitimate
   short-only deployment need not configure cognitive mutation policy: registered short item
   classification is already authoritative. No relaxed class floor or fabricated SDK Run. A new
   request ID need not equal old audit disclosure; it is current visibility, not old grant replay.
5. Same output: ordered binding_hash/visible/reason, checked_at, earliest visible source expiry,
   authority_epoch/policy_hash/snapshot_hash. Reasons: history_binding_mismatch (exact selection
   cannot be proven), history_source_stale (current source/lineage/time invalid), history_suppressed,
   history_disclosure_denied, history_visible; existing subject/error paths retained. No content
   or private source graph output, no new authority store/schema/grant. Host proves actual use,
   content bytes and complete causal dependencies; SDK proves selection and current eligibility.
   It is necessary current visibility for history/nextProvider, not sufficient proof of Host
   dependency completeness or an atomic lock over subsequent network sends. Check every outbound;
   epoch/time/policy/snapshot equality never authorizes cache reuse. Existing typed execution
   `authorize_recall_context_use` binding/replay restrictions remain unchanged.
6. Endpoint requires no SQL/private fields at Host. Source tests may use explicit internal fault
   fixtures solely to test corrupt/missing canonical rows. New public source export is pending
   independently allocated version; preserve every old snapshot JSON/wheel. No401/14attack/threshold
   or typed protocol/hash changes. No source-epoch claim beyond existing observation contract.

## Decisive tests (before code)

- Real standalone hit passes current exact check, including new Host request ID, no global
  cognitive policy; owned audit reopens. ENTITY/EVIDENCE/SUBJECT/chunk MEMORY and reverse cognitive
  MEMORY suppression deny; unrelated source control and revoke stay correct.
- Old binding after trusted clock reaches exact expiry denies; before expiry allows; cleaned
  source denies without consulting a fake typed result. Current changed disclosure denies.
- Unknown/wrong-owner/non-recall audit; eligible-but-not-selected chunk; mismatched hash or chunk;
  duplicate/malformed canonical audit membership; missing/incorrect source linkage all fail closed.
- Mixed cold S1/typed/standalone batch remains one snapshot/one clock; external suppression
  interleaving cannot produce half-old/half-new batch. Earliest deadline from visible sources only.
- Focused existing history, short recall, suppression, clock/rejection and root API regressions.
  These are source/library evidence, not installed new-wheel/Host/provider/UI acceptance.

Independent design challenge ACCEPT (Popper, before production edits). Concrete audit clarification:
this ledger has no status column or `success` string. Returnable recall success uses `event_kind=recall`
and degradation in {null,VECTOR_DEGRADED,NO_ACTIVE_GENERATION,STALE_ACTIVE_GENERATION}; rejected
`gate_outcome`, non-recall IDs, or any linked recall_terminal deny even if selected fields remain.
Require exact owned started audit query/disclosure linkage. Test both legitimate degraded lexical
success and failed/incomplete audit negatives. Host still proves that it actually received/used the
hit; SDK cannot infer wire delivery from a committed result. Short canonical classification/refs
remain mandatory without global policy; mixed evidence/typed bindings keep their original floors.
