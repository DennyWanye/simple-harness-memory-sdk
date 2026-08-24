from __future__ import annotations

import base64
import csv
import hashlib
import os
import subprocess
import zipfile
from email.parser import BytesParser
from io import StringIO
from pathlib import Path


def _wheel_metadata(wheel: Path):
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(names) == 1
        return BytesParser().parsebytes(archive.read(names[0]))


def _fake_harness_wheel(directory: Path, version: str) -> Path:
    """Create a resolver-only wheel; it is never imported or used as runtime evidence."""

    normalized = version.replace("-", "_")
    wheel = directory / f"simple_harness_sdk-{normalized}-py3-none-any.whl"
    dist_info = f"simple_harness_sdk-{normalized}.dist-info"
    files = {
        "simple_harness/__init__.py": f'__version__ = "{version}"\n'.encode(),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.4\n"
            "Name: simple-harness-sdk\n"
            f"Version: {version}\n"
            "Requires-Python: >=3.11\n\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: simple-harness-memory-sdk-resolver-fixture\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
    }
    records: list[tuple[str, str, str]] = []
    for name, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append((name, f"sha256={digest}", str(len(content))))
    record_name = f"{dist_info}/RECORD"
    records.append((record_name, "", ""))
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        lines: list[str] = []
        for record in records:
            stream = StringIO()
            csv.writer(stream, lineterminator="\n").writerow(record)
            lines.append(stream.getvalue())
        archive.writestr(record_name, "".join(lines))
    return wheel


def test_base_metadata_accepts_harness_0_4_through_0_6(exact_wheel: Path) -> None:
    metadata = _wheel_metadata(exact_wheel)
    requirements = metadata.get_all("Requires-Dist") or []
    harness_requirements = [item for item in requirements if item.startswith("simple-harness-sdk")]
    assert harness_requirements
    assert any(
        "simple-harness-sdk<0.7,>=0.4" in item and "extra ==" not in item
        for item in harness_requirements
    )
    assert any(
        "simple-harness-sdk<0.7,>=0.4" in item and "extra == 'harness'" in item
        for item in harness_requirements
    )


def test_base_requirement_accepts_exact_supported_harness_wheel(
    tmp_path: Path,
    exact_wheel: Path,
    exact_harness_wheel: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    venv = tmp_path / "resolver-venv"
    subprocess.run(
        ("uv", "venv", "--python", "3.11", str(venv)),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    for version in ("0.3.999", "0.6.0"):
        invalid = tmp_path / f"invalid-{version}"
        invalid.mkdir()
        invalid_wheel = _fake_harness_wheel(invalid, version)
        rejected = subprocess.run(
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                str(exact_wheel),
                str(invalid_wheel),
            ),
            check=False,
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
        )
        assert rejected.returncode != 0
        assert "No solution found" in rejected.stderr or "conflict" in rejected.stderr.lower()
    harness_version = str(_wheel_metadata(exact_harness_wheel)["Version"])
    assert harness_version in {"0.4.0", "0.5.0"}
    subprocess.run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(exact_harness_wheel),
            str(exact_wheel),
            "httpx>=0.27,<1",
            "mypy==1.20.2",
        ),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    mypy = venv / ("Scripts/mypy.exe" if os.name == "nt" else "bin/mypy")
    subprocess.run(
        (
            str(mypy),
            "--strict",
            "-c",
            (
                "from simple_harness import AgentMemoryPort\n"
                "from simple_harness_memory import MemoryManager\n"
                "async def check() -> None:\n"
                "    manager = await MemoryManager.build()\n"
                "    port: AgentMemoryPort = manager\n"
                "    await manager.close()\n"
                "    reveal_type(port)\n"
            ),
        ),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        (
            str(python),
            "-I",
            "-c",
            (
                "import importlib.metadata as m; import simple_harness; "
                f"assert m.version('simple-harness-sdk') == {harness_version!r}; "
                "assert 'site-packages' in simple_harness.__file__"
            ),
        ),
        check=True,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
