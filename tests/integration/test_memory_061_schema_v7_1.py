"""Historical7.0 fixture preserved; approved0.6.8 fresh7.2 rejects old roots unchanged."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from pathlib import Path

import pytest

from simple_harness_memory.backends.schema_v5 import (
    DDL,
    DDL_V7_0,
    SCHEMA_CHECKSUM,
    SCHEMA_CHECKSUM_V7_0,
    SCHEMA_EPOCH,
    SCHEMA_MINOR_VERSION,
    SCHEMA_VERSION,
    SCHEMA_VERSION_LABEL,
    V7_1_ADDED_COLUMNS,
    ddl_statements,
)
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryLegacySchemaUnsupported


def _legacy_receipt_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_v7_0_database(path: Path) -> dict[str, object]:
    """用 0.6.0 的真实 DDL（无新列）建库并写入其 receipt/meta。"""

    hmac_key = secrets.token_bytes(32)
    receipt = {
        "receipt_id": "init-v7-0",
        "schema_version": SCHEMA_VERSION,
        "schema_epoch": SCHEMA_EPOCH,
        "schema_checksum": SCHEMA_CHECKSUM_V7_0,
        "audit_cursor_authority_hash": hashlib.sha256(hmac_key).hexdigest(),
        "created_at": 12.5,
    }
    receipt_hash = _legacy_receipt_hash(receipt)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in ddl_statements(DDL_V7_0):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO audit_cursor_authority(singleton,hmac_key_hex) VALUES(1,?)",
            (hmac_key.hex(),),
        )
        connection.execute(
            "INSERT INTO initialization_receipts(singleton,receipt_id,schema_version,"
            "schema_epoch,schema_checksum,audit_cursor_authority_hash,created_at,receipt_hash) "
            "VALUES(1,?,?,?,?,?,?,?)",
            (
                receipt["receipt_id"],
                receipt["schema_version"],
                receipt["schema_epoch"],
                receipt["schema_checksum"],
                receipt["audit_cursor_authority_hash"],
                receipt["created_at"],
                receipt_hash,
            ),
        )
        connection.executemany(
            "INSERT INTO schema_meta(key,value) VALUES(?,?)",
            (
                ("schema_version", str(SCHEMA_VERSION)),
                ("schema_epoch", SCHEMA_EPOCH),
                ("schema_checksum", SCHEMA_CHECKSUM_V7_0),
                ("initialization_receipt_id", str(receipt["receipt_id"])),
                ("initialization_receipt_hash", receipt_hash),
            ),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()
    return {**receipt, "receipt_hash": receipt_hash}


def _columns(path: Path, table: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
    finally:
        connection.close()


def test_schema_v7_1_constants_and_v7_0_ddl_are_pinned() -> None:
    assert (SCHEMA_VERSION, SCHEMA_MINOR_VERSION, SCHEMA_VERSION_LABEL) == (7, 2, "7.2")
    assert hashlib.sha256(DDL.encode("utf-8")).hexdigest() == SCHEMA_CHECKSUM
    assert hashlib.sha256(DDL_V7_0.encode("utf-8")).hexdigest() == SCHEMA_CHECKSUM_V7_0
    assert SCHEMA_CHECKSUM != SCHEMA_CHECKSUM_V7_0
    assert V7_1_ADDED_COLUMNS == (("evidence_envelopes", "analysis_lineage_json", "BLOB"),)
    assert "analysis_lineage_json" in DDL and "analysis_lineage_json" not in DDL_V7_0


@pytest.mark.asyncio
async def test_v7_0_valid_database_is_rejected_without_old_automatic_migration(tmp_path: Path) -> None:
    path = tmp_path / "v7-0.db"
    _write_v7_0_database(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await backend.initialize()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "analysis_lineage_json" not in _columns(path, "evidence_envelopes")


@pytest.mark.asyncio
async def test_fresh_v7_2_has_lineage_and_source_receipts_old_fixture_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    first = await backend.initialize()
    await backend.close()
    assert "analysis_lineage_json" in _columns(path, "evidence_envelopes")
    assert "admission_receipt_hash" in _columns(path, "source_admission_receipts")
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    assert await reopened.initialize() == first
    await reopened.close()


@pytest.mark.asyncio
async def test_unknown_checksum_still_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    _write_v7_0_database(path)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("UPDATE schema_meta SET value='tampered' WHERE key='schema_checksum'")
    finally:
        connection.close()
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await backend.initialize()
