"""Fail-closed source-transparency check for roles that require it (#142).

A role may instruct its prompts to attribute sources; an instruction is not a
guarantee. When a role declares ``require_source_transparency`` this boundary
verifies, after generation and before any publisher is called, that the
composed bodies actually carry attribution — and that the attribution belongs
to **this run's** sources rather than merely looking like a citation.

Two checks, both against the run's own research artifact:

1. **Presence** — each required surface must reference at least one real
   source identity from the run: an exact source URL, a publisher name, or a
   source title. Text that cites nothing the run retrieved has no provenance,
   however confidently it reads.
2. **No invented links** — every http(s) URL in a checked body must be one of
   the run's source URLs or start with an explicitly allowed prefix (the
   configured site destination). A fabricated URL is the most dangerous form
   of fake citation, and it is exactly the thing a model produces when asked
   to "cite sources" it does not have.

Generic by construction: which roles require this, and what their prompts say
about presentation, is configuration. This module knows only bodies, a
research artifact, and allowed URL prefixes — no role names, no weekdays, no
publisher branching. Roles that do not declare the requirement are never
checked, so every existing stream keeps its prior behaviour.
"""

from __future__ import annotations

import re

from src.research.evidence import NormalizedResearchArtifact


class SourceTransparencyError(RuntimeError):
    """A required surface lacks usable, run-grounded source attribution."""


_URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")

#: Minimum length for a title fragment to count as attribution — a two-word
#: title like "The Report" would match prose by accident.
_MIN_TITLE_LENGTH = 12


def _normalize_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}\"'").rstrip("/").lower()


def _source_identities(research: NormalizedResearchArtifact) -> tuple[set, set]:
    """The run's real source identities: normalized URLs, and name fragments."""

    urls, names = set(), set()
    for source in research.sources:
        locator = getattr(source.locator, "value", "") or ""
        if locator.startswith("http"):
            urls.add(_normalize_url(locator))
        publisher = (source.publisher or "").strip()
        if publisher:
            names.add(publisher.lower())
        title = (source.title or "").strip()
        if len(title) >= _MIN_TITLE_LENGTH:
            names.add(title.lower())
    return urls, names


def _check_surface(
    surface: str,
    body: str,
    source_urls: set,
    source_names: set,
    allowed_prefixes: tuple[str, ...],
) -> None:
    text = body.lower()
    body_urls = {_normalize_url(url) for url in _URL_PATTERN.findall(body)}

    cited_urls = body_urls & source_urls
    cited_names = {name for name in source_names if name in text}
    if not cited_urls and not cited_names:
        raise SourceTransparencyError(
            f"the {surface} body carries no attribution to any of this run's "
            "sources — no source URL, publisher, or title appears in it"
        )

    allowed = tuple(_normalize_url(prefix) for prefix in allowed_prefixes if prefix)
    for url in body_urls - cited_urls:
        if not any(url.startswith(prefix) for prefix in allowed):
            raise SourceTransparencyError(
                f"the {surface} body links {url!r}, which is not one of this "
                "run's sources and not an allowed destination — an invented "
                "or unrelated link is not attribution"
            )


def validate_source_transparency(
    *,
    article_body: str,
    linkedin_body: str,
    research: NormalizedResearchArtifact,
    allowed_url_prefixes: tuple[str, ...] = (),
) -> None:
    """Verify both Release 1 surfaces against the run's actual sources.

    Raises ``SourceTransparencyError`` on the first surface that fails; the
    caller stops before any publisher is invoked, consumes nothing, and the
    run's evidence records the honest reason.
    """

    source_urls, source_names = _source_identities(research)
    if not source_urls and not source_names:
        raise SourceTransparencyError(
            "the run's research artifact carries no identifiable source "
            "identities to attribute against"
        )
    _check_surface(
        "article", article_body, source_urls, source_names, allowed_url_prefixes
    )
    _check_surface(
        "linkedin", linkedin_body, source_urls, source_names, allowed_url_prefixes
    )
