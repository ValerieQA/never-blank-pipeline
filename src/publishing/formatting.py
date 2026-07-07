"""
Publisher-layer presentation formatting: signature bolding and source-attribution
lines. Deliberately kept out of src/editorial/ - this module dresses text the
Editorial Engine already produced for a specific platform; it never decides what
the piece says. See docs/EDITORIAL_ENGINE_V2.md for where that line is drawn.
"""

# Unicode Mathematical Sans-Serif Bold block. Contiguous ranges, verified via
# unicodedata.name() against "𝗡𝗲𝘃𝗲𝗿 𝗕𝗹𝗮𝗻𝗸". Used on platforms whose post-text
# APIs have no real bold markup (LinkedIn, Facebook, Instagram, Threads).
_BOLD_UPPER_BASE = 0x1D5D4  # 'A'
_BOLD_LOWER_BASE = 0x1D5EE  # 'a'
_BOLD_DIGIT_BASE = 0x1D7EC  # '0'

_SIGNATURE_PREFIX = "Never Blank"


def bold_unicode(text: str) -> str:
    """Map ASCII letters/digits to Unicode Mathematical Sans-Serif Bold
    codepoints. Anything else (spaces, punctuation) passes through unchanged."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(_BOLD_UPPER_BASE + (ord(ch) - ord("A"))))
        elif "a" <= ch <= "z":
            out.append(chr(_BOLD_LOWER_BASE + (ord(ch) - ord("a"))))
        elif "0" <= ch <= "9":
            out.append(chr(_BOLD_DIGIT_BASE + (ord(ch) - ord("0"))))
        else:
            out.append(ch)
    return "".join(out)


def bold_signature_prefix(text: str, style: str) -> str:
    """
    Bold only the "Never Blank" brand name in the signature line (format:
    "Never Blank: <observation>", guaranteed by Platform Composer to be the
    last line of every format), leaving the rest of the line plain.

    Scans from the bottom of `text` so an incidental earlier mention of
    "Never Blank" in the body is never mistaken for the signature.

    style:
      "unicode"  - Unicode Mathematical Sans-Serif Bold substitution
                   (LinkedIn, Facebook, Instagram, Threads - no real bold in
                   their post-text APIs)
      "telegram" - *Never Blank* - Telegram legacy Markdown bold
                   (TelegramPublisher already sends parse_mode=Markdown)
      "markdown" - **Never Blank** - converted to a real bold rich-content
                   node by src.publishing.wix._md_to_rich_nodes
      anything else - returned unchanged
    """
    if style == "unicode":
        replacement = bold_unicode(_SIGNATURE_PREFIX)
    elif style == "telegram":
        replacement = f"*{_SIGNATURE_PREFIX}*"
    elif style == "markdown":
        replacement = f"**{_SIGNATURE_PREFIX}**"
    else:
        return text

    lines = text.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        if _SIGNATURE_PREFIX in lines[i]:
            lines[i] = lines[i].replace(_SIGNATURE_PREFIX, replacement, 1)
            return "\n".join(lines)
    return text


def source_line(source_name: str, source_url: str, style: str) -> str:
    """
    Build a source-attribution footer, or "" if there is no source URL.

    style:
      "blog_markdown" - "\\n\\n## Source\\n\\n[name](url)"  (Wix blog body)
      "telegram"      - "\\n\\nSource: [name](url)"           (Telegram Markdown
                        link - parse_mode=Markdown renders it)
      "bare_url"      - "\\n\\nSource: url"                   (LinkedIn/Facebook -
                        plain-text posts auto-linkify raw URLs)
    """
    if not source_url:
        return ""
    label = source_name or source_url
    if style == "blog_markdown":
        return f"\n\n## Source\n\n[{label}]({source_url})"
    if style == "telegram":
        return f"\n\nSource: [{label}]({source_url})"
    if style == "bare_url":
        return f"\n\nSource: {source_url}"
    return ""


def append_hashtags(text: str, hashtags: list[str]) -> str:
    """Append a hashtag line, or return text unchanged if hashtags is empty."""
    if not hashtags:
        return text
    return f"{text}\n\n{' '.join(hashtags)}"
