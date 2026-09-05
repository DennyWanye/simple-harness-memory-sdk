from __future__ import annotations

import json
import tomllib
from pathlib import Path

import simple_harness_memory
import simple_harness_memory.migrations as migrations

ROOT = Path(__file__).resolve().parents[2]


def test_public_api_0_6_11_preserves_privacy_and_adds_operation_audit() -> None:
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
        )
    }
    for version, snapshot in snapshots.items():
        assert snapshot["package"] == "simple-harness-memory-sdk"
        assert snapshot["version"] == version
    current = snapshots["0.6.11"]
    assert simple_harness_memory.__version__ == "0.6.11"
    assert current["root"] == sorted(simple_harness_memory.__all__)
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
    assert current["migrations"] == sorted(migrations.__all__)
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


def test_0_6_8_candidate_sources_and_docs_are_consistent() -> None:
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
    assert "当前 source candidate：**0.6.10**" in readme
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
