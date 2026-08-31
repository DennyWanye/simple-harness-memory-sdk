# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

from __future__ import annotations

import sqlite3

import pytest

from simple_harness_memory.backends.schema_v5 import DDL


@pytest.fixture
def connection() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(DDL)
    return db


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _column_not_null(connection: sqlite3.Connection, table: str, column: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table})")
    return bool(next(row[3] for row in rows if row[1] == column))


def _unique_indexes(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for row in connection.execute(f"PRAGMA index_list({table})"):
        if not bool(row[2]):
            continue
        result.add(
            tuple(str(column[2]) for column in connection.execute(f"PRAGMA index_info({row[1]})"))
        )
    return result


def test_cognitive_schema_has_independent_apply_head_and_privacy_dimensions(
    connection: sqlite3.Connection,
) -> None:
    assert _columns(connection, "cognitive_apply_heads") == {
        "principal_id",
        "revision",
        "updated_at",
    }
    assert {
        "principal_id",
        "plan_id",
        "plan_hash",
        "operation_id",
        "effective_privacy_class",
        "information_attributes_json",
    } <= _columns(connection, "cognitive_memory_revisions")
    unique_indexes = _unique_indexes(connection, "cognitive_memory_revisions")
    assert ("operation_id",) not in unique_indexes
    assert ("principal_id", "plan_id", "operation_id") in unique_indexes
    assert not _column_not_null(connection, "cognitive_memory_revisions", "valid_from"), (
        "Harness ValidTimeInterval permits an unknown start"
    )
    connection.execute(
        "INSERT INTO principals VALUES(?,?,?,?,?)",
        ("principal-1", "deployment-1", "household-1", "actor-1", 1.0),
    )
    connection.execute("INSERT INTO analysis_apply_heads VALUES(?,?,?)", ("principal-1", 2, 1.0))
    connection.execute("INSERT INTO cognitive_apply_heads VALUES(?,?,?)", ("principal-1", 7, 1.0))
    assert connection.execute(
        "SELECT revision FROM analysis_apply_heads WHERE principal_id='principal-1'"
    ).fetchone() == (2,)
    assert connection.execute(
        "SELECT revision FROM cognitive_apply_heads WHERE principal_id='principal-1'"
    ).fetchone() == (7,)


def test_evidence_span_schema_binds_every_host_authority_anchor(
    connection: sqlite3.Connection,
) -> None:
    assert {
        "span_id",
        "evidence_id",
        "envelope_hash",
        "sanitized_hash",
        "admission_receipt_id",
        "admission_receipt_hash",
        "evidence_item_ordinal",
        "evidence_item_id",
        "evidence_item_json_pointer",
        "actor_role",
        "provenance",
        "observation_schema_id",
        "observation_schema_version",
        "observation_registered_schema_hash",
        "observation_receipt_id",
        "observation_receipt_hash",
        "observation_authority_issuer_id",
        "observation_json_pointer",
        "observation_value_hash",
    } <= _columns(connection, "cognitive_evidence_spans")


def test_task_scope_provenance_is_bound_to_host_conversation_registration(
    connection: sqlite3.Connection,
) -> None:
    assert _columns(connection, "cognitive_revision_task_scope_origins") == {
        "memory_id",
        "revision",
        "task_scope_id",
        "evidence_id",
        "registration_id",
    }


def test_relation_identity_is_principal_and_plan_scoped(
    connection: sqlite3.Connection,
) -> None:
    assert {"principal_id", "plan_id", "plan_hash", "operation_id"} <= _columns(
        connection, "cognitive_relations"
    )
    assert (
        "principal_id",
        "plan_id",
        "operation_id",
        "relation_kind",
        "source_memory_id",
        "source_revision",
        "target_memory_id",
        "target_revision",
    ) in _unique_indexes(connection, "cognitive_relations")


def test_conflict_schema_persists_two_immutable_members_and_one_resolution(
    connection: sqlite3.Connection,
) -> None:
    assert {
        "group_id",
        "principal_id",
        "memory_id",
        "incumbent_revision",
        "challenger_revision",
        "creation_plan_id",
        "creation_plan_hash",
        "operation_id",
        "group_hash",
    } <= _columns(connection, "cognitive_conflict_groups")
    assert {
        "group_id",
        "ordinal",
        "role",
        "principal_id",
        "memory_id",
        "revision",
        "content_hash",
        "evidence_set_hash",
        "member_hash",
    } == _columns(connection, "cognitive_conflict_members")
    assert {
        "group_id",
        "principal_id",
        "memory_id",
        "resolution_revision",
        "resolution_kind",
        "selected_member_ordinal",
        "plan_id",
        "plan_hash",
        "operation_id",
        "created_at",
        "resolution_hash",
    } == _columns(connection, "cognitive_conflict_resolutions")
    assert ("group_id", "role") in _unique_indexes(
        connection, "cognitive_conflict_members"
    )
    assert ("group_id", "memory_id", "revision") in _unique_indexes(
        connection, "cognitive_conflict_members"
    )

    trigger_names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'cognitive_conflict_%_immutable_%'"
        )
    }
    assert trigger_names == {
        "cognitive_conflict_groups_immutable_update",
        "cognitive_conflict_groups_immutable_delete",
        "cognitive_conflict_members_immutable_update",
        "cognitive_conflict_members_immutable_delete",
        "cognitive_conflict_resolutions_immutable_update",
        "cognitive_conflict_resolutions_immutable_delete",
    }


