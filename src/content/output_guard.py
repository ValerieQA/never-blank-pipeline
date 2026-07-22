"""Hard output guards for production content generation.

These checks run after LLM generation and before drafts are eligible for publishing.
They intentionally fail closed: a malformed platform output must be regenerated or
quarantined, never silently published.
"""

from __future__ import annotations

import re
from collections import Counter


_DETECTIVE_PATTERNS = (
    r"\bI figured\b",
    r"\bI went looking\b",
    r"\bI expected to (?:see|find)\b",
    r"\bBut then I (?:found|realized|saw)\b",
    r"\bThat(?:'|’)s when I realized\b",
    r"\bSo I (?:checked|went back|looked)\b",
)

_DICTIONARY_OPENING_PATTERNS = (
    r"^(?:A|An|The) .{0,80} (?:is|are|serves|provides|offers) .{0,120}\.$",
    r"^Located in .{0,120}, .{0,120}\.$",
)


def nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def validate_telegram(text: str) -> None:
    """Telegram is a self-contained signal, never a full article or teaser."""
    lines = nonempty_lines(text)
    if not lines:
        raise ValueError("Telegram output is empty")
    if len(lines) > 3:
        raise ValueError(f"Telegram output has {len(lines)} non-empty lines; maximum is 3")
    if len(text.split()) > 90:
        raise ValueError("Telegram output exceeds 90 words; it is behaving like an article")
    lowered = text.lower()
    forbidden = ("read more", "check the link", "new post", "i wrote about", "article is live")
    if any(phrase in lowered for phrase in forbidden):
        raise ValueError("Telegram output contains announcement/teaser language")
    if "#" in text:
        raise ValueError("Telegram output must not contain hashtags")


def validate_no_detective_template(text: str, platform: str) -> None:
    matches = [p for p in _DETECTIVE_PATTERNS if re.search(p, text or "", flags=re.IGNORECASE)]
    if len(matches) >= 2:
        raise ValueError(
            f"{platform} output uses the repeated detective template; "
            "write from owner recognition and mechanism instead"
        )


def validate_opening(text: str, platform: str) -> None:
    first = next((s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()), "")
    if not first:
        raise ValueError(f"{platform} output is empty")
    for pattern in _DICTIONARY_OPENING_PATTERNS:
        if re.match(pattern, first, flags=re.IGNORECASE):
            raise ValueError(f"{platform} opens with a dictionary-style business description")


def _sentences(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", s.strip()).lower()
        for s in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if len(s.split()) >= 8
    ]


def validate_no_duplicate_echo(text: str, platform: str) -> None:
    """Catch adjacent or repeated long closing thoughts, including adapted + original Echo."""
    sentences = _sentences(text)
    if len(sentences) < 2:
        return
    counts = Counter(sentences)
    repeated = [s for s, count in counts.items() if count > 1]
    if repeated:
        raise ValueError(f"{platform} repeats a long sentence, likely a duplicated Echo")

    # Near-duplicate final sentences: high token overlap means two Echo variants survived.
    a, b = sentences[-2], sentences[-1]
    wa, wb = set(a.split()), set(b.split())
    if wa and wb and len(wa & wb) / len(wa | wb) >= 0.55:
        raise ValueError(f"{platform} ends with two near-duplicate Echo lines")


def repeated_cross_platform_phrases(texts: dict[str, str], min_words: int = 8) -> list[dict]:
    """Return verbatim sentence-length phrases repeated across platform outputs."""
    owners: dict[str, set[str]] = {}
    for platform, text in texts.items():
        for sentence in _sentences(text):
            if len(sentence.split()) >= min_words:
                owners.setdefault(sentence, set()).add(platform)
    return [
        {"phrase": phrase, "platforms": sorted(platforms)}
        for phrase, platforms in owners.items()
        if len(platforms) >= 2
    ]


def validate_platform_output(platform: str, text: str) -> None:
    validate_opening(text, platform)
    validate_no_detective_template(text, platform)
    validate_no_duplicate_echo(text, platform)
    if platform == "telegram":
        validate_telegram(text)
