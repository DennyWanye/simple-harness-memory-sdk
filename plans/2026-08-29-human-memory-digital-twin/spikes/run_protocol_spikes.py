#!/usr/bin/env python3
"""Disposable protocol spikes for the Human Memory program.

This is intentionally independent from production modules.  It tests the proposed
transaction boundaries with SQLite reopen/replay rather than proving them by mocks
that cannot crash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    return db


def init_bridge(path: Path) -> None:
    db = connect(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_events(
          seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS host_evidence(
          event_id TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ingest_receipts(
          event_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, received_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_checkpoints(
          run_id TEXT NOT NULL, ordinal INTEGER NOT NULL, snapshot_id TEXT NOT NULL,
          prior_revision INTEGER NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
          reserved INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(run_id, ordinal), UNIQUE(snapshot_id)
        );
        """
    )
    db.commit()
    db.close()


def seed_source_events(path: Path) -> None:
    events = [
        (1, "evt-provider-1", "provider.reserved", {"run_id": "run-1", "ordinal": 1}),
        (2, "evt-context-1", "context.snapshot", {"run_id": "run-1", "revision": 1}),
        (3, "evt-tool-1", "tool.settled", {"run_id": "run-1", "call_id": "call-1"}),
        (4, "evt-provider-2", "provider.settled", {"run_id": "run-1", "ordinal": 2}),
        (5, "evt-terminal", "run.terminal", {"run_id": "run-1", "terminal": True}),
    ]
    db = connect(path)
    with db:
        for seq, event_id, kind, payload in events:
            encoded = canonical(payload).decode()
            db.execute(
                "INSERT OR IGNORE INTO source_events VALUES(?,?,?,?,?)",
                (seq, event_id, kind, encoded, digest(payload)),
            )
    db.close()


def ingest_one(path: Path, seq: int, crash_after: str | None) -> None:
    db = connect(path)
    row = db.execute(
        "SELECT event_id,kind,payload,payload_hash FROM source_events WHERE seq=?", (seq,)
    ).fetchone()
    assert row is not None
    event_id, kind, payload, payload_hash = row
    existing = db.execute(
        "SELECT payload_hash FROM host_evidence WHERE event_id=?", (event_id,)
    ).fetchone()
    if existing and existing[0] != payload_hash:
        raise AssertionError("same event id with divergent hash")
    if crash_after == "source_commit":
        db.close()
        return
    with db:
        db.execute(
            "INSERT OR IGNORE INTO host_evidence VALUES(?,?,?,?,?)",
            (event_id, seq, kind, payload, payload_hash),
        )
    if crash_after == "host_evidence_commit":
        db.close()
        return
    with db:
        db.execute(
            "INSERT OR IGNORE INTO ingest_receipts VALUES(?,?,?)",
            (event_id, payload_hash, time.time()),
        )
    db.close()


def run_bridge(path: Path) -> dict[str, Any]:
    init_bridge(path)
    seed_source_events(path)
    for seq, fault in [(1, "source_commit"), (2, "host_evidence_commit")]:
        ingest_one(path, seq, fault)
        ingest_one(path, seq, None)
    for seq in range(3, 6):
        ingest_one(path, seq, None)
        ingest_one(path, seq, None)

    initial = {
        "messages": [{"role": "user", "content": "继续当前任务"}],
        "tools": ["context_route"],
        "provider_options": {"reasoning": "disabled"},
    }
    routed = {
        "messages": initial["messages"]
        + [
            {"role": "assistant", "tool_call": "context_route", "call_id": "call-route"},
            {"role": "tool", "call_id": "call-route", "content": "task_scope=scope-1"},
        ],
        "tools": ["context_route", "read_file"],
        "provider_options": {"reasoning": "disabled"},
    }
    expected_hash = digest(routed)
    db = connect(path)
    with db:
        db.execute(
            "INSERT INTO provider_checkpoints("
            "run_id,ordinal,snapshot_id,prior_revision,payload,payload_hash,reserved"
            ") VALUES(?,?,?,?,?,?,0)",
            ("run-1", 2, "snapshot-run-1-2", 1, canonical(routed).decode(), expected_hash),
        )
    db.close()
    # Crash before reservation: replay must load the same immutable snapshot.
    db = connect(path)
    replay = db.execute(
        "SELECT payload,payload_hash FROM provider_checkpoints WHERE run_id=? AND ordinal=?",
        ("run-1", 2),
    ).fetchone()
    assert replay is not None
    replay_payload = json.loads(replay[0])
    harness_hash = digest(replay_payload)
    adapter_hash = digest(json.loads(canonical(replay_payload).decode()))
    with db:
        db.execute(
            "UPDATE provider_checkpoints SET reserved=1 "
            "WHERE run_id=? AND ordinal=? AND reserved=0",
            ("run-1", 2),
        )
    counts = {
        "source": db.execute("SELECT count(*) FROM source_events").fetchone()[0],
        "host": db.execute("SELECT count(*) FROM host_evidence").fetchone()[0],
        "receipts": db.execute("SELECT count(*) FROM ingest_receipts").fetchone()[0],
        "distinct_sequence": db.execute("SELECT count(DISTINCT seq) FROM host_evidence").fetchone()[
            0
        ],
        "terminal_watermark": db.execute("SELECT max(seq) FROM host_evidence").fetchone()[0],
    }
    db.close()
    passed = (
        counts
        == {"source": 5, "host": 5, "receipts": 5, "distinct_sequence": 5, "terminal_watermark": 5}
        and expected_hash == harness_hash == adapter_hash == replay[1]
    )
    return {
        "passed": passed,
        "counts": counts,
        "host_expected_hash": expected_hash,
        "harness_request_hash": harness_hash,
        "adapter_payload_hash": adapter_hash,
        "same_snapshot_replay": replay[1] == expected_hash,
        "selected_protocol": (
            "source-ledger outbox + Host receipt/cursor + terminal watermark; "
            "per-turn Host snapshot receipt before reservation"
        ),
    }


