from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]


def _read_receipt(name: str) -> dict[str, object]:
    return json.loads(
        (ROOT / f"docs/{name}").read_text(encoding="utf-8")
    )


def _assert_privacy_safe(receipt: dict[str, object]) -> None:
    serialized = json.dumps(receipt, sort_keys=True)
    sensitive_fields = r"(?:content|query_text|user_text|assistant_text|db_path|wheel_path)"
    assert re.search(sensitive_fields, serialized) is None


def test_withdrawn_harness_0_5_candidate_receipt_is_explicitly_superseded() -> None:
    receipt = _read_receipt("harness-compatibility-candidate-0.5.1.json")
    assert receipt["result"] == "pass"
    assert receipt["promotion_status"] == "superseded"
    assert receipt["superseded_by_harness_source_commit"] == (
        "ac2e2add7e6f5efb5d4dd7b26fb138f9d750d334"
    )
    assert receipt["superseded_reason_code"] == (
        "harness-candidate-withdrawn-output-ownership"
    )
    _assert_privacy_safe(receipt)


def test_current_harness_0_5_candidate_receipt_is_exact_and_privacy_safe() -> None:
    receipt = _read_receipt("harness-compatibility-candidate-0.5.1-ac2e2add.json")
    assert set(receipt) == {
        "protocol",
        "result",
        "promotion_status",
        "tested_at_utc",
        "environment",
        "harness",
        "memory",
        "supersedes",
        "oracles",
    }
    assert receipt["protocol"] == "simple-harness-memory/harness-compatibility-receipt/v1"
    assert receipt["result"] == "pass"
    assert receipt["promotion_status"] == "candidate-pass-final-release-pending"
    assert receipt["environment"] == {
        "isolated_python": True,
        "python_version": "3.11.15",
    }
    assert receipt["harness"] == {
        "version": "0.5.0",
        "source_commit": "ac2e2add7e6f5efb5d4dd7b26fb138f9d750d334",
        "wheel_sha256": "d5ac29760304b0eeebd40dd26bac7f8e65d0700a4066699a9f0d5fca6ec3f94c",
        "candidate_manifest_sha256": (
            "9cc8363c33ecfef2a0c446d17ca89a02e0b58fe1b6fe6e4ae77a0ac2b706d59f"
        ),
        "artifact_status": "candidate",
    }
    assert receipt["memory"] == {
        "version": "0.5.1",
        "source_commit": "e28299108ade9275776b280fd008e349139f65e8",
        "wheel_sha256": "7821e895dd4adac5b98aa42c6f0fadc0362ee983e4531f7d75892107209939cc",
        "artifact_status": "candidate",
    }
    assert receipt["supersedes"] == {
        "receipt_commit": "e44d619310ce09507a817517d7f69e8e42f0d7db",
        "harness_wheel_sha256": "7d70b9fa2f5953ce8b2ba23cc0b9bc40fb101631964b25dcb047effda8f71167",
        "status": "superseded",
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
    _assert_privacy_safe(receipt)


def test_legacy_receipt_retains_original_exact_identity() -> None:
    receipt = json.loads(
        (ROOT / "docs/harness-compatibility-candidate-0.5.1.json").read_text(
            encoding="utf-8"
        )
    )
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


def test_formal_harness_release_receipt_closes_both_matrix_cells() -> None:
    receipt = _read_receipt("harness-compatibility-release-0.5.1.json")
    assert receipt["result"] == "pass"
    assert receipt["promotion_status"] == "harness-release-matrix-complete"
    assert receipt["memory_tested_wheel"] == {
        "version": "0.5.1",
        "source_commit": "e28299108ade9275776b280fd008e349139f65e8",
        "wheel_sha256": "7821e895dd4adac5b98aa42c6f0fadc0362ee983e4531f7d75892107209939cc",
    }
    harness_0_4, harness_0_5 = cast(list[dict[str, object]], receipt["harness_releases"])
    assert harness_0_4 == {
        "version": "0.4.0",
        "wheel_sha256": "aaf8d79a71b75bde0d71157a635b841eb557ea8889e2824571cacd7d8a58ecb6",
        "result": "pass",
    }
    assert harness_0_5["source_commit"] == "ac2e2add7e6f5efb5d4dd7b26fb138f9d750d334"
    assert harness_0_5["wheel_sha256"] == (
        "d5ac29760304b0eeebd40dd26bac7f8e65d0700a4066699a9f0d5fca6ec3f94c"
    )
    assert harness_0_5["byte_identical_to_candidate"] is True
    assert harness_0_5["latest"] is True
    assert harness_0_5["draft"] is False
    assert harness_0_5["prerelease"] is False
    _assert_privacy_safe(receipt)
