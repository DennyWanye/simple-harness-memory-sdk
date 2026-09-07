"""Explicit 7.2 -> 7.3 upgrade; preserve every old row and original init receipt."""
from __future__ import annotations
import hashlib
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from simple_harness_memory.backends import schema_v5 as old_schema, schema_v7_3 as schema
from simple_harness_memory.migrations import schema_upgrade as old
from simple_harness_memory.core.errors import (
    MemoryCorruptionError, MemoryIdempotencyConflict, MemoryLegacySchemaUnsupported,
    MemoryValidationError,
)

MARKER_KEY = 'prospective_settlement_upgrade_v1'
PROTOCOL = 'memory.schema.prospective-settlement-upgrade.v1'

@lru_cache(maxsize=1)
def catalogs():
    """Exact SQLite catalogs, derived only from frozen DDL plus the additive DDL."""
    result = {}
    variants = {'fresh-7.2': old_schema.DDL,
        'alter-7.2': old_schema.DDL_V7_0 + '\nALTER TABLE evidence_envelopes ADD COLUMN analysis_lineage_json BLOB;\n' + old_schema.SOURCE_ADMISSION_DDL}
    for name, ddl in variants.items():
        db = sqlite3.connect(':memory:')
        try:
            for statement in old_schema.ddl_statements(ddl):
                db.execute(statement)
            if old._catalog(db) != old.CATALOGS[name]:
                raise MemoryCorruptionError('settlement_base_catalog_differs')
            for statement in schema.ddl_statements(schema.TERMINAL_DDL):
                db.execute(statement)
            result[old._catalog(db)] = old.CATALOGS[name]
        finally:
            db.close()
    return result


def _id(payload):
    return 'schema-upgrade:' + old._hash(PROTOCOL + '.id', {key: payload[key] for key in (
        'original_initialization_receipt_id', 'original_initialization_receipt_hash',
        'source_schema_checksum', 'target_schema_checksum')})

@dataclass(frozen=True, slots=True)
class ProspectiveSettlementSchemaUpgradeReceipt:
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

    def __post_init__(self):
        from simple_harness_memory.core.mutation_receipts import _identifier
        _identifier(self.original_initialization_receipt_id, "original_initialization_receipt_id")
        if self.protocol != PROTOCOL or self.receipt_id != _id(self.to_json()):
            raise MemoryValidationError('settlement_upgrade_identity_invalid')
        for key, value in self.to_json().items():
            if key.endswith(('hash','checksum','sha256','catalog_id')) and (
                type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):
                raise MemoryValidationError('settlement_upgrade_digest_invalid')
        if type(self.committed_at) not in (int,float) or not math.isfinite(self.committed_at) or self.committed_at<0:
            raise MemoryValidationError('settlement_upgrade_time_invalid')
        object.__setattr__(self,'committed_at',float(self.committed_at))
        object.__setattr__(self,'receipt_hash',old._hash(PROTOCOL+'.receipt', self.to_json()))

    def to_json(self):
        return {key:getattr(self,key) for key in self.__dataclass_fields__ if key!='receipt_hash'}

@dataclass(frozen=True)
class _Root:
    initialization: old_schema.InitializationReceipt
    catalog_id: str
    marker: ProspectiveSettlementSchemaUpgradeReceipt | None


def _added_hash():
    return old._hash(PROTOCOL+'.ddl', list(schema.ddl_statements(schema.TERMINAL_DDL)))


