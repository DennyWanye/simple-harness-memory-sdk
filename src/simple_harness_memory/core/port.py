"""MemoryBackend — 核心抽象接口（Port 模式）。

所有后端实现（SQLite / Mock / Pinecone）都必须实现此接口。
主应用仅依赖此 Port，不依赖具体后端。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from simple_harness_memory.core.models import Fact, FactConflict, Hit, Message
from simple_harness_memory.core.twin import DigitalTwin


class MemoryBackend(ABC):
    """记忆后端抽象接口。"""

    # ── L2: 情景记忆 ────────────────────────────────

    @abstractmethod
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        salience: float = 0.0,
        decay_rate: float = 0.02,
    ) -> int:
        """追加一条消息，返回 message_id。"""

    @abstractmethod
    async def get_recent_messages(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[Message]:
        """获取最近 N 条消息（按时间倒序）。"""

    @abstractmethod
    async def get_message(self, message_id: int) -> Optional[Message]:
        """按 ID 获取单条消息。"""

    # ── L3: 语义记忆 ────────────────────────────────

    @abstractmethod
    async def extract_facts(
        self,
        message_id: int,
        content: str,
        role: str,
    ) -> list[Fact]:
        """从消息内容提取 Facts，自动写入存储，返回提取结果。"""

    @abstractmethod
    async def get_facts(
        self,
        subject: str = "user",
        category: Optional[str] = None,
        active_only: bool = True,
    ) -> list[Fact]:
        """查询 Facts。active_only=True 排除已 superseded/forgotten。"""

    @abstractmethod
    async def forget_fact(self, fact_id: int, reason: str = "") -> bool:
        """显式遗忘一个 Fact（设置 forgotten_at）。返回是否成功。"""

    # ── 数字孪生体 ────────────────────────────────────

    @abstractmethod
    async def get_digital_twin(self, subject: str = "user") -> DigitalTwin:
        """获取或构建数字孪生体。"""

    @abstractmethod
    async def update_digital_twin(self, twin: DigitalTwin) -> None:
        """持久化更新后的孪生体。"""

    @abstractmethod
    async def suggest_questions(self, subject: str = "user") -> list[str]:
        """根据孪生体空白字段，生成主动补全问题。"""

    @abstractmethod
    async def detect_inconsistencies(self, subject: str = "user") -> list[FactConflict]:
        """检测同一 subject 下的矛盾 / 冲突事实。"""

    # ── 混合召回 ─────────────────────────────────────

    @abstractmethod
    async def recall(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[Hit]:
        """RRF 六路混合召回，返回融合排名后的结果。"""

    @abstractmethod
    async def recall_and_reinforce(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[Hit]:
        """RRF 召回并对命中项执行 salience reinforcement（写 last_recalled）。"""

    @abstractmethod
    async def vector_search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Hit]:
        """纯向量语义搜索（不含 RRF 融合）。"""

    # ── 认知维护 ─────────────────────────────────────

    @abstractmethod
    async def daily_decay(self) -> dict[str, int]:
        """运行每日遗忘曲线衰减，返回统计 {decayed: N, forgotten: M}。"""

    @abstractmethod
    async def summarize_old_sessions(
        self,
        older_than_days: int = 7,
        max_sessions: int = 5,
    ) -> dict[str, int]:
        """对旧会话消息进行记忆压缩，返回 {summarized_sessions: N}。"""

    @abstractmethod
    async def record_workspace_action(
        self,
        session_id: str,
        action_type: str,
        payload: dict,
    ) -> None:
        """记录工作记忆动作（文件操作/工具调用等）。"""

    # ── 生命周期 ─────────────────────────────────────

    async def initialize(self) -> None:
        """初始化后端（建表、连接等）。子类可 override。"""

    async def close(self) -> None:
        """关闭连接、释放资源。子类可 override。"""

    async def __aenter__(self) -> "MemoryBackend":
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
