from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BEHAVIOR_BASELINE = "b8b8a776630fe114639927b0240c8bbc4ddc6166"


def _baseline(path: str) -> str:
    return subprocess.run(
        ("git", "show", f"{BEHAVIOR_BASELINE}:{path}"),
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout


def test_0_5_1_changes_no_memory_business_module() -> None:
    changed = subprocess.run(
        ("git", "diff", "--name-only", BEHAVIOR_BASELINE, "--", "src/simple_harness_memory"),
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert changed == [
        "src/simple_harness_memory/__init__.py",
        "src/simple_harness_memory/core/manager.py",
    ]
    for path in changed:
        expected = _baseline(path).replace('"0.5.0"', '"0.5.1"')
        assert (ROOT / path).read_text(encoding="utf-8") == expected
