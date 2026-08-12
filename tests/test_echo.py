from __future__ import annotations

from shenyu_gateway.echo import EchoStreamFilter, split_leading_echo, trim_assistant_echoes
from shenyu_gateway.private_capture import finalize_assistant_private_content, restore_assistant_echo


def _stream_parts(parts: list[str]) -> tuple[str, str, bool]:
    echo_filter = EchoStreamFilter()
    visible_parts: list[str] = []
    echo_parts: list[str] = []
    for part in parts:
        visible, echo, _closed = echo_filter.feed(part)
        visible_parts.append(visible)
        echo_parts.append(echo)
    visible, echo = echo_filter.finish()
    visible_parts.append(visible)
    echo_parts.append(echo)
    return "".join(visible_parts), "".join(echo_parts), echo_filter.closed


def test_split_leading_echo_keeps_body_and_extracts_echo():
    split = split_leading_echo("[回响]我有一点犹豫。[/回响]\n\n正文")

    assert split.visible == "\n\n正文"
    assert split.echo == "我有一点犹豫。"
    assert split.matched is True
    assert split.closed is True


def test_echo_stream_filter_handles_every_marker_split_point():
    text = "[回响]先停一下。[/回响]正文"

    for index in range(len(text) + 1):
        visible, echo, closed = _stream_parts([text[:index], text[index:]])
        assert visible == "正文", index
        assert echo == "先停一下。", index
        assert closed is True, index


def test_echo_stream_filter_handles_character_stream():
    visible, echo, closed = _stream_parts(list("  \n[回响]慢一点。[/回响]\n正文"))

    assert visible == "\n正文"
    assert echo == "慢一点。"
    assert closed is True


def test_echo_stream_filter_passes_non_echo_text_exactly():
    text = "  普通正文里的 [回响] 是字面文字"

    visible, echo, closed = _stream_parts(list(text))

    assert visible == text
    assert echo == ""
    assert closed is False


def test_echo_stream_filter_returns_unclosed_tail_as_echo():
    visible, echo, closed = _stream_parts(["[回", "响]还没有写完"])

    assert visible == ""
    assert echo == "还没有写完"
    assert closed is False


def test_trim_assistant_echoes_counts_subsequent_user_turns_not_echo_rows():
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "[回响]e1[/回响]a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "[回响]e3[/回响]a3"},
        {"role": "user", "content": "u4"},
    ]

    trimmed, meta = trim_assistant_echoes(messages, keep_subsequent_user_turns=1)

    assert trimmed[1]["content"] == "a1"
    assert trimmed[3]["content"] == "a2"
    assert trimmed[5]["content"] == "[回响]e3[/回响]a3"
    assert meta == {
        "echo_keep_subsequent_user_turns": 1,
        "echo_messages_seen": 2,
        "echo_messages_trimmed": 1,
    }


def test_trim_assistant_echoes_zero_hides_echo_on_next_request():
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "[回响]e1[/回响]a1"},
        {"role": "user", "content": "u2"},
    ]

    trimmed, _meta = trim_assistant_echoes(messages, keep_subsequent_user_turns=0)

    assert trimmed[1]["content"] == "a1"


def test_trim_assistant_echoes_keeps_echo_for_exactly_one_next_user_turn():
    after_reply = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "[回响]e1[/回响]a1"},
    ]
    next_request = [*after_reply, {"role": "user", "content": "u2"}]
    following_request = [
        *next_request,
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
    ]

    kept, _ = trim_assistant_echoes(next_request, keep_subsequent_user_turns=1)
    expired, _ = trim_assistant_echoes(following_request, keep_subsequent_user_turns=1)

    assert kept[1]["content"] == "[回响]e1[/回响]a1"
    assert expired[1]["content"] == "a1"


def test_finalize_and_restore_echo_preserve_inner_whitespace_exactly():
    message = {"role": "assistant", "content": "[回响]\n  不急。 \n[/回响]正文"}

    clean, heartbeat, echo, _meta = finalize_assistant_private_content(message)

    assert clean == "正文"
    assert heartbeat == ""
    assert echo == "\n  不急。 \n"
    assert restore_assistant_echo(clean, echo) == "[回响]\n  不急。 \n[/回响]正文"


def test_echo_only_reply_does_not_invent_visible_fallback():
    message = {"role": "assistant", "content": "[回响]只是安静地待一下。[/回响]"}

    clean, heartbeat, echo, meta = finalize_assistant_private_content(message)

    assert clean == ""
    assert heartbeat == ""
    assert echo == "只是安静地待一下。"
    assert meta == {
        "applied": False,
        "text": "",
        "kinds": [],
        "context": "",
    }
