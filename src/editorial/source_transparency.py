"""Fail-closed source-transparency check for roles that require it (#142).

A role may instruct its prompts to attribute sources; an instruction is not a
guarantee. When a role declares ``require_source_transparency`` this boundary
verifies, after generation and before any publisher is called, that the
composed bodies actually carry attribution — and that the attribution belongs
to **this run's** sources rather than merely looking like a citation.

Two checks, both against the run's own research artifact:

1. **Attribution** — the canonical article must attribute at least one real
   run source through an explicit, deterministic form: the exact source URL,
   or the source's publisher/title inside a recognizable attribution
   construction ("Source: X", "According to X", "X reported…", "documented by
   X", or a Sources section naming X) at word boundaries. Incidental lexical
   overlap is not attribution: a publisher named "Research" can never be
   satisfied by the phrase "our research shows", and a name whose every token
   is generic is excluded from name matching entirely — only its exact URL
   can attest it.
2. **No invented links** — every http(s) URL in a checked body must be one of
   the run's source URLs or live under an explicitly allowed destination,
   compared **structurally**: parsed scheme, exact hostname, effective port,
   and path boundary. String prefixes are not used, so
   ``https://site.example.evil.test/…``, userinfo tricks, foreign ports and
   lookalike hosts all fail.

A third check, ``validate_social_lineage`` (#196), governs the other half of
the chain: a social derivative must point at the run's own published
canonical article and at nothing else. Together the two functions preserve
the whole provenance path — ``social → canonical article → original
sources`` — without asking a social post to duplicate the article's citations.

Generic by construction: which roles require this is configuration; this
module knows only bodies, a research artifact, and allowed destinations — no
role names, no weekdays, no product vocabulary. Roles that do not declare the
requirement are never checked, so every existing stream keeps its prior
behaviour.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.research.evidence import NormalizedResearchArtifact


class SourceTransparencyError(RuntimeError):
    """A required surface lacks usable, run-grounded source attribution."""


# Publication surfaces can render absolute HTTP(S) URLs case-insensitively and
# protocol-relative URLs.  Both forms must reach the same fail-closed parser;
# otherwise an unchecked link can bypass the allow-list simply by changing its
# spelling.  Protocol-relative links are deliberately extracted and then
# rejected by ``_parse`` because the configured scheme is part of the policy.
_URL_PATTERN = re.compile(r"(?:https?:)?//[^\s)\]>\"']+", re.IGNORECASE)

#: Minimum length for a title to participate in name-based attribution — a
#: very short title matches prose too easily even at word boundaries.
_MIN_TITLE_LENGTH = 12

#: Tokens too generic to identify a source. A name whose alphanumeric tokens
#: are ALL in this set (articles/conjunctions aside) cannot be satisfied by
#: name matching — only its exact URL can attest it. Deterministic on purpose:
#: no scoring, no heuristics.
_GENERIC_TOKENS = frozenset({
    "research", "news", "business", "report", "reports", "study", "studies",
    "blog", "article", "articles", "insights", "media", "data", "review",
    "reviews", "journal", "daily", "weekly", "magazine", "post", "posts",
    "the", "a", "an", "of", "and", "for", "on", "in",
})

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _strip_trailing_punctuation(url: str) -> str:
    return url.rstrip(".,;:!?)]}\"'")


def _parse(url: str):
    """Structural parse: (scheme, host, effective port, path) or ``None``.

    ``None`` for anything unparseable, non-http(s), hostless, or carrying
    userinfo — a ``user@host`` URL is a classic confusion trick and is never
    treated as an allowed destination.
    """

    try:
        parts = urlsplit(_strip_trailing_punctuation(url.strip()))
        scheme = (parts.scheme or "").lower()
        if scheme not in _DEFAULT_PORTS or not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        port = parts.port if parts.port is not None else _DEFAULT_PORTS[scheme]
        return scheme, parts.hostname.lower(), port, parts.path or "/"
    except ValueError:
        return None


def _canonical(url: str) -> str | None:
    """A comparable canonical form: scheme://host[:port]/path, lowercased
    host/scheme, default port elided, trailing slash trimmed."""

    parsed = _parse(url)
    if parsed is None:
        return None
    scheme, host, port, path = parsed
    rendered_port = "" if port == _DEFAULT_PORTS[scheme] else f":{port}"
    return f"{scheme}://{host}{rendered_port}{path.rstrip('/') or ''}"


def _is_allowed_destination(url: str, allowed: tuple) -> bool:
    """Structural same-origin + path-boundary check. Never a string prefix."""

    parsed = _parse(url)
    if parsed is None:
        return False
    scheme, host, port, path = parsed
    for base in allowed:
        if base is None:
            continue
        base_scheme, base_host, base_port, base_path = base
        if (scheme, host, port) != (base_scheme, base_host, base_port):
            continue
        boundary = base_path.rstrip("/")
        if not boundary or path == boundary or path.startswith(boundary + "/"):
            return True
    return False


def _is_ambiguous(name: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    return not tokens or all(token in _GENERIC_TOKENS for token in tokens)


def _attribution_present(name: str, body: str) -> bool:
    """Explicit attribution constructions with an exact source identity."""

    escaped = re.escape(name.strip()).replace(r"\ ", r"\s+")
    # A word boundary alone is insufficient: ``According to HubSpot Evil``
    # would otherwise attest the real publisher ``HubSpot``.  Prefix forms
    # therefore require the exact identity to end the construction (possibly
    # followed by normal punctuation).  Publisher-first forms remain explicit
    # because a declared reporting verb must immediately follow the identity.
    exact_end = r"(?=\s*(?:$|[,.;:!?\)\]\}]))"
    constructions = (
        rf"\bsources?\s*:\s*{escaped}{exact_end}",
        rf"\baccording\s+to\s+(?:the\s+)?{escaped}{exact_end}",
        rf"\bper\s+(?:the\s+)?{escaped}{exact_end}",
        rf"\b{escaped}\b['’s]*\s+(?:reports?|reported|describes?|described|"
        rf"publishes?|published|writes?|wrote|notes?|noted|documents?|"
        rf"documented|found|data|case\s+study|article)\b",
        rf"\b(?:reported|documented|described|published|written|cited)\s+by\s+"
        rf"(?:the\s+)?{escaped}{exact_end}",
    )
    if any(re.search(pattern, body, re.IGNORECASE) for pattern in constructions):
        return True
    # A Sources section is line-oriented.  The identity must be the complete
    # entry (apart from a bullet and terminal punctuation), not a substring of
    # a fabricated longer publisher name.
    heading = re.search(r"(?mi)^\s*(?:#{1,6}\s*)?sources?\s*:?\s*$", body)
    if heading is not None:
        entry = re.compile(
            rf"(?mi)^\s*(?:(?:[-*])\s+|\d+[.)]\s+)?"
            rf"{escaped}\s*[.,;:]?\s*$"
        )
        return entry.search(body[heading.end():]) is not None
    return False


def _source_identities(research: NormalizedResearchArtifact) -> tuple[set, set]:
    """The run's real source identities: canonical URLs and usable names."""

    urls, names = set(), set()
    for source in research.sources:
        locator = getattr(source.locator, "value", "") or ""
        canonical = _canonical(locator)
        if canonical:
            urls.add(canonical)
        publisher = (source.publisher or "").strip()
        if publisher and not _is_ambiguous(publisher):
            names.add(publisher)
        title = (source.title or "").strip()
        if len(title) >= _MIN_TITLE_LENGTH and not _is_ambiguous(title):
            names.add(title)
    return urls, names