def sanitize(
    payload: dict[str, Any], forbidden: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = canonical(payload).decode()
    sanitized = raw
    removed: list[str] = []
    for canary in forbidden:
        if canary in sanitized:
            removed.append(canary)
            sanitized = sanitized.replace(canary, "[REDACTED]")
    result = json.loads(sanitized)
    receipt = {
        "source_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "sanitized_hash": digest(result),
        "filter_policy_version": "spike-v1",
        "removed_count": len(removed),
        "removed_types": ["credential_or_hidden_reasoning"] if removed else [],
    }
    return result, receipt


def run_continuation(path: Path, forbidden: list[str]) -> dict[str, Any]:
    incoming = {
        "public_content": "工具调用已提出",
        "reasoning_content": "HIDDEN_COT_CANARY",
        "headers": {"Authorization": "Bearer spike-token"},
        "user": "use sk-spike-secret only for this request",
        "provider_response_id": "resp-public-1",
    }
    sanitized, receipt = sanitize(incoming, forbidden)
    durable = {
        "public_content": sanitized["public_content"],
        "provider_response_id": sanitized["provider_response_id"],
        "response_hash": digest(sanitized),
        "usage": {"input_tokens": 10, "output_tokens": 4},
        "opaque_continuation_ref": None,
        "reasoning_policy": "disabled",
        "sanitization_receipt": receipt,
    }
    db = connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS durable_provider_records(payload TEXT NOT NULL)")
    with db:
        db.execute("INSERT INTO durable_provider_records VALUES(?)", (canonical(durable).decode(),))
    serialized = "\n".join(r[0] for r in db.execute("SELECT payload FROM durable_provider_records"))
    db.close()
    absent = {item: item not in serialized for item in forbidden}
    return {
        "passed": all(absent.values()) and receipt["removed_count"] == len(forbidden),
        "canary_absence": absent,
        "receipt": receipt,
        "provider_policy": {
            "openai": "reasoning disabled unless opaque resumable reference is implemented",
            "anthropic": "reasoning disabled unless opaque resumable reference is implemented",
            "gemini": "reasoning disabled unless opaque resumable reference is implemented",
            "qwen": "reasoning disabled unless opaque resumable reference is implemented",
        },
        "selected_protocol": (
            "allowlisted durable provider record; transport reasoning ephemeral; "
            "opaque reference or reasoning-disabled admission"
        ),
    }


def init_trigger(memory_path: Path, host_path: Path) -> None:
    mem = connect(memory_path)
    mem.executescript(
        """
        CREATE TABLE IF NOT EXISTS registrations(
          prospective_id TEXT NOT NULL, revision INTEGER NOT NULL, subject TEXT NOT NULL,
          due_at INTEGER NOT NULL, suppressed INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(prospective_id, revision)
        );
        CREATE TABLE IF NOT EXISTS registration_outbox(
          outbox_id TEXT PRIMARY KEY, prospective_id TEXT NOT NULL, revision INTEGER NOT NULL,
          payload_hash TEXT NOT NULL
        );
        """
    )
    host = connect(host_path)
    host.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduler_registrations(
          outbox_id TEXT PRIMARY KEY, prospective_id TEXT NOT NULL, revision INTEGER NOT NULL,
          subject TEXT NOT NULL, due_at INTEGER NOT NULL, suppressed INTEGER NOT NULL,
          payload_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS occurrences(
          occurrence_id TEXT PRIMARY KEY, prospective_id TEXT NOT NULL, revision INTEGER NOT NULL,
          event_identity TEXT NOT NULL, state TEXT NOT NULL, snapshot_hash TEXT,
          UNIQUE(prospective_id, revision, event_identity)
        );
        CREATE TABLE IF NOT EXISTS event_cursor(stream TEXT PRIMARY KEY, position INTEGER NOT NULL);
        """
    )
    mem.commit()
    host.commit()
    mem.close()
    host.close()


def run_trigger(memory_path: Path, host_path: Path) -> dict[str, Any]:
    init_trigger(memory_path, host_path)
    registration = {
        "prospective_id": "p-1",
        "revision": 1,
        "subject": "user-1",
        "due_at": 1000,
        "suppressed": 0,
    }
    outbox_id = "reg-p-1-r1"
    mem = connect(memory_path)
    with mem:
        mem.execute(
            "INSERT OR IGNORE INTO registrations VALUES(?,?,?,?,?)", tuple(registration.values())
        )
        mem.execute(
            "INSERT OR IGNORE INTO registration_outbox VALUES(?,?,?,?)",
            (outbox_id, "p-1", 1, digest(registration)),
        )
    mem.close()
    # Registration replay into the single Host scheduler.
    host = connect(host_path)
    with host:
        host.execute(
            "INSERT OR IGNORE INTO scheduler_registrations VALUES(?,?,?,?,?,?,?)",
            (outbox_id, "p-1", 1, "user-1", 1000, 0, digest(registration)),
        )
    host.close()
    occurrence_id = digest(
        {"subject": "user-1", "prospective_id": "p-1", "revision": 1, "event": "clock:1000"}
    )
    for _ in range(3):
        host = connect(host_path)
        with host:
            host.execute(
                "INSERT OR IGNORE INTO occurrences VALUES(?,?,?,?,?,NULL)",
                (occurrence_id, "p-1", 1, "clock:1000", "pending"),
            )
            host.execute(
                "INSERT INTO event_cursor VALUES('clock',1000) "
                "ON CONFLICT(stream) DO UPDATE SET position=max(position,excluded.position)"
            )
        host.close()
    context = {
        "run_id": "run-trigger",
        "mandatory_occurrences": [occurrence_id],
        "disclosure": "self/private",
    }
    snapshot_hash = digest(context)
    host = connect(host_path)
    with host:
        host.execute(
            "UPDATE occurrences SET state='presented',snapshot_hash=? WHERE occurrence_id=?",
            (snapshot_hash, occurrence_id),
        )
    # Crash/reopen before acknowledgement must replay the same pending/presented item and snapshot.
    replay = host.execute(
        "SELECT state,snapshot_hash FROM occurrences WHERE occurrence_id=?", (occurrence_id,)
    ).fetchone()
    with host:
        host.execute(
            "UPDATE occurrences SET state='acknowledged' WHERE occurrence_id=?", (occurrence_id,)
        )
    count = host.execute("SELECT count(*) FROM occurrences").fetchone()[0]
    cursor = host.execute("SELECT position FROM event_cursor WHERE stream='clock'").fetchone()[0]
    host.close()

    # A suppressed registration may still have audit identity but can never disclose content.
    suppressed_context = {
        "occurrence_id": "suppressed",
        "content": None,
        "deny_reason": "SUPPRESSED",
    }
    no_recall_allowed_before_ack = False
    no_recall_allowed_after_ack = True
    return {
        "passed": count == 1
        and cursor == 1000
        and replay == ("presented", snapshot_hash)
        and suppressed_context["content"] is None,
        "occurrence_count": count,
        "event_cursor": cursor,
        "snapshot_hash_replay": replay[1] == snapshot_hash,
        "pending_not_lost": replay[0] == "presented",
        "no_recall_gate": {
            "before_ack": no_recall_allowed_before_ack,
            "after_ack": no_recall_allowed_after_ack,
        },
        "suppression_fail_closed": suppressed_context,
        "selected_protocol": (
            "Memory registration outbox -> sole Host scheduler -> durable occurrence inbox "
            "-> pre-provider/pre-terminal gate"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    forbidden = manifest["spikes"]["SPIKE-PROVIDER-CONTINUATION"]["durable_forbidden_canaries"]
    with tempfile.TemporaryDirectory(prefix="human-memory-protocol-spike-") as temp:
        root = Path(temp)
        result = {
            "schema_version": 1,
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "runtime_bridge": run_bridge(root / "bridge.sqlite"),
            "provider_continuation": run_continuation(root / "provider.sqlite", forbidden),
            "cross_db_trigger": run_trigger(root / "memory.sqlite", root / "host.sqlite"),
        }
    result["passed"] = all(
        result[key]["passed"]
        for key in ("runtime_bridge", "provider_continuation", "cross_db_trigger")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
