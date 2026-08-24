"""Can a reader actually open the URL the provider gave us for this post?

Issue #200. Live run 32740322282 published a social post whose canonical
link returned 404: the provider had returned no URL, a route was constructed
locally from a hardcoded path shape, and every stage downstream treated that
guess as canonical because nothing ever asked where it came from or whether
it resolved.

This module answers exactly one of the two questions that failure raised —
**reachability**. The other one, *identity*, is deliberately not answered
here, and never by inspecting URL text: which post a URL belongs to is
established upstream by the provider object contract (publish, retrieve that
exact post ID, use the ``PageUrl`` the provider attaches to the object it
returns). A URL arriving here has already been proven to belong to the
published post; what remains is whether the public web agrees it exists.

So: a bounded HTTP request with redirects followed normally, a final
response that succeeds, and a final destination still on the expected host.
No path conventions, no slug matching, no page-content heuristics, no model.
Anything unproven fails closed — an unverifiable URL is not a weaker yes.

Generic by construction: it knows a URL, an expected host and a transport.
It knows nothing about which channel will use the URL, which business
publishes it, or what day it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Tuple
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
#: Redirect hops the HTTP client may follow before the chain is refused.
MAX_REDIRECTS = 5

#: The final destination must actually answer.
_SUCCESS_STATUSES = frozenset({200, 203, 204, 206})

#: ``(final_url, status)`` after redirects, or ``None`` when the transport
#: failed outright.
FetchResult = Optional[Tuple[str, int]]


class CanonicalUrlError(RuntimeError):
    """The canonical article URL could not be established."""


@dataclass(frozen=True)
class CanonicalUrlVerdict:
    """Whether a provider-attached URL is publicly usable, and why not."""

    #: The provider's URL for the post — what gets published on success.
    url: str
    provenance: UrlProvenance
    verified: bool
    #: Where the request actually landed, recorded only when a redirect moved
    #: it. The provider's URL stays canonical; this records the movement
    #: truthfully instead of silently substituting a different address.
    final_resolved_url: str = ""
    failure_reason: Optional[str] = None
    http_status: Optional[int] = None
    attempts: int = 0

    def as_audit_dict(self) -> dict:
        """The shape persisted into the run's publication evidence."""
        return {
            "url": self.url,
            "provenance": self.provenance.value,
            "verified": self.verified,
            "final_resolved_url": self.final_resolved_url or None,
            "failure_reason": self.failure_reason,
            "reachability_status": self.http_status,
            "attempts": self.attempts,
        }


def _fetch_final(url: str) -> FetchResult:
    """One bounded request, redirects followed; ``(final_url, status)``.

    ``HEAD`` first because the body is irrelevant; some hosts answer HEAD
    with 405/501, so a single ``GET`` follows in that case. Redirect
    following is the HTTP client's own job — there is no custom 3xx logic
    here, only a hop ceiling and the destination it lands on.
    """
    import requests

    for method in ("HEAD", "GET"):
        try:
            session = requests.Session()
            session.max_redirects = MAX_REDIRECTS
            response = session.request(
                method, url,
                timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True,
            )
        except Exception as exc:  # noqa: BLE001 — any transport failure is "unverified"
            log.warning("canonical url: %s %s failed (%s)", method, url, exc)
            return None
        if response.status_code not in (405, 501):
            return str(response.url), response.status_code
    return None


def _host_of(value: str) -> str:
    parsed = urlsplit(value if "//" in value else f"//{value}")
    return (parsed.hostname or "").lower()


def verify_canonical_url(
    *,
    url: str,
    provenance: UrlProvenance,
    expected_host: str,
    fetch: Callable[[str], FetchResult] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> CanonicalUrlVerdict:
    """Decide whether the provider's URL for this post may be published.

    The URL must already be provider-attached (``provenance``); this adds
    that it is structurally a page on the expected host and that the public
    web serves it. Returns a verdict rather than raising — a refused URL is
    evidence the run must record, not an exception to swallow.

    ``fetch`` and ``sleep`` are injectable so the decision can be exercised
    without a network.
    """

    request = fetch or _fetch_final
    pause = sleep if sleep is not None else __import__("time").sleep
    candidate = (url or "").strip()

    def refuse(reason, *, final="", status=None, attempts=0):
        log.warning("canonical url refused (%s): %s", reason, candidate or "—")
        return CanonicalUrlVerdict(
            url=candidate, provenance=provenance, verified=False,
            final_resolved_url=final, failure_reason=reason,
            http_status=status, attempts=attempts,
        )

    if not candidate:
        return refuse("no_candidate_url")

    # Origin: only a URL the provider attached to the post may be published.
    if not provenance.is_provider_sourced():
        return refuse(f"not_provider_sourced:{provenance.value}")

    expected = _host_of(expected_host).lstrip(".")
    if not expected:
        return refuse("no_expected_host_configured")

    parts = urlsplit(candidate)
    if parts.scheme.lower() != "https":
        return refuse("not_https")
    if not parts.hostname:
        return refuse("no_host")
    if parts.hostname.lower() != expected:
        return refuse(f"unexpected_host:{parts.hostname.lower()}")

    # Reachability: bounded attempts, fixed backoff, no polling.
    status = None
    final = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = request(candidate)
        if result is not None:
            final, status = result
            if status in _SUCCESS_STATUSES:
                # Where the reader lands must still be this site. A redirect
                # off the expected host is not our article, whatever it says.
                landed = _host_of(final)
                if landed and landed != expected:
                    return refuse(
                        f"redirect_left_expected_host:{landed}",
                        final=final, status=status, attempts=attempt,
                    )
                moved = final if final and final != candidate else ""
                log.info(
                    "canonical url reachable: %s (HTTP %s%s, attempt %s)",
                    candidate, status,
                    f", resolved to {final}" if moved else "", attempt,
                )
                return CanonicalUrlVerdict(
                    url=candidate, provenance=provenance, verified=True,
                    final_resolved_url=moved, http_status=status,
                    attempts=attempt,
                )
        if attempt < MAX_ATTEMPTS:
            pause(RETRY_DELAY_SECONDS)

    return refuse(
        "unreachable" if status is None else f"http_{status}",
        final=final, status=status, attempts=MAX_ATTEMPTS,
    )
