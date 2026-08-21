"""simple_harness_memory.core — 核心接口与数据模型。"""

from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.models import (
    BoundedRecallResult,
    Fact,
    Hit,
    MemoryApplyResult,
    Message,
)
from simple_harness_memory.core.port import MemoryBackend
from simple_harness_memory.core.twin import DigitalTwin

__all__ = [
    "MemoryManager",
    "MemoryBackend",
    "Message",
    "Fact",
    "Hit",
    "DigitalTwin",
    "MemoryApplyResult",
    "BoundedRecallResult",
]
