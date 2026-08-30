from __future__ import annotations

import json
import tomllib
from pathlib import Path

import simple_harness_memory
import simple_harness_memory.migrations as migrations

ROOT = Path(__file__).resolve().parents[2]


def test_public_api_0_6_0_snapshot_is_frozen_and_0_5_2_is_preserved() -> None:
    snapshot_path = Path(__file__).with_name("public-api-0.6.0.json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    previous = json.loads(
        Path(__file__).with_name("public-api-0.5.2.json").read_text(encoding="utf-8")
    )
    assert snapshot["package"] == "simple-harness-memory-sdk"
    assert snapshot["version"] == simple_harness_memory.__version__ == "0.6.0"
    assert snapshot["root"] == sorted(simple_harness_memory.__all__)
    assert snapshot["migrations"] == sorted(migrations.__all__)
    assert previous["version"] == "0.5.2"
    assert snapshot["migrations"] == previous["migrations"]
    assert snapshot["removed_public_methods"]
    assert "ConversationMemoryAdapter" not in snapshot["root"]


def test_0_6_0_candidate_sources_and_docs_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == (
        "src/simple_harness_memory/__init__.py"
    )
    assert pyproject["project"]["optional-dependencies"]["harness"] == [
        "simple-harness-sdk>=0.7,<0.8"
    ]
    assert "simple-harness-sdk>=0.7,<0.8" in pyproject["project"]["dependencies"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "当前 source candidate：**0.6.0**" in readme
    assert "已发布 fallback 为 0.5.1" in readme
    assert "## [0.6.0] - 2026-08-30" in changelog
    assert "## [0.5.1] - 2026-08-24" in changelog
    assert "## [0.5.0] - 2026-08-23" in changelog
    assert "## [0.4.0] - 2026-08-22" in changelog
    assert "version=0.5.1" in (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
