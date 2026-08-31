"""simple_harness_memory.core — 核心接口与数据模型。"""

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

__all__ = [
    "MemoryManager",
    "MemoryBackend",
    "CognitiveMemoryBackend",
    "TypedRecallExecution",
    "Message",
    "Fact",
    "Hit",
    "DigitalTwin",
    "MemoryApplyResult",
    "BoundedRecallResult",
    "ShortHorizonDegradationCode",
    "ShortHorizonGenerationBuildResult",
    "ShortHorizonProjectionBuildResult",
    "ShortHorizonRecallHit",
    "ShortHorizonRecallResult",
]
