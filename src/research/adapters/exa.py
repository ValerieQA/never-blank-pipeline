"""Exa production adapter behind the provider-neutral research protocol.

The default transport uses Exa's REST API through the repository's existing
``requests`` dependency.  Tests inject a deterministic transport and never use
the network or credentials.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

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
    PartialResearchResult,
    ProviderAttribution,
    ProviderFailure,
    ProviderFailureCode,
    ProviderInvocation,
    ResearchAdapterResult,
    ResearchOperationOutcome,
    ResearchProviderRequest,
    RetrievalStatus,
    SourceDirective,
    SourceDirectiveKind,
    SourceOrigin,
    SourcePriority,
    SourceRetrievalOutcome,
)
from src.research.url_safety import (
    UnsafeResearchUrl,
    is_within_domain,
    registrable_host,
    require_safe_url_authority,
)


EXA_PROVIDER_ID = "exa"
EXA_ADAPTER_ID = "never-blank-exa-rest"
EXA_ADAPTER_VERSION = "1.0"


@dataclass(frozen=True)
class ExaDocument:
    url: str
    title: str
    text: str
    publisher: str | None = None
    published_at: datetime | None = None


class ExaTransportError(RuntimeError):
    """Internal-only transport error translated at the adapter boundary."""

    retry_after_seconds: int | None = None


class ExaTimeout(ExaTransportError):
    pass


class ExaAuthenticationError(ExaTransportError):
    pass


class ExaRateLimited(ExaTransportError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__("Exa rate limited the request")
        self.retry_after_seconds = retry_after_seconds


class ExaMalformedResponse(ExaTransportError):
    pass


class ExaUnavailable(ExaTransportError):
    pass


class ExaTransport:
    """Narrow injectable transport contract; raw responses remain internal."""

    def contents(self, urls: Sequence[str]) -> tuple[ExaDocument, ...]:
        raise NotImplementedError

    def search(
        self,
        query: str,
        *,
        include_domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
    ) -> tuple[ExaDocument, ...]:
        raise NotImplementedError


class RequestsExaTransport(ExaTransport):
    """Minimal Exa REST transport using ``NB_EXA_API_KEY`` from the environment."""

    _base_url = "https://api.exa.ai"

    def __init__(self, api_key: str | None = None, timeout_seconds: int = 30) -> None:
        self._api_key = api_key or os.getenv("NB_EXA_API_KEY", "")
        if not self._api_key:
            raise EnvironmentError("NB_EXA_API_KEY is not set")
        self._timeout_seconds = timeout_seconds

    def contents(self, urls: Sequence[str]) -> tuple[ExaDocument, ...]:
        return self._post(
            "/contents",
            {"urls": list(urls), "text": True},
        )

    def search(
        self,
        query: str,
        *,
        include_domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
    ) -> tuple[ExaDocument, ...]:
        payload: dict[str, object] = {
            "query": query,
            "type": "auto",
            "numResults": 10,
            "contents": {"text": True},
        }
        if include_domains:
            payload["includeDomains"] = list(include_domains)
        if exclude_domains:
            payload["excludeDomains"] = list(exclude_domains)
        return self._post("/search", payload)

    def _post(self, path: str, payload: Mapping[str, object]) -> tuple[ExaDocument, ...]:
        import requests

        try:
            response = requests.post(
                self._base_url + path,
                headers={
                    "x-api-key": self._api_key,
                    "content-type": "application/json",
                },
                json=dict(payload),
                timeout=self._timeout_seconds,
            )
        except requests.Timeout as exc:
            raise ExaTimeout("Exa request timed out") from exc
        except requests.RequestException as exc:
            raise ExaUnavailable("Exa service is unavailable") from exc

        if response.status_code in {401, 403}:
            raise ExaAuthenticationError("Exa authentication failed")
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            parsed_retry = int(retry_after) if retry_after and retry_after.isdigit() else None
            raise ExaRateLimited(parsed_retry)
        if response.status_code >= 500:
            raise ExaUnavailable("Exa service is unavailable")
        if response.status_code >= 400:
            raise ExaMalformedResponse("Exa rejected the request")

        try:
            data = response.json()
            return _parse_documents(data)
        except (TypeError, ValueError, KeyError) as exc:
            raise ExaMalformedResponse("Exa returned a malformed response") from exc


def _parse_documents(data: object) -> tuple[ExaDocument, ...]:
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("results must be a list")
    documents: list[ExaDocument] = []
    for raw in data["results"]:
        if not isinstance(raw, dict):
            raise ValueError("result must be an object")
        url = raw.get("url")
        title = raw.get("title")
        text = raw.get("text")
        if not all(isinstance(item, str) and item.strip() for item in (url, title, text)):
            raise ValueError("result requires URL, title, and text")
        published_at = _parse_optional_utc(raw.get("publishedDate"))
        publisher = raw.get("author")
        if publisher is not None and not isinstance(publisher, str):
            raise ValueError("author must be text")
        documents.append(
            ExaDocument(
                url=url,
                title=title,
                text=text,
                publisher=publisher,
                published_at=published_at,
            )
        )
    return tuple(documents)


def _parse_optional_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("publishedDate must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("publishedDate must include a timezone")
    return parsed.astimezone(timezone.utc)


class ExaResearchAdapter:
    """Retrieve prioritized sources and normalize them into Issue #50 models."""

    def __init__(
        self,
        transport: ExaTransport | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        uuid_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self._transport = transport or RequestsExaTransport()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._uuid_factory = uuid_factory or uuid.uuid4

    def research(self, request: ResearchProviderRequest) -> ResearchAdapterResult:
        started_at = self._now()
        if started_at < request.requested_at:
            raise ValueError("provider invocation cannot precede request time")
        if started_at < request.freshness.retrieved_not_before:
            raise ValueError("provider invocation does not satisfy freshness boundary")
        invocation_id = str(self._uuid_factory())
        documents: list[tuple[ExaDocument, SourceOrigin, str | None, datetime]] = []
        outcomes: list[SourceRetrievalOutcome] = []
        excluded = tuple(
            item.value
            for item in request.source_directives
            if item.priority is SourcePriority.EXCLUDED
        )
        ordered = sorted(
            (
                item
                for item in request.source_directives
                if item.priority is not SourcePriority.EXCLUDED
            ),
            key=lambda item: {
                SourcePriority.REQUIRED: 0,
                SourcePriority.PREFERRED: 1,
                SourcePriority.DISCOVERY: 2,
            }[item.priority],
        )

        fatal: ProviderFailure | None = None
        for directive in ordered:
            if directive.priority is SourcePriority.DISCOVERY:
                if not request.freshness.allow_open_discovery:
                    continue
                error = self._search_directive(
                    request,
                    directive,
                    include_domains=(),
                    excluded=excluded,
                    documents=documents,
                    outcomes=outcomes,
                )
            elif directive.kind in {SourceDirectiveKind.URL, SourceDirectiveKind.FEED}:
                error = self._content_directive(
                    directive, excluded, documents, outcomes
                )
            else:
                error = self._search_directive(
                    request,
                    directive,
                    include_domains=(directive.value,),
                    excluded=excluded,
                    documents=documents,
                    outcomes=outcomes,
                )
            if error is not None and error.code in {
                ProviderFailureCode.AUTHENTICATION,
                ProviderFailureCode.MALFORMED_RESPONSE,
            }:
                fatal = error
                break

        completed_at = self._now()
        invocation = ProviderInvocation(
            attribution=ProviderAttribution(
                provider_id=EXA_PROVIDER_ID,
                adapter_id=EXA_ADAPTER_ID,
                adapter_version=EXA_ADAPTER_VERSION,
                invocation_id=invocation_id,
            ),
            started_at=started_at,
            completed_at=completed_at,
            attempt_count=max(1, len(ordered)),
        )

        successful = self._deduplicate(documents, excluded)
        successful_outcomes = self._successful_outcomes(successful)
        outcomes = [item for item in outcomes if item.status is RetrievalStatus.FAILED]
        outcomes.extend(successful_outcomes)

        if not successful:
            failure = fatal or _first_failure(outcomes) or ProviderFailure(
                code=ProviderFailureCode.EMPTY_RESULT,
                message="Research provider returned no usable sources",
                retryable=False,
            )
            return FailedResearchResult(
                outcome=ResearchOperationOutcome.FAILED,
                request_run_id=request.run_id,
                request_assignment_id=request.assignment_id,
                request_signal_id=request.signal_id,
                invocation=invocation,
                source_outcomes=tuple(outcomes),
                operation_failure=failure,
            )

        has_failure = any(item.status is RetrievalStatus.FAILED for item in outcomes)
        artifact = self._artifact(
            request,
            successful,
            completed_at,
            readiness=(
                EvidenceReadiness.INSUFFICIENT
                if has_failure
                else EvidenceReadiness.NEEDS_REVIEW
            ),
        )
        common = dict(
            request_run_id=request.run_id,
            request_assignment_id=request.assignment_id,
            request_signal_id=request.signal_id,
            invocation=invocation,
            source_outcomes=tuple(outcomes),
            artifact=artifact,
        )
        if has_failure:
            return PartialResearchResult(
                outcome=ResearchOperationOutcome.PARTIAL,
                operation_failure=fatal
                or ProviderFailure(
                    code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                    message="One or more research sources could not be retrieved",
                    retryable=True,
                ),
                **common,
            )
        return CompleteResearchResult(
            outcome=ResearchOperationOutcome.COMPLETE,
            operation_failure=None,
            **common,
        )

    def _content_directive(
        self,
        directive: SourceDirective,
        excluded: Sequence[str],
        documents: list[tuple[ExaDocument, SourceOrigin, str | None, datetime]],
        outcomes: list[SourceRetrievalOutcome],
    ) -> ProviderFailure | None:
        if _is_excluded(directive.value, excluded):
            failure = ProviderFailure(
                code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                message="Source is excluded by research policy",
                retryable=False,
            )
            outcomes.append(_failed_outcome(directive, failure, self._now()))
            return failure
        try:
            found = self._transport.contents((directive.value,))
            if not found:
                raise ExaUnavailable("Exact source was not retrieved")
            try:
                for document in found:
                    require_safe_url_authority(document.url)
            except UnsafeResearchUrl:
                failure = _unsafe_url_failure()
                outcomes.append(_failed_outcome(directive, failure, self._now()))
                return failure
            matching = tuple(
                document
                for document in found
                if _canonical_url(document.url).rstrip("/")
                == _canonical_url(directive.value).rstrip("/")
            )
            if not matching:
                raise ExaMalformedResponse("Exact source response did not match request")
            retrieved_at = self._now()
            for document in matching:
                if not _is_excluded(document.url, excluded):
                    documents.append(
                        (document, SourceOrigin.CLIENT_SUPPLIED, directive.directive_id, retrieved_at)
                    )
            return None
        except ExaTransportError as exc:
            failure = _normalize_error(exc, source_level=True)
            outcomes.append(_failed_outcome(directive, failure, self._now()))
            return failure

    def _search_directive(
        self,
        request: ResearchProviderRequest,
        directive: SourceDirective,
        *,
        include_domains: Sequence[str],
        excluded: Sequence[str],
        documents: list[tuple[ExaDocument, SourceOrigin, str | None, datetime]],
        outcomes: list[SourceRetrievalOutcome],
    ) -> ProviderFailure | None:
        if include_domains and any(_is_excluded(domain, excluded) for domain in include_domains):
            failure = ProviderFailure(
                code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                message="Preferred source is excluded by research policy",
                retryable=False,
            )
            outcomes.append(_failed_outcome(directive, failure, self._now()))
            return failure
        try:
            normalized_includes = tuple(_domain(item) for item in include_domains)
            found = self._transport.search(
                _research_query(request, directive.value),
                include_domains=normalized_includes,
                exclude_domains=_domain_exclusions(excluded),
            )
            retrieved_at = self._now()
            safe_found: list[ExaDocument] = []
            unsafe_found = False
            for document in found:
                try:
                    require_safe_url_authority(document.url)
                    safe_found.append(document)
                except UnsafeResearchUrl:
                    unsafe_found = True
            if unsafe_found:
                outcomes.append(
                    _failed_outcome(directive, _unsafe_url_failure(), self._now())
                )
            usable = tuple(
                document
                for document in safe_found
                if not _is_excluded(document.url, excluded)
                and (
                    not normalized_includes
                    or any(
                        _is_within_domain(document.url, domain)
                        for domain in normalized_includes
                    )
                )
            )
            for document in usable:
                documents.append(
                    (document, SourceOrigin.PROVIDER_DISCOVERED, directive.directive_id, retrieved_at)
                )
            if not usable:
                failure = (
                    _unsafe_url_failure()
                    if unsafe_found
                    else ProviderFailure(
                        code=ProviderFailureCode.SOURCE_RETRIEVAL_FAILED,
                        message="Search produced no usable sources",
                        retryable=False,
                    )
                )
                if not unsafe_found:
                    outcomes.append(_failed_outcome(directive, failure, self._now()))
                return failure
            return None
        except ExaTransportError as exc:
            failure = _normalize_error(exc, source_level=False)
            outcomes.append(_failed_outcome(directive, failure, self._now()))
            return failure

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("adapter clock must return timezone-aware UTC")
        return value

    @staticmethod
    def _deduplicate(
        documents: Sequence[tuple[ExaDocument, SourceOrigin, str | None, datetime]],
        excluded: Sequence[str],
    ) -> tuple[tuple[ExaDocument, SourceOrigin, str | None, datetime], ...]:
        unique: dict[str, tuple[ExaDocument, SourceOrigin, str | None, datetime]] = {}
        for item in documents:
            if not _is_excluded(item[0].url, excluded):
                canonical_url = _canonical_url(item[0].url)
                unique.setdefault(
                    canonical_url,
                    (replace(item[0], url=canonical_url), *item[1:]),
                )
        return tuple(unique.values())

    @staticmethod
    def _successful_outcomes(
        documents: Sequence[tuple[ExaDocument, SourceOrigin, str | None, datetime]],
    ) -> list[SourceRetrievalOutcome]:
        return [
            SourceRetrievalOutcome(
                retrieval_id=f"retrieval-{_digest(document.url)}",
                directive_id=directive_id,
                source_id=f"source-{_digest(document.url)}",
                origin=origin,
                locator=document.url,
                status=RetrievalStatus.RETRIEVED,
                attempted_at=retrieved_at,
                retrieved_at=retrieved_at,
            )
            for document, origin, directive_id, retrieved_at in documents
        ]

    @staticmethod
    def _artifact(
        request: ResearchProviderRequest,
        documents: Sequence[tuple[ExaDocument, SourceOrigin, str | None, datetime]],
        created_at: datetime,
        readiness: EvidenceReadiness,
    ) -> NormalizedResearchArtifact:
        sources: list[NormalizedSource] = []
        evidence: list[ExtractedEvidence] = []
        for document, _origin, _directive_id, retrieved_at in documents:
            source_id = f"source-{_digest(document.url)}"
            sources.append(
                NormalizedSource(
                    source_id=source_id,
                    locator=SourceLocator(kind=SourceLocatorKind.URL, value=document.url),
                    title=document.title,
                    publisher=document.publisher,
                    publication_time=PublicationTime(
                        status=(
                            PublicationTimeStatus.KNOWN
                            if document.published_at is not None
                            else PublicationTimeStatus.UNKNOWN
                        ),
                        value=document.published_at,
                    ),
                    retrieved_at=retrieved_at,
                )
            )
            excerpt = " ".join(document.text.split())[:4000]
            evidence.append(
                ExtractedEvidence(
                    evidence_id=f"evidence-{_digest(document.url)}",
                    claim=excerpt,
                    source_ids=(source_id,),
                    support=(SupportReference(source_id=source_id, excerpt=excerpt),),
                    disposition=EvidenceDisposition.NOT_ASSESSED,
                )
            )
        return NormalizedResearchArtifact(
            artifact_id=f"research-{request.run_id}",
            run_id=request.run_id,
            assignment_id=request.assignment_id,
            signal_id=request.signal_id,
            configuration_identity=request.strategy.identity,
            created_at=created_at,
            sources=tuple(sources),
            evidence=tuple(evidence),
            readiness=readiness,
        )


def _research_query(request: ResearchProviderRequest, seed: str) -> str:
    audience = request.strategy.select_audience(None)
    territories = ", ".join(request.strategy.content.territories)
    proof = ", ".join(request.strategy.positioning.proof_points)
    claims = ", ".join(request.strategy.preferred_claims)
    restrictions = ", ".join(request.strategy.restrictions)
    return (
        f"{seed}. Audience: {audience.audience_name}. Problem: {audience.selected_problem}. "
        f"Positioning: {request.strategy.positioning.statement}. "
        f"Territories: {territories}. Evidence boundaries: {proof}. "
        f"Preferred claims: {claims}. Exclude unsupported claims: {restrictions}."
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


#: #211: the definition moved to `url_safety` so the direct-URL adapter can
#: share it instead of inventing a second one. Same function, same behaviour;
#: the local names are kept so nothing else in this module changes.
_domain = registrable_host


def _canonical_url(value: str) -> str:
    """Normalize only URL syntax that identifies the same network resource."""

    require_safe_url_authority(value)
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname:
        return value
    hostname = parsed.hostname.casefold().rstrip(".")
    host = f"[{hostname}]" if ":" in hostname else hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            f"{host}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def _unsafe_url_failure() -> ProviderFailure:
    return ProviderFailure(
        code=ProviderFailureCode.MALFORMED_RESPONSE,
        message="Research provider returned an unsafe source locator",
        retryable=False,
    )


_is_within_domain = is_within_domain


def _is_excluded(url_or_domain: str, exclusions: Sequence[str]) -> bool:
    candidate_url = _canonical_url(url_or_domain).rstrip("/")
    for blocked in exclusions:
        parsed = urlsplit(blocked)
        if parsed.scheme and parsed.path.rstrip("/"):
            if candidate_url == _canonical_url(blocked).rstrip("/"):
                return True
        else:
            if _is_within_domain(url_or_domain, blocked):
                return True
    return False


def _domain_exclusions(exclusions: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        _domain(item)
        for item in exclusions
        if not (urlsplit(item).scheme and urlsplit(item).path.rstrip("/"))
    )


def _failed_outcome(
    directive: SourceDirective, failure: ProviderFailure, attempted_at: datetime
) -> SourceRetrievalOutcome:
    return SourceRetrievalOutcome(
        retrieval_id=f"retrieval-{_digest(directive.directive_id)}",
        directive_id=directive.directive_id,
        source_id=None,
        origin=SourceOrigin.CLIENT_SUPPLIED,
        locator=directive.value,
        status=RetrievalStatus.FAILED,
        attempted_at=attempted_at,
        failure=failure,
    )


def _first_failure(outcomes: Sequence[SourceRetrievalOutcome]) -> ProviderFailure | None:
    return next((item.failure for item in outcomes if item.failure is not None), None)


def _normalize_error(error: ExaTransportError, *, source_level: bool) -> ProviderFailure:
    if isinstance(error, ExaTimeout):
        code, message, retryable = ProviderFailureCode.TIMEOUT, "Research provider timed out", True
    elif isinstance(error, ExaAuthenticationError):
        code, message, retryable = ProviderFailureCode.AUTHENTICATION, "Research provider authentication failed", False
    elif isinstance(error, ExaRateLimited):
        code, message, retryable = ProviderFailureCode.RATE_LIMITED, "Research provider rate limit reached", True
    elif isinstance(error, ExaMalformedResponse):
        code, message, retryable = ProviderFailureCode.MALFORMED_RESPONSE, "Research provider returned an invalid response", False
    elif isinstance(error, ExaUnavailable):
        code = ProviderFailureCode.SOURCE_RETRIEVAL_FAILED if source_level else ProviderFailureCode.UNAVAILABLE
        message, retryable = "Research source could not be retrieved", True
    else:  # pragma: no cover - defensive normalization for transport subclasses
        code, message, retryable = ProviderFailureCode.UNAVAILABLE, "Research provider is unavailable", True
    return ProviderFailure(
        code=code,
        message=message,
        retryable=retryable,
        retry_after_seconds=getattr(error, "retry_after_seconds", None),
    )
