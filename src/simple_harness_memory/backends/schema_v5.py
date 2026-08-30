"""Authoritative fresh schema for the human-memory v1 data epoch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field

SCHEMA_VERSION = 5
SCHEMA_EPOCH = "human-memory-v1"

DDL = """
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE initialization_receipts (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    receipt_id TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL CHECK (schema_version = 5),
    schema_epoch TEXT NOT NULL CHECK (schema_epoch = 'human-memory-v1'),
    schema_checksum TEXT NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    receipt_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE audit_cursor_authority (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    hmac_key_hex TEXT NOT NULL CHECK (length(hmac_key_hex) = 64)
);
CREATE TRIGGER audit_cursor_authority_immutable_update
BEFORE UPDATE ON audit_cursor_authority
BEGIN SELECT RAISE(ABORT, 'immutable cursor authority'); END;
CREATE TRIGGER audit_cursor_authority_immutable_delete
BEFORE DELETE ON audit_cursor_authority
BEGIN SELECT RAISE(ABORT, 'immutable cursor authority'); END;
CREATE TABLE principals (
    principal_id TEXT PRIMARY KEY,
    deployment_id TEXT NOT NULL,
    household_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    UNIQUE (deployment_id, household_id, actor_id)
);
CREATE TABLE evidence_envelopes (
    evidence_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    run_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    sanitized_hash TEXT NOT NULL,
    envelope_hash TEXT NOT NULL UNIQUE,
    filter_policy_version TEXT NOT NULL,
    disclosure_json BLOB NOT NULL,
    disclosure_hash TEXT NOT NULL,
    removed_spans_json BLOB NOT NULL,
    sanitized_payload BLOB NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    UNIQUE (principal_id, source_ref)
);
CREATE TABLE evidence_items (
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    item_kind TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    public_payload BLOB,
    blob_ref TEXT,
    PRIMARY KEY (evidence_id, ordinal),
    CHECK ((public_payload IS NULL) != (blob_ref IS NULL))
);
CREATE TABLE evidence_links (
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    target_evidence_id TEXT NOT NULL,
    target_content_hash TEXT NOT NULL,
    PRIMARY KEY (evidence_id, ordinal)
);
CREATE TABLE ingestion_receipts (
    receipt_id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL UNIQUE REFERENCES evidence_envelopes(evidence_id),
    source_hash TEXT NOT NULL,
    envelope_hash TEXT NOT NULL,
    admission_receipt_id TEXT NOT NULL,
    admission_receipt_json BLOB NOT NULL,
    admission_receipt_hash TEXT NOT NULL,
    receipt_hash TEXT NOT NULL UNIQUE,
    accepted_at REAL NOT NULL CHECK (accepted_at >= 0)
);
CREATE UNIQUE INDEX ingestion_admission_receipt_unique
    ON ingestion_receipts(admission_receipt_id);
CREATE TRIGGER evidence_envelopes_immutable_update
BEFORE UPDATE ON evidence_envelopes BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER evidence_envelopes_immutable_delete
BEFORE DELETE ON evidence_envelopes BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER evidence_items_immutable_update
BEFORE UPDATE ON evidence_items BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER evidence_items_immutable_delete
BEFORE DELETE ON evidence_items BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER evidence_links_immutable_update
BEFORE UPDATE ON evidence_links BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER evidence_links_immutable_delete
BEFORE DELETE ON evidence_links BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER ingestion_receipts_immutable_update
BEFORE UPDATE ON ingestion_receipts BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TRIGGER ingestion_receipts_immutable_delete
BEFORE DELETE ON ingestion_receipts BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END;
CREATE TABLE suppression_directives (
    directive_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('directive', 'revoke')),
    scope_kind TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    purpose TEXT,
    reason_code TEXT NOT NULL,
    decision_hash TEXT NOT NULL UNIQUE,
    supersedes_directive_id TEXT REFERENCES suppression_directives(directive_id),
    decision_record_id TEXT,
    effective_at REAL NOT NULL CHECK (effective_at >= 0)
);
CREATE TABLE suppression_targets (
    directive_id TEXT NOT NULL REFERENCES suppression_directives(directive_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    PRIMARY KEY (directive_id, ordinal),
    UNIQUE (directive_id, target_kind, target_ref)
);
CREATE INDEX suppression_target_lookup
    ON suppression_targets(target_kind, target_ref, directive_id);
CREATE TRIGGER suppression_directives_immutable_update
BEFORE UPDATE ON suppression_directives BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
CREATE TRIGGER suppression_directives_immutable_delete
BEFORE DELETE ON suppression_directives BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
CREATE TRIGGER suppression_targets_immutable_update
BEFORE UPDATE ON suppression_targets BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
CREATE TRIGGER suppression_targets_immutable_delete
BEFORE DELETE ON suppression_targets BEGIN SELECT RAISE(ABORT, 'immutable suppression'); END;
CREATE TABLE sealed_audit_access_receipts (
    access_receipt_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    purpose TEXT NOT NULL CHECK (purpose = 'sealed_evidence_audit'),
    scope_kind TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    disclosure_context_json BLOB NOT NULL,
    decision_hash TEXT NOT NULL UNIQUE,
    max_reads INTEGER NOT NULL CHECK (max_reads >= 1 AND max_reads <= 32),
    issued_at REAL NOT NULL CHECK (issued_at >= 0),
    expires_at REAL NOT NULL CHECK (expires_at > issued_at),
    receipt_hash TEXT NOT NULL UNIQUE
);
CREATE TRIGGER sealed_audit_access_receipts_immutable_update
BEFORE UPDATE ON sealed_audit_access_receipts
BEGIN SELECT RAISE(ABORT, 'immutable audit access'); END;
CREATE TRIGGER sealed_audit_access_receipts_immutable_delete
BEFORE DELETE ON sealed_audit_access_receipts
BEGIN SELECT RAISE(ABORT, 'immutable audit access'); END;
CREATE TABLE sealed_audit_access_events (
    event_id TEXT PRIMARY KEY,
    access_receipt_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose = 'sealed_evidence_audit'),
    outcome TEXT NOT NULL CHECK (outcome IN ('granted', 'denied')),
    reason_code TEXT NOT NULL,
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX sealed_audit_access_event_lookup
    ON sealed_audit_access_events(access_receipt_id, outcome, occurred_at, event_id);
CREATE TRIGGER sealed_audit_access_events_immutable_update
BEFORE UPDATE ON sealed_audit_access_events
BEGIN SELECT RAISE(ABORT, 'immutable audit event'); END;
CREATE TRIGGER sealed_audit_access_events_immutable_delete
BEFORE DELETE ON sealed_audit_access_events
BEGIN SELECT RAISE(ABORT, 'immutable audit event'); END;
CREATE TABLE llm_invocations (
    invocation_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    run_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    public_input_refs_json BLOB NOT NULL,
    public_input_hash TEXT NOT NULL,
    public_output_json BLOB,
    public_output_hash TEXT,
    output_storage_status TEXT NOT NULL
        CHECK (output_storage_status IN ('public', 'rejected_unsafe')),
    output_reason_code TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    validator_version TEXT NOT NULL,
    provider_request_id TEXT,
    host_receipt_id TEXT NOT NULL UNIQUE,
    host_receipt_json BLOB NOT NULL,
    host_receipt_hash TEXT NOT NULL UNIQUE,
    result_hash TEXT NOT NULL UNIQUE,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cost_microunits INTEGER NOT NULL CHECK (cost_microunits >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    started_at REAL NOT NULL CHECK (started_at >= 0),
    completed_at REAL NOT NULL CHECK (completed_at >= started_at),
    invocation_hash TEXT NOT NULL UNIQUE,
    UNIQUE (principal_id, request_hash)
);
CREATE INDEX llm_invocation_trace_lookup
    ON llm_invocations(principal_id, turn_id, invocation_sequence);
CREATE TRIGGER llm_invocations_immutable_update
BEFORE UPDATE ON llm_invocations BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER llm_invocations_immutable_delete
BEFORE DELETE ON llm_invocations BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE llm_invocation_evidence_refs (
    invocation_id TEXT NOT NULL REFERENCES llm_invocations(invocation_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    evidence_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (invocation_id, ordinal),
    UNIQUE (invocation_id, evidence_id)
);
CREATE INDEX llm_invocation_evidence_lookup
    ON llm_invocation_evidence_refs(evidence_id, invocation_id);
CREATE TRIGGER llm_invocation_evidence_refs_immutable_update
BEFORE UPDATE ON llm_invocation_evidence_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER llm_invocation_evidence_refs_immutable_delete
BEFORE DELETE ON llm_invocation_evidence_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE llm_reasoning_refs (
    invocation_id TEXT NOT NULL REFERENCES llm_invocations(invocation_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    provider_item_id TEXT NOT NULL,
    item_type TEXT NOT NULL,
    item_hash TEXT NOT NULL,
    opaque_ref TEXT,
    PRIMARY KEY (invocation_id, ordinal),
    UNIQUE (invocation_id, provider_item_id)
);
CREATE TRIGGER llm_reasoning_refs_immutable_update
BEFORE UPDATE ON llm_reasoning_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER llm_reasoning_refs_immutable_delete
BEFORE DELETE ON llm_reasoning_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE decision_records (
    decision_id TEXT PRIMARY KEY,
    invocation_id TEXT NOT NULL REFERENCES llm_invocations(invocation_id),
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    operation_id TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected')),
    target_kind TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    canonical_payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    before_refs_json BLOB NOT NULL,
    after_refs_json BLOB NOT NULL,
    reason_code TEXT NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    decision_hash TEXT NOT NULL UNIQUE,
    UNIQUE (invocation_id, operation_id)
);
CREATE INDEX decision_trace_lookup ON decision_records(invocation_id, decision_id);
CREATE TRIGGER decision_records_immutable_update
BEFORE UPDATE ON decision_records BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER decision_records_immutable_delete
BEFORE DELETE ON decision_records BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE decision_evidence_refs (
    decision_id TEXT NOT NULL REFERENCES decision_records(decision_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    evidence_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (decision_id, ordinal),
    UNIQUE (decision_id, evidence_id)
);
CREATE INDEX decision_evidence_lookup ON decision_evidence_refs(evidence_id, decision_id);
CREATE TRIGGER decision_evidence_refs_immutable_update
BEFORE UPDATE ON decision_evidence_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER decision_evidence_refs_immutable_delete
BEFORE DELETE ON decision_evidence_refs BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE audit_trace_access_events (
    event_id TEXT PRIMARY KEY,
    access_receipt_id TEXT NOT NULL,
    query_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('granted', 'denied')),
    reason_code TEXT NOT NULL,
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX audit_trace_access_lookup
    ON audit_trace_access_events(access_receipt_id, outcome, occurred_at, event_id);
CREATE TRIGGER audit_trace_access_events_immutable_update
BEFORE UPDATE ON audit_trace_access_events BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER audit_trace_access_events_immutable_delete
BEFORE DELETE ON audit_trace_access_events BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    job_kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'applied', 'dead_letter')),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at REAL NOT NULL CHECK (next_attempt_at >= 0),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    UNIQUE (principal_id, idempotency_key)
);
CREATE TABLE job_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    request_hash TEXT NOT NULL,
    result_hash TEXT,
    state TEXT NOT NULL,
    reason_code TEXT,
    started_at REAL NOT NULL CHECK (started_at >= 0),
    completed_at REAL,
    PRIMARY KEY (job_id, attempt)
);
CREATE TABLE outbox (
    outbox_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    topic TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'applied', 'dead_letter')),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at REAL NOT NULL CHECK (next_attempt_at >= 0),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    UNIQUE (principal_id, topic, idempotency_key)
);
CREATE TABLE embedding_lineages (
    lineage_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    provider TEXT,
    model TEXT NOT NULL,
    revision TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension >= 1),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    format_version INTEGER NOT NULL CHECK (format_version >= 1),
    fingerprint TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL CHECK (created_at >= 0)
);
CREATE TABLE embedding_generations (
    generation_id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL REFERENCES embedding_lineages(lineage_id),
    state TEXT NOT NULL CHECK (state IN ('building', 'active', 'retired', 'failed')),
    cursor_evidence_id TEXT,
    content_hash TEXT,
    last_error_code TEXT,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    activated_at REAL
);
CREATE UNIQUE INDEX embedding_one_active
    ON embedding_generations(state) WHERE state = 'active';
