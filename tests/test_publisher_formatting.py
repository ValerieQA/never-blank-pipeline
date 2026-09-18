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


# --- generate_hashtags (deterministic since #176) ---

_HASHTAG_SIGNAL = {
    "SIGNAL_ID": "x",
    "HEADLINE": "Neighborhood bakery doubled repeat orders with a posted schedule",
    "INDUSTRY": "food service",
    "SIGNAL_TYPE": "market_trend",
    "REAL_COMPANY_EXAMPLE": "Corner Bakery",
}


def test_generate_hashtags_blog_and_telegram_take_none():
    assert generate_hashtags(_HASHTAG_SIGNAL, "blog") == []
    assert generate_hashtags(_HASHTAG_SIGNAL, "telegram") == []


def test_generate_hashtags_fixed_tags_lead_and_count_is_bounded():
    tags = generate_hashtags(_HASHTAG_SIGNAL, "linkedin")
    assert tags[:2] == ["#NeverBlank", "#CustomerTrust"]
    assert "#CompoundPresence" not in tags          # never forced
    assert 2 <= len(tags) <= 6


def test_generate_hashtags_threads_respects_max_of_two():
    tags = generate_hashtags(_HASHTAG_SIGNAL, "threads")
    assert len(tags) <= 2


def test_generate_hashtags_is_deterministic():
    assert generate_hashtags(_HASHTAG_SIGNAL, "linkedin") == \
        generate_hashtags(dict(_HASHTAG_SIGNAL), "linkedin")


def test_generate_hashtags_never_emits_the_company_name():
    tags = generate_hashtags(_HASHTAG_SIGNAL, "linkedin")
    assert "#CornerBakery" not in tags
    assert all("bakery" not in tag.casefold() for tag in tags)


def test_generate_hashtags_survives_empty_and_malformed_fields():
    tags = generate_hashtags({"SIGNAL_ID": "x", "HEADLINE": 42,
                              "INDUSTRY": "", "SIGNAL_TYPE": None}, "linkedin")
    # nothing topical survives; the fixed tags still hold
    assert tags == ["#NeverBlank", "#CustomerTrust"]


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
