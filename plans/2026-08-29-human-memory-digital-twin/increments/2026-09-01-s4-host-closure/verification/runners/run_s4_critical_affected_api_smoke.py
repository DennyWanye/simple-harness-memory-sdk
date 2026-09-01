#!/usr/bin/env python3
"""Draft one-shot critical + affected public API smoke for S4 Host closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from s4_runner_common import (
    canonical_bytes,
    expect_error,
    expect_ok,
    invoke,
    load_adapter,
    load_fixture,
    require_evidence_dir,
    require_ref_or_receipt,
    resolve_placeholders,
    sha256_bytes,
    write_result,
)


HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURE = HERE.parent / "fixtures" / "s4-host-closure-v1.json"


def _capture_context(case_id: str, result: dict[str, Any], context: dict[str, Any]) -> None:
    payload = result.get("payload", result)
    if not isinstance(payload, dict):
        return
    if case_id == "api-primary-open":
        context["primary_ref"] = payload.get("primary_ref") or payload.get("ref")
    elif case_id == "api-scope-create":
        context["scope_a_ref"] = payload.get("scope_ref") or payload.get("ref")
    elif case_id == "api-binding-propose":
        context["challenge_ref"] = payload.get("challenge_ref")
    elif case_id == "api-execution-running":
        context["sdk_run_id"] = payload.get("sdk_run_id")


def run(fixture: dict[str, Any], adapter: Any, adapter_identity: dict[str, str], artifact_dir: Path) -> dict[str, Any]:
    context: dict[str, Any] = {
        "subject": fixture["subject"],
        "wrong_principal": fixture["wrong_principal"],
        "scope_a": fixture["task_scopes"]["a"],
        "search_query": fixture["search"]["query"],
    }
    expect_ok(
        invoke(
            adapter,
            "host.reset_fresh",
            {
                "data_format": fixture["data_format"]["supported"],
                "scenario": "critical-affected-api-smoke",
            },
        ),
        "host.reset_fresh",
    )
    results = []
    for case in fixture["critical_affected_api"]:
        request = resolve_placeholders(case["request"], context)
        result = invoke(adapter, case["operation"], request)
        status = result.get("status")
        if isinstance(status, int) and status >= 500:
            raise AssertionError(f"{case['case_id']} returned {status}")
        if case["expect_ok"]:
            expect_ok(result, case["operation"])
            if case.get("requires_ref_or_receipt"):
                require_ref_or_receipt(result.get("payload", result), case["operation"])
            _capture_context(case["case_id"], result, context)
            required_context_key = {
                "api-primary-open": "primary_ref",
                "api-scope-create": "scope_a_ref",
            }.get(case["case_id"])
            if required_context_key and not context.get(required_context_key):
                raise AssertionError(f"{case['case_id']} did not expose its exact ref")
        else:
            expect_error(result, case["operation"], case["expected_code"])
        results.append({
            "case_id": case["case_id"],
            "operation": case["operation"],
            "ok": result.get("ok"),
            "status": result.get("status"),
            "code": result.get("code"),
            "response_sha256": sha256_bytes(canonical_bytes(result)),
        })

    required_operations = {
        "primary.open", "primary.append", "task_scope.create", "task_scope.search",
        "task_scope.open_exact", "task_scope.mutate", "binding.append", "queue.enqueue",
        "queue.control", "audit.refs", "recovery.manifest", "recovery.emergency_export",
        "legacy_session.create", "legacy_session.switch", "legacy_session.rename",
        "legacy_session.delete",
    }
    seen_operations = {item["operation"] for item in fixture["critical_affected_api"]}
    if not required_operations.issubset(seen_operations):
        raise AssertionError(f"critical/affected matrix missing: {sorted(required_operations - seen_operations)}")

    return {
        "schema_version": "1.0",
        "scenario": "HM-S4-TO-REGRESSION",
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": sha256_bytes(canonical_bytes(fixture)),
        "adapter": adapter_identity,
        "cases": results,
        "case_count": len(results),
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    if args.self_check:
        operation_count = len({item["operation"] for item in fixture["critical_affected_api"]})
        print(json.dumps({"fixture_id": fixture["fixture_id"], "fixture_sha256": sha256_bytes(canonical_bytes(fixture)), "operation_count": operation_count, "status": "FIXTURE_PASS"}, sort_keys=True))
        return 0
    if args.adapter is None or args.artifact_dir is None:
        parser.error("formal run requires --adapter and --artifact-dir")
    artifact_dir = require_evidence_dir(args.artifact_dir)
    adapter, identity = load_adapter(args.adapter, fixture, artifact_dir)
    result = run(fixture, adapter, identity, artifact_dir)
    path = write_result(artifact_dir, "s4-critical-affected-api-result.json", result)
    print(json.dumps({"result": str(path), "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
