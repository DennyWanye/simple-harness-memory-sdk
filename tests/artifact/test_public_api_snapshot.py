from __future__ import annotations

import inspect
import json
import tomllib
from pathlib import Path

import simple_harness_memory
import simple_harness_memory.migrations as migrations

ROOT = Path(__file__).resolve().parents[2]


def test_historical_public_api_0_6_12_preserves_0_6_11_public_contract() -> None:
    snapshots = {
        version: json.loads(Path(__file__).with_name(f"public-api-{version}.json").read_text())
        for version in (
            "0.5.2",
            "0.6.0",
            "0.6.1",
            "0.6.2",
            "0.6.3",
            "0.6.4",
            "0.6.5",
            "0.6.6",
            "0.6.7",
            "0.6.8",
            "0.6.9",
            "0.6.10",
            "0.6.11",
            "0.6.12",
        )
    }
    for version, snapshot in snapshots.items():
        assert snapshot["package"] == "simple-harness-memory-sdk"
        assert snapshot["version"] == version
    current = snapshots["0.6.12"]
    assert {k: v for k, v in current.items() if k != "version"} == {
        k: v for k, v in snapshots["0.6.11"].items() if k != "version"
    }
    assert current["root"] == sorted(
        [
            *snapshots["0.6.10"]["root"],
            *[
                "MemoryOperationObservationContext",
                "MemoryOperationObservationV1",
                "OperationAuditItemV1",
                "OperationAuditExpectation",
                "OperationAuditCursor",
                "OperationAuditCoverage",
                "OperationAuditExpectationResult",
                "OperationAuditPage",
                "operation_audit_ref_hash",
            ],
        ]
    )
    assert callable(simple_harness_memory.MemoryManager.read_operation_audit)
    assert snapshots["0.6.10"]["root"] == sorted(
        [
            *snapshots["0.6.9"]["root"],
            "HistoryForgetCutReceipt",
            "HistorySourceAuthorityPort",
            "HistorySourceNamespace",
            "HistorySourceOriginReceipt",
        ]
    )
    assert current["migrations"] == snapshots["0.6.9"]["migrations"]
    assert snapshots["0.6.9"]["root"] == sorted(
        [
            *snapshots["0.6.8"]["root"],
            "ShortHorizonSourceItem",
            "ShortHorizonSourceRef",
            "ShortHorizonSourceSnapshot",
        ]
    )
    assert snapshots["0.6.8"]["root"] == sorted(
        [*snapshots["0.6.7"]["root"], "EvidenceSourceAdmissionReceipt"]
    )
    assert snapshots["0.6.7"]["root"] == sorted(
        [*snapshots["0.6.6"]["root"], "HistoryShortHorizonBinding"]
    )
    history_exports = {
        "HistoryBinding",
        "HistoryEvidenceBinding",
        "HistoryRecallBinding",
        "HistoryVisibilityItem",
        "HistoryVisibilitySnapshot",
    }
    assert set(snapshots["0.6.6"]["root"]) - set(snapshots["0.6.5"]["root"]) == history_exports
    assert set(snapshots["0.6.5"]["root"]) < set(current["root"])
    assert set(snapshots["0.6.5"]["root"]) - set(snapshots["0.6.4"]["root"]) == {
        "TypedRecallRejectionV1"
    }
    assert set(snapshots["0.6.4"]["root"]) < set(snapshots["0.6.5"]["root"])
    for version in ("0.6.2", "0.6.3", "0.6.4"):
        assert snapshots[version]["root"] == snapshots["0.6.1"]["root"]
    assert set(snapshots["0.6.0"]["root"]) < set(snapshots["0.6.1"]["root"])
    assert set(snapshots["0.6.1"]["root"]) - set(snapshots["0.6.0"]["root"]) == {
        "AnalysisLineage",
        "PrincipalRegistrationReceipt",
    }
    for version in ("0.6.0", "0.6.1", "0.6.2", "0.6.3", "0.6.4", "0.6.5"):
        assert {k: v for k, v in current.items() if k not in {"version", "root", "migrations"}} == {
            k: v
            for k, v in snapshots[version].items()
            if k not in {"version", "root", "migrations"}
        }
    assert current["migrations"] == sorted(
        [
            *snapshots["0.6.8"]["migrations"],
            "HumanMemorySchemaUpgradeReceipt",
            "migrate_human_memory_v7_to_v7_2",
        ]
    )
    assert snapshots["0.6.8"]["migrations"] == snapshots["0.5.2"]["migrations"]
    assert "ConversationMemoryAdapter" not in current["root"]


