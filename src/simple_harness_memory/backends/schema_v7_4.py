"""Additive cognitive vector lane schema (0.6.23); the 7.3 DDL/checksum stay frozen in schema_v7_3.

7.4 只追加三张可重建/审计表：``cognitive_vector_generations``（同 ``short_horizon_generations``
形状 + 唯一 active 部分索引）、``cognitive_vectors``（按 (memory_id, revision, generation_id)）与
``cognitive_vector_audit``。lineage 复用 ``embedding_lineages``。7.3 库打开时前向追加（见
``migrations.cognitive_vector_forward``），初始化 receipt 与业务列不改写。
"""
import hashlib
from dataclasses import dataclass

from simple_harness_memory.backends import schema_v7_3 as previous

COGNITIVE_VECTOR_DDL = """
CREATE TABLE cognitive_vector_generations (
    generation_id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL REFERENCES embedding_lineages(lineage_id),
    state TEXT NOT NULL CHECK (state IN ('building', 'active', 'retired', 'failed')),
    content_hash TEXT,
    vector_manifest_hash TEXT NOT NULL,
    last_error_code TEXT,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    activated_at REAL
);
CREATE UNIQUE INDEX cognitive_vector_one_active
    ON cognitive_vector_generations(state) WHERE state = 'active';
CREATE TABLE cognitive_vectors (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    generation_id TEXT NOT NULL REFERENCES cognitive_vector_generations(generation_id),
    embedding BLOB NOT NULL,
    embedding_hash TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension >= 1),
    PRIMARY KEY (memory_id, revision, generation_id),
    FOREIGN KEY(memory_id, revision) REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TABLE cognitive_vector_audit (
    audit_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('generation_activated')),
    generation_id TEXT,
    generation_state TEXT NOT NULL CHECK (generation_state IN ('active', 'empty')),
    vector_count INTEGER NOT NULL CHECK (vector_count >= 0),
    audit_json BLOB NOT NULL,
    audit_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL CHECK (created_at >= 0)
);
CREATE TRIGGER cognitive_vector_audit_no_update
BEFORE UPDATE ON cognitive_vector_audit
BEGIN SELECT RAISE(ABORT, 'immutable cognitive vector audit'); END;
CREATE TRIGGER cognitive_vector_audit_no_delete
BEFORE DELETE ON cognitive_vector_audit
BEGIN SELECT RAISE(ABORT, 'immutable cognitive vector audit'); END;
"""
COGNITIVE_VECTOR_TABLES = frozenset(
    {"cognitive_vector_generations", "cognitive_vectors", "cognitive_vector_audit"}
)
DDL = previous.DDL + COGNITIVE_VECTOR_DDL
SCHEMA_CHECKSUM = hashlib.sha256(DDL.encode('utf-8')).hexdigest()
SCHEMA_CHECKSUM_V7_3 = previous.SCHEMA_CHECKSUM
SCHEMA_VERSION = previous.SCHEMA_VERSION
SCHEMA_EPOCH = previous.SCHEMA_EPOCH
SCHEMA_VERSION_LABEL = '7.4'
REQUIRED_TABLES = previous.REQUIRED_TABLES | COGNITIVE_VECTOR_TABLES
# 向量世代/缓存可重建；审计表按 principal 纳入 canonical manifest roots。
CANONICAL_MANIFEST_DERIVED_EXCLUSIONS = previous.CANONICAL_MANIFEST_DERIVED_EXCLUSIONS | {
    "cognitive_vector_generations",
    "cognitive_vectors",
}
SCHEMA_CHECKSUM_V7_0 = previous.SCHEMA_CHECKSUM_V7_0
V7_1_ADDED_COLUMNS = previous.V7_1_ADDED_COLUMNS

def ddl_statements(ddl=DDL):
    return previous.ddl_statements(ddl)

@dataclass(frozen=True, slots=True)
class InitializationReceipt(previous.InitializationReceipt):
    schema_checksum: str = SCHEMA_CHECKSUM
