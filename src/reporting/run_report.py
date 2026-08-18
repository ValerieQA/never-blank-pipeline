"""Authoritative per-run report (Issue #112 / Story #20).

Every terminal Release 1 run gets one persisted record answering: what
happened, where the run ended, whether it completed, what happened
independently in Wix and LinkedIn, and which canonical evidence proves that
account.

The report is an **index of canonical evidence, not a second evidence
store**. It references the run's artifacts by their canonical filename inside
the run namespace — plus the identities and digests those contracts already
provide — and never copies research, decision, article, composition, visual,
preflight or publication payloads. No universal artifact IDs, no manifest
platform, no second provenance engine.

Two invariants shape the design:

* **Partial terminal runs are legitimate.** A run that stops at research,
  Decision Lens, editorial acceptance, the visual gate or preflight is a
  truthful terminal outcome, not corruption. The report states the last
  proven lifecycle stage and never fabricates absent downstream artifacts.
* **Corrupt evidence yields no report.** Story #16's verifier — with its
  existing stopped-run ladder semantics — decides whether the chain is
  internally consistent. An internally contradictory run produces no
  authoritative-looking report at all.

The existence of a report never means success: `completed` is derived from
canonical terminal evidence, and channel outcomes keep their accepted
meanings (`PUBLISHED`, `REUSED`, `PROVIDER_DUPLICATE`, `BLOCKED`, `FAILED`)
rather than collapsing into one flag.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.strategy.execution_context import ConfigurationIdentity

RUN_REPORT_SCHEMA_VERSION = "1.0"

#: Canonical artifacts a run may hold, in lifecycle order. The report
#: references these by name; it never reproduces their contents.
CANONICAL_ARTIFACTS = (
    "assignment.json",
    "business_strategy.json",
    "research.json",
    "decision.json",
    "editorial_acceptance.json",
    "generated.json",
    "linkedin_composition.json",
    "visual_assets.json",
    "preflight_result.json",
    "publication_results.json",
)


class RunReportError(Exception):
    """An authoritative report could not be built from the run's evidence."""


class TerminalStage(str, Enum):
    """The last lifecycle stage the run actually reached."""

    INTAKE = "intake"
    READINESS = "readiness"
    RESEARCH = "research"
    DECISION = "decision"
    SOURCE_PACKAGE = "source_package"
    GENERATION = "generation"
    EDITORIAL = "editorial"
    LINKEDIN_COMPOSITION = "linkedin_composition"
    VISUAL = "visual"
    VALIDATION = "validation"
    PACKAGING = "packaging"
    PREFLIGHT = "preflight"
    DRY_RUN = "dry_run"
    PUBLICATION = "publication"


class TerminalDisposition(str, Enum):
    """Why the run ended where it did."""

    COMPLETED = "completed"     # the run did everything it set out to do
    STOPPED = "stopped"         # a business decision ended it (e.g. non-PROCEED)
    BLOCKED = "blocked"         # a gate refused to let it continue
    FAILED = "failed"           # something went wrong


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactReference(_ReportModel):
    """A pointer to canonical evidence — never a copy of it."""

    name: str = Field(min_length=1, max_length=80)
    #: identity the artifact's own contract already provides, when one exists
    digest: Optional[str] = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def _canonical(cls, value: str) -> str:
        if value not in CANONICAL_ARTIFACTS:
            raise ValueError(f"unknown canonical artifact: {value!r}")
        return value


class ChannelReport(_ReportModel):
    """One channel's outcome, kept independent of the other's."""

    channel: str = Field(min_length=1, max_length=40)
    #: the accepted publication status, preserved verbatim
    status: str = Field(min_length=1, max_length=40)
    external_id: Optional[str] = Field(default=None, max_length=200)
    url: Optional[str] = Field(default=None, max_length=2000)
    url_provenance: Optional[str] = Field(default=None, max_length=40)
    reused_from_run_id: Optional[str] = Field(default=None, max_length=200)
    #: proven to belong to the package Story #17 authorized for this channel
    authorized_package_digest: Optional[str] = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    blocking_reasons: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("channel")
    @classmethod
    def _release1_channel(cls, value: str) -> str:
        if value not in ("wix", "linkedin"):
            raise ValueError(f"unsupported Release 1 channel: {value!r}")
        return value


