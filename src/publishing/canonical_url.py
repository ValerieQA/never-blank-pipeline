"""Is this URL really the published article we are about to point readers at?

Issue #200. Live run 32740322282 published a social post whose canonical
link returned 404: the provider had returned no URL, a route was constructed
locally from a hardcoded path shape, and every stage downstream treated that
guess as canonical because nothing ever asked where it came from or whether
it resolved.

Two independent obligations, both deterministic and both required before a
URL may be called canonical:

1. **Origin** — the provider itself must have produced the URL. A route this
   codebase assembled is a hypothesis about site configuration; it may be
   recorded as evidence but can never be the destination of a published post.
2. **Resolution** — the URL must actually answer, on the expected host, at a
   path that carries this post's own slug. That last part is what separates
   "the site is up" from "this article is there": a generic 200 from the site
   root proves nothing about the post.

No model is involved at any point. Publication propagation can lag by a few
seconds, so resolution is retried a bounded number of times with a fixed
short backoff — never open-ended polling.

Generic by construction: it knows a URL, an expected host, a slug and a
transport. It knows nothing about which channel will use the URL, which
business publishes it, or what day it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit

from src.publishing.result import UrlProvenance

log = logging.getLogger(__name__)

#: Bounded resolution attempts. Publication propagation is usually immediate
#: and occasionally lags a moment; three attempts covers that without ever
#: becoming a poll loop.
MAX_ATTEMPTS = 3
#: Fixed seconds between attempts. Deliberately not exponential: the ceiling
#: must stay obvious and small.
RETRY_DELAY_SECONDS = 2.0
#: Hard per-request timeout.
REQUEST_TIMEOUT_SECONDS = 10.0

#: Statuses that prove the page answers. Anything else — 404 (the live
#: defect), 403, 5xx, a transport error — leaves the URL unverified.
_OK_STATUSES = frozenset({200, 203, 204, 206, 301, 302, 303, 307, 308})


class CanonicalUrlError(RuntimeError):
    """The canonical article URL could not be established."""


@dataclass(frozen=True)
class CanonicalUrlVerdict:
    """Why a candidate URL is, or is not, usable as the canonical article."""

    url: str
    provenance: UrlProvenance
    verified: bool
    #: Machine-readable reason a candidate was refused; ``None`` when verified.
    failure_reason: Optional[str] = None
    #: HTTP status the resolution attempt saw, when there was one.
    http_status: Optional[int] = None
    attempts: int = 0

    def as_audit_dict(self) -> dict:
        """The shape persisted into the run's publication evidence."""
        return {
            "url": self.url,
            "provenance": self.provenance.value,
            "verified": self.verified,
            "failure_reason": self.failure_reason,
            "http_status": self.http_status,
            "attempts": self.attempts,
        }


def _http_status(url: str) -> Optional[int]:
    """One bounded request. ``None`` when the transport itself failed.

    ``HEAD`` first because the body is irrelevant; some hosts answer HEAD
    with 405, so a single ``GET`` follows in that case. Redirects are not
    followed — a redirect status is itself proof the page exists.
    """
    import requests

    for method in ("head", "get"):
        try:
            response = getattr(requests, method)(
                url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False
            )
        except Exception as exc:  # noqa: BLE001 — any transport failure is "unverified"
            log.warning("canonical url: %s %s failed (%s)", method.upper(), url, exc)
            return None
        if response.status_code not in (405, 501):
            return response.status_code
    return None


def verify_canonical_url(
    *,
    url: str,
    provenance: UrlProvenance,
    expected_host: str,
    slug: str = "",
    status_probe: Callable[[str], Optional[int]] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> CanonicalUrlVerdict:
    """Decide whether ``url`` may be the canonical article URL.

    Returns a verdict rather than raising: a refused URL is evidence the run
    must record, not an exception to swallow. The caller fails closed on
    ``verified is False``.

    ``status_probe`` and ``sleep`` are injectable so the decision can be
    exercised without a network.
    """

    probe = status_probe or _http_status
    pause = sleep if sleep is not None else __import__("time").sleep

    def refuse(reason: str, status: Optional[int] = None, attempts: int = 0):
        log.warning("canonical url refused (%s): %s", reason, url or "—")
        return CanonicalUrlVerdict(
            url=url, provenance=provenance, verified=False,
            failure_reason=reason, http_status=status, attempts=attempts,
        )

    if not url:
        return refuse("no_candidate_url")

    # 1. Origin: only the provider may author a canonical destination.
    if not provenance.is_provider_sourced():
        return refuse(f"not_provider_sourced:{provenance.value}")

    # 2. Structure: https, on the site we publish to, with a real page path.
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https":
        return refuse("not_https")
    host = (parts.hostname or "").lower()
    if not host:
        return refuse("no_host")
    expected = (urlsplit(expected_host).hostname or expected_host or "").lower()
    if not expected:
        return refuse("no_expected_host_configured")
    if host != expected.lstrip("."):
        return refuse(f"unexpected_host:{host}")
    path = parts.path or ""
    if path.strip("/") == "":
        return refuse("no_page_path")

    # 3. Identity: the provider's own slug must be in the provider's own
    #    path. This is what a generic site 200 cannot satisfy.
    if slug and slug.strip().lower() not in path.lower():
        return refuse("path_does_not_carry_post_slug")

    # 4. Resolution: bounded attempts, fixed backoff, no polling.
    status = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status = probe(url)
        if status is not None and status in _OK_STATUSES:
            log.info(
                "canonical url verified: %s (HTTP %s, attempt %s)",
                url, status, attempt,
            )
            return CanonicalUrlVerdict(
                url=url, provenance=provenance, verified=True,
                http_status=status, attempts=attempt,
            )
        if attempt < MAX_ATTEMPTS:
            pause(RETRY_DELAY_SECONDS)

    return refuse(
        "unreachable" if status is None else f"http_{status}",
        status, MAX_ATTEMPTS,
    )
