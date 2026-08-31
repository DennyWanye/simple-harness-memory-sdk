# Human Memory Recall Candidate Corpus — AI Draft

This directory contains a deterministic candidate set for the later independent human review of Task 5 recall semantics.

## Status and evidence boundary

- `label_source`: `AI_DRAFT_UNREVIEWED`
- `quality_gate`: `NOT_RUN/BLOCKED`
- This is candidate material only. It is not human-labeled evidence.
- No real main-model recall evaluation was run while producing it.
- The corpus must not be used to claim semantic quality success until an independent human reviewer freezes the labels and the real evaluation is executed against that frozen hash.

## Files

- `recall-candidates.jsonl` — canonical, deterministic JSONL candidates.
- `manifest.json` — fixed corpus SHA-256, count, and stratification statistics.
- `generate_corpus.py` — deterministic generator; no randomness or external services.
- `validate_corpus.py` — offline structural, coverage, count, statistics, and hash validator.

Each candidate includes `scenario_id`, natural-language query, structured execution/disclosure context, memory fixtures and refs, required retrieval types, selected refs or expected non-recall outcome, privacy result, hard-trigger flag, and a concise design rationale.

The approved architecture treats Working Memory as a first-class cognitive system assembled in Context, not as a durable table. The four long-term cognitive stores are Episode, Semantic, Procedure, and Prospective. TaskScope is exercised as a separate durable task archive, not as a fifth cognitive-memory type. Short-Horizon is a disposable recent-conversation projection, while raw evidence remains the permanent audit source.

## Coverage

The 24 deterministic strata cover:

- no recall and Working-Memory-only requests;
- Episode, Semantic, Procedure, Prospective, TaskScope, Short-Horizon, and raw-evidence retrieval;
- cross-type selection and contested confirmation;
- suppression and privacy recipient/purpose denial;
- expired values, terminal/ineligible lifecycle states, and active revision replacement;
- minimal budget selection, cross-task recall, entity/time affinity, and hard triggers.

## Reproduce and validate

From this directory:

```bash
python3 generate_corpus.py
python3 validate_corpus.py
shasum -a 256 recall-candidates.jsonl
```

Generation is byte-deterministic for the checked-in generator and Python's standard JSON encoder. Re-running the generator replaces only the derived JSONL and manifest in this temporary directory.

## Human review handoff

The reviewer should inspect every stratum, correct ambiguous expectations, record reviewer identity and review evidence outside this draft, then freeze a new reviewed corpus hash. Until that separate step is complete, retain `AI_DRAFT_UNREVIEWED` and `NOT_RUN/BLOCKED` exactly.
