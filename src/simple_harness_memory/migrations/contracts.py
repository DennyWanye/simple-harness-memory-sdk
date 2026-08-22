"""Public, Harness-independent values for explicit offline memory migration."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from simple_harness_memory.core.conversation import validate_digest, validate_identity
from simple_harness_memory.core.errors import MemoryMigrationManifestError
from simple_harness_memory.core.identity import MemoryPrincipal

IDENTITY_MAP_PROTOCOL = "simple-harness/legacy-identity-map/v1"
PROVENANCE_MANIFEST_PROTOCOL = "simple-harness-memory/non-harness-provenance/v1"
EXECUTION_MANIFEST_PROTOCOL = "simple-harness/execution-migration-manifest/v1"


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class MigrationDecision(StrEnum):
    KEEP_COMPLETED_PAIR = "KEEP_COMPLETED_PAIR"
    SUPPRESS_TENTATIVE = "SUPPRESS_TENTATIVE"
    SUPPRESS_TERMINAL = "SUPPRESS_TERMINAL"
    DEFERRED_TURN = "DEFERRED_TURN"


@dataclass(frozen=True, slots=True)
class LegacyIdentityBinding:
    legacy_user_id: str
    legacy_session_id: str
    deployment_id: str
    household_id: str
    actor_id: str
    session_id: str

    def __post_init__(self) -> None:
        for name in (
            "legacy_user_id",
            "legacy_session_id",
            "deployment_id",
            "household_id",
            "actor_id",
            "session_id",
        ):
            validate_identity(getattr(self, name), name)

    @property
    def principal(self) -> MemoryPrincipal:
        return MemoryPrincipal(
            self.deployment_id,
            self.household_id,
            self.actor_id,
            self.session_id,
        )


@dataclass(frozen=True, slots=True)
class LegacyIdentityMap:
    protocol: str
    bindings: tuple[LegacyIdentityBinding, ...]
    digest: str

    @classmethod
    def create(cls, bindings: tuple[LegacyIdentityBinding, ...]) -> LegacyIdentityMap:
        if not bindings:
            raise ValueError("legacy identity map must not be empty")
        payload = {
            "protocol": IDENTITY_MAP_PROTOCOL,
            "bindings": [
                _identity_binding_payload(item)
                for item in sorted(bindings, key=_identity_binding_sort_key)
            ],
        }
        return cls(IDENTITY_MAP_PROTOCOL, bindings, _digest(payload))

    def verified(self) -> dict[tuple[str, str], LegacyIdentityBinding]:
        if self.protocol != IDENTITY_MAP_PROTOCOL:
            raise MemoryMigrationManifestError()
        validate_digest(self.digest, "identity_map.digest")
        payload = {
            "protocol": self.protocol,
            "bindings": [
                _identity_binding_payload(item)
                for item in sorted(self.bindings, key=_identity_binding_sort_key)
            ],
        }
        if not hmac.compare_digest(self.digest, _digest(payload)):
            raise MemoryMigrationManifestError()
        by_legacy: dict[tuple[str, str], LegacyIdentityBinding] = {}
        target_sessions: set[tuple[str, str]] = set()
        for binding in self.bindings:
            key = _binding_key(binding)
            target_session = (binding.deployment_id, binding.session_id)
            if key in by_legacy or target_session in target_sessions:
                raise MemoryMigrationManifestError()
            by_legacy[key] = binding
            target_sessions.add(target_session)
        return by_legacy


def normalize_identity_map(
    identity_map: object,
) -> tuple[dict[tuple[str, str], LegacyIdentityBinding], str]:
    """Accept the local value or the structurally equivalent public Harness value."""

    if isinstance(identity_map, LegacyIdentityMap):
        return identity_map.verified(), identity_map.digest
    raw_bindings = _field(identity_map, "bindings")
    digest = validate_digest(_field(identity_map, "digest"), "identity_map.digest")
    if not isinstance(raw_bindings, (tuple, list)) or not raw_bindings:
        raise MemoryMigrationManifestError()
    converted: list[LegacyIdentityBinding] = []
    for item in raw_bindings:
        identity = _field(item, "identity")
        converted.append(
            LegacyIdentityBinding(
                str(_field(item, "user_id", "legacy_user_id")),
                str(_field(item, "session_id", "legacy_session_id")),
                str(_field(identity, "deployment_id")),
                str(_field(identity, "household_id")),
                str(_field(identity, "actor_id")),
                str(_field(identity, "session_id")),
            )
        )
    local = LegacyIdentityMap.create(tuple(converted))
    if not hmac.compare_digest(digest, local.digest):
        raise MemoryMigrationManifestError()
    return local.verified(), digest


def _binding_key(binding: LegacyIdentityBinding) -> tuple[str, str]:
    return binding.legacy_user_id, binding.legacy_session_id


def _identity_binding_sort_key(binding: LegacyIdentityBinding) -> tuple[str, str]:
    return binding.legacy_session_id, binding.legacy_user_id


def _identity_binding_payload(binding: LegacyIdentityBinding) -> dict[str, object]:
    return {
        "user_id": binding.legacy_user_id,
        "session_id": binding.legacy_session_id,
        "identity": {
            "deployment_id": binding.deployment_id,
            "household_id": binding.household_id,
            "actor_id": binding.actor_id,
            "session_id": binding.session_id,
        },
    }


@dataclass(frozen=True, slots=True)
class NonHarnessProvenanceEntry:
    source_event_id: str
    payload_hash: str

    def __post_init__(self) -> None:
        validate_identity(self.source_event_id, "source_event_id")
        validate_digest(self.payload_hash, "payload_hash")


@dataclass(frozen=True, slots=True)
class NonHarnessProvenanceManifest:
    protocol: str
    entries: tuple[NonHarnessProvenanceEntry, ...]
    digest: str

    @classmethod
    def create(cls, entries: tuple[NonHarnessProvenanceEntry, ...]) -> NonHarnessProvenanceManifest:
        payload = {
            "protocol": PROVENANCE_MANIFEST_PROTOCOL,
            "entries": [
                asdict(item) for item in sorted(entries, key=lambda item: item.source_event_id)
            ],
        }
        return cls(PROVENANCE_MANIFEST_PROTOCOL, entries, _digest(payload))

    def verified(self) -> dict[str, NonHarnessProvenanceEntry]:
        if self.protocol != PROVENANCE_MANIFEST_PROTOCOL:
            raise MemoryMigrationManifestError()
        validate_digest(self.digest, "provenance_manifest.digest")
        payload = {
            "protocol": self.protocol,
            "entries": [
                asdict(item) for item in sorted(self.entries, key=lambda item: item.source_event_id)
            ],
        }
        if not hmac.compare_digest(self.digest, _digest(payload)):
            raise MemoryMigrationManifestError()
        by_source: dict[str, NonHarnessProvenanceEntry] = {}
        for entry in self.entries:
            if entry.source_event_id in by_source:
                raise MemoryMigrationManifestError()
            by_source[entry.source_event_id] = entry
        return by_source


@dataclass(frozen=True, slots=True)
class NormalizedExecutionEntry:
    source_event_id: str
    payload_hash: str
    decision: MigrationDecision
    turn_id: str | None
    role: str | None
    memory_text: str | None
    legacy_user_id: str | None
    legacy_session_id: str | None
    source_key: str | None = None
    canonical_turn: Mapping[str, Any] | None = None
    canonical_turn_hash: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedExecutionManifest:
    protocol: str
    entries: tuple[NormalizedExecutionEntry, ...]
    digest: str
    identity_map_digest: str | None = None
    source_schema: int = 3
    target_schema: int = 4


def normalize_execution_manifest(manifest: object) -> NormalizedExecutionManifest:
    """Validate the public Harness manifest structurally without importing Harness."""

    raw_manifest: object = manifest
    serializer = getattr(manifest, "to_json", None)
    if callable(serializer):
        try:
            serialized = serializer()
        except Exception as exc:
            raise MemoryMigrationManifestError() from exc
        if not isinstance(serialized, Mapping):
            raise MemoryMigrationManifestError()
        raw_manifest = serialized
        supplied_digest = str(_field(raw_manifest, "digest", "manifest_hash"))
        payload = {key: value for key, value in raw_manifest.items() if key != "digest"}
        if not hmac.compare_digest(supplied_digest, _digest(payload)):
            raise MemoryMigrationManifestError()
    protocol = str(_field(raw_manifest, "protocol"))
    if protocol != EXECUTION_MANIFEST_PROTOCOL:
        raise MemoryMigrationManifestError()
    raw_entries = _field(raw_manifest, "entries")
    if not isinstance(raw_entries, (tuple, list)):
        raise MemoryMigrationManifestError()
    entries = tuple(_normalize_execution_entry(item) for item in raw_entries)
    if len({item.source_event_id for item in entries}) != len(entries):
        raise MemoryMigrationManifestError()
    digest = str(_field(raw_manifest, "digest", "manifest_hash"))
    validate_digest(digest, "execution_manifest.digest")
    payload = {
        "protocol": protocol,
        "entries": [
            _execution_entry_payload(item)
            for item in sorted(entries, key=lambda item: item.source_event_id)
        ],
    }
    verifier = getattr(manifest, "verify_integrity", None)
    if callable(verifier):
        try:
            verified = verifier()
        except Exception as exc:
            raise MemoryMigrationManifestError() from exc
        if verified is False:
            raise MemoryMigrationManifestError()
    elif not callable(serializer) and not hmac.compare_digest(digest, _digest(payload)):
        raise MemoryMigrationManifestError()
    source_schema = int(_optional_field(raw_manifest, "source_schema") or 3)
    target_schema = int(_optional_field(raw_manifest, "target_schema") or 4)
    if source_schema != 3 or target_schema != 4:
        raise MemoryMigrationManifestError()
    identity_digest_value = _optional_field(raw_manifest, "identity_map_digest")
    identity_digest = None if identity_digest_value is None else str(identity_digest_value)
    if identity_digest is not None:
        validate_digest(identity_digest, "execution_manifest.identity_map_digest")
    return NormalizedExecutionManifest(
        protocol,
        entries,
        digest,
        identity_digest,
        source_schema,
        target_schema,
    )


def execution_manifest_digest(entries: tuple[NormalizedExecutionEntry, ...]) -> str:
    """Canonical digest helper for non-Harness fixtures and offline coordinators."""

    payload = {
        "protocol": EXECUTION_MANIFEST_PROTOCOL,
        "entries": [
            _execution_entry_payload(item)
            for item in sorted(entries, key=lambda item: item.source_event_id)
        ],
    }
    return _digest(payload)


def _normalize_execution_entry(value: object) -> NormalizedExecutionEntry:
    payload = _optional_field(value, "payload")
    source_event_id = validate_identity(_field(value, "source_event_id"), "source_event_id")
    payload_hash = validate_digest(_field(value, "payload_hash"), "payload_hash")
    try:
        raw_decision = str(_field(value, "decision", "disposition"))
        decision = (
            MigrationDecision[raw_decision.upper()]
            if raw_decision.upper() in MigrationDecision.__members__
            else MigrationDecision(raw_decision)
        )
    except (ValueError, MemoryMigrationManifestError) as exc:
        raise MemoryMigrationManifestError() from exc

    def optional(*names: str) -> Any | None:
        direct = _optional_field(value, *names)
        if direct is not None:
            return direct
        if payload is not None:
            return _optional_field(payload, *names)
        return None

    turn = optional("turn_id", "pair_id", "run_id")
    role = optional("role")
    text = optional("memory_text", "content", "text")
    legacy_user = optional("legacy_user_id", "user_id")
    legacy_session = optional("legacy_session_id", "session_id")
    canonical_turn_value = optional("canonical_turn")
    canonical_turn = (
        dict(canonical_turn_value) if isinstance(canonical_turn_value, Mapping) else None
    )
    canonical_turn_hash_value = optional("canonical_turn_hash")
    canonical_turn_hash = (
        None if canonical_turn_hash_value is None else str(canonical_turn_hash_value)
    )
    if canonical_turn_hash is not None:
        validate_digest(canonical_turn_hash, "canonical_turn_hash")
        if canonical_turn is None or not hmac.compare_digest(
            canonical_turn_hash, _digest(canonical_turn)
        ):
            raise MemoryMigrationManifestError()
    source_key_value = optional("source_key")
    source_key = None if source_key_value is None else str(source_key_value)
    if source_key is not None and source_key != f"legacy-source:{source_event_id}":
        raise MemoryMigrationManifestError()
    return NormalizedExecutionEntry(
        source_event_id,
        payload_hash,
        decision,
        None if turn is None else str(turn),
        None if role is None else str(getattr(role, "value", role)),
        None if text is None else str(text),
        None if legacy_user is None else str(legacy_user),
        None if legacy_session is None else str(legacy_session),
        source_key,
        canonical_turn,
        canonical_turn_hash,
    )


def _execution_entry_payload(entry: NormalizedExecutionEntry) -> dict[str, object]:
    return {
        "source_event_id": entry.source_event_id,
        "payload_hash": entry.payload_hash,
        "decision": entry.decision.value,
        "turn_id": entry.turn_id,
        "role": entry.role,
        "memory_text": entry.memory_text,
        "legacy_user_id": entry.legacy_user_id,
        "legacy_session_id": entry.legacy_session_id,
        "source_key": entry.source_key,
        "canonical_turn": entry.canonical_turn,
        "canonical_turn_hash": entry.canonical_turn_hash,
    }


def _field(value: object, *names: str) -> Any:
    result = _optional_field(value, *names)
    if result is None:
        raise MemoryMigrationManifestError()
    return result


def _optional_field(value: object, *names: str) -> Any | None:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


__all__ = (
    "EXECUTION_MANIFEST_PROTOCOL",
    "IDENTITY_MAP_PROTOCOL",
    "LegacyIdentityBinding",
    "LegacyIdentityMap",
    "MigrationDecision",
    "NonHarnessProvenanceEntry",
    "NonHarnessProvenanceManifest",
    "NormalizedExecutionEntry",
    "PROVENANCE_MANIFEST_PROTOCOL",
    "execution_manifest_digest",
)