class ProvenanceSummary(_ReportModel):
    """What Story #16 proved about this run — referenced, not re-derived."""

    verified: bool
    run_kind: Optional[str] = None
    stopped_after: Optional[str] = None


class RunReport(_ReportModel):
    """The authoritative account of one terminal run."""

    schema_version: str = RUN_REPORT_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=200)
    signal_id: str = Field(min_length=1, max_length=200)
    execution_mode: str = Field(min_length=1, max_length=40)
    configuration_identity: Optional[ConfigurationIdentity] = None
    reported_at: datetime
    terminal_stage: TerminalStage
    terminal_disposition: TerminalDisposition
    completed: bool
    provenance: ProvenanceSummary
    channels: tuple[ChannelReport, ...] = Field(default=(), max_length=2)
    override_state: Optional[str] = Field(default=None, max_length=40)
    unusable_prior_evidence: Optional[dict] = None
    errors: tuple[str, ...] = Field(default=(), max_length=20)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=10)

    @field_validator("schema_version")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != RUN_REPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported run report schema_version: {value!r}")
        return value

    @field_validator("unusable_prior_evidence")
    @classmethod
    def _sanitized_note(cls, value: Optional[dict]) -> Optional[dict]:
        """Only the typed note shape produced by the idempotency scans."""

        if value is None:
            return value
        if set(value) != {"count", "reasons"}:
            raise ValueError("unusable prior evidence note has an unexpected shape")
        if not isinstance(value["count"], int):
            raise ValueError("unusable prior evidence count must be an integer")
        reasons = value["reasons"]
        if not isinstance(reasons, list) or not all(
            isinstance(item, str) and len(item) <= 80 for item in reasons
        ):
            raise ValueError("unusable prior evidence reasons must be short codes")
        return value

    @model_validator(mode="after")
    def _truthful(self) -> "RunReport":
        channels = [item.channel for item in self.channels]
        if len(set(channels)) != len(channels):
            raise ValueError("channel outcomes must be unique")
        if self.completed and self.terminal_disposition is not TerminalDisposition.COMPLETED:
            raise ValueError(
                "a completed run must carry the completed disposition"
            )
        # A report about publication must actually reference publication
        # evidence; an earlier terminal stage must not invent channels.
        if self.terminal_stage is not TerminalStage.PUBLICATION and self.channels:
            raise ValueError(
                "channel outcomes exist only for a run that reached publication"
            )
        names = {item.name for item in self.artifacts}
        if len(names) != len(self.artifacts):
            raise ValueError("artifact references must be unique")
        return self

    def channel(self, name: str) -> Optional[ChannelReport]:
        for item in self.channels:
            if item.channel == name:
                return item
        return None


def _artifact_references(run_dir: Path) -> tuple[ArtifactReference, ...]:
    """Reference whichever canonical artifacts the run actually produced.

    Absent artifacts are simply absent — a run that stopped early is not
    made to look as though it produced evidence it never did.
    """

    return tuple(
        ArtifactReference(name=name)
        for name in CANONICAL_ARTIFACTS
        if (run_dir / name).is_file()
    )


#: Which channel statuses assert that an authorized publication package
#: existed for that channel, and therefore require the full verdict + package
#: binding before the report may describe them.
#:
#: The truthful matrix, derived from how the entrypoint actually records
#: outcomes: a channel only enters the publish path after Story #17 returns
#: ``ALLOW``, so every status produced there — a fresh publication, an
#: idempotent reuse that suppressed the provider call, a provider duplicate
#: after a real attempt, or a failure during the attempt — implies an
#: authorized package. ``BLOCKED`` is the opposite case: the channel never
#: reached the publisher, so demanding a package binding for it would be
#: demanding proof of something that legitimately never happened.
BINDING_REQUIRED_STATUSES = frozenset(
    {"PUBLISHED", "REUSED", "PROVIDER_DUPLICATE", "FAILED", "DRAFT_CREATED"}
)
NO_BINDING_STATUSES = frozenset({"BLOCKED", "SKIPPED"})

