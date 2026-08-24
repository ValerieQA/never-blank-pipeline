from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PublishStatus(str, Enum):
    PUBLISHED     = "PUBLISHED"
    DRAFT_CREATED = "DRAFT_CREATED"
    FAILED        = "FAILED"
    SKIPPED       = "SKIPPED"
    # Issue #105: this run created no draft or post and performed no provider
    # publication — an earlier canonical PUBLISHED result proved the exact
    # publication already exists, so the prior evidence is reused. Never a
    # fresh provider success for the current run.
    REUSED        = "REUSED"
    # Issue #108: the provider reported the content as a duplicate (Zernio 409).
    # That proves *a* duplicate exists but never *which post*, so it is neither
    # a proven publication nor a proven reuse: the channel is deliberately
    # neither successful nor complete, and it can never suppress a later run.
    PROVIDER_DUPLICATE = "PROVIDER_DUPLICATE"


class UrlProvenance(str, Enum):
    """Where a publication URL actually came from (Issue #105).

    A locally constructed URL is useful but must never be presented as
    confirmed by the provider.
    """

    #: the publish response itself carried the public URL
    PROVIDER_CONFIRMED = "provider_confirmed"
    #: retrieved from the provider afterwards, by post ID, through the
    #: provider's own URL field (Issue #200)
    PROVIDER_LOOKUP = "provider_lookup"
    #: the provider confirmed the post and returned a slug, but no URL, so a
    #: route was constructed locally. Issue #200 proved such a URL can be
    #: wrong and unreachable while looking entirely plausible: it is kept as
    #: recorded evidence and can NEVER be canonical for distribution.
    LOCALLY_DERIVED = "locally_derived"
    #: no provenance-confirmed URL exists (none returned, or its origin
    #: cannot be established — e.g. reused evidence recorded before #105)
    UNAVAILABLE = "unavailable"

    def is_provider_sourced(self) -> bool:
        """Did the provider itself produce this URL? (Issue #200)

        Only a provider-sourced URL may become the canonical article URL —
        and only after verification. A locally constructed route is a
        guess about site configuration, and live run 32740322282 published
        a social post pointing at a guess that returned 404.
        """
        return self in (
            UrlProvenance.PROVIDER_CONFIRMED,
            UrlProvenance.PROVIDER_LOOKUP,
        )


@dataclass
class PublishResult:
    platform:           str
    status:             PublishStatus
    url:                Optional[str] = None
    external_id:        Optional[str] = None
    error_message:      Optional[str] = None
    raw_response_path:  Optional[str] = None
    # Run identity — injected by the canonical entry point after publish.
    # Default "" for backward compat with publisher unit tests.
    run_id:             str = ""
    # Issue #105: truthful URL origin, and — for REUSED only — the earlier run
    # whose proven publication this result reports instead of creating a
    # duplicate. Defaults keep every existing caller unchanged.
    url_provenance:     UrlProvenance = UrlProvenance.UNAVAILABLE
    reused_from_run_id: Optional[str] = None
    #: Issue #200: the slug the PROVIDER reports for this post. Used to prove
    #: a candidate URL points at THIS post rather than at some other page
    #: that merely answers. Never derived locally from the title — deriving
    #: it here would re-introduce the assumption #200 exists to remove.
    provider_slug:      Optional[str] = None

    def ok(self) -> bool:
        return self.status in (PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED)

    def completed(self) -> bool:
        """Did this channel end in a state that is not a failure?

        ``REUSED`` is a completed channel — the article is live from the
        earlier publication — but it is deliberately not ``ok()``, so it never
        counts as a fresh provider success.
        """
        return self.ok() or self.status is PublishStatus.REUSED

    def to_dict(self) -> dict:
        return {
            "platform":          self.platform,
            "status":            self.status.value,
            "url":               self.url,
            "external_id":       self.external_id,
            "error_message":     self.error_message,
            "raw_response_path": self.raw_response_path,
            "run_id":            self.run_id,
            "url_provenance":    self.url_provenance.value,
            "reused_from_run_id": self.reused_from_run_id,
        }
