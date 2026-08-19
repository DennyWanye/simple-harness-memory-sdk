# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: Apache-2.0

"""Observability regression for memory-sdk (L-AC-5 / L-AC-6).

- AST existence: `Retriever.recall` must keep its logger call (FAIL-3).
- redaction: the recall query must stay truncated (FAIL-2).
"""

from __future__ import annotations

import ast
from pathlib import Path

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


def test_recall_query_is_truncated() -> None:
    src = (_SRC / "features/retriever.py").read_text(encoding="utf-8")
    # the user query must stay truncated at 80 chars, never emitted in full
    assert "query=query[:80]" in src