def test_0_6_1_public_surface_is_reachable_from_0_6_8_root() -> None:
    """0.6.1 §8 新增公共面在 0.6.6 仍可达：根导出 + 方法/关键字/函数（只读核对）。"""

    import inspect

    from simple_harness_memory import (
        AnalysisLineage,
        MemoryManager,
        PrincipalRegistrationReceipt,
    )
    from simple_harness_memory.core.jobs import (
        AnalysisBatchClaim,
        current_analysis_apply_head,
    )

    assert AnalysisLineage.__module__.endswith("core.jobs")
    assert PrincipalRegistrationReceipt.__module__.endswith("core.identity")
    assert callable(MemoryManager.register_principal_owner)
    assert (
        "supported_filter_policies"
        in inspect.signature(MemoryManager.build_human_memory_v7).parameters
    )
    assert (
        "analysis_lineage" in inspect.signature(MemoryManager.ingest_committed_evidence).parameters
    )
    assert current_analysis_apply_head() is None
    assert "analysis_apply_head" in AnalysisBatchClaim.__dataclass_fields__


def test_root_exports_construct_public_facade_contracts() -> None:
    from simple_harness import InformationAttribute, PrivacyClass

    from simple_harness_memory import (
        EffectiveInformationClassification,
        EvidenceIngestionReceipt,
        InformationClassificationPolicy,
        IngestedEvidenceRecord,
        MemoryMutationCommittedOperationView,
        MemoryMutationReceiptView,
        SealedAuditPurpose,
        SuppressionDecision,
        SuppressionRequest,
        SuppressionRevokeRequest,
        SuppressionScopeKind,
    )

    request = SuppressionRequest(
        "root-suppress-1",
        "actor-1",
        SuppressionScopeKind.EVIDENCE,
        "evidence-1",
        "user_forget",
        1.0,
    )
    revoke = SuppressionRevokeRequest(
        "root-revoke-1",
        "actor-1",
        "directive-1",
        "user_restore",
        2.0,
    )
    assert request.scope_kind is SuppressionScopeKind.EVIDENCE
    assert revoke.directive_id == "directive-1"
    assert SealedAuditPurpose.EVIDENCE_AUDIT.value == "sealed_evidence_audit"
    assert SuppressionDecision.__module__.endswith("core.suppression")
    assert EvidenceIngestionReceipt.__module__.endswith("core.evidence")
    assert IngestedEvidenceRecord.__module__.endswith("core.evidence")
    policy = InformationClassificationPolicy(
        policy_id="root-policy",
        policy_version="1",
        authority_ref="host-classification-authority",
        required_privacy_class=PrivacyClass.PERSONAL,
        required_information_attributes=(InformationAttribute.PREFERENCE,),
    )
    effective = EffectiveInformationClassification(
        PrivacyClass.SENSITIVE,
        (InformationAttribute.HEALTH,),
    )
    assert policy.required_privacy_class is PrivacyClass.PERSONAL
    assert policy.required_information_attributes == (InformationAttribute.PREFERENCE,)
    assert effective.privacy_class is PrivacyClass.SENSITIVE
    operation = MemoryMutationCommittedOperationView(
        operation_id="create-1",
        memory_id="memory-1",
        revision=1,
        memory_type="semantic",
        semantic_kind="claim",
        content_hash="a" * 64,
        effective_privacy_class="personal",
        epistemic_status="explicit_user",
        evidence_ids=("evidence-1",),
        decision_hash="b" * 64,
    )
    receipt = MemoryMutationReceiptView(
        receipt_id="receipt-1",
        receipt_hash="c" * 64,
        plan_id="plan-1",
        plan_hash="d" * 64,
        apply_mode="strict_atomic",
        operations=(operation,),
    )
    assert receipt.to_json()["operations"] == [operation.to_json()]


