# SPDX-FileCopyrightText: 2026 DennyWanye
# SPDX-License-Identifier: BUSL-1.1

"""0.6.30 短时域 chunk 长度上限：纯函数切段、投影键与行重推的冻结契约。

对应 ``plans/2026-08-29-human-memory-digital-twin/DECISION-2026-09-08-short-horizon-chunk-cap.md``。
"""

from __future__ import annotations

import pytest

from simple_harness_memory.core.short_horizon import (
    SHORT_HORIZON_CHUNK_MAX_CHARS,
    SHORT_HORIZON_CHUNK_MAX_SEGMENTS,
    SHORT_HORIZON_PROJECTION_KEY_SEPARATOR,
    ShortHorizonIndexError,
    parse_short_horizon_projection_key,
    render_short_horizon_line,
    resolve_short_horizon_projection_row,
    short_horizon_projection_key,
    short_horizon_segment_payload_fields,
    split_short_horizon_content,
)

N = SHORT_HORIZON_CHUNK_MAX_CHARS


def _reassembled(lines: list[tuple[str, str]], segments: tuple[str, ...]) -> str:
    """Strip the ``role: `` prefixes back out and compare to the original texts."""

    pieces: list[str] = []
    for segment in segments:
        for line in segment.split("\n"):
            role, _, text = line.partition(": ")
            pieces.append((role, text))
    # Consecutive pieces of the same registration re-concatenate; a paragraph cut keeps
    # its trailing newline inside the piece, so the original text survives verbatim.
    return "".join(text for _, text in pieces)


def test_constants_are_frozen() -> None:
    assert SHORT_HORIZON_CHUNK_MAX_CHARS == 2_048
    assert SHORT_HORIZON_CHUNK_MAX_SEGMENTS == 8
    assert SHORT_HORIZON_PROJECTION_KEY_SEPARATOR == "\x1f"


def test_group_that_fits_is_exactly_one_segment_and_carries_no_segment_payload() -> None:
    lines = [("user", "校对脚本用 Python 3.12 跑。"), ("assistant", "收到。")]
    split = split_short_horizon_content(lines)
    assert split.segments == ("user: 校对脚本用 Python 3.12 跑。\nassistant: 收到。",)
    assert split.truncated is False
    assert short_horizon_segment_payload_fields(1, 1) == {}
    assert short_horizon_projection_key("group-1", 1, 1) == "group-1"
    # Exactly at the cap still fits in one segment.
    exact = [("user", "x" * (N - len("user: ")))]
    assert len(render_short_horizon_line(*exact[0])) == N
    assert split_short_horizon_content(exact).segments == (render_short_horizon_line(*exact[0]),)


def test_whole_registration_lines_are_packed_before_any_line_is_cut() -> None:
    lines = [("user", "a" * 900), ("assistant", "b" * 900), ("user", "c" * 900)]
    split = split_short_horizon_content(lines)
    assert split.segment_count == 2
    assert split.segments[0] == "user: " + "a" * 900 + "\nassistant: " + "b" * 900
    assert split.segments[1] == "user: " + "c" * 900
    assert all(len(segment) <= N for segment in split.segments)


def test_over_long_line_prefers_paragraph_then_sentence_then_whitespace_then_hard_cut() -> None:
    limit = N - len("assistant: ")
    # Paragraph boundary inside the second half of the window wins.
    paragraph = "p" * 1_500 + "\n" + "q" * 2_000
    split = split_short_horizon_content([("assistant", paragraph)])
    assert split.segments[0] == "assistant: " + "p" * 1_500 + "\n"
    assert split.segments[1] == "assistant: " + "q" * 2_000
    # No newline: the last sentence terminator in the window wins.
    sentence = "s" * 1_200 + "。" + "t" * 500 + "！" + "u" * 2_000
    split = split_short_horizon_content([("assistant", sentence)])
    assert split.segments[0] == "assistant: " + "s" * 1_200 + "。" + "t" * 500 + "！"
    # No terminator: whitespace.
    spaced = "v" * 1_300 + " " + "w" * 3_000
    split = split_short_horizon_content([("assistant", spaced)])
    assert split.segments[0] == "assistant: " + "v" * 1_300 + " "
    # Nothing at all: hard cut exactly at the limit.
    solid = "x" * 5_000
    split = split_short_horizon_content([("assistant", solid)])
    assert [len(segment) for segment in split.segments] == [
        N, N, len("assistant: ") + 5_000 - 2 * limit,
    ]
    # A boundary in the first half of the window is ignored (no tiny fragments).
    early = "e" * 5 + "\n" + "f" * 3_000
    split = split_short_horizon_content([("assistant", early)])
    assert len(split.segments[0]) == N


