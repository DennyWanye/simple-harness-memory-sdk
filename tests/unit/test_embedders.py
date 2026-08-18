from simple_harness_memory.embedders import (
    HashEmbedder,
    cosine_similarity,
    decode_vector,
    encode_vector,
    get_embedder,
)


def test_hash_embedder_deterministic_and_normalized():
    e = HashEmbedder(dim=128)
    a = e.embed("猫")
    b = e.embed("猫")
    assert a == b
    norm = sum(x * x for x in a)
    assert abs(norm - 1.0) < 1e-6


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


def test_get_embedder_auto_falls_back_to_hash():
    # torch/sentence-transformers 未装 → auto 回退到 hash。
    assert isinstance(get_embedder("auto"), HashEmbedder)


def test_get_embedder_bge_raises_without_dependency():
    import pytest
    with pytest.raises(ImportError):
        get_embedder("bge")


def test_get_embedder_unknown_kind():
    import pytest
    with pytest.raises(ValueError):
        get_embedder("nope")
