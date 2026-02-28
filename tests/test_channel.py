"""Tests for channel helper functions."""

from __future__ import annotations

from smolclaw.channel import md_to_telegram_html, split_message


class TestMdToTelegramHtml:
    def test_bold(self):
        assert "<b>bold</b>" in md_to_telegram_html("**bold**")

    def test_italic(self):
        assert "<i>italic</i>" in md_to_telegram_html("*italic*")

    def test_strikethrough(self):
        assert "<s>strike</s>" in md_to_telegram_html("~~strike~~")

    def test_inline_code(self):
        result = md_to_telegram_html("Use `foo()` here")
        assert "<code>foo()</code>" in result

    def test_code_block(self):
        result = md_to_telegram_html("```python\nprint('hi')\n```")
        assert "<pre>" in result
        assert "print(" in result

    def test_heading_becomes_bold(self):
        result = md_to_telegram_html("## My Heading")
        assert "<b>My Heading</b>" in result

    def test_link(self):
        result = md_to_telegram_html("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in result

    def test_html_escape(self):
        result = md_to_telegram_html("1 < 2 & 3 > 0")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_code_not_escaped(self):
        result = md_to_telegram_html("`a < b`")
        assert "<code>a &lt; b</code>" in result


class TestSplitMessage:
    def test_short_message_no_split(self):
        assert split_message("Hello") == ["Hello"]

    def test_long_message_splits_at_paragraphs(self):
        text = ("A" * 100 + "\n\n") * 50
        chunks = split_message(text, max_len=500)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 500

    def test_single_long_paragraph_splits_at_lines(self):
        text = "\n".join(["Line " + str(i) for i in range(200)])
        chunks = split_message(text, max_len=200)
        assert len(chunks) > 1

    def test_empty_returns_original(self):
        assert split_message("") == [""]
