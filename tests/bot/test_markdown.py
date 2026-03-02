"""Tests for bot app markdown — MarkdownV2 escaping and stripping."""

from app.apps.bot.markdown import (
    _escape_code,
    _escape_link_url,
    _escape_text,
    _format_fenced_code,
    escape_markdown_v2,
    strip_markdown_v2,
)


# --- _escape_text ---


class TestEscapeText:
    def test_plain_text_unchanged(self):
        assert _escape_text("hello world") == "hello world"

    def test_escapes_special_chars(self):
        assert _escape_text("_") == "\\_"
        assert _escape_text("*") == "\\*"
        assert _escape_text("[") == "\\["
        assert _escape_text("]") == "\\]"
        assert _escape_text("(") == "\\("
        assert _escape_text(")") == "\\)"
        assert _escape_text("~") == "\\~"
        assert _escape_text("`") == "\\`"
        assert _escape_text(">") == "\\>"
        assert _escape_text("#") == "\\#"
        assert _escape_text("+") == "\\+"
        assert _escape_text("-") == "\\-"
        assert _escape_text("=") == "\\="
        assert _escape_text("|") == "\\|"
        assert _escape_text("{") == "\\{"
        assert _escape_text("}") == "\\}"
        assert _escape_text(".") == "\\."
        assert _escape_text("!") == "\\!"
        assert _escape_text("\\") == "\\\\"

    def test_mixed_text(self):
        result = _escape_text("Hello! How are you?")
        assert result == "Hello\\! How are you?"

    def test_multiple_special_chars(self):
        result = _escape_text("v1.0 (beta)")
        assert result == "v1\\.0 \\(beta\\)"


# --- _escape_code ---


class TestEscapeCode:
    def test_plain_code_unchanged(self):
        assert _escape_code("print('hello')") == "print('hello')"

    def test_escapes_backtick(self):
        assert _escape_code("use `code` here") == "use \\`code\\` here"

    def test_escapes_backslash(self):
        assert _escape_code("path\\to\\file") == "path\\\\to\\\\file"

    def test_both_backtick_and_backslash(self):
        assert _escape_code("\\`") == "\\\\\\`"

    def test_special_chars_not_escaped(self):
        """Only ` and \\ are escaped inside code."""
        assert _escape_code("*bold* _italic_") == "*bold* _italic_"


# --- _escape_link_url ---


class TestEscapeLinkUrl:
    def test_simple_url_unchanged(self):
        assert _escape_link_url("https://example.com") == "https://example.com"

    def test_escapes_close_paren(self):
        assert _escape_link_url("https://example.com/path)more") == "https://example.com/path\\)more"

    def test_escapes_backslash(self):
        assert _escape_link_url("https://example.com\\path") == "https://example.com\\\\path"

    def test_preserves_other_special_chars(self):
        """Only ) and \\ are escaped in URLs."""
        url = "https://example.com/path?key=value&other=1#section"
        assert _escape_link_url(url) == url


# --- _format_fenced_code ---


class TestFormatFencedCode:
    def test_code_with_language(self):
        raw = "```python\nprint('hello')\n```"
        result = _format_fenced_code(raw)
        assert result == "```python\nprint('hello')\n```"

    def test_code_without_language(self):
        raw = "```\nsome code\n```"
        result = _format_fenced_code(raw)
        assert result == "```\nsome code\n```"

    def test_strips_trailing_newline(self):
        raw = "```\ncode\n\n```"
        result = _format_fenced_code(raw)
        # Last \n before ``` is stripped, then the remaining \n is in the code
        assert result == "```\ncode\n\n```"

    def test_escapes_backtick_in_code(self):
        raw = "```\nuse `backtick`\n```"
        result = _format_fenced_code(raw)
        assert "\\`" in result

    def test_escapes_backslash_in_code(self):
        raw = "```\npath\\to\\file\n```"
        result = _format_fenced_code(raw)
        assert "\\\\" in result


# --- escape_markdown_v2 ---


class TestEscapeMarkdownV2:
    def test_plain_text(self):
        result = escape_markdown_v2("Hello world")
        assert result == "Hello world"

    def test_special_chars_escaped(self):
        result = escape_markdown_v2("Price: $10.00!")
        assert "\\." in result
        assert "\\!" in result

    def test_fenced_code_block(self):
        text = "Before\n```python\nx = 1\n```\nAfter"
        result = escape_markdown_v2(text)
        assert "```python" in result
        assert "x = 1" in result

    def test_inline_code(self):
        text = "Use `git status` to check"
        result = escape_markdown_v2(text)
        assert "`git status`" in result
        # "to" should not be escaped, "check" should not be escaped
        assert "Use" in result

    def test_markdown_link(self):
        text = "See [the docs](https://example.com) for info"
        result = escape_markdown_v2(text)
        assert "[the docs]" in result
        assert "(https://example.com)" in result

    def test_bold_text(self):
        text = "This is **important** stuff"
        result = escape_markdown_v2(text)
        assert "*important*" in result
        # ** should be converted to single *, not escaped
        assert "**" not in result

    def test_mixed_markdown(self):
        text = "Use **bold** and `code` and [link](https://example.com)"
        result = escape_markdown_v2(text)
        assert "*bold*" in result
        assert "`code`" in result
        assert "[link]" in result
        assert "(https://example.com)" in result

    def test_empty_string(self):
        assert escape_markdown_v2("") == ""

    def test_only_special_chars(self):
        result = escape_markdown_v2("!!!")
        assert result == "\\!\\!\\!"

    def test_text_before_and_after_code(self):
        text = "Run `cmd` now."
        result = escape_markdown_v2(text)
        assert result.startswith("Run ")
        assert result.endswith(" now\\.")

    def test_multiple_code_blocks(self):
        text = "Use `foo` and `bar`"
        result = escape_markdown_v2(text)
        assert "`foo`" in result
        assert "`bar`" in result

    def test_link_special_chars_in_text(self):
        text = "[v1.0 (beta)](https://example.com)"
        result = escape_markdown_v2(text)
        assert "\\." in result
        assert "\\(" in result


# --- strip_markdown_v2 ---


class TestStripMarkdownV2:
    def test_removes_escapes(self):
        assert strip_markdown_v2("Hello\\!") == "Hello!"

    def test_removes_multiple_escapes(self):
        assert strip_markdown_v2("v1\\.0 \\(beta\\)") == "v1.0 (beta)"

    def test_plain_text_unchanged(self):
        assert strip_markdown_v2("Hello world") == "Hello world"

    def test_double_backslash(self):
        assert strip_markdown_v2("path\\\\to") == "path\\to"

    def test_empty_string(self):
        assert strip_markdown_v2("") == ""

    def test_roundtrip_escape_strip(self):
        """Stripping an escaped string recovers the original."""
        original = "Hello! How are you?"
        escaped = escape_markdown_v2(original)
        stripped = strip_markdown_v2(escaped)
        assert stripped == original
