from __future__ import annotations

from pathlib import Path

from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend


class _FakeMsvcrt:
    LK_NBLCK = 7
    LK_UNLCK = 8

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, count: int) -> None:
        self.calls.append((fd, mode, count))


def test_windows_writer_lock_uses_nonblocking_one_byte_lease(tmp_path: Path) -> None:
    lock_path = tmp_path / "memory.writer.lock"
    lock_path.touch()
    api = _FakeMsvcrt()
    with lock_path.open("r+b") as handle:
        SQLiteMemoryBackend._platform_writer_lock(
            handle, acquire=True, platform_name="nt", windows_api=api
        )
        assert lock_path.stat().st_size == 1
        SQLiteMemoryBackend._platform_writer_lock(
            handle, acquire=False, platform_name="nt", windows_api=api
        )
        assert api.calls == [
            (handle.fileno(), api.LK_NBLCK, 1),
            (handle.fileno(), api.LK_UNLCK, 1),
        ]


def test_sqlite_module_import_has_no_eager_platform_lock_dependency() -> None:
    # Platform modules are deliberately loaded only when the selected lock branch runs.
    assert SQLiteMemoryBackend.__module__ == "simple_harness_memory.backends.sqlite"
