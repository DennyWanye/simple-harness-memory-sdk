"""simple_harness_memory — 认知记忆 SDK。

公共 API：
    MemoryManager   — 统一入口，管理全部子系统
    MemoryBackend   — 后端抽象接口（Port）
    WorldModelPort  — 世界对象抽象接口

数据模型：
    Message, Fact, Hit, DigitalTwin
"""

from typing import TYPE_CHECKING

from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.audit import (
    AuditAccessAuthorityPort,
    AuditAccessAuthorityRefV1,
    AuditAggregateMetricsV1,
    AuditTraceCursor,
    AuditTraceItem,
    AuditTraceLineageRef,
    AuditTracePage,
    AuditTraceQuery,
    AuditTraceSelector,
    CanonicalStateManifestAccessV1,
    CanonicalStateManifestV1,
    CanonicalStateTableRootV1,
)
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryValidationError,
)
from simple_harness_memory.core.evidence import (
    EvidenceIngestionReceipt,
    EvidenceSourceAdmissionReceipt,
    IngestedEvidenceRecord,
)
from simple_harness_memory.core.history import (
    HistoryBinding,
    HistoryEvidenceBinding,
    HistoryRecallBinding,
    HistoryShortHorizonBinding,
    HistoryProcedureDraftBinding,
    HistoryVisibilityItem,
    HistoryVisibilitySnapshot,
)
from simple_harness_memory.core.history_sources import (
    HistoryForgetCutReceipt,
    HistorySourceAuthorityPort,
    HistorySourceNamespace,
    HistorySourceOriginReceipt,
)
from simple_harness_memory.core.identity import (
    ExportPage,
    MemoryPrincipal,
    MemoryScope,
    PrincipalRegistrationReceipt,
    PrivacyReceipt,
    ScopeKind,
)
from simple_harness_memory.core.jobs import (
    AnalysisLineage,
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)
from simple_harness_memory.core.lifecycle_results import (
    LifecycleApplyOutcome,
    ProcedureObservationApplyResult,
    ProspectiveSignalApplyResult,
)
from simple_harness_memory.core.procedure_use import ProcedureUseTarget, PROCEDURE_OBSERVATION_RECOVERY_VERSION
from simple_harness_memory.core.procedure_operation_observation import (
    ProcedureOperationObservationV1, PreparedProcedureObservation,
)
from simple_harness_memory.core.manager import (
    MemoryManager,
    build_human_memory_v6,
    build_human_memory_v7,
)
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    Hit,
    MemoryApplyResult,
    Message,
)
from simple_harness_memory.core.prospective_settlement import RegistrationRequiredView, ProspectiveInvalidationNotRequiredReceipt
from simple_harness_memory.core.prospective_settlement_observation import ProspectiveInvalidationSettlementObservationV1
from simple_harness_memory.migrations.settlement_upgrade import (
    ProspectiveSettlementSchemaUpgradeReceipt, migrate_human_memory_v7_2_to_v7_3,
)
from simple_harness_memory.core.prospective_sources_v2 import (
    MutationTargetSource, ProspectiveSignalTargetSource, ProspectiveOutboxSourceViewV2,
)
from simple_harness_memory.core.prospective_source_observation_v2 import ProspectiveSourceReadObservationV2
from simple_harness_memory.core.prospective_sources import ProspectiveOutboxSourceView
from simple_harness_memory.core.prospective_source_observation import ProspectiveSourceReadObservationV1
from simple_harness_memory.core.mutation_receipts import (
    MemoryMutationCommittedOperationView,
    MemoryMutationReceiptView,
)
from simple_harness_memory.core.mutations import (
    EffectiveInformationClassification,
    InformationClassificationPolicy,
)
from simple_harness_memory.core.occurrence import (
    OccurrenceInboxEntryV1,
    OccurrenceInboxPageV1,
    OutboxEntryV1,
    OutboxPageV1,
)
from simple_harness_memory.core.operation_audit import (
    MemoryOperationObservationContext,
    MemoryOperationObservationV1,
    OperationAuditItemV1,
    OperationAuditExpectation,
    OperationAuditCursor,
    OperationAuditCoverage,
    OperationAuditExpectationResult,
    OperationAuditPage,
    operation_audit_ref_hash,
)
from simple_harness_memory.core.port import CognitiveMemoryBackend, MemoryBackend
from simple_harness_memory.core.recall import TypedRecallExecution, TypedRecallRejectionV1
from simple_harness_memory.core.short_horizon import (
    ShortHorizonDegradationCode,
    ShortHorizonGenerationBuildResult,
    ShortHorizonProjectionBuildResult,
    ShortHorizonRecallHit,
    ShortHorizonRecallResult,
)
from simple_harness_memory.core.short_sources import (
    ShortHorizonSourceItem,
    ShortHorizonSourceRef,
    ShortHorizonSourceSnapshot,
)
from simple_harness_memory.core.suppression import (
    OrdinaryMemoryPurpose,
    SealedAuditAccessDecision,
    SealedAuditAccessDenied,
    SealedAuditAccessReceipt,
    SealedAuditPurpose,
    SuppressionAction,
    SuppressionDecision,
    SuppressionRequest,
    SuppressionRevokeRequest,
    SuppressionScopeKind,
)
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.world.port import WorldModelPort

if TYPE_CHECKING:
    from simple_harness_memory.cognitive.twin_builder import (
        TwinGraphEdge,
        TwinGraphNode,
        TwinGraphSourceRef,
        TwinGraphView,
    )