#: The entrypoint's own completion rule, mirrored rather than imported so the
#: report does not depend on the script it accounts for: a run is complete
#: only when every channel ended in one of these. A stored ``completed: true``
#: beside a channel outside this set is an artifact contradicting itself.
COMPLETED_STATUSES = frozenset(
    {"PUBLISHED", "DRAFT_CREATED", "published_url_unavailable", "REUSED"}
)

#: The entrypoint's own status for a channel the preflight refused. It has no
#: ``PublishStatus`` because no publisher was ever constructed for it.
BLOCKED_STATUS = "BLOCKED"


def _validated_channel_result(channel: str, entry: dict) -> dict:
    """Check the stored provider result against its own accepted semantics.

    A proven package authorization says the run was allowed to publish that
    package; it says nothing about whether the recorded result is truthful.
    Story #16 validates selected top-level publication relationships but not
    per-channel result semantics, so without this a tampered result — a
    publication with no identifier, a provenance contradicting its URL, a
    provider duplicate dressed up with success evidence — could still be
    summarized as an authoritative account.

    The rules are the ones Stories #18/#19 already established, read through
    the existing ``PublishStatus`` and ``UrlProvenance`` contracts. Nothing is
    normalized: a violation raises rather than being coerced into a valid
    neighbouring status.
    """

    from src.publishing.result import PublishStatus, UrlProvenance

    def reject(reason: str):
        raise RunReportError(f"{channel} publication result {reason}")

    raw_status = entry.get("status")
    if raw_status == BLOCKED_STATUS:
        # The entrypoint's own status for a channel the preflight refused: it
        # never reaches a publisher, so it has no PublishStatus of its own.
        status = None
    else:
        try:
            status = PublishStatus(raw_status)
        except ValueError:
            reject("carries an unrecognized status")

    external_id = entry.get("external_id")
    url = entry.get("url")
    reused_from = entry.get("reused_from_run_id")
    raw_provenance = entry.get("url_provenance")

    for field, value in (("external_id", external_id), ("url", url),
                         ("reused_from_run_id", reused_from)):
        if value is not None and not isinstance(value, str):
            reject(f"has a malformed {field}")

    def provenance_or_reject():
        try:
            return UrlProvenance(raw_provenance)
        except ValueError:
            reject("carries an invalid url_provenance")

    def require_neutral_provenance(subject: str):
        """Absent, or exactly the untouched neutral value the code writes.

        Only the two publish paths ever set a provenance; every other result
        keeps the neutral default. A foreign, malformed or success-like value
        on such a result is evidence of tampering, not of a publication.
        """
        if raw_provenance is None:
            return
        if provenance_or_reject() is not UrlProvenance.UNAVAILABLE:
            reject(f"claims a URL provenance {subject} cannot have")

    def check_url_consistency(provenance):
        if provenance is UrlProvenance.PROVIDER_CONFIRMED and not (url or ""):
            reject("claims a provider-confirmed URL while carrying none")
        if provenance is UrlProvenance.UNAVAILABLE and (url or ""):
            reject("claims no provenance-confirmed URL while carrying one")
        if provenance is UrlProvenance.LOCALLY_DERIVED:
            # Only Wix has an accepted locally-derived form (base + slug);
            # LinkedIn has no legitimate construction (Issue #108).
            if channel != "wix":
                reject("claims a locally-derived URL the channel cannot produce")
            if not (url or ""):
                reject("claims a locally-derived URL while carrying none")

    if status is None:
        # BLOCKED — the preflight refused the channel, so no publisher was
        # ever constructed and no provider evidence of any kind may appear.
        # The entrypoint writes no provenance at all for these.
        if (external_id or "").strip() or reused_from:
            reject("claims provider evidence for a channel that never published")
        if (url or "").strip():
            reject("claims a URL for a channel that never published")
        require_neutral_provenance("a channel that never reached the publisher")

    elif status is PublishStatus.PUBLISHED:
        if not (external_id or "").strip():
            reject("claims a publication without a provider identifier")
        if reused_from:
            reject("claims a fresh publication while pointing at a reuse source")
        check_url_consistency(provenance_or_reject())

    elif status is PublishStatus.REUSED:
        if not (external_id or "").strip():
            reject("reuses a publication without its provider identifier")
        if not (reused_from or "").strip():
            reject("claims a reuse without naming the run it reuses")
        check_url_consistency(provenance_or_reject())

    elif status is PublishStatus.PROVIDER_DUPLICATE:
        # A 409 proves a duplicate exists but never which post: it may carry
        # no success evidence at all (Issue #108).
        if (external_id or "").strip() or (url or "").strip() or reused_from:
            reject("carries success evidence a provider duplicate cannot prove")
        if raw_provenance is not None:
            if provenance_or_reject() is not UrlProvenance.UNAVAILABLE:
                reject("claims a URL provenance a provider duplicate cannot have")

    elif status is PublishStatus.DRAFT_CREATED:
        # The accepted Wix draft contract (`BasePublisher._draft`): a draft
        # legitimately carries its draft identifier and a dashboard link, and
        # deliberately never sets a URL provenance — a dashboard link is not a
        # published post URL, which is exactly why it stays `unavailable`.
        if not (external_id or "").strip():
            reject("claims a created draft without its draft identifier")
        if reused_from:
            reject("claims a reuse source for a draft")
        require_neutral_provenance("a draft")

    else:
        # FAILED / SKIPPED — the canonical shapes (`BasePublisher._fail` and
        # `._skip`) carry an error message and nothing else: no identifier, no
        # URL, and the untouched neutral provenance. Success-like URL evidence
        # here would describe provider output that never existed, even when the
        # URL and provenance happen to agree with each other.
        if (external_id or "").strip():
            reject("claims a provider identifier for a channel that did not publish")
        if reused_from:
            reject("claims a reuse source for a channel that did not publish")
        if (url or "").strip():
            reject("claims a provider URL for a channel that did not publish")
        require_neutral_provenance("a channel that did not publish")

    return {
        "status": status.value if status is not None else BLOCKED_STATUS,
        "external_id": external_id or None,
        "url": url or None,
        "url_provenance": raw_provenance or None,
        "reused_from_run_id": reused_from or None,
    }


