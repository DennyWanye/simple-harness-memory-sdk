"""CloudEmbedder / OpenAICompatibleClient 测试（不真发网络请求）。"""

from __future__ import annotations

import asyncio

import pytest

from simple_harness_memory.core.errors import EmbeddingError
from simple_harness_memory.embedders.cloud import CloudEmbedder
from simple_harness_memory.embedders.factory import get_embedder
from simple_harness_memory.embedders.mock import HashEmbedder
from simple_harness_memory.embedders.openai_compatible import OpenAICompatibleClient


class _RecordingClient:
    def __init__(self, *, vectors=None, fail=False, hang=False):
        self.vectors = vectors or {}
        self.fail = fail
        self.hang = hang
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        if self.hang:
            await asyncio.sleep(10)
        return [self.vectors.get(t, [0.0, 0.0]) for t in texts]


@pytest.mark.asyncio
async def test_cloud_embedder_batch_and_cache():
    client = _RecordingClient(vectors={"a": [1.0, 0.0], "b": [0.0, 1.0]})
    e = CloudEmbedder(client, model="m", dim=2)
    out = await e.embed_batch(["a", "b", "a"])
    assert client.calls == 1  # 一次 batch 调用（非逐条）
    assert out[0] == [1.0, 0.0]
    assert out[2] == [1.0, 0.0]  # 缓存命中同向量
    # 再次 embed 已缓存文本，不再调 client
    await e.embed("a")
    assert client.calls == 1


@pytest.mark.asyncio
async def test_cloud_embedder_retry_fail_closed():
    client = _RecordingClient(fail=True)
    e = CloudEmbedder(client, model="m", dim=2, retries=2)
    with pytest.raises(EmbeddingError):
        await e.embed("a")
    assert client.calls == 3  # 1 初始 + 2 重试


@pytest.mark.asyncio
async def test_cloud_embedder_timeout_fail_closed():
    client = _RecordingClient(hang=True)
    e = CloudEmbedder(client, model="m", dim=2, retries=1, timeout=0.01)
    with pytest.raises(EmbeddingError):
        await e.embed("a")


def test_credential_not_in_repr():
    key = "sk-SENTINEL-123"
    client = OpenAICompatibleClient("https://api.example.com", key, "text-embedding-3-small", 1536)
    assert key not in repr(client)
    assert key not in str(client)
    cloud = CloudEmbedder(client, model="text-embedding-3-small", dim=1536)
    assert key not in repr(cloud)


@pytest.mark.asyncio
async def test_openai_compatible_client():
    httpx = pytest.importorskip("httpx")

    def handler(request):
        assert request.url == "https://api.example.com/embeddings"
        assert request.headers["Authorization"] == "Bearer sk-test"
        body = request.read().decode()
        assert "text-embedding-3-small" in body
        return httpx.Response(
            200,
            json={"data": [{"embedding": [1.0, 0.0]}, {"embedding": [0.0, 1.0]}]},
        )

    client = OpenAICompatibleClient(
        "https://api.example.com",
        "sk-test",
        "text-embedding-3-small",
        2,
        _transport=httpx.MockTransport(handler),
    )
    vectors = await client.embed(["a", "b"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.asyncio
async def test_openai_compatible_dim_mismatch():
    httpx = pytest.importorskip("httpx")

    client = OpenAICompatibleClient(
        "https://api.example.com",
        "sk-test",
        "m",
        3,  # 期望 3 维
        _transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0]}]})
        ),
    )
    with pytest.raises(EmbeddingError):
        await client.embed(["a"])


def test_factory_cloud_and_missing_params():
    e = get_embedder(
        "cloud",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="text-embedding-3-small",
        dim=1536,
    )
    assert isinstance(e, CloudEmbedder)
    assert e.kind == "cloud"
    assert e.dim == 1536
    with pytest.raises(ValueError):
        get_embedder("cloud", model="m", dim=1536)  # 缺 base_url/api_key


def test_factory_default_still_hash():
    assert isinstance(get_embedder(), HashEmbedder)