def inspect_root(connection, *, actual=None, meta=None):
    """``actual``/``meta`` let an additive successor (7.4) verify the frozen 7.3 identity
    beneath its own catalog and marker; omitted, both are read from the connection."""
    connection.row_factory = sqlite3.Row
    if actual is None:
        actual = old._catalog(connection)
    base = catalogs().get(actual)
    if base is None:
        raise MemoryLegacySchemaUnsupported()
    if meta is None:
        meta = {str(r[0]):str(r[1]) for r in connection.execute('SELECT key,value FROM schema_meta')}
    else:
        meta = dict(meta)
    if MARKER_KEY in meta:
        wire = meta.pop(MARKER_KEY)
        try:
            if len(wire.encode("utf-8")) > 1_048_576: raise ValueError("marker too large")
            value=json.loads(wire)
            if type(value) is not dict: raise ValueError("marker must be object")
            digest=value.pop('receipt_hash')
            marker=ProspectiveSettlementSchemaUpgradeReceipt(**value)
            if marker.receipt_hash!=digest or old._canonical({**marker.to_json(),'receipt_hash':digest})!=wire:
                raise ValueError('marker wire differs')
        except (KeyError,TypeError,ValueError) as exc:
            raise MemoryCorruptionError('settlement_upgrade_marker_invalid') from exc
        # The actual complete catalog was checked above; this verifies the preserved
        # old receipt/optional 7.0-7.2 marker against its exact original base catalog.
        root=old._inspect_identity(connection,base,meta)
        init=root.initialization
        if (marker.source_schema_checksum!=old_schema.SCHEMA_CHECKSUM
            or marker.target_schema_checksum!=schema.SCHEMA_CHECKSUM
            or marker.source_catalog_id!=base or marker.target_catalog_id!=actual
            or marker.original_initialization_receipt_id!=init.receipt_id
            or marker.original_initialization_receipt_hash!=init.receipt_hash
            or marker.added_ddl_hash!=_added_hash()):
            raise MemoryCorruptionError('settlement_upgrade_marker_binding_differs')
        return _Root(init,actual,marker)
    expected={'schema_version','schema_epoch','schema_checksum','initialization_receipt_id','initialization_receipt_hash'}
    if set(meta)!=expected or base!=old.CATALOGS['fresh-7.2']:
        raise MemoryLegacySchemaUnsupported()
    rows=connection.execute('SELECT * FROM initialization_receipts').fetchall()
    if len(rows)!=1:
        raise MemoryCorruptionError('initialization receipt cardinality differs')
    row=rows[0]
    init=schema.InitializationReceipt(**{key:row[key] for key in (
        'receipt_id','created_at','audit_cursor_authority_hash','schema_version','schema_epoch','schema_checksum')})
    if (init.schema_checksum!=schema.SCHEMA_CHECKSUM or row['receipt_hash']!=init.receipt_hash or meta!={
        'schema_version':str(init.schema_version),'schema_epoch':init.schema_epoch,
        'schema_checksum':init.schema_checksum,'initialization_receipt_id':init.receipt_id,
        'initialization_receipt_hash':init.receipt_hash}):
        raise MemoryCorruptionError('settlement_initialization_binding_differs')
    authority=connection.execute('SELECT singleton,hmac_key_hex FROM audit_cursor_authority').fetchall()
    try:
        key=bytes.fromhex(authority[0][1])
        if len(authority)!=1 or authority[0][0]!=1 or len(key)!=32 or hashlib.sha256(key).hexdigest()!=init.audit_cursor_authority_hash:
            raise ValueError('cursor differs')
    except (IndexError,TypeError,ValueError) as exc:
        raise MemoryCorruptionError('settlement_cursor_authority_differs') from exc
    if [r[0] for r in connection.execute('PRAGMA integrity_check')]!=['ok'] or connection.execute('PRAGMA foreign_key_check').fetchone():
        raise MemoryCorruptionError('settlement_schema_integrity_differs')
    return _Root(init,actual,None)


async def _validate_snapshot(connection,root):
    from simple_harness_memory.backends.upgrade_validation import validate_snapshot
    await validate_snapshot(connection,root)


async def probe_existing_root(path):
    from simple_harness_memory.backends.sqlite_v5 import _absolute_safe_probe_path
    path=_absolute_safe_probe_path(path)
    if not path.exists():
        if path.with_name(path.name+'-wal').exists():
            raise MemoryValidationError('schema_read_snapshot_unavailable')
        return 'fresh',None
    db=old._open_snapshot(path)
    try:
        try:
            if not db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
                return 'fresh',None
            root=inspect_root(db)
        except (MemoryCorruptionError,sqlite3.Error,TypeError,ValueError) as exc:
            if isinstance(exc,sqlite3.Error): old._raise_if_snapshot_unavailable(exc)
            raise MemoryLegacySchemaUnsupported() from exc
        await _validate_snapshot(db,root)
        return 'v5',root.initialization
    finally:
        db.close()


def _preserved_root(connection,columns):
    # Include every old metadata key (including the older upgrade marker), while
    # excluding ONLY the newly added marker. Old data are never rewritten.
    result={}
    def encode(v): return {'blob_hex':v.hex()} if isinstance(v,bytes) else v
    for table,names in columns.items():
        where=" WHERE key<>?" if table=='schema_meta' else ''
        rows=connection.execute(f"SELECT {','.join(map(old._quote,names))} FROM {old._quote(table)}{where}",
            (MARKER_KEY,) if where else ())
        result[table]={'columns':list(names),'rows':sorted(([encode(v) for v in row] for row in rows),key=old._canonical)}
    return hashlib.sha256(old._canonical(result).encode()).hexdigest()


def _fault(point):
    """Test-only failure injection; no production callback or environment switch."""


