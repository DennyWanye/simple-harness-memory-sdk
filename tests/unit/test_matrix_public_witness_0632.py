# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1
"""0.6.32 四个公共见证增量的纯函数与边界（不触库）。

对应 Host 401 矩阵 `TYPED-RECALL-401-RUN-08.md` §7 后继第 4 项的 (a)(c)(d)：
召回策略版本入口、apply validation 精确 reason 码、typed-recall 执行 lane 见证。
(b)（``MemoryManager.cleanup_short_horizon``）是纯转发，见集成用例。
"""

from __future__ import annotations

import hashlib

import pytest
from simple_harness.contracts import canonical_json

from simple_harness_memory.core.errors import MemoryValidationError
from simple_harness_memory.core.mutation_rejections import (
    MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE,
    MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE,
    MEMORY_MUTATION_VALIDATION_REASON_CODES,
    MemoryMutationValidationNoteV1,
    specific_validation_reason_code,
)
from simple_harness_memory.core.recall import (
    EXECUTED_LANE_ORDER,
    EXECUTED_LANE_WITNESS_VERSION,
    RRF_WEIGHTS,
    RecallCandidate,
    TypedRecallExecution,
    TypedRecallLaneWitnessV1,
    executed_lanes,
    lane_witnesses,
)
from simple_harness_memory.core.recall_policy import (
    DEFAULT_RECALL_POLICY_VERSION,
    MAX_RECALL_POLICY_VERSION,
    RECALL_POLICY_HASH_V1,
    RecallEligibilityPolicyV1,
    RecallPolicyStateV1,
    coerce_recall_policy,
    recall_policy_hash,
    recall_policy_id,
    recall_policy_payload,
    validate_recall_policy_version,
)

# 0.6.31 源（main ``fc7fa88``）上 ``backends/sqlite_v5.py:300-315`` 常量的实测值。
LEGACY_POLICY_PAYLOAD = (
    '{"policy":"typed-recall-eligibility/v1","rrf_k":60,"schema":6,'
    '"weights":{"entity":0.15,"full_text":0.3,"task_scope":0.1,'
    '"temporal":0.05,"vector":0.4}}'
)


def test_default_policy_version_reproduces_the_0_6_31_constant_byte_for_byte() -> None:
    assert DEFAULT_RECALL_POLICY_VERSION == 1
    assert canonical_json(recall_policy_payload()) == LEGACY_POLICY_PAYLOAD
    assert (
        hashlib.sha256(LEGACY_POLICY_PAYLOAD.encode("utf-8")).hexdigest()
        == RECALL_POLICY_HASH_V1
    )
    assert recall_policy_hash() == RECALL_POLICY_HASH_V1
    assert recall_policy_hash(1) == RECALL_POLICY_HASH_V1
    assert RecallEligibilityPolicyV1().policy_hash == RECALL_POLICY_HASH_V1
    # backend 常量必须由同一个函数导出，不允许两处字面值漂移。
    from simple_harness_memory.backends.sqlite_v5 import _RECALL_POLICY_HASH

    assert _RECALL_POLICY_HASH == RECALL_POLICY_HASH_V1


def test_a_higher_policy_version_changes_only_the_policy_id_and_the_hash() -> None:
    assert recall_policy_id(2) == "typed-recall-eligibility/v2"
    payload_v2 = recall_policy_payload(2)
    assert payload_v2["policy"] == "typed-recall-eligibility/v2"
    assert {k: v for k, v in payload_v2.items() if k != "policy"} == {
        k: v for k, v in recall_policy_payload(1).items() if k != "policy"
    }
    # 权重/常数与 core.recall 的 RRF 定义同源，不允许两处漂移。
    assert payload_v2["weights"] == RRF_WEIGHTS
    hashes = {recall_policy_hash(version) for version in (1, 2, 3, 7)}
    assert len(hashes) == 4
    assert recall_policy_hash(2) != RECALL_POLICY_HASH_V1
    assert (
        recall_policy_hash(2)
        == "0ffc875d94aeb5d712dd3d5b39ed5522a4a57ccc4d1ef7acababd9de96f3fd7f"
    )


