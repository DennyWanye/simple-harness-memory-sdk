from simple_harness_memory.embedders import (
    HashEmbedder,
    cosine_similarity,
    decode_vector,
    encode_vector,
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
