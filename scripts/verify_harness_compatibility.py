#!/usr/bin/env python3
"""Run one clean-venv compatibility cell against exact Harness and Memory wheels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityError(RuntimeError):
    """Fail-closed input or wheel identity error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wheel(path: Path, expected_sha256: str | None) -> tuple[Path, str]:
    resolved = path.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file() or resolved.suffix != ".whl":
        raise CompatibilityError(f"invalid wheel path: {resolved}")
    digest = _sha256(resolved)
    if expected_sha256 is not None and digest != expected_sha256:
        raise CompatibilityError(f"wheel SHA-256 mismatch: {resolved.name}")
    return resolved, digest


def run(args: argparse.Namespace) -> dict[str, str]:
    memory_wheel, memory_sha256 = _wheel(args.memory_wheel, args.memory_sha256)
    harness_wheel, harness_sha256 = _wheel(args.harness_wheel, args.harness_sha256)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="memory-harness-compat-") as temporary:
        root = Path(temporary)
        venv = root / "venv"
        subprocess.run(
            ("uv", "venv", "--python", args.python, str(venv)),
            check=True,
            cwd=root,
            env=environment,
        )
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                str(harness_wheel),
                str(memory_wheel),
            ),
            check=True,
            cwd=root,
            env=environment,
        )
        subprocess.run(
            (
                str(python),
                "-I",
                str(ROOT / "scripts/harness_compatibility_consumer.py"),
                "--expected-harness-version",
                args.expected_harness_version,
                "--expected-memory-version",
                args.expected_memory_version,
                "--work-dir",
                str(root / "oracle"),
            ),
            check=True,
            cwd=root,
            env=environment,
        )
    return {
        "harness_sha256": harness_sha256,
        "harness_version": args.expected_harness_version,
        "memory_sha256": memory_sha256,
        "memory_version": args.expected_memory_version,
        "result": "pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-wheel", required=True, type=Path)
    parser.add_argument("--memory-sha256")
    parser.add_argument("--expected-memory-version", default="0.6.0")
    parser.add_argument("--harness-wheel", required=True, type=Path)
    parser.add_argument("--harness-sha256")
    parser.add_argument("--expected-harness-version", required=True)
    parser.add_argument("--python", default="3.11")
    args = parser.parse_args()
    try:
        result = run(args)
    except (CompatibilityError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
