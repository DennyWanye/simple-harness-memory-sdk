# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: Apache-2.0

"""Observability regression for memory-sdk (L-AC-5 / L-AC-6).

- behaviour: triggering recall emits memory.recall (FAIL-4).
- AST existence: `Retriever.recall` must keep its logger call (FAIL-3).
- redaction: the recall query must stay truncated (FAIL-2).
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from simple_harness_memory.core.models import Message
from simple_harness_memory.core.twin import DigitalTwin
from simple_harness_memory.embedders.mock import HashEmbedder
from simple_harness_memory.features.retriever import Retriever

_SRC = Path(__file__).resolve().parents[2] / "src" / "simple_harness_memory"


def _function_uses_logger(source: Path, func_name: str) -> bool:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "logger"
                ):
                    return True
    return False


def test_recall_keeps_logging() -> None:
    assert _function_uses_logger(_SRC / "features/retriever.py", "recall")


def test_embedder_selection_keeps_logging() -> None:
    assert _function_uses_logger(_SRC / "embedders/factory.py", "get_embedder")


def test_recall_query_is_truncated() -> None:
    src = (_SRC / "features/retriever.py").read_text(encoding="utf-8")
    # the user query must stay truncated at 80 chars, never emitted in full
    assert "query=query[:80]" in src


def test_recall_emits_memory_recall(capsys) -> None:
    retriever = Retriever(HashEmbedder())
    msg = Message(
        id=1, session_id="s1", role="user",
        content="I have a dog named Max", created_at=0.0,
    )
    twin = DigitalTwin()
    hits = retriever.recall(
        "dog", messages=[msg], facts=[], twin=twin, limit=5
    )
    assert hits  # "dog" is a substring of the message content (FTS hit)
    captured = capsys.readouterr().out
    # structlog's default print logger writes to stdout
    assert "memory.recall" in captured
