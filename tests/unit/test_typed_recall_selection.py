from __future__ import annotations

import math

import pytest
from simple_harness.contracts import JsonValue, canonical_json

from simple_harness_memory.core.recall import (
    RRF_K,
    RecallCandidate,
    RecallConfirmationCandidate,
    apply_budget,
    apply_confirmation_budget,
    rank_candidates,
)


def _candidate(
    source_ref: str,
    *,
    source_kind: str = "cognitive_memory",
    source_revision: int | None = 1,
    memory_type: str | None = "semantic",
    payload: dict[str, JsonValue] | None = None,
    evidence_manifest_hash: str | None = None,
    source_time: float = 10.0,
    lane_ranks: tuple[tuple[str, int], ...] = (("full_text", 1),),
) -> RecallCandidate:
    return RecallCandidate(
        source_kind=source_kind,
        source_ref=source_ref,
        source_revision=source_revision,
        memory_type=memory_type,
        public_payload={"value": source_ref} if payload is None else payload,
        source_content_hash=(source_ref.encode().hex() + "0" * 64)[:64],
        effective_privacy_class="personal",
        information_attributes=("preference",),
        evidence_manifest_hash=(
            (source_ref.encode().hex() + "e" * 64)[:64]
            if evidence_manifest_hash is None
            else evidence_manifest_hash
        ),
        source_task_scope_ids=(),
        active_task_scope_id=None,
        source_time=source_time,
        authority_expires_at=100.0,
        lane_ranks=lane_ranks,
    )


def test_weighted_rrf_uses_frozen_weights_k_and_twelve_decimal_serialization() -> None:
    candidate = _candidate(
        "rrf",
        lane_ranks=(
            ("vector", 1),
            ("full_text", 2),
            ("entity", 3),
            ("task_scope", 4),
            ("temporal", 5),
        ),
    )
    expected = round(
        0.40 / (RRF_K + 1)
        + 0.30 / (RRF_K + 2)
        + 0.15 / (RRF_K + 3)
        + 0.10 / (RRF_K + 4)
        + 0.05 / (RRF_K + 5),
        12,
    )
    assert candidate.score == expected


def test_rrf_full_tie_chain_prefers_lane_count_then_time_and_typed_identity() -> None:
    one_lane = _candidate("one", lane_ranks=(("vector", 1),))
    two_lanes = _candidate(
        "two",
        lane_ranks=(("full_text", 1), ("task_scope", 1)),
    )
    assert one_lane.score == two_lanes.score
    assert rank_candidates((one_lane, two_lanes))[0] is two_lanes

    tied = (
        _candidate(
            "z",
            source_revision=2,
            payload={"value": "z2"},
            source_time=11.0,
        ),
        _candidate(
            "z",
            source_revision=1,
            payload={"value": "z1"},
            source_time=11.0,
        ),
        _candidate("a-semantic", memory_type="semantic", source_time=11.0),
        _candidate("z-episode", memory_type="episode", source_time=11.0),
        _candidate(
            "short",
            source_kind="short_horizon",
            source_revision=None,
            memory_type=None,
            source_time=11.0,
        ),
        _candidate("newest", source_time=12.0),
    )
    assert [item.source_ref + f":{item.source_revision}" for item in rank_candidates(tied)] == [
        "newest:1",
        "z-episode:1",
        "a-semantic:1",
        "z:1",
        "z:2",
        "short:None",
    ]
    assert [item.memory_type for item in rank_candidates(tied)[1:3]] == [
        "episode",
        "semantic",
    ]


