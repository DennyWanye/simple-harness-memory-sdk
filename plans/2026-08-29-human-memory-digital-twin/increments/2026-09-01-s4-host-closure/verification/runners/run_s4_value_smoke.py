#!/usr/bin/env python3
"""Draft S4 value smoke orchestrator over a pinned public-only Host adapter.

`--self-check` validates only this frozen fixture contract. A formal run needs
an adapter and writes raw output exclusively below `.local-test-evidence`.
"""

from __future__ import annotations

import argparse
import json
import math
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
    sha256_bytes,
    write_result,
)


HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURE = HERE.parent / "fixtures" / "s4-host-closure-v1.json"
VIEW_KINDS = ("README", "PLAN", "STATUS", "DECISIONS", "RESUME", "EVIDENCE")


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("payload", result)
    if not isinstance(value, dict):
        raise AssertionError("adapter payload must be a JSON object")
    return value


def _content_bytes(value: Any) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return canonical_bytes(value)


def _assert_view(kind: str, result: dict[str, Any], limits: dict[str, int]) -> dict[str, Any]:
    view = _payload(expect_ok(result, f"view.read:{kind}"))
    content = _content_bytes(view.get("content", ""))
    if kind == "README" and len(content) > limits["readme_bytes"]:
        raise AssertionError("README exceeded 16 KiB")
    if kind == "STATUS" and len(content) > limits["status_bytes"]:
        raise AssertionError("STATUS exceeded 12 KiB")
    pages = view.get("pages", [])
    if not isinstance(pages, list):
        raise AssertionError(f"{kind} pages must be a list")
    seen_ids: set[str] = set()
    for page in pages:
        page_bytes = _content_bytes(page.get("content", ""))
        if len(page_bytes) > limits["page_bytes"]:
            raise AssertionError(f"{kind} page exceeded 32 KiB")
        page_id = page.get("page_id") or page.get("ref")
        if not page_id or page_id in seen_ids:
            raise AssertionError(f"{kind} page IDs must be present and unique")
        seen_ids.add(str(page_id))
        if page.get("content_sha256") != sha256_bytes(page_bytes):
            raise AssertionError(f"{kind} page hash mismatch")
    return {"kind": kind, "content_bytes": len(content), "pages": pages, "hash": sha256_bytes(content)}


