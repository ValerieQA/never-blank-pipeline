"""Publisher-layer hashtag assembly — deterministic, no model call (#176).

Hashtags are platform dressing governed by a written product rule, not an
editorial judgment: three branded Never Blank tags first, then a bounded
number of article-specific tags derived from the signal's own descriptive
fields. A model call whose first three outputs are constants was a
formatting function wearing a model's price tag — and the prompt it
replaced violated the actual product rule twice (it asked for the company
name as a hashtag, and the branded trio appeared nowhere).

Deterministic by construction: the same normalized input always produces
the same tags. Kept out of src/editorial/: the Editorial Engine's job is
the article's thinking, not platform dressing (EDITORIAL_ENGINE_V2.md
defines no hashtag concept for any format).
"""

import re
import unicodedata

from src.utils.logger import get_logger

log = get_logger("publishing.hashtags")

# Per-platform hashtag matrix. (0, 0) means "no hashtags on this platform" -
# blog and telegram are intentionally absent (not "social post" formats per
# the platform formatting matrix).
_COUNT_RANGE = {
    "linkedin":  (3, 6),
    "facebook":  (3, 6),
    "instagram": (3, 6),
    "threads":   (0, 2),
}

#: The documented Never Blank rule: these three, in this order, always first.
BRANDED_HASHTAGS = ("#NeverBlank", "#CompoundPresence", "#CustomerTrust")

#: Tags the product rule prohibits outright (compared case-insensitively).
PROHIBITED_HASHTAGS = frozenset({"#presencesystem", "#contentmarketing"})

#: Words that never make a useful topical tag on their own.
_STOPWORDS = frozenset({
    "about", "after", "again", "their", "there", "these", "those", "which",
    "while", "would", "could", "should", "between", "because", "before",
    "being", "under", "over", "against", "through", "during", "without",
    "within", "every", "other", "another", "since", "still", "where",
    "business", "company", "companies", "market", "report", "study",
})

_URL_SHAPED = re.compile(r"https?|www\.|\.com|\.org|\.net|\.io|://", re.IGNORECASE)


def _camel_tag(text: str) -> str:
    """One sanitized hashtag from free text, or '' when nothing survives.

    NFKC-normalizes, keeps only letters and digits (URLs, punctuation,
    separators, credentials and raw ids cannot survive), and CamelCases the
    surviving words. Deterministic for identical input.
    """
    if not isinstance(text, str) or _URL_SHAPED.search(text):
        return ""
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text), re.UNICODE)
    joined = "".join(w[:1].upper() + w[1:] for w in words if w)
    if len(joined) < 2 or len(joined) > 40:
        return ""
    return f"#{joined}"


def _title_keyword(title: str, company: str) -> str:
    """The first substantial word of the published title, never the company."""
    if not isinstance(title, str):
        return ""
    company_words = {
        w.casefold()
        for w in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", company or ""))
    }
    for word in re.findall(r"[A-Za-z]{5,}", unicodedata.normalize("NFKC", title)):
        lowered = word.casefold()
        if lowered in _STOPWORDS or lowered in company_words:
            continue
        return _camel_tag(word)
    return ""


def _mechanism_tag(mechanism: str) -> str:
    """A tag for the run's supported mechanism (first three words at most)."""
    if not isinstance(mechanism, str):
        return ""
    return _camel_tag(" ".join(mechanism.split()[:3]))


def generate_hashtags(
    signal: dict,
    platform: str,
    *,
    mechanism: str = "",
    title: str = "",
) -> list[str]:
    """Deterministic hashtags for ``platform`` from canonical article context.

    Returns [] for platforms that take no hashtags. The documented product
    rule is applied exactly: the branded trio first, then article-specific
    tags, case-insensitively deduplicated, prohibited tags and company names
    excluded, bounded by the platform maximum. No model transport exists on
    this path.

    The topical half comes from context the run has already paid for — the
    signal's industry, the supported ``mechanism`` the editorial pipeline
    produced, and the composed ``title`` actually being published. Discovery
    metadata is never a substitute for what the article says: raw headlines
    and classification fields can differ materially from the published
    piece, so callers pass the canonical values in rather than this module
    re-deriving editorial meaning from the raw signal. Callers without a
    generation context (the legacy package publisher) simply omit them and
    get the branded trio plus the industry tag.
    """
    lo, hi = _COUNT_RANGE.get(platform, (0, 0))
    if hi == 0:
        return []

    company = signal.get("REAL_COMPANY_EXAMPLE") or ""
    company_tag = _camel_tag(company).casefold()

    candidates = list(BRANDED_HASHTAGS) + [
        _camel_tag(signal.get("INDUSTRY", "")),
        _mechanism_tag(mechanism),
        _title_keyword(title, company),
    ]

    clean: list[str] = []
    seen: set[str] = set()
    for tag in candidates:
        if not tag:
            continue
        lowered = tag.casefold()
        if lowered in seen:
            continue
        if lowered in PROHIBITED_HASHTAGS:
            continue
        if company_tag and lowered == company_tag:
            continue  # never brand/company names
        seen.add(lowered)
        clean.append(tag)
        if len(clean) >= hi:
            break
    return clean
