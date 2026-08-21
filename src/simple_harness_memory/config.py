"""Central resource limits for the memory SDK.

The defaults are deliberately finite.  Applications may tighten them, but no
production read or maintenance operation silently falls back to an unbounded
table scan.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryResourceBounds:
    """Resource ceilings shared by backends and conversation adapters."""

    max_content_chars: int = 100_000
    max_fact_value_chars: int = 10_000
    max_payload_bytes: int = 1_000_000
    max_db_bytes: int | None = None
    recall_candidate_messages: int = 512
    recall_candidate_facts: int = 512
    recall_max_results: int = 20
    recall_max_bytes: int = 64 * 1024
    recall_timeout_seconds: float = 2.0
    maintenance_batch_size: int = 256
    summary_messages_per_session: int = 256
    context_result_dedupe_seconds: float = 7 * 24 * 60 * 60

    def __post_init__(self) -> None:
        positive = {
            "max_content_chars": self.max_content_chars,
            "max_fact_value_chars": self.max_fact_value_chars,
            "max_payload_bytes": self.max_payload_bytes,
            "recall_candidate_messages": self.recall_candidate_messages,
            "recall_candidate_facts": self.recall_candidate_facts,
            "recall_max_results": self.recall_max_results,
            "recall_max_bytes": self.recall_max_bytes,
            "maintenance_batch_size": self.maintenance_batch_size,
            "summary_messages_per_session": self.summary_messages_per_session,
        }
        for name, value in positive.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_db_bytes is not None and (
            isinstance(self.max_db_bytes, bool)
            or not isinstance(self.max_db_bytes, int)
            or self.max_db_bytes <= 0
        ):
            raise ValueError("max_db_bytes must be positive when set")
        if (
            isinstance(self.recall_timeout_seconds, bool)
            or not isinstance(self.recall_timeout_seconds, (int, float))
            or self.recall_timeout_seconds <= 0
        ):
            raise ValueError("recall_timeout_seconds must be positive")
        if (
            isinstance(self.context_result_dedupe_seconds, bool)
            or not isinstance(self.context_result_dedupe_seconds, (int, float))
            or self.context_result_dedupe_seconds < 0
        ):
            raise ValueError("context_result_dedupe_seconds must not be negative")


DEFAULT_BOUNDS = MemoryResourceBounds()
