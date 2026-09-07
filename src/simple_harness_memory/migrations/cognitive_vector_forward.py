"""7.3 -> 7.4 additive forward (0.6.23): cognitive vector lane tables appended at open.

规则（照 0.6.1 v7.0→v7.1 的"旧库前向"与 7.3 的"checksum 冻结"）：
- fresh 库直接用 7.4 DDL，初始化 receipt/meta 记 7.4 checksum；
- 7.3 库（fresh-7.3 或经 7.2→7.3 显式升级带 marker）打开时在一个事务里追加三张 7.4 表并写入
  前向标记 ``schema_meta[cognitive_vector_forward_v1]``；原初始化 receipt、meta checksum、
  7.3 marker 与全部业务列都不改写；
- 未知 catalog / 未知 checksum 一律 ``MemoryLegacySchemaUnsupported`` /
  ``MemoryCorruptionError``（fail-closed）。
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache

from simple_harness_memory.backends import schema_v5 as old_schema
from simple_harness_memory.backends import schema_v7_3 as previous_schema
from simple_harness_memory.backends import schema_v7_4 as schema
from simple_harness_memory.core.errors import (
    MemoryCorruptionError,
    MemoryLegacySchemaUnsupported,
    MemoryValidationError,
)
from simple_harness_memory.migrations import schema_upgrade as old
from simple_harness_memory.migrations import settlement_upgrade as previous

FORWARD_KEY = 'cognitive_vector_forward_v1'
PROTOCOL = 'memory.schema.cognitive-vector-forward.v1'


@lru_cache(maxsize=1)
def catalogs() -> dict[str, str]:
    """Exact 7.4 SQLite catalogs -> the frozen 7.3 catalog each was appended onto."""
    result: dict[str, str] = {}
    variants = {
        'fresh-7.2': old_schema.DDL,
        'alter-7.2': old_schema.DDL_V7_0
        + '\nALTER TABLE evidence_envelopes ADD COLUMN analysis_lineage_json BLOB;\n'
        + old_schema.SOURCE_ADMISSION_DDL,
    }
    for ddl in variants.values():
        db = sqlite3.connect(':memory:')
        try:
            for statement in old_schema.ddl_statements(ddl):
                db.execute(statement)
            for statement in previous_schema.ddl_statements(previous_schema.TERMINAL_DDL):
                db.execute(statement)
            base = old._catalog(db)
            if base not in previous.catalogs():
                raise MemoryCorruptionError('cognitive_vector_base_catalog_differs')
            for statement in schema.ddl_statements(schema.COGNITIVE_VECTOR_DDL):
                db.execute(statement)
            result[old._catalog(db)] = base
        finally:
            db.close()
    return result


def added_ddl_hash() -> str:
    return old._hash(PROTOCOL + '.ddl', list(schema.ddl_statements(schema.COGNITIVE_VECTOR_DDL)))


@dataclass(frozen=True, slots=True)
class CognitiveVectorForwardMarker:
    protocol: str
    source_schema_checksum: str
    target_schema_checksum: str
    source_catalog_id: str
    target_catalog_id: str
    added_ddl_hash: str
    forwarded_at: float
    marker_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.protocol != PROTOCOL:
            raise MemoryValidationError('cognitive_vector_forward_identity_invalid')
        for key, value in self.to_json().items():
            if key.endswith(('hash', 'checksum', 'catalog_id')) and (
                type(value) is not str
                or len(value) != 64
                or any(c not in '0123456789abcdef' for c in value)
            ):
                raise MemoryValidationError('cognitive_vector_forward_digest_invalid')
        if (
            type(self.forwarded_at) not in (int, float)
            or not math.isfinite(self.forwarded_at)
            or self.forwarded_at < 0
        ):
            raise MemoryValidationError('cognitive_vector_forward_time_invalid')
        object.__setattr__(self, 'forwarded_at', float(self.forwarded_at))
        object.__setattr__(self, 'marker_hash', old._hash(PROTOCOL + '.marker', self.to_json()))

    def to_json(self) -> dict[str, object]:
        return {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
            if key != 'marker_hash'
        }

    def wire(self) -> str:
        return old._canonical({**self.to_json(), 'marker_hash': self.marker_hash})


@dataclass(frozen=True)
class _Root:
    initialization: old_schema.InitializationReceipt
    catalog_id: str
    marker: object | None
    forward: CognitiveVectorForwardMarker | None
    forwardable: bool


def _parse_marker(wire: str) -> CognitiveVectorForwardMarker:
    try:
        if len(wire.encode('utf-8')) > 65_536:
            raise ValueError('marker too large')
        value = json.loads(wire)
        if type(value) is not dict:
            raise ValueError('marker must be object')
        digest = value.pop('marker_hash')
        marker = CognitiveVectorForwardMarker(**value)
        if marker.marker_hash != digest or marker.wire() != wire:
            raise ValueError('marker wire differs')
    except (KeyError, TypeError, ValueError, MemoryValidationError) as exc:
        raise MemoryCorruptionError('cognitive_vector_forward_marker_invalid') from exc
    return marker


def inspect_root(connection: sqlite3.Connection) -> _Root:
    """One caller-owned SQLite snapshot: finite catalog, markers, init receipt, cursor authority."""
    connection.row_factory = sqlite3.Row
    actual = old._catalog(connection)
    if actual in previous.catalogs():
        # A 7.3 database not yet forwarded: identity is exactly the frozen 7.3 rule.
        root = previous.inspect_root(connection, actual=actual)
        return _Root(root.initialization, actual, root.marker, None, True)
    base = catalogs().get(actual)
    if base is None:
        raise MemoryLegacySchemaUnsupported()
    meta = {str(r[0]): str(r[1]) for r in connection.execute('SELECT key,value FROM schema_meta')}
    wire = meta.pop(FORWARD_KEY, None)
    if wire is not None:
        forward = _parse_marker(wire)
        if (
            forward.source_schema_checksum != previous_schema.SCHEMA_CHECKSUM
            or forward.target_schema_checksum != schema.SCHEMA_CHECKSUM
            or forward.source_catalog_id != base
            or forward.target_catalog_id != actual
            or forward.added_ddl_hash != added_ddl_hash()
        ):
            raise MemoryCorruptionError('cognitive_vector_forward_marker_binding_differs')
        # The preserved 7.3 identity (fresh-7.3 receipt or 7.2 receipt + 7.3 marker) is
        # verified by the frozen 7.3 rule against its own catalog and its own meta keys.
        root = previous.inspect_root(connection, actual=base, meta=meta)
        return _Root(root.initialization, actual, root.marker, forward, False)
    expected = {
        'schema_version', 'schema_epoch', 'schema_checksum',
        'initialization_receipt_id', 'initialization_receipt_hash',
    }
    if set(meta) != expected or previous.catalogs()[base] != old.CATALOGS['fresh-7.2']:
        raise MemoryLegacySchemaUnsupported()
    rows = connection.execute('SELECT * FROM initialization_receipts').fetchall()
    if len(rows) != 1:
        raise MemoryCorruptionError('initialization receipt cardinality differs')
    row = rows[0]
    try:
        init = schema.InitializationReceipt(**{
            key: row[key] for key in (
                'receipt_id', 'created_at', 'audit_cursor_authority_hash',
                'schema_version', 'schema_epoch', 'schema_checksum',
            )
        })
    except (TypeError, ValueError) as exc:
        raise MemoryCorruptionError('cognitive_vector_initialization_binding_differs') from exc
    if (
        init.schema_checksum != schema.SCHEMA_CHECKSUM
        or row['receipt_hash'] != init.receipt_hash
        or meta != {
            'schema_version': str(init.schema_version),
            'schema_epoch': init.schema_epoch,
            'schema_checksum': init.schema_checksum,
            'initialization_receipt_id': init.receipt_id,
            'initialization_receipt_hash': init.receipt_hash,
        }
    ):
        raise MemoryCorruptionError('cognitive_vector_initialization_binding_differs')
    authority = connection.execute(
        'SELECT singleton,hmac_key_hex FROM audit_cursor_authority'
    ).fetchall()
    try:
        key = bytes.fromhex(authority[0][1])
        if (
            len(authority) != 1
            or authority[0][0] != 1
            or len(key) != 32
            or hashlib.sha256(key).hexdigest() != init.audit_cursor_authority_hash
        ):
            raise ValueError('cursor differs')
    except (IndexError, TypeError, ValueError) as exc:
        raise MemoryCorruptionError('cognitive_vector_cursor_authority_differs') from exc
    if [r[0] for r in connection.execute('PRAGMA integrity_check')] != ['ok'] or connection.execute(
        'PRAGMA foreign_key_check'
    ).fetchone():
        raise MemoryCorruptionError('cognitive_vector_schema_integrity_differs')
    return _Root(init, actual, None, None, False)


async def _validate_snapshot(connection: sqlite3.Connection, root: _Root) -> None:
    from simple_harness_memory.backends.upgrade_validation import validate_snapshot

    await validate_snapshot(connection, root)


async def probe_existing_root(path):
    """Classify one durable path: fresh / v5 (7.4) / v7.3-forwardable; else unsupported."""
    from simple_harness_memory.backends.sqlite_v5 import _absolute_safe_probe_path

    path = _absolute_safe_probe_path(path)
    if not path.exists():
        if path.with_name(path.name + '-wal').exists():
            raise MemoryValidationError('schema_read_snapshot_unavailable')
        return 'fresh', None
    db = old._open_snapshot(path)
    try:
        try:
            if not db.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
                return 'fresh', None
            root = inspect_root(db)
        except (MemoryCorruptionError, sqlite3.Error, TypeError, ValueError) as exc:
            if isinstance(exc, sqlite3.Error):
                old._raise_if_snapshot_unavailable(exc)
            raise MemoryLegacySchemaUnsupported() from exc
        await _validate_snapshot(db, root)
        return ('v7.3-forwardable' if root.forwardable else 'v5'), root.initialization
    finally:
        db.close()


def forward_statements() -> tuple[str, ...]:
    return tuple(schema.ddl_statements(schema.COGNITIVE_VECTOR_DDL))


def build_marker(
    *, source_catalog_id: str, target_catalog_id: str, forwarded_at: float
) -> CognitiveVectorForwardMarker:
    return CognitiveVectorForwardMarker(
        protocol=PROTOCOL,
        source_schema_checksum=previous_schema.SCHEMA_CHECKSUM,
        target_schema_checksum=schema.SCHEMA_CHECKSUM,
        source_catalog_id=source_catalog_id,
        target_catalog_id=target_catalog_id,
        added_ddl_hash=added_ddl_hash(),
        forwarded_at=forwarded_at,
    )


__all__ = (
    'FORWARD_KEY',
    'PROTOCOL',
    'CognitiveVectorForwardMarker',
    'added_ddl_hash',
    'build_marker',
    'catalogs',
    'forward_statements',
    'inspect_root',
    'probe_existing_root',
)
