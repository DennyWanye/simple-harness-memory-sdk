"""Typed prospective-memory trigger evaluation.

Memory evaluates durable Host signals and emits state candidates.  It never
starts a clock, subscribes to events, sends a notification, or authorizes the
external action described by an intent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Final

from simple_harness.contracts import JsonValue, canonical_json
from simple_harness.runtime.memory_protocol import (
    EpistemicStatus,
    ProspectiveEventTrigger,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveTimeTrigger,
    ProspectiveTrigger,
)

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MemoryValidationError(f"{name}_invalid")
    return value


def _digest(value: str, name: str) -> str:
    if len(value) != 64:
        raise MemoryValidationError(f"{name}_invalid")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise MemoryValidationError(f"{name}_invalid") from exc
    return value


def _timestamp(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise MemoryValidationError(f"{name}_invalid")
    return float(value)


def normalize_trigger(trigger: ProspectiveTrigger) -> ProspectiveTrigger:
    """Round-trip an exact Harness trigger and reject any free-form substitute."""

    if isinstance(trigger, ProspectiveTimeTrigger):
        return ProspectiveTimeTrigger.from_json(trigger.to_json())
    if isinstance(trigger, ProspectiveEventTrigger):
        return ProspectiveEventTrigger.from_json(trigger.to_json())
    raise MemoryValidationError("harness_prospective_trigger_required")


@dataclass(frozen=True, slots=True)
class ProspectiveIntent:
    """Canonical state; not a model-facing wire DTO.

    A no-trigger action can remain a candidate internally.  Model proposals
    that cross the Host wire use :meth:`from_payload` and therefore retain the
    exact Harness 0.7 strict trigger union.
    """

    memory_id: str
    subject: str
    scope: MemoryScope
    revision: int
    action: str
    trigger: ProspectiveTrigger | None
    lifecycle_state: ProspectiveLifecycleState
    epistemic_status: EpistemicStatus
    evidence_span_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.memory_id, "memory_id")
        _identifier(self.subject, "subject")
        if not isinstance(self.scope, MemoryScope):
            raise MemoryValidationError("scope_invalid")
        if isinstance(self.revision, bool) or self.revision < 1:
            raise MemoryValidationError("revision_invalid")
        if not isinstance(self.action, str) or not self.action.strip():
            raise MemoryValidationError("prospective_action_invalid")
        if self.trigger is not None:
            object.__setattr__(self, "trigger", normalize_trigger(self.trigger))
        object.__setattr__(
            self, "lifecycle_state", ProspectiveLifecycleState(self.lifecycle_state)
        )
        object.__setattr__(self, "epistemic_status", EpistemicStatus(self.epistemic_status))
        if not self.evidence_span_hashes or len(self.evidence_span_hashes) != len(
            set(self.evidence_span_hashes)
        ):
            raise MemoryValidationError("evidence_span_hashes_invalid")
        object.__setattr__(
            self,
            "evidence_span_hashes",
            tuple(_digest(item, "evidence_span_hash") for item in self.evidence_span_hashes),
        )
        if self.lifecycle_state is not ProspectiveLifecycleState.CANDIDATE:
            if self.trigger is None:
                raise MemoryValidationError("prospective_trigger_required")
            if self.epistemic_status is EpistemicStatus.LLM_INFERENCE:
                raise MemoryValidationError("inference_cannot_schedule_prospective_intent")

    @classmethod
    def from_payload(
        cls,
        *,
        memory_id: str,
        subject: str,
        scope: MemoryScope,
        revision: int,
        payload: ProspectiveMemoryPayload,
        lifecycle_state: ProspectiveLifecycleState,
        epistemic_status: EpistemicStatus,
        evidence_span_hashes: tuple[str, ...],
    ) -> ProspectiveIntent:
        if not isinstance(payload, ProspectiveMemoryPayload):
            raise MemoryValidationError("prospective_payload_required")
        return cls(
            memory_id=memory_id,
            subject=subject,
            scope=scope,
            revision=revision,
            action=payload.action,
            trigger=payload.trigger,
            lifecycle_state=lifecycle_state,
            epistemic_status=epistemic_status,
            evidence_span_hashes=evidence_span_hashes,
        )


@dataclass(frozen=True, slots=True)
class TimeTriggerSignal:
    signal_id: str
    observed_at: float
    scheduler_authority_ref: str
    registration_revision: int

    def __post_init__(self) -> None:
        _identifier(self.signal_id, "signal_id")
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at, "observed_at"))
        _identifier(self.scheduler_authority_ref, "scheduler_authority_ref")
        if isinstance(self.registration_revision, bool) or self.registration_revision < 1:
            raise MemoryValidationError("registration_revision_invalid")


@dataclass(frozen=True, slots=True)
class EventTriggerSignal:
    signal_id: str
    occurred_at: float
    event_authority_ref: str
    condition_hash: str
    event_receipt_hash: str

    def __post_init__(self) -> None:
        _identifier(self.signal_id, "signal_id")
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        _identifier(self.event_authority_ref, "event_authority_ref")
        _digest(self.condition_hash, "condition_hash")
        _digest(self.event_receipt_hash, "event_receipt_hash")


TriggerSignal = TimeTriggerSignal | EventTriggerSignal


@dataclass(frozen=True, slots=True)
class TriggerEvaluation:
    matched: bool
    next_state: ProspectiveLifecycleState
    occurrence_key: str
    reason_code: str
    external_action_authorized: bool = False

    def __post_init__(self) -> None:
        if self.external_action_authorized:
            raise MemoryValidationError("prospective_memory_cannot_authorize_external_action")


def _occurrence_key(intent: ProspectiveIntent, signal: TriggerSignal) -> str:
    signal_value: dict[str, JsonValue]
    if isinstance(signal, TimeTriggerSignal):
        signal_value = {
            "kind": "time",
            "signal_id": signal.signal_id,
            "observed_at": signal.observed_at,
            "scheduler_authority_ref": signal.scheduler_authority_ref,
            "registration_revision": signal.registration_revision,
        }
    else:
        signal_value = {
            "kind": "event",
            "signal_id": signal.signal_id,
            "occurred_at": signal.occurred_at,
            "event_authority_ref": signal.event_authority_ref,
            "condition_hash": signal.condition_hash,
            "event_receipt_hash": signal.event_receipt_hash,
        }
    material = canonical_json(
        {
            "domain": "simple-harness-memory/prospective-occurrence/v1",
            "memory_id": intent.memory_id,
            "revision": intent.revision,
            "signal": signal_value,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def evaluate_trigger(
    intent: ProspectiveIntent,
    signal: TriggerSignal,
    *,
    seen_occurrence_keys: frozenset[str],
) -> TriggerEvaluation:
    """Evaluate one authority-issued signal without performing the action."""

    occurrence_key = _occurrence_key(intent, signal)
    if occurrence_key in seen_occurrence_keys:
        return TriggerEvaluation(
            False,
            intent.lifecycle_state,
            occurrence_key,
            "prospective_trigger_replay_ignored",
        )
    if intent.lifecycle_state is not ProspectiveLifecycleState.PENDING:
        return TriggerEvaluation(
            False,
            intent.lifecycle_state,
            occurrence_key,
            "prospective_intent_not_pending",
        )
    trigger = intent.trigger
    if isinstance(trigger, ProspectiveTimeTrigger):
        matched = isinstance(signal, TimeTriggerSignal) and signal.observed_at >= trigger.trigger_at
    elif isinstance(trigger, ProspectiveEventTrigger):
        matched = (
            isinstance(signal, EventTriggerSignal)
            and signal.event_authority_ref == trigger.event_authority_ref
            and signal.condition_hash == trigger.condition_hash
        )
    else:
        matched = False
    return TriggerEvaluation(
        matched,
        (
            ProspectiveLifecycleState.TRIGGERED
            if matched
            else ProspectiveLifecycleState.PENDING
        ),
        occurrence_key,
        "prospective_trigger_matched" if matched else "prospective_trigger_not_matched",
    )


_TRANSITIONS: Final[
    dict[ProspectiveLifecycleState, frozenset[ProspectiveLifecycleState]]
] = {
    ProspectiveLifecycleState.CANDIDATE: frozenset(
        {
            ProspectiveLifecycleState.PENDING,
            ProspectiveLifecycleState.CANCELLED,
            ProspectiveLifecycleState.EXPIRED,
            ProspectiveLifecycleState.FORGOTTEN,
        }
    ),
    ProspectiveLifecycleState.PENDING: frozenset(
        {
            ProspectiveLifecycleState.TRIGGERED,
            ProspectiveLifecycleState.RESCHEDULED,
            ProspectiveLifecycleState.CANCELLED,
            ProspectiveLifecycleState.EXPIRED,
            ProspectiveLifecycleState.SUPERSEDED,
            ProspectiveLifecycleState.FORGOTTEN,
        }
    ),
    ProspectiveLifecycleState.TRIGGERED: frozenset(
        {
            ProspectiveLifecycleState.IN_PROGRESS,
            ProspectiveLifecycleState.RESCHEDULED,
            ProspectiveLifecycleState.CANCELLED,
            ProspectiveLifecycleState.EXPIRED,
            ProspectiveLifecycleState.FORGOTTEN,
        }
    ),
    ProspectiveLifecycleState.IN_PROGRESS: frozenset(
        {
            ProspectiveLifecycleState.COMPLETED,
            ProspectiveLifecycleState.RESCHEDULED,
            ProspectiveLifecycleState.CANCELLED,
            ProspectiveLifecycleState.EXPIRED,
            ProspectiveLifecycleState.FORGOTTEN,
        }
    ),
    ProspectiveLifecycleState.RESCHEDULED: frozenset(
        {
            ProspectiveLifecycleState.PENDING,
            ProspectiveLifecycleState.CANCELLED,
            ProspectiveLifecycleState.EXPIRED,
            ProspectiveLifecycleState.FORGOTTEN,
        }
    ),
    ProspectiveLifecycleState.COMPLETED: frozenset(),
    ProspectiveLifecycleState.CANCELLED: frozenset(),
    ProspectiveLifecycleState.EXPIRED: frozenset(),
    ProspectiveLifecycleState.SUPERSEDED: frozenset(),
    ProspectiveLifecycleState.FORGOTTEN: frozenset(),
}


def transition_prospective(
    current: ProspectiveIntent,
    target: ProspectiveLifecycleState,
    *,
    signal: TriggerSignal | None = None,
    seen_occurrence_keys: frozenset[str] = frozenset(),
    trigger: ProspectiveTrigger | None = None,
) -> ProspectiveIntent:
    """Apply one legal state transition; triggering requires a matched signal."""

    target = ProspectiveLifecycleState(target)
    if target not in _TRANSITIONS[current.lifecycle_state]:
        raise MemoryValidationError("prospective_transition_invalid")
    next_trigger = current.trigger if trigger is None else normalize_trigger(trigger)
    if target in {
        ProspectiveLifecycleState.PENDING,
        ProspectiveLifecycleState.RESCHEDULED,
    } and next_trigger is None:
        raise MemoryValidationError("prospective_trigger_required")
    if target is ProspectiveLifecycleState.TRIGGERED:
        if signal is None:
            raise MemoryValidationError("prospective_trigger_signal_required")
        evaluation = evaluate_trigger(
            current,
            signal,
            seen_occurrence_keys=seen_occurrence_keys,
        )
        if not evaluation.matched:
            raise MemoryValidationError(evaluation.reason_code)
    return replace(
        current,
        revision=current.revision + 1,
        lifecycle_state=target,
        trigger=next_trigger,
    )


__all__ = (
    "EventTriggerSignal",
    "ProspectiveIntent",
    "TimeTriggerSignal",
    "TriggerEvaluation",
    "TriggerSignal",
    "evaluate_trigger",
    "normalize_trigger",
    "transition_prospective",
)
