"""Explicit migration APIs; never part of the runtime AgentMemoryPort."""

from simple_harness_memory.migrations.contracts import (
    EXECUTION_MANIFEST_PROTOCOL,
    IDENTITY_MAP_PROTOCOL,
    PROVENANCE_MANIFEST_PROTOCOL,
    LegacyIdentityBinding,
    LegacyIdentityMap,
    MigrationDecision,
    NonHarnessProvenanceEntry,
    NonHarnessProvenanceManifest,
    NormalizedExecutionEntry,
    execution_manifest_digest,
)
from simple_harness_memory.migrations.runtime import (
    ManifestImportReceipt,
    import_execution_manifest,
)
from simple_harness_memory.migrations.v3_to_v4 import (
    LEGACY_SCHEMA_CHECKSUM,
    LEGACY_SCHEMA_VERSION,
    MIGRATION_RECEIPT_PROTOCOL,
    MigrationReceipt,
    migrate_v3_to_v4,
)

__all__ = (
    "EXECUTION_MANIFEST_PROTOCOL",
    "IDENTITY_MAP_PROTOCOL",
    "LEGACY_SCHEMA_CHECKSUM",
    "LEGACY_SCHEMA_VERSION",
    "MIGRATION_RECEIPT_PROTOCOL",
    "PROVENANCE_MANIFEST_PROTOCOL",
    "LegacyIdentityBinding",
    "LegacyIdentityMap",
    "ManifestImportReceipt",
    "MigrationDecision",
    "MigrationReceipt",
    "NonHarnessProvenanceEntry",
    "NonHarnessProvenanceManifest",
    "NormalizedExecutionEntry",
    "execution_manifest_digest",
    "import_execution_manifest",
    "migrate_v3_to_v4",
)