def _check_surface(
    surface: str,
    body: str,
    source_urls: set,
    source_names: set,
    allowed: tuple,
) -> None:
    body_urls = {
        canonical
        for canonical in (_canonical(url) for url in _URL_PATTERN.findall(body))
        if canonical is not None
    }

    cited_urls = body_urls & source_urls
    cited_names = {
        name for name in source_names if _attribution_present(name, body)
    }
    if not cited_urls and not cited_names:
        raise SourceTransparencyError(
            f"the {surface} body carries no attribution to any of this run's "
            "sources — no source URL, and no explicit attribution of a source "
            "publisher or title, appears in it"
        )

    for url in body_urls - cited_urls:
        if not _is_allowed_destination(url, allowed):
            raise SourceTransparencyError(
                f"the {surface} body links {url!r}, which is not one of this "
                "run's sources and not an allowed destination — an invented "
                "or unrelated link is not attribution"
            )
    # a raw URL the parser refused (userinfo tricks included) is never allowed
    for raw in _URL_PATTERN.findall(body):
        if _canonical(raw) is None:
            raise SourceTransparencyError(
                f"the {surface} body contains an unparseable or "
                f"userinfo-bearing link {raw!r}"
            )


def validate_source_transparency(
    *,
    article_body: str,
    research: NormalizedResearchArtifact,
    allowed_destinations: tuple[str, ...] = (),
) -> None:
    """Verify the canonical article against the run's actual sources.

    ``allowed_destinations`` are full origins (optionally with a base path),
    e.g. the configured site URL; candidate links are compared to them
    structurally, never by string prefix. Raises ``SourceTransparencyError``
    when the article fails; the caller stops before any publisher is invoked,
    consumes nothing, and the run's evidence records the honest reason.

    Scope note (#196): this is the **canonical article's** provenance
    obligation and it is deliberately undiminished — the published article is
    what proves the run's connection to its external evidence. Social
    derivatives are governed by ``validate_social_lineage`` instead: they
    point at the canonical article, which owns the external-source links.
    """

    source_urls, source_names = _source_identities(research)
    if not source_urls and not source_names:
        raise SourceTransparencyError(
            "the run's research artifact carries no identifiable source "
            "identities to attribute against"
        )
    allowed = tuple(
        _parse(destination) for destination in allowed_destinations if destination
    )
    _check_surface("article", article_body, source_urls, source_names, allowed)