def run(fixture: dict[str, Any], adapter: Any, adapter_identity: dict[str, str], artifact_dir: Path) -> dict[str, Any]:
    subject = fixture["subject"]
    wrong = fixture["wrong_principal"]
    scope_a = fixture["task_scopes"]["a"]
    scope_b = fixture["task_scopes"]["b"]
    limits = fixture["limits"]

    reset = expect_ok(invoke(adapter, "host.reset_fresh", {"data_format": fixture["data_format"]["supported"]}), "host.reset_fresh")
    create_a = _payload(expect_ok(invoke(adapter, "task_scope.create", {"subject": subject, "scope": scope_a}), "task_scope.create:A"))
    create_b = _payload(expect_ok(invoke(adapter, "task_scope.create", {"subject": subject, "scope": scope_b}), "task_scope.create:B"))
    scope_a_ref = create_a.get("scope_ref") or create_a.get("ref")
    scope_b_ref = create_b.get("scope_ref") or create_b.get("ref")
    if not scope_a_ref or not scope_b_ref or scope_a_ref == scope_b_ref:
        raise AssertionError("A/B must have distinct exact scope refs")

    expect_ok(
        invoke(adapter, "task_scope.append_deterministic_events", {"subject": subject, "scope_ref": scope_a_ref, "count": 100000, "canary": scope_a["canary"]}),
        "append_events:A",
    )
    expect_ok(
        invoke(adapter, "task_scope.append_deterministic_events", {"subject": subject, "scope_ref": scope_b_ref, "count": scope_b["event_count"], "canary": scope_b["canary"]}),
        "append_events:B",
    )
    expect_ok(invoke(adapter, "task_scope.save_checkpoint", {"subject": subject, "scope_ref": scope_a_ref, "checkpoint": scope_a["checkpoint"]}), "save_checkpoint:A")
    for turn in fixture["queue"]["turns"]:
        expect_ok(invoke(adapter, "queue.enqueue", {"subject": subject, "scope_ref": scope_a_ref, **turn}), f"queue.enqueue:{turn['delivery_key']}")

    authority_before = _payload(expect_ok(invoke(adapter, "authority.snapshot", {"subject": subject}), "authority.snapshot:before"))
    manifest_before = _payload(expect_ok(invoke(adapter, "recovery.manifest", {"subject": subject}), "recovery.manifest:before"))
    expect_ok(invoke(adapter, "derived.drop_rebuildable", {"subject": subject, "scope_ref": scope_a_ref}), "derived.drop_rebuildable")
    expect_ok(invoke(adapter, "derived.rebuild", {"subject": subject, "scope_ref": scope_a_ref}), "derived.rebuild")
    restart = expect_ok(invoke(adapter, "host.cold_restart", {}), "host.cold_restart")

    search = _payload(expect_ok(invoke(adapter, "task_scope.search", {"subject": subject, **fixture["search"]}), "task_scope.search"))
    candidates = search.get("candidates", [])
    candidate_refs = [item.get("scope_ref") or item.get("ref") for item in candidates]
    if scope_a_ref not in candidate_refs or len(candidates) > fixture["search"]["max_candidates"]:
        raise AssertionError("bounded search did not return exact A candidate")
    wrong_search = invoke(adapter, "task_scope.search", {"subject": wrong, **fixture["search"]})
    if wrong_search.get("ok") is False:
        expect_error(wrong_search, "wrong-principal search", fixture["stable_errors"]["wrong_principal"])
    elif scope_a_ref in [item.get("scope_ref") or item.get("ref") for item in _payload(wrong_search).get("candidates", [])]:
        raise AssertionError("wrong principal received A candidate")
    authority_after_search = _payload(expect_ok(invoke(adapter, "authority.snapshot", {"subject": subject}), "authority.snapshot:after-search"))
    if canonical_bytes(authority_before) != canonical_bytes(authority_after_search):
        raise AssertionError("candidate search changed cursor, binding, or tool authority")

    opened = _payload(expect_ok(invoke(adapter, "task_scope.open_exact", {"subject": subject, "scope_ref": scope_a_ref, "live_probe": fixture["live_probe"]}), "task_scope.open_exact:A"))
    if (opened.get("scope_ref") or opened.get("ref")) != scope_a_ref:
        raise AssertionError("exact open returned the wrong TaskScope")
    resume = opened.get("resume_package")
    resume_bytes = canonical_bytes(resume)
    if len(resume_bytes) > limits["resume_package_bytes"]:
        raise AssertionError("ResumePackage exceeded 24 KiB")
    if scope_b["canary"].encode("utf-8") in resume_bytes or scope_b["poison_canary"].encode("utf-8") in resume_bytes:
        raise AssertionError("B candidate/poison canary leaked into A ResumePackage")
    drift = opened.get("drift_report", {})
    if not drift.get("drifted") or not drift.get("changed_fields"):
        raise AssertionError("checkpoint drift was not explicitly reported")

    views = []
    evidence_event_indices: set[int] = set()
    for kind in VIEW_KINDS:
        checked = _assert_view(kind, invoke(adapter, "view.read", {"subject": subject, "scope_ref": scope_a_ref, "kind": kind}), limits)
        views.append({key: value for key, value in checked.items() if key != "pages"})
        if kind == "EVIDENCE":
            for page in checked["pages"]:
                events = page.get("events", [])
                if len(events) > limits["evidence_events_per_page"]:
                    raise AssertionError("EVIDENCE page exceeded 500 events")
                for event in events:
                    if isinstance(event.get("event_index"), int):
                        evidence_event_indices.add(event["event_index"])
    expected_pages = math.ceil(scope_a["event_count"] / limits["evidence_events_per_page"])
    if len(evidence_event_indices) != scope_a["event_count"]:
        raise AssertionError("stable EVIDENCE pages did not recover all 100000 event indices")

    queue = _payload(expect_ok(invoke(adapter, "queue.snapshot", {"subject": subject}), "queue.snapshot"))
    delivery_keys = [item.get("delivery_key") for item in queue.get("turns", [])]
    expected_keys = [item["delivery_key"] for item in fixture["queue"]["turns"]]
    if delivery_keys[: len(expected_keys)] != expected_keys:
        raise AssertionError("durable FIFO order changed after restart")
    manifest_after = _payload(expect_ok(invoke(adapter, "recovery.manifest", {"subject": subject}), "recovery.manifest:after"))
    if manifest_before.get("raw_sets") != manifest_after.get("raw_sets"):
        raise AssertionError("cache rebuild/restart changed canonical raw manifest")

    return {
        "schema_version": "1.0",
        "scenario": "HM-S4-TO-VALUE",
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": sha256_bytes(canonical_bytes(fixture)),
        "adapter": adapter_identity,
        "restart": restart,
        "scope_refs": {"a": scope_a_ref, "b": scope_b_ref},
        "candidate_refs": candidate_refs,
        "resume_bytes": len(resume_bytes),
        "resume_sha256": sha256_bytes(resume_bytes),
        "view_summaries": views,
        "expected_min_evidence_pages": expected_pages,
        "recovered_event_indices": len(evidence_event_indices),
        "fifo_delivery_keys": delivery_keys,
        "status": "PASS"
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
        print(json.dumps({"fixture_id": fixture["fixture_id"], "fixture_sha256": sha256_bytes(canonical_bytes(fixture)), "status": "FIXTURE_PASS"}, sort_keys=True))
        return 0
    if args.adapter is None or args.artifact_dir is None:
        parser.error("formal run requires --adapter and --artifact-dir")
    artifact_dir = require_evidence_dir(args.artifact_dir)
    adapter, identity = load_adapter(args.adapter, fixture, artifact_dir)
    result = run(fixture, adapter, identity, artifact_dir)
    path = write_result(artifact_dir, "s4-value-smoke-result.json", result)
    print(json.dumps({"result": str(path), "status": result["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