def _channel_reports(
    packages_dir: Path,
    run_dir: Path,
    *,
    run_id: str,
    signal_id: str,
    publication: Optional[dict],
    preflight: Optional[dict],
    configuration_identity: dict,
) -> tuple[ChannelReport, ...]:
    """Independent per-channel outcomes, each proven against its authorization.

    Copying the verdict's digest beside the provider's output would prove
    nothing: Story #16 verifies the generation/publication chain but not the
    Story #17 artifact, so a swapped or relabelled verdict could otherwise
    make an authoritative-looking report. For every status that asserts an
    authorized publication existed, this therefore proves — with the same
    helpers the Wix and LinkedIn idempotency scans use, never a second
    implementation — that the verdict belongs to this run, signal and
    configuration, that its channel was allowed with a valid target, and that
    the exact canonical package reconstructs from persisted evidence to the
    digest the verdict recorded.

    The provider's own output is then preserved verbatim. No digest is ever
    reverse-derived from a provider-generated identifier — a pre-publication
    package cannot know one.
    """

    from src.publishing.idempotency import (
        authorized_package_digest_matches,
        validated_channel_verdict,
    )

    if not publication:
        return ()

    generation_run_id = publication.get("generation_run_id") or ""
    reports: list[ChannelReport] = []
    for channel in ("wix", "linkedin"):
        entry = (publication.get("results") or {}).get(channel)
        if not isinstance(entry, dict):
            continue
        validated = _validated_channel_result(channel, entry)
        status = validated["status"]

        digest: Optional[str] = None
        blocking: tuple[str, ...] = ()
        if status in BINDING_REQUIRED_STATUSES:
            verdict, reason = validated_channel_verdict(
                run_dir,
                channel_name=channel,
                signal_id=signal_id,
                configuration_identity=configuration_identity,
            )
            if reason is not None:
                raise RunReportError(
                    f"{channel} publication is not backed by an authorization "
                    "verdict that belongs to this run"
                )
            if not authorized_package_digest_matches(
                Path(packages_dir),
                run_dir,
                signal_id=signal_id,
                generation_run_id=generation_run_id,
                configuration_identity=configuration_identity,
                channel=verdict,
                channel_name=channel,
            ):
                raise RunReportError(
                    f"{channel} authorization verdict does not describe a "
                    "package reconstructable from this run's evidence"
                )
            digest = verdict.package_digest
            blocking = tuple(reason.value for reason in verdict.blocking_reasons)
        elif status in NO_BINDING_STATUSES:
            # The channel never reached the publisher; the (already validated)
            # verdict is read for its blocking reasons only, and no package
            # binding is claimed or fabricated.
            channel_verdict = (
                preflight.verdict_for(channel) if preflight is not None else None
            )
            if channel_verdict is not None:
                blocking = tuple(
                    reason.value for reason in channel_verdict.blocking_reasons
                )
        else:
            raise RunReportError(
                f"{channel} carries a status with no defined reporting rule"
            )

        reports.append(
            ChannelReport(
                channel=channel,
                status=status,
                external_id=validated["external_id"],
                url=validated["url"],
                url_provenance=validated["url_provenance"],
                reused_from_run_id=validated["reused_from_run_id"],
                authorized_package_digest=digest,
                blocking_reasons=blocking,
            )
        )
    return tuple(reports)


