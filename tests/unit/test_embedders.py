import importlib.util
import os

import pytest

from simple_harness_memory.embedders import (
    HashEmbedder,
    cosine_similarity,
    decode_vector,
    encode_vector,
    get_embedder,
)

_HAS_SENTENCE_TRANSFORMERS = importlib.util.find_spec("sentence_transformers") is not None


@pytest.mark.asyncio
async def test_hash_embedder_deterministic_and_normalized():
    e = HashEmbedder(dim=128)
    a = await e.embed("猫")
    b = await e.embed("猫")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_cosine_related_higher_than_unrelated():
    e = HashEmbedder(dim=256)
    q = await e.embed("猫")
    related = await e.embed("我养了一只猫")
    unrelated = await e.embed("今天天气很好")
    assert cosine_similarity(q, related) > cosine_similarity(q, unrelated)


def test_vector_roundtrip():
    v = [0.1, 0.2, 0.3]
    assert decode_vector(encode_vector(v)) == v


def test_get_embedder_hash():
    assert isinstance(get_embedder("hash"), HashEmbedder)
    assert isinstance(get_embedder("mock"), HashEmbedder)


def test_get_embedder_auto_returns_hash():
    # auto no longer eagerly loads BGE-M3; it is always the HashEmbedder.
    assert isinstance(get_embedder("auto"), HashEmbedder)


@pytest.mark.skipif(
    _HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers installed, ImportError not triggered"
)
def test_get_embedder_bge_raises_without_dependency():
    with pytest.raises(ImportError):
        get_embedder("bge")


def test_get_embedder_unknown_kind():
    with pytest.raises(ValueError):
        get_embedder("nope")


@pytest.mark.asyncio
async def test_bge_semantic_similarity():
    if not os.environ.get("RUN_SEMANTIC_SMOKE"):
        pytest.skip("set RUN_SEMANTIC_SMOKE=1 to run real BGE-M3 semantic smoke (~2GB)")
    e = get_embedder("bge")
    q = await e.embed("用户养了什么宠物？")
    rel = await e.embed("我养了一只叫Max的狗")
    unrel = await e.embed("今天天气很好，适合出门")
    assert cosine_similarity(q, rel) > cosine_similarity(q, unrel)