class SocialLineageError(RuntimeError):
    """A social derivative does not point at this run's canonical article."""


def validate_social_lineage(*, social_body: str, canonical_url: str) -> None:
    """Prove a social body points at exactly this canonical article (#196).

    Three obligations, all deterministic and all structural — no model call,
    no judgment, and no tolerance for a model-authored destination:

    1. the canonical URL must be real and parseable (a missing or malformed
       publication URL is not a link, so there is nothing to publish behind);
    2. the assembled body must actually carry it;
    3. it must be the body's **only** external link — a competing
       original-source URL would split the reader away from the article that
       owns the provenance.

    Comparison is the same canonical form the article check uses, so an
    equivalent rendering of the same URL is recognised while a different
    destination — lookalike host, foreign port, userinfo trick — is not.
    """

    canonical = _canonical(canonical_url)
    if canonical is None:
        raise SocialLineageError(
            f"the canonical article URL {canonical_url!r} is missing or "
            "unusable — a social derivative has nothing to point at"
        )
    raw_links = _URL_PATTERN.findall(social_body)
    for raw in raw_links:
        if _canonical(raw) is None:
            raise SocialLineageError(
                f"the social body contains an unparseable or "
                f"userinfo-bearing link {raw!r}"
            )
    body_urls = {_canonical(url) for url in raw_links}
    if canonical not in body_urls:
        raise SocialLineageError(
            "the social body does not link this run's canonical Never Blank "
            f"article ({canonical_url!r}) — social distribution must point at "
            "the published article"
        )
    competing = sorted(url for url in body_urls if url != canonical)
    if competing:
        raise SocialLineageError(
            f"the social body links {competing!r} alongside the canonical "
            "article — the canonical article owns the external-source links, "
            "and a social derivative carries no competing destination"
        )