def _authoritative_configuration(run_dir: Path) -> ConfigurationIdentity:
    """The run's proven configuration anchor, from its intake assignment.

    ``assignment.json`` is the anchor Story #16 already verifies the whole
    chain against, so it — not whichever artifact happens to be present — is
    what the report treats as authoritative. A malformed anchor is a hard
    failure: silently reporting "configuration unavailable" would let broken
    evidence pass as an authoritative account.
    """

    from src.intake.assignment_record import AssignmentRecord

    raw = _load(run_dir, "assignment.json")
    if raw is None:
        raise RunReportError("the run has no intake assignment to anchor its identity")
    try:
        return AssignmentRecord.model_validate(raw).configuration_identity
    except RunReportError:
        raise
    except Exception:  # noqa: BLE001 — an unreadable anchor fails closed
        raise RunReportError(
            "the run's intake assignment does not carry a valid configuration identity"
        ) from None


def _validated_preflight(
    run_dir: Path,
    *,
    run_id: str,
    signal_id: str,
    authoritative: ConfigurationIdentity,
):
    """Prove the Story #17 artifact is this run's own before consuming it.

    Story #16 verifies the generation/publication chain but not the preflight
    artifact, so a foreign or tampered verdict could otherwise supply the
    override state and channel information of a run it does not belong to —
    including on a legitimate preflight-BLOCK run, where no publication
    evidence exists to trigger the per-channel binding checks.

    This asks only whether the artifact is honest. Whether a *channel*
    authorized a package that was actually published is a separate question,
    answered per channel and only for publication-stage statuses.
    """

    from src.publishing.preflight import PreflightResult

    path = run_dir / "preflight_result.json"
    if not path.is_file():
        return None
    try:
        verdict = PreflightResult.model_validate_json(path.read_bytes())
    except Exception:  # noqa: BLE001 — a verdict that will not strict-load is not evidence
        raise RunReportError(
            "preflight_result.json does not satisfy its own strict contract"
        ) from None
    if verdict.run_id != run_id or verdict.signal_id != signal_id:
        raise RunReportError(
            "preflight_result.json belongs to a different run or signal"
        )
    if verdict.configuration_identity != authoritative:
        raise RunReportError(
            "preflight_result.json carries a configuration other than the "
            "run's authoritative identity"
        )
    return verdict


def _load(run_dir: Path, name: str) -> Optional[dict]:
    path = run_dir / name
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise RunReportError(
            f"{name} could not be read as canonical evidence "
            f"({type(exc).__name__})"
        ) from None
    if not isinstance(data, dict):
        raise RunReportError(f"{name} is not a canonical JSON object")
    return data


