# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: Apache-2.0

"""Read-only occurrence inbox and outbox projections (0.6 consumer surface).

The Host consumes these before every terminal ``no_recall`` decision (S5a
reconcile gate) and, later, for the S5b settled state machine.  Both surfaces
are strictly read-only: cursor/settlement authority lives on the Host side.

Frozen consumer contract (S5a): entries are ordered by ``(occurred_at,
event_id)`` — both fields are part of the returned shape, so the ordering key
is verifiable and usable as a resume anchor by the reader itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _required(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} is required")
    return value


def _digest(value: object, name: str) -> str:
    text = _required(value, name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be lowercase SHA-256")
    return text


@dataclass(frozen=True, slots=True)
class OccurrenceInboxEntryV1:
    """One prospective trigger occurrence plus its intent's CURRENT state.

    ``lifecycle_state`` is the target memory's current-head lifecycle state at
    read time (not the state pinned when the event fired) so the reader can
    apply liveness/eligibility gates without a second query.
    """

    event_id: str
    occurrence_key: str
    memory_id: str
    prospective_revision: int
    lifecycle_state: str
    outcome: str
    signal_kind: str
    reason_code: str
    occurred_at: float
    event_hash: str
    event_ref: str
    trigger_fingerprint: str
    action_text: str
    effective_privacy_class: str
    information_attributes: tuple[str, ...]
    content_hash: str
    suppressed: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported OccurrenceInboxEntry schema")
        for value, name in (
            (self.event_id, "event_id"),
            (self.memory_id, "memory_id"),
            (self.lifecycle_state, "lifecycle_state"),
            (self.outcome, "outcome"),
            (self.signal_kind, "signal_kind"),
            (self.reason_code, "reason_code"),
            (self.event_ref, "event_ref"),
            (self.trigger_fingerprint, "trigger_fingerprint"),
            (self.effective_privacy_class, "effective_privacy_class"),
        ):
            _required(value, name)
        _digest(self.occurrence_key, "occurrence_key")
        _digest(self.event_hash, "event_hash")
        _digest(self.content_hash, "content_hash")
        if (
            isinstance(self.prospective_revision, bool)
            or not isinstance(self.prospective_revision, int)
            or self.prospective_revision < 1
        ):
            raise ValueError("prospective_revision must be a positive integer")
        if not isinstance(self.occurred_at, (int, float)) or self.occurred_at < 0:
            raise ValueError("occurred_at must be non-negative")
        object.__setattr__(
            self,
            "information_attributes",
            tuple(str(item) for item in self.information_attributes),
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "occurrence_key": self.occurrence_key,
            "memory_id": self.memory_id,
            "prospective_revision": self.prospective_revision,
            "lifecycle_state": self.lifecycle_state,
            "outcome": self.outcome,
            "signal_kind": self.signal_kind,
            "reason_code": self.reason_code,
            "occurred_at": self.occurred_at,
            "event_hash": self.event_hash,
            "event_ref": self.event_ref,
            "trigger_fingerprint": self.trigger_fingerprint,
            "action_text": self.action_text,
            "effective_privacy_class": self.effective_privacy_class,
            "information_attributes": list(self.information_attributes),
            "content_hash": self.content_hash,
            "suppressed": self.suppressed,
        }


@dataclass(frozen=True, slots=True)
class OccurrenceInboxPageV1:
    entries: tuple[OccurrenceInboxEntryV1, ...]
    next_after: tuple[float, str] | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported OccurrenceInboxPage schema")
        object.__setattr__(self, "entries", tuple(self.entries))
        if not all(
            isinstance(item, OccurrenceInboxEntryV1) for item in self.entries
        ):
            raise TypeError("entries must be OccurrenceInboxEntryV1 values")
        if self.next_after is not None:
            occurred_at, event_id = self.next_after
            _required(event_id, "next_after event_id")
            if not isinstance(occurred_at, (int, float)) or occurred_at < 0:
                raise ValueError("next_after occurred_at must be non-negative")
            object.__setattr__(self, "next_after", (float(occurred_at), event_id))


@dataclass(frozen=True, slots=True)
class OutboxEntryV1:
    """Read-only projection of one durable outbox row."""

    outbox_id: str
    topic: str
    idempotency_key: str
    state: str
    payload_hash: str
    attempt_count: int
    next_attempt_at: float
    created_at: float
    updated_at: float
    payload: Mapping[str, object] | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported OutboxEntry schema")
        for value, name in (
            (self.outbox_id, "outbox_id"),
            (self.topic, "topic"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _required(value, name)
        if self.state not in {"pending", "claimed", "applied", "dead_letter"}:
            raise ValueError("state is not a durable outbox state")
        _required(self.payload_hash, "payload_hash")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 0
        ):
            raise ValueError("attempt_count must be non-negative")
        for value, name in (
            (self.next_attempt_at, "next_attempt_at"),
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
        ):
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class OutboxPageV1:
    entries: tuple[OutboxEntryV1, ...]
    next_after: tuple[float, str] | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported OutboxPage schema")
        object.__setattr__(self, "entries", tuple(self.entries))
        if not all(isinstance(item, OutboxEntryV1) for item in self.entries):
            raise TypeError("entries must be OutboxEntryV1 values")
        if self.next_after is not None:
            created_at, outbox_id = self.next_after
            _required(outbox_id, "next_after outbox_id")
            if not isinstance(created_at, (int, float)) or created_at < 0:
                raise ValueError("next_after created_at must be non-negative")
            object.__setattr__(self, "next_after", (float(created_at), outbox_id))


__all__ = (
    "OccurrenceInboxEntryV1",
    "OccurrenceInboxPageV1",
    "OutboxEntryV1",
    "OutboxPageV1",
)
