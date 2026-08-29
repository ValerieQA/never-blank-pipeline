"""Structural URL-authority safety shared by research contracts and adapters."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit


class UnsafeResearchUrl(ValueError):
    """A URL authority contains forbidden user-info; message is audit-safe."""


_SAFE_ERROR = "HTTP(S) URL authority must not contain user-info"


def require_safe_url_authority(value: str, *, allow_domain: bool = False) -> str:
    """Reject HTTP(S) authority user-info without echoing the supplied value.

    User-info is forbidden even when the delimiter or its username/password
    components are percent encoded. ``@`` in path, query, or fragment is not
    part of the authority and remains valid.
    """

    candidate = value
    if allow_domain and "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"}:
        return value
    authority = parsed.netloc
    decoded_authority = authority
    # Each decoding layer shortens at least one ``%xx`` sequence, so the
    # authority length is a strict finite upper bound for nested encodings.
    for _ in range(len(authority) + 1):
        decoded = unquote(decoded_authority)
        if decoded == decoded_authority:
            break
        decoded_authority = decoded
    if parsed.username is not None or "@" in decoded_authority:
        raise UnsafeResearchUrl(_SAFE_ERROR)
    return value


def registrable_host(value: str) -> str:
    """The comparable host of a URL or bare domain.

    Moved here from ``adapters/exa.py`` (#211) unchanged, so the two adapters
    share one definition of "the same site" rather than growing a second one.
    Exa imports it from here and behaves exactly as before.
    """
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    return (parsed.hostname or value).casefold().rstrip(".").removeprefix("www.")


def is_within_domain(url_or_domain: str, expected_domain: str) -> bool:
    """Is the candidate the expected host, or a subdomain of it?

    Also moved from ``adapters/exa.py`` unchanged. Not a public-suffix
    implementation: it answers "same host or below it", which is what both
    callers need and what the repository has always meant by same-site.
    """
    candidate = registrable_host(url_or_domain)
    expected = registrable_host(expected_domain)
    return candidate == expected or candidate.endswith("." + expected)