_TWIN_GRAPH_EXPORTS = frozenset(
    {"TwinGraphEdge", "TwinGraphNode", "TwinGraphSourceRef", "TwinGraphView"}
)


def __getattr__(name: str) -> object:
    if name in _TWIN_GRAPH_EXPORTS:
        from simple_harness_memory.cognitive import twin_builder

        return getattr(twin_builder, name)
    raise AttributeError(name)

__all__ = [
    "HistoryBinding",
    "HistoryForgetCutReceipt",
    "HistorySourceAuthorityPort",
    "HistorySourceNamespace",
    "HistorySourceOriginReceipt",
    "HistoryEvidenceBinding",
    "HistoryRecallBinding",
    "HistoryShortHorizonBinding",
    "HistoryProcedureDraftBinding",
    "ProcedureDraftCandidate",
    "ProcedureDraftPage",
    "HistoryVisibilityItem",
    "HistoryVisibilitySnapshot",
    "ShortHorizonSourceItem",
    "ShortHorizonSourceRef",
    "ShortHorizonSourceSnapshot",
    "MemoryManager",
    "build_human_memory_v7",
    "build_human_memory_v6",
    "AnalysisLineage",
    "DurableMemoryJobRunner",
    "MemoryJobWorkerConfig",
    "WorkerRunOutcome",
    "OccurrenceInboxEntryV1",
    "OccurrenceInboxPageV1",
    "OutboxEntryV1",
    "OutboxPageV1",
    "AuditAccessAuthorityPort",
    "AuditAccessAuthorityRefV1",
    "AuditAggregateMetricsV1",
    "AuditTraceCursor",
    "AuditTraceItem",
    "AuditTraceLineageRef",
    "AuditTracePage",
    "AuditTraceQuery",
    "AuditTraceSelector",
    "CanonicalStateManifestAccessV1",
    "CanonicalStateManifestV1",
    "CanonicalStateTableRootV1",
    "SealedAuditAccessDecision",
    "SealedAuditAccessDenied",
    "SealedAuditAccessReceipt",
    "SealedAuditPurpose",
    "OrdinaryMemoryPurpose",
    "SuppressionAction",
    "SuppressionDecision",
    "SuppressionRequest",
    "SuppressionRevokeRequest",
    "SuppressionScopeKind",
    "EvidenceIngestionReceipt",
    "EvidenceSourceAdmissionReceipt",
    "IngestedEvidenceRecord",
    "EffectiveInformationClassification",
    "InformationClassificationPolicy",
    "MemoryBackend",
    "CognitiveMemoryBackend",
    "TypedRecallExecution",
    "TypedRecallRejectionV1",
    "MemoryOperationObservationContext",
    "MemoryOperationObservationV1",
    "OperationAuditItemV1",
    "OperationAuditExpectation",
    "OperationAuditCursor",
    "OperationAuditCoverage",
    "OperationAuditExpectationResult",
    "OperationAuditPage",
    "operation_audit_ref_hash",
    "TwinGraphEdge",
    "TwinGraphNode",
    "TwinGraphSourceRef",
    "TwinGraphView",
    "WorldModelPort",
    "Message",
    "Fact",
    "Hit",
    "DigitalTwin",
    "MemoryApplyResult",
    "MemoryMutationCommittedOperationView",
    "MemoryMutationReceiptView",
    "ProspectiveOutboxSourceView",
    "ProspectiveOutboxSourceViewV2",
    "MutationTargetSource",
    "ProspectiveSignalTargetSource",
    "RegistrationRequiredView",
    "ProspectiveInvalidationNotRequiredReceipt",
    "ProspectiveInvalidationSettlementObservationV1",
    "ProspectiveSettlementSchemaUpgradeReceipt",
    "migrate_human_memory_v7_2_to_v7_3",
    "ProspectiveSourceReadObservationV2",
    "ProspectiveSourceReadObservationV1",
    "BoundedRecallResult",
    "MemoryResourceBounds",
    "MemoryPrincipal",
    "MemoryScope",
    "ScopeKind",
    "ExportPage",
    "PrincipalRegistrationReceipt",
    "PrivacyReceipt",
    "MemoryOwnershipConflict",
    "MemoryIdempotencyConflict",
    "MemoryValidationError",
    "LifecycleApplyOutcome",
    "ProcedureObservationApplyResult",
    "ProcedureUseTarget",
    "PROCEDURE_OBSERVATION_RECOVERY_VERSION",
    "ProcedureOperationObservationV1",
    "PreparedProcedureObservation",
    "ProspectiveSignalApplyResult",
    "ShortHorizonDegradationCode",
    "ShortHorizonGenerationBuildResult",
    "ShortHorizonProjectionBuildResult",
    "ShortHorizonRecallHit",
    "ShortHorizonRecallResult",
]

__version__ = "0.6.27"

from simple_harness_memory.core.procedure_discovery import ProcedureDraftCandidate, ProcedureDraftPage
# Bounded current USER input use. Ordinary history/recall policy is unchanged.
from simple_harness_memory.core.input_visibility import (
    CurrentInputBindingV1, CurrentInputAuthorityV1, CurrentInputAuthorityPort,
    CurrentInputVisibilityV1,
)
from simple_harness_memory.core.input_observation import CurrentInputObservationV1
__all__ += ["CurrentInputBindingV1", "CurrentInputAuthorityV1", "CurrentInputAuthorityPort",
    "CurrentInputVisibilityV1", "CurrentInputObservationV1"]
