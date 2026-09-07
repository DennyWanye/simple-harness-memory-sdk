"""Independent literal-input oracle; stdlib only, never product imports/output."""

import hashlib
import json
from pathlib import Path


def h(domain, payload):
    value = json.dumps(
        {"domain": domain, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def main():
    prefix = "memory.operation.audit."
    refs = {
        kind: h(prefix + "ref.v1", {"kind": kind, "value": value})
        for kind, value in (
            ("host_request", "请求-1"),
            ("host_attempt", "尝试-1"),
            ("invocation", "sdk-invocation-1"),
        )
    }
    payload = {
        "schema_version": 1,
        "operation": "execute_typed_recall",
        "host_request_ref_hash": refs["host_request"],
        "host_attempt_ref_hash": refs["host_attempt"],
        "invocation_ref_hash": refs["invocation"],
        "request_hash": None,
        "context_hash": "1" * 64,
        "plan_hash": "2" * 64,
        "stage": "protocol",
        "reason": "typed_recall_protocol_unsupported",
        "candidate_query_started": False,
        "candidate_query_count": 0,
        "observed_at": 40.0,
        "persistence_status": "host_persistence_unverified",
    }
    result = {
        "refs": refs,
        "observation": payload,
        "observation_hash": h(prefix + "observation.v1", payload),
    }
    target = Path(__file__).parents[1] / "tests/fixtures/operation-audit-v1/observation.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
