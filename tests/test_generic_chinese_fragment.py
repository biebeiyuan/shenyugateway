from __future__ import annotations

from shenyu_gateway.recall import (
    is_generic_chinese_fragment,
    _mem_note_keyword_anchor_is_specific,
)
from shenyu_gateway.mem_notes_relevance import _generic_chinese_semantic_fragment


def test_it_prefixed_fragment_consistent_across_paths():
    """'它的事' must be judged generic by BOTH subsystems (regression: recall.py
    previously omitted '它' from its prefix tuple, so the same keyword was
    indexed as a recall tag but suppressed as a mem-note anchor)."""
    term = "它的事"
    assert is_generic_chinese_fragment(term) is True
    assert _generic_chinese_semantic_fragment(term) is True
    # recall-tag filter now agrees: a generic fragment is not "specific".
    assert _mem_note_keyword_anchor_is_specific(term) is False


def test_shared_predicate_matches_mem_notes_wrapper():
    """The mem_notes wrapper must delegate to the shared predicate identically."""
    samples = ["它的事", "我们", "在家里", "决定论", "和弦", "房间设计", "cat", "你呀"]
    for s in samples:
        assert is_generic_chinese_fragment(s) == _generic_chinese_semantic_fragment(s), s


def test_real_keywords_stay_specific():
    """Genuine content keywords must not be filtered as generic."""
    assert is_generic_chinese_fragment("决定论") is False
    assert _mem_note_keyword_anchor_is_specific("决定论") is True
    assert is_generic_chinese_fragment("房间设计") is False


def test_generic_boundaries():
    # single char CJK -> generic
    assert is_generic_chinese_fragment("的") is True
    # prefix-led, <=4 chars -> generic
    assert is_generic_chinese_fragment("你好吗") is True
    # suffix-led -> generic
    assert is_generic_chinese_fragment("好的") is True
    # non-CJK -> not judged here
    assert is_generic_chinese_fragment("hello") is False
    assert is_generic_chinese_fragment("") is False
