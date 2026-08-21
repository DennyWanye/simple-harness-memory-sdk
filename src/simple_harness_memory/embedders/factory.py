"""Embedder 工厂：按 kind 选择哈希伪向量、BGE-M3 或云端。"""

from __future__ import annotations

from pathlib import Path

import structlog

from simple_harness_memory.embedders.base import Embedder
from simple_harness_memory.embedders.mock import HashEmbedder

logger = structlog.get_logger("simple_harness_memory.embedders.factory")


def get_embedder(
    kind: str = "auto",
    *,
    dim: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    revision: str | None = None,
    resource_path: str | None = None,
    production: bool = False,
    cache_size: int = 1024,
    retries: int = 2,
    timeout: float = 30.0,
) -> Embedder:
    """构建向量化器。

    kind:
      "hash" / "mock" — 确定性哈希伪向量（无重依赖）。
      "bge"           — BGE-M3 语义向量（缺依赖时抛 ImportError）。
      "auto"          — 恒返回 HashEmbedder（不加载 BGE-M3）。
      "cloud"         — 云端向量（需 base_url/api_key/model/dim，缺任一抛 ValueError）。
    """
    if kind in ("hash", "mock", "auto"):
        if production:
            raise ValueError("hash/mock/auto embedders are development-only")
        resolved_dim = dim or 256
        logger.info("memory.embedder_selected", kind="hash", dim=resolved_dim)
        return HashEmbedder(dim=resolved_dim)
    if kind == "bge":
        from simple_harness_memory.embedders.bge import BGEM3Embedder

        logger.info("memory.embedder_selected", kind="bge", dim=1024)
        if production and not all((resource_path, model, revision)):
            raise ValueError("production BGE requires resource_path, model, and revision")
        resolved_resource = resource_path or model or "BAAI/bge-m3"
        if production:
            path = Path(resolved_resource).expanduser()
            if not path.is_dir():
                raise ValueError("production BGE resource_path must be an existing directory")
            resolved_resource = str(path.resolve())
        return BGEM3Embedder(
            resolved_resource,
            revision=revision or "local-cache",
            model_name=model,
        )
    if kind == "cloud":
        if not all((base_url, api_key, model, dim)):
            raise ValueError("kind='cloud' requires base_url, api_key, model, and dim")
        if production and not all((provider, revision)):
            raise ValueError("production cloud requires provider and revision")
        assert base_url is not None
        assert api_key is not None
        assert model is not None
        assert dim is not None
        from simple_harness_memory.embedders.cloud import CloudEmbedder
        from simple_harness_memory.embedders.openai_compatible import (
            OpenAICompatibleClient,
        )

        logger.info("memory.embedder_selected", kind="cloud", model=model, dim=dim)
        client = OpenAICompatibleClient(base_url, api_key, model, dim)
        return CloudEmbedder(
            client,
            model=model,
            dim=dim,
            provider=provider or "openai-compatible",
            revision=revision or "unspecified",
            cache_size=cache_size,
            retries=retries,
            timeout=timeout,
        )
    raise ValueError(f"unknown embedder kind: {kind!r}")


def get_production_embedder(
    kind: str,
    *,
    dim: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    revision: str | None = None,
    resource_path: str | None = None,
    cache_size: int = 1024,
    retries: int = 2,
    timeout: float = 30.0,
) -> Embedder:
    """Build a production embedder with explicit immutable resources/lineage."""

    return get_embedder(
        kind,
        dim=dim,
        base_url=base_url,
        api_key=api_key,
        model=model,
        provider=provider,
        revision=revision,
        resource_path=resource_path,
        production=True,
        cache_size=cache_size,
        retries=retries,
        timeout=timeout,
    )
