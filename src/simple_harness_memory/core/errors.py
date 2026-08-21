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


class MemoryErrorBase(RuntimeError):
    """Base class for stable, content-free SDK failures."""

    code = "memory_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class MemorySchemaIncompatible(MemoryCorruptionError):
    """The database is not an empty/fresh v4 database."""

    code = "memory_schema_incompatible"

    def __init__(self) -> None:
        super().__init__(self.code)


class MemoryOwnershipConflict(MemoryErrorBase):
    """A session or record is already owned by another user."""

    code = "memory_ownership_conflict"


class MemoryIdempotencyConflict(MemoryErrorBase):
    """A deterministic id was replayed with different canonical input."""

    code = "memory_idempotency_conflict"


class MemoryValidationError(MemoryErrorBase, ValueError):
    """A public conversation-memory value failed canonical validation."""

    code = "memory_validation_error"


class MemoryUnsupportedOperation(MemoryErrorBase):
    """A legacy operation is intentionally fail-closed."""

    code = "runtime_delete_disabled"


class HarnessIntegrationExtraRequired(MemoryErrorBase):
    """The optional Harness integration dependency is unavailable."""

    code = "harness_integration_extra_required"
