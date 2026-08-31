from __future__ import annotations

from itertools import product
from types import SimpleNamespace
from typing import Any, cast

from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend

LIFECYCLES = {
    "episode": {
        "active",
        "amended",
        "candidate",
        "draft",
        "superseded",
        "suppressed",
    },
    "semantic": {"active", "draft", "superseded", "suppressed"},
    "procedure": {
        "draft",
        "eligible",
        "active",
        "reinforced",
        "revised",
        "inapplicable",
        "superseded",
    },
    "prospective": {
        "candidate",
        "pending",
        "triggered",
        "in_progress",
        "completed",
        "cancelled",
        "expired",
        "rescheduled",
    },
}
ALLOWED_LIFECYCLES = {
    "episode": {"active", "amended"},
    "semantic": {"active"},
    "procedure": {"active", "reinforced"},
    "prospective": {"pending", "triggered", "in_progress", "rescheduled"},
}
EPISTEMIC_STATES = {
    "explicit_user",
    "verified_external",
    "observed_behavior",
    "llm_inference",
    "unknown",
}
VERIFICATION_STATES = {
    "unverified",
    "source_bound",
    "source_verified",
    "repeated_observation",
    "user_confirmed",
}
ALLOWED_EPISTEMIC_VERIFICATION = {
    "episode": {
        ("explicit_user", "source_bound"),
        ("explicit_user", "user_confirmed"),
        ("verified_external", "source_verified"),
        ("observed_behavior", "source_verified"),
        ("observed_behavior", "repeated_observation"),
    },
    "semantic": {
        ("explicit_user", "source_bound"),
        ("explicit_user", "user_confirmed"),
        ("verified_external", "source_verified"),
        ("observed_behavior", "source_verified"),
        ("observed_behavior", "repeated_observation"),
    },
    "procedure": {
        ("explicit_user", "source_bound"),
        ("explicit_user", "user_confirmed"),
        ("observed_behavior", "repeated_observation"),
    },
    "prospective": {
        ("explicit_user", "source_bound"),
        ("explicit_user", "user_confirmed"),
    },
}


def test_cognitive_state_matrix_denies_every_unlisted_combination() -> None:
    checked = 0
    for memory_type, lifecycle, epistemic, verification, conflict in product(
        LIFECYCLES,
        sorted({state for states in LIFECYCLES.values() for state in states}),
        EPISTEMIC_STATES,
        VERIFICATION_STATES,
        ("uncontested", "resolved", "contested", "unknown"),
    ):
        row = {
            "memory_type": memory_type,
            "lifecycle_state": lifecycle,
            "epistemic_status": epistemic,
            "verification_state": verification,
            "conflict_status": conflict,
        }
        expected_ordinary = (
            lifecycle in ALLOWED_LIFECYCLES[memory_type]
            and (epistemic, verification)
            in ALLOWED_EPISTEMIC_VERIFICATION[memory_type]
            and conflict in {"uncontested", "resolved"}
        )
        expected_confirmation = expected_ordinary or (
            lifecycle in ALLOWED_LIFECYCLES[memory_type]
            and (epistemic, verification)
            in ALLOWED_EPISTEMIC_VERIFICATION[memory_type]
            and conflict == "contested"
        )
        assert (
            SQLiteHumanMemoryBackend._cognitive_recall_state_allowed(cast(Any, row))
            is expected_ordinary
        )
        assert (
            SQLiteHumanMemoryBackend._cognitive_recall_state_allowed(
                cast(Any, row), allow_contested=True
            )
            is expected_confirmation
        )
        checked += 1
    assert checked == 4 * 17 * 5 * 5 * 4


def test_validity_is_half_open_and_null_bound_is_unbounded() -> None:
    cases = (
        ({"valid_from": None, "valid_to": None}, 10.0, True),
        ({"valid_from": 10.0, "valid_to": None}, 10.0, True),
        ({"valid_from": 10.1, "valid_to": None}, 10.0, False),
        ({"valid_from": None, "valid_to": 10.1}, 10.0, True),
        ({"valid_from": None, "valid_to": 10.0}, 10.0, False),
        ({"valid_from": 9.0, "valid_to": 10.0}, 9.999999, True),
    )
    for row, now, expected in cases:
        assert (
            SQLiteHumanMemoryBackend._cognitive_recall_valid_at(cast(Any, row), now)
            is expected
        )


def _disclosure(
    recipient: str,
    purpose: str,
    *,
    trust: str = "trusted_authority",
    generation: str = "current",
) -> SimpleNamespace:
    return SimpleNamespace(
        recipient=SimpleNamespace(value=recipient),
        purpose=SimpleNamespace(value=purpose),
        trust=SimpleNamespace(value=trust),
        generation=SimpleNamespace(value=generation),
    )


def test_disclosure_matrix_and_non_self_attribute_floor_are_exhaustive() -> None:
    recipients = (
        "user_self",
        "household",
        "task_collaborator",
        "external_party",
        "public",
        "unknown",
    )
    purposes = (
        "task_execution",
        "personalization",
        "task_resume",
        "user_review",
        "audit",
        "export",
        "unknown",
    )
    privacies = ("public", "personal", "sensitive", "restricted")
    attributes = (
        (),
        ("preference",),
        ("identity",),
        ("relationship",),
        ("family",),
        ("health",),
        ("location",),
        ("financial",),
    )
    sensitive_attributes = {
        "identity",
        "relationship",
        "family",
        "health",
        "location",
        "financial",
    }
    checked = 0
    for recipient, purpose, privacy, attrs in product(
        recipients, purposes, privacies, attributes
    ):
        if recipient == "user_self":
            expected = (
                purpose
                in {"task_execution", "personalization", "task_resume", "user_review"}
                and privacy in {"public", "personal", "sensitive"}
            )
        else:
            expected = (
                recipient in {"household", "task_collaborator"}
                and purpose in {"task_execution", "task_resume"}
                and privacy == "public"
                and not sensitive_attributes.intersection(attrs)
            )
        assert (
            SQLiteHumanMemoryBackend._candidate_disclosure_allowed(
                _disclosure(recipient, purpose), privacy, attrs
            )
            is expected
        )
        checked += 1
    assert checked == len(recipients) * len(purposes) * len(privacies) * len(attributes)

    assert not SQLiteHumanMemoryBackend._ordinary_recall_disclosure_allowed(
        _disclosure("user_self", "task_execution", trust="untrusted")
    )
    assert not SQLiteHumanMemoryBackend._ordinary_recall_disclosure_allowed(
        _disclosure("user_self", "task_execution", generation="stale")
    )