@pytest.mark.parametrize(
    "value", [0, -1, True, False, 1.0, "1", None, MAX_RECALL_POLICY_VERSION + 1]
)
def test_policy_version_is_a_strict_bounded_integer(value: object) -> None:
    with pytest.raises((MemoryValidationError, TypeError)):
        validate_recall_policy_version(value)
    with pytest.raises((MemoryValidationError, TypeError)):
        RecallEligibilityPolicyV1(value)  # type: ignore[arg-type]


def test_coerce_recall_policy_accepts_none_int_and_record_only() -> None:
    assert coerce_recall_policy(None) == RecallEligibilityPolicyV1(1)
    assert coerce_recall_policy(3) == RecallEligibilityPolicyV1(3)
    record = RecallEligibilityPolicyV1(2)
    assert coerce_recall_policy(record) is record
    with pytest.raises(TypeError):
        coerce_recall_policy("2")
    with pytest.raises(TypeError):
        coerce_recall_policy(True)


def test_policy_state_view_is_bounded_and_reports_alignment() -> None:
    aligned = RecallPolicyStateV1(
        1, recall_policy_id(1), RECALL_POLICY_HASH_V1, 1, RECALL_POLICY_HASH_V1
    )
    assert aligned.policy_changed is False
    assert aligned.to_json()["policy_changed"] is False
    drifted = RecallPolicyStateV1(
        2, recall_policy_id(2), recall_policy_hash(2), 4, RECALL_POLICY_HASH_V1
    )
    assert drifted.policy_changed is True
    with pytest.raises(MemoryValidationError, match="recall_policy_id_invalid"):
        RecallPolicyStateV1(2, recall_policy_id(1), recall_policy_hash(2), 1, RECALL_POLICY_HASH_V1)
    with pytest.raises(MemoryValidationError, match="recall_policy_hash_invalid"):
        RecallPolicyStateV1(1, recall_policy_id(1), recall_policy_hash(2), 1, RECALL_POLICY_HASH_V1)
    with pytest.raises(MemoryValidationError, match="authority_epoch_invalid"):
        RecallPolicyStateV1(1, recall_policy_id(1), RECALL_POLICY_HASH_V1, 0, RECALL_POLICY_HASH_V1)
    with pytest.raises(MemoryValidationError, match="authority_policy_hash_invalid"):
        RecallPolicyStateV1(1, recall_policy_id(1), RECALL_POLICY_HASH_V1, 1, "not-a-digest")


def test_validation_reason_codes_are_stable_sorted_and_one_to_one() -> None:
    assert MEMORY_MUTATION_VALIDATION_REASON_CODES == tuple(
        sorted(MEMORY_MUTATION_VALIDATION_REASON_CODES)
    )
    assert len(set(MEMORY_MUTATION_VALIDATION_REASON_CODES)) == 6
    assert all(
        code.startswith("mutation_contest_")
        for code in MEMORY_MUTATION_VALIDATION_REASON_CODES
    )
    # 0.6.31 的两个泛化码本身不是精确码。
    for legacy in (
        MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE,
        MEMORY_MUTATION_LEGACY_VALIDATION_REASON_CODE,
    ):
        assert legacy not in MEMORY_MUTATION_VALIDATION_REASON_CODES
        assert specific_validation_reason_code(legacy) is None
    for code in MEMORY_MUTATION_VALIDATION_REASON_CODES:
        assert specific_validation_reason_code(code) == code
    assert specific_validation_reason_code("evidence_authority_rejected") is None


def _note(**overrides: object) -> MemoryMutationValidationNoteV1:
    fields: dict[str, object] = {
        "rejection_id": "rejection-1",
        "rejection_hash": "a" * 64,
        "plan_id": "plan-1",
        "plan_hash": "b" * 64,
        "idempotency_key": "key-1",
        "base_revision": 2,
        "reason_code": "mutation_contest_nested_group_rejected",
        "apply_result_id": "result-1",
        "apply_result_hash": "c" * 64,
        "rejected_at": 20.0,
    }
    fields.update(overrides)
    return MemoryMutationValidationNoteV1(**fields)  # type: ignore[arg-type]


