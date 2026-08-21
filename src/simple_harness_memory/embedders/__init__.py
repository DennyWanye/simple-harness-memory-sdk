"""simple_harness_memory.embedders — 文本向量化实现。"""

from simple_harness_memory.embedders.base import (
    Embedder,
    cosine_similarity,
    decode_vector,
    encode_vector,
)
from simple_harness_memory.embedders.bge import BGEM3Embedder
from simple_harness_memory.embedders.cloud import CloudEmbedder, EmbeddingClient
from simple_harness_memory.embedders.factory import get_embedder
from simple_harness_memory.embedders.mock import HashEmbedder, MockEmbedder
from simple_harness_memory.embedders.openai_compatible import OpenAICompatibleClient

__all__ = [
    "Embedder",
    "HashEmbedder",
    "MockEmbedder",
    "BGEM3Embedder",
    "CloudEmbedder",
    "EmbeddingClient",
    "OpenAICompatibleClient",
    "get_embedder",
    "encode_vector",
    "decode_vector",
    "cosine_similarity",
]