def _existing(connection):
    from simple_harness_memory.migrations import cognitive_vector_forward as successor
    actual = old._catalog(connection)
    if actual in successor.catalogs():
        # Already carried forward to the additive 7.4 successor: same 7.3 identity/marker.
        root = successor.inspect_root(connection)
        return _Root(root.initialization, root.catalog_id, root.marker)
    if actual in catalogs(): return inspect_root(connection)
    return old.inspect_root(connection)


async def migrate_human_memory_v7_2_to_v7_3(db_path, *, backup_path, expected_initialization_receipt_hash=None):
    from simple_harness_memory.backends.sqlite_v5 import SQLiteHumanMemoryBackend,_absolute_safe_probe_path
    from simple_harness_memory.core.mutation_receipts import _digest
    if expected_initialization_receipt_hash is not None:
        _digest(expected_initialization_receipt_hash,'expected_initialization_receipt_hash')
    source=_absolute_safe_probe_path(Path(db_path)); backup=_absolute_safe_probe_path(Path(backup_path))
    if not source.exists() or source==backup or (backup.exists() and os.path.samefile(source,backup)):
        raise MemoryValidationError('settlement_upgrade_paths_invalid')
    preflight=old._open_snapshot(source)
    try:
        root=_existing(preflight)
        if expected_initialization_receipt_hash is not None and root.initialization.receipt_hash!=expected_initialization_receipt_hash:
            raise MemoryIdempotencyConflict('settlement_upgrade_initialization_conflict')
        await _validate_snapshot(preflight,root)
    finally:
        preflight.close()
    lease=SQLiteHumanMemoryBackend(source); lease._secure_path=source; lease._acquire_writer_lease()
    writer=snapshot=None
    try:
        snapshot=old._open_snapshot(source)
        writer=sqlite3.connect(source,isolation_level=None,timeout=0)
        writer.execute('BEGIN IMMEDIATE')
        same=_existing(writer)
        if same!=root or _existing(snapshot)!=same:
            raise MemoryIdempotencyConflict('settlement_upgrade_snapshot_conflict')
        await _validate_snapshot(snapshot,same)
        from simple_harness_memory.migrations import cognitive_vector_forward as successor
        if same.catalog_id in catalogs() or same.catalog_id in successor.catalogs():
            writer.execute('ROLLBACK'); return same.marker
        columns=old._columns(snapshot); before=_preserved_root(snapshot,columns)
        if _preserved_root(writer,columns)!=before:
            raise MemoryIdempotencyConflict('settlement_upgrade_snapshot_conflict')
        if not backup.exists():
            fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            target=sqlite3.connect(backup)
            try: snapshot.backup(target)
            finally: target.close()
            with backup.open('rb') as file: os.fsync(file.fileno())
            if os.name=='posix':
                directory=os.open(backup.parent,os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
        check=old._open_snapshot(backup)
        try:
            if old.inspect_root(check)!=same or _preserved_root(check,columns)!=before:
                raise MemoryIdempotencyConflict('settlement_upgrade_backup_conflict')
            await _validate_snapshot(check,same)
        finally: check.close()
        backup_hash=hashlib.sha256(backup.read_bytes()).hexdigest()
        _fault('after_backup')
        for statement in schema.ddl_statements(schema.TERMINAL_DDL): writer.execute(statement)
        _fault('after_ddl')
        payload=dict(protocol=PROTOCOL,source_schema_checksum=old_schema.SCHEMA_CHECKSUM,
            target_schema_checksum=schema.SCHEMA_CHECKSUM,source_catalog_id=same.catalog_id,
            target_catalog_id=old._catalog(writer),original_initialization_receipt_id=same.initialization.receipt_id,
            original_initialization_receipt_hash=same.initialization.receipt_hash,added_ddl_hash=_added_hash(),
            preserved_old_columns_root_hash=before,backup_sha256=backup_hash,committed_at=time.time())
        receipt=ProspectiveSettlementSchemaUpgradeReceipt(receipt_id=_id(payload),**payload)
        writer.execute('INSERT INTO schema_meta(key,value) VALUES(?,?)',
            (MARKER_KEY,old._canonical({**receipt.to_json(),'receipt_hash':receipt.receipt_hash})))
        if inspect_root(writer).marker!=receipt or _preserved_root(writer,columns)!=before:
            raise MemoryCorruptionError('settlement_upgrade_preservation_differs')
        _fault('before_commit');writer.execute('COMMIT');_fault('after_commit')
        return receipt
    except sqlite3.OperationalError as exc:
        old._raise_if_snapshot_unavailable(exc);raise
    finally:
        if writer is not None: writer.close()
        if snapshot is not None: snapshot.close()
        lease._release_writer_lease()
