"""simple_harness_memory — 认知记忆 SDK。

公共 API：
    MemoryManager   — 统一入口，管理全部子系统
    MemoryBackend   — 后端抽象接口（Port）
    WorldModelPort  — 世界对象抽象接口

数据模型：
    Message, Fact, Hit, DigitalTwin
"""

from simple_harness_memory.config import MemoryResourceBounds
from simple_harness_memory.core.conversation import (
    ContextPreparationMode,
    ConversationMemoryAdapter,
    ConversationMemoryApplyResult,
    ConversationMemoryApplyStatus,
    ConversationMemoryError,
    ConversationMemoryErrorCode,
    ConversationMemoryIntent,
    ConversationMemoryQueryStatus,
    ConversationMemoryRecallQuery,
    ConversationMemoryRecallResult,
    ConversationMemoryRole,
)
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
from simple_harness_memory.world.port import WorldModelPort

__all__ = [
    "MemoryManager",
    "MemoryBackend",
    "WorldModelPort",
    "Message",
    "Fact",
    "Hit",
    "DigitalTwin",
    "MemoryApplyResult",
    "BoundedRecallResult",
    "MemoryResourceBounds",
    "ConversationMemoryAdapter",
    "ConversationMemoryIntent",
    "ConversationMemoryRecallQuery",
    "ConversationMemoryRecallResult",
    "ConversationMemoryApplyResult",
    "ConversationMemoryRole",
    "ConversationMemoryQueryStatus",
    "ConversationMemoryApplyStatus",
    "ConversationMemoryError",
    "ConversationMemoryErrorCode",
    "ContextPreparationMode",
]

__version__ = "0.3.0"