def test_exact_dedupe_keeps_higher_rrf_and_cross_source_merge_requires_exact_manifest() -> None:
    low = _candidate("same", lane_ranks=(("full_text", 5),))
    high = _candidate("same", lane_ranks=(("vector", 1),))
    exact = rank_candidates((low, high))
    assert exact == (high,)

    payload: dict[str, JsonValue] = {"content": "identical", "occurred_at": 1.0}
    manifest = "a" * 64
    cognitive = _candidate(
        "memory",
        payload=payload,
        evidence_manifest_hash=manifest,
    )
    short = _candidate(
        "chunk",
        source_kind="short_horizon",
        source_revision=None,
        memory_type=None,
        payload=payload,
        evidence_manifest_hash=manifest,
    )
    assert rank_candidates((short, cognitive)) == (cognitive,)

    different_evidence = _candidate(
        "chunk-other",
        source_kind="short_horizon",
        source_revision=None,
        memory_type=None,
        payload=payload,
        evidence_manifest_hash="b" * 64,
    )
    assert len(rank_candidates((cognitive, different_evidence))) == 2


@pytest.mark.parametrize(
    "value",
    (
        "plain ascii",
        "中文边界",
        "emoji 🧠✨",
        'quote " slash \\ newline\n tab\t',
    ),
)
def test_budget_exact_utf8_and_conservative_token_boundaries(value: str) -> None:
    candidate = _candidate("budget", payload={"value": value})
    encoded = canonical_json([candidate.provider_budget_value()])
    encoded_bytes = len(encoded.encode("utf-8"))
    conservative_tokens = max(1, len(encoded), math.ceil(encoded_bytes / 3))

    exact = apply_budget(
        (candidate,),
        max_items=1,
        max_bytes=encoded_bytes,
        max_tokens=conservative_tokens,
    )
    assert exact.selected == (candidate,)
    assert exact.encoded_bytes == encoded_bytes
    assert exact.conservative_tokens == conservative_tokens
    assert exact.truncated is False

    one_byte_short = apply_budget(
        (candidate,),
        max_items=1,
        max_bytes=encoded_bytes - 1,
        max_tokens=conservative_tokens,
    )
    assert one_byte_short.selected == ()
    assert one_byte_short.truncated is True

    one_token_short = apply_budget(
        (candidate,),
        max_items=1,
        max_bytes=encoded_bytes,
        max_tokens=conservative_tokens - 1,
    )
    assert one_token_short.selected == ()
    assert one_token_short.truncated is True


def test_budget_skips_oversize_first_item_and_keeps_later_whole_item() -> None:
    large = _candidate("large", payload={"value": "x" * 1_000})
    small = _candidate("small", payload={"value": "ok"})
    small_encoded = canonical_json([small.provider_budget_value()])
    selection = apply_budget(
        (large, small),
        max_items=2,
        max_bytes=len(small_encoded.encode("utf-8")),
        max_tokens=max(1, len(small_encoded)),
    )
    assert selection.selected == (small,)
    assert selection.truncated is True


def test_memory_confirmation_candidate_requires_exactly_two_members() -> None:
    first = _candidate("first")
    second = _candidate("second", source_revision=2)
    third = _candidate("third", source_revision=3)
    with pytest.raises(ValueError, match="exactly two"):
        RecallConfirmationCandidate("group", "a" * 64, (first,))
    assert RecallConfirmationCandidate("group", "a" * 64, (first, second)).members == (
        first,
        second,
    )
    with pytest.raises(ValueError, match="exactly two"):
        RecallConfirmationCandidate("group", "a" * 64, (first, second, third))


@pytest.mark.parametrize(
    ("max_items", "expected_group_count", "truncated"),
    ((2, 1, True), (3, 1, True), (4, 2, False)),
)
def test_confirmation_budget_counts_flat_members_and_keeps_groups_atomic(
    max_items: int,
    expected_group_count: int,
    truncated: bool,
) -> None:
    first = RecallConfirmationCandidate(
        "group-1", "1" * 64, (_candidate("g1-r1"), _candidate("g1-r2", source_revision=2))
    )
    second = RecallConfirmationCandidate(
        "group-2", "2" * 64, (_candidate("g2-r1"), _candidate("g2-r2", source_revision=2))
    )
    selection = apply_confirmation_budget(
        (first, second),
        max_items=max_items,
        max_bytes=65_536,
        max_tokens=8_192,
    )
    assert len(selection.selected) == expected_group_count
    assert selection.truncated is truncated
    assert all(len(group.members) == 2 for group in selection.selected)
