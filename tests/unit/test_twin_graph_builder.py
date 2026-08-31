from __future__ import annotations

from dataclasses import replace

import pytest
from simple_harness.contracts import JsonValue, canonical_json, fingerprint_json

from simple_harness_memory.cognitive.twin_builder import (
    TwinGraphRecordInput,
    TwinGraphRelationInput,
    TwinGraphSourceRef,
    TwinGraphView,
    build_twin_graph_view,
)
from simple_harness_memory.core.errors import MemoryValidationError


def _source(index: int) -> TwinGraphSourceRef:
    return TwinGraphSourceRef(
        fingerprint_json(f"evidence-{index}"),
        fingerprint_json(f"span-{index}"),
        "user_message",
        fingerprint_json(f"quote-{index}"),
    )


def _record(
    index: int,
    *,
    memory_id: str | None = None,
    revision: int = 1,
    head_revision: int | None = None,
    lifecycle_state: str = "active",
    epistemic_status: str = "explicit_user",
    conflict_status: str = "uncontested",
    verification_state: str = "source_bound",
    valid_to: float | None = None,
    conflict_group_id: str | None = None,
    suppressed: bool = False,
    redact_content: bool = False,
    value: str | None = None,
) -> TwinGraphRecordInput:
    content: dict[str, JsonValue] = {
        "memory_type": "semantic",
        "subject_entity": "user:self",
        "predicate": f"preference-{index}",
        "object_value": value or f"value-{index}",
    }
    return TwinGraphRecordInput(
        memory_id or f"memory-{index}",
        revision,
        revision if head_revision is None else head_revision,
        "semantic",
        lifecycle_state,
        epistemic_status,
        conflict_status,
        verification_state,
        None,
        valid_to,
        content,
        fingerprint_json(content),
        (_source(index),),
        conflict_group_id,
        suppressed,
        redact_content,
    )


def test_builder_includes_active_and_inferred_but_excludes_non_current_terminal_hidden() -> None:
    active = _record(1)
    inferred = _record(
        2,
        lifecycle_state="candidate",
        epistemic_status="llm_inference",
        verification_state="unverified",
    )
    expired = _record(3, valid_to=20.0, value="expired-canary")
    suppressed = _record(4, suppressed=True, value="suppressed-canary")
    superseded = _record(5, lifecycle_state="superseded", value="superseded-canary")
    historical = _record(6, revision=1, head_revision=2, value="historical-canary")
    relation = TwinGraphRelationInput(
        "relation-1",
        "supports",
        active.memory_id,
        active.revision,
        inferred.memory_id,
        inferred.revision,
        "a" * 64,
    )
    hidden_relation = TwinGraphRelationInput(
        "relation-hidden",
        "relates_to",
        active.memory_id,
        active.revision,
        suppressed.memory_id,
        suppressed.revision,
        "c" * 64,
    )

    view = build_twin_graph_view(
        subject="actor-1",
        generated_at=20.0,
        records=(superseded, active, expired, inferred, suppressed, historical),
        relations=(relation, hidden_relation),
    )

    assert [(item.memory_id, item.status) for item in view.nodes] == [
        ("memory-1", "active"),
        ("memory-2", "inferred"),
    ]
    assert view.nodes[0].confidence == 0.95
    assert view.nodes[1].confidence == 0.35
    assert view.nodes[0].can_correct is True
    assert view.nodes[0].can_forget is True
    assert [item.relation_kind for item in view.edges] == ["supports"]
    encoded = canonical_json(view.to_json())
    assert "evidence-1" not in encoded
    assert "span-1" not in encoded
    for canary in (
        "expired-canary",
        "suppressed-canary",
        "superseded-canary",
        "historical-canary",
    ):
        assert canary not in encoded


def test_conflict_group_is_atomic_and_only_current_member_has_action_capabilities() -> None:
    incumbent = _record(
        1,
        memory_id="memory-conflict",
        revision=1,
        head_revision=2,
        conflict_status="contested",
        conflict_group_id="group-1",
        value="incumbent",
    )
    challenger = _record(
        2,
        memory_id="memory-conflict",
        revision=2,
        head_revision=2,
        conflict_status="contested",
        conflict_group_id="group-1",
        value="challenger",
    )
    relation = TwinGraphRelationInput(
        "relation-contest",
        "contests",
        "memory-conflict",
        2,
        "memory-conflict",
        1,
        "b" * 64,
    )
    complete = build_twin_graph_view(
        subject="actor-1",
        generated_at=20.0,
        records=(incumbent, challenger),
        relations=(relation,),
    )
    assert len(complete.nodes) == 2
    assert len(complete.edges) == 1
    assert [item.can_correct for item in complete.nodes] == [False, True]
    assert all(item.status == "contested" for item in complete.nodes)

    partial = build_twin_graph_view(
        subject="actor-1",
        generated_at=20.0,
        records=(replace(incumbent, suppressed=True), challenger),
        relations=(relation,),
    )
    assert partial.nodes == ()
    assert partial.edges == ()
    assert "incumbent" not in canonical_json(partial.to_json())


def test_sensitive_content_is_redacted_and_payload_hash_round_trips() -> None:
    view = build_twin_graph_view(
        subject="actor-1",
        generated_at=20.0,
        records=(_record(1, redact_content=True, value="health-secret-canary"),),
        relations=(),
    )
    assert view.nodes[0].redacted is True
    assert view.nodes[0].label == "Semantic memory"
    assert "health-secret-canary" not in canonical_json(view.to_json())
    assert TwinGraphView.from_json(view.to_json()) == view

    tampered = view.to_json()
    tampered["generated_at"] = 21.0
    with pytest.raises(MemoryValidationError, match="twin_graph_payload_hash_differs"):
        TwinGraphView.from_json(tampered)
