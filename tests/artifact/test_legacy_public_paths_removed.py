from __future__ import annotations

import inspect
import zipfile
from pathlib import Path

import simple_harness_memory.features as features
from simple_harness_memory import MemoryManager
from simple_harness_memory.backends.base import BaseMemoryBackend
from simple_harness_memory.backends.mock import MockMemoryBackend
from simple_harness_memory.backends.sqlite import SQLiteMemoryBackend
from simple_harness_memory.core.port import MemoryBackend

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_defaults_and_physical_deletes_are_not_public() -> None:
    assert not hasattr(features, "RuleBasedFactExtractor")
    assert not hasattr(features, "FactExtractor")
    assert not hasattr(features, "LLMFactExtractor")
    for owner in (MemoryManager, MemoryBackend, BaseMemoryBackend):
        assert not hasattr(owner, "delete_session")
        assert not hasattr(owner, "delete_old_sessions")
        assert not hasattr(owner, "delete_all")
    assert not hasattr(MemoryManager, "extract_facts")
    assert not hasattr(MemoryManager, "drain_fact_jobs")
    assert not hasattr(MemoryBackend, "extract_facts")
    for backend_class in (MockMemoryBackend, SQLiteMemoryBackend):
        for method in (
            "recover_fact_jobs",
            "claim_fact_job",
            "apply_fact_job",
            "fail_fact_job",
        ):
            assert not hasattr(backend_class, method)
    for callable_object in (
        MemoryManager.build,
        MemoryManager.build_production,
        BaseMemoryBackend.__init__,
        MockMemoryBackend.__init__,
        SQLiteMemoryBackend.__init__,
    ):
        parameters = inspect.signature(callable_object).parameters
        assert "enable_facts" not in parameters
        assert "fact_extractor" not in parameters
        assert "auto_extract_facts" not in parameters


def test_legacy_production_names_do_not_reappear() -> None:
    production = ROOT / "src" / "simple_harness_memory"
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in production.rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert "RuleBasedFactExtractor" not in rendered
    assert "class LLMFactExtractor" not in rendered
    assert "FACT_DECAY_DEFAULTS" not in rendered
    assert "class _LegacyFactJobWorker" not in rendered
    for method in (
        "def recover_fact_jobs",
        "def claim_fact_job",
        "def apply_fact_job",
        "def fail_fact_job",
    ):
        assert method not in rendered
    assert "# L1:" not in rendered
    assert "# L2:" not in rendered
    assert "# L3:" not in rendered


def test_exact_wheel_has_no_regex_or_legacy_extractor(exact_wheel: Path) -> None:
    with zipfile.ZipFile(exact_wheel) as archive:
        sources = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("simple_harness_memory/") and name.endswith(".py")
        }
    rendered = b"\n".join(sources.values())
    source_names = b"\n".join(name.encode() for name in sources)
    assert b"features/facts.py" not in source_names
    assert b"core/fact_jobs.py" not in source_names
    assert b"LegacyRegexFactExtractor" not in rendered
    assert b"LegacyFactJobWorker" not in rendered
    assert b"auto_extract_facts" not in rendered
    assert b"fact_extractor" not in rendered
    for method in (
        b"def recover_fact_jobs",
        b"def claim_fact_job",
        b"def apply_fact_job",
        b"def fail_fact_job",
    ):
        assert method not in rendered
