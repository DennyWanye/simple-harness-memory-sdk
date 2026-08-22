from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
import time
from pathlib import Path

import pytest
from simple_harness import AgentIdentity, CommittedTurn, MemoryScopeRef
from simple_harness.execution.sqlite import (
    ExecutionMigrationManifest,
    LegacyDisposition,
    MigrationManifestEntry,
)
from simple_harness.execution.sqlite import (
    LegacyIdentityBinding as HarnessLegacyIdentityBinding,
)
from simple_harness.execution.sqlite import (
    LegacyIdentityMap as HarnessLegacyIdentityMap,
)

from simple_harness_memory import MemoryManager
from simple_harness_memory.backends.sqlite import SCHEMA_VERSION
from simple_harness_memory.core.conversation import canonical_message_payload_hash
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryMigrationError,
    MemoryMigrationManifestError,
    MemoryMigrationSourceBusy,
)
from simple_harness_memory.core.identity import MemoryPrincipal, MemoryScope
from simple_harness_memory.migrations import (
    EXECUTION_MANIFEST_PROTOCOL,
    LEGACY_SCHEMA_CHECKSUM,
    LegacyIdentityBinding,
    LegacyIdentityMap,
    MigrationDecision,
    NonHarnessProvenanceEntry,
    NonHarnessProvenanceManifest,
    NormalizedExecutionEntry,
    execution_manifest_digest,
    import_execution_manifest,
    migrate_v3_to_v4,
)

