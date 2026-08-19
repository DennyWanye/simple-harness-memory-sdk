"""OpenAICompatibleClient — OpenAI 兼容 /embeddings HTTP client。"""
from __future__ import annotations

from simple_harness_memory.core.errors import EmbeddingError


class OpenAICompatibleClient:
    """HTTP client for an OpenAI-compatible ``/embeddings`` endpoint.

    Holds the API key but never renders it in ``repr``/``str`` or exception
    messages (M4-AC-3 credential safety).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        *,
        _transport=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._transport = _transport

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleClient(base_url={self._base_url!r}, "
            f"model={self._model!r}, dim={self._dim!r})"
        )

    __str__ = __repr__

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import httpx
        except ImportError as exc:
            raise ImportError(
                "OpenAICompatibleClient requires httpx "
                "(install simple-harness-memory-sdk[world] or [all])"
            ) from exc

        payload = {"model": self._model, "input": texts}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings", json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            # 不把 request/header 的 repr 带进异常消息（防 api_key 泄露）
            raise EmbeddingError(
                f"embedding request failed: {type(exc).__name__}"
            ) from exc

        vectors = [item["embedding"] for item in data["data"]]
        if any(len(v) != self._dim for v in vectors):
            raise EmbeddingError(
                f"embedding dimension mismatch: expected {self._dim}, "
                f"got {len(vectors[0]) if vectors else '?'}"
            )
        return vectors