def test_pieces_reassemble_exactly_and_never_split_a_code_point() -> None:
    astral = "𝔘𝔫𝔦𝔠𝔬𝔡𝔢" * 900  # 6 300 astral code points, no whitespace or terminators
    lines = [("user", "开头"), ("assistant", astral), ("user", "结尾。")]
    split = split_short_horizon_content(lines)
    assert all(len(segment) <= N for segment in split.segments)
    assert _reassembled(lines, split.segments) == "开头" + astral + "结尾。"
    for segment in split.segments:
        segment.encode("utf-8")  # every segment is a valid code-point sequence
        for line in segment.split("\n"):
            _, _, text = line.partition(": ")
            assert set(text) <= set("𝔘𝔫𝔦𝔠𝔬𝔡𝔢开头结尾。")
    assert split_short_horizon_content(lines) == split  # pure and deterministic


def test_segments_beyond_the_cap_are_dropped_and_reported() -> None:
    lines = [("assistant", "z" * 2_000)] * 20
    split = split_short_horizon_content(lines)
    assert split.segment_count == SHORT_HORIZON_CHUNK_MAX_SEGMENTS and split.truncated is True
    assert split.segments[0] == "assistant: " + "z" * 2_000
    widened = split_short_horizon_content(lines, max_segments=32)
    assert widened.segment_count == 20 and widened.truncated is False
    with pytest.raises(ShortHorizonIndexError):
        split_short_horizon_content(lines, max_chars=0)
    with pytest.raises(ShortHorizonIndexError):
        split_short_horizon_content(lines, max_segments=True)  # type: ignore[arg-type]


def test_projection_key_round_trips_and_malformed_keys_fail_closed() -> None:
    key = short_horizon_projection_key("group-long", 3, 8)
    assert key == "group-long\x1f3/8"
    assert parse_short_horizon_projection_key(key) == ("group-long", 3, 8)
    assert parse_short_horizon_projection_key("group-long") == ("group-long", 1, 1)
    malformed_keys = (
        "g\x1f0/2", "g\x1f3/2", "g\x1fa/b", "\x1f1/2", "g\x1f1/1", "g\x1f1", "g\x1fx\x1f1/2",
    )
    for malformed in malformed_keys:
        with pytest.raises(ShortHorizonIndexError):
            parse_short_horizon_projection_key(malformed)


def test_projection_row_resolution_accepts_legacy_unsplit_rows_only_for_bare_keys() -> None:
    small = [("user", "小组。")]
    row = resolve_short_horizon_projection_row("group-small", small)
    assert (row.causal_group_id, row.segment_ordinal, row.segment_count) == ("group-small", 1, 1)
    assert row.content == "user: 小组。" and row.legacy_unsplit is False
    long = [("user", "问"), ("assistant", "y" * 5_000)]
    split = split_short_horizon_content(long)
    legacy = resolve_short_horizon_projection_row("group-long", long)
    assert legacy.legacy_unsplit is True
    assert legacy.content == "user: 问\nassistant: " + "y" * 5_000  # the exact 0.6.29 shape
    second = resolve_short_horizon_projection_row(f"group-long\x1f2/{split.segment_count}", long)
    assert second.content == split.segments[1] and second.legacy_unsplit is False
    with pytest.raises(ShortHorizonIndexError):
        resolve_short_horizon_projection_row("group-long\x1f2/99", long)
    with pytest.raises(ShortHorizonIndexError):
        resolve_short_horizon_projection_row("group-small\x1f1/2", small)
