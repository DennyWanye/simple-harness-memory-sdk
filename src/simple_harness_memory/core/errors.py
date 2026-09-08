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


class TypedRecallDeadlineExceeded(TimeoutError):
    """``TimeoutError("DEADLINE_EXCEEDED")`` that names the stage where the budget ran out.

    0.6.27：typed recall 的 deadline 失败一律是 ``TimeoutError``（Host 契约不变，仍映射到
    ``context_route_recall_timeout``），但 ``stage`` 让调用方能区分「在哪一段耗尽预算」——
    目前只有 ``admit_write_lock``（等 admit 写锁超时，幂等记录尚未落库）会用到它。
    """

    code = "DEADLINE_EXCEEDED"

    def __init__(self, stage: str) -> None:
        super().__init__("DEADLINE_EXCEEDED")
        self.stage = stage


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


class MemoryLegacySchemaUnsupported(MemorySchemaIncompatible):
    """The human-memory v1 loader rejected a legacy or unknown schema read-only."""

    code = "LEGACY_SCHEMA_UNSUPPORTED"

    def __init__(self) -> None:
        MemoryCorruptionError.__init__(self, self.code)


class MemoryOwnershipConflict(MemoryErrorBase):
    """A session or record is not owned by the supplied trusted principal."""

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


class MemoryWriterConflict(MemoryErrorBase):
    """Another live manager already owns the SQLite writer lease."""

    code = "memory_second_writer_rejected"


class MemoryBackupError(MemoryErrorBase):
    """Backup or restore validation failed without exposing local paths."""

    code = "memory_backup_invalid"


class MemoryProductionConfigurationError(MemoryErrorBase):
    """A production manager was requested without pinned embedding resources."""

    code = "memory_production_embedder_required"


class MemoryMigrationError(MemoryErrorBase):
    """An offline migration failed without publishing a partial database."""

    code = "memory_migration_failed"


class MemoryMigrationManifestError(MemoryMigrationError):
    """A hash-protected migration input was incomplete, ambiguous, or tampered."""

    code = "memory_migration_manifest_invalid"


class MemoryMigrationSourceBusy(MemoryMigrationError):
    """The legacy database still has an active writer."""

    code = "memory_migration_source_busy"


class CognitiveVectorGenerationFailed(MemoryErrorBase):
    """One cognitive vector generation rebuild failed (0.6.24).

    ``code`` is the persisted ``cognitive_vector_generations.last_error_code``;
    ``generation_id`` is the ``failed`` row that recorded it (``None`` only when even
    that record could not be written). Raised instead of a bare ``MemoryCorruptionError``
    so a maintenance worker can log a stable code rather than an unrecorded failure.
    """

    code = "cognitive_vector_generation_failed"

    def __init__(self, code: str, *, generation_id: str | None) -> None:
        super().__init__(code)
        self.code = code
        self.generation_id = generation_id
