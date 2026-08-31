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
from simple_harness_memory.core.errors import (
    MemoryIdempotencyConflict,
    MemoryOwnershipConflict,
    MemoryValidationError,
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
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    Hit,
    MemoryApplyResult,
    Message,
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
