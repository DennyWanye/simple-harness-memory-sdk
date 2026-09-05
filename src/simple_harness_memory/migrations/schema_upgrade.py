"""Explicit, additive7.0/7.1 upgrade. No automatic migration or data replacement."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from simple_harness_memory.backends.schema_v5 import (
    SCHEMA_CHECKSUM,
    SCHEMA_CHECKSUM_V7_0,
    SCHEMA_CHECKSUM_V7_1,
    SOURCE_ADMISSION_DDL,
    InitializationReceipt,
    ddl_statements,
)
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryIdempotencyConflict,
    MemoryLegacySchemaUnsupported,
    MemoryValidationError,
    MemoryWriterConflict,
)

MARKER_KEY = "source_admission_upgrade_v1"
PROTOCOL = "memory.schema.source-admission-upgrade.v1"
CATALOGS = {
    "fresh-7.0": "898c3b09b0d635fb36d15a35305eb89a73aec56e21ecb2b8b83dc789769df2ca",
    "fresh-7.1": "307199a1ffe903de5b94dd6bc0f9033e109528e00e1fb03afff34f41a665fa13",
    "alter-7.1": "926307f8fb1e60dcda0a3cdb97b70f1baf2cbaf8934fc8f46806129c199ced32",
    "fresh-7.2": "0814906373db2e3898ff775e2515764493bff9f15565c59ba22c3f66c371c221",
    "alter-7.2": "3f05ba843314a5227be263723422388957c32518ea8e9e665250a3fa4c0947fc",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _hash(domain: str, payload: Any) -> str:
    return hashlib.sha256(_canonical({"domain": domain, "payload": payload}).encode()).hexdigest()


def _receipt_id(payload: dict[str, Any]) -> str:
    keys = (
        "original_initialization_receipt_id",
        "original_initialization_receipt_hash",
        "source_schema_checksum",
        "target_schema_checksum",
    )
    return "schema-upgrade:" + _hash(
        "memory.schema.source-admission-upgrade.id.v1", {key: payload[key] for key in keys}
    )


@dataclass(frozen=True, slots=True)
class HumanMemorySchemaUpgradeReceipt:
    protocol: str
    receipt_id: str
    source_schema_checksum: str
    target_schema_checksum: str
    source_catalog_id: str
    target_catalog_id: str
    original_initialization_receipt_id: str
    original_initialization_receipt_hash: str
    added_ddl_hash: str
    preserved_old_columns_root_hash: str
    backup_sha256: str
    committed_at: float
    receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.protocol != PROTOCOL:
            raise MemoryValidationError("schema_upgrade_protocol_invalid")
        for key, value in self.to_json().items():
            if key.endswith(("hash", "checksum", "sha256", "catalog_id")) and (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise MemoryValidationError("schema_upgrade_digest_invalid")
        if (
            not isinstance(self.original_initialization_receipt_id, str)
            or not self.original_initialization_receipt_id.strip()
        ):
            raise MemoryValidationError("schema_upgrade_initialization_id_invalid")
        if (
            type(self.committed_at) not in (int, float)
            or not math.isfinite(self.committed_at)
            or self.committed_at < 0
        ):
            raise MemoryValidationError("schema_upgrade_time_invalid")
        object.__setattr__(self, "committed_at", float(self.committed_at))
        if self.receipt_id != _receipt_id(self.to_json()):
            raise MemoryValidationError("schema_upgrade_receipt_id_invalid")
        object.__setattr__(
            self,
            "receipt_hash",
            _hash("memory.schema.source-admission-upgrade.receipt.v1", self.to_json()),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            key: getattr(self, key) for key in self.__dataclass_fields__ if key != "receipt_hash"
        }


def _catalog(connection: sqlite3.Connection) -> str:
    objects = [
        list(r)
        for r in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        )
    ]
    tables = [r[1] for r in objects if r[0] == "table"]
    # Catalog names are quoted as identifiers; never interpolate arbitrary SQL.
    values = {
        name: {
            pragma: [list(r) for r in connection.execute(f"PRAGMA {pragma}({_quote(name)})")]
            for pragma in ("table_xinfo", "index_list", "foreign_key_list")
        }
        for name in tables
    }
    return hashlib.sha256(_canonical({"objects": objects, "tables": values}).encode()).hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ddl(source_catalog: str) -> tuple[str, ...]:
    return (
        ("ALTER TABLE evidence_envelopes ADD COLUMN analysis_lineage_json BLOB",)
        if source_catalog == CATALOGS["fresh-7.0"]
        else ()
    ) + tuple(ddl_statements(SOURCE_ADMISSION_DDL))


def _target(source_catalog: str) -> str:
    return CATALOGS["fresh-7.2" if source_catalog == CATALOGS["fresh-7.1"] else "alter-7.2"]


def _added_hash(source_catalog: str) -> str:
    return _hash("memory.schema.source-admission-upgrade.ddl.v1", list(_ddl(source_catalog)))


@dataclass(frozen=True)
class _Root:
    initialization: InitializationReceipt
    catalog_id: str
    marker: HumanMemorySchemaUpgradeReceipt | None


def inspect_root(connection: sqlite3.Connection, *, allow_legacy: bool = False) -> _Root:
    """One caller-owned SQLite snapshot; finite schema+init+marker+cursor authority."""
    connection.row_factory = sqlite3.Row
    actual = _catalog(connection)
    if actual not in CATALOGS.values():
        raise MemoryLegacySchemaUnsupported()
    meta = {str(r[0]): str(r[1]) for r in connection.execute("SELECT key,value FROM schema_meta")}
    expected_keys = {
        "schema_version",
        "schema_epoch",
        "schema_checksum",
        "initialization_receipt_id",
        "initialization_receipt_hash",
    }
    if set(meta) not in (expected_keys, expected_keys | {MARKER_KEY}):
        raise MemoryLegacySchemaUnsupported()
    rows = connection.execute("SELECT * FROM initialization_receipts").fetchall()
    if len(rows) != 1:
        raise MemoryCorruptionError("initialization receipt cardinality differs")
    row = rows[0]
    receipt = InitializationReceipt(
        **{
            key: row[key]
            for key in (
                "receipt_id",
                "created_at",
                "audit_cursor_authority_hash",
                "schema_version",
                "schema_epoch",
                "schema_checksum",
            )
        }
    )
    if (
        row["receipt_hash"] != receipt.receipt_hash
        or meta["initialization_receipt_id"] != receipt.receipt_id
        or meta["initialization_receipt_hash"] != receipt.receipt_hash
        or meta["schema_checksum"] != receipt.schema_checksum
        or meta["schema_version"] != str(receipt.schema_version)
        or meta["schema_epoch"] != receipt.schema_epoch
    ):
        raise MemoryCorruptionError("schema upgrade initialization binding differs")
    authority = connection.execute(
        "SELECT singleton,hmac_key_hex FROM audit_cursor_authority"
    ).fetchall()
    if len(authority) != 1 or authority[0][0] != 1:
        raise MemoryCorruptionError("audit cursor authority cardinality differs")
    try:
        key = bytes.fromhex(authority[0][1])
    except (ValueError, TypeError) as exc:
        raise MemoryCorruptionError("audit cursor authority is invalid") from exc
    if len(key) != 32 or hashlib.sha256(key).hexdigest() != receipt.audit_cursor_authority_hash:
        raise MemoryCorruptionError("audit cursor authority hash differs")
    marker = None
    if MARKER_KEY in meta:
        try:
            payload = json.loads(meta[MARKER_KEY])
            digest = payload.pop("receipt_hash")
            marker = HumanMemorySchemaUpgradeReceipt(**payload)
            if (
                marker.receipt_hash != digest
                or _canonical({**marker.to_json(), "receipt_hash": digest}) != meta[MARKER_KEY]
            ):
                raise ValueError("marker hash differs")
        except (TypeError, ValueError, KeyError) as exc:
            raise MemoryCorruptionError("schema upgrade marker invalid") from exc
        permitted = (
            {CATALOGS["fresh-7.0"]}
            if receipt.schema_checksum == SCHEMA_CHECKSUM_V7_0
            else {CATALOGS["fresh-7.1"], CATALOGS["alter-7.1"]}
            if receipt.schema_checksum == SCHEMA_CHECKSUM_V7_1
            else set()
        )
        if (
            marker.source_catalog_id not in permitted
            or marker.source_schema_checksum != receipt.schema_checksum
            or marker.target_schema_checksum != SCHEMA_CHECKSUM
            or marker.target_catalog_id != actual
            or actual != _target(marker.source_catalog_id)
            or marker.original_initialization_receipt_id != receipt.receipt_id
            or marker.original_initialization_receipt_hash != receipt.receipt_hash
            or marker.added_ddl_hash != _added_hash(marker.source_catalog_id)
        ):
            raise MemoryCorruptionError("schema upgrade marker binding differs")
    elif receipt.schema_checksum == SCHEMA_CHECKSUM:
        if actual != CATALOGS["fresh-7.2"]:
            raise MemoryLegacySchemaUnsupported()
    elif not allow_legacy or not (
        (receipt.schema_checksum == SCHEMA_CHECKSUM_V7_0 and actual == CATALOGS["fresh-7.0"])
        or (
            receipt.schema_checksum == SCHEMA_CHECKSUM_V7_1
            and actual in {CATALOGS["fresh-7.1"], CATALOGS["alter-7.1"]}
        )
    ):
        raise MemoryLegacySchemaUnsupported()
    if [r[0] for r in connection.execute("PRAGMA integrity_check")] != ["ok"]:
        raise MemoryCorruptionError("human-memory v7 integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MemoryCorruptionError("human-memory v7 foreign key check failed")
    return _Root(receipt, actual, marker)


def _raise_if_snapshot_unavailable(exc: sqlite3.Error) -> None:
    # Extended result codes (e.g. BUSY_SNAPSHOT) retain their primary low byte.
    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        raise MemoryWriterConflict() from exc
    if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_READONLY):
        raise MemoryValidationError("schema_read_snapshot_unavailable") from exc


def _open_snapshot(path: Path) -> sqlite3.Connection:
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        return db
    except sqlite3.Error as exc:
        if db is not None:
            db.close()
        _raise_if_snapshot_unavailable(exc)
        raise MemoryValidationError("schema_read_snapshot_unavailable") from exc


def _columns(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    return {
        str(row[0]): tuple(
            str(c[1]) for c in connection.execute(f"PRAGMA table_info({_quote(str(row[0]))})")
        )
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    }


def _old_root(connection: sqlite3.Connection, columns: dict[str, tuple[str, ...]]) -> str:
    def encode(value: Any) -> Any:
        return {"blob_hex": value.hex()} if isinstance(value, bytes) else value

    result = {}
    for table, names in columns.items():
        where = f" WHERE key<>'{MARKER_KEY}'" if table == "schema_meta" else ""
        rows = [
            [encode(v) for v in row]
            for row in connection.execute(
                f"SELECT {','.join(map(_quote, names))} FROM {_quote(table)}{where}"
            )
        ]
        result[table] = {"columns": list(names), "rows": sorted(rows, key=_canonical)}
    return hashlib.sha256(_canonical(result).encode()).hexdigest()


async def _validate_canonical_snapshot(connection: sqlite3.Connection, root: _Root) -> None:
    """Reuse SDK canonical validators on a disposable snapshot, never write source.

    Old roots lack columns/tables expected by the current union reader. The clone
    receives only allowed DDL so those readers can check unchanged original facts.
    It is never an output database, backup artifact or source of rewritten receipts.
    """
    from simple_harness_memory.backends.upgrade_validation import validate_snapshot

    await validate_snapshot(connection, root)


async def probe_existing_root(path: Path) -> tuple[str, InitializationReceipt | None]:
    from simple_harness_memory.backends.sqlite_v5 import _absolute_safe_probe_path

    path = _absolute_safe_probe_path(path)
    if not path.exists():
        if path.with_name(path.name + "-wal").exists():
            raise MemoryValidationError("schema_read_snapshot_unavailable")
        return "fresh", None
    db = _open_snapshot(path)
    try:
        try:
            if not db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                return "fresh", None
            root = inspect_root(db)
        except (MemoryCorruptionError, sqlite3.Error, TypeError, ValueError) as exc:
            if isinstance(exc, sqlite3.Error):
                _raise_if_snapshot_unavailable(exc)
            # Preserve the original initializer's schema/initial receipt rejection.
            # Later canonical business corruption keeps its existing corruption type.
            raise MemoryLegacySchemaUnsupported() from exc
        await _validate_canonical_snapshot(db, root)
        return "v5", root.initialization
    finally:
        db.close()


def _fault(point: str) -> None:
    """Source-test injection seam. Production has no callback/environment override."""


async def migrate_human_memory_v7_to_v7_2(
    db_path: str | Path,
    *,
    backup_path: str | Path,
    expected_initialization_receipt_hash: str | None = None,
) -> HumanMemorySchemaUpgradeReceipt | None:
    from simple_harness_memory.backends.sqlite_v5 import (
        SQLiteHumanMemoryBackend,
        _absolute_safe_probe_path,
    )

    if expected_initialization_receipt_hash is not None and (
        type(expected_initialization_receipt_hash) is not str
        or len(expected_initialization_receipt_hash) != 64
        or any(c not in "0123456789abcdef" for c in expected_initialization_receipt_hash)
    ):
        raise MemoryValidationError("schema_upgrade_expected_hash_invalid")

    source = _absolute_safe_probe_path(Path(db_path))
    backup = _absolute_safe_probe_path(Path(backup_path))
    if (
        not source.exists()
        or source == backup
        or (backup.exists() and os.path.samefile(source, backup))
    ):
        raise MemoryValidationError("schema_upgrade_paths_invalid")
    preflight = _open_snapshot(source)
    try:
        root = inspect_root(preflight, allow_legacy=True)
        if (
            expected_initialization_receipt_hash is not None
            and expected_initialization_receipt_hash != root.initialization.receipt_hash
        ):
            raise MemoryIdempotencyConflict("schema_upgrade_initialization_conflict")
        await _validate_canonical_snapshot(preflight, root)
    except sqlite3.Error as exc:
        _raise_if_snapshot_unavailable(exc)
        raise
    finally:
        preflight.close()
    lease = SQLiteHumanMemoryBackend(source)
    lease._secure_path = source
    lease._acquire_writer_lease()
    writer = None
    snapshot = None
    try:
        # Hold a read connection until after the writer closes. Besides pinning
        # the backup view, it prevents a rejected write connection's close from
        # checkpointing previously committed WAL into the original main file.
        snapshot = _open_snapshot(source)
        writer = sqlite3.connect(source, isolation_level=None, timeout=0)
        writer.execute("BEGIN IMMEDIATE")
        fenced = inspect_root(writer, allow_legacy=True)
        if fenced != root:
            raise MemoryIdempotencyConflict("schema_upgrade_initialization_conflict")
        same = inspect_root(snapshot, allow_legacy=True)
        if same != fenced:
            raise MemoryIdempotencyConflict("schema_upgrade_snapshot_conflict")
        await _validate_canonical_snapshot(snapshot, same)
        if same.marker is not None:
            writer.execute("ROLLBACK")
            return same.marker
        if same.initialization.schema_checksum == SCHEMA_CHECKSUM:
            writer.execute("ROLLBACK")
            return None
        columns = _columns(snapshot)
        before = _old_root(snapshot, columns)
        if _old_root(writer, columns) != before:
            raise MemoryIdempotencyConflict("schema_upgrade_snapshot_conflict")
        if not backup.exists():
            fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            target = sqlite3.connect(backup)
            try:
                snapshot.backup(target)
            finally:
                target.close()
            with backup.open("rb") as f:
                os.fsync(f.fileno())
            if os.name == "posix":
                directory = os.open(backup.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        try:
            check = _open_snapshot(backup)
            try:
                if (
                    inspect_root(check, allow_legacy=True) != same
                    or _old_root(check, columns) != before
                ):
                    raise ValueError("backup state differs")
                await _validate_canonical_snapshot(check, same)
            finally:
                check.close()
        except (
            sqlite3.Error,
            ValueError,
            MemoryCorruptionError,
            MemoryLegacySchemaUnsupported,
            MemoryValidationError,
        ) as exc:
            if isinstance(exc, sqlite3.Error):
                _raise_if_snapshot_unavailable(exc)
            raise MemoryIdempotencyConflict("schema_upgrade_backup_conflict") from exc
        digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        _fault("after_backup")
        for statement in _ddl(same.catalog_id):
            writer.execute(statement)
        _fault("after_ddl")
        payload: dict[str, Any] = dict(
            protocol=PROTOCOL,
            source_schema_checksum=same.initialization.schema_checksum,
            target_schema_checksum=SCHEMA_CHECKSUM,
            source_catalog_id=same.catalog_id,
            target_catalog_id=_target(same.catalog_id),
            original_initialization_receipt_id=same.initialization.receipt_id,
            original_initialization_receipt_hash=same.initialization.receipt_hash,
            added_ddl_hash=_added_hash(same.catalog_id),
            preserved_old_columns_root_hash=before,
            backup_sha256=digest,
            committed_at=time.time(),
        )
        receipt = HumanMemorySchemaUpgradeReceipt(receipt_id=_receipt_id(payload), **payload)
        writer.execute(
            "INSERT INTO schema_meta(key,value) VALUES(?,?)",
            (MARKER_KEY, _canonical({**receipt.to_json(), "receipt_hash": receipt.receipt_hash})),
        )
        if inspect_root(writer).marker != receipt or _old_root(writer, columns) != before:
            raise MemoryCorruptionError("schema_upgrade_preservation_differs")
        _fault("before_commit")
        writer.execute("COMMIT")
        _fault("after_commit")
        return receipt
    except sqlite3.OperationalError as exc:
        _raise_if_snapshot_unavailable(exc)
        raise
    finally:
        if writer is not None:
            writer.close()  # rollback if uncommitted; committed ACK loss stays committed
        if snapshot is not None:
            snapshot.close()
        lease._release_writer_lease()
