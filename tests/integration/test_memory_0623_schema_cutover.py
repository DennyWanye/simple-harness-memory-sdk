"""0.6.23 cutover：附加式 schema 7.4（认知向量三表）；7.3 checksum 冻结；7.3 库打开前向；未知 checksum fail-closed。

照 0.6.1/0.6.2 先例：钉 checksum、旧库打开即用（receipt/meta/业务列不改写）、fail-closed。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import simple_harness_memory as m
from simple_harness_memory import __version__
from simple_harness_memory.backends import schema_v7_3, schema_v7_4, sqlite_v5
from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend
from simple_harness_memory.core.errors import MemoryCorruptionError, MemoryLegacySchemaUnsupported
from simple_harness_memory.migrations import cognitive_vector_forward as forward
from simple_harness_memory.migrations import settlement_upgrade
from tests.integration.test_memory_061_core import LINEAGE_A, _evidence

# 7.3 定稿 DDL checksum（冻结）与 0.6.23 定稿的 7.4 DDL checksum。
SCHEMA_CHECKSUM_V7_3 = "3634279614538c29329510e1a843c1d39eaff334e581c4e14032988a4919fb15"
SCHEMA_CHECKSUM_V7_4 = "43f1bb1ad4d55327c8a3e8929a9368565090a1f278f805622d834d46343d13c3"
VECTOR_TABLES = {"cognitive_vector_generations", "cognitive_vectors", "cognitive_vector_audit"}


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        connection.close()


def _meta(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    try:
        return {str(k): str(v) for k, v in connection.execute("SELECT key,value FROM schema_meta")}
    finally:
        connection.close()


async def _write_v7_3_database(path: Path, monkeypatch) -> schema_v7_3.InitializationReceipt:
    """Reproduce the frozen fresh-7.3 initializer contract through public operations."""

    with monkeypatch.context() as patch:
        for key in ("REQUIRED_TABLES", "SCHEMA_CHECKSUM", "SCHEMA_VERSION_LABEL", "InitializationReceipt"):
            patch.setattr(sqlite_v5, key, getattr(schema_v7_3, key))
        patch.setattr(sqlite_v5, "_DDL", schema_v7_3.ddl_statements())
        patch.setattr(forward, "probe_existing_root", settlement_upgrade.probe_existing_root)
        patch.setattr(forward, "inspect_root", settlement_upgrade.inspect_root)

        async def _skip(self):
            return None

        patch.setattr(SQLiteHumanMemoryBackend, "_load_cognitive_vector_cache_unlocked", _skip)
        patch.setattr(SQLiteHumanMemoryBackend, "_validate_cognitive_vector_integrity_unlocked", _skip)
        backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
        receipt = await backend.initialize()
        try:
            await backend.ingest_committed_evidence(*_evidence(1), analysis_lineage=LINEAGE_A)
        finally:
            await backend.close()
    assert receipt.schema_checksum == SCHEMA_CHECKSUM_V7_3
    assert _tables(path) == schema_v7_3.REQUIRED_TABLES
    return receipt


def test_0_6_23_pins_additive_schema_v7_4_and_freezes_v7_3() -> None:
    assert __version__ == "0.6.26"  # 0.6.24/0.6.25/0.6.26 不改 7.4 checksum
    assert schema_v7_3.SCHEMA_CHECKSUM == SCHEMA_CHECKSUM_V7_3
    assert schema_v7_4.SCHEMA_CHECKSUM == SCHEMA_CHECKSUM_V7_4 != SCHEMA_CHECKSUM_V7_3
    assert schema_v7_4.SCHEMA_CHECKSUM_V7_3 == SCHEMA_CHECKSUM_V7_3
    assert schema_v7_4.DDL == schema_v7_3.DDL + schema_v7_4.COGNITIVE_VECTOR_DDL
    assert (schema_v7_4.SCHEMA_VERSION, schema_v7_4.SCHEMA_VERSION_LABEL) == (7, "7.4")
    assert schema_v7_3.SCHEMA_VERSION_LABEL == "7.3"
    assert schema_v7_4.REQUIRED_TABLES == schema_v7_3.REQUIRED_TABLES | VECTOR_TABLES
    assert schema_v7_4.CANONICAL_MANIFEST_DERIVED_EXCLUSIONS - schema_v7_3.CANONICAL_MANIFEST_DERIVED_EXCLUSIONS == {
        "cognitive_vector_generations", "cognitive_vectors",
    }
    assert sqlite_v5.SCHEMA_CHECKSUM == SCHEMA_CHECKSUM_V7_4
    assert sqlite_v5.REQUIRED_TABLES == schema_v7_4.REQUIRED_TABLES
    assert len(forward.catalogs()) == 2 and set(forward.catalogs().values()) == set(settlement_upgrade.catalogs())


@pytest.mark.asyncio
async def test_fresh_0_6_23_database_uses_v7_4_and_reopens_same_receipt(tmp_path: Path) -> None:
    path = tmp_path / "fresh.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    receipt = await backend.initialize()
    await backend.close()
    assert receipt.schema_checksum == SCHEMA_CHECKSUM_V7_4
    assert _tables(path) == schema_v7_4.REQUIRED_TABLES
    meta = _meta(path)
    assert meta["schema_checksum"] == SCHEMA_CHECKSUM_V7_4 and forward.FORWARD_KEY not in meta
    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    assert await reopened.initialize() == receipt
    await reopened.close()
    assert _meta(path) == meta


@pytest.mark.asyncio
async def test_0_6_22_written_v7_3_database_is_forwarded_on_open_without_rewriting_identity(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "v7-3.db"
    receipt = await _write_v7_3_database(path, monkeypatch)
    meta_before = _meta(path)
    columns_before = {
        table: [row[1] for row in sqlite3.connect(path).execute(f"PRAGMA table_info({table})")]
        for table in ("evidence_envelopes", "cognitive_memory_revisions", "schema_meta")
    }

    reopened = SQLiteHumanMemoryBackend(path, now=lambda: 30.0)
    second = await reopened.initialize()
    try:
        assert second == receipt and second.schema_checksum == SCHEMA_CHECKSUM_V7_3
        assert reopened.initialization_receipt == receipt
        ingestion = await reopened.ingest_committed_evidence(*_evidence(2), analysis_lineage=LINEAGE_A)
        assert ingestion.evidence_id == "evidence-2"
    finally:
        await reopened.close()
    assert _tables(path) == schema_v7_4.REQUIRED_TABLES
    meta_after = _meta(path)
    marker = json.loads(meta_after.pop(forward.FORWARD_KEY))
    assert meta_after == meta_before  # original receipt binding and 7.3 checksum untouched
    assert marker["protocol"] == forward.PROTOCOL
    assert marker["source_schema_checksum"] == SCHEMA_CHECKSUM_V7_3
    assert marker["target_schema_checksum"] == SCHEMA_CHECKSUM_V7_4
    assert marker["added_ddl_hash"] == forward.added_ddl_hash()
    assert marker["source_catalog_id"] in settlement_upgrade.catalogs()
    assert forward.catalogs()[marker["target_catalog_id"]] == marker["source_catalog_id"]
    assert {
        table: [row[1] for row in sqlite3.connect(path).execute(f"PRAGMA table_info({table})")]
        for table in columns_before
    } == columns_before

    # Idempotent: a third open neither rewrites the marker nor appends a second one.
    third = SQLiteHumanMemoryBackend(path, now=lambda: 40.0)
    assert await third.initialize() == receipt
    await third.close()
    assert _meta(path) == {**meta_before, forward.FORWARD_KEY: _meta(path)[forward.FORWARD_KEY]}
    assert json.loads(_meta(path)[forward.FORWARD_KEY]) == marker
    # The frozen 7.3 upgrade entry treats the forwarded database as already settled.
    assert await m.migrate_human_memory_v7_2_to_v7_3(path, backup_path=path.with_suffix(".backup")) is None
    assert not path.with_suffix(".backup").exists()


@pytest.mark.asyncio
async def test_7_2_upgraded_database_keeps_7_3_marker_and_gains_forward_marker(tmp_path: Path, monkeypatch) -> None:
    from tests.integration.test_prospective_invalidation_settlement import legacy_case

    w, _entry, _source, init = await legacy_case(tmp_path, monkeypatch)
    with pytest.raises(MemoryLegacySchemaUnsupported):
        await m.build_human_memory_v7(w["path"], **w["kwargs"])
    upgraded = await m.migrate_human_memory_v7_2_to_v7_3(
        w["path"], backup_path=w["path"].with_suffix(".backup"),
        expected_initialization_receipt_hash=init.receipt_hash,
    )
    assert upgraded.target_schema_checksum == SCHEMA_CHECKSUM_V7_3
    assert set(_meta(w["path"])) == {
        "schema_version", "schema_epoch", "schema_checksum", "initialization_receipt_id",
        "initialization_receipt_hash", settlement_upgrade.MARKER_KEY,
    }
    manager = await m.build_human_memory_v7(w["path"], **w["kwargs"])
    try:
        assert manager._backend.initialization_receipt.to_json() == init.to_json()
    finally:
        await manager.close()
    meta = _meta(w["path"])
    assert settlement_upgrade.MARKER_KEY in meta and forward.FORWARD_KEY in meta
    assert json.loads(meta[settlement_upgrade.MARKER_KEY])["receipt_hash"] == upgraded.receipt_hash
    assert _tables(w["path"]) == schema_v7_4.REQUIRED_TABLES
    assert await m.migrate_human_memory_v7_2_to_v7_3(w["path"], backup_path=w["path"].with_suffix(".backup")) == upgraded


@pytest.mark.asyncio
async def test_unknown_checksum_and_tampered_forward_marker_fail_closed(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="checksum differs"):
        schema_v7_4.InitializationReceipt("init-x", 1.0, "a" * 64, schema_checksum="f" * 64)
    path = tmp_path / "tampered-checksum.db"
    backend = SQLiteHumanMemoryBackend(path, now=lambda: 20.0)
    await backend.initialize()
    await backend.close()
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("UPDATE schema_meta SET value=? WHERE key='schema_checksum'", ("f" * 64,))
    finally:
        connection.close()
    with pytest.raises((MemoryLegacySchemaUnsupported, MemoryCorruptionError)):
        await SQLiteHumanMemoryBackend(path, now=lambda: 30.0).initialize()

    forwarded = tmp_path / "tampered-marker.db"
    await _write_v7_3_database(forwarded, monkeypatch)
    opened = SQLiteHumanMemoryBackend(forwarded, now=lambda: 30.0)
    await opened.initialize()
    await opened.close()
    connection = sqlite3.connect(forwarded, isolation_level=None)
    try:
        wire = json.loads(connection.execute(
            "SELECT value FROM schema_meta WHERE key=?", (forward.FORWARD_KEY,)
        ).fetchone()[0])
        wire["target_schema_checksum"] = "e" * 64
        connection.execute(
            "UPDATE schema_meta SET value=? WHERE key=?", (json.dumps(wire), forward.FORWARD_KEY)
        )
    finally:
        connection.close()
    with pytest.raises((MemoryLegacySchemaUnsupported, MemoryCorruptionError)):
        await SQLiteHumanMemoryBackend(forwarded, now=lambda: 40.0).initialize()
