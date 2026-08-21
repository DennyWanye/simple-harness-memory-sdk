from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIST = ROOT / ".local-test-evidence/2026-08-21-agent-runtime/M-WHEEL/dist"


@pytest.fixture(scope="session")
def artifact_dist() -> Path:
    configured = os.environ.get("MEMORY_SDK_ARTIFACT_DIST")
    path = Path(configured).resolve() if configured else LOCAL_DIST
    assert path.is_dir(), f"artifact dist does not exist: {path}"
    return path


@pytest.fixture(scope="session")
def exact_wheel(artifact_dist: Path) -> Path:
    wheels = sorted(artifact_dist.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]