def test_validation_note_is_bounded() -> None:
    note = _note()
    assert note.to_json()["reason_code"] == "mutation_contest_nested_group_rejected"
    assert _note(apply_result_id=None, apply_result_hash=None).apply_result_id is None
    with pytest.raises(MemoryValidationError, match="reason_code_invalid"):
        _note(reason_code=MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE)
    with pytest.raises(MemoryValidationError, match="apply_result_binding_invalid"):
        _note(apply_result_hash=None)
    with pytest.raises(MemoryValidationError, match="rejection_hash_invalid"):
        _note(rejection_hash="short")
    with pytest.raises(MemoryValidationError, match="base_revision_invalid"):
        _note(base_revision=0)


def _candidate(lane_ranks: tuple[tuple[str, int], ...], ref: str = "memory-1") -> RecallCandidate:
    return RecallCandidate(
        source_kind="cognitive_memory",
        source_ref=ref,
        source_revision=1,
        memory_type="semantic",
        public_payload={"subject_entity": "user:self"},
        source_content_hash="d" * 64,
        effective_privacy_class="PERSONAL",
        information_attributes=(),
        evidence_manifest_hash="e" * 64,
        source_task_scope_ids=(),
        active_task_scope_id=None,
        source_time=10.0,
        authority_expires_at=100.0,
        lane_ranks=lane_ranks,
    )


class _Wire:
    def __init__(self, item_id: str, ordinal: int) -> None:
        self.item_id = item_id
        self.ordinal = ordinal


def test_lane_order_is_frozen_and_matches_the_rrf_weight_order() -> None:
    assert EXECUTED_LANE_WITNESS_VERSION == 1
    assert EXECUTED_LANE_ORDER == ("vector", "full_text", "entity", "task_scope", "temporal")
    assert set(EXECUTED_LANE_ORDER) == set(RRF_WEIGHTS)
    assert EXECUTED_LANE_ORDER == tuple(
        sorted(RRF_WEIGHTS, key=lambda lane: (-RRF_WEIGHTS[lane], lane))
    )


def test_lane_witnesses_report_the_lanes_that_actually_produced_each_item() -> None:
    candidates = (
        _candidate((("full_text", 1), ("vector", 2)), "memory-1"),
        _candidate((("temporal", 3),), "memory-2"),
    )
    wires = (_Wire("recall-item:x:1", 1), _Wire("recall-item:x:2", 2))
    witnesses = lane_witnesses(wires, candidates)
    assert [w.item_id for w in witnesses] == ["recall-item:x:1", "recall-item:x:2"]
    # 冻结序：vector 在 full_text 之前，与 lane_ranks 的输入顺序无关。
    assert witnesses[0].lanes == ("vector", "full_text")
    assert witnesses[0].lane_ranks == (("vector", 2), ("full_text", 1))
    assert witnesses[0].matched_lane_count == candidates[0].matched_lane_count == 2
    assert witnesses[1].lanes == ("temporal",)
    assert executed_lanes(witnesses) == ("vector", "full_text", "temporal")
    assert executed_lanes(()) == ()
    assert isinstance(witnesses[0], TypedRecallLaneWitnessV1)


def test_execution_lane_fields_are_additive_with_empty_defaults() -> None:
    fields = tuple(TypedRecallExecution.__dataclass_fields__)
    assert fields[:7] == (
        "decision",
        "result",
        "candidate_query_started",
        "candidate_query_count",
        "replayed",
        "unsupported_capabilities",
        "degradation_codes",
    )
    assert fields[7:] == ("item_lane_witnesses", "executed_lanes")
    execution = TypedRecallExecution(object(), object(), False, 0, True)  # type: ignore[arg-type]
    assert execution.item_lane_witnesses == () and execution.executed_lanes == ()
