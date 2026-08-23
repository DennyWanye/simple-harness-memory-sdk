from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_harness_0_5_candidate_receipt_is_exact_and_privacy_safe() -> None:
    receipt = json.loads(
        (ROOT / "docs/harness-compatibility-candidate-0.5.1.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(receipt) == {
        "protocol",
        "result",
        "tested_at_utc",
        "environment",
        "harness",
        "memory",
        "oracles",
    }
    assert receipt["protocol"] == "simple-harness-memory/harness-compatibility-receipt/v1"
    assert receipt["result"] == "pass"
    assert receipt["environment"] == {
        "isolated_python": True,
        "python_version": "3.11.15",
    }
    assert receipt["harness"] == {
        "version": "0.5.0",
        "source_commit": "7fd6610ffd5630a7d1f8f263637264bc95360d2c",
        "wheel_sha256": "7d70b9fa2f5953ce8b2ba23cc0b9bc40fb101631964b25dcb047effda8f71167",
        "artifact_status": "candidate",
    }
    assert receipt["memory"] == {
        "version": "0.5.1",
        "source_commit": "e28299108ade9275776b280fd008e349139f65e8",
        "wheel_sha256": "7821e895dd4adac5b98aa42c6f0fadc0362ee983e4531f7d75892107209939cc",
        "artifact_status": "candidate",
    }
    assert receipt["oracles"] == [
        "agent-memory-v1-public-contract-golden",
        "personal-family-scope-isolation",
        "cloud-embedding-lineage",
        "recall-release-lifecycle",
        "committed-turn-receipt-idempotency",
        "context-preparation-consumed",
        "memory-outbox-applied",
        "committed-turn-message-pair",
        "restart-replay-no-duplicates",
    ]
    serialized = json.dumps(receipt, sort_keys=True)
    sensitive_fields = r"(?:content|query_text|user_text|assistant_text|db_path|wheel_path)"
    assert re.search(sensitive_fields, serialized) is None
