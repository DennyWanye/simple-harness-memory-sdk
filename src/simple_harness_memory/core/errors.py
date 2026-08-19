"""Stable error types for the memory SDK."""
from __future__ import annotations


class MemoryCorruptionError(RuntimeError):
    """A persisted memory record (e.g. a DigitalTwin) failed to deserialize.

    Raised instead of silently returning an empty object, so callers can
    report or isolate corruption rather than treating it as "no data".
    """


class MemoryLimitError(RuntimeError):
    """A write exceeded a configured size limit (content / fact / payload / DB)."""


class EmbeddingError(RuntimeError):
    """Embedding generation failed (network / timeout / dimension mismatch)."""


