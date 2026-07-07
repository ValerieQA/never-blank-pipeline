"""
Tests for src/publishing/formatting.py and src/publishing/hashtags.py —
Publisher-layer presentation dressing (Editorial Polish task).

Covers:
- bold_unicode: ASCII letters/digits map to Mathematical Sans-Serif Bold,
  punctuation/spaces pass through
- bold_signature_prefix: bolds only "Never Blank" per style, targets the last
  matching line (not an earlier incidental mention), unknown style is a no-op
- source_line: blog/telegram/bare_url formats, "" when no source_url
- append_hashtags: appends a hashtag line, no-op on empty list
- generate_hashtags: platform hashtag-count matrix, validates/dedupes LLM output,
  returns [] on any failure (never raises)
- wix._md_to_rich_nodes: **bold** spans become real Wix BOLD-decorated text
  nodes instead of being stripped
"""

import json
from unittest.mock import patch

from src.publishing.formatting import (
    bold_unicode,
    bold_signature_prefix,
    source_line,
    append_hashtags,
)
from src.publishing.hashtags import generate_hashtags
from src.publishing.wix import _md_to_rich_nodes


def _json_response(data: dict) -> str:
    return json.dumps(data)


# --- bold_unicode ---

def test_bold_unicode_matches_user_example():
    assert bold_unicode("Never Blank") == "𝗡𝗲𝘃𝗲𝗿 𝗕𝗹𝗮𝗻𝗸"


def test_bold_unicode_passes_through_punctuation():
    assert bold_unicode("A: b!") == "𝗔: 𝗯!"


# --- bold_signature_prefix ---

def test_bold_signature_prefix_unicode_style():
    text = "Some body text.\n\nNever Blank: the signal is rarely the event."
    result = bold_signature_prefix(text, "unicode")
    assert result == "Some body text.\n\n𝗡𝗲𝘃𝗲𝗿 𝗕𝗹𝗮𝗻𝗸: the signal is rarely the event."


def test_bold_signature_prefix_telegram_style():
    text = "Body.\n\nNever Blank: an observation."
    result = bold_signature_prefix(text, "telegram")
    assert result == "Body.\n\n*Never Blank*: an observation."


def test_bold_signature_prefix_markdown_style():
    text = "Body.\n\nNever Blank: an observation."
    result = bold_signature_prefix(text, "markdown")
    assert result == "Body.\n\n**Never Blank**: an observation."


def test_bold_signature_prefix_only_bolds_last_occurrence():
    """An incidental earlier 'Never Blank' mention must not be bolded — only
    the actual signature line (always last, per Platform Composer)."""
    text = "Never Blank has been tracking this. More body.\n\nNever Blank: the real signature."
    result = bold_signature_prefix(text, "unicode")
    assert result.startswith("Never Blank has been tracking this.")
    assert result.endswith("𝗡𝗲𝘃𝗲𝗿 𝗕𝗹𝗮𝗻𝗸: the real signature.")


def test_bold_signature_prefix_unknown_style_is_noop():
    text = "Body.\n\nNever Blank: an observation."
    assert bold_signature_prefix(text, "plain") == text


def test_bold_signature_prefix_no_signature_present():
    text = "Body with no signature line."
    assert bold_signature_prefix(text, "unicode") == text


# --- source_line ---

def test_source_line_blog_markdown():
    result = source_line("Reuters", "https://reuters.com/a", "blog_markdown")
    assert result == "\n\n## Source\n\n[Reuters](https://reuters.com/a)"


def test_source_line_telegram():
    result = source_line("Reuters", "https://reuters.com/a", "telegram")
    assert result == "\n\nSource: [Reuters](https://reuters.com/a)"


def test_source_line_bare_url():
    result = source_line("Reuters", "https://reuters.com/a", "bare_url")
    assert result == "\n\nSource: https://reuters.com/a"


def test_source_line_empty_without_url():
    assert source_line("Reuters", "", "blog_markdown") == ""


def test_source_line_falls_back_to_url_as_label():
    result = source_line("", "https://reuters.com/a", "bare_url")
    assert result == "\n\nSource: https://reuters.com/a"


