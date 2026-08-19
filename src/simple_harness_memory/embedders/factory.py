"""Embedder 工厂：按 kind 选择哈希伪向量或 BGE-M3，并做优雅回退。"""
from __future__ import annotations

import structlog

from simple_harness_memory.embedders.base import Embedder
from simple_harness_memory.embedders.mock import HashEmbedder

logger = structlog.get_logger("simple_harness_memory.embedders.factory")


def get_embedder(kind: str = "auto", *, dim: int = 256) -> Embedder:
    """构建向量化器。

    kind:
      "hash" / "mock" — 确定性哈希伪向量（无重依赖）。
      "bge"           — BGE-M3 语义向量（缺依赖时抛 ImportError）。
      "auto"          — 恒返回 HashEmbedder（不加载 BGE-M3）。
    """
    if kind in ("hash", "mock"):
        logger.info("memory.embedder_selected", kind="hash", dim=dim)
        return HashEmbedder(dim=dim)
    if kind == "bge":
        from simple_harness_memory.embedders.bge import BGEM3Embedder
        logger.info("memory.embedder_selected", kind="bge", dim=1024)
        return BGEM3Embedder()
    if kind == "auto":
        logger.info("memory.embedder_selected", kind="hash", dim=dim)
        return HashEmbedder(dim=dim)
    raise ValueError(f"unknown embedder kind: {kind!r}")