def build_run_report(
    packages_dir: Path,
    *,
    run_id: str,
    signal_id: str,
    execution_mode: str,
    terminal_stage: TerminalStage,
    terminal_disposition: TerminalDisposition,
    errors: tuple[str, ...] = (),
    now: Optional[datetime] = None,
) -> RunReport:
    """Assemble the authoritative account of one terminal run.

    Raises :class:`RunReportError` when the run's evidence is internally
    inconsistent — an authoritative-looking report is never produced over
    corrupt evidence, and the corruption is never normalized into a business
    stop. A legitimately partial chain is reported normally.
    """

    from src.artifacts import resolve_run_dir
    from src.artifacts.provenance import ProvenanceError, verify_run_provenance

    run_dir = resolve_run_dir(Path(packages_dir), signal_id, run_id)
    if not run_dir.is_dir():
        raise RunReportError("the run namespace does not exist")

    # Story #16 decides consistency, including its stopped-run ladder
    # semantics: a partial chain is valid, a contradictory one is not.
    try:
        report = verify_run_provenance(Path(packages_dir), signal_id, run_id)
    except (ProvenanceError, FileNotFoundError, ValueError, OSError) as exc:
        raise RunReportError(
            f"run evidence is not internally consistent ({type(exc).__name__})"
        ) from None
    provenance = ProvenanceSummary(
        verified=True, run_kind=report.run_kind, stopped_after=report.stopped_after
    )

    assignment = _load(run_dir, "assignment.json")
    publication = _load(run_dir, "publication_results.json")
    preflight = _load(run_dir, "preflight_result.json")

    # The report may only summarize evidence that is actually about this run.
    # This is an input check on the report's own sources, not a second
    # provenance engine: Story #16 proves the chain, and it does not currently
    # compare the signal recorded inside publication_results / preflight
    # against the run namespace, so a record claiming another signal would
    # otherwise be summarized as if it belonged here.
    for name, evidence in (("publication_results.json", publication),
                           ("preflight_result.json", preflight)):
        if evidence is None:
            continue
        for field in ("run_id", "signal_id"):
            recorded = evidence.get(field)
            expected = run_id if field == "run_id" else signal_id
            if recorded is not None and recorded != expected:
                raise RunReportError(
                    f"{name} claims a different {field} than the run it is "
                    "stored under"
                )

    # The anchor is the run's own assignment; a malformed one fails closed
    # rather than degrading into "configuration unavailable".
    configuration = _authoritative_configuration(run_dir)

    # Whenever the Story #17 artifact exists it must be proven to be this
    # run's own — before any of its content is consumed, and regardless of
    # whether the run ever reached publication.
    verdict = _validated_preflight(
        run_dir, run_id=run_id, signal_id=signal_id, authoritative=configuration
    )

    if publication and not preflight:
        # A publication cannot be authoritative without the authorization that
        # permitted it.
        raise RunReportError(
            "publication evidence exists without its authorization verdict"
        )
    channels = _channel_reports(
        Path(packages_dir),
        run_dir,
        run_id=run_id,
        signal_id=signal_id,
        publication=publication,
        preflight=verdict,
        configuration_identity=configuration.model_dump(),
    )
    completed = bool(publication.get("completed")) if publication else (
        terminal_disposition is TerminalDisposition.COMPLETED
    )
    if completed:
        # "Partial completion cannot be reported as full success" has to hold
        # against the stored flag too: the entrypoint derives completion from
        # the channel statuses, so a run claiming completion while a channel
        # failed or was blocked is contradicting itself, and the report is the
        # last place that contradiction should be laundered into an
        # authoritative account.
        incomplete = [
            channel.channel for channel in channels
            if channel.status not in COMPLETED_STATUSES
        ]
        if incomplete:
            raise RunReportError(
                "publication evidence claims completion while "
                f"{', '.join(sorted(incomplete))} did not complete"
            )
    if completed and terminal_disposition is not TerminalDisposition.COMPLETED:
        # canonical evidence outranks the caller's view of the outcome
        terminal_disposition = TerminalDisposition.COMPLETED
    if not completed and terminal_disposition is TerminalDisposition.COMPLETED:
        completed = False

    try:
        return RunReport(
            run_id=run_id,
            signal_id=signal_id,
            execution_mode=execution_mode,
            configuration_identity=configuration,
            reported_at=now or datetime.now(timezone.utc),
            terminal_stage=terminal_stage,
            terminal_disposition=terminal_disposition,
            completed=completed,
            provenance=provenance,
            channels=channels,
            override_state=(
                verdict.override_state.value if verdict is not None else None
            ),
            unusable_prior_evidence=(
                (publication or {}).get("unusable_prior_publication_evidence")
            ),
            errors=tuple(str(item)[:300] for item in errors)[:20],
            artifacts=_artifact_references(run_dir),
        )
    except RunReportError:
        raise
    except Exception as exc:  # noqa: BLE001 — a rejected model fails closed
        raise RunReportError(f"run report is invalid: {type(exc).__name__}") from None
