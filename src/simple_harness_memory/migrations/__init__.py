"""Explicit migration APIs; never part of the runtime AgentMemoryPort."""

from simple_harness_memory.migrations.schema_upgrade import (
    HumanMemorySchemaUpgradeReceipt,
    migrate_human_memory_v7_to_v7_2,
)

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
    "HumanMemorySchemaUpgradeReceipt",
    "migrate_human_memory_v7_to_v7_2",
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

from simple_harness_memory.migrations.settlement_upgrade import (
    ProspectiveSettlementSchemaUpgradeReceipt, migrate_human_memory_v7_2_to_v7_3,
)
__all__ += ("ProspectiveSettlementSchemaUpgradeReceipt", "migrate_human_memory_v7_2_to_v7_3")