# --- append_hashtags ---

def test_append_hashtags_joins_with_blank_line():
    assert append_hashtags("Body.", ["#A", "#B"]) == "Body.\n\n#A #B"


def test_append_hashtags_noop_on_empty():
    assert append_hashtags("Body.", []) == "Body."


# --- generate_hashtags ---

def test_generate_hashtags_blog_and_telegram_take_none():
    with patch("src.publishing.hashtags.chat") as mock_chat:
        assert generate_hashtags({"SIGNAL_ID": "x"}, "blog") == []
        assert generate_hashtags({"SIGNAL_ID": "x"}, "telegram") == []
    mock_chat.assert_not_called()


def test_generate_hashtags_linkedin_respects_max_count():
    data = {"hashtags": ["#Toyota", "#Automotive", "#EV", "#Hybrid", "#Manufacturing", "#Extra", "#TooMany"]}
    with patch("src.publishing.hashtags.chat", return_value=_json_response(data)):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "linkedin")
    assert len(tags) <= 6
    assert tags[:5] == ["#Toyota", "#Automotive", "#EV", "#Hybrid", "#Manufacturing"]


def test_generate_hashtags_threads_respects_max_of_two():
    data = {"hashtags": ["#Toyota", "#Automotive", "#EV"]}
    with patch("src.publishing.hashtags.chat", return_value=_json_response(data)):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "threads")
    assert len(tags) <= 2


def test_generate_hashtags_dedupes_case_insensitively():
    data = {"hashtags": ["#Toyota", "#toyota", "#EV"]}
    with patch("src.publishing.hashtags.chat", return_value=_json_response(data)):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "linkedin")
    assert tags == ["#Toyota", "#EV"]


def test_generate_hashtags_drops_malformed_entries():
    data = {"hashtags": ["#Good", "NoHash", "#has space", 42, "#"]}
    with patch("src.publishing.hashtags.chat", return_value=_json_response(data)):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "linkedin")
    assert tags == ["#Good"]


def test_generate_hashtags_returns_empty_on_invalid_json():
    with patch("src.publishing.hashtags.chat", return_value="not json"):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "linkedin")
    assert tags == []


def test_generate_hashtags_returns_empty_on_exception():
    with patch("src.publishing.hashtags.chat", side_effect=RuntimeError("boom")):
        tags = generate_hashtags({"SIGNAL_ID": "x"}, "instagram")
    assert tags == []


# --- wix._md_to_rich_nodes bold handling ---

def test_md_to_rich_nodes_bold_span_becomes_decorated_text_node():
    nodes = _md_to_rich_nodes("Body.\n\n**Never Blank**: an observation.")
    paragraph = nodes[-1]
    assert paragraph["type"] == "PARAGRAPH"
    texts = paragraph["nodes"]
    bold_nodes = [n for n in texts if n["textData"].get("decorations")]
    assert len(bold_nodes) == 1
    assert bold_nodes[0]["textData"]["text"] == "Never Blank"
    assert bold_nodes[0]["textData"]["decorations"] == [{"type": "BOLD"}]
    plain_text = "".join(n["textData"]["text"] for n in texts if not n["textData"].get("decorations"))
    assert plain_text == ": an observation."


def test_md_to_rich_nodes_plain_paragraph_has_no_decorations():
    nodes = _md_to_rich_nodes("Just a plain paragraph.")
    texts = nodes[0]["nodes"]
    assert all(not n["textData"].get("decorations") for n in texts)
    assert texts[0]["textData"]["text"] == "Just a plain paragraph."


def test_md_to_rich_nodes_strips_italic_but_keeps_bold():
    nodes = _md_to_rich_nodes("*italic* and **bold** text.")
    texts = nodes[0]["nodes"]
    joined_plain = "".join(n["textData"]["text"] for n in texts if not n["textData"].get("decorations"))
    bold_texts = [n["textData"]["text"] for n in texts if n["textData"].get("decorations")]
    assert bold_texts == ["bold"]
    assert "italic" in joined_plain
    assert "*" not in joined_plain
