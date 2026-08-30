from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD_INFO_KEYS = (
    "package",
    "version",
    "source_commit",
    "requires_python",
    "harness_requires",
    "build_utc",
    "wheel_sha256",
    "sdist_sha256",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata_module():
    path = ROOT / "scripts/write_candidate_metadata.py"
    spec = importlib.util.spec_from_file_location("memory_candidate_metadata", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_build_info(path: Path) -> dict[str, str]:
    pairs = [line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(len(pair) == 2 for pair in pairs)
    assert tuple(pair[0] for pair in pairs) == BUILD_INFO_KEYS
    return {key: value for key, value in pairs}


def _assert_ci_metadata(dist: Path) -> None:
    info = _read_build_info(dist / "BUILD_INFO.txt")
    assert info["package"] == "simple-harness-memory-sdk"
    assert info["version"] == "0.6.0"
    assert re.fullmatch(r"[0-9a-f]{40}", info["source_commit"])
    assert info["requires_python"] == "<3.14,>=3.11"
    assert info["harness_requires"] == "simple-harness-sdk<0.8,>=0.7"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", info["build_utc"])
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted((*dist.glob("*.tar.gz"), *dist.glob("*.zip")))
    assert len(wheels) == len(sdists) == 1
    assert info["wheel_sha256"] == _sha256(wheels[0])
    assert info["sdist_sha256"] == _sha256(sdists[0])
    lines = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == sorted((wheels[0].name, sdists[0].name))
    assert all(re.fullmatch(r"[0-9a-f]{64}  [^/]+", line) for line in lines)
    for line in lines:
        digest, name = line.split("  ", 1)
        assert digest == _sha256(dist / name)


def test_ci_metadata_writer_has_canonical_contract(tmp_path: Path, artifact_dist: Path) -> None:
    dist = tmp_path / "candidate-dist"
    dist.mkdir()
    for artifact in (*artifact_dist.glob("*.whl"), *artifact_dist.glob("*.tar.gz")):
        shutil.copy2(artifact, dist / artifact.name)
    module = _metadata_module()
    module.write_metadata(
        dist,
        "a" * 40,
        "2026-08-21T00:00:00Z",
    )
    _assert_ci_metadata(dist)
    with pytest.raises(module.CandidateMetadataError, match="already-exists"):
        module.write_metadata(dist, "a" * 40, "2026-08-21T00:00:00Z")


def test_current_artifact_metadata_policy(artifact_dist: Path) -> None:
    if os.environ.get("MEMORY_SDK_CI_CANDIDATE") == "1":
        _assert_ci_metadata(artifact_dist)
    else:
        assert not (artifact_dist / "BUILD_INFO.txt").exists()
        assert not (artifact_dist / "SHA256SUMS").exists()


def test_ci_covers_full_matrix_clean_wheel_and_arm64() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for version in ('"3.11"', '"3.12"', '"3.13"'):
        assert version in workflow
    assert "uv run --frozen --group dev pytest -q" in workflow
    assert "uv run --frozen --group dev ruff check src tests" in workflow
    assert "uv run --frozen --group dev mypy src tests" in workflow
    assert "Build candidate bytes once" in workflow
    assert "twine check candidate-dist/*" in workflow
    assert workflow.count("SOURCE_DATE_EPOCH=315532800") == 1
    assert "scripts/write_candidate_metadata.py" in workflow
    assert "MEMORY_SDK_ARTIFACT_DIST: candidate-dist" in workflow
    assert "HARNESS_SDK_ARTIFACT_DIST: harness-dist" in workflow
    assert 'MEMORY_SDK_CI_CANDIDATE: "1"' in workflow
    assert "retention-days: 30" in workflow
    assert "ubuntu-24.04-arm" in workflow
    assert "windows-latest" in workflow
    assert "macos-14" in workflow
    assert "exact-wheel-platform-matrix" in workflow
    assert 'find_spec("simple_harness.observability") is not None' in workflow
    assert "uv pip install --system" in workflow
    assert 'test "$(uname -m)" = "aarch64"' in workflow
    assert "agent_record_turn" in workflow
    assert "harness-0-7-compatibility" in workflow
    assert "scripts/verify_harness_compatibility.py" in workflow
    assert "simple_harness_sdk-0.7.0-*.whl" in workflow
    assert "8f1027d2d64ca3a7e7a4d161833507eadac9552b" in workflow
    assert "b9421ddf2b1d5a4a4a0920a2e878c1d3cf098ff6ef0af8975b9eb5c516037d7b" in workflow
    assert "secrets.HARNESS_REPOSITORY_TOKEN || github.token" in workflow
    assert "fail closed without repository access" in workflow
    assert "harness-sdk-candidate-${{ github.sha }}" in workflow
    assert workflow.count("uv pip install") >= 3
    assert (
        "FROM turn_receipts WHERE deployment_id='deployment-a' AND turn_id='turn-a'"
        in workflow
    )
    assert "PRAGMA journal_mode" in workflow
    assert "PRAGMA foreign_key_check" in workflow


def test_release_only_verifies_for_the_task_10_single_publisher() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "artifact_run_id:" in workflow
    assert "artifact_id:" in workflow
    assert "wheel_sha256:" in workflow
    assert "source_commit:" in workflow
    assert "artifact-ids: ${{ inputs.artifact_id }}" in workflow
    assert "run-id: ${{ inputs.artifact_run_id }}" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow
    assert "source_commit=$EXPECTED_COMMIT" in workflow
    assert "requires_python=<3.14,>=3.11" in workflow
    assert "version=0.5.1" in workflow
    assert "harness_requires=simple-harness-sdk<0.6,>=0.4" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "Task 10 single publisher" in workflow
    assert "softprops/action-gh-release" not in workflow
    assert "release_tag:" not in workflow
    assert "tag_name:" not in workflow
    assert "uv build" not in workflow
    assert "tags:" not in workflow
