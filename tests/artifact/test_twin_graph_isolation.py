from __future__ import annotations

import ast
from pathlib import Path

import simple_harness_memory
from simple_harness_memory.cognitive.twin_builder import (
    TwinGraphEdge,
    TwinGraphNode,
    TwinGraphSourceRef,
    TwinGraphView,
)
from simple_harness_memory.core.manager import MemoryManager
from simple_harness_memory.core.port import CognitiveMemoryBackend

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    return imported


def test_twin_graph_public_surface_has_one_read_name_and_typed_dtos() -> None:
    graph_methods = {
        name
        for name in CognitiveMemoryBackend.__dict__
        if "twin" in name and "graph" in name
    }
    assert graph_methods == {"get_twin_graph_view"}
    assert hasattr(MemoryManager, "get_twin_graph_view")
    assert {
        "TwinGraphEdge",
        "TwinGraphNode",
        "TwinGraphSourceRef",
        "TwinGraphView",
    } <= set(simple_harness_memory.__all__)
    assert all(
        value.__module__ == "simple_harness_memory.cognitive.twin_builder"
        for value in (TwinGraphEdge, TwinGraphNode, TwinGraphSourceRef, TwinGraphView)
    )


def test_recall_and_twin_projection_dependencies_are_one_way_and_display_only() -> None:
    recall_path = ROOT / "src/simple_harness_memory/core/recall.py"
    twin_path = ROOT / "src/simple_harness_memory/cognitive/twin_builder.py"
    recall_imports = _imports(recall_path)
    twin_imports = _imports(twin_path)
    assert "simple_harness_memory.cognitive.twin_builder" not in recall_imports
    assert not any(name.startswith("simple_harness.runtime") for name in twin_imports)
    assert "simple_harness_memory.core.recall" not in twin_imports
    twin_source = twin_path.read_text(encoding="utf-8")
    for forbidden in (
        "RecallCandidate",
        "RecallContext",
        "ContextFragment",
        "rank_candidates",
        "authorize_recall_context_use",
    ):
        assert forbidden not in twin_source
