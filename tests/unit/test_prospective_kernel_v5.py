from __future__ import annotations

import hashlib

import pytest
from simple_harness.contracts import fingerprint_json
from simple_harness.runtime.memory_protocol import (
    EpistemicStatus,
    ProspectiveEventTrigger,
    ProspectiveLifecycleState,
    ProspectiveMemoryPayload,
    ProspectiveTimeTrigger,
)

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.identity import MemoryScope
from simple_harness_memory.core.prospective import (
    EventTriggerSignal,
    ProspectiveIntent,
    TimeTriggerSignal,
    evaluate_trigger,
    normalize_trigger,
    transition_prospective,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _intent(
    *,
    trigger: ProspectiveTimeTrigger | ProspectiveEventTrigger | None,
    state: ProspectiveLifecycleState,
    epistemic: EpistemicStatus = EpistemicStatus.EXPLICIT_USER,
) -> ProspectiveIntent:
    return ProspectiveIntent(
        memory_id="future-1",
        subject="user-1",
        scope=MemoryScope.personal("user-1"),
        revision=1,
        action="更新变更日志",
        trigger=trigger,
        lifecycle_state=state,
        epistemic_status=epistemic,
        evidence_span_hashes=(_sha("span-1"),),
    )


def test_exact_harness_trigger_round_trip_and_no_free_form_trigger() -> None:
    trigger = ProspectiveTimeTrigger(100.0, "Asia/Shanghai")
    assert normalize_trigger(trigger) == trigger
    with pytest.raises(MemoryValidationError, match="harness_prospective_trigger_required"):
        normalize_trigger(object())  # type: ignore[arg-type]

    payload = ProspectiveMemoryPayload("更新变更日志", trigger)
    intent = ProspectiveIntent.from_payload(
        memory_id="future-1",
        subject="user-1",
        scope=MemoryScope.personal("user-1"),
        revision=1,
        payload=payload,
        lifecycle_state=ProspectiveLifecycleState.PENDING,
        epistemic_status=EpistemicStatus.EXPLICIT_USER,
        evidence_span_hashes=(_sha("span-1"),),
    )
    assert intent.trigger == trigger


def test_action_without_trigger_stays_candidate_and_inference_never_schedules() -> None:
    candidate = _intent(trigger=None, state=ProspectiveLifecycleState.CANDIDATE)
    assert candidate.lifecycle_state is ProspectiveLifecycleState.CANDIDATE
    inferred = _intent(
        trigger=None,
        state=ProspectiveLifecycleState.CANDIDATE,
        epistemic=EpistemicStatus.LLM_INFERENCE,
    )
    assert inferred.lifecycle_state is ProspectiveLifecycleState.CANDIDATE
    with pytest.raises(MemoryValidationError, match="inference_cannot_schedule"):
        _intent(
            trigger=ProspectiveTimeTrigger(100.0, "UTC"),
            state=ProspectiveLifecycleState.PENDING,
            epistemic=EpistemicStatus.LLM_INFERENCE,
        )


def test_event_trigger_matches_exact_authority_once_and_never_authorizes_action() -> None:
    condition = "project == 'a'"
    trigger = ProspectiveEventTrigger(
        "event-authority-1",
        condition,
        fingerprint_json(condition),
    )
    pending = _intent(trigger=trigger, state=ProspectiveLifecycleState.PENDING)
    signal = EventTriggerSignal(
        signal_id="signal-1",
        occurred_at=20.0,
        event_authority_ref="event-authority-1",
        condition_hash=trigger.condition_hash,
        event_receipt_hash=_sha("event-receipt-1"),
    )

    evaluation = evaluate_trigger(pending, signal, seen_occurrence_keys=frozenset())
    assert evaluation.matched
    assert evaluation.next_state is ProspectiveLifecycleState.TRIGGERED
    assert evaluation.external_action_authorized is False

    replay = evaluate_trigger(
        pending,
        signal,
        seen_occurrence_keys=frozenset({evaluation.occurrence_key}),
    )
    assert not replay.matched
    assert replay.reason_code == "prospective_trigger_replay_ignored"

    wrong_authority = EventTriggerSignal(
        "signal-2",
        20.0,
        "event-authority-other",
        trigger.condition_hash,
        _sha("event-receipt-2"),
    )
    assert not evaluate_trigger(
        pending, wrong_authority, seen_occurrence_keys=frozenset()
    ).matched


def test_time_trigger_and_legal_reschedule_cancel_expire_complete_transitions() -> None:
    trigger = ProspectiveTimeTrigger(100.0, "UTC")
    pending = _intent(trigger=trigger, state=ProspectiveLifecycleState.PENDING)
    early = TimeTriggerSignal("clock-1", 99.0, "scheduler-1", 1)
    assert not evaluate_trigger(pending, early, seen_occurrence_keys=frozenset()).matched

    due = TimeTriggerSignal("clock-2", 100.0, "scheduler-1", 1)
    triggered = transition_prospective(
        pending,
        ProspectiveLifecycleState.TRIGGERED,
        signal=due,
        seen_occurrence_keys=frozenset(),
    )
    assert triggered.lifecycle_state is ProspectiveLifecycleState.TRIGGERED
    in_progress = transition_prospective(
        triggered, ProspectiveLifecycleState.IN_PROGRESS
    )
    assert transition_prospective(
        in_progress, ProspectiveLifecycleState.COMPLETED
    ).lifecycle_state is ProspectiveLifecycleState.COMPLETED
    assert transition_prospective(
        in_progress,
        ProspectiveLifecycleState.RESCHEDULED,
        trigger=ProspectiveTimeTrigger(200.0, "UTC"),
    ).lifecycle_state is ProspectiveLifecycleState.RESCHEDULED
    assert transition_prospective(
        pending, ProspectiveLifecycleState.CANCELLED
    ).lifecycle_state is ProspectiveLifecycleState.CANCELLED
    assert transition_prospective(
        pending, ProspectiveLifecycleState.EXPIRED
    ).lifecycle_state is ProspectiveLifecycleState.EXPIRED

    with pytest.raises(MemoryValidationError, match="prospective_transition_invalid"):
        transition_prospective(pending, ProspectiveLifecycleState.COMPLETED)
    with pytest.raises(MemoryValidationError, match="prospective_trigger_signal_required"):
        transition_prospective(pending, ProspectiveLifecycleState.TRIGGERED)