def test_mutation_receipt_is_strict_atomic_not_partial(
    connection: sqlite3.Connection,
) -> None:
    columns = _columns(connection, "memory_mutation_receipts")
    assert {
        "authority_ref",
        "run_id",
        "subject",
        "plan_outcome",
        "plan_json",
        "canonical_operation_ids_json",
        "apply_mode",
        "classification_decision_refs_json",
        "classification_decisions_hash",
        "committed_at",
    } <= columns
    assert "accepted_count" not in columns
    assert "rejected_count" not in columns


def test_classification_and_rejection_audits_have_explicit_authority_inputs(
    connection: sqlite3.Connection,
) -> None:
    assert {
        "policy_id",
        "policy_version",
        "policy_authority_ref",
        "policy_hash",
        "target_privacy_class",
        "proposed_privacy_class",
        "effective_privacy_class",
        "decision_hash",
    } <= _columns(connection, "cognitive_classification_decisions")
    assert {
        "span_hash",
        "authority_schema_version",
        "authority_id",
        "authority_hash",
        "classification_authority_ref",
        "required_privacy_class",
        "required_attributes_json",
    } <= _columns(connection, "cognitive_classification_evidence_authorities")
    assert {
        "plan_hash",
        "policy_hash",
        "reason_code",
        "rejection_hash",
    } <= _columns(connection, "memory_mutation_rejection_audits")


def test_recall_decision_binds_exact_context_and_evidence(
    connection: sqlite3.Connection,
) -> None:
    assert {
        "subject",
        "context_hash",
        "context_revision",
        "disclosure_context_json",
        "disclosure_context_hash",
        "evidence_refs_json",
        "evidence_refs_hash",
        "candidate_count_stage",
    } <= _columns(connection, "recall_decisions")


def test_expiring_projection_does_not_delete_registration_or_raw_evidence(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "INSERT INTO principals VALUES(?,?,?,?,?)",
        ("principal-1", "deployment-1", "household-1", "actor-1", 1.0),
    )
    connection.execute(
        """
        INSERT INTO evidence_envelopes VALUES(
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        (
            "evidence-1",
            "principal-1",
            "run-1",
            "actor-1",
            "user_message",
            "turn-1/user",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "credential-filter/v1",
            b"{}",
            "d" * 64,
            b"[]",
            b"{}",
            1.0,
        ),
    )
    connection.execute(
        """
        INSERT INTO conversation_evidence_registrations(
            registration_id, registration_hash, principal_id, evidence_id,
            envelope_hash, admission_receipt_id, admission_receipt_hash,
            metadata_id, metadata_hash, metadata_json, metadata_receipt_id,
            metadata_receipt_hash, metadata_receipt_json, authority_issuer_id,
            run_id, subject, conversation_id, primary_conversation_id,
            causal_group_id, causal_group_sequence, item_ordinal, group_item_count,
            ordered_group_manifest_hash, role, occurred_at, task_scope_id,
            tool_causal_link_json, entities_json, registration_json, registered_at
            , conversation_schema_version
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "registration-1",
            "e" * 64,
            "principal-1",
            "evidence-1",
            "c" * 64,
            "admission-1",
            "f" * 64,
            "metadata-1",
            "1" * 64,
            b"{}",
            "metadata-receipt-1",
            "2" * 64,
            b"{}",
            "host-conversation-registry",
            "run-1",
            "actor-1",
            "primary-1",
            "primary-1",
            "group-1",
            1,
            1,
            1,
            "3" * 64,
            "user",
            1.0,
            None,
            None,
            b"[]",
            b"{}",
            1.0,
            3,
        ),
    )
    connection.execute(
        """
        INSERT INTO short_horizon_chunks(
            chunk_id,principal_id,subject,primary_conversation_id,causal_group_id,
            causal_group_sequence,roles_json,task_scope_ids_json,entities_json,
            source_refs_json,effective_privacy_class,information_attributes_json,
            classification_authority_refs_json,public_text,content_hash,occurred_at,
            expires_at,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "chunk-1",
            "principal-1",
            "actor-1",
            "primary-1",
            "group-1",
            1,
            b'["user"]',
            b"[]",
            b"[]",
            b"[]",
            "public",
            b"[]",
            b'["classification-1"]',
            "user: hello",
            "4" * 64,
            1.0,
            2.0,
            1.0,
        ),
    )
    connection.execute(
        "INSERT INTO short_horizon_chunk_evidence VALUES(?,?,?,?,?)",
        ("chunk-1", 1, "registration-1", "evidence-1", "c" * 64),
    )
    assert connection.execute(
        "SELECT count(*) FROM short_horizon_fts WHERE chunk_id='chunk-1'"
    ).fetchone() == (1,)

    connection.execute("DELETE FROM short_horizon_chunks WHERE chunk_id='chunk-1'")

    assert connection.execute("SELECT count(*) FROM short_horizon_chunk_evidence").fetchone() == (
        0,
    )
    assert connection.execute("SELECT count(*) FROM evidence_envelopes").fetchone() == (1,)
    assert connection.execute(
        "SELECT count(*) FROM conversation_evidence_registrations"
    ).fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM short_horizon_fts").fetchone() == (0,)
    with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
        connection.execute("DELETE FROM evidence_envelopes WHERE evidence_id='evidence-1'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable conversation registration"):
        connection.execute(
            "DELETE FROM conversation_evidence_registrations WHERE registration_id='registration-1'"
        )