CREATE TABLE evidence_vectors (
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    generation_id TEXT NOT NULL REFERENCES embedding_generations(generation_id),
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension >= 1),
    PRIMARY KEY (evidence_id, generation_id)
);
"""


def ddl_statements(script: str = DDL) -> tuple[str, ...]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        buffer.append(line)
        candidate = "\n".join(buffer).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            buffer.clear()
    if "".join(buffer).strip():
        raise ValueError("schema v5 DDL is incomplete")
    return tuple(statements)


SCHEMA_CHECKSUM = hashlib.sha256(DDL.encode("utf-8")).hexdigest()
REQUIRED_TABLES = frozenset(
    {
        "schema_meta",
        "initialization_receipts",
        "audit_cursor_authority",
        "principals",
        "evidence_envelopes",
        "evidence_items",
        "evidence_links",
        "ingestion_receipts",
        "suppression_directives",
        "suppression_targets",
        "sealed_audit_access_receipts",
        "sealed_audit_access_events",
        "llm_invocations",
        "llm_invocation_evidence_refs",
        "llm_reasoning_refs",
        "decision_records",
        "decision_evidence_refs",
        "audit_trace_access_events",
        "jobs",
        "job_attempts",
        "outbox",
        "embedding_lineages",
        "embedding_generations",
        "evidence_vectors",
    }
)


@dataclass(frozen=True, slots=True)
class InitializationReceipt:
    receipt_id: str
    created_at: float
    schema_version: int = SCHEMA_VERSION
    schema_epoch: str = SCHEMA_EPOCH
    schema_checksum: str = SCHEMA_CHECKSUM
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, str) or not self.receipt_id.strip():
            raise ValueError("receipt_id is required")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("initialization receipt schema version differs")
        if self.schema_epoch != SCHEMA_EPOCH:
            raise ValueError("initialization receipt schema epoch differs")
        if self.schema_checksum != SCHEMA_CHECKSUM:
            raise ValueError("initialization receipt schema checksum differs")
        if isinstance(self.created_at, bool) or not isinstance(self.created_at, (int, float)):
            raise TypeError("created_at must be numeric")
        if self.created_at < 0:
            raise ValueError("created_at must be non-negative")
        object.__setattr__(self, "created_at", float(self.created_at))
        object.__setattr__(self, "receipt_hash", _receipt_hash(self))

    def to_json(self) -> dict[str, str | int | float]:
        return {
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "schema_epoch": self.schema_epoch,
            "schema_checksum": self.schema_checksum,
            "created_at": self.created_at,
        }


def _receipt_hash(receipt: InitializationReceipt) -> str:
    payload = json.dumps(
        receipt.to_json(),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = (
    "DDL",
    "InitializationReceipt",
    "REQUIRED_TABLES",
    "SCHEMA_CHECKSUM",
    "SCHEMA_EPOCH",
    "SCHEMA_VERSION",
    "ddl_statements",
)
