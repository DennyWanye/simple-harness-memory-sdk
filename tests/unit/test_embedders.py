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


def test_hash_embedder_deterministic_and_normalized():
    e = HashEmbedder(dim=128)
    a = e.embed("猫")
    b = e.embed("猫")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_cosine_related_higher_than_unrelated():
    e = HashEmbedder(dim=256)
    q = e.embed("猫")
    related = e.embed("我养了一只猫")
    unrelated = e.embed("今天天气很好")
    assert cosine_similarity(q, related) > cosine_similarity(q, unrelated)


def test_vector_roundtrip():
    v = [0.1, 0.2, 0.3]
    assert decode_vector(encode_vector(v)) == v


def test_get_embedder_hash():
    assert isinstance(get_embedder("hash"), HashEmbedder)
    assert isinstance(get_embedder("mock"), HashEmbedder)


@pytest.mark.skipif(_HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers installed, fallback not triggered")
def test_get_embedder_auto_falls_back_to_hash():
    assert isinstance(get_embedder("auto"), HashEmbedder)


@pytest.mark.skipif(_HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers installed, ImportError not triggered")
def test_get_embedder_bge_raises_without_dependency():
    with pytest.raises(ImportError):
        get_embedder("bge")


@pytest.mark.skipif(not _HAS_SENTENCE_TRANSFORMERS, reason="sentence-transformers not installed")
def test_get_embedder_auto_returns_bge_when_available():
    from simple_harness_memory.embedders.bge import BGEM3Embedder
    assert isinstance(get_embedder("auto"), BGEM3Embedder)


def test_get_embedder_unknown_kind():
    with pytest.raises(ValueError):
        get_embedder("nope")


def test_bge_semantic_similarity():
    if not os.environ.get("RUN_SEMANTIC_SMOKE"):
        pytest.skip("set RUN_SEMANTIC_SMOKE=1 to run real BGE-M3 semantic smoke (~2GB)")
    e = get_embedder("bge")
    q = e.embed("用户养了什么宠物？")
    rel = e.embed("我养了一只叫Max的狗")
    unrel = e.embed("今天天气很好，适合出门")
    assert cosine_similarity(q, rel) > cosine_similarity(q, unrel)
