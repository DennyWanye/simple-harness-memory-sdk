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
    IngestedEvidenceRecord,
)
from simple_harness_memory.core.identity import (
    ExportPage,
    MemoryPrincipal,
    MemoryScope,
    PrivacyReceipt,
    ScopeKind,
)
from simple_harness_memory.core.lifecycle_results import (
    LifecycleApplyOutcome,
    ProcedureObservationApplyResult,
    ProspectiveSignalApplyResult,
)
from simple_harness_memory.core.jobs import (
    DurableMemoryJobRunner,
    MemoryJobWorkerConfig,
    WorkerRunOutcome,
)
from simple_harness_memory.core.manager import (
    MemoryManager,
    build_human_memory_v6,
    build_human_memory_v7,
)
from simple_harness_memory.core.occurrence import (
    OccurrenceInboxEntryV1,
    OccurrenceInboxPageV1,
    OutboxEntryV1,
    OutboxPageV1,
)
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    Hit,
    MemoryApplyResult,
    Message,
)
from simple_harness_memory.core.mutation_receipts import (
    MemoryMutationCommittedOperationView,
    MemoryMutationReceiptView,
)
from simple_harness_memory.core.mutations import (
    EffectiveInformationClassification,
    InformationClassificationPolicy,
)
from simple_harness_memory.core.port import CognitiveMemoryBackend, MemoryBackend
from simple_harness_memory.core.recall import TypedRecallExecution
from simple_harness_memory.core.short_horizon import (
    ShortHorizonDegradationCode,
    ShortHorizonGenerationBuildResult,
    ShortHorizonProjectionBuildResult,
    ShortHorizonRecallHit,
    ShortHorizonRecallResult,
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
    "MemoryManager",
    "build_human_memory_v7",
    "build_human_memory_v6",
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
    "IngestedEvidenceRecord",
    "EffectiveInformationClassification",
    "InformationClassificationPolicy",
    "MemoryBackend",
    "CognitiveMemoryBackend",
    "TypedRecallExecution",
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
    "BoundedRecallResult",
    "MemoryResourceBounds",
    "MemoryPrincipal",
    "MemoryScope",
    "ScopeKind",
    "ExportPage",
    "PrivacyReceipt",
    "MemoryOwnershipConflict",
    "MemoryIdempotencyConflict",
    "MemoryValidationError",
    "LifecycleApplyOutcome",
    "ProcedureObservationApplyResult",
    "ProspectiveSignalApplyResult",
    "ShortHorizonDegradationCode",
    "ShortHorizonGenerationBuildResult",
    "ShortHorizonProjectionBuildResult",
    "ShortHorizonRecallHit",
    "ShortHorizonRecallResult",
]

__version__ = "0.6.0"
