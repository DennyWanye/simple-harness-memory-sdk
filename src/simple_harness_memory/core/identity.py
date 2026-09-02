"""Standalone identity and privacy values for Memory SDK operations.

These values deliberately do not import :mod:`simple_harness`.  The manager's
Agent Memory entry points translate the canonical Harness DTOs lazily.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from simple_harness_memory.core.errors import MemoryValidationError


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MemoryValidationError(f"{name} must be non-blank and contain no NUL")
    return value


class ScopeKind(StrEnum):
    PERSONAL = "personal"
    FAMILY = "family"


@dataclass(frozen=True, slots=True)
class MemoryPrincipal:
    deployment_id: str
    household_id: str
    actor_id: str
    session_id: str

    def __post_init__(self) -> None:
        for name in ("deployment_id", "household_id", "actor_id", "session_id"):
            _identifier(getattr(self, name), name)

    @property
    def opaque_id(self) -> str:
        material = "\x1f".join(
            (self.deployment_id, self.household_id, self.actor_id, self.session_id)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    kind: ScopeKind
    owner_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ScopeKind(self.kind))
        _identifier(self.owner_id, "owner_id")

    @classmethod
    def personal(cls, actor_id: str) -> MemoryScope:
        return cls(ScopeKind.PERSONAL, actor_id)

    @classmethod
    def family(cls, household_id: str) -> MemoryScope:
        return cls(ScopeKind.FAMILY, household_id)

    def authorize(self, principal: MemoryPrincipal) -> None:
        expected = principal.actor_id if self.kind is ScopeKind.PERSONAL else principal.household_id
        if self.owner_id != expected:
            from simple_harness_memory.core.errors import MemoryOwnershipConflict

            raise MemoryOwnershipConflict()


def scope_predicate(
    principal: MemoryPrincipal,
    scopes: tuple[MemoryScope, ...],
    *,
    table_alias: str = "",
) -> tuple[str, tuple[object, ...]]:
    """Return the single shared SQL ownership predicate used by v4 operations."""

    if not scopes:
        raise MemoryValidationError("at least one scope is required")
    prefix = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[object] = [principal.deployment_id, principal.household_id]
    for scope in scopes:
        scope.authorize(principal)
        clauses.append(f"({prefix}scope_kind = ? AND {prefix}scope_owner = ?)")
        params.extend((scope.kind.value, scope.owner_id))
    return (
        f"{prefix}deployment_id = ? AND {prefix}household_id = ? AND ("
        + " OR ".join(clauses)
        + ")",
        tuple(params),
    )


@dataclass(frozen=True, slots=True)
class ExportPage:
    protocol: str
    records: tuple[dict[str, object], ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class PrivacyReceipt:
    receipt_id: str
    deleted_messages: int = 0
    deleted_facts: int = 0
    deleted_snapshots: int = 0
    cancelled_jobs: int = 0


@dataclass(frozen=True, slots=True)
class PrincipalRegistrationReceipt:
    """``register_principal_owner`` 的幂等回执：同一属主形状重复登记返回同一回执。"""

    registration_id: str
    principal_id: str
    deployment_id: str
    household_id: str
    actor_id: str
    registered_at: float
    schema_version: int = 1
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise MemoryValidationError("principal_registration_schema_unsupported")
        for name in (
            "registration_id",
            "principal_id",
            "deployment_id",
            "household_id",
            "actor_id",
        ):
            _identifier(getattr(self, name), name)
        if self.principal_id != self.actor_id:
            raise MemoryValidationError("principal_registration_actor_differs")
        if (
            isinstance(self.registered_at, bool)
            or not isinstance(self.registered_at, (int, float))
            or self.registered_at < 0
        ):
            raise MemoryValidationError("principal_registration_time_invalid")
        object.__setattr__(self, "registered_at", float(self.registered_at))
        material = "\x1f".join(
            (
                str(self.schema_version),
                self.registration_id,
                self.principal_id,
                self.deployment_id,
                self.household_id,
                self.actor_id,
                repr(self.registered_at),
            )
        )
        object.__setattr__(
            self, "receipt_hash", hashlib.sha256(material.encode("utf-8")).hexdigest()
        )


__all__ = (
    "ExportPage",
    "MemoryPrincipal",
    "MemoryScope",
    "PrincipalRegistrationReceipt",
    "PrivacyReceipt",
    "ScopeKind",
)
