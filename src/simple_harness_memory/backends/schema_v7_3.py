"""Additive settlement schema. The 7.2 DDL/checksum remain frozen in schema_v5."""
import hashlib
from dataclasses import dataclass
from simple_harness_memory.backends import schema_v5 as previous

TERMINAL_DDL = """
CREATE TABLE prospective_invalidation_terminal_receipts (
    receipt_id TEXT PRIMARY KEY,
    outbox_id TEXT NOT NULL UNIQUE REFERENCES outbox(outbox_id),
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    target_revision INTEGER NOT NULL CHECK(target_revision > 0),
    registration_revision INTEGER NOT NULL CHECK(registration_revision = target_revision),
    payload_hash TEXT NOT NULL,
    target_source_hash TEXT NOT NULL,
    trigger_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind = 'not_required'),
    reason TEXT NOT NULL CHECK(reason = 'signal_revision_never_registration_requested'),
    receipt_json BLOB NOT NULL,
    receipt_hash TEXT NOT NULL,
    checked_at REAL NOT NULL CHECK(checked_at >= 0),
    UNIQUE(memory_id, target_revision),
    FOREIGN KEY(memory_id, target_revision) REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TRIGGER prospective_terminal_no_update
BEFORE UPDATE ON prospective_invalidation_terminal_receipts
BEGIN SELECT RAISE(ABORT, 'immutable prospective terminal receipt'); END;
CREATE TRIGGER prospective_terminal_no_delete
BEFORE DELETE ON prospective_invalidation_terminal_receipts
BEGIN SELECT RAISE(ABORT, 'immutable prospective terminal receipt'); END;
CREATE TRIGGER prospective_terminal_registration_insert_guard
BEFORE INSERT ON outbox
WHEN NEW.topic='memory.prospective.registration.requested' AND EXISTS (
    SELECT 1 FROM prospective_invalidation_terminal_receipts t
    WHERE t.memory_id=json_extract(NEW.payload,'$.memory_id')
      AND t.target_revision=json_extract(NEW.payload,'$.prospective_revision'))
BEGIN SELECT RAISE(ABORT, 'prospective registration already not required'); END;
CREATE TRIGGER prospective_terminal_ack_insert_guard
BEFORE INSERT ON prospective_scheduler_registrations
WHEN EXISTS (SELECT 1 FROM prospective_invalidation_terminal_receipts t
    WHERE t.memory_id=NEW.memory_id AND (t.target_revision=NEW.prospective_revision
        OR t.registration_revision=NEW.registration_revision))
BEGIN SELECT RAISE(ABORT, 'prospective registration already not required'); END;
"""
DDL = previous.DDL + TERMINAL_DDL
SCHEMA_CHECKSUM = hashlib.sha256(DDL.encode('utf-8')).hexdigest()
SCHEMA_VERSION = previous.SCHEMA_VERSION
SCHEMA_EPOCH = previous.SCHEMA_EPOCH
SCHEMA_VERSION_LABEL = '7.3'
REQUIRED_TABLES = previous.REQUIRED_TABLES | {'prospective_invalidation_terminal_receipts'}
CANONICAL_MANIFEST_DERIVED_EXCLUSIONS = previous.CANONICAL_MANIFEST_DERIVED_EXCLUSIONS
SCHEMA_CHECKSUM_V7_0 = previous.SCHEMA_CHECKSUM_V7_0
V7_1_ADDED_COLUMNS = previous.V7_1_ADDED_COLUMNS

def ddl_statements(ddl=DDL):
    return previous.ddl_statements(ddl)

@dataclass(frozen=True, slots=True)
class InitializationReceipt(previous.InitializationReceipt):
    schema_checksum: str = SCHEMA_CHECKSUM
