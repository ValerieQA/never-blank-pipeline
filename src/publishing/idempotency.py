"""Wix publication idempotency (Issue #105 / Story #18).

Never Blank must not put the exact same accepted article on the same Wix site
twice merely because a run was retried. A retry deliberately creates a new
``run_id``, so run identity is not publication identity. For Release 1 the
same Wix publication is::

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

**Concurrency**: this provides deterministic *sequential* retry idempotency
only. Two runs started concurrently can both observe "no prior success" and
both publish; per-run create-once artifacts give no mutual exclusion, and the
Wix Blog v3 calls this adapter makes expose no provider-native idempotency
key. That limitation is deliberate and documented, not solved.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.editorial.linkedin_composition import article_digest
from src.publishing.result import UrlProvenance

#: Typed, sanitized reasons why a candidate could not be interpreted. Raw
#: artifact content never leaves this module.
UNUSABLE_MALFORMED_RESULTS = "malformed_publication_results"
UNUSABLE_MISSING_CONTENT_ID = "missing_content_id"
UNUSABLE_MISSING_PREFLIGHT = "missing_preflight_verdict"
UNUSABLE_INVALID_PREFLIGHT = "invalid_preflight_verdict"
UNUSABLE_INCONSISTENT = "inconsistent_prior_evidence"
UNUSABLE_ARTICLE_UNREADABLE = "prior_article_evidence_unreadable"
UNUSABLE_PROVENANCE_INVALID = "prior_run_provenance_invalid"


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
class PriorWixPublication:
    """A proven earlier publication of the exact same article to the same site."""

    run_id: str
    post_id: str
    url: str
    url_provenance: UrlProvenance


@dataclass(frozen=True)
class PriorEvidenceScan:
    """Outcome of looking for a proven prior publication."""

    match: Optional[PriorWixPublication] = None
    unusable_reasons: tuple[str, ...] = ()

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


def _prior_site_id(run_dir: Path) -> tuple[Optional[str], Optional[str]]:
    """Read the candidate's own preflight verdict for its Wix destination.

    Returns ``(site_id, unusable_reason)``. The verdict is strict-validated
    rather than string-scanned, and its Wix channel must actually have been
    allowed to publish — a run whose preflight blocked Wix while its results
    claim a publication is internally inconsistent evidence.
    """

    from src.publishing.preflight import PreflightDisposition, PreflightResult

    path = run_dir / "preflight_result.json"
    if not path.exists():
        return None, UNUSABLE_MISSING_PREFLIGHT
    try:
        verdict = PreflightResult.model_validate_json(path.read_bytes())
    except Exception:  # noqa: BLE001 — unparseable verdict is unusable evidence
        return None, UNUSABLE_INVALID_PREFLIGHT
    channel = verdict.verdict_for("wix")
    if channel is None or channel.target is None:
        return None, UNUSABLE_INVALID_PREFLIGHT
    if channel.disposition is not PreflightDisposition.ALLOW:
        return None, UNUSABLE_INCONSISTENT
    site_id = getattr(channel.target, "site_id", None)
    if not site_id:
        return None, UNUSABLE_INVALID_PREFLIGHT
    return site_id, None


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


def find_prior_wix_publication(
    packages_dir: Path,
    identity: WixPublicationIdentity,
    *,
    current_run_id: str,
) -> PriorEvidenceScan:
    """Look for a proven earlier publication of this exact Wix publication.

    Returns the first proven match plus the typed reasons for any candidate
    whose evidence could not be interpreted. A candidate that is simply
    *different* — another site, another article, a non-``PUBLISHED`` status —
    is a plain non-match and is never reported as unusable evidence.
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

        site_id, reason = _prior_site_id(run_dir)
        if reason is not None:
            unusable.append(reason)
            continue
        if site_id != identity.wix_site_id:
            continue                      # a different destination entirely

        # The candidate must be a proven canonical chain in its own right,
        # verified by Story #16 — a syntactically plausible but internally
        # contradictory run can never manufacture a reuse match.
        if not _candidate_provenance_is_canonical(
            Path(packages_dir), identity.signal_id, run_dir.name
        ):
            unusable.append(UNUSABLE_PROVENANCE_INVALID)
            continue

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
            match=PriorWixPublication(
                run_id=str(data.get("run_id") or run_dir.name),
                post_id=post_id,
                url=url if isinstance(url, str) else "",
                url_provenance=provenance,
            ),
            unusable_reasons=tuple(unusable),
        )

    return PriorEvidenceScan(unusable_reasons=tuple(unusable))
