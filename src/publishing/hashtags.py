"""Publisher-layer hashtag assembly — deterministic, no model call (#176).

Hashtags are platform dressing governed by a written product rule, not an
editorial judgment: the fixed Never Blank tags first — #CompoundPresence only
when the article is actually about it — then the signal's industry tag. A
model call whose first outputs are constants was a formatting function
wearing a model's price tag — and the prompt it replaced violated the actual
product rule twice (it asked for the company name as a hashtag, and the
branded tags appeared nowhere).

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

#: Always first, in this order.
BRANDED_HASHTAGS = ("#NeverBlank", "#CustomerTrust")

#: Conditional, never automatic: carried only when the article itself is about
#: Compound Presence. The article structure makes that connection conditional
#: (clients/never_blank/lenses/structure.md, step 9), so a tag asserting it on
#: every post would claim a connection most articles deliberately do not make.
COMPOUND_PRESENCE_HASHTAG = "#CompoundPresence"
_COMPOUND_PRESENCE_PHRASE = "compound presence"

#: Tags the product rule prohibits outright (compared case-insensitively).
PROHIBITED_HASHTAGS = frozenset({"#presencesystem", "#contentmarketing"})

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


def generate_hashtags(
    signal: dict,
    platform: str,
    *,
    article_text: str = "",
) -> list[str]:
    """Deterministic hashtags for ``platform``.

    Returns [] for platforms that take no hashtags. Order: ``#NeverBlank``;
    ``#CompoundPresence`` only when ``article_text`` — the canonical accepted
    article — actually names Compound Presence; ``#CustomerTrust``; then the
    signal's industry tag. Case-insensitively deduplicated, prohibited tags
    and company names excluded, bounded by the platform maximum. No model
    transport exists on this path.

    Topical tags are no longer derived from free text. The mechanism's first
    three words and the title's first long word produced tags such as
    ``#WhenPotentialCustomers`` and ``#Fewer`` (controlled live run
    35383199073): fragments, not topics. The industry field is a
    classification value, so it is the only topical tag kept.
    """
    lo, hi = _COUNT_RANGE.get(platform, (0, 0))
    if hi == 0:
        return []

    company = signal.get("REAL_COMPANY_EXAMPLE") or ""
    company_tag = _camel_tag(company).casefold()

    about_compound_presence = (
        isinstance(article_text, str)
        and _COMPOUND_PRESENCE_PHRASE in unicodedata.normalize("NFKC", article_text).casefold()
    )
    candidates = [
        BRANDED_HASHTAGS[0],
        COMPOUND_PRESENCE_HASHTAG if about_compound_presence else "",
        *BRANDED_HASHTAGS[1:],
        _camel_tag(signal.get("INDUSTRY", "")),
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
