"""Small, deterministic lexical helpers for bounded agent recall."""

from __future__ import annotations

import re

_ASCII_TOKEN = re.compile(r"[a-z0-9]+")
_CJK_CHUNK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def lexical_units(text: str) -> tuple[str, ...]:
    """Return lexical units without requiring a language-specific model."""

    normalized = text.casefold()
    units: list[str] = [token for token in _ASCII_TOKEN.findall(normalized) if token]
    for chunk in _CJK_CHUNK.findall(normalized):
        if len(chunk) == 1:
            units.append(chunk)
        else:
            units.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tuple(dict.fromkeys(units))


def cjk_trigrams(text: str) -> tuple[str, ...]:
    """Return CJK trigrams suitable for SQLite's indexed trigram tokenizer."""

    units: list[str] = []
    for chunk in _CJK_CHUNK.findall(text.casefold()):
        units.extend(chunk[index : index + 3] for index in range(max(0, len(chunk) - 2)))
    return tuple(dict.fromkeys(units))


def lexical_similarity(query: str, candidate: str) -> float:
    """Score token/bigram overlap using a Dice coefficient in the [0, 1] range."""

    query_units = set(lexical_units(query))
    candidate_units = set(lexical_units(candidate))
    if not query_units or not candidate_units:
        return 0.0
    return (2.0 * len(query_units & candidate_units)) / (len(query_units) + len(candidate_units))