def test_current_candidate_sources_and_docs_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == (
        "src/simple_harness_memory/__init__.py"
    )
    assert pyproject["project"]["optional-dependencies"]["harness"] == [
        "simple-harness-sdk>=0.7,<0.8"
    ]
    assert "simple-harness-sdk>=0.7,<0.8" in pyproject["project"]["dependencies"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "当前 source candidate：**0.6.33**" in readme
    assert "已发布 fallback 为 0.5.1" in readme
    assert "## [0.6.6] - 2026-09-05" in changelog
    assert "## [0.6.5] - 2026-09-05" in changelog
    assert "## [0.6.2] - 2026-09-03" in changelog
    assert "## [0.6.1] - 2026-09-02" in changelog
    assert "## [0.6.0] - 2026-08-30" in changelog
    assert "## [0.5.1] - 2026-08-24" in changelog
    assert "## [0.5.0] - 2026-08-23" in changelog
    assert "## [0.4.0] - 2026-08-22" in changelog
    assert "version=0.5.1" in (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")


def test_public_api_0_6_33_keeps_0_6_19_surface() -> None:
    previous = json.loads(Path(__file__).with_name("public-api-0.6.19.json").read_text())
    for version in ("0.6.20", "0.6.21", "0.6.22", "0.6.23", "0.6.24", "0.6.25", "0.6.26",
                    "0.6.27", "0.6.28", "0.6.29", "0.6.30", "0.6.31", "0.6.32",
                    "0.6.33"):
        snapshot = json.loads(Path(__file__).with_name(f"public-api-{version}.json").read_text())
        assert snapshot["version"] == version
        assert {k: v for k, v in previous.items() if k != "version"} == {
            k: v for k, v in snapshot.items() if k != "version"
        }
    assert simple_harness_memory.__version__ == "0.6.33"
    assert snapshot["root"] == sorted(simple_harness_memory.__all__)
    assert len(snapshot["root"]) == len(set(snapshot["root"]))
    assert snapshot["migrations"] == sorted(migrations.__all__)
    assert all(hasattr(simple_harness_memory, name) for name in snapshot["root"])
    for method in ("check_current_input_visibility", "discover_procedure_drafts",
                   "read_procedure_use_target", "prepare_procedure_observation",
                   "record_procedure_observation"):
        assert callable(getattr(simple_harness_memory.MemoryManager, method))
    assert simple_harness_memory.PROCEDURE_OBSERVATION_RECOVERY_VERSION == 1
    # 0.6.23：根导出零增减；新增方法只做可达性只读核对。
    assert callable(simple_harness_memory.MemoryManager.rebuild_cognitive_vector_generation)
    assert "short_horizon_embedder" in inspect.signature(
        simple_harness_memory.MemoryManager.build_human_memory_v7
    ).parameters
    assert "cognitive_vector_embedder" not in inspect.signature(
        simple_harness_memory.MemoryManager.build_human_memory_v7
    ).parameters
    # 0.6.24：构建失败的有码异常不进根导出，经 core.errors 可达。
    from simple_harness_memory.core.errors import CognitiveVectorGenerationFailed

    assert issubclass(CognitiveVectorGenerationFailed, RuntimeError)
    assert "CognitiveVectorGenerationFailed" not in snapshot["root"]
    # 0.6.25：发现面白名单常量留在 core 层，不进根导出；候选 DTO 与 hash 域不变。
    from simple_harness_memory.core.procedure_discovery import DISCOVERABLE_LIFECYCLE_STATES

    assert DISCOVERABLE_LIFECYCLE_STATES == ("draft", "eligible_for_activation", "active", "reinforced")
    assert "DISCOVERABLE_LIFECYCLE_STATES" not in snapshot["root"]
    assert simple_harness_memory.ProcedureDraftCandidate(
        "memory-1", 1, "n", ("s",), ("a",), "low", "active", "epoch-1", "unbound:procedure-applicability:v2", "0" * 64
    ).lifecycle_state == "active"
    # 0.6.26：prospective 触发渲染与文本格式版本留在 features 层，不进根导出；公开 payload 不变。
    from simple_harness_memory.features.cognitive_vector import (
        COGNITIVE_TEXT_FORMAT_VERSION,
        cognitive_text_supplement,
        prospective_trigger_text,
    )

    assert COGNITIVE_TEXT_FORMAT_VERSION == 2
    assert callable(prospective_trigger_text) and callable(cognitive_text_supplement)
    assert not {
        "COGNITIVE_TEXT_FORMAT_VERSION",
        "cognitive_text_supplement",
        "prospective_trigger_text",
    } & set(snapshot["root"])
    # 0.6.27：typed recall 的分阶段超时异常留在 core.errors，不进根导出；
    # 它仍是 TimeoutError 的子类，Host 到 context_route_recall_timeout 的映射逐字不变。
    from simple_harness_memory.core.errors import TypedRecallDeadlineExceeded

    assert "TypedRecallDeadlineExceeded" not in simple_harness_memory.__all__
    assert issubclass(TypedRecallDeadlineExceeded, TimeoutError)
    assert str(TypedRecallDeadlineExceeded("admit_write_lock")) == "DEADLINE_EXCEEDED"
    assert TypedRecallDeadlineExceeded("admit_write_lock").stage == "admit_write_lock"
    # 0.6.29：用途围栏的降级码与只读视图留在 core.recall_context_use，不进根导出；
    # 收据类型 RecallContextUseReceiptV1 属于冻结的 Harness SDK（from_json 走 _exact_keys），
    # 因此「哪两个 epoch」只能靠既有的两条不可变行导出，不新增任何 DDL。
    from simple_harness_memory.core.recall_context_use import (
        RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,
        RECALL_CONTEXT_USE_REASON_CODES,
        RecallContextUseAuthorityNoteV1,
    )

    assert RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED == "authority_epoch_advanced"
    assert RECALL_CONTEXT_USE_REASON_CODES == (RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED,)
    assert not {
        "RECALL_CONTEXT_USE_AUTHORITY_EPOCH_ADVANCED",
        "RECALL_CONTEXT_USE_REASON_CODES",
        "RecallContextUseAuthorityNoteV1",
    } & set(snapshot["root"])
    assert callable(
        simple_harness_memory.MemoryManager.read_recall_context_use_authority_notes
    )
    # 0.6.31：争议槽位文本留在 features.conflict_slot，不进根导出；公开 payload、
    # 决定/结果/收据的 hash 域与 Harness v4 wire 形状零变化（0.6.30 由另一分支并入，
    # 版本序由合并时统一）。
    from simple_harness_memory.features.conflict_slot import (
        CONFLICT_SLOT_TEXT_VERSION,
        contested_slot_text,
    )

    assert CONFLICT_SLOT_TEXT_VERSION == 1 and callable(contested_slot_text)
    assert not {"CONFLICT_SLOT_TEXT_VERSION", "contested_slot_text"} & set(snapshot["root"])
    # 0.6.32：矩阵公共见证四增量。新符号全部留在 core.* / features.*，**不进根导出**；
    # 新增的 MemoryManager 方法与 TypedRecallExecution 的两个默认空字段是纯增量，
    # 快照的 root/migrations/removed_public_methods 三个集合逐字未变。
    from simple_harness_memory.core.mutation_rejections import (
        MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE,
        MEMORY_MUTATION_VALIDATION_REASON_CODES,
        MemoryMutationValidationNoteV1,
    )
    from simple_harness_memory.core.recall import (
        EXECUTED_LANE_ORDER,
        EXECUTED_LANE_WITNESS_VERSION,
        TypedRecallExecution,
        TypedRecallLaneWitnessV1,
    )
    from simple_harness_memory.core.recall_policy import (
        DEFAULT_RECALL_POLICY_VERSION,
        RECALL_POLICY_CHANGED_EVENT_KIND,
        RECALL_POLICY_HASH_V1,
        RecallEligibilityPolicyV1,
        RecallPolicyStateV1,
        recall_policy_hash,
    )

    assert DEFAULT_RECALL_POLICY_VERSION == 1
    assert recall_policy_hash(1) == RECALL_POLICY_HASH_V1 == (
        "c27604aa354d34f9597a62873a2a53547df192b74c267c569fae445d23c7fc04"
    )
    assert RECALL_POLICY_CHANGED_EVENT_KIND == "recall_policy_changed"
    assert len(MEMORY_MUTATION_VALIDATION_REASON_CODES) == 6
    assert MEMORY_MUTATION_LEGACY_CONTEST_REASON_CODE == "mutation_contest_rejected"
    assert EXECUTED_LANE_WITNESS_VERSION == 1
    assert EXECUTED_LANE_ORDER == ("vector", "full_text", "entity", "task_scope", "temporal")
    assert not {
        "DEFAULT_RECALL_POLICY_VERSION",
        "EXECUTED_LANE_ORDER",
        "EXECUTED_LANE_WITNESS_VERSION",
        "MEMORY_MUTATION_VALIDATION_REASON_CODES",
        "RECALL_POLICY_CHANGED_EVENT_KIND",
        "RECALL_POLICY_HASH_V1",
        "MemoryMutationValidationNoteV1",
        "RecallEligibilityPolicyV1",
        "RecallPolicyStateV1",
        "TypedRecallLaneWitnessV1",
    } & set(snapshot["root"])
    # TypedRecallExecution **是**根导出（0.6.19 起），两个新字段带默认值、排在末尾，
    # 位置式构造与既有 7 参形状逐字不变（与 0.6.30 给 ShortHorizonProjectionBuildResult
    # 追加 split_group_count/truncated_group_count 同一纪律）。
    assert "TypedRecallExecution" in snapshot["root"]
    assert tuple(TypedRecallExecution.__dataclass_fields__)[7:] == (
        "item_lane_witnesses",
        "executed_lanes",
    )
    for method in (
        "cleanup_short_horizon",
        "read_recall_policy",
        "read_memory_mutation_validation_notes",
    ):
        assert callable(getattr(simple_harness_memory.MemoryManager, method))
    assert "recall_policy" in inspect.signature(
        simple_harness_memory.MemoryManager.build_human_memory_v7
    ).parameters
    assert RecallEligibilityPolicyV1().policy_id == "typed-recall-eligibility/v1"
    # 0.6.33：候选收集段耗尽预算的终态修复。新增的 backends.sqlite_tx 是内部原语
    # （backends.* 从来不在公共面上），TypedRecallDeadlineExceeded 仍只经 core.errors
    # 可达且仍是 TimeoutError 子类、``str(exc)`` 仍是 ``DEADLINE_EXCEEDED``；
    # 快照的 root/migrations/removed_public_methods 三个集合逐字未变，无 DDL。
    from simple_harness_memory.backends.sqlite_tx import (
        BEGIN_STATEMENTS,
        begin_transaction,
        rollback_transaction,
    )

    assert callable(begin_transaction) and callable(rollback_transaction)
    assert BEGIN_STATEMENTS == frozenset(
        {"BEGIN", "BEGIN DEFERRED", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE"}
    )
    assert not {
        "BEGIN_STATEMENTS",
        "begin_transaction",
        "rollback_transaction",
    } & set(snapshot["root"])
    assert issubclass(TypedRecallDeadlineExceeded, TimeoutError)
    assert str(TypedRecallDeadlineExceeded("collect_candidates")) == "DEADLINE_EXCEEDED"
    assert TypedRecallDeadlineExceeded("collect_candidates").stage == "collect_candidates"
