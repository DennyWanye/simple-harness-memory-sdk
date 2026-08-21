"""核心数据模型：Message / Fact / Hit。

基于认知科学设计：
- Message 携带 salience（显著性）和 decay_rate（遗忘曲线）
- Fact 按 category 差异化衰减率，支持演化链（superseded_by）
- Hit 携带六路召回信号，用于 RRF 融合
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ─────────────────────────────────────────────
# L2: 情景记忆单元
# ─────────────────────────────────────────────

@dataclass
class Message:
    """单条对话消息，携带认知科学特性。"""

    id: Optional[int]
    user_id: str                # 最高产品主体；不可由 session_id 推导
    session_id: str             # 会话隔离（不同任务互不干扰）
    role: str                   # "user" | "assistant" | "system" | "tool"
    content: str
    created_at: float           # Unix timestamp

    # 认知科学特性
    salience: float = 0.0           # 显著性（每次被召回 +0.05）
    decay_rate: float = 0.02        # 衰减率（Ebbinghaus 遗忘曲线）
    last_recalled: Optional[float] = None  # 最后召回时间（Unix ts）

    # 向量化（延迟填充）
    embedding: Optional[bytes] = None  # BGE-M3 向量，BLOB

    # embedding lineage（embedder 元数据，用于 reindex / 维度一致性）
    embedder_kind: Optional[str] = None
    embedding_dim: Optional[int] = None
    embedding_format_version: Optional[int] = None

    # durable source-event identity
    source_event_id: Optional[str] = None
    payload_hash: Optional[str] = None

    # 压缩元数据
    is_summary: bool = False            # 是否为压缩后的 summary
    summary_of: Optional[str] = None    # summary 覆盖的源消息 ID（JSON list）


# ─────────────────────────────────────────────
# L3: 语义记忆单元
# ─────────────────────────────────────────────

# Fact 分类 → 默认衰减率（基于认知科学）
FACT_DECAY_DEFAULTS: dict[str, float] = {
    "profile":           0.0,    # 永久（身份信息）
    "preference":        0.005,  # ~200天（偏好/习惯）
    "project":           0.01,   # ~70天（正在进行的项目）
    "event":             0.05,   # ~14天（情景记忆）
    "reflection":        0.02,   # ~35天（自我认知）
    "episodic_summary":  0.01,   # ~70天（情景压缩）
    "goal":              0.005,  # ~200天（前瞻性记忆）
    "decision":          0.002,  # ~1年（程序性记忆）
    "constraint":        0.001,  # 最慢（规则/限制）
    "learning":          0.01,   # ~70天（习得知识）
}


@dataclass
class Fact:
    """从对话中自动提取的结构化事实（语义记忆）。"""

    id: Optional[int]
    user_id: str           # SQL 隔离主体
    subject: str            # 主体，如 "user"
    key: str                # 属性 key（英文 snake_case），如 "pet_name"
    value: str              # 值（保留原始语言），如 "Max"
    category: str           # 见 FACT_DECAY_DEFAULTS
    confidence: float       # LLM 提取的置信度 0.0-1.0
    evidence: str           # 原文引用（verbatim）
    source_msg_id: int
    created_at: float       # Unix timestamp

    # 认知特性
    decay_rate: float = field(init=False)
    pinned: bool = False    # 用户手动钉住（跳过衰减）
    last_decay_at: Optional[float] = None

    # 演化（冲突 / 替换）
    superseded_by: Optional[int] = None    # 被哪个 fact 替代
    forgotten_at: Optional[float] = None   # 显式遗忘时间

    def __post_init__(self) -> None:
        self.decay_rate = FACT_DECAY_DEFAULTS.get(self.category, 0.01)

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None and self.forgotten_at is None


# ─────────────────────────────────────────────
# 召回结果
# ─────────────────────────────────────────────

@dataclass
class Hit:
    """RRF 融合后的单条召回结果。"""

    message_id: int
    text: str
    score: float                # RRF 融合后的最终分数
    source: str                 # "vec"|"fts"|"recency"|"salience"|"facts"|"entity"

    # 各路原始信号
    recency: float = 0.0
    salience: float = 0.0
    session_affinity: float = 1.0   # 跨 session 降权系数（0.0-1.0）

    # 元数据
    session_id: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[float] = None


# 单值 key：同一 subject 下同一 key 只允许一个 active 值，新值 supersede 旧值。
SINGLE_VALUED_KEYS: frozenset[str] = frozenset({
    "name", "occupation", "location", "language", "timezone",
    "birthday", "email", "phone", "pet_name",
})


@dataclass
class FactConflict:
    """同一 subject/key 下出现多个互斥 active 值的冲突。"""
    subject: str
    key: str
    values: list[str]
    fact_ids: list[int]


class MemoryApplyStatus(str, Enum):
    """Outcome of an idempotent message apply."""

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"


@dataclass(frozen=True, slots=True)
class MemoryApplyResult:
    """Durable acknowledgement returned to a memory outbox consumer."""

    message_id: int
    source_event_id: str
    payload_hash: str
    status: MemoryApplyStatus


class RecallStatus(str, Enum):
    """Stable bounded-recall terminal states."""

    COMPLETE = "complete"
    TRUNCATED = "truncated"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class BoundedRecallResult:
    """A canonical, optionally durable bounded recall result."""

    hits: tuple[Hit, ...]
    status: RecallStatus
    result_hash: str
    result_bytes: int
    context_query_id: str | None = None
    query_hash: str | None = None
    replayed: bool = False

    @property
    def truncated(self) -> bool:
        return self.status is not RecallStatus.COMPLETE

    def as_payload(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "message_id": hit.message_id,
                    "text": hit.text,
                    "score": hit.score,
                    "source": hit.source,
                    "recency": hit.recency,
                    "salience": hit.salience,
                    "session_affinity": hit.session_affinity,
                    "session_id": hit.session_id,
                    "role": hit.role,
                    "created_at": hit.created_at,
                }
                for hit in self.hits
            ],
            "status": self.status.value,
        }
