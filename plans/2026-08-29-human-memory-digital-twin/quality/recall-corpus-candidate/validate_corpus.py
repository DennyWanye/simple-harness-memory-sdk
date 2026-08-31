#!/usr/bin/env python3
"""Validate structure, coverage, labels, counts, and hashes for the draft corpus."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "recall-candidates.jsonl"
MANIFEST = ROOT / "manifest.json"
LABEL_SOURCE = "AI_DRAFT_UNREVIEWED"
QUALITY_GATE = "NOT_RUN/BLOCKED"

REQUIRED_FIELDS = {
    "corpus_schema_version", "scenario_id", "family", "query",
    "structured_context", "memory_fixtures", "memory_refs",
    "expected_required_types", "expected_selected_refs",
    "expected_confirmation_candidate_refs", "expected_outcome",
    "expected_privacy_outcome", "hard_trigger", "design_reason",
    "label_source", "quality_gate",
}
REQUIRED_FAMILIES = {
    "no_recall_chitchat", "semantic_active", "episode_event", "procedure_active",
    "prospective_pending", "short_horizon_recent", "task_scope_continue",
    "cross_type_personalized_plan", "contested_confirmation", "suppression_deny",
    "privacy_recipient_deny", "privacy_purpose_deny", "expired_validity",
    "active_revision", "procedure_status_deny", "prospective_terminal",
    "budget_minimal", "cross_task_semantic", "cross_task_procedure",
    "raw_evidence_quote", "working_context_only", "entity_affinity",
    "temporal_episode", "hard_trigger_composite",
}
REQUIRED_SOURCE_TYPES = {
    "episode", "semantic", "procedure", "prospective", "short_horizon",
    "task_scope", "raw_evidence",
}
OUTCOMES = {"RECALL", "NO_RECALL", "NEEDS_USER_CONFIRMATION", "REJECTED"}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calculate_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = Counter(t for row in rows for t in row["expected_required_types"])
    return {
        "by_family": dict(sorted(Counter(row["family"] for row in rows).items())),
        "by_outcome": dict(sorted(Counter(row["expected_outcome"] for row in rows).items())),
        "by_required_type": dict(sorted(required.items())),
        "by_privacy_decision": dict(sorted(Counter(row["expected_privacy_outcome"]["decision"] for row in rows).items())),
        "hard_trigger": dict(sorted(Counter(str(row["hard_trigger"]).lower() for row in rows).items())),
    }


def validate_row(row: dict[str, Any], line_number: int, seen: set[str]) -> None:
    if set(row) != REQUIRED_FIELDS:
        fail(f"line {line_number}: fields differ: {sorted(set(row) ^ REQUIRED_FIELDS)}")
    sid = row["scenario_id"]
    if not isinstance(sid, str) or not sid or sid in seen:
        fail(f"line {line_number}: scenario_id is missing or duplicated")
    seen.add(sid)
    if row["label_source"] != LABEL_SOURCE or row["quality_gate"] != QUALITY_GATE:
        fail(f"line {line_number}: review labels differ")
    if row["expected_outcome"] not in OUTCOMES:
        fail(f"line {line_number}: unknown expected outcome")
    if not isinstance(row["hard_trigger"], bool):
        fail(f"line {line_number}: hard_trigger is not boolean")
    if not isinstance(row["query"], str) or not row["query"].strip():
        fail(f"line {line_number}: query is empty")
    if not isinstance(row["design_reason"], str) or not row["design_reason"].strip():
        fail(f"line {line_number}: design reason is empty")
    ctx = row["structured_context"]
    required_context = {
        "identity", "subject", "run_id", "current_task_scope_id", "task_goal",
        "task_phase", "recipient", "purpose", "environment", "entities",
        "event_constraints", "time_constraints", "budget",
    }
    if not isinstance(ctx, dict) or set(ctx) != required_context:
        fail(f"line {line_number}: structured context differs")
    fixtures = row["memory_fixtures"]
    if not isinstance(fixtures, list) or not fixtures:
        fail(f"line {line_number}: fixtures must be non-empty")
    refs = [item.get("ref") for item in fixtures if isinstance(item, dict)]
    if len(refs) != len(fixtures) or len(set(refs)) != len(refs):
        fail(f"line {line_number}: fixture refs are invalid")
    if refs != row["memory_refs"]:
        fail(f"line {line_number}: memory_refs differ from fixtures")
    selected = row["expected_selected_refs"]
    confirmation = row["expected_confirmation_candidate_refs"]
    if not set(selected).issubset(refs) or not set(confirmation).issubset(refs):
        fail(f"line {line_number}: expected refs are not fixture refs")
    if row["expected_outcome"] == "RECALL" and not selected:
        fail(f"line {line_number}: RECALL must select at least one ref")
    if row["expected_outcome"] != "RECALL" and selected:
        fail(f"line {line_number}: non-RECALL cannot have selected refs")
    if row["expected_outcome"] == "NEEDS_USER_CONFIRMATION" and len(confirmation) < 2:
        fail(f"line {line_number}: confirmation requires at least two candidates")
    if row["expected_outcome"] != "NEEDS_USER_CONFIRMATION" and confirmation:
        fail(f"line {line_number}: confirmation candidates only belong to confirmation outcome")
    privacy = row["expected_privacy_outcome"]
    if not isinstance(privacy, dict) or set(privacy) != {"decision", "reason_code"}:
        fail(f"line {line_number}: privacy outcome differs")
    if privacy["decision"] not in {"ALLOW", "DENY"}:
        fail(f"line {line_number}: privacy decision differs")


def main() -> int:
    if not CORPUS.is_file() or not MANIFEST.is_file():
        fail("corpus or manifest is missing; run generate_corpus.py first")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(CORPUS.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        if not isinstance(row, dict):
            fail(f"line {line_number}: JSON value is not an object")
        validate_row(row, line_number, seen)
        rows.append(row)
    if len(rows) < 200:
        fail(f"candidate count {len(rows)} is below 200")
    families = {row["family"] for row in rows}
    if families != REQUIRED_FAMILIES:
        fail(f"family coverage differs: {sorted(families ^ REQUIRED_FAMILIES)}")
    source_types = {item["source_kind"] for row in rows for item in row["memory_fixtures"]}
    if not REQUIRED_SOURCE_TYPES.issubset(source_types):
        fail(f"source type coverage missing: {sorted(REQUIRED_SOURCE_TYPES - source_types)}")
    if not any(row["hard_trigger"] for row in rows) or not any(not row["hard_trigger"] for row in rows):
        fail("hard-trigger polarity coverage is incomplete")
    if not any(row["expected_privacy_outcome"]["decision"] == "DENY" for row in rows):
        fail("privacy denial coverage is missing")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["label_source"] != LABEL_SOURCE or manifest["quality_gate"] != QUALITY_GATE:
        fail("manifest review labels differ")
    if manifest["count"] != len(rows):
        fail("manifest count differs")
    if manifest["sha256"] != sha256(CORPUS):
        fail("manifest corpus hash differs")
    if manifest["stats"] != calculate_stats(rows):
        fail("manifest statistics differ")
    if manifest["generator_sha256"] != sha256(ROOT / manifest["deterministic_generator"]):
        fail("manifest generator hash differs")
    for name, expected in manifest.get("companion_sha256", {}).items():
        if sha256(ROOT / name) != expected:
            fail(f"companion hash differs: {name}")
    print(json.dumps({
        "status": "VALID_AI_DRAFT_ONLY",
        "count": len(rows),
        "sha256": sha256(CORPUS),
        "label_source": LABEL_SOURCE,
        "quality_gate": QUALITY_GATE,
        "stats": calculate_stats(rows),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
