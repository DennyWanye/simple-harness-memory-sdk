"""Backup-first, identity-bound, offline migration from Memory schema v3 to v4."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from simple_harness_memory.backends.sqlite import create_fresh_v4_sync
from simple_harness_memory.backends.storage import path_digest, verify_sqlite_path
from simple_harness_memory.cognitive.twin_builder import build_twin_from_facts
from simple_harness_memory.core.conversation import canonical_message_payload_hash
from simple_harness_memory.core.errors import (
    MemoryMigrationError,
    MemoryMigrationManifestError,
    MemoryMigrationSourceBusy,
)
from simple_harness_memory.core.models import Fact
from simple_harness_memory.migrations.contracts import (
    LegacyIdentityBinding,
    MigrationDecision,
    NonHarnessProvenanceManifest,
    NormalizedExecutionEntry,
    normalize_execution_manifest,
    normalize_identity_map,
)

logger = structlog.get_logger("simple_harness_memory.migrations.v3_to_v4")

LEGACY_SCHEMA_VERSION = "3"
LEGACY_SCHEMA_CHECKSUM = "fbe1ca178f2d545531cb82c5326be23d6680845478848438e94e45ec8fd8b212"
MIGRATION_RECEIPT_PROTOCOL = "simple-harness-memory/v3-to-v4-receipt/v1"


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    protocol: str
    execution_manifest_digest: str
    provenance_manifest_digest: str
    identity_map_digest: str
    backup_sha256: str
    migrated_sha256: str
    kept_messages: int
    kept_facts: int
    suppressed_sources: int
    completed_pairs: int

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                dataclasses.asdict(self),
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def to_json(self) -> dict[str, object]:
        return {**dataclasses.asdict(self), "digest": self.digest}


@dataclass(frozen=True, slots=True)
class _ResolvedMessage:
    source_event_id: str
    payload_hash: str
    legacy_user_id: str
    legacy_session_id: str
    role: str
    content: str
    created_at: float
    salience: float
    decay_rate: float
    last_recalled: float | None
    last_decay_at: float | None
    embedding: bytes | None
    is_summary: int
    summary_of: str | None
    embedder_kind: str | None
    embedding_dim: int | None
    embedding_format_version: int | None
    old_message_id: int | None


def migrate_v3_to_v4(
    source_path: str | os.PathLike[str],
    *,
    execution_manifest: object,
    provenance_manifest: NonHarnessProvenanceManifest,
    identity_map: object,
    backup_path: str | os.PathLike[str] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> MigrationReceipt:
    """Migrate a closed v3 database through a verified temporary v4 database.

    The source is never edited in place. A consistent SQLite backup is created
    first, the new database is validated independently, and only then atomically
    replaces the source. Any injected or real failure after replacement restores
    the verified backup before returning an error.
    """

    source = Path(source_path).resolve()
    if not source.is_file() or source.is_symlink():
        raise MemoryMigrationError()
    verify_sqlite_path(source)
    backup = (
        Path(backup_path).resolve()
        if backup_path is not None
        else source.with_name(source.name + ".v3.backup.db")
    )
    if backup.exists() or not backup.parent.is_dir():
        raise MemoryMigrationError("memory_migration_backup_unavailable")
    temporary = source.with_name(f".{source.name}.v4.{uuid.uuid4().hex}.tmp")
    restore_temp = source.with_name(f".{source.name}.restore.{uuid.uuid4().hex}.tmp")
    normalized = normalize_execution_manifest(execution_manifest)
    bindings, identity_map_digest = normalize_identity_map(identity_map)
    if (
        normalized.identity_map_digest is not None
        and normalized.identity_map_digest != identity_map_digest
    ):
        raise MemoryMigrationManifestError()
    provenance = provenance_manifest.verified()
    swapped = False
    started = time.monotonic()
    try:
        _fault(fault_injector, "before_backup")
        _create_verified_backup(source, backup)
        backup_sha = _file_sha256(backup)
        _fault(fault_injector, "after_backup")
        counts = _build_v4(
            backup,
            temporary,
            normalized.entries,
            provenance,
            bindings,
        )
        migrated_sha = _file_sha256(temporary)
        _fault(fault_injector, "after_temp_validated")
        _fault(fault_injector, "before_swap")
        os.replace(temporary, source)
        os.chmod(source, 0o600)
        swapped = True
        _fault(fault_injector, "after_swap")
        receipt = MigrationReceipt(
            MIGRATION_RECEIPT_PROTOCOL,
            normalized.digest,
            provenance_manifest.digest,
            identity_map_digest,
            backup_sha,
            migrated_sha,
            counts["messages"],
            counts["facts"],
            counts["suppressed"],
            counts["pairs"],
        )
        logger.info(
            "memory.migration_completed",
            source_path_hash=path_digest(source),
            migrated_sha256=migrated_sha,
            kept_messages=receipt.kept_messages,
            kept_facts=receipt.kept_facts,
            suppressed_sources=receipt.suppressed_sources,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return receipt
    except Exception as exc:
        if swapped:
            try:
                _copy_sqlite(backup, restore_temp)
                os.replace(restore_temp, source)
                os.chmod(source, 0o600)
            except Exception as restore_exc:
                raise MemoryMigrationError("memory_migration_restore_failed") from restore_exc
        if isinstance(exc, MemoryMigrationError):
            raise
        raise MemoryMigrationError() from exc
    finally:
        temporary.unlink(missing_ok=True)
        restore_temp.unlink(missing_ok=True)
        for candidate in (temporary, restore_temp):
            candidate.with_name(candidate.name + "-wal").unlink(missing_ok=True)
            candidate.with_name(candidate.name + "-shm").unlink(missing_ok=True)


def _create_verified_backup(source: Path, backup: Path) -> None:
    staging = backup.with_name(f".{backup.name}.{uuid.uuid4().hex}.tmp")
    try:
        _create_owner_only_file(staging)
        connection = sqlite3.connect(source, timeout=0, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError as exc:
                raise MemoryMigrationSourceBusy() from exc
            _validate_v3(connection)
            destination = sqlite3.connect(staging)
            try:
                connection.backup(destination)
            finally:
                destination.close()
        finally:
            connection.close()
        os.chmod(staging, 0o600)
        verify_sqlite_path(staging)
        verified = sqlite3.connect(f"file:{staging}?mode=ro", uri=True)
        try:
            _validate_v3(verified)
        finally:
            verified.close()
        os.replace(staging, backup)
    finally:
        staging.unlink(missing_ok=True)


def _validate_v3(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise MemoryMigrationError("memory_migration_source_corrupt")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MemoryMigrationError("memory_migration_source_fk_invalid")
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    required = {"users", "sessions", "messages", "facts", "schema_meta"}
    if not required.issubset(tables):
        raise MemoryMigrationError("memory_migration_source_schema_invalid")
    meta = dict(connection.execute("SELECT key, value FROM schema_meta"))
    if meta.get("schema_version") != LEGACY_SCHEMA_VERSION:
        raise MemoryMigrationError("memory_migration_source_schema_invalid")
    if meta.get("schema_checksum") != LEGACY_SCHEMA_CHECKSUM:
        raise MemoryMigrationError("memory_migration_source_schema_invalid")
    expected_columns = {
        "messages": {"source_event_id", "payload_hash", "embedding", "session_id", "role"},
        "facts": {"source_msg_id", "superseded_by", "forgotten_at"},
    }
    for table, expected in expected_columns.items():
        actual = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        if not expected.issubset(actual):
            raise MemoryMigrationError("memory_migration_source_schema_invalid")


def _build_v4(
    backup: Path,
    temporary: Path,
    execution_entries: tuple[NormalizedExecutionEntry, ...],
    provenance: dict[str, Any],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> dict[str, int]:
    _create_owner_only_file(temporary)
    source = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(temporary)
    target.row_factory = sqlite3.Row
    try:
        target.execute("PRAGMA foreign_keys = ON")
        create_fresh_v4_sync(target)
        target.commit()
        target.execute("BEGIN IMMEDIATE")
        rows = {
            str(row["source_event_id"]): row
            for row in source.execute("SELECT * FROM messages ORDER BY id")
        }
        execution = {entry.source_event_id: entry for entry in execution_entries}
        _validate_coverage(rows, execution, provenance, bindings)
        kept: list[tuple[_ResolvedMessage, LegacyIdentityBinding, str | None]] = []
        suppressed = 0
        pair_entries: dict[tuple[str, str], list[NormalizedExecutionEntry]] = {}
        for entry in execution_entries:
            if entry.decision is MigrationDecision.KEEP_COMPLETED_PAIR:
                if entry.turn_id is None:
                    raise MemoryMigrationManifestError()
                deployment_id = _entry_target_deployment(entry, rows, bindings)
                pair_entries.setdefault((deployment_id, entry.turn_id), []).append(entry)
            else:
                target.execute(
                    "INSERT INTO suppression_receipts "
                    "(source_event_id, payload_hash, decision, created_at) VALUES (?, ?, ?, ?)",
                    (
                        f"legacy-source:{entry.source_event_id}",
                        entry.payload_hash,
                        entry.decision.value,
                        time.time(),
                    ),
                )
                suppressed += 1
        pairs: dict[
            tuple[str, str], list[tuple[_ResolvedMessage, LegacyIdentityBinding]]
        ] = {}
        for pair_key, entries in sorted(pair_entries.items()):
            deployment_id, turn_id = pair_key
            pair = _resolve_execution_pair(entries, rows, bindings)
            roles = {message.role for message, _binding in pair}
            if len(pair) != 2 or roles != {"user", "assistant"}:
                raise MemoryMigrationManifestError()
            principals = {binding.principal for _message, binding in pair}
            if len(principals) != 1 or pair[0][1].deployment_id != deployment_id:
                raise MemoryMigrationManifestError()
            for message, binding in pair:
                kept.append((message, binding, turn_id))
            pairs[pair_key] = pair
        for source_id in sorted(provenance):
            row = rows[source_id]
            binding = bindings[(str(row["user_id"]), str(row["session_id"]))]
            kept.append((_resolved_from_row(row), binding, None))
        message_map: dict[int, int] = {}
        inserted_sources: set[str] = set()
        for message, binding, _turn_id in sorted(kept, key=lambda item: item[0].source_event_id):
            if message.source_event_id in inserted_sources:
                raise MemoryMigrationManifestError()
            inserted_sources.add(message.source_event_id)
            new_id = _insert_message(target, message, binding)
            if message.old_message_id is not None:
                message_map[message.old_message_id] = new_id
        for pair_key, pair in sorted(pairs.items()):
            _deployment_id, turn_id = pair_key
            binding = pair[0][1]
            hashes = sorted(message.payload_hash for message, _binding in pair)
            manifest_pair = pair_entries[pair_key]
            canonical_hashes = {
                entry.canonical_turn_hash
                for entry in manifest_pair
                if entry.canonical_turn_hash is not None
            }
            if len(canonical_hashes) > 1:
                raise MemoryMigrationManifestError()
            pair_hash = (
                next(iter(canonical_hashes))
                if canonical_hashes
                else hashlib.sha256("\x1f".join(hashes).encode()).hexdigest()
            )
            target.execute(
                "INSERT INTO turn_receipts "
                "(turn_id, deployment_id, household_id, actor_id, session_id, scope_kind, "
                "scope_owner, payload_hash, status, receipt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'personal', ?, ?, 'applied', ?, ?)",
                (
                    turn_id,
                    binding.deployment_id,
                    binding.household_id,
                    binding.actor_id,
                    binding.session_id,
                    binding.actor_id,
                    pair_hash,
                    f"memory-turn/v1/{turn_id}",
                    time.time(),
                ),
            )
        fact_count = _copy_facts(source, target, message_map, bindings)
        _rebuild_aggregates(target)
        expected_messages = len(kept)
        actual_messages = int(target.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        if actual_messages != expected_messages:
            raise MemoryMigrationError("memory_migration_count_mismatch")
        if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MemoryMigrationError("memory_migration_target_fk_invalid")
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MemoryMigrationError("memory_migration_target_corrupt")
        target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MemoryMigrationError("memory_migration_target_corrupt")
        return {
            "messages": actual_messages,
            "facts": fact_count,
            "suppressed": suppressed,
            "pairs": len(pairs),
        }
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()


def _validate_coverage(
    rows: dict[str, sqlite3.Row],
    execution: dict[str, NormalizedExecutionEntry],
    provenance: dict[str, Any],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> None:
    for source_id, row in rows.items():
        owners = int(source_id in execution) + int(source_id in provenance)
        if owners != 1:
            raise MemoryMigrationManifestError()
        expected_hash = (
            execution[source_id].payload_hash
            if source_id in execution
            else provenance[source_id].payload_hash
        )
        if not hmac.compare_digest(str(row["payload_hash"]), expected_hash):
            raise MemoryMigrationManifestError()
        identity = (str(row["user_id"]), str(row["session_id"]))
        if identity not in bindings:
            raise MemoryMigrationManifestError()
    if any(source_id not in rows for source_id in provenance):
        raise MemoryMigrationManifestError()


def _resolve_execution_message(
    entry: NormalizedExecutionEntry,
    rows: dict[str, sqlite3.Row],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> tuple[_ResolvedMessage, LegacyIdentityBinding]:
    row = rows.get(entry.source_event_id)
    if row is not None:
        message = _resolved_from_row(row)
    else:
        if None in (
            entry.role,
            entry.memory_text,
            entry.legacy_user_id,
            entry.legacy_session_id,
        ):
            raise MemoryMigrationManifestError()
        assert entry.role is not None
        assert entry.memory_text is not None
        assert entry.legacy_user_id is not None
        assert entry.legacy_session_id is not None
        computed = canonical_message_payload_hash(
            source_event_id=entry.source_event_id,
            user_id=entry.legacy_user_id,
            session_id=entry.legacy_session_id,
            role=entry.role,
            memory_text=entry.memory_text,
        )
        if not hmac.compare_digest(computed, entry.payload_hash):
            raise MemoryMigrationManifestError()
        message = _ResolvedMessage(
            entry.source_event_id,
            entry.payload_hash,
            entry.legacy_user_id,
            entry.legacy_session_id,
            entry.role,
            entry.memory_text,
            time.time(),
            0.0,
            0.02,
            None,
            None,
            None,
            0,
            None,
            None,
            None,
            None,
            None,
        )
    binding = bindings.get((message.legacy_user_id, message.legacy_session_id))
    if binding is None:
        raise MemoryMigrationManifestError()
    return message, binding


def _entry_target_deployment(
    entry: NormalizedExecutionEntry,
    rows: dict[str, sqlite3.Row],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> str:
    row = rows.get(entry.source_event_id)
    if row is not None:
        binding = bindings.get((str(row["user_id"]), str(row["session_id"])))
        if binding is None:
            raise MemoryMigrationManifestError()
        return binding.deployment_id
    if entry.legacy_user_id is not None and entry.legacy_session_id is not None:
        binding = bindings.get((entry.legacy_user_id, entry.legacy_session_id))
        if binding is None:
            raise MemoryMigrationManifestError()
        return binding.deployment_id
    if entry.canonical_turn is not None:
        identity = entry.canonical_turn.get("identity")
        if isinstance(identity, dict) and isinstance(identity.get("deployment_id"), str):
            return str(identity["deployment_id"])
    raise MemoryMigrationManifestError()


def _resolve_execution_pair(
    entries: list[NormalizedExecutionEntry],
    rows: dict[str, sqlite3.Row],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> list[tuple[_ResolvedMessage, LegacyIdentityBinding]]:
    if len(entries) != 2:
        raise MemoryMigrationManifestError()
    resolved: list[tuple[_ResolvedMessage, LegacyIdentityBinding]] = []
    missing: list[NormalizedExecutionEntry] = []
    for entry in entries:
        if entry.source_event_id in rows or all(
            value is not None
            for value in (
                entry.role,
                entry.memory_text,
                entry.legacy_user_id,
                entry.legacy_session_id,
            )
        ):
            resolved.append(_resolve_execution_message(entry, rows, bindings))
        else:
            missing.append(entry)
    if missing:
        if len(missing) != 1 or len(resolved) != 1:
            raise MemoryMigrationManifestError()
        entry = missing[0]
        existing, binding = resolved[0]
        canonical_values = [
            item.canonical_turn for item in entries if item.canonical_turn is not None
        ]
        if not canonical_values or any(value != canonical_values[0] for value in canonical_values):
            raise MemoryMigrationManifestError()
        canonical = canonical_values[0]
        role = "assistant" if existing.role == "user" else "user"
        text_key = "assistant_text" if role == "assistant" else "user_text"
        text = canonical.get(text_key)
        identity = canonical.get("identity")
        if not isinstance(text, str) or not isinstance(identity, dict):
            raise MemoryMigrationManifestError()
        if (
            identity.get("deployment_id") != binding.deployment_id
            or identity.get("household_id") != binding.household_id
            or identity.get("actor_id") != binding.actor_id
            or identity.get("session_id") != binding.session_id
        ):
            raise MemoryMigrationManifestError()
        computed = canonical_message_payload_hash(
            source_event_id=entry.source_event_id,
            user_id=existing.legacy_user_id,
            session_id=existing.legacy_session_id,
            role=role,
            memory_text=text,
        )
        if not hmac.compare_digest(computed, entry.payload_hash):
            raise MemoryMigrationManifestError()
        supplemented = _ResolvedMessage(
            entry.source_event_id,
            entry.payload_hash,
            existing.legacy_user_id,
            existing.legacy_session_id,
            role,
            text,
            existing.created_at,
            0.0,
            0.02,
            None,
            None,
            None,
            0,
            None,
            None,
            None,
            None,
            None,
        )
        resolved.append((supplemented, binding))
    roles = {message.role for message, _binding in resolved}
    if roles != {"user", "assistant"}:
        raise MemoryMigrationManifestError()
    for entry in entries:
        if entry.canonical_turn is None:
            continue
        canonical = entry.canonical_turn
        by_role = {message.role: message for message, _binding in resolved}
        if canonical.get("user_text") != by_role["user"].content:
            raise MemoryMigrationManifestError()
        if canonical.get("assistant_text") != by_role["assistant"].content:
            raise MemoryMigrationManifestError()
    return resolved


def _resolved_from_row(row: sqlite3.Row) -> _ResolvedMessage:
    return _ResolvedMessage(
        str(row["source_event_id"]),
        str(row["payload_hash"]),
        str(row["user_id"]),
        str(row["session_id"]),
        str(row["role"]),
        str(row["content"]),
        float(row["created_at"]),
        float(row["salience"]),
        float(row["decay_rate"]),
        None if row["last_recalled"] is None else float(row["last_recalled"]),
        None if row["last_decay_at"] is None else float(row["last_decay_at"]),
        None if row["embedding"] is None else bytes(row["embedding"]),
        int(row["is_summary"]),
        None if row["summary_of"] is None else str(row["summary_of"]),
        None if row["embedder_kind"] is None else str(row["embedder_kind"]),
        None if row["embedding_dim"] is None else int(row["embedding_dim"]),
        None if row["embedding_format_version"] is None else int(row["embedding_format_version"]),
        int(row["id"]),
    )


def _principal_key(binding: LegacyIdentityBinding) -> str:
    material = "\x1f".join((binding.deployment_id, binding.household_id, binding.actor_id))
    return hashlib.sha256(material.encode()).hexdigest()


def _ensure_target_session(connection: sqlite3.Connection, binding: LegacyIdentityBinding) -> str:
    user_id = _principal_key(binding)
    now = time.time()
    connection.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)", (user_id, now)
    )
    connection.execute(
        "INSERT OR IGNORE INTO sessions "
        "(session_id, user_id, deployment_id, household_id, actor_id, "
        "created_at, last_activity_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            binding.session_id,
            user_id,
            binding.deployment_id,
            binding.household_id,
            binding.actor_id,
            now,
            now,
        ),
    )
    row = connection.execute(
        "SELECT user_id, household_id, actor_id FROM sessions "
        "WHERE deployment_id=? AND session_id=?",
        (binding.deployment_id, binding.session_id),
    ).fetchone()
    if row is None or tuple(row) != (
        user_id,
        binding.household_id,
        binding.actor_id,
    ):
        raise MemoryMigrationManifestError()
    return user_id


def _insert_message(
    connection: sqlite3.Connection,
    message: _ResolvedMessage,
    binding: LegacyIdentityBinding,
) -> int:
    user_id = _ensure_target_session(connection, binding)
    cursor = connection.execute(
        "INSERT INTO messages "
        "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
        "session_id, role, content, created_at, salience, decay_rate, last_recalled, "
        "last_decay_at, embedding, is_summary, summary_of, source_event_id, payload_hash, "
        "embedder_kind, embedding_dim, embedding_format_version) "
        "VALUES (?, ?, ?, ?, 'personal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            binding.deployment_id,
            binding.household_id,
            binding.actor_id,
            binding.actor_id,
            binding.session_id,
            message.role,
            message.content,
            message.created_at,
            message.salience,
            message.decay_rate,
            message.last_recalled,
            message.last_decay_at,
            message.embedding,
            message.is_summary,
            message.summary_of,
            message.source_event_id,
            message.payload_hash,
            message.embedder_kind,
            message.embedding_dim,
            message.embedding_format_version,
        ),
    )
    if cursor.lastrowid is None:
        raise MemoryMigrationError("memory_migration_insert_failed")
    return int(cursor.lastrowid)


def _copy_facts(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    message_map: dict[int, int],
    bindings: dict[tuple[str, str], LegacyIdentityBinding],
) -> int:
    fact_map: dict[int, int] = {}
    copied: list[tuple[int, int, int | None]] = []
    for row in source.execute("SELECT * FROM facts ORDER BY id"):
        old_source = int(row["source_msg_id"])
        if old_source not in message_map:
            continue
        message = source.execute(
            "SELECT user_id, session_id FROM messages WHERE id = ?", (old_source,)
        ).fetchone()
        if message is None:
            raise MemoryMigrationError("memory_migration_source_fk_invalid")
        binding = bindings[(str(message["user_id"]), str(message["session_id"]))]
        user_id = _principal_key(binding)
        deterministic_id = (
            "legacy-fact:"
            + hashlib.sha256(
                f"{int(row['id'])}\x1f{str(row['key'])}\x1f{str(row['value'])}".encode()
            ).hexdigest()
        )
        cursor = target.execute(
            "INSERT INTO facts "
            "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
            "deterministic_id, extractor_lineage, subject, key, value, category, confidence, "
            "evidence, source_msg_id, created_at, decay_rate, pinned, last_decay_at, forgotten_at) "
            "VALUES (?, ?, ?, ?, 'personal', ?, ?, 'legacy-v3', "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                binding.deployment_id,
                binding.household_id,
                binding.actor_id,
                binding.actor_id,
                deterministic_id,
                str(row["subject"]),
                str(row["key"]),
                str(row["value"]),
                str(row["category"]),
                float(row["confidence"]),
                str(row["evidence"]),
                message_map[old_source],
                float(row["created_at"]),
                float(row["decay_rate"]),
                int(row["pinned"]),
                row["last_decay_at"],
                row["forgotten_at"],
            ),
        )
        if cursor.lastrowid is None:
            raise MemoryMigrationError("memory_migration_insert_failed")
        new_id = int(cursor.lastrowid)
        old_id = int(row["id"])
        superseded = None if row["superseded_by"] is None else int(row["superseded_by"])
        fact_map[old_id] = new_id
        copied.append((old_id, new_id, superseded))
    for _old_id, new_id, superseded in copied:
        if superseded is not None and superseded in fact_map:
            target.execute(
                "UPDATE facts SET superseded_by = ? WHERE id = ?",
                (fact_map[superseded], new_id),
            )
    return len(copied)


def _rebuild_aggregates(connection: sqlite3.Connection) -> None:
    user_ids = [str(row[0]) for row in connection.execute("SELECT user_id FROM users")]
    for user_id in user_ids:
        facts: list[Fact] = []
        for row in connection.execute(
            "SELECT * FROM facts WHERE user_id = ? ORDER BY id", (user_id,)
        ):
            fact = Fact(
                id=int(row["id"]),
                user_id=user_id,
                subject=str(row["subject"]),
                key=str(row["key"]),
                value=str(row["value"]),
                category=str(row["category"]),
                confidence=float(row["confidence"]),
                evidence=str(row["evidence"]),
                source_msg_id=int(row["source_msg_id"]),
                created_at=float(row["created_at"]),
                pinned=bool(row["pinned"]),
                last_decay_at=row["last_decay_at"],
                superseded_by=row["superseded_by"],
                forgotten_at=row["forgotten_at"],
            )
            fact.decay_rate = float(row["decay_rate"])
            facts.append(fact)
        if not facts:
            continue
        twin = build_twin_from_facts(facts, base=None, subject="user")
        connection.execute(
            "INSERT INTO digital_twins(user_id, subject, data_json, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (
                user_id,
                "user",
                json.dumps(
                    dataclasses.asdict(twin),
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                time.time(),
            ),
        )


def _copy_sqlite(source_path: Path, destination_path: Path) -> None:
    _create_owner_only_file(destination_path)
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(destination_path, 0o600)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_owner_only_file(path: Path) -> None:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise MemoryMigrationError("memory_migration_path_unavailable") from exc
    os.close(descriptor)


def _fault(injector: Callable[[str], None] | None, phase: str) -> None:
    if injector is not None:
        injector(phase)


__all__ = (
    "LEGACY_SCHEMA_CHECKSUM",
    "LEGACY_SCHEMA_VERSION",
    "MIGRATION_RECEIPT_PROTOCOL",
    "MigrationReceipt",
    "migrate_v3_to_v4",
)
