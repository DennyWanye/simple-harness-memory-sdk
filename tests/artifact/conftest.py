from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def artifact_dist() -> Path:
    configured = os.environ.get("MEMORY_SDK_ARTIFACT_DIST")
    if configured is None:
        pytest.skip("artifact tests require explicit MEMORY_SDK_ARTIFACT_DIST")
    assert configured.strip(), "MEMORY_SDK_ARTIFACT_DIST must be non-empty"
    path = Path(configured).resolve()
    assert path.is_dir(), f"artifact dist does not exist: {path}"
    return path


@pytest.fixture(scope="session")
def exact_wheel(artifact_dist: Path) -> Path:
    wheels = sorted(artifact_dist.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]