_V3_DDL = """
CREATE TABLE users(user_id TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE sessions(
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  created_at REAL NOT NULL,
  last_activity_at REAL NOT NULL,
  UNIQUE(user_id, session_id)
);
CREATE TABLE messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at REAL NOT NULL,
  salience REAL NOT NULL DEFAULT 0,
  decay_rate REAL NOT NULL DEFAULT 0.02,
  last_recalled REAL,
  last_decay_at REAL,
  embedding BLOB,
  is_summary INTEGER NOT NULL DEFAULT 0,
  summary_of TEXT,
  source_event_id TEXT NOT NULL UNIQUE,
  payload_hash TEXT NOT NULL,
  embedder_kind TEXT,
  embedding_dim INTEGER,
  embedding_format_version INTEGER,
  UNIQUE(user_id, id),
  FOREIGN KEY(user_id, session_id) REFERENCES sessions(user_id, session_id) ON DELETE CASCADE
);
CREATE TABLE facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  category TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1,
  evidence TEXT NOT NULL DEFAULT '',
  source_msg_id INTEGER NOT NULL,
  created_at REAL NOT NULL,
  decay_rate REAL NOT NULL DEFAULT 0.01,
  pinned INTEGER NOT NULL DEFAULT 0,
  last_decay_at REAL,
  superseded_by INTEGER,
  forgotten_at REAL,
  UNIQUE(user_id, id),
  FOREIGN KEY(user_id, source_msg_id) REFERENCES messages(user_id, id) ON DELETE CASCADE,
  FOREIGN KEY(superseded_by) REFERENCES facts(id) ON DELETE SET NULL
);
CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _hash(source: str, role: str, text: str) -> str:
    return canonical_message_payload_hash(
        source_event_id=source,
        user_id="legacy-user",
        session_id="legacy-session",
        role=role,
        memory_text=text,
    )


def _create_v3(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    connection.executescript(_V3_DDL)
    connection.executemany(
        "INSERT INTO schema_meta VALUES (?, ?)",
        (("schema_version", "3"), ("schema_checksum", LEGACY_SCHEMA_CHECKSUM)),
    )
    now = time.time()
    connection.execute("INSERT INTO users VALUES ('legacy-user', ?)", (now,))
    connection.execute(
        "INSERT INTO sessions VALUES ('legacy-session', 'legacy-user', ?, ?)", (now, now)
    )
    rows = {
        "tentative-user": ("user", "tentative secret"),
        "keep-user": ("user", "My pet is Max"),
        "terminal-failed": ("assistant", "failed terminal secret"),
        "deferred-user": ("user", "deferred secret"),
        "standalone": ("user", "I live in Shanghai"),
    }
    hashes: dict[str, str] = {}
    for index, (source, (role, content)) in enumerate(rows.items(), 1):
        payload_hash = _hash(source, role, content)
        hashes[source] = payload_hash
        cursor = connection.execute(
            "INSERT INTO messages(user_id, session_id, role, content, created_at, embedding, "
            "source_event_id, payload_hash, embedder_kind, embedding_dim, "
            "embedding_format_version) VALUES "
            "('legacy-user', 'legacy-session', ?, ?, ?, ?, ?, ?, 'hash', 2, 1)",
            (role, content, now + index, b"[0.1,0.2]", source, payload_hash),
        )
        assert cursor.lastrowid is not None
        fact_key = {
            "tentative-user": "name",
            "keep-user": "pet_name",
            "standalone": "location",
        }.get(source, f"key_{index}")
        connection.execute(
            "INSERT INTO facts(user_id, subject, key, value, category, confidence, evidence, "
            "source_msg_id, created_at) VALUES "
            "('legacy-user', 'user', ?, ?, 'profile', 1, ?, ?, ?)",
            (fact_key, content, content, cursor.lastrowid, now + index),
        )
    connection.commit()
    connection.close()
    path.chmod(0o600)
    return hashes


def _identity_map() -> LegacyIdentityMap:
    return LegacyIdentityMap.create(
        (
            LegacyIdentityBinding(
                "legacy-user",
                "legacy-session",
                "deployment-a",
                "house-a",
                "actor-a",
                "session-a",
            ),
        )
    )


def _entry(
    source: str,
    payload_hash: str,
    decision: MigrationDecision,
    *,
    turn: str | None = None,
    role: str | None = None,
    text: str | None = None,
) -> NormalizedExecutionEntry:
    return NormalizedExecutionEntry(
        source,
        payload_hash,
        decision,
        turn,
        role,
        text,
        "legacy-user" if text is not None else None,
        "legacy-session" if text is not None else None,
    )


def _manifest(hashes: dict[str, str]) -> dict[str, object]:
    assistant_hash = _hash("keep-assistant", "assistant", "I will remember Max")
    entries = (
        _entry("tentative-user", hashes["tentative-user"], MigrationDecision.SUPPRESS_TENTATIVE),
        _entry(
            "keep-user",
            hashes["keep-user"],
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="turn-complete",
        ),
        _entry(
            "keep-assistant",
            assistant_hash,
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="turn-complete",
            role="assistant",
            text="I will remember Max",
        ),
        _entry(
            "terminal-failed",
            hashes["terminal-failed"],
            MigrationDecision.SUPPRESS_TERMINAL,
        ),
        _entry("deferred-user", hashes["deferred-user"], MigrationDecision.DEFERRED_TURN),
    )
    return {
        "protocol": EXECUTION_MANIFEST_PROTOCOL,
        "entries": [
            {
                "source_event_id": entry.source_event_id,
                "payload_hash": entry.payload_hash,
                "decision": entry.decision.value,
                "turn_id": entry.turn_id,
                "role": entry.role,
                "memory_text": entry.memory_text,
                "legacy_user_id": entry.legacy_user_id,
                "legacy_session_id": entry.legacy_session_id,
            }
            for entry in entries
        ],
        "digest": execution_manifest_digest(entries),
    }


def test_offline_migration_filters_derived_state_and_completes_pair(tmp_path):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )
    receipt = migrate_v3_to_v4(
        path,
        execution_manifest=_manifest(hashes),
        provenance_manifest=provenance,
        identity_map=_identity_map(),
    )
    assert (receipt.kept_messages, receipt.kept_facts, receipt.suppressed_sources) == (3, 2, 3)
    assert receipt.completed_pairs == 1
    assert receipt.to_json()["digest"] == receipt.digest
    assert path.with_name(path.name + ".v3.backup.db").exists()

    connection = sqlite3.connect(path)
    assert dict(connection.execute("SELECT key, value FROM schema_meta"))["schema_version"] == str(
        SCHEMA_VERSION
    )
    sources = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            "SELECT source_event_id, role, content FROM messages ORDER BY source_event_id"
        )
    }
    assert set(sources) == {"keep-user", "keep-assistant", "standalone"}
    assert sources["keep-assistant"] == ("assistant", "I will remember Max")
    assert connection.execute(
        "SELECT COUNT(*) FROM messages WHERE embedding IS NOT NULL"
    ).fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
    suppressed = dict(
        connection.execute("SELECT source_event_id, decision FROM suppression_receipts")
    )
    assert suppressed == {
        "legacy-source:tentative-user": "SUPPRESS_TENTATIVE",
        "legacy-source:terminal-failed": "SUPPRESS_TERMINAL",
        "legacy-source:deferred-user": "DEFERRED_TURN",
    }
    aggregate = " ".join(
        str(row[0]) for row in connection.execute("SELECT data_json FROM digital_twins")
    )
    assert "secret" not in aggregate
    assert "Max" in aggregate and "Shanghai" in aggregate
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


@pytest.mark.parametrize("phase", ["after_backup", "after_temp_validated", "after_swap"])
def test_migration_fault_restores_usable_v3(tmp_path, phase):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )

    def fail(current: str) -> None:
        if current == phase:
            raise RuntimeError("injected migration fault")

    with pytest.raises(MemoryMigrationError):
        migrate_v3_to_v4(
            path,
            execution_manifest=_manifest(hashes),
            provenance_manifest=provenance,
            identity_map=_identity_map(),
            backup_path=tmp_path / f"backup-{phase}.db",
            fault_injector=fail,
        )
    connection = sqlite3.connect(path)
    meta = dict(connection.execute("SELECT key, value FROM schema_meta"))
    assert meta["schema_version"] == "3"
    assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 5
    assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    connection.close()


def test_manifest_tamper_duplicate_coverage_and_identity_fail_closed(tmp_path):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )
    tampered = _manifest(hashes)
    tampered["digest"] = "0" * 64
    with pytest.raises(MemoryMigrationManifestError):
        migrate_v3_to_v4(
            path,
            execution_manifest=tampered,
            provenance_manifest=provenance,
            identity_map=_identity_map(),
        )
    assert not path.with_name(path.name + ".v3.backup.db").exists()

    duplicate = NonHarnessProvenanceManifest.create(
        (
            NonHarnessProvenanceEntry("standalone", hashes["standalone"]),
            NonHarnessProvenanceEntry("keep-user", hashes["keep-user"]),
        )
    )
    with pytest.raises(MemoryMigrationError):
        migrate_v3_to_v4(
            path,
            execution_manifest=_manifest(hashes),
            provenance_manifest=duplicate,
            identity_map=_identity_map(),
            backup_path=tmp_path / "duplicate-backup.db",
        )
    connection = sqlite3.connect(path)
    assert dict(connection.execute("SELECT key, value FROM schema_meta"))["schema_version"] == "3"
    connection.close()

    missing = NonHarnessProvenanceManifest.create(())
    with pytest.raises(MemoryMigrationError):
        migrate_v3_to_v4(
            path,
            execution_manifest=_manifest(hashes),
            provenance_manifest=missing,
            identity_map=_identity_map(),
            backup_path=tmp_path / "missing-backup.db",
        )
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 5
    connection.close()


def test_offline_migration_rejects_live_legacy_writer(tmp_path):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(MemoryMigrationSourceBusy) as busy:
            migrate_v3_to_v4(
                path,
                execution_manifest=_manifest(hashes),
                provenance_manifest=provenance,
                identity_map=_identity_map(),
            )
        assert busy.value.code == "memory_migration_source_busy"
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert not path.with_name(path.name + ".v3.backup.db").exists()


def test_offline_migration_rejects_incomplete_identity_mapping(tmp_path):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )
    wrong_map = LegacyIdentityMap.create(
        (
            LegacyIdentityBinding(
                "different-user",
                "different-session",
                "deployment-a",
                "house-a",
                "actor-a",
                "different-session",
            ),
        )
    )
    with pytest.raises(MemoryMigrationError):
        migrate_v3_to_v4(
            path,
            execution_manifest=_manifest(hashes),
            provenance_manifest=provenance,
            identity_map=wrong_map,
            backup_path=tmp_path / "identity-backup.db",
        )
    connection = sqlite3.connect(path)
    assert dict(connection.execute("SELECT key, value FROM schema_meta"))["schema_version"] == "3"
    connection.close()


@pytest.mark.asyncio
async def test_public_runtime_import_accepts_keep_only_and_replays(tmp_path):
    manager = await MemoryManager.build(db_path=str(tmp_path / "v4.db"))
    user_text = "runtime imported user"
    assistant_text = "runtime imported assistant"
    entries = (
        _entry(
            "runtime-user",
            _hash("runtime-user", "user", user_text),
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="runtime-turn",
            role="user",
            text=user_text,
        ),
        _entry(
            "runtime-assistant",
            _hash("runtime-assistant", "assistant", assistant_text),
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="runtime-turn",
            role="assistant",
            text=assistant_text,
        ),
    )
    manifest = {
        "protocol": EXECUTION_MANIFEST_PROTOCOL,
        "entries": [dataclasses.asdict(entry) for entry in entries],
        "digest": execution_manifest_digest(entries),
    }
    first = await import_execution_manifest(manager, manifest, _identity_map())
    replay = await import_execution_manifest(manager, manifest, _identity_map())
    assert (first.applied_pairs, replay.replayed_pairs) == (1, 1)
    remapped = LegacyIdentityMap.create(
        (
            LegacyIdentityBinding(
                "legacy-user",
                "legacy-session",
                "deployment-a",
                "house-a",
                "actor-b",
                "session-b",
            ),
        )
    )
    with pytest.raises(MemoryIdempotencyConflict):
        await import_execution_manifest(manager, manifest, remapped)

    for index, decision in enumerate(
        (
            MigrationDecision.SUPPRESS_TENTATIVE,
            MigrationDecision.SUPPRESS_TERMINAL,
            MigrationDecision.DEFERRED_TURN,
        )
    ):
        source = f"runtime-rejected-{index}"
        rejected_entries = (
            _entry(
                source,
                _hash(source, "user", "later"),
                decision,
                role="user",
                text="later",
            ),
        )
        rejected = {
            "protocol": EXECUTION_MANIFEST_PROTOCOL,
            "entries": [dataclasses.asdict(entry) for entry in rejected_entries],
            "digest": execution_manifest_digest(rejected_entries),
        }
        with pytest.raises(MemoryMigrationManifestError):
            await import_execution_manifest(manager, rejected, _identity_map())
    await manager.close()


@pytest.mark.asyncio
async def test_runtime_manifest_import_does_not_resurrect_erased_scope(tmp_path):
    manager = await MemoryManager.build(db_path=str(tmp_path / "erased.db"))
    principal = MemoryPrincipal("deployment-a", "house-a", "actor-a", "session-a")
    scope = MemoryScope.personal("actor-a")
    async with manager.backend._transaction():
        await manager.backend._bind_agent_session(principal)
    await manager.delete_scope(principal, (scope,))
    entries = (
        _entry(
            "erased-user",
            _hash("erased-user", "user", "must stay erased"),
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="erased-turn",
            role="user",
            text="must stay erased",
        ),
        _entry(
            "erased-assistant",
            _hash("erased-assistant", "assistant", "ack"),
            MigrationDecision.KEEP_COMPLETED_PAIR,
            turn="erased-turn",
            role="assistant",
            text="ack",
        ),
    )
    manifest = {
        "protocol": EXECUTION_MANIFEST_PROTOCOL,
        "entries": [dataclasses.asdict(entry) for entry in entries],
        "digest": execution_manifest_digest(entries),
    }
    with pytest.raises(MemoryMigrationError, match="memory_migration_erased_scope"):
        await import_execution_manifest(manager, manifest, _identity_map())
    async with manager.backend._conn.execute("SELECT COUNT(*) FROM messages") as cursor:
        assert (await cursor.fetchone())[0] == 0
    await manager.close()


def test_offline_migrator_accepts_public_harness_manifest_without_adapter(tmp_path):
    path = tmp_path / "memory.db"
    hashes = _create_v3(path)
    identity = AgentIdentity("deployment-a", "house-a", "actor-a", "target-session")
    harness_map = HarnessLegacyIdentityMap.from_bindings(
        (HarnessLegacyIdentityBinding("legacy-user", "legacy-session", identity),)
    )
    turn = CommittedTurn(
        "official-turn",
        identity,
        "My pet is Max",
        "I will remember Max",
        MemoryScopeRef.personal("actor-a"),
        None,
        time.time(),
    )
    canonical = turn.canonical_payload()
    assistant_hash = _hash("official-assistant", "assistant", "I will remember Max")

    def official_entry(
        source: str,
        payload_hash: str,
        disposition: LegacyDisposition,
        *,
        keep: bool = False,
    ) -> MigrationManifestEntry:
        return MigrationManifestEntry(
            source,
            f"legacy-source:{source}",
            disposition,
            payload_hash,
            "run-a",
            "official-turn" if keep else None,
            "terminal-event" if keep else None,
            None,
            1 if keep else None,
            canonical if keep else None,
            turn.payload_hash if keep else None,
        )

    entries = (
        official_entry(
            "tentative-user",
            hashes["tentative-user"],
            LegacyDisposition.SUPPRESS_TENTATIVE,
        ),
        official_entry(
            "keep-user",
            hashes["keep-user"],
            LegacyDisposition.KEEP_COMPLETED_PAIR,
            keep=True,
        ),
        official_entry(
            "official-assistant",
            assistant_hash,
            LegacyDisposition.KEEP_COMPLETED_PAIR,
            keep=True,
        ),
        official_entry(
            "terminal-failed",
            hashes["terminal-failed"],
            LegacyDisposition.SUPPRESS_TERMINAL,
        ),
        official_entry("deferred-user", hashes["deferred-user"], LegacyDisposition.DEFERRED_TURN),
    )
    manifest = ExecutionMigrationManifest(
        harness_map.digest,
        3,
        4,
        "a" * 64,
        entries,
    )
    provenance = NonHarnessProvenanceManifest.create(
        (NonHarnessProvenanceEntry("standalone", hashes["standalone"]),)
    )
    receipt = migrate_v3_to_v4(
        path,
        execution_manifest=manifest,
        provenance_manifest=provenance,
        identity_map=harness_map,
    )
    assert receipt.execution_manifest_digest == manifest.digest
    connection = sqlite3.connect(path)
    assert {row[0] for row in connection.execute("SELECT source_event_id FROM messages")} == {
        "keep-user",
        "official-assistant",
        "standalone",
    }
    connection.close()

    keep_manifest = ExecutionMigrationManifest(
        harness_map.digest,
        3,
        4,
        "a" * 64,
        tuple(
            entry for entry in entries if entry.disposition is LegacyDisposition.KEEP_COMPLETED_PAIR
        ),
    )

    async def exercise_runtime_import() -> None:
        manager = await MemoryManager.build(db_path=str(tmp_path / "runtime-official.db"))
        first = await import_execution_manifest(manager, keep_manifest, harness_map)
        replay = await import_execution_manifest(manager, keep_manifest, harness_map)
        assert (first.applied_pairs, replay.replayed_pairs) == (1, 1)
        status, receipt_id = await manager.backend.agent_record_turn(
            principal=MemoryPrincipal("deployment-a", "house-a", "actor-a", "target-session"),
            scope=MemoryScope.personal("actor-a"),
            turn_id="official-turn",
            payload_hash=turn.payload_hash,
            user_text="My pet is Max",
            assistant_text="I will remember Max",
            write_fence=None,
            turn_started_at=time.time(),
        )
        assert (status, receipt_id) == (
            "already_applied",
            "memory-turn/v1/official-turn",
        )
        async with manager.backend._conn.execute("SELECT COUNT(*) FROM messages") as cursor:
            assert (await cursor.fetchone())[0] == 2
        await manager.close()

    asyncio.run(exercise_runtime_import())
