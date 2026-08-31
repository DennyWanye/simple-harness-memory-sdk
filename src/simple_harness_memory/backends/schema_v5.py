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
    delivery_receipt_id TEXT UNIQUE,
    delivery_receipt_json BLOB,
    delivery_receipt_hash TEXT UNIQUE,
    validation_receipt_id TEXT NOT NULL UNIQUE,
    validation_receipt_json BLOB NOT NULL,
    validation_receipt_hash TEXT NOT NULL UNIQUE,
    result_hash TEXT NOT NULL UNIQUE,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    cost_microunits INTEGER NOT NULL CHECK (cost_microunits >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    started_at REAL NOT NULL CHECK (started_at >= 0),
    completed_at REAL NOT NULL CHECK (completed_at >= started_at),
    invocation_hash TEXT NOT NULL UNIQUE,
    CHECK ((delivery_receipt_id IS NULL) = (delivery_receipt_json IS NULL)),
    CHECK ((delivery_receipt_id IS NULL) = (delivery_receipt_hash IS NULL)),
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
    batch_key TEXT NOT NULL,
    evidence_watermark TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'applied', 'dead_letter')),
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at REAL,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error_code TEXT,
    next_attempt_at REAL NOT NULL CHECK (next_attempt_at >= 0),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0),
    UNIQUE (principal_id, idempotency_key)
);
CREATE TABLE job_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    batch_id TEXT NOT NULL,
    lease_token TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_hash TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('handed_off', 'result_committed', 'audit_pending', 'applied', 'failed')
    ),
    reason_code TEXT,
    started_at REAL NOT NULL CHECK (started_at >= 0),
    completed_at REAL,
    PRIMARY KEY (job_id, attempt)
);
CREATE TABLE analysis_batches (
    batch_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    batch_key TEXT NOT NULL,
    evidence_watermark TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    request_json BLOB NOT NULL,
    request_hash TEXT NOT NULL UNIQUE,
    result_json BLOB,
    result_hash TEXT UNIQUE,
    delivery_receipt_json BLOB,
    delivery_receipt_hash TEXT UNIQUE,
    result_envelope_hash TEXT UNIQUE,
    state TEXT NOT NULL CHECK (
        state IN ('handed_off', 'result_committed', 'audit_pending', 'applied', 'failed')
    ),
    application_receipt_json BLOB,
    application_receipt_hash TEXT UNIQUE,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= 0)
);
CREATE TABLE analysis_batch_members (
    batch_id TEXT NOT NULL REFERENCES analysis_batches(batch_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    job_attempt INTEGER NOT NULL CHECK (job_attempt >= 1),
    evidence_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (batch_id, ordinal),
    UNIQUE (batch_id, job_id)
);
CREATE TABLE job_attempt_events (
    event_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES analysis_batches(batch_id),
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    event_kind TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    result_hash TEXT,
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    event_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX job_attempt_event_lookup
    ON job_attempt_events(job_id, attempt, occurred_at, event_id);
CREATE TRIGGER job_attempt_events_immutable_update
BEFORE UPDATE ON job_attempt_events BEGIN SELECT RAISE(ABORT, 'immutable job event'); END;
CREATE TRIGGER job_attempt_events_immutable_delete
BEFORE DELETE ON job_attempt_events BEGIN SELECT RAISE(ABORT, 'immutable job event'); END;
CREATE TABLE analysis_apply_heads (
    principal_id TEXT PRIMARY KEY REFERENCES principals(principal_id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL CHECK (updated_at >= 0)
);
CREATE TABLE accepted_analysis_plans (
    batch_id TEXT PRIMARY KEY REFERENCES analysis_batches(batch_id),
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    base_revision INTEGER NOT NULL CHECK (base_revision >= 1),
    committed_revision INTEGER NOT NULL CHECK (committed_revision >= base_revision),
    plan_json BLOB NOT NULL,
    plan_hash TEXT NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0)
);
CREATE TRIGGER accepted_analysis_plans_immutable_update
BEFORE UPDATE ON accepted_analysis_plans BEGIN SELECT RAISE(ABORT, 'immutable job apply'); END;
CREATE TRIGGER accepted_analysis_plans_immutable_delete
BEFORE DELETE ON accepted_analysis_plans BEGIN SELECT RAISE(ABORT, 'immutable job apply'); END;
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
CREATE TABLE cognitive_apply_heads (
    principal_id TEXT PRIMARY KEY REFERENCES principals(principal_id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL CHECK (updated_at >= 0)
);
CREATE TABLE cognitive_memory_heads (
    memory_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    memory_type TEXT NOT NULL CHECK (
        memory_type IN ('episode', 'semantic', 'procedure', 'prospective')
    ),
    current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    updated_at REAL NOT NULL CHECK (updated_at >= created_at),
    UNIQUE (principal_id, memory_id)
);
CREATE INDEX cognitive_memory_head_lookup
    ON cognitive_memory_heads(principal_id, memory_type, updated_at, memory_id);
CREATE TABLE cognitive_memory_revisions (
    memory_id TEXT NOT NULL REFERENCES cognitive_memory_heads(memory_id),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    operation_id TEXT NOT NULL UNIQUE,
    task_scope_id TEXT,
    lifecycle_state TEXT NOT NULL,
    epistemic_status TEXT NOT NULL,
    conflict_status TEXT NOT NULL,
    verification_state TEXT NOT NULL,
    effective_privacy_class TEXT NOT NULL CHECK (
        effective_privacy_class IN ('public', 'personal', 'sensitive', 'restricted')
    ),
    information_attributes_json BLOB NOT NULL,
    content_json BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    valid_from REAL CHECK (valid_from IS NULL OR valid_from >= 0),
    valid_to REAL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    PRIMARY KEY (memory_id, revision),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);
CREATE INDEX cognitive_memory_revision_lookup
    ON cognitive_memory_revisions(memory_id, revision, lifecycle_state);
CREATE TRIGGER cognitive_memory_revisions_immutable_update
BEFORE UPDATE ON cognitive_memory_revisions
BEGIN SELECT RAISE(ABORT, 'immutable cognitive revision'); END;
CREATE TRIGGER cognitive_memory_revisions_immutable_delete
BEFORE DELETE ON cognitive_memory_revisions
BEGIN SELECT RAISE(ABORT, 'immutable cognitive revision'); END;
CREATE TABLE episode_records (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    title TEXT NOT NULL,
    thread_ref TEXT,
    participants_json BLOB NOT NULL,
    goals_json BLOB NOT NULL,
    actions_json BLOB NOT NULL,
    results_json BLOB NOT NULL,
    impacts_json BLOB NOT NULL,
    occurred_start REAL NOT NULL CHECK (occurred_start >= 0),
    occurred_end REAL,
    PRIMARY KEY (memory_id, revision),
    FOREIGN KEY (memory_id, revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision),
    CHECK (occurred_end IS NULL OR occurred_end >= occurred_start)
);
CREATE TRIGGER episode_records_immutable_update
BEFORE UPDATE ON episode_records
BEGIN SELECT RAISE(ABORT, 'immutable episode record'); END;
CREATE TRIGGER episode_records_immutable_delete
BEFORE DELETE ON episode_records
BEGIN SELECT RAISE(ABORT, 'immutable episode record'); END;
CREATE TABLE semantic_claims (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    subject_entity TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_json BLOB NOT NULL,
    object_hash TEXT NOT NULL,
    qualifiers_json BLOB NOT NULL,
    PRIMARY KEY (memory_id, revision),
    FOREIGN KEY (memory_id, revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE INDEX semantic_claim_lookup
    ON semantic_claims(subject_entity, predicate, object_hash, memory_id);
CREATE TRIGGER semantic_claims_immutable_update
BEFORE UPDATE ON semantic_claims
BEGIN SELECT RAISE(ABORT, 'immutable semantic claim'); END;
CREATE TRIGGER semantic_claims_immutable_delete
BEFORE DELETE ON semantic_claims
BEGIN SELECT RAISE(ABORT, 'immutable semantic claim'); END;
CREATE TABLE procedure_records (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    name TEXT NOT NULL,
    applicability_json BLOB NOT NULL,
    steps_json BLOB NOT NULL,
    risk_level TEXT NOT NULL CHECK (
        risk_level IN ('low', 'medium', 'high', 'irreversible')
    ),
    applicability_fingerprint TEXT NOT NULL,
    success_evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (success_evidence_count >= 0),
    failure_evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_evidence_count >= 0),
    PRIMARY KEY (memory_id, revision),
    FOREIGN KEY (memory_id, revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TRIGGER procedure_records_immutable_update
BEFORE UPDATE ON procedure_records
BEGIN SELECT RAISE(ABORT, 'immutable procedure record'); END;
CREATE TRIGGER procedure_records_immutable_delete
BEFORE DELETE ON procedure_records
BEGIN SELECT RAISE(ABORT, 'immutable procedure record'); END;
CREATE TABLE prospective_records (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    action_text TEXT NOT NULL,
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('time', 'event')),
    trigger_json BLOB NOT NULL,
    scheduler_registration_ref TEXT,
    due_at REAL,
    PRIMARY KEY (memory_id, revision),
    FOREIGN KEY (memory_id, revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision),
    CHECK ((trigger_kind = 'time') = (due_at IS NOT NULL))
);
CREATE TRIGGER prospective_records_immutable_update
BEFORE UPDATE ON prospective_records
BEGIN SELECT RAISE(ABORT, 'immutable prospective record'); END;
CREATE TRIGGER prospective_records_immutable_delete
BEFORE DELETE ON prospective_records
BEGIN SELECT RAISE(ABORT, 'immutable prospective record'); END;
CREATE TABLE cognitive_evidence_spans (
    memory_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    span_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    envelope_hash TEXT NOT NULL,
    sanitized_hash TEXT NOT NULL,
    admission_receipt_id TEXT NOT NULL,
    admission_receipt_hash TEXT NOT NULL,
    evidence_item_ordinal INTEGER NOT NULL CHECK (evidence_item_ordinal >= 1),
    evidence_item_id TEXT NOT NULL,
    evidence_item_json_pointer TEXT NOT NULL,
    byte_start INTEGER NOT NULL CHECK (byte_start >= 0),
    byte_end INTEGER NOT NULL CHECK (byte_end > byte_start),
    exact_quote TEXT NOT NULL,
    quote_hash TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    provenance TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    support_kind TEXT NOT NULL,
    observation_schema_id TEXT,
    observation_schema_version INTEGER,
    observation_registered_schema_hash TEXT,
    observation_receipt_id TEXT,
    observation_receipt_hash TEXT,
    observation_authority_issuer_id TEXT,
    observation_json_pointer TEXT,
    observation_value_hash TEXT,
    PRIMARY KEY (memory_id, revision, ordinal),
    UNIQUE (memory_id, revision, span_id),
    FOREIGN KEY (memory_id, revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision),
    FOREIGN KEY (evidence_id, evidence_item_ordinal)
        REFERENCES evidence_items(evidence_id, ordinal),
    CHECK (
        (observation_schema_id IS NULL AND observation_schema_version IS NULL
            AND observation_registered_schema_hash IS NULL
            AND observation_receipt_id IS NULL AND observation_receipt_hash IS NULL
            AND observation_authority_issuer_id IS NULL
            AND observation_json_pointer IS NULL AND observation_value_hash IS NULL)
        OR
        (observation_schema_id IS NOT NULL AND observation_schema_version >= 1
            AND observation_registered_schema_hash IS NOT NULL
            AND observation_receipt_id IS NOT NULL AND observation_receipt_hash IS NOT NULL
            AND observation_authority_issuer_id IS NOT NULL
            AND observation_json_pointer IS NOT NULL AND observation_value_hash IS NOT NULL)
    )
);
CREATE INDEX cognitive_evidence_lookup
    ON cognitive_evidence_spans(evidence_id, memory_id, revision);
CREATE TRIGGER cognitive_evidence_spans_immutable_update
BEFORE UPDATE ON cognitive_evidence_spans
BEGIN SELECT RAISE(ABORT, 'immutable cognitive evidence'); END;
CREATE TRIGGER cognitive_evidence_spans_immutable_delete
BEFORE DELETE ON cognitive_evidence_spans
BEGIN SELECT RAISE(ABORT, 'immutable cognitive evidence'); END;
CREATE TABLE cognitive_relations (
    relation_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    source_memory_id TEXT NOT NULL REFERENCES cognitive_memory_heads(memory_id),
    source_revision INTEGER NOT NULL,
    relation_kind TEXT NOT NULL CHECK (
        relation_kind IN ('amends', 'supersedes', 'contests', 'supports', 'relates_to')
    ),
    target_memory_id TEXT NOT NULL REFERENCES cognitive_memory_heads(memory_id),
    target_revision INTEGER NOT NULL,
    operation_id TEXT NOT NULL,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    relation_hash TEXT NOT NULL UNIQUE,
    UNIQUE (operation_id, relation_kind, source_memory_id, target_memory_id),
    FOREIGN KEY (source_memory_id, source_revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision),
    FOREIGN KEY (target_memory_id, target_revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TRIGGER cognitive_relations_immutable_update
BEFORE UPDATE ON cognitive_relations
BEGIN SELECT RAISE(ABORT, 'immutable cognitive relation'); END;
CREATE TRIGGER cognitive_relations_immutable_delete
BEFORE DELETE ON cognitive_relations
BEGIN SELECT RAISE(ABORT, 'immutable cognitive relation'); END;
CREATE TABLE memory_mutation_receipts (
    receipt_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    authority_ref TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    plan_outcome TEXT NOT NULL CHECK (plan_outcome IN ('mutate', 'no_mutation')),
    plan_json BLOB NOT NULL,
    base_revision INTEGER NOT NULL CHECK (base_revision >= 1),
    committed_revision INTEGER NOT NULL CHECK (committed_revision >= base_revision),
    canonical_operation_ids_json BLOB NOT NULL,
    apply_mode TEXT NOT NULL CHECK (apply_mode = 'strict_atomic'),
    receipt_json BLOB NOT NULL,
    receipt_hash TEXT NOT NULL UNIQUE,
    committed_at REAL NOT NULL CHECK (committed_at >= 0),
    UNIQUE (principal_id, idempotency_key),
    CHECK (committed_revision IN (base_revision, base_revision + 1))
);
CREATE TRIGGER memory_mutation_receipts_immutable_update
BEFORE UPDATE ON memory_mutation_receipts
BEGIN SELECT RAISE(ABORT, 'immutable mutation receipt'); END;
CREATE TRIGGER memory_mutation_receipts_immutable_delete
BEFORE DELETE ON memory_mutation_receipts
BEGIN SELECT RAISE(ABORT, 'immutable mutation receipt'); END;
CREATE TABLE memory_mutation_decisions (
    decision_id TEXT PRIMARY KEY,
    receipt_id TEXT NOT NULL REFERENCES memory_mutation_receipts(receipt_id),
    operation_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome = 'committed'),
    reason_code TEXT NOT NULL,
    before_ref TEXT,
    after_ref TEXT,
    decision_json BLOB NOT NULL,
    decision_hash TEXT NOT NULL UNIQUE,
    UNIQUE (receipt_id, operation_id)
);
CREATE TRIGGER memory_mutation_decisions_immutable_update
BEFORE UPDATE ON memory_mutation_decisions
BEGIN SELECT RAISE(ABORT, 'immutable mutation decision'); END;
CREATE TRIGGER memory_mutation_decisions_immutable_delete
BEFORE DELETE ON memory_mutation_decisions
BEGIN SELECT RAISE(ABORT, 'immutable mutation decision'); END;
CREATE TABLE procedure_observations (
    observation_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES cognitive_memory_heads(memory_id),
    procedure_revision INTEGER NOT NULL CHECK (procedure_revision >= 1),
    task_scope_id TEXT NOT NULL,
    terminal_receipt_ref TEXT NOT NULL,
    applicability_fingerprint TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    observation_hash TEXT NOT NULL UNIQUE,
    UNIQUE (memory_id, procedure_revision, task_scope_id, terminal_receipt_ref),
    FOREIGN KEY (memory_id, procedure_revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TRIGGER procedure_observations_immutable_update
BEFORE UPDATE ON procedure_observations
BEGIN SELECT RAISE(ABORT, 'immutable procedure observation'); END;
CREATE TRIGGER procedure_observations_immutable_delete
BEFORE DELETE ON procedure_observations
BEGIN SELECT RAISE(ABORT, 'immutable procedure observation'); END;
CREATE TABLE prospective_trigger_events (
    event_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES cognitive_memory_heads(memory_id),
    prospective_revision INTEGER NOT NULL CHECK (prospective_revision >= 1),
    trigger_fingerprint TEXT NOT NULL,
    event_ref TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('matched', 'ignored', 'invalidated', 'registered')
    ),
    reason_code TEXT NOT NULL,
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    event_hash TEXT NOT NULL UNIQUE,
    UNIQUE (memory_id, prospective_revision, event_ref, outcome),
    FOREIGN KEY (memory_id, prospective_revision)
        REFERENCES cognitive_memory_revisions(memory_id, revision)
);
CREATE TRIGGER prospective_trigger_events_immutable_update
BEFORE UPDATE ON prospective_trigger_events
BEGIN SELECT RAISE(ABORT, 'immutable prospective trigger event'); END;
CREATE TRIGGER prospective_trigger_events_immutable_delete
BEFORE DELETE ON prospective_trigger_events
BEGIN SELECT RAISE(ABORT, 'immutable prospective trigger event'); END;
CREATE TABLE conversation_evidence_registrations (
    registration_id TEXT PRIMARY KEY,
    registration_hash TEXT NOT NULL UNIQUE,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    evidence_id TEXT NOT NULL UNIQUE REFERENCES evidence_envelopes(evidence_id),
    envelope_hash TEXT NOT NULL,
    admission_receipt_id TEXT NOT NULL,
    admission_receipt_hash TEXT NOT NULL,
    metadata_id TEXT NOT NULL UNIQUE,
    metadata_hash TEXT NOT NULL UNIQUE,
    metadata_json BLOB NOT NULL,
    metadata_receipt_id TEXT NOT NULL UNIQUE,
    metadata_receipt_hash TEXT NOT NULL UNIQUE,
    metadata_receipt_json BLOB NOT NULL,
    authority_issuer_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    primary_conversation_id TEXT NOT NULL,
    causal_group_id TEXT NOT NULL,
    causal_group_sequence INTEGER NOT NULL CHECK (causal_group_sequence >= 1),
    item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 1),
    group_item_count INTEGER NOT NULL CHECK (group_item_count >= item_ordinal),
    ordered_group_manifest_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'runtime')),
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    task_scope_id TEXT,
    tool_causal_link_json BLOB,
    entities_json BLOB NOT NULL,
    registration_json BLOB NOT NULL,
    registered_at REAL NOT NULL CHECK (registered_at >= 0),
    UNIQUE (
        principal_id, primary_conversation_id, causal_group_id, item_ordinal
    ),
    CHECK (conversation_id = primary_conversation_id),
    CHECK ((role = 'tool') = (tool_causal_link_json IS NOT NULL))
);
CREATE INDEX conversation_evidence_group_lookup
    ON conversation_evidence_registrations(
        principal_id, primary_conversation_id, causal_group_sequence, item_ordinal
    );
CREATE TRIGGER conversation_evidence_registrations_immutable_update
BEFORE UPDATE ON conversation_evidence_registrations
BEGIN SELECT RAISE(ABORT, 'immutable conversation registration'); END;
CREATE TRIGGER conversation_evidence_registrations_immutable_delete
BEFORE DELETE ON conversation_evidence_registrations
BEGIN SELECT RAISE(ABORT, 'immutable conversation registration'); END;
CREATE TABLE short_horizon_chunks (
    chunk_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    subject TEXT NOT NULL,
    primary_conversation_id TEXT NOT NULL,
    causal_group_id TEXT NOT NULL,
    causal_group_sequence INTEGER NOT NULL CHECK (causal_group_sequence >= 1),
    roles_json BLOB NOT NULL,
    task_scope_ids_json BLOB NOT NULL,
    entities_json BLOB NOT NULL,
    source_refs_json BLOB NOT NULL,
    public_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    occurred_at REAL NOT NULL CHECK (occurred_at >= 0),
    expires_at REAL NOT NULL CHECK (expires_at > occurred_at),
    created_at REAL NOT NULL CHECK (created_at >= 0),
    UNIQUE (principal_id, primary_conversation_id, causal_group_id)
);
CREATE INDEX short_horizon_eligibility_lookup
    ON short_horizon_chunks(principal_id, expires_at, occurred_at, chunk_id);
CREATE TABLE short_horizon_chunk_evidence (
    chunk_id TEXT NOT NULL REFERENCES short_horizon_chunks(chunk_id) ON DELETE CASCADE,
    item_ordinal INTEGER NOT NULL CHECK (item_ordinal >= 1),
    registration_id TEXT NOT NULL REFERENCES conversation_evidence_registrations(registration_id),
    evidence_id TEXT NOT NULL REFERENCES evidence_envelopes(evidence_id),
    envelope_hash TEXT NOT NULL,
    PRIMARY KEY (chunk_id, item_ordinal),
    UNIQUE (chunk_id, registration_id),
    UNIQUE (chunk_id, evidence_id)
);
CREATE VIRTUAL TABLE short_horizon_fts USING fts5(
    chunk_id UNINDEXED,
    public_text,
    tokenize='unicode61'
);
CREATE TRIGGER short_horizon_fts_insert
AFTER INSERT ON short_horizon_chunks
BEGIN
    INSERT INTO short_horizon_fts(chunk_id, public_text)
    VALUES (new.chunk_id, new.public_text);
END;
CREATE TRIGGER short_horizon_fts_delete
AFTER DELETE ON short_horizon_chunks
BEGIN
    DELETE FROM short_horizon_fts WHERE chunk_id = old.chunk_id;
END;
CREATE TRIGGER short_horizon_fts_update
AFTER UPDATE OF public_text ON short_horizon_chunks
BEGIN
    DELETE FROM short_horizon_fts WHERE chunk_id = old.chunk_id;
    INSERT INTO short_horizon_fts(chunk_id, public_text)
    VALUES (new.chunk_id, new.public_text);
END;
CREATE TABLE short_horizon_generations (
    generation_id TEXT PRIMARY KEY,
    lineage_id TEXT NOT NULL REFERENCES embedding_lineages(lineage_id),
    state TEXT NOT NULL CHECK (state IN ('building', 'active', 'retired', 'failed')),
    content_hash TEXT,
    last_error_code TEXT,
    created_at REAL NOT NULL CHECK (created_at >= 0),
    activated_at REAL
);
CREATE UNIQUE INDEX short_horizon_one_active
    ON short_horizon_generations(state) WHERE state = 'active';
CREATE TABLE short_horizon_vectors (
    chunk_id TEXT NOT NULL REFERENCES short_horizon_chunks(chunk_id),
    generation_id TEXT NOT NULL REFERENCES short_horizon_generations(generation_id),
    embedding BLOB NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension >= 1),
    PRIMARY KEY (chunk_id, generation_id)
);
CREATE TABLE recall_decisions (
    decision_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(principal_id),
    run_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    context_revision INTEGER NOT NULL CHECK (context_revision >= 1),
    plan_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    disclosure_context_json BLOB NOT NULL,
    disclosure_context_hash TEXT NOT NULL,
    evidence_refs_json BLOB NOT NULL,
    evidence_refs_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('no_recall', 'recall', 'needs_user_confirmation', 'rejected')
    ),
    filtered_candidate_count INTEGER NOT NULL CHECK (filtered_candidate_count >= 0),
    candidate_count_stage TEXT NOT NULL CHECK (
        candidate_count_stage = 'after_all_eligibility_gates'
    ),
    decision_json BLOB NOT NULL,
    decision_hash TEXT NOT NULL UNIQUE,
    decided_at REAL NOT NULL CHECK (decided_at >= 0),
    UNIQUE (principal_id, plan_id, plan_hash)
);
CREATE INDEX recall_decision_trace_lookup
    ON recall_decisions(principal_id, run_id, decided_at, decision_id);
CREATE TRIGGER recall_decisions_immutable_update
BEFORE UPDATE ON recall_decisions
BEGIN SELECT RAISE(ABORT, 'immutable recall decision'); END;
CREATE TRIGGER recall_decisions_immutable_delete
BEFORE DELETE ON recall_decisions
BEGIN SELECT RAISE(ABORT, 'immutable recall decision'); END;
CREATE TABLE recall_decision_items (
    decision_id TEXT NOT NULL REFERENCES recall_decisions(decision_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('memory', 'short_horizon')),
    source_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    memory_type TEXT,
    score REAL NOT NULL,
    cross_scope INTEGER NOT NULL CHECK (cross_scope IN (0, 1)),
    PRIMARY KEY (decision_id, ordinal),
    UNIQUE (decision_id, source_kind, source_ref)
);
CREATE TRIGGER recall_decision_items_immutable_update
BEFORE UPDATE ON recall_decision_items
BEGIN SELECT RAISE(ABORT, 'immutable recall decision item'); END;
CREATE TRIGGER recall_decision_items_immutable_delete
BEFORE DELETE ON recall_decision_items
BEGIN SELECT RAISE(ABORT, 'immutable recall decision item'); END;
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
        "analysis_batches",
        "analysis_batch_members",
        "job_attempt_events",
        "analysis_apply_heads",
        "accepted_analysis_plans",
        "outbox",
        "embedding_lineages",
        "embedding_generations",
        "evidence_vectors",
        "cognitive_apply_heads",
        "cognitive_memory_heads",
        "cognitive_memory_revisions",
        "episode_records",
        "semantic_claims",
        "procedure_records",
        "prospective_records",
        "cognitive_evidence_spans",
        "cognitive_relations",
        "memory_mutation_receipts",
        "memory_mutation_decisions",
        "procedure_observations",
        "prospective_trigger_events",
        "conversation_evidence_registrations",
        "short_horizon_chunks",
        "short_horizon_chunk_evidence",
        "short_horizon_fts",
        "short_horizon_fts_data",
        "short_horizon_fts_idx",
        "short_horizon_fts_content",
        "short_horizon_fts_docsize",
        "short_horizon_fts_config",
        "short_horizon_generations",
        "short_horizon_vectors",
        "recall_decisions",
        "recall_decision_items",
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
