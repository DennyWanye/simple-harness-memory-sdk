"""Explicit public import API, intentionally outside ``AgentMemoryPort``."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.conversation import canonical_message_payload_hash
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryMigrationError,
    MemoryMigrationManifestError,
)
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.migrations.contracts import (
    MigrationDecision,
    NormalizedExecutionEntry,
    normalize_execution_manifest,
    normalize_identity_map,
)


@dataclass(frozen=True, slots=True)
class ManifestImportReceipt:
    protocol: str
    manifest_digest: str
    applied_pairs: int
    replayed_pairs: int


async def import_execution_manifest(
    manager: object,
    execution_manifest: object,
    identity_map: object,
) -> ManifestImportReceipt:
    """Import payload-complete KEEP pairs into an initialized v4 SQLite manager.

    Runtime import deliberately rejects all suppression/deferred dispositions;
    only the backup-first offline migrator is allowed to materialize their
    hash-only receipts.
    """

    normalized = normalize_execution_manifest(execution_manifest)
    bindings, identity_map_digest = normalize_identity_map(identity_map)
    if (
        normalized.identity_map_digest is not None
        and normalized.identity_map_digest != identity_map_digest
    ):
        raise MemoryMigrationManifestError()
    if any(
        entry.decision is not MigrationDecision.KEEP_COMPLETED_PAIR for entry in normalized.entries
    ):
        raise MemoryMigrationManifestError()
    backend = getattr(manager, "backend", None)
    if not isinstance(backend, SQLiteMemoryBackend):
        raise MemoryMigrationError("memory_migration_sqlite_required")
    groups: dict[str, list[NormalizedExecutionEntry]] = {}
    for entry in normalized.entries:
        if entry.turn_id is None:
            raise MemoryMigrationManifestError()
        groups.setdefault(entry.turn_id, []).append(entry)
    applied = 0
    replayed = 0
    async with backend._transaction():
        for turn_id, entries in sorted(groups.items()):
            entries = _materialize_pair(entries, bindings)
            if len(entries) != 2 or {entry.role for entry in entries} != {"user", "assistant"}:
                raise MemoryMigrationManifestError()
            if any(
                None
                in (
                    entry.memory_text,
                    entry.legacy_user_id,
                    entry.legacy_session_id,
                )
                for entry in entries
            ):
                raise MemoryMigrationManifestError()
            identities = {
                (str(entry.legacy_user_id), str(entry.legacy_session_id)) for entry in entries
            }
            if len(identities) != 1:
                raise MemoryMigrationManifestError()
            binding = bindings.get(next(iter(identities)))
            if binding is None:
                raise MemoryMigrationManifestError()
            for entry in entries:
                computed = canonical_message_payload_hash(
                    source_event_id=entry.source_event_id,
                    user_id=str(entry.legacy_user_id),
                    session_id=str(entry.legacy_session_id),
                    role=str(entry.role),
                    memory_text=str(entry.memory_text),
                )
                if computed != entry.payload_hash:
                    raise MemoryMigrationManifestError()
            principal = binding.principal
            scope = MemoryScope.personal(principal.actor_id)
            user_id = await backend._bind_agent_session(principal)
            _epoch, erased_at = await backend._scope_epoch(principal, scope)
            if erased_at is not None:
                raise MemoryMigrationError("memory_migration_erased_scope")
            canonical_hashes = {
                entry.canonical_turn_hash
                for entry in entries
                if entry.canonical_turn_hash is not None
            }
            if len(canonical_hashes) > 1:
                raise MemoryMigrationManifestError()
            pair_hash = (
                next(iter(canonical_hashes))
                if canonical_hashes
                else hashlib.sha256(
                    "\x1f".join(sorted(entry.payload_hash for entry in entries)).encode()
                ).hexdigest()
            )
            async with backend._conn.execute(
                "SELECT payload_hash, deployment_id, household_id, actor_id, session_id, "
                "scope_kind, scope_owner, status, receipt_id "
                "FROM turn_receipts WHERE turn_id = ?",
                (turn_id,),
            ) as cursor:
                prior = await cursor.fetchone()
            existing: list[str] = []
            for entry in entries:
                async with backend._conn.execute(
                    "SELECT source_event_id, payload_hash, deployment_id, household_id, actor_id, "
                    "session_id, scope_kind, scope_owner, role, content "
                    "FROM messages WHERE source_event_id = ?",
                    (entry.source_event_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is not None:
                    if tuple(row[1:]) != (
                        entry.payload_hash,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        principal.session_id,
                        "personal",
                        principal.actor_id,
                        entry.role,
                        entry.memory_text,
                    ):
                        raise MemoryIdempotencyConflict()
                    existing.append(str(row[0]))
            if existing:
                if prior is None or tuple(prior) != (
                    pair_hash,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                    "personal",
                    principal.actor_id,
                    "applied",
                    f"memory-turn/v1/{turn_id}",
                ) or len(existing) != 2:
                    raise MemoryIdempotencyConflict()
                replayed += 1
                continue
            if prior is not None:
                raise MemoryIdempotencyConflict()
            now = time.time()
            for entry in sorted(entries, key=lambda item: 0 if item.role == "user" else 1):
                await backend._conn.execute(
                    "INSERT INTO messages "
                    "(user_id, deployment_id, household_id, actor_id, scope_kind, scope_owner, "
                    "session_id, role, content, created_at, source_event_id, payload_hash) "
                    "VALUES (?, ?, ?, ?, 'personal', ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        principal.deployment_id,
                        principal.household_id,
                        principal.actor_id,
                        principal.actor_id,
                        principal.session_id,
                        entry.role,
                        entry.memory_text,
                        now,
                        entry.source_event_id,
                        entry.payload_hash,
                    ),
                )
            await backend._conn.execute(
                "INSERT INTO turn_receipts "
                "(turn_id, deployment_id, household_id, actor_id, session_id, scope_kind, "
                "scope_owner, payload_hash, status, receipt_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'personal', ?, ?, 'applied', ?, ?)",
                (
                    turn_id,
                    principal.deployment_id,
                    principal.household_id,
                    principal.actor_id,
                    principal.session_id,
                    principal.actor_id,
                    pair_hash,
                    f"memory-turn/v1/{turn_id}",
                    now,
                ),
            )
            applied += 1
    return ManifestImportReceipt(
        "simple-harness-memory/execution-manifest-import/v1",
        normalized.digest,
        applied,
        replayed,
    )


def _materialize_pair(
    entries: list[NormalizedExecutionEntry],
    bindings: Mapping[tuple[str, str], object],
) -> list[NormalizedExecutionEntry]:
    if all(
        entry.role is not None
        and entry.memory_text is not None
        and entry.legacy_user_id is not None
        and entry.legacy_session_id is not None
        for entry in entries
    ):
        return entries
    canonical_values = [
        entry.canonical_turn for entry in entries if entry.canonical_turn is not None
    ]
    if (
        len(entries) != 2
        or not canonical_values
        or any(value != canonical_values[0] for value in canonical_values)
    ):
        raise MemoryMigrationManifestError()
    canonical = canonical_values[0]
    identity = canonical.get("identity")
    if not isinstance(identity, dict):
        raise MemoryMigrationManifestError()
    matching = [
        (legacy, binding)
        for legacy, binding in bindings.items()
        if getattr(binding, "deployment_id") == identity.get("deployment_id")
        and getattr(binding, "household_id") == identity.get("household_id")
        and getattr(binding, "actor_id") == identity.get("actor_id")
        and getattr(binding, "session_id") == identity.get("session_id")
    ]
    if len(matching) != 1:
        raise MemoryMigrationManifestError()
    (legacy_user, legacy_session), _binding = matching[0]
    result: list[NormalizedExecutionEntry] = []
    assigned_roles: set[str] = set()
    for entry in entries:
        candidates: list[tuple[str, str]] = []
        for role, key in (("user", "user_text"), ("assistant", "assistant_text")):
            text = canonical.get(key)
            if not isinstance(text, str):
                raise MemoryMigrationManifestError()
            candidate_hash = canonical_message_payload_hash(
                source_event_id=entry.source_event_id,
                user_id=legacy_user,
                session_id=legacy_session,
                role=role,
                memory_text=text,
            )
            if candidate_hash == entry.payload_hash:
                candidates.append((role, text))
        if len(candidates) != 1 or candidates[0][0] in assigned_roles:
            raise MemoryMigrationManifestError()
        role, text = candidates[0]
        assigned_roles.add(role)
        result.append(
            replace(
                entry,
                role=role,
                memory_text=text,
                legacy_user_id=legacy_user,
                legacy_session_id=legacy_session,
            )
        )
    return result


__all__ = ("ManifestImportReceipt", "import_execution_manifest")
