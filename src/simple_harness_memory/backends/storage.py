"""Fail-closed SQLite file creation and owner-only permission checks."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from simple_harness_memory.core.errors import MemoryValidationError


OWNER_ONLY_MODE = 0o600


def path_digest(path: str | os.PathLike[str]) -> str:
    absolute = os.path.abspath(os.fspath(path))
    return hashlib.sha256(absolute.encode("utf-8")).hexdigest()[:16]


def secure_sqlite_path(path: str | os.PathLike[str]) -> Path:
    """Create/verify a regular, non-symlink, current-owner 0600 DB file."""

    db_path = Path(path)
    if str(db_path) == ":memory:":
        raise MemoryValidationError(":memory: is not a durable storage path")
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    parent = db_path.parent
    if not parent.exists() or not parent.is_dir():
        raise MemoryValidationError("database parent directory must already exist")
    if parent.is_symlink():
        raise MemoryValidationError("database parent must not be a symlink")

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(db_path, flags, OWNER_ONLY_MODE)
    except OSError as exc:
        raise MemoryValidationError("database path cannot be opened safely") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise MemoryValidationError("database path must be a regular file")
        if hasattr(os, "getuid") and opened.st_uid != os.getuid():
            raise MemoryValidationError("database file must be owned by current user")
        if os.name == "posix":
            os.fchmod(fd, OWNER_ONLY_MODE)
            if stat.S_IMODE(os.fstat(fd).st_mode) != OWNER_ONLY_MODE:
                raise MemoryValidationError("database mode is not owner-only")
    finally:
        os.close(fd)

    final = db_path.lstat()
    if stat.S_ISLNK(final.st_mode) or not stat.S_ISREG(final.st_mode):
        raise MemoryValidationError("database path changed during validation")
    if os.name == "posix" and stat.S_IMODE(final.st_mode) != OWNER_ONLY_MODE:
        raise MemoryValidationError("database mode read-back failed")
    return db_path


def verify_sqlite_path(path: str | os.PathLike[str]) -> None:
    """Re-check storage invariants after SQLite has opened the file."""

    db_path = Path(path)
    info = db_path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise MemoryValidationError("database path is not a regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise MemoryValidationError("database owner read-back failed")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) != OWNER_ONLY_MODE:
        raise MemoryValidationError("database mode read-back failed")


__all__ = ("OWNER_ONLY_MODE", "path_digest", "secure_sqlite_path", "verify_sqlite_path")
