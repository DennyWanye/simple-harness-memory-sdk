from __future__ import annotations

import json
import tomllib
from pathlib import Path

import simple_harness_memory
import simple_harness_memory.migrations as migrations

ROOT = Path(__file__).resolve().parents[2]


def test_public_api_0_5_0_snapshot_is_frozen() -> None:
    snapshot_path = Path(__file__).with_name("public-api-0.5.0.json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["package"] == "simple-harness-memory-sdk"
    assert snapshot["version"] == simple_harness_memory.__version__ == "0.5.0"
    assert snapshot["root"] == sorted(simple_harness_memory.__all__)
    assert snapshot["migrations"] == sorted(migrations.__all__)
    assert "ConversationMemoryAdapter" not in snapshot["root"]


def test_0_5_0_version_sources_and_docs_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == (
        "src/simple_harness_memory/__init__.py"
    )
    assert pyproject["project"]["optional-dependencies"]["harness"] == [
        "simple-harness-sdk>=0.4,<0.5"
    ]
    assert "simple-harness-sdk>=0.4,<0.5" in pyproject["project"]["dependencies"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "当前版本：**0.5.0**" in readme
    assert "## [0.5.0] - 2026-08-23" in changelog
    assert "## [0.4.0] - 2026-08-22" in changelog
    assert "version=0.5.0" in (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
