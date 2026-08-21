import os
import stat

import pytest

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.errors import MemoryValidationError


@pytest.mark.asyncio
async def test_database_is_owner_only_regular_file(tmp_path):
    path = tmp_path / "memory.db"
    backend = SQLiteMemoryBackend(str(path))
    await backend.initialize()
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode)
    if os.name == "posix":
        assert stat.S_IMODE(info.st_mode) == 0o600
    await backend.close()


@pytest.mark.asyncio
async def test_symlink_and_non_regular_targets_fail_closed(tmp_path):
    target = tmp_path / "target.db"
    target.write_bytes(b"")
    link = tmp_path / "link.db"
    link.symlink_to(target)
    with pytest.raises(MemoryValidationError):
        await SQLiteMemoryBackend(str(link)).initialize()
    directory = tmp_path / "directory.db"
    directory.mkdir()
    with pytest.raises(MemoryValidationError):
        await SQLiteMemoryBackend(str(directory)).initialize()
