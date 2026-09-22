"""Has this publication already happened? (Issue #105 / Story #18, NB-00b.)

Never Blank must not put the exact same accepted article on the same Wix site
twice merely because a run was retried. A retry deliberately creates a new
``run_id``, so run identity is not publication identity.

**The authority is the marker store** (NB-00b, invariant S3-I1). Every lookup
here asks :mod:`src.publishing.publication_markers` first — the committed,
per-destination store that survives a fresh checkout — and its answer is
final: a marker is a proven publication to reuse, an intent with no marker or
a store that cannot answer is a refusal the caller records as a ``SKIP``. The
identity key it decides on is ``(client, destination, sorted source signal
IDs)``, with no article digest, so one signal set is one publication per
destination however often the article is rewritten (Step 5 §1.1). The same
lookup therefore answers for all six destinations, not only the two that have
a run-directory evidence reader below.

The run-directory scan this module used to be is kept *behind* that authority.
It reads only ``packages_dir/<signal_id>/runs/*``, which a GitHub-hosted
runner's checkout does not have (Step 5 §1.1: ``find_prior_*`` finds nothing
in a fresh CI checkout), so it can still recognise a sequential retry inside
one working tree and it can never authorize a call. For Release 1 the Wix
publication it recognises is::

    (signal_id, source_article_digest, wix_site_id)

``configuration_identity`` stays mandatory provenance (#100/#101/#16) but is
deliberately **not** part of the duplicate key: using it would turn any
accepted configuration revision into an implicit republish channel.
``owner_member_id`` is author metadata, not a destination, so changing the
post owner on the same site cannot authorize a duplicate. A different
``site_id`` is a genuinely different destination and publishes independently.

Only a prior ``PUBLISHED`` result with a real Wix content ID suppresses a new
publication. ``DRAFT_CREATED`` does not: a draft is not proof the article is
live, and suppressing on one could leave it permanently unpublished. There is
no draft-resume behavior here.

**Ambiguity never manufactures idempotency.** Unusable prior evidence —
malformed artifacts, a pre-#101 run with no preflight verdict, a PUBLISHED
record with no content ID, internally inconsistent evidence — does not
suppress the current, already preflight-authorized publication. It is
reported as typed sanitized reason codes so the current run's evidence can
say that unusable prior evidence was encountered, without a corrupt
historical file being able to suppress publication forever.

**Concurrency**: the run-directory scan below provides deterministic
*sequential* retry idempotency only — two runs started concurrently can both
observe "no prior success" in it, because per-run create-once artifacts give
no mutual exclusion and the Wix Blog v3 calls this adapter makes expose no
provider-native idempotency key. Simultaneous runs are arbitrated by the
authority instead, whose claim is an exclusive create decided before any
external call (see :mod:`src.publishing.publication_markers` and
:mod:`src.publishing.shared_claim`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from src.artifacts import resolve_run_dir
from src.editorial.linkedin_composition import article_digest
from src.publishing.publication_markers import (
    AUTHORITY_UNAVAILABLE,
    DESTINATIONS,
    MarkerStore,
    PublicationGuard,
    refused_result,
)
from src.publishing.result import PublishStatus, UrlProvenance

#: Typed, sanitized reasons why a candidate could not be interpreted. Raw
#: artifact content never leaves this module.
UNUSABLE_MALFORMED_RESULTS = "malformed_publication_results"
UNUSABLE_MISSING_CONTENT_ID = "missing_content_id"
UNUSABLE_MISSING_PREFLIGHT = "missing_preflight_verdict"
UNUSABLE_INVALID_PREFLIGHT = "invalid_preflight_verdict"
UNUSABLE_INCONSISTENT = "inconsistent_prior_evidence"
UNUSABLE_ARTICLE_UNREADABLE = "prior_article_evidence_unreadable"
UNUSABLE_PROVENANCE_INVALID = "prior_run_provenance_invalid"
UNUSABLE_COMPOSITION_UNREADABLE = "prior_composition_evidence_unreadable"
UNUSABLE_URL_EVIDENCE_INVALID = "prior_url_evidence_invalid"


@dataclass(frozen=True)
class WixPublicationIdentity:
    """What makes two Wix publications the same publication."""

    signal_id: str
    source_article_digest: str
    wix_site_id: str

    @classmethod
    def from_package(cls, package) -> "WixPublicationIdentity":
        return cls(
            signal_id=package.signal_id,
            source_article_digest=package.source_article_digest,
            wix_site_id=package.target.site_id,
        )


@dataclass(frozen=True)
class LinkedInPublicationIdentity:
    """What makes two LinkedIn publications the same publication (Issue #109).

    The middle component is the accepted **LinkedIn body**, not the article:
    a different composition of the same article is a different publication
    payload and a genuinely different post. ``run_id`` and
    ``configuration_identity`` are excluded for the same reasons as Wix.
    """

    signal_id: str
    accepted_linkedin_body_digest: str
    linkedin_account_id: str

    @classmethod
    def from_package(cls, package) -> "LinkedInPublicationIdentity":
        return cls(
            signal_id=package.signal_id,
            accepted_linkedin_body_digest=article_digest(package.linkedin_body),
            linkedin_account_id=package.target.account_id,
        )


@dataclass(frozen=True)
class PriorPublication:
    """A proven earlier publication of this identity to this destination.

    One shape for all six destinations (NB-00b), because what a ``REUSED``
    result needs is the same everywhere: which run published it, the
    provider's own ID for the publication, and the URL with the provenance it
    was established by.
    """

    destination: str
    run_id: str
    post_id: str
    url: str
    url_provenance: UrlProvenance


@dataclass(frozen=True)
class PriorEvidenceScan:
    """Outcome of looking for a proven prior publication."""

    match: Optional[PriorPublication] = None
    unusable_reasons: tuple[str, ...] = ()
    #: Set when the authority refused the call instead of proving a
    #: publication: an intent with no marker (``publication_possibly_exists``)
    #: or a store that could not answer (``idempotency_authority_unavailable``).
    #: The caller records a ``SKIP`` carrying this reason and publishes
    #: nothing — at most once, and never a wait (§3.6 rules 2 and 6).
    refusal: Optional[str] = None

    @property
    def unusable_count(self) -> int:
        return len(self.unusable_reasons)

    def evidence_note(self) -> Optional[dict]:
        """Sanitized record for the current run's publication evidence."""

        if not self.unusable_reasons:
            return None
        return {
            "count": self.unusable_count,
            "reasons": sorted(set(self.unusable_reasons)),
        }


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _candidate_provenance_is_canonical(
    packages_dir: Path, signal_id: str, run_id: str
) -> bool:
    """Prove the candidate run is itself a valid canonical chain.

    Duplicate suppression is an authorization-affecting decision, so a prior
    publication may only suppress a new one when that prior run is internally
    honest: its own identity, configuration, source/generation relationships
    and artifact lineage must hold together. That is exactly what the Story
    #16 verifier already proves, so it is reused rather than reimplemented —
    and the candidate must have reached the publication-results stage, since
    a run that never got there cannot evidence a publication.

    Note the deliberate distinction: this asks *is the old run internally
    honest*, never *does its configuration equal the current run's*. The
    latter is not part of the duplicate key.
    """

    from src.artifacts.provenance import ProvenanceError, verify_run_provenance

    try:
        report = verify_run_provenance(packages_dir, signal_id, run_id)
    except (ProvenanceError, FileNotFoundError, ValueError, OSError):
        # Raw verifier text never reaches persisted evidence — only the
        # typed reason code recorded by the caller.
        return False
    return "publication_results" in report.verified_artifacts


def _validated_prior_target(
    run_dir: Path,
    *,
    channel_name: str = "wix",
    signal_id: str,
    configuration_identity: dict,
):
    """Read the candidate's destination from a verdict proven to be its own.

    Story #16 verification covers the generation/publication chain but not the
    Story #17 preflight artifact, so a structurally valid verdict from another
    run — or one whose target was relabelled — could otherwise pass off a
    publication to site B as a publication to site A. Strict-loading the
    schema is therefore not enough: the verdict must also *belong* to this
    candidate.

    Returns ``(target, unusable_reason)``.
    """

    from src.publishing.preflight import PreflightDisposition, PreflightResult

    path = run_dir / "preflight_result.json"
    if not path.exists():
        return None, UNUSABLE_MISSING_PREFLIGHT
    try:
        verdict = PreflightResult.model_validate_json(path.read_bytes())
    except Exception:  # noqa: BLE001 — unparseable verdict is unusable evidence
        return None, UNUSABLE_INVALID_PREFLIGHT

    # …belongs to this run directory, this signal, and this run's authoritative
    # configuration (which Story #16 already proved consistent with the chain).
    if verdict.run_id != run_dir.name:
        return None, UNUSABLE_INCONSISTENT
    if verdict.signal_id != signal_id:
        return None, UNUSABLE_INCONSISTENT
    try:
        if verdict.configuration_identity.model_dump() != dict(configuration_identity):
            return None, UNUSABLE_INCONSISTENT
    except (TypeError, ValueError):
        return None, UNUSABLE_INCONSISTENT

    channel = verdict.verdict_for(channel_name)
    if channel is None or channel.target is None:
        return None, UNUSABLE_INVALID_PREFLIGHT
    if channel.disposition is not PreflightDisposition.ALLOW:
        return None, UNUSABLE_INCONSISTENT
    # The target must actually identify a destination for this channel.
    destination = (
        getattr(channel.target, "site_id", None)
        if channel_name == "wix"
        else getattr(channel.target, "account_id", None)
    )
    if not destination:
        return None, UNUSABLE_INVALID_PREFLIGHT
    return channel, None


def _authorized_package_digest_matches(
    packages_dir: Path,
    run_dir: Path,
    *,
    signal_id: str,
    generation_run_id: str,
    configuration_identity: dict,
    channel,
    channel_name: str = "wix",
) -> bool:
    """Rebuild the candidate's canonical package and compare its digest.

    The strongest binding available from persisted evidence: the accepted
    article (generation run), the run's own visual passport, its authoritative
    configuration and the verdict's target are enough to reconstruct the exact
    #100 package the verdict claims to have authorized. A relabelled target
    changes that digest, so a verdict whose recorded ``package_digest`` no
    longer matches its own contents cannot be the one that authorized this
    publication.

    Reuses the #100 builder — no second package system — and answers ``False``
    whenever the reconstruction cannot be performed, so uncertainty never
    suppresses a publication.
    """

    from src.artifacts import load_run_generated
    from src.publishing.package import (
        build_linkedin_publication_package,
        build_wix_publication_package,
    )
    from src.strategy.execution_context import ConfigurationIdentity
    from src.visual.contract import VisualAssetsRecord

    if channel.package_digest is None:
        return False
    try:
        generated = load_run_generated(packages_dir, signal_id, generation_run_id)
        visual = VisualAssetsRecord.model_validate_json(
            (run_dir / "visual_assets.json").read_bytes()
        )
        identity = ConfigurationIdentity.model_validate(configuration_identity)
        if channel_name == "wix":
            package = build_wix_publication_package(
                run_id=run_dir.name,
                signal_id=signal_id,
                configuration_identity=identity,
                generated=generated,
                visual_record=visual,
                target=channel.target,
            )
        else:
            # The accepted composition lives at the generation run — a reuse
            # publication run never writes one of its own.
            composition = _load_json(
                resolve_run_dir(packages_dir, signal_id, generation_run_id)
                / "linkedin_composition.json"
            )
            if composition is None:
                return False
            package = build_linkedin_publication_package(
                run_id=run_dir.name,
                signal_id=signal_id,
                configuration_identity=identity,
                generated=generated,
                linkedin_composition=composition,
                visual_record=visual,
                target=channel.target,
            )
    except Exception:  # noqa: BLE001 — unreconstructable evidence never suppresses
        return False
    return package.package_digest() == channel.package_digest


#: Public names for the two channel-verdict checks the Story #20 run report
#: reuses (Issue #112). They are the same functions the Wix and LinkedIn scans
#: already use — exposed rather than duplicated, so a report and a suppression
#: decision can never disagree about what "the verdict authorized this package"
#: means. Behavior is unchanged.
validated_channel_verdict = _validated_prior_target
authorized_package_digest_matches = _authorized_package_digest_matches


def _prior_article_digest(
    packages_dir: Path, signal_id: str, generation_run_id: str
) -> tuple[Optional[str], Optional[str]]:
    """Derive the candidate's accepted-article identity from canonical evidence.

    Uses the Story #16 relationship — the generation run's ``generated.json``
    is the accepted article — instead of trusting a field copied into the
    publication record.
    """

    from src.artifacts import load_run_generated

    if not generation_run_id:
        return None, UNUSABLE_INCONSISTENT
    try:
        generated = load_run_generated(packages_dir, signal_id, generation_run_id)
    except (FileNotFoundError, ValueError, OSError):
        return None, UNUSABLE_ARTICLE_UNREADABLE
    body = generated.get("blog_article")
    if not isinstance(body, str) or not body.strip():
        return None, UNUSABLE_ARTICLE_UNREADABLE
    return article_digest(body), None


def _prior_linkedin_body_digest(
    packages_dir: Path, signal_id: str, generation_run_id: str
) -> tuple[Optional[str], Optional[str]]:
    """Derive the candidate's accepted LinkedIn body identity (Issue #109).

    The accepted body is read from the canonical composition record at the
    **generation** run: a ``--from-package`` publication run never writes its
    own composition, so resolving through ``generation_run_id`` is what keeps
    a legitimate reuse candidate visible instead of silently unmatchable.

    Returns ``(digest, unusable_reason)``.
    """

    from src.editorial.linkedin_composition import LinkedInCompositionRecord

    if not generation_run_id:
        return None, UNUSABLE_INCONSISTENT
    try:
        run_dir = resolve_run_dir(Path(packages_dir), signal_id, generation_run_id)
    except Exception:  # noqa: BLE001 — an unusable address is unusable evidence
        return None, UNUSABLE_COMPOSITION_UNREADABLE
    data = _load_json(run_dir / "linkedin_composition.json")
    if data is None:
        return None, UNUSABLE_COMPOSITION_UNREADABLE
    try:
        record = LinkedInCompositionRecord.model_validate(data)
    except Exception:  # noqa: BLE001 — malformed composition proves nothing
        return None, UNUSABLE_COMPOSITION_UNREADABLE
    return article_digest(record.linkedin_body), None


def _validated_reuse_url(entry: dict) -> tuple[Optional[str], object, Optional[str]]:
    """Validate the prior result's URL evidence before it can be reused.

    ``REUSED`` preserves the prior URL and provenance *exactly*, so evidence
    that cannot be read exactly is not reusable. Silently coercing a malformed
    provenance to ``unavailable`` or a non-string URL to ``""`` would turn
    corrupted history into a suppression decision — precisely what the
    accepted ambiguity policy forbids.

    Two shapes are legitimate for LinkedIn (Issue #108): a provider-confirmed
    URL, or an explicitly unavailable one — a real publication ID with no URL
    is still proven evidence, since URL availability is not part of the
    duplicate identity. LinkedIn has no legitimate ``locally_derived`` form,
    so a record claiming one is inconsistent evidence.

    Returns ``(url, provenance, unusable_reason)``.
    """

    raw_url = entry.get("url")
    if raw_url is not None and not isinstance(raw_url, str):
        return None, None, UNUSABLE_URL_EVIDENCE_INVALID
    try:
        provenance = UrlProvenance(entry.get("url_provenance"))
    except ValueError:
        # missing, misspelled or foreign value — never normalized into a match
        return None, None, UNUSABLE_URL_EVIDENCE_INVALID

    url = raw_url or ""
    if provenance is UrlProvenance.PROVIDER_CONFIRMED and not url:
        # claims the provider returned a URL while carrying none
        return None, None, UNUSABLE_URL_EVIDENCE_INVALID
    if provenance is UrlProvenance.UNAVAILABLE and url:
        # claims no provenance-confirmed URL while carrying one
        return None, None, UNUSABLE_URL_EVIDENCE_INVALID
    if provenance is UrlProvenance.LOCALLY_DERIVED:
        # no legitimate LinkedIn construction exists (Issue #108)
        return None, None, UNUSABLE_URL_EVIDENCE_INVALID
    return url, provenance, None


def _scan_runs_for_linkedin(
    packages_dir: Path,
    identity: LinkedInPublicationIdentity,
    *,
    current_run_id: str,
) -> PriorEvidenceScan:
    """Look in this checkout's run directories for the same LinkedIn post.

    The same acceptance discipline the Wix scan established (Issue #105):
    only a literal ``PUBLISHED`` result with a real provider publication ID
    counts, the candidate run must itself verify as a canonical chain, its
    Story #17 verdict must be proven to be its own, and the exact authorized
    package must reconstruct to the digest that verdict recorded. Anything
    that merely differs — another account, another accepted body, a
    non-published status — is a plain non-match, never "unusable evidence".

    ``PROVIDER_DUPLICATE`` never suppresses: a 409 proves a duplicate exists
    but never which post, so it is not evidence of a publication (Issue #108).

    Subordinate to the marker authority since NB-00b, and reached only when
    the authority has said nothing was published. Its identity carries the
    composed LinkedIn body, which the canonical entrypoint has already
    enriched with the published article's link by the time it looks — see
    ``docs/PUBLICATION_MARKER_LOOKUP.md`` for the tested result.
    """

    runs_dir = Path(packages_dir) / identity.signal_id / "runs"
    if not runs_dir.is_dir():
        return PriorEvidenceScan()

    unusable: list[str] = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if run_dir.name == current_run_id:
            continue
        results_path = run_dir / "publication_results.json"
        if not results_path.exists():
            continue                      # run never reached publication
        data = _load_json(results_path)
        if data is None:
            unusable.append(UNUSABLE_MALFORMED_RESULTS)
            continue
        if data.get("signal_id") != identity.signal_id:
            unusable.append(UNUSABLE_INCONSISTENT)
            continue
        entry = (data.get("results") or {}).get("linkedin")
        if not isinstance(entry, dict):
            continue                      # this run published no LinkedIn channel
        if entry.get("status") != "PUBLISHED":
            # failed / blocked / skipped / reused / provider-duplicate: none of
            # them prove a live post exists.
            continue
        post_id = entry.get("external_id") or ""
        if not isinstance(post_id, str) or not post_id.strip():
            unusable.append(UNUSABLE_MISSING_CONTENT_ID)
            continue

        if not _candidate_provenance_is_canonical(
            Path(packages_dir), identity.signal_id, run_dir.name
        ):
            unusable.append(UNUSABLE_PROVENANCE_INVALID)
            continue

        channel, reason = _validated_prior_target(
            run_dir,
            channel_name="linkedin",
            signal_id=identity.signal_id,
            configuration_identity=data.get("configuration_identity") or {},
        )
        if reason is not None:
            unusable.append(reason)
            continue
        generation_run_id = data.get("generation_run_id") or ""
        if not _authorized_package_digest_matches(
            Path(packages_dir),
            run_dir,
            signal_id=identity.signal_id,
            generation_run_id=generation_run_id,
            configuration_identity=data.get("configuration_identity") or {},
            channel=channel,
            channel_name="linkedin",
        ):
            unusable.append(UNUSABLE_INCONSISTENT)
            continue
        if channel.target.account_id != identity.linkedin_account_id:
            continue                      # a different destination account

        digest, reason = _prior_linkedin_body_digest(
            Path(packages_dir), identity.signal_id, generation_run_id
        )
        if reason is not None:
            unusable.append(reason)
            continue
        if digest != identity.accepted_linkedin_body_digest:
            continue                      # a different accepted LinkedIn body

        url, provenance, reason = _validated_reuse_url(entry)
        if reason is not None:
            unusable.append(reason)
            continue
        return PriorEvidenceScan(
            match=PriorPublication(
                destination="linkedin",
                run_id=str(data.get("run_id") or run_dir.name),
                post_id=post_id,
                url=url,
                url_provenance=provenance,
            ),
            unusable_reasons=tuple(unusable),
        )

    return PriorEvidenceScan(unusable_reasons=tuple(unusable))


def _scan_runs_for_wix(
    packages_dir: Path,
    identity: WixPublicationIdentity,
    *,
    current_run_id: str,
) -> PriorEvidenceScan:
    """Look in this checkout's run directories for the same Wix publication.

    Returns the first proven match plus the typed reasons for any candidate
    whose evidence could not be interpreted. A candidate that is simply
    *different* — another site, another article, a non-``PUBLISHED`` status —
    is a plain non-match and is never reported as unusable evidence.

    Subordinate to the marker authority since NB-00b, and reached only when
    the authority has said nothing was published.
    """

    runs_dir = Path(packages_dir) / identity.signal_id / "runs"
    if not runs_dir.is_dir():
        return PriorEvidenceScan()

    unusable: list[str] = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if run_dir.name == current_run_id:
            continue
        results_path = run_dir / "publication_results.json"
        if not results_path.exists():
            continue                      # run never reached publication
        data = _load_json(results_path)
        if data is None:
            unusable.append(UNUSABLE_MALFORMED_RESULTS)
            continue
        if data.get("signal_id") != identity.signal_id:
            unusable.append(UNUSABLE_INCONSISTENT)
            continue
        entry = (data.get("results") or {}).get("wix")
        if not isinstance(entry, dict):
            continue                      # this run published no Wix channel
        if entry.get("status") != "PUBLISHED":
            continue                      # draft/failed/blocked/skipped/reused
        post_id = entry.get("external_id") or ""
        if not isinstance(post_id, str) or not post_id.strip():
            # A publication claimed without its authoritative content ID
            # cannot prove anything.
            unusable.append(UNUSABLE_MISSING_CONTENT_ID)
            continue

        # The candidate must be a proven canonical chain in its own right,
        # verified by Story #16 — a syntactically plausible but internally
        # contradictory run can never manufacture a reuse match.
        if not _candidate_provenance_is_canonical(
            Path(packages_dir), identity.signal_id, run_dir.name
        ):
            unusable.append(UNUSABLE_PROVENANCE_INVALID)
            continue

        # Story #16 does not cover the Story #17 verdict, so the target
        # evidence must be proven to belong to this candidate before it can
        # decide where the prior publication went.
        channel, reason = _validated_prior_target(
            run_dir,
            signal_id=identity.signal_id,
            configuration_identity=data.get("configuration_identity") or {},
        )
        if reason is not None:
            unusable.append(reason)
            continue
        if not _authorized_package_digest_matches(
            Path(packages_dir),
            run_dir,
            signal_id=identity.signal_id,
            generation_run_id=data.get("generation_run_id") or "",
            configuration_identity=data.get("configuration_identity") or {},
            channel=channel,
        ):
            unusable.append(UNUSABLE_INCONSISTENT)
            continue
        if channel.target.site_id != identity.wix_site_id:
            continue                      # a different destination entirely

        digest, reason = _prior_article_digest(
            Path(packages_dir), identity.signal_id, data.get("generation_run_id") or ""
        )
        if reason is not None:
            unusable.append(reason)
            continue
        if digest != identity.source_article_digest:
            continue                      # a different accepted article

        url = entry.get("url") or ""
        raw_provenance = entry.get("url_provenance")
        try:
            provenance = UrlProvenance(raw_provenance)
        except ValueError:
            # Recorded before Issue #105: the URL's origin cannot be
            # established, so it is never promoted to provider-confirmed.
            provenance = UrlProvenance.UNAVAILABLE
        return PriorEvidenceScan(
            match=PriorPublication(
                destination="wix",
                run_id=str(data.get("run_id") or run_dir.name),
                post_id=post_id,
                url=url if isinstance(url, str) else "",
                url_provenance=provenance,
            ),
            unusable_reasons=tuple(unusable),
        )

    return PriorEvidenceScan(unusable_reasons=tuple(unusable))


# ── The authority: one marker-backed lookup for all six destinations ─────────


def find_prior_publication(
    destination: str,
    *,
    source_signal_ids: Iterable[str],
    client: Optional[str] = None,
    store: Optional[MarkerStore] = None,
) -> PriorEvidenceScan:
    """Ask the marker authority whether this publication already happened.

    The durable, committed store is what S-14 must consult before any
    irreversible call (§3.6 rule 2), and it is keyed by ``(client,
    destination, sorted source signal IDs)`` — so this one lookup answers for
    every destination, including the four that never had a run-directory
    evidence reader of their own.

    Exactly three answers, and no fourth:

    - a marker — the publication exists, and the match is the evidence a
      ``REUSED`` result is built from;
    - a ``refusal`` — an intent with no marker means *possibly published*, and
      a store that cannot answer means the authority is unavailable. Both are
      a ``SKIP``, fail-closed, at most once, never a wait (rule 6);
    - nothing — this publication has never been attempted.

    The marker is converted through the authority's own ``refused_result``, so
    a lookup here and a guard check inside a publishing path can never
    disagree about what a marker means.
    """

    guard = PublicationGuard(
        source_signal_ids=source_signal_ids,
        # Lookup only: nothing here records an intent or a marker, so there is
        # no run for this guard to attribute one to.
        run_id="",
        client=client,
        store=store,
    )
    decision = guard.check(destination)
    if decision.proceed:
        return PriorEvidenceScan()
    reused = refused_result(decision)
    if reused.status is PublishStatus.REUSED:
        return PriorEvidenceScan(
            match=PriorPublication(
                destination=decision.destination,
                run_id=reused.reused_from_run_id or "",
                post_id=reused.external_id or "",
                url=reused.url or "",
                url_provenance=reused.url_provenance,
            )
        )
    return PriorEvidenceScan(refusal=reused.error_message or AUTHORITY_UNAVAILABLE)


@dataclass(frozen=True)
class SignalPublicationState:
    """What the authority knows about one signal set, across all destinations."""

    published: tuple[str, ...] = ()
    possibly_published: tuple[str, ...] = ()
    #: The store could not answer at all. Never read as "nothing was
    #: published": that confusion is exactly what turns a fresh checkout into
    #: a second publication.
    unavailable: bool = False

    @property
    def consumed(self) -> bool:
        """Has this signal already been spent — or possibly been spent?"""

        return bool(self.published or self.possibly_published)

    def as_audit_dict(self) -> dict:
        """Sanitized record for a selection audit. No path ever appears here."""

        return {
            "published": list(self.published),
            "possibly_published": list(self.possibly_published),
            "unavailable": self.unavailable,
        }


def signal_publication_state(
    source_signal_ids: Iterable[str],
    *,
    client: Optional[str] = None,
    store: Optional[MarkerStore] = None,
) -> SignalPublicationState:
    """Ask the authority about one signal set at every destination (NB-00b).

    Selection reads this beside ``data/research/published_signal_ids.txt``.
    That file is a signal-level summary committed only when a whole job
    succeeded, so a run that published Wix and then failed LinkedIn leaves it
    untouched and the signal still looks unused — the partial-success hole in
    Step 5 §1.1. A marker for any destination proves otherwise, and an intent
    without one proves it may.

    A store that cannot answer stops the question rather than answering it:
    the state is ``unavailable`` and the caller must select nothing.
    """

    ids = tuple(source_signal_ids)
    store = store if store is not None else MarkerStore()
    published: list[str] = []
    possibly: list[str] = []
    for destination in DESTINATIONS:
        scan = find_prior_publication(
            destination, source_signal_ids=ids, client=client, store=store
        )
        if scan.refusal == AUTHORITY_UNAVAILABLE:
            return SignalPublicationState(unavailable=True)
        if scan.match is not None:
            published.append(destination)
        elif scan.refusal is not None:
            possibly.append(destination)
    return SignalPublicationState(tuple(published), tuple(possibly))


def find_prior_wix_publication(
    packages_dir: Path,
    identity: WixPublicationIdentity,
    *,
    current_run_id: str,
    store: Optional[MarkerStore] = None,
) -> PriorEvidenceScan:
    """Has this Wix publication already happened? (Authority first, NB-00b.)

    The marker store decides. Its key ignores the article digest this
    identity carries, which is deliberate and stricter: one signal set is one
    Wix publication however often the article is rewritten (Step 5 §1.1).
    Only when the authority has proven nothing was published is this
    checkout's run-directory evidence read, which can still recognise a
    sequential retry in a working tree that holds the earlier run.
    """

    authority = find_prior_publication(
        "wix", source_signal_ids=(identity.signal_id,), store=store
    )
    if authority.match is not None or authority.refusal is not None:
        return authority
    return _scan_runs_for_wix(
        packages_dir, identity, current_run_id=current_run_id
    )


def find_prior_linkedin_publication(
    packages_dir: Path,
    identity: LinkedInPublicationIdentity,
    *,
    current_run_id: str,
    store: Optional[MarkerStore] = None,
) -> PriorEvidenceScan:
    """Has this LinkedIn publication already happened? (Authority first.)

    The same rebuild as the Wix lookup, and it matters more here: the marker
    key does not contain the accepted body digest, so binding the published
    article's link into the package before the lookup — which the canonical
    entrypoint does — can no longer move the identity out from under the
    prior evidence (Step 5 §1.1, tested in ``tests/test_288_marker_lookup.py``
    and recorded in ``docs/PUBLICATION_MARKER_LOOKUP.md``).
    """

    authority = find_prior_publication(
        "linkedin", source_signal_ids=(identity.signal_id,), store=store
    )
    if authority.match is not None or authority.refusal is not None:
        return authority
    return _scan_runs_for_linkedin(
        packages_dir, identity, current_run_id=current_run_id
    )
