#!/usr/bin/env python3
"""Disposable vector, Context and bounded-document capacity spikes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def vector_tier(root: Path, count: int, dim: int, queries: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed + count)
    vectors = rng.standard_normal((count, dim), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    memory_types = np.arange(count, dtype=np.int8) % 4
    eligible = np.ones(count, dtype=bool)
    suppressed_indices = np.arange(0, min(count, 200), 10)
    eligible[suppressed_indices] = False
    path = root / f"vectors-{count}.npy"
    start_write = time.perf_counter()
    np.save(path, vectors, allow_pickle=False)
    write_ms = (time.perf_counter() - start_write) * 1000
    del vectors

    cold_start = time.perf_counter()
    matrix = np.load(path, mmap_mode="r")
    first_index = max(201, count // 3)
    first_query = np.asarray(matrix[first_index], dtype=np.float32)
    first_scores = matrix @ first_query
    first_scores[~eligible] = -np.inf
    cold_first_ms = (time.perf_counter() - cold_start) * 1000
    assert int(np.argmax(first_scores)) == first_index

    query_indices = rng.choice(np.flatnonzero(eligible), size=queries, replace=count < queries)
    latencies: list[float] = []
    required_hits = 0
    extra_type_items = 0
    returned_items = 0
    privacy_violations = 0
    hard_trigger_hits = 0
    for ordinal, index in enumerate(query_indices):
        query = np.asarray(matrix[index], dtype=np.float32).copy()
        query += rng.normal(0.0, 0.002, size=dim).astype(np.float32)
        query /= np.linalg.norm(query)
        wanted_type = memory_types[index]
        type_mask = memory_types == wanted_type
        started = time.perf_counter()
        scores = matrix @ query
        scores[~eligible] = -np.inf
        scores[~type_mask] = -np.inf
        top = np.argpartition(scores, -5)[-5:]
        top = top[np.argsort(scores[top])[::-1]]
        latencies.append((time.perf_counter() - started) * 1000)
        required_hits += int(index in top)
        privacy_violations += int(any(not eligible[item] for item in top))
        extra_type_items += sum(int(memory_types[item] != wanted_type) for item in top)
        returned_items += len(top)
        if ordinal < 20:
            hard_trigger_hits += int(index in top)

    # Suppression and rebuild operate from canonical eligibility, never from stale cached scores.
    stale_target = int(query_indices[0])
    eligible[stale_target] = False
    stale_scores = matrix @ np.asarray(matrix[stale_target], dtype=np.float32)
    stale_scores[~eligible] = -np.inf
    stale_resurrection = int(int(np.argmax(stale_scores)) == stale_target)
    del matrix
    rebuilt = np.load(path, mmap_mode="r")
    rebuilt_scores = rebuilt @ np.asarray(rebuilt[stale_target], dtype=np.float32)
    rebuilt_scores[~eligible] = -np.inf
    stale_resurrection += int(int(np.argmax(rebuilt_scores)) == stale_target)

    recall = required_hits / queries
    extra_rate = extra_type_items / max(1, returned_items)
    privacy = 1.0 - privacy_violations / queries
    hard_trigger = hard_trigger_hits / min(20, queries)
    p95 = percentile(latencies, 95)
    maximum = max(latencies)
    passed = (
        recall >= 0.9
        and extra_rate <= 0.15
        and privacy == 1.0
        and hard_trigger == 1.0
        and p95 <= 500
        and maximum <= 2000
        and cold_first_ms <= 2000
        and stale_resurrection == 0
    )
    return {
        "records": count,
        "dimension": dim,
        "queries": queries,
        "required_type_recall": recall,
        "extra_type_rate": extra_rate,
        "privacy_correctness": privacy,
        "hard_trigger_correctness": hard_trigger,
        "warm_p50_ms": percentile(latencies, 50),
        "warm_p95_ms": p95,
        "hard_max_ms": maximum,
        "cold_open_first_query_ms": cold_first_ms,
        "index_bytes": path.stat().st_size,
        "build_write_ms": write_ms,
        "stale_resurrection_count": stale_resurrection,
        "passed": passed,
    }


def run_vector(root: Path, config: dict[str, Any], seed: int) -> dict[str, Any]:
    tiers = [
        vector_tier(root, count, config["dimension"], config["queries_per_tier"], seed)
        for count in config["record_counts"]
    ]
    return {
        "passed": all(tier["passed"] for tier in tiers),
        "selected_backend": (
            "SQLite metadata/FTS5 plus rebuildable numpy float32 generation cache exact scan"
        ),
        "new_native_dependency": False,
        "degradation": (
            "If generation cache cannot open within deadline, use permission-filtered "
            "FTS/entity/time candidates and record VECTOR_DEGRADED; never use stale generation."
        ),
        "tiers": tiers,
    }


def token_upper_bound(value: Any) -> int:
    encoded = canonical(value)
    text = encoded.decode()
    # Conservative for CJK and JSON punctuation; synthetic oracle below is bytes/4 plus items.
    return max(len(text), math.ceil(len(encoded) / 3))


def provider_usage_oracle(value: Any) -> int:
    encoded = canonical(value)
    item_overhead = 8 * len(value.get("messages", [])) if isinstance(value, dict) else 0
    return math.ceil(len(encoded) / 4) + item_overhead


def make_groups(count: int, large_bytes: int) -> list[dict[str, Any]]:
    groups = []
    for index in range(count):
        scope = "scope-alpha" if index < 12 else "scope-beta"
        group: dict[str, Any] = {
            "group_id": f"g-{index:02d}",
            "task_scope_id": scope,
            "messages": [
                {"role": "user", "content": f"第 {index} 轮：继续 {scope} 的目标与步骤"},
                {"role": "assistant", "content": f"已完成步骤 {index}，记录 decision-{index}"},
            ],
        }
        if index in {5, 13, 22}:
            result = "R" * (large_bytes if index == 22 else 2048)
            group["tool"] = {
                "call": {"call_id": f"call-{index}", "name": "read_file"},
                "result": result,
                "artifact_ref": f"evidence://tool/{index}",
                "result_hash": hashlib.sha256(result.encode()).hexdigest(),
            }
        groups.append(group)
    return groups


def bounded_group(group: dict[str, Any]) -> dict[str, Any]:
    result = dict(group)
    if "tool" in result:
        tool = dict(result["tool"])
        raw = tool.pop("result")
        tool["typed_summary"] = {
            "bytes": len(raw.encode()),
            "kind": "tool_result",
            "preview": raw[:128],
        }
        result["tool"] = tool
    return result


def assemble_context(
    groups: list[dict[str, Any]], window: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    reserve = {4096: 1024, 8192: 2048, 32768: 4096}[window]
    safety = max(256, math.ceil(window * 0.1))
    effective = window - reserve - safety
    protected = [
        {"role": "system", "content": "protected rules"},
        {"role": "user", "content": "当前问题：继续旧任务并核对下一步"},
    ]
    recent = [bounded_group(group) for group in groups[-10:]]
    task = {
        "active": "scope-beta",
        "resume": {"goal": "完成记忆升级", "phase": "implementation", "next_action": "run tests"},
        "recent_scopes": ["scope-alpha", "scope-beta"],
    }
    optional = {
        "short_horizon": ["five-day episode ref"],
        "long_term": ["semantic preference", "procedure preference", "prospective reminder"],
        "skills": ["plan-test"],
        "attachments": [{"ref": "artifact://large", "bytes": 1048576}],
    }
    payload = {"messages": protected, "recent_groups": recent, "task": task, "optional": optional}
    crop_order: list[str] = []
    while token_upper_bound(payload) > effective:
        if payload["optional"].get("attachments"):
            payload["optional"]["attachments"] = []
            crop_order.append("attachments")
        elif payload["optional"].get("long_term"):
            payload["optional"]["long_term"] = payload["optional"]["long_term"][:1]
            crop_order.append("long_term")
        elif payload["optional"].get("short_horizon"):
            payload["optional"]["short_horizon"] = []
            crop_order.append("short_horizon")
        else:
            raise AssertionError("protected/current/recent/task cannot fit configured window")
    estimate = token_upper_bound(payload)
    provider_usage = provider_usage_oracle(payload)
    group_ids = [group["group_id"] for group in payload["recent_groups"]]
    tool_pairs_complete = all(
        "tool" not in group
        or (
            group["tool"].get("call")
            and group["tool"].get("typed_summary")
            and group["tool"].get("artifact_ref")
        )
        for group in payload["recent_groups"]
    )
    checks = {
        "effective_input_tokens": effective,
        "estimated_tokens": estimate,
        "provider_usage_oracle": provider_usage,
        "estimator_underestimated": estimate < provider_usage,
        "recent_group_ids": group_ids,
        "recent_groups_exactly_10": group_ids == [f"g-{i:02d}" for i in range(14, 24)],
        "tool_pairs_complete": tool_pairs_complete,
        "protected_and_current_present": payload["messages"] == protected,
        "active_scope": payload["task"]["active"],
        "payload_bytes": len(canonical(payload)),
        "crop_order": crop_order,
    }
    checks["passed"] = (
        estimate <= effective
        and not checks["estimator_underestimated"]
        and checks["recent_groups_exactly_10"]
        and checks["tool_pairs_complete"]
        and checks["protected_and_current_present"]
        and checks["active_scope"] == "scope-beta"
    )
    return payload, checks


def run_context(config: dict[str, Any]) -> dict[str, Any]:
    groups = make_groups(config["causal_groups"], config["large_tool_result_bytes"])
    cases = {}
    hashes = {}
    for window in config["context_windows"]:
        payload, checks = assemble_context(groups, window)
        replay_hash = hashlib.sha256(canonical(payload)).hexdigest()
        hashes[str(window)] = replay_hash
        checks["replay_hash_stable"] = (
            replay_hash == hashlib.sha256(canonical(json.loads(canonical(payload)))).hexdigest()
        )
        checks["passed"] = checks["passed"] and checks["replay_hash_stable"]
        cases[str(window)] = checks
    return {
        "passed": all(case["passed"] for case in cases.values()),
        "selected": {
            "recent_causal_groups": 10,
            "large_tool_results": "typed summary + exact artifact/evidence ref",
            "generation_reserve": {"4096": 1024, "8192": 2048, "32768": 4096},
            "safety_margin": "max(256 tokens, 10% context window)",
            "crop_priority": ["attachments", "long_term_to_one", "short_horizon"],
        },
        "cases": cases,
        "payload_hashes": hashes,
        "remaining_real_provider_gate": (
            "Calibrate estimator against actual provider usage; any underestimate blocks S5."
        ),
    }


def project_documents(event_count: int, config: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    page_size = 500
    pages = math.ceil(event_count / page_size)
    latest = [
        {
            "event_id": f"event-{event_count - offset}",
            "kind": "step",
            "summary": f"completed step {event_count - offset}",
        }
        for offset in range(min(40, event_count))
    ]
    readme = {
        "task_scope_id": "scope-long",
        "goal": "Implement Human Memory Digital Twin",
        "current_phase": "verification",
        "summary": f"Canonical archive has {event_count} events across {pages} stable pages.",
        "page_index_ref": "task://scope-long/EVIDENCE/index",
    }
    status = {
        "current_phase": "verification",
        "completed": event_count - 3,
        "changed": ["route authority", "memory activation"],
        "cancelled": [
            {"step": "legacy session migration", "reason": "prototype fresh data decision"}
        ],
        "next_action": "run full gate",
        "latest": latest,
    }
    resume = {
        "goal": readme["goal"],
        "current_phase": status["current_phase"],
        "completed": status["completed"],
        "changed": status["changed"],
        "cancelled": status["cancelled"],
        "next_action": status["next_action"],
        "repo_state": {"branch": "feat/human-memory-plan", "head": "spike", "dirty": False},
        "test_evidence": ["verification://human-memory/v0"],
        "page_refs": [f"task://scope-long/EVIDENCE/page/{index}" for index in range(pages)],
    }
    generation_ms = (time.perf_counter() - started) * 1000
    sizes = {
        "readme": len(canonical(readme)),
        "status": len(canonical(status)),
        "resume": len(canonical(resume)),
    }
    oracle = all(
        key in resume
        for key in (
            "goal",
            "current_phase",
            "completed",
            "changed",
            "cancelled",
            "next_action",
            "repo_state",
            "test_evidence",
        )
    )
    passed = (
        sizes["readme"] <= config["readme_bytes_max"]
        and sizes["status"] <= config["status_bytes_max"]
        and sizes["resume"] <= config["resume_bytes_max"]
        and oracle
        and len(resume["page_refs"]) == pages
    )
    return {
        "events": event_count,
        "pages": pages,
        "sizes_bytes": sizes,
        "generation_ms": generation_ms,
        "field_recovery_oracle": oracle,
        "stable_page_refs": len(resume["page_refs"]) == pages,
        "passed": passed,
    }


def run_documents(config: dict[str, Any]) -> dict[str, Any]:
    tiers = [project_documents(count, config) for count in config["task_event_counts"]]
    return {
        "passed": all(tier["passed"] for tier in tiers),
        "selected": {
            "readme_bytes_max": config["readme_bytes_max"],
            "status_bytes_max": config["status_bytes_max"],
            "resume_bytes_max": config["resume_bytes_max"],
            "page_bytes_max": config["page_bytes_max"],
            "events_per_evidence_page": 500,
        },
        "tiers": tiers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    config = manifest["spikes"]
    with tempfile.TemporaryDirectory(prefix="human-memory-capacity-spike-") as temp:
        vector = run_vector(Path(temp), config["SPIKE-VECTOR"], manifest["seed"])
    result = {
        "schema_version": 1,
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "vector": vector,
        "context": run_context(config["SPIKE-CONTEXT-DOC"]),
        "documents": run_documents(config["SPIKE-CONTEXT-DOC"]),
    }
    result["passed"] = all(result[key]["passed"] for key in ("vector", "context", "documents"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
