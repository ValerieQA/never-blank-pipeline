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


def _channel_reports(
    publication: Optional[dict], preflight: Optional[dict]
) -> tuple[ChannelReport, ...]:
    """Independent per-channel outcomes bound to the authorized package.

    The recorded result is proven to belong to the package Story #17
    authorized for that channel: the digest carried here is the verdict's
    own ``package_digest``, never a digest reverse-derived from a
    provider-generated identifier — a pre-publication package cannot know
    one, and pretending otherwise would be a fabricated guarantee.
    """

    if not publication:
        return ()
    verdicts = {
        item.get("channel"): item
        for item in (preflight or {}).get("channels", [])
        if isinstance(item, dict)
    }
    reports: list[ChannelReport] = []
    for channel in ("wix", "linkedin"):
        entry = (publication.get("results") or {}).get(channel)
        if not isinstance(entry, dict):
            continue
        verdict = verdicts.get(channel) or {}
        reports.append(
            ChannelReport(
                channel=channel,
                status=str(entry.get("status") or "UNKNOWN"),
                external_id=entry.get("external_id") or None,
                url=entry.get("url") or None,
                url_provenance=entry.get("url_provenance") or None,
                reused_from_run_id=entry.get("reused_from_run_id") or None,
                authorized_package_digest=verdict.get("package_digest"),
                blocking_reasons=tuple(verdict.get("blocking_reasons") or ()),
            )
        )
    return tuple(reports)


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

    configuration = None
    source = publication or preflight or assignment or {}
    raw_configuration = source.get("configuration_identity")
    if isinstance(raw_configuration, dict):
        try:
            configuration = ConfigurationIdentity.model_validate(raw_configuration)
        except Exception:  # noqa: BLE001 — an unreadable identity is simply absent
            configuration = None

    channels = _channel_reports(publication, preflight)
    completed = bool(publication.get("completed")) if publication else (
        terminal_disposition is TerminalDisposition.COMPLETED
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
            override_state=(preflight or {}).get("override_state"),
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
