"""Retrieve exactly the source a signal already names — and nothing else.

Wednesday is the historical control path (#211). Its job is to reproduce the
July product cleanly enough to be compared against the current Monday system,
and a control that borrows one stage from the system under test is not a
control. Running July discovery, July enrichment and July generation but
*Exa* retrieval made Wednesday a hybrid, so this replaces that one stage.

The contract is deliberately much narrower than a research provider's. This
adapter cannot find anything. It has no query, no domain, no index and no
search endpoint — only a list of exact URLs the caller already decided on. If
asked to do anything wider than fetch those URLs it refuses rather than
improvising, because the one thing that must never happen here is Wednesday
quietly acquiring a source July never had.

**Verification is not weakened, only re-sourced.** The URL is fetched over
plain HTTP, redirects are followed and the final URL recorded, the authority
is checked by the same `require_safe_url_authority` every provider uses, and
a source that cannot be retrieved produces a typed failure — which the
research gate turns into a stopped run. The evidence it emits is
``not_assessed``, exactly as Exa's is, so the shared assessment stage judges
it and the canonical gate holds it to the same READY standard as everything
else. Nothing downstream can tell which adapter retrieved the page, which is
the point: source transparency still receives a real, verified
source-of-record.

Monday is untouched and keeps Exa.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Sequence
from urllib.parse import urlsplit

import requests

from src.research.evidence import (
    EvidenceDisposition,
    EvidenceReadiness,
    ExtractedEvidence,
    NormalizedResearchArtifact,
    NormalizedSource,
    PublicationTime,
    PublicationTimeStatus,
    SourceLocator,
    SourceLocatorKind,
    SupportReference,
)
from src.research.provider import (
    CompleteResearchResult,
    FailedResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchAdapterResult,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceDirectiveKind,
    SourceOrigin,
    SourcePriority,
    SourceRetrievalOutcome,
)
from src.research.url_safety import UnsafeResearchUrl, require_safe_url_authority
from src.utils.logger import get_logger

log = get_logger("research.direct_url")

PROVIDER_ID = "direct-url"
ADAPTER_ID = "never-blank-direct-url"
ADAPTER_VERSION = "1.0"

#: Matched to the canonical-URL verifier (#200/#201) so the two HTTP paths in
#: this repository behave the same way under redirects and slow origins.
REQUEST_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0

USER_AGENT = "NeverBlank/1.0 (+https://www.inneros.online)"

#: Bounded by the evidence contract's own excerpt ceiling.
MAX_EXCERPT_CHARS = 4000


class _PageReader(HTMLParser):
    """Deterministic, dependency-free extraction of title, publisher, text.

    Not a general HTML parser and not trying to be. It reads the handful of
    fields the evidence contract needs and ignores everything else, so its
    behaviour is easy to predict and impossible to surprise.
    """

    _SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self.publisher: str | None = None
        self.published_at: str | None = None
        self._chunks: list[str] = []
        self._in_title = False
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            meta = {key.lower(): (value or "") for key, value in attrs}
            name = (meta.get("property") or meta.get("name") or "").lower()
            content = meta.get("content", "").strip()
            if not content:
                return
            if name in ("og:site_name", "article:publisher") and not self.publisher:
                self.publisher = content
            elif name in ("article:published_time", "datepublished",
                          "og:article:published_time") and not self.published_at:
                self.published_at = content
            elif name == "og:title" and not self.title:
                self.title = content

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skipping:
            return
        if self._in_title and not self.title:
            self.title = data.strip()
        text = data.strip()
        if text:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


class DirectUrlFetchError(RuntimeError):
    """The named source could not be retrieved."""


class _FetchedPage:
    __slots__ = ("requested_url", "final_url", "status", "title", "publisher",
                 "published_at", "text", "redirected")

    def __init__(self, *, requested_url, final_url, status, title, publisher,
                 published_at, text, redirected):
        self.requested_url = requested_url
        self.final_url = final_url
        self.status = status
        self.title = title
        self.publisher = publisher
        self.published_at = published_at
        self.text = text
        self.redirected = redirected


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(1))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


#: Hostnames that are never a published source. Moving retrieval in-house
#: changes who makes the request: Exa fetched from its own infrastructure,
#: while this adapter fetches from our runner, so a URL pointing inward would
#: reach our own network. `require_safe_url_authority` rejects credentials in
#: the authority but not loopback or private ranges, so this closes that.
_LOCAL_HOST_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")
_LOCAL_HOST_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def _require_public_http_url(url: str) -> None:
    """Refuse anything that is not a public http(s) URL.

    Literal addresses are checked against the reserved ranges. Hostnames are
    checked by name only — deliberately no DNS resolution, which would be a
    network call and would race its own answer anyway. That leaves a name
    resolving inward as a residual risk this cannot see; the narrow directive
    contract is what bounds it, since the only URLs reaching here are ones a
    signal's own research already selected.
    """
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise DirectUrlFetchError(f"unsafe source authority: scheme {parsed.scheme!r}")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise DirectUrlFetchError("unsafe source authority: no host")
    if host in _LOCAL_HOST_NAMES or host.endswith(_LOCAL_HOST_SUFFIXES):
        raise DirectUrlFetchError(f"unsafe source authority: local host {host!r}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return                                    # a public-looking name
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast
            or address.is_unspecified):
        raise DirectUrlFetchError(
            f"unsafe source authority: non-public address {host!r}"
        )


def _publisher_of(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _digest(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()[:12]


def _invocation_id(seed: str) -> str:
    """A deterministic, canonical UUID v4 for this invocation.

    Deterministic because a research envelope is create-once and compared
    byte-for-byte on reload: a random id would make the same retrieval
    unreproducible for no benefit.
    """
    raw = bytearray(hashlib.md5(seed.encode()).digest())
    raw[6] = (raw[6] & 0x0F) | 0x40        # version 4
    raw[8] = (raw[8] & 0x3F) | 0x80        # RFC 4122 variant
    return str(uuid.UUID(bytes=bytes(raw)))


def fetch_source(
    url: str,
    *,
    session_factory: Callable[[], "requests.Session"] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> _FetchedPage:
    """GET exactly this URL, following redirects, and read what came back.

    Raises :class:`DirectUrlFetchError` on an unsafe authority, a transport
    failure, or a non-2xx response. There is no partial success: a source
    that could not be read is not evidence.
    """
    import time

    pause = sleep or time.sleep
    # Resolved here, not bound as a default argument, so the transport is
    # replaceable — and so `requests` is only touched when a fetch happens.
    open_session = session_factory or requests.Session
    try:
        require_safe_url_authority(url)
    except UnsafeResearchUrl as exc:
        raise DirectUrlFetchError(f"unsafe source authority: {exc}") from exc
    _require_public_http_url(url)

    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            session = open_session()
            session.max_redirects = MAX_REDIRECTS
            response = session.get(
                url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            status = int(getattr(response, "status_code", 0) or 0)
            final_url = str(getattr(response, "url", "") or url)
            if not 200 <= status < 300:
                raise DirectUrlFetchError(
                    f"source returned HTTP {status} ({url})"
                )
            # The final URL is verified too: a redirect that lands somewhere
            # unsafe is still a source this run must not cite.
            if final_url != url:
                try:
                    require_safe_url_authority(final_url)
                    _require_public_http_url(final_url)
                except UnsafeResearchUrl as exc:
                    raise DirectUrlFetchError(
                        f"source redirected to an unsafe authority: {exc}"
                    ) from exc
                except DirectUrlFetchError as exc:
                    raise DirectUrlFetchError(
                        f"source redirected to an unsafe authority: {exc}"
                    ) from exc

            reader = _PageReader()
            reader.feed(getattr(response, "text", "") or "")
            title = reader.title.strip() or _publisher_of(final_url)
            return _FetchedPage(
                requested_url=url,
                final_url=final_url,
                status=status,
                title=title[:300],
                publisher=(reader.publisher or _publisher_of(final_url))[:200],
                published_at=_parse_published(reader.published_at),
                text=reader.text or title,
                redirected=final_url != url,
            )
        except DirectUrlFetchError:
            raise
        except Exception as exc:                       # transport-level only
            last = exc
            if attempt < MAX_ATTEMPTS:
                pause(RETRY_DELAY_SECONDS)
    raise DirectUrlFetchError(f"source could not be retrieved ({url}): {last}")


class DirectUrlResearchProvider:
    """A research provider that can only fetch URLs it was handed.

    Implements the same protocol as :class:`ExaResearchAdapter` so every
    downstream stage — assessment, the research gate, sources-of-record,
    source transparency — is reached unchanged, and so the choice of adapter
    is a one-line decision at the composition root rather than a fork in the
    lifecycle.
    """

    def __init__(
        self,
        *,
        fetch: Callable[..., _FetchedPage] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Resolved from the module at construction rather than bound as a
        # default argument, so the transport is replaceable without reaching
        # into the instance.
        self._fetch = fetch or fetch_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.requests: list[ResearchProviderRequest] = []

    # -- the protocol ----------------------------------------------------

    def research(self, request: ResearchProviderRequest) -> ResearchAdapterResult:
        self.requests.append(request)
        started = self._clock()

        def invocation(completed_at: datetime) -> ProviderInvocation:
            # Built at the end of each path rather than up front: the contract
            # refuses an invocation that "completed" before its own retrieval
            # attempts, and rightly so.
            return ProviderInvocation(
                attribution=ProviderAttribution(
                    provider_id=PROVIDER_ID,
                    adapter_id=ADAPTER_ID,
                    adapter_version=ADAPTER_VERSION,
                    invocation_id=_invocation_id(request.run_id),
                ),
                started_at=started,
                completed_at=max(completed_at, started),
                attempt_count=1,
            )

        base = dict(
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
        )

        targets, refusal = self._targets(request)
        if refusal is not None:
            log.error("direct-url research refused the request: %s", refusal.message)
            return FailedResearchResult(
                outcome=ResearchOperationOutcome.FAILED, source_outcomes=(),
                operation_failure=refusal,
                invocation=invocation(self._clock()), **base,
            )

        pages: list[tuple[str, _FetchedPage, datetime]] = []
        outcomes: list[SourceRetrievalOutcome] = []
        for directive_id, url in targets:
            attempted_at = self._clock()
            try:
                page = self._fetch(url)
            except DirectUrlFetchError as exc:
                # Fail closed. A named source that cannot be read leaves the
                # run with nothing to attribute, and publishing a claim about
                # a source nobody could fetch is the defect this prevents.
                failure = ProviderFailure(
                    code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                    message=str(exc)[:500], retryable=True,
                )
                outcomes.append(SourceRetrievalOutcome(
                    retrieval_id=f"retrieval-{_digest(url)}",
                    directive_id=directive_id, origin=SourceOrigin.CLIENT_SUPPLIED,
                    locator=url, status=RetrievalStatus.FAILED,
                    attempted_at=attempted_at, failure=failure,
                ))
                log.error("direct-url retrieval failed for %s: %s", url, exc)
                return FailedResearchResult(
                    outcome=ResearchOperationOutcome.FAILED,
                    source_outcomes=tuple(outcomes),
                    operation_failure=failure,
                    invocation=invocation(self._clock()), **base,
                )

            retrieved_at = self._clock()
            pages.append((directive_id, page, retrieved_at))
            outcomes.append(SourceRetrievalOutcome(
                retrieval_id=f"retrieval-{_digest(page.requested_url)}",
                directive_id=directive_id,
                source_id=f"source-{_digest(page.requested_url)}",
                # Never PROVIDER_DISCOVERED: this adapter cannot discover.
                origin=SourceOrigin.CLIENT_SUPPLIED,
                # The redirect diagnostic: where the request actually ended up.
                locator=page.final_url,
                status=RetrievalStatus.RETRIEVED,
                attempted_at=attempted_at,
                retrieved_at=retrieved_at,
            ))
            log.info(
                "direct-url retrieved %s (status=%s redirected=%s final=%s)",
                page.requested_url, page.status, page.redirected, page.final_url,
            )

        completed = self._clock()
        return CompleteResearchResult(
            outcome=ResearchOperationOutcome.COMPLETE,
            source_outcomes=tuple(outcomes),
            artifact=self._artifact(request, pages, completed),
            operation_failure=None,
            invocation=invocation(completed), **base,
        )

    # -- internals -------------------------------------------------------

    @staticmethod
    def _targets(
        request: ResearchProviderRequest,
    ) -> tuple[list[tuple[str, str]], ProviderFailure | None]:
        """The exact URLs to fetch — or a refusal, if anything wider is asked.

        A DISCOVERY directive or a bare domain is a request to go looking.
        This adapter does not look, and says so rather than silently ignoring
        the directive, because an ignored directive would leave the caller
        believing a source class had been consulted when it had not.
        """
        wider = [
            directive.directive_id
            for directive in request.source_directives
            if directive.priority is not SourcePriority.EXCLUDED
            and (
                directive.priority is SourcePriority.DISCOVERY
                or directive.kind is not SourceDirectiveKind.URL
            )
        ]
        if wider or request.freshness.allow_open_discovery:
            return [], ProviderFailure(
                code=ProviderFailureCode.UNAVAILABLE,
                message=(
                    "direct-url retrieval cannot discover sources; refused "
                    f"non-URL or discovery directives {wider!r}"
                )[:500],
                retryable=False,
            )

        excluded = {
            directive.value.lower()
            for directive in request.source_directives
            if directive.priority is SourcePriority.EXCLUDED
        }
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for directive in request.source_directives:
            if directive.priority is SourcePriority.EXCLUDED:
                continue
            url = directive.value.strip()
            if url.lower() in excluded or url in seen:
                continue
            seen.add(url)
            targets.append((directive.directive_id, url))

        if not targets:
            return [], ProviderFailure(
                code=ProviderFailureCode.EMPTY_RESULT,
                message="no exact source URL was supplied to retrieve",
                retryable=False,
            )
        return targets, None

    @staticmethod
    def _artifact(
        request: ResearchProviderRequest,
        pages: Sequence[tuple[str, _FetchedPage, datetime]],
        created_at: datetime,
    ) -> NormalizedResearchArtifact:
        sources: list[NormalizedSource] = []
        evidence: list[ExtractedEvidence] = []
        for _directive_id, page, retrieved_at in pages:
            # The source-of-record is the URL the signal cites and the article
            # will attribute — not wherever a redirect happened to land. A
            # publication that moves its own article to a new path has not
            # become a different source, and recording the landing URL here
            # would make source transparency reject an article for citing the
            # very URL its research selected. Where the fetch actually ended
            # up is preserved as retrieval diagnostics on the outcome below.
            source_id = f"source-{_digest(page.requested_url)}"
            sources.append(NormalizedSource(
                source_id=source_id,
                locator=SourceLocator(
                    kind=SourceLocatorKind.URL, value=page.requested_url
                ),
                title=page.title,
                publisher=page.publisher,
                publication_time=PublicationTime(
                    status=(
                        PublicationTimeStatus.KNOWN
                        if page.published_at is not None
                        else PublicationTimeStatus.UNKNOWN
                    ),
                    value=page.published_at,
                ),
                retrieved_at=retrieved_at,
            ))
            excerpt = page.text[:MAX_EXCERPT_CHARS] or page.title
            evidence.append(ExtractedEvidence(
                evidence_id=f"evidence-{_digest(page.requested_url)}",
                claim=excerpt,
                source_ids=(source_id,),
                support=(SupportReference(source_id=source_id, excerpt=excerpt),),
                # Retrieval never judges. The shared assessment stage does,
                # exactly as it does for every other adapter.
                disposition=EvidenceDisposition.NOT_ASSESSED,
            ))
        return NormalizedResearchArtifact(
            artifact_id=f"research-{request.run_id}",
            run_id=request.run_id,
            assignment_id=request.assignment_id,
            signal_id=request.signal_id,
            configuration_identity=request.strategy.identity,
            created_at=created_at,
            sources=tuple(sources),
            evidence=tuple(evidence),
            # Retrieval never asserts readiness — `assess_artifact` derives
            # it from the assessment. This adapter reaches the artifact only
            # when every named source was retrieved (any failure returns a
            # FailedResearchResult above), so the pre-assessment value is the
            # same NEEDS_REVIEW Exa uses for a complete retrieval.
            readiness=EvidenceReadiness.NEEDS_REVIEW,
        )


__all__ = [
    "ADAPTER_ID",
    "PROVIDER_ID",
    "DirectUrlFetchError",
    "DirectUrlResearchProvider",
    "fetch_source",
]
